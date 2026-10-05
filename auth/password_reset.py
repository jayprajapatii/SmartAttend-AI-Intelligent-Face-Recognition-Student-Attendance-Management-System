"""
auth/password_reset.py

Forgot-password (OTP-based reset) and change-password (while logged
in) flows. Builds on otp_verification.py + AdminModel.
"""

import logging
import re

from database.models.admin_model import AdminModel
from database.models.security_log_model import SecurityLogModel
from auth.otp_verification import verify_otp

logger = logging.getLogger("SmartAttendAI.auth.password_reset")

MIN_PASSWORD_LENGTH = 8


def _validate_password_strength(password: str) -> str | None:
    """Returns an error message if invalid, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number."
    return None


# ------------------------------------------------------------
# Forgot password (unauthenticated - via OTP)
# ------------------------------------------------------------
def reset_password_with_otp(username: str, otp_code: str, new_password: str, confirm_password: str) -> dict:
    """
    Full "Forgot Password" flow: verify OTP, then set the new password.

    Returns:
        {"success": bool, "message": str}
    """
    if new_password != confirm_password:
        return {"success": False, "message": "Passwords do not match."}

    strength_error = _validate_password_strength(new_password)
    if strength_error:
        return {"success": False, "message": strength_error}

    otp_result = verify_otp(username, otp_code)
    if not otp_result["success"]:
        return {"success": False, "message": otp_result["message"]}

    user = AdminModel.get_by_username(username)
    if not user:
        return {"success": False, "message": "Account not found."}

    AdminModel.change_password(user["admin_id"], new_password)
    logger.info("Password reset via OTP for username=%s", username)
    return {"success": True, "message": "Your password has been reset. Please log in."}


# ------------------------------------------------------------
# Change password (authenticated - user knows current password)
# ------------------------------------------------------------
def change_password(admin_id: int, current_password: str, new_password: str, confirm_password: str) -> dict:
    """
    "Change Password" flow, used from the Settings page while logged in.

    Returns:
        {"success": bool, "message": str}
    """
    if new_password != confirm_password:
        return {"success": False, "message": "New passwords do not match."}

    if new_password == current_password:
        return {"success": False, "message": "New password must be different from the current password."}

    strength_error = _validate_password_strength(new_password)
    if strength_error:
        return {"success": False, "message": strength_error}

    user = AdminModel.get_by_id(admin_id)
    if not user:
        return {"success": False, "message": "Account not found."}

    if not AdminModel.verify_password(current_password, user["password_hash"]):
        SecurityLogModel.log(
            event_type="Login Failure",
            description=f"Incorrect current password on change-password attempt (admin_id={admin_id}).",
        )
        return {"success": False, "message": "Current password is incorrect."}

    AdminModel.change_password(admin_id, new_password)
    logger.info("Password changed for admin_id=%s", admin_id)
    return {"success": True, "message": "Password changed successfully."}