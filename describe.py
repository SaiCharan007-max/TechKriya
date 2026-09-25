"""
describe.py -- Stretch A: on-demand scene description via a vision-language
model (Claude Haiku), per CLAUDE.md section 4.7.

Runs on a background thread so it never blocks the main loop; the result is
spoken at INFO priority once ready. Falls back to a fixed message if there is
no API key, the `anthropic` package isn't installed, or the request fails --
this must never crash the main loop.
"""

from __future__ import annotations

import base64
import os
import threading
from typing import Callable

import cv2
import numpy as np

import config

NOT_AVAILABLE = "Description not available."


def _describe_sync(frame: np.ndarray) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return NOT_AVAILABLE

    try:
        import anthropic
    except ImportError:
        return NOT_AVAILABLE

    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return NOT_AVAILABLE
    image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                  "data": image_b64}},
                    {"type": "text", "text": config.DESCRIBE_PROMPT},
                ],
            }],
        )
        text = "".join(getattr(block, "text", "") for block in response.content)
        return text.strip() or NOT_AVAILABLE
    except Exception as exc:
        print(f"[describe] request failed: {exc}")
        return NOT_AVAILABLE


def describe_scene_async(frame: np.ndarray, on_result: Callable[[str], None]) -> None:
    """Fire-and-forget: describes a snapshot of `frame` on a background
    thread and calls on_result(text) when done. Never blocks the caller and
    never raises out of the thread."""
    snapshot = frame.copy()

    def _run():
        try:
            text = _describe_sync(snapshot)
        except Exception as exc:  # extra safety net -- never kill the thread silently
            print(f"[describe] unexpected error: {exc}")
            text = NOT_AVAILABLE
        on_result(text)

    threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    print("=== describe.py self-test ===")
    dummy = np.full((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3), 60, dtype=np.uint8)
    done = threading.Event()
    result_holder = {}

    def on_result(text):
        result_holder["text"] = text
        done.set()

    describe_scene_async(dummy, on_result)
    done.wait(timeout=15)
    print("Result:", result_holder.get("text", "<timed out>"))
    print("=== describe.py self-test complete (no crash = pass) ===")
