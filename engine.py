"""Scan engine: frame in -> 'nothing' | 'unsupported' | 'same' | 'solved'. No web framework, no network.

The glasses (or the browser test client) only send a frame once the wearer's head has been still for a moment.
Everything else (OCR, solving, "is this the problem I already solved?") happens here, on the tablet.
"""
import difflib
import re
import threading
import time
from pathlib import Path

import llm
import offline

SAME_THRESHOLD = 0.9
SAVE_LAST = True      # keep the newest frame as last_scan.jpg so you can see exactly what the camera sent
LAST_FILE = Path(__file__).parent / "last_scan.jpg"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+\-*/^=()∫]", "", s.lower())


def looks_like_question(text: str) -> bool:
    """Only spend a model call on text that reads like a question, not a poster or a shopping list."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    if len(words) < 8:
        return False
    return bool("?" in text or re.search(r"\d", text) or
                re.search(r"\b(find|calculate|determine|what|how|why|explain|solve|prove|show|compute|given|suppose|if)\b", text, re.I))


class Session:
    def __init__(self):
        self.last_key = ""
        self.last_llm_key = ""
        self.lock = threading.Lock()


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def session(sid: str) -> Session:
    with _sessions_lock:
        if len(_sessions) > 64:
            _sessions.clear()
        return _sessions.setdefault(sid or "default", Session())


def present(res: dict) -> dict:
    return {"status": "solved", "read_as": res["read_as"], "subject": res["subject"], "steps": res["steps"],
            "answer": res["final_answer"], "verified": res["verified"], "verify_note": res["verify_note"],
            "note": res.get("ambiguity_note", "")}


def handle_text(text: str, sid: str = "default", force: bool = False) -> dict:
    """Solve already-read text. Returns the same statuses as a scan."""
    sess = session(sid)
    if not text.strip():
        return {"status": "nothing"}
    res = offline.solve_text(text)
    if not res["ok"] and llm.configured() and looks_like_question(text):
        key = norm(text)[:300]
        if not force and sess.last_llm_key and difflib.SequenceMatcher(None, key, sess.last_llm_key).ratio() >= SAME_THRESHOLD:
            return {"status": "same"}
        try:
            out = llm.solve(text)
        except llm.LLMError as e:
            return {"status": "unsupported", "read": res["read"][:300], "reason": f"language model: {e}"}
        sess.last_llm_key = key
        sess.last_key = norm(out["read_as"])
        return present({"read_as": out["read_as"], "subject": "AI", "steps": out["steps"], "final_answer": out["final_answer"],
                        "verified": "unverified", "verify_note": "solved by a language model; not re-checked", "ambiguity_note": ""})
    if not res["ok"]:
        return {"status": "unsupported", "read": res["read"][:300], "reason": res["reason"]}
    key = norm(res["read_as"])
    if not force and sess.last_key and difflib.SequenceMatcher(None, key, sess.last_key).ratio() >= SAME_THRESHOLD:
        return {"status": "same"}
    sess.last_key = key
    return present(res)


def handle_frame(image: bytes, sid: str = "default", force: bool = False) -> dict:
    sess = session(sid)
    if not sess.lock.acquire(blocking=False):
        return {"status": "busy"}
    t0 = time.time()
    try:
        if SAVE_LAST:
            try:
                LAST_FILE.write_bytes(image)
            except OSError:
                pass
        try:
            text = offline.ocr(image)
        except offline.OCRUnavailable as e:
            return {"status": "error", "reason": str(e)}
        res = handle_text(text, sid, force)
        res["ocr"] = text[:300]
        # ascii() so a Windows console never chokes on symbols like the integral sign
        print(f"[scan {1000 * (time.time() - t0):5.0f} ms] {res['status']:<11} {len(image) // 1024} KB  ocr={ascii(text[:140])}", flush=True)
        return res
    finally:
        sess.lock.release()
