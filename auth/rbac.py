"""
auth/rbac.py

Role-Based Access Control.

Roles (matches admin_users.role ENUM): 'super_admin', 'admin', 'faculty'

Usage as a decorator (wrap any UI action / controller function):

    from auth.rbac import require_role

    @require_role("admin", "super_admin")
    def delete_student(student_id):
        ...

Usage as a direct check (e.g. to show/hide a sidebar button):

    from auth.rbac import can_access

    if can_access("settings"):
        show_settings_button()
"""

import logging
from functools import wraps

from auth.session_manager import session_manager

logger = logging.getLogger("SmartAttendAI.auth.rbac")


class PermissionDenied(Exception):
    """Raised when the current session's role is not permitted to perform an action."""
    pass


# ------------------------------------------------------------
# Role hierarchy (higher roles inherit lower-role permissions)
# ------------------------------------------------------------
ROLE_HIERARCHY = {
    "super_admin": 3,
    "admin": 2,
    "faculty": 1,
}

# ------------------------------------------------------------
# Feature -> minimum required role
# Adjust freely as pages/features are built out.
# ------------------------------------------------------------
FEATURE_PERMISSIONS = {
    "dashboard": "faculty",
    "students": "admin",
    "students.delete": "super_admin",
    "faculty": "admin",
    "faculty.delete": "super_admin",
    "dataset_generator": "admin",
    "face_recognition": "faculty",
    "attendance": "faculty",
    "attendance.edit": "admin",
    "reports": "faculty",
    "analytics": "admin",
    "settings": "super_admin",
    "admin_users.manage": "super_admin",
    "backup_restore": "super_admin",
    "help": "faculty",
}


def _role_level(role: str) -> int:
    return ROLE_HIERARCHY.get(role, 0)


def has_role(*allowed_roles: str) -> bool:
    """True if the current logged-in user's role is one of allowed_roles
    or ranks at/above the lowest of the allowed roles in the hierarchy."""
    current_role = session_manager.get_current_role()
    if not current_role:
        return False
    if current_role in allowed_roles:
        return True
    min_required_level = min(_role_level(r) for r in allowed_roles)
    return _role_level(current_role) >= min_required_level


def can_access(feature_key: str) -> bool:
    """Check access against the FEATURE_PERMISSIONS map (used to show/hide UI)."""
    required_role = FEATURE_PERMISSIONS.get(feature_key)
    if required_role is None:
        logger.warning("Unknown feature_key '%s' in RBAC check - denying by default.", feature_key)
        return False

    current_role = session_manager.get_current_role()
    if not current_role:
        return False

    return _role_level(current_role) >= _role_level(required_role)


def require_role(*allowed_roles: str):
    """Decorator: raises PermissionDenied if the session's role isn't allowed."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not has_role(*allowed_roles):
                current_role = session_manager.get_current_role()
                logger.warning(
                    "Access denied to '%s' for role='%s' (requires one of %s)",
                    func.__name__, current_role, allowed_roles,
                )
                raise PermissionDenied(
                    f"You do not have permission to perform this action. "
                    f"Requires role: {', '.join(allowed_roles)}."
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_feature(feature_key: str):
    """Decorator variant that checks against FEATURE_PERMISSIONS instead of explicit roles."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not can_access(feature_key):
                current_role = session_manager.get_current_role()
                logger.warning(
                    "Access denied to feature '%s' for role='%s'", feature_key, current_role
                )
                raise PermissionDenied(
                    f"You do not have permission to access '{feature_key}'."
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator