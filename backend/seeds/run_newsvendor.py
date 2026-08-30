"""
The newsvendor headline is the only evaluation-backed result in this repo with no artifact.

MOTIVATION. `docs/RESEARCH_TECHNIQUES.md` Section 3.4 publishes real measured numbers --
beats every stocking baseline across 47,574-ish held-out decisions, ~4% against the toughest
(Scarf min-max) with a paired bootstrap CI excluding zero, and the headline finding that
`zero` wins MASE on this panel while being the WORST policy on decision cost. Every one of
those figures is real: `app.optimization.newsvendor.run_panel_evaluation` computes them from
the committed Monash car-parts panel. But nothing regenerates them and nothing checks that
the doc still says what the code says. `backend/tests/test_docs_match_artifacts.py`
enumerates the docs it guards and explicitly excludes `RESEARCH_TECHNIQUES.md` -- this is the
one published artifact in the repo that ships with a reproduce command in an HTML comment
instead of a generator and a doc-match test. Every sibling technique
(CVaR frontier, diversification sweep, leakage progression, intermittent-demand benchmark)
has both. This script is the newsvendor's.

WHAT THIS SCRIPT DOES AND DOES NOT DO. It calls `run_panel_evaluation` -- unmodified, already
shipped, already tested by `backend/tests/test_newsvendor.py` -- five times, at the five
configurations Section 3.4 actually quotes, and then once more for every OTHER configuration
`GET /newsvendor/evaluation` can be asked for (see the grid section below), and writes the
results plus a provenance block to `docs/newsvendor.json`. It does not change the
evaluation, the ship gate, or the cost model.
It does not touch the database (`run_panel_evaluation` only reads the committed
`seeds/data/car_parts_monthly.npz`) and it does not write anywhere under `seeds/data/`.

THE FIVE CONFIGURATIONS, each a direct read of a claim in Section 3.4:

  primary                    tsb / expedite / L=1 review period -- the headline table and the
                              method leaderboard (`zero` wins MASE, loses on decision cost).
  sensitivity_line_down      shortage_mode="line_down" (tau=0.993) -- the honest failure: the
                              margin over the toughest baseline stops being significant.
  sensitivity_review_period_3   L=3 -- the other honest failure: the policy LOSES to the point
                              forecast at a quarterly review period.
  sensitivity_review_period_6   L=6 -- the policy wins again, larger than at L=1. Reported
                              alongside L=3 so neither is quoted without the other.
  negative_control_permuted  `permute_forecasts_seed=17` -- the falsification check: each
                              series scored against ANOTHER series' forecast. If this run did
                              not cost more and fail the ship gate, none of the above would be
                              evidence of anything except the shape of an asymmetric cost.

All five share `n_boot=5000, seed=0` -- the same bootstrap settings
`app/api/newsvendor.py::EVALUATION_N_BOOT` serves, so a reader comparing this artifact to a
live `GET /newsvendor/evaluation` call at the same parameters sees the same numbers up to
Monte Carlo noise in nothing (the bootstrap itself is seeded).

WHY THE NUMBERS MAY NOT MATCH AN OLDER COPY OF SECTION 3.4. `app/ml/intermittent.py`'s
`_size_shape` had a numerical defect -- overdispersion by a few parts in 1e16 sent the
negative-binomial shape parameter to ~1e16 instead of the Poisson limit, breaking this
module's `E[pmf] == point forecast` invariant on 3 of 8,022 (series, origin) pairs, which
`newsvendor.predictive_distribution` correctly refused and `run_panel_evaluation` dropped
from the panel (`n_series_dropped_pmf_invariant`). That defect was fixed in
`app/ml/intermittent.py::_size_shape` (commit 92f1e71, the same commit that shipped this
newsvendor layer) by guarding the Poisson limit numerically rather than only exactly. This
generator runs against that fixed code, so it scores 2,646 series with **zero** dropped by
the invariant, not the 2,643 an earlier draft of Section 3.4 described -- the fix landed
after that paragraph was written and the prose was never re-run against it. This is exactly
the silent-rot failure mode this script exists to close: see
`backend/tests/test_newsvendor_docs_match_artifact.py`, which reads this artifact rather
than trusting the prose.

AND THEN THE WHOLE REACHABLE GRID, under the `grid` key. The five runs above are the five
CLAIMS. They are not the five configurations a visitor can reach: `GET
/newsvendor/evaluation` takes `forecast_method` x `review_period_months` x `shortage_mode`,
and anything the artifact does not publish is evaluated on the spot -- 106.6 s measured on
the deployed 0.5-CPU single-worker instance, during which that worker serves nothing else.
Publishing only the five named runs left every other cell of the grid as a
denial-of-service surface reachable by changing a dropdown and pressing Solve. So
`build_grid` runs `run_panel_evaluation` once per remaining cell, at the same `n_boot` and
`seed`, and the endpoint serves all of them.

THE GRID IS 6 x 6 x 2 = 72, NOT 6 x 12 x 2 = 144. `MAX_REVIEW_PERIOD_MONTHS` in
`app/api/newsvendor.py` used to be 12, but `run_panel_evaluation` splits the 6-month
held-out horizon into floor(horizon / L) non-overlapping blocks and raises `ValueError`
when that is zero, so L in 7..12 never produced an evaluation -- it produced an unhandled
500. Those 72 cells are not published here because they do not exist; the endpoint now
bounds the query at `PANEL_HORIZON` and answers 422.

RUNTIME. Approximately 4 minutes on a single core (~3.4 s/run x 5 named runs + 68 grid
runs; the panel is 2,674 series x 3 rolling origins x 6 forecast methods, and each run
repeats that full pass because each is a different cost/tau, a different aggregation or a
different pairing). This is NOT re-run by `test_newsvendor_docs_match_artifact.py`; that
test reads the committed `docs/newsvendor.json`.

Invocation: `cd backend && ./venv/bin/python -m seeds.run_newsvendor`
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.optimization.newsvendor import (  # noqa: E402
    DIST_BUILDERS,
    PANEL_HORIZON,
    PANEL_PATH,
    SHORTAGE_MODES,
    run_panel_evaluation,
)
from seeds.provenance import build_provenance  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
JSON_PATH = DOCS / "newsvendor.json"

#: Matches `app/api/newsvendor.py::EVALUATION_N_BOOT` so the committed artifact and a live
#: call to `GET /newsvendor/evaluation` at the same parameters are the same computation.
N_BOOT = 5000
SEED = 0

#: The pairing-destruction seed for the negative control. Not tuned to produce a particular
#: number -- it is the same seed `tests/test_newsvendor.py::test_the_permutation_control_
#: destroys_the_advantage` uses, chosen once and kept fixed so this is a single reproducible
#: falsification check rather than a seed search.
PERMUTATION_SEED = 17

#: Default protocol for every run below: the demand leaderboard's own forecast method,
#: one-month review period, the expedite (not line_down) shortage cost. Each configuration
#: varies exactly one of these from Section 3.4's own sensitivity sweep.
DEFAULT_METHOD = "tsb"


#: The longest review period `GET /newsvendor/evaluation` can be asked for. This is NOT a
#: taste: `run_panel_evaluation` splits the 6-month held-out horizon into
#: floor(horizon / L) non-overlapping blocks and raises `ValueError` the moment that is
#: zero, so L > PANEL_HORIZON is not a slow configuration, it is not a configuration at
#: all. `app/api/newsvendor.py::EVALUATION_MAX_REVIEW_PERIOD_MONTHS` derives its query
#: bound from the same constant; the two must agree or the endpoint advertises
#: configurations this generator does not publish.
MAX_REVIEW_PERIOD_MONTHS = PANEL_HORIZON

#: Top-level key holding the exhaustive sweep. Kept SEPARATE from the five named runs
#: above so this file stays readable as "the five claims Section 3.4 makes, then the rest
#: of the space", and so `test_newsvendor_docs_match_artifact.py` keeps reading the named
#: blocks by name.
GRID_KEY = "grid"


def _grid_name(forecast_method: str, review_period_months: int, shortage_mode: str) -> str:
    """The grid's key for one configuration. Derived from the configuration itself."""
    return f"{forecast_method}_L{review_period_months}_{shortage_mode}"


