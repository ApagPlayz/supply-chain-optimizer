# Feature Landscape: Graph ML Supply Chain Risk Platform

**Domain:** Graph ML supply chain risk platform — DS portfolio targeting Amazon SCOT, BCG, Google Logistics, UPS
**Researched:** 2026-04-15
**Confidence:** HIGH (graph metrics, open datasets), MEDIUM (hiring bar signals), LOW (internal team-specific weighting)

---

## Context: What the Interviewer Is Evaluating

DS interviewers at Amazon SCOT, BCG, Google Logistics, and UPS are not looking for a tutorial. They are looking for evidence that you:

1. **Framed a real problem correctly** — not just "applied NetworkX"
2. **Made defensible modeling choices** — and can explain why (e.g., "betweenness over degree because we care about flow bottlenecks, not just connectivity")
3. **Measured something that matters** — quantified improvement, not just visualized
4. **Handled failure modes** — what breaks your model and why

The feature list below is organized around that evaluation bar.

---

## Table Stakes

Features whose absence signals a toy project. Every candidate building a graph risk platform will have these.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Supplier-component bipartite graph construction | Foundation of every supply chain GNN paper (arXiv 2411.08550, Stanford supply-chains) | Low | Nodes = distributors + components; edges = DistributorOffer rows with price/stock/risk weight |
| Degree centrality per node | Baseline — "how many connections does this distributor have?" | Low | Use NetworkX `degree_centrality`; expected output: ranked list |
| Betweenness centrality | Identifies flow bottlenecks — which distributors lie on most shortest paths between components | Medium | Use NetworkX `betweenness_centrality`; computationally O(VE) for unweighted |
| Static risk score overlay | Per-node coloring by risk_score on graph visualization | Low | Already in the data model; just wire it to the graph node attributes |
| Basic graph statistics | Node count, edge count, average degree, density | Low | These are the first numbers any interviewer asks for |
| Connected components analysis | How many isolated subgraphs? Can every component be reached from every distributor? | Low | Use `nx.connected_components`; reveals hidden single-source situations |

---

## Differentiators

Features that separate the portfolio from the median DS candidate. Each requires a deliberate modeling decision that can be defended in an interview.

### Graph Topology Metrics

| Feature | Value Proposition | Complexity | Interview Hook |
|---------|-------------------|------------|----------------|
| **Betweenness centrality — weighted by stock** | Identifies the distributors whose failure causes the most disruption to supply paths, weighted by available inventory (not just topology) | Medium | "I weight edges by inverse stock availability so distributors that are the sole source of scarce components rank higher than well-stocked hubs — standard betweenness underestimates the risk of a constrained bottleneck" |
| **Fiedler value (algebraic connectivity)** | Second-smallest eigenvalue of the graph Laplacian; measures how well-connected the network is overall. Low Fiedler value → network splits easily | High | Compute with `nx.algebraic_connectivity`; compare before/after simulated node removal. Cite: Fiedler (1973), confirmed in supply chain context by arXiv chip trade networks paper (Scientific Reports 2024) |
| **k-core decomposition** | Identifies the "irreducible core" of the distributor network — suppliers that remain connected even after removing low-degree nodes | Medium | Use `nx.k_core(G, k=N)`; the innermost k-core reveals your most entrenched single-source dependencies |
| **Herfindahl-Hirschman Index (HHI) per component category** | Measures market concentration per component type. HHI = sum of squared market share fractions across distributors. Range: 0 (perfectly competitive) to 1 (monopoly) | Low | Fed Reserve uses HHI for their Sourcing Risk Index (2023); this directly mirrors how BCG/McKinsey measure supplier concentration risk |
| **Clustering coefficient per distributor** | Low clustering = distributor sits between otherwise disconnected groups → removal is highly disruptive. High clustering = distributor is redundant | Low | `nx.clustering(G, node)` |

**Specific numbers to compute and report:**
- Fiedler value baseline: `λ₂ = X.XX`
- Fiedler value after removing top-5 distributors by betweenness: `λ₂_degraded = Y.YY` (% drop)
- HHI per category (e.g., MCU: 0.42 = moderate concentration; passives: 0.11 = competitive)
- k-core max depth (k_max) and number of nodes in the innermost core
- Network density: `|E| / (|V| × (|V|-1))` before and after disruption

