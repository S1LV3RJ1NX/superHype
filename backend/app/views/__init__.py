"""API router aggregation: includes every resource router under /v1."""

from fastapi import APIRouter

from app.views import auth, campaigns, connections, skills, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(campaigns.router)
api_router.include_router(connections.router)
api_router.include_router(skills.router)
api_router.include_router(users.router)
