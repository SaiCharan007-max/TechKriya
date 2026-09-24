"""
hud.py -- all drawing / dashboard for Drishti.

Produces a single 1000x480 BGR frame: the camera view (with corridor overlay
and detection boxes) on the left, a dark side panel with status info and the
decision log on the right.
"""

from __future__ import annotations

import time
from typing import Iterable, List, Optional

import cv2
import numpy as np

import config
from vision import Detection


def compute_state(detections: List[Detection]) -> str:
    """SAFE / CAUTION / DANGER, used for the badge and corridor colour."""
    for d in detections:
        if d.approaching or (d.in_path and d.distance < config.OBSTACLE_STOP_DISTANCE_M):
            return "DANGER"
    for d in detections:
        if d.in_path and d.distance < config.OBSTACLE_DISTANCE_M:
            return "CAUTION"
    return "SAFE"


def _state_color(state: str):
    return {
        "SAFE": config.COLOR_SAFE,
        "CAUTION": config.COLOR_CAUTION,
        "DANGER": config.COLOR_DANGER,
    }[state]


def draw_corridor(frame: np.ndarray, blocked: bool) -> np.ndarray:
    h, w = frame.shape[:2]
    left = int(w * config.CORRIDOR_LEFT_FRAC)
    right = int(w * config.CORRIDOR_RIGHT_FRAC)
    # A trapezoid: narrower near the top (far away), full corridor width at
    # the bottom (near the user), to suggest a walking path receding ahead.
    top_left = int(left + (right - left) * 0.30)
    top_right = int(right - (right - left) * 0.30)
    pts = np.array([[top_left, int(h * 0.35)], [top_right, int(h * 0.35)],
                     [right, h], [left, h]], dtype=np.int32)

    overlay = frame.copy()
    color = config.COLOR_DANGER if blocked else config.COLOR_SAFE
    cv2.fillPoly(overlay, [pts], color)
    cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, dst=frame)
    cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=1)
    return frame


def _box_color(d: Detection):
    if d.approaching or d.distance < config.OBSTACLE_STOP_DISTANCE_M:
        return config.COLOR_ALERT_BOX
    if d.in_path:
        return config.COLOR_IN_PATH_BOX
    return config.COLOR_FAR_BOX


