"""Fernet encryption for tokens at rest.

LinkedIn access and refresh tokens are encrypted here before they ever reach the
database, and decrypted only when a provider call needs them. Plaintext tokens
never get persisted or logged.
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> bytes:
    """Encrypt a token string into ciphertext bytes for storage."""
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt stored ciphertext back into the original token string."""
    return _fernet().decrypt(ciphertext).decode()
