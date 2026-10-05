"""Tablet server: Python standard library + SymPy only (no FastAPI/pydantic, which are painful on Android).

    python lite_server.py                    # this device only  -> http://localhost:8000
    python lite_server.py --host 0.0.0.0     # let glasses/phone on the same Wi-Fi/hotspot reach it

Endpoints
    POST /api/scan    raw JPEG/PNG bytes (Content-Type: image/*, optional X-Session) or JSON {"image_b64": ...}
    POST /api/solve   JSON {"text": "..."}        (typed problem, skips OCR)
    GET  /api/status  OCR backend + health
    GET  /            the auto-detect teleprompter page (static/)
    GET  /glasses     what the wearer sees: the world + a 30x3 green display, nothing else
No internet is used at any point. Set ACCESS_CODE=... to require the X-Access-Code header on /api/*.
"""
import argparse
import base64
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import engine
import llm
import offline

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8_000_000
ACCESS_CODE = os.environ.get("ACCESS_CODE")


class Handler(BaseHTTPRequestHandler):
    server_version = "LensTutor/0.2"

    def log_message(self, *a):
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if ACCESS_CODE and self.headers.get("X-Access-Code") != ACCESS_CODE:
            self.send_json(401, {"status": "error", "reason": "access code required"})
            return False
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            return self.send_json(200, {"engine": "offline", "ocr": offline.ocr_backend(), "llm": llm.describe(), "needs_code": bool(ACCESS_CODE)})
        if path in ("/glasses", "/glasses/"):
            path = "/glasses.html"
        rel = "index.html" if path in ("/", "") else path.removeprefix("/static/").lstrip("/")
        f = (STATIC / rel).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self.send_json(404, {"status": "error", "reason": "not found"})
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self.send_json(404, {"status": "error", "reason": "not found"})
        if not self.authorized():
            return None
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self.send_json(413, {"status": "error", "reason": "body missing or too large"})
        raw = self.rfile.read(n)
        sid = self.headers.get("X-Session", "default")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        try:
            if path == "/api/scan":
                if ctype.startswith("image/"):
                    image = raw
                else:
                    j = json.loads(raw)
                    sid = j.get("session", sid)
                    image = base64.b64decode(j["image_b64"])
                return self.send_json(200, engine.handle_frame(image, sid, force=self.headers.get("X-Force") == "1"))
            if path == "/api/solve":
                j = json.loads(raw)
                return self.send_json(200, engine.handle_text(str(j.get("text", "")), j.get("session", sid), force=True))
        except (ValueError, KeyError, TypeError) as e:
            return self.send_json(400, {"status": "error", "reason": f"bad request: {e}"})
        return self.send_json(404, {"status": "error", "reason": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Lens Tutor (offline) on http://{a.host}:{a.port}   OCR: {offline.ocr_backend() or 'NONE - install tesseract'}")
    print("Word problems / everything else: " + (f"language model {llm.describe()}" if llm.configured() else "NOT set up (see docs/LLM.md); only calculus, equations, limits and electron configs"))
    if a.host != "127.0.0.1" and not ACCESS_CODE:
        print("Note: reachable from your network with no access code. Set ACCESS_CODE=... if others share the Wi-Fi.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
