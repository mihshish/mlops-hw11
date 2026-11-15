"""Run the FastAPI implementation over real loopback sockets, no Kubernetes claim."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from lab11.client import attempt

@contextmanager
def serve(mode="fixed",valid=True):
    model=b'{"prefix":"SIMULATED","version":"A"}'
    with tempfile.TemporaryDirectory(prefix="mlops11-smoke-") as d:
        p=Path(d)/"model.json";p.write_bytes(model)
        with socket.socket() as s:
            s.bind(("127.0.0.1",0));port=s.getsockname()[1]
        env=dict(os.environ,POD_NAME="loopback-fixture",MODEL_VERSION="A",MODEL_PATH=str(p),
                 MODEL_SHA256=hashlib.sha256(model).hexdigest() if valid else "0"*64,
                 WARMUP_SECONDS="3",CHUNK_SECONDS=".025",PROBE_MODE=mode)
        with tempfile.TemporaryFile() as log:
            proc=subprocess.Popen([sys.executable,"-m","uvicorn","lab11.app:app","--port",str(port),
                                   "--log-level","warning"],env=env,stdout=log,stderr=log)
            try:
                for _ in range(180):
                    if proc.poll() is not None:
                        log.seek(0);raise AssertionError(log.read().decode("utf-8","replace"))
                    try:
                        if http(port,"/health")[0]==200:break
                    except URLError:pass
                    time.sleep(.05)
                else:raise AssertionError("health never came up")
                yield port
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(5)
                    except subprocess.TimeoutExpired: proc.kill();proc.wait(5)

def http(port,path):
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}",timeout=2) as r:return r.status,r.read()
    except HTTPError as e:return e.code,e.read()

def sent(port,marker,session):
    return attempt("127.0.0.1",port,"req",dict(session_id=session,prompt="continue",history=[marker],chunks=2),
                  time.monotonic(),0,"loopback")

class LocalService(unittest.TestCase):
    def test_fixed_probe_and_isolation(self):
        with serve() as port:
            self.assertEqual(http(port,"/ready")[0],503)
            self.assertEqual(sent(port,"a","A")["status"],503)
            for _ in range(100):
                if http(port,"/ready")[0]==200:break
                time.sleep(.05)
            self.assertEqual(http(port,"/ready")[0],200)
            self.assertEqual(http(port,"/startup")[0],200)
            a=sent(port,"FIRST_ONLY","A");b=sent(port,"SECOND_ONLY","B")
            self.assertEqual((a["outcome"],a["warmed"],a["version"],a["backend_mode"]),("completed","true","A","simulated"))
            self.assertIn("FIRST_ONLY",a["first_text"]);self.assertNotIn("SECOND_ONLY",a["first_text"])
            self.assertIn("SECOND_ONLY",b["first_text"]);self.assertNotIn("FIRST_ONLY",b["first_text"])
            self.assertNotEqual(a["request_id"],b["request_id"])
            self.assertIn(b'ml_ttfc_seconds_count 2.0',http(port,"/metrics")[1])
    def test_broken_probe_reproduces_cold_request(self):
        with serve("broken") as port:
            self.assertEqual(http(port,"/startup")[0],200)
            self.assertEqual(http(port,"/ready")[0],200)
            cold=sent(port,"marker","C")
            self.assertEqual((cold["warmed"],cold["outcome"]),("false","completed"))
    def test_tampered_artifact_never_becomes_ready(self):
        with serve(valid=False) as port:
            status,obj=http(port,"/ready")
            self.assertEqual(status,503)
            self.assertIsNone(json.loads(obj)["version"])
