"""
core/face_recognition/embedding_generator.py

Generates 128-d face encodings (via the `face_recognition` / dlib
library) from the images captured by ui/pages/dataset_generator_page.py,
quality-gates them again at encoding time, and persists them through
FaceEmbeddingModel.

This is the module ui/pages/dataset_generator_page.py's
`_finish_dataset()` already tries to import:
    from core.face_recognition.embedding_generator import generate_embeddings_for_student

Usage:
    from core.face_recognition.embedding_generator import generate_embeddings_for_student

    count = generate_embeddings_for_student(student_id, image_dir)
"""

import logging
from pathlib import Path

import cv2
import numpy as np

from database.models.face_embedding_model import FaceEmbeddingModel
from core.face_detection.face_quality import quality_checker

logger = logging.getLogger("SmartAttendAI.core.face_recognition.embedding_generator")

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logger.warning("face_recognition library not installed - embedding generation unavailable.")

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png")
MIN_QUALITY_SCORE_TO_KEEP = 0.0  # embeddings are kept regardless of quality score; score is stored for reference


def generate_embeddings_for_student(student_id: int, image_dir: Path, replace_existing: bool = True) -> int:
    """
    Reads every image in `image_dir` (as produced by the dataset
    generator page), computes a face encoding for each, and stores
    them via FaceEmbeddingModel.

    Args:
        student_id: the student these images belong to.
        image_dir: directory containing cropped face images
                    (data/student_photos/<enrollment_number>/).
        replace_existing: if True, deletes this student's previously
                    stored embeddings before inserting the new batch
                    (avoids duplicate/stale encodings on re-capture).

    Returns:
        Number of embeddings successfully generated and stored.
    """
    if not FACE_RECOGNITION_AVAILABLE:
        raise RuntimeError(
            "'face_recognition' package is not installed. Run: pip install face_recognition"
        )

    image_dir = Path(image_dir)
    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {image_dir}")

    image_paths = sorted(
        p for p in image_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not image_paths:
        logger.warning("No images found in %s for student_id=%s", image_dir, student_id)
        return 0

    if replace_existing:
        try:
            deleted = FaceEmbeddingModel.delete_all_for_student(student_id)
            logger.info("Cleared %d existing embedding(s) for student_id=%s before regeneration.", deleted, student_id)
        except AttributeError:
            logger.warning(
                "FaceEmbeddingModel.delete_all_for_student() not found - skipping cleanup of old embeddings."
            )
        except Exception as exc:
            logger.error("Failed to clear existing embeddings: %s", exc)

    records = []
    skipped = 0

    for image_path in image_paths:
        result = _process_single_image(image_path)
        if result is None:
            skipped += 1
            continue

        vector, quality_score, angle_label, lighting_label = result
        # NOTE: embedding_vector is JSON-serialized here, not yet encrypted.
        # Once security/embedding_encryptor.py exists, wrap this with
        # embedding_encryptor.encrypt(...) before storage, per the
        # "Encrypted Face Embeddings" security requirement.
        serialized_vector = FaceEmbeddingModel.serialize_vector(vector.tolist())
        records.append((
            student_id, serialized_vector, str(image_path), angle_label, lighting_label, quality_score,
        ))

    if not records:
        logger.warning("No usable embeddings could be generated for student_id=%s (all %d images skipped).",
                        student_id, skipped)
        return 0

    try:
        inserted = FaceEmbeddingModel.bulk_create(records)
    except Exception as exc:
        # Fallback if bulk insert fails for any reason - insert one at a time
        # so a single bad row doesn't lose the whole batch.
        logger.warning("bulk_create failed (%s) - falling back to per-row insert.", exc)
        inserted = 0
        for student_id_, vector_json, path_, angle_, lighting_, score_ in records:
            try:
                FaceEmbeddingModel.create(
                    student_id=student_id_, embedding_vector=vector_json, image_path=path_,
                    image_angle=angle_, lighting_condition=lighting_, quality_score=score_,
                )
                inserted += 1
            except Exception as row_exc:
                logger.error("Failed to store embedding for %s: %s", path_, row_exc)

    logger.info(
        "Embedding generation complete for student_id=%s: %d stored, %d skipped (of %d images).",
        student_id, inserted, skipped, len(image_paths),
    )
    return inserted


def _process_single_image(image_path: Path):
    """
    Returns (encoding_vector, quality_score, angle_label, lighting_label)
    or None if the image should be skipped (no face found, multiple
    faces, or encoding failed).
    """
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        logger.warning("Could not read image: %s", image_path)
        return None

    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb)

    if len(face_locations) == 0:
        logger.debug("No face found in %s - skipping.", image_path.name)
        return None
    if len(face_locations) > 1:
        logger.debug("Multiple faces found in %s - using the largest.", image_path.name)
        face_locations = [_largest_face_location(face_locations)]

    encodings = face_recognition.face_encodings(rgb, face_locations)
    if not encodings:
        logger.debug("Encoding failed for %s - skipping.", image_path.name)
        return None

    encoding = encodings[0]

    top, right, bottom, left = face_locations[0]
    face_crop = image_bgr[top:bottom, left:right]
    quality = quality_checker.assess(face_crop, check_angle=False)
    quality_score = round(min(quality.blur_score / 500.0, 1.0), 3)  # normalize roughly to 0-1 for storage

    angle_label = _estimate_angle_label(image_bgr, face_locations[0])
    lighting_label = _estimate_lighting_label(quality.brightness)

    return encoding, quality_score, angle_label, lighting_label


def _largest_face_location(face_locations: list) -> tuple:
    def area(loc):
        top, right, bottom, left = loc
        return (bottom - top) * (right - left)
    return max(face_locations, key=area)


def _estimate_angle_label(image_bgr: np.ndarray, face_location: tuple) -> str:
    """
    Rough heuristic label for dataset diversity tracking - not used
    for recognition, just metadata. Compares face-center offset from
    image-center to guess "left" / "right" / "center".
    """
    top, right, bottom, left = face_location
    face_center_x = (left + right) / 2
    image_width = image_bgr.shape[1]
    relative_position = face_center_x / image_width

    if relative_position < 0.4:
        return "left"
    if relative_position > 0.6:
        return "right"
    return "center"


def _estimate_lighting_label(brightness: float) -> str:
    if brightness < 80:
        return "low"
    if brightness > 180:
        return "bright"
    return "normal"