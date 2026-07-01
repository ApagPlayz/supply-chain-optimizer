---
name: project-state-jun2026
description: Current state of the supply chain optimization project as of June 2026 benchmark assessment
metadata:
  type: project
---

Project is production-ready at Phase 6 completion (June 2026). All 6 phases complete.

**What's built and working:**
- CP-SAT MILP sourcing optimizer (OR-Tools) with 4 distinct Pareto strategies (cost/time/carbon/balanced)
- TSP routing optimizer with OR-Tools
- Graph ML: Fiedler algebraic connectivity, betweenness centrality, PageRank, k-core, HHI on bipartite supply network (NetworkX)
- Monte Carlo cascade simulation (1,000 scenarios, SIR-style, P10/P50/P90/EVaR-95)
- 4 live data feeds: GPR index, ACLED conflict counts, IMF PortWatch congestion, FRED freight index
- Prophet demand forecasting (12-week horizon, FRED macro regressors, stockout warnings)
- ML lead-time prediction (4 competing models: Ridge, RF, GBT, MLP — auto-selects best RMSE)
- Macro stress regime detection (logistic regression on FRED, validated on 2021-22 chip shortage)
- Resilience scenario API: distributor-failure, geopolitical-risk, delivery-target (3 POST endpoints)
- OpenTelemetry tracing, SHA256 scenario cache (1h TTL)
- Benchmark dashboard: A/B comparison graph-aware vs baseline across 10 BOMs
- 195 passing tests

**Critical gap identified in benchmark assessment (Jun 2026):**
The resilience scenario API (resilience.py) uses hardcoded/placeholder values for cost impact (+15%), ETA (+5 days), fulfillment percentiles (0.6/0.75/0.9) instead of actually re-running the optimizer. The Monte Carlo simulation exists and works but is NOT called from the scenario endpoints. This is the single most damaging gap for recruiter credibility.

**Why:** Phase 6 was implemented with simplified scenario logic to meet the deadline. The simulation module (graph/simulation.py) and optimizer (optimization/sourcing.py) are both complete and correct — they just aren't wired to the scenario endpoints.

**How to apply:** When suggesting Phase 7 or enhancements, prioritize wiring the real optimizer into the scenario endpoints as the single highest-ROI fix.