def _servable_config(block: Dict[str, Any]) -> Optional[Tuple[str, int, str]]:
    """The (method, L, mode) a block answers for, or None if no request can ask for it.

    Read off the block's OWN fields, exactly as `app/api/newsvendor.py::_artifact_index`
    reads them, so "which configurations are already published" is derived from the same
    place on both sides instead of being asserted twice and drifting once.
    """
    protocol = block["protocol"]
    if protocol.get("permutation_control"):
        return None  # scored against another series' forecast; unreachable by any request
    return (
        protocol["forecast_method"],
        protocol["review_period_months"],
        block["costs"]["shortage_mode"],
    )


def build_grid(already_published: Set[Tuple[str, int, str]]) -> Dict[str, Dict[str, Any]]:
    """Every remaining configuration the endpoint can be asked for, really evaluated.

    Enumerates `DIST_BUILDERS x 1..MAX_REVIEW_PERIOD_MONTHS x SHORTAGE_MODES` and runs
    `run_panel_evaluation` once per cell, at the same `n_boot` and `seed` as the five named
    runs. The cells `already_published` under a name above are SKIPPED rather than
    duplicated: two blocks claiming one configuration make the endpoint's index refuse to
    serve either (that is the deliberate coin-flip guard), so a duplicate here would
    silently un-optimise the four configurations that matter most.
    """
    grid: Dict[str, Dict[str, Any]] = {}
    for method in sorted(DIST_BUILDERS):
        for review in range(1, MAX_REVIEW_PERIOD_MONTHS + 1):
            for mode in sorted(SHORTAGE_MODES):
                if (method, review, mode) in already_published:
                    continue
                name = _grid_name(method, review, mode)
                grid[name] = _run(
                    f"{GRID_KEY}.{name}",
                    forecast_method=method,
                    review_period_months=review,
                    shortage_mode=mode,
                )
    return grid


