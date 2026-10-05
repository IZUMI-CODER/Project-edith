# Testing without paying

## Option 0: built-in offline solver (default, nothing to install or sign up for)
Run `uvicorn server:app --port 8000` with no key and no settings. It uses OCR (`pip install rapidocr-onnxruntime`,
models ship inside the package) to read a photo and SymPy plus rule-based hint generation to solve.

Honest scope: indefinite integrals (u-substitution / parts / standard forms, flags non-elementary ones),
derivatives (names the rule), single-variable equations, limits, and electron configurations (exceptions
like Cr/Cu/Pd/Au and ions like Fe2+, O2-). Word problems, physics, stoichiometry and "any question" are not
covered; the app says so instead of guessing. Every answer is re-checked numerically (`✓ verified`).
Printed text reads well; handwriting is weak, so use the confirm step and the **Type** button.
Measured here: 7/10 on the built-in eval through the image path (the 3 misses are word problems).

Options A and B below add a real vision model for everything else.

The server speaks the common OpenAI-style chat protocol, so any vision model that offers it works.
Set `OPENAI_BASE_URL` (and `OPENAI_MODEL`); leave `ANTHROPIC_API_KEY` unset.

Status: tested against a fake local server that returns messy replies (prose + code fences, wrong
maths, bad JSON). NOT yet tested against real Ollama/Gemini; the first real run may need small tweaks.
Check each provider's current model names, limits and terms; they change.

## Option A: fully local and free (Ollama)
Needs a reasonably modern computer (a vision model wants roughly 6-10 GB of RAM/VRAM).

    # install Ollama from ollama.com, then:
    ollama pull llama3.2-vision          # or a smaller one: qwen2.5vl:3b, gemma3:4b, minicpm-v
    OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_MODEL=llama3.2-vision \
      uvicorn server:app --port 8000

Nothing leaves your machine. Small local models read handwriting and write hints worse than big
hosted ones, so treat the result as a floor, not the ceiling. The SymPy check helps catch wrong maths.

## Option B: free hosted tier (Google AI Studio / Gemini)
Make a key at aistudio.google.com (no card needed last I knew; verify). Then:

    OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai \
    OPENAI_API_KEY=<your free key> OPENAI_MODEL=gemini-2.5-flash \
      uvicorn server:app --port 8000

Free tiers are rate-limited and may use your inputs to improve their products; don't send anything private.

## Then
    python -m pytest -q tests     # no model needed
    python eval.py                # 10 built-in problems + your photos in eval_images/
