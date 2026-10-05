"""
security/audit_logger.py

Centralized audit logging: records who (admin_id) did what
(action_performed) to which record (table_affected, record_id) and
when, per the "Audit Logs" security requirement. No AuditLogModel
exists yet in database/models/, so this module is the audit_logs
table's interface for now - written the same way the model layer is
(parameterized queries via db_connector), so promoting it to
database/models/audit_log_model.py later is a pure file move.

This is deliberately separate from security_logs (SecurityLogModel) -
security_logs is for suspicious/security-relevant EVENTS (unknown
faces, spoof attempts, login failures); audit_logs is for routine
ADMINISTRATIVE ACTIONS (an admin edited a student record, changed a
setting, deleted a faculty member) - a compliance/accountability
trail, not a threat-detection feed.

Usage:
    from security.audit_logger import audit_logger

    audit_logger.log(
        admin_id=current_admin_id,
        action="Updated student record",
        table_affected="students",
        record_id=student_id,
    )

    # Convenience wrapper that also runs the mutation and logs it atomically:
    audit_logger.log_and_execute(
        admin_id=current_admin_id,
        action="Deactivated student",
        table_affected="students",
        record_id=student_id,
        mutation=lambda: StudentModel.soft_delete(student_id),
    )
"""

import logging

from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.security.audit_logger")


class AuditLogger:
    """Write-and-query interface for the audit_logs table."""

    # ------------------------------------------------------------
    # Write
    # ------------------------------------------------------------
    @staticmethod
    def log(admin_id: int, action: str, table_affected: str = None, record_id: int = None) -> int:
        query = """
            INSERT INTO audit_logs (admin_id, action_performed, table_affected, record_id)
            VALUES (%s, %s, %s, %s)
        """
        try:
            audit_id = db.execute(query, (admin_id, action, table_affected, record_id))
            logger.info(
                "Audit: admin_id=%s action='%s' table=%s record_id=%s",
                admin_id, action, table_affected, record_id,
            )
            return audit_id
        except Exception as exc:
            # Audit logging failures should never block the underlying
            # action from completing - log locally and move on.
            logger.error("Failed to write audit log entry: %s", exc)
            return -1

    @staticmethod
    def log_and_execute(admin_id: int, action: str, mutation, table_affected: str = None, record_id: int = None):
        """
        Runs `mutation` (a zero-arg callable performing the actual DB
        change) and writes the audit entry, in that order - so an
        audit entry is only created if the mutation itself succeeded.
        Returns whatever `mutation()` returns.
        """
        result = mutation()
        AuditLogger.log(admin_id, action, table_affected, record_id)
        return result

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_recent(limit: int = 100) -> list:
        query = """
            SELECT al.*, au.username AS admin_username
            FROM audit_logs al
            LEFT JOIN admin_users au ON au.admin_id = al.admin_id
            ORDER BY al.timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (limit,))

    @staticmethod
    def get_by_admin(admin_id: int, limit: int = 100) -> list:
        query = """
            SELECT * FROM audit_logs
            WHERE admin_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (admin_id, limit))

    @staticmethod
    def get_by_table(table_affected: str, limit: int = 100) -> list:
        query = """
            SELECT al.*, au.username AS admin_username
            FROM audit_logs al
            LEFT JOIN admin_users au ON au.admin_id = al.admin_id
            WHERE al.table_affected = %s
            ORDER BY al.timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (table_affected, limit))

    @staticmethod
    def get_by_record(table_affected: str, record_id: int) -> list:
        """Full change history for one specific record, e.g. one student's edit trail."""
        query = """
            SELECT al.*, au.username AS admin_username
            FROM audit_logs al
            LEFT JOIN admin_users au ON au.admin_id = al.admin_id
            WHERE al.table_affected = %s AND al.record_id = %s
            ORDER BY al.timestamp ASC
        """
        return db.fetch_all(query, (table_affected, record_id))

    @staticmethod
    def get_by_date_range(start_date: str, end_date: str, limit: int = 500) -> list:
        query = """
            SELECT al.*, au.username AS admin_username
            FROM audit_logs al
            LEFT JOIN admin_users au ON au.admin_id = al.admin_id
            WHERE DATE(al.timestamp) BETWEEN %s AND %s
            ORDER BY al.timestamp DESC
            LIMIT %s
        """
        return db.fetch_all(query, (start_date, end_date, limit))

    # ------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------
    @staticmethod
    def delete_older_than(days: int) -> int:
        """
        Use with caution - audit trails are often required to be kept
        for a minimum retention period by institutional policy. Confirm
        your retention requirements before calling this.
        """
        query = "DELETE FROM audit_logs WHERE timestamp < (NOW() - INTERVAL %s DAY)"
        rows_affected = db.execute(query, (days,))
        logger.info("Cleaned up %d audit log entries older than %d days.", rows_affected, days)
        return rows_affected


# Singleton instance - import this everywhere instead of instantiating directly
audit_logger = AuditLogger()