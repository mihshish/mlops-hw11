"""Summarize live evidence without silently replacing failed or missing experiments."""
import collections
import datetime as dt
import json
from pathlib import Path
import statistics
from hw11.cluster import dump
from hw11.report import obj, lines

def mean_median(values):
    return statistics.median(v for v in values if v is not None) if any(v is not None for v in values) else None

def result_b(phases):
    reports=[]
    signals=obj("b-pod-signals.json",{})
    for r in phases:
        total=sum(x["n"] for x in r["by_pod"].values())
        heavy=max(r["by_pod"],key=lambda p:r["by_pod"][p]["n"]) if total else None
        waiting=collections.defaultdict(dict)
        running=collections.defaultdict(dict)
        for series in signals.get(r["run"],[]):
            key=series["metric"].get("pod")
            target=waiting if series["metric"]["__name__"]=="ml_waiting" else running
            for epoch,value in series["values"]:target[epoch][key]=float(value)
        simultaneous=[dict(time=t,hot=heavy,waiting=wp[heavy],cold=other,running=n) for t,wp in waiting.items()
                      if wp.get(heavy,0)>0 for other,n in running.get(t,{}).items() if other!=heavy and n<2]
        reports.append(dict(run=r["run"],pattern=r["pattern"],policy=r["policy"],repeat=r["repeat"],
                            routed=total,heavy_pod=heavy,
                            max_pod_share=r["by_pod"][heavy]["n"]/total if total else None,
                            loss_fraction=(r["sent"]-r["completed"])/r["sent"] if r["sent"] else None,
                            hit_fraction=r["hit"]/r["completed"] if r["completed"] else None,
                            success_p95_ttfc=r["ttfc_p95"],success_p95_queue=r["queue_p95"],
                            waiting_with_capacity_samples=len(simultaneous),
                            capacity_example=simultaneous[0] if simultaneous else None))
    grouped={}
    for pattern in ("uniform","skew"):
        for policy in ("sticky","balanced"):
            rr=[r for r in reports if r["pattern"]==pattern and r["policy"]==policy]
            if rr:grouped[pattern+"/"+policy]=dict(repeats=len(rr),
                   median_p95_ttfc=mean_median([r["success_p95_ttfc"] for r in rr]),
                   median_p95_queue=mean_median([r["success_p95_queue"] for r in rr]),
                   median_loss_fraction=mean_median([r["loss_fraction"] for r in rr]),
                   median_hottest_share=mean_median([r["max_pod_share"] for r in rr]),
                   median_hit_fraction=mean_median([r["hit_fraction"] for r in rr]),
                   total_hot_with_capacity_samples=sum(r["waiting_with_capacity_samples"] for r in rr))
    return dict(grouped=grouped,phase_details=reports)

def result_c(timeline,traffic):
    phases={}
    for phase in ("balanced_cpu","sticky_cpu"):
        trace=[s for s in timeline if s["phase"].startswith(phase) and "pods" in s]
        requests=[r for r in traffic if r["run"]=="c-"+phase.split("_",1)[0]]
        if not trace or not requests:continue
        t0=min(r["planned_wall"] for r in requests); last=max(r["planned_wall"] for r in requests)
        initial={p["name"] for p in trace[0]["pods"]}
        new={}
        for s in trace:
            for pod in s["pods"]:
                if pod["name"] in initial:continue
                record=new.setdefault(pod["name"],dict(created_seconds=dt.datetime.fromisoformat(pod["created"]).timestamp()-t0,
                                          observed_seconds=s["time"]-t0,ready_seconds=None))
                if pod["ready"] and record["ready_seconds"] is None:record["ready_seconds"]=s["time"]-t0
        after_three=False; returned=None
        for s in trace:
            if len(s["pods"])==3:after_three=True
            if after_three and len(s["pods"])==2 and s["time"]>=last and returned is None:returned=s["time"]-last
        transitions=[]
        previous={}
        for s in trace:
            if "alerts" not in s:continue
            current={a["name"]:a["state"] for a in s["alerts"]}
            for name in sorted(current.keys()|previous.keys()):
                before=previous.get(name,"inactive"); after=current.get(name,"inactive")
                if before!=after:transitions.append(dict(name=name,before=before,after=after,seconds=s["time"]-t0))
            previous=current
        pod_counts=collections.Counter(r["pod"] for r in requests if r.get("pod"))
        phases[phase]=dict(counts=dict(collections.Counter(r["outcome"] for r in requests)),
               ponames_and_counts=dict(pod_counts),new_pods=new,observed_return_after_last_planned_seconds=returned,
               replicas=[len(s["pods"]) for s in trace],ready_max=max(sum(p["ready"] for p in s["pods"]) for s in trace),
               transitions=transitions,final_alerts=trace[-1].get("alerts"),
               busiest_pod_share=(max(pod_counts.values())/sum(pod_counts.values())) if pod_counts else None)
    return phases

def main():
    b=result_b(obj("balance-summary.json",[]))
    c=result_c(lines("c-timeline.jsonl"),lines("c-requests.jsonl"))
    dump("measured-findings.json",dict(balance=b,hpa=c))
    print(json.dumps(dict(balance=b["grouped"],hpa=c),indent=2),flush=True)

if __name__=="__main__":main()
