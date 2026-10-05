import http.client
import importlib.util
import json
import subprocess
import threading
from http.server import ThreadingHTTPServer

import pytest

import engine
import lite_server
import offline

INT = "∫ 2x·e^(x²) dx"


@pytest.fixture(autouse=True)
def fresh_sessions():
    engine._sessions.clear()


def fake_ocr(monkeypatch, *texts):
    it = iter(texts)
    monkeypatch.setattr(offline, "ocr", lambda image: next(it))


def test_new_then_same_then_different(monkeypatch):
    fake_ocr(monkeypatch, INT, INT, "∫ 2x·e^(x²) dx\n", "electron configuration of Cr")
    assert engine.handle_frame(b"x")["status"] == "solved"
    assert engine.handle_frame(b"x")["status"] == "same"
    assert engine.handle_frame(b"x")["status"] == "same"
    r = engine.handle_frame(b"x")
    assert r["status"] == "solved" and "Cr" in r["read_as"] and r["steps"][-1].startswith("Answer")


def test_slightly_noisy_rereads_do_not_retrigger(monkeypatch):
    fake_ocr(monkeypatch, INT, "∫ 2x·e^(x²) dx.", "∫ 2x e^(x²)  dx")
    assert engine.handle_frame(b"x")["status"] == "solved"
    assert engine.handle_frame(b"x")["status"] == "same"
    assert engine.handle_frame(b"x")["status"] == "same"


def test_statuses_nothing_unsupported_error(monkeypatch):
    fake_ocr(monkeypatch, "", "Lorem ipsum dolor sit amet")
    assert engine.handle_frame(b"x")["status"] == "nothing"
    assert engine.handle_frame(b"x")["status"] == "unsupported"

    def boom(image):
        raise offline.OCRUnavailable("no OCR installed")
    monkeypatch.setattr(offline, "ocr", boom)
    assert engine.handle_frame(b"x")["status"] == "error"


def test_busy_while_previous_frame_is_reading(monkeypatch):
    fake_ocr(monkeypatch, INT)
    sess = engine.session("s1")
    sess.lock.acquire()
    try:
        assert engine.handle_frame(b"x", "s1")["status"] == "busy"
    finally:
        sess.lock.release()


def test_problem_found_among_other_lines():
    page = "Homework 3\nQuestion 2 (5 marks)\n∫ 2x·e^(x²) dx\nShow all working"
    r = offline.solve_text(page)
    assert r["ok"] and "e^(x²)" in r["final_answer"]


def test_problem_split_over_two_lines():
    r = offline.solve_text("Write the electron\nconfiguration of Cr")
    assert r["ok"] and r["final_answer"].startswith("Cr: [Ar] 4s¹ 3d⁵")


def test_every_solution_ends_with_an_answer_line_and_fits():
    for p in ["∫ 2x·e^(x²) dx", "∫ x*cos(x) dx", "d/dx (x^2+1)/(x-3)", "d/dx sin(x^3)", "lim x->2 (x^2-4)/(x-2)",
              "Solve x² - 5x + 6 = 0", "electron configuration of Fe2+", "∫ e^(x²) dx"]:
        r = offline.solve_text(p)
        assert r["ok"] and len(r["steps"]) >= 3 and r["steps"][-1].startswith("Answer") or r["steps"][-1].startswith("Check"), p


def test_tesseract_backend_used_when_rapidocr_missing(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "rapidocr_onnxruntime" else real(n, *a))
    monkeypatch.setattr("shutil.which", lambda n: "/data/data/com.termux/files/usr/bin/tesseract")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="{ 2x·e~(x²) dx\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert offline.ocr_backend() == "tesseract"
    from PIL import Image
    import io
    buf = io.BytesIO(); Image.new("RGB", (50, 20), "white").save(buf, "PNG")
    assert offline.ocr(buf.getvalue()) == "∫ 2x·e^(x²) dx"          # repaired
    assert calls[0][0].endswith("tesseract") and "--psm" in calls[0]


def test_no_ocr_at_all_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(offline, "ocr_backend", lambda: None)
    with pytest.raises(offline.OCRUnavailable, match="tesseract"):
        offline.ocr(b"x")


# ---------------------------------------------------------------- real HTTP round trips
@pytest.fixture
def http_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), lite_server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


def call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    return r.status, data


def test_http_endpoints(monkeypatch, http_server):
    fake_ocr(monkeypatch, INT)
    s, b = call(http_server, "GET", "/")
    assert s == 200 and b"Lens" in b
    s, b = call(http_server, "GET", "/api/status")
    assert s == 200 and "ocr" in json.loads(b)
    s, b = call(http_server, "POST", "/api/solve", json.dumps({"text": "Solve 2x + 3 = 11"}), {"Content-Type": "application/json"})
    assert json.loads(b)["answer"] == "x = 4"
    s, b = call(http_server, "POST", "/api/scan", b"\xff\xd8fakejpeg", {"Content-Type": "image/jpeg", "X-Session": "t1"})
    assert json.loads(b)["status"] == "solved"
    s, b = call(http_server, "POST", "/api/scan", b"", {"Content-Type": "image/jpeg"})
    assert s == 413
    s, b = call(http_server, "POST", "/api/solve", b"not json", {"Content-Type": "application/json"})
    assert s == 400


def test_http_blocks_path_traversal_and_enforces_access_code(monkeypatch, http_server):
    for path in ("/static/../server.py", "/../engine.py", "/static/%2e%2e/offline.py"):
        s, _ = call(http_server, "GET", path)
        assert s == 404, path
    monkeypatch.setattr(lite_server, "ACCESS_CODE", "sesame")
    body = json.dumps({"text": "Solve 2x + 3 = 11"})
    assert call(http_server, "POST", "/api/solve", body, {"Content-Type": "application/json"})[0] == 401
    assert call(http_server, "POST", "/api/solve", body, {"Content-Type": "application/json", "X-Access-Code": "sesame"})[0] == 200


def test_glasses_page_is_served_and_built(http_server):
    s, b = call(http_server, "GET", "/glasses")
    assert s == 200 and b"Glasses view" in b and b"__SAMPLES__" not in b
    assert b"Integral, substitution" in b          # demo samples are embedded, so the file also works without a server
