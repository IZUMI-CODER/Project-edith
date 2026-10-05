# Word problems and everything else: a free local language model

The rule-based solver (instant, checked with SymPy) only does integrals, derivatives, single-variable equations, limits
and electron configurations. For long word problems, physics, chemistry calculations, anything else, the server can hand the
text to a language model running on your own laptop. Free, offline, no key.

Status: written and tested against a fake model server here. NOT yet tested with a real Ollama model (my sandbox can't
download one), so expect to tune the model choice for your laptop.

## Setup on Windows
1. Install Ollama from ollama.com (a normal installer). Open a new terminal afterwards.
2. Download a model (one time, several GB). Pick by your RAM:
       ollama pull qwen2.5:7b        # 16 GB RAM: best quality of the easy options
       ollama pull qwen2.5:3b        # 8 GB RAM: faster, makes more mistakes
3. In the Project-edith window, point the server at it, then start it (cmd syntax):
       set LLM_URL=http://localhost:11434/v1
       set LLM_MODEL=qwen2.5:7b
       python lite_server.py
   The first lines it prints should say `language model qwen2.5:7b @ http://localhost:11434/v1`.

## How it behaves
- Anything the rules can solve is solved instantly and shown as `verified`.
- Other text that reads like a question (at least 8 words, plus a digit, a "?" or a word like find/calculate/what) is sent to the
  model. Random text (posters, menus) is not.
- A word problem takes a while on a laptop CPU: expect roughly 10-60 seconds before the teleprompter starts. The page waits
  and then types the whole solution.
- The same page re-read by the camera does not ask the model again.
- Model answers are marked `unverified`: nothing re-checks them, and small models make arithmetic mistakes.
  Check the key steps, especially for graded work.
- If the model isn't running, the status says so instead of failing silently.

## Faster / better
Hosted models are faster and stronger, but need a key and cost money. `LLM_URL` and `LLM_KEY` accept any OpenAI-compatible
service; ask if you want that.
