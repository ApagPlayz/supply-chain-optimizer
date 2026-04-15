# Domain Pitfalls: Graph ML + Live Data Feeds in Supply Chain Optimizer

**Domain:** Graph ML + live data integration for supply chain optimization portfolio project
**Researched:** 2026-04-15
**Project context:** FastAPI + React, 92 distributor nodes, NetworkX graph risk analysis,
live freight/port/geopolitical feeds, quantified benchmarks vs. baseline VRP

---

## Critical Pitfalls

These will cause an interviewer to dismiss the project as naive.

---

### Pitfall 1: Graph With No Structural Argument

**What goes wrong:** You compute betweenness centrality, closeness centrality, and PageRank on
92 distributor nodes and report the top-5 "critical" distributors — but the graph is essentially
a bipartite structure (distributors — components) with no meaningful path structure that those
metrics were designed to measure. Betweenness centrality detects brokers on shortest paths between
node pairs. If the real supply flow is `buyer → distributor → component` with no multi-hop
distributor-to-distributor chains, then a high-betweenness score has no operational meaning.

**Why it happens:** Tutorials show `nx.betweenness_centrality(G)` on social-network examples,
and developers port that code without asking whether the algorithm's assumptions match their graph.

**Consequences:** An Amazon SCOT or BCG Gamma interviewer will ask "what does betweenness
centrality mean operationally in your distributor graph?" and the honest answer is "nothing useful."
This single question will unravel the entire graph section.

**Prevention:** Define the graph structure first, then choose algorithms that match it.

- Bipartite graph (distributors × components): use bipartite projection, co-occurrence analysis,
  or supplier-overlap risk (how many components share a single-source distributor).
- Directed graph (buyer → dist → component, weighted by offer price): use reachability and
  single-source vulnerability (components only reachable via one node).
- If you want centrality to mean something, weight edges by `1/stock` or `price_volatility` so
  high-centrality genuinely signals a concentration risk, not random topology.

**Detection:** Before demo, for every metric you report, write one sentence stating what a
procurement manager would DO differently because of that score. If you cannot, cut the metric.

---

### Pitfall 2: Benchmark Numbers Produced by the Same Model That Created the Labels

**What goes wrong:** You train a graph-aware risk model, run it on the same 8,731 offers that
trained the ML lead-time model, and then compare "graph-aware routing" vs "baseline routing"
on those same offers. Because the baseline VRP was also tuned on that data (strategy weights,
consolidation bonus, transport penalty scale), both systems saw the data. Any improvement claim
is partially a reflection of fitting the evaluation set, not a genuine held-out comparison.

**Why it happens:** With a fixed dataset (no new data arriving), there is no truly independent
test partition unless you deliberately carve one out before any model/strategy tuning.

**Consequences:** An interviewer will ask "what's your test/train split?" and when the answer
is "the VRP strategies were manually tuned on observed outcomes from the full dataset," the
10-15% cost improvement claim collapses. Cherry-picking one BOM scenario that happens to show
large improvement is the portfolio equivalent of p-hacking.

**Prevention:**

1. Freeze a holdout partition — 20% of BOMs (or distributor subsets) that are never used during
   strategy weight tuning, graph construction, or ML training.
2. If you cannot partition, be explicit: "This is an illustrative comparison on training data.
   Out-of-sample validation requires live procurement data we don't have access to."
3. Report confidence intervals or scenario ranges, not single headline numbers. "Across 50
   randomly sampled BOMs, graph-aware routing shows median 8% cost reduction (IQR: 3–14%)" is
   more credible than "12% improvement."
4. Use a fixed random seed and document it. Reproducibility is a proxy for rigor.

**Detection:** Red flag phrase to avoid: "the graph-aware strategy is X% better." Replace with:
"On held-out scenarios, graph-aware routing achieves X% lower cost; on full dataset the figure
is Y% and likely inflated."

---

### Pitfall 3: Live Data Feed That Is Actually Stale Cache

