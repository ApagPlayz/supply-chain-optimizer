---
phase: 06-interactive-resilience-dashboard
phase_number: 06
phase_name: Interactive Resilience Dashboard
phase_goal: Users can run "what if" scenarios interactively and see cascading supply chain impacts
version: 1.0
created_date: 2026-04-29
---

# Phase 6 Context: Interactive Resilience Dashboard

## Why This Phase

After completing Phases 1-5, the app has deep technical capabilities:
- Graph ML risk scoring (Phase 2)
- Live macro feeds (Phase 3)  
- Quantified benchmark comparisons (Phase 4)
- Demand forecasting (Phase 5)

**But:** All of this is backend plumbing. An interviewer cannot *see* or *interact* with it.

Phase 6 brings these capabilities to the surface by letting users **explore "what if" scenarios** in an intuitive, visual way. This transforms abstract algorithms into a narrative: "Here's how supply chain resilience works in practice."

## Key Audience

- **DS/ML interviewers** at Amazon, BCG, Google, UPS who want to see:
  - Can you think about supply chain as a graph resilience problem?
  - Can you quantify the cost of resilience?
  - Can you integrate multiple signals (graph, live data, forecasts)?
  - Can you build something that's actually useful?

## Three Core Scenarios

1. **Distributor Failure** (graph-based): "What if DigiKey goes down?"
   - Uses Phase 2 Monte Carlo cascade
   - Shows which BOMs break, rerouting options, cost/ETA delta
   
2. **Geopolitical Risk Spike** (live feed-based): "What if GPR index doubles?"
   - Overrides Phase 3 live feeds in real-time
   - Recalculates risk scores, shows component tier migrations
   
3. **Delivery Acceleration** (optimization-based): "Can I get this in 2 weeks instead of 4?"
   - Triggers new optimization run with tighter lead-time constraint
   - Shows which suppliers qualify, cost/risk impact

## Technical Foundation

Phase 6 assumes you have working:
- `POST /api/v1/graph/simulate` (Phase 2) — Monte Carlo cascade, returns P10/P50/P90
- `GET /api/v1/graph/metrics` (Phase 2) — real-time graph centrality scores
- `LiveDataCache` (Phase 3) — feeds can be overridden for scenario testing
- `GET /api/v1/benchmark/summary` (Phase 4) — baseline A/B comparison
- `GET /api/v1/forecasts/all` (Phase 5) — demand horizons
- `POST /api/v1/optimize/vrp` (existing) — BOM optimization with graph_aware flag

## Success Metric for Interviews

After demo, the interviewer should be able to:
1. Say "Imagine GPR spikes in the next 2 weeks" → you click a slider, watch scores change
2. Ask "What breaks if we lose our second-largest distributor?" → you click, see affected BOMs + rerouting options + cost impact
3. Say "We need to hit 2-week delivery" → you slide, see which suppliers can do it and what it costs

That's a technically impressive, scenario-driven narrative that's memorable.

## Interview Talking Points

- "The graph tells us which distributors are critical to supply chain resilience"
- "We overlay real geopolitical risk (GPR index, ACLED conflicts) to surface which regions/suppliers are exposed"
- "We quantify the cost of resilience — e.g., 'Adding a backup distributor costs 3% more but halves tail-risk'"
- "We use Monte Carlo simulation to understand distribution tails, not just means"
- "This is all integrated with demand forecasting so we can alert when a component might stock out"

## What Not To Do

- Don't over-engineer: Phase 6 is about **interactivity**, not perfection
- Don't add new ML models: use Phase 2-5 outputs as-is
- Don't rebuild the optimizer: use existing `/optimize/vrp` endpoint with new parameters
- Don't make it slow: cache results, show spinners, async loading is OK

## Phase 6 Scope (3 plans)

- **06-01**: API endpoints for three scenarios (distributor-failure, geopolitical-risk, delivery-target)
- **06-02**: ResiliencePage frontend with scenario selectors and delta cards
- **06-03**: Performance tuning, caching, docs, and interview prep narrative

---

## Next Steps

1. `/gsd-discuss-phase 06` — clarify UI/UX approach and scenario definitions
2. `/gsd-plan-phase 06` — break down into 3-4 specific tasks per plan
3. `/gsd-execute-phase 06` — build it
