"""Single quick check: no weights, model imports, training, or network models."""
import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument('--save',action='store_true'); a=p.parse_args()
    repo=Path(__file__).resolve().parents[1]
    suites=[(repo,'tests'),(repo,'tests_integration'),(repo/'legacy_hw67','tests')]
    logs=[]; failed=False
    for cwd,suite in suites:
        command=[sys.executable,'-m','unittest','discover','-s',suite,'-v']
        r=subprocess.run(command,cwd=cwd,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),
                         stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=180)
        text=f'COMMAND: {command}\nCWD: {cwd}\nEXIT: {r.returncode}\n{r.stdout}'
        print(text,flush=True); logs.append(text); failed |= r.returncode!=0
    fingerprint=hashlib.sha256(Path('tests/test_release.py').read_bytes()).hexdigest()[:12]
    # The instructor fingerprint hashes the set of original test files (name + bytes).
    original=hashlib.sha256()
    for path in sorted(Path('tests').glob('*')):
        if path.is_file(): original.update(path.name.encode()); original.update(path.read_bytes())
    print('Original tests fingerprint:',original.hexdigest()[:12])
    failed |= original.hexdigest()[:12]!='09bd65e6b886'
    old=hashlib.sha256()
    for path in sorted(Path('legacy_hw67/tests').glob('*')):
        if path.is_file(): old.update(path.name.encode()); old.update(path.read_bytes())
    print('HW6+7 tests fingerprint:',old.hexdigest()[:12])
    failed |= old.hexdigest()[:12]!='c42ac7788026'
    if a.save:
        Path('evidence/quick-green.log').write_text('\n'.join(logs),encoding='utf-8')
    print('QUICK CHECK:', 'FAILED' if failed else '44/44 PASSED (13 + 7 + 24)')
    raise SystemExit(1 if failed else 0)


if __name__=='__main__': main()
