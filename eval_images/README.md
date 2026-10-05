# Your handwriting test set

Goal: 20-30 photos of YOUR handwriting and YOUR textbook pages across the subjects you care about.

How to shoot:
- Phone held ~30-40 cm above the page, page flat, in daylight or a bright lamp. No shadow of your hand.
- One problem per photo. Fill most of the frame. Hold still.
- Mix: neat, messy, pencil, pen, printed textbook, photocopy, slightly angled, dim light.
- Include 3-4 deliberately ambiguous ones (a 2 that looks like a z, "x" vs "×") to test the read-back.

Then copy `cases.example.json` to `cases.json`, list each photo with a couple of tokens the read-back
must contain and a token the final answer must contain, and run `python eval.py`.
Photos stay on your machine (`*.jpg` is git-ignored).
