# Technology Stack: Graph ML for Supply Chain Network Risk Analysis

**Project:** Electronic Components Supply Chain Optimizer — Graph ML Extension
**Researched:** 2026-04-15
**Context:** Extending existing FastAPI + React optimizer with Graph ML network risk
**Target graph:** 92 distributor nodes + 791 component nodes = ~883-node bipartite graph
**Portfolio target:** Amazon, BCG, Google, UPS Data Scientist roles

---

## Decision 1: NetworkX vs PyG vs DGL

**Recommendation: NetworkX for graph analytics; PyG for GNN training. Use both.**

This is not an either/or question. They serve different purposes and compose well.

### The case for NetworkX first

At 92 distributor nodes (883 total with components), this is a small graph by every measure.
The classic GNN justification — learning from local neighborhood structure at scale — does not apply.
What does apply: centrality metrics, community detection, cascade simulation, and vulnerability scoring.
All of these are native NetworkX operations, run in milliseconds on a graph this size, require zero GPU,
and produce interpretable outputs that portfolio reviewers at McKinsey/BCG understand immediately.

NetworkX is also the lingua franca for supply chain graph research. The Monte Carlo cascade failure
simulation literature (2024-2025) standardizes on it. Using it is not a concession — it is correct.

| Library | Version | Role | When to Use |
|---------|---------|------|-------------|
| networkx | 3.4.x | Graph construction, centrality, community detection, cascade sim | Always — primary analytics layer |
| torch-geometric (PyG) | 2.7.0 | GNN training: GAT/HeteroConv for risk scoring | Phase 2 — after NetworkX analytics are working |
| torch | 2.5.x | PyG backend | Required by PyG |
| torch-geometric-temporal | 0.56.0 | Temporal GNN variants (T-GCN, TGCRN) | Optional Phase 3 — if adding time-series node features |

**Do NOT use DGL** for this project. DGL's strengths are distributed training and giant graphs (millions
of nodes). The PyTorch backend switching adds complexity for no benefit at 883 nodes. PyG has a more
Pythonic API, better heterogeneous graph support (critical for bipartite distributor/component graphs),
and the supply chain research literature (arxiv:2411.08550, Nov 2024) uses PyG exclusively.

**Do NOT use graph-tool or igraph** despite their speed advantages. Neither integrates with PyTorch.
The portfolio audience expects PyG-compatible code.

---

## Decision 2: Graph Algorithms for Supply Chain Vulnerability

**Recommendation: Three-layer approach — structural metrics, community detection, then cascade sim.**

### Layer 1: Structural Vulnerability Metrics (NetworkX)

These are the algorithms with the strongest evidence base for supply chain risk (2024-2025 literature):

| Algorithm | NetworkX Function | What It Finds | Supply Chain Use |
|-----------|------------------|--------------|-----------------|
| Betweenness Centrality | `nx.betweenness_centrality()` | Nodes that lie on most shortest paths — choke points | Distributors whose failure disconnects the most components |
| Degree Centrality | `nx.degree_centrality()` | Highly connected nodes | Distributors carrying many components = single points of failure |
| Closeness Centrality | `nx.closeness_centrality()` | How quickly a node reaches all others | Distributor reachability from your factory |
| PageRank | `nx.pagerank()` | Influence-weighted connectivity | Distributor importance accounting for what they supply |
| Clustering Coefficient | `nx.clustering()` | Local redundancy | How substitutable a distributor is |

Source: "Establishing the robustness of chip trade networks by dynamically considering topology and risk
cascading propagation," Scientific Reports 2024 (doi:10.1038/s41598-024-71345-y). Confirms betweenness
centrality + PageRank as the strongest predictors of cascade impact in semiconductor supply networks.

**Implementation note:** Build the bipartite graph as a projected unipartite distributor-to-distributor
graph (connected if they share components) for centrality calculations. Keep the full bipartite graph for
GNN training. Both representations are needed.

### Layer 2: Community Detection (NetworkX / python-louvain)

Use the Louvain algorithm to find distributor clusters that share component exposure. Clusters with high
internal similarity and one dominant node are fragile. Clusters with low similarity are well-diversified.

```bash
pip install python-louvain  # community package, wraps networkx
```

Use `community.best_partition(G)` from the `community` module. This is standard for supply chain
community structure analysis (confirmed in arxiv:2408.14501, Aug 2024 SupplyGraph benchmark paper).

### Layer 3: Cascade Failure Simulation (NetworkX + Monte Carlo)

Model distributor failure propagation. When a distributor fails, components it exclusively supplies
become unavailable, which may cause other distributors' shipments to be incomplete, propagating
through the BOM graph.

