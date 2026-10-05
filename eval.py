"""Eval harness: renders problems to images, sends them to the running server, checks the output.

    uvicorn server:app --port 8000 &        # with ANTHROPIC_API_KEY set
    python eval.py [--url http://localhost:8000] [--text]   # --text skips the image step

Checks per case: read-back contains expected tokens, 4-7 hints, every hint <= 90 chars,
the final answer is not leaked into the hints, and the final answer contains the expected token.
Add your own handwritten photos by dropping .jpg files in eval_images/ named like case ids.
"""
import argparse, base64, io, json, sys, urllib.request
from pathlib import Path

CASES = [
    # id, problem text, tokens expected in read_as, token expected in final_answer
    ("int_sub", "∫ 2x·e^(x²) dx", ["2x", "e"], "e^(x²)+C"),
    ("int_nonelem", "∫ e^(x²) dx", ["e"], "erf"),
    ("deriv_chain", "d/dx [ sin(x³) ]", ["sin"], "3x²"),
    ("limit", "lim x→0 of sin(x)/x", ["sin"], "1"),
    ("quadratic", "Solve x² - 5x + 6 = 0", ["x²", "6"], "3"),
    ("config_fe", "Write the electron configuration of Fe (Z=26).", ["Fe"], "3d⁶"),
    ("config_cr", "Write the electron configuration of Cr (Z=24).", ["Cr"], "4s¹"),
    ("projectile", "A ball is thrown at 20 m/s at 30° above horizontal. Find the time of flight (g = 9.8).", ["20", "30"], "2.04"),
    ("stoich", "How many moles are in 36 g of H2O? (M = 18 g/mol)", ["36"], "2"),
    ("logic", "If all A are B, and some B are C, must some A be C?", ["A", "B", "C"], "no"),
]


def post(url, body):
    req = urllib.request.Request(url + "/api/tutor", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def render(text):
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf", "Arial.ttf"):
        try:
            font = ImageFont.truetype(p, 34); break
        except OSError:
            pass
    img = Image.new("RGB", (1000, 260), "white"); ImageDraw.Draw(img).multiline_text((30, 40), text, fill="black", font=font)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90); return base64.b64encode(buf.getvalue()).decode()


def norm(s): return s.lower().replace(" ", "")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--url", default="http://localhost:8000"); ap.add_argument("--text", action="store_true")
    a = ap.parse_args(); passed = 0
    for cid, text, read_tok, ans_tok in CASES:
        body = {"text": text} if a.text else {"image_b64": render(text), "media_type": "image/jpeg"}
        try:
            d = post(a.url, body)
        except Exception as e:
            print(f"{cid:12} ERROR {e}"); continue
        hints = d.get("hints", [])
        fails = []
        if not all(norm(t) in norm(d.get("read_as", "")) for t in read_tok): fails.append(f"read_as={d.get('read_as')!r}")
        if not 4 <= len(hints) <= 7: fails.append(f"{len(hints)} hints")
        long = [h for h in hints if len(h) > 90]
        if long: fails.append(f"{len(long)} hint(s) > 90 chars")
        if any(norm(ans_tok) in norm(h) and len(ans_tok) > 2 for h in hints): fails.append("answer leaked in hints")
        if norm(ans_tok) not in norm(d.get("final_answer", "")): fails.append(f"answer lacks {ans_tok!r}")
        passed += not fails
        print(f"{cid:12} {'PASS' if not fails else 'FAIL ' + '; '.join(fails)}")
    print(f"\n{passed}/{len(CASES)} passed" + ("  (mock server: failures expected)" if d.get("mock") else ""))
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
