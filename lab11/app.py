"""Bounded streaming API; one process per Pod, explicit loaded artifact identity."""
import asyncio
import hashlib
import json
import os
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, ConfigDict, Field
from backends import StubBackend

MODE = "simulated"
POD = os.getenv("POD_NAME", "local")
VERSION = os.getenv("MODEL_VERSION", "A")
WARMUP = float(os.getenv("WARMUP_SECONDS", "20"))
PROBE = os.getenv("PROBE_MODE", "fixed")
FAIL_WARMUP = os.getenv("FAIL_WARMUP", "false") == "true"
CAPACITY = int(os.getenv("CAPACITY", "2"))
QUEUE_LIMIT = int(os.getenv("QUEUE_LIMIT", "4"))
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "4"))
HIT = float(os.getenv("HIT_SECONDS", ".06"))
MISS = float(os.getenv("MISS_SECONDS", ".36"))
CHUNK_DELAY = float(os.getenv("CHUNK_SECONDS", ".13"))
DRAIN = Path("/tmp/mlops11-drain")
ARTIFACT = Path(os.getenv("MODEL_PATH", "/model/model.json"))
REG = CollectorRegistry()
REQ = Counter("ml_requests", "Terminal outcomes seen by API", ["outcome"], registry=REG)
EARLY = Counter("ml_unwarmed", "Requests arriving before warmup", registry=REG)
RUN = Gauge("ml_running", "Active computations and streams", registry=REG)
WAIT = Gauge("ml_waiting", "Requests queued before execution", registry=REG)
READY = Gauge("ml_ready", "Backend ready and not draining", registry=REG)
CACHE = Counter("ml_cache", "Simulated Pod-local prefix cache lookups", ["result"], registry=REG)
BUCKETS = (.01,.025,.05,.1,.2,.35,.5,.75,1,1.5,2,3,5,8,12,20,35,60)
TTFC = Histogram("ml_ttfc_seconds", "Successful first content chunk", buckets=BUCKETS, registry=REG)
FULL = Histogram("ml_full_seconds", "Successful full response duration", buckets=BUCKETS, registry=REG)
QUEUE = Histogram("ml_queue_seconds", "Queue time of completed requests", buckets=BUCKETS, registry=REG)

def read_model():
    data = ARTIFACT.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    obj = json.loads(data)
    if actual != os.environ["MODEL_SHA256"] or obj["version"] != VERSION:
        raise ValueError("Model artifact hash/version mismatch")
    return obj, actual

def cpu_work(seconds):
    deadline = time.thread_time() + seconds
    data = b"mlops11 bounded CPU workload"
    while time.thread_time() < deadline:
        for _ in range(256):
            data = hashlib.sha256(data).digest()

class SimBackend(StubBackend):
    def __init__(self, obj, digest):
        super().__init__({"model_id": obj["version"], "runtime_sha256": digest})
        self.cache = OrderedDict()
        self.prefix = obj["prefix"]

    async def prefill(self, prefix, cpu_ms):
        hit = prefix in self.cache
        CACHE.labels("hit" if hit else "miss").inc()
        self.cache[prefix] = True
        self.cache.move_to_end(prefix)
        if len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)
        await asyncio.sleep(HIT if hit else MISS)
        if cpu_ms:
            await asyncio.to_thread(cpu_work, cpu_ms / 1000)
        return hit

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str = Field(min_length=1,max_length=512)
    history: list[str] = Field(default_factory=list,max_length=8)
    session_id: str = Field(default="demo",min_length=1,max_length=64)
    prefix: str = Field(default="shared",max_length=64)
    chunks: int = Field(default=3,ge=1,le=30)
    chunk_seconds: float | None = Field(default=None,ge=.02,le=.9)
    cpu_ms: int = Field(default=0,ge=0,le=400)

class State:
    backend = None
    warmed = False
    error = None
    active = 0
    queued = 0

state = State()
slots = asyncio.Semaphore(CAPACITY)

def ready():
    return state.warmed and not DRAIN.exists()

def identity():
    b = state.backend
    return dict(pod=POD,version=b.loaded_id if b else None,artifact_sha256=b.runtime_sha256 if b else None,
                backend_mode=MODE,warmed=state.warmed)

def log(event, **fields):
    print(json.dumps(dict(event=event,time=time.time(),**identity(),**fields),ensure_ascii=True),flush=True)

