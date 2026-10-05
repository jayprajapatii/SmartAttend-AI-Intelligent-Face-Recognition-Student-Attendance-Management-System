"""
security/input_validator.py

Centralized input validation and sanitization for user-submitted data
across the app: email/phone/enrollment-number format checks, string
length limits, and whitespace/control-character sanitization. UI
pages (student_registration_page.py, faculty_management_page.py,
login_page.py, etc.) should validate through here before handing data
to the model layer, rather than each page hand-rolling its own regex.

This is distinct from sql_injection_guard.py: that module defends the
database layer (identifier whitelisting, pattern detection on raw
SQL-adjacent input); this module is about data quality and basic
input hygiene for what's ultimately going into parameterized queries
either way.

Usage:
    from security.input_validator import input_validator

    result = input_validator.validate_email("student@example.com")
    if not result.is_valid:
        show_error(result.reason)

    clean_name = input_validator.sanitize_text(raw_name, max_length=100)
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("SmartAttendAI.security.input_validator")

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9]{7,15}$")
ENROLLMENT_PATTERN = re.compile(r"^[A-Za-z0-9\-/]{3,30}$")
ROLL_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9\-]{1,20}$")
NAME_PATTERN = re.compile(r"^[A-Za-z .'\-]{2,100}$")

# Strips control characters (except common whitespace) that have no
# business appearing in names, addresses, etc. and can cause display
# or export issues (e.g. in CSV/PDF reports).
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str = ""
    cleaned_value: str = None


class InputValidator:
    """Stateless validation/sanitization helpers - all methods are safe to call as static-style utilities."""

    # ------------------------------------------------------------
    # Format validators
    # ------------------------------------------------------------
    @staticmethod
    def validate_email(value: str, required: bool = True) -> ValidationResult:
        value = (value or "").strip()
        if not value:
            return ValidationResult(is_valid=not required, reason="" if not required else "Email is required.")

        if len(value) > 254:
            return ValidationResult(is_valid=False, reason="Email address is too long.")
        if not EMAIL_PATTERN.match(value):
            return ValidationResult(is_valid=False, reason="Enter a valid email address.")

        return ValidationResult(is_valid=True, cleaned_value=value.lower())

    @staticmethod
    def validate_phone(value: str, required: bool = True) -> ValidationResult:
        value = (value or "").strip().replace(" ", "").replace("-", "")
        if not value:
            return ValidationResult(is_valid=not required, reason="" if not required else "Phone number is required.")

        if not PHONE_PATTERN.match(value):
            return ValidationResult(is_valid=False, reason="Enter a valid phone number (7-15 digits, optional +country code).")

        return ValidationResult(is_valid=True, cleaned_value=value)

    @staticmethod
    def validate_enrollment_number(value: str) -> ValidationResult:
        value = (value or "").strip()
        if not value:
            return ValidationResult(is_valid=False, reason="Enrollment number is required.")
        if not ENROLLMENT_PATTERN.match(value):
            return ValidationResult(
                is_valid=False,
                reason="Enrollment number must be 3-30 characters (letters, numbers, hyphens, slashes only).",
            )
        return ValidationResult(is_valid=True, cleaned_value=value.upper())

    @staticmethod
    def validate_roll_number(value: str, required: bool = False) -> ValidationResult:
        value = (value or "").strip()
        if not value:
            return ValidationResult(is_valid=not required, reason="" if not required else "Roll number is required.")
        if not ROLL_NUMBER_PATTERN.match(value):
            return ValidationResult(is_valid=False, reason="Roll number contains invalid characters.")
        return ValidationResult(is_valid=True, cleaned_value=value)

    @staticmethod
    def validate_name(value: str, field_label: str = "Name") -> ValidationResult:
        value = InputValidator.sanitize_text(value, max_length=100)
        if not value:
            return ValidationResult(is_valid=False, reason=f"{field_label} is required.")
        if not NAME_PATTERN.match(value):
            return ValidationResult(
                is_valid=False,
                reason=f"{field_label} should only contain letters, spaces, hyphens, and apostrophes.",
            )
        return ValidationResult(is_valid=True, cleaned_value=value)

    @staticmethod
    def validate_password_strength(value: str, min_length: int = 8) -> ValidationResult:
        if not value or len(value) < min_length:
            return ValidationResult(is_valid=False, reason=f"Password must be at least {min_length} characters.")
        if not re.search(r"[A-Z]", value):
            return ValidationResult(is_valid=False, reason="Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", value):
            return ValidationResult(is_valid=False, reason="Password must contain at least one lowercase letter.")
        if not re.search(r"[0-9]", value):
            return ValidationResult(is_valid=False, reason="Password must contain at least one number.")
        return ValidationResult(is_valid=True, cleaned_value=value)

    @staticmethod
    def validate_date_string(value: str, required: bool = False) -> ValidationResult:
        value = (value or "").strip()
        if not value:
            return ValidationResult(is_valid=not required, reason="" if not required else "Date is required.")
        try:
            from datetime import date
            date.fromisoformat(value)
        except ValueError:
            return ValidationResult(is_valid=False, reason="Enter a valid date in YYYY-MM-DD format.")
        return ValidationResult(is_valid=True, cleaned_value=value)

    # ------------------------------------------------------------
    # General-purpose sanitization
    # ------------------------------------------------------------
    @staticmethod
    def sanitize_text(value: str, max_length: int = 255, allow_newlines: bool = False) -> str:
        """
        Strips control characters and excess whitespace, and truncates
        to max_length. This is data hygiene, not SQL-injection defense
        (parameterized queries already handle that) - it exists to
        keep free-text fields (names, addresses, notes) clean for
        display and for report exports.
        """
        if not value:
            return ""

        value = CONTROL_CHAR_PATTERN.sub("", value)
        if not allow_newlines:
            value = value.replace("\n", " ").replace("\r", " ")
        value = re.sub(r"[ \t]+", " ", value).strip()

        return value[:max_length]

    @staticmethod
    def validate_length(value: str, field_label: str, min_length: int = 0, max_length: int = 255) -> ValidationResult:
        value = value or ""
        if len(value) < min_length:
            return ValidationResult(is_valid=False, reason=f"{field_label} must be at least {min_length} characters.")
        if len(value) > max_length:
            return ValidationResult(is_valid=False, reason=f"{field_label} must be at most {max_length} characters.")
        return ValidationResult(is_valid=True, cleaned_value=value)

    @staticmethod
    def validate_integer_range(value, field_label: str, min_value: int = None, max_value: int = None) -> ValidationResult:
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            return ValidationResult(is_valid=False, reason=f"{field_label} must be a whole number.")

        if min_value is not None and int_value < min_value:
            return ValidationResult(is_valid=False, reason=f"{field_label} must be at least {min_value}.")
        if max_value is not None and int_value > max_value:
            return ValidationResult(is_valid=False, reason=f"{field_label} must be at most {max_value}.")

        return ValidationResult(is_valid=True, cleaned_value=str(int_value))


# Singleton instance - import this everywhere instead of instantiating directly
input_validator = InputValidator()