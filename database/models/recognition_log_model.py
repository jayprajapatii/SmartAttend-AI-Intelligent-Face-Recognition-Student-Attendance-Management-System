"""
database/models/recognition_log_model.py

CRUD + query operations for the `recognition_logs` table.
Every face recognition attempt (recognized / unknown / failed) is
logged here - used for recognition accuracy stats on the dashboard,
troubleshooting misfires, and feeding the "unknown face" alert flow.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.recognition_log")


class RecognitionLogModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def log(
        recognition_result: str,
        student_id: int = None,
        confidence_score: float = None,
        liveness_check: bool = False,
        captured_image_path: str = None,
        camera_id: str = None,
    ) -> int:
        """
        recognition_result: 'Recognized' | 'Unknown' | 'Failed'
        """
        query = """
            INSERT INTO recognition_logs (
                student_id, recognition_result, confidence_score,
                liveness_check, captured_image_path, camera_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (student_id, recognition_result, confidence_score, liveness_check, captured_image_path, camera_id)
        log_id = db.execute(query, params)
        logger.info(
            "Recognition log: result=%s student=%s confidence=%s (id=%s)",
            recognition_result, student_id, confidence_score, log_id,
        )
        return log_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(log_id: int) -> dict | None:
        return db.fetch_one("SELECT * FROM recognition_logs WHERE log_id = %s", (log_id,))

    @staticmethod
    def get_by_student(student_id: int, limit: int = 50) -> list:
        query = """
            SELECT * FROM recognition_logs
            WHERE student_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (student_id, limit))

    @staticmethod
    def get_recent(limit: int = 50) -> list:
        query = """
            SELECT rl.*, s.full_name, s.roll_number
            FROM recognition_logs rl
            LEFT JOIN students s ON s.student_id = rl.student_id
            ORDER BY rl.timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (limit,))

    @staticmethod
    def get_unknown_faces(start_date: str = None, end_date: str = None, limit: int = 100) -> list:
        query = "SELECT * FROM recognition_logs WHERE recognition_result = 'Unknown'"
        params = []
        if start_date and end_date:
            query += " AND DATE(timestamp) BETWEEN %s AND %s"
            params += [start_date, end_date]
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        return db.fetch_all(query, tuple(params))

    @staticmethod
    def get_by_camera(camera_id: str, limit: int = 100) -> list:
        query = """
            SELECT * FROM recognition_logs
            WHERE camera_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (camera_id, limit))

    # ------------------------------------------------------------
    # Analytics (dashboard "Face Recognition Accuracy" card)
    # ------------------------------------------------------------
    @staticmethod
    def get_accuracy_stats(start_date: str = None, end_date: str = None) -> dict:
        query = """
            SELECT
                COUNT(*) AS total_attempts,
                SUM(CASE WHEN recognition_result = 'Recognized' THEN 1 ELSE 0 END) AS recognized,
                SUM(CASE WHEN recognition_result = 'Unknown' THEN 1 ELSE 0 END) AS unknown_count,
                SUM(CASE WHEN recognition_result = 'Failed' THEN 1 ELSE 0 END) AS failed,
                AVG(confidence_score) AS avg_confidence
            FROM recognition_logs
        """
        params = []
        if start_date and end_date:
            query += " WHERE DATE(timestamp) BETWEEN %s AND %s"
            params = [start_date, end_date]

        result = db.fetch_one(query, tuple(params)) or {}
        total = result.get("total_attempts") or 0
        recognized = result.get("recognized") or 0
        return {
            "total_attempts": total,
            "recognized": recognized,
            "unknown_count": result.get("unknown_count") or 0,
            "failed": result.get("failed") or 0,
            "avg_confidence": round(float(result.get("avg_confidence") or 0), 3),
            "accuracy_percentage": round((recognized / total) * 100, 1) if total else 0.0,
        }

    @staticmethod
    def get_daily_recognition_volume(start_date: str, end_date: str) -> list:
        query = """
            SELECT DATE(timestamp) AS log_date,
                   COUNT(*) AS total_attempts,
                   SUM(CASE WHEN recognition_result = 'Recognized' THEN 1 ELSE 0 END) AS recognized
            FROM recognition_logs
            WHERE DATE(timestamp) BETWEEN %s AND %s
            GROUP BY DATE(timestamp)
            ORDER BY log_date ASC
        """
        return db.fetch_all(query, (start_date, end_date))

    # ------------------------------------------------------------
    # Delete / housekeeping
    # ------------------------------------------------------------
    @staticmethod
    def delete_older_than(days: int) -> int:
        query = "DELETE FROM recognition_logs WHERE timestamp < (NOW() - INTERVAL %s DAY)"
        rows_affected = db.execute(query, (days,))
        logger.info("Cleaned up %s recognition logs older than %s days.", rows_affected, days)
        return rows_affected