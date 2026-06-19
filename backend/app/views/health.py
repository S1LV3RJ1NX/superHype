"""Health check. Unprefixed GET /healthz for liveness probes and the acceptance test."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
