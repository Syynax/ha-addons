"""Minimaler GitHub-Contents-API-Mock für lokale Tests."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LATEST = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Morgenbriefing 30.09.2026</title></head>
<body><h1>Morgenbriefing</h1><p>Test <a href="https://example.org" target="_blank">Quelle</a></p><script>alert(1)</script></body></html>"""
FILES = {"latest.html": LATEST, "summary.txt": "Drei Sätze. Zweiter Satz. Dritter Satz.",
         "archive/2026-09-29.html": LATEST.replace("30.09", "29.09"),
         "archive/2026-09-30.html": LATEST}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split("?")[0]
        prefix = "/repos/test/repo/contents/"
        if not path.startswith(prefix):
            self.send_response(404); self.end_headers(); return
        name = path[len(prefix):]
        etag = '"v1"'
        if self.headers.get("If-None-Match") == etag and name in FILES:
            self.send_response(304); self.end_headers(); return
        if name == "archive":
            body = json.dumps([{"name": n.split("/")[1], "type": "file"} for n in FILES if n.startswith("archive/")]).encode()
            ctype = "application/json"
        elif name in FILES:
            body = FILES[name].encode(); ctype = "text/plain"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("ETag", etag)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
