# Roadmap: Electronics Supply Chain Optimizer — Interactive Resilience v2.0

## Milestone Overview (v2.0)

The v2.0 milestone transforms the technical foundation (Phases 1-5) into an **interactive, interview-ready demonstration** of supply chain resilience concepts. Phase 6 adds a resilience simulator that lets users explore trade-offs: what happens if a key distributor fails? What if geopolitical risk spikes? What does faster delivery cost in risk terms?

This phase makes the graph ML, live feeds, and forecasting work **visible and explorable**, turning backend algorithms into a compelling narrative about modern supply chain optimization.

---

## Phases

- [x] **Phase 1: Codebase Hardening** - Eliminate security vulnerabilities and orphaned pre-pivot artifacts (completed 2026-04-17)
- [x] **Phase 2: Graph ML Network Risk Engine** - NetworkX bipartite supply graph with centrality, Fiedler, k-core, HHI, Monte Carlo cascade (completed 2026-04-22)
- [x] **Phase 3: Live Data Feeds** - GPR, ACLED, IMF PortWatch, FRED freight signals with TTL caching (completed 2026-04-17)
- [x] **Phase 4: Benchmark Dashboard** - A/B comparison (graph-aware vs baseline) with Monte Carlo and Fiedler outputs (completed 2026-04-25)
- [x] **Phase 5: Prophet Demand Forecasting** - 12-week demand horizon and stock-out warnings on Scheduler page (completed 2026-04-29)
- [ ] **Phase 6: Interactive Resilience Dashboard** - Scenario explorer: "What if a distributor fails?" / "What if GPR spikes?" / "What if I need 2-week delivery?" with cost/risk/lead-time trade-off visualization

---

## Phase Details

### Phase 6: Interactive Resilience Dashboard

**Goal**: Users can run "what if" scenarios interactively, see cascading supply chain impacts in real-time, and understand the tradeoffs between cost, delivery speed, and resilience.

**Depends on**: Phase 2 (graph simulation), Phase 3 (live feeds), Phase 4 (benchmark framework)

**Requirements**: RESIL-01, RESIL-02, RESIL-03, RESIL-04, RESIL-05

**UI hint**: yes

**Success Criteria** (what must be TRUE):
  1. User opens ResiliencePage, selects a distributor (via dropdown or map click), clicks "Simulate Failure" → API returns which BOMs break, rerouting options, cost/ETA impact; frontend shows before/after cards with delta percentages
  2. Dropdown "Geopolitical Risk Scenario" (baseline, mild, severe) updates live feed override in real-time, recalculates risk scores, shows which components move to higher-risk tiers (color change in component list)
  3. Slider "Target Delivery (days): 4 → 2 → 1" triggers re-optimization, shows cost delta and list of suppliers who CAN meet the timeline (with inventory check) vs. those who cannot
  4. "Monte Carlo Cascade Resilience" card displays P10/P50/P90 fulfillment rates under each scenario (baseline, single-distributor-failure, GPR-spike) with a Recharts area chart
  5. ResiliencePage loads scenarios asynchronously; one slow scenario does NOT block others from rendering; users see a "recalculating..." spinner per scenario card

**Plans**: 3 plans
- 06-01: Scenario API endpoints — POST /simulate/distributor-failure, POST /simulate/geopolitical-risk, POST /simulate/delivery-target, all returning cost/ETA/risk deltas + affected BOM lists
- 06-02: ResiliencePage frontend — scenario selector cards (distributor dropdown, risk slider, delivery-days slider), before/after delta cards, Monte Carlo chart, responsive grid layout
- 06-03: Performance tuning + documentation — cache scenario results (1h TTL), add Otel tracing to slow paths, README with interview talking points

**Plan List**:
- [x] 06-01-PLAN.md — Scenario API endpoints (POST /distributor-failure, /geopolitical-risk, /delivery-target) with ScenarioCache model, Alembic migration, OpenTelemetry tracing
- [x] 06-02-PLAN.md — ResiliencePage UI with 3 scenario tabs, selector components (dropdown, sliders), delta cards, Monte Carlo chart, BOM impact table, async loading
- [x] 06-03-PLAN.md — Performance caching (1h TTL), background cleanup job, OpenTelemetry instrumentation, interview guide docs, API reference docs

---

## v2.0 Completion Criteria

- [ ] All 6 phases complete with code + tests
- [ ] User can run ≥3 distinct "what if" scenarios in <2s each
- [ ] Interview narrative: "Here's what our graph ML engine can tell you about supply chain resilience" (with demo)
- [ ] Deployed locally or staging with seed data ready for demo
