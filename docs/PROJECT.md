# Project: Supply Chain Risk Optimizer

## Core Value
Real-time supply chain risk scoring and optimization for electronic components — built to showcase DS/ML skills for Amazon, BCG, Google, UPS roles.

## Stack
FastAPI · React · PostgreSQL · OR-Tools · Prophet · Docker · NetworkX · scikit-learn

## Data
791 real electronic components · 92 distributors · 8,176 price offers (static 2024 snapshot, originally via Nexar/Octopart, redistributed on HuggingFace under CC-BY-4.0)

## Key Decisions
- Real data only — no synthetic prices or suppliers
- 4 distinct optimization strategies: cost, resilience, balanced, us_only
- Graph ML (Fiedler value) for network risk scoring
- Benchmark dashboard compares strategies across 10 BOMs
