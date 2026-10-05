"""
core/notifications/push_service.py

Sends push notifications via Firebase Cloud Messaging (FCM), using
the service account credentials at config.FIREBASE_CREDENTIALS_PATH.
Consumes `Pending` rows created by
NotificationModel.create(notification_type="Push") and marks each as
Sent or Failed after attempting delivery. Optional feature per the
spec - gracefully reports "not configured" rather than crashing when
no Firebase credentials file is present.

Unlike email/phone, push notifications need a device FCM token, which
isn't part of the current schema. This service reads an optional
`fcm_token` field if present on the student/faculty/admin record (once
one is added), or accepts an explicit token via send_raw() for direct
calls from a mobile companion app integration.

Usage:
    from core.notifications.push_service import push_service

    push_service.send_notification(notification_id)
    sent, failed = push_service.process_pending_queue()

    # Ad-hoc send directly to a device token:
    push_service.send_raw(token="fcm_device_token_here", title="...", body="...")

    # Broadcast to a topic (e.g. all devices subscribed to "admin_alerts"):
    push_service.send_to_topic(topic="admin_alerts", title="...", body="...")
"""

import logging
from pathlib import Path

import config
from database.models.notification_model import NotificationModel
from database.models.student_model import StudentModel
from database.models.faculty_model import FacultyModel
from database.models.admin_model import AdminModel

logger = logging.getLogger("SmartAttendAI.core.notifications.push_service")

try:
    import firebase_admin  # type: ignore[import-not-found]
    from firebase_admin import credentials, messaging  # type: ignore[import-not-found]
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.info("firebase_admin package not installed - push notifications unavailable.")

# NOTE: no `fcm_token` column exists yet on students/faculty/admin_users.
# These lookups return None until such a column (or a separate
# device_tokens table, for multi-device support) is added - at which
# point just swap the lambda bodies below.
RECIPIENT_TOKEN_LOOKUP = {
    "Student": lambda rid: (StudentModel.get_by_id(rid) or {}).get("fcm_token"),
    "Faculty": lambda rid: (FacultyModel.get_by_id(rid) or {}).get("fcm_token"),
    "Admin": lambda rid: (AdminModel.get_by_id(rid) or {}).get("fcm_token"),
}


class PushService:
    """Firebase Cloud Messaging-backed push sender, wired to the `notifications` table's Pending queue."""

    def __init__(self):
        self._initialized = False
        self._try_initialize()

    def _try_initialize(self):
        if not FIREBASE_AVAILABLE:
            return

        credentials_path = config.FIREBASE_CREDENTIALS_PATH
        try:
            if not Path(credentials_path).exists():
                logger.info(
                    "No Firebase credentials file found at %s - push notifications unavailable "
                    "until one is provided.", credentials_path,
                )
                return

            if not firebase_admin._apps:  # avoid re-initializing on module reload
                cred = credentials.Certificate(credentials_path)
                firebase_admin.initialize_app(cred)

            self._initialized = True
            logger.info("Firebase Admin SDK initialized for push notifications.")
        except Exception as exc:
            logger.error("Failed to initialize Firebase Admin SDK: %s", exc)

    def is_configured(self) -> bool:
        return FIREBASE_AVAILABLE and self._initialized

    # ------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------
    def send_raw(self, token: str, title: str, body: str, data: dict = None) -> bool:
        if not self.is_configured():
            logger.error("Firebase is not configured - cannot send push notification.")
            return False
        if not token:
            logger.error("No FCM device token provided - cannot send.")
            return False

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token,
        )

        try:
            response = messaging.send(message)
            logger.info("Push notification sent (message id=%s).", response)
            return True
        except messaging.UnregisteredError:
            logger.warning("FCM token is no longer valid (device unregistered) - notification not delivered.")
        except Exception as exc:
            logger.error("Failed to send push notification: %s", exc)

        return False

    def send_to_topic(self, topic: str, title: str, body: str, data: dict = None) -> bool:
        """Broadcasts to all devices subscribed to a topic (e.g. 'admin_alerts')."""
        if not self.is_configured():
            logger.error("Firebase is not configured - cannot send topic push notification.")
            return False

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            topic=topic,
        )

        try:
            response = messaging.send(message)
            logger.info("Push notification sent to topic '%s' (message id=%s).", topic, response)
            return True
        except Exception as exc:
            logger.error("Failed to send push notification to topic '%s': %s", topic, exc)
            return False

    # ------------------------------------------------------------
    # Queue-backed send (via the `notifications` table)
    # ------------------------------------------------------------
    def send_notification(self, notification_id: int) -> bool:
        notification = NotificationModel.get_by_id(notification_id)
        if not notification:
            logger.error("Notification id=%s not found.", notification_id)
            return False

        if notification["notification_type"] != "Push":
            logger.warning(
                "Notification id=%s is type '%s', not 'Push' - skipping in PushService.",
                notification_id, notification["notification_type"],
            )
            return False

        token = self._resolve_recipient_token(notification["recipient_type"], notification["recipient_id"])

        if not token:
            logger.error(
                "Could not resolve an FCM token for %s id=%s - marking notification as failed.",
                notification["recipient_type"], notification["recipient_id"],
            )
            NotificationModel.mark_failed(notification_id)
            return False

        success = self.send_raw(
            token=token,
            title=notification.get("subject") or config.APP_NAME,
            body=notification["message"],
        )

        if success:
            NotificationModel.mark_sent(notification_id)
        else:
            NotificationModel.mark_failed(notification_id)

        return success

    def process_pending_queue(self, limit: int = 50) -> tuple:
        """Processes all Pending Push notifications. Returns (sent_count, failed_count)."""
        pending = [n for n in NotificationModel.get_pending(limit=limit) if n["notification_type"] == "Push"]

        sent_count = 0
        failed_count = 0
        for notification in pending:
            if self.send_notification(notification["notification_id"]):
                sent_count += 1
            else:
                failed_count += 1

        if pending:
            logger.info("Push queue processed: %d sent, %d failed (of %d pending).",
                        sent_count, failed_count, len(pending))
        return sent_count, failed_count

    @staticmethod
    def _resolve_recipient_token(recipient_type: str, recipient_id: int):
        resolver = RECIPIENT_TOKEN_LOOKUP.get(recipient_type)
        if not resolver:
            return None
        try:
            return resolver(recipient_id)
        except Exception as exc:
            logger.error("Failed to resolve FCM token for %s id=%s: %s", recipient_type, recipient_id, exc)
            return None


# Singleton instance - import this everywhere instead of instantiating directly
push_service = PushService()