**What goes wrong:** You wire in a freight rate or port congestion API (Freightos, Portcast,
MarineTraffic, or similar). In the demo, the data displayed is the response from the last time
the API call succeeded — possibly 24-72 hours ago — but the UI says "live." The API's free tier
has 25-100 calls/month. During an interview or recruiter demo, the first page load burns a call;
the next 5 refreshes hit the stale cache or, worse, the backend crashes with a 429 because you
ran out of quota the day before.

**Why it happens:** Developers assume free tier limits are per-day. Many logistics APIs
(ShippingRates.org: 25/month; MarineTraffic: credit-based at ~$0.30/call) have monthly or
credit-based limits that drain faster than expected, especially during development.

**Consequences:** Interviewer opens the app and sees a "freight stress score" dated three days
ago, or the live feed widget shows an error state. This undermines the entire live-data
narrative — the feature that was supposed to differentiate the project becomes a liability.

**Prevention:**

1. Implement a hard TTL cache (Redis or an in-memory dict with a timestamp) per data type:
   - Freight indices: cache 24 hours (they publish daily; pretending you need sub-hour freshness
     is theater for a portfolio app).
   - Port congestion: cache 4 hours.
   - Geopolitical risk (GDELT, news): cache 12 hours.
2. Display the cache timestamp prominently: "Freight index as of 2026-04-14 09:00 UTC."
   Transparency about data age is more professional than hiding it.
3. Implement a fallback static value. If the API is down or quota exhausted, serve the last
   known value with a `[stale]` label rather than crashing.
4. Develop against mocked fixtures; only enable real API calls in a controlled way. Never
   allow live calls during free-form UI exploration or automated tests.
5. Consider FRED (Federal Reserve Economic Data) as the anchor feed — it is genuinely free,
   has no meaningful rate limits, and is IOSCO-credible. This project already uses it for the
   ML stress regime model. Lean into it rather than chasing fancier but pricier alternatives.

---

### Pitfall 4: API Keys Committed to Git or Exposed to the Frontend

**What goes wrong:** The FastAPI backend calls an external freight API using a key stored in
`config.py` or hardcoded in a route. Either the key ends up in git history (even after deletion,
it is recoverable), or the key is passed to the React frontend where it is visible in browser
developer tools.

**Why it happens:** Portfolio projects skip secrets management because there is "nothing sensitive."
But API keys for paid services can generate charges, and a public GitHub repo with an embedded
key will be found by automated scanners within minutes.

**Consequences:** During technical review, a senior engineer checking the repo will flag this
immediately as a security-unaware candidate. For McKinsey/BCG/Amazon roles that involve
client data, demonstrating careless secrets handling is a disqualifying signal.

**Prevention:**

1. All external API keys must live in `.env` and never in source code. Confirm `.env` is in
   `.gitignore`.
2. All external calls happen server-side (FastAPI). The React frontend must never receive or
   store raw API keys.
3. Before publishing the repo, run `git log -S "YOUR_KEY_FRAGMENT"` to confirm no historical
   commits contain the key.
4. Use a dedicated low-limit API key for the demo with spending alerts enabled. Invalidate it
   after each demo session if the service supports key rotation.

---

### Pitfall 5: NetworkX at 92 Nodes Is Trivially Fast — Which Reads as Trivially Shallow

**What goes wrong:** You mention "graph analysis" and the interviewer expects scale. When they
ask "what were the computational challenges?", the honest answer is "none — 92 nodes runs in
milliseconds." This is not a problem you needed a graph library for; you could have done
equivalent analysis with a pandas DataFrame and a pivot table.

**Why it happens:** NetworkX is the obvious Python graph choice, and it is appropriate here.
The pitfall is not the tool choice — it is failing to acknowledge the scale and justify why
graph *structure* (not just tabular computation) adds value at this size.

**Consequences:** The project looks like it used a graph library to dress up what is effectively
a matrix computation. An interviewer who knows NetworkX will immediately ask about scalability:
"What happens at 10,000 distributors? 1 million components?" If you have no answer, the graph
layer looks decorative.

**Prevention:**

