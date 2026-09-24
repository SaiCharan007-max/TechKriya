# Drishti -- AI Street Navigation Assistant for the Visually Impaired

A laptop-based prototype that helps a blind pedestrian walk safely on a
street. A chest-mounted webcam watches the path; Drishti detects obstacles
and moving vehicles and speaks **only the most important instruction** into
the user's earphones (e.g. "Stop. Bike approaching.", "Chair ahead, 2
metres. Step left.").

This README covers the **core system** (see `CLAUDE.md` for the full spec,
including the scene-description and simulated-navigation stretch goals).

## 1. Setup

Requirements: Python 3.10+, a webcam (or a test video), and Windows, macOS
or Linux (Windows + laptop CPU is the primary target).

```bash
cd drishti
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

The first run downloads the YOLO11n weights (`yolo11n.pt`, ~5 MB) automatically.

Put 2-3 short first-person street-walking videos in `videos/` (chest-height,
20-60s) so you always have an offline backup demo.

## 2. Running

```bash
python main.py --source 0                       # webcam
python main.py --source videos/street1.mp4       # video file (loops at the end)
python main.py --source videos/street1.mp4 --debug   # print per-object distance/speed/TTC each second
```

### Controls (in the OpenCV window)
| Key | Action |
|-----|--------|
| `q` | quit |
| `m` | mute / unmute speech |
| `r` | repeat the last spoken message |
| `space` | pause / resume the video |
| `d` | scene description (stretch goal, not in the core build) |
| `n` | start simulated route (stretch goal, not in the core build) |

### What you should see and hear
- A window titled **Drishti**: your camera/video on the left with a
  translucent green walking-corridor overlay (turns red when the path is
  blocked), colour-coded detection boxes (green = far, orange = in your
  path, red = approaching or very close), and a dark side panel on the
  right showing FPS, a SAFE/CAUTION/DANGER badge, object counts, and a
  colour-coded decision log.
- Spoken alerts through your speakers/earphones for the single most
  important thing happening right now -- e.g. a bike closing in fast gets
  "Stop. Bike approaching ahead.", a stationary chair in your path gets
  "Chair ahead, 2 metres. Step left.". The same object will not be
  announced again within its cooldown window unless it becomes more
  dangerous.

## 3. Module overview

| File | Responsibility |
|------|-----------------|
| `config.py` | every tunable threshold (distances, cooldowns, colours, FPS target) |
| `vision.py` | YOLO11n detection + ByteTrack tracking, distance estimate, corridor zones, approach/closing-speed detection |
| `decision.py` | the priority engine: CRITICAL > OBSTACLE > NAVIGATION > INFO, with anti-chatter cooldowns |
| `speech.py` | background threaded TTS with a priority queue (SAPI / pyttsx3 / `say`) |
| `hud.py` | all drawing: corridor, boxes, banner, side panel, decision log |
| `main.py` | CLI, main loop, keyboard controls |

Each module has a self-test: run it directly, e.g. `python vision.py`,
`python decision.py`, `python speech.py`, `python hud.py`.

## 4. Troubleshooting

**"Could not open source"** -- check the webcam index (`0`, `1`, ...) or
that the video path is correct and the file exists.

**No sound / speech doesn't work** -- on Windows this uses SAPI via
`pywin32`, falling back to `pyttsx3`. If neither backend is available the
message is printed to the console (`[SPEECH] ...`) instead of crashing, so
the demo keeps running either way. Run `python speech.py` to test speech in
isolation.

**Low FPS** -- the target is >= 8 FPS on a laptop CPU. If it's slower,
lower `YOLO_IMGSZ` in `config.py`, or run detection every 2nd frame and
reuse the previous results (see `config.DETECT_EVERY_N_FRAMES`).

**No display / "could not connect to display"** -- on a headless Linux
machine (e.g. a CI container) there is no window server, so `main.py`
detects this automatically and keeps running without a video window; all
detection, decision and speech logic still runs. On your demo laptop, run
it from a normal desktop session and the window will appear.

**Approach detection feels off** (misses a fast walker, or false-alarms on
static objects) -- run with `--debug` to see each tracked object's
distance/closing-speed/TTC once a second, and tune the thresholds in
`config.py` (`APPROACH_CLOSING_SPEED_MIN_MPS`, `APPROACH_TTC_MAX_S`,
`APPROACH_DISTANCE_MAX_M`).

**Too much talking** -- check `decision.py`'s cooldowns
(`COOLDOWN_APPROACH_S`, `COOLDOWN_OBSTACLE_S`, `GLOBAL_MESSAGE_GAP_S` in
`config.py`); an object should not repeat within its cooldown unless it
gets more dangerous (e.g. obstacle -> approaching, or distance drops below
the stop threshold).

## 5. Out of scope (by design)

Semantic segmentation, depth models, pothole detection, custom model
training, smart glasses, live phone GPS, a mobile app, and road-crossing
assistance are intentionally not part of this prototype.