@asynccontextmanager
async def lifespan(app):
    async def load():
        try:
            obj, digest = read_model()
            state.backend = SimBackend(obj,digest)
            log("artifact_loaded")
            await asyncio.sleep(WARMUP)
            if FAIL_WARMUP:
                raise ValueError("Injected warmup failure")
            state.warmed = True
            log("warmup_complete")
        except Exception as exc:
            state.error = str(exc)
            log("warmup_failed",error=state.error)
    task = asyncio.create_task(load())
    yield
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)

app = FastAPI(title="HW11 / simulated streaming",lifespan=lifespan)

@app.get("/health")
async def health():
    return {"alive":True,**identity()}

@app.get("/startup")
@app.get("/ready")
async def readiness():
    good = ready() or (PROBE == "broken" and not DRAIN.exists())
    return JSONResponse({"ready":good,"error":state.error,**identity()},status_code=200 if good else 503)

@app.get("/metrics")
async def metrics():
    READY.set(ready())
    return Response(generate_latest(REG),headers={"Content-Type":CONTENT_TYPE_LATEST})

@app.post("/generate")
async def generate(payload: Input, request: Request):
    started = time.monotonic()
    request_id = str(uuid.uuid4())
    peer = request.client.host if request.client else None
    info = identity()
    headers = {"X-Request-ID":request_id,"X-Pod":POD,"X-Version":str(info["version"]),
               "X-Artifact-SHA256":str(info["artifact_sha256"]),"X-Backend-Mode":MODE,
               "X-Warmed":str(info["warmed"]).lower(),"X-Peer-IP":peer or "",
               "Cache-Control":"no-store","Connection":"close"}
    details = dict(request_id=request_id,session_id=payload.session_id,peer_ip=peer,arrival_warmed=info["warmed"])
    log("arrived",**details)
    if not info["warmed"]:
        EARLY.inc()
    def reject(status,reason):
        REQ.labels("rejected").inc()
        log("rejected",status=status,reason=reason,**details)
        return JSONResponse(dict(error=reason,**info,**details),status_code=status,headers=headers)
    if not payload.prompt.strip() or any(len(x)>512 for x in payload.history):
        return reject(422,"invalid prompt/history")
    if DRAIN.exists() or state.backend is None or (PROBE != "broken" and not state.warmed):
        return reject(503,"not ready")
    if state.active+state.queued >= CAPACITY+QUEUE_LIMIT:
        return reject(429,"queue full")
    state.queued += 1
    WAIT.set(state.queued)
    deadline = min(12, max(2, QUEUE_LIMIT*2))
    try:
        await asyncio.wait_for(slots.acquire(), timeout=deadline)
    except TimeoutError:
        return reject(429,"queue deadline")
    except asyncio.CancelledError:
        REQ.labels("aborted").inc()
        log("aborted",stage="queue",**details)
        raise
    finally:
        state.queued -= 1
        WAIT.set(state.queued)
    state.active += 1
    RUN.set(state.active)
    q = time.monotonic()-started
    headers["X-Queue-Seconds"] = f"{q:.6f}"
    backend = state.backend
    delay = payload.chunk_seconds if payload.chunk_seconds is not None else CHUNK_DELAY
    async def stream():
        first = None
        outcome = "aborted"
        try:
            hit = await backend.prefill(payload.prefix,payload.cpu_ms)
            for i in range(payload.chunks):
                await asyncio.sleep(delay)
                if first is None:
                    first = time.monotonic()-started
                msg = dict(kind="chunk",index=i+1,request_id=request_id,cache_hit=hit,
                           text=(backend.prefix+"|"+"|".join(payload.history+[payload.prompt]) if i==0 else f"part-{i+1}"),
                           **info)
                yield json.dumps(msg,ensure_ascii=True).encode()+b"\n"
            yield json.dumps(dict(kind="done",chunks=payload.chunks,request_id=request_id)).encode()+b"\n"
            outcome = "completed"
        finally:
            total = time.monotonic()-started
            state.active -= 1
            RUN.set(state.active)
            slots.release()
            REQ.labels(outcome).inc()
            if outcome=="completed":
                TTFC.observe(first); FULL.observe(total); QUEUE.observe(q)
            log(outcome,queue_seconds=q,ttfc_seconds=first,full_seconds=total,**details)
    return StreamingResponse(stream(),media_type="application/x-ndjson",headers=headers)
