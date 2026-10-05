"""
database/models/security_log_model.py

CRUD + query operations for the `security_logs` table.
Captures security-relevant events: unknown faces, spoof attempts,
multiple simultaneous faces, login failures - feeds the admin
security dashboard and the "Unknown Person Alerts" notification flow.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.security_log")


class SecurityLogModel:

    VALID_EVENT_TYPES = {"Unknown Face", "Spoof Attempt", "Multiple Faces", "Login Failure"}

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def log(
        event_type: str,
        description: str = None,
        image_path: str = None,
        ip_address: str = None,
    ) -> int:
        if event_type not in SecurityLogModel.VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type '{event_type}'. Must be one of {SecurityLogModel.VALID_EVENT_TYPES}")

        query = """
            INSERT INTO security_logs (event_type, description, image_path, ip_address)
            VALUES (%s, %s, %s, %s)
        """
        log_id = db.execute(query, (event_type, description, image_path, ip_address))
        logger.warning("Security event logged: %s (id=%s) - %s", event_type, log_id, description)
        return log_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(security_log_id: int) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM security_logs WHERE security_log_id = %s", (security_log_id,)
        )

    @staticmethod
    def get_all(resolved: bool = None, limit: int = 100) -> list:
        query = "SELECT * FROM security_logs"
        params = []
        if resolved is not None:
            query += " WHERE resolved = %s"
            params.append(resolved)
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        return db.fetch_all(query, tuple(params))

    @staticmethod
    def get_unresolved(limit: int = 100) -> list:
        return SecurityLogModel.get_all(resolved=False, limit=limit)

    @staticmethod
    def get_by_event_type(event_type: str, limit: int = 100) -> list:
        query = """
            SELECT * FROM security_logs
            WHERE event_type = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (event_type, limit))

    @staticmethod
    def get_by_date_range(start_date: str, end_date: str) -> list:
        query = """
            SELECT * FROM security_logs
            WHERE DATE(timestamp) BETWEEN %s AND %s
            ORDER BY timestamp DESC
        """
        return db.fetch_all(query, (start_date, end_date))

    @staticmethod
    def count_by_event_type(start_date: str = None, end_date: str = None) -> list:
        """Grouped counts - used for the security overview chart."""
        query = "SELECT event_type, COUNT(*) AS total FROM security_logs"
        params = []
        if start_date and end_date:
            query += " WHERE DATE(timestamp) BETWEEN %s AND %s"
            params = [start_date, end_date]
        query += " GROUP BY event_type ORDER BY total DESC"
        return db.fetch_all(query, tuple(params))

    # ------------------------------------------------------------
    # Update
    # ------------------------------------------------------------
    @staticmethod
    def mark_resolved(security_log_id: int) -> int:
        rows_affected = db.execute(
            "UPDATE security_logs SET resolved = TRUE WHERE security_log_id = %s",
            (security_log_id,),
        )
        logger.info("Security log %s marked resolved.", security_log_id)
        return rows_affected

    @staticmethod
    def mark_unresolved(security_log_id: int) -> int:
        rows_affected = db.execute(
            "UPDATE security_logs SET resolved = FALSE WHERE security_log_id = %s",
            (security_log_id,),
        )
        return rows_affected

    # ------------------------------------------------------------
    # Delete / housekeeping
    # ------------------------------------------------------------
    @staticmethod
    def delete(security_log_id: int) -> int:
        rows_affected = db.execute(
            "DELETE FROM security_logs WHERE security_log_id = %s", (security_log_id,)
        )
        logger.info("Security log %s deleted.", security_log_id)
        return rows_affected

    @staticmethod
    def delete_resolved_older_than(days: int) -> int:
        query = """
            DELETE FROM security_logs
            WHERE resolved = TRUE AND timestamp < (NOW() - INTERVAL %s DAY)
        """
        rows_affected = db.execute(query, (days,))
        logger.info("Cleaned up %s resolved security logs older than %s days.", rows_affected, days)
        return rows_affected