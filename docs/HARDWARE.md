# Hardware plan

Status: planning. Numbers marked (est.) are my derivations, not datasheet values; part names are
starting points to check against current datasheets, availability and prices before you rely on them.

## 1. What the camera really needs
Reading text takes far less than a "nice photo" camera.

| Target | Math | Result |
|---|---|---|
| 10 pt printed page, whole A4 width at 40 cm, 60° FOV | width = 2·40·tan30° = 46 cm; need ≥ ~10 px on a 1.8 mm x-height → 0.18 mm/px → ~2560 px wide | ~5 MP (est.) |
| A few lines of print or handwriting (3-4 mm x-height), ~40° FOV | ~29 cm wide at 40 cm → ~1000-1600 px wide | **2-3 MP** (est.) |

Conclusion: aim a narrower FOV at the reading area and a 2-3 MP sensor is enough. Smaller sensor =
smaller module. A 5 MP, ~1.1 µm-pixel sensor is ~3x2 mm of silicon (est.); with lens a footprint of
roughly 4x4 mm and ~3 mm height is plausible (est.). Fixed focus set for 25-80 cm drops the
autofocus actuator, the biggest size cost. Compare candidate modules' datasheet footprint against the
Ray-Ban Meta camera (measure a teardown photo for your "2x smaller" baseline).

## 2. System
```
camera -> glasses MCU/SoC (JPEG, BLE) -> phone app (this repo's web UI/API client)
       -> server.py -> Claude + SymPy check -> hint text -> BLE -> glasses display
```
The glasses stay dumb: capture, compress, show text. All thinking happens off-device, which keeps
power and heat down.

## 3. Build in phases (cheapest first)
| Phase | What | Why |
|---|---|---|
| 0 | Web app on phone (done) | Proves the AI side |
| 1 | Open developer glasses with camera + tiny display, e.g. **Brilliant Labs Frame** (check current specs/SDK/price) | Real glasses, BLE, scripting SDK. Phone relays photo to `/api/tutor` and sends hint text back to the display |
| 2 | Custom 3D-printed or modified frame: your small camera module + a monocular micro-LED/waveguide display module, dev boards in the temples | Test look, weight, balance, thermals |
| 3 | Custom flex PCBs, battery in the temples, charging case | The Stark-looking, normal-looking version |

Display options to evaluate in Phase 2: monochrome green micro-LED + waveguide (the lowest-power, least
visible-from-outside approach; the idea behind Even Realities G1-class glasses, which have no camera),
or micro-OLED + prism/birdbath (brighter, bulkier). Hints are written to fit ~3 lines x 30 chars.

## 4. Looking like normal glasses
- Light leakage ("eye glow") is the tell: use waveguide out-coupling that sends light to the eye, polarizers,
  adaptive brightness.
- Put boards and 150-250 mAh cells in the temples; target under ~45 g (est.).
- Camera in the bridge or hinge as a design detail. Use fixed-focus, capture-on-tap (never continuous).
- Prescription: plan for lens inserts from day one.

## 5. Rough power budget (est., to be measured)
Capture-on-demand + BLE bursts + display on for tens of seconds per problem is realistic for hours of
study use. Always-on video or continuous display is not. Measure with a power profiler in Phase 1.

## 6. Non-negotiables
- **Visible capture indicator.** A small LED that lights whenever the camera captures. No covert recording.
  Many jurisdictions require it and bystanders deserve it.
- **No exam use.** In a closed-book exam this is cheating. Position and market it as a study and
  accessibility tool (dyslexia, low vision, labs, open-book work).
- Certification (FCC/CE, battery, eye safety for the display) before selling anything.
