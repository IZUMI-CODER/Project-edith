"""Optional language-model fallback for what the rule-based solver can't do (word problems, physics, anything).

Works with any OpenAI-compatible chat endpoint using only the standard library, so it runs with a free local model:
    LLM_URL=http://localhost:11434/v1   LLM_MODEL=qwen2.5:7b      (Ollama)
Optional: LLM_KEY (hosted services), LLM_TIMEOUT (seconds, default 240).
The model's answer is shown as 'unverified': unlike the SymPy path, nothing re-checks it.
"""
import json
import os
import re
import urllib.error
import urllib.request

SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
MAX_LINES = 60

SYSTEM = (
    "You are the solver behind smart glasses with a tiny teleprompter display. You are given text read from a page by OCR "
    "(it may contain typos, extra headings or a second question). Reply with the complete worked solution of the FIRST question only.\n"
    "Rules:\n"
    "- Output ONLY plain text lines. No preamble, no markdown, no LaTeX, no bullet symbols, no code fences.\n"
    "- One short step per line, at most 70 characters.\n"
    "- Write maths in plain linear notation: x², √x, ∫, π, e^(x²), a/b. Use × or · for multiplication.\n"
    "- First line: restate the problem as you understood it, starting with \"Read: \".\n"
    "- Then every step with its reason, naming the formula or law used.\n"
    "- Add a line starting \"Check: \" when you can verify the result (substitute back, units).\n"
    "- Last line: \"Answer: ...\" with the final result and units.\n"
    "- If there is no solvable question, output exactly one line: Read: nothing to solve"
)


class LLMError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("LLM_URL"))


def describe() -> str | None:
    return f"{os.environ.get('LLM_MODEL', '?')} @ {os.environ['LLM_URL']}" if configured() else None


def delatex(s: str) -> str:
    """Small models love LaTeX. Turn the common bits into plain text a 30-column display can show."""
    s = re.sub(r"\\[\[\]()]|\$\$|\$", "", s)
    for _ in range(3):                                            # nested fractions
        s = re.sub(r"\\d?frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", s)
    s = re.sub(r"\\text(?:bf|it|rm)?\{([^{}]*)\}", r"\1", s)
    for a, b in (("\\times", "×"), ("\\cdot", "·"), ("\\pi", "π"), ("\\theta", "θ"), ("\\leq", "≤"), ("\\geq", "≥"), ("\\neq", "≠"),
                 ("\\approx", "≈"), ("\\rightarrow", "→"), ("\\to", "→"), ("\\%", "%"), ("\\,", " "), ("\\left", ""), ("\\right", ""),
                 ("\\Delta", "Δ"), ("\\alpha", "α"), ("\\beta", "β"), ("\\mu", "μ"), ("\\omega", "ω"), ("\\lambda", "λ"), ("\\circ", "°")):
        s = s.replace(a, b)
    s = re.sub(r"\^\{?(-?\d+)\}?", lambda m: m.group(1).translate(SUP), s)
    s = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", s)
    s = re.sub(r"_\{?(\d+)\}?", lambda m: m.group(1).translate(SUB), s)
    s = re.sub(r"\\(?:q?quad|[;!:, ])", " ", s)
    return s.replace("{", "").replace("}", "")


def clean_lines(raw: str) -> list:
    out = []
    for line in delatex(raw).splitlines():
        t = re.sub(r"\*\*|__|`", "", line)
        t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t)
        t = re.sub(r" {2,}", " ", re.sub(r"^#+\s*", "", t)).strip()
        if not t or t.startswith("```"):
            continue
        while len(t) > 90:                                        # split very long lines at a space
            cut = t.rfind(" ", 0, 90)
            cut = cut if cut > 30 else 90
            out.append(t[:cut].strip())
            t = t[cut:].strip()
        out.append(t)
    return out[:MAX_LINES]


def solve(text: str) -> dict:
    if not configured():
        raise LLMError("no language model configured")
    base = os.environ["LLM_URL"].rstrip("/")
    body = {"model": os.environ.get("LLM_MODEL", "qwen2.5:7b"), "temperature": 0.1, "max_tokens": 1200,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Text read from the page:\n" + text[:4000]}]}
    headers = {"Content-Type": "application/json"}
    if os.environ.get("LLM_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LLM_KEY"]
    req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=float(os.environ.get("LLM_TIMEOUT", "240"))) as r:
            raw = json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise LLMError(f"model server said {e.code}: {e.read()[:160].decode(errors='replace')}")
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as e:
        raise LLMError(f"couldn't reach the model at {base} ({type(e).__name__}). Is it running?")
    lines = clean_lines(raw)
    if not lines:
        raise LLMError("the model returned nothing")
    if re.match(r"Read:\s*nothing to solve", lines[0], re.I):
        raise LLMError("nothing to solve")
    if not any(re.match(r"Answer\b", l, re.I) for l in lines):
        lines.append("Answer: " + lines[-1])
    read = re.sub(r"^Read:\s*", "", lines[0], flags=re.I) if re.match(r"Read:", lines[0], re.I) else text.strip().splitlines()[0]
    answer = next((re.sub(r"^Answer:?\s*", "", l, flags=re.I) for l in reversed(lines) if re.match(r"Answer\b", l, re.I)), lines[-1])
    return {"read_as": read[:200], "steps": lines, "final_answer": answer}
