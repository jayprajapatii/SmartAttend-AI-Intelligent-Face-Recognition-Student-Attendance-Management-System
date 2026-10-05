"""
core/anti_spoofing/liveness_detector.py

Combines blink_detector and head_movement_detector into a single
liveness verdict per recognition session. This is the module
ui/pages/face_recognition_page.py should call before setting
liveness_status=True on AttendanceModel.mark_attendance() - currently
that page hardcodes liveness_status=False with a TODO pointing here.

Liveness is confirmed once EITHER:
    - a completed blink is observed, OR
    - natural (non-static, non-erratic) head movement is observed
      across enough frames
within a bounded time window - requiring one completed within a
window (rather than an instant one-frame check) is what actually
defeats a printed photo or a paused video frame, since neither can
produce either signal on demand.

Usage:
    from core.anti_spoofing.liveness_detector import liveness_detector

    # Call once per frame, per actively-tracked face (e.g. keyed by
    # the matched student_id, or a temporary tracking id for unknowns):
    verdict = liveness_detector.update(session_id, frame_bgr, face_box)

    if verdict.is_live:
        # safe to mark attendance with liveness_status=True
        ...
    elif verdict.timed_out:
        # no liveness signal within the window - likely a spoof attempt
        flag_as_suspicious()
"""

import logging
import time
from dataclasses import dataclass

import numpy as np

from core.anti_spoofing.blink_detector import blink_detector
from core.anti_spoofing.head_movement_detector import head_movement_detector

logger = logging.getLogger("SmartAttendAI.core.anti_spoofing.liveness_detector")

DEFAULT_WINDOW_SEC = 4.0   # how long to wait for a liveness signal before giving up


@dataclass
class LivenessVerdict:
    is_live: bool
    method: str = ""          # "blink" | "head_movement" | "" (not yet confirmed)
    timed_out: bool = False
    elapsed_sec: float = 0.0


class LivenessDetector:
    """
    Stateful per-session liveness orchestrator. A "session" is
    typically one continuous observation of a single face - e.g. keyed
    by student_id once a face_recognition match is found, so the same
    student doesn't need to re-prove liveness every single frame
    within one attendance-marking attempt.
    """

    def __init__(self, window_sec: float = DEFAULT_WINDOW_SEC):
        self.window_sec = window_sec
        # session_id -> {"start_time": float, "confirmed": bool, "method": str}
        self._sessions = {}

    def is_available(self) -> bool:
        return blink_detector.is_available() or True  # centroid-based head movement always works as a fallback

    # ------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------
    def update(self, session_id, frame_bgr: np.ndarray, face_box=None) -> LivenessVerdict:
        """
        Feed one frame for the given session. Once liveness is
        confirmed for a session, subsequent calls keep returning
        is_live=True immediately (no need to re-detect) until
        reset(session_id) is called.
        """
        now = time.time()
        state = self._sessions.setdefault(session_id, {
            "start_time": now, "confirmed": False, "method": "",
        })

        if state["confirmed"]:
            return LivenessVerdict(is_live=True, method=state["method"])

        elapsed = now - state["start_time"]

        blinked = blink_detector.update(session_id, frame_bgr)
        if blinked:
            state["confirmed"] = True
            state["method"] = "blink"
            logger.info("Liveness confirmed via blink for session=%s (%.1fs).", session_id, elapsed)
            return LivenessVerdict(is_live=True, method="blink", elapsed_sec=elapsed)

        moved_naturally = head_movement_detector.update(session_id, frame_bgr, face_box)
        if moved_naturally:
            state["confirmed"] = True
            state["method"] = "head_movement"
            logger.info("Liveness confirmed via head movement for session=%s (%.1fs).", session_id, elapsed)
            return LivenessVerdict(is_live=True, method="head_movement", elapsed_sec=elapsed)

        if head_movement_detector.is_rejected(session_id):
            logger.warning("Erratic motion flagged for session=%s - possible spoof attempt.", session_id)

        if elapsed > self.window_sec:
            return LivenessVerdict(is_live=False, timed_out=True, elapsed_sec=elapsed)

        return LivenessVerdict(is_live=False, elapsed_sec=elapsed)

    def is_confirmed(self, session_id) -> bool:
        state = self._sessions.get(session_id)
        return bool(state and state["confirmed"])

    def reset(self, session_id=None):
        if session_id is None:
            self._sessions.clear()
        else:
            self._sessions.pop(session_id, None)
        blink_detector.reset(session_id)
        head_movement_detector.reset(session_id)

    def get_diagnostics(self, session_id) -> dict:
        """Useful for a debug overlay or security log detail."""
        return {
            "confirmed": self.is_confirmed(session_id),
            "method": self._sessions.get(session_id, {}).get("method", ""),
            "blink_count": blink_detector.get_blink_count(session_id),
            "head_movement_variance": head_movement_detector.get_variance(session_id),
            "head_movement_mode": head_movement_detector.mode,
            "erratic_motion_flagged": head_movement_detector.is_rejected(session_id),
        }


# Singleton instance - import this everywhere instead of instantiating directly
liveness_detector = LivenessDetector()