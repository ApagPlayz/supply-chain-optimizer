"""
Drift guard: the published benchmark DOCS must agree with the JSON ARTIFACTS.

Why this file exists
--------------------
Both benchmark documents had silently drifted away from the code and data that
were supposed to produce them:

  * ``docs/BENCHMARK_RESULTS.md`` carried figures from ``run_id=4`` while its own
    banner told the reader to "re-run ``python -m seeds.run_benchmark`` to
    regenerate this file". That instruction did not work: the generator wrote to
    ``Path("docs/BENCHMARK-RESULTS.md")`` — CWD-relative *and* hyphenated — so
    running it the documented way (``cd backend && python -m seeds.run_benchmark``)
    produced a stray ``backend/docs/BENCHMARK-RESULTS.md`` and left the real doc
    untouched. The published TOTAL was −44.66%; the code actually reproduced
    −47.25%.
  * ``docs/BENCHMARK_VOLUME_CURVE.md`` was hand-transcribed from
    ``docs/volume_sweep.json`` with no generator at all.

Nothing detected either drift, because nothing compared the prose to the data.
This test does exactly that, and nothing else:

  1. every headline figure quoted in ``BENCHMARK_RESULTS.md`` equals the matching
     field in ``benchmark_results.json``;
  2. every pooled figure quoted in ``BENCHMARK_VOLUME_CURVE.md`` equals the value
     recomputed from ``volume_sweep.json`` under the aggregation rule the document
     itself states;
  3. both artifacts carry a ``provenance`` block (seeds/provenance.py), so a
     reader can tell which commit and which input bytes produced them;
  4. the ``run_benchmark`` generator still targets the repo-root, underscored
     path — the specific bug that let (1) happen.

It is deliberately FAST and unmarked: it re-runs nothing, it only reads four
files that are already committed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

BENCH_MD = DOCS / "BENCHMARK_RESULTS.md"
BENCH_JSON = DOCS / "benchmark_results.json"
CURVE_MD = DOCS / "BENCHMARK_VOLUME_CURVE.md"
CURVE_JSON = DOCS / "volume_sweep.json"

# Cost figures are rounded to cents in both artifacts; percentages to 2dp.
MONEY_TOL = 0.011
PCT_TOL = 0.011
# The volume curve's dollar columns are printed with thousands separators and no
# decimals, so a whole dollar of rounding is expected there.
CURVE_MONEY_TOL = 1.0


# ── parsing helpers ──────────────────────────────────────────────────────────

def _num(cell: str) -> Optional[float]:
    """Parse a markdown table cell into a float, tolerating the doc's styling.

    Handles bold/italic markers, thousands separators, currency and percent
    signs, the ``×`` multiplier suffix, and the UNICODE minus ``−`` (U+2212)
    which the prose uses in places where the tables use ASCII ``-``.
    """
    s = cell.strip()
    if not s or s in {"—", "-", "n/a", "None"}:
        return None
    s = s.replace("−", "-").replace("–", "-")
    s = re.sub(r"[*`_]", "", s)
    s = s.replace(",", "").replace("$", "").replace("%", "").replace("×", "")
    s = s.replace("x", "").strip()
    if not s or not re.fullmatch(r"[+-]?\d*\.?\d+", s):
        return None
    return float(s)


def _rows(md: str, header_must_contain: List[str]) -> List[List[str]]:
    """Return the body cells of the first markdown table whose header row
    contains every one of ``header_must_contain``."""
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        if not all(tok.lower() in line.lower() for tok in header_must_contain):
            continue
        # The next line must be the |---|---| separator for this to be a table.
        if i + 1 >= len(lines) or not re.match(r"^\s*\|[-: |]+\|\s*$", lines[i + 1]):
            continue
        out: List[List[str]] = []
        for body in lines[i + 2:]:
            if not body.lstrip().startswith("|"):
                break
            cells = [c.strip() for c in body.strip().strip("|").split("|")]
            out.append(cells)
        return out
    raise AssertionError(
        f"No markdown table found whose header contains {header_must_contain!r}."
    )


def _plain(cell: str) -> str:
    """Strip markdown emphasis/backticks from a label cell."""
    return re.sub(r"[*`]", "", cell).strip()


# ── fixtures ─────────────────────────────────────────────────────────────────

def _load(path: Path) -> str:
    if not path.is_file():
        pytest.fail(
            f"{path.relative_to(REPO_ROOT)} is missing. Regenerate the artifacts "
            f"with `cd backend && python -m seeds.run_benchmark` and "
            f"`python -m seeds.run_volume_sweep`."
        )
    return path.read_text()


@pytest.fixture(scope="module")
def bench_md() -> str:
    return _load(BENCH_MD)


@pytest.fixture(scope="module")
def bench_json() -> Dict[str, Any]:
    return json.loads(_load(BENCH_JSON))


@pytest.fixture(scope="module")
def curve_md() -> str:
    return _load(CURVE_MD)


@pytest.fixture(scope="module")
def curve_json() -> Dict[str, Any]:
    return json.loads(_load(CURVE_JSON))


# ── 1. BENCHMARK_RESULTS.md §A vs benchmark_results.json ─────────────────────

def test_section_a_total_row_matches_artifact(bench_md, bench_json):
    """The single most-quoted number in the repo: §A's TOTAL save%."""
    head = bench_json["headline"]
    rows = _rows(bench_md, ["greedy $", "milp $", "save% vs greedy"])
    total = next((r for r in rows if _plain(r[0]) == "TOTAL"), None)
    assert total is not None, "§A has no TOTAL row"

    for col, key, tol in (
        (1, "total_greedy_usd", MONEY_TOL),
        (2, "total_greedy_add_usd", MONEY_TOL),
        (3, "total_milp_usd", MONEY_TOL),
        (4, "total_save_pct_vs_greedy", PCT_TOL),
        (5, "total_save_pct_vs_greedy_add", PCT_TOL),
    ):
        doc_val = _num(total[col])
        assert doc_val is not None, f"§A TOTAL column {col} is unparseable: {total[col]!r}"
        assert doc_val == pytest.approx(bench_json["headline"][key], abs=tol), (
            f"§A TOTAL column {col} says {doc_val} but "
            f"benchmark_results.json headline.{key} is {head[key]}. "
            f"Re-run `python -m seeds.run_benchmark`."
        )


