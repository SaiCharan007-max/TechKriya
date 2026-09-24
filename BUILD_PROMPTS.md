# Drishti – Build Prompts for Claude Code (5-day plan)

## Setup (once, about 15 min)
1. Install Python 3.10+ and Git. Create a folder `drishti` and put `CLAUDE.md` inside it.
2. Open a terminal in that folder and run `git init`, then `claude`.
3. Use **Sonnet** for all the prompts below. Switch to **Opus** only if you're stuck on a bug after 2–3 tries.
4. After every prompt that works, run: `git add . && git commit -m "working: <what>"`.
5. Download 2–3 street walking videos (first-person, Indian street, 20–60 s) into `drishti/videos/`. Your own phone recordings, filmed at chest height while walking, work best.

---

## MASTER PROMPT (Day 1, paste first)

```
Read CLAUDE.md fully. It is the complete spec for this project.

Build the CORE system now (sections 4.1 to 4.6). Do NOT build the stretch goals yet (describe.py, navigation.py).

Create: requirements.txt, config.py, vision.py, decision.py, speech.py, hud.py, main.py, README.md.

Requirements:
- It must run on Windows with a laptop CPU.
- `python main.py --source 0` for the webcam and `python main.py --source videos/<file>.mp4` for a video file (loop the video).
- Follow the decision engine priorities and cooldown rules exactly as written.
- Put all thresholds in config.py.

After writing the code:
1. Install the requirements.
2. Run each module's self-test.
3. Run main.py on a video file (if there is none in videos/, then on webcam) and fix every error until it runs cleanly.

At the end, tell me exactly what command to run and what I should see and hear.
```

---

## Day 1–2: fixing and tuning (use as needed)

**If speech doesn't work:**
```
Speech is not working (describe what happens: silent / only speaks once / crashes). Fix speech.py so it reliably speaks every message on Windows. Try SAPI via pywin32 first, then pyttsx3 with the engine created inside the thread. Add a test: `python speech.py` should speak 3 sentences with different priorities.
```

**If it's too slow:**
```
FPS is only <X>. Make it at least 8 FPS on CPU: run YOLO every 2nd frame and reuse results in between, lower imgsz if needed, and show the FPS on the HUD. Don't break tracking or the approach detection.
```

**Tuning approach detection:**
```
Test the approach detection. Add a debug mode (`--debug`) that prints, for every tracked object, its id, distance, closing_speed and ttc each second. Right now [a person walking toward the camera is NOT detected / static objects trigger false alerts]. Tune the logic and config values so that fast approaching objects trigger the alert and static ones don't.
```

**Too much talking:**
```
The system talks too much / repeats itself. Review decision.py against the anti-chatter rules in CLAUDE.md section 4.3 and fix it. The same object should not be announced again within its cooldown unless it becomes more dangerous (e.g. obstacle -> approaching, or distance drops below the stop threshold).
```

---

## Day 3: make the HUD impressive

```
Polish hud.py so it looks professional for a judges' demo, following CLAUDE.md section 4.5:
- smooth semi-transparent walking corridor that turns red when blocked
- colour-coded boxes with labels, distance and a speed arrow for approaching objects
- a big top banner with the current audio message that fades after 3 seconds
- a side panel with title, FPS, SAFE/CAUTION/DANGER state badge, counts, and a colour-coded decision log
- add a `--record out.mp4` flag that saves the HUD output as a video (for our backup demo)
Keep FPS the same. Show me a screenshot description of the final layout.
```

---

## Day 4: stretch goals (only if Days 1–3 work well; commit first!)

**Stretch A: scene description**
```
Implement CLAUDE.md section 4.7 (describe.py). Pressing `d` sends the current frame to the Claude API (model claude-haiku-4-5-20251001, key from env ANTHROPIC_API_KEY) and speaks the answer. It must run in a background thread so video doesn't freeze. Show "Describing..." on the HUD while waiting. If there is no key or no internet, say "Description not available" and continue.
```

**Stretch B: simulated route navigation**
```
Implement CLAUDE.md section 4.8 (navigation.py) with OpenRouteService (env ORS_API_KEY).
- CLI: `--route "startLat,startLon" "endLat,endLon"`. Fetch the foot-walking route once and cache it to route.json.
- Pressing `n` starts a simulated walk at 1.3 m/s along the route.
- Speak turn prompts at 25 m and 8 m before each maneuver, and "You have arrived" at the end.
- Add the NAVIGATION priority and the fusion rule to decision.py ("Turn left after the car" when an obstacle is on the turn side).
- Add a mini-map in the HUD side panel: route line, moving dot, next turn with distance.
The camera/video keeps running at the same time so obstacle alerts can interrupt navigation.
```

---

## Day 5: demo preparation (no new features!)

```
Freeze features. Do a final review:
1. Run the full definition-of-done checklist in CLAUDE.md section 6 and report pass/fail for each item.
2. Fix only bugs, no new features.
3. Update README.md with setup, run commands, controls, and troubleshooting.
4. Create demo.bat that launches the video demo with one double-click.
```

Then:
- Record 2 backup demo videos with `--record`: one street video, one live (a friend walks toward the camera fast, and a chair is placed in the path).
- Test once with a blindfolded friend, with the webcam on the chest and earphones in.
- Slides: Problem → Existing solutions and their gap → Our approach (architecture diagram: Camera → YOLO + Tracking → Decision Engine → Speech/HUD) → Live demo → Results → Future scope (live GPS + Google Maps, smart glasses, depth/segmentation, haptics).

---

## Tips for vibe coding
- One prompt = one goal. Test and commit before the next.
- When something breaks, paste the **full error message**. Don't describe it.
- If Claude goes in circles after 3 tries: `git checkout .` to reset, then ask again with a simpler request.
- Tell Claude what you *observed*, e.g. "the bike was announced 4 times in 5 seconds", not "fix it".
- Watch your Pro usage limit: long sessions burn quota. Start a fresh session (`/clear`) for each new day. CLAUDE.md keeps the context.
