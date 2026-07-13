# The 44.7% benchmark number is an artifact. Here is the proof.

**Generated:** 2026-07-13 · **Script:** `backend/seeds/run_volume_sweep.py` · **Data:** `docs/volume_sweep.json`
**Hardware:** arm64 / Darwin 25.5.0 · **Solver:** OR-Tools CP-SAT, `num_search_workers=1`, 5s limit
**Runtime:** 0.8s for the full sweep (10 BOMs × 13 multipliers × 3 arms × 2 offer pools)

---

## Headline finding

The project's benchmark claims the CP-SAT MILP is **44.7% cheaper than a greedy baseline**, with
`iot_sensor_node` quoted at **71.75% saved**. We reproduce those numbers exactly (44.66% / 72.4%).

**They are fee arithmetic, not optimization.**

The greedy baseline picks `min(price_usd)` per BOM line, so it is *the component-cost minimum by
construction* — the MILP can never beat it on component cost, and in fact loses to it on component
cost in **all 10 of 10 BOMs**. Every dollar the MILP "saves" comes from avoiding fixed,
**per-supplier** charges: `LTL_BASE_FEE_USD = $75` (domestic) and `AIR_FREIGHT_BASE_USD = $150`
(international), each scaled by `transport_penalty_scale = 1.5`.

At the benchmark's toy volumes (4 BOM lines, quantities 1-4, **5-9 units total**) those fees are
larger than the parts. On `iot_sensor_node` the components cost **$6.96**; consolidating 3 suppliers
into 1 avoids **$337.50** of fees. That is the 71.75%.

The fee saving is roughly **constant in volume** ($112.50 per supplier avoided). Component cost grows
**linearly** in volume. So the savings *percentage* must decay ~1/volume — and it does:

| BOM volume | Savings % (aggregate) | Of which: fixed supplier fees |
|-----------:|----------------------:|------------------------------:|
| 1× (5-9 units)   | **47.7%** | **116%** *(fees exceed the entire saving)* |
| 10×  | 24.8% | 111% |
| 50×  | 8.3%  | 100% |
| 250× | 6.7%  | 15% |
| 1,000× | 2.8% | 6% |
| 5,000× | 2.4% | 2% |

**At production scale this optimizer's cost edge is noise.** Under a corrected freight model (below)
it falls to **0.68%** — statistically indistinguishable from just buying the cheapest part every time.

---

## The decomposition: where the 44.7% actually comes from

At 1× volume, aggregated across all 10 BOMs (deduplicated offer pool, balanced strategy):

| Component of the saving | Amount |
|---|---:|
| Avoided fixed per-supplier fees ($75 LTL / $150 air, ×1.5) | **+$3,863** |
| Variable freight (weight × distance) | +$24 |
| **Component cost** | **−$561** ← *the MILP pays MORE for parts* |
| **Total saving** | **$3,326 (47.7%)** |

**The fixed fees account for 116% of the saving.** The MILP overpays for components by $561 and
funds that overpayment — plus the entire headline number — out of $3,863 of avoided supplier fees.
Supplier count across the 10 BOMs drops from **33 (greedy) → 14 (MILP)**. 19 suppliers avoided ×
~$112.50–$225 per supplier ≈ the entire "win".

This is not the optimizer finding cheaper parts. It is the optimizer noticing that the cost model
charges $75 every time you talk to a new distributor.

### Per-BOM, at 1× volume

