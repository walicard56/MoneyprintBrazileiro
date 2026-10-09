"""Encryption helpers for secrets at rest and local API authentication.

API keys for providers are stored encrypted in the database using Fernet
(AES-128-CBC + HMAC). The plaintext key never leaves the backend process and is
never serialized to the frontend or logs.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretCipher:
    """Symmetric encryption for provider credentials.

    The Fernet key comes from ``MP_SECRET_ENCRYPTION_KEY``. In development, if it
    is unset, a key is derived deterministically from the DB URL so the app can
    boot — but this is insecure and logged as a warning by the caller. Production
    must set a real, random key.
    """

    def __init__(self, key: str | None = None) -> None:
        raw = key if key is not None else settings.secret_encryption_key
        self._fernet = Fernet(self._coerce_key(raw))

    @staticmethod
    def _coerce_key(raw: str) -> bytes:
        if raw:
            # Accept either a valid Fernet key or any passphrase (hashed to 32 bytes).
            try:
                Fernet(raw.encode())
                return raw.encode()
            except (ValueError, TypeError):
                digest = hashlib.sha256(raw.encode()).digest()
                return base64.urlsafe_b64encode(digest)
        # Dev fallback: derive from the DB URL. Insecure; for local use only.
        digest = hashlib.sha256(settings.database_url.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt(self, plaintext: str) -> str:
        if plaintext == "":
            return ""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        if token == "":
            return ""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:  # pragma: no cover - surfaced to caller
            raise ValueError(
                "Could not decrypt a stored secret. The encryption key likely changed."
            ) from exc


_cipher: SecretCipher | None = None


def get_cipher() -> SecretCipher:
    global _cipher
    if _cipher is None:
        _cipher = SecretCipher()
    return _cipher


def mask_secret(plaintext: str) -> str:
    """Return a display-safe masked form of a secret, e.g. ``sk-…AB12``."""
    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return "••••"
    return f"{plaintext[:3]}…{plaintext[-4:]}"