### Cascade / Contagion Simulation

| Feature | Value Proposition | Complexity | Interview Hook |
|---------|-------------------|------------|----------------|
| **SIR-style cascade propagation** | Simulate a supplier failure propagating through the network — which components become unavailable? What fraction of BOM is unfulfillable? | High | Infectious disease models (SIS, SIR) are the standard approach in supply chain contagion literature (IIETA 2019, ScienceDirect 2024). Frame as: "I adapted an SIR model where 'infected' = out-of-stock and 'susceptible' = components with no alternative source" |
| **Monte Carlo disruption scenarios (N=1000)** | Sample random node failures weighted by risk score; compute distribution of BOM fulfillment rate | High | Output: P10/P50/P90 fulfillment rate under disruption. "At P10, only 63% of BOM items are fulfillable from a single distributor failure." This is the number BCG consultants report to clients |
| **Targeted attack vs random failure** | Compare network resilience under sequential removal of highest-betweenness nodes vs random removal | Medium | This distinguishes structured risk from random noise; standard in critical infrastructure analysis |

**Specific numbers to compute:**
- Mean BOM fulfillment rate under single-distributor failure: `μ = X%`, `σ = Y%`
- Expected Value at Risk (EVaR): worst-case BOM cost inflation at 95th percentile disruption scenario
- Time-to-recovery estimate (days) per disrupted node, based on ML lead time model
- Network diameter before/after cascade

### GNN-Based Features

| Feature | Value Proposition | Complexity | Interview Hook |
|---------|-------------------|------------|----------------|
| **Node risk embedding (GCN or GAT)** | Learn a dense vector per distributor that encodes neighborhood risk context — not just its own risk score, but the risk of its neighbors and their neighbors | High | Use PyTorch Geometric GAT (Graph Attention Network). "A distributor in Phoenix might have a low individual risk score, but if all its neighboring component nodes are single-sourced from Chinese manufacturers, the neighborhood risk is high. GAT learns this." |
| **Link prediction: missing distributor-component relationships** | Predict which distributors are likely to stock a component they do not currently list, based on category similarity and network structure | High | Frame as visibility problem: "We only see the offers that exist; link prediction reveals shadow inventory." Cite: Taylor & Ledwoch (2021) in Int'l J Production Research |
| **Anomaly detection on offer graph** | Flag distributor-component pairs with pricing anomalies (outlier offers relative to neighborhood expectations) | Medium | Use autoencoder reconstruction error on node embeddings; flag top-5% as anomalies |

**Which GNN to use:** GAT (Graph Attention Network) — consistently outperforms GCN on supply chain tasks in 2024 benchmark (arXiv 2411.08550). Implemented in PyTorch Geometric (`torch_geometric.nn.GATConv`).

### Live Data Feeds (Signals Operational Maturity)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **FRED macro stress (already built)** | Current regime probability fed into edge weights | Done | Extend: use stress score to dynamically re-weight graph edges at query time |
| **BTS Freight Transportation Index** | Free government API; TSIFRGHT series already in FRED pipeline | Low | Add to node feature vector for temporal GNN inputs |
| **Port congestion proxy** | Portcast or VIZION API for major US port delays (LA/Long Beach, Savannah, Houston) | Medium | Use dwell time as a multiplier on lead time for distributor nodes that route through that port |
| **Geopolitical risk flag** | Chinese-origin flag already in data; extend with ACLED or Global Conflict Tracker for active conflict zones | Medium | Already partially done via `chinese_origin` risk factor; extend to country-level conflict score |

---

## Anti-Features

