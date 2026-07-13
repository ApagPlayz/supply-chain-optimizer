from contextlib import asynccontextmanager
import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401 — ensure all ORM models are registered before create_all

# Configure OpenTelemetry SDK.
# Tracing is opt-in: Jaeger is optional for the local demo, and exporting to a
# Jaeger agent that isn't running spams stderr with "OSError: Message too long"
# (oversized UDP batches with no listener). Enable explicitly with OTEL_ENABLED=true.
logger = logging.getLogger(__name__)
_OTEL_ENABLED = os.getenv("OTEL_ENABLED", "").lower() in ("1", "true", "yes")
if _OTEL_ENABLED:
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        jaeger_exporter = JaegerExporter(
            agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
            agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
            udp_split_oversized_batches=True,  # avoid OSError [Errno 40] on large batches
        )
        _tracer_provider = TracerProvider()
        _tracer_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
        trace.set_tracer_provider(_tracer_provider)
        logger.info("OpenTelemetry configured with Jaeger exporter (localhost:6831)")
    except ImportError:
        logger.warning("OpenTelemetry not available — tracing disabled")
    except Exception as e:
        logger.warning(f"OpenTelemetry initialization failed: {e}")
else:
    logger.info("OpenTelemetry tracing disabled (set OTEL_ENABLED=true to enable)")

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
    # Resolve the serving model: MLflow `champion` alias if a registry is reachable,
    # else the committed on-disk joblib (the real path on the Render free tier).
    # See app/ml/serving.py; provenance is exposed at GET /api/v1/ml/model-info.
    try:
        from app.ml import set_ml_state
        from app.ml.serving import load_ml_state

        _state = load_ml_state()
        if _state is not None:
            set_ml_state(_state)
            _prov = _state.provenance or {}
            logger.info(
                "ML models loaded (source=%s, model=%s, version=%s, stress_prob=%.3f)",
                _prov.get("model_source"), _prov.get("model_name"),
                _prov.get("model_version"), _state.current_stress_prob,
            )
    except Exception as exc:
        logger.warning("ML model load skipped: %s", exc)

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
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                    _future = _pool.submit(compute_fiedler_curve, _gs, _db, 5)
                    try:
                        _gs.fiedler_curve = _future.result(timeout=10)
                        import logging
                        logging.getLogger(__name__).info(
                            "Fiedler curve: %d steps pre-computed", len(_gs.fiedler_curve)
                        )
                    except concurrent.futures.TimeoutError:
                        import logging
                        logging.getLogger(__name__).warning(
                            "Fiedler curve pre-compute timed out (>10s) — skipped"
                        )
                        _gs.fiedler_curve = []
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

    # ── Background cache cleanup job (Phase 6 - performance) ──────────────────
    _cleanup_task = None
    try:
        import logging as _log_module
        _logger = _log_module.getLogger(__name__)

        async def cleanup_loop():
            """Run cache cleanup every 10 minutes."""
            from app.cache import CacheManager

            while True:
                try:
                    await asyncio.sleep(600)  # 10 minutes
                    db = SessionLocal()
                    try:
                        deleted = CacheManager.cleanup_expired(db)
                        if deleted > 0:
                            _logger.info(f"Cache cleanup: deleted {deleted} expired entries")
                    except Exception as e:
                        _logger.error(f"Cache cleanup failed: {e}")
                    finally:
                        db.close()
                except asyncio.CancelledError:
                    _logger.info("Cache cleanup task cancelled")
                    break
                except Exception as e:
                    _logger.error(f"Cache cleanup loop error: {e}")

        _cleanup_task = asyncio.create_task(cleanup_loop())
        _logger.info("Background cache cleanup scheduled (10-min interval)")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Cache cleanup job setup skipped: %s", exc)

    yield

    # Cleanup: shut down scheduler and cache cleanup task
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass

    if _cleanup_task is not None:
        try:
            _cleanup_task.cancel()
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


@app.get("/version")
def version_info():
    """Deployed build info — used by ./launch and the UI build badge."""
    commit = os.getenv("RENDER_GIT_COMMIT", "")
    if not commit:
        try:
            import subprocess

            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            commit = "unknown"
    return {
        "commit": commit,
        "service": os.getenv("RENDER_SERVICE_NAME", "local"),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
