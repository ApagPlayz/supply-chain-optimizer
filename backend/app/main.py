from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.database import Base, engine
import app.models  # noqa: F401 — ensure all ORM models are registered before create_all

# Create tables
Base.metadata.create_all(bind=engine)


def compute_fiedler_curve(gs, db, top_k: int = 5):
    """
    Pre-compute sequential-removal λ₂ curve for the top-k highest-betweenness distributors.

    Uses method="lanczos" on the UNWEIGHTED laplacian of the largest connected component.
    Guards against Pitfall #1 (tracemin_pcg hang on stock-weighted bipartite graphs —
    returned λ₂=0 in 146s on 847-node LCC in Phase 2).

    Returns a list of exactly `top_k + 1` dicts:
        [
          {"step": 0, "removed": None, "removed_name": None, "lambda2": base, "delta_pct": 0.0},
          {"step": 1, "removed": did, "removed_name": name, "lambda2": ..., "delta_pct": ...},
          ...
        ]

    Each step removes the distributor node with the next-highest betweenness and
    recomputes λ₂ on the remaining largest connected component.
    """
    import logging
    import time

    import networkx as nx

    from app.models.distributor import Distributor

    logger = logging.getLogger(__name__)
    dist_name_by_id = {d.id: d.name for d in db.query(Distributor).all()}

    Gu = gs.graph.to_undirected()
    curve = []

    def _lambda2(G):
        if G.number_of_nodes() <= 2:
            return 0.0
        ccs = list(nx.connected_components(G))
        if not ccs:
            return 0.0
        cc = max(ccs, key=len)
        Gsub = G.subgraph(cc).copy()
        # Strip edge weights — Pitfall #1 mitigation (lanczos on unweighted laplacian)
        for u, v in Gsub.edges():
            Gsub[u][v]["weight"] = 1.0
        try:
            t0 = time.time()
            lam = nx.algebraic_connectivity(Gsub, method="lanczos", normalized=False)
            elapsed = time.time() - t0
            if elapsed > 5.0:
                logger.warning(
                    "Fiedler lanczos slow (%.1fs) on %d nodes",
                    elapsed, Gsub.number_of_nodes(),
                )
            return float(lam) if lam > 0 else 0.0
        except Exception as exc:
            logger.warning("Fiedler lanczos failed: %s — returning 0.0", exc)
            return 0.0

    base_lambda = _lambda2(Gu)
    curve.append({
        "step": 0, "removed": None, "removed_name": None,
        "lambda2": base_lambda, "delta_pct": 0.0,
    })

    top_dists = sorted(gs.betweenness.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    Gtmp = Gu.copy()
    for step, (did, _btwn) in enumerate(top_dists, start=1):
        node = f"d_{did}"
        if Gtmp.has_node(node):
            Gtmp.remove_node(node)
        lam = _lambda2(Gtmp)
        delta_pct = (
            (lam - base_lambda) / max(base_lambda, 1e-9) * 100
            if base_lambda > 0 else 0.0
        )
        curve.append({
            "step": step,
            "removed": int(did),
            "removed_name": dist_name_by_id.get(did, f"distributor-{did}"),
            "lambda2": lam,
            "delta_pct": round(delta_pct, 1),
        })

    # Pad to exactly top_k+1 entries even if fewer distributors were available
    while len(curve) < top_k + 1:
        curve.append({
            "step": len(curve), "removed": None, "removed_name": None,
            "lambda2": 0.0, "delta_pct": -100.0,
        })
    return curve


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
            # Phase 4 (BENCH-05): pre-compute sequential-removal λ₂ curve.
            # Inner try/except so a Fiedler failure doesn't kill the whole graph build.
            try:
                _gs.fiedler_curve = compute_fiedler_curve(_gs, _db, top_k=5)
                import logging
                logging.getLogger(__name__).info(
                    "Fiedler curve: %d steps pre-computed", len(_gs.fiedler_curve)
                )
            except Exception as _fiedler_exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Fiedler curve pre-compute skipped: %s", _fiedler_exc
                )
                _gs.fiedler_curve = []
        finally:
            _db.close()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Graph build skipped: %s", exc)

    # ── Live data feeds ────────────────────────────────────────────────────────
    _scheduler = None
    try:
        from app.feeds.scheduler import build_scheduler
        from app.feeds import set_live_data_cache, LiveDataCache
        _ldc = LiveDataCache()
        set_live_data_cache(_ldc)
        _scheduler = build_scheduler(_ldc)
        _scheduler.start()
        import logging
        logging.getLogger(__name__).info("Feed scheduler started (15-min interval)")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Feed scheduler start skipped: %s", exc)

    yield

    # Cleanup: shut down scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass


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
