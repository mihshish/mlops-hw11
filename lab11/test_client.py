"""Loopback transport tests, not Kubernetes evidence."""
import http.server
import json
import threading
import time
import unittest
from lab11.client import assignment, attempt

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        case=payload["prompt"]
        status=429 if case=="reject" else 200
        self.send_response(status)
        self.send_header("X-Request-ID","test-id")
        self.end_headers()
        if case=="reject":
            self.wfile.write(b'{"error":"queue full"}')
        else:
            self.wfile.write(b'{"kind":"chunk","index":1,"request_id":"test-id","text":"first","cache_hit":false}\n')
            if case=="done":
                self.wfile.write(b'{"kind":"done","chunks":1,"request_id":"test-id"}\n')

class ClientAccounting(unittest.TestCase):
    def setUp(self):
        self.server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
    def call(self,case):
        return attempt("127.0.0.1",self.server.server_port,"r1",dict(session_id="s",prompt=case,chunks=1),time.monotonic(),0,"test")
    def test_reject_counts_without_first_chunk(self):
        r=self.call("reject");self.assertEqual((r["status"],r["outcome"],r["chunks"]),(429,"rejected",0))
        self.assertIsNone(r["first_monotonic"])
    def test_http_200_without_done_is_aborted(self):
        r=self.call("abort");self.assertEqual((r["status"],r["outcome"],r["chunks"]),(200,"aborted",1))
        self.assertIsNotNone(r["ttfc_seconds"])
    def test_done_makes_one_chunk_complete(self):
        r=self.call("done");self.assertEqual(r["outcome"],"completed")
        self.assertEqual(r["inter_chunk_seconds"],[])
    def test_equal_and_80_percent_schedules(self):
        from collections import Counter
        self.assertEqual(Counter(assignment(i,"uniform") for i in range(60)),{0:15,1:15,2:15,3:15})
        self.assertEqual(Counter(assignment(i,"skew") for i in range(60)),{0:48,1:4,2:4,3:4})