Pattern from "A graph-based Monte Carlo framework for multi-tier supply chain disruption" (IJSRA 2025):
1. Assign each distributor a failure probability (derived from risk_score + macro_stress)
2. For N=10,000 Monte Carlo iterations, sample failures and propagate through the component graph
3. Measure: % of BOM fulfillment in each scenario, expected shortfall, worst-5% scenarios

This is the most portfolio-differentiated deliverable. BCG/McKinsey interviewers respond to "I built a
cascade simulation and found that 3 distributors account for 60% of failure scenarios."

---

## Decision 3: GNN Architecture

**Recommendation: GAT (Graph Attention Network) with HeteroConv wrapper for the bipartite graph.**

Evidence base: The November 2024 survey (arxiv:2411.08550, "Graph Neural Networks in Supply Chain
Analytics and Optimization") tested GCN and GAT across six supply chain tasks. GAT achieved 75-91%
accuracy on risk classification and anomaly detection, consistently outperforming GCN. The attention
mechanism is not just an accuracy improvement — it produces interpretable attention weights showing
which component relationships drive each distributor's risk score. This is critical for portfolio demos.

### Why GAT over GCN

- GCN assumes uniform neighbor weighting. In a bipartite distributor/component graph, different
  components have vastly different risk profiles. Attention weights capture this.
- GCN cannot handle heterogeneous node types natively. The distributor-component graph has two node
  types with different feature dimensionalities.
- GAT attention weights are a natural explanation artifact: "DigiKey's risk score is driven 40% by
  its exposure to these 3 high-risk Chinese-origin components."

### Why GAT over GraphSAGE

GraphSAGE's inductive learning advantage (generalizing to unseen nodes) is irrelevant at 92 fixed
distributor nodes. GAT's attention interpretability is more valuable for this use case.

### Architecture for this project

```python
# PyG 2.7.0 — HeteroData with two node types
# distributor nodes: features = [tier, latitude, longitude, is_domestic, current_risk_score, stress_prob]
# component nodes: features = [category_embedding, risk_score, chinese_origin, stock_coverage]
# edges: distributor -> component (offers), component -> distributor (reverse)

from torch_geometric.nn import HeteroConv, GATConv

conv = HeteroConv({
    ('distributor', 'offers', 'component'): GATConv((-1, -1), 64, add_self_loops=False),
    ('component', 'rev_offers', 'distributor'): GATConv((-1, -1), 64, add_self_loops=False),
}, aggr='sum')
```

Task: Node-level risk score regression on distributor nodes. Loss: MSE against composite risk score
(centrality rank + cascade failure frequency + macro stress exposure).

**Confidence: HIGH** — GAT for supply chain risk is the most-cited architecture in 2024-2025 papers.
PyG 2.7.0 heterogeneous graph support is confirmed via official releases page.

---

## Decision 4: Live Data Feeds

### 4a. Freight Rates

**Recommendation: Freightos Baltic Index (FBX) via free terminal account + FRED TSIFRGHT via fredapi.**

| Source | Access | Data | Update Freq | Cost |
|--------|--------|------|-------------|------|
| Freightos FBX | Free terminal account (fbx.freightos.com) | Container rates, 12 trade lanes | Weekly | Free with signup |
| FRED TSIFRGHT | API key (free, fred.stlouisfed.org) | Freight Transportation Services Index | Monthly | Free |
| Baltic Dry Index | tradingeconomics.com CSV export | Dry bulk rates (less relevant for electronics) | Daily | Free (limited) |

The project already uses FRED for the macro stress model (TSIFRGHT is already in the FRED series list in
CLAUDE.md). Use `fredapi` Python library (github.com/mortada/fredapi) — the standard wrapper.

```bash
pip install fredapi  # wraps FRED REST API, returns pandas Series
```

Do NOT build a web scraper for freight rate data. FBX free tier CSV export is the right tool.
The Baltic Exchange API itself requires paid membership — do not pursue this path.

### 4b. Port Congestion

**Recommendation: IMF PortWatch (free download) + BTS Port Performance Statistics (free CSV).**

| Source | Access | Data | Update Freq | Cost |
|--------|--------|------|-------------|------|
| IMF PortWatch | portwatch.imf.org (free download, GeoServices API) | 2,033 ports, vessel calls, trade estimates | Weekly (Tuesdays) | Free |
| BTS Port Performance | bts.gov/ports (CSV download) | Throughput, crane counts, annual | Annual | Free |
| AISHub | aishub.net (API, registration required) | Raw AIS position data | Real-time | Free tier available |

IMF PortWatch is the strongest free option for a portfolio project. It covers 2,033 global ports, is
backed by IMF credibility, and has an ArcGIS-based API for programmatic access. A GitHub project
(github.com/amanid/imf-portwatch-analytics) demonstrates Python integration patterns.

Do NOT pay for MarineTraffic, Portcast, Sinay, or VIZION. They are commercial products costing $200-2000/mo.
Do NOT attempt to parse AIS streams directly — AISHub is the correct free aggregator if you need real-time.

For a portfolio project, weekly IMF PortWatch data is sufficient. Frame it as: "I ingest weekly port
throughput data from IMF PortWatch to detect congestion regimes that affect lead time predictions."

### 4c. Geopolitical Risk

**Recommendation: Caldara-Iacoviello GPR Index (free CSV) as primary; ACLED API as secondary.**

| Source | Access | Data | Update Freq | Cost |
|--------|--------|------|-------------|------|
| GPR Index (Caldara-Iacoviello) | matteoiacoviello.com/gpr.htm — direct CSV download | Monthly GPR score + country-level indexes | Monthly | Free with attribution |
| ACLED API | acleddata.com — free registration, API key | Conflict events by country/date, 1997-present | Weekly | Free (disaggregated) |
| World Uncertainty Index | policyuncertainty.com — CSV download | WUI by country, quarterly | Quarterly | Free |

The GPR Index (American Economic Review, 2022) is the academically rigorous geopolitical risk measure.
It is free, CSV-downloadable, covers 1985-present at monthly frequency, and includes country-level
indexes for China, Taiwan, and other electronics-relevant geographies. This is the right citation for
a BCG/McKinsey portfolio — "I use the Caldara-Iacoviello (2022, AER) geopolitical risk index."

ACLED provides event-level conflict data via a free REST API (registration required, no credit card).
Use it for country-level conflict counts that feed the risk graph as node features.

```python
# ACLED API pattern
import requests
resp = requests.get("https://api.acleddata.com/acled/read", params={
    "key": ACLED_KEY,
    "email": ACLED_EMAIL,
    "country": "China|Taiwan|Russia",
    "event_date": "2025-01-01|2025-12-31",
    "event_date_where": "BETWEEN",
    "fields": "country|event_date|event_type|fatalities",
    "limit": 500,
})
```

Do NOT use S&P Global, Maplecroft, or Z2Data geopolitical risk products — all require enterprise contracts.

---

## Complete Recommended Stack

### Core Graph ML

```bash
pip install networkx==3.4.2
pip install torch==2.5.1
pip install torch-geometric==2.7.0
pip install torch-scatter torch-sparse  # required PyG dependencies
pip install python-louvain==0.16        # Louvain community detection
```

### Data Feeds

```bash
pip install fredapi==0.5.2              # FRED API wrapper (TSIFRGHT + existing FRED series)
pip install requests==2.32.x            # ACLED API calls
pip install pandas==2.2.x               # Data wrangling for all feeds
pip install httpx==0.28.x               # Async HTTP (already in backend)
```

### Supporting Analytics

```bash
pip install scikit-learn==1.6.x         # Already in project; cascade simulation feature engineering
pip install scipy==1.15.x               # Graph distance matrices, sparse operations
pip install numpy==2.2.x                # Already in project
```

### Visualization (existing stack, no additions needed)

The existing Deck.gl ArcLayer and ScatterplotLayer in the frontend handle graph overlay rendering.
Risk scores from the Graph ML layer feed into the existing color-coding system. No new frontend
dependencies required — expose graph risk scores via a new FastAPI endpoint.

---

## What NOT to Use and Why

| Library / Service | Why Not |
|-------------------|---------|
| **DGL (Deep Graph Library)** | Designed for giant graphs (millions of nodes). Adds complexity with PyTorch/TF backend switching, no benefit at 883 nodes. PyG is better supported and better documented for heterogeneous graphs. |
| **Spektral (TensorFlow)** | TF backend conflicts with the existing PyTorch ML layer in this project (torch, scikit-learn already in use). Do not introduce a second DL framework. |
| **StellarGraph** | Deprecated as of 2022. No active development. Do not use. |
| **graph-tool** | Excellent performance but no PyTorch integration. C++ bindings make Docker packaging painful. |
| **Baltic Exchange API** | Paid membership required (£thousands/year). FBX free terminal achieves the same portfolio demo. |
| **MarineTraffic / Portcast** | Commercial AIS products, $200-2000/mo. Not justified for a portfolio project. |
| **Amazon / Bloomberg supply chain data APIs** | Require enterprise contracts. Use public alternatives (IMF PortWatch, BTS, FRED). |
| **PyG Temporal (torch-geometric-temporal)** | Only add if implementing T-GCN temporal layers. Overkill for Phase 1. Last release was 2023 — verify maintenance status before adopting. |
| **Neo4j / graph databases** | The distributor-component graph at 92 nodes fits comfortably in memory as a NetworkX graph. A graph database adds operational complexity (another Docker service) with no query performance benefit at this scale. |
| **GraphSAGE** | Valid architecture but inductive generalization to unseen nodes is irrelevant at fixed 92-node graph. GAT's attention weights are more useful for portfolio explanations. |

---

## Integration with Existing Stack

The existing project already uses:
- `scikit-learn` (LogisticRegression for macro stress model)
- `torch` (implied by existing ML layer)
- `fredapi` pattern (FRED series already integrated)
- `FastAPI` endpoints (add `/api/v1/graph/risk` alongside existing `/api/v1/ml/*`)

The Graph ML layer should be a new module `backend/app/graph/` alongside `backend/app/optimization/`:

```
backend/app/graph/
  ├── build_graph.py       # NetworkX bipartite graph construction from DB
  ├── centrality.py        # Betweenness, PageRank, closeness computations
  ├── community.py         # Louvain community detection
  ├── cascade.py           # Monte Carlo cascade failure simulation
  ├── gnn_model.py         # PyG GAT model definition
  ├── gnn_train.py         # Training loop (run once, save to disk)
  └── risk_scores.py       # Composite risk score assembly
```

Expose via:
```
GET /api/v1/graph/centrality        → distributor centrality rankings
GET /api/v1/graph/communities       → distributor cluster assignments
GET /api/v1/graph/cascade?runs=1000 → Monte Carlo cascade results
GET /api/v1/graph/risk              → GAT-predicted risk scores per distributor
```

---

## Confidence Assessment

| Area | Confidence | Source |
|------|------------|--------|
| NetworkX for small graph analytics | HIGH | Multiple 2024-2025 papers confirm; official docs |
| PyG 2.7.0 as GNN library | HIGH | Confirmed via GitHub releases page (Oct 2024) |
| GAT for supply chain risk | HIGH | arxiv:2411.08550 (Nov 2024), confirmed best performer |
| Freightos FBX free tier | MEDIUM | Official FBX site confirms free account; CSV export confirmed; API tier pricing unclear |
| IMF PortWatch free access | HIGH | Official portwatch.imf.org, confirmed public dataset downloads |
| ACLED API free tier | HIGH | Official ACLED docs confirm free registration with API key, no credit card |
| GPR Index free CSV | HIGH | matteoiacoviello.com confirmed free download with attribution |
| FRED / fredapi for freight | HIGH | Already used in this project; TSIFRGHT series confirmed on FRED |
| DGL vs PyG recommendation | HIGH | DGL's own docs confirm it targets large-scale distributed graphs |

---

## Sources

- PyTorch Geometric releases: [github.com/pyg-team/pytorch_geometric/releases](https://github.com/pyg-team/pytorch_geometric/releases)
- GNN Supply Chain Survey (Nov 2024): [arxiv.org/abs/2411.08550](https://arxiv.org/abs/2411.08550)
- GNN Supply Chain Optimization (Jan 2025): [arxiv.org/html/2501.06221v1](https://arxiv.org/html/2501.06221v1)
- SupplyGraph benchmark (Aug 2024): [arxiv.org/html/2408.14501v1](https://arxiv.org/html/2408.14501v1)
- Chip trade network robustness (2024): [nature.com/articles/s41598-024-71345-y](https://www.nature.com/articles/s41598-024-71345-y)
- Freightos Baltic Index: [fbx.freightos.com](https://fbx.freightos.com/)
- IMF PortWatch: [portwatch.imf.org](https://portwatch.imf.org/)
- ACLED API docs: [acleddata.com/acled-api-documentation](https://acleddata.com/acled-api-documentation)
- GPR Index (Caldara-Iacoviello): [matteoiacoviello.com/gpr.htm](https://www.matteoiacoviello.com/gpr.htm)
- FRED TSIFRGHT: [fred.stlouisfed.org/series/TSIFRGHT](https://fred.stlouisfed.org/series/TSIFRGHT)
- fredapi Python library: [github.com/mortada/fredapi](https://github.com/mortada/fredapi)
- BTS Freight Indicators: [bts.gov/freight-indicators](https://www.bts.gov/freight-indicators)
- PyG vs DGL comparison: [exxactcorp.com/blog/Deep-Learning/pytorch-geometric-vs-deep-graph-library](https://www.exxactcorp.com/blog/Deep-Learning/pytorch-geometric-vs-deep-graph-library)
- IMF PortWatch Python analytics: [github.com/amanid/imf-portwatch-analytics](https://github.com/amanid/imf-portwatch-analytics)
- ACLED Access Guide: [acleddata.com/knowledge-base/acled-access-guide](https://acleddata.com/knowledge-base/acled-access-guide/)
