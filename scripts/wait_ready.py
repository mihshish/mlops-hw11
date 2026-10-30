"""Capture actual health vs readiness while real model loads in background."""
import time
import argparse
from scripts.http_client import request
from process_core import write


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',default='evidence/real-readiness.json'); a=p.parse_args()
    start=time.perf_counter(); observations=[]; previous=None
    for attempt in range(360):
        try:
            health,h,_=request('http://127.0.0.1:8091','/health',timeout=3)
            ready,r,_=request('http://127.0.0.1:8091','/ready',timeout=3)
            phase=(health,ready)
            if phase!=previous:
                row=dict(elapsed_seconds=time.perf_counter()-start,health=health,ready=ready,health_body=h,ready_body=r)
                observations.append(row); print(row,flush=True); previous=phase
            if ready==200:
                write(a.output,dict(observations=observations,load_wait_seconds=time.perf_counter()-start))
                return
        except OSError:
            pass
        time.sleep(1)
    raise SystemExit('Real API did not become ready in six minutes; inspect .runtime/service-err.log')


if __name__=='__main__': main()
