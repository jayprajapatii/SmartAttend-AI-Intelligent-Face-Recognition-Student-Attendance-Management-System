"""
core/face_detection/face_quality.py

Face image quality gate: rejects frames that are too blurry, too
dark/bright, too small, or too far off-angle (side profile beyond
threshold) before they're saved to the dataset or used for
recognition/embedding generation.

This replaces the inline blur/brightness checks currently duplicated
in ui/pages/dataset_generator_page.py - swap that page to import
`quality_checker` from here for a single source of truth, matching
the pattern used for core/face_detection/detector.py.

Usage:
    from core.face_detection.face_quality import quality_checker

    result = quality_checker.assess(face_crop_bgr)
    if result.passed:
        save_image(face_crop_bgr)
    else:
        print(result.reason)   # e.g. "too_blurry", "too_dark", "too_small"
"""

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

import config

logger = logging.getLogger("SmartAttendAI.core.face_detection.face_quality")

# ------------------------------------------------------------
# Defaults (overridable per-call; also mirrors config.py / the
# system_settings DB table for admin-adjustable thresholds)
# ------------------------------------------------------------
DEFAULT_MIN_BRIGHTNESS = 40.0
DEFAULT_MAX_BRIGHTNESS = 220.0
DEFAULT_MIN_SIZE = (100, 100)          # pixels (w, h) - reject faces smaller than this
DEFAULT_MAX_YAW_RATIO = 0.35           # eye-symmetry heuristic threshold for side-profile rejection


@dataclass
class QualityResult:
    passed: bool
    reason: str = ""              # e.g. "too_blurry", "too_dark", "too_bright", "too_small", "off_angle"
    blur_score: float = 0.0
    brightness: float = 0.0
    width: int = 0
    height: int = 0
    details: dict = field(default_factory=dict)

    def __bool__(self):
        return self.passed


class FaceQualityChecker:
    """
    Runs a sequence of quality gates on a cropped face image (BGR).
    Each gate is independently callable for cases where only one
    check is needed (e.g. duplicate-frame detection wants blur only).
    """

    def __init__(
        self,
        blur_threshold: float = None,
        min_brightness: float = DEFAULT_MIN_BRIGHTNESS,
        max_brightness: float = DEFAULT_MAX_BRIGHTNESS,
        min_size: tuple = DEFAULT_MIN_SIZE,
        max_yaw_ratio: float = DEFAULT_MAX_YAW_RATIO,
    ):
        self.blur_threshold = blur_threshold if blur_threshold is not None else config.BLUR_THRESHOLD
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.min_size = min_size
        self.max_yaw_ratio = max_yaw_ratio

    # ------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------
    def blur_score(self, face_bgr: np.ndarray) -> float:
        """Laplacian variance - higher is sharper. Works on grayscale."""
        if face_bgr is None or face_bgr.size == 0:
            return 0.0
        gray = self._to_gray(face_bgr)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def is_blurry(self, face_bgr: np.ndarray) -> bool:
        return self.blur_score(face_bgr) < self.blur_threshold

    def brightness(self, face_bgr: np.ndarray) -> float:
        if face_bgr is None or face_bgr.size == 0:
            return 0.0
        gray = self._to_gray(face_bgr)
        return float(np.mean(gray))

    def is_too_dark(self, face_bgr: np.ndarray) -> bool:
        return self.brightness(face_bgr) < self.min_brightness

    def is_too_bright(self, face_bgr: np.ndarray) -> bool:
        return self.brightness(face_bgr) > self.max_brightness

    def is_too_small(self, face_bgr: np.ndarray) -> bool:
        if face_bgr is None or face_bgr.size == 0:
            return True
        h, w = face_bgr.shape[:2]
        min_w, min_h = self.min_size
        return w < min_w or h < min_h

    def is_off_angle(self, face_bgr: np.ndarray) -> bool:
        """
        Lightweight side-profile heuristic: compares left-half vs
        right-half mean intensity symmetry as a proxy for yaw. This
        is intentionally simple (no landmark model dependency) - for
        precise pose estimation, route through MediaPipe Face Mesh
        landmarks instead once that's wired into detector.py.
        """
        if face_bgr is None or face_bgr.size == 0:
            return True
        gray = self._to_gray(face_bgr)
        h, w = gray.shape
        if w < 10:
            return True

        left_half = gray[:, : w // 2]
        right_half = gray[:, w // 2:]
        left_mean = float(np.mean(left_half))
        right_mean = float(np.mean(right_half))

        if max(left_mean, right_mean) == 0:
            return True

        asymmetry = abs(left_mean - right_mean) / max(left_mean, right_mean)
        return asymmetry > self.max_yaw_ratio

    # ------------------------------------------------------------
    # Combined assessment
    # ------------------------------------------------------------
    def assess(self, face_bgr: np.ndarray, check_angle: bool = True) -> QualityResult:
        """Runs all gates in order, short-circuiting on the first failure."""
        if face_bgr is None or face_bgr.size == 0:
            return QualityResult(passed=False, reason="empty_image")

        h, w = face_bgr.shape[:2]
        blur = self.blur_score(face_bgr)
        bright = self.brightness(face_bgr)

        if self.is_too_small(face_bgr):
            return QualityResult(
                passed=False, reason="too_small", blur_score=blur, brightness=bright, width=w, height=h,
            )

        if blur < self.blur_threshold:
            return QualityResult(
                passed=False, reason="too_blurry", blur_score=blur, brightness=bright, width=w, height=h,
            )

        if bright < self.min_brightness:
            return QualityResult(
                passed=False, reason="too_dark", blur_score=blur, brightness=bright, width=w, height=h,
            )

        if bright > self.max_brightness:
            return QualityResult(
                passed=False, reason="too_bright", blur_score=blur, brightness=bright, width=w, height=h,
            )

        if check_angle and self.is_off_angle(face_bgr):
            return QualityResult(
                passed=False, reason="off_angle", blur_score=blur, brightness=bright, width=w, height=h,
            )

        return QualityResult(passed=True, blur_score=blur, brightness=bright, width=w, height=h)

    # ------------------------------------------------------------
    # Duplicate-frame detection (used alongside quality checks during
    # dataset capture to avoid saving near-identical consecutive shots)
    # ------------------------------------------------------------
    @staticmethod
    def is_duplicate(face_bgr: np.ndarray, previous_gray_64: np.ndarray, diff_threshold: float = 8.0) -> bool:
        """
        Compares a downsampled 64x64 grayscale version of the current
        face against a previously saved one. Returns True if too
        similar (i.e. should be skipped as a duplicate).
        """
        if previous_gray_64 is None:
            return False
        gray = FaceQualityChecker._to_gray(face_bgr)
        resized = cv2.resize(gray, (64, 64))
        diff = cv2.absdiff(resized, previous_gray_64)
        return float(np.mean(diff)) < diff_threshold

    @staticmethod
    def make_duplicate_fingerprint(face_bgr: np.ndarray) -> np.ndarray:
        """Produces the 64x64 grayscale fingerprint to pass as `previous_gray_64` next call."""
        gray = FaceQualityChecker._to_gray(face_bgr)
        return cv2.resize(gray, (64, 64))

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    @staticmethod
    def _to_gray(face_bgr: np.ndarray) -> np.ndarray:
        if len(face_bgr.shape) == 2:
            return face_bgr  # already grayscale
        return cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)


# Singleton instance - import this everywhere instead of instantiating directly
quality_checker = FaceQualityChecker()