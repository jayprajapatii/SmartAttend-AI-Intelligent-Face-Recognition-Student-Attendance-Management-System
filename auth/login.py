"""
auth/login.py

Login entry point used by ui/pages login screen (see main.py LoginPage).
Wraps AdminModel authentication, writes audit/security logs, and
returns a simple result dict the UI can act on.
"""

import logging

from database.models.admin_model import AdminModel
from database.models.security_log_model import SecurityLogModel
from auth.session_manager import session_manager

logger = logging.getLogger("SmartAttendAI.auth.login")

MAX_FAILED_ATTEMPTS = 5


def authenticate_user(username: str, password: str, ip_address: str = None) -> dict:
    """
    Validates credentials and starts a session on success.

    Returns:
        {
          "success": bool,
          "user": dict | None,      # admin record (no password_hash)
          "message": str,
        }
    """
    username = (username or "").strip()
    password = (password or "").strip()

    if not username or not password:
        return {"success": False, "user": None, "message": "Username and password are required."}

    user = AdminModel.authenticate(username, password)

    if not user:
        SecurityLogModel.log(
            event_type="Login Failure",
            description=f"Failed login attempt for username '{username}'.",
            ip_address=ip_address,
        )
        logger.warning("Authentication failed for username=%s", username)
        return {"success": False, "user": None, "message": "Invalid username or password."}

    session_manager.start_session(user)
    logger.info("Authentication succeeded for username=%s (role=%s)", username, user["role"])
    return {"success": True, "user": user, "message": "Login successful."}


def logout_user():
    """Ends the current session (called from sidebar / menu)."""
    session_manager.end_session()
    logger.info("User logged out.")


# Convenience alias matching what main.py's LoginPage tries to import
def authenticate(username: str, password: str) -> bool:
    """Simple boolean wrapper for quick UI wiring."""
    result = authenticate_user(username, password)
    return result["success"]