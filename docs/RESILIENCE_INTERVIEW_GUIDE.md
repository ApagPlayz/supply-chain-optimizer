# Resilience Dashboard — Interview Narrative

## Opening: The Problem

Modern supply chains are optimized for cost and speed, but fragility is hidden in the network structure. We've built a tool that makes that fragility visible and quantifiable.

## The Graph Resilience Metric

**Story:** I use Fiedler's algebraic connectivity to measure network resilience. It's a spectral graph metric that captures how robust the supply network is to single-node failures.

**Talking point:** "The Fiedler value of 0.05 means we have a single critical distributor — DigiKey, for instance, handles 40% of our component offers. If they go down, half our BOMs break. Let me show you."

**Demo:** Click "Distributor Failure" tab, select DigiKey, simulate.
- **Result:** Cost delta +15%, ETA delta +5 days, 12 components have no alternative source. Risk score increases from 0.3 → 0.6.
- **Narrative:** "This is why we need backup distributors. The cost of resilience is 15% on this BOM, but it prevents cascading failure."

## Scenario 1: Distributor Failure (Graph-Based)

When we lose a distributor, our Monte Carlo cascade simulation shows which components are orphaned and which alternatives can absorb the load.

**Key metrics:**
- Cost delta: How much more does it cost to reroute?
- ETA delta: How much longer do deliveries take?
- Risk score: Does centrality increase (more reliance on fewer distributors)?
- Fulfillment P10/P50/P90: What's the worst-case, median, best-case fulfillment rate?

**Business value:** 
"If losing DigiKey costs us 15% but losing Arrow costs us 40%, we know Arrow is more critical. We'd prioritize Arrow's redundancy in our procurement strategy."

## Scenario 2: Geopolitical Risk (Live Feeds + Graph)

We pull real-time data from four sources: GPR (Geopolitical Risk Index), ACLED (conflict events), IMF PortWatch (port disruptions), and FRED freight indices. If geopolitical risk spikes, we can overlay that scenario instantly.

**Demo:** Adjust risk slider to 2.0x (double the current GPR index).
- **Result:** Some suppliers move from medium risk → high risk. Cost increases 8%. Certain regions become less attractive.
- **Narrative:** "This is useful during actual crises. If we see a military conflict near a key supplier region, we can instantly see the cost impact of de-risking."

**Key metrics:**
- Risk score change: Which components are affected?
- Cost delta: What's the rerouting cost?
- Component tier migration: Blue (low) → yellow (medium) → red (high) risk.

## Scenario 3: Delivery Acceleration (Optimization Constraint)

What if we need a 2-week delivery instead of 4? Which suppliers can do it, and what's the cost?

**Demo:** Set delivery target to 14 days.
- **Result:** 8 suppliers can't meet the timeline. 11 can, but at 25% cost premium. ETA changes from 21 days → 14 days. Risk increases slightly (fewer supplier options).
- **Narrative:** "This is a trade-off tool. For a rush order, you pay a premium in cost and potentially risk. But you have the math to justify it to leadership."

**Key metrics:**
- Cost delta: Expedited shipping surcharge.
- ETA delta: Delivery time vs. target.
- Suppliers capable: List of suppliers who can meet the constraint.
- Risk delta: Are we taking on riskier suppliers to hit the timeline?

## The Interview Hook

After running 2-3 scenarios, say:

"The real power is that these aren't just numbers — they're trade-offs. When your CFO asks 'Can we reduce supply chain risk?' you can show them: yes, but here's the cost. When ops says 'We need 2-week delivery,' you can show them the supplier list and the premium. That's supply chain optimization in practice."

## Technical Depth (If Asked)

- **Graph metrics:** Fiedler value (algebraic connectivity), betweenness centrality (chokepoints), PageRank (importance), k-core decomposition (resilience tiers), HHI (concentration risk).
- **Monte Carlo simulation:** 1,000 scenarios, each removing one distributor and simulating which BOMs fail (P10/P50/P90 fulfillment rates).
- **Live feed integration:** Real data from GPR, ACLED, IMF PortWatch, FRED; graceful degradation if feeds unavailable.
- **Optimization:** CPMpy (OR-Tools) solver with graph-aware cost adjustments (risky suppliers penalized).
- **Caching:** 1-hour TTL for repeated scenarios; cleanup job every 10 minutes.
- **Performance:** P99 latency <2s; cache hits <50ms; OpenTelemetry tracing to Jaeger for diagnostics.

## Demo Checklist

- [ ] All three tabs visible and clickable
- [ ] Distributor dropdown populated (>50 distributors listed)
- [ ] Risk slider smooth (0.5x to 5.0x)
- [ ] Delivery slider smooth (1–90 days)
- [ ] Simulate buttons trigger API calls <2s each
- [ ] Delta cards show cost/ETA/risk changes
- [ ] Monte Carlo chart renders with confidence bands
- [ ] BOM impact table expandable with supplier details
- [ ] Error messages user-friendly if backend unavailable
- [ ] No console errors or TypeScript violations
- [ ] Caching verified: 2nd request ~100ms faster than 1st

## Talking Points Summary

1. "Supply chain resilience is a graph problem — find the critical nodes."
2. "Monte Carlo shows distribution tails, not just means — that's where the risk lives."
3. "Overlay real geopolitical data to surface hidden regional concentrations."
4. "Quantify the cost of resilience — make trade-offs visible to non-technical stakeholders."
5. "Optimize under constraints — balance cost, delivery, and risk."

## System Requirements (Local Demo)

- Backend: `python -m uvicorn app.main:app --reload` (port 8000)
- Frontend: `npm start` (port 3000)
- Database: SQLite at `supply_chain.db` (auto-created on first run)
- Optional Jaeger: `docker run -d -p 6831:6831/udp -p 16686:16686 jaeger` (for tracing; app works without it)

## Seed Data

The system ships with 791 real electronic components and 92 distributors from Nexar/Octopart. No synthetic data — all prices, lead times, and availability are real offers.

**Sample: Select "DigiKey" as failure scenario on a typical BOM (e.g., resistors, capacitors, ICs).**
- Expected: Cost delta ~15–20%, 30–40% of components have alternatives, ETA unchanged (similar lead times).
