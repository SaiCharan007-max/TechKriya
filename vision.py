"""
vision.py -- YOLO detection + ByteTrack tracking + distance/zone/approach logic.

Turns raw camera frames into a list of Detection objects that decision.py can
reason about. Keeps a short history of (timestamp, distance) per track id so
it can tell whether something is approaching the user.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

import config


@dataclass
class Detection:
    id: int
    label: str
    spoken_name: str
    conf: float
    box: Tuple[int, int, int, int]  # x1, y1, x2, y2 in pixel coords
    distance: float                 # metres, smoothed
    side: str                       # "left" / "ahead" / "right"
    in_path: bool
    closing_speed: float            # m/s, positive = approaching
    ttc: Optional[float]            # seconds, None if not closing
    approaching: bool


@dataclass
class _TrackState:
    history: Deque[Tuple[float, float]] = field(default_factory=deque)  # (t, raw_distance)
    smoothed_distance: Optional[float] = None
    last_seen: float = 0.0


def spoken_name_for(label: str) -> str:
    return config.SPOKEN_NAMES.get(label, label)


def _focal_px(frame_width: int, hfov_deg: float) -> float:
    hfov_rad = math.radians(hfov_deg)
    return (frame_width / 2.0) / math.tan(hfov_rad / 2.0)


def estimate_distance_m(real_height_m: float, box_height_px: float, focal_px: float) -> float:
    if box_height_px <= 0:
        return config.DISTANCE_MAX_M
    distance = real_height_m * focal_px / box_height_px
    return max(config.DISTANCE_MIN_M, min(config.DISTANCE_MAX_M, distance))


def compute_side(box: Tuple[int, int, int, int], frame_width: int) -> str:
    x1, _, x2, _ = box
    cx = (x1 + x2) / 2.0
    left = frame_width * config.CORRIDOR_LEFT_FRAC
    right = frame_width * config.CORRIDOR_RIGHT_FRAC
    if cx < left:
        return "left"
    if cx > right:
        return "right"
    return "ahead"


def compute_in_path(box: Tuple[int, int, int, int], frame_width: int) -> bool:
    x1, _, x2, _ = box
    box_w = max(1, x2 - x1)
    corridor_left = frame_width * config.CORRIDOR_LEFT_FRAC
    corridor_right = frame_width * config.CORRIDOR_RIGHT_FRAC
    overlap = max(0.0, min(x2, corridor_right) - max(x1, corridor_left))
    return (overlap / box_w) >= config.IN_PATH_OVERLAP_FRAC


def _closing_speed_and_ttc(history: Deque[Tuple[float, float]]) -> Tuple[float, Optional[float], float]:
    """Linear regression of distance vs time over the history window.

    Returns (closing_speed_mps, ttc_seconds_or_none, span_seconds).
    closing_speed is positive when distance is decreasing (approaching).
    """
    if len(history) < 2:
        return 0.0, None, 0.0

    times = np.array([t for t, _ in history], dtype=np.float64)
    dists = np.array([d for _, d in history], dtype=np.float64)
    span = float(times[-1] - times[0])
    if span <= 0:
        return 0.0, None, span

    t0 = times[0]
    times = times - t0
    # slope of distance over time via least squares
    A = np.vstack([times, np.ones_like(times)]).T
    slope, _ = np.linalg.lstsq(A, dists, rcond=None)[0]
    closing_speed = -slope  # distance shrinking -> positive closing speed

    latest_distance = dists[-1]
    ttc = None
    if closing_speed > 0:
        ttc = latest_distance / closing_speed
    return float(closing_speed), ttc, span


class VisionPipeline:
    """Wraps a YOLO model + ByteTrack tracker and produces Detection lists."""

    def __init__(self, model_path: str = config.YOLO_MODEL_PATH):
        self._model = None
        self._model_path = model_path
        self._tracks: Dict[int, _TrackState] = {}

    def _ensure_model(self):
        if self._model is None:
            from ultralytics import YOLO
            self._model = YOLO(self._model_path)
        return self._model

    def _cleanup_stale_tracks(self, now: float):
        stale_ids = [
            tid for tid, st in self._tracks.items()
            if now - st.last_seen > config.TRACK_STALE_SECONDS
        ]
        for tid in stale_ids:
            del self._tracks[tid]

    def process_frame(self, frame: np.ndarray, now: Optional[float] = None) -> List[Detection]:
        """Run detection+tracking on a frame and return Detection objects."""
        now = time.time() if now is None else now
        model = self._ensure_model()
        frame_h, frame_w = frame.shape[:2]
        focal_px = _focal_px(frame_w, config.CAMERA_HFOV_DEG)

        results = model.track(
            frame,
            persist=True,
            tracker=config.TRACKER_CONFIG,
            conf=config.YOLO_CONF_THRESHOLD,
            imgsz=config.YOLO_IMGSZ,
            verbose=False,
        )

        detections: List[Detection] = []
        if not results:
            self._cleanup_stale_tracks(now)
            return detections

        result = results[0]
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            self._cleanup_stale_tracks(now)
            return detections

        names = result.names
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)
        track_ids = boxes.id.cpu().numpy().astype(int)

        for box, conf, cls_id, track_id in zip(xyxy, confs, cls_ids, track_ids):
            label = names.get(int(cls_id), str(cls_id)) if isinstance(names, dict) else names[int(cls_id)]
            if label not in config.CLASS_HEIGHTS_M:
                continue

            x1, y1, x2, y2 = [int(v) for v in box]
            box_h_px = max(1, y2 - y1)
            real_h = config.CLASS_HEIGHTS_M[label]
            raw_distance = estimate_distance_m(real_h, box_h_px, focal_px)

            state = self._tracks.setdefault(int(track_id), _TrackState())
            alpha = config.DISTANCE_EMA_ALPHA
            if state.smoothed_distance is None:
                state.smoothed_distance = raw_distance
            else:
                state.smoothed_distance = alpha * raw_distance + (1 - alpha) * state.smoothed_distance
            state.last_seen = now
            state.history.append((now, state.smoothed_distance))
            cutoff = now - config.APPROACH_HISTORY_SECONDS
            while state.history and state.history[0][0] < cutoff:
                state.history.popleft()

            closing_speed, ttc, span = _closing_speed_and_ttc(state.history)
            has_enough_history = span >= config.APPROACH_MIN_HISTORY_SECONDS

            approaching = (
                has_enough_history
                and label in config.APPROACH_CLASSES
                and closing_speed > config.APPROACH_CLOSING_SPEED_MIN_MPS
                and ttc is not None
                and ttc < config.APPROACH_TTC_MAX_S
                and state.smoothed_distance < config.APPROACH_DISTANCE_MAX_M
            )

            box_t = (x1, y1, x2, y2)
            detections.append(Detection(
                id=int(track_id),
                label=label,
                spoken_name=spoken_name_for(label),
                conf=float(conf),
                box=box_t,
                distance=round(state.smoothed_distance, 2),
                side=compute_side(box_t, frame_w),
                in_path=compute_in_path(box_t, frame_w),
                closing_speed=round(closing_speed, 2),
                ttc=round(ttc, 2) if ttc is not None else None,
                approaching=approaching,
            ))

        self._cleanup_stale_tracks(now)
        return detections


if __name__ == "__main__":
    # Self-test: exercise the pure geometry/approach-detection logic without
    # requiring a camera or the YOLO weights to be downloaded.
    print("=== vision.py self-test ===")

    focal = _focal_px(config.FRAME_WIDTH, config.CAMERA_HFOV_DEG)
    print(f"focal_px for {config.FRAME_WIDTH}px @ {config.CAMERA_HFOV_DEG} deg HFOV = {focal:.1f}")

    d = estimate_distance_m(1.65, 200, focal)
    print(f"person, box_h=200px -> distance = {d:.2f} m")
    assert config.DISTANCE_MIN_M <= d <= config.DISTANCE_MAX_M

    box_center = (260, 100, 380, 400)  # centred in a 640-wide frame
    assert compute_in_path(box_center, config.FRAME_WIDTH) is True
    assert compute_side(box_center, config.FRAME_WIDTH) == "ahead"

    box_left = (0, 100, 80, 400)
    assert compute_side(box_left, config.FRAME_WIDTH) == "left"
    assert compute_in_path(box_left, config.FRAME_WIDTH) is False

    box_right = (600, 100, 640, 400)
    assert compute_side(box_right, config.FRAME_WIDTH) == "right"

    # Simulate an object approaching quickly: distance shrinks 10m -> 4m over 1s
    hist = deque()
    t0 = 1000.0
    for i in range(6):
        t = t0 + i * 0.2
        dist = 10.0 - i * 1.2
        hist.append((t, dist))
    speed, ttc, span = _closing_speed_and_ttc(hist)
    print(f"approaching object: closing_speed={speed:.2f} m/s, ttc={ttc}, span={span:.2f}s")
    assert speed > config.APPROACH_CLOSING_SPEED_MIN_MPS
    assert ttc is not None and ttc < config.APPROACH_TTC_MAX_S

    # Simulate a static object: distance barely changes
    hist_static = deque()
    for i in range(6):
        t = t0 + i * 0.2
        dist = 5.0 + (0.01 * i)
        hist_static.append((t, dist))
    speed_s, ttc_s, span_s = _closing_speed_and_ttc(hist_static)
    print(f"static object: closing_speed={speed_s:.2f} m/s, ttc={ttc_s}")
    assert speed_s <= config.APPROACH_CLOSING_SPEED_MIN_MPS

    print("All geometry / approach-detection checks passed.")

    try:
        import cv2
        pipeline = VisionPipeline()
        pipeline._ensure_model()
        frame = np.zeros((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3), dtype=np.uint8)
        dets = pipeline.process_frame(frame)
        print(f"YOLO model loaded OK, ran on a blank frame -> {len(dets)} detections (expected 0).")
    except Exception as exc:  # pragma: no cover - best effort in constrained envs
        print(f"(Skipping live YOLO check: {exc})")

    print("=== vision.py self-test complete ===")
