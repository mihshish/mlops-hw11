import json
import os
from pathlib import Path
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

CTX=os.environ.get("HW11_CONTEXT","kind-mlops11")
NS="hw11"
_LOCAL_KUBECTL=Path(".runtime/bin/kubectl.exe")
KUBECTL=str(_LOCAL_KUBECTL.resolve()) if _LOCAL_KUBECTL.exists() else "kubectl"
K=[KUBECTL,"--context",CTX,"-n",NS]
RESULT=Path("results")
WORK=Path(".runtime")
RESULT.mkdir(exist_ok=True)
def run(*command,check=True,timeout=100):
    p=subprocess.run([str(a) for a in command],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
    if check and p.returncode: raise RuntimeError(f"{list(command)} exit {p.returncode}: {p.stdout}\n{p.stderr}")
    return p

def k(*a,**kw): return run(*K,*a,**kw).stdout

def kj(*a): return json.loads(k(*a,"-o","json"))

def helm(*args,**kw):
    binary=WORK/"bin/windows-amd64/helm.exe"
    return run(str(binary.resolve()) if binary.exists() else "helm",*args,"--kube-context",CTX,**kw).stdout

def release(**values):
    sets=[]
    for n,v in values.items():
        sets.extend(["--set",n.replace("__",".")+"="+str(v).lower() if isinstance(v,bool) else n.replace("__",".")+"="+str(v)])
    return helm("upgrade","--install","hw11","hw11/chart","-n",NS,"--create-namespace",*sets)

def rollout(timeout=130): return k("rollout","status","deployment/api",f"--timeout={timeout}s",timeout=timeout+10)

def dump(name,obj): (RESULT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def data(name,rows):
    with (RESULT/name).open("w",encoding="utf-8",newline="\n") as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")

def client(command,*args, pod=0,timeout=170):
    return k("exec",f"load-{pod}","--","python","-m","lab11.client",*command,*map(str,args),timeout=timeout)

def single(tag,host="balanced",pod=0,more=(),timeout=60):
    return json.loads(client(("--single","--host",host,"--run",tag),"--client",pod,*more,pod=pod,timeout=timeout))

def load(tag,host,pattern="uniform",duration=120,interval=.15,cpu=0):
    start=time.time()+12
    cmd=("--host",host,"--run",tag,"--pattern",pattern,"--start",str(start),
         "--duration",str(duration),"--interval",str(interval),"--cpu-ms",str(cpu))
    with ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(client,cmd,"--client",p,pod=p,timeout=duration+45) for p in range(4)]
        raws=[f.result() for f in fs]
    rows=sorted([json.loads(l) for raw in raws for l in raw.splitlines() if l.strip()],key=lambda r:r["planned_wall"])
    assert len(rows)==round(duration/interval),(tag,len(rows),duration,interval)
    data(tag+".jsonl",rows)
    return rows,start

def sample():
    pods=kj("get","pods","-l","app=hw11-api")["items"]
    slices=kj("get","endpointslice","-l","kubernetes.io/service-name=balanced")["items"]
    hpa=kj("get","hpa")["items"]
    return dict(time=time.time(),pods=[dict(name=p["metadata"]["name"],version=p["metadata"]["labels"]["model-version"],
        created=p["metadata"]["creationTimestamp"],deleting=p["metadata"].get("deletionTimestamp"),
        ready=any(c["type"]=="Ready" and c["status"]=="True" for c in p.get("status",{}).get("conditions",[])),
        restart_count=sum(x["restartCount"] for x in p.get("status",{}).get("containerStatuses",[])))
        for p in pods], endpoints=[dict(pod=e.get("targetRef",{}).get("name"),**e["conditions"]) for s in slices for e in s["endpoints"]],
        hpa=hpa[0].get("status",{}) if hpa else None)