| BOM | greedy $ | MILP $ | save % | suppliers | fee saving $ | component saving $ |
|---|---:|---:|---:|:---:|---:|---:|
| automotive_ecu | 722.40 | 157.11 | 78.3% | 4→1 | 568 | −8 |
| iot_sensor_node | 466.39 | 128.60 | **72.4%** | 3→1 | 342 | −6 |
| pcb_power_supply | 356.55 | 132.35 | 62.9% | 3→1 | 229 | −8 |
| rf_transceiver_module | 586.32 | 251.97 | 57.0% | 3→2 | 340 | −6 |
| audio_dsp_board | 708.79 | 373.94 | 47.2% | 4→2 | 342 | −10 |
| smart_meter | 783.46 | 427.99 | 45.4% | 3→1 | 454 | −99 |
| medical_monitoring_device | 583.45 | 323.21 | 44.6% | 3→1 | 342 | −86 |
| industrial_motor_driver | 731.36 | 416.09 | 43.1% | 3→1 | 454 | −139 |
| robotics_servo_driver | 1088.12 | 649.03 | 40.4% | 4→1 | 568 | −135 |
| drone_flight_controller | 951.99 | 792.26 | 16.8% | 3→3 | 225 | −65 |

Note the last column: **the component saving is negative in every single BOM.** That is not a bug,
it is arithmetic — greedy minimizes component cost by definition.

---

## The retraction: `iot_sensor_node`, the 71.75% case

| Multiplier | Units | greedy $ | MILP $ | **Savings %** | Fee share of saving | Suppliers |
|---:|---:|---:|---:|---:|---:|:---:|
| 1× | 5 | 466.39 | 128.60 | **72.4%** | 101% | 3→1 |
| 2× | 10 | 476.78 | 142.70 | 70.1% | 102% | 3→1 |
| 5× | 25 | 507.96 | 185.00 | 63.6% | 106% | 3→1 |
| 10× | 50 | 559.92 | 255.51 | 54.4% | 112% | 3→1 |
| 25× | 125 | 715.81 | 467.02 | 34.8% | 137% | 3→1 |
| 50× | 250 | 975.62 | 774.44 | 20.6% | 113% | 3→2 |
| 100× | 500 | 1,495.24 | 1,228.48 | 17.8% | 43% | 3→2 |
| 250× | 1,250 | 3,054.09 | 2,558.94 | 16.2% | 23% | 3→2 |
| 500× | 2,500 | 6,265.47 | 5,329.82 | 14.9% | 0% | 3→3 |
| 1,000× | 5,000 | 12,074.93 | 10,952.65 | 9.3% | 0% | 3→3 |
| 5,000× | 25,000 | 61,344.42 | 59,335.67 | 3.3% | 11% | 4→3 |
| 10,000× | 50,000 | 122,005.84 | 118,215.34 | **3.1%** | 6% | 4→3 |

**72.4% → 3.1%.** The absolute dollar saving barely moves at low volume ($337.79 at 1×, $304.41 at
10×) — because it *is* the fee, and the fee doesn't care how many units you buy. Only the denominator
grows.

We are retracting "71.75% cheaper." The defensible statement is: *on a 5-unit prototype BOM the MILP
avoids $337 of supplier onboarding fees; at 50,000 units that advantage is ~3% and mostly freight.*

---

## The crossover

Under the **shipped** cost model, aggregate savings fall below 10% at **~50× volume (250-400 units)**
and then plateau at **2-3%**. They never quite reach 1%.

That plateau is itself a second artifact. `_transport_cost_by_did()` (`sourcing.py`) charges **every
opened supplier** freight for a *representative full-BOM shipment*:

```python
avg_demand = sum(b.quantity for b in bom) / max(len(bom), 1)
avg_weight_kg = avg_demand * AVG_KG_PER_UNIT
for did in all_distributors:
    cost = LTL_BASE + cwt * miles * LTL_RATE     # charged per SUPPLIER
```

The charge does not depend on how much that supplier actually ships. Splitting a BOM across 3
suppliers therefore **triples** the variable freight instead of dividing it among them — so
consolidation keeps paying off linearly in volume, and the savings curve never converges to zero.

Re-scoring both arms with freight **allocated by actual shipped weight** (keeping the per-stop base
fee, which is real), applied identically to greedy and the MILP:

