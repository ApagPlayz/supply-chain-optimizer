from fastapi import APIRouter

from app.api import auth

api_router = APIRouter()
api_router.include_router(auth.router)

__all__ = ["api_router"]
