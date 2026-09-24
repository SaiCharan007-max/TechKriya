# Drishti – AI Street Navigation Assistant for the Visually Impaired

> This file is the full project context. Put it in the project root. Claude Code reads it automatically.

## 1. What we are building

A laptop-based prototype that helps a blind pedestrian walk safely on a street.
A chest-mounted webcam watches the path. The system detects obstacles and moving vehicles, then speaks **only the most important instruction** into the user's earphones.
Examples: "Stop. Bike approaching.", "Pole ahead, 2 metres, step right."

Context: this is a **college project for a judged demo. The deadline is 5 days.**
Priority order: **works reliably > looks impressive > feature count.**
Do not over-engineer. No training of custom models. Everything must run on a normal Windows laptop CPU (no GPU required).

### The pitch (what makes it special)
"Most solutions just detect objects and read them all out. Drishti **prioritizes**. It tells a blind user only what matters, when it matters: moving vehicles first, obstacles in the path next, silence otherwise."

Differentiators to show judges:
1. **Approaching-object alert.** It tracks objects over time and knows whether something is *coming toward* the user or is static.
2. **Priority decision engine.** Safety beats navigation, which beats description. Cooldowns prevent chatter.
3. **Explainable HUD.** The screen shows detections, the walking corridor, and a live log of *what it said and why*.
4. (Stretch) **Scene description on demand** using a vision-language model.
5. (Stretch) **Simulated Google Maps / OpenRouteService route** with spoken turn-by-turn prompts, combined with obstacle alerts.

### Out of scope (do NOT build)
Semantic segmentation, depth models, pothole detection, custom training, smart glasses, live phone GPS, mobile app, road-crossing assistance.

## 2. Tech stack
- Python 3.10+
- `ultralytics`: YOLO11n (`yolo11n.pt`, pretrained COCO) with built-in ByteTrack tracking (`model.track(..., persist=True, tracker="bytetrack.yaml")`)
- `opencv-python`: camera/video input, HUD drawing, display window
- Text-to-speech in a background thread:
  - Windows: SAPI via `pywin32` (`win32com.client.Dispatch("SAPI.SpVoice")`, call `pythoncom.CoInitialize()` inside the thread)
  - Fallback: `pyttsx3`, with the engine created inside the speech thread
  - Mac: the `say` command
- `numpy`, `requests`
- Optional: `anthropic` for the scene description (model `claude-haiku-4-5-20251001`, key from env `ANTHROPIC_API_KEY`)

## 3. Project structure
```
drishti/
  CLAUDE.md
  requirements.txt
  config.py        # ALL tunable constants live here
  main.py          # entry point, main loop, keyboard controls, CLI args
  vision.py        # YOLO + tracking + zones + distance + approach detection
  decision.py      # priority engine -> what to say
  speech.py        # threaded TTS with priority queue
  hud.py           # all drawing / dashboard
  describe.py      # (stretch) VLM scene description
  navigation.py    # (stretch) route fetch + simulated walk + turn prompts
  videos/          # test street videos (.mp4)
```

## 4. Detailed behaviour

### 4.1 Input
- `--source 0` for the webcam, or `--source videos/street1.mp4` for a video file (loop the video at the end). This is critical: the demo must work from recorded video as a backup.
- Resize frames to 640x480 (keep this in config).

### 4.2 Vision (`vision.py`)
- Only these COCO classes, each with an approximate real height in metres for distance:
  person 1.65, bicycle 1.0, motorcycle 1.1, car 1.5, bus 3.0, truck 3.0, dog 0.55, cow 1.4, bench 0.85, chair 0.9, fire hydrant 0.8, parking meter 1.3, potted plant 0.8, suitcase 0.65, stop sign 0.75.
- Spoken names: motorcycle→"bike", bicycle→"cycle", parking meter→"pole", potted plant→"plant pot".
- Confidence threshold 0.4, imgsz 480.
- **Distance:** `distance_m = real_height * focal_px / box_height_px`, with `focal_px = (frame_width/2) / tan(HFOV/2)` and HFOV = 70° (configurable). Clamp to 0.5–30 m. Smooth each track with an EMA (alpha 0.4).
- **Zones:** the walking corridor is the centre band x ∈ [0.30W, 0.70W].
  - An object is `in_path` if its box overlaps the corridor by ≥ 30% of the box width.
  - `side` = "left" / "ahead" / "right" from the box centre.
- **Approach detection:** keep about 1.5 s of (timestamp, distance) history per track ID.
  - Compute `closing_speed` (m/s) by linear regression over the history. Require at least 0.5 s of history.
  - `ttc = distance / closing_speed` when closing_speed > 0.
  - An object is `approaching` when its class is in {bicycle, motorcycle, car, bus, truck, dog, cow}, closing_speed > 2.0 m/s (faster than walking), ttc < 4 s, and distance < 15 m.
- Output a list of `Detection` dataclasses: id, label, spoken_name, conf, box, distance, side, in_path, closing_speed, ttc, approaching.
- Clean up histories for track IDs not seen for 2 s.

### 4.3 Decision engine (`decision.py`), the heart of the project
Each frame, it takes the detections (and navigation events, if any) and returns at most **one** message to speak, plus a log entry with the reason.

