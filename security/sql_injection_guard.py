"""
security/sql_injection_guard.py

Defense-in-depth for SQL injection, on top of what already does the
real work: database/db_connector.py uses parameterized queries
(%s placeholders) everywhere, which is the actual primary defense -
user-supplied VALUES are never string-formatted into SQL text.

This module covers the one place parameterization can't help:
dynamic identifiers (table/column names) built from code, not user
values - e.g. StudentModel.update()'s dynamic SET clause, which
already whitelists column names against an `allowed` set inline. This
module centralizes that identifier-whitelisting pattern so every
model's dynamic-update method validates column names the same way,
and adds an optional heuristic scanner that flags suspicious patterns
in free-text input for security logging - a secondary alerting signal,
not a replacement for parameterized queries.

Usage:
    from security.sql_injection_guard import sql_guard

    # Identifier whitelisting (for dynamic SET clauses, ORDER BY columns, etc.)
    safe_columns = sql_guard.filter_allowed_columns(
        provided={"full_name": "Jay", "hacked; DROP TABLE students;--": "x"},
        allowed={"full_name", "email", "phone_number"},
    )
    # -> {"full_name": "Jay"}  (the malicious key is silently dropped and logged)

    # Heuristic scan (defense-in-depth logging only, never the sole gate)
    if sql_guard.looks_suspicious(user_search_text):
        SecurityLogModel.log(event_type="Spoof Attempt", description=...)
"""

import logging
import re

logger = logging.getLogger("SmartAttendAI.security.sql_injection_guard")

# Valid SQL identifier: letters, digits, underscore, must not start with a digit.
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Heuristic patterns that commonly appear in SQL injection payloads.
# This is a SECONDARY signal for logging/alerting only - it is not,
# and cannot be, a reliable primary defense (both false positives on
# legitimate text and false negatives on obfuscated payloads are
# expected). The real defense is parameterized queries in db_connector.py.
SUSPICIOUS_PATTERNS = [
    re.compile(r"(\b(UNION|SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|EXECUTE)\b.*\b(FROM|INTO|TABLE|WHERE)\b)", re.IGNORECASE),
    re.compile(r"(--|\#|/\*|\*/)"),                    # SQL comment markers
    re.compile(r"(\bOR\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+)", re.IGNORECASE),  # classic "OR 1=1"
    re.compile(r"(;\s*(DROP|DELETE|UPDATE|INSERT)\b)", re.IGNORECASE),         # stacked query attempt
    re.compile(r"(\bXP_CMDSHELL\b)", re.IGNORECASE),
]


class SQLInjectionGuard:
    """
    Identifier whitelisting for dynamic SQL construction, plus an
    optional heuristic scanner for defense-in-depth logging.
    """

    # ------------------------------------------------------------
    # Identifier whitelisting (the actually load-bearing part)
    # ------------------------------------------------------------
    @staticmethod
    def is_valid_identifier(name: str) -> bool:
        """True if `name` is syntactically a safe bare SQL identifier (no injection surface at all)."""
        return bool(name) and bool(IDENTIFIER_PATTERN.match(name))

    @staticmethod
    def filter_allowed_columns(provided: dict, allowed: set) -> dict:
        """
        Given a dict of {column_name: value} from a caller (e.g. a
        **fields update() call) and a whitelist of permitted column
        names, returns only the entries whose keys are both in the
        whitelist AND are themselves syntactically valid identifiers.
        Silently drops (and logs) anything else, rather than raising -
        callers already treat an empty filtered result as "nothing to
        update", matching the existing pattern in e.g. StudentModel.update().
        """
        filtered = {}
        for key, value in provided.items():
            if key in allowed and SQLInjectionGuard.is_valid_identifier(key):
                filtered[key] = value
            else:
                logger.warning("Rejected disallowed/invalid column in dynamic update: '%s'", key)
        return filtered

    @staticmethod
    def validate_order_by_column(column: str, allowed: set, default: str) -> str:
        """
        For dynamic ORDER BY clauses (another spot where a plain %s
        placeholder can't be used, since placeholders are for values,
        not identifiers). Returns `column` if it's in the whitelist,
        otherwise returns `default` and logs the rejection.
        """
        if column in allowed and SQLInjectionGuard.is_valid_identifier(column):
            return column
        logger.warning("Rejected disallowed ORDER BY column '%s' - using default '%s'.", column, default)
        return default

    # ------------------------------------------------------------
    # Heuristic scanner (secondary signal only - see module docstring)
    # ------------------------------------------------------------
    @staticmethod
    def looks_suspicious(text: str) -> bool:
        """
        Flags free-text input that resembles a SQL injection attempt,
        for SECURITY LOGGING purposes only. This must never be relied
        on as the actual defense - parameterized queries already make
        injection structurally impossible regardless of what this
        returns. Useful for e.g. flagging a search box query for
        review, not for deciding whether to run a query.
        """
        if not text:
            return False
        return any(pattern.search(text) for pattern in SUSPICIOUS_PATTERNS)

    @staticmethod
    def get_matched_patterns(text: str) -> list:
        """Returns which heuristic patterns matched, for a more detailed security log entry."""
        if not text:
            return []
        return [f"pattern_{i}" for i, pattern in enumerate(SUSPICIOUS_PATTERNS) if pattern.search(text)]


# Singleton instance - import this everywhere instead of instantiating directly
sql_guard = SQLInjectionGuard()