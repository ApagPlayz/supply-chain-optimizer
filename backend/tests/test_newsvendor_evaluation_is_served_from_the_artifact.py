"""`GET /newsvendor/evaluation` must answer fast, and answer with the SAME numbers.

WHY THIS FILE EXISTS
---------------------
Measured against the live API on 2026-08-30, this endpoint reported `wall_seconds:
259.897` on a cold container and `106.589` on a warm one with a cold cache. `render.yaml`
starts ONE uvicorn worker on a 0.5-CPU free instance, so those are not "a slow endpoint" --
for the whole of that window the API is doing nothing else, and abandoning the request does
not stop the computation. The source comment claimed "~4 s", which is true on an
Apple-silicon laptop and was never true in production.

The first fix served `docs/newsvendor.json` for the FOUR configurations
`seeds.run_newsvendor` published under a name. That left the other sixty-eight recomputing
at ~107 s each, reachable by changing a dropdown on the newsvendor page and pressing the
button -- so an ordinary click still stalled the whole API. The fix this file now guards is
the exhaustive one: `seeds.run_newsvendor` publishes EVERY configuration the endpoint can be
asked for, and the endpoint serves all of them.

WHAT "EVERY CONFIGURATION" MEANS, AND WHY IT IS 72 AND NOT 144
---------------------------------------------------------------
6 forecast methods x 2 shortage modes x review periods 1..6. Not 1..12: `run_panel_evaluation`
splits the 6-month held-out horizon into floor(horizon / L) non-overlapping blocks and raises
`ValueError` when that is zero, so review periods 7..12 never produced an evaluation -- they
produced an unhandled traceback and an HTTP 500, on values the query bound advertised as
valid. `test_a_review_period_past_the_horizon_is_a_422_and_not_a_500` is that regression.

WHAT THIS FILE ASSERTS, AND WHY EACH HALF IS WORTHLESS ALONE
-------------------------------------------------------------
  * `test_every_reachable_configuration_is_served_from_the_artifact` walks the whole space
    through the real endpoint and fails if ANY of it recomputes. This is the denial-of-service
    surface itself, stated as a test.
  * `test_the_served_response_equals_the_full_computation` re-runs `run_panel_evaluation` the
    slow way and compares every leaf exactly -- `==`, not `approx`. It is the reason the fast
    path is allowed to exist. It also pins the DERIVED mapping: if the artifact index ever
    matched a request to the wrong block, this would compare a real evaluation of one
    configuration against a real evaluation of another and go red. No schema check can catch
    that. It runs on a deterministic SAMPLE (every named block plus three grid blocks spread
    across the sweep) because 72 recomputations is four minutes; `SLOW_NEWSVENDOR_SAMPLE=all`
    in the environment recomputes the entire grid.
  * `test_the_published_evaluation_answers_within_a_latency_bound` fails if the fast path
    silently stops applying. The bound sits between two measurements taken on the machine
    this was written on: serving the artifact takes ~0.02 s, recomputing takes ~3.4 s. A
    bound loose enough to survive a recomputation would be a check that cannot fail.

The identity guards are tested one at a time below, because "the endpoint got fast" and
"the endpoint got fast by serving whatever JSON happened to be on disk" are different
outcomes and must not be able to look alike. Every guard drops the artifact and falls back
to recomputing: slow is a bug, stale is a lie, and the fallback direction is the safe one.
`test_the_recompute_fallback_still_answers_when_the_artifact_publishes_nothing` proves that
fallback still works, because a guard that fails over to a broken path is not a guard.
"""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.api import newsvendor as nv_api
from app.optimization import newsvendor as nv

PANEL = Path(__file__).resolve().parents[1] / "seeds" / "data" / "car_parts_monthly.npz"
ARTIFACT = Path(__file__).resolve().parents[2] / "docs" / "newsvendor.json"

needs_panel = pytest.mark.skipif(not PANEL.is_file(), reason="Monash car-parts panel absent")
needs_artifact = pytest.mark.skipif(not ARTIFACT.is_file(), reason="docs/newsvendor.json absent")

EVALUATION = "/api/v1/newsvendor/evaluation"

#: Keys the endpoint ADDS to the block. They describe the request, not the evaluation, so
#: they are the only things allowed to differ from `run_panel_evaluation`'s output.
ADDED_BY_THE_ENDPOINT = frozenset({"computation", "units", "reproduce"})

