import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import engine
import llm

WORD = ("A ball is thrown upward at 20 m/s from the ground. How long does it take to reach its highest point? Use g = 9.8 m/s².")
LATEX_REPLY = (r"Read: Time to top of a ball thrown up at 20 m/s" "\n"
               r"**Step 1:** At the top v = 0." "\n"
               r"- Use $v = u - g t$." "\n"
               r"\( t = \frac{u}{g} = \frac{20}{9.8} \)" "\n"
               r"t \approx 2.04 \text{ s}, \quad x^{2}" "\n"
               "Answer: 2.04 s")


@pytest.fixture
def model():
    seen, replies = [], []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            if not replies:
                self.send_response(500); self.end_headers(); self.wfile.write(b"boom"); return
            out = json.dumps({"choices": [{"message": {"content": replies.pop(0)}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", replies, seen
    srv.shutdown()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    engine._sessions.clear()
    monkeypatch.setattr(engine, "SAVE_LAST", False)
    monkeypatch.delenv("LLM_URL", raising=False)


def use(monkeypatch, url):
    monkeypatch.setenv("LLM_URL", url); monkeypatch.setenv("LLM_MODEL", "tiny")


def test_latex_is_turned_into_plain_text():
    lines = llm.clean_lines(LATEX_REPLY)
    assert lines[0].startswith("Read:") and "**" not in " ".join(lines) and "$" not in " ".join(lines)
    assert "t = (u)/(g) = (20)/(9.8)" in lines and any("t ≈ 2.04 s" in l and "x²" in l for l in lines)
    assert lines[-1] == "Answer: 2.04 s"


def test_word_problem_goes_to_the_model_once(monkeypatch, model):
    url, replies, seen = model; use(monkeypatch, url); replies.append(LATEX_REPLY)
    r = engine.handle_text(WORD)
    assert r["status"] == "solved" and r["answer"] == "2.04 s" and r["verified"] == "unverified" and r["subject"] == "AI"
    assert seen[0]["model"] == "tiny" and WORD[:30] in seen[0]["messages"][1]["content"]
    # the same page re-read (with OCR jitter) must NOT call the model again
    assert engine.handle_text(WORD.replace("highest", "h1ghest"))["status"] == "same" and len(seen) == 1


def test_math_the_rules_can_solve_never_calls_the_model(monkeypatch, model):
    url, replies, seen = model; use(monkeypatch, url)
    assert engine.handle_text("∫ 2x·e^(x²) dx")["status"] == "solved" and not seen


def test_random_text_is_not_sent_to_the_model(monkeypatch, model):
    url, replies, seen = model; use(monkeypatch, url)
    assert engine.handle_text("Welcome to the library please be quiet")["status"] == "unsupported" and not seen


def test_model_down_is_reported_not_crashed(monkeypatch):
    use(monkeypatch, "http://127.0.0.1:9/v1")
    r = engine.handle_text(WORD)
    assert r["status"] == "unsupported" and "couldn't reach the model" in r["reason"]


def test_model_http_error_and_nothing_to_solve(monkeypatch, model):
    url, replies, seen = model; use(monkeypatch, url)
    assert "500" in engine.handle_text(WORD, force=True)["reason"]
    replies.append("Read: nothing to solve")
    assert "nothing to solve" in engine.handle_text(WORD, force=True)["reason"]


def test_without_a_model_word_problems_are_unsupported(monkeypatch):
    assert engine.handle_text(WORD)["status"] == "unsupported"
