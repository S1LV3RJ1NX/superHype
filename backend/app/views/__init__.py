"""API router aggregation: includes every resource router under /v1."""

from fastapi import APIRouter

from app.views import campaigns

api_router = APIRouter()
api_router.include_router(campaigns.router)
