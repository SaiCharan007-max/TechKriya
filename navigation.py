"""
navigation.py -- Stretch B: simulated route navigation, per CLAUDE.md 4.8.

Fetches a real walking route once (OpenRouteService foot-walking, or Google
Routes API WALK -- whichever API key is set), caches it to `route.json` so
the demo still works with no network on stage, then simulates walking the
route at a fixed speed (or step-by-step with a key), emitting spoken turn
prompts that `decision.py` fuses with live obstacle detections.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional, Tuple

import requests

import config


def _side_from_instruction(text: str) -> Optional[str]:
    lower = text.lower()
    if "left" in lower:
        return "left"
    if "right" in lower:
        return "right"
    return None


def fetch_route(start: Tuple[float, float], end: Tuple[float, float],
                 cache_path: str = config.ROUTE_CACHE_PATH) -> Optional[dict]:
    """Fetch a walking route once and cache it to disk. Returns the route
    dict, or None if no provider key is set or the request fails -- callers
    must treat that as "navigation not available", not a crash."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            pass  # corrupt cache -- fall through and re-fetch

    ors_key = os.environ.get("ORS_API_KEY")
    google_key = os.environ.get("GOOGLE_MAPS_API_KEY")

    try:
        if ors_key:
            route = _fetch_ors(start, end, ors_key)
        elif google_key:
            route = _fetch_google(start, end, google_key)
        else:
            print("[navigation] no ORS_API_KEY or GOOGLE_MAPS_API_KEY set.")
            return None
    except Exception as exc:
        print(f"[navigation] route fetch failed: {exc}")
        return None

    try:
        with open(cache_path, "w") as f:
            json.dump(route, f)
    except Exception as exc:
        print(f"[navigation] could not cache route: {exc}")
    return route


def _fetch_ors(start: Tuple[float, float], end: Tuple[float, float], api_key: str) -> dict:
    url = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": [[start[1], start[0]], [end[1], end[0]]]}  # ORS wants [lon, lat]
    resp = requests.post(url, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    feature = data["features"][0]
    coords = feature["geometry"]["coordinates"]  # [[lon, lat], ...]
    steps_raw = feature["properties"]["segments"][0]["steps"]

    steps = []
    cum = 0.0
    for s in steps_raw:
        cum += s["distance"]
        p0, p1 = s["way_points"]
        steps.append({
            "instruction": s["instruction"],
            "distance_m": s["distance"],
            "cum_distance_m": cum,
            "coords": coords[p0:p1 + 1],
        })
    return {"provider": "ors", "coords": coords, "steps": steps,
            "total_distance_m": feature["properties"]["summary"]["distance"]}


def _fetch_google(start: Tuple[float, float], end: Tuple[float, float], api_key: str) -> dict:
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.legs.steps.navigationInstruction,"
                             "routes.legs.steps.distanceMeters,routes.distanceMeters",
    }
    body = {
        "origin": {"location": {"latLng": {"latitude": start[0], "longitude": start[1]}}},
        "destination": {"location": {"latLng": {"latitude": end[0], "longitude": end[1]}}},
        "travelMode": "WALK",
    }
    resp = requests.post(url, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    route = data["routes"][0]

    steps = []
    cum = 0.0
    for leg in route.get("legs", []):
        for s in leg.get("steps", []):
            dist = s.get("distanceMeters", 0)
            cum += dist
            instr = s.get("navigationInstruction", {}).get("instructions", "Continue")
            steps.append({"instruction": instr, "distance_m": dist,
                          "cum_distance_m": cum, "coords": []})
    return {"provider": "google", "coords": [], "steps": steps,
            "total_distance_m": route.get("distanceMeters", cum)}


class Navigator:
    """Simulates walking a cached route and emits spoken turn-prompt events
    that main.py feeds into decision.py as `nav_event`."""

    def __init__(self, route: dict):
        self.route = route
        self.steps: List[dict] = route.get("steps", [])
        self.total_distance: float = route.get("total_distance_m", 0.0)
        self.traveled = 0.0
        self.active = False
        self._far_announced: set = set()
        self._near_announced: set = set()
        self._arrived = False

    def start(self) -> None:
        self.active = True

    def toggle(self) -> bool:
        self.active = not self.active
        return self.active

    def _current_step_index(self) -> Optional[int]:
        for i, s in enumerate(self.steps):
            if self.traveled < s["cum_distance_m"]:
                return i
        return None

    def advance(self, dt: float) -> Optional[dict]:
        """Auto-walk by dt seconds at the configured walking speed."""
        if not self.active or self._arrived:
            return None
        return self._tick(config.WALK_SPEED_MPS * dt)

    def step_once(self, meters: float = 5.0) -> Optional[dict]:
        """Manual single step, for a demo where auto-walk isn't desired."""
        return self._tick(meters)

    def _tick(self, delta_m: float) -> Optional[dict]:
        if self._arrived or not self.steps:
            return None
        self.traveled = min(self.traveled + delta_m, self.total_distance)
        idx = self._current_step_index()

        if idx is None:
            self._arrived = True
            self.active = False
            return {"message": "You have arrived.", "step": "arrive", "side": None}

        step = self.steps[idx]
        remaining = step["cum_distance_m"] - self.traveled
        side = _side_from_instruction(step["instruction"])

        if remaining <= config.NAV_ANNOUNCE_NEAR_M and idx not in self._near_announced:
            self._near_announced.add(idx)
            message = f"Turn {side} now." if side else "Continue straight."
            return {"message": message, "step": f"near-{idx}", "side": side}

        if remaining <= config.NAV_ANNOUNCE_FAR_M and idx not in self._far_announced:
            self._far_announced.add(idx)
            message = (f"In {round(remaining)} metres, turn {side}." if side
                       else f"In {round(remaining)} metres, continue straight.")
            return {"message": message, "step": f"far-{idx}", "side": side}

        return None

    # -- for the HUD mini-map / side panel --

    def progress_fraction(self) -> float:
        if self.total_distance <= 0:
            return 0.0
        return min(1.0, self.traveled / self.total_distance)

    def next_turn_info(self) -> Optional[Tuple[str, float]]:
        """(instruction, metres remaining to it), or None once arrived."""
        idx = self._current_step_index()
        if idx is None:
            return None
        step = self.steps[idx]
        return step["instruction"], step["cum_distance_m"] - self.traveled


if __name__ == "__main__":
    print("=== navigation.py self-test (no network -- synthetic route) ===")
    synthetic = {
        "provider": "synthetic",
        "coords": [],
        "steps": [
            {"instruction": "Head north", "distance_m": 40.0, "cum_distance_m": 40.0, "coords": []},
            {"instruction": "Turn left onto Main St", "distance_m": 30.0, "cum_distance_m": 70.0, "coords": []},
            {"instruction": "Arrive at destination", "distance_m": 0.0, "cum_distance_m": 70.0, "coords": []},
        ],
        "total_distance_m": 70.0,
    }
    nav = Navigator(synthetic)
    nav.start()
    events = []
    t = 0.0
    while nav.active and t < 120:
        ev = nav.advance(1.0)
        if ev:
            events.append(ev)
        t += 1.0
    for e in events:
        print(" ", e)
    assert any(e["step"].startswith("far-") for e in events)
    assert any(e["step"].startswith("near-") for e in events)
    assert events[-1]["step"] == "arrive"
    print("=== navigation.py self-test complete (all events fired, no crash) ===")
