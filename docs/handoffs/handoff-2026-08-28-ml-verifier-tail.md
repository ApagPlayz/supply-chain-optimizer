# Handoff — the ML-verifier tail, 2026-08-28 (evening)

## Read this first: verify, don't trust

The previous session wrote this document about its own work. **Do not take any claim in it
on faith.** Every factual claim below is followed by the command that checks it. Run the
five commands in "Verify the starting state" before you begin; if any disagrees with what
is written here, believe the command and fix this document.

The repo rule that matters most here is in `LEARNINGS.md`: *a check that cannot fail is
worse than no check.* Before trusting any green result, ask whether it would go red if the
thing were broken — and prove it by making it red.

---

## Goal

Portfolio piece for operations-research / forecasting / supply-chain-DS roles. The standing
bar is that **nothing the site publishes may be contradicted by the code or the artifacts**.

This session closed the previous handoff's list and then fixed 18 further defects found by
two verification passes. **Four findings from the `ml-pipeline-verifier` pass remain open.**
They are the entire content of this handoff.

---

## Verify the starting state

Run these first. Expected results are stated; if one differs, that is your first finding.

```bash
cd "/Users/alessiopagliarulo/Documents/Claude Projects/Logisitics Project"

git log --oneline -1                 # expect 06e16e5
git rev-list --count origin/main..main   # expect 0 (nothing unpushed)
git status --porcelain backend/seeds/data/   # expect empty

curl -s https://supply-chain-ui-bhwz.onrender.com/version.json   # expect commit 06e16e5...
curl -s https://supply-chain-api-qy8x.onrender.com/version       # expect commit 06e16e5...
```

Both services were confirmed live on `06e16e5` at the end of the session. The API is on
Render's free tier: **the first request after idle takes 50–120 s and can time out. That is
a cold start, not an outage — retry before concluding anything.**

---

## The four open items

Ordered by interview damage. Each is written as: the claim, the command that proves it, and
what "done" looks like. Total ≈ 2–3 hours plus one ~26-minute push cycle.

### 1. The live optimizer prices risk off a two-month-old frame, and says nothing about it

**The most damaging of the four, because it is a number a reader will quote.**

`GET /api/v1/ml/stress` currently returns `stress_probability: 0.8284`, `stress_level:
"high"`, `regime_active: true` — presented as the current state of the world, with **no
as-of or data-vintage field anywhere in the payload**. It is computed from
`features_df.tail(1)` (`backend/app/ml/regime_model.py`, the `stress_proba` path around
line 762), and the last row of the committed feature frame is **2026-07-01**.

So an "82.84% HIGH" reading, which feeds a ~12.4% surcharge into the optimizer, describes
July. Nothing on the page or in the response lets a reader discover that.

Prove it:
```bash
tail -1 backend/seeds/data/regime_features_monthly.csv     # -> 2026-07-01,75.377,,191.8973,
curl -s https://supply-chain-api-qy8x.onrender.com/api/v1/ml/stress | python3 -m json.tool | grep -i "as_of\|vintage\|date\|observed"
# expect: no as-of field at all -- that absence IS the defect
```

Done looks like: the response carries the frame's last observation date as a first-class
field, the UI renders it beside the figure, and a test fails if the served probability is
computed from a frame older than a stated tolerance. Decide deliberately whether a stale
frame should still drive the surcharge or should degrade — **that is an owner decision, do
not silently change optimizer behaviour.** Ask before changing what the optimizer does with
it; publishing the vintage is safe and can be done without asking.

### 2. Item 13's discriminating measures are computed and thrown away

The 2026-08-28 sweep added `p_shortfall`, `p_total_shortfall`, `cvar_95_ceiling` and
`cvar_95_saturated` precisely because CVaR-95 saturates at its 1.15 ceiling and stops
discriminating. **They exist in exactly one module and are served nowhere**, so the 18
published CVaR rows still tie at the ceiling with no saturation flag a reader can see.

