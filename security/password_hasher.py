"""
security/password_hasher.py

Centralized password hashing via bcrypt. AdminModel currently has its
own inline hash_password()/verify_password() static methods (in
database/models/admin_model.py) - this module is the single source of
truth those should delegate to, so hashing logic (cost factor, etc.)
lives in exactly one place instead of being duplicated if another
user-type (e.g. a future parent portal login) needs password auth too.

Usage:
    from security.password_hasher import password_hasher

    hashed = password_hasher.hash("my-plain-password")
    is_valid = password_hasher.verify("my-plain-password", hashed)

    if password_hasher.needs_rehash(hashed):
        # cost factor was increased since this hash was created - rehash on next successful login
        new_hash = password_hasher.hash(plain_password)
"""

import logging

import bcrypt

logger = logging.getLogger("SmartAttendAI.security.password_hasher")

DEFAULT_COST_FACTOR = 12  # bcrypt work factor - higher is slower but more resistant to brute force


class PasswordHasher:
    """Thin, centralized wrapper around bcrypt for password hashing and verification."""

    def __init__(self, cost_factor: int = DEFAULT_COST_FACTOR):
        self.cost_factor = cost_factor

    def hash(self, plain_password: str) -> str:
        if not plain_password:
            raise ValueError("Cannot hash an empty password.")

        salt = bcrypt.gensalt(rounds=self.cost_factor)
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    def verify(self, plain_password: str, password_hash: str) -> bool:
        if not plain_password or not password_hash:
            return False

        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            # Malformed hash (e.g. legacy plaintext row, corrupted data) - treat as failed verification, not a crash
            logger.error("Password verification failed due to malformed hash: %s", exc)
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """
        True if the given hash was created with a lower cost factor
        than the currently configured one - useful for opportunistic
        rehashing on successful login after raising DEFAULT_COST_FACTOR.
        """
        try:
            # bcrypt hash format: $2b$<cost>$<salt+hash>
            parts = password_hash.split("$")
            existing_cost = int(parts[2])
            return existing_cost < self.cost_factor
        except (IndexError, ValueError):
            return True  # unparseable hash - safest to rehash


# Singleton instance - import this everywhere instead of instantiating directly
password_hasher = PasswordHasher()