"""Post-run inventory, exact same-window classic histogram delta and raw JSONL merge."""
import json
from urllib.parse import urlencode
from hw11.cluster import RESULT, data,dump,k,kj,run
from hw11.hpa import fetch
from hw11.balance import summary

def query(expr):
    r=fetch("/api/v1/query?"+urlencode({"query":expr}))
    if r["status"]!="success":raise ValueError(r)
    return r["data"]["result"]

def compare():
    phases=json.loads((RESULT/"balance-summary.json").read_text(encoding="utf-8"))
    rows=[]
    queries={}
    for phase in phases:
        run_id=phase["run"]; start=phase["start_unix"]-.5
        raw=[json.loads(l) for l in (RESULT/(run_id+".jsonl")).read_text(encoding="utf-8").splitlines()]
        end=max(r["sent_wall"]+r["total_seconds"] for r in raw if r.get("sent_wall") is not None)+6
        results={}
        for field,client_key in [("ttfc","ttfc_p95"),("full","full_p95")]:
            hist=f'ml_{field}_seconds_bucket{{job="api"}}'
            delta=f'(sum by (le) ({hist} @ {end:.3f}) - sum by (le) ({hist} @ {start:.3f}))'
            quant=f'histogram_quantile(0.95, {delta})'
            count=delta.replace("sum by (le)","sum").replace("_bucket{","_bucket{le=\"+Inf\",")
            p95=query(quant); n=query(count)
            queries[f"{run_id}/{field}"]=dict(quantile=quant,count=count)
            results[field]=dict(prom_p95=float(p95[0]["value"][1]) if p95 else None,
                prom_count=float(n[0]["value"][1]) if n else None,client_p95=phase[client_key],client_count=phase["completed"])
        rows.append(dict(run=run_id,start=start,end=end,results=results))
    dump("promql.json",queries);dump("prom-v-client.json",rows)

def main():
    dump("server-versions.json",kj("version"))
    dump("pods-final.json",kj("get","pods"))
    dump("services-final.json",kj("get","service"))
    dump("prom-targets.json",fetch("/api/v1/targets")["data"])
    dump("prom CPU and RAM.json",{q:query(q) for q in [
        'count by(job) (up)', 'sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="hw11",container="api"}[1m]))',
        'sum by(pod) (container_memory_working_set_bytes{namespace="hw11",container="api"})', 'sum(up{job="ready-endpoint"})']})
    dump("container-images.json",run("docker","exec","mlops11-control-plane","crictl","images").stdout.splitlines())
    dump("container-disk.json",dict(node_used=run("docker","exec","mlops11-control-plane","du","-sh","/var/lib/containerd","/var/lib/kubelet",check=False).stdout,
             images=run("docker","image","ls","--format","{{.Repository}}:{{.Tag}} {{.Size}}",check=False).stdout.splitlines()))
    paths=sorted(list(RESULT.glob("b-*.jsonl"))+list(RESULT.glob("*-requests.jsonl")))
    data("requests.jsonl",(json.loads(line) for p in paths for line in p.read_text(encoding="utf-8").splitlines() if line.strip()))
    compare()
if __name__=="__main__":main()
