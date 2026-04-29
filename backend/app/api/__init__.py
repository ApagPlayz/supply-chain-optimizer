from fastapi import APIRouter

from app.api import auth, components, distributors, cart, optimize, live_prices, market_intelligence, ml, graph, feeds, benchmark, forecasts

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(components.router)
api_router.include_router(distributors.router)
api_router.include_router(cart.router)
api_router.include_router(optimize.router)
api_router.include_router(live_prices.router)
api_router.include_router(market_intelligence.router)
api_router.include_router(ml.router)
api_router.include_router(graph.router)
api_router.include_router(feeds.router)
api_router.include_router(benchmark.router)
api_router.include_router(forecasts.router)

__all__ = ["api_router"]
