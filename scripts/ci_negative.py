"""Introduce a real temporary code defect in an isolated copy, run original tests."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from process_core import write


def main():
    repo=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='hw8910-ci-negative-') as tmp:
        root=Path(tmp)
        shutil.copy2(repo/'release.py',root/'release.py'); shutil.copytree(repo/'tests',root/'tests')
        with (root/'release.py').open('a',encoding='utf-8') as f:
            f.write('\n# Deliberate defect ONLY in disposable CI copy\ndef cache_key(data_path, config):\n    return "0"*64\n')
        command=[sys.executable,'-m','unittest','discover','-s','tests','-v']
        r=subprocess.run(command,cwd=root,env=dict(os.environ,PYTHONUTF8='1'),stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=30)
        Path('evidence/ci-negative.log').write_text(r.stdout,encoding='utf-8')
        assert r.returncode!=0 and 'AssertionError' in r.stdout,r.stdout
        write('evidence/ci-negative.json',dict(mutated='cache_key -> constant',isolated_copy=True,
              actual_test_exit=r.returncode,source_unchanged=True))
        print(r.stdout[-1700:],flush=True)
    print('NEGATIVE CI: expected nonzero test exit; working code untouched')
    print('actual_test_exit='+str(r.returncode),flush=True)
    raise SystemExit(r.returncode)


if __name__=='__main__': main()
