# Glasses Tutor (software prototype)

**Auto mode (`lite_server.py`):** continuous camera, detects when you hold still on a problem, solves it offline and types the full
worked solution as a self-scrolling teleprompter. **Tutor mode (`server.py`):** capture, confirm, hint ladder.

Photo of a problem in, confirm what was read, then a step-by-step hint ladder out.
Subject-agnostic (maths, chemistry, physics, ...). Hints are written to fit a tiny
heads-up display: at most 90 characters, plain-text math.

## Run
**On the tablet / any device, fully offline (recommended):** see `docs/TABLET.md`.

    pip install sympy                      # + `pkg install tesseract` on Termux, or `pip install rapidocr-onnxruntime` on a PC
    python lite_server.py                  # http://localhost:8000: point the camera, hold still, it solves and scrolls the solution

**Word problems (free, local model):** see `docs/LLM.md`.

**Glasses-only view:** `http://localhost:8000/glasses` (or double-click `docs/glasses-demo.html`).

**PC with model backends (hints/tutor mode, optional):** `pip install -r requirements.txt`, then
`uvicorn server:app --port 8000` and open `/` (tutor page). Set `ANTHROPIC_API_KEY` or `OPENAI_BASE_URL` for a model;
with neither, the same offline solver runs. `MOCK=1` serves canned demo data.

## Tutor-mode flow (`server.py`)
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
With no key set, the built-in offline solver runs (OCR + SymPy; calculus, equations, limits, electron configs).
`docs/FREE.md` also covers a local Ollama vision model or a free Gemini tier for everything else.

## Phone and hardware
See `docs/PHONE.md` (install as an app, HTTPS, access code) and `docs/HARDWARE.md` (camera sizing math,
phased build plan, non-negotiables).

## Next
- Eval set: 50 printed + handwritten problems, track read accuracy and hint quality.
- Port the HUD to a phone companion, then to a real monocular display module.
