"""`Component.risk_score` is a catalogue attribute. It must never be published
as a probability, and it must be banded in exactly one place.

Why this file exists
--------------------
`risk_score` was rendered with a `%` sign on `/dashboard` and `/components`
(KPI tile, scatter axis, radar axis, tooltip, detail tile). A `%` is a unit
claim, and this quantity cannot support it:

* Nothing in this repo computes it. `seeds/seed_db.py:248` copies a HuggingFace
  dataset column through verbatim (`row.get("risk_score") or 0.0`).
* Upstream it behaves as an additive hand-weighted flag sum,
  ``0.60*chinese_origin + 0.25*critical_category + 0.10*limited_suppliers``.
* Its ENTIRE support across the 791 seeded parts is six values -- 0.00, 0.10,
  0.20, 0.25, 0.60, 0.70.
* 387 of those parts (48.9%) sit at 0.20 with ``risk_factors = NULL``: a nonzero
  number with no flag behind it. The score is not even a function of the flags
  it claims to sum.

There is no base rate, no exposure window and no unit, so it is not a
probability. This is the repo's own Check-8 pathology, already fixed three times
(`graph/builder.py`, `graph/simulation.py`, `optimization/recommendations.py`);
these tests stop it reappearing on the two pages that publish the catalogue.

The second half is the band split. `lib/risk.ts` banded at 0.4/0.7 and
`SchedulerPage.tsx` at 0.3/0.6. Every one of those cuts lands inside the score's
empty interval ``(0.25, 0.60)`` -- nothing is observed between 0.25 and 0.60, so
any cut in that range produces an identical partition and no observation could
ever distinguish them. The visible consequence was that the same 13 ESP8266
parts (score 0.60) rendered **red on /components and amber on /dashboard**. The
fix is not a better cutoff -- there is no honest one -- it is to band on the
flags, in one shared function both pages import.

If this fails
-------------
Do not relax the assertion. Re-render the quantity as an index on its stated
0-1 scale (``0.17 / 1.0``) and take the tier from
``frontend/src/lib/risk.ts::catalogueRiskTier``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

DASHBOARD = FRONTEND_SRC / "pages" / "Dashboard.tsx"
SCHEDULER = FRONTEND_SRC / "pages" / "SchedulerPage.tsx"
RISK_LIB = FRONTEND_SRC / "lib" / "risk.ts"

#: The pages that publish `Component.risk_score` from the catalogue API.
CATALOGUE_PAGES = (DASHBOARD, SCHEDULER)

#: The exact support of `risk_score` in the seeded catalogue, and the flag set
#: that explains each value. `None` means `risk_factors` is NULL.
DOCUMENTED_SUPPORT = {
    0.00: None,
    0.10: ["limited_suppliers"],
    0.20: None,  # the placeholder cohort: a nonzero score with no flag
    0.25: ["critical_category"],
    0.60: ["chinese_origin"],
    0.70: ["chinese_origin", "limited_suppliers"],
}


def _read(path: Path) -> str:
    if not path.exists():  # pragma: no cover - guards a moved file, not a branch
        pytest.skip(f"{path} is not present in this checkout")
    return path.read_text(encoding="utf-8")


# ── 1. The unit claim ───────────────────────────────────────────────────────


@pytest.mark.parametrize("page", CATALOGUE_PAGES, ids=lambda p: p.name)
def test_the_catalogue_risk_score_is_never_multiplied_into_a_percentage(page: Path) -> None:
    """No page turns the flag sum into a rate by scaling it to 100.

    These are the five expressions that actually shipped. Each one put a `%`
    in front of a number with no denominator.
    """
    source = _read(page)
    retired = [
        "risk_score * 100",
        "risk_score*100",
        "(d.y * 100)",          # scatter tooltip
        "avgRisk * 100",        # "Avg Supply Risk" KPI tile
        "(d.risk / d.count) * 100",  # radar series
    ]
    offenders = [expr for expr in retired if expr in source]
    assert not offenders, (
        f"{page.name} scales risk_score to a percentage via {offenders}. "
        "It is a 6-valued flag sum with no base rate; render it as an index "
        "(formatRiskIndex) on its 0-1 scale instead."
    )


@pytest.mark.parametrize("page", CATALOGUE_PAGES, ids=lambda p: p.name)
def test_each_catalogue_page_renders_the_score_through_the_shared_index_formatter(
    page: Path,
) -> None:
    """The index has exactly one renderer, so its unit cannot drift per page."""
    source = _read(page)
    assert "formatRiskIndex" in source, (
        f"{page.name} publishes risk_score but does not use formatRiskIndex from "
        "lib/risk.ts. Ad-hoc formatting is how the `%` got in."
    )


# ── 2. One band definition ──────────────────────────────────────────────────


@pytest.mark.parametrize("page", CATALOGUE_PAGES, ids=lambda p: p.name)
def test_both_catalogue_pages_take_their_tier_from_the_single_shared_definition(
    page: Path,
) -> None:
    """A part cannot be red on /components and amber on /dashboard."""
    source = _read(page)
    assert "catalogueRiskTier" in source, (
        f"{page.name} must import catalogueRiskTier from ../lib/risk. Two local "
        "band sets (0.4/0.7 here, 0.3/0.6 there) is exactly the bug this closes."
    )
    assert "from '../lib/risk'" in source, (
        f"{page.name} must source the band definition from lib/risk.ts, not redefine it."
    )


def test_the_scheduler_page_no_longer_defines_its_own_numeric_risk_bands() -> None:
    """The 0.3/0.6 rival band set is gone, not merely unused."""
    source = _read(SCHEDULER)
    for retired in ("function riskColor(", "function riskBadge("):
        assert retired not in source, (
            f"SchedulerPage.tsx still defines {retired!r}. Its 0.3/0.6 cuts "
            "disagreed with the Dashboard's 0.4/0.7 on the same parts."
        )


def test_the_generic_risk_label_is_not_applied_to_the_catalogue_score() -> None:
    """`riskLabel` bands an arbitrary 0-1 number at 0.4/0.7.

    Both cuts sit inside risk_score's empty interval (0.25, 0.60), so it is not
    a valid tiering for this quantity. It survives in lib/risk.ts for the other
    callers that pass genuinely different numbers.
    """
    for page in CATALOGUE_PAGES:
        source = _read(page)
        assert "riskLabel" not in source, (
            f"{page.name} uses riskLabel on the catalogue score. Its 0.4/0.7 cuts "
            "are unfalsifiable on a support with nothing between 0.25 and 0.60."
        )


def test_the_shared_module_states_why_there_is_no_numeric_cutoff() -> None:
    """The justification lives next to the code, not only in a doc that can rot."""
    source = _read(RISK_LIB)
    assert "catalogueRiskTier" in source
    assert "0.25" in source and "0.60" in source, (
        "lib/risk.ts must record the empty interval that makes numeric bands "
        "on risk_score unfalsifiable."
    )
    assert "Not a probability" in source or "not a probability" in source


# ── 3. The provenance claim in the ORM model ────────────────────────────────


def test_the_component_model_does_not_claim_nexar_provenance_for_risk_score() -> None:
    """`models/component.py:17` said "0-1 from Nexar analysis". Wrong twice.

    It is not from Nexar, and the Nexar path hardcodes 0.0 because the API
    exposes no such field.
    """
    source = (BACKEND_ROOT / "app" / "models" / "component.py").read_text(encoding="utf-8")
    assert "0-1 from Nexar analysis" not in source, (
        "component.py still credits risk_score to Nexar analysis. It is a "
        "verbatim HuggingFace dataset column (seeds/seed_db.py:248)."
    )
    assert "HuggingFace" in source, (
        "component.py must name the real provenance of risk_score."
    )


def test_the_nexar_client_really_does_hardcode_a_zero_risk_score() -> None:
    """The code fact the corrected comment cites. If Nexar ever starts serving a
    real score, the comment above `risk_score` has to be revisited, not this
    assertion relaxed.
    """
    source = (
        BACKEND_ROOT / "app" / "core" / "clients" / "nexar_client.py"
    ).read_text(encoding="utf-8")
    assert '"risk_score": 0.0' in source


# ── 4. The support the comments assert ──────────────────────────────────────


def test_the_seeded_catalogue_matches_the_documented_risk_score_support() -> None:
    """Pins the six values and the placeholder cohort that every comment cites.

    Skips on a checkout without the seeded database; the numbers quoted in
    `lib/risk.ts` and `models/component.py` are only meaningful against it.
    """
    db_path = BACKEND_ROOT / "supply_chain.db"
    if not db_path.exists():
        pytest.skip("supply_chain.db not seeded in this checkout")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT risk_score, risk_factors FROM components").fetchall()
    except sqlite3.OperationalError:  # pragma: no cover - unseeded schema
        pytest.skip("components table not present in supply_chain.db")
    finally:
        conn.close()

    if not rows:
        pytest.skip("components table is empty")

    observed = {round(float(score), 2) for score, _ in rows}
    assert observed == set(DOCUMENTED_SUPPORT), (
        f"risk_score support changed: {sorted(observed)} vs the documented "
        f"{sorted(DOCUMENTED_SUPPORT)}. Every comment and UI caption that "
        "quotes this support has to be re-derived, starting with lib/risk.ts."
    )

    for score, raw in rows:
        expected = DOCUMENTED_SUPPORT[round(float(score), 2)]
        actual = json.loads(raw) if raw else None
        assert actual == expected, (
            f"risk_score {score} carries flags {actual!r}, documented as {expected!r}."
        )

    placeholder = [s for s, raw in rows if not (json.loads(raw) if raw else None) and s > 0]
    assert placeholder, (
        "The placeholder cohort is gone. If every nonzero score now has a flag "
        "behind it, the UI captions saying otherwise are stale."
    )
    share = len(placeholder) / len(rows)
    assert share > 0.4, (
        f"Placeholder cohort is {share:.1%} of the catalogue; the comments and "
        "captions quote ~48.9% and need updating."
    )
