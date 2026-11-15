"""Post-run inventory, exact same-window classic histogram delta and raw JSONL merge."""
import json
import math
from urllib.parse import urlencode
from hw11.cluster import RESULT, data,dump,k,kj,run
from hw11.hpa import fetch

def query(expr):
    r=fetch("/api/v1/query?"+urlencode({"query":expr}))
    if r["status"]!="success":raise ValueError(r)
    return r["data"]["result"]

def range_query(expr,start,end,step=5):
    return fetch("/api/v1/query_range?"+urlencode(dict(query=expr,start=start,end=end,step=step)))["data"]["result"]

def numeric(metric):
    if not metric: return None
    n=float(metric[0]["value"][1])
    return n if math.isfinite(n) else None

def compare():
    phases=json.loads((RESULT/"balance-summary.json").read_text(encoding="utf-8"))
    rows=[]
    queries={}
    pod_signals={}
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
            results[field]=dict(prom_p95=numeric(p95),prom_count=numeric(n),
                                client_p95=phase[client_key],client_count=phase["completed"])
        if phase["pattern"]=="skew":
            pod_signals[run_id]=range_query('{job="api",__name__=~"ml_running|ml_waiting"}',
                 phase["start_unix"],phase["start_unix"]+120)
        rows.append(dict(run=run_id,start=start,end=end,results=results))
    dump("promql.json",queries);dump("prom-v-client.json",rows);dump("b-pod-signals.json",pod_signals)

def main():
    dump("server-versions.json",kj("version"))
    dump("pods-final.json",kj("get","pods"))
    dump("services-final.json",kj("get","service"))
    dump("prom-targets.json",fetch("/api/v1/targets")["data"])
    dash=fetch("/api/dashboards/uid/hw11-observability","http://grafana:3000")["dashboard"]
    dump("grafana-live-export.json",dash)
    dump("prom-cpu-ram.json",{q:query(q) for q in [
        'count by(job) (up)', 'sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="hw11",container="api"}[1m]))',
        'sum by(pod) (container_memory_working_set_bytes{namespace="hw11",container="api"})', 'sum(up{job="ready-endpoint"})']})
    dump("container-images.json",run("docker","exec","mlops11-control-plane","crictl","images").stdout.splitlines())
    dump("container-disk.json",dict(node_used=run("docker","exec","mlops11-control-plane","du","-sh",
             "/var/lib/containerd","/var/lib/kubelet",check=False).stdout,
             telemetry_used=run("docker","exec","mlops11-control-plane","du","-sh","/var/log/pods",
             check=False).stdout,
             images={i:run("docker","image","inspect",i,"--format","{{.Size}} {{json .RepoDigests}}",check=False).stdout.strip()
                     for i in ("mlops11-api:1.0.0","kindest/node:v1.34.0")}))
    dump("network.json",dict(kube_proxy_config=kj("-n","kube-system","get","configmap","kube-proxy")["data"],
         kube_proxy_logs=k("-n","kube-system","logs","-l","k8s-app=kube-proxy","--tail=12").splitlines()))
    paths=sorted(list(RESULT.glob("b-*.jsonl"))+list(RESULT.glob("*-requests.jsonl")))
    data("requests.jsonl",(json.loads(line) for p in paths for line in p.read_text(encoding="utf-8").splitlines() if line.strip()))
    compare()
if __name__=="__main__":main()
