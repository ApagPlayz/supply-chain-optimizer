from fastapi import APIRouter

from app.api import auth, hubs, materials, cart, optimize

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(hubs.router)
api_router.include_router(materials.router)
api_router.include_router(cart.router)
api_router.include_router(optimize.router)

__all__ = ["api_router"]
