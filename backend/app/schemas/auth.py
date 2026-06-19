"""Auth request/response schemas."""

from pydantic import BaseModel


class GoogleCallbackBody(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
