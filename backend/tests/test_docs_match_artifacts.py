"""Published prose must agree with the artifact it claims to quote.

Every number in this repo's headline docs is supposed to come from a committed
JSON artifact or a code constant. In practice six of them did not, because they
were transcribed by hand once and then never re-checked:

  * "467 part families"        — 467 is the count of ``_group_key`` outputs. The
                                 count of ``base_product`` values is 360. The
                                 number was right; the *noun* was wrong.
  * "CVaR figure is 100% data-derived" — the spend side is; the probability side
                                 is betweenness centrality, which is not a
                                 calibrated likelihood.
  * "serving coverage 94.4%"   — matched no denominator in the repo. Measured
                                 today: 97.85% of offer×component pairs, 93.05%
                                 of components. Stale, pre-DB-rebuild.
  * "2,658 series"             — a count that exists nowhere. The panel is 2,674
                                 and 2,646 are scored.
  * "$4.27 per $1 of tail risk" — true only at 60,000 units. ``knee`` is ``null``
                                 at 100x and 1000x.

This module is the regression guard for that class of drift: it re-derives each
figure from its source and fails when the doc and the source disagree. It is
deliberately fast — it reads JSON and text, fits nothing, and touches no DB.

Two shapes of assertion are used, and the distinction matters:

  * **Generated regions** (``docs/INTERMITTENT_DEMAND.md``) are compared
    byte-for-byte against what the generator would write today. That is the only
    check strong enough to catch a hand-edit of a generated table.
  * **Curated prose** everywhere else is checked for the presence of the right
    number and the *absence* of the retracted one, because prose cannot be
    regenerated and a substring check is what is actually enforceable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent
DOCS = REPO_ROOT / "docs"


# ── fixtures ─────────────────────────────────────────────────────────────────

def _json(name: str) -> Dict[str, Any]:
    path = DOCS / name
    if not path.is_file():
        pytest.skip(f"{name} is not committed in this checkout")
    return json.loads(path.read_text())


def _doc(name: str) -> str:
    path = DOCS / name
    if not path.is_file():
        pytest.skip(f"{name} is not committed in this checkout")
    return path.read_text()


@pytest.fixture(scope="module")
def leakage() -> Dict[str, Any]:
    return _json("leakage_progression.json")


@pytest.fixture(scope="module")
def intermittent() -> Dict[str, Any]:
    return _json("intermittent_demand.json")


@pytest.fixture(scope="module")
def cvar() -> Dict[str, Any]:
    return _json("cvar_frontier.json")


# ─────────────────────────────────────────────────────────────────────────────
# 1. 467 family GROUPING KEYS vs 360 BASE PRODUCTS
# ─────────────────────────────────────────────────────────────────────────────

def test_the_two_grouping_counts_are_what_the_artifact_says(leakage):
    """467 and 360 are both real, and they count different things."""
    assert leakage["counts"]["n_family_group_keys"] == 467
    assert leakage["identity_column_in_sample_r2"]["base_product"]["n_levels"] == 360
    assert leakage["identity_column_in_sample_r2"]["family_group_key"]["n_levels"] == 467
    # The group key can only ever split a base_product, never merge two of them.
    assert (
        leakage["identity_column_in_sample_r2"]["family_group_key"]["n_levels"]
        >= leakage["identity_column_in_sample_r2"]["base_product"]["n_levels"]
    )


def test_group_key_docstring_states_both_counts():
    """``lead_time_model._group_key`` is the code of record for these two numbers."""
    source = (BACKEND_ROOT / "app" / "ml" / "lead_time_model.py").read_text()
    assert "collapses 736 MPNs into 360 families" in source
    assert "467 group" in source


#: A retracted phrase is allowed to survive inside the paragraph that retracts it —
#: deleting the old wording entirely would erase the record of the correction. What is
#: forbidden is quoting it as a live claim.
_CORRECTION = re.compile(r"correct|retract|stale|previously|is not|earlier revision", re.I)


def _paragraphs(text: str):
    return re.split(r"\n\s*\n", text)


def _assert_only_in_a_correction(doc: str, text: str, phrase: str, why: str) -> None:
    for paragraph in _paragraphs(text):
        if phrase not in paragraph:
            continue
        assert _CORRECTION.search(paragraph), (
            f"{doc} states '{phrase}' as a live claim. {why}\n"
            f"offending paragraph:\n{paragraph.strip()[:400]}"
        )


#: RESEARCH_TECHNIQUES.md also says "467 families" but is owned by another workstream,
#: so it is named here rather than asserted on — add it when that file is quiet.
@pytest.mark.parametrize(
    "doc", ["LEAKAGE_PROGRESSION.md", "MODEL_CI.md", "PROJECT_OVERVIEW.md"]
)
def test_no_doc_calls_467_a_count_of_part_families(doc):
    """The retracted phrasing, in every casing it was written in."""
    text = _doc(doc)
    for phrase in ("467 part families", "467 families", "467 part-families"):
        _assert_only_in_a_correction(
            doc, text, phrase,
            "467 counts _group_key outputs; the count of part families / "
            "base_product values is 360.",
        )


def test_leakage_doc_quotes_both_counts_with_the_right_names(leakage):
    text = _doc("LEAKAGE_PROGRESSION.md")
    keys = leakage["counts"]["n_family_group_keys"]
    base = leakage["identity_column_in_sample_r2"]["base_product"]["n_levels"]
    assert f"{keys} family grouping keys" in text
    assert f"{base} distinct `base_product` values" in text
    assert f"{leakage['counts']['n_manufacturers']} manufacturers" in text
    assert f"{leakage['counts']['n_rows']} rows" in text


def test_model_ci_leakage_table_matches_the_artifact(leakage):
    """MODEL_CI.md restates the progression; it must restate the measured one."""
    text = _doc("MODEL_CI.md")
    prog = leakage["progression"]
    for value in (prog["random_mean"], prog["family_mean"], prog["manufacturer_mean"]):
        rendered = f"{abs(value):.3f}"
        assert rendered in text, f"MODEL_CI.md does not quote {value:+.3f}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. The CVaR dollar figure is NOT "100% data-derived"
# ─────────────────────────────────────────────────────────────────────────────

def test_impact_framing_retracts_the_fully_data_derived_claim():
    text = _doc("IMPACT_FRAMING.md")
    _assert_only_in_a_correction(
        "IMPACT_FRAMING.md", text, "100% data-derived",
        "README.md retracted it: the spend side is real, the probability side is "
        "betweenness centrality and is not calibrated.",
    )
    assert "betweenness centrality" in text, (
        "the retraction must name what the probability side actually is"
    )
    assert "half data-derived" in text or "not calibrated" in text


def test_the_readme_retraction_is_still_the_one_being_propagated():
    """If README's wording changes, this doc's copy of it must be revisited."""
    readme = (REPO_ROOT / "README.md").read_text()
    assert "half data-derived" in readme
    assert "betweenness centrality" in readme


# ─────────────────────────────────────────────────────────────────────────────
# 3. Serving coverage — one denominator, stated
# ─────────────────────────────────────────────────────────────────────────────

#: Measured 2026-08-16 against the tracked supply_chain.db and the committed
#: lead-time artifacts. 8,000 of 8,176 offer x component pairs answer; 736 of 791
#: distinct components answer through the endpoint. The two differ only because 55
#: components have digikey_category IS NULL and those 55 own 176 offers.
PAIR_COVERAGE = "97.85%"
COMPONENT_COVERAGE = "93.05%"
RETRACTED_COVERAGE = "94.4%"


@pytest.mark.parametrize("doc", ["MODEL_CI.md", "ML_API_PUSH_PLAN.md"])
def test_coverage_docs_quote_the_measured_rate_not_the_retracted_one(doc):
    text = _doc(doc)
    assert PAIR_COVERAGE in text, (
        f"{doc} must quote the measured {PAIR_COVERAGE} answer rate over "
        "(offer, component) pairs — the denominator tests/test_serve_coverage.py uses"
    )
    assert COMPONENT_COVERAGE in text, (
        f"{doc} must also give the component-level rate {COMPONENT_COVERAGE} "
        "(736 of 791), because the endpoint answers per component"
    )
    _assert_only_in_a_correction(
        doc, text, RETRACTED_COVERAGE,
        f"{RETRACTED_COVERAGE} matches neither denominator and predates the DB rebuild.",
    )


def test_the_two_coverage_denominators_are_arithmetically_consistent():
    """8000/8176 and 736/791 must actually round to the published percentages."""
    assert f"{8000 / 8176 * 100:.2f}%" == PAIR_COVERAGE
    assert f"{736 / 791 * 100:.2f}%" == COMPONENT_COVERAGE


# ─────────────────────────────────────────────────────────────────────────────
# 4. The series count in model_comparison.py
# ─────────────────────────────────────────────────────────────────────────────

def test_model_comparison_docstring_quotes_a_series_count_that_exists(intermittent):
    source = (BACKEND_ROOT / "app" / "ml" / "model_comparison.py").read_text()
    assert "2,658" not in source and "2658 series" not in source, (
        "model_comparison.py still cites 2,658 series, a number that appears in no "
        "artifact"
    )
    scored = intermittent["configs"]["primary"]["n_series_scored"]
    panel = intermittent["dataset"]["n_series"]
    assert f"{scored:,}" in source, f"expected the scored count {scored:,}"
    assert f"{panel:,}" in source, f"expected the panel size {panel:,}"


def test_the_scored_and_panel_counts_are_the_ones_the_docs_use(intermittent):
    assert intermittent["dataset"]["n_series"] == 2674
    assert intermittent["configs"]["primary"]["n_series_scored"] == 2646
    assert (
        intermittent["configs"]["primary"]["n_series_dropped_undefined"]
        == 2674 - 2646
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. "$4.27 per $1" is conditional on 60,000 units
# ─────────────────────────────────────────────────────────────────────────────

def test_the_knee_ratio_exists_only_at_the_top_volume(cvar):
    primary = cvar["primary"]
    assert primary["x100"]["knee"] is None
    assert primary["x1000"]["knee"] is None
    knee = primary["x10000"]["knee"]
    assert knee is not None
    ratio = knee["vs_risk_neutral"]["usd_of_cvar_removed_per_usd_of_expected_cost"]
    assert round(ratio, 2) == 4.27, f"the artifact's knee ratio is now {ratio}"
    assert primary["x10000"]["total_units"] == 60000


@pytest.mark.parametrize("doc", ["PROJECT_OVERVIEW.md", "ML_API_PUSH_PLAN.md"])
def test_every_quote_of_the_knee_ratio_carries_its_volume_condition(doc):
    """A summary may quote $4.27 only in a sentence that also states the volume."""
    text = _doc(doc)
    for paragraph in _paragraphs(text):
        if "4.27" not in paragraph:
            continue
        assert "60,000" in paragraph or "60000" in paragraph, (
            f"{doc} quotes $4.27 without the 60,000-unit condition:\n{paragraph}"
        )
        assert re.search(r"knee`? is `?null|no trade-off|frontier is flat", paragraph), (
            f"{doc} quotes $4.27 without saying the knee vanishes at lower volume:"
            f"\n{paragraph}"
        )
        assert "CVAR_EFFICIENT_FRONTIER.md" in paragraph, (
            f"{doc} quotes $4.27 without pointing at the fuller disclosure:\n{paragraph}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. INTERMITTENT_DEMAND.md is generated, and still matches its generator
# ─────────────────────────────────────────────────────────────────────────────

def test_the_generated_regions_are_byte_identical_to_the_generator_output(intermittent):
    """The strong check: re-render every GENERATED block from the artifact.

    A hand-edit inside a marked region fails here, which is the whole point — the
    doc used to be hand-transcribed and that is how its numbers drifted.
    """
    from seeds import run_carparts_backtest as rcb

    doc_path = DOCS / "INTERMITTENT_DEMAND.md"
    if not doc_path.is_file():
        pytest.skip("INTERMITTENT_DEMAND.md is not committed in this checkout")
    current = doc_path.read_text()
    expected = rcb.splice_generated(current, rcb.render_blocks(intermittent))
    assert current == expected, (
        "docs/INTERMITTENT_DEMAND.md disagrees with docs/intermittent_demand.json. "
        "Re-run `cd backend && python -m seeds.run_carparts_backtest` rather than "
        "editing the generated regions by hand."
    )


def test_the_doc_declares_every_block_the_generator_renders(intermittent):
    """Marker set and block set must agree, in both directions."""
    from seeds import run_carparts_backtest as rcb

    text = _doc("INTERMITTENT_DEMAND.md")
    declared = set(re.findall(r"<!-- GENERATED:([a-z0-9_]+) BEGIN -->", text))
    closed = set(re.findall(r"<!-- GENERATED:([a-z0-9_]+) END -->", text))
    assert declared == closed, f"unbalanced markers: {declared ^ closed}"
    assert declared == set(rcb.render_blocks(intermittent))


def test_curated_prose_in_the_demand_doc_still_matches_the_artifact(intermittent):
    """Numbers that live in hand-written sentences, outside any marker."""
    text = _doc("INTERMITTENT_DEMAND.md")
    scored = intermittent["configs"]["primary"]["n_series_scored"]
    nonzero = intermittent["dataset"]["nonzero_fraction"]
    assert f"{scored:,}" in text
    assert f"{nonzero * 100:.1f}%" in text
    # §4's Poisson-limit justification is prose, and it quotes the artifact.
    justification = intermittent["size_distribution"]["empirical_justification"]
    for token in re.findall(r"\d+\.\d+|\d+\.\d%", justification):
        assert token in text, (
            f"the size-law justification quotes {token}, which the doc no longer does"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Provenance is stamped, and dirtiness is loud
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "artifact", ["leakage_progression.json", "intermittent_demand.json"]
)
def test_generated_artifacts_carry_a_provenance_block(artifact):
    from seeds.provenance import DIRTY_WARNING

    prov = _json(artifact).get("provenance")
    assert prov is not None, f"{artifact} has no provenance block"
    assert prov["generator"].startswith("seeds.run_")
    assert prov["generated_at_utc"].endswith("Z")
    git = prov["git"]
    assert isinstance(git["dirty"], bool), "dirtiness must be an explicit boolean"
    if git["dirty"]:
        # The whole point of the migration: never a silent `-dirty` suffix again.
        # The property asserted is that the flag carries a loud explanation, not that
        # it carries one exact sentence — the wording lives in seeds/provenance.py.
        assert git["warning"], "a dirty artifact must carry a warning string"
        assert "reproduc" in git["warning"].lower()
        assert "UNCOMMITTED" in git["warning"]
        assert DIRTY_WARNING
    assert prov["inputs"], f"{artifact} records no input hashes"
    for meta in prov["inputs"].values():
        assert meta["exists"], f"{artifact} hashes a missing input: {meta['path']}"
        assert len(meta["sha256"]) == 64


def test_the_demand_artifact_no_longer_hides_dirtiness_in_a_sha_suffix(intermittent):
    """The old failure mode: `meta.git_sha` = '<sha>-dirty', and nothing else."""
    assert "git_sha" not in intermittent["meta"], (
        "meta.git_sha is back. Git state belongs in the provenance block, where "
        "`dirty` is a boolean with a warning attached."
    )


@pytest.mark.parametrize(
    ("doc", "artifact"),
    [
        ("LEAKAGE_PROGRESSION.md", "leakage_progression.json"),
        ("INTERMITTENT_DEMAND.md", "intermittent_demand.json"),
    ],
)
def test_the_doc_renders_the_commit_its_artifact_recorded(doc, artifact):
    text = _doc(doc)
    prov = _json(artifact)["provenance"]
    assert prov["git"]["commit"] in text, f"{doc} does not show its generating commit"
    if prov["git"]["dirty"]:
        assert "DIRTY WORKING TREE" in text, (
            f"{doc} was generated from a dirty tree and does not say so"
        )
