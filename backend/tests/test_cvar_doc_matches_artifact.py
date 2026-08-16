"""`docs/CVAR_EFFICIENT_FRONTIER.md` must agree with `docs/cvar_frontier.json`.

WHY THIS FILE EXISTS
--------------------
The CVaR document used to be hand-transcribed from the artifact, and it drifted in two
different ways at once:

1. Sections 6, 7 and 8 each said *"Populated from `docs/cvar_frontier.json` ->
   sensitivity / saa_quality / breadth"* while the committed artifact was a `--quick`
   run containing only `[meta, calibration, primary]`. All three pointers dangled.
2. The section 9 row for `iot_sensor_node x100` quoted "157 scenarios / ~60 s /
   timeouts at lambda=0" from a run that no longer existed.

Both are the same failure: a number typed into prose has no mechanism that makes it
wrong when the artifact changes. So the numeric blocks of that document are now
GENERATED, delimited by `<!-- GENERATED:name:BEGIN/END -->` markers, and this file is
the gate: it re-renders each block from the committed artifact and asserts the committed
document contains exactly that. If a generated block is edited by hand, or the artifact
is regenerated without re-rendering the document, these tests fail.

The tests deliberately do NOT re-solve anything: they read the two committed files.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent
ARTIFACT = REPO_ROOT / "docs" / "cvar_frontier.json"
DOC = REPO_ROOT / "docs" / "CVAR_EFFICIENT_FRONTIER.md"

MARKER_RE = re.compile(
    r"<!-- GENERATED:(?P<name>[a-z_]+):BEGIN -->\n(?P<body>.*?)\n?<!-- GENERATED:(?P=name):END -->",
    re.DOTALL,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def artifact() -> dict:
    if not ARTIFACT.is_file():
        pytest.skip(f"{ARTIFACT} not generated; run `python -m seeds.run_cvar_frontier`")
    return json.loads(ARTIFACT.read_text())


@pytest.fixture(scope="module")
def doc_text() -> str:
    if not DOC.is_file():
        pytest.skip(f"{DOC} missing")
    return DOC.read_text()


@pytest.fixture(scope="module")
def doc_blocks(doc_text: str) -> dict:
    return {m.group("name"): m.group("body").strip() for m in MARKER_RE.finditer(doc_text)}


# ── The artifact must actually contain what the document points at ───────────

def test_the_committed_artifact_is_a_full_run_not_a_quick_one(artifact: dict) -> None:
    """
    The regression this whole file exists for.

    `--quick` writes only `primary` + `calibration`. Committing that artifact while the
    document's sections 6, 7 and 8 point at `sensitivity`, `saa_quality` and `breadth`
    leaves three dangling pointers, which is what shipped.
    """
    assert artifact["meta"]["quick_mode"] is False, (
        "docs/cvar_frontier.json was generated with --quick, so sections 6/7/8 of "
        "docs/CVAR_EFFICIENT_FRONTIER.md have nothing to be built from. Re-run "
        "`python -m seeds.run_cvar_frontier` with no flag."
    )
    for key in ("primary", "calibration", "sensitivity", "saa_quality", "breadth"):
        assert key in artifact, f"artifact is missing the `{key}` arm"


def test_no_section_still_promises_content_it_does_not_have(doc_text: str) -> None:
    """The literal 'Populated from ...' placeholders must be gone, not just satisfied."""
    assert "Populated from `docs/cvar_frontier.json`" not in doc_text, (
        "a section still carries the placeholder pointer instead of generated content"
    )


# ── Every generated block must equal a fresh render of the artifact ──────────

def test_every_generated_marker_is_well_formed_and_has_a_renderer(doc_text: str) -> None:
    from seeds.run_cvar_frontier import RENDERERS

    begins = set(re.findall(r"<!-- GENERATED:([a-z_]+):BEGIN -->", doc_text))
    ends = set(re.findall(r"<!-- GENERATED:([a-z_]+):END -->", doc_text))
    assert begins == ends, f"unbalanced markers: {begins ^ ends}"
    assert begins, "the document has no generated blocks at all"
    unknown = begins - set(RENDERERS)
    assert not unknown, f"markers with no registered renderer: {sorted(unknown)}"
    missing = set(RENDERERS) - begins
    assert not missing, (
        f"renderers with no marker in the document: {sorted(missing)} -- their output "
        "is being generated and thrown away"
    )


@pytest.mark.parametrize("name", [
    "headline_pitch", "solve_quality", "calibration_table", "exact_vs_saa_table",
    "frontier_table", "knee_table", "tail_table", "baselines_table", "volume_table",
    "sensitivity", "saa_quality", "breadth", "solve_times",
])
def test_generated_block_matches_a_fresh_render_of_the_artifact(
    name: str, artifact: dict, doc_blocks: dict,
) -> None:
    """
    The load-bearing assertion: the committed prose IS the artifact, byte for byte,
    inside the markers. Hand-editing a number in one of these tables fails here.
    """
    from seeds.run_cvar_frontier import RENDERERS

    assert name in doc_blocks, f"no `{name}` block in {DOC.name}"
    expected = RENDERERS[name](artifact).strip()
    assert doc_blocks[name] == expected, (
        f"the `{name}` block in {DOC.name} does not match a fresh render of "
        f"{ARTIFACT.name}. Re-run `python -m seeds.run_cvar_frontier --render-only` "
        "instead of editing the block by hand."
    )


def test_the_provenance_block_records_a_hashed_input_and_a_commit(
    artifact: dict, doc_blocks: dict,
) -> None:
    prov = artifact.get("provenance")
    assert prov, "artifact carries no provenance block"
    assert prov["generator"] == "seeds.run_cvar_frontier"
    assert prov["git"]["commit"], "provenance records no git commit"
    db = prov["inputs"]["component_database"]
    assert db["exists"] and db["sha256"], (
        "the component database was not hashed, so two artifacts cannot be compared "
        "for whether they were built from the same bytes"
    )
    assert "provenance" in doc_blocks


# ── Solve quality: the frontier may not quote unproved points ────────────────

def test_every_frontier_point_reports_its_solve_status_and_gap(artifact: dict) -> None:
    required = {"solver_status", "mip_gap_pct", "hit_time_limit", "converged",
                "time_limit_s"}
    n = 0
    for inst in artifact["primary"].values():
        for p in inst["frontier"]:
            missing = required - set(p)
            assert not missing, f"frontier point lambda={p['lambda']} lacks {missing}"
            n += 1
    assert n, "no frontier points found"


def test_a_point_that_did_not_converge_is_flagged_and_carries_a_reason(
    artifact: dict,
) -> None:
    """
    A 93%-gap solve is not a point on the efficient frontier. It may be reported --
    hiding it would hide the cost of the compute budget -- but it must say so.
    """
    threshold = artifact["solve_quality"]["convergence_gap_threshold_pct"]
    for arm in ("primary",):
        for inst in artifact[arm].values():
            for p in inst["frontier"]:
                proved = p["solver_status"] == "OPTIMAL" or p["mip_gap_pct"] <= threshold
                assert p["converged"] is proved, (
                    f"lambda={p['lambda']}: converged={p['converged']} but status="
                    f"{p['solver_status']} at gap {p['mip_gap_pct']}%"
                )
                if not p["converged"]:
                    assert p["excluded_reason"], "a non-converged point with no reason"


def test_the_knee_is_computed_on_converged_points_only(artifact: dict) -> None:
    for inst in artifact["primary"].values():
        knee = inst.get("knee")
        if knee is None:
            continue
        assert knee["computed_on"] == "converged points only"
        n_ok = sum(1 for p in inst["frontier"] if p["converged"])
        assert knee["n_points_considered"] == n_ok
        assert knee["n_points_excluded_not_converged"] == len(inst["frontier"]) - n_ok


def test_the_run_level_solve_quality_summary_adds_up(artifact: dict) -> None:
    sq = artifact["solve_quality"]
    assert sq["n_solves"] == sq["n_converged"] + sq["n_not_converged"]
    assert sum(sq["counts_by_status"].values()) == sq["n_solves"]
    assert sq["gap_pct_distribution"]["max"] >= sq["gap_pct_distribution"]["p50"] >= 0.0
    assert sq["gap_pct_distribution"]["n_above_5pct"] <= sq["n_solves"]


def test_the_headline_arm_is_fully_proved(artifact: dict) -> None:
    """
    Section 0 of the document states that the '$ of tail removed per $ spent' headline
    is unaffected by the convergence gate because every primary solve was OPTIMAL. That
    sentence must remain true, so it is asserted rather than trusted.
    """
    for name, inst in artifact["primary"].items():
        sq = inst["solve_quality"]
        assert sq["all_points_converged"], (
            f"primary/{name} has {sq['n_excluded_not_converged']} non-converged points; "
            "section 0 of the document claims the primary arm is fully proved"
        )
        assert sq["statuses"] == ["OPTIMAL"], f"primary/{name} statuses: {sq['statuses']}"


# ── The specific stale figures that motivated this file ──────────────────────

def test_section_9_quotes_the_run_it_was_generated_from(
    artifact: dict, doc_blocks: dict,
) -> None:
    """
    The stale row said `iot_sensor_node x100`: 157 scenarios, ~60 s, "timeouts at
    lambda=0". Whatever the current run produces, the document must quote THAT.
    """
    block = doc_blocks["solve_times"]
    breadth = artifact.get("breadth") or {}
    for name, blk in breadth.items():
        for e in blk.get("points") or []:
            if e.get("sweep_wall_seconds") is None:
                continue
            row = f"`{name}` ×{e['multiplier']:,} (breadth arm)"
            if row not in block:
                continue
            assert f"{e['sweep_wall_seconds']:.1f} s" in block, (
                f"{row} is listed in section 9 with a wall time that is not the "
                f"artifact's {e['sweep_wall_seconds']:.1f} s"
            )
            assert str(e.get("n_distinct_scenarios")) in block


def test_the_hand_written_section_5_prose_still_matches_the_artifact(
    artifact: dict, doc_text: str,
) -> None:
    """
    Section 5's *mechanism* paragraphs are prose, not a generated table -- the argument
    they make ("the supplier driving the tail is not the one with the highest failure
    probability") is the point of the section and is not something a renderer should
    write. But the numbers inside them are still artifact figures, so they are pinned
    here rather than trusted to stay true.
    """
    inst = artifact["primary"][f"x{artifact['meta']['headline_multiplier']}"]
    t0 = inst["tail_decomposition_at_lambda_0"]
    tk = inst["tail_decomposition_at_knee"]
    top = t0["worst_scenarios"][0]
    top_knee = next(
        s for s in tk["worst_scenarios"]
        if s["failed_distributor_ids"] == top["failed_distributor_ids"]
    )
    driver = top["failed_distributor_ids"][0]

    assert f"distributor {driver} (cheap" in doc_text, (
        f"the prose names a different tail driver than the artifact's {driver}"
    )
    assert f"**{top['unmet_units']:,} units are simply" in doc_text
    assert f"**{top_knee['emergency_units']:,} emergency units instead of" in doc_text
    assert f"\n{top['emergency_units']:,}**" in doc_text
    saved = top["total_cost_usd"] - top_knee["total_cost_usd"]
    assert f"${saved:,.0f} out of the single worst-contributing scenario" in doc_text

    probs = {
        c["distributor_id"]: c["p_disruption_over_horizon"]
        for c in artifact["calibration"]["primary_bom_distributors"]
    }
    riskiest = max(probs, key=lambda d: probs[d])
    assert f"Distributor {riskiest} has the highest `p_fail` ({probs[riskiest] * 100:.2f}%)" \
        in doc_text
    assert f"distributor {driver} has one of the lowest ({probs[driver] * 100:.2f}%)" \
        in doc_text
    assert f"contributes {top['share_of_tail'] * 100:.1f}%." in doc_text


def test_the_volume_caveat_is_still_true(artifact: dict) -> None:
    """
    The document discloses that the '$4.27 per $1' headline holds only at the headline
    volume, the knee being null at the two lower ones. That disclosure must not become
    a lie if the numbers move.
    """
    prim = artifact["primary"]
    knees = {k: (v.get("knee") or {}).get("lambda") for k, v in prim.items()}
    assert any(v is not None for v in knees.values()), (
        "no volume has a knee at all, but the document recommends one"
    )
    headline = f"x{artifact['meta']['headline_multiplier']}"
    assert knees.get(headline) is not None, (
        f"the headline volume {headline} has no knee, yet the document's recommendation "
        "is built on it"
    )
