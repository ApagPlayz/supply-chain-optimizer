from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.database import Base, engine
import app.models  # noqa: F401 — ensure all ORM models are registered before create_all

# Create tables
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app):
    # Load ML models from disk if previously trained
    try:
        from app.ml import MLState, set_ml_state
        from app.ml import model_store
        if model_store.models_exist():
            import logging
            logger = logging.getLogger(__name__)
            regime_pipe = model_store.load("regime")
            regime_features = model_store.load("regime_features")
            lt_models = model_store.load("lead_time")
            feature_cols = model_store.load("feature_cols")
            metrics = model_store.load("metrics") or {}
            best = metrics.get("best_lead_time_model", "gradient_boosting")
            stress = metrics.get("current_stress_prob", 0.0)
            set_ml_state(MLState(
                regime_model=regime_pipe,
                regime_features=regime_features,
                lead_time_models=lt_models,
                best_lead_time_model=best,
                current_stress_prob=stress,
                feature_columns=feature_cols or [],
            ))
            logger.info("ML models loaded from disk (stress_prob=%.3f, best_lt=%s)",
                        stress, best)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("ML model load skipped: %s", exc)

    # Build graph state from SQLite
    try:
        from app.graph.builder import build_graph_state
        from app.graph import set_graph_state
        from app.core.database import SessionLocal
        _db = SessionLocal()
        try:
            _gs = build_graph_state(_db)
            set_graph_state(_gs)
        finally:
            _db.close()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Graph build skipped: %s", exc)

    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Parse CORS origins from settings (D-05)
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if settings.DEBUG:
    # D-06: Always include localhost origins in dev mode
    dev_origins = {"http://localhost:5173", "http://localhost:3000"}
    origins = list(set(origins) | dev_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
