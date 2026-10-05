"""
core/attendance_engine/qr_backup.py

QR Code Backup Attendance: when facial recognition fails (poor
lighting, camera issue, unusual appearance, etc.), a student can
present a QR code instead. Codes are signed and time-limited so they
can't be screenshotted and reused indefinitely, or forged by editing
a student ID into arbitrary QR text.

Token format (before encoding into the QR image):
    "<student_id>.<expiry_unix_ts>.<hmac_signature>"

The HMAC signature is computed over "<student_id>.<expiry_unix_ts>"
using config.SECRET_KEY, so a token can't be forged or have its
expiry extended without knowing the app's secret key.

Usage:
    from core.attendance_engine.qr_backup import qr_backup

    # Generate (e.g. shown on the student's phone or printed ID card):
    token, image_bytes = qr_backup.generate_token(student_id, valid_minutes=5)

    # Scan a frame from the camera for a QR code and verify it:
    scan_result = qr_backup.scan_frame(frame_bgr)
    if scan_result and scan_result.is_valid:
        AttendanceModel.mark_attendance(
            student_id=scan_result.student_id, verification_method="QR", ...
        )
"""

import hashlib
import hmac
import io
import logging
import time
from dataclasses import dataclass

import cv2
import numpy as np

import config

logger = logging.getLogger("SmartAttendAI.core.attendance_engine.qr_backup")

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    logger.warning("qrcode package not installed - QR generation unavailable.")

DEFAULT_VALID_MINUTES = 5
TOKEN_SEPARATOR = "."


@dataclass
class QRScanResult:
    is_valid: bool
    student_id: int = None
    reason: str = ""   # "expired" | "invalid_signature" | "malformed" | "" (valid)
    raw_data: str = ""


class QRBackupAttendance:
    """
    Generates and verifies signed, time-limited QR attendance tokens.
    Uses HMAC-SHA256 with config.SECRET_KEY so tokens can't be forged
    without the app's secret, and an embedded expiry so a captured
    screenshot of the code stops working after a few minutes.
    """

    def __init__(self, secret_key: str = None):
        self.secret_key = (secret_key or config.SECRET_KEY).encode("utf-8")
        self._detector = cv2.QRCodeDetector()

    # ------------------------------------------------------------
    # Token generation
    # ------------------------------------------------------------
    def generate_token(self, student_id: int, valid_minutes: int = DEFAULT_VALID_MINUTES):
        """
        Returns (token_string, png_bytes). png_bytes is None if the
        `qrcode` package isn't installed - the token string is still
        useful on its own (e.g. displayed as plain text / a barcode
        via a different renderer).
        """
        expiry_ts = int(time.time()) + (valid_minutes * 60)
        payload = f"{student_id}{TOKEN_SEPARATOR}{expiry_ts}"
        signature = self._sign(payload)
        token = f"{payload}{TOKEN_SEPARATOR}{signature}"

        png_bytes = self._render_qr_image(token) if QRCODE_AVAILABLE else None
        return token, png_bytes

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    @staticmethod
    def _render_qr_image(token: str) -> bytes:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(token)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def save_token_image(self, student_id: int, filepath: str, valid_minutes: int = DEFAULT_VALID_MINUTES) -> str:
        """Convenience: generate and write the QR PNG directly to disk. Returns the token string."""
        token, png_bytes = self.generate_token(student_id, valid_minutes)
        if png_bytes is None:
            raise RuntimeError("qrcode package not installed - cannot render QR image.")
        with open(filepath, "wb") as f:
            f.write(png_bytes)
        return token

    # ------------------------------------------------------------
    # Token verification
    # ------------------------------------------------------------
    def verify_token(self, token: str) -> QRScanResult:
        if not token:
            return QRScanResult(is_valid=False, reason="malformed", raw_data=token or "")

        parts = token.strip().split(TOKEN_SEPARATOR)
        if len(parts) != 3:
            return QRScanResult(is_valid=False, reason="malformed", raw_data=token)

        student_id_str, expiry_str, signature = parts

        if not student_id_str.isdigit() or not expiry_str.isdigit():
            return QRScanResult(is_valid=False, reason="malformed", raw_data=token)

        payload = f"{student_id_str}{TOKEN_SEPARATOR}{expiry_str}"
        expected_signature = self._sign(payload)

        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("QR token signature mismatch - possible forged/tampered code.")
            return QRScanResult(is_valid=False, reason="invalid_signature", raw_data=token)

        expiry_ts = int(expiry_str)
        if time.time() > expiry_ts:
            return QRScanResult(is_valid=False, reason="expired", raw_data=token, student_id=int(student_id_str))

        return QRScanResult(is_valid=True, student_id=int(student_id_str), raw_data=token)

    # ------------------------------------------------------------
    # Camera-frame scanning
    # ------------------------------------------------------------
    def scan_frame(self, frame_bgr: np.ndarray) -> QRScanResult | None:
        """
        Looks for a QR code in a camera frame using OpenCV's built-in
        detector (no extra dependency needed beyond opencv-python).
        Returns None if no QR code was found in this frame at all;
        returns a QRScanResult (valid or invalid) if one was found
        and decoded.
        """
        try:
            data, points, _ = self._detector.detectAndDecode(frame_bgr)
        except Exception as exc:
            logger.debug("QR detection error on this frame: %s", exc)
            return None

        if not data:
            return None

        return self.verify_token(data)


# Singleton instance - import this everywhere instead of instantiating directly
qr_backup = QRBackupAttendance()