1. Explicitly frame the graph as a *modeling choice*, not a performance necessity: "At 92 nodes,
   NetworkX is overkill computationally, but the graph abstraction cleanly models multi-hop risk
   propagation that a flat table cannot." Then demonstrate one concrete example of multi-hop risk
   (e.g., two components share the same distributor who sources from the same manufacturer in a
   high-risk region — that cascade requires traversal logic, not just a filter).
2. Address scalability proactively: "At 100K components, we would migrate to a native graph DB
   (Neo4j or TigerGraph) or use sparse matrix operations via scipy.sparse rather than
   NetworkX in-memory objects." This shows you understand the tool's limits.
3. Benchmark and report the actual runtime anyway: "Graph construction: 12ms; full centrality
   pass: 34ms; path queries: <1ms per query." Showing you measured it demonstrates engineering
   discipline even when the numbers are small.

---

### Pitfall 6: Metrics With No Business Translation

**What goes wrong:** The graph analysis section reports: betweenness centrality = [0.23, 0.18,
0.12...], clustering coefficient = 0.41, graph density = 0.08, average path length = 2.3.
These numbers are presented without any link to a procurement decision.

**Why it happens:** Graph metrics tutorials never require you to explain the business implication.
The metric is the end product in a tutorial; in a portfolio project it must be the input to a
decision.

**Consequences:** BCG Gamma interviewers are trained to ask "so what?" after every metric. If
the answer requires more than two sentences and does not end with a dollar sign, headcount number,
or a named risk event, the metric is noise. Amazon SCOT specifically evaluates whether candidates
can tie analytical output to inventory, cost, or customer experience decisions.

**Prevention:** For every graph metric exposed in the UI, require a business translation:

| Metric | Business Translation |
|--------|---------------------|
| High betweenness centrality (distributor) | "Removing this distributor disconnects N components from all alternative sources — single point of failure. Recommend qualifying backup supplier." |
| Low graph density | "92% of component-distributor pairs have no offer — extreme concentration. Top 5 distributors cover 67% of BOM." |
| Clustering coefficient | "Component clusters reveal substitution groups — if one cluster's distributor fails, X components have no alternative." |
| Single-source nodes | "17 components are available from exactly one distributor — geopolitical tariff risk is unhedged on $[X] of BOM value." |

If you cannot fill in the right-hand column from actual data, do not expose the metric.

---

## Moderate Pitfalls

These will not immediately disqualify the project but will invite skeptical follow-up.

---

### Pitfall 7: Geopolitical Risk Score That Is a Static Lookup Table

**What goes wrong:** The existing risk score from the Nexar/Octopart data is a fixed value per
component. If the "live geopolitical feed" simply overwrites this with another static score
fetched at startup, you have not added genuine dynamism — you have swapped one static source for
another while calling it "live."