def test_section_a_per_bom_rows_match_artifact(bench_md, bench_json):
    by_bom = {
        r["bom"]: r for r in bench_json["value_of_optimization"] if r["bom"] != "TOTAL"
    }
    rows = _rows(bench_md, ["greedy $", "milp $", "save% vs greedy"])
    seen = set()
    for cells in rows:
        name = _plain(cells[0])
        if name == "TOTAL":
            continue
        assert name in by_bom, f"§A lists {name!r}, absent from benchmark_results.json"
        seen.add(name)
        exp = by_bom[name]
        for col, key, tol in (
            (1, "greedy_usd", MONEY_TOL),
            (2, "greedy_add_usd", MONEY_TOL),
            (3, "milp_usd", MONEY_TOL),
            (4, "save_pct_vs_greedy", PCT_TOL),
            (5, "save_pct_vs_greedy_add", PCT_TOL),
        ):
            assert _num(cells[col]) == pytest.approx(exp[key], abs=tol), (
                f"§A row {name}, column {col}: doc {cells[col]!r} != artifact {exp[key]}"
            )
        # "greedy→milp" supplier-count cell.
        sup = _plain(cells[6]).replace("→", " ").split()
        assert [int(x) for x in sup] == [exp["suppliers_greedy"], exp["suppliers_milp"]], (
            f"§A row {name}: supplier counts {cells[6]!r} != artifact "
            f"{exp['suppliers_greedy']}→{exp['suppliers_milp']}"
        )
    assert seen == set(by_bom), (
        f"§A is missing BOMs present in the artifact: {sorted(set(by_bom) - seen)}"
    )