Features that waste time and signal misalignment with what DS teams care about.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Interactive drag-to-rearrange force graph** | Impressive-looking, adds no analytical insight. Interviewers at SCOT/BCG are not visual designers | Use force-directed layout for rendering only; put the analytical weight on the metric panel |
| **"Real-time" port scraping via unofficial sources** | Fragile, legally gray, not reproducible. SCOT/Google care about reproducibility | Use BTS and FRED (official, free, stable APIs) for macro signals |
| **Full GNN training pipeline in the browser/notebook** | Training a GNN in a demo is theater; what matters is whether outputs are interpretable and defensible | Pre-train offline; serve inference via the existing FastAPI `/ml/` endpoint pattern |
| **More than 4 optimization strategies** | Dilutes the multi-objective framing. Adding "eco-friendly premium" as a 5th strategy doesn't add intellectual value | Deepen existing 4 strategies with graph-informed risk weights instead |
| **Neo4j or a graph database** | Overengineering for 791 nodes + 8731 edges; adds ops complexity with no analytical payoff at this scale | NetworkX in-memory graph is correct; the data fits in RAM trivially |
| **Raw GNN accuracy numbers without a baseline** | "Our GAT got 82% accuracy" means nothing without comparison | Always report: GNN vs. Logistic Regression baseline vs. random baseline; report delta, not absolute |

---

## Feature Dependencies

```
DistributorOffer DB rows
  → Graph construction (NetworkX bipartite)
    → Basic topology metrics (degree, density, components)
      → Betweenness centrality (weighted)
        → Fiedler value (requires connected graph — check first)
          → k-core decomposition
            → Cascade simulation (SIR model on k-core subgraph)
              → Monte Carlo disruption scenarios
                → EVaR / P10-P90 fulfillment distribution

    → HHI per category (parallel path — only needs offer counts per distributor per category)

    → GCN/GAT node embeddings (requires PyTorch Geometric)
      → Link prediction (requires negative sampling)
      → Anomaly detection (requires autoencoder head)

ML lead time model (already built)
  → Time-to-recovery estimates in cascade simulation
  → Temporal GNN node features (lead time as dynamic attribute)

FRED macro stress (already built)
  → Dynamic edge weight re-weighting at query time
  → Feature input to GNN node attributes
```

---

## Open-Source Datasets to Supplement Existing Data

| Dataset | What It Adds | URL | Confidence |
|---------|--------------|-----|------------|
| **SupplyGraph (CIOL Research Lab, 2024)** | Benchmark temporal GNN dataset from real FMCG supply chain; 41 nodes, 684 edges, 6 evaluated tasks. Use for: validate your GNN architecture produces similar benchmark-aligned results | https://github.com/ciol-researchlab/SupplyGraph | HIGH |
| **Stanford supply-chains (SNAP Lab)** | Temporal graph neural network baselines for supply chain link prediction; SupplySim synthetic datasets available; code for SC-TGN and SC-GraphMixer | https://github.com/snap-stanford/supply-chains | HIGH |
| **ETO ChipExplorer (Georgetown CSET, 2024)** | Semiconductor supply chain network: tools, materials, processes, countries, firms involved in advanced logic chip production. Real market shares. Directly relevant to electronic components domain | https://eto.tech/dataset-docs/chipexplorer/ | HIGH |
| **BTS Freight Transportation Services Index** | Free official US freight volume index (FRED series TSIFRGHT) for macro feature engineering | https://www.bts.gov/freight-indicators | HIGH |
| **FRED CAPUTLG3344S + PCU33443344** | Already in pipeline; extend to all 6 series as temporal node features | https://fred.stlouisfed.org | HIGH |

---

## Benchmark Output: What Numbers to Report

This is the highest-signal section for DS interviewers. The goal is a reproducible, quantified output table — not a dashboard.

### Optimization Solver Benchmarks (already partially built — extend)

| Metric | What It Measures | Target Value / Signal |
|--------|-----------------|----------------------|
| **Total landed cost per strategy (USD)** | Absolute cost for each of the 4 strategies on a standard 15-component BOM | Report delta: "Cheapest vs. Balanced saves $X.XX; Balanced vs. Fastest saves $Y.YY" |
| **Strategy cost spread (max - min)** | Range of outcomes across 4 strategies | Wide spread signals meaningful tradeoff surface |
| **MILP optimality gap (%)** | How far from provably optimal is the solver solution? | < 1% for 92-node instance is expected; report it explicitly |
| **Solver wall time (ms)** | Computational cost | Report for BOM sizes 5, 15, 30, 50 components — shows scaling behavior |
| **Route consolidation ratio** | avg distributors visited / total components | < 1.0 means consolidation working; report per strategy |

