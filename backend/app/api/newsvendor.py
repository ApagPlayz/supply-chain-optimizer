"""
Newsvendor inventory-decision API -- the demand distribution turned into an order.

Three endpoints over `app/optimization/newsvendor.py`:

  GET  /newsvendor/assumptions   The two costs and the critical fractile they imply,
                                 with the provenance of every input. Nothing else.
  POST /newsvendor/decision      One order quantity for one demand history, with its
                                 expected cost decomposition and what the naive rules
                                 would have ordered instead.
  GET  /newsvendor/evaluation    The policy scored against every baseline on 2,643
                                 held-out car-parts series, with paired bootstrap CIs.

WHY THE ASSUMPTIONS ENDPOINT EXISTS
------------------------------------
Same reason `/stochastic/calibration` exists. The weakest input in this subsystem is not
the forecast, it is the COST ASYMMETRY: an expedite premium and a holding rate, each cited
but each an industry average rather than a measurement of any part this app sells. The
entire answer is a monotone function of their ratio. Burying that behind a confident order
quantity would be the same mistake the CVaR work was built to fix, so the ratio is a
first-class, inspectable resource and every knob that moves it is a request parameter.

WHAT DRIVES THE DECISION, STATED ONCE HERE AND AGAIN IN EVERY RESPONSE
----------------------------------------------------------------------
The DEMAND predictive distribution from `app/ml/intermittent.py` -- the compound
Bernoulli x zero-truncated NegBin law that `GET /demand/benchmark` already scores under
CRPS and the pinball loss. Not the lead-time model, and not a per-part forecast for the
electronic components in this catalogue: none exists, `docs/INTERMITTENT_DEMAND.md`
explains why the synthetic one was deleted, and this endpoint does not bring it back under
a new name. The panel is Monash car parts, real intermittent spare-parts demand used as a
labelled stand-in.

DoS POSTURE
-----------
`/decision` is closed-form -- one smoothing pass and one cdf lookup -- and its only
unbounded input, the demand history, is length-capped. `/evaluation` is the expensive one
(~4 s over 2,674 series x 3 origins x 6 methods), so its parameter space is deliberately
small and fully enumerable: 6 methods x 12 review periods x 2 shortage modes, cached on a
bounded LRU. It takes NO unit price, because the critical fractile does not depend on price
and the dollars scale linearly -- so a caller cannot force a recomputation by perturbing a
float. That is a security property, and it falls out of the maths rather than a rate limit.

Public, no auth -- consistent with `/demand/benchmark` and `/stochastic/*`, which likewise
serve aggregate model results derived from committed data and no user data.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ml.proper_scoring import DEFAULT_QUANTILE_LEVELS
from app.optimization import newsvendor as nv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/newsvendor", tags=["newsvendor"])

# ── Server-fixed bounds (never caller-controlled beyond these) ───────────────

#: Longest demand history accepted. 600 monthly observations is 50 years; anything longer
#: is not a spare-parts history, and the smoothing recursions are O(n) so the cap is about
#: bounding request size rather than compute.
MAX_HISTORY = 600

#: Shortest history that can support a forecast at all. Croston needs at least one
#: non-zero observation and an inter-arrival interval; TSB needs a probability to smooth.
#: Below a year of monthly data none of them are saying anything.
MIN_HISTORY = 12

#: Largest single demand observation accepted, so a caller cannot allocate a huge
#: `climatology_dist` support (its length is max(train) + 1).
MAX_OBSERVATION = 100_000

#: Longest review period. Past a year the single-period newsvendor abstraction -- no
#: carry-over, no reorder -- has stopped describing anything real.
MAX_REVIEW_PERIOD_MONTHS = 12

#: How many distinct `/evaluation` configurations stay warm. The whole space is
#: 6 x 12 x 2 = 144; this holds the ones anyone actually asks for.
EVALUATION_CACHE_SIZE = 32

#: Bootstrap replications for the served evaluation. 5,000 is what
#: `app/ml/regime_model.py::_paired_brier` uses; matched so the two CIs are comparable.
EVALUATION_N_BOOT = 5000


class DecisionRequest(BaseModel):
    """One stocking decision. Either bring your own history or name a panel series."""

    demand_history: Optional[List[float]] = Field(
        default=None,
        description=(
            "Observed demand per period, oldest first, as non-negative counts. This is the "
            "training window: the predictive distribution is fitted to it and nothing else. "
            f"Between {MIN_HISTORY} and {MAX_HISTORY} observations."
        ),
    )
    series: Optional[str] = Field(
        default=None,
        description=(
            "Instead of a history, the id of a series in the committed Monash car-parts "
            "panel (e.g. 'T2674'). Real intermittent spare-parts demand, used as a labelled "
            "stand-in for electronic components -- there is no public per-SKU demand series "
            "for the parts in this catalogue."
        ),
    )
    train_periods: Optional[int] = Field(
        default=None,
        ge=MIN_HISTORY,
        le=MAX_HISTORY,
        description=(
            "When `series` is used, fit on only the first N months of it. Defaults to the "
            "whole series. Set it to 33, 39 or 45 to reproduce a rolling origin of the "
            "published backtest."
        ),
    )
    method: str = Field(
        default=nv.DEFAULT_METHOD,
        description=(
            "Which predictive distribution to decide on. 'tsb' / 'sba' / 'croston' are the "
            "parametric compound-Bernoulli laws; 'climatology' is the empirical in-sample "
            "distribution; 'naive_last' and 'zero' are degenerate point forecasts with no "
            "spread, on the list only because they are on the demand leaderboard."
        ),
    )
    unit_price_usd: float = Field(
        default=1.0,
        gt=0.0,
        le=1_000_000.0,
        description=(
            "Price of one unit. Both costs are proportional to it, so it scales every dollar "
            "figure linearly and cancels out of the critical fractile entirely. The default "
            "of $1.00 makes the response read as 'per dollar of unit price'."
        ),
    )
    review_period_months: int = Field(
        default=1,
        ge=1,
        le=MAX_REVIEW_PERIOD_MONTHS,
        description=(
            "How long the order has to cover. >1 aggregates the monthly predictive law by "
            "exact convolution, which is exact only under the model's i.i.d.-across-periods "
            "assumption, and lengthens the holding charge."
        ),
    )
    shortage_mode: str = Field(
        default="expedite",
        description=(
            "How a shortage is priced. 'expedite' (default) = 0.15 x unit price, the "
            "emergency-reprocurement premium: a spare part that is out of stock is "
            "re-procured, not lost. 'line_down' = 3.0 x unit price after Snyder & Daskin "
            "(2005), for a single-sourced part with no substitute -- a SENSITIVITY whose "
            "0.993 fractile is past what 45 monthly observations can resolve."
        ),
    )
    expedite_freight_usd_per_unit: float = Field(
        default=0.0,
        ge=0.0,
        le=10_000.0,
        description=(
            "Optional variable air-freight uplift per expedited unit ($0.25 at this repo's "
            "IATA-cited rate x 0.05 kg/unit). Defaults to 0.0, which understates Cu -- the "
            "fixed $150 consignment charge is per shipment and cannot be made per-unit."
        ),
    )


def _validate_history(values: List[float]) -> np.ndarray:
    if len(values) < MIN_HISTORY or len(values) > MAX_HISTORY:
        raise HTTPException(
            status_code=422,
            detail=f"demand_history must have between {MIN_HISTORY} and {MAX_HISTORY} observations, got {len(values)}",
        )
    arr = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(arr)):
        raise HTTPException(status_code=422, detail="demand_history contains a non-finite value")
    if np.any(arr < 0):
        raise HTTPException(status_code=422, detail="demand is a count; demand_history cannot contain a negative value")
    if np.any(arr > MAX_OBSERVATION):
        raise HTTPException(
            status_code=422, detail=f"demand_history contains an observation above {MAX_OBSERVATION}"
        )
    return arr


def _resolve_series(series_id: str, train_periods: Optional[int]) -> np.ndarray:
    try:
        names, mat = nv.load_panel()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The Monash car-parts panel is not present in this deployment, so a series "
                "cannot be resolved. Send `demand_history` instead."
            ),
        ) from exc
    lookup = {n: i for i, n in enumerate(names)}
    if series_id not in lookup:
        raise HTTPException(
            status_code=404,
            detail=f"unknown series {series_id!r}; the panel holds {len(names)} series named T1..T{len(names)}",
        )
    row = np.asarray(mat[lookup[series_id]], dtype=float)
    if train_periods is not None:
        if train_periods > row.size:
            raise HTTPException(
                status_code=422,
                detail=f"train_periods={train_periods} exceeds the {row.size}-month series {series_id!r}",
            )
        row = row[:train_periods]
    return row


def _costs_or_422(req: DecisionRequest) -> nv.NewsvendorCosts:
    try:
        return nv.newsvendor_costs(
            unit_price_usd=req.unit_price_usd,
            review_period_months=float(req.review_period_months),
            shortage_mode=req.shortage_mode,
            expedite_freight_usd_per_unit=req.expedite_freight_usd_per_unit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assumptions")
def get_assumptions(
    unit_price_usd: float = Query(1.0, gt=0.0, le=1_000_000.0),
    review_period_months: int = Query(1, ge=1, le=MAX_REVIEW_PERIOD_MONTHS),
    shortage_mode: str = Query("expedite"),
    expedite_freight_usd_per_unit: float = Query(0.0, ge=0.0, le=10_000.0),
) -> Dict[str, Any]:
    """The cost asymmetry behind every order quantity this API returns.

    Published separately and first because it is the weakest link: the fractile is a
    monotone function of Cu/Co, and both are cited industry averages rather than a
    measurement of any part in this catalogue. A reader who disagrees with 0.15 or 0.25
    should be able to see exactly what changes, which is what the query parameters are for.
    """
    try:
        costs = nv.newsvendor_costs(
            unit_price_usd=unit_price_usd,
            review_period_months=float(review_period_months),
            shortage_mode=shortage_mode,
            expedite_freight_usd_per_unit=expedite_freight_usd_per_unit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "critical_fractile": costs.as_dict(),
        "inputs": {
            "holding_rate_annual": {
                "value": nv.ANNUAL_HOLDING_RATE,
                "source": "Gartner IT Supply Chain Benchmarks 2022 -- electronics annual holding "
                          "cost (capital + obsolescence + warehousing + insurance)",
                "used_via": "app.optimization.costs.holding_cost_usd, the same function the "
                            "freight/holding cost model calls, so the two cannot drift",
            },
            "expedite_premium": {
                "value": nv.EXPEDITE_PREMIUM,
                "source": "the emergency-reprocurement premium already used by "
                          "app/optimization/sourcing.py and app/graph/simulation.py",
                "justification": "A spare part that is out of stock is not a lost sale. The "
                                 "demand does not evaporate; the unit is re-procured on an "
                                 "emergency footing. The cost of the shortage is therefore the "
                                 "PREMIUM paid to recover it, not the margin on it -- which is "
                                 "why Cu is a fraction of unit price, not a multiple of it.",
            },
            "stockout_escalation_multiple": {
                "value": nv.STOCKOUT_ESCALATION_MULTIPLE,
                "source": "Snyder & Daskin (2005), Reliable Facility Location Models, "
                          "Transportation Science 39(3):400-416 -- via "
                          "app/optimization/sourcing.py::STOCKOUT_PENALTY_MULTIPLE",
                "applies_when": "shortage_mode='line_down': a single-sourced part with no "
                                "substitutable offer, where the recourse is a line-down or "
                                "respin event rather than an expedite.",
            },
            "excluded_fixed_expedite_charge": {
                "value": 150.0,
                "source": "app/optimization/constants.py::AIR_FREIGHT_BASE_USD (DHL/FedEx "
                          "commercial minimum consignment handling charge)",
                "why_excluded": "It is per CONSIGNMENT, not per unit, so it cannot enter a "
                                "linear per-unit Cu without an assumption about how many short "
                                "units share a shipment. Excluding it pushes Cu down, tau down "
                                "and q* down: the published order quantities understock relative "
                                "to the true asymmetry, and the measured saving is a lower bound.",
            },
        },
        "derivation": {
            "formula": "q* = F^-1(Cu / (Cu + Co)); for integer demand, min{q : F(q) >= tau}",
            "why": "C(q) = Cu E[(D-q)+] + Co E[(q-D)+] is convex with first difference "
                   "(Cu + Co) F(q) - Cu, which first turns non-negative exactly at that q.",
            "price_invariance": "Cu and Co are both proportional to unit price, so tau does not "
                                "depend on it. That is what makes this computable on a real "
                                "demand panel that carries no prices, with nothing fabricated.",
            "dual_identity": "realized cost at q equals (Cu + Co) x pinball_loss(q, y, tau) "
                             "exactly -- so the scaled pinball loss already on "
                             "GET /demand/benchmark is this decision cost up to a constant.",
        },
        "caveats": [
            "These are INDUSTRY AVERAGES, not measurements of any part in this catalogue. "
            "0.25/yr is an electronics-sector holding rate and 0.15 is a generic expedite "
            "premium; neither was estimated from this repo's data, and neither could be.",
            "THIS IS A CARRYING-CHARGE NEWSVENDOR, NOT A PERISHABLE ONE. Unsold stock carries "
            "forward, so Co is one period of carrying charge (~2% of unit price per month), not "
            "a write-off of the whole unit. That single choice is what makes tau 0.88 rather "
            "than 0.13. If the part genuinely perishes or obsoletes inside the period, raise "
            "holding_rate_annual or lengthen review_period_months and re-read tau.",
        ],
    }


@router.post("/decision")
def post_decision(req: DecisionRequest) -> Dict[str, Any]:
    """How much to order, the fractile behind it, and what the naive rules would have done.

    Closed form: one smoothing pass over the history, one inverse-cdf lookup. There is no
    solver here and no approximation -- for an integer-valued demand the critical fractile
    IS the exact minimiser of expected cost, not a relaxation of it.
    """
    if (req.demand_history is None) == (req.series is None):
        raise HTTPException(
            status_code=422,
            detail="send exactly one of `demand_history` or `series` -- not both, not neither",
        )
    if req.method not in nv.DIST_BUILDERS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown method {req.method!r}; expected one of {sorted(nv.DIST_BUILDERS)}",
        )

    if req.series is not None:
        train = _resolve_series(req.series, req.train_periods)
        origin = {"kind": "panel_series", "series": req.series, "n_periods": int(train.size)}
    else:
        train = _validate_history(list(req.demand_history or []))
        origin = {"kind": "caller_history", "series": None, "n_periods": int(train.size)}

    costs = _costs_or_422(req)

    try:
        monthly_pmf, source = nv.predictive_distribution(train, method=req.method)
    except nv.PredictiveLawError as exc:
        # 422, not 500: the input window is what triggers the upstream numerical defect,
        # and the caller can act on it (different window, different method). Failing loudly
        # is the point -- the alternative is an order quantity 30x too large.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pmf = nv.aggregate_pmf(monthly_pmf, req.review_period_months) if req.review_period_months > 1 else monthly_pmf
    decision = nv.decide_from_pmf(pmf, costs, method=req.method, distribution_source=source)

    mean, sd = nv.pmf_moments(pmf)
    quantiles = {
        f"q{int(round(level * 100)):02d}": nv.order_quantity_from_pmf(pmf, level)
        for level in DEFAULT_QUANTILE_LEVELS
    }

    payload = decision.as_dict()
    payload["input"] = {
        **origin,
        "method": req.method,
        "review_period_months": req.review_period_months,
        "unit_price_usd": req.unit_price_usd,
        "shortage_mode": req.shortage_mode,
        "observed_mean_per_month": round(float(np.mean(train)), 6),
        "observed_nonzero_fraction": round(float(np.mean(np.asarray(train) > 0)), 6),
    }
    payload["demand_distribution"] = {
        "family": "compound Bernoulli(p) x zero-truncated NegBin(mean z)"
        if source == "parametric"
        else ("in-sample empirical distribution" if source == "empirical" else "degenerate point mass"),
        "source": source,
        "driving_model": "app/ml/intermittent.py demand predictive distribution -- the same "
                         "law GET /demand/benchmark scores under CRPS and pinball loss. NOT the "
                         "lead-time model, and NOT a per-part forecast for this catalogue.",
        "periods_aggregated": req.review_period_months,
        "mean": round(mean, 6),
        "sd": round(sd, 6),
        "p_zero": round(float(np.asarray(pmf, dtype=float)[0] / float(np.sum(pmf))), 6),
        "support_max": int(np.asarray(pmf).size - 1),
        "quantiles": quantiles,
    }
    return payload


@lru_cache(maxsize=EVALUATION_CACHE_SIZE)
def _cached_evaluation(forecast_method: str, review_period_months: int, shortage_mode: str) -> Dict[str, Any]:
    started = time.perf_counter()
    result = nv.run_panel_evaluation(
        unit_price_usd=1.0,
        review_period_months=review_period_months,
        shortage_mode=shortage_mode,
        forecast_method=forecast_method,
        n_boot=EVALUATION_N_BOOT,
        seed=0,
    )
    result["wall_seconds"] = round(time.perf_counter() - started, 3)
    logger.info(
        "newsvendor evaluation: method=%s L=%d mode=%s in %.2fs",
        forecast_method, review_period_months, shortage_mode, result["wall_seconds"],
    )
    return result


@router.get("/evaluation")
def get_evaluation(
    forecast_method: str = Query(nv.DEFAULT_METHOD, description="Which predictive distribution the policy runs on."),
    review_period_months: int = Query(1, ge=1, le=MAX_REVIEW_PERIOD_MONTHS),
    shortage_mode: str = Query("expedite"),
) -> Dict[str, Any]:
    """The policy against every baseline on held-out demand, with paired bootstrap CIs.

    This endpoint exists because an order quantity on its own is not evidence. The house
    rule is that a policy ships only by beating a stated baseline, so the comparison ships
    with it: expected cost against six naive rules on 2,643 held-out series at three
    rolling origins, paired by series, with a 95% bootstrap CI and a win/tie/loss split.

    Read `ship_gate` before quoting anything. It fails closed, and it does fail -- at
    `shortage_mode=line_down` the margin over the toughest baseline stops being
    significant, which is the honest report on a fractile the data cannot resolve.

    NO UNIT PRICE PARAMETER, deliberately: the fractile does not depend on price and every
    dollar figure scales linearly in it, so the figures below are per $1.00 of unit price.
    Multiply. It also means the cacheable parameter space is finite, which is what keeps a
    4-second computation from being a denial-of-service surface.
    """
    if forecast_method not in nv.DIST_BUILDERS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown forecast_method {forecast_method!r}; expected one of {sorted(nv.DIST_BUILDERS)}",
        )
    if shortage_mode not in nv.SHORTAGE_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown shortage_mode {shortage_mode!r}; expected one of {sorted(nv.SHORTAGE_MODES)}",
        )
    try:
        result = dict(_cached_evaluation(forecast_method, review_period_months, shortage_mode))
    except FileNotFoundError as exc:
        # 503, not an empty body: "the panel is not deployed here" and "no policy beats its
        # baselines" are different claims and must not be able to look alike.
        raise HTTPException(
            status_code=503,
            detail=(
                "The Monash car-parts panel is not present in this deployment, so the "
                "newsvendor policy cannot be evaluated. It is committed at "
                "backend/seeds/data/car_parts_monthly.npz."
            ),
        ) from exc

    result["units"] = {
        "cost": "USD per SKU per review period, at a unit price of $1.00 -- multiply by your "
                "part's unit price",
        "order_quantity": "units, integer",
        "mean_difference": "USD per SKU per review period; POSITIVE means the newsvendor "
                           "policy is cheaper than that baseline",
    }
    result["reproduce"] = (
        "python -c \"from app.optimization.newsvendor import run_panel_evaluation as r; "
        f"print(r(forecast_method='{forecast_method}', review_period_months={review_period_months}, "
        f"shortage_mode='{shortage_mode}'))\""
    )
    return result