#: `wall_seconds` is a timing, not a result. `test_artifacts_pinned_to_code.py` skips it for
#: the same reason.
NOT_A_RESULT = frozenset({"wall_seconds"})

#: The bound the fast path must beat, in seconds. Deliberately BELOW the cost of a single
#: recomputation on the machine this was written on (3.3-3.8 s measured, and far more on a
#: shared CI runner or the 0.5-CPU deployed instance), and roughly 100x ABOVE the cost of
#: reading, parsing and deep-copying the artifact (~0.02 s). If this endpoint ever
#: recomputes the default configuration again, this fails everywhere.
LATENCY_BUDGET_SECONDS = 2.0


def _reachable_configs() -> List[Tuple[str, int, str]]:
    """Every (method, L, mode) a caller can ask this endpoint for.

    Enumerated from the SAME constants the endpoint validates against, so a method or a
    shortage mode added to `app/optimization/newsvendor.py` lands in this list on its own
    and this file goes red until `seeds.run_newsvendor` publishes it. A hard-coded list of
    72 tuples would quietly stop covering the space the day the space changed.
    """
    return [
        (method, review, mode)
        for method, review, mode in itertools.product(
            sorted(nv.DIST_BUILDERS),
            range(1, nv_api.EVALUATION_MAX_REVIEW_PERIOD_MONTHS + 1),
            sorted(nv.SHORTAGE_MODES),
        )
    ]


def _params(cfg: Tuple[str, int, str]) -> Dict[str, Any]:
    return {"forecast_method": cfg[0], "review_period_months": cfg[1], "shortage_mode": cfg[2]}


def _config_of(block: Dict[str, Any]) -> Tuple[str, int, str]:
    """The request that produces this artifact block, read off the block itself."""
    return (
        block["protocol"]["forecast_method"],
        block["protocol"]["review_period_months"],
        block["costs"]["shortage_mode"],
    )


def _index() -> Dict[Tuple[str, int, str], Dict[str, Any]]:
    nv_api._artifact_index.cache_clear()
    return nv_api._artifact_index(ARTIFACT.stat().st_mtime, str(ARTIFACT))


def _served_configs() -> List[Dict[str, Any]]:
    """Every (method, L, mode) the endpoint currently answers from the artifact.

    Read off the endpoint's OWN derived index rather than off the raw blocks, because the
    two are not the same list and the difference is the point: `negative_control_permuted`
    carries the same (tsb, 1, expedite) configuration as `primary` and is deliberately
    excluded, so walking the raw file would claim a block is served that never is.
    """
    return [
        {"block_name": entry["block_name"], **dict(zip(
            ("forecast_method", "review_period_months", "shortage_mode"),
            _config_of(entry["block"]),
            strict=True,
        ))}
        for entry in _index().values()
        if entry
    ]


