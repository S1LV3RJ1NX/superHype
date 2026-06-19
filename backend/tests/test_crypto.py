from cryptography.fernet import Fernet

from app.config import settings
from app.core import crypto


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", key)
    crypto._fernet.cache_clear()

    plaintext = "linkedin-access-token-abc123"
    ciphertext = crypto.encrypt(plaintext)

    # Stored bytes must not be the plaintext.
    assert ciphertext != plaintext.encode()
    assert plaintext.encode() not in ciphertext
    assert crypto.decrypt(ciphertext) == plaintext

    crypto._fernet.cache_clear()
