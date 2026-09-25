"""
main.py -- Drishti entry point.

Usage:
    python main.py --source 0                              (webcam)
    python main.py --source videos/street1.mp4              (looping video file)
    python main.py --source http://192.168.1.42:8080/video  (phone via IP Webcam app)

Controls (in the OpenCV window):
    q      quit
    m      mute / unmute speech
    r      repeat last spoken message
    space  pause / resume the video
    d      scene description (stretch goal -- not built in the core system)
    n      start simulated route (stretch goal -- not built in the core system)
"""

from __future__ import annotations

import argparse
import os
import platform
import time
from typing import Optional

import cv2

import config
import hud
from decision import DecisionEngine
from speech import SpeechEngine
from vision import VisionPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drishti street navigation assistant")
    parser.add_argument("--source", default="0",
                         help="Camera index (e.g. 0) or a path to a video file.")
    parser.add_argument("--debug", action="store_true",
                         help="Print per-track id/distance/closing_speed/ttc once a second.")
    parser.add_argument("--max-frames", type=int, default=None,
                         help="Stop after N frames (for automated testing).")
    return parser.parse_args()


def open_source(source_arg: str):
    if source_arg.isdigit():
        cap = cv2.VideoCapture(int(source_arg))
        return cap, "Webcam", False, False
    if source_arg.startswith(("http://", "https://", "rtsp://")):
        cap = cv2.VideoCapture(source_arg)
        return cap, "Phone", False, True
    cap = cv2.VideoCapture(source_arg)
    return cap, "Video", True, False


def main() -> None:
    args = parse_args()
    cap, mode, is_video, is_stream = open_source(args.source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source!r}")

    vision = VisionPipeline()
    decision_engine = DecisionEngine()
    speech = SpeechEngine()

    window_name = "Drishti"
    # On Linux without an X display, cv2.imshow aborts the whole process
    # instead of raising a catchable exception -- detect that up front.
    headless = platform.system() == "Linux" and not os.environ.get("DISPLAY")
    if headless:
        print("No display detected; running headless (HUD is still computed each frame).")
    paused = False
    message: Optional[str] = None
    message_time: Optional[float] = None
    detections = []
    fps_smoothed = 0.0
    last_time = time.time()
    last_debug_print = 0.0
    frame_count = 0
    stream_fail_count = 0

    print(f"Drishti starting. Source: {args.source} ({mode}). Press 'q' in the window to quit.")

    try:
        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret:
                    if is_video:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    if is_stream:
                        # Wi-Fi phone streams occasionally drop a frame or stall;
                        # retry a bit before giving up, instead of ending the demo.
                        stream_fail_count += 1
                        if stream_fail_count <= 30:
                            time.sleep(0.05)
                            continue
                        print("Reconnecting to phone stream...")
                        cap.release()
                        cap = cv2.VideoCapture(args.source)
                        stream_fail_count = 0
                        continue
                    print("Source ended.")
                    break
                stream_fail_count = 0

                frame = cv2.resize(frame, (config.FRAME_WIDTH, config.FRAME_HEIGHT))
                now = time.time()

                try:
                    detections = vision.process_frame(frame, now=now)
                except Exception as exc:  # never let a vision hiccup kill the demo
                    print(f"[vision] error: {exc}")
                    detections = []

                try:
                    result = decision_engine.decide(detections, now=now)
                    if result.message:
                        speech.say(result.message, result.priority)
                        message, message_time = result.message, now
                except Exception as exc:  # never let a decision hiccup kill the demo
                    print(f"[decision] error: {exc}")

                if args.debug and now - last_debug_print >= 1.0:
                    last_debug_print = now
                    for d in detections:
                        print(f"  id={d.id:<4} {d.spoken_name:<10} dist={d.distance:5.2f}m "
                              f"closing={d.closing_speed:5.2f}m/s ttc={d.ttc} "
                              f"in_path={d.in_path} side={d.side} approaching={d.approaching}")

                dt = now - last_time
                last_time = now
                inst_fps = (1.0 / dt) if dt > 0 else 0.0
                fps_smoothed = inst_fps if fps_smoothed == 0 else 0.9 * fps_smoothed + 0.1 * inst_fps
                frame_count += 1
            else:
                now = time.time()

            canvas = hud.render(
                frame, detections, message, message_time, fps_smoothed, mode,
                decision_engine.decision_log, muted=getattr(speech, "_mute", False), now=now,
            )

            if not headless:
                try:
                    cv2.imshow(window_name, canvas)
                except cv2.error as exc:
                    headless = True
                    print(f"[hud] display unavailable ({exc}); continuing headless.")

            key = (cv2.waitKey(1) & 0xFF) if not headless else -1
            if key == ord('q'):
                break
            elif key == ord('m'):
                muted = speech.toggle_mute()
                print("Muted." if muted else "Unmuted.")
            elif key == ord('r'):
                speech.repeat_last()
            elif key == ord(' '):
                paused = not paused
            elif key in (ord('d'), ord('n')):
                print("That control is a stretch-goal feature, not built in the core system.")

            if args.max_frames is not None and frame_count >= args.max_frames:
                break

    finally:
        speech.stop()
        cap.release()
        if not headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
