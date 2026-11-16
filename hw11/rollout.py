"""Observe actual EndpointSlices, arrivals before warmup, rollout, rollback and a SIGKILL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import argparse
import json
import threading
import time
from hw11.cluster import RESULT,data,dump,k,kj,load,release,rollout,run,sample,single

class Trace:
    def __init__(self):
        self.rows=[];self.events=[];self.requests=[];self.phase="init"
    def mark(self,phase,**kw):
        self.phase=phase
        r=dict(time=time.time(),phase=phase,**kw)
        self.events.append(r);print("EVENT",r,flush=True)
    @contextmanager
    def capture(self):
        stop=threading.Event()
        def recorder():
            while not stop.is_set():
                try:self.rows.append(dict(phase=self.phase,**sample()))
                except Exception as e:self.rows.append(dict(time=time.time(),phase=self.phase,sample_error=str(e)))
                stop.wait(1.5)
        t=threading.Thread(target=recorder,daemon=True);t.start()
        try:yield
        finally:stop.set();t.join(timeout=30)
    def track_load(self,pool,tag,seconds):
        f=pool.submit(load,tag,"balanced","uniform",seconds,.75)
        return f
    def keep(self,f):
        rows,_=f.result();self.requests.extend(rows);return rows
    def save(self):
        data("a-timeline.jsonl",self.rows);data("a-requests.jsonl",self.requests);dump("a-events.json",self.events)

def wait_arrival(session, pod=None):
    target=[pod] if pod else ["-l","app=hw11-api"]
    until=time.monotonic()+16
    while time.monotonic()<until:
        for line in k("logs",*target,"--since=20s","--tail=90",timeout=8).splitlines():
            try: r=json.loads(line)
            except ValueError: continue
            if r.get("event")=="arrived" and r.get("session_id")==session:
                return r
        time.sleep(.35)
    raise TimeoutError(f"No arrival for {session}")

def warmup_experiments(t,pool,reuse):
    if reuse:
        def existing(name):
            return [json.loads(l) for l in (RESULT/name).read_text(encoding="utf-8").splitlines()]
        events=json.loads((RESULT/"a-events.json").read_text(encoding="utf-8"))
        t.events=[e for e in events if e["phase"] in ("broken-warmup","fixed-warmup")]
        t.rows.extend(r for r in existing("a-timeline.jsonl") if r.get("phase") in ("broken-warmup","fixed-warmup"))
        before=existing("a-broken.jsonl");fixed=existing("a-fixed.jsonl")
        t.requests.extend(before+fixed)
        t.mark("restore-A-after-diagnostic")
        release(modelVersion="A",probeMode="fixed",failWarmup=False);rollout()
    else:
        t.mark("broken-warmup")
        b=t.track_load(pool,"a-broken",46)
        time.sleep(12)
        release(probeMode="broken",modelVersion="A");rollout()
        before=t.keep(b)
        for p in {r["pod"] for r in before if r.get("warmed")=="false" and r["outcome"]=="completed"}:
            dump(f"a-broken-log-{p}.json",k("logs",p).splitlines())
        t.mark("fixed-warmup")
        f=t.track_load(pool,"a-fixed",46)
        time.sleep(12)
        release(probeMode="fixed",modelVersion="A");rollout()
        fixed=t.keep(f)
    early=[r for r in before if r.get("warmed")=="false" and r["outcome"]=="completed"]
    assert early,"Defect not reproduced"
    assert any(r["outcome"]=="completed" for r in fixed) and all(r.get("warmed")!="false" for r in fixed)
    return before,fixed,early

def main():
    p=argparse.ArgumentParser();p.add_argument("--reuse-warmup",action="store_true")
    args=p.parse_args()
    t=Trace()
    try:
        with ThreadPoolExecutor(5) as pool,t.capture():
            before,fixed,unwarmed=warmup_experiments(t,pool,args.reuse_warmup)
            t.mark("steady-A")
            assert single("a-check-A")["version"]=="A"
            rev_a=kj("get","deployment","api")["metadata"]["annotations"]["deployment.kubernetes.io/revision"]
            f=t.track_load(pool,"a-normal",78)
            time.sleep(13)
            long=pool.submit(single,"a-long","balanced",0,
                             ("--chunks",30,"--chunk-seconds",.9,"--session","rollout-long"))
            r=wait_arrival("rollout-long")
            t.mark("long-request-arrived",request_id=r["request_id"],server_time=r["time"],pod=r["pod"])
            time.sleep(1.8)
            t.mark("rolling-B")
            rollout_start=t.events[-1]["time"]
            release(probeMode="fixed",modelVersion="B");rollout()
            results=t.keep(f)
            long_result=long.result();t.requests.append(long_result)
            assert long_result["sent_wall"]<rollout_start<long_result["sent_wall"]+long_result["total_seconds"],long_result
            assert all(r["outcome"]=="completed" and r["status"]==200 for r in results+[long_result]),dict(
                bad=[r for r in results+[long_result] if r["outcome"]!="completed"])
            assert single("a-check-B")["version"]=="B"
            t.mark("back-to-A")
            release(modelVersion="A");rollout()
            rev_a=kj("get","deployment","api")["metadata"]["annotations"]["deployment.kubernetes.io/revision"]
            bad=t.track_load(pool,"a-bad",55)
            time.sleep(12)
            t.mark("bad-B")
            release(modelVersion="B",failWarmup=True)
            time.sleep(28)
            s=sample()
            assert any(p["version"]=="B" and not p["ready"] for p in s["pods"]),s
            assert not {p["name"] for p in s["pods"] if p["version"]=="B"} & {e["pod"] for e in s["endpoints"] if e.get("ready")}
            for p in s["pods"]:
                if p["version"]=="B":dump("a-bad-pod-log.json",k("logs",p["name"]).splitlines())
            t.mark("rollback-A",target_revision=rev_a)
            # Use Helm values to keep the declared state in sync with actual rollback.
            release(modelVersion="A",failWarmup=False);rollout()
            badrows=t.keep(bad)
            assert all(r.get("version")=="A" for r in badrows if r["outcome"]=="completed")
            rolled=[single(f"a-rollback-{i}",pod=i) for i in range(4)]
            t.requests.extend(rolled)
            assert all(r["outcome"]=="completed" and r["version"]=="A" for r in rolled)
            t.mark("forced-stop-start")
            pod=next(p for p in kj("get","pods","-l","app=hw11-api")["items"] if not p["metadata"].get("deletionTimestamp"))
            name=pod["metadata"]["name"]
            ip=pod["status"]["podIP"]
            cid=pod["status"]["containerStatuses"][0]["containerID"].split("://")[-1]
            doomed=pool.submit(single,"a-forced",ip,0,("--chunks",30,"--chunk-seconds",.9,"--session","forced-long"))
            r=wait_arrival("forced-long",name)
            t.mark("forced-request-arrived",request_id=r["request_id"],server_time=r["time"],pod=name)
            time.sleep(3.2)
            t.mark("forced-stop",pod=name)
            run("docker","exec","mlops11-control-plane","crictl","stop","--timeout","0",cid)
            result=doomed.result();t.requests.append(result)
            assert result["outcome"]=="aborted" and 0<result["chunks"]<30,result
            recovery=[]
            for i in range(28):
                r=single(f"a-recover-{i}",ip)
                recovery.append(r)
                if r["outcome"]=="completed" and r["version"]=="A":
                    break
                time.sleep(1)
            t.requests.extend(recovery)
            assert recovery[-1]["outcome"]=="completed",recovery[-1]
            t.mark("forced-stop-recovered",pod=name)
            rollout()
            dump("a-summary.json",dict(broken_early=len(unwarmed),fixed_early=sum(r.get("warmed")=="false" for r in fixed),
                broken_planned=len(before),fixed_planned=len(fixed),rollout_completed=len(results)+1,rollout_5xx=0,
                rollout_incomplete=0,long_stream=long_result,rollback_versions=[r["version"] for r in rolled],
                failed_B_ready=False,bad_B_service_versions=sorted({r["version"] for r in badrows if r["outcome"]=="completed"}),
                forced_outcome=result["outcome"],forced_chunks=result["chunks"],recovery_attempts=len(recovery),
                recovery_seconds=recovery[-1]["sent_wall"]-t.events[-2]["time"]))
    finally:t.save()

if __name__=="__main__":main()
