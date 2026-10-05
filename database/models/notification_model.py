"""
database/models/notification_model.py

CRUD + status tracking for the `notifications` table.
Actual sending (SMTP/Twilio/Firebase) lives in core/notifications/*;
this model only persists the notification record and its delivery status.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.notification")


class NotificationModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(
        recipient_type: str,
        recipient_id: int,
        notification_type: str,
        message: str,
        subject: str = None,
        status: str = "Pending",
    ) -> int:
        query = """
            INSERT INTO notifications (
                recipient_type, recipient_id, notification_type, subject, message, status
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (recipient_type, recipient_id, notification_type, subject, message, status)
        notification_id = db.execute(query, params)
        logger.info(
            "Notification queued: type=%s recipient=%s(%s) (id=%s)",
            notification_type, recipient_type, recipient_id, notification_id,
        )
        return notification_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(notification_id: int) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM notifications WHERE notification_id = %s", (notification_id,)
        )

    @staticmethod
    def get_by_recipient(recipient_type: str, recipient_id: int) -> list:
        query = """
            SELECT * FROM notifications
            WHERE recipient_type = %s AND recipient_id = %s
            ORDER BY created_at DESC
        """
        return db.fetch_all(query, (recipient_type, recipient_id))

    @staticmethod
    def get_pending(limit: int = 50) -> list:
        """Fetched by a background worker/queue to actually dispatch notifications."""
        query = """
            SELECT * FROM notifications
            WHERE status = 'Pending'
            ORDER BY created_at ASC
            LIMIT %s
        """
        return db.fetch_all(query, (limit,))

    @staticmethod
    def get_failed(limit: int = 50) -> list:
        query = """
            SELECT * FROM notifications
            WHERE status = 'Failed'
            ORDER BY created_at DESC
            LIMIT %s
        """
        return db.fetch_all(query, (limit,))

    @staticmethod
    def get_recent(limit: int = 20) -> list:
        return db.fetch_all(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT %s", (limit,)
        )

    # ------------------------------------------------------------
    # Update status (called after attempting delivery)
    # ------------------------------------------------------------
    @staticmethod
    def mark_sent(notification_id: int) -> int:
        rows_affected = db.execute(
            "UPDATE notifications SET status = 'Sent', sent_at = NOW() WHERE notification_id = %s",
            (notification_id,),
        )
        logger.info("Notification %s marked as Sent.", notification_id)
        return rows_affected

    @staticmethod
    def mark_failed(notification_id: int) -> int:
        rows_affected = db.execute(
            "UPDATE notifications SET status = 'Failed' WHERE notification_id = %s",
            (notification_id,),
        )
        logger.warning("Notification %s marked as Failed.", notification_id)
        return rows_affected

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    @staticmethod
    def delete(notification_id: int) -> int:
        return db.execute(
            "DELETE FROM notifications WHERE notification_id = %s", (notification_id,)
        )

    @staticmethod
    def delete_older_than(days: int) -> int:
        """Housekeeping - clean up old sent notifications."""
        query = """
            DELETE FROM notifications
            WHERE status = 'Sent' AND sent_at < (NOW() - INTERVAL %s DAY)
        """
        rows_affected = db.execute(query, (days,))
        logger.info("Cleaned up %s old notifications (older than %s days).", rows_affected, days)
        return rows_affected