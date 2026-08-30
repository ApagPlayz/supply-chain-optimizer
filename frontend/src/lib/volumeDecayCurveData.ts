/**
 * Volume-decay curve — data + helpers for the benchmark retraction.
 *
 * Lives outside the component file so React Fast Refresh stays happy
 * (a component module must export only components).
 *
 * WHAT THIS IS
 * ------------
 * The benchmark's published cost advantage over a greedy baseline is a function
 * of how small the order is. On the benchmark's own toy orders (4 BOM lines,
 * 4–9 units total) a fixed per-supplier freight fee is almost the entire cost
 * being optimized, so the optimizer "wins" by consolidating suppliers and
 * dodging that fee. Re-solve the same BOMs at real quantities and the advantage
 * decays to low single digits. That decay is the retraction, and this is its data.
 *
 * DATA PROVENANCE
 * ---------------
 * Every row of VOLUME_SWEEP_FALLBACK was computed from the checked-in artifact
 * `docs/volume_sweep.json` (generated 2026-08-30T02:43Z, OR-Tools CP-SAT, `balanced`
 * strategy) using the aggregate definition that document specifies:
 *
 *   POOLED = (Σ greedy total_cost − Σ milp_matched total_cost) / Σ greedy total_cost
 *
 * across the BOMs feasible at that multiplier; `milp_matched` arm (greedy and
 * MILP see the *same* offer pool, us_only=False for both); deduplicated offer
 * pool (one offer per component/distributor pair); excluding every point where
 * greedy's plan would order more units than exist in stock — greedy is not
 * allowed to "win" with a physically unexecutable plan.
 *
 * These values reproduce the table in `docs/BENCHMARK_VOLUME_CURVE.md`
 * ("The corrected volume curve") exactly. Nothing here is invented or hand-tuned.
 * If the API starts serving this curve, the API wins — see normalizeVolumeCurve().
 *
 * CAVEAT (rendered in the UI, not hidden here): the cohort shrinks as volume
 * rises — 10 BOMs at 1×, 2 at 10,000× — because stock ceilings knock BOMs out.
 * It is NOT a like-for-like series across the whole x-axis.
 */

export interface VolumeCurvePoint {
  /** Order-size multiplier applied to every BOM line (1× = the benchmark's own toy order). */
  multiplier: number;
  /** Pooled cost advantage of the MILP over greedy at this multiplier, in percent. */
  savings_pct: number;
  /** How many reference BOMs were feasible (and stock-legal) at this multiplier. */
  n_boms?: number;
  /** Units per BOM at this multiplier — the cohort spans a range. */
  units_min?: number;
  units_max?: number;
  /** Decomposition of the pooled saving, in USD. Positive = greedy paid more. */
  fixed_fee_usd?: number;
  component_usd?: number;
  variable_freight_usd?: number;
  /** Avoided fixed fees as a share of the whole saving. >100% ⇒ every other term is a loss. */
  fee_share_of_saving_pct?: number;
  /** Fixed per-supplier fees as a share of the greedy baseline's total landed cost. */
  greedy_fixed_share_of_cost_pct?: number;
}

/** Derived from docs/volume_sweep.json — see the provenance block above. */
export const VOLUME_SWEEP_FALLBACK: VolumeCurvePoint[] = [
  { multiplier: 1, savings_pct: 47.22, n_boms: 10, units_min: 4, units_max: 9, fixed_fee_usd: 3863, component_usd: -561, variable_freight_usd: 2, fee_share_of_saving_pct: 117, greedy_fixed_share_of_cost_pct: 78.8 },
  { multiplier: 2, savings_pct: 36.48, n_boms: 9, units_min: 8, units_max: 16, fixed_fee_usd: 2840, component_usd: -322, variable_freight_usd: 7, fee_share_of_saving_pct: 112, greedy_fixed_share_of_cost_pct: 68.3 },
  { multiplier: 5, savings_pct: 29.14, n_boms: 8, units_min: 20, units_max: 40, fixed_fee_usd: 2501, component_usd: -301, variable_freight_usd: 27, fee_share_of_saving_pct: 112, greedy_fixed_share_of_cost_pct: 54.5 },
  { multiplier: 10, savings_pct: 23.06, n_boms: 7, units_min: 40, units_max: 80, fixed_fee_usd: 2274, component_usd: -406, variable_freight_usd: 69, fee_share_of_saving_pct: 117, greedy_fixed_share_of_cost_pct: 44.2 },
  { multiplier: 25, savings_pct: 17.01, n_boms: 6, units_min: 100, units_max: 200, fixed_fee_usd: 1589, component_usd: -363, variable_freight_usd: 374, fee_share_of_saving_pct: 99, greedy_fixed_share_of_cost_pct: 33.5 },
  { multiplier: 50, savings_pct: 7.30, n_boms: 5, units_min: 200, units_max: 400, fixed_fee_usd: 910, component_usd: -465, variable_freight_usd: 490, fee_share_of_saving_pct: 97, greedy_fixed_share_of_cost_pct: 19.3 },
  { multiplier: 100, savings_pct: 8.51, n_boms: 5, units_min: 400, units_max: 800, fixed_fee_usd: 570, component_usd: 743, variable_freight_usd: 769, fee_share_of_saving_pct: 27, greedy_fixed_share_of_cost_pct: 10.6 },
  { multiplier: 250, savings_pct: 6.51, n_boms: 5, units_min: 1000, units_max: 2000, fixed_fee_usd: 342, component_usd: 406, variable_freight_usd: 3043, fee_share_of_saving_pct: 9, greedy_fixed_share_of_cost_pct: 4.4 },
  { multiplier: 500, savings_pct: 5.67, n_boms: 5, units_min: 2000, units_max: 4000, fixed_fee_usd: -116, component_usd: -111, variable_freight_usd: 6788, fee_share_of_saving_pct: -2, greedy_fixed_share_of_cost_pct: 2.1 },
  { multiplier: 1000, savings_pct: 4.99, n_boms: 5, units_min: 4000, units_max: 8000, fixed_fee_usd: -458, component_usd: -1585, variable_freight_usd: 13536, fee_share_of_saving_pct: -4, greedy_fixed_share_of_cost_pct: 1.1 },
  { multiplier: 2500, savings_pct: 2.63, n_boms: 4, units_min: 10000, units_max: 20000, fixed_fee_usd: -231, component_usd: -5177, variable_freight_usd: 18449, fee_share_of_saving_pct: -2, greedy_fixed_share_of_cost_pct: 0.4 },
  { multiplier: 5000, savings_pct: 2.61, n_boms: 3, units_min: 25000, units_max: 40000, fixed_fee_usd: -460, component_usd: -1313, variable_freight_usd: 25251, fee_share_of_saving_pct: -2, greedy_fixed_share_of_cost_pct: 0.2 },
  { multiplier: 10000, savings_pct: 7.97, n_boms: 2, units_min: 50000, units_max: 60000, fixed_fee_usd: -574, component_usd: 867, variable_freight_usd: 26019, fee_share_of_saving_pct: -2, greedy_fixed_share_of_cost_pct: 0.3 },
];