### Graph Risk Benchmarks (new — the differentiator)

| Metric | What It Measures | How to Report |
|--------|-----------------|---------------|
| **Network Fiedler value (λ₂)** | Overall network resilience; higher = more resilient | `λ₂ = X.XX (baseline)` then show degradation curve as top-k nodes are removed |
| **HHI per component category** | Supplier concentration per category | Table: category → HHI → risk band (< 0.15 competitive, 0.15-0.25 moderate, > 0.25 concentrated) |
| **Single-source ratio** | % of components available from only 1 distributor in the DB | One number: "34% of components in this BOM have a single-source dependency" |
| **Max betweenness node (distributor name + score)** | The most critical distributor in the network | "DigiKey has betweenness = 0.43, meaning it mediates 43% of shortest paths" |
| **Cascade impact at top-1 failure** | BOM fulfillment rate if the highest-betweenness distributor fails | "If DigiKey fails: 67% BOM fulfillment (33 of 50 components available from alternative sources)" |
| **P10/P50/P90 fulfillment rate (Monte Carlo, N=1000)** | Distribution of BOM fulfillment under random single-distributor failures | Three numbers: "P10=58%, P50=79%, P90=94%" — shows fat-tail risk |
| **EVaR (expected value at risk, 95th percentile)** | Cost inflation at tail-risk scenario | "At the 95th percentile disruption scenario, BOM cost increases by $X.XX (+Y%)" |
| **GNN anomaly detection precision / recall** | Quality of the anomaly detection on offer pricing | Report vs. z-score baseline: "GAT autoencoder: P=0.71, R=0.68 vs. z-score P=0.52, R=0.61" |
| **Link prediction AUC-ROC** | How well the model predicts unobserved distributor-component relationships | Report with 80/20 train/test split; compare GAT vs. Node2vec vs. random |

### ML Model Benchmarks (extend what's already built)

| Metric | Existing | Extension |
|--------|----------|-----------|
| Lead time RMSE per model | Already in `/ml/model-comparison` | Add: RMSE per category (MCU vs passives vs RF) to show the model handles heterogeneous lead times |
| Macro stress recall on 2021-2022 window | Already in training script | Add: precision-recall curve, not just threshold recall |
| Graph risk score correlation with historical disruption | Not yet built | Backtesting: correlate node betweenness with the known 2021 chip shortage affected categories |

---

## Visualization Types (Ranked by Interviewer Impact)

High-signal visualizations show a modeling decision, not just pretty data.

| Visualization | Tool | Why High Signal | What NOT to Do |
|---------------|------|----------------|----------------|
| **Fiedler degradation curve** | Recharts line chart | Shows how network resilience drops as top-k nodes are removed; directly quantifies single points of failure | Don't show this without labeling which node is removed at each step |
| **HHI heatmap by category** | Recharts heatmap or color-coded table | Instantly shows which component categories have concentration risk; directly comparable to Fed Reserve Sourcing Risk Index methodology | Don't use a bar chart — heatmap communicates severity bands |
| **Bipartite graph with risk coloring** | D3.js force-directed or Deck.gl node-link | Nodes colored by risk score; edge thickness = stock volume; shows topology AND risk simultaneously | Don't use a purely aesthetic layout; anchor it to betweenness centrality in the layout algorithm |
| **Cascade propagation animation** | D3.js or custom React | Show which nodes "fail" sequentially when the top bottleneck is removed; SIR state colors | Don't animate if you can't also display the quantitative fulfillment rate dropping in real time |
| **Monte Carlo P10/P50/P90 bands** | Recharts area chart | Shows the distribution of outcomes under uncertainty — not a single number. This is how BCG presents risk to clients | Don't show only the mean; the tail is the point |
| **Strategy Pareto frontier** | Recharts scatter plot | Cost vs. time vs. risk tradeoff surface; each strategy is a point; shows the efficient frontier | Don't connect the points with a line unless you're interpolating; label each strategy explicitly |
| **Lead time vs. risk score scatterplot per category** | Recharts scatter | Shows the ML model's signal: does predicted lead time correlate with risk? Should it? | Add a regression line with R² displayed |

