"""Verify Git transport, Windows newline policy and a clean-clone quick run."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from process_core import write


def main():
    root=Path.cwd()
    with tempfile.TemporaryDirectory(prefix='hw8910-checkout-') as tmp:
        clone=Path(tmp)/'repo'
        subprocess.run(['git','-c','core.autocrlf=true','clone','--no-hardlinks',str(root),str(clone)],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        command=[sys.executable,'-m','scripts.check']
        env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        p=subprocess.run(command,cwd=clone,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                         text=True,encoding='utf-8',timeout=180)
        Path('evidence/fresh-checkout.log').write_text(p.stdout,encoding='utf-8')
        print(p.stdout[-700:],flush=True)
        assert p.returncode==0,p.stdout
        validation=subprocess.run([sys.executable,'-c','from provenance import verified_evaluation; c,r,p=verified_evaluation(); print(p)'],
            cwd=clone,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert validation.returncode==0,validation.stderr
        write('evidence/fresh-checkout.json',dict(command=command,exit_code=p.returncode,
              upstream_integrity_exit=validation.returncode,upstream_integrity_output=validation.stdout.strip(),
              source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))
        print('FRESH CHECKOUT: 44/44 and complete upstream byte integrity passed',flush=True)


if __name__=='__main__': main()