# ── 2. BENCHMARK_RESULTS.md §B vs the artifact ───────────────────────────────

def test_section_b_resilience_rows_match_artifact(bench_md, bench_json):
    by_key = {
        (r["bom"], r["scenario"]): r for r in bench_json["value_of_resilience"]
    }
    rows = _rows(bench_md, ["scenario", "cascade_risk", "cvar_95"])
    assert rows, "§B resilience table is empty"
    seen = set()
    for cells in rows:
        key = (_plain(cells[0]), _plain(cells[1]))
        assert key in by_key, f"§B lists {key}, absent from benchmark_results.json"
        seen.add(key)
        exp = by_key[key]
        assert _num(cells[2]) == pytest.approx(exp["nominal_premium_pct"], abs=PCT_TOL)

        # "0.5000→0.2500 (+0.2500)" — assert the endpoints AND the delta, so a
        # doc that pins both sides to the same value (as run_id=4's did) fails.
        for col, (a, b, delta) in (
            (3, ("cascade_risk_blind", "cascade_risk_graph", "cascade_risk_reduction")),
            (4, ("cvar_95_blind", "cvar_95_graph", "cvar_95_reduction")),
        ):
            m = re.match(
                r"\s*([\d.]+)\s*→\s*([\d.]+)\s*\(([+-][\d.]+)\)\s*$", cells[col]
            )
            assert m, f"§B {key} column {col} is malformed: {cells[col]!r}"
            assert float(m.group(1)) == pytest.approx(exp[a], abs=1e-4)
            assert float(m.group(2)) == pytest.approx(exp[b], abs=1e-4)
            assert float(m.group(3)) == pytest.approx(exp[delta], abs=1e-4), (
                f"§B {key}: quoted delta {m.group(3)} != artifact {exp[delta]}"
            )
    assert seen == set(by_key)


def test_section_b_summary_counts_match_artifact(bench_md, bench_json):
    """The generated §B prose counts improved/worsened cells — check them too."""
    s = bench_json["resilience_summary"]
    body = bench_md
    for phrase, value in (
        ("cascade-risk improves in", s["cascade_risk_improved"]),
        ("gets **worse in", s["cascade_risk_worsened"]),
        ("CVaR-95 improves in", s["cvar_95_improved"]),
    ):
        m = re.search(re.escape(phrase) + r"\D{0,4}(\d+)", body)
        assert m, f"§B prose no longer states {phrase!r}"
        assert int(m.group(1)) == value, (
            f"§B prose says {phrase} {m.group(1)}, artifact says {value}"
        )


# ── 3. BOM inclusion — the silently-dropped sample (BENCH-07) ────────────────

def test_bom_inclusion_table_accounts_for_every_catalog_bom(bench_md, bench_json):
    inc = bench_json["bom_inclusion"]
    rows = _rows(bench_md, ["in benchmark?", "reason"])
    assert len(rows) == inc["n_catalog"] == 10, (
        f"§0 lists {len(rows)} BOMs; the catalog has {inc['n_catalog']}. Every "
        f"catalog BOM must get an explicit verdict — a dropped sample must not "
        f"live only in a log line."
    )
    doc_included = {_plain(r[0]) for r in rows if "EXCLUDED" not in r[1]}
    doc_excluded = {_plain(r[0]) for r in rows if "EXCLUDED" in r[1]}
    assert doc_included == set(inc["included"])
    assert doc_excluded == {e["bom"] for e in inc["excluded"]}

    # Every exclusion must carry a non-empty, specific reason.
    for cells in rows:
        if "EXCLUDED" in cells[1]:
            reason = _plain(cells[4])
            assert len(reason) > 20 and reason != "all 4 arms solved", (
                f"{_plain(cells[0])} is excluded with a uselessly vague reason: "
                f"{reason!r}"
            )


