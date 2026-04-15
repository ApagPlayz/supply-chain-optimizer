# Electronics Supply Chain Optimizer

## What This Is

A portfolio-grade supply chain intelligence platform targeting mid-level Data Scientist roles at Amazon, BCG, Deloitte, Google, UPS, and Honeywell. Built on real Nexar/Octopart data (791 electronic components, 92 distributors, 8,731 competitive offers), the platform combines multi-objective VRP route optimization with ML-driven risk scoring — and is being extended with Graph ML network risk modeling, live data feeds (freight rates, port congestion, geopolitical risk), and quantified benchmark outputs that demonstrate measurable business impact.

## Core Value

Demonstrate that ML-informed supply chain decisions (Graph ML network risk + live macro signals) produce quantifiably better outcomes than baseline optimization — with the numbers to prove it.

## Requirements

### Validated

- ✓ Real Nexar/Octopart data ingestion (791 components, 92 distributors, 8,731 offers) — existing
- ✓ Multi-objective VRP solver (OR-Tools CP-SAT + TSP) with 4 strategies (cost/time/risk/balanced) — existing
- ✓ JWT authentication, user accounts, demo login — existing
- ✓ React frontend: component browser, cart/BOM, Mapbox route visualization — existing
- ✓ ML stress regime model (LogReg on 6 FRED series, validated on 2021-22 shortage window) — existing
- ✓ Multi-model lead time predictor (Ridge/RF/GBM/MLP, 8,731 training rows) — existing
- ✓ ML API endpoints (/ml/stress, /ml/model-comparison, /ml/lead-time) — existing
- ✓ Digital Twin scenario simulator page — existing

### Active

- [ ] Graph ML supply chain network — model 92 distributors + components as a graph, compute centrality, detect cascade failure vulnerability, score each distributor's systemic risk
- [ ] Live freight rate feed — integrate Freightos Baltic Index or equivalent (free tier / RSS) as a real-time cost signal wired into the optimizer
- [ ] Live port congestion feed — US Bureau of Transportation port wait-time data as a lead time modifier
- [ ] Geopolitical risk index — Armed Conflict Location (ACLED) or GPR Index to validate and augment Chinese-origin risk scores
- [ ] Benchmark dashboard — side-by-side quantified comparison: Graph-aware routing vs baseline, showing % reduction in cascade exposure, stockout risk, and procurement cost
- [ ] Codebase hardening — fix critical issues (hardcoded SECRET_KEY, wildcard CORS, unauthenticated live-price endpoints, orphaned pre-pivot files)
- [ ] Prophet forecaster resurrection — port broken `prophet_forecaster.py` to use Component/DistributorOffer schema for demand forecasting

### Out of Scope

- Real-time order execution / ERP integration — portfolio project, not a production procurement system
- Mobile app — web-only is sufficient for portfolio purposes
- Multi-tenant enterprise features (SSO, RBAC, org isolation) — adds complexity without DS portfolio signal
- Full MLOps infrastructure (Airflow DAGs, feature stores, model registry) — too infra-heavy for the DS narrative; clean training scripts + joblib suffice

## Context

**Current state:** The codebase completed a data pivot from synthetic materials to real Nexar/Octopart electronic components data. The ML layer (stress + lead time models) is integrated and functional. The optimizer produces 4 distinct strategies with real competitive pricing. Several pre-pivot artifacts are broken (prophet_forecaster.py, data_pipeline.py reference deleted `material` model). Security defaults are dev-only and must be hardened before any public demo.

**Target audience:** Hiring managers and technical interviewers at companies with supply chain DS/ML divisions — Amazon Supply Chain Optimization Technologies (SCOT), Google Logistics, UPS Data Science, BCG Gamma, Deloitte Analytics, Honeywell Connected Enterprise.

**What impresses this audience:** Quantified business impact numbers ("reduced cascade failure exposure by X%"), applied Graph ML on a real supply chain graph (not a toy dataset), and live data integration that shows production-readiness mindset.

**Data reality:** 92 real distributor nodes is a small but real graph — centrality and vulnerability analysis are meaningful. The 8,731 offer edges create a bipartite component-distributor graph with genuine concentration risk (LCSC/DigiKey dominate many categories).

## Constraints

- **Data:** All prices, stock levels, and distributor data must be from real sources (Nexar/Octopart) — no synthetic generation
- **Stack:** Python/FastAPI backend, React/TypeScript frontend — no stack changes
- **ML runtime:** Models must load at startup from joblib; no training at request time
- **Free APIs only:** Live data feeds must use free tiers or public data sources (no paid API budget assumed)
- **Portfolio framing:** Every new feature should produce a demonstrable output (number, visualization, report) that can be discussed in an interview

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| NetworkX over full GNN framework | 92 nodes fits classical graph algorithms; PyG/DGL adds complexity without benefit at this scale | — Pending |
| Freightos Baltic Index via RSS | Free, real, and well-known in logistics — recognizable signal to interviewers | — Pending |
| Benchmark as frontend dashboard tab | Interviewers can be walked through it live; more impressive than a static report | — Pending |
| Fix critical security issues first | Public demo links on resume expose real API keys if CORS/auth gaps aren't closed | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-15 after initialization*
