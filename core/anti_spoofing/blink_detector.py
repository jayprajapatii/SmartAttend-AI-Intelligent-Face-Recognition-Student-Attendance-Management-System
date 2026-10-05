"""
core/anti_spoofing/blink_detector.py

Blink detection via Eye Aspect Ratio (EAR) computed from MediaPipe
Face Mesh eye landmarks. A blink is a strong liveness signal: a
printed photo or a static video frame cannot blink on demand.

EAR formula (Soukupova & Cech, 2016): ratio of vertical eye-landmark
distances to horizontal eye-landmark distance. EAR drops sharply
during a blink and recovers immediately after.

Usage:
    from core.anti_spoofing.blink_detector import BlinkDetector

    detector = BlinkDetector()

    # Per frame, per tracked face:
    blinked = detector.update(session_id, frame_bgr)
    if blinked:
        print("Blink detected - liveness signal confirmed.")
"""

import logging
from collections import deque

import numpy as np

logger = logging.getLogger("SmartAttendAI.core.anti_spoofing.blink_detector")

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logger.warning("mediapipe not installed - blink detection unavailable.")

# MediaPipe Face Mesh landmark indices for eye contour points used in EAR.
# Order per eye: [outer_corner, top1, top2, inner_corner, bottom2, bottom1]
LEFT_EYE_IDX = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]

DEFAULT_EAR_THRESHOLD = 0.21     # below this = eye considered closed
DEFAULT_CONSEC_FRAMES = 2        # frames EAR must stay low to count as a real blink (not noise)
DEFAULT_HISTORY_SIZE = 30        # rolling EAR history per session, for smoothing/debugging


class BlinkDetector:
    """
    Stateful blink detector: tracks EAR over consecutive frames per
    "session" (typically one per actively-recognized face/student) and
    reports True the moment a full blink (close -> reopen) completes.
    """

    def __init__(
        self,
        ear_threshold: float = DEFAULT_EAR_THRESHOLD,
        consec_frames: int = DEFAULT_CONSEC_FRAMES,
    ):
        self.ear_threshold = ear_threshold
        self.consec_frames = consec_frames

        self._face_mesh = None
        if MEDIAPIPE_AVAILABLE:
            try:
                self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False, max_num_faces=1,
                    refine_landmarks=False, min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
            except Exception as exc:
                logger.error("Failed to initialize MediaPipe Face Mesh: %s", exc)
                self._face_mesh = None

        # session_id -> state dict
        self._sessions = {}

    def is_available(self) -> bool:
        return MEDIAPIPE_AVAILABLE and self._face_mesh is not None

    # ------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------
    def update(self, session_id, frame_bgr: np.ndarray) -> bool:
        """
        Feed one frame for the given session. Returns True exactly on
        the frame where a completed blink (eyes were closed for
        `consec_frames`+ frames, then reopened) is detected.
        """
        if not self.is_available():
            return False

        ear = self._compute_ear(frame_bgr)
        if ear is None:
            return False

        state = self._sessions.setdefault(session_id, {
            "history": deque(maxlen=DEFAULT_HISTORY_SIZE),
            "closed_frames": 0,
            "blink_count": 0,
        })
        state["history"].append(ear)

        if ear < self.ear_threshold:
            state["closed_frames"] += 1
            return False

        # Eye is open this frame - check if we just came out of a
        # sufficiently long closed streak, i.e. a completed blink.
        if state["closed_frames"] >= self.consec_frames:
            state["closed_frames"] = 0
            state["blink_count"] += 1
            logger.debug("Blink detected for session=%s (total this session: %d).", session_id, state["blink_count"])
            return True

        state["closed_frames"] = 0
        return False

    def get_blink_count(self, session_id) -> int:
        state = self._sessions.get(session_id)
        return state["blink_count"] if state else 0

    def reset(self, session_id=None):
        if session_id is None:
            self._sessions.clear()
        else:
            self._sessions.pop(session_id, None)

    # ------------------------------------------------------------
    # EAR computation
    # ------------------------------------------------------------
    def _compute_ear(self, frame_bgr: np.ndarray):
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return None

        landmarks = results.multi_face_landmarks[0].landmark
        height, width = frame_bgr.shape[:2]

        def to_px(idx):
            lm = landmarks[idx]
            return np.array([lm.x * width, lm.y * height])

        left_ear = self._eye_aspect_ratio([to_px(i) for i in LEFT_EYE_IDX])
        right_ear = self._eye_aspect_ratio([to_px(i) for i in RIGHT_EYE_IDX])
        return (left_ear + right_ear) / 2.0

    @staticmethod
    def _eye_aspect_ratio(points: list) -> float:
        """points: [outer, top1, top2, inner, bottom2, bottom1] as (x, y) arrays."""
        outer, top1, top2, inner, bottom2, bottom1 = points

        vertical_1 = np.linalg.norm(top1 - bottom1)
        vertical_2 = np.linalg.norm(top2 - bottom2)
        horizontal = np.linalg.norm(outer - inner)

        if horizontal == 0:
            return 0.0
        return (vertical_1 + vertical_2) / (2.0 * horizontal)


# Singleton instance - import this everywhere instead of instantiating directly
blink_detector = BlinkDetector()