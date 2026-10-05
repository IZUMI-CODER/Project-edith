# Running on the Samsung tablet (DeX), fully offline

```
glasses  ⇄  local link (tablet hotspot / same Wi-Fi, no internet)  ⇄  tablet terminal runs lite_server.py
  camera frame ───────────────────────────────►  OCR + solve + verify  (all on the tablet)
  teleprompter text  ◄─────────────────────────  worked solution, line by line
```
`lite_server.py` needs only Python's standard library plus SymPy. No FastAPI/pydantic (those need Rust to
compile on Android), no cloud, no key.

Status: written and tested on a Linux box with the real OCR; the Termux/Samsung steps below are NOT yet
tested on your tablet. Treat package names as starting points and tell me what errors you hit.

## 1. Install (Termux from F-Droid; the Play Store build is outdated)
    pkg update && pkg upgrade
    pkg install python git tesseract
    pkg install python-pillow            # optional: better OCR preprocessing
    pip install sympy
    git clone https://github.com/IZUMI-CODER/Project-edith && cd Project-edith
If `tesseract` complains about missing language data, run `pkg search tesseract` and install the English data package.

## 2. Run
    python lite_server.py                      # only this tablet: http://localhost:8000
    python lite_server.py --host 0.0.0.0       # glasses/phone can reach it too
Open `http://localhost:8000` in the tablet's browser (works in DeX; `localhost` counts as secure, so the camera is allowed).
Point the camera at a problem and hold still: it reads, solves and starts typing the worked solution by itself.

Keep Termux alive: run `termux-wake-lock`, and exclude Termux from battery optimisation in Android settings.

## 3. Connecting the glasses
Any device that can send an HTTP request works, so the glasses firmware only needs:

    POST http://<tablet-ip>:8000/api/scan      body = JPEG bytes, Content-Type: image/jpeg, header X-Session: glasses1
    -> {"status": "solved", "read_as": "...", "steps": ["Evaluate ...", "...", "Answer: ..."], "verified": "pass"}
    -> or {"status": "same" | "nothing" | "unsupported" | "busy"}

Find the tablet IP in Termux with `ifconfig` (`pkg install net-tools`). Easiest link with no internet: turn on the
tablet's hotspot and join the glasses to it.
The glasses decide WHEN to send: an IMU "head has been still for ~1 s" trigger is the hardware version of the
browser's stillness detector, and saves power because frames are only sent when something new is being looked at.
The server remembers the last problem per X-Session and answers `same` for re-reads, so the display doesn't restart.
Bluetooth LE instead of Wi-Fi would need a small bridge on the tablet; say if you want that.

## 3b. See exactly what the wearer sees
    python lite_server.py    ->   open  http://localhost:8000/glasses
The camera is the "room" and only a 30-column, 3-line green display floats in the lower-right of the lens (black is
transparent on a real additive display, so there is no box). Keys: space pause, up/down speed, r replay, t type a question,
b dark backing, f show the display area, h hide help. No server? Double-click `docs/glasses-demo.html`: same view with
sample problems (keys 1-9, 0). Simulation only: it can't show real optics, brightness or focus distance. Green on a bright
white page has weak contrast on real see-through displays; a tinted lens or a dark backing helps.

## If it doesn't detect a problem
Detection is automatic (hold still on a printed problem for ~2 s). To see why it isn't firing:
- Look at the window running `lite_server.py`: every scan prints a line with what the OCR read, e.g. `[scan 350 ms] solved ... ocr='...'`. No lines = the page never sent a frame; lines with garbage text = the camera image is blurry/dark/too small.
- `last_scan.jpg` (in the project folder) is the exact frame the camera last sent.
- On the page press `d` for a live panel: motion, stillness, sharpness, contrast, and the last OCR text.
- Tips: good light, the page flat and filling a third of the frame or more, hold the camera still for 2-3 seconds.

## 4. Display behaviour
- Teleprompter types the solution at ~40 characters/second and scrolls on its own. Space = pause, ↑/↓ = speed, R = replay, Esc = clear.
- "Glasses view" (key `g`) shows exactly what a 30-column, 3-line display would show.
- Type / Upload buttons exist for when OCR misreads (handwriting especially) or there's no camera.

## 5. Limits (same as the offline solver)
Integrals, derivatives, single-variable equations, limits and electron configurations only. Word problems, physics and
stoichiometry say "can't solve this type yet". If your terminal already has chemistry packages (`pip list | grep -i -E
"chem|mendeleev|periodictable"`), tell me which and I'll use them for molar mass, moles and equation balancing.