def test_headline_states_true_bom_coverage(bench_md, bench_json):
    """The header must say "N of 10", not imply the full catalog was benchmarked."""
    inc = bench_json["bom_inclusion"]
    m = re.search(r"\*\*(\d+) of (\d+) BOMs\*\*", bench_md)
    assert m, "Header does not state coverage as '**N of M BOMs**'"
    assert (int(m.group(1)), int(m.group(2))) == (inc["n_included"], inc["n_catalog"])

    # The "Rows:" line must be consistent with the included count, not the catalog.
    m2 = re.search(r"\*\*Rows:\*\*\s*(\d+)\s*\((\d+) BOMs", bench_md)
    assert m2, "Header does not state a parseable 'Rows:' line"
    assert int(m2.group(2)) == inc["n_included"]
    assert int(m2.group(1)) == bench_json["meta"]["n_rows"] == inc["n_included"] * 8


# ── 4. The hand-written retraction must quote the CURRENT aggregate ──────────

def test_curated_retraction_quotes_the_reproduced_total(bench_md, bench_json):
    """The curated region is preserved verbatim across regenerations — which is
    exactly why it can go stale. Pin the one number it quotes."""
    m = re.search(
        r"Aggregate quoted in this retraction:\*\*\s*`(-?\d+\.\d+)%`", bench_md
    )
    assert m, (
        "The curated retraction no longer declares the aggregate it quotes. It "
        "must contain a line of the form: **Aggregate quoted in this "
        "retraction:** `-NN.NN%` so this guard can verify it."
    )
    assert float(m.group(1)) == pytest.approx(
        bench_json["headline"]["total_save_pct_vs_greedy"], abs=PCT_TOL
    ), (
        "The hand-written retraction quotes a stale aggregate. Update the text "
        "inside the CURATED markers to match the regenerated §A TOTAL."
    )


def test_retracted_run_id_4_figures_are_gone(bench_md):
    """−44.66% was retracted repo-wide; it must not reappear in this doc."""
    for stale in ("44.66", "33.91"):
        assert stale not in bench_md, (
            f"{stale!r} is a retracted run_id=4 figure and must not appear in "
            f"BENCHMARK_RESULTS.md."
        )


# ── 5. BENCHMARK_VOLUME_CURVE.md vs volume_sweep.json ────────────────────────

def _pooled_from_sweep(curve_json: Dict[str, Any]) -> Dict[int, Dict[str, float]]:
    """Recompute the pooled curve under the rule the document states:

    pooled = (Σ greedy − Σ milp_matched) / Σ greedy over the BOMs feasible at
    that multiplier in the DEDUPED offer pool, EXCLUDING points where greedy's
    plan orders more units than exist (those plans are not executable).
    """
    agg: Dict[int, Dict[str, float]] = {}
    for entry in curve_json["boms"].values():
        for point in entry.get("points", []):
            arms = point.get("arms", {})
            greedy, milp = arms.get("greedy", {}), arms.get("milp_matched", {})
            if not (greedy.get("feasible") and milp.get("feasible")):
                continue
            if greedy.get("stock_violations"):
                continue
            slot = agg.setdefault(
                int(point["multiplier"]), {"greedy": 0.0, "milp": 0.0, "n": 0.0}
            )
            slot["greedy"] += greedy["total_cost"]
            slot["milp"] += milp["total_cost"]
            slot["n"] += 1
    for slot in agg.values():
        slot["saving_pct"] = (
            (slot["greedy"] - slot["milp"]) / slot["greedy"] * 100.0
            if slot["greedy"]
            else 0.0
        )
    return agg