| Multiplier | Shipped model | Weight-allocated freight |
|---:|---:|---:|
| 1× | 47.7% | 47.2% |
| 10× | 24.8% | 23.1% |
| 50× | 8.3% | 7.2% |
| 250× | 6.7% | 6.1% |
| 1,000× | 2.8% | 4.0% |
| 2,500× | 2.2% | 2.0% |
| 5,000× | 2.4% | **0.94%** |
| 10,000× | 3.5% | **0.68%** |

**Crossover: the MILP's cost advantage drops below 1% at ~5,000× volume (25,000-60,000 units).**

Individual BOMs get there sooner. `rf_transceiver_module` hits **exactly 0.00%** from 100× onward —
greedy and the MILP converge on the *identical plan*. `medical_monitoring_device` reaches 0.15% at
5,000×.

---

## Two bugs found while doing this

Neither was patched. Fixing the solver to make the MILP look better is exactly the thing this exercise
exists to catch. They are reported, not quietly repaired.

### 1. Duplicate-offer variable collision (`sourcing.py`, `_build_and_solve`) — **production bug**

CP-SAT decision variables are keyed on `(component_id, distributor_id)`:

```python
key = (b.component_id, o.distributor_id)
x[key] = model.NewBoolVar(...)      # duplicates OVERWRITE
q[key] = model.NewIntVar(0, max(upper, 0), ...)
```

But the offer table contains **509 duplicated `(component, distributor)` pairs** database-wide (41 of
them inside the 10 benchmark BOMs) — price-break tiers from the same distributor. When a distributor
has *k* offers for one component, the same `q[key]` variable is:

* **summed k times** in the demand constraint → `k·q == demand`, which is **INFEASIBLE whenever
  `demand % k != 0`** (we observed spurious infeasibility on `automotive_ecu` at 250× and
  `rf_transceiver_module` at 5,000×), and
* **priced k times** in the objective → the unit price is charged as the *sum of the k tier prices*.
  `PCM4202DBT` at distributor 28 costs **$11.35 + $11.35 + $7.28 = $29.98/unit** in the model instead
  of $7.28.

The greedy baseline is unaffected (it scans a flat list and takes `min(price)`). So on any BOM
touching a duplicated pair, **the MILP competes against a corrupted model and can lose to greedy** —
which it did, before we controlled for this. A corrupted MILP losing to greedy is a bug artifact, not
a finding. All primary numbers above use a de-duplicated pool (one offer per component/distributor —
the cheapest, which is all the variable keying can represent), applied **identically to every arm**.

**This affects production sourcing, not just the benchmark.** It should be fixed by keying variables
on the offer, not on `(component, distributor)`.

### 2. Freight replicated per supplier rather than allocated (`_transport_cost_by_did`)

Described under *The crossover* above. Inflates the value of consolidation at every volume, and is the
sole reason the savings curve plateaus at 2-3% instead of converging to zero.

---

## Feasibility ceilings — what the data can actually support

Stock is a hard cap in the MILP (`q ≤ stock`). We computed each BOM's maximum feasible multiplier from
total available stock per line and swept only within it. **The snapshot's stock levels cannot support
production volumes for most BOMs:**

| BOM | Base units | Max multiplier | Max total units | Duplicated offer pairs |
|---|---:|---:|---:|---:|
| pcb_power_supply | 6 | 22,051 | 132,306 | 0 |
| iot_sensor_node | 5 | 18,758 | 93,790 | 2 |
| rf_transceiver_module | 4 | 7,912 | 31,648 | 3 |
| medical_monitoring_device | 8 | 6,175 | 49,400 | 6 |
| audio_dsp_board | 7 | 2,430 | 17,010 | 3 |
| automotive_ecu | 7 | 92 | 644 | 7 |
| smart_meter | 4 | 34 | 136 | 6 |
| industrial_motor_driver | 7 | 11 | 77 | 3 |
| drone_flight_controller | 7 | 7 | 49 | 7 |
| robotics_servo_driver | 9 | **2** | **18** | 4 |

