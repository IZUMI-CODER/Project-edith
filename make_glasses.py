"""Build static/glasses.html (and the double-click copy docs/glasses-demo.html) from the template + samples.json."""
import json
from pathlib import Path

root = Path(__file__).parent
samples = json.dumps(json.loads((root / "static" / "samples.json").read_text()), ensure_ascii=False).replace("</", "<\\/")
html = (root / "static" / "glasses_template.html").read_text().replace("__SAMPLES__", samples)
(root / "static" / "glasses.html").write_text(html)
(root / "docs" / "glasses-demo.html").write_text(html)
print("built static/glasses.html and docs/glasses-demo.html")
