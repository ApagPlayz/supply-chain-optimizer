"""Demand model API — the real intermittent-demand benchmark.

Replaces the retired `/forecasts/*` surface. That endpoint served per-part Prophet
fits over `component_demand_history`, whose magnitudes were derived from inventory
position and a risk score (demand inferred from stock — causally backwards), and
whose 12-week forecast window closed 17 months ago with no actuals ever recorded
against it. It was unscoreable in principle, so it was removed rather than
patched; migration 0008 drops the tables.

What replaced it is narrower and true. There is no public per-SKU demand series
for electronic components, so this app does not claim a per-part demand forecast.
What it can show is which intermittent-demand method to trust and why, measured on
real data: the Monash car-parts panel (2,674 SKUs x 51 months, 24.1% non-zero),
scored under both point and proper scoring rules with significance tests.

The endpoint is a thin, typed read of the committed artifact
`docs/intermittent_demand.json`, produced by
`python -m seeds.run_carparts_backtest`. It computes nothing at request time — the
numbers a reader sees are the same bytes the doc cites.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/demand", tags=["demand"])

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: Resolution order for the artifact. The repo-root docs/ copy is canonical and is
#: what the documentation cites; the seeds/data mirror exists because the container
#: build context is `backend/` (Dockerfile `COPY . .`, render.yaml `rootDir:
#: backend`), so repo-root docs/ is not guaranteed to be on disk at runtime. The
#: backtest script writes both in one pass, so they cannot drift.
ARTIFACT_CANDIDATES = (
    BACKEND_ROOT.parent / "docs" / "intermittent_demand.json",
    BACKEND_ROOT / "seeds" / "data" / "intermittent_demand.json",
)

_PRIMARY_CONFIG = "primary"


class MethodRow(BaseModel):
    """One method's scores under both the point and the distributional rules."""

    name: str
    family: str
    assumption: str
    mase_mean: float
    mase_median: float
    rmsse_mean: float
    crps_mean: float
    spl_mean: float
    #: Mean Friedman rank (1 = best). The ranking the MCB test actually compares.
    rank_mase: float
    rank_rmsse: float
    rank_crps: float
    rank_spl: float


class McbSummary(BaseModel):
    """Critical-difference diagram data for one metric."""

    metric: str
    n_series: int
    alpha: float
    friedman_chi2: float
    friedman_p: float
    critical_difference: float
    mean_ranks: Dict[str, float]
    #: Groups whose mean ranks span less than the CD — the diagram's horizontal bars.
    cliques: List[List[str]]


class SignificanceRow(BaseModel):
    test: str
    a: str
    b: str
    statistic: float
    p_value: float
    note: str


class DemandBenchmarkResponse(BaseModel):
    headline: str
    generated_utc: str
    git_sha: Optional[str] = None
    dataset: Dict[str, Any]
    protocol: Dict[str, Any]
    scoring: Dict[str, Any]
    methods: List[MethodRow]
    #: True when the leaderboard order differs between point and proper scoring.
    ranking_changed: bool
    winner_changed: bool
    point_winner: str
    distributional_winner: str
    mcb: List[McbSummary]
    significance: List[SignificanceRow]
    artifact: str
    reproduce_command: str


def _find_artifact() -> Optional[Path]:
    for path in ARTIFACT_CANDIDATES:
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=1)
def _load(mtime_key: float, path_str: str) -> Dict[str, Any]:
    """Parse the artifact. Keyed on mtime so an on-disk regeneration invalidates it."""
    del mtime_key
    data: Dict[str, Any] = json.loads(Path(path_str).read_text())
    return data


def _build_response(payload: Dict[str, Any], artifact_rel: str) -> DemandBenchmarkResponse:
    config = payload["configs"][_PRIMARY_CONFIG]
    leaderboard = config["leaderboard"]
    mcb = config["mcb"]
    params = payload["parameterisations"]

    methods = [
        MethodRow(
            name=name,
            family=params.get(name, {}).get("family", ""),
            assumption=params.get(name, {}).get("assumption", ""),
            mase_mean=row["mase"]["mean"],
            mase_median=row["mase"]["median"],
            rmsse_mean=row["rmsse"]["mean"],
            crps_mean=row["crps"]["mean"],
            spl_mean=row["spl"]["mean"],
            rank_mase=mcb["mase"]["mean_ranks"][name],
            rank_rmsse=mcb["rmsse"]["mean_ranks"][name],
            rank_crps=mcb["crps"]["mean_ranks"][name],
            rank_spl=mcb["spl"]["mean_ranks"][name],
        )
        for name, row in leaderboard.items()
    ]
    methods.sort(key=lambda m: m.rank_crps)

    mcb_summaries = [
        McbSummary(
            metric=metric,
            n_series=block["n_series"],
            alpha=block["alpha"],
            friedman_chi2=block["friedman_chi2"],
            friedman_p=block["friedman_p"],
            critical_difference=block["critical_difference"],
            mean_ranks=block["mean_ranks"],
            cliques=block["cliques"],
        )
        for metric, block in mcb.items()
    ]

    significance: List[SignificanceRow] = []
    for row in config["clark_west"]:
        significance.append(
            SignificanceRow(
                test="clark_west",
                a=row["restricted_model"],
                b=row["unrestricted_model"],
                statistic=row["statistic"],
                p_value=row["p_value"],
                note=row.get("caveat") or row["nesting"],
            )
        )
    for row in config["diebold_mariano"]:
        significance.append(
            SignificanceRow(
                test="diebold_mariano",
                a=row["baseline"],
                b=row["candidate"],
                statistic=row["statistic"],
                p_value=row["p_value"],
                note=row["loss"],
            )
        )

    ranking = config["ranking_comparison"]
    orders = ranking["orders_by_mean_friedman_rank"]
    return DemandBenchmarkResponse(
        headline=payload["headline"],
        generated_utc=payload["meta"]["generated_utc"],
        git_sha=payload["meta"].get("git_sha"),
        dataset=payload["dataset"],
        protocol={
            **payload["protocol"],
            "horizon": config["horizon"],
            "n_origins": config["n_origins"],
            "train_sizes": config["train_sizes"],
            "seasonality": config["seasonality"],
            "n_series_scored": config["n_series_scored"],
            "n_series_dropped_undefined": config["n_series_dropped_undefined"],
        },
        scoring=payload["scoring"],
        methods=methods,
        ranking_changed=ranking["ranking_changed"],
        winner_changed=ranking["winner_changed"],
        point_winner=orders["mase"][0],
        distributional_winner=orders["crps"][0],
        mcb=mcb_summaries,
        significance=significance,
        artifact=artifact_rel,
        reproduce_command=payload["meta"]["command"],
    )


@router.get("/benchmark", response_model=DemandBenchmarkResponse)
def get_demand_benchmark() -> DemandBenchmarkResponse:
    """The intermittent-demand method benchmark: point vs proper scoring, with MCB.

    503 rather than an empty body when the artifact is absent: an empty leaderboard
    would read as "no method works", which is a different and false claim from
    "the measurement has not been run in this deployment".
    """
    path = _find_artifact()
    if path is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Demand benchmark artifact not found. Regenerate it with "
                "`cd backend && python -m seeds.run_carparts_backtest`."
            ),
        )
    payload = _load(path.stat().st_mtime, str(path))
    try:
        return _build_response(payload, f"docs/{path.name}")
    except KeyError as exc:  # artifact from an older schema
        raise HTTPException(
            status_code=503,
            detail=f"Demand benchmark artifact is missing key {exc}; regenerate it.",
        ) from exc
