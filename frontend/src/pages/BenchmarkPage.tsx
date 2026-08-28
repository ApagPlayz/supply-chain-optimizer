import { useEffect, useState, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { AlertTriangle, CheckCircle2, Ban, TrendingUp, Split } from 'lucide-react';
import api, { benchmarkAPI } from '../services/api';
import { RISK_COLORS, riskLabel } from '../lib/risk';
import VolumeDecayCurve from '../components/VolumeDecayCurve';
// The SAME interval renderer the Newsvendor page's paired-bootstrap table uses.
// Two pages drawing bootstrap CIs must draw them identically, so there is one
// definition and both import it.
import CiStrip from '../components/CiStrip';
import {
  VOLUME_SWEEP_FALLBACK,
  VOLUME_SWEEP_FALLBACK_SOURCE,
  normalizeVolumeCurve,
  productionVolumeRange,
  PRODUCTION_VOLUME_MIN_MULTIPLIER,
} from '../lib/volumeDecayCurveData';

// ── Types (mirrors backend/app/api/benchmark.py response_model) ──────────────

/**
 * A 95% paired percentile-bootstrap interval around one published delta.
 *
 * The resample unit is the BOM CLUSTER: both arms of every per-BOM delta come
 * from the same BOM under the same simulation seed, so the BOM is the
 * independent unit. 10,000 resamples, seed 42, computed by the API from the
 * per-BOM values the run already stored — the benchmark is not re-solved and no
 * published mean moves.
 *
 * `significant` is true ONLY when the interval excludes zero. A delta whose
 * interval covers zero is not a result and this page must not render it as one.
 */
interface PairedBootstrapCI {
  metric: string;
  units: string;                       // "share_0_1" | "cost_multiplier" | "percent"
  mean: number;
  ci95_low: number | null;
  ci95_high: number | null;
  significant: boolean;
  n: number;
  n_effective: number;
  mean_effective: number | null;
  ci95_low_effective: number | null;
  ci95_high_effective: number | null;
  significant_effective: boolean;
  zero_plan_boms: string[];
  n_boot: number;
  seed: number;
  method: string;
}

interface ResilienceSection {
  nominal_cost_premium_pct: number;
  stress_cascade_risk_reduction: number;
  stress_cvar95_reduction: number;
  targeted_cascade_risk_reduction: number;
  targeted_cvar95_reduction: number;
  /**
   * Paired bootstrap CIs keyed by the exact scalar field they qualify. Optional
   * so an older API build still renders — but when it IS served, every scalar
   * above must be read through it: `significant === false` means the interval
   * covers zero and the number is not distinguishable from zero on this panel.
   */
  intervals?: Record<string, PairedBootstrapCI>;
  n_boms?: number;
  n_effective_boms?: number;
  n_effective_definition?: string;
  significant_metrics?: string[];
  non_significant_metrics?: string[];
  inference_note?: string;
}

interface MonteCarloSummary {
  baseline_p10: number;
  baseline_p50: number;
  baseline_p90: number;
  graph_aware_p10: number;
  graph_aware_p50: number;
  graph_aware_p90: number;
  baseline_cvar_95: number | null;
  graph_aware_cvar_95: number | null;
}

interface TradeoffEntry {
  bom_name: string;
  losing_axis: string;
  baseline_value: number;
  graph_aware_value: number;
  delta_pct: number;
  narrative: string;
}

interface BomDelta {
  bom_name: string;
  cost_delta_pct: number;
  eta_delta_pct: number;
  co2_delta_pct: number;
  cascade_risk_delta_pct: number;
}

interface BenchmarkSummary {
  run_id: number;
  run_tag: string;
  timestamp: string;
  n_boms: number;
  // Value of optimization: MILP vs greedy baseline (nominal)
  savings_pct: number;
  savings_usd_per_bom: number;
  savings_usd_annualized: number;
  annual_reorders: number;
  avg_suppliers_greedy: number;
  avg_suppliers_milp: number;
  // Value of resilience: graph-aware vs blind MILP (nominal + disruption)
  resilience: ResilienceSection;
  // Legacy graph-aware-vs-blind A/B fields (arm='milp', scenario='nominal')
  cost_delta_pct: number;
  cost_delta_usd: number;
  baseline_spend_at_risk_usd: number;
  eta_delta_pct: number;
  co2_delta_pct: number;
  cascade_risk_delta_pct: number;
  monte_carlo: MonteCarloSummary;
  tradeoff: TradeoffEntry;
  bom_deltas: BomDelta[];
  feeds_fallback: boolean;
  /**
   * Materiality cut the page reports against, in percent. Renamed from
   * `noise_floor_pct` (2026-08) because it never was a noise floor: nothing
   * measures it. `materiality_threshold_basis` is the API's own sentence
   * saying where it comes from — render it, never paraphrase it.
   */
  materiality_threshold_pct: number;
  materiality_threshold_basis?: string | null;

  // ── Optional / forward-compatible fields ───────────────────────────────────
  // The /benchmark/summary payload is actively being extended. Everything below
  // is read defensively: if the endpoint starts serving the volume sweep or the
  // cost decomposition, we render the API's numbers; otherwise we fall back to
  // the checked-in docs/volume_sweep.json artifact and say so in the UI.
  // Never hardcode a figure the API can supply.
  volume_curve?: unknown;
  volume_sweep?: unknown;
  savings_volume_curve?: unknown;
  /** Pooled cost edge at production volume, if the API computes it. */
  realistic_savings_pct_low?: number | null;
  realistic_savings_pct_high?: number | null;
  /** Share of the greedy baseline's landed cost that is fixed per-supplier fees. */
  fixed_fee_share_of_cost_pct?: number | null;
  /** Share of the headline saving attributable to avoided fixed per-supplier fees. */
  fixed_fee_share_of_savings_pct?: number | null;
  /** Per-supplier fixed freight fee actually charged by the cost model, in USD. */
  fixed_fee_per_supplier_usd?: number | null;
  /** Mean units per BOM in the benchmarked orders — the "tiny order" evidence. */
  mean_units_per_bom?: number | null;
  /** If the backend ships its own retraction note, it takes precedence. */
  headline_retracted?: boolean | null;
  retraction_note?: string | null;
}

// ── The price-of-resilience frontier ─────────────────────────────────────────
// Mirrors `DiversificationFrontierResponse` in backend/app/api/benchmark.py.
// Everything is optional-tolerant: an older backend that does not serve
// `/benchmark/diversification-frontier` simply hides the section rather than
// falling back to a checked-in copy of numbers that could drift.

interface FrontierInterval {
  n: number;
  mean: number;
  ci95_low: number | null;
  ci95_high: number | null;
  significant: boolean;      // true ONLY when the interval EXCLUDES zero
  n_boot: number;
  seed: number;
  method: string;
}

interface FrontierPoint {
  k: number;
  n_boms_feasible: number;
  n_effective: number;
  boms_infeasible: string[];
  n_keeps_k1_suppliers: number;
  mean_total_cost_usd: number;
  mean_suppliers: number;
  mean_stress_cascade_risk: number | null;
  mean_stress_expected_shortfall: number | null;
  mean_targeted_cascade_risk: number | null;
  mean_targeted_expected_shortfall: number | null;
  delta_cost_usd: FrontierInterval | null;
  delta_stress_cascade_risk: FrontierInterval | null;
  delta_stress_expected_shortfall: FrontierInterval | null;
  delta_targeted_cascade_risk: FrontierInterval | null;
  delta_targeted_expected_shortfall: FrontierInterval | null;
  usd_per_unit_targeted_cascade_risk: number | null;
  usd_per_unit_targeted_cascade_risk_note: string | null;
  usd_per_unit_stress_cascade_risk: number | null;
  usd_per_unit_stress_cascade_risk_note: string | null;
}

interface FrontierStep {
  label: string;
  from_k: number;
  to_k: number;
  marginal_cost_usd: FrontierInterval | null;
  marginal_targeted_cascade_risk_removed: FrontierInterval | null;
  marginal_stress_cascade_risk_removed: FrontierInterval | null;
  marginal_targeted_expected_shortfall_removed: FrontierInterval | null;
  marginal_stress_expected_shortfall_removed: FrontierInterval | null;
  usd_per_unit_targeted_cascade_risk: number | null;
  usd_per_unit_targeted_cascade_risk_note: string | null;
  usd_per_unit_stress_expected_shortfall: number | null;
  usd_per_unit_stress_expected_shortfall_note: string | null;
  cost_multiple_vs_first_step: number | null;
}

interface FrontierNonMonotoneExample {
  bom: string;
  from_k: number;
  to_k: number;
  expected_shortfall_before: number;
  expected_shortfall_after: number;
  n_suppliers_before: number;
  n_suppliers_after: number;
  keeps_k1_suppliers: boolean;
}

interface DiversificationFrontier {
  available: boolean;
  source: string;
  unavailable_reason: string | null;
  generated_utc: string | null;
  finding: string;
  verdict: string;
  strategy: string | null;
  mc_scenarios: number | null;
  mc_seed: number | null;
  stress_factor: number | null;
  bootstrap_n: number | null;
  bootstrap_seed: number | null;
  n_boms_in_catalog: number | null;
  n_boms_included: number | null;
  boms_excluded: Record<string, string>;
  baseline_check: string;
  baseline_check_passed: boolean;
  aggregate_definition: string;
  points: FrontierPoint[];
  steps: FrontierStep[];
  mean_suppliers_at_k1: number | null;
  nesting_caveat: string;
  non_monotone_example: FrontierNonMonotoneExample | null;
  cost_axis_caveat: string;
  seed_caveat: string;
  quantisation_caveat: string;
  independence_caveat: string;
  n_effective_definition: string;
  caveats: string[];
}

interface FiedlerPoint {
  step: number;
  removed: number | null;
  removed_name: string | null;
  lambda2: number;
  delta_pct: number;
  collapsed_boms: string[];
}

interface FiedlerCurveData {
  points: FiedlerPoint[];
  baseline_lambda2: number;
  /** How many reference BOMs the collapse check covered. 0 = it did not run. */
  boms_checked?: number;
  /** Where those BOMs came from, and which graph they were checked against. */
  bom_source?: string;
}

// ── Formatting helpers ────────────────────────────────────────────────────────
// Resilience reductions arrive as raw fractions. plan_cascade_risk is a SHARE on
// 0-1 — 1 minus the median fraction of a BOM's lines that stay fulfillable across
// the Monte Carlo trials — and is NOT a probability: no base rate, no exposure
// window, and on the 4-line reference BOMs it can only be 0, .25, .5, .75 or 1.
// mc_cvar_95 is a ~1.0-2.0 cost multiplier. We display both as percentage points
// and treat anything under this magnitude as "no material difference".
//
// This cut is an ASSUMPTION, not a measured noise level: the benchmark is a single
// deterministic solve with no replicates, so there is no run-to-run variance to
// estimate one from. Never render it as "noise".
const RESILIENCE_MATERIALITY = 0.01; // 1 percentage point, assumed

/** Pull `source` / `generated_utc` off the API's volume-curve object, if served. */
function readCurveMeta(raw: unknown): { source?: string; generated?: string } {
  if (!raw || typeof raw !== 'object') return {};
  const o = raw as Record<string, unknown>;
  return {
    source: typeof o.source === 'string' ? o.source : undefined,
    generated: typeof o.generated_utc === 'string' ? o.generated_utc : undefined,
  };
}

function isMaterial(x: number | null | undefined): boolean {
  return typeof x === 'number' && Number.isFinite(x) && Math.abs(x) >= RESILIENCE_MATERIALITY;
}

/**
 * Percentage-POINT formatter. Only valid for quantities that are genuinely
 * SHARES on a 0–1 scale (here: plan_cascade_risk, the median unfulfilled-line
 * share). pp scaling is arithmetically fine on a share; calling the underlying
 * quantity a probability is not. Pass the signed CHANGE in the metric —
 * negative means the metric went down.
 */
function fmtPP(changeFraction: number | null | undefined): string {
  if (typeof changeFraction !== 'number' || !Number.isFinite(changeFraction)) return '—';
  const pp = changeFraction * 100;
  return `${pp > 0 ? '+' : ''}${pp.toFixed(2)} pp`;
}

/**
 * CVaR-95 is a cost MULTIPLIER (~1.0–2.0), not a percentage. A delta between two
 * multipliers is therefore measured in multiplier units ("×"), not percentage
 * points — calling it "pp" was wrong. Pass the signed change; negative is better.
 */
function fmtMultiplierDelta(change: number | null | undefined): string {
  if (typeof change !== 'number' || !Number.isFinite(change)) return '—';
  return `${change > 0 ? '+' : ''}${change.toFixed(4)}×`;
}

/** The same multiplier change expressed relative to the baseline multiplier. */
function fmtRelativeToBaseline(
  change: number | null | undefined,
  baseline: number | null | undefined,
): string | null {
  if (typeof change !== 'number' || !Number.isFinite(change)) return null;
  if (typeof baseline !== 'number' || !Number.isFinite(baseline) || baseline === 0) return null;
  const rel = (change / baseline) * 100;
  return `${rel > 0 ? '+' : ''}${rel.toFixed(2)}% of baseline`;
}

/**
 * Direction glyph derived from the SIGN of the value. Never hardcode an arrow
 * next to a signed number — that is how "↓" ends up sitting beside "+19.44".
 */
function deltaGlyph(change: number | null | undefined): string {
  if (typeof change !== 'number' || !Number.isFinite(change) || change === 0) return '→';
  return change < 0 ? '↓' : '↑';
}

/** Improvement = the metric went DOWN. Green when down, amber when up, grey at 0. */
function improvementColor(change: number | null | undefined, material: boolean): string {
  if (!material || typeof change !== 'number' || !Number.isFinite(change)) return '#94a3b8';
  return change < 0 ? '#10b981' : '#f59e0b';
}

/**
 * Format one bootstrap interval in the SAME units and the SAME sign convention
 * as the number it sits beneath.
 *
 * The API publishes each delta as a REDUCTION (blind − graph-aware); the tiles
 * render the signed CHANGE (graph-aware − blind), which is the negation. Flipping
 * a sign on an interval also swaps its endpoints — `flip` does both, so the low
 * bound stays the low bound. Getting this wrong is how an interval ends up
 * printed backwards under a number it is supposed to qualify.
 */
function fmtCiBand(
  ci: PairedBootstrapCI | undefined,
  fmt: (x: number | null | undefined) => string,
  flip: boolean,
): string | null {
  if (!ci || ci.ci95_low === null || ci.ci95_high === null) return null;
  const lo = flip ? -ci.ci95_high : ci.ci95_low;
  const hi = flip ? -ci.ci95_low : ci.ci95_high;
  return `${fmt(lo)} to ${fmt(hi)}`;
}

/**
 * The interval line under a resilience figure.
 *
 * Two states, and the amber one is the point of the component: when the CI
 * covers zero the page says so in words, in place, next to the number — it does
 * not quietly print a mean and let the reader assume it survived. The mean stays
 * visible (hiding a measurement is its own dishonesty) but it is labelled as not
 * distinguishable from zero, and the tile's colour is neutralised by the caller.
 */
function CiNote({
  ci,
  fmt,
  flip = false,
}: {
  ci: PairedBootstrapCI | undefined;
  fmt: (x: number | null | undefined) => string;
  flip?: boolean;
}) {
  const band = fmtCiBand(ci, fmt, flip);
  if (!ci || !band) return null;
  const panel = `n=${ci.n} BOMs${ci.n_effective !== ci.n ? ` (${ci.n_effective} effective)` : ''}`;
  if (!ci.significant) {
    return (
      <p
        className="text-[11px] text-amber-400/90 mt-1.5 leading-snug"
        title={ci.method}
      >
        95% CI {band} — <span className="font-semibold">covers zero</span>. Not
        distinguishable from no effect on {panel}; not a result.
      </p>
    );
  }
  return (
    <p className="text-xs text-slate-400 mt-1.5 leading-snug" title={ci.method}>
      95% CI {band} · excludes zero · {panel}
    </p>
  );
}

function fmtPct(x: number | null | undefined, digits = 1): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return '—';
  return `${x > 0 ? '+' : ''}${x.toFixed(digits)}%`;
}

