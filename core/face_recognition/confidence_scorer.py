"""
core/face_recognition/confidence_scorer.py

Two responsibilities:
    1. Convert a raw face-distance value (lower = more similar) into
       a human-readable 0-1 confidence score, scaled against the
       active recognition threshold.
    2. Temporal smoothing across consecutive frames: a single-frame
       match can flicker (lighting, motion blur, partial occlusion),
       so this tracks a short rolling window of recent matches per
       student and only confirms a "stable" recognition once the
       same student has matched consistently across enough frames -
       this is what should gate AttendanceModel.mark_attendance()
       calls in face_recognition_page.py, rather than marking on the
       very first frame a face is seen.

Usage:
    from core.face_recognition.confidence_scorer import confidence_scorer

    confidence = confidence_scorer.distance_to_confidence(distance, threshold)

    # Temporal smoothing (call once per frame, per detected face):
    stable = confidence_scorer.observe(student_id, confidence)
    if stable:
        mark_attendance(student_id)
"""

import logging
import time
from collections import deque

logger = logging.getLogger("SmartAttendAI.core.face_recognition.confidence_scorer")

DEFAULT_WINDOW_SIZE = 5          # frames to consider per student
DEFAULT_MIN_CONSISTENT_HITS = 3  # of the window, how many must match to confirm
DEFAULT_OBSERVATION_TTL_SEC = 5.0  # drop stale per-student tracking after this long unseen


class ConfidenceScorer:
    """
    Stateless distance->confidence conversion, plus stateful temporal
    smoothing to reduce false positives / single-frame flicker before
    attendance is actually marked.
    """

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        min_consistent_hits: int = DEFAULT_MIN_CONSISTENT_HITS,
        observation_ttl_sec: float = DEFAULT_OBSERVATION_TTL_SEC,
    ):
        self.window_size = window_size
        self.min_consistent_hits = min_consistent_hits
        self.observation_ttl_sec = observation_ttl_sec

        # student_id -> deque[confidence values, most recent last]
        self._history = {}
        # student_id -> last_seen timestamp (for TTL cleanup)
        self._last_seen = {}
        # student_id -> bool, whether this student has already been
        # confirmed stable this session (avoids re-triggering every frame)
        self._confirmed = set()

    # ------------------------------------------------------------
    # Distance -> confidence
    # ------------------------------------------------------------
    @staticmethod
    def distance_to_confidence(distance: float, threshold: float) -> float:
        """
        Maps a face_recognition distance (0 = identical, ~1+ = very
        different) to a 0-1 confidence score, scaled so that a
        distance at the threshold reads as roughly 50% confidence and
        distance 0 reads as 100%.
        """
        if threshold <= 0:
            return 0.0
        raw = 1.0 - (distance / (threshold * 2))
        return max(0.0, min(1.0, raw))

    # ------------------------------------------------------------
    # Temporal smoothing
    # ------------------------------------------------------------
    def observe(self, student_id: int, confidence: float, min_confidence: float = 0.0) -> bool:
        """
        Records a single-frame observation for `student_id` and
        returns True once this student has matched consistently
        enough (within the rolling window) to be treated as a
        confirmed, stable recognition - not just a lucky single frame.

        Returns False on every call after the first confirmation for
        this student (so callers can safely call this every frame
        without re-triggering mark_attendance repeatedly) - call
        reset(student_id) to allow re-confirmation (e.g. new session).
        """
        self._cleanup_stale()

        now = time.time()
        self._last_seen[student_id] = now

        if student_id not in self._history:
            self._history[student_id] = deque(maxlen=self.window_size)
        self._history[student_id].append(confidence)

        if student_id in self._confirmed:
            return False  # already confirmed this session - don't re-fire

        hits = sum(1 for c in self._history[student_id] if c >= min_confidence)
        if hits >= self.min_consistent_hits:
            self._confirmed.add(student_id)
            logger.debug(
                "Student %s confirmed stable: %d/%d recent frames matched.",
                student_id, hits, len(self._history[student_id]),
            )
            return True

        return False

    def is_confirmed(self, student_id: int) -> bool:
        return student_id in self._confirmed

    def reset(self, student_id: int = None):
        """Reset tracking for one student, or all students if student_id is None."""
        if student_id is None:
            self._history.clear()
            self._last_seen.clear()
            self._confirmed.clear()
            return

        self._history.pop(student_id, None)
        self._last_seen.pop(student_id, None)
        self._confirmed.discard(student_id)

    def average_confidence(self, student_id: int) -> float:
        history = self._history.get(student_id)
        if not history:
            return 0.0
        return sum(history) / len(history)

    def _cleanup_stale(self):
        """Drop tracking for students not seen recently, so memory doesn't grow unbounded across a long session."""
        now = time.time()
        stale_ids = [
            sid for sid, last_seen in self._last_seen.items()
            if now - last_seen > self.observation_ttl_sec
        ]
        for sid in stale_ids:
            self._history.pop(sid, None)
            self._last_seen.pop(sid, None)
            self._confirmed.discard(sid)


# Singleton instance - import this everywhere instead of instantiating directly
confidence_scorer = ConfidenceScorer()