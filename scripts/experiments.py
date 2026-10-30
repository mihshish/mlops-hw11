"""Replay controlled stub incidents and persist raw command/output evidence."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
import release
from process_core import read,write
from scripts.runner import capture


def main():
    p=argparse.ArgumentParser(); p.add_argument('--prefect',action='store_true'); a=p.parse_args()
    repo=Path(__file__).resolve().parents[1]; evidence=repo/'evidence'; evidence.mkdir(exist_ok=True)
    name='prefect' if a.prefect else 'process'
    records=[]
    with tempfile.TemporaryDirectory(prefix='hw8910-experiment-') as tmp:
        root=Path(tmp)/'stand'
        def invoke(label,*args,expected=0,script='lab.py'):
            command=[sys.executable,script,'--workspace',str(root),*args]
            result=capture(command,evidence/f'{name}-{label}.log',cwd=repo,timeout=240)
            records.append(dict(label=label,command=command,exit_code=result.returncode))
            print(label,'EXIT',result.returncode,result.stdout[-650:],flush=True)
            if expected==0: assert result.returncode==0,result.stdout
            else: assert result.returncode!=0,result.stdout
            return result
        invoke('init','init')
        if a.prefect:
            config=read(root/'config.json'); config['experiment_id']=uuid.uuid4().hex
            write(root/'config.json',config)
        source='pipeline.py' if a.prefect else 'lab.py'
        prefix=[] if a.prefect else ['run']
        failed=invoke('fail-after-prepare',*prefix,'--fail-after-prepare',expected=1,script=source)
        resumed=invoke('recover',*prefix,script=source)
        repeat=invoke('repeat',*prefix,script=source)
        assert len((root/'publications.jsonl').read_text().splitlines())==1
        if a.prefect:
            assert 'PREPARATION_STATE Cached' in resumed.stdout,resumed.stdout
        else: assert 'CACHE_HIT' in resumed.stdout
        (root/'input.txt').write_text('Changed bytes at the same input path\n',encoding='utf-8')
        changed=invoke('invalidate',*prefix,script=source)
        assert 'PREPARED' in changed.stdout and 'PREPARATION_STATE Cached' not in changed.stdout
        if a.prefect:
            write(evidence/f'{name}-experiments.json',records)
            print('ALL PREFECT CACHE/RECOVERY EXPERIMENTS VERIFIED; gate/crash proofs are separate',flush=True)
            return
        before=release.file_sha(root/'accepted.json')
        for report in ('report-incomplete.json','report-A.json','report-reject.json'):
            invoke(report.removesuffix('.json'),*prefix,'--report',report,expected=1,script=source)
            assert before==release.file_sha(root/'accepted.json')
        records.append(dict(label='rejection-preserves-accepted',sha256_before=before,
                            sha256_after=release.file_sha(root/'accepted.json')))
        if not a.prefect:
            # Independent workspace/state for the crash between pointer and journal.
            crashroot=Path(tmp)/'crash'; root=crashroot
            invoke('crash-init','init')
            invoke('crash-after-pointer',*prefix,'--fail-after-pointer',expected=1,script=source)
            assert read(root/'accepted.json')['model_id']=='fixture-B'
            invoke('crash-recover',*prefix,script=source); invoke('crash-repeat',*prefix,script=source)
            assert len((root/'publications.jsonl').read_text().splitlines())==1
            invoke('rollback-A',*prefix,'--manifest','manifest-A.json','--report','report-A.json',script=source)
            assert read(root/'accepted.json')['model_id']=='fixture-A'
            records.append(dict(label='crash-recovery-events',count_before_rollback=1,
                                count_after_rollback=len((root/'publications.jsonl').read_text().splitlines())))
    write(evidence/f'{name}-experiments.json',records)
    print('ALL',name.upper(),'EXPERIMENTS VERIFIED')


if __name__=='__main__': main()
