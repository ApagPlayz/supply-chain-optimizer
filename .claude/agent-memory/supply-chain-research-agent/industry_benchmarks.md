---
name: industry-benchmarks
description: Key industry benchmarks, technologies, employer priorities, and data sources for supply chain roles (updated Jun 2026)
metadata:
  type: reference
---

## Target Employer Priorities

**Amazon SCOT (Supply Chain Optimization Technologies):**
- Stochastic/robust optimization under uncertainty (not deterministic)
- Multi-echelon inventory planning (not single-echelon)
- Mechanism design + incentive-compatible coordination
- Causal inference, Bayesian methods, reinforcement learning for sequential decisions
- Scale: billions of transactions — but portfolio projects should show the *thinking*, not the scale
- Key interview signals: depth in causal inference, econometrics, or optimization; mathematical underpinnings of algorithms; OR applications to routing, capacity planning, demand forecasting, network optimization

**McKinsey/BCG:**
- Digital twin maturity: scenario planning with re-optimization (not hardcoded deltas)
- Quantified business impact framing (cost/service level tradeoff curves, Pareto frontiers)
- ESG/Scope 3 integration — Scope 3 = 60-90% of company carbon footprint; mandatory SEC disclosure coming
- Control tower capabilities: exception management, alerting thresholds, SLA tracking
- AI fluency now tested in MBB final rounds (McKinsey US); BCG "T-shaped" model prizes AI depth
- Quantifiable achievements: cost reduction %, efficiency gains, risk mitigation in dollar terms

**Apple/Tesla Ops:**
- Multi-echelon inventory; guaranteed service model (GSM) or stochastic service model (SSM)
- n-tier supplier visibility (Tier 1 → Tier 2 → Tier 3)
- Vertical integration analysis
- Demand sensing with real-time signals (not just historical)

## Industry Benchmarks (2025-2026)
- WAPE under 20% is good; 10-15% is strong; under 10% is best-in-class for A/X items
- Bias target: ±5% at aggregated level; track systematically
- Tracking signal: cumulative error / MAD — detects when model needs retraining
- RMSE at horizon: how accuracy degrades week 1 → week 12
- Walk-forward backtesting standard: min 24 months history, 3 non-overlapping out-of-sample windows, min horizon = planning cycle (6-12 months)
- Digital twin market: $14.5B in 2024 → $149.8B by 2030 (CAGR 47.9%)
- McKinsey: digital twins deliver 20% improvement in on-time delivery, 90% faster decisions
- Gartner 2025 Resilience Benchmark: companies with risk-sensitive AI metrics have 28% faster response rate, 19% shorter recovery cycle
- Supply chain disruptions cost ~$184B annually (2025 estimate)
- Resilinc: up to Tier 10 supplier mapping; real-time disruption alerts
- Everstream: AI-driven predictive risk scores, automated scorecards
- Causal AI business impact examples: 10% order delay reduction (textile), $19M savings (IT products)

## Key Technologies (2025-2026)
- **Time Series Foundation Models**: Amazon Chronos, Google TimesFM, Salesforce Moirai, Nixtla TimeGPT — all outperform Auto ARIMA/Prophet by 15-25% on MAE across supply chain datasets. Zero-shot capability is a killer feature. Credibility requires: multi-metric eval (MAE, RMSE, MAPE, MASE, Pinball Loss, CRPS), fine-tuning demos, uncertainty quantification.
- **Stockpyl**: Python package for multi-echelon inventory (newsvendor, GSM/SSM) — publishable reference
- **Graph Neural Networks** for demand forecasting
- **Guaranteed Service Model (GSM)** for safety stock across echelons
- **Demand sensing**: short-horizon forecast refresh using POS/order data (not just historical)
- **MLOps**: MLflow (100% free, Apache 2.0), Weights & Biases (free tier for individuals), ClearML (free self-hosted). Model drift monitoring, automated retraining triggers — mostly missing from portfolio projects.
- **Causal AI / Causal Inference**: Structural causal models, counterfactual what-if ("what could we have done to prevent this delay?") — differentiator in 2025-2026
- **Agentic AI for supply chain**: autonomous ERP/WMS/TMS query agents triggering actions; supplier scoring agents; quote automation. Trending hard in 2026.
- **EVaR (Entropic Value-at-Risk)**: coherent risk measure, upper bound for VaR and CVaR, computationally efficient — more rigorous than simple VaR for risk quantification

## Free/Accessible Data Sources

**Macro/Logistics indices:**
- NY Fed GSCPI (Global Supply Chain Pressure Index) — monthly, free download from newyorkfed.org/research/policy/gscpi; components include BDI, Harpex, airfreight, PMI surveys from 7 economies
- FRED API (fredapi Python package) — FRED code for many supply chain indicators; free, requires API key from fred.stlouisfed.org
- Baltic Dry Index (BDI) — historical data via Investing.com or FRED
- IMF PortWatch — daily port activity for 2065 ports, 28 chokepoints; free download (CSV/GeoJSON/KML); API Explorer at portwatch.imf.org; updated weekly

**Geopolitical/Conflict:**
- ACLED (Armed Conflict Location & Event Data) — free API with registration, conflict events globally
- GDELT Cloud — global news events structured data, 15-min update frequency, 65+ languages, events from 1979–present; geopolitical risk signals; free API at gdeltcloud.com

**Electronic Components:**
- Nexar/Octopart API — 10 years empirical data, 280+ suppliers; free evaluation plan (up to 100 matched parts); provides: stock levels, pricing, lifecycle status, lead times, geographic risk; SCR (Supply Chain Resilience) data available
- Nexar SCR endpoint at nexar.com/spectra/supply-chain-resilience

**Supplier/Facility:**
- Open Supply Hub API — supplier facility data, deduplication; free API at info.opensupplyhub.org/api

## What Separates Elite Portfolio Projects from Average Ones
1. **Backtesting rigor**: walk-forward validation, not just a single train/test split; reporting accuracy degradation by horizon; multiple metrics not just MAPE
2. **Quantified dollar impact**: cost saved, revenue at risk protected, EVaR reduction — in $ not just %
3. **Production packaging**: Docker, FastAPI, deployed endpoint (Render/Railway free tier) — not just Jupyter notebooks
4. **Business constraint framing**: service level vs. cost tradeoff curves (Pareto frontiers), not just "lowest cost"
5. **Real data, not synthetic**: acknowledged and called out explicitly in README
6. **Causal reasoning**: why did X happen, what would have happened if Y — counterfactual framing
7. **Domain-specific adaptation**: explain *why* choices were made for electronics/components specifically
8. **Sustainability angle**: CO2 metrics, ESG framing — increasingly mandatory at MBB
