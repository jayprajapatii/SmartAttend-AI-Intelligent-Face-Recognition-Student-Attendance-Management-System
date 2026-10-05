"""
core/dataset_generation/auto_cropper.py

Crops a detected face region out of a full camera frame, with
configurable margin, optional square aspect-ratio padding, and
resizing to a standard output size - so every saved dataset image
(and every image fed to the embedding generator) has consistent
framing regardless of the student's distance from the camera.

Usage:
    from core.face_detection.detector import detector
    from core.dataset_generation.auto_cropper import auto_cropper

    face_box = detector.detect_largest(frame_bgr)
    if face_box:
        crop = auto_cropper.crop(frame_bgr, face_box)
        # crop is margin-padded, square, and resized to STANDARD_OUTPUT_SIZE
"""

import logging

import cv2
import numpy as np

from core.face_detection.detector import FaceBox

logger = logging.getLogger("SmartAttendAI.core.dataset_generation.auto_cropper")

DEFAULT_MARGIN = 0.35              # extra padding as a fraction of face width/height
DEFAULT_OUTPUT_SIZE = (300, 300)   # final saved image size (w, h)
DEFAULT_SQUARE = True              # pad to a square before resizing (avoids stretching faces)


class AutoCropper:
    """
    Crops and normalizes face regions for consistent dataset storage.
    """

    def __init__(
        self,
        margin: float = DEFAULT_MARGIN,
        output_size: tuple = DEFAULT_OUTPUT_SIZE,
        square: bool = DEFAULT_SQUARE,
    ):
        self.margin = margin
        self.output_size = output_size
        self.square = square

    def crop(self, frame_bgr: np.ndarray, face: FaceBox, margin: float = None, resize: bool = True) -> np.ndarray:
        """
        Returns a cropped (and optionally resized) face image. If the
        margin-padded box would extend past the frame edges, it's
        clamped rather than padded with black - avoids introducing
        fake border pixels into the dataset/embedding pipeline.
        """
        margin = self.margin if margin is None else margin
        height, width = frame_bgr.shape[:2]

        box_x, box_y, box_w, box_h = face.x, face.y, face.w, face.h

        if self.square:
            box_x, box_y, box_w, box_h = self._to_square_box(box_x, box_y, box_w, box_h, width, height)

        margin_x = int(box_w * margin)
        margin_y = int(box_h * margin)

        x1 = max(box_x - margin_x, 0)
        y1 = max(box_y - margin_y, 0)
        x2 = min(box_x + box_w + margin_x, width)
        y2 = min(box_y + box_h + margin_y, height)

        crop = frame_bgr[y1:y2, x1:x2]

        if crop.size == 0:
            logger.warning("Auto-crop produced an empty region for face box %s - returning original frame.", face)
            return frame_bgr

        if resize and self.output_size:
            crop = cv2.resize(crop, self.output_size, interpolation=cv2.INTER_AREA)

        return crop

    @staticmethod
    def _to_square_box(x: int, y: int, w: int, h: int, frame_width: int, frame_height: int) -> tuple:
        """
        Expands the shorter dimension of the box so width == height,
        centered on the original box, then clamps to frame bounds.
        This prevents faces from being squashed/stretched when the
        final resize forces a square aspect ratio.
        """
        size = max(w, h)
        center_x = x + w // 2
        center_y = y + h // 2

        new_x = center_x - size // 2
        new_y = center_y - size // 2

        # Clamp to frame bounds without shrinking the box
        new_x = max(0, min(new_x, frame_width - size)) if size <= frame_width else 0
        new_y = max(0, min(new_y, frame_height - size)) if size <= frame_height else 0
        size = min(size, frame_width, frame_height)

        return new_x, new_y, size, size

    def crop_multiple(self, frame_bgr: np.ndarray, faces: list, margin: float = None) -> list:
        """Convenience batch version - crops every FaceBox in `faces`, returns list of images."""
        return [self.crop(frame_bgr, face, margin=margin) for face in faces]


# Singleton instance - import this everywhere instead of instantiating directly
auto_cropper = AutoCropper()