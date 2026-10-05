"""
core/mask_detection/mask_classifier.py

Classifies whether a detected face is wearing a mask. Two backends:

    1. Trained model (preferred): loads a Keras/TensorFlow classifier
       from ml_models/mask_model.h5 if present. Any standard binary
       mask/no-mask CNN (e.g. MobileNetV2-based, trained on a public
       mask dataset) works as a drop-in - just export it to that path.

    2. Heuristic fallback (no model file required): looks at the
       lower third of the face (nose/mouth/chin region) and scores
       edge density + color uniformity there. A visible mouth/nose/
       chin has more edges and more color variation (lips, teeth,
       shadows, stubble) than a cloth/surgical mask, which tends to
       be comparatively flat and uniform. This is a rough proxy, not
       a real classifier - swap in a trained model for production
       accuracy; the heuristic exists so mask detection degrades
       gracefully instead of being unavailable when no model is
       trained yet, matching the fallback pattern used throughout
       core/ (e.g. detector.py's Haar cascade fallback).

Usage:
    from core.mask_detection.mask_classifier import mask_classifier

    result = mask_classifier.classify(face_crop_bgr)
    print(result.label, result.confidence)   # "Mask" | "No Mask"
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

import config

logger = logging.getLogger("SmartAttendAI.core.mask_detection.mask_classifier")

MASK_MODEL_PATH = config.ML_MODELS_DIR / "mask_model.h5"
MODEL_INPUT_SIZE = (224, 224)  # standard MobileNetV2-style input size

# Heuristic fallback thresholds (tuned loosely - adjust based on real footage)
HEURISTIC_EDGE_DENSITY_THRESHOLD = 0.045   # below this = looks mask-like (flat, few edges)
HEURISTIC_COLOR_STD_THRESHOLD = 18.0       # below this = looks mask-like (uniform color)


@dataclass
class MaskResult:
    has_mask: bool
    label: str            # "Mask" | "No Mask"
    confidence: float      # 0-1
    method: str = ""       # "model" | "heuristic"


class MaskClassifier:
    """
    Wraps a trained mask-detection model when available, with an
    automatic heuristic fallback otherwise. Call classify() with a
    cropped face image (BGR) - not the full frame.
    """

    def __init__(self):
        self._model = None
        self._backend = "heuristic"
        self._try_load_model()

    def _try_load_model(self):
        if not MASK_MODEL_PATH.exists():
            logger.info(
                "No trained mask model found at %s - using heuristic fallback. "
                "Place a trained Keras model there to enable model-based detection.",
                MASK_MODEL_PATH,
            )
            return

        try:
            import tensorflow as tf
            self._model = tf.keras.models.load_model(str(MASK_MODEL_PATH))
            self._backend = "model"
            logger.info("Mask detection model loaded from %s.", MASK_MODEL_PATH)
        except ImportError:
            logger.warning("tensorflow not installed - cannot load mask model, using heuristic fallback.")
        except Exception as exc:
            logger.error("Failed to load mask model (%s) - using heuristic fallback.", exc)

    @property
    def backend(self) -> str:
        return self._backend

    # ------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------
    def classify(self, face_bgr: np.ndarray) -> MaskResult:
        if face_bgr is None or face_bgr.size == 0:
            return MaskResult(has_mask=False, label="No Mask", confidence=0.0, method=self._backend)

        if self._model is not None:
            return self._classify_with_model(face_bgr)
        return self._classify_with_heuristic(face_bgr)

    def classify_batch(self, face_crops: list) -> list:
        return [self.classify(crop) for crop in face_crops]

    # ------------------------------------------------------------
    # Model-based path
    # ------------------------------------------------------------
    def _classify_with_model(self, face_bgr: np.ndarray) -> MaskResult:
        try:
            rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, MODEL_INPUT_SIZE)
            normalized = resized.astype("float32") / 255.0
            batch = np.expand_dims(normalized, axis=0)

            prediction = self._model.predict(batch, verbose=0)
            # Assumes a single sigmoid output: 1.0 = mask, 0.0 = no mask.
            # Adjust indexing here if your model uses a 2-class softmax instead.
            mask_probability = float(prediction[0][0]) if prediction.ndim > 1 else float(prediction[0])

            has_mask = mask_probability >= 0.5
            confidence = mask_probability if has_mask else (1.0 - mask_probability)

            return MaskResult(
                has_mask=has_mask,
                label="Mask" if has_mask else "No Mask",
                confidence=round(confidence, 3),
                method="model",
            )
        except Exception as exc:
            logger.error("Mask model inference failed (%s) - falling back to heuristic for this frame.", exc)
            return self._classify_with_heuristic(face_bgr)

    # ------------------------------------------------------------
    # Heuristic fallback path
    # ------------------------------------------------------------
    def _classify_with_heuristic(self, face_bgr: np.ndarray) -> MaskResult:
        lower_region = self._extract_lower_face(face_bgr)
        if lower_region.size == 0:
            return MaskResult(has_mask=False, label="No Mask", confidence=0.0, method="heuristic")

        gray = cv2.cvtColor(lower_region, cv2.COLOR_BGR2GRAY)

        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / edges.size

        color_std = float(np.std(gray))

        mask_votes = 0
        total_checks = 2

        if edge_density < HEURISTIC_EDGE_DENSITY_THRESHOLD:
            mask_votes += 1
        if color_std < HEURISTIC_COLOR_STD_THRESHOLD:
            mask_votes += 1

        has_mask = mask_votes >= 1  # either signal alone is enough to lean "mask" (favors safety - see policy note below)
        confidence = mask_votes / total_checks if has_mask else (total_checks - mask_votes) / total_checks
        confidence = max(0.5, confidence)  # heuristic is never fully confident; floor at 0.5

        return MaskResult(
            has_mask=has_mask,
            label="Mask" if has_mask else "No Mask",
            confidence=round(confidence, 3),
            method="heuristic",
        )

    @staticmethod
    def _extract_lower_face(face_bgr: np.ndarray) -> np.ndarray:
        """Crops roughly the bottom half of the face image (nose/mouth/chin region)."""
        h, w = face_bgr.shape[:2]
        return face_bgr[int(h * 0.45):h, int(w * 0.1):int(w * 0.9)]


# Singleton instance - import this everywhere instead of instantiating directly
mask_classifier = MaskClassifier()