"""Glasses Tutor backend: photo (or text) in -> read-back + hint ladder out.

Run:  ANTHROPIC_API_KEY=... uvicorn server:app --port 8000
Backends (first match wins):
  MOCK=1                      canned examples, no model
  ANTHROPIC_API_KEY set       Anthropic API (paid)
  OPENAI_BASE_URL set         any OpenAI-compatible vision endpoint: local Ollama (free) or a free hosted tier
  otherwise                   mock
"""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from verify import verify

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
if os.environ.get("MOCK") == "1":
    PROVIDER = "mock"
elif os.environ.get("ANTHROPIC_API_KEY"):
    PROVIDER = "anthropic"
elif os.environ.get("OPENAI_BASE_URL"):
    PROVIDER = "openai"
else:
    PROVIDER = "mock"
MOCK = PROVIDER == "mock"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "llama3.2-vision")
MAX_IMAGE_B64 = 7_000_000  # ~5 MB of image data
ACCESS_CODE = os.environ.get("ACCESS_CODE")  # set when hosting, so strangers cannot spend your API credit

HERE = Path(__file__).parent

SYSTEM = """You are the reasoning core of a pair of smart glasses that act as a tutor.
The user looks at a problem (any subject: maths, chemistry, physics, biology, \
programming, languages, economics, logic, ...) and you help them solve it themselves.

Rules:
- Transcribe the problem exactly as you read it in plain-text linear notation \
(e.g. "∫ 2x·e^(x²) dx"). If the writing is ambiguous, pick the most likely reading and \
describe the main alternative in `ambiguity_note`. If a reading has a very different \
answer (e.g. no closed form), say so there.
- Never give the final answer in `hints`. Hints form a ladder: first recognise the \
problem type, then the method, then one small step at a time, ending with a way for \
the student to check their own result.
- Each hint is for a tiny heads-up display: at most 90 characters, plain text, \
linear math (x², √x, a/b), no LaTeX, no markdown.
- 4 to 7 hints. Each should be actionable ("Let u = x². Find du.") not vague.
- `concepts`: the named rules/principles/theorems involved (e.g. Aufbau, Pauli \
exclusion, Hund's rule, u-substitution), each with a one-line meaning of at most 60 \
characters. Include known exceptions the student should watch for (e.g. Cr and Cu).
- `final_answer` holds the complete worked result; it is only shown if the user asks.
- `check`: when the answer is machine-checkable, fill it so the server can verify you. \
Use ASCII SymPy syntax: x^2, exp(x), sqrt(x), sin(x), pi, implicit multiplication ok. \
Kinds: integral (expr = integrand, result = antiderivative, e.g. "exp(x^2) + C"), \
derivative (expr, result), equation (expr = "lhs = rhs", result = comma-separated roots), \
limit (expr, point, result), electron_count (z, optional charge, config like "[Ar] 4s2 3d6"). \
Use kind "none" if nothing fits, if the integral is non-elementary, or if you are unsure.
- If the image has no readable problem, set `read_as` to "" and explain in \
`ambiguity_note`, with an empty `hints` list.
"""

TOOL = {
    "name": "tutor_response",
    "description": "Return the transcription and the hint ladder.",
    "input_schema": {
        "type": "object",
        "properties": {
            "read_as": {"type": "string"},
            "subject": {"type": "string"},
            "ambiguity_note": {"type": "string"},
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "meaning": {"type": "string"},
                    },
                    "required": ["name", "meaning"],
                },
            },
            "hints": {"type": "array", "items": {"type": "string"}},
            "final_answer": {"type": "string"},
            "check": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["integral", "derivative", "equation", "limit", "electron_count", "none"]},
                    "expr": {"type": "string"},
                    "result": {"type": "string"},
                    "var": {"type": "string"},
                    "point": {"type": "string"},
                    "z": {"type": "integer"},
                    "charge": {"type": "integer"},
                    "config": {"type": "string"},
                },
                "required": ["kind"],
            },
        },
        "required": ["read_as", "subject", "concepts", "hints", "final_answer"],
    },
}

