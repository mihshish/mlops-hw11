"""FastAPI with background startup, immutable loaded identity and bounded compute."""
import asyncio
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from process_core import read
from release import verify_artifact
from backends import StubBackend, TransformersBackend


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    prompt: str = Field(min_length=1,max_length=6000)
    max_new_tokens: int = 32

    @field_validator('prompt')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Prompt cannot be blank')
        return value

    @field_validator('max_new_tokens')
    @classmethod
    def evaluated_limit(cls,value):
        if value != 32: raise ValueError('Only evaluated max_new_tokens=32 is supported')
        return value


class ServiceState:
    def __init__(self,root,warmup_seconds,backend_kind='stub',factory=None):
        self.root=Path(root); self.ready=False; self.error=None; self.backend=None; self.manifest=None
        self.warmup_finished=threading.Event(); self.compute_lock=threading.Lock()
        self.slots=threading.BoundedSemaphore(3)
        self.warmup_seconds=warmup_seconds; self.kind=backend_kind
        self.factory=factory or (StubBackend if backend_kind=='stub' else TransformersBackend)

    def load(self):
        try:
            manifest=read(self.root/'accepted.json')
            verify_artifact(manifest)
            if self.kind=='real' and manifest.get('synthetic'):
                raise ValueError('Synthetic manifest cannot serve a real release')
            if self.kind=='stub' and not manifest.get('synthetic'):
                raise ValueError('Real manifest cannot be advertised by STUB ONLY')
            if self.kind=='real':
                from provenance import verify_decision
                verify_decision(self.root,manifest,read(self.root/f"report-{manifest['evaluation_role']}.json"))
            backend=self.factory(manifest)
            backend.warmup()
            time.sleep(self.warmup_seconds)
            self.manifest=manifest; self.backend=backend
            self.warmup_finished.set(); self.ready=True
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}'
            print('LOAD_FAILED',self.error,flush=True)

    def generate(self,payload):
        started=time.perf_counter()
        if not self.ready: raise HTTPException(503,'Model not ready')
        if not self.slots.acquire(blocking=False): raise HTTPException(429,'Queue full')
        try:
            with self.compute_lock:
                compute_start=time.perf_counter()
                try:
                    result=self.backend.generate(payload.prompt,payload.max_new_tokens)
                except ValueError as exc:
                    raise HTTPException(422,str(exc)) from exc
                ended=time.perf_counter()
                result.update(model_id=self.backend.loaded_id,runtime_sha256=self.backend.runtime_sha256,
                    request_id=str(uuid.uuid4()),generation_seconds=ended-compute_start,
                    queue_seconds=compute_start-started,total_seconds=ended-started)
                return result
        finally:
            self.slots.release()


def create_app(root,warmup_seconds=0,backend_kind='stub',factory=None,debug=True):
    state=ServiceState(root,warmup_seconds,backend_kind,factory)
    @asynccontextmanager
    async def lifespan(app):
        loading=asyncio.create_task(asyncio.to_thread(state.load))
        yield
        await loading
    app=FastAPI(title='MLOps HW8-9-10 model API',lifespan=lifespan)
    app.state.model=state

    @app.get('/health')
    def health(): return dict(alive=True,backend='STUB ONLY' if backend_kind=='stub' else 'Transformers')

    @app.get('/ready')
    def ready():
        if not state.ready: raise HTTPException(503,'Model loading, failed verification, or warming up')
        return dict(ready=True,model_id=state.backend.loaded_id,runtime_sha256=state.backend.runtime_sha256)

    if debug:
        @app.get('/debug')
        def diagnostics():
            return dict(loaded_id=state.backend.loaded_id if state.backend else None,
                        calls=state.backend.calls if state.backend else 0,
                        warmup_finished=state.warmup_finished.is_set(),load_error=state.error)

    @app.post('/generate')
    def generate(payload:GenerateRequest): return state.generate(payload)
    return app
