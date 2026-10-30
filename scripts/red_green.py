"""Execute the SAME integration regressions on the preserved original commit."""
import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ORIGINAL='59c11d4c9c510780b85a5a72c0170f83724f1278'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--red-only',action='store_true'); args=p.parse_args()
    root=Path(__file__).resolve().parents[1]; evidence=root/'evidence'; evidence.mkdir(exist_ok=True)
    archive=subprocess.check_output(['git','archive','--format=zip',ORIGINAL],cwd=root)
    results={}
    with tempfile.TemporaryDirectory(prefix='hw8910-original-') as tmp:
        with zipfile.ZipFile(io.BytesIO(archive)) as z: z.extractall(tmp)
        versions=[('red',Path(tmp))] if args.red_only else [('red',Path(tmp)),('green',root)]
        for label,impl in versions:
            command=[sys.executable,'-m','unittest','discover','-s',str(root/'tests_integration'),'-v']
            run=subprocess.run(command,cwd=root,env=dict(os.environ,LAB_IMPL=str(impl),PYTHONUTF8='1'),
                               stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=240)
            (evidence/f'integration-{label}.log').write_text(run.stdout,encoding='utf-8')
            print(label.upper(),'exit',run.returncode,run.stdout[-2000:],flush=True)
            results[label]=dict(exit_code=run.returncode,original_commit=ORIGINAL if label=='red' else None)
            if label=='red':
                assert run.returncode!=0 and 'Ran 7 tests' in run.stdout
                assert 'FAILED (failures=7)' in run.stdout, 'All seven must fail for behavioral assertions, not import/CLI errors'
            else:
                assert run.returncode==0 and 'Ran 7 tests' in run.stdout
    (evidence/'red-green.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print('Verified seven behavioral RED -> GREEN regressions' if not args.red_only else 'Seven original defects reproduced')


if __name__=='__main__': main()