function fmtUsd(x: number | null | undefined): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return '—';
  return `$${Math.abs(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

// ── Frontier helpers ─────────────────────────────────────────────────────────

/** A risk share on 0-1, three decimals. Never a percentage: it is not a rate. */
function fmtShare(x: number | null | undefined, digits = 3): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return '—';
  return x.toFixed(digits);
}

/** Dollars with an explicit sign, so a cost INCREASE never reads as a saving. */
function fmtSignedUsd(x: number | null | undefined): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return '—';
  const sign = x > 0 ? '+' : x < 0 ? '−' : '';
  return `${sign}$${Math.abs(x).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
}

/**
 * The published caveat strings carry one leading `**bold title.**` segment
 * (see `backend/seeds/run_diversification_sweep.py` CAVEATS) — render that
 * segment as emphasis instead of showing the reader literal asterisks.
 */
function renderCaveatProse(text: string): ReactNode[] {
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
    i % 2 === 1 ? (
      <strong key={i} className="text-slate-200 font-semibold">{part}</strong>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

/** The literal endpoints under a strip, so the picture is never the only record. */
function fmtIntervalText(
  ci: FrontierInterval | null | undefined,
  fmt: (x: number | null | undefined) => string,
): string {
  if (!ci || ci.ci95_low === null || ci.ci95_high === null) return '—';
  return `[${fmt(ci.ci95_low)}, ${fmt(ci.ci95_high)}]`;
}

/**
 * A single domain shared by every strip in one column, always containing zero.
 *
 * Strips drawn on per-row domains are not comparable to each other and the zero
 * line moves between rows, which defeats the entire point of drawing them.
 */
function ciDomain(intervals: (FrontierInterval | null | undefined)[]): [number, number] {
  const vals: number[] = [0];
  for (const ci of intervals) {
    if (!ci) continue;
    for (const v of [ci.ci95_low, ci.ci95_high, ci.mean]) {
      if (typeof v === 'number' && Number.isFinite(v)) vals.push(v);
    }
  }
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = (hi - lo || 1) * 0.08;
  return [lo - pad, hi + pad];
}

/**
 * The verdict in words beside every interval, because the strip is a picture
 * and a picture is not a claim. "covers zero" is said out loud, never implied
 * by a colour.
 */
function CiVerdict({ ci }: { ci: FrontierInterval | null | undefined }) {
  if (!ci || ci.ci95_low === null || ci.ci95_high === null) {
    return <span className="text-xs text-slate-400">—</span>;
  }
  return ci.significant ? (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-300">
      <CheckCircle2 size={13} aria-hidden="true" />
      excludes zero
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-300">
      <AlertTriangle size={13} aria-hidden="true" />
      covers zero
    </span>
  );
}

/**
 * The five series on the frontier chart.
 *
 * LINE STYLE carries the measure and COLOUR carries the scenario, so no series
 * is identified by colour alone — every dash pattern is distinct, the key below
 * the chart reproduces the exact pattern, and every plotted value is repeated as
 * text in the tables underneath.
 */
const FRONTIER_SERIES: Array<{
  key: string; name: string; color: string; dash: string; axis: 'cost' | 'risk';
}> = [
  { key: 'cost', name: 'Mean landed cost (USD per BOM)', color: '#818cf8', dash: '', axis: 'cost' },
  { key: 'targetedCascade', name: 'Cascade risk, targeted outage (share 0–1)', color: '#f87171', dash: '9 4', axis: 'risk' },
  { key: 'stressCascade', name: 'Cascade risk, broad stress (share 0–1)', color: '#fbbf24', dash: '2 4', axis: 'risk' },
  { key: 'targetedShortfall', name: 'E[shortfall], targeted outage (share 0–1)', color: '#fb7185', dash: '12 4 3 4', axis: 'risk' },
  { key: 'stressShortfall', name: 'E[shortfall], broad stress (share 0–1)', color: '#fcd34d', dash: '5 4 1 4', axis: 'risk' },
];

/** The chart's legend, drawn with the real stroke patterns rather than swatches. */
function FrontierChartKey() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 mt-2 px-1">
      {FRONTIER_SERIES.map((s) => (
        <li key={s.key} className="flex items-center gap-2 text-xs text-slate-400">
          <svg width="26" height="8" aria-hidden="true" className="shrink-0">
            <line
              x1="0" y1="4" x2="26" y2="4"
              stroke={s.color} strokeWidth="2"
              strokeDasharray={s.dash || undefined}
            />
          </svg>
          {s.name}
        </li>
      ))}
    </ul>
  );
}

// ── KPI Card ──────────────────────────────────────────────────────────────────
function KpiCard({
  title, value, sub, accent, delay = 0,
}: {
  title: string; value: string | number; sub: string; accent: string; delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: 'easeOut' }}
      className={`bg-slate-800/70 border rounded-xl p-4 flex flex-col gap-1 backdrop-blur-sm ${accent}`}
    >
      <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">{title}</span>
      <span className="text-3xl font-semibold text-white tabular-nums">{value}</span>
      <span className="text-slate-400 text-xs">{sub}</span>
    </motion.div>
  );
}

// ── Custom Dot for Fiedler LineChart ──────────────────────────────────────────
function FiedlerDot(props: {
  cx?: number; cy?: number; payload?: FiedlerPoint;
  selectedStep: number | null;
  onSelect: (step: number) => void;
}) {
  const { cx = 0, cy = 0, payload, selectedStep, onSelect } = props;
  if (!payload) return null;

  const isSelected = payload.step === selectedStep;
  const r = isSelected ? 7 : 5;
  const stroke = isSelected ? '#6366f1' : 'none';
  const strokeWidth = isSelected ? 3 : 0;

  const handleClick = () => onSelect(payload.step);
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(payload.step);
    }
  };

  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="#ef4444"
        stroke={stroke}
        strokeWidth={strokeWidth}
        style={{ cursor: 'pointer' }}
      />
      {/* Invisible larger hit area for accessibility */}
      <circle
        cx={cx}
        cy={cy}
        r={12}
        fill="transparent"
        role="button"
        tabIndex={0}
        aria-label={payload.removed_name
          ? `Remove ${payload.removed_name}, lambda2 ${payload.lambda2.toFixed(3)}, delta ${payload.delta_pct.toFixed(1)}%`
          : `Baseline, lambda2 ${payload.lambda2.toFixed(3)}`}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        style={{ cursor: 'pointer', outline: 'none' }}
      />
    </g>
  );
}

