"""
decision.py -- the priority decision engine, the heart of Drishti.

Takes the current frame's Detection list (from vision.py) and returns at most
one message to speak, applying the priority order and anti-chatter rules from
CLAUDE.md section 4.3:

  1. CRITICAL   - an approaching object
  2. OBSTACLE   - the nearest in-path object closer than a threshold
  3. NAVIGATION - turn prompts (stretch goal, fed in via `nav_event`)
  4. INFO       - silence, or a one-off "Path clear."
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

import config
from vision import Detection


@dataclass
class DecisionResult:
    message: Optional[str]
    priority: Optional[int]
    flush: bool  # True for CRITICAL: caller should clear pending speech


def _side_phrase(side: str) -> str:
    return "ahead" if side == "ahead" else f"from the {side}"


class DecisionEngine:
    def __init__(self):
        # message_key -> {"time": float, "distance": float}
        self._last_spoken: Dict[str, dict] = {}
        # track_id -> {"category": str, "distance": float}  (for escalation checks)
        self._track_state: Dict[int, dict] = {}
        self._last_message_time: float = -1e9
        self._suppress_until: float = -1e9
        self._obstacle_active: bool = False
        self.decision_log: Deque[str] = deque(maxlen=config.DECISION_LOG_MAXLEN)
        self.critical_count: int = 0
        self.obstacle_count: int = 0

    # -- helpers -----------------------------------------------------------

    def _is_escalated(self, track_id: int, new_category: str, new_distance: float) -> bool:
        prev = self._track_state.get(track_id)
        if prev is None:
            return False
        was_obstacle_now_approaching = prev["category"] != "approaching" and new_category == "approaching"
        dropped_below_stop = (
            new_distance < config.OBSTACLE_STOP_DISTANCE_M
            and prev["distance"] >= config.OBSTACLE_STOP_DISTANCE_M
        )
        return was_obstacle_now_approaching or dropped_below_stop

    def _pick_side(self, detections: List[Detection], exclude_id: int) -> Optional[str]:
        """Pick the clearer side to step to. None means both sides are blocked."""
        left = [d for d in detections if d.side == "left" and d.id != exclude_id
                and d.distance <= config.SIDE_CHECK_DISTANCE_M]
        right = [d for d in detections if d.side == "right" and d.id != exclude_id
                 and d.distance <= config.SIDE_CHECK_DISTANCE_M]

        left_blocked = any(d.distance <= config.OBSTACLE_STOP_DISTANCE_M for d in left)
        right_blocked = any(d.distance <= config.OBSTACLE_STOP_DISTANCE_M for d in right)
        if left_blocked and right_blocked:
            return None
        if left_blocked:
            return "right"
        if right_blocked:
            return "left"

        if len(left) != len(right):
            return "left" if len(left) < len(right) else "right"

        left_min = min((d.distance for d in left), default=float("inf"))
        right_min = min((d.distance for d in right), default=float("inf"))
        return "left" if left_min >= right_min else "right"

    def _log(self, now: float, priority_name: str, reason: str, message: str):
        ts = time.strftime("%H:%M:%S", time.localtime(now))
        self.decision_log.append(f'{ts} [{priority_name}] {reason} -> "{message}"')

    # -- main entry point ----------------------------------------------------

    def decide(self, detections: List[Detection], now: Optional[float] = None,
               nav_event: Optional[dict] = None) -> DecisionResult:
        now = time.time() if now is None else now

        # 1. CRITICAL: approaching objects, prefer in_path, then most urgent (lowest ttc).
        approaching = [d for d in detections if d.approaching]
        if approaching:
            approaching.sort(key=lambda d: (not d.in_path, d.ttc if d.ttc is not None else 1e9))
            chosen = approaching[0]
            key = f"approach-{chosen.id}"
            prev = self._last_spoken.get(key)
            cooled_down = prev is None or (now - prev["time"]) >= config.COOLDOWN_APPROACH_S
            escalated = self._is_escalated(chosen.id, "approaching", chosen.distance)

            if cooled_down or escalated:
                message = f"Stop. {chosen.spoken_name.capitalize()} approaching {_side_phrase(chosen.side)}."
                reason = f"{chosen.spoken_name}#{chosen.id} closing {chosen.closing_speed} m/s, TTC {chosen.ttc} s"
                self._log(now, "CRITICAL", reason, message)
                self._last_spoken[key] = {"time": now, "distance": chosen.distance}
                self._track_state[chosen.id] = {"category": "approaching", "distance": chosen.distance}
                self._last_message_time = now
                self._suppress_until = now + config.POST_CRITICAL_SUPPRESS_S
                self.critical_count += 1
                return DecisionResult(message, config.PRIORITY_CRITICAL, flush=True)

            self._track_state[chosen.id] = {"category": "approaching", "distance": chosen.distance}

        # Recently issued a CRITICAL message: suppress everything else briefly.
        if now < self._suppress_until:
            return DecisionResult(None, None, flush=False)

        # 2. OBSTACLE: nearest in-path object under the obstacle threshold.
        in_path = [d for d in detections if d.in_path and d.distance < config.OBSTACLE_DISTANCE_M]
        obstacle_condition_now = bool(in_path)

        if in_path:
            in_path.sort(key=lambda d: d.distance)
            chosen = in_path[0]
            key = f"obstacle-{chosen.id}"
            prev = self._last_spoken.get(key)
            cooled_down = prev is None or (now - prev["time"]) >= config.COOLDOWN_OBSTACLE_S
            escalated = self._is_escalated(chosen.id, "obstacle", chosen.distance)
            gap_ok = now - self._last_message_time >= config.GLOBAL_MESSAGE_GAP_S

            if escalated or (cooled_down and gap_ok):
                if chosen.distance < config.OBSTACLE_STOP_DISTANCE_M:
                    message = f"Stop. {chosen.spoken_name.capitalize()} right in front."
                else:
                    side = self._pick_side(detections, chosen.id)
                    if side is None:
                        message = "Path blocked. Stop."
                    else:
                        message = f"{chosen.spoken_name.capitalize()} ahead, {round(chosen.distance)} metres. Step {side}."
                reason = f"{chosen.spoken_name}#{chosen.id} at {chosen.distance} m"
                self._log(now, "OBSTACLE", reason, message)
                self._last_spoken[key] = {"time": now, "distance": chosen.distance}
                self._track_state[chosen.id] = {"category": "obstacle", "distance": chosen.distance}
                self._last_message_time = now
                self._obstacle_active = True
                self.obstacle_count += 1
                return DecisionResult(message, config.PRIORITY_OBSTACLE, flush=False)

            self._track_state[chosen.id] = {"category": "obstacle", "distance": chosen.distance}

        # 3. NAVIGATION (stretch): handled by navigation.py feeding nav_event in.
        if nav_event and now - self._last_message_time >= config.GLOBAL_MESSAGE_GAP_S:
            message = nav_event.get("message")
            step_key = f"nav-{nav_event.get('step')}"
            if message and step_key not in self._last_spoken:
                turn_side = nav_event.get("side")
                if turn_side:
                    blocker = next(
                        (d for d in detections if d.side == turn_side
                         and d.distance <= config.NAV_OBSTACLE_FUSION_DISTANCE_M),
                        None,
                    )
                    if blocker:
                        message = f"Turn {turn_side} after the {blocker.spoken_name}."
                self._log(now, "NAVIGATION", f"step {nav_event.get('step')}", message)
                self._last_spoken[step_key] = {"time": now, "distance": 0.0}
                self._last_message_time = now
                self._obstacle_active = obstacle_condition_now
                return DecisionResult(message, config.PRIORITY_NAVIGATION, flush=False)

        # 4. INFO: announce "Path clear." once, when an obstacle warning stops applying.
        if self._obstacle_active and not obstacle_condition_now:
            if now - self._last_message_time >= config.GLOBAL_MESSAGE_GAP_S:
                self._obstacle_active = False
                message = "Path clear."
                self._log(now, "INFO", "obstacle cleared", message)
                self._last_message_time = now
                return DecisionResult(message, config.PRIORITY_INFO, flush=False)

        self._obstacle_active = obstacle_condition_now
        return DecisionResult(None, None, flush=False)


if __name__ == "__main__":
    print("=== decision.py self-test ===")

    def det(id_, label, distance, side, in_path, approaching=False, closing_speed=0.0, ttc=None):
        from config import SPOKEN_NAMES
        return Detection(
            id=id_, label=label, spoken_name=SPOKEN_NAMES.get(label, label), conf=0.9,
            box=(0, 0, 10, 10), distance=distance, side=side, in_path=in_path,
            closing_speed=closing_speed, ttc=ttc, approaching=approaching,
        )

    engine = DecisionEngine()
    t = 1000.0

    # 1. Approaching bike should trigger CRITICAL.
    r = engine.decide([det(1, "motorcycle", 8.0, "ahead", True, approaching=True,
                           closing_speed=4.1, ttc=2.2)], now=t)
    print(r.message)
    assert r.priority == config.PRIORITY_CRITICAL and "Stop" in r.message and "Bike" in r.message

    # 2. Same object, well inside its cooldown -> should NOT repeat (returns None,
    #    since we're within the post-critical suppression window too).
    r2 = engine.decide([det(1, "motorcycle", 7.5, "ahead", True, approaching=True,
                            closing_speed=4.0, ttc=2.0)], now=t + 0.5)
    print("repeat suppressed:", r2.message)
    assert r2.message is None

    # 3. After the post-critical suppression window and obstacle cooldown, a
    #    static chair in the path should trigger an OBSTACLE message.
    t2 = t + 3.0
    r3 = engine.decide([det(2, "chair", 2.0, "ahead", True)], now=t2)
    print(r3.message)
    assert r3.priority == config.PRIORITY_OBSTACLE and "Chair" in r3.message

    # 4. Same chair, immediately again -> suppressed by obstacle cooldown.
    r4 = engine.decide([det(2, "chair", 1.9, "ahead", True)], now=t2 + 0.2)
    print("chair repeat suppressed:", r4.message)
    assert r4.message is None

    # 5. Chair distance drops below the stop threshold -> escalation overrides cooldown.
    r5 = engine.decide([det(2, "chair", 1.0, "ahead", True)], now=t2 + 0.3)
    print(r5.message)
    assert "right in front" in r5.message

    # 6. Chair removed -> "Path clear." once, after the global gap has elapsed.
    t3 = t2 + 3.0
    r6 = engine.decide([], now=t3)
    print(r6.message)
    assert r6.message == "Path clear."
    r7 = engine.decide([], now=t3 + 0.1)
    assert r7.message is None

    print("Decision log:")
    for line in engine.decision_log:
        print(" ", line)

    print("All decision-engine checks passed.")