Priority levels:
1. **CRITICAL**: an approaching object, preferring in_path, highest ttc urgency first.
   → "Stop. {Name} approaching {from the left / ahead / from the right}."
2. **OBSTACLE**: the nearest in_path object with distance < 3.5 m.
   - Distance < 1.3 m → "Stop. {Name} right in front."
   - Otherwise → "{Name} ahead, {n} metres. Step {left/right}." Choose the side whose zone has fewer or farther obstacles within 4 m. If both sides are blocked → "Path blocked. Stop."
3. **NAVIGATION** (stretch): turn prompts from `navigation.py`.
   - **Fusion rule:** if the turn direction side has an obstacle within 3 m → "Turn {dir} after the {name}."
4. **INFO**: nothing, so stay silent. Optional: "Path clear" once, after an obstacle warning stops applying.

Anti-chatter rules:
- Cooldown per message key: e.g. `approach-{track_id}` 4 s, `obstacle-{track_id}` 5 s, `nav-{step}` never repeats.
- Global gap of ≥ 2.5 s between non-critical messages.
- CRITICAL ignores the global gap and flushes the speech queue.
- After a CRITICAL message, suppress lower priorities for 2 s.
- Keep a `decision_log` deque (last 8) of strings like
  `12:04:31 [CRITICAL] bike#7 closing 4.1 m/s, TTC 2.2 s -> "Stop. Bike approaching ahead."`

### 4.4 Speech (`speech.py`)
- A background thread with a priority queue. `say(text, priority)`.
- Critical messages clear pending lower-priority items.
- Keep `last_spoken` for a "repeat" key. Add a `mute` toggle.
- Backend auto-selected by OS with fallbacks. If all backends fail, print to the console instead of crashing.

### 4.5 HUD (`hud.py`), which must look good to judges
Window 1000x480: camera 640x480 on the left, dark side panel 360 px on the right.

- **On the camera view:**
  - A semi-transparent green trapezoid showing the walking corridor. It turns red when the path is blocked.
  - Boxes colour-coded: green = far / not in path, orange = in path, red = approaching or < 1.3 m.
  - Each box labelled `name #id 3.2m`, plus `▲ 4.1m/s` when approaching.
  - A top banner showing the current spoken message (e.g. `AUDIO: "Stop. Bike approaching."`).
- **Side panel:**
  - Title "DRISHTI", FPS, mode (Webcam/Video), and a state indicator (SAFE / CAUTION / DANGER with a colour).
  - Counts: objects detected, in path, approaching.
  - (Stretch) navigation: next turn and distance, plus a mini route map.
  - Decision log (last 8 lines, small font, colour by priority).

### 4.6 Controls (keyboard, in the OpenCV window)
`q` quit · `m` mute · `r` repeat last message · `d` describe scene (stretch) · `n` start the simulated route (stretch) · `space` pause video.

### 4.7 Stretch A: scene description (`describe.py`)
- On `d`: JPEG-encode the current frame and send it with the prompt:
  "You are guiding a blind pedestrian. In at most 2 short sentences, describe the scene ahead: path, obstacles, people, vehicles and their positions (left/ahead/right). No filler."
- Runs in a background thread, and the result is spoken at INFO priority.
- If there is no API key, say "Description not available".

### 4.8 Stretch B: simulated route navigation (`navigation.py`)
- Fetch a real walking route once: OpenRouteService `foot-walking` (free key, env `ORS_API_KEY`) or Google Routes API `WALK` (env `GOOGLE_MAPS_API_KEY`). Start and end come from CLI coordinates.
- Cache the route to `route.json` so the demo works offline.
- Simulate walking along the route at 1.3 m/s (or step with a key).
- Emit events:
  - "In 20 metres, turn left" at 25 m before a maneuver
  - "Turn left now" at 8 m
  - "You have arrived" at the end
- Show the route polyline and the moving dot on the HUD mini-map.
- **Future work (slides only):** replace the simulation with live phone GPS.

## 5. Coding rules
- All thresholds in `config.py`. No magic numbers elsewhere.
- Each module must be testable alone (`if __name__ == "__main__":` quick demo).
- Never crash the main loop. Wrap optional features in try/except and log a warning.
- Target ≥ 8 FPS on a laptop CPU with yolo11n at imgsz 480. If slower, run detection on every 2nd frame and reuse the last results.
- Keep code simple and commented. Students must be able to explain it to judges.
- A README.md with setup, run commands and troubleshooting.

## 6. Definition of done (demo checklist)
- [ ] `python main.py --source videos/street1.mp4` runs and shows the HUD with boxes, corridor and log
- [ ] `python main.py --source 0` works with the webcam
- [ ] A person walking quickly toward the webcam triggers an approach / "stop" warning
- [ ] A chair placed in the path triggers "Chair ahead, 2 metres. Step left/right."
- [ ] No repeated chatter: the same object is not announced again within its cooldown
- [ ] Mute / repeat keys work
- [ ] (Stretch) `d` speaks a scene description
- [ ] (Stretch) the simulated route speaks turn prompts, and the fusion message appears