**Prevention:** The feed must either change behavior on a per-session basis (demonstrating that
today's stress score actually affects this BOM's routing differently than last week's) or be
clearly labeled as a periodic refresh rather than a real-time signal. Have a recorded example
of two different routing decisions produced under different stress regime values. One concrete
before/after is worth more than architectural diagrams about "live data pipelines."

---

### Pitfall 8: Directed vs. Undirected Graph Confusion

**What goes wrong:** Supply chain flows are directed (component manufactured → distributor stocks
→ buyer purchases). Using an undirected graph and then reporting path-based metrics implicitly
assumes bidirectional flow, which is physically wrong. An interviewer who notices that your
adjacency matrix is symmetric when it should be triangular will conclude the graph model was
not thought through.

**Prevention:** Use `nx.DiGraph` from the start. Document directionality conventions in code
comments. When describing the graph to interviewers, always specify direction: "edges run from
distributor to component, weighted by inverse stock level."

---

### Pitfall 9: Benchmark Scenario That Is Too Convenient

**What goes wrong:** The single demo scenario used for the benchmark comparison is a 15-component
PCB BOM where the graph-aware strategy happens to show 18% cost savings, 2-day faster delivery,
and lower risk. Every metric improved. This is implausible in practice — multi-objective
improvements across all dimensions simultaneously indicate the baseline was set up to lose.

**Prevention:**

1. Show scenarios where graph-aware routing is WORSE on at least one objective (e.g., lower risk
   but 12% higher cost). Trade-off scenarios are more credible than clean sweeps.
2. Include at least one scenario where the baseline wins (e.g., simple single-supplier BOM where
   graph overhead adds zero value). Honesty about limitations builds more trust than a pitch deck.
3. Document the BOM used for benchmarking and make it reproducible. If an interviewer suspects
   the demo BOM was hand-crafted to look good, having a reproducible seed and reasoning for
   scenario selection answers the implicit challenge.

---

### Pitfall 10: Frontend Directly Polling External APIs

**What goes wrong:** To simplify development, the React frontend calls the freight rate or port
congestion API directly from the browser using a key in the environment config (e.g.,
`VITE_FREIGHTOS_KEY`). Vite bakes this into the bundle. It is visible in browser source.

**Prevention:** All external API calls route through the FastAPI backend. The frontend calls
`/api/v1/external/freight-index`. The backend holds the key in `.env`, applies caching, handles
retries and rate limits, and returns a clean response. This is the correct architecture. It also
means the demo app degrades gracefully if a key expires — the backend returns a stale cached
value rather than the frontend throwing an unhandled CORS or 401 error in the console during
a live demo.

---

### Pitfall 11: "Live Data" That Is Actually Free Tier With No Fallback Plan

**What goes wrong:** The app relies on an external API that offers a free tier. During a
recruiting call, the interviewer asks to see the live stress index update. You navigate to the
page and the API call fails because you hit the monthly quota. The interviewer watches you
frantically try to reload.

**Prevention:**

1. Build a demo mode that serves pre-recorded API responses (fixture JSON files) for all
   external feeds. Toggle with an env variable: `USE_LIVE_FEEDS=false` for demos.
2. Keep a local copy of the last successful API response per feed type, committed to the repo
   (minus any PII). This serves as both the fallback and the test fixture.
3. The FRED API (already integrated) has no meaningful rate limits and historical data back to
   the 1950s. Structure the demo to foreground FRED-derived signals (macro stress regime) and
   treat other feeds as optional enhancement.

---

### Pitfall 12: Graph Construction Inside a Request Handler

**What goes wrong:** The `/graph/risk` endpoint rebuilds the full NetworkX graph from the
database on every request. At 92 nodes and 8,731 offers, this takes 200-400ms including
DB query overhead. Fine in development, but it means every visualization refresh hammers
the database and CPU. An interviewer clicking through the UI will notice latency that
an application of this complexity should not have.

**Prevention:** Build the graph once at application startup and cache it in a module-level
variable or FastAPI lifespan context. Invalidate and rebuild only on data changes (e.g.,
after a cart checkout that changes stock levels). The rebuild should be a background task,
not blocking the request.

---

## Minor Pitfalls

---

### Pitfall 13: Reporting R² for a Task Where It Is Misleading

**What goes wrong:** The existing ML layer reports R² for lead time prediction. R² for a
regression task with high-leverage outliers (e.g., a single MCU with 52-week lead time) can
look reasonable (R²=0.71) while MAE is unacceptably high for operational use. Interviewers
from quantitative backgrounds will ask for MAE and RMSE first, and if R² is the headline number,
it signals the candidate optimized for a flattering metric rather than the operationally
meaningful one.

**Prevention:** Lead with MAE in weeks (operationally interpretable) and RMSE (penalizes
outlier errors). Show both on the `/ml/model-comparison` endpoint. R² is fine to include but
not as the primary metric.

---

### Pitfall 14: Graph Analysis Section With No Code Reviewable Path

**What goes wrong:** The graph analysis is an endpoint that returns numbers, but there is no
notebook, script, or documented methodology showing how the graph was constructed, why those
weights were chosen, and what sensitivity analysis was done. An interviewer who asks "can you
walk me through the graph construction?" should be able to see code, not just output.

**Prevention:** Keep a `backend/notebooks/graph_analysis.ipynb` (or a standalone script) that
is executable and contains the graph construction rationale, weight justification, and a few
spot-check visualizations. This is the artifact that earns the "rigorous" label in a technical
review.

---

### Pitfall 15: Claiming Causal Inference From Observational Correlations

**What goes wrong:** "Components with high graph centrality scores have 34% longer lead times."
Presented as a finding. This is an observational correlation from a static snapshot of a single
dataset. A high-centrality distributor may be large (DigiKey, Mouser) with excellent stock
levels, or it may be a niche specialist. Without controlling for distributor tier, component
category, and time period, the correlation is uninterpretable.

**Prevention:** Frame all graph-derived findings as descriptive or associational, not causal:
"In this dataset, high-centrality distributors are associated with longer lead times (r=0.34,
n=92). This may reflect distributor size, category mix, or data artifacts — causal claims
would require a controlled study." Hedged language demonstrates statistical sophistication.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Graph construction | Undirected graph for directed flow | Use nx.DiGraph from day one |
| Centrality metrics | No business translation | Map every metric to a procurement action before exposing in UI |
| Benchmark comparison | Same data for tuning and evaluation | Reserve 20% holdout before any model or strategy tuning |
| Live freight feed | Free tier exhaustion mid-demo | Implement fixture fallback + demo mode toggle |
| Port/geopolitical feed | Data age displayed as "live" | Show cache timestamp; label stale data explicitly |
| API key management | Keys in frontend bundle or git history | Server-side only; `.env` + `.gitignore`; git log audit |
| Graph rebuild per request | Latency spike during UI demo | Build graph at startup; cache in lifespan context |
| ML metrics reporting | R² as headline for lead time | Lead with MAE (weeks), RMSE; R² secondary |
| Benchmark scenarios | All-green improvement claims | Include at least one scenario where graph routing loses |
| Business presentation | Metrics without "so what" | BCG/Amazon will ask; prepare two-sentence business translation for every metric |

