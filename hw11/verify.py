"""Five acceptance checks: three against live Kubernetes, two evidence/HTTP checks."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from hw11.cluster import data,dump,k,kj,release,rollout,sample,single,RESULT
from hw11.rollout import Trace

def main():
    checks=[]; rows=[]
    def passed(name,**actual):
        checks.append(dict(check=name,passed=True,**actual)); print("PASS",name,actual,flush=True)
    try:
        rollout()
        exp=json.loads((RESULT/"a-summary.json").read_text(encoding="utf-8"))
        events=json.loads((RESULT/"a-events.json").read_text(encoding="utf-8"))
        assert exp["broken_early"]>0 and exp["fixed_early"]==0
        with ThreadPoolExecutor(2) as pool:
            future=pool.submit(single,"verify-long-live","balanced",0,("--chunks",30,"--chunk-seconds",.9))
            time.sleep(2)
            release(modelVersion="B")
            after=[]
            for i in range(16):
                s=sample(); after.append(s)
                if any(p["version"]=="B" and not p["ready"] for p in s["pods"]):
                    warming={p["name"] for p in s["pods"] if p["version"]=="B" and not p["ready"]}
                    assert not warming & {e["pod"] for e in s["endpoints"] if e.get("ready")}
                    warm=single("verify-during-warmup")
                    rows.append(warm)
                    assert warm["outcome"]=="completed" and warm["warmed"]=="true" and warm["pod"] not in warming
                    passed("warmup_endpoint_service",warming=sorted(warming),served_by=warm["pod"])
                    break
                time.sleep(.3)
            else:raise AssertionError("No warming B sampled")
            rollout()
            rows.append(future.result())
            assert rows[-1]["outcome"]=="completed"
        through=single("verify-B")
        assert through["version"]=="B" and through["outcome"]=="completed"
        release(modelVersion="A");rollout()
        restored=single("verify-rollback-A");rows.extend([through,restored])
        assert restored["version"]=="A" and restored["artifact_sha256"]!=through["artifact_sha256"]
        passed("actual_loaded_version_after_rollback",before=through["version"],after=restored["version"])
        x=single("verify-A-history",more=("--history",'["FIRST_DIALOG_MARK"]',"--session","dialog-A"))
        old=x["pod"]
        assert old and x["outcome"]=="completed"
        names={p["metadata"]["name"] for p in kj("get","pods","-l","app=hw11-api")["items"]}
        k("delete","pod",old,"--wait=true")
        rollout()
        replacement=next(p for p in kj("get","pods","-l","app=hw11-api")["items"]
                         if p["metadata"]["name"] not in names)
        new=single("verify-A-continue",host=replacement["status"]["podIP"],
                   more=("--history",'["FIRST_DIALOG_MARK"]',"--session","dialog-A"))
        y=single("verify-B-history",pod=1,more=("--history",'["SECOND_DIALOG_MARK"]',"--session","dialog-B"))
        rows.extend([x,new,y])
        assert new["pod"]==replacement["metadata"]["name"] and old!=new["pod"]
        assert x["artifact_sha256"]==new["artifact_sha256"] and new["version"]=="A"
        assert all(r["outcome"]=="completed" for r in [x,new,y])
        passed("pod_replacement_artifact_and_dialog",old=old,new=new["pod"],sha256=new["artifact_sha256"])
        assert "FIRST_DIALOG_MARK" in new["first_text"] and "SECOND_DIALOG_MARK" not in new["first_text"]
        assert "SECOND_DIALOG_MARK" in y["first_text"] and "FIRST_DIALOG_MARK" not in y["first_text"]
        passed("dialog_isolation",session_a=new["session_id"],session_b=y["session_id"])
        rejected=single("verify-rejected",more=("--prompt"," "))
        rows.append(rejected)
        assert rejected["status"]==422 and rejected["outcome"]=="rejected" and rejected["chunks"]==0
        assert exp["forced_outcome"]=="aborted" and 0<exp["forced_chunks"]<30
        passed("rejection_and_abort_counted_separately",reject_status=422,forced_chunks=exp["forced_chunks"])
    finally:
        dump("checks.json",checks);data("checks-requests.jsonl",rows)
if __name__=="__main__":main()