MOCKS = {
    "integral": {
        "read_as": "∫ 2x·e^(x²) dx",
        "subject": "Calculus",
        "ambiguity_note": "If it is really ∫ e^(x²) dx (no 2x), there is no elementary antiderivative.",
        "concepts": [
            {"name": "u-substitution", "meaning": "Reverse chain rule: swap an inner function for u."},
            {"name": "Chain rule", "meaning": "d/dx f(g(x)) = f'(g(x))·g'(x)"},
        ],
        "hints": [
            "Spot it: a function inside e^( ) and its derivative sitting outside.",
            "That pattern calls for u-substitution.",
            "Let u = x². What is du in terms of dx?",
            "Rewrite the whole integral using only u and du.",
            "Integrate e^u, then put x² back in for u.",
            "Check: differentiate your result. Do you get 2x·e^(x²)?",
        ],
        "final_answer": "u = x², du = 2x dx, so ∫ e^u du = e^u + C = e^(x²) + C.",
        "check": {"kind": "integral", "expr": "2*x*exp(x^2)", "result": "exp(x^2) + C"},
    },
    "config": {
        "read_as": "Write the electron configuration of Fe (Z = 26).",
        "subject": "Chemistry",
        "ambiguity_note": "",
        "concepts": [
            {"name": "Aufbau", "meaning": "Fill the lowest-energy orbitals first."},
            {"name": "Pauli exclusion", "meaning": "Max 2 electrons per orbital, opposite spins."},
            {"name": "Hund's rule", "meaning": "Fill degenerate orbitals singly before pairing."},
            {"name": "Exceptions", "meaning": "Cr and Cu promote a 4s electron into 3d."},
        ],
        "hints": [
            "Fe has Z = 26, so a neutral atom has 26 electrons to place.",
            "Aufbau order: 1s 2s 2p 3s 3p 4s 3d. Fill in that sequence.",
            "Pauli: each orbital holds 2 e⁻ max. s=2, p=6, d=10.",
            "Use the noble-gas core: which gas ends at Z = 18?",
            "Put the remaining 8 e⁻ into 4s first, then 3d.",
            "Hund: draw the 3d boxes. Which one gets the paired electron?",
        ],
        "final_answer": "Fe: [Ar] 4s² 3d⁶ (3d: one paired box, four unpaired, so 4 unpaired e⁻).",
        "check": {"kind": "electron_count", "z": 26, "config": "[Ar] 4s2 3d6"},
    },
}


class TutorRequest(BaseModel):
    image_b64: str | None = None
    media_type: str = "image/jpeg"
    text: str | None = None  # corrected transcription, skips the image


def mock_response(req: TutorRequest) -> dict:
    t = (req.text or "").lower()
    data = MOCKS["config"] if any(k in t for k in ("electron", "config", "fe ", "aufbau")) else MOCKS["integral"]
    r = verify(data.get("check"))
    return {**data, "verified": r["status"], "verify_note": r["note"]}


def real_response(req: TutorRequest) -> dict:
    import anthropic

    content: list[dict] = []
    if req.text:
        content.append({"type": "text", "text": f"Problem (user-corrected transcription):\n{req.text}"})
    elif req.image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": req.media_type, "data": req.image_b64}})
        content.append({"type": "text", "text": "Read the problem in this image and build the hint ladder."})
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": content}]
    data, result = None, {"status": "skipped", "note": ""}
    for attempt in range(2):  # one retry if our own check contradicts the model
        resp = client.messages.create(
            model=MODEL, max_tokens=2500, system=SYSTEM, tools=[TOOL],
            tool_choice={"type": "tool", "name": "tutor_response"}, messages=messages,
        )
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            raise HTTPException(502, "model returned no structured answer")
        data = block.input
        result = verify(data.get("check"))
        if result["status"] != "fail" or attempt == 1:
            break
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                "content": f"Independent verification FAILED: {result['note']}. Re-solve carefully, "
                           "then return corrected read_as/hints/final_answer/check."}]},
        ]
    return {**data, "verified": result["status"], "verify_note": result["note"]}


