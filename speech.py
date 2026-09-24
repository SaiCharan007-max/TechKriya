"""
speech.py -- threaded text-to-speech with a priority queue.

Runs a single background thread that owns the TTS engine (TTS engines are
generally not thread-safe / must be created on the thread that uses them).
`say(text, priority)` queues a message; CRITICAL messages clear any pending
lower-priority messages so the user hears the urgent one immediately.

Backend selection:
  - Windows: SAPI via pywin32, falling back to pyttsx3.
  - macOS: the `say` command.
  - Linux / anything else: pyttsx3 (espeak), falling back to printing.
If every backend fails, messages are printed to the console instead of
crashing the main loop.
"""

from __future__ import annotations

import platform
import subprocess
import threading
import time
from typing import Callable, List, Optional, Tuple

import config


def _build_backend() -> Callable[[str], None]:
    """Create and return a speak(text) function. Must be called on the
    thread that will use it, since most TTS engines are not thread-safe."""
    system = platform.system()

    if system == "Windows":
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")

            def speak_sapi(text: str) -> None:
                voice.Speak(text)

            return speak_sapi
        except Exception:
            pass  # fall through to pyttsx3

        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", config.SPEECH_RATE_WPM)

            def speak_pyttsx3(text: str) -> None:
                engine.say(text)
                engine.runAndWait()

            return speak_pyttsx3
        except Exception:
            pass

    elif system == "Darwin":
        def speak_say(text: str) -> None:
            subprocess.run(["say", text], check=False)

        return speak_say

    else:  # Linux and everything else
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", config.SPEECH_RATE_WPM)

            def speak_pyttsx3(text: str) -> None:
                engine.say(text)
                engine.runAndWait()

            return speak_pyttsx3
        except Exception:
            pass

    def speak_fallback(text: str) -> None:
        print(f"[SPEECH] {text}")

    return speak_fallback


class SpeechEngine:
    """Background TTS worker with a priority queue and a mute toggle."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._items: List[Tuple[int, int, str]] = []  # (priority, seq, text)
        self._seq = 0
        self._mute = False
        self._last_spoken: Optional[str] = None
        self._running = True
        self._backend_ready = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # -- public API ----------------------------------------------------

    def say(self, text: str, priority: int = config.PRIORITY_INFO) -> None:
        with self._cv:
            if priority >= config.PRIORITY_CRITICAL:
                # Flush anything less urgent so the critical message is next.
                self._items = [it for it in self._items if it[0] >= config.PRIORITY_CRITICAL]
            self._seq += 1
            self._items.append((priority, self._seq, text))
            self._items.sort(key=lambda it: (-it[0], it[1]))
            self._cv.notify()

    def set_mute(self, muted: bool) -> None:
        with self._lock:
            self._mute = muted

    def toggle_mute(self) -> bool:
        with self._lock:
            self._mute = not self._mute
            return self._mute

    def repeat_last(self) -> None:
        with self._lock:
            last = self._last_spoken
        if last:
            self.say(last, priority=config.PRIORITY_INFO)

    def stop(self, timeout: float = 1.0) -> None:
        with self._cv:
            self._running = False
            self._cv.notify_all()
        self._thread.join(timeout=timeout)

    # -- worker thread ---------------------------------------------------

    def _worker(self) -> None:
        backend = _build_backend()
        self._backend_ready.set()
        while True:
            with self._cv:
                while not self._items and self._running:
                    self._cv.wait(timeout=0.5)
                if not self._running and not self._items:
                    return
                if not self._items:
                    continue
                _priority, _seq, text = self._items.pop(0)
                muted = self._mute

            if muted:
                continue

            with self._lock:
                self._last_spoken = text
            try:
                backend(text)
            except Exception as exc:  # never crash the main loop over speech
                print(f"[speech] backend failed ({exc}); message was: {text}")


if __name__ == "__main__":
    print("=== speech.py self-test ===")
    engine = SpeechEngine()
    engine._backend_ready.wait(timeout=5)

    print("Speaking 3 sentences with different priorities...")
    engine.say("This is an information level message.", config.PRIORITY_INFO)
    time.sleep(0.2)
    engine.say("This is an obstacle level warning.", config.PRIORITY_OBSTACLE)
    time.sleep(0.2)
    engine.say("Stop. This is a critical alert.", config.PRIORITY_CRITICAL)

    time.sleep(3.0)
    print("Testing mute...")
    engine.set_mute(True)
    engine.say("You should not hear this.", config.PRIORITY_INFO)
    time.sleep(1.0)
    engine.set_mute(False)

    print("Testing repeat...")
    engine.repeat_last()
    time.sleep(1.5)

    engine.stop()
    print("=== speech.py self-test complete (no crash = pass) ===")
