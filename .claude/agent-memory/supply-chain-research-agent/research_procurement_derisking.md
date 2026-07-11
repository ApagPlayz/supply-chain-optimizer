---
name: research-procurement-derisking
description: Cited methods/formulas for presenting procurement de-risking recommendations (risk-per-dollar, CVaR, REI/TTR/TTS, tornado, dual-sourcing deliverable)
metadata:
  type: reference
---

Research done 2026-07-06 for the recommendation-layer build. How top firms + OR literature present procurement de-risking DECISIONS (not just numbers). Use when designing ranking/sensitivity/dual-sourcing features. See also [[project_state_jun2026]], [[industry_benchmarks]].

## Risk-reduction-per-dollar / cost of resilience
- **Prabhakar & Sandborn (2015), Int. J. Product Lifecycle Mgmt** — rank parts by **K = ΔC_TCO / C_SUP** = (disruption cost avoided by 2nd source) / (cost to qualify+maintain it). This IS risk-reduction-per-dollar. escml.umd.edu/Papers/IJPLM_-_Prabhakar_and_Sandborn.pdf
- **Chopra & Meindl SCM Ch.2** — cost-responsiveness efficient frontier; ancestor of "cost of resilience" curves. Draw ours in (E[cost], CVaR) space.
- Practitioner TCO: expected disruption cost = P(disruption) × impact($); compare vs dual-source unit+qual premium.

## CVaR / tail risk (app already uses CVaR-95 — validated)
- **Chen, Xu & Zhang (2009), Operations Research 57(4):1040** — seminal risk-averse CVaR newsvendor. Dual-source benefit shows in CVaR column, not the mean.
- **Jammernegg, Kischka & Silbermayr (2024), IJPE 270:109171** — mean-CVaR frontier w/ tunable pessimism ("risk-aversion slider").

## Single-source exposure scoring (framework to imitate)
- **Simchi-Levi REI / TTR / TTS** (MIT News 2022; SCDigest 2015). TTR=recover time, TTS=survive time; flag nodes where **TTS<TTR**. REI is probability-AGNOSTIC — scores impact of failure normalized by max across nodes (0-1). Ford punchline: biggest risks were $0.10 single-source parts with TTS<1wk, not big strategic suppliers.

## Tornado / one-way sensitivity
- Recipe (Bounthavong; CFO Perspective; Clemen "Making Hard Decisions"): fix baseline output; per input set evidence-based low/high; vary one-at-a-time; spread=|high-low|; sort widest-top; baseline vertical line; label bar ends.
- Pitfalls: OAT ignores correlations (pair w/ Monte Carlo dist); arbitrary ±10/25% ranges are a known flaw (anchor to operational values); tornado ranks variance-contribution NOT risk severity.

## Dual-sourcing plan deliverable
- Two-layer artifact (Umbrex dual-vs-single; Bain; McKinsey): (1) ranked table [component, sole source, spend-at-risk, risk score, recommended 2nd source, incremental cost, risk reduction, payback, tier]; (2) wave sequencing **no-regret / hedge / big-bet** (Bain). bain.com/insights/a-strategy-for-thriving-in-uncertainty
- McKinsey MGI "Risk, resilience, rebalancing" (2020): disruption ≥1mo every 3.7yrs; ~45% of 1yr EBITDA lost per decade. BCG 2025 "Balancing Cost and Resilience" coins the cost-of-resilience frontier framing.

## Gaps
- Gartner supplier-risk scoring rubric is paywalled. Amazon/Apple internal frameworks not published (only qualitative dual-sourcing blog content).
