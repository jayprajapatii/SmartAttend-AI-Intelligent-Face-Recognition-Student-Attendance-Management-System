"""
security/embedding_encryptor.py

Encrypts face embedding vectors before they're stored in the
face_embeddings table, per the "Encrypted Face Embeddings" security
requirement. Uses Fernet (AES-128-CBC + HMAC, from the `cryptography`
package already in requirements.txt) for authenticated symmetric
encryption - tampering with an encrypted embedding is detectable, not
just unreadable.

This is the module core/face_recognition/embedding_generator.py
already has a TODO pointing at: currently
FaceEmbeddingModel.serialize_vector() just JSON-encodes the raw
vector before storage. Wrap that with encrypt() before the DB write,
and decrypt() after reading it back in recognizer.py's reload().

Key management: the encryption key is derived from config.SECRET_KEY
via PBKDF2 (so the same app secret that signs QR tokens and sessions
also protects embeddings, without needing a second secret to manage).
For a production deployment where SECRET_KEY might rotate
independently of embeddings, generate and store a dedicated key
instead - see generate_standalone_key() below.

Usage:
    from security.embedding_encryptor import embedding_encryptor

    encrypted = embedding_encryptor.encrypt(json_string)
    # ... store `encrypted` in face_embeddings.embedding_vector ...

    decrypted_json = embedding_encryptor.decrypt(encrypted)
"""

import base64
import logging

import config

logger = logging.getLogger("SmartAttendAI.security.embedding_encryptor")

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    logger.warning("cryptography package not installed - embedding encryption unavailable.")

PBKDF2_ITERATIONS = 480_000  # OWASP-recommended minimum as of recent guidance, for SHA-256
# Fixed salt derived from the app context, not per-record: embeddings
# need to be decryptable by key alone (there's no per-row salt storage
# in the current schema), so the salt here is a fixed, non-secret
# domain-separation value - it does not need to be secret, only
# consistent, since PBKDF2's purpose here is stretching a short
# app secret into a proper key length, not per-user salting.
KEY_DERIVATION_SALT = b"smartattend-ai-embedding-encryption-v1"


class EmbeddingEncryptor:
    """Fernet-based authenticated encryption for face embedding vectors."""

    def __init__(self, secret: str = None):
        self._fernet = None
        if CRYPTOGRAPHY_AVAILABLE:
            try:
                key = self._derive_key(secret or config.SECRET_KEY)
                self._fernet = Fernet(key)
            except Exception as exc:
                logger.error("Failed to initialize embedding encryption: %s", exc)

    def is_available(self) -> bool:
        return self._fernet is not None

    @staticmethod
    def _derive_key(secret: str) -> bytes:
        """Stretches the app secret into a 32-byte urlsafe-base64 key, as Fernet requires."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=KEY_DERIVATION_SALT,
            iterations=PBKDF2_ITERATIONS,
        )
        derived = kdf.derive(secret.encode("utf-8"))
        return base64.urlsafe_b64encode(derived)

    # ------------------------------------------------------------
    # Encrypt / decrypt
    # ------------------------------------------------------------
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypts a plaintext string (e.g. the JSON-serialized
        embedding vector from FaceEmbeddingModel.serialize_vector()).
        Returns a urlsafe-base64 token string, safe to store in the
        existing LONGTEXT embedding_vector column as-is.
        """
        if not self.is_available():
            raise RuntimeError(
                "Embedding encryption is not available (cryptography package missing or key setup failed). "
                "Refusing to store embeddings in plaintext - install 'cryptography' to proceed."
            )
        if plaintext is None:
            raise ValueError("Cannot encrypt None.")

        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        """Decrypts a token produced by encrypt(). Raises ValueError if the token is invalid/tampered/expired."""
        if not self.is_available():
            raise RuntimeError("Embedding encryption is not available - cannot decrypt.")
        if not token:
            raise ValueError("Cannot decrypt an empty token.")

        try:
            plaintext = self._fernet.decrypt(token.encode("utf-8"))
            return plaintext.decode("utf-8")
        except InvalidToken as exc:
            logger.error("Embedding decryption failed - token invalid, tampered, or wrong key: %s", exc)
            raise ValueError("Could not decrypt embedding - data may be corrupted or the encryption key changed.") from exc

    def try_decrypt(self, token: str) -> str:
        """Non-raising variant - returns None instead of raising, for bulk-loading loops that should skip bad rows."""
        try:
            return self.decrypt(token)
        except (ValueError, RuntimeError) as exc:
            logger.warning("Skipping unreadable embedding: %s", exc)
            return None

    # ------------------------------------------------------------
    # Migration helper
    # ------------------------------------------------------------
    def is_encrypted(self, value: str) -> bool:
        """
        Best-effort check for whether a stored value is already an
        encrypted Fernet token vs. legacy plaintext JSON - useful for
        a one-time migration pass over existing face_embeddings rows
        that were stored before encryption was enabled.
        """
        if not value:
            return False
        try:
            base64.urlsafe_b64decode(value.encode("utf-8") + b"=" * (-len(value) % 4))
            return not value.strip().startswith(("[", "{"))  # JSON arrays/objects are unmistakably plaintext
        except Exception:
            return False

    # ------------------------------------------------------------
    # Standalone key generation (for production key rotation setups)
    # ------------------------------------------------------------
    @staticmethod
    def generate_standalone_key() -> str:
        """
        Generates a fresh, random Fernet key independent of
        config.SECRET_KEY. Use this if you want embedding encryption
        to have its own dedicated key (stored separately, e.g. in a
        secrets manager) rather than being derived from the app's
        general-purpose secret.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise RuntimeError("cryptography package not installed.")
        return Fernet.generate_key().decode("utf-8")


# Singleton instance - import this everywhere instead of instantiating directly
embedding_encryptor = EmbeddingEncryptor()