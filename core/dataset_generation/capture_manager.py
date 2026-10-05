"""
core/dataset_generation/capture_manager.py

The decision engine behind the live dataset-capture loop: given a raw
camera frame, decides whether it contains a usable face, whether that
face passes quality gates, whether it's a near-duplicate of a recently
saved shot, and if not - crops, saves, and tracks progress toward the
target image count.

This centralizes what's currently inline in
ui/pages/dataset_generator_page.py's `_maybe_capture()` /
`_passes_quality_check()` / `_is_duplicate()` methods. The UI page
should own the camera + threading + Tkinter widgets; this module owns
the "is this frame good enough to save" decision, built from:
    - core.face_detection.detector      (face detection)
    - core.face_detection.face_quality  (blur/brightness/size/angle)
    - core.dataset_generation.duplicate_checker
    - core.dataset_generation.auto_cropper

Usage (inside the page's per-frame camera loop):
    from core.dataset_generation.capture_manager import CaptureManager

    manager = CaptureManager(output_dir=student_photo_dir,
                              enrollment_number=student["enrollment_number"],
                              target_count=150)

    result = manager.process_frame(frame_bgr)
    if result.saved:
        update_progress(manager.saved_count, manager.target_count)
    elif result.face_box is None:
        show_status("No face detected.")
    else:
        show_status(f"Skipped: {result.reason}")

    if manager.is_complete:
        stop_capture()
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from core.face_detection.detector import detector, FaceBox
from core.face_detection.face_quality import quality_checker
from core.dataset_generation.duplicate_checker import DuplicateChecker
from core.dataset_generation.auto_cropper import auto_cropper

logger = logging.getLogger("SmartAttendAI.core.dataset_generation.capture_manager")

DEFAULT_MIN_CAPTURE_INTERVAL_SEC = 0.25  # minimum time between saved captures, even if quality passes


@dataclass
class CaptureFrameResult:
    saved: bool
    face_box: FaceBox = None
    reason: str = ""          # e.g. "no_face", "too_blurry", "duplicate", "rate_limited", "" (saved)
    image_path: str = None


class CaptureManager:
    """
    Stateful per-student capture session. Create one instance per
    dataset-generation session (i.e. per student), feed it frames one
    at a time via process_frame(), and it handles detection, quality
    gating, duplicate rejection, cropping, saving to disk, and
    progress tracking.
    """

    def __init__(
        self,
        output_dir: Path,
        enrollment_number: str,
        target_count: int = 150,
        min_capture_interval_sec: float = DEFAULT_MIN_CAPTURE_INTERVAL_SEC,
        resume_existing_count: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.enrollment_number = enrollment_number
        self.target_count = target_count
        self.min_capture_interval_sec = min_capture_interval_sec

        self._duplicate_checker = DuplicateChecker()
        self._last_capture_time = 0.0
        self._rejected_blurry = 0
        self._rejected_duplicate = 0
        self._rejected_other = 0

        self.saved_count = len(list(self.output_dir.glob("*.jpg"))) if resume_existing_count else 0

    # ------------------------------------------------------------
    # Main per-frame entry point
    # ------------------------------------------------------------
    def process_frame(self, frame_bgr: np.ndarray) -> CaptureFrameResult:
        """
        Call this once per camera frame while actively capturing.
        Returns a CaptureFrameResult describing what happened - always
        safe to call even after is_complete becomes True (it will just
        keep returning "target_reached" without saving further).
        """
        if self.is_complete:
            return CaptureFrameResult(saved=False, reason="target_reached")

        face_box = detector.detect_largest(frame_bgr)
        if face_box is None:
            return CaptureFrameResult(saved=False, reason="no_face")

        now = time.time()
        if now - self._last_capture_time < self.min_capture_interval_sec:
            return CaptureFrameResult(saved=False, face_box=face_box, reason="rate_limited")

        face_crop = auto_cropper.crop(frame_bgr, face_box, resize=False)

        quality = quality_checker.assess(face_crop, check_angle=True)
        if not quality.passed:
            self._rejected_blurry += 1
            return CaptureFrameResult(saved=False, face_box=face_box, reason=quality.reason)

        if self._duplicate_checker.is_duplicate(face_crop):
            self._rejected_duplicate += 1
            return CaptureFrameResult(saved=False, face_box=face_box, reason="duplicate")

        # Passed all gates - normalize size and save
        normalized_crop = auto_cropper.crop(frame_bgr, face_box, resize=True)
        image_path = self._save(normalized_crop)

        self._duplicate_checker.remember(face_crop)
        self._last_capture_time = now
        self.saved_count += 1

        return CaptureFrameResult(saved=True, face_box=face_box, image_path=str(image_path))

    # ------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------
    def _save(self, face_crop: np.ndarray) -> Path:
        filename = f"{self.enrollment_number}_{self.saved_count + 1:04d}.jpg"
        filepath = self.output_dir / filename
        cv2.imwrite(str(filepath), face_crop)
        return filepath

    # ------------------------------------------------------------
    # Progress / stats
    # ------------------------------------------------------------
    @property
    def is_complete(self) -> bool:
        return self.saved_count >= self.target_count

    @property
    def progress_fraction(self) -> float:
        return min(self.saved_count / max(self.target_count, 1), 1.0)

    def get_stats(self) -> dict:
        return {
            "saved_count": self.saved_count,
            "target_count": self.target_count,
            "is_complete": self.is_complete,
            "rejected_quality": self._rejected_blurry,
            "rejected_duplicate": self._rejected_duplicate,
            "rejected_other": self._rejected_other,
        }

    def reset(self, resume_existing_count: bool = True):
        """Start a fresh capture pass (e.g. re-capturing a student's dataset)."""
        self._duplicate_checker.reset()
        self._last_capture_time = 0.0
        self._rejected_blurry = 0
        self._rejected_duplicate = 0
        self._rejected_other = 0
        self.saved_count = len(list(self.output_dir.glob("*.jpg"))) if resume_existing_count else 0