"""Actual retained baseline and rejected candidate through the Prefect flow."""
import os
import subprocess
import sys
from pathlib import Path
import release
from process_core import write,read
from scripts.runner import capture


def main():
    root=Path('.runtime/real'); records=[]
    def run(label,role,fail=False,expected=0):
        command=[sys.executable,'pipeline.py','--workspace',str(root),'--manifest',f'manifest-{role}.json','--report',f'report-{role}.json']
        if fail: command.append('--fail-after-prepare')
        before=release.file_sha(root/'accepted.json')
        r=capture(command,Path(f'evidence/real-flow-{label}.log'),timeout=240)
        after=release.file_sha(root/'accepted.json')
        Path(f'evidence/real-flow-{label}.log').write_text(r.stdout,encoding='utf-8')
        records.append(dict(label=label,command=command,exit_code=r.returncode,
                            accepted_sha256_before=before,accepted_sha256_after=after))
        print(label,'EXIT',r.returncode,'accepted unchanged:',before==after,r.stdout[-900:],flush=True)
        assert (r.returncode==0)==(expected==0),r.stdout
        if expected!=0: assert before==after,'Failed flow modified accepted.json'
        return r
    run('failure-after-prepare','baseline',True,expected=1)
    recovered=run('baseline-recover','baseline')
    assert 'PREPARATION_STATE Cached' in recovered.stdout,recovered.stdout
    run('baseline-repeat','baseline')
    run('candidate-rejected','candidate',expected=1)
    assert len((root/'publications.jsonl').read_text().splitlines())==1
    assert read(root/'accepted.json')['evaluation_role']=='baseline'
    write('evidence/real-flow-summary.json',dict(attempts=records,actual_publications=1,
        final_model_id=read(root/'accepted.json')['model_id'],no_training=True))
    print('REAL FLOW VERIFIED: retained baseline, rejected candidate, one publication')


if __name__=='__main__': main()
