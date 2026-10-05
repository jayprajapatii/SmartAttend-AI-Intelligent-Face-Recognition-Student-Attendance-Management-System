"""
core/notifications/whatsapp_service.py

Sends WhatsApp (and optionally plain SMS) notifications via Twilio
(config.TWILIO_CONFIG). Consumes `Pending` rows created by
NotificationModel.create(notification_type="WhatsApp") and marks each
as Sent or Failed after attempting delivery. Optional feature per the
spec - gracefully reports "not configured" rather than crashing when
Twilio credentials aren't set.

Usage:
    from core.notifications.whatsapp_service import whatsapp_service

    whatsapp_service.send_notification(notification_id)
    sent, failed = whatsapp_service.process_pending_queue()

    # Ad-hoc send:
    whatsapp_service.send_raw(to="+15551234567", body="Attendance marked.")
"""

import logging
from importlib import import_module

import config
from database.models.notification_model import NotificationModel
from database.models.student_model import StudentModel
from database.models.faculty_model import FacultyModel

logger = logging.getLogger("SmartAttendAI.core.notifications.whatsapp_service")

try:
    # Twilio is optional; load it dynamically so static analysis does not
    # report an unresolved import when the package is not installed.
    TwilioClient = import_module("twilio.rest").Client
    TwilioRestException = import_module("twilio.base.exceptions").TwilioRestException
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logger.info("twilio package not installed - WhatsApp/SMS notifications unavailable.")

# Recipient phone-number lookups. "Parent" uses parent_contact, which
# the schema stores as a phone number - the natural fit for this channel.
RECIPIENT_PHONE_LOOKUP = {
    "Student": lambda rid: (StudentModel.get_by_id(rid) or {}).get("phone_number"),
    "Parent": lambda rid: (StudentModel.get_by_id(rid) or {}).get("parent_contact"),
    "Faculty": lambda rid: (FacultyModel.get_by_id(rid) or {}).get("phone"),
}


class WhatsAppService:
    """Twilio-backed WhatsApp/SMS sender, wired to the `notifications` table's Pending queue."""

    def __init__(self):
        self.account_sid = config.TWILIO_CONFIG["account_sid"]
        self.auth_token = config.TWILIO_CONFIG["auth_token"]
        self.from_number = config.TWILIO_CONFIG["whatsapp_number"]
        self._client = None

        if self.is_configured():
            try:
                self._client = TwilioClient(self.account_sid, self.auth_token)
            except Exception as exc:
                logger.error("Failed to initialize Twilio client: %s", exc)

    def is_configured(self) -> bool:
        return bool(TWILIO_AVAILABLE and self.account_sid and self.auth_token and self.from_number)

    # ------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------
    def send_raw(self, to: str, body: str, as_sms: bool = False) -> bool:
        if not self.is_configured() or self._client is None:
            logger.error("Twilio is not configured (missing account_sid/auth_token/whatsapp_number) - cannot send.")
            return False
        if not to:
            logger.error("No recipient phone number provided - cannot send.")
            return False

        to_address = to if as_sms else self._as_whatsapp_address(to)
        from_address = self._format_from_number(as_sms)

        try:
            message = self._client.messages.create(body=body, from_=from_address, to=to_address)
            logger.info("%s sent to %s (sid=%s).", "SMS" if as_sms else "WhatsApp message", to, message.sid)
            return True
        except TwilioRestException as exc:
            logger.error("Twilio API error sending to %s: %s", to, exc)
        except Exception as exc:
            logger.error("Failed to send WhatsApp/SMS to %s: %s", to, exc)

        return False

    def _format_from_number(self, as_sms: bool) -> str:
        if as_sms:
            return self.from_number
        return self._as_whatsapp_address(self.from_number)

    @staticmethod
    def _as_whatsapp_address(number: str) -> str:
        number = number.strip()
        return number if number.startswith("whatsapp:") else f"whatsapp:{number}"

    # ------------------------------------------------------------
    # Queue-backed send (via the `notifications` table)
    # ------------------------------------------------------------
    def send_notification(self, notification_id: int) -> bool:
        notification = NotificationModel.get_by_id(notification_id)
        if not notification:
            logger.error("Notification id=%s not found.", notification_id)
            return False

        if notification["notification_type"] != "WhatsApp":
            logger.warning(
                "Notification id=%s is type '%s', not 'WhatsApp' - skipping in WhatsAppService.",
                notification_id, notification["notification_type"],
            )
            return False

        recipient_phone = self._resolve_recipient_phone(
            notification["recipient_type"], notification["recipient_id"]
        )

        if not recipient_phone:
            logger.error(
                "Could not resolve a phone number for %s id=%s - marking notification as failed.",
                notification["recipient_type"], notification["recipient_id"],
            )
            NotificationModel.mark_failed(notification_id)
            return False

        success = self.send_raw(to=recipient_phone, body=notification["message"])

        if success:
            NotificationModel.mark_sent(notification_id)
        else:
            NotificationModel.mark_failed(notification_id)

        return success

    def process_pending_queue(self, limit: int = 50) -> tuple:
        """Processes all Pending WhatsApp notifications. Returns (sent_count, failed_count)."""
        pending = [n for n in NotificationModel.get_pending(limit=limit) if n["notification_type"] == "WhatsApp"]

        sent_count = 0
        failed_count = 0
        for notification in pending:
            if self.send_notification(notification["notification_id"]):
                sent_count += 1
            else:
                failed_count += 1

        if pending:
            logger.info("WhatsApp queue processed: %d sent, %d failed (of %d pending).",
                        sent_count, failed_count, len(pending))
        return sent_count, failed_count

    @staticmethod
    def _resolve_recipient_phone(recipient_type: str, recipient_id: int):
        resolver = RECIPIENT_PHONE_LOOKUP.get(recipient_type)
        if not resolver:
            return None
        try:
            return resolver(recipient_id)
        except Exception as exc:
            logger.error("Failed to resolve phone number for %s id=%s: %s", recipient_type, recipient_id, exc)
            return None


# Singleton instance - import this everywhere instead of instantiating directly
whatsapp_service = WhatsAppService()