---

## Sources

- [Memgraph: Biggest Challenges with NetworkX](https://memgraph.github.io/networkx-guide/biggest-challenges/)
- [Memgraph: Data Persistency and Large-Scale Analytics with NetworkX](https://memgraph.com/blog/data-persistency-large-scale-data-analytics-and-visualizations-biggest-networkx-challenges)
- [BCG GAMMA Interview Prep — Hacking the Case Interview](https://www.hackingthecaseinterview.com/pages/bcg-gamma-interview)
- [BCG GAMMA Interview — MyConsultingOffer](https://www.myconsultingoffer.org/case-study-interview-prep/bcg-gamma/)
- [Amazon SCOT Team — Amazon Science](https://www.amazon.science/tag/supply-chain-optimization-technologies)
- [Amazon Data Scientist Interview Guide — DataLemur](https://datalemur.com/blog/amazon-data-scientist-interview-guide)
- [Amazon Data Scientist Interview — IGotAnOffer](https://igotanoffer.com/blogs/tech/amazon-data-science-interview)
- [Graph Neural Networks in Supply Chain — arXiv 2411.08550](https://arxiv.org/html/2411.08550v1)
- [The Biggest Mistake in DS Portfolio Projects — Maggie in Data](https://maggieindata.substack.com/p/the-biggest-mistake-candidates-make)
- [API Key Security Best Practices — Legit Security](https://www.legitsecurity.com/aspm-knowledge-base/api-key-security-best-practices)
- [Portcast Port Congestion API](https://www.portcast.io/blog/portcast-port-congestion-data-now-available-via-api-for-reliable-real-time-insights)
- [Freightos Baltic Index Overview](https://www.freightos.com/freightos-baltic-index/)
- [S&P Global: Confusion Around Ocean Freight Indexes](https://www.spglobal.com/market-intelligence/en/news-insights/research/confusion-around-ocean-freight-indexes-limits-their-usefulness)
- [Supply Chain Graph — Linkurious](https://linkurious.com/blog/supply-chain-graph/)
- [Systemic Risk Assessment in Complex Supply Networks — Strathclyde University](https://strathprints.strath.ac.uk/61173/)
- [Visible Network Labs: Understanding Network Centrality](https://visiblenetworklabs.com/2021/04/16/understanding-network-centrality/)