/** Multiplier at/above which docs/BENCHMARK_VOLUME_CURVE.md calls the regime "production volume". */
export const PRODUCTION_VOLUME_MIN_MULTIPLIER = 500;

/** Human-readable provenance string, rendered under the chart. */
export const VOLUME_SWEEP_FALLBACK_SOURCE =
  'docs/volume_sweep.json — OR-Tools CP-SAT sweep, 13 order sizes × 10 reference BOMs, pooled greedy vs milp_matched on a deduplicated offer pool. Reproduces the table in docs/BENCHMARK_VOLUME_CURVE.md.';

// ── Defensive normaliser for whatever the API might start serving ────────────
function num(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

function pick(row: Record<string, unknown>, keys: string[]): number | undefined {
  for (const k of keys) {
    const v = num(row[k]);
    if (v !== undefined) return v;
  }
  return undefined;
}

/**
 * Accepts anything the (concurrently evolving) /benchmark/summary endpoint might
 * hand us — an array of points, or an object wrapping one under a plausible key —
 * and coerces it into VolumeCurvePoint[]. Returns null when there is nothing
 * usable, so the caller falls back to the checked-in artifact.
 */
export function normalizeVolumeCurve(raw: unknown): VolumeCurvePoint[] | null {
  if (raw == null) return null;

  let rows: unknown[] | null = null;
  if (Array.isArray(raw)) {
    rows = raw;
  } else if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>;
    for (const key of ['points', 'curve', 'volume_curve', 'rows', 'data']) {
      if (Array.isArray(obj[key])) { rows = obj[key] as unknown[]; break; }
    }
  }
  if (!rows || rows.length === 0) return null;

  const out: VolumeCurvePoint[] = [];
  for (const r of rows) {
    if (r == null || typeof r !== 'object') continue;
    const row = r as Record<string, unknown>;
    const multiplier = pick(row, ['multiplier', 'volume_multiplier', 'qty_multiplier', 'x']);
    const savings = pick(row, [
      'savings_pct', 'saving_pct', 'pooled_savings_pct', 'pooled_saving_pct',
      'savings_percent', 'cost_advantage_pct',
    ]);
    if (multiplier === undefined || savings === undefined) continue;
    out.push({
      multiplier,
      savings_pct: savings,
      n_boms: pick(row, ['n_boms', 'boms', 'boms_feasible', 'n_feasible']),
      units_min: pick(row, ['units_min', 'min_units']),
      units_max: pick(row, ['units_max', 'max_units', 'total_units']),
      fixed_fee_usd: pick(row, ['fixed_fee_usd', 'fixed_fee_delta_usd', 'fixed_fees_usd']),
      component_usd: pick(row, ['component_usd', 'component_cost_usd', 'component_delta_usd']),
      variable_freight_usd: pick(row, ['variable_freight_usd', 'freight_var_usd', 'variable_freight_delta_usd']),
      fee_share_of_saving_pct: pick(row, ['fee_share_of_saving_pct', 'fixed_fee_share_pct', 'fee_share_pct']),
      greedy_fixed_share_of_cost_pct: pick(row, ['greedy_fixed_share_of_cost_pct', 'fixed_share_of_cost_pct']),
    });
  }
  if (out.length === 0) return null;
  return out.sort((a, b) => a.multiplier - b.multiplier);
}

/** Min/max pooled saving across the production-volume tail of the curve. */
export function productionVolumeRange(
  points: VolumeCurvePoint[],
  minMultiplier: number = PRODUCTION_VOLUME_MIN_MULTIPLIER,
): { low: number; high: number } | null {
  const tail = points.filter((p) => p.multiplier >= minMultiplier).map((p) => p.savings_pct);
  if (tail.length === 0) return null;
  return { low: Math.min(...tail), high: Math.max(...tail) };
}
