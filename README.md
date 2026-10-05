# Glasses Tutor (software prototype)

Photo of a problem in, confirm what was read, then a step-by-step hint ladder out.
Subject-agnostic (maths, chemistry, physics, ...). Hints are written to fit a tiny
heads-up display: at most 90 characters, plain-text math.

## Run
    pip install -r requirements.txt
    ANTHROPIC_API_KEY=sk-... uvicorn server:app --port 8000   # real model
    MOCK=1 uvicorn server:app --port 8000                      # canned demo data, no key

Open http://localhost:8000. Keys: Space/→ next hint, ← back, A answer, C capture.
`CLAUDE_MODEL` overrides the model (default `claude-sonnet-5-5`).

## Flow
1. Capture (camera or upload) -> scan animation.
2. "I read: ..." confirmation. Fix it by typing the correction; it re-runs from text.
3. Hint ladder, one step per tap. The full answer only appears on request.
4. "Glasses HUD sim" shows hints in a 30-column, 3-line box; red outline = hint too long.

## Next
- Verify maths steps with SymPy before showing them.
- Eval set: 50 printed + handwritten problems, track read accuracy and hint quality.
- Port the HUD to a phone companion, then to a real monocular display module.
