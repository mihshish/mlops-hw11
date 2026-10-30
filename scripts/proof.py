"""Display measured evidence; explicitly not a new model/pipeline execution."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument('kind',choices=['flow','rollback','benchmark'])
    a=p.parse_args()
    print('SAVED EXPERIMENT EVIDENCE (not rerunning heavy steps)',flush=True)
    if a.kind=='flow':
        for name in ('prefect-fail-after-prepare','prefect-recover','prefect-invalidate','process-crash-after-pointer','process-crash-recover'):
            path=Path('evidence')/(name+'.log')
            print('\nSOURCE:',path)
            for line in path.read_text(encoding='utf-8').splitlines():
                if any(key in line for key in ('FLOW_ID','PREPARATION_STATE','PREPARED','CACHE_HIT','ALREADY_PUBLISHED','Injected','Finished in state')):
                    print(line)
        path=Path('evidence/real-flow-summary.json')
    elif a.kind=='rollback': path=Path('evidence/rollback-http.json')
    else: path=Path('evidence/benchmark-summary.json')
    print('\nSOURCE:',path)
    print(json.dumps(json.loads(path.read_text(encoding='utf-8')),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
