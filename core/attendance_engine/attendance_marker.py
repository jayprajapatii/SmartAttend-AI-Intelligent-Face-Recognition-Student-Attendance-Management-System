"""
core/attendance_engine/attendance_marker.py

The central orchestrator for turning "a face was recognized in a
frame" into "attendance was safely recorded". Composes:

    recognizer          -> who is this? (student_id, confidence)
    confidence_scorer    -> is this match stable across frames, not a
                            single-frame fluke?
    liveness_detector    -> has liveness (blink / natural head
                            movement) been proven for this session?
    mask_classifier       -> is a mask being worn, and does that
                            block/warn/allow per system_settings?
    AttendanceModel        -> the actual dedup'd DB write

ui/pages/face_recognition_page.py should call AttendanceMarker.process_frame()
once per camera frame instead of re-implementing this pipeline inline -
this is the single source of truth for "when is it actually safe to
mark someone present".

Usage:
    from core.attendance_engine.attendance_marker import attendance_marker

    attendance_marker.configure(subject_id=..., faculty_id=..., classroom=...)

    for frame in camera_frames:
        events = attendance_marker.process_frame(frame)
        for event in events:
            if event.status == "marked":
                show_toast(f"{event.student_name} marked present")
            elif event.status == "unknown":
                flag_security_alert(event)
"""

import logging
import time
from dataclasses import dataclass

import numpy as np

import config
from database.models.attendance_model import AttendanceModel
from database.models.student_model import StudentModel
from database.models.recognition_log_model import RecognitionLogModel
from database.models.security_log_model import SecurityLogModel
from database.db_connector import db

from core.face_recognition.recognizer import recognizer
from core.face_recognition.confidence_scorer import confidence_scorer
from core.anti_spoofing.liveness_detector import liveness_detector
from core.mask_detection.mask_classifier import mask_classifier
from core.face_detection.detector import detector, FaceBox

logger = logging.getLogger("SmartAttendAI.core.attendance_engine.attendance_marker")

UNKNOWN_ALERT_COOLDOWN_SEC = 15.0


@dataclass
class AttendanceEvent:
    """Result of processing one detected face for one frame."""
    status: str                  # "marked" | "already_marked" | "pending" | "blocked_mask" | "blocked_liveness" | "unknown"
    face_box: FaceBox = None
    student_id: int = None
    student_name: str = ""
    confidence: float = 0.0
    reason: str = ""
    mask_label: str = ""
    liveness_method: str = ""


