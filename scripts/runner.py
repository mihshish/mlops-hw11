"""Bounded child execution: log to file, reap only children of this exact attempt.

Avoid PIPE/communicate hanging on Windows when an ephemeral server inherits
stdout and outlives the command after a timeout. No unrelated process is touched.
"""
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
import psutil


def capture(command,path,cwd=None,timeout=240):
    owned={}; deadline=time.monotonic()+timeout; expired=False
    with Path(path).open('w',encoding='utf-8') as stream:
        proc=subprocess.Popen(command,cwd=cwd,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),
                              stdout=stream,stderr=subprocess.STDOUT)
        try:
            while proc.poll() is None:
                try:
                    for child in psutil.Process(proc.pid).children(recursive=True):
                        owned[(child.pid,child.create_time())]=child
                except psutil.Error: pass
                if time.monotonic()>deadline:
                    expired=True; proc.terminate(); break
                time.sleep(.2)
        finally:
            for child in reversed(list(owned.values())):
                try:
                    if child.is_running(): child.terminate()
                except psutil.Error: pass
            _,alive=psutil.wait_procs(list(owned.values()),timeout=3)
            for child in alive:
                try: child.kill()
                except psutil.Error: pass
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
    output=Path(path).read_text(encoding='utf-8')
    if expired: raise TimeoutError(f'Child exceeded {timeout}s; log: {path}')
    return SimpleNamespace(returncode=proc.returncode,stdout=output)
