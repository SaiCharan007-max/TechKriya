"""
Drishti configuration. ALL tunable thresholds live here -- no magic numbers
in the other modules.
"""

# ---------------------------------------------------------------------------
# Frame / input
# ---------------------------------------------------------------------------
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# ---------------------------------------------------------------------------
# Vision: detection
# ---------------------------------------------------------------------------
YOLO_MODEL_PATH = "yolo11n.pt"
YOLO_CONF_THRESHOLD = 0.4
YOLO_IMGSZ = 480
TRACKER_CONFIG = "bytetrack.yaml"

# Classes we care about (COCO names) -> approximate real-world height, metres.
# Used for the pinhole-camera distance estimate.
CLASS_HEIGHTS_M = {
    "person": 1.65,
    "bicycle": 1.0,
    "motorcycle": 1.1,
    "car": 1.5,
    "bus": 3.0,
    "truck": 3.0,
    "dog": 0.55,
    "cow": 1.4,
    "bench": 0.85,
    "chair": 0.9,
    "fire hydrant": 0.8,
    "parking meter": 1.3,
    "potted plant": 0.8,
    "suitcase": 0.65,
    "stop sign": 0.75,
}

# Friendlier names to speak aloud. Classes not listed here are spoken as-is.
SPOKEN_NAMES = {
    "motorcycle": "bike",
    "bicycle": "cycle",
    "parking meter": "pole",
    "potted plant": "plant pot",
}

# ---------------------------------------------------------------------------
# Vision: distance estimation
# ---------------------------------------------------------------------------
# Horizontal field of view of the camera, degrees. Tune per-webcam if needed.
CAMERA_HFOV_DEG = 70.0
DISTANCE_MIN_M = 0.5
DISTANCE_MAX_M = 30.0
DISTANCE_EMA_ALPHA = 0.4  # smoothing factor per track id (higher = more reactive)

# ---------------------------------------------------------------------------
# Vision: walking corridor / zones
# ---------------------------------------------------------------------------
CORRIDOR_LEFT_FRAC = 0.30   # corridor spans [0.30W, 0.70W]
CORRIDOR_RIGHT_FRAC = 0.70
IN_PATH_OVERLAP_FRAC = 0.30  # box must overlap corridor by >= 30% of its width

# ---------------------------------------------------------------------------
# Vision: approach detection
# ---------------------------------------------------------------------------
APPROACH_HISTORY_SECONDS = 1.5
APPROACH_MIN_HISTORY_SECONDS = 0.5
APPROACH_CLOSING_SPEED_MIN_MPS = 2.0
APPROACH_TTC_MAX_S = 4.0
APPROACH_DISTANCE_MAX_M = 15.0
APPROACH_CLASSES = {"bicycle", "motorcycle", "car", "bus", "truck", "dog", "cow"}
TRACK_STALE_SECONDS = 2.0  # forget a track's history if unseen this long

# ---------------------------------------------------------------------------
# Decision engine: obstacle thresholds
# ---------------------------------------------------------------------------
OBSTACLE_DISTANCE_M = 3.5      # nearest in-path object closer than this -> OBSTACLE
OBSTACLE_STOP_DISTANCE_M = 1.3  # closer than this -> "Stop. X right in front."
SIDE_CHECK_DISTANCE_M = 4.0     # how far to look when picking the clearer side

# ---------------------------------------------------------------------------
# Decision engine: anti-chatter / cooldowns (seconds)
# ---------------------------------------------------------------------------
COOLDOWN_APPROACH_S = 4.0
COOLDOWN_OBSTACLE_S = 5.0
GLOBAL_MESSAGE_GAP_S = 2.5      # min gap between two non-critical messages
POST_CRITICAL_SUPPRESS_S = 2.0  # suppress lower priorities right after a CRITICAL
DECISION_LOG_MAXLEN = 8

# ---------------------------------------------------------------------------
# Speech
# ---------------------------------------------------------------------------
SPEECH_RATE_WPM = 180

# Priority levels (higher number = more important). Used by decision.py and
# speech.py's priority queue.
PRIORITY_INFO = 0
PRIORITY_NAVIGATION = 1
PRIORITY_OBSTACLE = 2
PRIORITY_CRITICAL = 3

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
TARGET_MIN_FPS = 8.0
DETECT_EVERY_N_FRAMES = 2  # re-run YOLO every Nth frame when FPS is too low

# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------
HUD_WINDOW_WIDTH = 1000
HUD_WINDOW_HEIGHT = 480
HUD_SIDE_PANEL_WIDTH = 360
HUD_BANNER_FADE_S = 3.0
HUD_LOG_LINES = 8

COLOR_SAFE = (60, 200, 60)
COLOR_CAUTION = (0, 200, 255)
COLOR_DANGER = (0, 0, 255)
COLOR_FAR_BOX = (60, 200, 60)      # green
COLOR_IN_PATH_BOX = (0, 165, 255)  # orange
COLOR_ALERT_BOX = (0, 0, 255)      # red
COLOR_PANEL_BG = (25, 25, 25)
COLOR_TEXT = (230, 230, 230)

# ---------------------------------------------------------------------------
# Stretch A: scene description
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DESCRIBE_PROMPT = (
    "You are guiding a blind pedestrian. In at most 2 short sentences, "
    "describe the scene ahead: path, obstacles, people, vehicles and their "
    "positions (left/ahead/right). No filler."
)

# ---------------------------------------------------------------------------
# Stretch B: simulated navigation
# ---------------------------------------------------------------------------
ROUTE_CACHE_PATH = "route.json"
WALK_SPEED_MPS = 1.3
NAV_ANNOUNCE_FAR_M = 25.0
NAV_ANNOUNCE_NEAR_M = 8.0
NAV_OBSTACLE_FUSION_DISTANCE_M = 3.0
