"""
core/emotion_recognition/emotion_classifier.py

Classifies the emotion of a detected face into one of: Happy, Neutral,
Sad, Angry, Surprised - stored alongside each attendance record per
the spec's "Emotion Recognition" feature.

Two backends:

    1. Trained model (preferred): loads a Keras/TensorFlow classifier
       from ml_models/emotion_model.h5 if present. Standard FER-style
       CNNs (e.g. trained on FER2013) typically take a 48x48 grayscale
       face crop and output a softmax over emotion classes. FER2013's
       native 7 classes are (angry, disgust, fear, happy, sad,
       surprise, neutral) - EMOTION_MODEL_LABELS below maps whatever
       label set your model was trained on down to this app's 5
       supported labels. Adjust EMOTION_MODEL_LABELS to match your
       model's actual output order.

    2. Heuristic fallback (no model required): OpenCV ships a smile
       Haar cascade, which gives a genuinely reasonable Happy vs.
       Neutral signal without any training. It CANNOT reliably
       distinguish Sad/Angry/Surprised - those are reported as
       "Neutral" with low confidence when no model is loaded, rather
       than guessed. This is an honest limitation, not a full 5-class
       heuristic - train and drop in a real model at
       ml_models/emotion_model.h5 for full coverage, matching the
       fallback pattern used throughout core/ (e.g. mask_classifier.py).

Usage:
    from core.emotion_recognition.emotion_classifier import emotion_classifier

    result = emotion_classifier.classify(face_crop_bgr)
    print(result.label, result.confidence)   # e.g. "Happy", 0.87
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

import config

logger = logging.getLogger("SmartAttendAI.core.emotion_recognition.emotion_classifier")

EMOTION_MODEL_PATH = config.ML_MODELS_DIR / "emotion_model.h5"
MODEL_INPUT_SIZE = (48, 48)  # standard FER-style grayscale input

SUPPORTED_LABELS = ("Happy", "Neutral", "Sad", "Angry", "Surprised")

# Maps a model's raw output index -> this app's supported label.
# Default assumes a 7-class FER2013-style model in its canonical order:
# (angry, disgust, fear, happy, sad, surprise, neutral).
# "disgust" and "fear" don't have a direct slot in SUPPORTED_LABELS,
# so they're folded into the closest supported label. Adjust this list
# to match your actual trained model's class order.
EMOTION_MODEL_LABELS = [
    "Angry",      # 0: angry
    "Angry",      # 1: disgust  (folded into Angry - closest negative-affect match)
    "Surprised",  # 2: fear     (folded into Surprised - closest high-arousal match)
    "Happy",      # 3: happy
    "Sad",        # 4: sad
    "Surprised",  # 5: surprise
    "Neutral",    # 6: neutral
]

SMILE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_smile.xml"


@dataclass
class EmotionResult:
    label: str            # one of SUPPORTED_LABELS
    confidence: float      # 0-1
    method: str = ""       # "model" | "heuristic"
    raw_scores: dict = None  # full per-class distribution, when available (model backend only)


class EmotionClassifier:
    """
    Wraps a trained FER-style emotion model when available, with a
    smile-cascade heuristic fallback (Happy/Neutral only) otherwise.
    Call classify() with a cropped face image (BGR) - not the full frame.
    """

    def __init__(self):
        self._model = None
        self._backend = "heuristic"
        self._smile_cascade = None

        self._try_load_model()
        self._try_load_smile_cascade()

    def _try_load_model(self):
        if not EMOTION_MODEL_PATH.exists():
            logger.info(
                "No trained emotion model found at %s - using smile-cascade heuristic "
                "(Happy/Neutral only). Place a trained Keras model there for full "
                "Happy/Neutral/Sad/Angry/Surprised coverage.",
                EMOTION_MODEL_PATH,
            )
            return

        try:
            import tensorflow as tf
            self._model = tf.keras.models.load_model(str(EMOTION_MODEL_PATH))
            self._backend = "model"
            logger.info("Emotion detection model loaded from %s.", EMOTION_MODEL_PATH)
        except ImportError:
            logger.warning("tensorflow not installed - cannot load emotion model, using heuristic fallback.")
        except Exception as exc:
            logger.error("Failed to load emotion model (%s) - using heuristic fallback.", exc)

    def _try_load_smile_cascade(self):
        try:
            cascade = cv2.CascadeClassifier(SMILE_CASCADE_PATH)
            if cascade.empty():
                raise RuntimeError("Smile cascade file failed to load.")
            self._smile_cascade = cascade
        except Exception as exc:
            logger.warning("Could not load smile cascade (%s) - heuristic fallback will always report Neutral.", exc)

    @property
    def backend(self) -> str:
        return self._backend

    # ------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------
    def classify(self, face_bgr: np.ndarray) -> EmotionResult:
        if face_bgr is None or face_bgr.size == 0:
            return EmotionResult(label="Neutral", confidence=0.0, method=self._backend)

        if self._model is not None:
            return self._classify_with_model(face_bgr)
        return self._classify_with_heuristic(face_bgr)

    def classify_batch(self, face_crops: list) -> list:
        return [self.classify(crop) for crop in face_crops]

    # ------------------------------------------------------------
    # Model-based path
    # ------------------------------------------------------------
    def _classify_with_model(self, face_bgr: np.ndarray) -> EmotionResult:
        try:
            gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, MODEL_INPUT_SIZE)
            normalized = resized.astype("float32") / 255.0
            batch = np.expand_dims(normalized, axis=(0, -1))  # (1, H, W, 1)

            predictions = self._model.predict(batch, verbose=0)[0]

            collapsed_scores = {label: 0.0 for label in SUPPORTED_LABELS}
            for idx, score in enumerate(predictions):
                model_label = EMOTION_MODEL_LABELS[idx] if idx < len(EMOTION_MODEL_LABELS) else "Neutral"
                collapsed_scores[model_label] = collapsed_scores.get(model_label, 0.0) + float(score)

            best_label = max(collapsed_scores, key=collapsed_scores.get)
            confidence = collapsed_scores[best_label]

            return EmotionResult(
                label=best_label,
                confidence=round(min(confidence, 1.0), 3),
                method="model",
                raw_scores={k: round(v, 3) for k, v in collapsed_scores.items()},
            )
        except Exception as exc:
            logger.error("Emotion model inference failed (%s) - falling back to heuristic for this frame.", exc)
            return self._classify_with_heuristic(face_bgr)

    # ------------------------------------------------------------
    # Heuristic fallback path (Happy/Neutral only, via smile cascade)
    # ------------------------------------------------------------
    def _classify_with_heuristic(self, face_bgr: np.ndarray) -> EmotionResult:
        if self._smile_cascade is None:
            return EmotionResult(label="Neutral", confidence=0.5, method="heuristic")

        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        # Smile cascade works best on the lower half of the face and
        # needs fairly strict params to avoid false positives on a
        # face-sized crop (it's usually run on a full-frame mouth ROI).
        lower_half = gray[gray.shape[0] // 2:, :]

        smiles = self._smile_cascade.detectMultiScale(
            lower_half, scaleFactor=1.7, minNeighbors=22, minSize=(25, 25),
        )

        if len(smiles) > 0:
            # More detections / larger detections -> slightly higher confidence,
            # capped since this heuristic is inherently noisy.
            confidence = min(0.55 + 0.1 * len(smiles), 0.85)
            return EmotionResult(label="Happy", confidence=round(confidence, 3), method="heuristic")

        return EmotionResult(label="Neutral", confidence=0.55, method="heuristic")


# Singleton instance - import this everywhere instead of instantiating directly
emotion_classifier = EmotionClassifier()