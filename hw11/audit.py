"""Read-only checks of the submission (no HTTP and no rerun of the experiments)."""
from collections import Counter
from hashlib import sha256
import math
from pathlib import Path
from hw11.report import obj,lines

def main():
    phase=obj("balance-summary.json",[])
    actual=Counter((r["pattern"],r["policy"]) for r in phase)
    target=Counter({(pattern,mode):3 for pattern in ("uniform","skew") for mode in ("sticky","balanced")})
    assert actual==target,actual
    client=obj("client-pods.json",[])
    assert len({p["ip"] for p in client})==4,client
    stable=set()
    for p in phase:
        rows=lines(p["run"]+".jsonl")
        assert len(rows)==len({r["id"] for r in rows})==800
        assert all(r["expected_chunks"]==3 for r in rows if r.get("sent_monotonic") is not None)
        assert math.isclose(max(r["planned_wall"] for r in rows)-min(r["planned_wall"] for r in rows),
                            119.85,abs_tol=.01)
        stable.update(p["by_pod"])
        weights=Counter(r["client"] for r in rows)
        expected=200 if p["pattern"]=="uniform" else 641
        assert abs(weights[0]-expected)<=3,weights
        assert all(r.get("backend_mode")=="simulated" and r.get("version")=="A" and r["chunks"]==3
                   for r in rows if r["outcome"]=="completed")
        assert sum(p["outcomes"].values())==800
    assert len(stable)==2,stable
    print("PASS B: 12 × 120 s, four source IPs, 9600 scheduled, same two replicas")
    a=obj("a-summary.json",{})
    assert a["broken_early"]>0 and a["fixed_early"]==0
    assert a["rollout_5xx"]==a["rollout_incomplete"]==0 and a["rollout_completed"]>1
    assert a["long_stream"]["outcome"]=="completed" and a["long_stream"]["chunks"]==30
    assert a["forced_outcome"]=="aborted" and a["forced_chunks"]>0
    assert a["rollback_versions"]==["A"]*4 and not a["failed_B_ready"]
    print("PASS A: cold failure and fix, complete stream, bad B rejected, rollback A, forced abort")
    c=obj("measured-findings.json",{})["hpa"]
    states=c["balanced_cpu"]["replicas"]
    assert states[0]==states[-1]==2 and 3 in states and c["balanced_cpu"]["ready_max"]==3
    for name in ("HighTTFC","HighRejectionRate"):
        transition={t["after"] for run in c.values() for t in run["transitions"] if t["name"]==name}
        assert {"pending","firing","inactive"} <= transition,(name,transition)
    assert len(c)==2 and c["sticky_cpu"]["final_alerts"]==[]
    assert c["sticky_cpu"]["replicas"][0]==c["sticky_cpu"]["replicas"][-1]==2
    assert min(c["sticky_cpu"]["replicas"])==2 and max(c["sticky_cpu"]["replicas"])==3
    fix=obj("hpa-install-fix.json",{})
    if fix:
        assert fix["fixed_install_min"]==2 and fix["pod_names_unchanged"]
    print("PASS C: autoscaling and readiness, both alerts pending → firing → inactive")
    checks=obj("checks.json",[])
    assert len(checks)==5 and all(r["passed"] for r in checks)
    comp=obj("prom-v-client.json",[])
    assert len(comp)==len(phase) and all(
        v["prom_count"] is not None and v["prom_p95"] is not None
        for r in comp for v in r["results"].values())
    n_exact=sum(v["prom_count"]==v["client_count"] for r in comp for v in r["results"].values())
    print(f"Prometheus vs client counts: {n_exact}/24 matched exactly; investigate any difference.")
    projected=lines("requests.jsonl")
    assert len(projected)>=9600
    for name in ("a-ready","b-pods","b-policies","c-hpa"):
        assert Path("results", "plots",name+".svg").is_file()
    print("PASS: five integration checks, four measured SVG charts, raw rows",len(projected))
    for name in ("report.html","results/requests.jsonl","results/balance-summary.json"):
        print(name,sha256(Path(name).read_bytes()).hexdigest())

if __name__=="__main__":main()
