# Glasses Tutor (software prototype)

Photo of a problem in, confirm what was read, then a step-by-step hint ladder out.
Subject-agnostic (maths, chemistry, physics, ...). Hints are written to fit a tiny
heads-up display: at most 90 characters, plain-text math.

## Run
    pip install -r requirements.txt
    ANTHROPIC_API_KEY=sk-... uvicorn server:app --port 8000   # real model
    MOCK=1 uvicorn server:app --port 8000                      # canned demo data, no key
    OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_MODEL=llama3.2-vision uvicorn server:app   # free, local (docs/FREE.md)
    # hosting it? also set ACCESS_CODE=... (see docs/PHONE.md)

Open http://localhost:8000. Keys: Space/→ next hint, ← back, A answer, C capture.
`CLAUDE_MODEL` overrides the model (default `claude-sonnet-5-5`).

## Flow
1. Capture (camera or upload) -> scan animation.
2. "I read: ..." confirmation. Fix it by typing the correction; it re-runs from text.
3. Hint ladder, one step per tap. The full answer only appears on request.
4. "Glasses HUD sim" shows hints in a 30-column, 3-line box; red outline = hint too long.

## Verification (SymPy)
The model also returns a machine-checkable `check` (integral, derivative, equation roots, limit, electron
count). `verify.py` re-derives it numerically (differentiates the antiderivative, substitutes the roots,
counts electrons and Pauli capacities). If it contradicts the model, the server retries once with the failure
fed back; the UI shows `✓ verified`, `⚠ check failed` or `unverified`. Model-written expressions are
whitelisted before parsing (never `eval`'d blindly).

## Tests
    pip install pytest && python -m pytest -q tests     # verifier + retry/auth logic, no API key needed
    python eval.py                                       # needs a running server + API key; see eval_images/README.md

## No paid key
`docs/FREE.md`: run it with a local Ollama vision model or a free Gemini tier. Same hint ladder, same SymPy check.

## Phone and hardware
See `docs/PHONE.md` (install as an app, HTTPS, access code) and `docs/HARDWARE.md` (camera sizing math,
phased build plan, non-negotiables).

## Next
- Eval set: 50 printed + handwritten problems, track read accuracy and hint quality.
- Port the HUD to a phone companion, then to a real monocular display module.
