from fastapi import APIRouter

from app.api import auth, components, distributors, cart, optimize, live_prices, market_intelligence, ml

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(components.router)
api_router.include_router(distributors.router)
api_router.include_router(cart.router)
api_router.include_router(optimize.router)
api_router.include_router(live_prices.router)
api_router.include_router(market_intelligence.router)
api_router.include_router(ml.router)

__all__ = ["api_router"]