def parse_json_loose(text: str) -> dict:
    """Small/free models wrap JSON in prose or ``` fences; pull the first object out."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def normalize(d: dict) -> dict:
    """Coerce a possibly sloppy model reply into the shape the UI expects."""
    def s(v): return v if isinstance(v, str) else ("" if v is None else str(v))
    concepts = []
    for c in d.get("concepts") or []:
        if isinstance(c, dict):
            concepts.append({"name": s(c.get("name")), "meaning": s(c.get("meaning"))})
        else:
            concepts.append({"name": s(c), "meaning": ""})
    hints = d.get("hints") or []
    if isinstance(hints, str):
        hints = [h.strip(" -•\t") for h in hints.splitlines() if h.strip()]
    check = d.get("check")
    return {"read_as": s(d.get("read_as")), "subject": s(d.get("subject")) or "General",
            "ambiguity_note": s(d.get("ambiguity_note")), "concepts": concepts,
            "hints": [s(h) for h in hints], "final_answer": s(d.get("final_answer")),
            "check": check if isinstance(check, dict) else {"kind": "none"}}


def openai_chat(messages: list) -> str:
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    body = {"model": OPENAI_MODEL, "messages": messages, "temperature": 0.2,
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        base + "/chat/completions", json.dumps(body).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "none")})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"model server said {e.code}: {e.read()[:200].decode(errors='replace')}")
    except (urllib.error.URLError, KeyError, ValueError) as e:
        raise HTTPException(502, f"could not use model server at {base}: {e}")


def openai_response(req: TutorRequest) -> dict:
    system = SYSTEM + "\nReply with ONLY one JSON object (no prose, no code fences) matching this JSON schema:\n" \
        + json.dumps(TOOL["input_schema"])
    if req.text:
        user = [{"type": "text", "text": f"Problem (user-corrected transcription):\n{req.text}"}]
    else:
        user = [{"type": "text", "text": "Read the problem in this image and build the hint ladder."},
                {"type": "image_url", "image_url": {"url": f"data:{req.media_type};base64,{req.image_b64}"}}]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    data, result = None, {"status": "skipped", "note": ""}
    for attempt in range(2):
        raw = openai_chat(messages)
        try:
            data = normalize(parse_json_loose(raw))
            result = verify(data.get("check"))
            problem = f"Independent verification FAILED: {result['note']}. Re-solve carefully." if result["status"] == "fail" else None
        except (ValueError, TypeError) as e:
            data, result, problem = None, {"status": "skipped", "note": "unparseable reply"}, f"Your reply was not valid JSON ({e}). Reply with only the JSON object."
        if problem is None or attempt == 1:
            break
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": problem}]
    if data is None:
        raise HTTPException(502, "model did not return valid JSON; try a larger model")
    return {**data, "verified": result["status"], "verify_note": result["note"]}


app = FastAPI()


@app.post("/api/tutor")
def tutor(req: TutorRequest, x_access_code: str | None = Header(default=None)):
    if ACCESS_CODE and x_access_code != ACCESS_CODE:
        raise HTTPException(401, "access code required")
    if not req.text and not req.image_b64:
        raise HTTPException(400, "send image_b64 or text")
    if req.image_b64 and len(req.image_b64) > MAX_IMAGE_B64:
        raise HTTPException(413, "image too large")
    data = {"mock": mock_response, "anthropic": real_response, "openai": openai_response}[PROVIDER](req)
    return {**data, "mock": MOCK, "provider": PROVIDER,
            "model": {"mock": None, "anthropic": MODEL, "openai": OPENAI_MODEL}[PROVIDER]}


@app.get("/api/config")
def config():
    return {"needs_code": bool(ACCESS_CODE)}


@app.get("/sw.js")
def sw():
    return FileResponse(HERE / "static" / "sw.js", media_type="text/javascript")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
