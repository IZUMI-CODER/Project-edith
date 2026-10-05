"""Scan engine: frame in -> 'nothing' | 'unsupported' | 'same' | 'solved'. No web framework, no network.

The glasses (or the browser test client) only send a frame once the wearer's head has been still for a moment.
Everything else (OCR, solving, "is this the problem I already solved?") happens here, on the tablet.
"""
import difflib
import re
import threading

import offline

SAME_THRESHOLD = 0.9


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+\-*/^=()∫]", "", s.lower())


class Session:
    def __init__(self):
        self.last_key = ""
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
    try:
        try:
            text = offline.ocr(image)
        except offline.OCRUnavailable as e:
            return {"status": "error", "reason": str(e)}
        return handle_text(text, sid, force)
    finally:
        sess.lock.release()