def test_volume_curve_pooled_table_matches_sweep_json(curve_md, curve_json):
    pooled = _pooled_from_sweep(curve_json)
    assert pooled, "volume_sweep.json produced no feasible pooled points"

    rows = _rows(curve_md, ["multiplier", "pooled saving"])
    assert rows, "The corrected-volume-curve table is missing"

    checked = 0
    for cells in rows:
        mult = _num(cells[0])
        if mult is None:
            continue
        key = int(mult)
        assert key in pooled, (
            f"The curve table has a {key}x row that volume_sweep.json does not "
            f"support (feasible multipliers: {sorted(pooled)})"
        )
        exp = pooled[key]
        assert _num(cells[1]) == pytest.approx(exp["n"], abs=0.5), (
            f"{key}x: doc says {cells[1]} BOMs feasible, sweep says {exp['n']:.0f}"
        )
        assert _num(cells[2]) == pytest.approx(exp["greedy"], abs=CURVE_MONEY_TOL), (
            f"{key}x: doc greedy ${cells[2]} != sweep ${exp['greedy']:.0f}"
        )
        assert _num(cells[3]) == pytest.approx(exp["milp"], abs=CURVE_MONEY_TOL), (
            f"{key}x: doc MILP ${cells[3]} != sweep ${exp['milp']:.0f}"
        )
        assert _num(cells[4]) == pytest.approx(exp["saving_pct"], abs=PCT_TOL), (
            f"{key}x: doc pooled saving {cells[4]} != recomputed "
            f"{exp['saving_pct']:.2f}%. Re-run `python -m seeds.run_volume_sweep`."
        )
        checked += 1

    assert checked == len(pooled), (
        f"The curve table documents {checked} multipliers but volume_sweep.json "
        f"has {len(pooled)} feasible ones — a row was dropped or added by hand."
    )


def test_volume_curve_feasibility_ceilings_match_sweep_json(curve_md, curve_json):
    """The stock-ceiling table is the doc's honesty about cohort drift."""
    rows = _rows(curve_md, ["max multiplier", "base units"])
    assert rows, "The feasibility-ceiling table is missing"
    boms = curve_json["boms"]
    for cells in rows:
        name = _plain(cells[0])
        assert name in boms, f"Ceiling table lists unknown BOM {name!r}"
        entry = boms[name]
        assert _num(cells[1]) == pytest.approx(entry["base_total_units"], abs=0.5), (
            f"{name}: doc base units {cells[1]} != sweep {entry['base_total_units']}"
        )
        assert _num(cells[2]) == pytest.approx(
            entry["stock_ceiling_multiplier_all_offers"], abs=0.5
        ), (
            f"{name}: doc max multiplier {cells[2]} != sweep "
            f"{entry['stock_ceiling_multiplier_all_offers']}"
        )
    assert {_plain(c[0]) for c in rows} == set(boms), (
        "The ceiling table must cover every BOM in volume_sweep.json"
    )


# ── 6. Provenance is present on every artifact ───────────────────────────────

@pytest.mark.parametrize("path", [BENCH_JSON, CURVE_JSON], ids=lambda p: p.name)
def test_json_artifacts_carry_provenance(path):
    payload = json.loads(_load(path))
    prov = payload.get("provenance")
    assert isinstance(prov, dict), (
        f"{path.name} has no top-level 'provenance' block. Stamp one with "
        f"seeds.provenance.build_provenance()."
    )
    for key in ("generated_at_utc", "generator", "git", "inputs", "python"):
        assert key in prov, f"{path.name} provenance is missing {key!r}"
    git = prov["git"]
    assert git.get("commit"), f"{path.name} provenance records no commit SHA"
    # A dirty tree must be flagged loudly, never silently suffixed.
    if git.get("dirty"):
        assert git.get("warning"), (
            f"{path.name} was generated from a dirty tree but carries no warning "
            f"— that is the exact failure seeds/provenance.py exists to prevent."
        )
    assert prov["inputs"], f"{path.name} provenance hashes no input files"
    for label, meta in prov["inputs"].items():
        assert meta.get("sha256"), f"{path.name}: input {label!r} has no sha256"