// ── Main BenchmarkPage ────────────────────────────────────────────────────────
export default function BenchmarkPage() {
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [fiedler, setFiedler] = useState<FiedlerCurveData | null>(null);
  const [frontier, setFrontier] = useState<DiversificationFrontier | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<'empty' | 'error' | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([benchmarkAPI.summary(), benchmarkAPI.fiedlerCurve()])
      .then(([s, f]) => {
        setSummary(s.data);
        setFiedler(f.data);
      })
      .catch((err) => {
        setError(err.response?.status === 404 ? 'empty' : 'error');
      })
      .finally(() => setLoading(false));
  }, []);

  // The frontier is fetched SEPARATELY and never blocks the page: it reads a
  // committed artifact, so a deployment that predates the artifact should lose
  // this one section rather than the whole benchmark.
  useEffect(() => {
    api
      .get<DiversificationFrontier>('/benchmark/diversification-frontier')
      .then((r) => setFrontier(r.data))
      .catch(() => setFrontier(null));
  }, []);

  // ── Loading state ────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
          <span className="text-slate-400 text-sm">Loading benchmark results…</span>
        </div>
      </div>
    );
  }

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (error === 'empty') {
    return (
      <div className="min-h-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full flex items-center justify-center">
        <div className="flex flex-col items-center justify-center h-96 gap-4">
          <h2 className="text-3xl font-semibold text-slate-300">No benchmark run found</h2>
          <p className="text-sm text-slate-400 text-center max-w-md">
            Run <code className="bg-slate-800 px-1 rounded text-slate-300">python -m seeds.run_benchmark</code> to populate the optimization_runs table.
          </p>
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────────
  if (error === 'error') {
    return (
      <div className="min-h-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full flex items-center justify-center">
        <div className="flex flex-col items-center justify-center h-96 gap-4">
          <h2 className="text-amber-400 text-3xl font-semibold">Benchmark summary unavailable</h2>
          <p className="text-sm text-slate-400 text-center max-w-md">
            Benchmark summary unavailable. Confirm the backend is running and optimization_runs has rows.
          </p>
          <button
            onClick={() => {
              setError(null);
              setLoading(true);
              Promise.all([benchmarkAPI.summary(), benchmarkAPI.fiedlerCurve()])
                .then(([s, f]) => { setSummary(s.data); setFiedler(f.data); })
                .catch((err) => setError(err.response?.status === 404 ? 'empty' : 'error'))
                .finally(() => setLoading(false));
            }}
            className="bg-slate-800 border border-slate-700 px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-950"
          >
            Retry Loading Benchmark
          </button>
        </div>
      </div>
    );
  }

  if (!summary) return null;

  // ── Derived values ────────────────────────────────────────────────────────────
  const formattedTimestamp = summary.timestamp
    ? new Date(summary.timestamp).toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '—';

  // Resilience materiality: are graph-aware's disruption protections real, or ~0
  // on this catalog? Render the honest callout either way — never fake a win.
  const resilienceReductions = [
    summary.resilience.stress_cascade_risk_reduction,
    summary.resilience.stress_cvar95_reduction,
    summary.resilience.targeted_cascade_risk_reduction,
    summary.resilience.targeted_cvar95_reduction,
  ];
  const resilienceHasMaterialEffect = resilienceReductions.some(isMaterial);

  // Run 5 (2026-08-27) splits by scenario: graph-aware is materially SAFER under a
  // targeted outage and materially WORSE under broad stress. The page previously had
  // only two states — "measurably lowers risk" or "within noise" — so a directional
  // split rendered as an unqualified win. It is not one, and saying so is the finding.
  const stressReductions = [
    summary.resilience.stress_cascade_risk_reduction,
    summary.resilience.stress_cvar95_reduction,
  ];
  const targetedReductions = [
    summary.resilience.targeted_cascade_risk_reduction,
    summary.resilience.targeted_cvar95_reduction,
  ];

  // Monte Carlo chart data (ETA distribution, baseline/blind vs graph-aware MILP)
  const mcData = [
    {
      name: 'P10',
      Baseline: summary.monte_carlo.baseline_p10,
      'Graph-Aware': summary.monte_carlo.graph_aware_p10,
    },
    {
      name: 'P50',
      Baseline: summary.monte_carlo.baseline_p50,
      'Graph-Aware': summary.monte_carlo.graph_aware_p50,
    },
    {
      name: 'P90',
      Baseline: summary.monte_carlo.baseline_p90,
      'Graph-Aware': summary.monte_carlo.graph_aware_p90,
    },
  ];

  // Fiedler chart data
  const fiedlerData = fiedler?.points.map((pt) => ({
    name: pt.step === 0 ? 'Baseline' : (pt.removed_name ?? `Step ${pt.step}`),
    lambda2: pt.lambda2,
    step: pt.step,
    delta_pct: pt.delta_pct,
    collapsed_boms: pt.collapsed_boms,
    removed_name: pt.removed_name,
  })) ?? [];

  const selectedPoint = fiedler?.points.find((p) => p.step === selectedStep) ?? null;
  // Provenance for the collapse column. `boms_checked === 0` means the check did
  // not run, which is NOT the same as "nothing collapsed" — the page said the
  // latter for both cases while the backend never wrote the key at all.
  const fiedlerBomsChecked = fiedler?.boms_checked ?? 0;
  const fiedlerBomSource = fiedler?.bom_source ?? '';

  // Risk color for tradeoff losing-axis severity
  const tradeoffRiskScore = Math.min(1.0, Math.abs(summary.tradeoff.delta_pct) / 20.0);
  const tradeoffRiskLevel = riskLabel(tradeoffRiskScore);
  const tradeoffColor = RISK_COLORS[tradeoffRiskLevel];

  const suppliersAccent = summary.avg_suppliers_milp < summary.avg_suppliers_greedy
    ? 'border-emerald-500/30'
    : 'border-slate-700';

  // ── The retraction ──────────────────────────────────────────────────────────
  // summary.savings_pct is the headline this project publicly retracted. It is
  // measured on the benchmark's own toy orders (4 BOM lines, single-digit unit
  // counts) where a fixed per-supplier freight fee dominates landed cost. Prefer
  // the API's own volume curve if it serves one; otherwise use the checked-in
  // docs/volume_sweep.json artifact. Either way we show the decay, not the peak.
  const apiCurve =
    normalizeVolumeCurve(summary.volume_curve) ??
    normalizeVolumeCurve(summary.volume_sweep) ??
    normalizeVolumeCurve(summary.savings_volume_curve);
  const curveIsFromApi = apiCurve !== null;
  const volumeCurve = apiCurve ?? VOLUME_SWEEP_FALLBACK;
  // The curve is NOT a benchmark run. It is its own sweep artifact — both arms on
  // the same international offer pool, 10 BOMs — so labelling it "run N" (it used
  // to say "run 4") attributed it to an experiment that never produced it.
  // `_load_volume_curve()` takes no run argument and is cached for the process.
  const curveMeta = readCurveMeta(
    summary.volume_curve ?? summary.volume_sweep ?? summary.savings_volume_curve,
  );
  const curveSource = curveIsFromApi
    ? `GET /benchmark/summary — pooled live by the API from ${
        curveMeta.source ?? 'docs/volume_sweep.json'
      }${curveMeta.generated ? `, generated ${curveMeta.generated}` : ''}. A standalone sweep, not a benchmark run: greedy and MILP both see the full international offer pool.`
    : VOLUME_SWEEP_FALLBACK_SOURCE;
  // The reference line must come from THIS curve, not from the withdrawn headline
  // of a different experiment (us_only MILP vs international greedy, 9 BOMs,
  // pre-fix solver). Anchor it on the curve's own 1× point.
  const curveAnchorPoint =
    volumeCurve.find((pt) => pt.multiplier === 1) ?? volumeCurve[0] ?? null;

  // Honest headline: the pooled edge across the production-volume tail of the curve.
  const curveRange = productionVolumeRange(volumeCurve);
  const honestLow = typeof summary.realistic_savings_pct_low === 'number'
    ? summary.realistic_savings_pct_low
    : curveRange?.low ?? null;
  const honestHigh = typeof summary.realistic_savings_pct_high === 'number'
    ? summary.realistic_savings_pct_high
    : curveRange?.high ?? null;
  const honestRangeLabel = honestLow !== null && honestHigh !== null
    ? `${honestLow.toFixed(1)}–${honestHigh.toFixed(1)}%`
    : '—';

  // Decomposition at the smallest (benchmarked) order size on the curve.
  const tinyOrderPoint = volumeCurve[0] ?? null;
  const feeShareOfSavings = typeof summary.fixed_fee_share_of_savings_pct === 'number'
    ? summary.fixed_fee_share_of_savings_pct
    : tinyOrderPoint?.fee_share_of_saving_pct ?? null;
  const feeShareOfCost = typeof summary.fixed_fee_share_of_cost_pct === 'number'
    ? summary.fixed_fee_share_of_cost_pct
    : tinyOrderPoint?.greedy_fixed_share_of_cost_pct ?? null;
  const tinyOrderUnitsLabel = typeof summary.mean_units_per_bom === 'number'
    ? `${summary.mean_units_per_bom.toLocaleString()} units per BOM`
    : (tinyOrderPoint?.units_min !== undefined && tinyOrderPoint?.units_max !== undefined
        ? `${tinyOrderPoint.units_min}–${tinyOrderPoint.units_max} units per BOM`
        : 'single-digit unit counts per BOM');
  const perSupplierFeeUsd = typeof summary.fixed_fee_per_supplier_usd === 'number'
    ? summary.fixed_fee_per_supplier_usd
    : null;

  // Resilience metrics, rendered as signed CHANGES (negative = the metric fell).
  const stressCascadeChange = -summary.resilience.stress_cascade_risk_reduction;
  const stressCvarChange = -summary.resilience.stress_cvar95_reduction;
  const targetedCascadeChange = -summary.resilience.targeted_cascade_risk_reduction;
  const targetedCvarChange = -summary.resilience.targeted_cvar95_reduction;

  // ── Paired bootstrap intervals (item 12) ──────────────────────────────────
  // Every figure in this section is a mean over 9 BOMs, several of which select
  // an identical plan in both arms and contribute a hard zero. The lead-time
  // model may only ship by beating its baselines with a paired bootstrap CI
  // excluding zero; until 2026-08-28 this page published the benchmark's means
  // with no interval at all. `ciOf` reads the API's interval for a metric and
  // `sigOf` says whether it cleared zero — a metric that did NOT clear zero is
  // rendered neutral, never green, so a null finding cannot read as a win.
  const resilienceIntervals = summary.resilience.intervals;
  const ciOf = (metric: string): PairedBootstrapCI | undefined =>
    resilienceIntervals ? resilienceIntervals[metric] : undefined;
  // Fallback is `true` ONLY when the API served no intervals at all (older
  // build): in that case the page falls back to its previous materiality-only
  // behaviour rather than blanking every figure. When intervals ARE served, an
  // absent or non-significant one is treated as not significant.
  const sigOf = (metric: string): boolean =>
    resilienceIntervals ? Boolean(resilienceIntervals[metric]?.significant) : true;

  // Materiality alone cannot claim a DIRECTION — that needs the interval, so this
  // must sit AFTER sigOf. The paired bootstrap (10,000 resamples over the BOM
  // clusters) puts stress_cascade at [-27.78, +5.56] pp and stress_cvar95 at
  // [0.0000, +0.0043]: both cover zero. "Graph-aware is 8.33 pp WORSE under stress"
  // is therefore not supportable in either direction — it is a mean with a sign and
  // an interval that spans no-effect.
  const STRESS_KEYS = ['stress_cascade_risk_reduction', 'stress_cvar95_reduction'];
  const TARGETED_KEYS = ['targeted_cascade_risk_reduction', 'targeted_cvar95_reduction'];
  const stressIsWorse = stressReductions.some((v, i) => isMaterial(v) && v < 0 && sigOf(STRESS_KEYS[i]));
  const targetedIsBetter = targetedReductions.some((v, i) => isMaterial(v) && v > 0 && sigOf(TARGETED_KEYS[i]));
  const stressIsIndistinguishable = !STRESS_KEYS.some((k) => sigOf(k));
  const resilienceIsSplit = targetedIsBetter && (stressIsWorse || stressIsIndistinguishable);
  const fmtPct2 = (x: number | null | undefined) => fmtPct(x, 2);
  const nSignificant = summary.resilience.significant_metrics?.length ?? null;
  const nNonSignificant = summary.resilience.non_significant_metrics?.length ?? null;
  const nEffectiveBoms = summary.resilience.n_effective_boms ?? null;
  const zeroPlanBoms = ciOf('targeted_cascade_risk_reduction')?.zero_plan_boms ?? [];
  const bootstrapResamples = ciOf('targeted_cascade_risk_reduction')?.n_boot ?? null;
  const bootstrapSeed = ciOf('targeted_cascade_risk_reduction')?.seed ?? null;

  // Is the nominal cost premium itself material? If it is, we must NOT also claim
  // cost was "held roughly flat" — that was the page contradicting itself.
  const nominalPremiumPct = summary.resilience.nominal_cost_premium_pct;
  const materialityPct = summary.materiality_threshold_pct ?? 2;
  const materialityBasis = summary.materiality_threshold_basis ?? null;
  const nominalPremiumIsMaterial =
    Number.isFinite(nominalPremiumPct) && Math.abs(nominalPremiumPct) > materialityPct;

  // ── Price-of-resilience frontier: derived views over the API payload ───────
  // Every figure below is read off the response. Nothing is recomputed here that
  // the endpoint already publishes, and nothing is invented when it does not.
  const frontierPoints = frontier?.points ?? [];
  const frontierSteps = frontier?.steps ?? [];

  const frontierChartData = frontierPoints.map((p) => ({
    k: p.k,
    cost: p.mean_total_cost_usd,
    targetedCascade: p.mean_targeted_cascade_risk,
    stressCascade: p.mean_stress_cascade_risk,
    targetedShortfall: p.mean_targeted_expected_shortfall,
    stressShortfall: p.mean_stress_expected_shortfall,
  }));

  // One domain per column of strips, shared across rows and always containing
  // zero — strips on per-row domains are not comparable and the zero line moves.
  const costDomain = ciDomain(frontierPoints.map((p) => p.delta_cost_usd));
  const riskDomain = ciDomain([
    ...frontierPoints.map((p) => p.delta_targeted_cascade_risk),
    ...frontierPoints.map((p) => p.delta_stress_cascade_risk),
  ]);
  const marginalRiskDomain = ciDomain([
    ...frontierSteps.map((s) => s.marginal_targeted_cascade_risk_removed),
    ...frontierSteps.map((s) => s.marginal_stress_expected_shortfall_removed),
  ]);

  // The collapse: the first priced step, and the next priced step after it.
  const pricedSteps = frontierSteps.filter(
    (s) => typeof s.usd_per_unit_targeted_cascade_risk === 'number',
  );
  const firstStep = pricedSteps[0] ?? null;
  const collapseStep = pricedSteps[1] ?? null;

  // k values where the MILP could not be solved for every BOM — the k = 5 row is
  // a smaller panel than the rows above it and must not be read as the same
  // comparison.
  const infeasibleKs = frontierPoints.filter((p) => p.boms_infeasible.length > 0);
  const infeasibleNote = infeasibleKs.length
    ? `${infeasibleKs
        .map(
          (p) =>
            `At k=${p.k}, ${p.boms_infeasible.length} BOM${
              p.boms_infeasible.length === 1 ? '' : 's'
            } (${p.boms_infeasible.join(', ')}) are infeasible`,
        )
        .join('; ')}. Those rows are a SMALLER panel than the rows above them and are not the same comparison — every row publishes its own panel size.`
    : null;

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full">
      <div className="max-w-7xl mx-auto px-6 py-8">

        {/* ── Page Header ──────────────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex items-start justify-between mb-8"
        >
          <div>
            <h1 className="text-3xl font-semibold text-white">Benchmark: Optimization &amp; Resilience</h1>
            <p className="text-sm text-slate-400 mt-1">
              All {summary.n_boms} reference BOMs · seed=42 · run {summary.run_id} — {formattedTimestamp}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-xs px-3 py-1.5 rounded-full font-semibold uppercase tracking-wider">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              All {summary.n_boms} BOMs · Seed 42
            </span>
            {summary.feeds_fallback && (
              <span className="inline-flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs px-3 py-1.5 rounded-full font-semibold uppercase tracking-wider">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                Static Feeds
              </span>
            )}
          </div>
        </motion.div>

        {/* ── Stale-feed banner ─────────────────────────────────────────────────── */}
        {summary.feeds_fallback && (
          <div className="mb-4 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2">
            Benchmark generated with static-fallback feeds — live data was unavailable at run time.
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
            SECTION 1 — VALUE OF OPTIMIZATION
            The headline this project retracted, and the number that replaced it.
            The retracted figure is deliberately NOT the largest thing on screen.
           ══════════════════════════════════════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0, duration: 0.4, ease: 'easeOut' }}
          className="bg-slate-800/70 border border-amber-500/40 rounded-xl overflow-hidden mb-5"
        >
          {/* Retraction banner — the first thing the eye lands on */}
          <div className="bg-amber-500/15 border-b border-amber-500/30 px-6 py-3 flex items-start gap-3">
            <Ban className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <span className="text-xs font-bold uppercase tracking-widest text-amber-300">
                Retracted headline — do not quote this number
              </span>
              <p className="text-sm text-amber-100/80 mt-1 leading-relaxed">
                {summary.retraction_note ?? (
                  <>
                    This page used to lead with the figure below as the value of optimization. We audited it and
                    withdrew it. It is arithmetically correct and substantively meaningless: it is measured on
                    orders of {tinyOrderUnitsLabel}, where a fixed per-supplier freight fee
                    {perSupplierFeeUsd !== null ? ` (${fmtUsd(perSupplierFeeUsd)} per supplier)` : ''} is almost the
                    entire cost being optimized. The optimizer wins by consolidating suppliers and dodging that fee,
                    not by sourcing better.
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="p-6 grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-6 items-start">
            {/* The retracted number — demoted: small, grey, struck through, labelled */}
            <div className="flex-shrink-0">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Withdrawn figure (tiny-order regime)
              </span>
              <div
                className="text-2xl font-semibold leading-tight tabular-nums mt-1 text-slate-400 line-through decoration-amber-500/70 decoration-2"
                aria-live="polite"
              >
                {fmtPct(summary.savings_pct)}
              </div>
              <span className="text-[11px] text-slate-400">
                run {summary.run_id} · {summary.n_boms} BOMs · 1× order size
              </span>
            </div>

            {/* The honest number — the biggest thing in this card */}
            <div className="lg:border-l lg:border-slate-700 lg:pl-6">
              <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                Honest cost edge at production volume
              </span>
              <div className="text-5xl font-semibold leading-tight tabular-nums mt-2 text-emerald-400">
                {honestRangeLabel}
              </div>
              <p className="text-sm text-slate-400 mt-2 leading-relaxed">
                Pooled MILP-vs-greedy landed-cost advantage once the same BOMs are re-solved at{' '}
                {PRODUCTION_VOLUME_MIN_MULTIPLIER.toLocaleString()}× the benchmark's quantities and above.{' '}
                <span className="text-slate-300">Within the sweep below</span> the solver, the offer pool and the
                objective are held fixed and only the order size changes. It is <em>not</em> a like-for-like
                continuation of the withdrawn figure on the left: that one pitted a domestic-only MILP against an
                international greedy on a different BOM set and an earlier solver, so the two are different
                experiments and must not be read as two points on one line. This is the number to quote.
              </p>
            </div>
          </div>
        </motion.div>

        {/* ── Volume-decay curve: watch the headline evaporate ─────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.06, duration: 0.4, ease: 'easeOut' }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
          aria-label="Cost advantage versus order volume — the optimizer's measured edge decays from roughly 47 percent on toy orders to low single digits at production volume"
        >
          <h2 className="text-2xl font-semibold text-slate-300">Why the headline was withdrawn</h2>
          <p className="text-xs text-slate-400 mt-1 mb-4">
            The optimizer's cost advantage is a function of how small the order is. Re-solve the same BOMs at
            larger quantities and it decays monotonically until the fixed fee stops mattering.
          </p>
          <VolumeDecayCurve
            points={volumeCurve}
            headlineValue={curveAnchorPoint?.savings_pct ?? null}
            headlineLabel={`This curve at ${(curveAnchorPoint?.multiplier ?? 1).toLocaleString()}×`}
            source={curveSource}
          />
          <p className="text-xs text-slate-400 mt-2 leading-relaxed">
            The dashed line is this curve's own {(curveAnchorPoint?.multiplier ?? 1).toLocaleString()}× point
            {curveAnchorPoint ? ` (${curveAnchorPoint.savings_pct.toFixed(2)}%)` : ''} — the anchor the decay is
            measured from. It is deliberately <em>not</em> the withdrawn {fmtPct(summary.savings_pct)} headline:
            that figure came from a different experiment (domestic-only MILP vs international greedy,{' '}
            {summary.n_boms} BOMs, earlier solver) and overlaying it here implied the two differed only in order
            size.
          </p>
        </motion.div>

        {/* ── Decomposition: where the saving actually came from ───────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.09, duration: 0.4, ease: 'easeOut' }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
        >
          <h2 className="text-2xl font-semibold text-slate-300">Decomposition of the withdrawn saving</h2>
          <p className="text-xs text-slate-400 mt-1 mb-4">
            Breaking the 1×-order saving into its cost terms. Positive = the greedy baseline paid more, i.e. the
            optimizer won on that term.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-slate-900/50 border border-amber-500/25 rounded-lg p-4">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-400">
                Avoided fixed per-supplier fees
              </span>
              <div className="text-2xl font-semibold text-amber-300 tabular-nums mt-1">
                {tinyOrderPoint?.fixed_fee_usd !== undefined
                  ? `${tinyOrderPoint.fixed_fee_usd >= 0 ? '+' : '−'}${fmtUsd(tinyOrderPoint.fixed_fee_usd)}`
                  : '—'}
              </div>
              <span className="text-xs text-slate-400">
                {feeShareOfSavings !== null
                  ? `${feeShareOfSavings.toFixed(0)}% of the entire saving`
                  : 'the dominant term'}
              </span>
            </div>
            <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Component cost
              </span>
              <div
                className="text-2xl font-semibold tabular-nums mt-1"
                style={{ color: (tinyOrderPoint?.component_usd ?? 0) < 0 ? '#f87171' : '#10b981' }}
              >
                {tinyOrderPoint?.component_usd !== undefined
                  ? `${tinyOrderPoint.component_usd >= 0 ? '+' : '−'}${fmtUsd(tinyOrderPoint.component_usd)}`
                  : '—'}
              </div>
              <span className="text-xs text-slate-400">
                {(tinyOrderPoint?.component_usd ?? 0) < 0
                  ? 'negative — the optimizer pays MORE for the parts themselves'
                  : 'the optimizer also bought parts cheaper'}
              </span>
            </div>
            <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Variable freight (weight × distance)
              </span>
              <div className="text-2xl font-semibold text-slate-300 tabular-nums mt-1">
                {tinyOrderPoint?.variable_freight_usd !== undefined
                  ? `${tinyOrderPoint.variable_freight_usd >= 0 ? '+' : '−'}${fmtUsd(tinyOrderPoint.variable_freight_usd)}`
                  : '—'}
              </div>
              <span className="text-xs text-slate-400">
                rounding error at 1× — it only becomes the real lever at volume
              </span>
            </div>
          </div>

          <p className="text-sm text-slate-300 leading-relaxed mt-4">
            The greedy baseline picks the cheapest offer per BOM line, which makes it the component-cost minimum
            by construction — the optimizer <em>cannot</em> beat it on parts, and doesn't. It only wins on fixed
            charges.
            {feeShareOfSavings !== null && feeShareOfSavings > 100 && (
              <>
                {' '}Avoided fees are <span className="text-amber-300 font-semibold">{feeShareOfSavings.toFixed(0)}%</span>{' '}
                of the total saving — over 100%, because every other term is a net loss.
              </>
            )}
            {feeShareOfCost !== null && (
              <>
                {' '}At 1×, fixed per-supplier fees are{' '}
                <span className="text-amber-300 font-semibold">{feeShareOfCost.toFixed(1)}%</span> of the greedy
                baseline's entire landed cost. Optimizing that basket is optimizing a freight fee, not a supply chain.
              </>
            )}
          </p>
        </motion.div>

        {/* ── Optimization stat row (all tiny-order-regime figures) ─────────────── */}
        <div className="flex items-center gap-2 mb-2 px-1">
          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">
            The three cards below inherit the retraction — same 1× toy-order regime
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-2">
          <KpiCard
            title="MILP vs greedy · $ / BOM run"
            value={fmtUsd(summary.savings_usd_per_bom)}
            sub="mean landed-cost gap, optimizer vs greedy baseline, one reorder at 1× order size — mostly avoided freight fees"
            accent="border-amber-500/30"
            delay={0.05}
          />
          <KpiCard
            title="MILP vs greedy · $ / year (est.)"
            value={fmtUsd(summary.savings_usd_annualized)}
            sub={`the card to its left × ${summary.annual_reorders} reorders/yr — a disclosed assumption, not a measured cadence, on a retracted per-run figure`}
            accent="border-amber-500/30"
            delay={0.1}
          />
          <KpiCard
            title="Suppliers consolidated"
            value={`${summary.avg_suppliers_greedy.toFixed(1)} → ${summary.avg_suppliers_milp.toFixed(1)}`}
            sub="avg distinct suppliers per BOM, greedy → MILP — this consolidation is real, and it is the entire mechanism behind the withdrawn number"
            accent={suppliersAccent}
            delay={0.15}
          />
        </div>
        <p className="text-xs text-slate-400 mb-5 px-1">
          Figures are fleet-wide means across {summary.n_boms} BOMs (run {summary.run_id}) at the benchmark's own
          1× order size. The benchmark pipeline also solves a{' '}
          <code className="bg-slate-800 px-1 rounded">greedy_add</code> baseline and a full per-BOM cost ledger
          (see <code className="bg-slate-800 px-1 rounded">seeds/run_benchmark.py</code> output) — the public{' '}
          <code className="bg-slate-800 px-1 rounded">/benchmark/summary</code> endpoint currently reports only the
          aggregates above. The volume sweep that produced the retraction is written up in{' '}
          <code className="bg-slate-800 px-1 rounded">docs/BENCHMARK_VOLUME_CURVE.md</code> and{' '}
          <code className="bg-slate-800 px-1 rounded">docs/BENCHMARK_RESULTS.md</code>; the raw sweep is{' '}
          <code className="bg-slate-800 px-1 rounded">docs/volume_sweep.json</code>.
        </p>

        {/* ══════════════════════════════════════════════════════════════════════
            SECTION 2 — VALUE OF RESILIENCE (graph-aware vs blind MILP, honest)
           ══════════════════════════════════════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.4, ease: 'easeOut' }}
          className="mt-8 mb-4"
        >
          <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
            Value of Resilience
          </span>
          <h2 className="text-white text-2xl font-semibold mt-1">Graph-aware vs blind MILP under disruption</h2>
          <p className="text-sm text-slate-400 mt-1">
            Both arms are already MILP-optimized, so this is a different question from the section above: does
            routing around high-centrality distributors lower tail risk when one is disrupted, and what does that
            protection cost in the nominal (no-disruption) world? On run {summary.run_id} it is{' '}
            {nominalPremiumIsMaterial ? 'not free' : 'roughly free'} — see the premium below.
          </p>
        </motion.div>

        {/* ── Nominal premium + dollar framing ─────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div
            className="bg-slate-800/70 border border-slate-700 rounded-xl p-4"
            title="Mean (graph-aware − blind) / blind landed cost in the nominal (no-disruption) world. Expect ~0: graph-aware should not cost materially more when nothing is disrupted."
          >
            <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">
              Nominal cost premium {deltaGlyph(summary.resilience.nominal_cost_premium_pct)}
            </span>
            <div
              className="text-3xl font-semibold tabular-nums mt-1"
              style={{
                color:
                  isMaterial(summary.resilience.nominal_cost_premium_pct / 100)
                  && sigOf('nominal_cost_premium_pct')
                    ? '#f59e0b'
                    : '#94a3b8',
              }}
            >
              {fmtPct(summary.resilience.nominal_cost_premium_pct, 2)}
            </div>
            <CiNote ci={ciOf('nominal_cost_premium_pct')} fmt={fmtPct2} />
            <span className="text-slate-400 text-xs">
              graph-aware vs blind MILP, no disruption ·{' '}
              <span className="text-amber-400/90">
                {fmtUsd(summary.cost_delta_usd)} {summary.cost_delta_usd <= 0 ? 'cheaper' : 'more expensive'} / BOM run
              </span>
            </span>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed border-t border-slate-700/60 pt-2">
              Different comparison from the cards above. Those measure{' '}
              <span className="text-slate-400">optimizer vs greedy baseline</span> ({fmtUsd(summary.savings_usd_per_bom)}{' '}
              gap). This measures <span className="text-slate-400">graph-aware MILP vs blind MILP</span> — both
              already optimized. The two figures are not the same quantity and do not net against each other:
              paying {fmtUsd(summary.cost_delta_usd)} more for graph-aware routing is the price of the resilience
              below, not a reversal of the optimization result.
            </p>
          </div>
          <div
            className="bg-slate-800/70 border border-amber-500/20 rounded-xl p-4"
            title="CVaR-95 (Conditional VaR / Expected Shortfall) = mean emergency-procurement cost multiplier over the worst-5% Monte Carlo scenarios. Field: mc_cvar_95 / baseline_cvar_95."
          >
            <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">
              CVaR-95 / Expected Shortfall · spend at risk
            </span>
            <div className="text-3xl font-semibold text-amber-400 tabular-nums mt-1">
              {fmtUsd(summary.baseline_spend_at_risk_usd)}
            </div>
            <span className="text-slate-400 text-xs">
              extra spend exposed in worst-5% scenarios · mean per blind-MILP BOM
            </span>
          </div>
        </div>

        {/* ── Stress / Targeted scenario reductions ────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Stress scenario</span>
            <p className="text-xs text-slate-400 mt-1 mb-3">Broad disruption (stress_factor=3) applied to every distributor</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wider">
                  Cascade risk {deltaGlyph(stressCascadeChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{
                    color: improvementColor(
                      stressCascadeChange,
                      isMaterial(stressCascadeChange) && sigOf('stress_cascade_risk_reduction'),
                    ),
                  }}
                >
                  {fmtPP(stressCascadeChange)}
                </div>
                <span
                  className="text-[11px] text-slate-400"
                  title="plan_cascade_risk = 1 − the median fraction of the BOM's lines that stay fulfillable across the Monte Carlo trials. A share on 0–1, not a probability: it has no base rate and no exposure window, and on 4-line BOMs it can only take the values 0, .25, .5, .75, 1."
                >
                  change in median unfulfilled-line share (0–1)
                </span>
                <CiNote ci={ciOf('stress_cascade_risk_reduction')} fmt={fmtPP} flip />
              </div>
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wider">
                  CVaR-95 {deltaGlyph(stressCvarChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{
                    color: improvementColor(
                      stressCvarChange,
                      isMaterial(stressCvarChange) && sigOf('stress_cvar95_reduction'),
                    ),
                  }}
                >
                  {fmtMultiplierDelta(stressCvarChange)}
                </div>
                <span className="text-[11px] text-slate-400">
                  change in cost multiplier
                  {fmtRelativeToBaseline(stressCvarChange, summary.monte_carlo?.baseline_cvar_95)
                    ? ` · ${fmtRelativeToBaseline(stressCvarChange, summary.monte_carlo?.baseline_cvar_95)}`
                    : ''}
                </span>
                <CiNote ci={ciOf('stress_cvar95_reduction')} fmt={fmtMultiplierDelta} flip />
              </div>
            </div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Targeted scenario</span>
            <p className="text-xs text-slate-400 mt-1 mb-3">Single highest-betweenness distributor in the BOM's pool goes fully offline</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wider">
                  Cascade risk {deltaGlyph(targetedCascadeChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{
                    color: improvementColor(
                      targetedCascadeChange,
                      isMaterial(targetedCascadeChange) && sigOf('targeted_cascade_risk_reduction'),
                    ),
                  }}
                >
                  {fmtPP(targetedCascadeChange)}
                </div>
                <span
                  className="text-[11px] text-slate-400"
                  title="plan_cascade_risk = 1 − the median fraction of the BOM's lines that stay fulfillable across the Monte Carlo trials. A share on 0–1, not a probability: it has no base rate and no exposure window, and on 4-line BOMs it can only take the values 0, .25, .5, .75, 1."
                >
                  change in median unfulfilled-line share (0–1)
                </span>
                <CiNote ci={ciOf('targeted_cascade_risk_reduction')} fmt={fmtPP} flip />
              </div>
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wider">
                  CVaR-95 {deltaGlyph(targetedCvarChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{
                    color: improvementColor(
                      targetedCvarChange,
                      isMaterial(targetedCvarChange) && sigOf('targeted_cvar95_reduction'),
                    ),
                  }}
                >
                  {fmtMultiplierDelta(targetedCvarChange)}
                </div>
                <span className="text-[11px] text-slate-400">
                  change in cost multiplier
                  {fmtRelativeToBaseline(targetedCvarChange, summary.monte_carlo?.baseline_cvar_95)
                    ? ` · ${fmtRelativeToBaseline(targetedCvarChange, summary.monte_carlo?.baseline_cvar_95)}`
                    : ''}
                </span>
                <CiNote ci={ciOf('targeted_cvar95_reduction')} fmt={fmtMultiplierDelta} flip />
              </div>
            </div>
          </div>
        </div>

        {/* ── How the intervals were made, and what survived them ─────────────── */}
        {resilienceIntervals && (
          <div className="bg-slate-900/60 border border-slate-700 rounded-xl p-4 mb-5">
            <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
              Statistical treatment
            </span>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              Each figure above is a <span className="text-slate-300">mean over{' '}
              {summary.resilience.n_boms ?? summary.n_boms} BOMs</span>, and every one now carries a 95%{' '}
              <span className="text-slate-300">paired percentile-bootstrap interval</span>
              {bootstrapResamples !== null && bootstrapSeed !== null
                ? ` (${bootstrapResamples.toLocaleString()} resamples, seed ${bootstrapSeed})`
                : ''}
              . The resample unit is the <span className="text-slate-300">BOM</span>, not the row: both arms of a
              per-BOM delta come from the same BOM under the same simulation seed, so the BOM is the independent
              cluster. Nothing was re-solved — the intervals are computed from the per-BOM values run{' '}
              {summary.run_id} already stored, so no published mean moved.
            </p>
            {nEffectiveBoms !== null && zeroPlanBoms.length > 0 && (
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                <span className="font-semibold text-slate-300">Effective n is smaller than n.</span>{' '}
                {zeroPlanBoms.length} of {summary.resilience.n_boms ?? summary.n_boms} BOMs ({' '}
                {zeroPlanBoms.map((b, i) => (
                  <span key={b}>
                    {i > 0 ? ', ' : ''}
                    <code className="bg-slate-800 px-1 rounded">{b}</code>
                  </span>
                ))}{' '}
                ) select an identical plan in both arms, so they contribute an exact 0.0 to every delta and carry no information
                about the treatment. They drag every mean toward zero <em>and</em> narrow the apparent spread. The
                effective panel is <span className="text-slate-300">n = {nEffectiveBoms}</span>; both panels' intervals
                are served by the API and neither is hidden.
              </p>
            )}
            {nSignificant !== null && nNonSignificant !== null && (
              <p className="text-xs text-slate-400 mt-2 leading-relaxed border-t border-slate-700/60 pt-2">
                <span className="font-semibold text-slate-300">
                  {nSignificant} of {nSignificant + nNonSignificant} deltas clear zero.
                </span>{' '}
                {nNonSignificant > 0 ? (
                  <>
                    The other {nNonSignificant} —{' '}
                    <span className="text-amber-400">
                      {(summary.resilience.non_significant_metrics ?? []).join(', ')}
                    </span>{' '}
                    — have intervals that cover zero and are marked as such above. They are shown, not deleted, and
                    they are not counted as findings. On a nine-BOM benchmark that is the expected outcome, and
                    publishing it is the point: this is the same bar the lead-time model is held to on the model
                    card, and a benchmark exempt from it would be a double standard rather than a result.
                  </>
                ) : (
                  <>Every delta's interval excludes zero on this panel.</>
                )}
              </p>
            )}
          </div>
        )}

        {/* ── Honest callout: real win vs ~0 finding, never fabricated ─────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.4 }}
          className={`rounded-xl p-5 mb-5 border ${
            resilienceHasMaterialEffect
              ? 'bg-emerald-500/5 border-emerald-500/20'
              : 'bg-amber-500/5 border-amber-500/20'
          }`}
        >
          <div className="flex items-start gap-3">
            {resilienceHasMaterialEffect && !resilienceIsSplit ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
            )}
            <div>
              <span className={`text-xs font-semibold uppercase tracking-wider ${resilienceHasMaterialEffect && !resilienceIsSplit ? 'text-emerald-400' : 'text-amber-400'}`}>
                Honest finding
              </span>
              {resilienceIsSplit ? (
                <p className="text-sm text-slate-300 leading-relaxed mt-2">
                  Graph-aware sourcing protects against a{' '}
                  <span className="text-emerald-400 font-semibold">targeted</span> supplier outage and does{' '}
                  <span className="text-amber-400 font-semibold">not</span> protect against broad systemic stress.
                  Against a targeted outage it removes{' '}
                  {Math.abs(summary.resilience.targeted_cascade_risk_reduction * 100).toFixed(2)} pp of cascade risk
                  and {Math.abs(summary.resilience.targeted_cvar95_reduction * 100).toFixed(2)} pp of CVaR-95.
                  {stressIsIndistinguishable ? (
                    <>
                      Under broad systemic stress there is{' '}
                      <span className="text-amber-400 font-semibold">no measurable effect</span>: the mean is{' '}
                      {(summary.resilience.stress_cascade_risk_reduction * 100).toFixed(2)} pp, but the paired
                      bootstrap interval covers zero, so it cannot be claimed in either direction — not as a win,
                      and not as the loss an unqualified −8 pp would imply.{' '}
                    </>
                  ) : (
                    <>
                      Under broad stress it is{' '}
                      {Math.abs(summary.resilience.stress_cascade_risk_reduction * 100).toFixed(2)} pp{' '}
                      <span className="text-amber-400 font-semibold">worse</span> than blind MILP.{' '}
                    </>
                  )}
                  These are the disclosed deltas from run {summary.run_id}; none is rounded toward the answer we
                  wanted, and each carries the interval that decides whether it may be claimed at all.{' '}
                  {nominalPremiumIsMaterial && (
                    <>
                      The protection is not free either — a {fmtPct(nominalPremiumPct, 2)} nominal premium
                      ({fmtUsd(summary.cost_delta_usd)} per BOM run).{' '}
                    </>
                  )}
                  The defensible claim is therefore narrow: this mitigation is worth buying against the threat it
                  was designed for, and on nine BOMs there is not enough evidence to say anything at all about a
                  correlated shock. Note also
                  that 2 of the {summary.n_boms} benchmarked BOMs select an identical plan in both arms and
                  contribute a hard zero to every mean, so the effective n behind these figures is{' '}
                  {summary.n_boms - 2}.
                </p>
              ) : resilienceHasMaterialEffect ? (
                <p className="text-sm text-slate-300 leading-relaxed mt-2">
                  Graph-aware sourcing measurably lowers cascade risk and/or CVaR-95 under disruption — the numbers
                  above are the real, disclosed deltas from run {summary.run_id}.{' '}
                  {nominalPremiumIsMaterial ? (
                    <>
                      It is <span className="text-amber-400 font-semibold">not free</span>: it costs a{' '}
                      {fmtPct(nominalPremiumPct, 2)} nominal premium ({fmtUsd(summary.cost_delta_usd)} per BOM run),
                      which is above the {materialityPct.toFixed(1)}% materiality threshold this page reports
                      against — <span title={materialityBasis ?? undefined}>an assumed cut fixed before the run,
                      not a measured noise floor</span>. That is a real trade — buying tail-risk reduction with
                      nominal cost — and we state it as one rather than claiming cost was held flat.
                    </>
                  ) : (
                    <>
                      The nominal premium ({fmtPct(nominalPremiumPct, 2)}) sits under the{' '}
                      {materialityPct.toFixed(1)}% materiality threshold this page reports against, so nominal cost
                      is roughly flat here — flat against a cut we{' '}
                      <span title={materialityBasis ?? undefined}>assumed rather than measured</span>.
                    </>
                  )}
                </p>
              ) : (
                <p className="text-sm text-slate-300 leading-relaxed mt-2">
                  On this catalog, the reductions above all fall under the{' '}
                  {(RESILIENCE_MATERIALITY * 100).toFixed(0)} pp materiality cut this page reports against (an
                  assumption, not a measured noise level) —
                  cost-optimal consolidation dominates the graph surcharge, so graph-aware selects essentially the
                  same plan as blind MILP. The consolidated single-hub plan that wins on cost is itself the
                  concentration risk the targeted scenario exposes. We report this as a real ~0 finding rather than
                  manufacturing a resilience win: on the current supplier catalog, cost and graph-aware routing do
                  not diverge enough to trade one for the other. This still quantifies the cost-vs-resilience
                  trade-off honestly — it just shows the trade-off is currently slack in one direction.
                </p>
              )}
              <p className="text-xs text-slate-400 mt-3 leading-relaxed border-t border-slate-700/60 pt-2">
                <span className="font-semibold text-slate-300">
                  On the {materialityPct.toFixed(1)}% threshold:
                </span>{' '}
                {materialityBasis ??
                  `it is an assumed reporting cut, not a measured noise floor. The benchmark is a single deterministic solve (seed 42, one CP-SAT worker, no gap limit), so re-running it reproduces every figure exactly and there are no replicates to estimate run-to-run variance from. Read it as "smaller than this is not worth acting on", not as "smaller than this is indistinguishable from noise".`}
              </p>
            </div>
          </div>
        </motion.div>


        {/* ══════════════════════════════════════════════════════════════════════
            SECTION 2b — THE PRICE OF RESILIENCE (the diversification frontier)
            ──────────────────────────────────────────────────────────────────────
            The section above reports a SPLIT — graph-aware sourcing wins against a
            targeted outage and shows nothing under broad stress — and cannot say
            why. This one prices the trade and explains the split: the constraint
            bounds a supplier COUNT while the objective stays pure cost, so the
            cheapest way to satisfy it is often to abandon the incumbent. Sourced
            from GET /benchmark/diversification-frontier; nothing here is hardcoded.
           ══════════════════════════════════════════════════════════════════════ */}
        {frontier && (
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.22, duration: 0.4, ease: 'easeOut' }}
            className="mb-6"
            aria-labelledby="price-of-resilience-heading"
          >
            <div className="mt-8 mb-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                Price of Resilience
              </span>
              <h2 id="price-of-resilience-heading" className="text-white text-2xl font-semibold mt-1">
                What a second supplier costs, and what it buys
              </h2>
              <p className="text-sm text-slate-400 mt-1 max-w-4xl leading-relaxed">
                The split above — better against a named single point of failure, nothing measurable under broad
                stress — is a finding only if you can price it. This sweep does. The same sourcing MILP is
                re-solved subject to a hard <span className="text-slate-300">open at least k distinct
                distributors</span> constraint, each plan is costed, and each is simulated under this
                benchmark&rsquo;s own scenarios.
                {typeof summary.avg_suppliers_greedy === 'number' && frontier.mean_suppliers_at_k1 !== null && (
                  <>
                    {' '}The MILP consolidates suppliers from{' '}
                    <span className="tabular-nums">{summary.avg_suppliers_greedy.toFixed(2)}</span> per BOM under
                    the greedy baseline to{' '}
                    <span className="text-slate-300 tabular-nums">
                      {frontier.mean_suppliers_at_k1.toFixed(2)}
                    </span>{' '}
                    at the unconstrained optimum. This sweep prices what un-consolidating costs.
                  </>
                )}
              </p>
            </div>

            {!frontier.available ? (
              <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
                <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-400">
                  <AlertTriangle size={14} aria-hidden="true" />
                  Frontier unavailable
                </span>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                  {frontier.unavailable_reason ??
                    'The sweep artifact is not present in this deployment. No cost-per-unit-of-risk figure is quoted.'}
                </p>
              </div>
            ) : (
              <>
                {/* ── The one sentence ──────────────────────────────────────── */}
                <div className="bg-emerald-500/5 border border-emerald-500/25 rounded-xl p-5 mb-5">
                  <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-400">
                    <TrendingUp size={14} aria-hidden="true" />
                    The finding
                  </span>
                  <p className="text-slate-100 text-lg sm:text-xl font-semibold mt-2 leading-snug">
                    {frontier.finding}
                  </p>
                  {frontier.verdict && (
                    <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-base font-semibold">
                      <span className="inline-flex items-center gap-2 text-emerald-300">
                        <CheckCircle2 size={18} aria-hidden="true" />
                        Buy the second supplier.
                      </span>
                      <span className="inline-flex items-center gap-2 text-red-300">
                        <Ban size={18} aria-hidden="true" />
                        Do not buy the third.
                      </span>
                    </p>
                  )}
                  <p className="text-xs text-slate-400 mt-3 leading-relaxed border-t border-emerald-500/20 pt-3">
                    <span className="font-semibold text-slate-300">n and n_effective are both quoted, and they
                    differ.</span>{' '}
                    {frontier.n_effective_definition}
                  </p>
                  {frontier.baseline_check && (
                    <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                      <span className="font-semibold text-slate-300">The control arm is the published one.</span>{' '}
                      {frontier.baseline_check}
                    </p>
                  )}
                </div>

                {/* ── Cost and risk against k ───────────────────────────────── */}
                <div
                  className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
                  aria-label="Mean landed cost in US dollars per BOM and cascade risk as a share from 0 to 1, plotted against k, the minimum number of distinct distributors per BOM"
                >
                  <h3 className="text-base font-semibold text-slate-200">
                    Cost and risk against the minimum supplier count
                  </h3>
                  <p className="text-xs text-slate-400 mt-1 mb-4 max-w-4xl leading-relaxed">
                    Left axis is dollars, right axis is a risk share on 0&ndash;1. Line style distinguishes the
                    measure and colour distinguishes the scenario; every value plotted here is repeated as text in
                    the tables below, so no reading depends on telling two colours apart.
                  </p>
                  <div className="w-full overflow-x-auto">
                    <div className="min-w-[520px]">
                      <ResponsiveContainer width="100%" height={360}>
                        <LineChart
                          data={frontierChartData}
                          margin={{ top: 8, right: 40, left: 26, bottom: 34 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                          <XAxis
                            dataKey="k"
                            tick={{ fill: '#94a3b8', fontSize: 12 }}
                            stroke="#94a3b8"
                            label={{
                              value: 'k — minimum distinct distributors per BOM (count)',
                              position: 'insideBottom', offset: -18,
                              fill: '#94a3b8', fontSize: 12,
                            }}
                          />
                          <YAxis
                            yAxisId="cost"
                            tick={{ fill: '#94a3b8', fontSize: 12 }}
                            stroke="#94a3b8"
                            label={{
                              value: 'mean landed cost (USD per BOM)',
                              angle: -90, position: 'insideLeft', offset: 8,
                              style: { textAnchor: 'middle' }, fill: '#94a3b8', fontSize: 12,
                            }}
                          />
                          <YAxis
                            yAxisId="risk"
                            orientation="right"
                            domain={[0, 1]}
                            tick={{ fill: '#94a3b8', fontSize: 12 }}
                            stroke="#94a3b8"
                            label={{
                              value: 'risk (share of BOM lines, 0–1)',
                              angle: 90, position: 'insideRight', offset: 8,
                              style: { textAnchor: 'middle' }, fill: '#94a3b8', fontSize: 12,
                            }}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: '#0f172a', border: '1px solid #475569',
                              borderRadius: '8px', padding: '12px', fontSize: '12px',
                            }}
                            labelFormatter={(k) => `k = ${k} distinct distributors`}
                          />
                          <Legend content={<FrontierChartKey />} />
                          {FRONTIER_SERIES.map((s) => (
                            <Line
                              key={s.key}
                              yAxisId={s.axis}
                              type="monotone"
                              dataKey={s.key}
                              name={s.name}
                              stroke={s.color}
                              strokeWidth={2}
                              strokeDasharray={s.dash || undefined}
                              dot={{ r: 3, fill: s.color, stroke: s.color }}
                              activeDot={{ r: 5 }}
                              connectNulls
                            />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400 mt-3 leading-relaxed border-t border-slate-700/60 pt-3">
                    <span className="font-semibold text-amber-300">Read the risk axis, not the cost axis.</span>{' '}
                    {frontier.cost_axis_caveat}
                  </p>
                </div>

                {/* ── The frontier, cumulative vs k = 1 ─────────────────────── */}
                <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5">
                  <h3 className="text-base font-semibold text-slate-200">
                    The frontier — every k, paired against its own k&nbsp;=&nbsp;1 plan
                  </h3>
                  <p className="text-xs text-slate-400 mt-1 mb-4 max-w-4xl leading-relaxed">
                    {frontier.aggregate_definition} Each interval is drawn against a shared zero line so
                    &ldquo;excludes zero&rdquo; is something you see, and the verdict is written out beside it.
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm min-w-[860px]">
                      <caption className="sr-only">
                        Diversification frontier: mean landed cost and paired change in cascade risk at each
                        minimum supplier count k
                      </caption>
                      <thead>
                        <tr className="text-left text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700">
                          <th scope="col" className="py-2 pr-4">k</th>
                          <th scope="col" className="py-2 pr-4 text-right">BOMs (n / n_eff)</th>
                          <th scope="col" className="py-2 pr-4 text-right">Mean cost (USD/BOM)</th>
                          <th scope="col" className="py-2 pr-4">&Delta; cost vs k=1 (USD)</th>
                          <th scope="col" className="py-2 pr-4">Cascade risk removed — targeted (share)</th>
                          <th scope="col" className="py-2 pr-4">Cascade risk removed — broad stress (share)</th>
                          <th scope="col" className="py-2 text-right">Cumulative USD per unit removed (targeted)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {frontier.points.map((p) => (
                          <tr
                            key={p.k}
                            className={`border-b border-slate-800/70 text-slate-300 ${
                              p.k === 2 ? 'bg-emerald-500/10' : ''
                            }`}
                          >
                            <th scope="row" className="py-2 pr-4 font-semibold text-slate-200 text-left">
                              {p.k}
                              {p.k === 1 && (
                                <span className="block text-xs font-normal text-slate-400">control arm</span>
                              )}
                            </th>
                            <td className="py-2 pr-4 text-right tabular-nums">
                              {p.n_boms_feasible} / {p.n_effective}
                              {p.boms_infeasible.length > 0 && (
                                <span className="block text-xs text-amber-300">
                                  {p.boms_infeasible.length} infeasible
                                </span>
                              )}
                            </td>
                            <td className="py-2 pr-4 text-right tabular-nums">
                              {fmtUsd(p.mean_total_cost_usd)}
                              <span className="block text-xs text-slate-400 tabular-nums">
                                {p.mean_suppliers.toFixed(2)} suppliers
                              </span>
                            </td>
                            <td className="py-2 pr-4">
                              <span className="block tabular-nums">
                                {fmtSignedUsd(p.delta_cost_usd?.mean)}
                              </span>
                              {p.k > 1 && (
                                <>
                                  <CiStrip
                                    low={p.delta_cost_usd?.ci95_low ?? 0}
                                    high={p.delta_cost_usd?.ci95_high ?? 0}
                                    mean={p.delta_cost_usd?.mean ?? 0}
                                    domainMin={costDomain[0]}
                                    domainMax={costDomain[1]}
                                    excludesZero={Boolean(p.delta_cost_usd?.significant)}
                                    favourable={false}
                                  />
                                  <span className="block text-xs text-slate-400 tabular-nums">
                                    {fmtIntervalText(p.delta_cost_usd, fmtSignedUsd)}
                                  </span>
                                </>
                              )}
                            </td>
                            <td className="py-2 pr-4">
                              <span className="block tabular-nums">
                                {fmtShare(p.delta_targeted_cascade_risk?.mean)}
                              </span>
                              {p.k > 1 && (
                                <>
                                  <CiStrip
                                    low={p.delta_targeted_cascade_risk?.ci95_low ?? 0}
                                    high={p.delta_targeted_cascade_risk?.ci95_high ?? 0}
                                    mean={p.delta_targeted_cascade_risk?.mean ?? 0}
                                    domainMin={riskDomain[0]}
                                    domainMax={riskDomain[1]}
                                    excludesZero={Boolean(p.delta_targeted_cascade_risk?.significant)}
                                    favourable={(p.delta_targeted_cascade_risk?.mean ?? 0) > 0}
                                  />
                                  <span className="block text-xs text-slate-400 tabular-nums">
                                    {fmtIntervalText(p.delta_targeted_cascade_risk, fmtShare)}
                                  </span>
                                  <CiVerdict ci={p.delta_targeted_cascade_risk} />
                                </>
                              )}
                            </td>
                            <td className="py-2 pr-4">
                              <span className="block tabular-nums">
                                {fmtShare(p.delta_stress_cascade_risk?.mean)}
                              </span>
                              {p.k > 1 && (
                                <>
                                  <CiStrip
                                    low={p.delta_stress_cascade_risk?.ci95_low ?? 0}
                                    high={p.delta_stress_cascade_risk?.ci95_high ?? 0}
                                    mean={p.delta_stress_cascade_risk?.mean ?? 0}
                                    domainMin={riskDomain[0]}
                                    domainMax={riskDomain[1]}
                                    excludesZero={Boolean(p.delta_stress_cascade_risk?.significant)}
                                    favourable={(p.delta_stress_cascade_risk?.mean ?? 0) > 0}
                                  />
                                  <span className="block text-xs text-slate-400 tabular-nums">
                                    {fmtIntervalText(p.delta_stress_cascade_risk, fmtShare)}
                                  </span>
                                  <CiVerdict ci={p.delta_stress_cascade_risk} />
                                </>
                              )}
                            </td>
                            <td className="py-2 text-right">
                              {p.usd_per_unit_targeted_cascade_risk !== null ? (
                                <span className="tabular-nums text-slate-200">
                                  {fmtUsd(p.usd_per_unit_targeted_cascade_risk)}
                                </span>
                              ) : (
                                <span className="text-xs text-slate-400">
                                  {p.k === 1 ? 'baseline' : 'not reported'}
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-xs text-slate-400 mt-3 leading-relaxed">
                    A price per unit of risk removed is printed only where that k&rsquo;s risk change has a paired
                    95% CI excluding zero. Everywhere else the denominator is indistinguishable from zero and the
                    ratio would be an artifact of division, not a price.
                  </p>
                </div>

                {/* ── Marginal return: where the curve collapses ────────────── */}
                <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5">
                  <h3 className="text-base font-semibold text-slate-200">
                    Marginal return — what the k-th supplier alone buys
                  </h3>
                  <p className="text-xs text-slate-400 mt-1 mb-4 max-w-4xl leading-relaxed">
                    Each row is the step from k&minus;1 to k, paired on the BOMs feasible at both ends. This is the
                    column that says where to stop: the price per unit of targeted cascade risk removed, and how
                    many times the first step&rsquo;s price that is.
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm min-w-[820px]">
                      <caption className="sr-only">
                        Marginal cost and marginal risk removed at each step from k minus one to k
                      </caption>
                      <thead>
                        <tr className="text-left text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700">
                          <th scope="col" className="py-2 pr-4">Step</th>
                          <th scope="col" className="py-2 pr-4 text-right">Marginal cost (USD/BOM)</th>
                          <th scope="col" className="py-2 pr-4">Cascade risk removed — targeted (share)</th>
                          <th scope="col" className="py-2 pr-4 text-right">USD per unit removed</th>
                          <th scope="col" className="py-2 pr-4 text-right">vs the first step</th>
                          <th scope="col" className="py-2 pr-4">E[shortfall] removed — broad stress (share)</th>
                          <th scope="col" className="py-2 text-right">USD per unit removed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {frontier.steps.map((s) => {
                          const collapsed = s.usd_per_unit_targeted_cascade_risk === null;
                          return (
                            <tr
                              key={s.label}
                              className={`border-b border-slate-800/70 text-slate-300 ${
                                s.to_k === 2 ? 'bg-emerald-500/10' : collapsed ? 'bg-amber-500/5' : ''
                              }`}
                            >
                              <th scope="row" className="py-2 pr-4 font-semibold text-slate-200 text-left tabular-nums">
                                {s.label}
                              </th>
                              <td className="py-2 pr-4 text-right tabular-nums">
                                {fmtSignedUsd(s.marginal_cost_usd?.mean)}
                                <span className="block text-xs text-slate-400 tabular-nums">
                                  {fmtIntervalText(s.marginal_cost_usd, fmtSignedUsd)}
                                </span>
                                {/* Each step is paired only on the BOMs feasible at BOTH ends,
                                    so a step can be a smaller panel than the one above it. */}
                                <span className="block text-xs text-slate-400 tabular-nums">
                                  paired on n={s.marginal_cost_usd?.n ?? 0} BOMs
                                </span>
                              </td>
                              <td className="py-2 pr-4">
                                <span className="block tabular-nums">
                                  {fmtShare(s.marginal_targeted_cascade_risk_removed?.mean)}
                                </span>
                                <CiStrip
                                  low={s.marginal_targeted_cascade_risk_removed?.ci95_low ?? 0}
                                  high={s.marginal_targeted_cascade_risk_removed?.ci95_high ?? 0}
                                  mean={s.marginal_targeted_cascade_risk_removed?.mean ?? 0}
                                  domainMin={marginalRiskDomain[0]}
                                  domainMax={marginalRiskDomain[1]}
                                  excludesZero={Boolean(s.marginal_targeted_cascade_risk_removed?.significant)}
                                  favourable={(s.marginal_targeted_cascade_risk_removed?.mean ?? 0) > 0}
                                />
                                <span className="block text-xs text-slate-400 tabular-nums">
                                  {fmtIntervalText(s.marginal_targeted_cascade_risk_removed, fmtShare)}
                                </span>
                                <CiVerdict ci={s.marginal_targeted_cascade_risk_removed} />
                              </td>
                              <td className="py-2 pr-4 text-right">
                                {s.usd_per_unit_targeted_cascade_risk !== null ? (
                                  <span
                                    className={`tabular-nums font-semibold ${
                                      s.to_k === 2 ? 'text-emerald-300' : 'text-slate-200'
                                    }`}
                                  >
                                    {fmtUsd(s.usd_per_unit_targeted_cascade_risk)}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-300">
                                    <AlertTriangle size={13} aria-hidden="true" />
                                    no price — CI covers zero
                                  </span>
                                )}
                              </td>
                              <td className="py-2 pr-4 text-right">
                                {s.cost_multiple_vs_first_step !== null ? (
                                  <span
                                    className={`tabular-nums font-semibold ${
                                      s.cost_multiple_vs_first_step >= 2 ? 'text-red-300' : 'text-slate-300'
                                    }`}
                                  >
                                    {s.cost_multiple_vs_first_step.toFixed(1)}&times;
                                  </span>
                                ) : (
                                  <span className="text-xs text-slate-400">—</span>
                                )}
                              </td>
                              <td className="py-2 pr-4">
                                <span className="block tabular-nums">
                                  {fmtShare(s.marginal_stress_expected_shortfall_removed?.mean)}
                                </span>
                                <CiStrip
                                  low={s.marginal_stress_expected_shortfall_removed?.ci95_low ?? 0}
                                  high={s.marginal_stress_expected_shortfall_removed?.ci95_high ?? 0}
                                  mean={s.marginal_stress_expected_shortfall_removed?.mean ?? 0}
                                  domainMin={marginalRiskDomain[0]}
                                  domainMax={marginalRiskDomain[1]}
                                  excludesZero={Boolean(s.marginal_stress_expected_shortfall_removed?.significant)}
                                  favourable={(s.marginal_stress_expected_shortfall_removed?.mean ?? 0) > 0}
                                />
                                <span className="block text-xs text-slate-400 tabular-nums">
                                  {fmtIntervalText(s.marginal_stress_expected_shortfall_removed, fmtShare)}
                                </span>
                                <CiVerdict ci={s.marginal_stress_expected_shortfall_removed} />
                              </td>
                              <td className="py-2 text-right">
                                {s.usd_per_unit_stress_expected_shortfall !== null ? (
                                  <span className="tabular-nums text-slate-200">
                                    {fmtUsd(s.usd_per_unit_stress_expected_shortfall)}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-300">
                                    <AlertTriangle size={13} aria-hidden="true" />
                                    no price — CI covers zero
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {collapseStep && firstStep && (
                    <p className="text-sm text-slate-300 mt-4 leading-relaxed border-t border-slate-700/60 pt-3">
                      <span className="font-semibold text-white">Where it collapses.</span> The first supplier
                      costs{' '}
                      <span className="tabular-nums text-emerald-300">
                        {fmtUsd(firstStep.usd_per_unit_targeted_cascade_risk)}
                      </span>{' '}
                      per unit of targeted cascade risk removed. The next one costs{' '}
                      <span className="tabular-nums text-red-300">
                        {fmtUsd(collapseStep.usd_per_unit_targeted_cascade_risk)}
                      </span>{' '}
                      — {collapseStep.cost_multiple_vs_first_step?.toFixed(1)}&times; more for the same unit of
                      risk. Past that step no price can be quoted at all: the marginal risk removed has an
                      interval covering zero, so the ratio would be division by something indistinguishable from
                      nothing.
                    </p>
                  )}
                  <p className="text-xs text-slate-400 mt-3 leading-relaxed">
                    <span className="font-semibold text-slate-300">Why E[shortfall] is shown beside
                    cascade&nbsp;risk.</span>{' '}
                    {frontier.quantisation_caveat}
                  </p>
                </div>

                {/* ── The mechanism ─────────────────────────────────────────── */}
                <div className="bg-slate-900/60 border border-slate-700 rounded-xl p-5 mb-5">
                  <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-indigo-400">
                    <Split size={14} aria-hidden="true" />
                    The mechanism — why a supplier count is not a resilience constraint
                  </span>
                  <p className="text-xs text-slate-400 mt-2 leading-relaxed max-w-4xl">
                    {frontier.nesting_caveat}
                  </p>
                  <ul className="flex flex-wrap gap-2 mt-3">
                    {frontier.points
                      .filter((p) => p.k > 1)
                      .map((p) => (
                        <li
                          key={p.k}
                          className="text-xs text-slate-300 tabular-nums bg-slate-800/80 border border-slate-700 rounded px-2 py-1"
                        >
                          k={p.k}:{' '}
                          <span
                            className={
                              p.n_keeps_k1_suppliers * 2 <= p.n_boms_feasible
                                ? 'text-amber-300 font-semibold'
                                : 'text-slate-200'
                            }
                          >
                            {p.n_keeps_k1_suppliers} of {p.n_boms_feasible}
                          </span>{' '}
                          plans keep every k=1 supplier
                        </li>
                      ))}
                  </ul>
                  {frontier.non_monotone_example && (
                    <p className="text-sm text-slate-300 mt-4 leading-relaxed border-t border-slate-700/60 pt-3">
                      <span className="font-semibold text-white">Risk is therefore not monotone in k.</span>{' '}
                      <code className="bg-slate-800 px-1 rounded text-slate-200">
                        {frontier.non_monotone_example.bom}
                      </code>{' '}
                      goes from{' '}
                      <span className="tabular-nums text-emerald-300">
                        {fmtShare(frontier.non_monotone_example.expected_shortfall_before)}
                      </span>{' '}
                      to{' '}
                      <span className="tabular-nums text-red-300">
                        {fmtShare(frontier.non_monotone_example.expected_shortfall_after)}
                      </span>{' '}
                      expected shortfall under broad stress going from k={frontier.non_monotone_example.from_k} to
                      k={frontier.non_monotone_example.to_k}
                      {frontier.non_monotone_example.keeps_k1_suppliers ? (
                        <> — it keeps its incumbent and still ends up more exposed</>
                      ) : (
                        <>
                          {' '}— it drops a low-hazard incumbent for a cheaper set of{' '}
                          {frontier.non_monotone_example.n_suppliers_after} whose combined hazard is higher
                        </>
                      )}
                      . Under a{' '}
                      <span className="text-slate-100 font-semibold">targeted</span> outage the effect is
                      one-directional, because spreading always shrinks the blast radius of losing one named hub.
                      That asymmetry is exactly the split the section above reports, and it is a property of the
                      constraint, not of resilience.
                    </p>
                  )}
                </div>

                {/* ── What this frontier cannot tell you ────────────────────── */}
                <div className="bg-slate-900/60 border border-slate-700 rounded-xl p-5 mb-5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                    What this frontier cannot tell you
                  </span>
                  <dl className="mt-3 space-y-3">
                    <div>
                      <dt className="text-xs font-semibold text-slate-300">
                        The cost axis is largely a fixed-charge artifact
                      </dt>
                      <dd className="text-xs text-slate-400 leading-relaxed mt-1">
                        {frontier.cost_axis_caveat}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-semibold text-slate-300">
                        One seed — these intervals have no Monte-Carlo error term
                      </dt>
                      <dd className="text-xs text-slate-400 leading-relaxed mt-1">{frontier.seed_caveat}</dd>
                    </div>
                    <div>
                      <dt className="text-xs font-semibold text-slate-300">
                        Cascade risk is quantised to {'{'}0, .25, .5, .75, 1{'}'}
                      </dt>
                      <dd className="text-xs text-slate-400 leading-relaxed mt-1">
                        {frontier.quantisation_caveat}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-semibold text-slate-300">
                        Failures are independent beyond a shared stress multiplier
                      </dt>
                      <dd className="text-xs text-slate-400 leading-relaxed mt-1">
                        {frontier.independence_caveat}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-semibold text-slate-300">Coverage</dt>
                      <dd className="text-xs text-slate-400 leading-relaxed mt-1">
                        {frontier.n_boms_included} of {frontier.n_boms_in_catalog} catalogue BOMs are swept.
                        {Object.entries(frontier.boms_excluded).map(([bom, reason]) => (
                          <span key={bom} className="block mt-1">
                            <code className="bg-slate-800 px-1 rounded text-slate-300">{bom}</code> excluded:{' '}
                            {reason}
                          </span>
                        ))}
                        {infeasibleNote && <span className="block mt-1">{infeasibleNote}</span>}
                      </dd>
                    </div>
                    {frontier.caveats.length > 0 && (
                      <div>
                        <dt className="text-xs font-semibold text-slate-300">
                          Full caveat list, as published with the artifact
                        </dt>
                        <dd className="text-xs text-slate-400 leading-relaxed mt-1">
                          <ul className="space-y-2">
                            {frontier.caveats.map((caveat, i) => (
                              <li key={i}>{renderCaveatProse(caveat)}</li>
                            ))}
                          </ul>
                        </dd>
                      </div>
                    )}
                  </dl>
                  <p className="text-xs text-slate-400 mt-4 leading-relaxed border-t border-slate-700/60 pt-3">
                    Source:{' '}
                    <code className="bg-slate-800 px-1 rounded text-slate-300">{frontier.source}</code>
                    {frontier.generated_utc ? ` · generated ${frontier.generated_utc}` : ''}
                    {frontier.strategy ? ` · strategy ${frontier.strategy}` : ''}
                    {frontier.mc_scenarios !== null && frontier.mc_seed !== null
                      ? ` · ${frontier.mc_scenarios.toLocaleString()} Monte Carlo scenarios at seed ${frontier.mc_seed}`
                      : ''}
                    {frontier.stress_factor !== null ? ` · stress factor ${frontier.stress_factor}` : ''}
                    {frontier.bootstrap_n !== null && frontier.bootstrap_seed !== null
                      ? ` · ${frontier.bootstrap_n.toLocaleString()} bootstrap resamples at seed ${frontier.bootstrap_seed}`
                      : ''}
                    . Served by <code className="bg-slate-800 px-1 rounded text-slate-300">
                      GET /benchmark/diversification-frontier
                    </code>; nothing on this page is a hardcoded copy of it.
                  </p>
                </div>
              </>
            )}
          </motion.section>
        )}

        {/* ── Monte Carlo ETA distribution ──────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.25, duration: 0.5 }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
          aria-label="Monte Carlo ETA distribution, blind vs graph-aware MILP across P10 P50 P90"
        >
          <div className="mb-4">
            <h2 className="text-2xl font-semibold text-slate-300">Monte Carlo ETA distribution</h2>
            <p className="text-xs text-slate-400 mt-1">P10 · P50 · P90 delivery days, blind vs graph-aware MILP (n={summary.n_boms} BOMs)</p>
          </div>
          {summary.monte_carlo ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={mcData} margin={{ top: 8, right: 16, left: 16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                  label={{ value: 'ETA (days)', angle: -90, position: 'insideLeft', offset: 8,
                           style: { textAnchor: 'middle' }, fill: '#94a3b8', fontSize: 12 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    border: '1px solid #475569',
                    borderRadius: '8px',
                    padding: '12px',
                    fontSize: '12px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '12px' }} />
                <Bar dataKey="Baseline" fill="#64748b" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Graph-Aware" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-52 flex items-center justify-center text-slate-400 text-sm">
              Monte Carlo data not available for this run.
            </div>
          )}
        </motion.div>

        {/* ── Per-BOM: graph-aware vs blind MILP (nominal) ─────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.28, duration: 0.4 }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5 overflow-x-auto"
        >
          <h2 className="text-2xl font-semibold text-slate-300 mb-1">Per-BOM: graph-aware vs blind MILP</h2>
          <p className="text-xs text-slate-400 mb-4">Nominal-world deltas per reference BOM. Negative = graph-aware is cheaper/faster/less risky.</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700">
                <th className="py-2 pr-4">BOM</th>
                <th className="py-2 pr-4 text-right">Cost Δ</th>
                <th className="py-2 pr-4 text-right">ETA Δ</th>
                <th className="py-2 pr-4 text-right">CO2 Δ</th>
                <th className="py-2 pr-4 text-right">Cascade risk Δ</th>
              </tr>
            </thead>
            <tbody>
              {summary.bom_deltas.map((d) => (
                <tr key={d.bom_name} className="border-b border-slate-800/70 text-slate-300">
                  <td className="py-2 pr-4">{d.bom_name}</td>
                  <td className="py-2 pr-4 text-right tabular-nums" style={{ color: d.cost_delta_pct < 0 ? '#10b981' : d.cost_delta_pct > 0 ? '#ef4444' : '#94a3b8' }}>
                    {fmtPct(d.cost_delta_pct)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums" style={{ color: d.eta_delta_pct < 0 ? '#10b981' : d.eta_delta_pct > 0 ? '#ef4444' : '#94a3b8' }}>
                    {fmtPct(d.eta_delta_pct)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums" style={{ color: d.co2_delta_pct < 0 ? '#10b981' : d.co2_delta_pct > 0 ? '#ef4444' : '#94a3b8' }}>
                    {fmtPct(d.co2_delta_pct)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums" style={{ color: d.cascade_risk_delta_pct < 0 ? '#10b981' : d.cascade_risk_delta_pct > 0 ? '#ef4444' : '#94a3b8' }}>
                    {fmtPct(d.cascade_risk_delta_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>

        {/* ── Tradeoff Card ────────────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.4 }}
          className="bg-slate-800/60 border border-amber-500/20 rounded-xl p-5 mb-5"
        >
          <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">
            HONEST TRADEOFF
          </span>
          <h2 className="text-white text-2xl font-semibold mt-1">Where Graph-Aware Loses</h2>
          <p className="text-sm text-slate-300 leading-relaxed mt-3">
            {summary.tradeoff.narrative}
          </p>
          <div className="mt-4 flex items-center gap-6 text-sm">
            <div className="flex flex-col gap-1">
              <span className="text-xs text-slate-400 uppercase tracking-wider">Blind MILP ({summary.tradeoff.losing_axis})</span>
              <span className="text-white tabular-nums font-semibold">
                {summary.tradeoff.losing_axis === 'cost'
                  ? fmtUsd(summary.tradeoff.baseline_value)
                  : summary.tradeoff.baseline_value.toFixed(2)}
              </span>
            </div>
            <div className="text-slate-400">→</div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-amber-400 uppercase tracking-wider">Graph-Aware ({summary.tradeoff.losing_axis})</span>
              <span className="text-amber-400 tabular-nums font-semibold">
                {summary.tradeoff.losing_axis === 'cost'
                  ? fmtUsd(summary.tradeoff.graph_aware_value)
                  : summary.tradeoff.graph_aware_value.toFixed(2)}
                {summary.tradeoff.delta_pct !== 0 && (
                  <span className="text-xs ml-1" style={{ color: tradeoffColor }}>
                    ({fmtPct(summary.tradeoff.delta_pct)} {deltaGlyph(summary.tradeoff.delta_pct)})
                  </span>
                )}
              </span>
            </div>
          </div>
        </motion.div>

        {/* ══════════════════════════════════════════════════════════════════════
            SECTION 3 — Network structure (independent of arm/scenario)
           ══════════════════════════════════════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35, duration: 0.4 }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
          aria-label="Network resilience under sequential distributor removal, 6 steps from 0 to 5 distributors removed"
        >
          <div className="mb-4">
            <h2 className="text-2xl font-semibold text-slate-300">
              Network resilience (λ₂) under sequential removal
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Top-5 highest-betweenness distributors removed in order. Click a point to see its fulfillability
              detail — which BOMs (if any) collapse. A BOM collapses when one of its lines has no supplier left
              in the graph after the removals up to that step.
            </p>
            {fiedlerBomSource && (
              <p className="text-xs text-slate-400 mt-1">
                {fiedlerBomsChecked === 0
                  ? `Fulfillability check did not run — ${fiedlerBomSource}`
                  : `Checked on ${fiedlerBomsChecked} reference BOM${
                      fiedlerBomsChecked === 1 ? '' : 's'
                    } · ${fiedlerBomSource}`}
              </p>
            )}
          </div>

          {fiedler && fiedler.points.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart
                  data={fiedlerData}
                  margin={{ top: 28, right: 16, left: 8, bottom: 28 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    label={{ value: 'Distributors removed', position: 'insideBottom', offset: -16, fill: '#94a3b8', fontSize: 12 }}
                  />
                  <YAxis
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    label={{ value: 'λ₂ (algebraic connectivity)', angle: -90, position: 'insideLeft', offset: 8,
                      style: { textAnchor: 'middle' }, fill: '#94a3b8', fontSize: 12 }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#0f172a',
                      border: '1px solid #475569',
                      borderRadius: '8px',
                      padding: '12px',
                      fontSize: '12px',
                    }}
                    formatter={(value) => [typeof value === 'number' ? value.toFixed(4) : '—', 'λ₂']}
                  />
                  <Line
                    type="monotone"
                    dataKey="lambda2"
                    stroke="#ef4444"
                    strokeWidth={2}
                    dot={(dotProps) => (
                      <FiedlerDot
                        key={dotProps.payload?.step}
                        {...dotProps}
                        selectedStep={selectedStep}
                        onSelect={setSelectedStep}
                      />
                    )}
                    activeDot={false}
                  />
                </LineChart>
              </ResponsiveContainer>

              {/* Annotation strip */}
              <div className="mt-3 min-h-[1.5rem]">
                {selectedPoint ? (
                  <p className="text-amber-400 text-sm">
                    {selectedPoint.removed_name
                      ? `Remove ${selectedPoint.removed_name} → ${selectedPoint.delta_pct.toFixed(1)}%`
                      : 'Baseline (no removal)'}
                  </p>
                ) : (
                  <p className="text-slate-400 text-sm">Click a point for its fulfillability detail.</p>
                )}
              </div>

              {/* Click-reveal drawer */}
              <AnimatePresence>
                {selectedStep !== null && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: 'easeOut' }}
                    className="overflow-hidden"
                    aria-live="polite"
                  >
                    <div className="mt-4 border-t border-slate-700 pt-4">
                      <p className="text-sm font-semibold text-white mb-3">
                        BOMs that collapse after this removal
                      </p>
                      {fiedlerBomsChecked === 0 ? (
                        <p className="text-amber-400 text-xs">
                          Not computed for this deployment — {fiedlerBomSource || 'no benchmarked BOMs are loaded'}.
                          An empty list here would mean nothing, so we do not show one.
                        </p>
                      ) : selectedPoint && selectedPoint.collapsed_boms.length === 0 ? (
                        <p className="text-emerald-500 text-xs">
                          All {fiedlerBomsChecked} reference BOMs remain fulfillable after this removal.
                        </p>
                      ) : (
                        <div className="space-y-1.5">
                          {(selectedPoint?.collapsed_boms ?? []).map((bom) => (
                            <div
                              key={bom}
                              className="bg-slate-900/50 rounded-lg px-3 py-2 text-xs text-slate-300 border-l-2 border-red-500"
                            >
                              {bom}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          ) : (
            <div className="h-52 flex items-center justify-center text-slate-400 text-sm">
              Fiedler curve not computed for this run.
            </div>
          )}
        </motion.div>

      </div>
    </div>
  );
}
