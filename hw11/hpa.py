"""Real metrics API, sampled CPU HPA and overload alerts."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
from hw11.cluster import data,dump,k,kj,load,release,rollout,sample

def fetch(path, service="http://prometheus:9090"):
    script="import sys,urllib.request; print(urllib.request.urlopen(sys.argv[1]+sys.argv[2],timeout=5).read().decode())"
    return json.loads(k("exec","load-0","--","python","-c",script,service,path,timeout=20))

def alerts():return [{k:a[k] for k in ("state","name") if k in a} | {"name":a["labels"]["alertname"]} for a in fetch("/api/v1/alerts")["data"]["alerts"]]

def main():
    rows=[]; traffic=[]
    try:
        release(hpa__enabled=True)
        rollout()
        dump("metrics-api-before.json",json.loads(k("get","--raw","/apis/metrics.k8s.io/v1beta1/namespaces/hw11/pods")))
        dump("hpa-config.json",kj("get","hpa","api"))
        with ThreadPoolExecutor(2) as pool:
            balanced=pool.submit(load,"c-balanced","balanced","uniform",115,.085,260)
            phase="balanced_cpu"; future=balanced; t0=time.time()
            while time.time()-t0<460:
                s=sample()
                try: s["alerts"]=alerts()
                except Exception as e:s["alerts_error"]=str(e)
                s["phase"]=phase
                rows.append(s)
                print(phase,len(s["pods"]),sum(p["ready"] for p in s["pods"]),
                      (s.get("hpa") or {}).get("currentMetrics"),s.get("alerts"),flush=True)
                if future is not None and future.done():
                    result,_=future.result();traffic.extend(result);future=None
                    phase += "_cooldown"
                if (future is None and phase=="balanced_cpu_cooldown" and len(s["pods"])==2
                    and s.get("alerts")==[] and any(len(r["pods"])==3 for r in rows)):
                    future=pool.submit(load,"c-sticky","sticky","skew",95,.12,330)
                    phase="sticky_cpu"
                if future is None and phase=="sticky_cpu_cooldown" and len(s["pods"])==2 and s.get("alerts")==[]:
                    break
                time.sleep(3)
        dump("hpa-after.json",kj("get","hpa","api"))
        dump("hpa-alert-rules.json",fetch("/api/v1/rules"))
        seen=[len(s["pods"]) for s in rows if s["phase"].startswith("balanced_cpu")]
        assert seen[0]==2 and 3 in seen and seen[-1]==2,seen
        assert any(sum(p["ready"] for p in s["pods"])==3 for s in rows), "No three Ready replicas"
        assert len({r["run"] for r in traffic})==2 and rows[-1].get("alerts")==[], "Missing sticky or alert recovery"
        for name in ("HighTTFC","HighRejectionRate"):
            for state in ("pending","firing"):
                assert any(a["name"]==name and a["state"]==state for s in rows for a in s.get("alerts",[])),(name,state)
    finally:
        data("c-timeline.jsonl",rows);data("c-requests.jsonl",traffic)
if __name__=="__main__":main()
