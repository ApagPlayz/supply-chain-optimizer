# Dollar-Denominated Impact Framing (P3)

Every abstract metric in this project is paired with a concrete financial
interpretation. This note documents how each dollar figure is derived, so the
numbers can be defended in an interview. **Real-data rule:** no dollar figure is
invented — each is computed from quantities already in the codebase, with any
conversion constant taken from a cited industry source and labeled as an
assumption.

---

## 1. CVaR-95 → "$X of procurement spend at risk"

**Metric.** CVaR-95 (`SimulationResult.cvar_95`, `backend/app/graph/simulation.py`)
is the *mean emergency-procurement cost multiplier over the worst-5% of the 1,000
Monte Carlo cascade-failure scenarios*. Each scenario inflates cost by
`1 + (unfulfillable / BOM_size) × 0.15` (15% emergency premium per unsourceable
line); CVaR-95 averages that multiplier across the worst-5% tail. It is ≥ 1.0.

**Dollar translation.**

```
procurement_spend_at_risk_usd = baseline_component_cost × (CVaR-95 − 1)
```

where `baseline_component_cost` is the sum of each BOM line's **average real
distributor offer price** (Nexar/Octopart). Subtracting 1 strips the baseline
bill so the figure is the *extra* dollars a tail disruption would add.

- **Backend:** computed per BOM in `_compute_baseline_metrics`
  (`backend/app/api/resilience.py`) and returned on all three resilience
  endpoints as `procurement_spend_at_risk_usd` (alongside `baseline_cvar_95`).
- **Benchmark:** aggregated across the 10 reference BOMs as
  `baseline_spend_at_risk_usd` = mean(`total_cost_usd × (mc_cvar_95 − 1)`) in
  `backend/app/api/benchmark.py`.
- **UI:** amber "Procurement Spend at Risk · CVaR-95" banner on the Resilience
  page; "Tail risk · CVaR-95 spend at risk" tile on the Benchmark page.

**Assumptions/citations.** None external. The only constant is the 15% emergency
premium, which already lives in `simulation.py` (`EMERGENCY_COST_PREMIUM`). The
figure is otherwise 100% data-derived.

---

## 2. Optimizer cost delta → "$Y saved per BOM run"

**Metric.** The benchmark compares the graph-aware optimizer to the baseline
optimizer over 10 reference BOMs (`backend/app/api/benchmark.py`).

**Dollar translation.**

```
cost_delta_usd = mean( graph_aware.total_cost_usd − baseline.total_cost_usd )
```

over the BOMs common to both arms. Negative ⇒ graph-aware is cheaper (money
saved). `total_cost_usd` is the real landed cost (component + transport + holding)
each optimizer run produced.

- **UI:** "Optimizer impact · $ / BOM run" tile on the Benchmark page.

**Honesty note.** This is intentionally surfaced as a *live, run-dependent* figure,
not a fixed marketing claim. On the current reference set the graph-aware vs
baseline delta sits near the ±2% noise floor (the page already flags this with a
"Low confidence" badge). The dollar tile reflects whatever the real run produced.

**Assumptions/citations.** None external — directly from run totals.

---

## 3. Forecast WAPE → "≈ N weeks of safety stock at $W carrying cost"

**Metric.** Walk-forward backtest ([FORECAST_BACKTEST.md](FORECAST_BACKTEST.md)) on
FRED `IPG3344S` (Industrial Production: Semiconductors): **Prophet WAPE = 4.8%** vs
**seasonal-naive WAPE = 8.7%** (skill score +45%).

**Dollar translation.** Forecast error drives the safety stock a buyer must hold to
hit a service level. Using WAPE as a σ/μ forecast-error proxy over the planning
horizon and a normal service factor `z`:

```
safety_stock_fraction ≈ z × WAPE          (fraction of horizon demand held as buffer)
weeks_of_buffer        ≈ z × WAPE × 12     (12-week forecast horizon)
```

With `z = 1.645` (95% service level, one-sided):

| Model | WAPE | Buffer (fraction) | Buffer (weeks of 12-wk horizon) |
|-------|-----:|------------------:|--------------------------------:|
| Prophet | 0.048 | 0.079 | ≈ 0.95 wk |
| Seasonal-naive | 0.087 | 0.143 | ≈ 1.72 wk |

Prophet's accuracy edge therefore **avoids ≈ 0.8 weeks of safety stock**.

Carrying-cost dollarization, per **$1M of annual component spend**:

```
1 week of demand as inventory = $1,000,000 / 52        ≈ $19,231
annual cost to carry that week  = 25% × $19,231         ≈ $4,808 / yr
saving from 0.8 fewer weeks     = 0.8 × $4,808          ≈ $3,700 / yr  per $1M spend
```

- **UI:** Component Browser (`SchedulerPage.tsx`) forecast sparkline/stockout
  tooltip.

**Assumptions/citations.**
- **Carrying cost 25%/yr** — reuses `ANNUAL_HOLDING_RATE = 0.25`
  (`backend/app/optimization/costs.py`), cited to **Gartner IT Supply Chain
  Benchmarks 2022** (electronics). Typical industry range 20–25%/yr (Richardson,
  HBR; APICS).
- **Service factor z = 1.645** (95%, one-sided) and WAPE-as-σ/μ proxy — standard
  safety-stock framing (Silver, Pyke & Peterson, *Inventory Management and
  Production Planning and Scheduling*).
- The per-$1M-spend figure is **illustrative and explicitly normalized** (the demand
  series is the FRED production index, not a dollar series), so it is expressed per
  unit of spend rather than as an invented absolute total.

---

## 4. Per-route holding cost (already dollar-denominated)

The checkout cost breakdown already shows a real holding-cost line
(`cost_breakdown.holding_cost`). P3 adds a tooltip documenting its basis:

```
holding_cost = component_value × 25%/yr × (lead_time_days / 365)
```

cited to the same Gartner 2022 rate (`holding_cost_usd` in `costs.py`).

---

## Summary of constants introduced/reused

| Constant | Value | Source | Status |
|----------|-------|--------|--------|
| Inventory carrying rate | 25%/yr | Gartner IT Supply Chain Benchmarks 2022 | **Reused** (`ANNUAL_HOLDING_RATE`) |
| Service factor z | 1.645 (95%) | Standard normal / Silver-Pyke-Peterson | New, labeled assumption |
| Emergency premium | 15%/unsourceable line | Existing `EMERGENCY_COST_PREMIUM` | Reused |

No new hardcoded dollar figures were introduced into the application logic; all
dynamic dollar values are computed from real BOM spend and real simulation output.