def draw_detections(frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
    for d in detections:
        x1, y1, x2, y2 = d.box
        color = _box_color(d)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = f"{d.spoken_name} #{d.id} {d.distance:.1f}m"
        if d.approaching:
            label += f"  ▲ {d.closing_speed:.1f}m/s"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = max(th + 4, y1 - 4)
        cv2.rectangle(frame, (x1, ty - th - 4), (x1 + tw + 4, ty), color, -1)
        cv2.putText(frame, label, (x1 + 2, ty - 3), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


def draw_banner(frame: np.ndarray, message: Optional[str], message_time: Optional[float],
                 now: float) -> np.ndarray:
    if not message or message_time is None:
        return frame
    age = now - message_time
    if age > config.HUD_BANNER_FADE_S:
        return frame

    h, w = frame.shape[:2]
    alpha = max(0.0, 1.0 - age / config.HUD_BANNER_FADE_S) * 0.75
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 34), (0, 0, 0), -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)

    text = f'AUDIO: "{message}"'
    text_alpha = max(0.15, 1.0 - age / config.HUD_BANNER_FADE_S)
    color = tuple(int(c * text_alpha) for c in (255, 255, 255))
    cv2.putText(frame, text, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    return frame


_LOG_COLORS = {
    "CRITICAL": config.COLOR_DANGER,
    "OBSTACLE": config.COLOR_CAUTION,
    "NAVIGATION": (255, 180, 60),
    "INFO": config.COLOR_TEXT,
}


def _log_line_color(line: str):
    for tag, color in _LOG_COLORS.items():
        if f"[{tag}]" in line:
            return color
    return config.COLOR_TEXT


def draw_side_panel(fps: float, mode: str, state: str, counts: dict,
                     decision_log: Iterable[str], muted: bool) -> np.ndarray:
    panel = np.full((config.HUD_WINDOW_HEIGHT, config.HUD_SIDE_PANEL_WIDTH, 3),
                     config.COLOR_PANEL_BG, dtype=np.uint8)

    y = 30
    cv2.putText(panel, "DRISHTI", (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (255, 255, 255), 2, cv2.LINE_AA)
    y += 28
    cv2.putText(panel, f"Mode: {mode}   FPS: {fps:.1f}", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, config.COLOR_TEXT, 1, cv2.LINE_AA)
    y += 34

    badge_color = _state_color(state)
    cv2.rectangle(panel, (16, y - 20), (16 + 150, y + 8), badge_color, -1)
    cv2.putText(panel, state, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 0), 2, cv2.LINE_AA)
    if muted:
        cv2.putText(panel, "MUTED", (190, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 255), 2, cv2.LINE_AA)
    y += 36

    cv2.putText(panel, f"Detected: {counts.get('detected', 0)}", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, config.COLOR_TEXT, 1, cv2.LINE_AA)
    y += 22
    cv2.putText(panel, f"In path:  {counts.get('in_path', 0)}", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, config.COLOR_TEXT, 1, cv2.LINE_AA)
    y += 22
    cv2.putText(panel, f"Approaching: {counts.get('approaching', 0)}", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, config.COLOR_TEXT, 1, cv2.LINE_AA)
    y += 30

    cv2.line(panel, (16, y), (config.HUD_SIDE_PANEL_WIDTH - 16, y), (80, 80, 80), 1)
    y += 22
    cv2.putText(panel, "DECISION LOG", (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 200, 200), 1, cv2.LINE_AA)
    y += 20

    for line in list(decision_log)[-config.HUD_LOG_LINES:]:
        color = _log_line_color(line)
        # wrap long lines so they fit the panel width
        max_chars = 46
        wrapped = [line[i:i + max_chars] for i in range(0, len(line), max_chars)] or [""]
        for chunk in wrapped:
            if y > config.HUD_WINDOW_HEIGHT - 10:
                break
            cv2.putText(panel, chunk, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                        color, 1, cv2.LINE_AA)
            y += 16

    return panel


def render(frame: np.ndarray, detections: List[Detection], message: Optional[str],
           message_time: Optional[float], fps: float, mode: str,
           decision_log: Iterable[str], muted: bool, now: Optional[float] = None) -> np.ndarray:
    """Compose the full 1000x480 HUD frame."""
    now = time.time() if now is None else now
    cam = frame.copy()

    state = compute_state(detections)
    blocked = state == "DANGER"
    cam = draw_corridor(cam, blocked)
    cam = draw_detections(cam, detections)
    cam = draw_banner(cam, message, message_time, now)

    counts = {
        "detected": len(detections),
        "in_path": sum(1 for d in detections if d.in_path),
        "approaching": sum(1 for d in detections if d.approaching),
    }
    panel = draw_side_panel(fps, mode, state, counts, decision_log, muted)

    canvas = np.zeros((config.HUD_WINDOW_HEIGHT, config.HUD_WINDOW_WIDTH, 3), dtype=np.uint8)
    canvas[:, :cam.shape[1]] = cam
    canvas[:, cam.shape[1]:cam.shape[1] + panel.shape[1]] = panel
    return canvas


if __name__ == "__main__":
    print("=== hud.py self-test ===")
    frame = np.full((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3), 40, dtype=np.uint8)

    dets = [
        Detection(id=1, label="motorcycle", spoken_name="bike", conf=0.9,
                   box=(260, 150, 380, 380), distance=6.0, side="ahead",
                   in_path=True, closing_speed=4.1, ttc=2.2, approaching=True),
        Detection(id=2, label="chair", spoken_name="chair", conf=0.8,
                   box=(50, 250, 150, 400), distance=8.0, side="left",
                   in_path=False, closing_speed=0.0, ttc=None, approaching=False),
    ]
    log = [
        "12:04:31 [CRITICAL] bike#1 closing 4.1 m/s, TTC 2.2 s -> \"Stop. Bike approaching ahead.\"",
        "12:04:35 [OBSTACLE] chair#2 at 2.0 m -> \"Chair ahead, 2 metres. Step left.\"",
    ]

    canvas = render(frame, dets, "Stop. Bike approaching ahead.", time.time(),
                     fps=9.3, mode="Video", decision_log=log, muted=False)
    assert canvas.shape == (config.HUD_WINDOW_HEIGHT, config.HUD_WINDOW_WIDTH, 3)

    out_path = "hud_selftest.png"
    cv2.imwrite(out_path, canvas)
    print(f"Rendered a sample HUD frame to {out_path} (1000x480). Layout:")
    print("  Left 640x480: camera feed, translucent green/red walking corridor,")
    print("  colour-coded boxes with distance + approach-speed labels, fading")
    print("  top banner with the current spoken message.")
    print("  Right 360x480: dark panel with title DRISHTI, FPS/mode, a coloured")
    print("  SAFE/CAUTION/DANGER badge, object counts, and the decision log")
    print("  colour-coded by priority (red=CRITICAL, amber=OBSTACLE).")
    print("=== hud.py self-test complete ===")