def _equality_sample() -> List[Dict[str, Any]]:
    """Which served configurations get recomputed the slow way.

    Every block published under a NAME -- those are the four Section 3.4 quotes and the ones
    `RESEARCH_TECHNIQUES.md` reads -- plus three from the grid, taken at the ends and the
    middle of the sorted sweep so the sample spans forecast methods, review periods and both
    shortage modes rather than clustering. Deterministic on purpose: a random sample would
    make a red run unreproducible.

    `SLOW_NEWSVENDOR_SAMPLE=all` recomputes the entire grid (~4 minutes).
    """
    served = _served_configs()
    named = [c for c in served if not c["block_name"].startswith("grid.")]
    grid = sorted((c for c in served if c["block_name"].startswith("grid.")),
                  key=lambda c: c["block_name"])
    if os.environ.get("SLOW_NEWSVENDOR_SAMPLE") == "all":
        return named + grid
    if not grid:
        return named
    picks = sorted({0, len(grid) // 2, len(grid) - 1})
    return named + [grid[i] for i in picks]


def _diff(actual: Any, expected: Any, path: str = "") -> List[str]:
    """Every leaf on which two nested payloads disagree. Exact equality, no tolerance."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        out: List[str] = []
        for key in sorted(set(actual) | set(expected)):
            if key in NOT_A_RESULT or key in ADDED_BY_THE_ENDPOINT:
                continue
            if key not in actual:
                out.append(f"{path}.{key}: served response is MISSING it")
            elif key not in expected:
                out.append(f"{path}.{key}: served response INVENTED it")
            else:
                out += _diff(actual[key], expected[key], f"{path}.{key}")
        return out
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return [f"{path}: length {len(actual)} served vs {len(expected)} computed"]
        out = []
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            out += _diff(a, e, f"{path}[{i}]")
        return out
    return [] if actual == expected else [f"{path}: served {actual!r} != computed {expected!r}"]


# ── 1. The defect this was opened for: the WHOLE space, not four of it ────────

@needs_panel
@needs_artifact
def test_every_reachable_configuration_is_served_from_the_artifact(client):
    """Not one request may recompute the panel. This is the DoS surface, as a test.

    Every cell of `methods x review periods x shortage modes` goes through the real
    endpoint. A cell that is missing from the artifact does not fail loudly -- it answers
    200 with `recomputed: true`, after ~107 s on the deployed instance -- so the assertion
    is on `computation.recomputed`, not on the status code.
    """
    configs = _reachable_configs()
    assert len(configs) == 72, f"the reachable space changed shape: {len(configs)} configurations"

    recomputed: List[Tuple[str, int, str]] = []
    for cfg in configs:
        resp = client.get(EVALUATION, params=_params(cfg))
        assert resp.status_code == 200, f"{cfg}: {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        if body["computation"]["recomputed"] is not False:
            recomputed.append(cfg)
            continue
        # Served the block for the configuration that was ASKED FOR, not a neighbour's.
        assert _config_of(body) == cfg, (
            f"asked for {cfg} and was served the evaluation of {_config_of(body)} -- the "
            f"artifact index is matching requests to the wrong block"
        )
        assert body["computation"]["source"].startswith("docs/newsvendor.json ::")

    assert not recomputed, (
        f"{len(recomputed)} of {len(configs)} reachable configurations still recompute the "
        f"panel on request, at ~107 s of the deployed instance's only worker each. "
        f"Regenerate with `cd backend && ./venv/bin/python -m seeds.run_newsvendor`. "
        f"Missing: {recomputed[:10]}"
    )


@needs_artifact
def test_the_grid_and_the_named_runs_never_claim_one_configuration_twice(client):
    """A duplicate is not a harmless duplicate -- the index refuses to serve EITHER block.

    So a grid entry that repeated `primary` would not corrupt a number; it would silently
    hand the four most-read configurations back to the 107-second path. That failure is
    invisible in the response body, which is why it is asserted on the index directly.
    """
    index = _index()
    conflicted = sorted(k for k, v in index.items() if not v)
    assert not conflicted, (
        f"docs/newsvendor.json publishes two blocks for {conflicted} -- neither is served "
        f"and every request for them recomputes"
    )


# ── 2. The reason the fast path is allowed to exist ───────────────────────────

@needs_panel
@needs_artifact
def test_the_served_response_equals_the_full_computation(client):
    """Served configurations, recomputed the slow way, leaf by leaf.

    This is the whole licence for the optimisation. It runs the real evaluator with the
    real arguments -- no `max_series`, no reduced `n_boot`, nothing shortened -- and demands
    exact equality, because the artifact is not a rounding of the computation, it is its
    output passed through `json.dumps`/`json.loads` and back.
    """
    sample = _equality_sample()
    assert len(sample) >= 7, (
        f"the equality sample collapsed to {len(sample)} configurations -- it must cover "
        f"every named block and at least three grid blocks, or it is not evidence"
    )

    for cfg in sample:
        cfg = dict(cfg)
        block_name = cfg.pop("block_name")
        resp = client.get(EVALUATION, params=cfg)
        assert resp.status_code == 200, resp.text
        served = resp.json()
        assert served["computation"]["recomputed"] is False, (
            f"{cfg} was recomputed; this test would then be comparing the computation "
            f"against itself and could not fail"
        )
        assert served["computation"]["source"].endswith(block_name)

        computed = nv.run_panel_evaluation(
            unit_price_usd=1.0,
            review_period_months=cfg["review_period_months"],
            shortage_mode=cfg["shortage_mode"],
            forecast_method=cfg["forecast_method"],
            n_boot=nv_api.EVALUATION_N_BOOT,
            seed=nv_api.EVALUATION_SEED,
        )
        # Through JSON, exactly as the artifact went, so this compares values and not the
        # difference between a float and its own serialisation.
        computed = json.loads(json.dumps(computed))

        differences = _diff(served, computed, block_name)
        assert not differences, (
            f"{block_name} ({cfg}) is served from docs/newsvendor.json but no longer equals "
            f"what run_panel_evaluation produces. Regenerate it with "
            f"`cd backend && ./venv/bin/python -m seeds.run_newsvendor`. First differences:\n"
            + "\n".join(differences[:10])
        )


# ── 3. Latency, and the shape of what is served ───────────────────────────────

@needs_panel
@needs_artifact
def test_the_published_evaluation_answers_within_a_latency_bound(client):
    """Cold caches, default parameters -- the exact request the UI makes on mount.

    259.897 s is what this measured on the deployed instance. The endpoint runs on the only
    worker there is, so that number is not the endpoint's problem alone.
    """
    nv_api._artifact_index.cache_clear()
    nv_api._cached_evaluation.cache_clear()

    started = time.perf_counter()
    resp = client.get(EVALUATION)
    elapsed = time.perf_counter() - started

    assert resp.status_code == 200, resp.text
    # The TIMING first, deliberately. If `recomputed` were asserted first this clause would
    # never be reached on the regression it exists to catch, and a bound that is only ever
    # evaluated when the code is already known-good is not a bound.
    assert elapsed < LATENCY_BUDGET_SECONDS, (
        f"the default evaluation took {elapsed:.2f}s from a cold cache, over the "
        f"{LATENCY_BUDGET_SECONDS}s budget -- it is recomputing the panel again"
    )
    body = resp.json()
    assert body["computation"]["recomputed"] is False
    # `wall_seconds` must describe THIS request, not the artifact's generation.
    assert body["wall_seconds"] < LATENCY_BUDGET_SECONDS
    assert body["computation"]["artifact_wall_seconds"] is not None


@needs_panel
@needs_artifact
def test_a_configuration_reachable_only_from_the_grid_answers_within_the_same_bound(client):
    """The dropdown change that used to cost 107 s. Cold caches, a non-default cell."""
    nv_api._artifact_index.cache_clear()
    nv_api._cached_evaluation.cache_clear()

    started = time.perf_counter()
    resp = client.get(
        EVALUATION,
        params={"forecast_method": "sba", "review_period_months": 4, "shortage_mode": "line_down"},
    )
    elapsed = time.perf_counter() - started

    assert resp.status_code == 200, resp.text
    assert elapsed < LATENCY_BUDGET_SECONDS, (
        f"sba / L=4 / line_down took {elapsed:.2f}s from a cold cache -- it is recomputing"
    )
    body = resp.json()
    assert body["computation"]["recomputed"] is False
    assert body["computation"]["source"].startswith("docs/newsvendor.json :: grid.")
    assert _config_of(body) == ("sba", 4, "line_down")


@needs_panel
@needs_artifact
def test_the_served_payload_still_carries_everything_the_ui_reads(client):
    """A fast wrong shape is not an improvement. The block must be the full response."""
    body = client.get(EVALUATION).json()
    for key in (
        "costs", "protocol", "panel", "policies", "paired_vs_newsvendor", "baselines_beaten",
        "toughest_baseline", "paired_vs_toughest_baseline", "method_leaderboard", "caveats",
        "ship_gate", "wall_seconds", "units", "reproduce",
    ):
        assert key in body, f"the artifact fast path dropped {key!r} from the response"
    assert set(body["paired_vs_newsvendor"]) == set(nv.BASELINE_POLICIES)
    assert body["panel"]["n_series_scored"] > 2500


@needs_panel
@needs_artifact
def test_a_grid_block_carries_the_same_payload_shape_as_a_named_one(client):
    """The grid is 68 blocks nobody hand-inspected. They must not be thinner."""
    named = client.get(EVALUATION).json()
    grid = client.get(
        EVALUATION, params={"forecast_method": "croston", "review_period_months": 5}
    ).json()
    assert grid["computation"]["source"].startswith("docs/newsvendor.json :: grid.")
    missing = sorted(set(named) - set(grid))
    assert not missing, f"the grid block is missing {missing} that a named block carries"
    assert set(grid["paired_vs_newsvendor"]) == set(nv.BASELINE_POLICIES)
    assert set(grid["method_leaderboard"]) == set(named["method_leaderboard"])
    assert set(grid["method_leaderboard"]["decision_cost_usd_per_sku_period"]) == set(nv.DIST_BUILDERS)
    assert set(grid["ship_gate"]) == set(named["ship_gate"])
    # Not the same COUNT: an L>1 block correctly carries an extra caveat about aggregating
    # the monthly law by convolution. What must hold is that the standing disclosures survive.
    assert set(named["caveats"]) <= set(grid["caveats"])
    assert any("STAND-IN" in c for c in grid["caveats"])


@needs_panel
@needs_artifact
def test_the_response_says_where_its_numbers_came_from(client):
    """Serving a precomputed number without saying so is the overclaim, not the speed."""
    comp = client.get(EVALUATION).json()["computation"]
    assert comp["recomputed"] is False
    assert comp["source"].startswith("docs/newsvendor.json")
    assert comp["artifact_generated_at_utc"]
    assert comp["artifact_git_commit"]
    assert "run_panel_evaluation" in comp["equality_guarantee"]
    assert "259.897" in comp["why"], "the measurement that motivated this must stay quotable"


# ── 4. The horizon: a 422 about the request, never a 500 about the server ─────

@needs_panel
@pytest.mark.parametrize("review_period", [7, 9, 12])
def test_a_review_period_past_the_horizon_is_a_422_and_not_a_500(client, review_period):
    """`MAX_REVIEW_PERIOD_MONTHS = 12` advertised six configurations per method that
    `run_panel_evaluation` refuses outright: it splits the 6-month held-out horizon into
    floor(horizon / L) blocks and raises when that is zero. The UI offered "12 months" in
    its dropdown, so this was a plain HTTP 500 one click away on the live site.
    """
    resp = client.get(EVALUATION, params={"review_period_months": review_period})
    assert resp.status_code == 422, (
        f"review_period_months={review_period} returned {resp.status_code}; the horizon is "
        f"{nv.PANEL_HORIZON} months and there is no evaluation to return past it"
    )


@needs_panel
def test_the_longest_review_period_the_endpoint_advertises_actually_answers(client):
    """The bound must be at the horizon, not below it -- a bound that is too tight hides
    working configurations instead of fixing anything."""
    resp = client.get(
        EVALUATION, params={"review_period_months": nv_api.EVALUATION_MAX_REVIEW_PERIOD_MONTHS}
    )
    assert resp.status_code == 200, resp.text
    assert nv_api.EVALUATION_MAX_REVIEW_PERIOD_MONTHS == nv.PANEL_HORIZON


# ── 5. The fallback the guards fail over to must still work ───────────────────

def test_the_permuted_negative_control_can_never_be_served_as_a_real_answer():
    """`negative_control_permuted` scores each series against ANOTHER series' forecast.

    No request can ask for it, so it must not be reachable by any request. Serving it would
    be handing back a deliberately meaningless evaluation as though it were the policy's.
    """
    index = _index() if ARTIFACT.is_file() else {}
    for entry in index.values():
        if entry:
            assert entry["block"]["protocol"]["permutation_control"] is False
            assert entry["block_name"] != "negative_control_permuted"


def _mutated_artifact(tmp_path: Path, mutate) -> Path:
    raw = json.loads(ARTIFACT.read_text())
    mutate(raw)
    path = tmp_path / "newsvendor.json"
    path.write_text(json.dumps(raw))
    return path


@pytest.fixture
def artifact_at(monkeypatch):
    """Point the endpoint at a different artifact file and clear the derived index."""
    def _use(path: Path) -> Dict[Any, Any]:
        monkeypatch.setattr(nv_api, "EVALUATION_ARTIFACT_PATH", path)
        nv_api._artifact_index.cache_clear()
        nv_api._cached_evaluation.cache_clear()
        return nv_api._artifact_index(path.stat().st_mtime, str(path))
    yield _use
    nv_api._artifact_index.cache_clear()
    nv_api._cached_evaluation.cache_clear()


@needs_panel
@needs_artifact
def test_the_recompute_fallback_still_answers_when_the_artifact_publishes_nothing(
    client, tmp_path, artifact_at
):
    """Every identity guard below fails over to computing. If that path were broken, each
    of those guards would be turning a stale number into a 500, and this file would be
    proving the wrong thing.

    So: strip the artifact down to nothing servable, then make the ordinary request. It must
    answer 200, from the real evaluator, and SAY that it recomputed.
    """
    def strip(raw: Dict[str, Any]) -> None:
        raw.pop("grid", None)
        for name in list(raw):
            if name not in ("provenance", "meta"):
                raw.pop(name)

    assert artifact_at(_mutated_artifact(tmp_path, strip)) == {}

    resp = client.get(EVALUATION)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["computation"]["recomputed"] is True, (
        "the artifact published nothing and the endpoint still claimed a served block"
    )
    assert body["computation"]["source"].endswith("run in this process")
    assert body["computation"]["artifact_git_commit"] is None
    assert _config_of(body) == ("tsb", 1, "expedite")
    assert body["ship_gate"]["passed"] in (True, False)
    assert body["panel"]["n_series_scored"] > 2500


# ── 6. The identity guards, one at a time ─────────────────────────────────────

@needs_artifact
def test_an_unmutated_copy_is_served(tmp_path, artifact_at):
    """The control. Without this, every guard test below could pass for the wrong reason."""
    index = artifact_at(_mutated_artifact(tmp_path, lambda raw: None))
    assert index, "the guard tests below prove nothing if the unmutated copy is also rejected"
    assert len(index) == 72, f"the unmutated copy served {len(index)} of 72 configurations"


@needs_artifact
@pytest.mark.parametrize(
    "label,mutate",
    [
        ("bootstrap replications", lambda raw: raw["meta"].__setitem__("n_boot", 4999)),
        ("bootstrap seed", lambda raw: raw["meta"].__setitem__("bootstrap_seed", 1)),
        (
            "panel checksum",
            lambda raw: raw["provenance"]["inputs"]["car_parts_panel"].__setitem__("sha256", "0" * 64),
        ),
    ],
)
def test_an_artifact_that_describes_a_different_computation_is_not_served(
    tmp_path, artifact_at, label, mutate
):
    """These are inputs the caller cannot set, so a mismatch means the artifact is
    answering a different question from the one that was asked."""
    assert artifact_at(_mutated_artifact(tmp_path, mutate)) == {}, (
        f"an artifact with a different {label} was served anyway"
    )


@needs_artifact
@pytest.mark.parametrize("block_path", [("primary",), ("grid", "sba_L4_line_down")])
@pytest.mark.parametrize(
    "field,value",
    [
        ("horizon_months", 12),
        ("n_origins", 4),
        ("seasonality", 4),
        ("permutation_control", True),
        ("distribution_source", "empirical"),
    ],
)
def test_a_block_whose_protocol_is_not_this_codes_protocol_is_dropped(
    tmp_path, artifact_at, block_path, field, value
):
    """Applied to a named block AND a grid block: the grid is 68 blocks nobody reads by
    hand, so it is exactly where an unguarded one would sit unnoticed."""
    def mutate(raw: Dict[str, Any]) -> None:
        node: Any = raw
        for step in block_path:
            node = node[step]
        node["protocol"][field] = value

    index = artifact_at(_mutated_artifact(tmp_path, mutate))
    dropped = ("tsb", 1, "expedite") if block_path == ("primary",) else ("sba", 4, "line_down")
    assert dropped not in index, (
        f"{'/'.join(block_path)} was served with protocol.{field}={value!r}, which is not "
        f"what this code would have computed"
    )
    # The rest of the artifact is untouched and must still be servable -- the guard drops
    # one block, not the whole file.
    assert len(index) == 71, f"one mutated block cost {72 - len(index)} configurations"


@needs_artifact
@pytest.mark.parametrize(
    "label,mutate",
    [
        # A named block duplicated at the top level, the original shape of this guard.
        ("a second named block", lambda raw: raw.__setitem__("primary_copy", json.loads(json.dumps(raw["primary"])))),
        # And the way it would actually happen now: a grid entry that repeats a named run.
        ("a grid entry repeating a named run", lambda raw: raw["grid"].__setitem__(
            "tsb_L1_expedite", json.loads(json.dumps(raw["primary"]))
        )),
    ],
)
def test_two_blocks_claiming_one_configuration_serve_neither(tmp_path, artifact_at, label, mutate):
    """A generator that grew a duplicate must not turn into a coin flip."""
    index = artifact_at(_mutated_artifact(tmp_path, mutate))
    assert not index.get(("tsb", 1, "expedite")), f"one of two identical claims was picked ({label})"


@needs_artifact
def test_a_missing_or_unreadable_artifact_falls_back_to_computing(tmp_path, artifact_at):
    missing = tmp_path / "gone.json"
    nv_api._artifact_index.cache_clear()
    assert nv_api._artifact_index(0.0, str(missing)) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert artifact_at(broken) == {}
