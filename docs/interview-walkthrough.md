# Sub-Project A — Interview Walkthrough

A one-page whiteboard-ready explanation of the sourcing + routing +
cross-dock system. Target audience: supply chain / operations / data
science interview at McKinsey, BCG, Amazon Ops, Apple Ops.

## 1. Business framing

A US PCB manufacturer runs a production run of 50 wireless IoT sensor
nodes. The BOM contains 5 electronic components sourced from a market
of 92 distributors offering 8,176 competing price offers (real data —
a static 2024 snapshot originally sourced via Nexar/Octopart, redistributed
on HuggingFace under CC-BY-4.0). We need to decide *which distributor fills
each line*, and
*which route the pickup truck takes*, balancing cost, delivery time,
and carbon emissions.

## 2. Decision variables

- `x[c,d] ∈ {0,1}` — is component c sourced from distributor d?
- `q[c,d] ∈ ℤ≥0` — quantity
- `y[d] ∈ {0,1}` — is distributor d visited at all?

## 3. Constraints

- Demand coverage: Σ_d q[c,d] = demand[c]
- Stock cap: q[c,d] ≤ stock[c,d] · x[c,d]
- MOQ floor: q[c,d] ≥ moq[c,d] · x[c,d]
- Distributor linking: y[d] ≥ x[c,d]
- US-only filter: x[c,d] = 0 if distributor d is international

## 4. Objective function

Weighted sum scalarization (Marler & Arora 2004) over three
normalized objectives:

```
min  w_cost · cost_n + w_time · time_n + w_carbon · carbon_n
```

**Cost terms (all cited):**
- TL rate: $2.271/mi — ATRI 2023
- LTL base + per-cwt: $75 + $0.43/cwt·mi — FreightWaves SONAR 2023
- CO2: 161.8 g/ton-mi — EPA SmartWay 2023
- Holding cost: 25%/yr — Gartner 2022
- Ground speed: 800 km/day — BTS CFS 2022

**Strategy weight profiles:**
| Strategy | w_cost | w_time | w_carbon | Basis |
|---|---|---|---|---|
| Lowest Cost | 1.00 | 0.00 | 0.00 | Weber 1991 |
| Fastest | 0.15 | 0.80 | 0.05 | JIT / Toyota |
| Greenest | 0.25 | 0.05 | 0.70 | CDP Supply Chain |
| Balanced | 0.40 | 0.35 | 0.25 | Ghodsypour & O'Brien 1998 |

## 5. Why CP-SAT (not pure LP, not pure OR-Tools routing)

- Integer quantities (`q[c,d] ∈ ℤ`) make it a MILP, not LP
- Combinatorial supplier selection via `x[c,d] ∈ {0,1}`
- OR-Tools routing handles vehicle flow, not supplier selection
- CP-SAT treats linear integer programs as MILP-equivalent and is
  faster than CBC on small combinatorial problems
- Already a transitive dependency via OR-Tools routing

## 6. Pipeline

```
BOM → Outlier Filter → Stage 1 CP-SAT Sourcing →
Stage 2 TSP → Cross-Dock Evaluation → 4 RouteAlternatives
```

**Outlier filter:** Drop any offer where `price > 5 × median(price)`
for that MPN. One-sided (low discounts stay). Aberdeen Group 2020.

**Stage 1 (Sourcing MILP):** CP-SAT picks cheapest offers subject to
demand/stock/MOQ.

**Stage 2 (TSP):** OR-Tools routing over the selected distributors —
PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH, haversine distance matrix.

**Cross-dock:** Lagrangian relaxation of the Capacitated Facility
Location Problem (Daskin 2013, Ch. 4). With only 10 candidate hubs,
exact enumeration is trivially fast. A hub is chosen iff it beats
direct pickup by ≥5% on the weighted objective.

## 7. Why the four strategies diverge

- `cost`: dominated by component price (varies 3.8×–17× post-filter
  across distributors for the same MPN — this IS the lever)
- `time`: depends on distributor handling tier + ceiling(distance/800)
  — discrete days, not a distance scalar
- `carbon`: depends on actual shipment weight × distance — varies by
  SKU and quantity
- `cross-dock decision`: changes per strategy because the weighted
  objective differs — "fastest" avoids hubs (dwell time), "greenest"
  prefers them (tonne-miles reduction)

None of the three objectives is a scalar multiple of another, so
weighted-sum combinations produce genuinely distinct optima.

## 8. Extensions (Sub-Project B)

- Two-echelon joint MILP (facility + routing in one program)
- Time windows on distributor pickup
- Stochastic demand (Monte Carlo + robust optimization)
- OSRM driving distances instead of haversine
- Weather + traffic per-leg ETA adjustment
- Air freight as an explicit decision variable
