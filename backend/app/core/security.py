"""JWT creation and decoding (PyJWT, HS256)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from pydantic import BaseModel

from app.config import settings


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
    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    try:
        data = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return TokenPayload(
            user_id=uuid.UUID(data["sub"]),
            email=data["email"],
            role=data["role"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired.") from exc
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=401, detail="Invalid authentication token."
        ) from exc
