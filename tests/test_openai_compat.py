import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

GOOD = {"read_as": "∫ 2x e^(x²) dx", "subject": "Calculus", "concepts": [{"name": "u-sub", "meaning": "swap inner fn"}],
        "hints": ["h1", "h2", "h3", "h4"], "final_answer": "e^(x²)+C",
        "check": {"kind": "integral", "expr": "2*x*exp(x^2)", "result": "exp(x^2)+C"}}
BAD = {**GOOD, "check": {"kind": "integral", "expr": "2*x*exp(x^2)", "result": "x^2"}}


@pytest.fixture
def fake_server():
    replies, seen = [], []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            out = json.dumps({"choices": [{"message": {"content": replies[len(seen) - 1]}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", replies, seen
    srv.shutdown()


def load(monkeypatch, base):
    monkeypatch.delenv("MOCK", raising=False); monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", base); monkeypatch.setenv("OPENAI_MODEL", "tiny-vl")
    sys.modules.pop("server", None)
    return importlib.import_module("server")


def test_fenced_json_in_prose_with_image(monkeypatch, fake_server):
    base, replies, seen = fake_server
    replies.append("Sure! Here you go:\n```json\n" + json.dumps(GOOD) + "\n```\nHope that helps.")
    srv = load(monkeypatch, base)
    out = srv.tutor(srv.TutorRequest(image_b64="QUJD"))
    assert srv.PROVIDER == "openai" and out["verified"] == "pass" and out["model"] == "tiny-vl"
    user = seen[0]["messages"][1]["content"]
    assert user[1]["image_url"]["url"].startswith("data:image/jpeg;base64,QUJD")
    assert seen[0]["response_format"] == {"type": "json_object"}


def test_wrong_math_is_retried_and_garbage_json_is_retried(monkeypatch, fake_server):
    base, replies, seen = fake_server
    replies += [json.dumps(BAD), "not json at all", json.dumps(GOOD)]
    srv = load(monkeypatch, base)
    # attempt 1 fails verification -> retry; attempt 2 is garbage -> but it is the last attempt
    with pytest.raises(srv.HTTPException):
        srv.tutor(srv.TutorRequest(text="x"))
    assert "FAILED" in seen[1]["messages"][-1]["content"]


def test_sloppy_shapes_are_normalized(monkeypatch, fake_server):
    base, replies, _ = fake_server
    replies.append(json.dumps({"read_as": "2+2", "hints": "- add them\n- check", "concepts": ["Addition"], "final_answer": 4}))
    srv = load(monkeypatch, base)
    out = srv.tutor(srv.TutorRequest(text="2+2"))
    assert out["hints"] == ["add them", "check"] and out["final_answer"] == "4"
    assert out["concepts"][0]["name"] == "Addition" and out["verified"] == "skipped"


def test_unreachable_server_gives_clear_error(monkeypatch):
    srv = load(monkeypatch, "http://127.0.0.1:9/v1")
    with pytest.raises(srv.HTTPException) as e:
        srv.tutor(srv.TutorRequest(text="x"))
    assert e.value.status_code == 502 and "could not use model server" in e.value.detail