@pytest.mark.parametrize("path", [BENCH_MD, CURVE_MD], ids=lambda p: p.name)
def test_markdown_artifacts_render_provenance(path):
    md = _load(path)
    assert "## Provenance" in md, (
        f"{path.name} does not render a Provenance section. Generators must emit "
        f"seeds.provenance.provenance_markdown(prov)."
    )
    assert re.search(r"\*\*Commit:\*\*\s*`[0-9a-f]{7,40}`", md), (
        f"{path.name}'s Provenance section records no commit SHA"
    )


# ── 7. The path bug that caused all of this ──────────────────────────────────

@pytest.mark.parametrize("module", ["run_benchmark.py", "run_volume_sweep.py"])
def test_generators_write_repo_root_underscored_paths(module):
    """Inspect STRING LITERALS only (via ast), so the historical explanation of
    the bug can stay in the comments without tripping its own regression guard."""
    import ast

    src_path = REPO_ROOT / "backend" / "seeds" / module
    tree = ast.parse(src_path.read_text())
    literals = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    # Docstrings are prose, not paths — exclude the module/def/class docstrings.
    docstrings = {
        ast.get_docstring(n)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    code_literals = [s for s in literals if s not in docstrings]

    for s in code_literals:
        assert "BENCHMARK-RESULTS" not in s, (
            f"{module} has a string literal referencing the HYPHENATED filename "
            f"({s!r}). The canonical committed artifact is "
            f"docs/BENCHMARK_RESULTS.md (underscore); writing the hyphenated name "
            f"silently produces a second, never-read file."
        )
        # Only literals that actually LOOK like a path — a log message that
        # happens to start with "docs/…" is not a filesystem write.
        looks_like_path = (
            " " not in s.strip() and s.endswith((".md", ".json"))
        )
        assert not (s.startswith("docs/") and looks_like_path), (
            f"{module} builds a CWD-relative docs path again ({s!r}). Anchor "
            f"output on REPO_ROOT (as seeds/run_forecast_backtest.py does) so "
            f"`cd backend && python -m seeds.<module>` cannot create a stray "
            f"backend/docs/ directory."
        )


@pytest.mark.parametrize(
    "module_name", ["seeds.run_benchmark", "seeds.run_volume_sweep"]
)
def test_generator_output_paths_resolve_under_repo_docs(module_name):
    """The functional half of the guard: every module-level Path constant that
    names a .md/.json artifact must resolve inside the repo's own docs/, so the
    working directory cannot change where the file lands."""
    import importlib

    mod = importlib.import_module(module_name)
    expected_dir = (REPO_ROOT / "docs").resolve()

    found = 0
    for attr in dir(mod):
        value = getattr(mod, attr)
        if not isinstance(value, Path):
            continue
        if value.suffix not in (".md", ".json"):
            continue
        found += 1
        assert value.is_absolute(), (
            f"{module_name}.{attr} = {value} is a RELATIVE path — where it lands "
            f"depends on the working directory."
        )
        assert value.resolve().parent == expected_dir, (
            f"{module_name}.{attr} resolves to {value.resolve().parent}, not "
            f"{expected_dir}. That is how a stray backend/docs/ gets created."
        )

    docs_attr = getattr(mod, "DOCS", None)
    assert isinstance(docs_attr, Path) and docs_attr.resolve() == expected_dir, (
        f"{module_name} must expose DOCS anchored on the repo root "
        f"(got {docs_attr!r})."
    )


def test_no_stray_backend_docs_directory():
    stray = REPO_ROOT / "backend" / "docs"
    assert not stray.exists(), (
        f"{stray} exists — a generator is writing docs relative to the working "
        f"directory again. Delete it and anchor the path on REPO_ROOT."
    )
