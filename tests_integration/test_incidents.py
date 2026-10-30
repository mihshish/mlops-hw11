"""Same seven integration regressions run against original and repaired code.

LAB_IMPL selects an implementation directory, not different test expectations.
HTTP is TCP/localhost, CLI uses real child processes and isolated files.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

IMPL=Path(os.environ.get('LAB_IMPL',Path(__file__).resolve().parents[1])).resolve()


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


class IncidentRegression(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'stand'
        p=self.cli('init')
        self.assertEqual(p.returncode,0,p.stdout)

    def cli(self,*args):
        p=subprocess.run([sys.executable,str(IMPL/'lab.py'),'--workspace',str(self.root),*args],
                         cwd=IMPL,text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                         env=dict(os.environ,PYTHONUTF8='1'),timeout=30)
        print('CLI',list(args),'EXIT',p.returncode,'OUTPUT',p.stdout.strip(),flush=True)
        return p

    def put(self,name,value):
        (self.root/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')

    @contextmanager
    def server(self,warmup=0):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        log=tempfile.TemporaryFile(mode='w+b')
        proc=subprocess.Popen([sys.executable,str(IMPL/'service.py'),'--workspace',str(self.root),
                               '--port',str(port),'--warmup-seconds',str(warmup)],
                               cwd=IMPL,env=dict(os.environ,PYTHONUTF8='1'),stdout=log,stderr=log)
        self.url=f'http://127.0.0.1:{port}'
        try:
            for _ in range(150):
                if proc.poll() is not None:
                    log.seek(0); self.fail('Server exited: '+log.read().decode('utf-8',errors='replace'))
                try:
                    if self.http('/health')[0]==200: break
                except (OSError,urllib.error.URLError): pass
                time.sleep(.1)
            else: self.fail('Server did not become healthy')
            yield
        finally:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
            log.close()

    def http(self,path,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request(self.url+path,data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=10) as r: status,body=r.status,r.read()
        except urllib.error.HTTPError as e: status,body=e.code,e.read()
        result=json.loads(body)
        print('HTTP',path,'STATUS',status,'BODY',result,flush=True)
        return status,result

    def ready(self):
        for _ in range(150):
            if self.http('/ready')[0]==200: return
            time.sleep(.1)
        self.fail('Warmup never completed')

    def test_01_cache_recovery_and_content_invalidation_subprocess(self):
        failed=self.cli('run','--fail-after-prepare')
        self.assertNotEqual(failed.returncode,0); self.assertIn('PREPARED',failed.stdout)
        recovered=self.cli('run'); self.assertEqual(recovered.returncode,0,recovered.stdout)
        self.assertIn('CACHE_HIT',recovered.stdout)
        (self.root/'input.txt').write_text('Changed input at the same path\n',encoding='utf-8')
        changed=self.cli('run'); self.assertEqual(changed.returncode,0,changed.stdout)
        self.assertIn('PREPARED',changed.stdout,'Same-path content change must invalidate cache')

    def test_02_incomplete_foreign_and_rejected_reports_subprocess(self):
        before=(self.root/'accepted.json').read_bytes()
        for report in ('report-incomplete.json','report-A.json','report-reject.json'):
            p=self.cli('run','--report',report)
            self.assertNotEqual(p.returncode,0,'Invalid/foreign report was admitted: '+report)
            self.assertEqual((self.root/'accepted.json').read_bytes(),before)

    def test_03_atomic_write_failure_subprocess(self):
        before=(self.root/'accepted.json').read_bytes()
        code="from pathlib import Path; from unittest.mock import patch; import lab; " \
             "root=Path(__import__('sys').argv[1]); " \
             "m=lab.read(root/'manifest-B.json'); r=lab.read(root/'report-B.json'); " \
             "p=patch('os.replace',side_effect=OSError('injected replacement failure')); p.start(); " \
             "lab.release.publish(m,r,root/'accepted.json')"
        p=subprocess.run([sys.executable,'-c',code,str(self.root)],cwd=IMPL,capture_output=True,text=True,timeout=30)
        print('ATOMIC_REPLACE_EXIT',p.returncode,p.stderr,flush=True)
        self.assertNotEqual(p.returncode,0,'Atomic replace was not used')
        self.assertIn('injected replacement failure',p.stderr)
        self.assertEqual((self.root/'accepted.json').read_bytes(),before)
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_04_repeated_publication_subprocess(self):
        for _ in range(2): self.assertEqual(self.cli('run').returncode,0)
        events=[json.loads(s) for s in (self.root/'publications.jsonl').read_text().splitlines() if s]
        self.assertEqual(len(events),1,'Retry created duplicate actual publication events')

    def test_05_readiness_http(self):
        with self.server(warmup=2):
            self.assertEqual(self.http('/health')[0],200)
            self.assertEqual(self.http('/ready')[0],503,'Ready before warmup')
            self.assertEqual(self.http('/generate',{'prompt':'test','max_new_tokens':32})[0],503)
            self.assertEqual(self.http('/debug')[1]['calls'],0)
            self.ready()
            self.assertTrue(self.http('/debug')[1]['warmup_finished'])
            self.assertEqual(self.http('/generate',{'prompt':'test','max_new_tokens':32})[0],200)

    def test_06_loaded_version_http(self):
        with self.server():
            self.ready(); self.assertEqual(self.http('/generate',{'prompt':'test'})[1]['model_id'],'fixture-A')
            self.assertEqual(self.cli('run').returncode,0)
            body=self.http('/generate',{'prompt':'test'})[1]
            self.assertEqual(body['model_id'],'fixture-A','Advertised B but A remains loaded')
            self.assertIn('fixture-A',body['answer'])
        with self.server():
            self.ready(); body=self.http('/generate',{'prompt':'test'})[1]
            self.assertEqual(body['model_id'],'fixture-B'); self.assertIn('fixture-B',body['answer'])

    def test_07_invalid_request_http_without_backend_call(self):
        with self.server():
            self.ready(); before=self.http('/debug')[1]['calls']
            for payload in ({'prompt':''},{'prompt':'   '},{'prompt':'x','max_new_tokens':0},
                            {'prompt':'x','max_new_tokens':100000},{'prompt':'x','max_new_tokens':'32'},
                            {'prompt':'x','max_new_tokens':True},{'prompt':'x'*6001}):
                status,_=self.http('/generate',payload)
                self.assertTrue(400<=status<500,'Invalid request reached the backend')
                self.assertEqual(self.http('/debug')[1]['calls'],before)
            self.assertEqual(self.http('/generate',{'prompt':'valid','max_new_tokens':32})[0],200)
            self.assertEqual(self.http('/debug')[1]['calls'],before+1)


if __name__=='__main__': unittest.main(verbosity=2)
