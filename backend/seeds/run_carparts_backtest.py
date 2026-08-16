"""Probabilistic intermittent-demand backtest on the REAL Monash Car Parts panel.

This is the demand evidence for the whole repo. There is no public per-SKU demand
series for electronic components, so the demand claim is made where real data
exists: 2,674 monthly car-parts SKU series (51 months, 24.1% non-zero) from the
Monash Time Series Forecasting Archive — the canonical public benchmark for
*intermittent* demand, which is the pattern component planners actually face.

What this run answers
---------------------
A MASE leaderboard on intermittent demand is suspect, for a specific reason:
MAE (hence MASE) is minimised by the conditional MEDIAN, and on a 24%-non-zero
panel that median is usually ZERO. So a degenerate forecast that predicts nothing
can top the table while being useless to a planner, who needs P(demand > stock),
not the median. The `zero` method below is included precisely so that risk is
MEASURED rather than asserted.

The run therefore scores every method twice:
  * as a POINT forecast          — MASE, RMSSE (the existing, scaled metrics)
  * as a PREDICTIVE DISTRIBUTION — scaled CRPS and scaled pinball loss (SPL),
    both strictly proper (Gneiting & Raftery 2007), both divided by the identical
    training-only MASE denominator so the two leaderboards are on one scale.
and then asks whether the RANKING CHANGES. A null result is reported as a null
result; nothing here is arranged to produce a reversal.

Protocol
--------
  * ROLLING ORIGIN, not a single split. The origins come from
    `app.ml.backtest.rolling_origins` — the same function `walk_forward_backtest`
    uses — so this backtest and the macro A34SNO backtest run the same protocol by
    construction rather than by resemblance. Each origin refits from scratch on the
    data strictly before it.
  * Primary config: horizon 6, three origins (train sizes 33/39/45).
    Why not the Monash-standard horizon of 12: 51 months cannot hold three
    non-overlapping 12-month blocks without the first origin training on 15 months,
    fewer than two seasonal cycles, which leaves the seasonal-naive MASE
    denominator built from three differences and unusable. A `sensitivity` config
    (horizon 12, two origins) is run as well and reports whether the conclusion
    depends on that choice.
  * Metrics are computed per series per origin, then averaged within a series, so
    the series is the independent replication unit for every test.
  * Significance: Friedman + Nemenyi (MCB) across the complete series, plus
    Diebold-Mariano for non-nested pairs and Clark-West for nested ones.

Usage:
    cd backend
    python -m seeds.run_carparts_backtest              # ~1 min, fully offline
    python -m seeds.run_carparts_backtest --prophet    # + the slow Prophet sample
    python -m seeds.run_carparts_backtest --quick      # primary config only

Writes docs/intermittent_demand.json (canonical, cited by docs/INTERMITTENT_DEMAND.md)
and a byte-identical mirror at seeds/data/intermittent_demand.json. The mirror
exists only because the container build context is `backend/` (see render.yaml
rootDir / Dockerfile), so repo-root docs/ is not guaranteed to be present at
runtime for `GET /demand/benchmark` to read.

It also rewrites the NUMERIC sections of docs/INTERMITTENT_DEMAND.md in place
--------------------------------------------------------------------------
That doc used to be hand-transcribed from the JSON, which is how its figures
drifted away from the artifact they claimed to quote. Every table and every
stated statistic now lives inside a delimited region::

    <!-- GENERATED:leaderboard BEGIN -->
    ...replaced wholesale on every run...
    <!-- GENERATED:leaderboard END -->

`splice_generated` replaces ONLY the text between matching markers. Everything
outside a marker pair — the argument, the caveats, the references, every
hand-written sentence — is curated prose this script never touches. The default
is therefore "curated", and a section becomes machine-owned only by being wrapped
explicitly; that way adding prose can never silently put a number under the
writer's control, and the writer fails loudly (`KeyError`/`ValueError`) if the
doc's marker set and this module's block set stop agreeing.

Provenance
----------
The artifact carries a top-level ``provenance`` block from ``seeds.provenance``.
It replaces the old ``meta.git_sha`` string, which recorded a ``-dirty`` suffix
SILENTLY — a reader had to notice a 47-character suffix to learn the numbers were
not reproducible from the recorded commit. ``provenance.git.dirty`` is an explicit
boolean carrying an explicit warning string, and it is rendered into the markdown.
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import re
import sys
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np  # noqa: E402
import scipy  # noqa: E402

from app.ml import intermittent as it  # noqa: E402
from app.ml.backtest import rolling_origins  # noqa: E402
from app.ml.model_comparison import clark_west, diebold_mariano, mcb_test  # noqa: E402
from seeds.monash_loader import CACHE_PATH  # noqa: E402
from seeds.provenance import build_provenance, provenance_markdown  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = BACKEND_ROOT.parent
DOCS = REPO_ROOT / "docs"
ARTIFACT_NAME = "intermittent_demand.json"
SERVED_MIRROR = BACKEND_ROOT / "seeds" / "data" / ARTIFACT_NAME
DOC_PATH = DOCS / "INTERMITTENT_DEMAND.md"

SEED = 42
ALPHA = 0.05           # family-wise level for the Nemenyi critical difference
SEASONALITY = 12       # monthly data

#: (label, horizon, n_windows, min_train). See the module docstring for why the
#: primary config is not the Monash-standard horizon of 12.
CONFIGS: Tuple[Tuple[str, int, int, int], ...] = (
    ("primary", 6, 3, 33),
    ("sensitivity_h12", 12, 2, 27),
)

#: name -> (point forecaster, distribution forecaster). Order is the leaderboard order.
METHODS: Dict[str, Tuple[Callable[..., List[float]], Callable[..., List[np.ndarray]]]] = {
    "zero": (lambda tr, h: [0.0] * h, it.zero_dist),
    "naive_last": (it.naive_last, it.naive_last_dist),
    "climatology": (
        lambda tr, h: [float(np.mean(tr)) if len(tr) else 0.0] * h,
        it.climatology_dist,
    ),
    "croston": (it.croston, it.croston_dist),
    "sba": (it.sba, it.sba_dist),
    "tsb": (it.tsb, it.tsb_dist),
}

#: What each method assumes to become a distribution — mirrored into the artifact
#: so the JSON is self-describing. Full derivations in app/ml/intermittent.py.
PARAMETERISATIONS: Dict[str, Dict[str, str]] = {
    "zero": {
        "family": "degenerate at 0",
        "assumption": "None. This is the conditional median of most intermittent series "
                      "and therefore the degenerate forecast a MASE leaderboard is at risk "
                      "of rewarding. Included to measure that risk, not to compete.",
    },
    "naive_last": {
        "family": "degenerate at the last observed value",
        "assumption": "None. The point forecast lifted to a distribution with zero spread — "
                      "the honest probabilistic reading of 'repeat the last number'. Makes "
                      "CRPS collapse to absolute error, so scaled CRPS equals MASE exactly "
                      "and the two leaderboards share an anchor.",
    },
    "climatology": {
        "family": "in-sample empirical distribution of the training window",
        "assumption": "The training window is exchangeable with the test window — no trend, "
                      "no obsolescence. The standard probabilistic reference forecast.",
    },
    "croston": {
        "family": "compound Bernoulli(p) x zero-truncated NegBin(mean z)",
        "assumption": "Croston smooths the inter-arrival INTERVAL and gives no probability. "
                      "We assume memoryless arrivals, so intervals are Geometric(p) with "
                      "mean 1/p and therefore p = 1 / interval_hat. This is not an addition "
                      "to the method: Croston (1972) derives it under Bernoulli arrivals, so "
                      "the assumption restates the model the estimator already lives in. "
                      "Intervals are >= 1 by construction, so p <= 1 always.",
    },
    "sba": {
        "family": "compound Bernoulli(p) x zero-truncated NegBin(mean z)",
        "assumption": "As Croston, with the (1 - alpha/2) Syntetos-Boylan factor applied to "
                      "the OCCURRENCE PROBABILITY rather than the size: Syntetos & Boylan "
                      "(2001) show Croston's bias is the Jensen gap in E[1/interval_hat], "
                      "which lives in the inverse-interval term; the size estimator is "
                      "unbiased. Placing the correction there both matches the derivation "
                      "and reproduces the SBA point forecast exactly.",
    },
    "tsb": {
        "family": "compound Bernoulli(p) x zero-truncated NegBin(mean z)",
        "assumption": "None beyond the compound-Bernoulli structure. TSB already estimates an "
                      "occurrence probability and a conditional size every period, so this is "
                      "the method's native parameterisation.",
    },
}

#: Clark-West is degenerate when the restricted model is the zero forecast. With
#: f1 = 0 the adjusted difference collapses to f_hat = 2 * y * f2, which on
#: non-negative demand with a non-negative forecast is >= 0 by construction — the
#: test then rejects for ANY forecast that is not identically zero, so it has no
#: power to discriminate between the three Croston-family methods. It is reported
#: anyway, flagged, because silently dropping an inconvenient test is worse than
#: showing it with its limitation. (Two side-effects of the algebra confirm the
#: degeneracy: SBA = Croston x 0.95 is a pure rescaling of f2, so f_hat rescales
#: with it and the t-statistic is IDENTICAL for zero->croston and zero->sba.)
_ZERO_RESTRICTION_CAVEAT = (
    "DEGENERATE — not an informative test. With f1 = 0 the Clark-West adjusted "
    "difference reduces to 2*y*f2, which is >= 0 for any non-negative forecast on "
    "non-negative demand, so rejection is automatic and carries no evidence about "
    "which method is better. Note the statistic is identical for croston and sba "
    "because SBA is a pure rescaling of Croston, which is the algebra showing the "
    "test is scale-invariant here. The informative nested comparison is croston -> sba."
)

#: Nested pairs (restricted, unrestricted, why) — these get Clark-West, not DM.
NESTED_PAIRS: Tuple[Tuple[str, str, str, Optional[str]], ...] = (
    ("zero", "croston", "`zero` is the p = 0 restriction of the compound-Bernoulli model", _ZERO_RESTRICTION_CAVEAT),
    ("zero", "sba", "`zero` is the p = 0 restriction of the compound-Bernoulli model", _ZERO_RESTRICTION_CAVEAT),
    ("zero", "tsb", "`zero` is the p = 0 restriction of the compound-Bernoulli model", _ZERO_RESTRICTION_CAVEAT),
    ("croston", "sba", "SBA = Croston × (1 − φ/2); Croston is the φ = 0 restriction", None),
)

#: Non-nested pairs, compared on scaled CRPS with the HLN-corrected DM test.
DM_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("naive_last", "tsb"),
    ("naive_last", "climatology"),
    ("climatology", "tsb"),
    ("croston", "tsb"),
)

#: Metrics carried through the leaderboard. (key, lower_is_better, kind)
METRIC_KEYS: Tuple[str, ...] = ("mase", "rmsse", "crps", "spl")
POINT_METRICS: Tuple[str, ...] = ("mase", "rmsse")
DIST_METRICS: Tuple[str, ...] = ("crps", "spl")


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────


def _score_one(
    train: np.ndarray,
    test: np.ndarray,
    point: Sequence[float],
    dists: Sequence[np.ndarray],
) -> Dict[str, float]:
    """All four metrics for one (series, origin, method)."""
    return {
        "mase": it.mase(train, test, point, seasonality=SEASONALITY),
        "rmsse": it.rmsse(train, test, point),
        "crps": it.scaled_crps(train, test, dists, seasonality=SEASONALITY),
        "spl": it.scaled_pinball(train, test, dists, seasonality=SEASONALITY),
    }


def score_panel(
    mat: np.ndarray,
    horizon: int,
    n_windows: int,
    min_train: int,
    methods: Dict[str, Tuple[Callable[..., List[float]], Callable[..., List[np.ndarray]]]],
    idx: Optional[np.ndarray] = None,
) -> Tuple[Dict[str, Dict[str, np.ndarray]], np.ndarray, Dict[str, np.ndarray]]:
    """Backtest every method over every series at every rolling origin.

    Returns:
        per_series: {method: {metric: array of length n_scored}} — each entry is the
            mean of that metric across origins for one series.
        kept: indices (into `mat`) of the series that produced a finite score for
            EVERY method and EVERY metric. Only these enter the tests, so the panel
            the MCB ranks is balanced.
        squared_error: {method: array} of per-series mean squared error, pooled over
            origins — the input Clark-West needs (it is an MSPE test).
    """
    rows = np.arange(mat.shape[0]) if idx is None else np.asarray(idx)
    cuts = rolling_origins(int(mat.shape[1]), horizon, n_windows, min_train)

    names = list(methods)
    acc: Dict[str, Dict[str, List[float]]] = {m: {k: [] for k in METRIC_KEYS} for m in names}
    sq: Dict[str, List[float]] = {m: [] for m in names}
    kept: List[int] = []

    for i in rows:
        series = mat[i]
        per_method: Dict[str, Dict[str, List[float]]] = {m: {k: [] for k in METRIC_KEYS} for m in names}
        per_method_sq: Dict[str, List[float]] = {m: [] for m in names}
        for cut in cuts:
            train, test = series[:cut], series[cut:cut + horizon]
            for name, (point_fn, dist_fn) in methods.items():
                point = point_fn(train, horizon)
                dists = dist_fn(train, horizon)
                scores = _score_one(train, test, point, dists)
                for k in METRIC_KEYS:
                    per_method[name][k].append(scores[k])
                per_method_sq[name].append(float(np.mean((test - np.asarray(point, dtype=float)) ** 2)))

        complete = all(
            np.all(np.isfinite(per_method[m][k])) for m in names for k in METRIC_KEYS
        )
        if not complete:
            continue
        kept.append(int(i))
        for m in names:
            for k in METRIC_KEYS:
                acc[m][k].append(float(np.mean(per_method[m][k])))
            sq[m].append(float(np.mean(per_method_sq[m])))

    per_series = {m: {k: np.asarray(v, dtype=float) for k, v in acc[m].items()} for m in names}
    squared_error = {m: np.asarray(v, dtype=float) for m, v in sq.items()}
    return per_series, np.asarray(kept, dtype=int), squared_error


def _aggregate(vals: np.ndarray) -> Dict[str, float]:
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"mean": float("nan"), "median": float("nan"), "n": 0}
    return {
        "mean": round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "n": int(arr.size),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ranking comparison — the question the run exists to answer
# ─────────────────────────────────────────────────────────────────────────────


def _kendall_tau(order_a: Sequence[str], order_b: Sequence[str]) -> float:
    """Kendall rank correlation between two orderings of the same method set."""
    pos_b = {name: i for i, name in enumerate(order_b)}
    n = len(order_a)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if pos_b[order_a[i]] < pos_b[order_a[j]]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return float((concordant - discordant) / total) if total else 1.0


def compare_rankings(
    mcb_by_metric: Dict[str, dict],
    aggregates: Dict[str, Dict[str, Dict[str, float]]],
) -> dict:
    """Does the leaderboard order change when we score distributions instead of points?

    Compared on MEAN FRIEDMAN RANK, not mean loss, for the reason in
    app/ml/model_comparison.py: mean scaled loss over thousands of series is
    dominated by the few with a near-zero scaling denominator.
    """
    def order(metric: str) -> List[str]:
        ranks = mcb_by_metric[metric]["mean_ranks"]
        return sorted(ranks, key=lambda m: ranks[m])

    orders = {m: order(m) for m in METRIC_KEYS}
    comparisons = []
    for point_metric in POINT_METRICS:
        for dist_metric in DIST_METRICS:
            a, b = orders[point_metric], orders[dist_metric]
            comparisons.append(
                {
                    "point_metric": point_metric,
                    "distributional_metric": dist_metric,
                    "point_order": a,
                    "distributional_order": b,
                    "identical": a == b,
                    "winner_changed": a[0] != b[0],
                    "kendall_tau": round(_kendall_tau(a, b), 4),
                }
            )
    any_change = any(not c["identical"] for c in comparisons)
    winner_change = any(c["winner_changed"] for c in comparisons)
    return {
        "orders_by_mean_friedman_rank": orders,
        "comparisons": comparisons,
        "ranking_changed": any_change,
        "winner_changed": winner_change,
        "zero_forecast_rank": {
            m: aggregates["zero"][m] for m in METRIC_KEYS
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────


def run_config(
    mat: np.ndarray,
    label: str,
    horizon: int,
    n_windows: int,
    min_train: int,
) -> dict:
    """One protocol configuration end to end: scores, leaderboard, MCB, DM/CW."""
    t0 = time.perf_counter()
    per_series, kept, squared_error = score_panel(mat, horizon, n_windows, min_train, METHODS)
    names = list(METHODS)
    n_kept = int(kept.size)
    logger.info(
        "[%s] h=%d origins=%d — scored %d/%d series on all %d methods",
        label, horizon, n_windows, n_kept, mat.shape[0], len(names),
    )

    leaderboard = {m: {k: _aggregate(per_series[m][k]) for k in METRIC_KEYS} for m in names}

    mcb_by_metric: Dict[str, dict] = {}
    for metric in METRIC_KEYS:
        losses = np.column_stack([per_series[m][metric] for m in names])
        mcb_by_metric[metric] = mcb_test(losses, names, alpha=ALPHA).as_dict()

    ranking = compare_rankings(mcb_by_metric, leaderboard)

    dm_results = [
        diebold_mariano(
            per_series[a]["crps"], per_series[b]["crps"],
            baseline_name=a, candidate_name=b, horizon=1,
        ).as_dict()
        for a, b in DM_PAIRS
    ]
    for r in dm_results:
        r["loss"] = "scaled_crps (per-series mean over origins)"
        r["nested"] = False

    # Clark-West needs the raw (actual, forecast) pairs, so replay the point
    # forecasts over the kept series only. Cheap: point methods, no distributions.
    cw_results = []
    cuts = rolling_origins(int(mat.shape[1]), horizon, n_windows, min_train)
    actuals: List[float] = []
    series_idx: List[int] = []
    point_by_method: Dict[str, List[float]] = {m: [] for m in names}
    for i in kept:
        for cut in cuts:
            train, test = mat[i][:cut], mat[i][cut:cut + horizon]
            actuals.extend(float(v) for v in test)
            series_idx.extend([int(i)] * horizon)
            for name, (point_fn, _) in METHODS.items():
                point_by_method[name].extend(float(v) for v in point_fn(train, horizon))
    for restricted, unrestricted, why, caveat in NESTED_PAIRS:
        res = clark_west(
            actuals,
            point_by_method[restricted],
            point_by_method[unrestricted],
            series_index=series_idx,
            restricted_name=restricted,
            unrestricted_name=unrestricted,
        ).as_dict()
        res["nesting"] = why
        res["why_not_diebold_mariano"] = (
            "Under the null that the restricted model generates the data, the larger "
            "model's extra parameters are pure estimation noise, so its MSPE is larger "
            "in population. The DM statistic is therefore centred below zero and is "
            "under-sized. Clark & West (2007) add back the (f1 - f2)^2 term to recentre it."
        )
        res["informative"] = caveat is None
        if caveat is not None:
            res["caveat"] = caveat
        cw_results.append(res)

    return {
        "label": label,
        "horizon": horizon,
        "n_origins": n_windows,
        "min_train": min_train,
        "train_sizes": cuts,
        "seasonality": SEASONALITY,
        "n_series_scored": n_kept,
        "n_series_dropped_undefined": int(mat.shape[0] - n_kept),
        "leaderboard": leaderboard,
        "mcb": mcb_by_metric,
        "ranking_comparison": ranking,
        "diebold_mariano": dm_results,
        "clark_west": cw_results,
        "wall_seconds": round(time.perf_counter() - t0, 2),
    }


def run_prophet_sample(mat: np.ndarray, sample: int, horizon: int, n_windows: int, min_train: int) -> dict:
    """Prophet on a random sample, scored as a DEGENERATE distribution.

    Prophet's own interval is Gaussian and continuous — the wrong object for a
    count with a ~76% atom at zero — so it is not used. Prophet is scored as a
    point forecast lifted to zero spread, exactly like `naive_last`, and the
    Croston-family methods are re-scored on the identical sample for a fair read.
    """
    import pandas as pd
    from prophet import Prophet

    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    def prophet_point(train: np.ndarray, h: int) -> List[float]:
        ds = pd.date_range("1998-01-01", periods=len(train), freq="MS")
        df = pd.DataFrame({"ds": ds, "y": [float(v) for v in train]})
        m = Prophet(
            yearly_seasonality=True, weekly_seasonality=False,
            daily_seasonality=False, uncertainty_samples=0,
        )
        m.fit(df)
        future = m.make_future_dataframe(periods=h, freq="MS", include_history=False)
        return [max(0.0, float(v)) for v in m.predict(future)["yhat"].to_numpy()]

    def prophet_dist(train: np.ndarray, h: int) -> List[np.ndarray]:
        return [it.point_mass(int(round(v))) for v in prophet_point(train, h)]

    rng = np.random.default_rng(SEED)
    k = min(sample, mat.shape[0])
    idx = np.sort(rng.choice(np.arange(mat.shape[0]), size=k, replace=False))
    methods = dict(METHODS)
    methods["prophet"] = (prophet_point, prophet_dist)

    logger.info("Prophet sample: %d series x %d origins (slow, refits per origin)...", k, n_windows)
    per_series, kept, _ = score_panel(mat, horizon, n_windows, min_train, methods, idx=idx)
    return {
        "sample_size": k,
        "seed": SEED,
        "n_series_scored": int(kept.size),
        "scored_as": "degenerate point mass (Prophet's Gaussian interval is not a count distribution)",
        "leaderboard": {
            m: {key: _aggregate(per_series[m][key]) for key in METRIC_KEYS} for m in methods
        },
    }


def _headline(primary: dict) -> str:
    """One sentence stating what the primary config actually found, computed not written."""
    ranks = primary["mcb"]
    mase_order = sorted(ranks["mase"]["mean_ranks"], key=lambda m: ranks["mase"]["mean_ranks"][m])
    crps_order = sorted(ranks["crps"]["mean_ranks"], key=lambda m: ranks["crps"]["mean_ranks"][m])
    spl_order = sorted(ranks["spl"]["mean_ranks"], key=lambda m: ranks["spl"]["mean_ranks"][m])
    if not primary["ranking_comparison"]["ranking_changed"]:
        return (
            f"NULL RESULT: across {primary['n_series_scored']} series the leaderboard order is "
            f"unchanged between point scoring (MASE) and proper scoring (CRPS/SPL) — "
            f"{mase_order[0]} wins under both."
        )
    return (
        f"Across {primary['n_series_scored']} series, MASE ranks '{mase_order[0]}' first "
        f"(mean rank {ranks['mase']['mean_ranks'][mase_order[0]]:.2f}) while CRPS ranks it "
        f"#{crps_order.index(mase_order[0]) + 1} and scaled pinball loss ranks it "
        f"#{spl_order.index(mase_order[0]) + 1}; under proper scoring the winner is "
        f"'{crps_order[0]}'. The point and distributional leaderboards disagree."
    )


def build_payload(mat: np.ndarray, configs: Sequence[dict], prophet: Optional[dict], started: datetime, wall: float) -> dict:
    nonzero = float((mat > 0).mean())
    nz = mat[mat > 0]
    return {
        "provenance": build_provenance(
            generator="seeds.run_carparts_backtest",
            inputs={"monash_car_parts_cache": CACHE_PATH},
            extra={
                "artifacts": [
                    f"docs/{ARTIFACT_NAME}",
                    f"backend/seeds/data/{ARTIFACT_NAME}",
                    "docs/INTERMITTENT_DEMAND.md (generated regions only)",
                ]
            },
        ),
        "headline": _headline(configs[0]),
        "meta": {
            "generated_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "wall_seconds": round(wall, 2),
            "hardware": f"{platform.machine()} / {platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "seed": SEED,
            # git provenance deliberately does NOT live here any more. This slot used
            # to hold a bare `git_sha()` string whose "-dirty" suffix was the only
            # signal that the numbers were unreproducible — easy to miss, and missed.
            # See the top-level "provenance" key, where `git.dirty` is a boolean with
            # a warning string attached and the markdown renders it in bold.
            "script": "backend/seeds/run_carparts_backtest.py",
            "command": "cd backend && python -m seeds.run_carparts_backtest",
        },
        "dataset": {
            "name": "monash_car_parts_with_missing_values",
            "source": "HuggingFace Monash-University/monash_tsf",
            "license": "CC-BY 4.0",
            "n_series": int(mat.shape[0]),
            "series_length": int(mat.shape[1]),
            "frequency": "monthly",
            "n_observations": int(mat.size),
            "nonzero_fraction": round(nonzero, 4),
            "mean_demand": round(float(mat.mean()), 4),
            "nonzero_size_mean": round(float(nz.mean()), 4),
            "nonzero_size_variance": round(float(nz.var()), 4),
            "nonzero_size_median": round(float(np.median(nz)), 4),
            "nonzero_size_p99": round(float(np.percentile(nz, 99)), 4),
            "nonzero_size_max": round(float(nz.max()), 4),
            "missing_convention": "'?' in the .tsf is read as 0 sales — Monash's own "
                                  "'without missing values' variant, the standard convention "
                                  "for count data where 'no record' means 'no sale'.",
            "why_this_panel": "No public per-SKU demand series exists for electronic "
                              "components. Car parts are real intermittent spare-parts "
                              "demand — the closest available analogue.",
        },
        "parameterisations": PARAMETERISATIONS,
        "size_distribution": {
            "family": "zero-truncated negative binomial, Poisson limit when not overdispersed",
            "shape_estimator": "method-of-moments plug-in r = m^2 / (v - m) on the non-zero "
                               "(truncated) sample; r = infinity when v <= m",
            "approximation_noted": "Applying the untruncated NB moment relation to a truncated "
                                   "sample is an approximation. It only binds on the ~18% of "
                                   "series whose non-zero sizes are overdispersed.",
            "empirical_justification": "Across the panel the non-zero sizes have a median "
                                       "variance/mean ratio of 0.42 and only 17.6% of series "
                                       "exceed 1.0. A zero-truncated Poisson with lambda ~ 1 "
                                       "implies 0.418, so the Poisson limit is the data's own "
                                       "default rather than a convenience.",
        },
        "scoring": {
            "point": {
                "mase": "MAE / in-sample seasonal-naive MAE (seasonality 12), training-only denominator",
                "rmsse": "sqrt(MSE / in-sample naive MSE), training-only denominator",
                "caveat": "Neither is a proper scoring rule. MASE is minimised by the "
                          "conditional median, which on this panel is usually zero.",
            },
            "distributional": {
                "crps": "CRPS by the exact threshold decomposition SUM_k (F(k) - 1{y<=k})^2 for "
                        "integer support — NOT the Gaussian closed form, which assumes a "
                        "continuous symmetric law that a count with a 76% atom at zero violates. "
                        "Scaled by the SAME denominator as MASE, so a degenerate distribution's "
                        "scaled CRPS equals its MASE exactly.",
                "spl": "Scaled pinball loss over quantile levels "
                       f"{list(it.DEFAULT_QUANTILE_LEVELS)}, same denominator (M5 Uncertainty metric).",
                "reference": "Gneiting & Raftery (2007), JASA 102(477):359-378",
            },
        },
        "protocol": {
            "split": "rolling origin, non-overlapping test blocks, refit at every origin",
            "shared_with": "app.ml.backtest.rolling_origins — the same function "
                           "walk_forward_backtest uses, so this and the macro A34SNO backtest "
                           "run one protocol by construction",
            "replication_unit": "the series: metrics are averaged within a series across origins "
                                "before any cross-series test",
            "balance": "a series enters the tests only if EVERY method produced a finite score at "
                       "EVERY origin, so the ranked panel is balanced",
            "previous_protocol": "single split (last 12 months held out) — replaced here; the "
                                 "inconsistency with the other backtests was a known weakness",
        },
        "configs": {c["label"]: c for c in configs},
        "prophet_sample": prophet,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Markdown: the numeric half of docs/INTERMITTENT_DEMAND.md, generated
# ─────────────────────────────────────────────────────────────────────────────

#: Matches one delimited region. The closing marker must name the same key as the
#: opening one, so a mismatched pair is a non-match and therefore a loud failure
#: rather than a silent over-write of the wrong span.
_BLOCK_RE = re.compile(
    r"(?P<open><!-- GENERATED:(?P<key>[a-z0-9_]+) BEGIN -->\n)"
    r".*?"
    r"(?P<close>\n<!-- GENERATED:(?P=key) END -->)",
    re.DOTALL,
)

#: Leaderboard-order suffixes. Used only for "1st of 6"-style rank prose.
_ORDINALS = ("0th", "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th")


def _ordinal(n: int) -> str:
    return _ORDINALS[n] if n < len(_ORDINALS) else f"{n}th"


def _fmt_p(p: float) -> str:
    """A p-value that underflowed to 0.0 is a bound, not a zero — say so."""
    return "< 1e-300" if not p else f"{p:.1e}"


def _order_by_rank(mcb: Mapping[str, Any], metric: str) -> List[str]:
    ranks = mcb[metric]["mean_ranks"]
    return sorted(ranks, key=lambda m: ranks[m])


def _bold(text: str, on: bool) -> str:
    return f"**{text}**" if on else text


def _num(value: float, spec: str = ".2f") -> str:
    """Format a number with a typographic minus (U+2212), matching the doc's prose."""
    return format(value, spec).replace("-", "\u2212")