Prove it:
```bash
grep -rln "p_total_shortfall\|cvar_95_saturated" backend/app backend/seeds frontend/src docs
# expect exactly: backend/app/graph/simulation.py, docs/CVAR_EFFICIENT_FRONTIER.md,
#                 docs/OUTSTANDING_WORK.md, and this handoff itself
# i.e. the computation and three docs -- no API, no artifact, no page
```

Done looks like: the fields are persisted by the benchmark run and served, and `/benchmark`
marks a saturated row as saturated so a tie there cannot be read as evidence of equal
exposure. `optimization_runs` is append-only, so persisting them means a schema column plus
a re-run of `seeds/run_benchmark.py`.

**Warning, learned the hard way this week:** do not estimate the impact of a change with a
scratch reimplementation. Run the real `seeds/run_benchmark.py` and diff the rows with
`scripts/snapshot_run.py`. An out-of-tree harness predicted a supplier flip that a real
re-run showed did not happen.

### 3. `README.md:196-214` publishes a retired vintage

The R² table (`+0.638 / +0.082 / −0.550`, "810 rows", "360 levels", "27 manufacturers") is
from the two-snapshot vintage. The deployed artifact is 1,879 rows / 472 families / 28
manufacturers, champion `gradient_boosting`. The README *does* carry a parenthetical saying
the study was not re-run — so this is stale-but-caveated, not a bare falsehood — yet it sits
twelve lines below the same README stating the model is "fitted on 1,879 of those rows".

Prove it:
```bash
sed -n '196,214p' README.md
python3 -c "import json;d=json.load(open('docs/leakage_progression.json'));print(d['counts'])"
# artifact: n_rows 1879, n_family_group_keys 472, n_manufacturers 28
```

Done looks like: either re-run the grouped-split study on the current panel and publish the
new numbers, or keep the old ones and label them unmistakably as a superseded vintage with
its retirement date — the treatment already applied to `RESILIENCE_INTERVIEW_GUIDE.md`,
`PROJECT_OVERVIEW.md` and `RESEARCH_TECHNIQUES.md` this session. Re-running is the better
answer if the panel supports it. Also unresolved in the same area: `python_version`
provenance stamping (3.13 local vs 3.11 CI), ~1 h plus a retrain.

### 4. NOT VERIFIED — FRED write-on-read with no vintage pin

**This one was never confirmed. The agent assigned to it did not return. It is reported here
as unchecked, not as a finding.**

`backend/app/ml/fred_client.py:355` writes `df.to_csv(REGIME_FEATURE_CACHE)` inside the
feature-frame fetch, and `:307` does the same for the GSCPI series. If that path runs
against a live FRED response with no ALFRED vintage pin, then simply *reading* features
silently rewrites the committed CSV, and the training data changes underneath the model
with no revision control over the vintage.

Prove or refute it:
```bash
sed -n '295,360p' backend/app/ml/fred_client.py       # read the whole fetch path
grep -rn "alfred\|vintage\|realtime_start\|as_of" backend/app/ml/fred_client.py
git log --follow --oneline -- backend/seeds/data/regime_features_monthly.csv | head
# a CSV that changes on commits that were not deliberate retrains is the smoking gun
```

Establish first **whether the write actually triggers in normal operation** (it may be
gated behind an API key that is absent in prod, in which case it is latent, not live).
Report which it is before fixing anything.

### Also open, lower priority

`/benchmark` highlights `k === 2` as the recommended answer using a bare numeral
(`BenchmarkPage.tsx` around `:1861`, `:2005`, `:2044`) rather than a served `recommended_k`
field. Nothing on screen is false today and the backend's `_frontier_finding()` anchors the
same way — but there is no field guaranteeing the two stay in agreement if the frontier
moves. Same class as everything fixed this session, simply not yet triggered.

---

## Standing gates — every change must pass

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q
#   expect 997 passed, 1 failed. The ONE permitted failure is
#   test_the_served_estimator_is_the_one_the_metrics_describe -- a documented
#   local-only MLflow identity check that passes in CI. DO NOT "fix" it.
#   Takes ~10 minutes. Targeted runs are safe to parallelise now (per-process DB).

cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app     # both clean

cd frontend && npx tsc --noEmit && npm run build

cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate
#   expect 188 passed, 0 failed
```

`git status --porcelain backend/seeds/data/` must be empty — never let a seed CSV drift.

---

## Gotchas that each cost an hour

- **The gate proxies API calls to the LIVE API.** A check can pass *vacuously* against a
  local build because the deployed API does not yet return the data the element needs.
  A 12px-text defect hid this way all session and only appeared after the deploy.
  **A green local gate is only as good as the API it is pointed at.**
- **`DATABASE_URL` is CWD-relative and SQLite creates rather than fails.** A DB script run
  from the wrong directory silently makes an empty database instead of erroring.
- **`npm run build` writes to a shared `dist/`.** Never run it while an agent is working.
- **`backend/supply_chain.db` shows as modified after any pytest run.** That is SQLite page
  churn, not data. Check row counts before believing otherwise; `git checkout --` it.
- **Never commit anything under `.claude/`.** An agent wrote memory into `frontend/.claude/`
  earlier this week and it reached the staging area.
- **Each push costs ~26 minutes** (CI **18–20 min**, then the gated Render deploy). Measured on
  this session's own runs: `94b74d2` 20 min, `3e9e43b` 18 min, `06e16e5` 20 min. Batch work
  into one push. *(The "~12 min" first written here was wrong; corrected 2026-08-28.)*
- **A green "Deploy to Render" step means *triggered*, not live.** Only `/version` +
  `/version.json` + `git rev-parse HEAD` all agreeing proves a deploy.
- CI failing is how the deploy gate is *supposed* to behave — a red CI means no deploy, by
  design. That is what happened to `1536742` this morning.

---

## What this session actually did

Three commits, all pushed and live:

- `94b74d2` — unblocked CI (two float-equality tests that could only fail on CI); rewrote
  `/benchmark/summary`'s interpretation, which had published "the graph-aware arm lowered
  both plan cascade risk and the CVaR-95 tail" while returning `-0.0833` and
  `significant: false` in the same response; corrected Swagger's "2,643 held-out series" to
  the 2,646 the endpoint returns; corrected three docs quoting a retired model vintage;
  relabelled a GSCPI regime probability that was called "Semiconductor shortage stress";
  wired `graph_aware`/`us_only` through to the live optimizer (owner-approved).
- `3e9e43b` — the "covers zero, not a result" caveat was set in smaller type than the claim
  it disqualifies.
- `06e16e5` — `/frontier` was printing the literal string `undefined` at readers; plus seven
  more display defects and three new gate checks.

Backlog items **23–40** in `docs/OUTSTANDING_WORK.md` record each one with its file and
status. That file is the live backlog and the source of truth.

Two facts worth carrying forward:

- **`graph_aware` returns an identical plan on the demo cart.** The graph is real (max
  betweenness 0.2458) but the surcharge cannot outweigh the price gaps in this catalogue.
  The page says so outright. Do not "fix" this by inflating the weight.
- **`us_only` only moves the Lowest Cost strategy** — the other three are already
  `us_only_sourcing=True`. Turning it on takes that plan from $374 to $791 and costs it the
  cost-winner position.

---

## Open questions for the owner

1. **Item 1**: when the regime frame is stale, should the surcharge still fire, or degrade?
   Publishing the vintage is safe either way; changing optimizer behaviour is not.
2. **`LEARNINGS.md` now breaks its own stated 50-line cap** (87 lines, six entries merged
   2026-08-28). The July entries about the Actions loop could be compressed without losing
   an actionable rule, but they are owner-merged entries and were left alone.
3. Still standing from previous handoffs: Render Starter at $7/mo to kill the 50–120 s cold
   start (owner said leave on free, 2026-08-28); FRED write-on-read into a tracked CSV;
   six caller-less `/market/*` routes on public Swagger.
