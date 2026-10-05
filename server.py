"""Glasses Tutor backend: photo (or text) in -> read-back + hint ladder out.

Run:  ANTHROPIC_API_KEY=... uvicorn server:app --port 8000
Without a key (or with MOCK=1) it serves canned examples so the UI works offline.
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
MOCK = os.environ.get("MOCK") == "1" or not os.environ.get("ANTHROPIC_API_KEY")
MAX_IMAGE_B64 = 7_000_000  # ~5 MB of image data

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
    },
}


class TutorRequest(BaseModel):
    image_b64: str | None = None
    media_type: str = "image/jpeg"
    text: str | None = None  # corrected transcription, skips the image


def mock_response(req: TutorRequest) -> dict:
    t = (req.text or "").lower()
    if any(k in t for k in ("electron", "config", "fe ", "aufbau")):
        return MOCKS["config"]
    return MOCKS["integral"]


def real_response(req: TutorRequest) -> dict:
    import anthropic

    content: list[dict] = []
    if req.text:
        content.append({"type": "text", "text": f"Problem (user-corrected transcription):\n{req.text}"})
    elif req.image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": req.media_type, "data": req.image_b64}})
        content.append({"type": "text", "text": "Read the problem in this image and build the hint ladder."})
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "tutor_response"},
        messages=[{"role": "user", "content": content}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise HTTPException(502, "model returned no structured answer")


app = FastAPI()


@app.post("/api/tutor")
def tutor(req: TutorRequest):
    if not req.text and not req.image_b64:
        raise HTTPException(400, "send image_b64 or text")
    if req.image_b64 and len(req.image_b64) > MAX_IMAGE_B64:
        raise HTTPException(413, "image too large")
    data = mock_response(req) if MOCK else real_response(req)
    return {**data, "mock": MOCK, "model": None if MOCK else MODEL}


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
