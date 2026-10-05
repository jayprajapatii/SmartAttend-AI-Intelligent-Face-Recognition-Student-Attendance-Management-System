"""
core/dataset_generation/duplicate_checker.py

Stateful near-duplicate detection for dataset capture: keeps a short
rolling history of recently-saved face fingerprints and rejects new
captures that are too visually similar to any of them. This is a
richer version of the single-previous-frame check that was inline in
ui/pages/dataset_generator_page.py - comparing against a short
history (not just the last frame) catches duplicates from a student
briefly looking away and back.

Usage:
    from core.dataset_generation.duplicate_checker import DuplicateChecker

    checker = DuplicateChecker(history_size=15, diff_threshold=8.0)

    if checker.is_duplicate(face_crop_bgr):
        skip()
    else:
        save(face_crop_bgr)
        checker.remember(face_crop_bgr)
"""

import logging
from collections import deque

import cv2
import numpy as np

logger = logging.getLogger("SmartAttendAI.core.dataset_generation.duplicate_checker")

DEFAULT_HISTORY_SIZE = 15       # how many recent fingerprints to compare against
DEFAULT_DIFF_THRESHOLD = 8.0    # mean pixel diff below this = too similar
FINGERPRINT_SIZE = (64, 64)     # downsample size for fast comparison


class DuplicateChecker:
    """
    Compares a downsampled grayscale "fingerprint" of each new face
    crop against a rolling history of recently-saved fingerprints.
    If the mean absolute pixel difference against ANY recent
    fingerprint falls below `diff_threshold`, the new frame is
    considered a duplicate and should be skipped.
    """

    def __init__(self, history_size: int = DEFAULT_HISTORY_SIZE, diff_threshold: float = DEFAULT_DIFF_THRESHOLD):
        self.history_size = history_size
        self.diff_threshold = diff_threshold
        self._history = deque(maxlen=history_size)

    def is_duplicate(self, face_bgr: np.ndarray) -> bool:
        """Returns True if `face_bgr` is too similar to any recently remembered fingerprint."""
        if not self._history:
            return False

        fingerprint = self._make_fingerprint(face_bgr)
        for previous in self._history:
            diff = cv2.absdiff(fingerprint, previous)
            if float(np.mean(diff)) < self.diff_threshold:
                return True
        return False

    def remember(self, face_bgr: np.ndarray):
        """Adds `face_bgr` to the rolling history (call after a successful, non-duplicate save)."""
        self._history.append(self._make_fingerprint(face_bgr))

    def check_and_remember(self, face_bgr: np.ndarray) -> bool:
        """
        Convenience combo: returns True if duplicate (and does NOT
        remember it). Returns False if unique, and remembers it for
        future comparisons.
        """
        if self.is_duplicate(face_bgr):
            return True
        self.remember(face_bgr)
        return False

    def reset(self):
        """Clear all remembered fingerprints (e.g. when switching to a new student)."""
        self._history.clear()

    @property
    def history_length(self) -> int:
        return len(self._history)

    @staticmethod
    def _make_fingerprint(face_bgr: np.ndarray) -> np.ndarray:
        if face_bgr is None or face_bgr.size == 0:
            return np.zeros(FINGERPRINT_SIZE, dtype=np.uint8)
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY) if len(face_bgr.shape) == 3 else face_bgr
        return cv2.resize(gray, FINGERPRINT_SIZE)