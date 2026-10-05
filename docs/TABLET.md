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

## 4. Display behaviour
- Teleprompter types the solution at ~40 characters/second and scrolls on its own. Space = pause, ↑/↓ = speed, R = replay, Esc = clear.
- "Glasses view" (key `g`) shows exactly what a 30-column, 3-line display would show.
- Type / Upload buttons exist for when OCR misreads (handwriting especially) or there's no camera.

## 5. Limits (same as the offline solver)
Integrals, derivatives, single-variable equations, limits and electron configurations only. Word problems, physics and
stoichiometry say "can't solve this type yet". If your terminal already has chemistry packages (`pip list | grep -i -E
"chem|mendeleev|periodictable"`), tell me which and I'll use them for molar mass, moles and equation balancing.
