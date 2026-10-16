"""Disposable test app: serves /health. --crash-after N makes it exit(1) after N seconds (crash-loop demo)."""
import sys, time, threading, argparse
from http.server import BaseHTTPRequestHandler, HTTPServer

p = argparse.ArgumentParser()
p.add_argument("--port", type=int, default=8101)
p.add_argument("--crash-after", type=float, default=0)
a = p.parse_args()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404); self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *x): pass

if a.crash_after:
    threading.Timer(a.crash_after, lambda: __import__("os")._exit(1)).start()
HTTPServer(("127.0.0.1", a.port), H).serve_forever()