class AttendanceMarker:
    """
    Stateful per-session orchestrator. Call configure() once at the
    start of a recognition session (subject/faculty/classroom
    context), then process_frame() once per camera frame.
    """

    def __init__(self):
        self.subject_id = None
        self.faculty_id = None
        self.classroom = None
        self._marked_this_session = set()
        self._last_unknown_alert_time = 0.0
        self._mask_policy = "Warn"  # loaded from system_settings on configure()

    def configure(self, subject_id: int = None, faculty_id: int = None, classroom: str = None):
        self.subject_id = subject_id
        self.faculty_id = faculty_id
        self.classroom = classroom
        self._marked_this_session = set()
        self._last_unknown_alert_time = 0.0
        self._mask_policy = self._load_mask_policy()

        loaded_count = recognizer.reload()
        logger.info(
            "AttendanceMarker configured: subject_id=%s faculty_id=%s classroom=%s mask_policy=%s "
            "(%d known encodings loaded).",
            subject_id, faculty_id, classroom, self._mask_policy, loaded_count,
        )

    @staticmethod
    def _load_mask_policy() -> str:
        try:
            row = db.fetch_one("SELECT mask_policy FROM system_settings ORDER BY setting_id DESC LIMIT 1")
            return row["mask_policy"] if row else "Warn"
        except Exception as exc:
            logger.warning("Could not load mask policy from system_settings, defaulting to 'Warn': %s", exc)
            return "Warn"

    def reset_session(self):
        """Clears session state without a full reconfigure (e.g. between classes on the same subject)."""
        self._marked_this_session = set()
        liveness_detector.reset()
        confidence_scorer.reset()

    # ------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------
    def process_frame(self, frame_bgr: np.ndarray) -> list:
        """Runs the full pipeline for every face detected in this frame. Returns a list of AttendanceEvent."""
        if not recognizer.is_ready():
            return []

        frame_results = recognizer.recognize_frame(frame_bgr)
        events = []

        for result in frame_results:
            if result.match.is_match:
                event = self._handle_match(frame_bgr, result)
            else:
                event = self._handle_unknown(result)
            events.append(event)

        return events

    # ------------------------------------------------------------
    # Matched face pipeline
    # ------------------------------------------------------------
    def _handle_match(self, frame_bgr, result) -> AttendanceEvent:
        student_id = result.match.student_id
        confidence = result.match.confidence

        if student_id in self._marked_this_session:
            return AttendanceEvent(
                status="already_marked", face_box=result.face_box,
                student_id=student_id, confidence=confidence,
            )

        # Temporal smoothing - require consistent matches across a few
        # frames before treating this as stable enough to proceed.
        stable = confidence_scorer.observe(student_id, confidence)
        if not stable and not confidence_scorer.is_confirmed(student_id):
            return AttendanceEvent(
                status="pending", face_box=result.face_box, student_id=student_id, confidence=confidence,
            )

        # Liveness check
        verdict = liveness_detector.update(student_id, frame_bgr, result.face_box)
        if not verdict.is_live:
            reason = "liveness_timeout" if verdict.timed_out else "awaiting_liveness_signal"
            if verdict.timed_out:
                logger.warning(
                    "Liveness not confirmed for student_id=%s within window - possible spoof attempt.", student_id
                )
                self._log_security_event(
                    "Spoof Attempt",
                    f"Liveness could not be confirmed for student_id={student_id} within the detection window.",
                )
            return AttendanceEvent(
                status="blocked_liveness", face_box=result.face_box, student_id=student_id,
                confidence=confidence, reason=reason,
            )

        # Mask policy check
        face_crop = detector.crop(frame_bgr, result.face_box)
        mask_result = mask_classifier.classify(face_crop)

        if mask_result.has_mask and self._mask_policy == "Deny":
            return AttendanceEvent(
                status="blocked_mask", face_box=result.face_box, student_id=student_id,
                confidence=confidence, mask_label=mask_result.label,
                reason="Mask detected - attendance denied per system policy.",
            )

        # All checks passed - mark attendance
        return self._mark(student_id, confidence, verdict.method, mask_result.label)

    def _mark(self, student_id: int, confidence: float, liveness_method: str, mask_label: str) -> AttendanceEvent:
        try:
            RecognitionLogModel.log(
                recognition_result="Recognized", student_id=student_id,
                confidence_score=confidence, liveness_check=True,
                camera_id=str(config.DEFAULT_CAMERA_INDEX),
            )
        except Exception as exc:
            logger.error("Failed to write recognition log: %s", exc)

        try:
            result = AttendanceModel.mark_attendance(
                student_id=student_id,
                subject_id=self.subject_id,
                faculty_id=self.faculty_id,
                classroom=self.classroom,
                recognition_confidence=confidence,
                liveness_status=True,
                mask_status=mask_label or None,
                verification_method="Face",
            )
        except Exception as exc:
            logger.error("Failed to mark attendance for student_id=%s: %s", student_id, exc)
            return AttendanceEvent(status="pending", student_id=student_id, confidence=confidence)

        if not result["success"] and result["already_marked"]:
            self._marked_this_session.add(student_id)
            return AttendanceEvent(status="already_marked", student_id=student_id, confidence=confidence)

        self._marked_this_session.add(student_id)
        student = StudentModel.get_by_id(student_id) or {}
        logger.info(
            "Attendance marked for student_id=%s via %s (confidence=%.2f).", student_id, liveness_method, confidence
        )

        return AttendanceEvent(
            status="marked", student_id=student_id, student_name=student.get("full_name", "Unknown"),
            confidence=confidence, liveness_method=liveness_method, mask_label=mask_label,
        )

    # ------------------------------------------------------------
    # Unknown face pipeline
    # ------------------------------------------------------------
    def _handle_unknown(self, result) -> AttendanceEvent:
        now = time.time()

        try:
            RecognitionLogModel.log(
                recognition_result="Unknown",
                camera_id=str(config.DEFAULT_CAMERA_INDEX),
            )
        except Exception as exc:
            logger.error("Failed to write unknown-face recognition log: %s", exc)

        if now - self._last_unknown_alert_time >= UNKNOWN_ALERT_COOLDOWN_SEC:
            self._last_unknown_alert_time = now
            self._log_security_event("Unknown Face", "Unrecognized face detected during live attendance session.")

        return AttendanceEvent(status="unknown", face_box=result.face_box)

    @staticmethod
    def _log_security_event(event_type: str, description: str):
        try:
            SecurityLogModel.log(event_type=event_type, description=description)
        except Exception as exc:
            logger.error("Failed to write security log: %s", exc)


# Singleton instance - import this everywhere instead of instantiating directly
attendance_marker = AttendanceMarker()