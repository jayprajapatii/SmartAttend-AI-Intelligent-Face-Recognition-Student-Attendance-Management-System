"""
auth/otp_verification.py

OTP generation + verification for forgot-password flow and optional
multi-factor authentication (MFA) on login.

Delegates OTP storage to AdminModel (otp_code / otp_expiry columns)
and delivery to the notification model (actual sending happens via
core/notifications/email_service.py or whatsapp_service.py).
"""

import logging

from database.models.admin_model import AdminModel
from database.models.notification_model import NotificationModel

logger = logging.getLogger("SmartAttendAI.auth.otp")

OTP_EXPIRY_MINUTES = 10


def request_otp(username: str) -> dict:
    """
    Generates an OTP for the given user and queues it for delivery
    (email by default). Call this from the "Forgot Password" screen
    or when MFA is enabled for a login.

    Returns:
        {"success": bool, "message": str}
    """
    user = AdminModel.get_by_username(username)
    if not user:
        # Do not reveal whether the username exists - generic message
        logger.warning("OTP requested for unknown username=%s", username)
        return {"success": True, "message": "If the account exists, an OTP has been sent."}

    otp_code = AdminModel.generate_otp(username, expiry_minutes=OTP_EXPIRY_MINUTES)
    if not otp_code:
        return {"success": False, "message": "Could not generate OTP. Please try again."}

    message = (
        f"Your SmartAttend AI verification code is: {otp_code}\n"
        f"This code expires in {OTP_EXPIRY_MINUTES} minutes. "
        f"Do not share this code with anyone."
    )
    NotificationModel.create(
        recipient_type="Admin",
        recipient_id=user["admin_id"],
        notification_type="Email",
        subject="SmartAttend AI - Your Verification Code",
        message=message,
        status="Pending",  # picked up and actually sent by the notification worker
    )

    logger.info("OTP generated and queued for delivery: username=%s", username)
    return {"success": True, "message": "An OTP has been sent to your registered email."}


def verify_otp(username: str, otp_code: str) -> dict:
    """
    Verifies a previously issued OTP.

    Returns:
        {"success": bool, "message": str}
    """
    otp_code = (otp_code or "").strip()
    if not otp_code or len(otp_code) != 6 or not otp_code.isdigit():
        return {"success": False, "message": "Enter the 6-digit code sent to your email."}

    is_valid = AdminModel.verify_otp(username, otp_code)

    if is_valid:
        logger.info("OTP verified successfully for username=%s", username)
        return {"success": True, "message": "Verification successful."}

    logger.warning("OTP verification failed for username=%s", username)
    return {"success": False, "message": "Invalid or expired code. Please try again."}


def resend_otp(username: str) -> dict:
    """Simple alias - generates and queues a fresh OTP, invalidating the old one."""
    return request_otp(username)