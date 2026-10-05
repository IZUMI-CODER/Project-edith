import importlib
import sys
import types

import pytest


def fake_anthropic(monkeypatch, outputs):
    calls = []

    class Block:
        type = "tool_use"
        def __init__(self, i, inp): self.id, self.input = f"tu_{i}", inp

    class Client:
        def __init__(self): self.messages = self
        def create(self, **kw):
            calls.append(kw)
            return types.SimpleNamespace(content=[Block(len(calls), outputs[len(calls) - 1])])

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    return calls


def load(monkeypatch, **env):
    monkeypatch.delenv("MOCK", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("server", None)
    return importlib.import_module("server")


BASE = {"read_as": "∫ 2x e^(x²) dx", "subject": "Calculus", "concepts": [], "hints": ["a", "b", "c", "d"], "final_answer": "x"}
GOOD = {**BASE, "check": {"kind": "integral", "expr": "2*x*exp(x^2)", "result": "exp(x^2) + C"}}
BAD = {**BASE, "check": {"kind": "integral", "expr": "2*x*exp(x^2)", "result": "x^2*exp(x^2)"}}


def test_wrong_answer_is_retried_with_feedback(monkeypatch):
    calls = fake_anthropic(monkeypatch, [BAD, GOOD])
    srv = load(monkeypatch)
    out = srv.tutor(srv.TutorRequest(text="x"))
    assert out["verified"] == "pass" and len(calls) == 2
    last = calls[1]["messages"][-1]["content"][0]
    assert last["is_error"] and "FAILED" in last["content"]


def test_persistent_failure_is_flagged_not_hidden(monkeypatch):
    fake_anthropic(monkeypatch, [BAD, BAD])
    srv = load(monkeypatch)
    assert srv.tutor(srv.TutorRequest(text="x"))["verified"] == "fail"


def test_unverifiable_is_marked_skipped_without_retry(monkeypatch):
    calls = fake_anthropic(monkeypatch, [{**BASE, "check": {"kind": "none"}}])
    srv = load(monkeypatch)
    assert srv.tutor(srv.TutorRequest(text="x"))["verified"] == "skipped" and len(calls) == 1


def test_access_code(monkeypatch):
    fake_anthropic(monkeypatch, [GOOD])
    srv = load(monkeypatch, ACCESS_CODE="open-sesame")
    with pytest.raises(srv.HTTPException) as e:
        srv.tutor(srv.TutorRequest(text="x"), x_access_code="nope")
    assert e.value.status_code == 401
    assert srv.tutor(srv.TutorRequest(text="x"), x_access_code="open-sesame")["verified"] == "pass"
