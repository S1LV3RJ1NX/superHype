"""JWT creation and decoding.

Phase 0 stub: the signatures and the TokenPayload shape are fixed here so the rest
of the app can import them, but the real implementation lands in Phase 1 (auth).
"""

import uuid
from datetime import timedelta

from pydantic import BaseModel


class TokenPayload(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str


async def create_access_token(
    *,
    user_id: uuid.UUID,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Mint a signed JWT carrying user_id, email, and role. Implemented in Phase 1."""
    raise NotImplementedError("JWT issuance lands in Phase 1 (auth).")


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a bearer token, raising 401 on failure. Implemented in Phase 1."""
    raise NotImplementedError("JWT decoding lands in Phase 1 (auth).")
