"""
core/anti_spoofing/head_movement_detector.py

Head movement / pose-variance liveness signal: tracks an estimated
head yaw/pitch angle (or, as a lightweight fallback, raw face-box
centroid position) over a short rolling window and checks that it
varies naturally - a printed photo held in front of the camera stays
essentially motionless, while a live person exhibits small
involuntary head movement even when trying to stay still.

Also guards against the opposite spoofing attempt (rapidly panning a
phone/tablet playing a video) by rejecting movement that's too large
or too erratic to be natural head motion.

Usage:
    from core.anti_spoofing.head_movement_detector import HeadMovementDetector

    detector = HeadMovementDetector()

    natural_movement = detector.update(session_id, frame_bgr, face_box)
    if natural_movement:
        print("Natural head movement observed - liveness signal confirmed.")
"""

import logging
from collections import deque

import numpy as np

logger = logging.getLogger("SmartAttendAI.core.anti_spoofing.head_movement_detector")

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logger.warning("mediapipe not installed - head-pose tracking unavailable; falling back to centroid tracking.")

# MediaPipe Face Mesh landmarks used for a rough yaw/pitch estimate
NOSE_TIP = 1
CHIN = 152
LEFT_EYE_OUTER = 33
RIGHT_EYE_OUTER = 263
FOREHEAD = 10

DEFAULT_WINDOW_SIZE = 20          # frames of history to evaluate
DEFAULT_MIN_VARIANCE = 0.4        # degrees^2 (pose mode) or px^2 (centroid mode) - below = "too static"
DEFAULT_MAX_JUMP = 25.0           # degrees (pose) or px (centroid) - single-frame jump above this = erratic/rejected
DEFAULT_MIN_SAMPLES = 8           # minimum frames collected before a verdict can be given


class HeadMovementDetector:
    """
    Stateful per-session head movement tracker. Prefers MediaPipe
    Face Mesh for a real yaw/pitch estimate; falls back to simple
    face-box centroid tracking (still useful - even a
    centroid-only signal distinguishes a static photo from natural
    handheld/head micro-motion) if MediaPipe isn't available.
    """

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        min_variance: float = DEFAULT_MIN_VARIANCE,
        max_jump: float = DEFAULT_MAX_JUMP,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ):
        self.window_size = window_size
        self.min_variance = min_variance
        self.max_jump = max_jump
        self.min_samples = min_samples

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

        # session_id -> deque of (x, y) pose-proxy or centroid samples
        self._sessions = {}
        # session_id -> True once erratic/rejected motion has been seen
        self._rejected = {}

    @property
    def mode(self) -> str:
        return "pose" if self._face_mesh is not None else "centroid"

    # ------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------
    def update(self, session_id, frame_bgr: np.ndarray, face_box=None) -> bool:
        """
        Feed one frame for the given session. Returns True once
        enough samples have been collected AND the observed motion
        falls in the "natural" band (neither frozen-still nor
        erratic). Returns False while still collecting samples or if
        erratic motion was detected (session flagged as suspicious
        until reset()).
        """
        sample = self._extract_sample(frame_bgr, face_box)
        if sample is None:
            return False

        history = self._sessions.setdefault(session_id, deque(maxlen=self.window_size))

        if history and self._rejected.get(session_id):
            return False  # already flagged erratic this session

        if history:
            jump = float(np.linalg.norm(np.array(sample) - np.array(history[-1])))
            if jump > self.max_jump:
                logger.debug("Erratic motion detected for session=%s (jump=%.1f) - flagging.", session_id, jump)
                self._rejected[session_id] = True
                return False

        history.append(sample)

        if len(history) < self.min_samples:
            return False

        variance = self._positional_variance(history)
        is_natural = variance >= self.min_variance
        return is_natural

    def get_variance(self, session_id) -> float:
        history = self._sessions.get(session_id)
        if not history or len(history) < 2:
            return 0.0
        return self._positional_variance(history)

    def is_rejected(self, session_id) -> bool:
        return self._rejected.get(session_id, False)

    def reset(self, session_id=None):
        if session_id is None:
            self._sessions.clear()
            self._rejected.clear()
        else:
            self._sessions.pop(session_id, None)
            self._rejected.pop(session_id, None)

    # ------------------------------------------------------------
    # Sample extraction
    # ------------------------------------------------------------
    def _extract_sample(self, frame_bgr: np.ndarray, face_box):
        if self._face_mesh is not None:
            pose = self._estimate_pose(frame_bgr)
            if pose is not None:
                return pose
            # fall through to centroid if landmarks weren't found this frame

        if face_box is not None:
            return (face_box.x + face_box.w / 2, face_box.y + face_box.h / 2)

        return None

    def _estimate_pose(self, frame_bgr: np.ndarray):
        """
        Very lightweight yaw/pitch proxy (not a full solvePnP pose
        estimate): uses relative landmark offsets to approximate head
        rotation in degrees. Good enough to detect "is this head
        moving at all" without needing camera calibration.
        """
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

        nose = to_px(NOSE_TIP)
        chin = to_px(CHIN)
        forehead = to_px(FOREHEAD)
        left_eye = to_px(LEFT_EYE_OUTER)
        right_eye = to_px(RIGHT_EYE_OUTER)

        # Yaw proxy: horizontal offset of nose from the eye midpoint,
        # normalized by inter-eye distance.
        eye_midpoint = (left_eye + right_eye) / 2
        eye_distance = np.linalg.norm(right_eye - left_eye) or 1.0
        yaw_proxy = float((nose[0] - eye_midpoint[0]) / eye_distance) * 45.0  # scaled to ~degrees

        # Pitch proxy: vertical offset of nose relative to forehead-chin line.
        face_height = np.linalg.norm(chin - forehead) or 1.0
        pitch_proxy = float((nose[1] - (forehead[1] + chin[1]) / 2) / face_height) * 45.0

        return (yaw_proxy, pitch_proxy)

    @staticmethod
    def _positional_variance(history: deque) -> float:
        points = np.array(history)
        return float(np.mean(np.var(points, axis=0)))


# Singleton instance - import this everywhere instead of instantiating directly
head_movement_detector = HeadMovementDetector()