Half the BOMs cap out below 100 units. `robotics_servo_driver` cannot be built more than **twice**
from this data. BOMs surviving at each multiplier: **10 at 1×, 7 at 10×, 5 at 50×-1,000×, 2 at
10,000×.** The high-volume aggregate is therefore a *different, smaller* BOM set than the low-volume
one — it is not a like-for-like cohort, and should not be read as one.

`audio_dsp_board` has **zero domestic stock** (`domestic-only ceiling = 0`), which is why the existing
benchmark's domestic-only MILP arm cannot solve it and skips it (9 of 10 BOMs run). That is expected,
not a bug.

### Greedy's plans become physically impossible at scale

`solve_sourcing_greedy` falls back to "cheapest offer with *any* stock" when no single offer covers the
line. At high volume this produces plans that **order more units than exist**: greedy assigned 2,500
units of `AD7934BRUZ` from an offer holding **1 unit**. Those points are flagged
(`arms.greedy.stock_violations`) and **excluded from every number in this document** — greedy cannot be
allowed to "win" with a plan that cannot be executed. Every case where the MILP appears to lose to
greedy is one of these.

---

## What the MILP is still genuinely good for

The cost story is over: **at production volume the MILP's cost edge is ~0-1%, and at prototype volume
it is a fixed-fee consolidation trick that a two-line heuristic would also find.** Being honest about
that, three things remain real:

1. **It produces executable plans.** Greedy does not. Greedy's fallback happily orders 2,500 units from
   a distributor holding 1. The MILP enforces `q ≤ stock` and MOQ floors as hard constraints, so its
   plan can actually be placed. At 100×+ volume this is the difference between a purchase order and a
   fiction — and it is worth more than 2% of landed cost.
2. **It can split a BOM line across distributors.** Greedy structurally cannot (one offer per line). At
   ≥100× the MILP splits 1-4 lines across suppliers to stay inside stock caps. This is *why* it stays
   feasible where greedy doesn't.
3. **It optimizes a multi-objective tradeoff** (cost/time/carbon weights, MOQ, domestic-sourcing
   constraints, risk surcharges). Greedy optimizes cost and nothing else. The resilience results
   (graph-aware vs blind MILP, `cvar_95` under disruption) are a separate story on a separate axis and
   are **not** affected by anything in this document.

What we should stop claiming: that the optimizer delivers a large landed-cost saving. It does not, at
any volume a real buyer would order.

---

## Reproduce

```bash
cd backend
source venv/bin/activate
python -m seeds.run_volume_sweep      # ~1 second
```

Writes `docs/volume_sweep.json` (full per-BOM/per-multiplier/per-arm results with cost decomposition,
supplier counts, solver status, feasibility ceilings, and both offer pools).

**Arms** — all three scored through the *same* `landed_cost_breakdown()`, no cost model reimplemented:

| Arm | Solver | Offer pool |
|---|---|---|
| `greedy` | `solve_sourcing_greedy`, `us_only=False` | as the published benchmark calls it |
| `milp_matched` | `solve_sourcing`, `us_only=False` | **PRIMARY** — same pool as greedy, a fair fight |
| `milp_bench` | `solve_sourcing`, `us_only=True` | reproduces the published benchmark's MILP arm |

The published benchmark compares a **domestic-only MILP** against an **international-inclusive greedy**
(`balanced.us_only_sourcing = True` overrides the caller's `us_only=False` inside `optimize_bom`, while
`solve_sourcing_greedy` is called with `us_only=False` directly). The arms do not see the same offer
pool. `milp_matched` fixes that; `milp_bench` reproduces the original. Our `milp_bench` at 1× yields
**44.66%**, matching the published 44.7% — confirming we are measuring the same thing before we take it
apart.

**Solver hygiene:** of 326 MILP solve attempts, 297 were feasible and **all 297 returned `OPTIMAL`** —
none hit the 5s time limit (max solve: 15 ms). The 29 infeasible attempts are the genuine stock/MOQ
ceilings and the duplicate-offer collisions documented above. No result in this document is a timeout
artifact.
