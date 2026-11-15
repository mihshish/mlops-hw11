"""Scoped setup / teardown. Never prune Docker or touch other workloads."""
import argparse
import json
import platform
import shutil
from pathlib import Path
from hw11.cluster import CTX,NS,KUBECTL,WORK,dump,k,kj,release,rollout,run,single

NAME="mlops11"
NODE="kindest/node:v1.34.0"
IMAGES=["prom/prometheus:v3.5.0","grafana/grafana:12.1.1",
        "registry.k8s.io/metrics-server/metrics-server:v0.8.0"]
URL="https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.0/components.yaml"

def kind(*args,**kwargs):
    bin=WORK/"bin/kind.exe"
    return run(bin.resolve() if bin.exists() else "kind",*args,**kwargs)

def preflight():
    disk=shutil.disk_usage(Path.cwd().anchor)
    engine=run("docker","info","--format","{{json .}}",check=False,timeout=15)
    d=dict(platform=platform.platform(),free_bytes=disk.free,disk_bytes=disk.total,docker_error=engine.stderr)
    if engine.returncode==0:
        obj=json.loads(engine.stdout)
        d.update(engine_version=obj["ServerVersion"],cpus=obj["NCPU"],docker_ram_bytes=obj["MemTotal"],os=obj["OSType"])
    dump("preflight.json",d);print(d,flush=True)
    if engine.returncode!=0:raise SystemExit("Docker engine unavailable; start Docker Desktop first")
    if d["os"]!="linux":raise SystemExit("Switch Docker Desktop to Linux containers")
    if disk.free<8*1024**3:raise SystemExit("Need at least 8 GiB free on Docker/host disk; no images downloaded")
    return d

def setup():
    assert CTX=="kind-mlops11","Setup is scoped to the default isolated lab cluster"
    preflight()
    kind("version")
    # Build before loading other images to avoid concurrent extraction peaks on 8 GiB hosts.
    run("docker","build","-f","Dockerfile.hw11","-t","mlops11-api:1.0.0",".",timeout=500)
    if NAME not in kind("get","clusters").stdout.splitlines():
        kind("create","cluster","--config","hw11/kind.yaml","--image",NODE,"--wait","180s",timeout=700)
    proxy=kj("-n","kube-system","get","configmap","kube-proxy")["data"]["config.conf"]
    if "mode: nftables" not in proxy and 'mode: "nftables"' not in proxy:
        raise SystemExit("This lab needs the nftables kind config (old iptables WSL cluster cannot implement ClientIP).")
    kind("load","docker-image","mlops11-api:1.0.0","--name",NAME,timeout=300)
    # Pull directly into the node, without a duplicate host image import for monitoring.
    for image in IMAGES:
        run("docker","exec","mlops11-control-plane","crictl","pull",image,timeout=300)
    run(KUBECTL,"--context",CTX,"apply","-f",URL,timeout=120)
    dep=kj("-n","kube-system","get","deployment","metrics-server")
    args=dep["spec"]["template"]["spec"]["containers"][0]["args"]
    patch=[dict(op="add",path="/spec/template/spec/containers/0/args/-",value="--kubelet-insecure-tls")] if "--kubelet-insecure-tls" not in args else []
    if patch:k("-n","kube-system","patch","deployment","metrics-server","--type=json","-p",json.dumps(patch))
    print(release(),flush=True);print(rollout(),flush=True)
    for target in ("deployment/prometheus","deployment/grafana","pod/load-0","pod/load-1","pod/load-2","pod/load-3"):
        condition="Available" if target.startswith("deployment") else "Ready"
        print(k("wait",f"--for=condition={condition}",target,"--timeout=120s",timeout=130).strip())
    print(k("get","pods","-o","wide"))
    dump("metrics-server-config.json",kj("-n","kube-system","get","deployment","metrics-server"))
    rows=[single(f"stand-smoke-{mode}",mode) for mode in ("balanced","sticky")]
    dump("stand-network-smoke.json",rows)
    if not all(r["status"]==200 and r["outcome"]=="completed" for r in rows):
        raise SystemExit(f"Service smoke failed (no benchmark will be meaningful): {rows}")
    print("Both Services served and completed a real Kubernetes stream.",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["preflight","up","status","down"])
    p.add_argument("--confirm",action="store_true");a=p.parse_args()
    if a.command=="up":setup()
    elif a.command=="preflight":preflight()
    elif a.command=="status":
        print(k("get","deploy,pods,svc,hpa","-o","wide"))
        print(k("get","endpointslice","-l","kubernetes.io/service-name=balanced","-o","wide"))
    elif a.confirm:
        assert CTX=="kind-mlops11";print(kind("delete","cluster","--name",NAME,timeout=180).stdout)
    else:p.error("down deletes ONLY kind/mlops11; specify --confirm")
if __name__=="__main__":main()
