"""
core/face_recognition/recognizer.py

Loads known student face encodings from the database and matches new
encodings against them. This is the module ui/pages/face_recognition_page.py
should import instead of its current inline `_load_known_faces()` /
`_match_face()` methods - same interface, single source of truth.

Usage:
    from core.face_recognition.recognizer import recognizer

    recognizer.reload()  # call once per session start (or after new
                          # students are added / re-captured)

    match = recognizer.match(face_encoding)
    if match.is_match:
        print(match.student_id, match.confidence)

    # Or run detection + encoding + matching all at once on a raw frame:
    results = recognizer.recognize_frame(frame_bgr)
    for r in results:
        print(r.face_box, r.match)
"""

import logging
from dataclasses import dataclass

import numpy as np

from database.models.face_embedding_model import FaceEmbeddingModel
from core.face_detection.detector import FaceBox
from core.face_recognition.confidence_scorer import confidence_scorer
import config

logger = logging.getLogger("SmartAttendAI.core.face_recognition.recognizer")

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logger.warning("face_recognition library not installed - recognizer will not be able to match faces.")


@dataclass
class MatchResult:
    is_match: bool
    student_id: int = None
    confidence: float = 0.0
    distance: float = None


@dataclass
class FrameRecognitionResult:
    face_box: FaceBox
    encoding: np.ndarray
    match: MatchResult


class FaceRecognizer:
    """
    Holds the in-memory index of known face encodings (loaded from
    FaceEmbeddingModel) and performs matching against it. Reload the
    index whenever new students/embeddings are added, e.g. at the
    start of each recognition session.
    """

    def __init__(self, threshold: float = None):
        self.threshold = threshold if threshold is not None else config.RECOGNITION_THRESHOLD
        self._known_encodings = []    # list[np.ndarray]
        self._known_student_ids = []  # parallel list[int]
        self._loaded = False

    # ------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------
    def reload(self) -> int:
        """(Re)loads all known face embeddings from the database. Returns count loaded."""
        self._known_encodings = []
        self._known_student_ids = []

        try:
            embeddings = FaceEmbeddingModel.get_all_for_matching()
        except Exception as exc:
            logger.error("Failed to load face embeddings from database: %s", exc)
            embeddings = []

        for row in embeddings:
            try:
                vector = FaceEmbeddingModel.deserialize_vector(row["embedding_vector"])
                self._known_encodings.append(np.array(vector, dtype=np.float64))
                self._known_student_ids.append(row["student_id"])
            except (ValueError, TypeError, KeyError) as exc:
                logger.debug("Skipping malformed embedding row: %s", exc)
                continue

        self._loaded = True
        unique_students = len(set(self._known_student_ids))
        logger.info(
            "Recognizer index loaded: %d encodings across %d student(s).",
            len(self._known_encodings), unique_students,
        )
        return len(self._known_encodings)

    def is_ready(self) -> bool:
        return FACE_RECOGNITION_AVAILABLE and self._loaded and len(self._known_encodings) > 0

    @property
    def known_student_count(self) -> int:
        return len(set(self._known_student_ids))

    def set_threshold(self, threshold: float):
        self.threshold = threshold

    # ------------------------------------------------------------
    # Matching a single pre-computed encoding
    # ------------------------------------------------------------
    def match(self, encoding: np.ndarray) -> MatchResult:
        if not self._known_encodings:
            return MatchResult(is_match=False)

        distances = face_recognition.face_distance(self._known_encodings, encoding)
        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])

        if best_distance <= self.threshold:
            confidence = confidence_scorer.distance_to_confidence(best_distance, self.threshold)
            return MatchResult(
                is_match=True,
                student_id=self._known_student_ids[best_idx],
                confidence=confidence,
                distance=best_distance,
            )

        return MatchResult(is_match=False, distance=best_distance)

    # ------------------------------------------------------------
    # Full pipeline: detect faces in a raw frame, encode, and match
    # ------------------------------------------------------------
    def recognize_frame(self, frame_bgr: np.ndarray, downscale: float = 0.5) -> list:
        """
        Runs detection + encoding + matching on a full BGR frame.
        `downscale` trades accuracy for speed (0.5 = half-size frame
        for detection, matching face_recognition_page.py's approach).

        Returns a list of FrameRecognitionResult, one per detected face.
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return []

        import cv2

        small_frame = cv2.resize(frame_bgr, (0, 0), fx=downscale, fy=downscale) if downscale != 1.0 else frame_bgr
        rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_small)
        if not face_locations:
            return []

        encodings = face_recognition.face_encodings(rgb_small, face_locations)
        scale = 1.0 / downscale if downscale != 1.0 else 1.0

        results = []
        for (top, right, bottom, left), encoding in zip(face_locations, encodings):
            face_box = FaceBox(
                x=int(left * scale), y=int(top * scale),
                w=int((right - left) * scale), h=int((bottom - top) * scale),
            )
            match_result = self.match(encoding)
            results.append(FrameRecognitionResult(face_box=face_box, encoding=encoding, match=match_result))

        return results


# Singleton instance - import this everywhere instead of instantiating directly
recognizer = FaceRecognizer()