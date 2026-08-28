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
configurations Section 3.4 actually quotes, and writes the results plus a provenance block to
`docs/newsvendor.json`. It does not change the evaluation, the ship gate, or the cost model.
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

RUNTIME. Approximately 17 seconds on a single core (~3.3 s/run x 5 configurations; the panel
is 2,674 series x 3 rolling origins x 6 forecast methods, and each run repeats that full pass
because each is a different cost/tau or a different pairing). This is NOT re-run by
`test_newsvendor_docs_match_artifact.py`; that test reads the committed
`docs/newsvendor.json`.

Invocation: `cd backend && ./venv/bin/python -m seeds.run_newsvendor`
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.optimization.newsvendor import PANEL_PATH, run_panel_evaluation  # noqa: E402
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
        },
        "primary": primary,
        "sensitivity_line_down": sensitivity_line_down,
        "sensitivity_review_period_3": sensitivity_review_period_3,
        "sensitivity_review_period_6": sensitivity_review_period_6,
        "negative_control_permuted": negative_control_permuted,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    payload = build_payload()
    DOCS.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("wrote %s", JSON_PATH.relative_to(REPO_ROOT))
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