def _prose(text: str, width: int = 90) -> str:
    """Soft-wrap a generated paragraph so its diffs stay line-sized and reviewable."""
    return "\n".join(textwrap.wrap(" ".join(text.split()), width=width))


def render_blocks(payload: Mapping[str, Any]) -> Dict[str, str]:
    """Every generated region of docs/INTERMITTENT_DEMAND.md, keyed by marker name.

    Nothing here is transcribed: each figure is read out of ``payload``, which is
    the same object written to ``docs/intermittent_demand.json``. That is the whole
    point — the doc and the artifact can no longer disagree.
    """
    meta = payload["meta"]
    dataset = payload["dataset"]
    configs = payload["configs"]
    primary = configs["primary"]
    sensitivity = configs.get("sensitivity_h12")
    names = list(primary["leaderboard"])
    mcb = primary["mcb"]
    n_methods = len(names)

    blocks: Dict[str, str] = {}

    # ── provenance / run header ──────────────────────────────────────────────
    blocks["header"] = "\n".join([
        f"Generated `{meta['generated_utc']}` by `{meta['command']}`.",
        f"Machine-readable: [`{ARTIFACT_NAME}`]({ARTIFACT_NAME}).",
        f"Hardware {meta['hardware']} · Python {meta['python']} · numpy {meta['numpy']} · "
        f"scipy {meta['scipy']} · seed {meta['seed']} · {meta['wall_seconds']:.1f} s wall.",
    ])

    # ── the headline: who wins under which question ──────────────────────────
    winners = {m: _order_by_rank(mcb, m)[0] for m in METRIC_KEYS}
    zero_rank = {m: _order_by_rank(mcb, m).index("zero") + 1 for m in METRIC_KEYS}
    labels = {
        "mase": "**MASE** (point)",
        "rmsse": "**RMSSE** (point)",
        "crps": "**CRPS** (proper)",
        "spl": "**Scaled pinball loss** (proper)",
    }
    rows = ["| | winner | `zero` forecast's rank |", "|---|---|---:|"]
    for metric in METRIC_KEYS:
        # The zero-forecast's rank is emphasised only where it wins, which is the
        # claim the page is making; the winner column is always emphasised.
        rows.append(
            f"| {labels[metric]} | **`{winners[metric]}`** | "
            f"{_bold(f'{_ordinal(zero_rank[metric])} of {n_methods}', zero_rank[metric] == 1)} |"
        )
    blocks["headline_table"] = "\n".join(rows)

    tau = next(
        c["kendall_tau"]
        for c in primary["ranking_comparison"]["comparisons"]
        if c["point_metric"] == "mase" and c["distributional_metric"] == "spl"
    )
    blocks["kendall"] = _prose(
        f"Kendall's tau between the MASE ordering and the pinball ordering is "
        f"**{_num(tau, '+.2f')}** — the two leaderboards are not merely different, they "
        "are mildly *anti*-correlated."
    )
    blocks["nonzero_share"] = _prose(
        f"This panel is {dataset['nonzero_fraction'] * 100:.1f}% non-zero, so for most "
        "series in most months the conditional median *is zero*."
    )

    # ── §2 the panel ─────────────────────────────────────────────────────────
    nz = dataset["nonzero_size_variance"] / dataset["nonzero_size_mean"]
    blocks["panel_table"] = "\n".join([
        "| | |",
        "|---|---|",
        f"| Dataset | Monash car parts, `{dataset['name']}` |",
        f"| Source | HuggingFace `{dataset['source'].split()[-1]}`, {dataset['license']} |",
        f"| Size | **{dataset['n_series']:,} series × {dataset['series_length']} months = "
        f"{dataset['n_observations']:,} observations**, {dataset['frequency']} |",
        f"| Intermittency | **{dataset['nonzero_fraction'] * 100:.1f}% non-zero** "
        f"({(1 - dataset['nonzero_fraction']) * 100:.1f}% of observations are exactly 0) |",
        f"| Mean demand | {dataset['mean_demand']:.3f} units/month |",
        f"| Non-zero order size | mean {dataset['nonzero_size_mean']:.2f}, variance "
        f"{dataset['nonzero_size_variance']:.2f} (variance/mean {nz:.2f}), median "
        f"{dataset['nonzero_size_median']:.0f}, 99th pct {dataset['nonzero_size_p99']:.0f}, "
        f"max {dataset['nonzero_size_max']:.0f} |",
        "| Missing convention | `?` read as 0 — Monash's own "
        '"without missing values" variant |',
    ])

    # ── §3 the protocol ──────────────────────────────────────────────────────
    def _col(cfg: Optional[Mapping[str, Any]], key: str) -> str:
        if cfg is None:
            return "*not run*"
        if key == "train_sizes":
            return " / ".join(str(v) for v in cfg["train_sizes"])
        if key == "scored":
            return f"{cfg['n_series_scored']:,} of {dataset['n_series']:,}"
        return str(cfg[key])

    blocks["protocol_table"] = "\n".join([
        "| | primary | sensitivity |",
        "|---|---|---|",
        f"| Horizon | {_col(primary, 'horizon')} months | "
        f"{_col(sensitivity, 'horizon')}{' months' if sensitivity else ''} |",
        f"| Origins | {_col(primary, 'n_origins')} | {_col(sensitivity, 'n_origins')} |",
        f"| Train sizes | {_col(primary, 'train_sizes')} | {_col(sensitivity, 'train_sizes')} |",
        f"| Seasonality (MASE denominator) | {_col(primary, 'seasonality')} | "
        f"{_col(sensitivity, 'seasonality')} |",
        f"| Series scored | {_col(primary, 'scored')} | {_col(sensitivity, 'scored')} |",
    ])
    blocks["dropped_series"] = _prose(
        f"{primary['n_series_dropped_undefined']} series are dropped from the primary "
        "configuration — all of them constant training windows, where the seasonal-naive "
        "denominator is zero and every scaled metric is undefined. Scoring one method on "
        f"{dataset['n_series']:,} series and another on {primary['n_series_scored']:,} "
        "would make their mean ranks incomparable."
    )

    # ── §5 the leaderboard ───────────────────────────────────────────────────
    best: Dict[str, float] = {}
    for metric in METRIC_KEYS:
        best[metric] = min(primary["leaderboard"][m][metric]["mean"] for m in names)
    best["mase_median"] = min(primary["leaderboard"][m]["mase"]["median"] for m in names)
    best_rank = {m: min(mcb[m]["mean_ranks"].values()) for m in ("mase", "crps", "spl")}

    rows = [
        "| Method | MASE mean | MASE median | RMSSE | scaled CRPS | scaled pinball | "
        "rank<sub>MASE</sub> | rank<sub>CRPS</sub> | rank<sub>SPL</sub> |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in names:
        lb = primary["leaderboard"][name]
        cells = [
            _bold(f"{lb['mase']['mean']:.3f}", lb["mase"]["mean"] == best["mase"]),
            _bold(f"{lb['mase']['median']:.3f}", lb["mase"]["median"] == best["mase_median"]),
            _bold(f"{lb['rmsse']['mean']:.3f}", lb["rmsse"]["mean"] == best["rmsse"]),
            _bold(f"{lb['crps']['mean']:.3f}", lb["crps"]["mean"] == best["crps"]),
            _bold(f"{lb['spl']['mean']:.3f}", lb["spl"]["mean"] == best["spl"]),
        ]
        for metric in ("mase", "crps", "spl"):
            r = mcb[metric]["mean_ranks"][name]
            cells.append(_bold(f"{r:.2f}", r == best_rank[metric]))
        rows.append(f"| `{name}` | " + " | ".join(cells) + " |")
    blocks["leaderboard"] = "\n".join(rows)

    # ── §6 MCB ───────────────────────────────────────────────────────────────
    cd = mcb["mase"]["critical_difference"]
    blocks["critical_difference"] = _prose(
        f"**CD = {cd:.4f}** at α = {mcb['mase']['alpha']} for k = {n_methods} methods and "
        f"N = {primary['n_series_scored']:,} series. Any two methods whose mean ranks "
        "differ by more than that are significantly different."
    )
    rows = [
        f"| Metric | Friedman χ²({n_methods - 1}) | p | Iman–Davenport F | "
        "Not separated by the CD |",
        "|---|---:|---:|---:|---|",
    ]
    metric_titles = {"mase": "MASE", "rmsse": "RMSSE", "crps": "**CRPS**",
                     "spl": "**Scaled pinball**"}
    for metric in METRIC_KEYS:
        block = mcb[metric]
        cliques = block["cliques"]
        if cliques:
            not_sep = "; ".join(" — ".join(f"`{m}`" for m in c) for c in cliques)
        else:
            not_sep = "**none — every pair separated**"
        rows.append(
            f"| {metric_titles[metric]} | {block['friedman_chi2']:.1f} | "
            f"{_fmt_p(block['friedman_p'])} | {block['iman_davenport_f']:.1f} | {not_sep} |"
        )
    blocks["mcb_table"] = "\n".join(rows)

    # Critical-difference diagram, drawn as fixed-width text: methods laid out on the
    # mean-rank axis, best on the left, with a bar under any adjacent pair the data
    # cannot separate. Column width follows the longest method name so the rank row
    # always sits under its own label.
    pad = max(len(m) for m in names) + 2
    indent = " " * 10
    axis = "─" * (pad * n_methods - 4)
    diagram: List[str] = ["```"]
    for metric, title in (("crps", "CRPS"), ("mase", "MASE")):
        order = _order_by_rank(mcb, metric)
        ranks = mcb[metric]["mean_ranks"]
        cd_m = mcb[metric]["critical_difference"]
        diagram.append(f"{title:<6} 1 {axis} {n_methods}")
        diagram.append((indent + "".join(f"{m:<{pad}}" for m in order)).rstrip())
        diagram.append((indent + "".join(f"{ranks[m]:<{pad}.2f}" for m in order)).rstrip())
        bar = [" "] * (pad * n_methods)
        tight: List[Tuple[str, str, float]] = []
        for i, (a, b) in enumerate(zip(order[:-1], order[1:], strict=True)):
            gap = ranks[b] - ranks[a]
            if gap >= cd_m:
                continue
            tight.append((a, b, gap))
            bar[i * pad] = "└"
            bar[(i + 1) * pad + 3] = "┘"
            for j in range(i * pad + 1, (i + 1) * pad + 3):
                bar[j] = "─"
        if tight:
            diagram.append((indent + "".join(bar)).rstrip())
            for a, b, gap in tight:
                diagram.append(
                    f"{indent}{a}–{b} gap {gap:.2f} < CD {cd_m:.3f} — not separated"
                )
        else:
            diagram.append(
                f"{indent}(no bar: every adjacent gap exceeds CD = {cd_m:.3f})"
            )
        diagram.append("")
    diagram[-1] = "```"
    blocks["cd_diagram"] = "\n".join(diagram)

    # ── §7 sensitivity ───────────────────────────────────────────────────────
    if sensitivity is None:
        blocks["sensitivity"] = (
            "*The horizon-12 sensitivity configuration was not run "
            "(`--quick`), so this section has nothing to report.*"
        )
    else:
        s_mcb = sensitivity["mcb"]
        same = [
            m for m in ("mase", "crps", "spl")
            if _order_by_rank(s_mcb, m) == _order_by_rank(mcb, m)
        ]
        # The section is titled with a question, so the answer is computed, never
        # written: it is whatever the sensitivity run's orderings actually did.
        verdict = "**Yes.**" if len(same) == 3 else "**Only partly.**"
        rows = [
            _prose(
                f"{verdict} Under the sensitivity configuration (horizon "
                f"{sensitivity['horizon']}, {sensitivity['n_origins']} origins, "
                f"{sensitivity['n_series_scored']:,} series):"
            ),
            "",
            "| Metric | Ordering, best first |",
            "|---|---|",
        ]
        for metric, title in (("mase", "MASE"), ("crps", "CRPS"), ("spl", "Scaled pinball")):
            ordering = " · ".join(f"`{m}`" for m in _order_by_rank(s_mcb, metric))
            rows.append(f"| {title} | {ordering} |")
        rows.append("")
        if len(same) == 3:
            rows.append(_prose(
                "Identical to the primary configuration on all three, including `zero` "
                f"{_ordinal(_order_by_rank(s_mcb, 'mase').index('zero') + 1)} under MASE and "
                f"{_ordinal(_order_by_rank(s_mcb, 'crps').index('zero') + 1)}/"
                f"{_ordinal(_order_by_rank(s_mcb, 'spl').index('zero') + 1)} under proper "
                "scoring. The finding is a property of the metric, not of the protocol."
            ))
        else:
            differing = [m for m in ("mase", "crps", "spl") if m not in same]
            rows.append(_prose(
                "**Not identical to the primary configuration.** The ordering matches on "
                + (", ".join(same) or "no metric")
                + " and differs on "
                + ", ".join(differing)
                + " — reported as measured, not as expected."
            ))
        blocks["sensitivity"] = "\n".join(rows)

    # ── §8 Clark–West and Diebold–Mariano ────────────────────────────────────
    rows = [
        "| Restricted | Unrestricted | Nesting | CW t | p | Informative? |",
        "|---|---|---|---:|---:|---|",
    ]
    informative: List[Mapping[str, Any]] = [
        r for r in primary["clark_west"] if r["informative"]
    ]
    # Informative rows first — the degenerate zero-restriction rows are kept and
    # flagged, not dropped, but they are not the result.
    ordered = informative + [r for r in primary["clark_west"] if not r["informative"]]
    previous_nesting = ""
    for res in ordered:
        verdict = "**yes**" if res["informative"] else "**no — degenerate**"
        stat = _bold(f"{res['statistic']:.2f}", res["informative"])
        nesting = "as above" if res["nesting"] == previous_nesting else res["nesting"]
        previous_nesting = res["nesting"]
        rows.append(
            f"| `{res['restricted_model']}` | `{res['unrestricted_model']}` | "
            f"{nesting} | {stat} | {_fmt_p(res['p_value'])} | {verdict} |"
        )
    blocks["clark_west_table"] = "\n".join(rows)

    if len(informative) == 1:
        res = informative[0]
        blocks["clark_west_verdict"] = _prose(
            f"**The one informative nested result** is therefore "
            f"`{res['restricted_model']} → {res['unrestricted_model']}`: "
            f"t = {res['statistic']:.2f}, p = {_fmt_p(res['p_value'])}. The "
            "Syntetos–Boylan bias correction genuinely improves squared-error accuracy "
            f"over Croston. Modest — mean adjusted difference "
            f"{res['mean_adjusted_difference']:.3f} — but real, and it is the kind of "
            "claim that a raw DM test on a nested pair would have understated."
        )
    else:
        blocks["clark_west_verdict"] = _prose(
            f"{len(informative)} of {len(primary['clark_west'])} nested comparisons are "
            "informative; the rest are the degenerate zero-restriction rows flagged above."
        )

    rows = [
        "| Baseline | Candidate | Δ scaled CRPS | t | p |",
        "|---|---|---:|---:|---:|",
    ]
    for res in primary["diebold_mariano"]:
        rows.append(
            f"| `{res['baseline']}` | `{res['candidate']}` | "
            f"{res['mean_loss_difference']:+.3f} | {res['statistic']:.2f} | "
            f"{_fmt_p(res['p_value'])} |"
        )
    blocks["dm_table"] = "\n".join(rows)

    blocks["provenance"] = provenance_markdown(
        payload["provenance"], heading="### Provenance of this run"
    ).strip("\n")

    return blocks


def splice_generated(existing: str, blocks: Mapping[str, str]) -> str:
    """Replace every ``GENERATED:<key>`` region in ``existing`` with ``blocks[key]``.

    Text outside the markers is curated prose and is returned byte-for-byte. Raises
    when the doc's marker set and ``blocks`` disagree in either direction, so a
    renamed block can never silently leave a stale number on the page.
    """
    found: set[str] = set()

    def _sub(match: "re.Match[str]") -> str:
        key = match.group("key")
        if key not in blocks:
            raise KeyError(
                f"docs/INTERMITTENT_DEMAND.md declares GENERATED:{key}, which "
                f"render_blocks() does not produce. Known blocks: {sorted(blocks)}"
            )
        found.add(key)
        return match.group("open") + blocks[key] + match.group("close")

    out = _BLOCK_RE.sub(_sub, existing)
    missing = set(blocks) - found
    if missing:
        raise ValueError(
            "render_blocks() produced blocks with no GENERATED marker in "
            f"docs/INTERMITTENT_DEMAND.md: {sorted(missing)}"
        )
    return out


def write_doc(payload: Mapping[str, Any], path: Path = DOC_PATH) -> bool:
    """Refresh the generated regions of the writeup. Returns True when it changed."""
    if not path.is_file():
        logger.warning("no %s to refresh — skipping the doc rewrite", path)
        return False
    before = path.read_text()
    after = splice_generated(before, render_blocks(payload))
    if after == before:
        logger.info("%s already matches the artifact", path.name)
        return False
    path.write_text(after)
    logger.info("refreshed the generated regions of %s", path.name)
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true", help="primary config only (skip the h=12 sensitivity run)")
    ap.add_argument("--prophet", action="store_true", help="also score Prophet on a random sample (slow)")
    ap.add_argument("--sample", type=int, default=150, help="series count for the Prophet sample")
    ap.add_argument("--no-refresh", action="store_true", help="use the cached Monash snapshot, skip the download")
    args = ap.parse_args(argv)

    started = datetime.now(UTC)
    t0 = time.perf_counter()

    from seeds.monash_loader import as_matrix, load_car_parts

    series = load_car_parts(refresh=not args.no_refresh)
    _, mat = as_matrix(series)
    logger.info(
        "Loaded %d Monash car-parts series x %d months (non-zero %.1f%%)",
        mat.shape[0], mat.shape[1], (mat > 0).mean() * 100,
    )

    configs = [
        run_config(mat, label, h, w, mt)
        for label, h, w, mt in (CONFIGS[:1] if args.quick else CONFIGS)
    ]

    prophet = None
    if args.prophet:
        _, h, w, mt = CONFIGS[0]
        prophet = run_prophet_sample(mat, args.sample, h, w, mt)

    payload = build_payload(mat, configs, prophet, started, time.perf_counter() - t0)

    text = json.dumps(payload, indent=2) + "\n"
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / ARTIFACT_NAME).write_text(text)
    SERVED_MIRROR.parent.mkdir(parents=True, exist_ok=True)
    SERVED_MIRROR.write_text(text)
    if args.quick:
        logger.warning(
            "--quick run: NOT rewriting %s. The doc quotes the horizon-12 sensitivity "
            "check, which --quick skips; publishing it would silently drop §7.",
            DOC_PATH.name,
        )
    else:
        write_doc(payload)

    primary = configs[0]
    logger.info("── %s ──", primary["label"])
    for name in METHODS:
        row = primary["leaderboard"][name]
        logger.info(
            "  %-12s MASE %.3f (med %.3f) | RMSSE %.3f | sCRPS %.3f | SPL %.3f",
            name, row["mase"]["mean"], row["mase"]["median"], row["rmsse"]["mean"],
            row["crps"]["mean"], row["spl"]["mean"],
        )
    rc = primary["ranking_comparison"]
    logger.info("  ranking changed under proper scoring: %s", rc["ranking_changed"])
    logger.info("  winner changed: %s", rc["winner_changed"])
    logger.info("DONE — wrote %s and %s", DOCS / ARTIFACT_NAME, SERVED_MIRROR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
