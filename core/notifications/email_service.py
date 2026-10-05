"""
core/notifications/email_service.py

Sends email notifications via SMTP (config.SMTP_CONFIG). Consumes
`Pending` rows created by NotificationModel.create(notification_type="Email")
- e.g. from auth/otp_verification.py, or attendance confirmations -
and marks each as Sent or Failed after attempting delivery.

Usage:
    from core.notifications.email_service import email_service

    # Send one notification record immediately:
    email_service.send_notification(notification_id)

    # Or process the whole pending queue (call periodically, e.g. from
    # a background scheduler or a "Send Now" button in the admin panel):
    sent, failed = email_service.process_pending_queue()

    # Or send an ad-hoc email without going through the notifications table:
    email_service.send_raw(to="student@example.com", subject="...", body="...")
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from database.models.notification_model import NotificationModel
from database.models.student_model import StudentModel
from database.models.faculty_model import FacultyModel
from database.models.admin_model import AdminModel

logger = logging.getLogger("SmartAttendAI.core.notifications.email_service")

# NOTE: `parent_contact` in the students table is currently a phone
# number field per the schema, not an email address. Parent email
# notifications will fail to resolve until either a dedicated
# parent_email column is added, or this lookup is pointed at one.
RECIPIENT_EMAIL_LOOKUP = {
    "Student": lambda rid: (StudentModel.get_by_id(rid) or {}).get("email"),
    "Parent": lambda rid: (StudentModel.get_by_id(rid) or {}).get("parent_contact"),
    "Faculty": lambda rid: (FacultyModel.get_by_id(rid) or {}).get("email"),
    "Admin": lambda rid: (AdminModel.get_by_id(rid) or {}).get("email"),
}


class EmailService:
    """SMTP-backed email sender, wired to the `notifications` table's Pending queue."""

    def __init__(self):
        self.host = config.SMTP_CONFIG["host"]
        self.port = config.SMTP_CONFIG["port"]
        self.username = config.SMTP_CONFIG["username"]
        self.password = config.SMTP_CONFIG["password"]
        self.from_name = config.SMTP_CONFIG["from_name"]

    def is_configured(self) -> bool:
        return bool(self.host and self.username and self.password)

    # ------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------
    def send_raw(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        if not self.is_configured():
            logger.error("SMTP is not configured (missing host/username/password) - cannot send email.")
            return False
        if not to:
            logger.error("No recipient email address provided - cannot send.")
            return False

        message = MIMEMultipart()
        message["From"] = f"{self.from_name} <{self.username}>"
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(body, "html" if html else "plain"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, to, message.as_string())
            logger.info("Email sent to %s (subject: %s).", to, subject)
            return True
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("SMTP authentication failed - check SMTP_USERNAME/SMTP_PASSWORD: %s", exc)
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)

        return False

    # ------------------------------------------------------------
    # Queue-backed send (via the `notifications` table)
    # ------------------------------------------------------------
    def send_notification(self, notification_id: int) -> bool:
        notification = NotificationModel.get_by_id(notification_id)
        if not notification:
            logger.error("Notification id=%s not found.", notification_id)
            return False

        if notification["notification_type"] != "Email":
            logger.warning(
                "Notification id=%s is type '%s', not 'Email' - skipping in EmailService.",
                notification_id, notification["notification_type"],
            )
            return False

        recipient_email = self._resolve_recipient_email(
            notification["recipient_type"], notification["recipient_id"]
        )

        if not recipient_email:
            logger.error(
                "Could not resolve an email address for %s id=%s - marking notification as failed.",
                notification["recipient_type"], notification["recipient_id"],
            )
            NotificationModel.mark_failed(notification_id)
            return False

        success = self.send_raw(
            to=recipient_email,
            subject=notification.get("subject") or "SmartAttend AI Notification",
            body=notification["message"],
        )

        if success:
            NotificationModel.mark_sent(notification_id)
        else:
            NotificationModel.mark_failed(notification_id)

        return success

    def process_pending_queue(self, limit: int = 50) -> tuple:
        """
        Processes all Pending Email notifications. Returns (sent_count, failed_count).
        Call this periodically (e.g. a background thread, or a manual
        "Send Now" trigger from the admin panel) since notifications
        are created as Pending and don't send themselves.
        """
        pending = [n for n in NotificationModel.get_pending(limit=limit) if n["notification_type"] == "Email"]

        sent_count = 0
        failed_count = 0
        for notification in pending:
            if self.send_notification(notification["notification_id"]):
                sent_count += 1
            else:
                failed_count += 1

        if pending:
            logger.info("Email queue processed: %d sent, %d failed (of %d pending).",
                        sent_count, failed_count, len(pending))
        return sent_count, failed_count

    @staticmethod
    def _resolve_recipient_email(recipient_type: str, recipient_id: int):
        resolver = RECIPIENT_EMAIL_LOOKUP.get(recipient_type)
        if not resolver:
            return None
        try:
            return resolver(recipient_id)
        except Exception as exc:
            logger.error("Failed to resolve email for %s id=%s: %s", recipient_type, recipient_id, exc)
            return None


# Singleton instance - import this everywhere instead of instantiating directly
email_service = EmailService()