"""
core/face_detection/detector.py

Face detection module: MediaPipe Face Detection as the primary
backend (fast, good angle tolerance, gives landmark-free bounding
boxes + confidence), with an OpenCV Haar cascade fallback if
MediaPipe isn't installed or fails to initialize.

This replaces the inline `cv2.CascadeClassifier` calls currently
duplicated in ui/pages/dataset_generator_page.py and
ui/pages/face_recognition_page.py - swap those over to import
`detector` from here for a single source of truth.

Usage:
    from core.face_detection.detector import detector

    faces = detector.detect(frame_bgr)
    # faces: list[FaceBox], each with .x, .y, .w, .h, .confidence

    largest = detector.detect_largest(frame_bgr)
    if largest:
        crop = detector.crop(frame_bgr, largest, margin=0.35)
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger("SmartAttendAI.core.face_detection.detector")

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logger.warning("mediapipe not installed - falling back to Haar cascade face detection.")

DEFAULT_MIN_CONFIDENCE = 0.6
DEFAULT_MIN_FACE_SIZE = (80, 80)  # pixels; used by the Haar fallback


@dataclass
class FaceBox:
    """A detected face's bounding box in pixel coordinates, plus confidence."""
    x: int
    y: int
    w: int
    h: int
    confidence: float = 1.0

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def center(self) -> tuple:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def as_tuple(self) -> tuple:
        """(x, y, w, h) - matches cv2/Haar cascade convention."""
        return (self.x, self.y, self.w, self.h)


class FaceDetector:
    """
    Wraps MediaPipe Face Detection (preferred) with a Haar cascade
    fallback, exposing a single consistent interface regardless of
    which backend is active.
    """

    def __init__(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
        self.min_confidence = min_confidence
        self._backend = None
        self._mp_detector = None
        self._haar_cascade = None
        self._initialize_backend()

    def _initialize_backend(self):
        if MEDIAPIPE_AVAILABLE:
            try:
                mp_face_detection = mp.solutions.face_detection
                self._mp_detector = mp_face_detection.FaceDetection(
                    model_selection=1,  # 1 = full-range model, better for varied distances
                    min_detection_confidence=self.min_confidence,
                )
                self._backend = "mediapipe"
                logger.info("Face detector backend: MediaPipe (full-range model).")
                return
            except Exception as exc:
                logger.error("MediaPipe initialization failed, falling back to Haar cascade: %s", exc)

        try:
            self._haar_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            if self._haar_cascade.empty():
                raise RuntimeError("Haar cascade file failed to load.")
            self._backend = "haar"
            logger.info("Face detector backend: OpenCV Haar cascade.")
        except Exception as exc:
            logger.critical("No face detection backend could be initialized: %s", exc)
            self._backend = None

    @property
    def backend_name(self) -> str:
        return self._backend or "none"

    # ------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------
    def detect(self, frame_bgr: np.ndarray) -> list:
        """Returns a list of FaceBox, sorted by area descending (largest first)."""
        if self._backend == "mediapipe":
            faces = self._detect_mediapipe(frame_bgr)
        elif self._backend == "haar":
            faces = self._detect_haar(frame_bgr)
        else:
            faces = []

        return sorted(faces, key=lambda f: f.area, reverse=True)

    def detect_largest(self, frame_bgr: np.ndarray) -> FaceBox | None:
        faces = self.detect(frame_bgr)
        return faces[0] if faces else None

    def _detect_mediapipe(self, frame_bgr: np.ndarray) -> list:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._mp_detector.process(rgb)

        if not results.detections:
            return []

        height, width = frame_bgr.shape[:2]
        faces = []
        for detection in results.detections:
            box = detection.location_data.relative_bounding_box
            x = max(int(box.xmin * width), 0)
            y = max(int(box.ymin * height), 0)
            w = min(int(box.width * width), width - x)
            h = min(int(box.height * height), height - y)
            confidence = detection.score[0] if detection.score else 0.0

            if w > 0 and h > 0:
                faces.append(FaceBox(x=x, y=y, w=w, h=h, confidence=float(confidence)))

        return faces

    def _detect_haar(self, frame_bgr: np.ndarray) -> list:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        detections = self._haar_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=6, minSize=DEFAULT_MIN_FACE_SIZE
        )
        # Haar gives no confidence score - default to 1.0 for anything it finds
        return [FaceBox(x=int(x), y=int(y), w=int(w), h=int(h), confidence=1.0) for x, y, w, h in detections]

    # ------------------------------------------------------------
    # Cropping helper
    # ------------------------------------------------------------
    @staticmethod
    def crop(frame_bgr: np.ndarray, face: FaceBox, margin: float = 0.0) -> np.ndarray:
        """
        Crop a face region from the frame, with an optional margin
        (fraction of width/height) added on each side and clamped to
        the frame boundaries.
        """
        height, width = frame_bgr.shape[:2]
        margin_x = int(face.w * margin)
        margin_y = int(face.h * margin)

        x1 = max(face.x - margin_x, 0)
        y1 = max(face.y - margin_y, 0)
        x2 = min(face.x + face.w + margin_x, width)
        y2 = min(face.y + face.h + margin_y, height)

        return frame_bgr[y1:y2, x1:x2]

    @staticmethod
    def draw_box(frame_bgr: np.ndarray, face: FaceBox, color=(0, 200, 0), thickness: int = 2, label: str = None):
        """Draws the bounding box (and optional label) directly on the frame in place."""
        cv2.rectangle(frame_bgr, (face.x, face.y), (face.x + face.w, face.y + face.h), color, thickness)
        if label:
            cv2.putText(
                frame_bgr, label, (face.x, max(face.y - 10, 0)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
            )


# Singleton instance - import this everywhere instead of instantiating directly
detector = FaceDetector()