"""Controlled 2 policies × 2 patterns × 3 measured 120-second phases."""
import collections
import time
from hw11.cluster import data,dump,k,kj,load,RESULT

def percentile(xs,p):
    xs=sorted(xs)
    if not xs:return None
    rank=(len(xs)-1)*p; lo=int(rank)
    return xs[lo]+(xs[min(lo+1,len(xs)-1)]-xs[lo])*(rank-lo)

def summary(rows):
    outcomes=dict(collections.Counter(r["outcome"] for r in rows))
    groups=collections.defaultdict(list)
    for r in rows:
        if r.get("pod"):groups[r["pod"]].append(r)
    def stats(items):
        good=[r for r in items if r["outcome"]=="completed"]
        return dict(n=len(items),completed=len(good),rejected=sum(r["outcome"]=="rejected" for r in items),
            ttfc_p50=percentile([r["ttfc_seconds"] for r in good],.5),ttfc_p95=percentile([r["ttfc_seconds"] for r in good],.95),
            full_p50=percentile([r["total_seconds"] for r in good],.5),full_p95=percentile([r["total_seconds"] for r in good],.95),
            queue_p95=percentile([r["queue_seconds"] for r in good],.95),
            hit=sum(r.get("cache_hit") is True for r in good),miss=sum(r.get("cache_hit") is False for r in good))
    return {**stats(rows),"outcomes":outcomes,"sent":sum(r.get("sent_monotonic") is not None for r in rows),
        "by_pod":{p:stats(v) for p,v in groups.items()},
        "by_client":dict(collections.Counter(r["client"] for r in rows)),
        "peer_ips":sorted({r["peer_ip"] for r in rows if r.get("peer_ip")}),
        "send_lag_p95":percentile([r["send_lag_seconds"] for r in rows if r.get("send_lag_seconds") is not None],.95)}

def main():
    results=[]
    for repeat in range(1,4):
        for pattern in ("uniform","skew"):
            pair=("sticky","balanced") if repeat%2 else ("balanced","sticky")
            for policy in pair:
                tag=f"b-{pattern}-{policy}-{repeat}"
                existing=RESULT/(tag+".jsonl")
                if existing.exists():
                    import json
                    rows=[json.loads(line) for line in existing.read_text(encoding="utf-8").splitlines()]
                    start=rows[0]["planned_wall"]
                    assert len(rows)==800
                else:
                    print("START",tag,flush=True)
                    rows,start=load(tag,policy,pattern)
                report=dict(run=tag,pattern=pattern,policy=policy,repeat=repeat,start_unix=start,
                     schedule_seconds=120,interval_seconds=.15,initial_cache="cold distinct prefix namespace",**summary(rows))
                results.append(report)
                dump("balance-summary.json",results)
                print("DONE",tag,report["outcomes"],"p95",report["ttfc_p95"],"pod",[(p,v["n"]) for p,v in report["by_pod"].items()],flush=True)
    dump("client-pods.json",[{ "name":p["metadata"]["name"],"ip":p["status"].get("podIP")}
          for p in kj("get","pods","-l","app=hw11-client")["items"]])
if __name__=="__main__": main()
