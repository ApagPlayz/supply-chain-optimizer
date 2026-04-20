"""
Regression tests for is_chinese_origin flag propagation from Component.risk_factors
through Offer construction into the sourcing pipeline.

Guards Research Pitfall 2: `manufacturer_country` is inconsistent in the
HuggingFace dataset — use `risk_factors` JSON as the source of truth for
Chinese-origin detection. Without this propagation, the benchmark would show
zero delta on Chinese-origin BOMs because _feed_risk_cents() (GPR surcharge)
never fires.

Also verifies that `seeds/run_benchmark.py` (Task 4) uses the same
risk_factors-derived logic, not manufacturer_country.

See .planning/phases/04-benchmark-dashboard/04-RESEARCH.md §Pitfall 2
and §Assumptions A7.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _detect_chinese_origin(risk_factors) -> bool:
    """
    Mirror of the inline logic in backend/app/api/optimize.py lines 90-93
    and backend/seeds/run_benchmark.py. Any membership check treating
    risk_factors as None, a list, or a dict uniformly yields the correct
    Chinese-origin flag.
    """
    return any(
        "chinese" in str(f).lower()
        for f in (risk_factors or [])
    )


# ── Behavior tests ───────────────────────────────────────────────────────────


def test_offer_chinese_flag_from_risk_factors():
    """Component with ['chinese_origin', 'single_source'] must produce is_chinese_origin=True."""
    assert _detect_chinese_origin(["chinese_origin", "single_source"]) is True


def test_offer_chinese_flag_empty_risk_factors():
    """Component with None (no risk factors) must produce is_chinese_origin=False."""
    assert _detect_chinese_origin(None) is False
    assert _detect_chinese_origin([]) is False


def test_offer_chinese_flag_case_insensitive():
    """Mixed-case variants must still be detected as Chinese-origin."""
    assert _detect_chinese_origin(["Chinese_Origin"]) is True
    assert _detect_chinese_origin(["CHINESE_ORIGIN"]) is True
    assert _detect_chinese_origin(["cHiNeSe_OriGIN"]) is True


def test_offer_chinese_flag_from_dict_shape():
    """Graceful handling when risk_factors is a dict — iteration yields keys."""
    # Iterating a dict yields its keys; the key 'chinese_origin' must trip the check.
    assert _detect_chinese_origin({"chinese_origin": True, "single_source": True}) is True
    assert _detect_chinese_origin({"single_source": True}) is False


def test_offer_chinese_flag_non_chinese_factors():
    """Risk factors present but NOT containing 'chinese' must produce False."""
    assert _detect_chinese_origin(["single_source"]) is False
    assert _detect_chinese_origin(["single_source", "high_obsolescence"]) is False


def test_optimize_endpoint_propagates_flag_via_source():
    """
    Static grep against backend/app/api/optimize.py — the /optimize/vrp route
    MUST derive is_chinese from risk_factors and pass it into the Offer.

    This guards against a future refactor that deletes the propagation block.
    """
    path = Path(__file__).resolve().parent.parent / "app" / "api" / "optimize.py"
    src = path.read_text()
    assert '"chinese" in str(f).lower()' in src, (
        "Pitfall 2 regression — /optimize/vrp must derive is_chinese from risk_factors"
    )
    assert "is_chinese_origin=is_chinese" in src, (
        "Pitfall 2 regression — /optimize/vrp must pass is_chinese into Offer()"
    )
    assert "comp.risk_factors" in src, (
        "Pitfall 2 regression — source of truth for Chinese-origin is risk_factors"
    )


def test_run_benchmark_offer_construction_uses_risk_factors():
    """
    Task 4 regression hook. After `backend/seeds/run_benchmark.py` lands,
    it must also derive is_chinese_origin from risk_factors.

    Uses `pytest.importorskip` so this test passes today (before Task 4)
    and gains coverage automatically once the file exists.
    """
    seeds_path = Path(__file__).resolve().parent.parent / "seeds" / "run_benchmark.py"
    if not seeds_path.exists():
        pytest.skip("seeds/run_benchmark.py not yet created (Task 4)")

    src = seeds_path.read_text()
    assert '"chinese" in str(f).lower()' in src, (
        "Pitfall 2 regression — run_benchmark must derive is_chinese from risk_factors"
    )
    assert "is_chinese_origin=is_chinese" in src, (
        "Pitfall 2 regression — run_benchmark must pass is_chinese into Offer()"
    )
    assert "risk_factors" in src, (
        "Pitfall 2 regression — run_benchmark must read risk_factors, not manufacturer_country"
    )
