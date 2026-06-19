"""Shared pagination primitives: PageParams dependency and the generic Page[T].

High-volume lists (campaigns, posts, audit_log) use keyset pagination on
(created_at, id): the cursor encodes the last row seen, so deep paging stays fast
and avoids the overlap/gap problems of offset paging.
"""

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Annotated, Generic, TypeVar

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


class PageParams:
    """Query params for a paginated list endpoint."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: Annotated[str | None, Query()] = None,
    ) -> None:
        self.limit = limit
        self.cursor = cursor

    @property
    def decoded_cursor(self) -> tuple[datetime, uuid.UUID] | None:
        if self.cursor is None:
            return None
        return decode_cursor(self.cursor)


class Page(BaseModel, Generic[T]):
    # arbitrary_types_allowed lets the repository layer return Page[Model] holding
    # ORM instances; the controller re-wraps into Page[SchemaOut] for the response.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T]
    next_cursor: str | None = None


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "id": str(row_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except (ValueError, KeyError, binascii.Error) as exc:
        raise HTTPException(
            status_code=400, detail="Invalid pagination cursor."
        ) from exc