---

## MVP Recommendation

Build in this order to maximize interview-readiness per hour of work:

**Phase 1 — Graph Foundation (1-2 days)**
1. NetworkX bipartite graph from existing DistributorOffer data
2. Degree, betweenness, clustering coefficient, connected components
3. HHI per category
4. Single-source ratio
5. API endpoint: `GET /api/v1/graph/metrics` returning all of the above as JSON

**Phase 2 — Resilience Analysis (1-2 days)**
6. Fiedler value + degradation curve (sequential node removal)
7. k-core decomposition
8. API endpoint: `GET /api/v1/graph/resilience`

**Phase 3 — Cascade Simulation (2-3 days)**
9. SIR cascade model
10. Monte Carlo (N=1000) BOM fulfillment distribution
11. EVaR at 95th percentile
12. API endpoint: `POST /api/v1/graph/simulate` (body: list of failed distributor IDs)

**Phase 4 — GNN (2-3 days, highest complexity)**
13. GAT node embeddings (PyTorch Geometric)
14. Link prediction with AUC-ROC vs. Node2vec baseline
15. Anomaly detection on offer pricing

**Defer:**
- Full temporal GNN (requires time-series data not currently in the DB schema)
- Live port congestion API (useful signal, but MarineTraffic/Portcast require paid API keys)
- Knowledge graph reasoning (neurosymbolic GNN + KG is active research; high complexity, marginal portfolio return)

---

## Sources

- [Graph Neural Networks in Supply Chain Analytics and Optimization — arXiv 2411.08550 (2024)](https://arxiv.org/html/2411.08550v1)
- [SupplyGraph: A Benchmark Dataset for GNN Supply Chain Planning — arXiv 2401.15299 (2024)](https://arxiv.org/html/2401.15299v1)
- [Stanford SNAP supply-chains repository (SC-TGN, SC-GraphMixer)](https://github.com/snap-stanford/supply-chains)
- [ETO ChipExplorer: Advanced Semiconductor Supply Chain Dataset](https://eto.tech/dataset-docs/chipexplorer/)
- [Towards knowledge graph reasoning for supply chain risk management using GNNs — Taylor & Francis (2022)](https://www.tandfonline.com/doi/full/10.1080/00207543.2022.2100841)
- [A machine learning approach for predicting hidden links in supply chain with GNNs — Int'l J Production Research (2021)](https://www.tandfonline.com/doi/full/10.1080/00207543.2021.1956697)
- [Graph-Based Digital Twins for Supply Chain Management — arXiv 2504.03692 (2025)](https://arxiv.org/html/2504.03692v1)
- [Establishing robustness of chip trade networks — topology and risk cascading — Scientific Reports (2024)](https://www.nature.com/articles/s41598-024-71345-y)
- [Measuring exposure to network concentration risk: volume vs. frequency — ScienceDirect (2023)](https://www.sciencedirect.com/science/article/abs/pii/S0954349X23001339)
- [Federal Reserve: A Sourcing Risk Index for U.S. Manufacturing Industries (2023)](https://www.federalreserve.gov/econres/notes/feds-notes/a-sourcing-risk-index-for-u-s-manufacturing-industries-20230908.html)
- [Everstream Analytics 2025 Supply Chain Annual Risk Report](https://www.everstream.ai/special-reports/2025-supply-chain-annual-risk-report/)
- [BCG: Emerging Resilience in the Semiconductor Supply Chain (2024)](https://www.bcg.com/publications/2024/emerging-resilience-in-semiconductor-supply-chain)
- [Amazon SCOT Research — Amazon Science](https://www.amazon.science/tag/supply-chain-optimization-technologies)
- [UPS ORION dynamic routing (2024-2025)](https://www.supplychaindive.com/news/ups-orion-route-planning-analytics-data-logistics/601673/)
- [BTS Freight Transportation Indicators](https://www.bts.gov/freight-indicators)
- [Portcast Port Congestion API](https://www.portcast.io/blog/portcast-port-congestion-data-now-available-via-api-for-reliable-real-time-insights)