def _run(label: str, **kwargs: Any) -> Dict[str, Any]:
    t0 = time.perf_counter()
    result = run_panel_evaluation(n_boot=N_BOOT, seed=SEED, **kwargs)
    wall = time.perf_counter() - t0
    logger.info(
        "%s: n=%d cost=%.6f ship_gate=%s (%.2fs)",
        label,
        result["panel"]["n_series_scored"],
        result["policies"]["newsvendor_fractile"]["mean_cost_usd_per_sku_period"],
        result["ship_gate"]["passed"],
        wall,
    )
    result["wall_seconds"] = round(wall, 3)
    return result


def build_payload() -> Dict[str, Any]:
    t0 = time.perf_counter()

    primary = _run("primary")
    sensitivity_line_down = _run("sensitivity_line_down", shortage_mode="line_down")
    sensitivity_review_period_3 = _run("sensitivity_review_period_3", review_period_months=3)
    sensitivity_review_period_6 = _run("sensitivity_review_period_6", review_period_months=6)
    negative_control_permuted = _run(
        "negative_control_permuted", permute_forecasts_seed=PERMUTATION_SEED
    )

    named = {
        "primary": primary,
        "sensitivity_line_down": sensitivity_line_down,
        "sensitivity_review_period_3": sensitivity_review_period_3,
        "sensitivity_review_period_6": sensitivity_review_period_6,
        "negative_control_permuted": negative_control_permuted,
    }
    already_published = {
        cfg for cfg in (_servable_config(b) for b in named.values()) if cfg is not None
    }
    grid = build_grid(already_published)

    elapsed = time.perf_counter() - t0
    prov = build_provenance(
        generator="seeds.run_newsvendor",
        inputs={"car_parts_panel": PANEL_PATH},
        extra={"n_boot": N_BOOT, "bootstrap_seed": SEED, "permutation_seed": PERMUTATION_SEED},
    )

    return {
        "provenance": prov,
        "meta": {
            "generator": "seeds.run_newsvendor",
            "default_forecast_method": DEFAULT_METHOD,
            "n_boot": N_BOOT,
            "bootstrap_seed": SEED,
            "permutation_seed": PERMUTATION_SEED,
            "wall_seconds": round(elapsed, 1),
            "writes_to_database": False,
            "reads": "backend/seeds/data/car_parts_monthly.npz (committed, read-only)",
            "evaluation_grid": {
                "forecast_methods": sorted(DIST_BUILDERS),
                "review_period_months": list(range(1, MAX_REVIEW_PERIOD_MONTHS + 1)),
                "shortage_modes": sorted(SHORTAGE_MODES),
                "n_configurations": len(DIST_BUILDERS)
                * MAX_REVIEW_PERIOD_MONTHS
                * len(SHORTAGE_MODES),
                "n_published_under_a_name": len(already_published),
                "n_in_grid": len(grid),
                "why": (
                    "Every configuration GET /newsvendor/evaluation can be asked for is "
                    "published here, so no request recomputes the panel on the deployed "
                    "0.5-CPU worker. review_period_months stops at PANEL_HORIZON because "
                    "run_panel_evaluation splits the held-out horizon into "
                    "floor(horizon / L) blocks and refuses L > horizon -- past that there "
                    "is no evaluation to publish, and the endpoint answers 422."
                ),
            },
        },
        **named,
        GRID_KEY: grid,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = build_payload()
    DOCS.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    logger.info(
        "wrote %s (%.2f MB, %d grid configurations)",
        JSON_PATH.relative_to(REPO_ROOT),
        JSON_PATH.stat().st_size / 1e6,
        len(payload[GRID_KEY]),
    )
    # Ship gate for the record, not a hard failure: the whole point of publishing the
    # line_down and permutation runs is that they FAIL the gate, on purpose.
    logger.info(
        "gates: primary=%s line_down=%s L3=%s L6=%s permutation=%s",
        payload["primary"]["ship_gate"]["passed"],
        payload["sensitivity_line_down"]["ship_gate"]["passed"],
        payload["sensitivity_review_period_3"]["ship_gate"]["passed"],
        payload["sensitivity_review_period_6"]["ship_gate"]["passed"],
        payload["negative_control_permuted"]["ship_gate"]["passed"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
