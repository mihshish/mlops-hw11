"""Open-loop traffic from four real client Pods, one TCP connection per attempt."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import http.client
import hashlib
import json
import socket
import threading
import time

def attempt(host, port, ident, payload, planned, client, tag, deadline=14):
    sent = time.monotonic()
    row = dict(id=ident,client=client,run=tag,planned_monotonic=planned,sent_monotonic=sent,
               sent_wall=time.time(),send_lag_seconds=max(0,sent-planned),session_id=payload["session_id"],
               first_monotonic=None,end_monotonic=None,status=None,pod=None,version=None,artifact_sha256=None,
               backend_mode=None,peer_ip=None,warmed=None,request_id=None,queue_seconds=None,cache_hit=None,
               chunks=0,expected_chunks=payload["chunks"],inter_chunk_seconds=[],outcome=None,error=None)
    conn=http.client.HTTPConnection(host,port,timeout=deadline)
    try:
        conn.request("POST","/generate",json.dumps(payload).encode(),{"Content-Type":"application/json","Connection":"close"})
        response=conn.getresponse()
        row.update(status=response.status,pod=response.getheader("X-Pod"),version=response.getheader("X-Version"),
                   artifact_sha256=response.getheader("X-Artifact-SHA256"),backend_mode=response.getheader("X-Backend-Mode"),
                   peer_ip=response.getheader("X-Peer-IP"),warmed=response.getheader("X-Warmed"),
                   request_id=response.getheader("X-Request-ID"))
        q=response.getheader("X-Queue-Seconds")
        row["queue_seconds"]=float(q) if q else None
        if response.status!=200:
            row.update(outcome="rejected" if 400<=response.status<500 else "http_error",
                       error=response.read(8192).decode("utf-8","replace"))
        else:
            last=None; done=False
            while line:=response.readline(65536):
                now=time.monotonic()
                if now-sent>deadline: raise TimeoutError("end-to-end deadline")
                obj=json.loads(line)
                if obj["request_id"]!=row["request_id"]: raise ValueError("stream identity changed")
                if obj["kind"]=="done":
                    done = obj["chunks"]==row["chunks"]==payload["chunks"]
                    break
                if obj["index"]!=row["chunks"]+1: raise ValueError("chunk order invalid")
                row["chunks"]+=1
                if last is None:
                    row.update(first_monotonic=now,first_text=obj["text"],cache_hit=obj["cache_hit"])
                else: row["inter_chunk_seconds"].append(now-last)
                last=now
            row["outcome"]="completed" if done else "aborted"
            if not done: row["error"]="missing terminal done marker or incomplete count"
    except (socket.timeout,TimeoutError) as exc:
        row.update(outcome="timeout",error=repr(exc))
    except (OSError,http.client.HTTPException,ValueError,KeyError) as exc:
        row.update(outcome="aborted" if row["status"]==200 else "transport_error",error=repr(exc))
    finally:
        conn.close()
    row["end_monotonic"]=time.monotonic()
    row["total_seconds"]=row["end_monotonic"]-sent
    row["ttfc_seconds"]=row["first_monotonic"]-sent if row["first_monotonic"] else None
    return row

def assignment(index, pattern):
    if pattern=="uniform": return index%4
    return 0 if index%15<12 else index%15-11

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--host",default="balanced")
    p.add_argument("--port",type=int,default=8080)
    p.add_argument("--run",required=True)
    p.add_argument("--client",type=int,default=0)
    p.add_argument("--start",type=float,default=0)
    p.add_argument("--duration",type=float,default=120)
    p.add_argument("--interval",type=float,default=.15)
    p.add_argument("--pattern",choices=["uniform","skew"],default="uniform")
    p.add_argument("--cpu-ms",type=int,default=0)
    p.add_argument("--chunks",type=int,default=3)
    p.add_argument("--chunk-seconds",type=float)
    p.add_argument("--history",default="[]")
    p.add_argument("--prompt",default="follow-up request")
    p.add_argument("--session",default="demo")
    p.add_argument("--single",action="store_true")
    a=p.parse_args()
    start=a.start or time.time()
    start_m=time.monotonic()+(start-time.time())
    out=threading.Lock()
    def emit(row):
        with out: print(json.dumps(row,ensure_ascii=True),flush=True)
    def send(i,planned):
        namespace=hashlib.sha256(a.run.encode()).hexdigest()[:12]
        payload=dict(prompt=a.prompt,history=json.loads(a.history),session_id=a.session,prefix=f"{namespace}-{i%3}",
                     chunks=a.chunks,cpu_ms=a.cpu_ms)
        if a.chunk_seconds is not None: payload["chunk_seconds"]=a.chunk_seconds
        row=attempt(a.host,a.port,f"{a.run}/{i}",payload,planned,a.client,a.run,deadline=40 if a.single else 14)
        row["planned_wall"]=start+i*a.interval
        emit(row)
    if a.single:
        time.sleep(max(0,start_m-time.monotonic())); send(0,start_m); return
    futures=[]
    with ThreadPoolExecutor(max_workers=24) as pool:
        for i in range(round(a.duration/a.interval)):
            if assignment(i,a.pattern)!=a.client: continue
            planned=start_m+i*a.interval
            time.sleep(max(0,planned-time.monotonic()))
            futures=[f for f in futures if not f.done()]
            if len(futures)>=24:
                emit(dict(id=f"{a.run}/{i}",client=a.client,run=a.run,session_id=a.session,
                          planned_monotonic=planned,planned_wall=start+i*a.interval,sent_monotonic=None,outcome="not_sent",
                          error="bounded client worker capacity"))
            else:
                futures.append(pool.submit(send,i,planned))
        time.sleep(max(0,start_m+a.duration-time.monotonic()))
        for f in futures: f.result()

if __name__=="__main__": main()
