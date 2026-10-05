"""
database/models/admin_model.py

CRUD + authentication helpers for the `admin_users` table.
Passwords are hashed with bcrypt - never stored or compared in plain text.
"""

import logging
import random
from datetime import datetime, timedelta


import bcrypt

from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.admin")


class AdminModel:

    # ------------------------------------------------------------
    # Password hashing helpers
    # ------------------------------------------------------------
    @staticmethod
    def hash_password(plain_password: str) -> str:
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            logger.error("Password verification failed: %s", exc)
            return False

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(username: str, plain_password: str, email: str, phone: str = None, role: str = "admin") -> int:
        password_hash = AdminModel.hash_password(plain_password)
        query = """
            INSERT INTO admin_users (username, password_hash, email, phone, role)
            VALUES (%s, %s, %s, %s, %s)
        """
        admin_id = db.execute(query, (username, password_hash, email, phone, role))
        logger.info("Admin user created: %s (id=%s, role=%s)", username, admin_id, role)
        return admin_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(admin_id: int) -> dict | None:
        return db.fetch_one("SELECT * FROM admin_users WHERE admin_id = %s", (admin_id,))

    @staticmethod
    def get_by_username(username: str) -> dict | None:
        return db.fetch_one("SELECT * FROM admin_users WHERE username = %s", (username,))

    @staticmethod
    def get_by_email(email: str) -> dict | None:
        return db.fetch_one("SELECT * FROM admin_users WHERE email = %s", (email,))

    @staticmethod
    def get_all() -> list:
        return db.fetch_all(
            "SELECT admin_id, username, email, phone, role, is_active, last_login, created_at "
            "FROM admin_users ORDER BY username ASC"
        )

    # ------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------
    @staticmethod
    def authenticate(username: str, plain_password: str) -> dict | None:
        """Returns the admin record (without password_hash) on success, else None."""
        user = AdminModel.get_by_username(username)
        if not user or not user.get("is_active"):
            logger.warning("Login failed - unknown or inactive user: %s", username)
            return None

        if not AdminModel.verify_password(plain_password, user["password_hash"]):
            logger.warning("Login failed - wrong password: %s", username)
            return None

        AdminModel.update_last_login(user["admin_id"])
        user.pop("password_hash", None)
        logger.info("Login success: %s", username)
        return user

    @staticmethod
    def update_last_login(admin_id: int) -> int:
        return db.execute(
            "UPDATE admin_users SET last_login = NOW() WHERE admin_id = %s", (admin_id,)
        )

    @staticmethod
    def change_password(admin_id: int, new_plain_password: str) -> int:
        password_hash = AdminModel.hash_password(new_plain_password)
        rows_affected = db.execute(
            "UPDATE admin_users SET password_hash = %s WHERE admin_id = %s",
            (password_hash, admin_id),
        )
        logger.info("Password changed for admin_id=%s", admin_id)
        return rows_affected

    # ------------------------------------------------------------
    # OTP (forgot password / MFA)
    # ------------------------------------------------------------
    @staticmethod
    def generate_otp(username: str, expiry_minutes: int = 10) -> str | None:
        user = AdminModel.get_by_username(username)
        if not user:
            return None

        otp_code = f"{random.randint(0, 999999):06d}"
        expiry = datetime.now() + timedelta(minutes=expiry_minutes)
        db.execute(
            "UPDATE admin_users SET otp_code = %s, otp_expiry = %s WHERE admin_id = %s",
            (otp_code, expiry, user["admin_id"]),
        )
        logger.info("OTP generated for %s (expires in %s min)", username, expiry_minutes)
        return otp_code

    @staticmethod
    def verify_otp(username: str, otp_code: str) -> bool:
        user = AdminModel.get_by_username(username)
        if not user or not user.get("otp_code") or not user.get("otp_expiry"):
            return False

        if user["otp_code"] != otp_code:
            logger.warning("OTP mismatch for %s", username)
            return False

        if datetime.now() > user["otp_expiry"]:
            logger.warning("OTP expired for %s", username)
            return False

        # OTP is single-use - clear it after successful verification
        db.execute(
            "UPDATE admin_users SET otp_code = NULL, otp_expiry = NULL WHERE admin_id = %s",
            (user["admin_id"],),
        )
        return True

    # ------------------------------------------------------------
    # Update / Delete
    # ------------------------------------------------------------
    @staticmethod
    def update(admin_id: int, **fields) -> int:
        if not fields:
            return 0
        allowed = {"username", "email", "phone", "role", "is_active"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return 0

        set_clause = ", ".join(f"{col} = %s" for col in updates)
        params = tuple(updates.values()) + (admin_id,)
        query = f"UPDATE admin_users SET {set_clause} WHERE admin_id = %s"
        rows_affected = db.execute(query, params)
        logger.info("Admin %s updated: %s", admin_id, list(updates.keys()))
        return rows_affected

    @staticmethod
    def deactivate(admin_id: int) -> int:
        return db.execute(
            "UPDATE admin_users SET is_active = FALSE WHERE admin_id = %s", (admin_id,)
        )

    @staticmethod
    def delete(admin_id: int) -> int:
        rows_affected = db.execute("DELETE FROM admin_users WHERE admin_id = %s", (admin_id,))
        logger.info("Admin %s deleted.", admin_id)
        return rows_affected