# Benchmark Results — run_id=6

> **This file is generated** by `python -m seeds.run_benchmark`. Everything outside the `CURATED:BEGIN` / `CURATED:END` HTML-comment markers is overwritten on every run; everything inside them is preserved verbatim. Put prose, retractions and caveats there.

**Generated:** 2026-08-28 13:58 UTC
**Coverage:** **9 of 10 BOMs** — 1 excluded, see §0 for the reason.
**Rows:** 72 (9 BOMs × 8 rows: 4 arms×nominal + 2 milp×2 disruptions)
**Seed:** 42 · **Strategy:** balanced · **Holdout:** benchmark IS the holdout

Every arm's selection is scored through the SAME `landed_cost_breakdown` cost function, so MILP-vs-greedy is a fair comparison. Greedy arms are pure sourcing baselines with no route model — their ETA/CO2 are omitted; cost, supplier count and tail-risk are their story.

<!-- CURATED:BEGIN -->
> ### ⚠️ RETRACTION — do not quote the `save%` column as a headline
>
> **Aggregate quoted in this retraction:** `-47.25%` — this must equal
> `headline.total_save_pct_vs_greedy` in
> [`benchmark_results.json`](benchmark_results.json), and
> `tests/test_benchmark_docs_match_artifacts.py` fails the build if it drifts.
>
> That aggregate is **arithmetically correct and substantively meaningless.** Greedy is
> the component-cost minimum *by construction*, so the MILP can never beat it on
> component cost — it can only win on flat **per-supplier** freight fees
> (`LTL_BASE_FEE_USD = $75` domestic / `AIR_FREIGHT_BASE_USD = $150` international, each
> ×`transport_penalty_scale`). These BOMs are 4 parts / 4–9 units, so those fees dwarf
> the parts: the MILP pays **more** for components and funds it entirely from avoided
> supplier fees. Table A's own last column is the tell — supplier count collapses
> **29 → 12** across the 9 BOMs, and 17 avoided suppliers × ~$112.50 *is* the "saving".
>
> At benchmark scale that saving is a constant (`fee × suppliers avoided`), not a rate,
> so it decays as volume grows — to **single digits** at any volume a real buyer would
> order. See **[BENCHMARK_VOLUME_CURVE.md](BENCHMARK_VOLUME_CURVE.md)** for the full
> decomposition and the measured decay curve; that document, not this one, is the
> authority on what the optimizer is worth. What survives at production volume is *not*
> the fee trick: it is a genuine low-single-digit edge from routing volume by
> **price + freight** rather than by unit price.
>
> **Second retraction — resilience is not free.** §B used to assert that the graph-aware
> arm "spends ~0 extra nominally". Run 5 shows that is false: its nominal cost premium
> runs from **+0.00% to +82.16%** (median **+12.25%**), because `require_dual_source`
> forbids exactly the single-supplier consolidation that makes the blind arm cheap. Nor
> does it always help — of 18 (BOM × scenario) cells, cascade-risk **worsens in 2**
> (`industrial_motor_driver` and `pcb_power_supply`, both under broad stress). The real,
> defensible pattern is narrower than "graph-aware is safer": it is that graph-awareness
> pays off under a **targeted** outage of a high-betweenness distributor (7 of 9 BOMs
> improve) and is roughly a coin-flip under undirected macro stress.
>
> **Provenance caveats for this specific run.** (a) `audio_dsp_board` is **excluded** —
> the blind MILP arm is INFEASIBLE on it (it has zero domestic stock, and the balanced
> strategy's `us_only_sourcing` makes that arm domestic-only). The benchmark is
> **9 of 10 BOMs**, and §0 now says so in the artifact instead of only in a log line.
> (b) This run read a *snapshot copy* of `backend/supply_chain.db` rather than the live
> file, because other work was writing to the database concurrently; the exact bytes are
> pinned by sha-256 in the Provenance section at the foot of this file.
<!-- CURATED:END -->

## 0) BOM inclusion — 9 of 10 catalog BOMs are in the tables below

An excluded BOM is one where at least one of the four arms failed to solve. The 8-row-per-BOM invariant is all-or-nothing, so a BOM that cannot be scored on every arm is dropped from **all** tables rather than compared unevenly. Exclusions are published here; they are not just a log line.

| BOM | in benchmark? | rows | offers | reason |
|-----|:-------------:|-----:|-------:|--------|
| iot_sensor_node | ✅ included | 8 | 44 | all 4 arms solved |
| drone_flight_controller | ✅ included | 8 | 75 | all 4 arms solved |
| pcb_power_supply | ✅ included | 8 | 20 | all 4 arms solved |
| industrial_motor_driver | ✅ included | 8 | 65 | all 4 arms solved |
| rf_transceiver_module | ✅ included | 8 | 53 | all 4 arms solved |
| automotive_ecu | ✅ included | 8 | 108 | all 4 arms solved |
| medical_monitoring_device | ✅ included | 8 | 65 | all 4 arms solved |
| smart_meter | ✅ included | 8 | 81 | all 4 arms solved |
| robotics_servo_driver | ✅ included | 8 | 65 | all 4 arms solved |
| audio_dsp_board | ❌ **EXCLUDED** | 0 | 46 | MILP arm `milp_blind` (graph_aware=False) raised RuntimeError: Sourcing MILP infeasible (status=INFEASIBLE) |

## A) Value of optimization — MILP vs greedy baselines (nominal)

| BOM | greedy $ | greedy_add $ | milp $ | save% vs greedy | save% vs greedy_add | suppliers greedy→milp |
|-----|---------:|-------------:|-------:|----------------:|--------------------:|:---------------------:|
| automotive_ecu | 725.60 | 498.79 | 159.56 | -78.01% | -68.01% | 4→1 |
| drone_flight_controller | 952.57 | 952.57 | 794.72 | -16.57% | -16.57% | 3→3 |
| industrial_motor_driver | 732.04 | 732.04 | 421.68 | -42.40% | -42.40% | 3→1 |
| iot_sensor_node | 467.98 | 351.47 | 132.59 | -71.67% | -62.28% | 3→1 |
| medical_monitoring_device | 589.62 | 369.96 | 329.59 | -44.10% | -10.91% | 3→1 |
| pcb_power_supply | 356.85 | 241.34 | 137.13 | -61.57% | -43.18% | 3→1 |
| rf_transceiver_module | 586.69 | 586.69 | 252.46 | -56.97% | -56.97% | 3→2 |
| robotics_servo_driver | 1088.92 | 753.94 | 656.22 | -39.74% | -12.96% | 4→1 |
| smart_meter | 783.84 | 783.84 | 431.12 | -45.00% | -45.00% | 3→1 |
| **TOTAL** | 6284.11 | 5270.64 | 3315.07 | -47.25% | -37.10% | — |

*Negative save% = MILP is cheaper (the win). MILP jointly optimizes component price, per-distributor transport and consolidation, so it consolidates orders the myopic greedy baseline cannot.*

## B) Value of resilience — graph-aware MILP vs blind MILP

`plan_cascade_risk` = 1 − P50 fulfillment of the selected plan; `cvar_95` = mean emergency-cost multiplier of the worst-5% scenarios. A **positive** reduction means the graph-aware arm is the safer plan.

**What this run actually shows.** Resilience is **not** free here: the graph-aware arm's nominal cost premium is median **+12.2%**, range **+0.0% to +82.2%** across the 9 BOMs — it buys tail-risk protection with real money, because `require_dual_source` forbids the single-supplier consolidation that makes the blind arm cheap. And it does not win everywhere: of 18 (BOM × scenario) cells, cascade-risk improves in **8**, is unchanged in **8**, and gets **worse in 2**; CVaR-95 improves in **6** and worsens in **0**. Read the per-row signs below rather than the headline.

| BOM | scenario | nominal cost premium | cascade_risk (blind→graph, ↓) | cvar_95 (blind→graph, ↓) |
|-----|----------|---------------------:|:-----------------------------:|:------------------------:|
| automotive_ecu | stress | +69.65% | 0.5000→0.2500 (+0.2500) | 1.1500→1.1372 (+0.0128) |
| automotive_ecu | targeted | +69.65% | 0.5000→0.2500 (+0.2500) | 1.1500→1.1155 (+0.0345) |
| drone_flight_controller | stress | +0.00% | 0.5000→0.5000 (+0.0000) | 1.1418→1.1418 (+0.0000) |
| drone_flight_controller | targeted | +0.00% | 0.5000→0.5000 (+0.0000) | 1.1148→1.1148 (+0.0000) |
| industrial_motor_driver | stress | +11.82% | 0.0000→0.7500 (-0.7500) | 1.1500→1.1500 (+0.0000) |
| industrial_motor_driver | targeted | +11.82% | 1.0000→0.5000 (+0.5000) | 1.1500→1.1193 (+0.0307) |
| iot_sensor_node | stress | +82.16% | 0.0000→0.0000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| iot_sensor_node | targeted | +82.16% | 1.0000→0.5000 (+0.5000) | 1.1500→1.1500 (+0.0000) |
| medical_monitoring_device | stress | +12.25% | 0.2500→0.2500 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| medical_monitoring_device | targeted | +12.25% | 1.0000→0.2500 (+0.7500) | 1.1500→1.1500 (+0.0000) |
| pcb_power_supply | stress | +75.99% | 0.0000→0.2500 (-0.2500) | 1.1500→1.1500 (+0.0000) |
| pcb_power_supply | targeted | +75.99% | 1.0000→0.0000 (+1.0000) | 1.1500→1.0600 (+0.0900) |
| rf_transceiver_module | stress | +0.00% | 0.5000→0.5000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| rf_transceiver_module | targeted | +0.00% | 0.5000→0.5000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| robotics_servo_driver | stress | +2.99% | 0.5000→0.5000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| robotics_servo_driver | targeted | +2.99% | 1.0000→0.2500 (+0.7500) | 1.1500→1.0885 (+0.0615) |
| smart_meter | stress | +24.55% | 0.5000→0.5000 (+0.0000) | 1.1500→1.1500 (+0.0000) |
| smart_meter | targeted | +24.55% | 0.5000→0.2500 (+0.2500) | 1.1500→1.0885 (+0.0615) |

*Annualization assumption: each BOM re-ordered ANNUAL_REORDERS=12×/yr (a stated modelling assumption, not measured cadence).*

## Reproduce

```bash
cd backend && source venv/bin/activate
python -m seeds.run_benchmark      # ~2-3 minutes
```

Writes this file and `docs/benchmark_results.json` (the machine-readable twin these tables are generated from). Both paths are anchored on the repo root, so the working directory does not matter.

## Provenance

- **Generated:** 2026-08-28T13:55:55Z (UTC)
- **Generator:** `seeds.run_benchmark`
- **Commit:** `6a33ad09b8e654c28c289b189b7e334df79c722c` — ⚠️ **DIRTY WORKING TREE.** UNCOMMITTED CHANGES: this artifact was generated from a working tree that did not match its git commit. Checking out the recorded SHA alone will NOT reproduce these numbers. Regenerate from a clean tree before treating them as published.
- **Input `database`:** `backend/supply_chain.db` · sha256 `ad2afcbed1edaf3f…`
- **Python:** 3.13.5 · macOS-26.5-arm64-arm-64bit-Mach-O

