"""
database/models/face_embedding_model.py

CRUD operations for the `face_embeddings` table.
Embeddings are stored as encrypted text (see security/embedding_encryptor.py);
this model handles persistence, this file does not do the actual face math -
that lives in core/face_recognition/*.
"""

import json
import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.face_embedding")


class FaceEmbeddingModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(
        student_id: int,
        embedding_vector: str,
        image_path: str = None,
        image_angle: str = None,
        lighting_condition: str = None,
        quality_score: float = None,
    ) -> int:
        """
        `embedding_vector` should already be an encrypted string
        (e.g. output of security/embedding_encryptor.encrypt(vector)).
        """
        query = """
            INSERT INTO face_embeddings (
                student_id, embedding_vector, image_path, image_angle,
                lighting_condition, quality_score
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (student_id, embedding_vector, image_path, image_angle, lighting_condition, quality_score)
        embedding_id = db.execute(query, params)
        logger.info("Face embedding stored for student=%s (id=%s)", student_id, embedding_id)
        return embedding_id

    @staticmethod
    def bulk_create(embeddings: list) -> int:
        """
        Bulk insert during dataset generation (100-300 images per student).
        `embeddings` is a list of tuples:
            (student_id, embedding_vector, image_path, image_angle, lighting_condition, quality_score)
        """
        query = """
            INSERT INTO face_embeddings (
                student_id, embedding_vector, image_path, image_angle,
                lighting_condition, quality_score
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        rows_inserted = db.execute_many(query, embeddings)
        logger.info("Bulk embeddings stored: %s rows.", rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(embedding_id: int) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM face_embeddings WHERE embedding_id = %s", (embedding_id,)
        )

    @staticmethod
    def get_by_student(student_id: int) -> list:
        return db.fetch_all(
            "SELECT * FROM face_embeddings WHERE student_id = %s ORDER BY created_at ASC",
            (student_id,),
        )

    @staticmethod
    def get_all_for_matching() -> list:
        """
        Pulls every embedding + owning student's identity, used to build
        the in-memory match index the recognizer loads at startup.
        """
        query = """
            SELECT fe.embedding_id, fe.student_id, fe.embedding_vector, fe.quality_score,
                   s.full_name, s.roll_number, s.enrollment_number
            FROM face_embeddings fe
            INNER JOIN students s ON s.student_id = fe.student_id
            WHERE s.is_active = TRUE
        """
        return db.fetch_all(query)

    @staticmethod
    def count_by_student(student_id: int) -> int:
        result = db.fetch_one(
            "SELECT COUNT(*) AS total FROM face_embeddings WHERE student_id = %s",
            (student_id,),
        )
        return result["total"] if result else 0

    @staticmethod
    def get_low_quality(quality_threshold: float = 0.4) -> list:
        """Used by dataset-quality review tooling to flag/re-capture weak samples."""
        return db.fetch_all(
            "SELECT * FROM face_embeddings WHERE quality_score < %s ORDER BY quality_score ASC",
            (quality_threshold,),
        )

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    @staticmethod
    def delete(embedding_id: int) -> int:
        rows_affected = db.execute(
            "DELETE FROM face_embeddings WHERE embedding_id = %s", (embedding_id,)
        )
        logger.info("Face embedding %s deleted.", embedding_id)
        return rows_affected

    @staticmethod
    def delete_all_for_student(student_id: int) -> int:
        """Used when re-generating a student's dataset from scratch."""
        rows_affected = db.execute(
            "DELETE FROM face_embeddings WHERE student_id = %s", (student_id,)
        )
        logger.info("All embeddings deleted for student=%s (%s rows).", student_id, rows_affected)
        return rows_affected

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    @staticmethod
    def serialize_vector(vector: list) -> str:
        """Convert a raw embedding (list/np.array) to a JSON string before encrypting."""
        return json.dumps(list(vector))

    @staticmethod
    def deserialize_vector(vector_json: str) -> list:
        return json.loads(vector_json)