import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { AlertTriangle, CheckCircle2, Ban } from 'lucide-react';
import { benchmarkAPI } from '../services/api';
import { RISK_COLORS, riskLabel } from '../lib/risk';
import VolumeDecayCurve from '../components/VolumeDecayCurve';
import {
  VOLUME_SWEEP_FALLBACK,
  VOLUME_SWEEP_FALLBACK_SOURCE,
  normalizeVolumeCurve,
  productionVolumeRange,
  PRODUCTION_VOLUME_MIN_MULTIPLIER,
} from '../lib/volumeDecayCurveData';

// ── Types (mirrors backend/app/api/benchmark.py response_model) ──────────────
interface ResilienceSection {
  nominal_cost_premium_pct: number;
  stress_cascade_risk_reduction: number;
  stress_cvar95_reduction: number;
  targeted_cascade_risk_reduction: number;
  targeted_cvar95_reduction: number;
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
  noise_floor_pct: number;

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
}

// ── Formatting helpers ────────────────────────────────────────────────────────
// Resilience reductions arrive as raw fractions (e.g. plan_cascade_risk is a
// 0-1 probability, mc_cvar_95 is a ~1.0-2.0 cost multiplier). We display them
// as percentage points and treat anything under this magnitude as "no material
// difference" rather than rendering misleading precision on noise.
const RESILIENCE_MATERIALITY = 0.01; // 1 percentage point

function isMaterial(x: number | null | undefined): boolean {
  return typeof x === 'number' && Number.isFinite(x) && Math.abs(x) >= RESILIENCE_MATERIALITY;
}

/**
 * Percentage-POINT formatter. Only valid for quantities that are genuinely
 * probabilities / shares on a 0–1 scale (here: plan_cascade_risk). Pass the
 * signed CHANGE in the metric — negative means the metric went down.
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

function fmtPct(x: number | null | undefined, digits = 1): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return '—';
  return `${x > 0 ? '+' : ''}${x.toFixed(digits)}%`;
}

function fmtUsd(x: number | null | undefined): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return '—';
  return `$${Math.abs(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
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
      <span className="text-slate-500 text-xs">{sub}</span>
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

  // ── Loading state ────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center">
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
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center">
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
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center">
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
  const curveSource = curveIsFromApi
    ? `GET /benchmark/summary — volume sweep served live by the API (run ${summary.run_id})`
    : VOLUME_SWEEP_FALLBACK_SOURCE;

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

  // Is the nominal cost premium itself material? If it is, we must NOT also claim
  // cost was "held roughly flat" — that was the page contradicting itself.
  const nominalPremiumPct = summary.resilience.nominal_cost_premium_pct;
  const nominalPremiumIsMaterial =
    Number.isFinite(nominalPremiumPct) && Math.abs(nominalPremiumPct) > (summary.noise_floor_pct ?? 2);

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full">
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
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Withdrawn figure (tiny-order regime)
              </span>
              <div
                className="text-2xl font-semibold leading-tight tabular-nums mt-1 text-slate-500 line-through decoration-amber-500/70 decoration-2"
                aria-live="polite"
              >
                {fmtPct(summary.savings_pct)}
              </div>
              <span className="text-[11px] text-slate-600">
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
                Pooled MILP-vs-greedy landed-cost advantage once orders are re-run at{' '}
                {PRODUCTION_VOLUME_MIN_MULTIPLIER.toLocaleString()}× the benchmark's quantities and above. Same
                solver, same offer pool, same objective — only the order size changes. This is the number to quote.
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
          <p className="text-xs text-slate-500 mt-1 mb-4">
            The optimizer's cost advantage is a function of how small the order is. Re-solve the same BOMs at
            larger quantities and it decays monotonically until the fixed fee stops mattering.
          </p>
          <VolumeDecayCurve
            points={volumeCurve}
            headlineValue={summary.savings_pct}
            headlineLabel="Withdrawn headline"
            source={curveSource}
          />
        </motion.div>

        {/* ── Decomposition: where the saving actually came from ───────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.09, duration: 0.4, ease: 'easeOut' }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
        >
          <h2 className="text-2xl font-semibold text-slate-300">Decomposition of the withdrawn saving</h2>
          <p className="text-xs text-slate-500 mt-1 mb-4">
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
              <span className="text-xs text-slate-500">
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
              <span className="text-xs text-slate-500">
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
              <span className="text-xs text-slate-500">
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
        <p className="text-xs text-slate-500 mb-5 px-1">
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
              style={{ color: isMaterial(summary.resilience.nominal_cost_premium_pct / 100) ? '#f59e0b' : '#94a3b8' }}
            >
              {fmtPct(summary.resilience.nominal_cost_premium_pct, 2)}
            </div>
            <span className="text-slate-500 text-xs">
              graph-aware vs blind MILP, no disruption ·{' '}
              <span className="text-amber-400/90">
                {fmtUsd(summary.cost_delta_usd)} {summary.cost_delta_usd <= 0 ? 'cheaper' : 'more expensive'} / BOM run
              </span>
            </span>
            <p className="text-[11px] text-slate-500 mt-2 leading-relaxed border-t border-slate-700/60 pt-2">
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
            <span className="text-slate-500 text-xs">
              extra spend exposed in worst-5% scenarios · mean per blind-MILP BOM
            </span>
          </div>
        </div>

        {/* ── Stress / Targeted scenario reductions ────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Stress scenario</span>
            <p className="text-xs text-slate-500 mt-1 mb-3">Broad disruption (stress_factor=3) applied to every distributor</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-xs text-slate-500 uppercase tracking-wider">
                  Cascade risk {deltaGlyph(stressCascadeChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{ color: improvementColor(stressCascadeChange, isMaterial(stressCascadeChange)) }}
                >
                  {fmtPP(stressCascadeChange)}
                </div>
                <span className="text-[11px] text-slate-600">change in collapse probability (0–1 scale)</span>
              </div>
              <div>
                <span className="text-xs text-slate-500 uppercase tracking-wider">
                  CVaR-95 {deltaGlyph(stressCvarChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{ color: improvementColor(stressCvarChange, isMaterial(stressCvarChange)) }}
                >
                  {fmtMultiplierDelta(stressCvarChange)}
                </div>
                <span className="text-[11px] text-slate-600">
                  change in cost multiplier
                  {fmtRelativeToBaseline(stressCvarChange, summary.monte_carlo?.baseline_cvar_95)
                    ? ` · ${fmtRelativeToBaseline(stressCvarChange, summary.monte_carlo?.baseline_cvar_95)}`
                    : ''}
                </span>
              </div>
            </div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Targeted scenario</span>
            <p className="text-xs text-slate-500 mt-1 mb-3">Single highest-betweenness distributor in the BOM's pool goes fully offline</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-xs text-slate-500 uppercase tracking-wider">
                  Cascade risk {deltaGlyph(targetedCascadeChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{ color: improvementColor(targetedCascadeChange, isMaterial(targetedCascadeChange)) }}
                >
                  {fmtPP(targetedCascadeChange)}
                </div>
                <span className="text-[11px] text-slate-600">change in collapse probability (0–1 scale)</span>
              </div>
              <div>
                <span className="text-xs text-slate-500 uppercase tracking-wider">
                  CVaR-95 {deltaGlyph(targetedCvarChange)}
                </span>
                <div
                  className="text-2xl font-semibold tabular-nums mt-1"
                  style={{ color: improvementColor(targetedCvarChange, isMaterial(targetedCvarChange)) }}
                >
                  {fmtMultiplierDelta(targetedCvarChange)}
                </div>
                <span className="text-[11px] text-slate-600">
                  change in cost multiplier
                  {fmtRelativeToBaseline(targetedCvarChange, summary.monte_carlo?.baseline_cvar_95)
                    ? ` · ${fmtRelativeToBaseline(targetedCvarChange, summary.monte_carlo?.baseline_cvar_95)}`
                    : ''}
                </span>
              </div>
            </div>
          </div>
        </div>

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
            {resilienceHasMaterialEffect ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
            )}
            <div>
              <span className={`text-xs font-semibold uppercase tracking-wider ${resilienceHasMaterialEffect ? 'text-emerald-400' : 'text-amber-400'}`}>
                Honest finding
              </span>
              {resilienceHasMaterialEffect ? (
                <p className="text-sm text-slate-300 leading-relaxed mt-2">
                  Graph-aware sourcing measurably lowers cascade risk and/or CVaR-95 under disruption — the numbers
                  above are the real, disclosed deltas from run {summary.run_id}.{' '}
                  {nominalPremiumIsMaterial ? (
                    <>
                      It is <span className="text-amber-400 font-semibold">not free</span>: it costs a{' '}
                      {fmtPct(nominalPremiumPct, 2)} nominal premium ({fmtUsd(summary.cost_delta_usd)} per BOM run),
                      which is well above this run's {summary.noise_floor_pct.toFixed(1)}% noise floor. That is a
                      real trade — buying tail-risk reduction with nominal cost — and we state it as one rather
                      than claiming cost was held flat.
                    </>
                  ) : (
                    <>
                      The nominal premium ({fmtPct(nominalPremiumPct, 2)}) sits inside this run's{' '}
                      {summary.noise_floor_pct.toFixed(1)}% noise floor, so nominal cost really is roughly flat here.
                    </>
                  )}
                </p>
              ) : (
                <p className="text-sm text-slate-300 leading-relaxed mt-2">
                  On this catalog, the reductions above are within noise (&lt; {(RESILIENCE_MATERIALITY * 100).toFixed(0)} pp) —
                  cost-optimal consolidation dominates the graph surcharge, so graph-aware selects essentially the
                  same plan as blind MILP. The consolidated single-hub plan that wins on cost is itself the
                  concentration risk the targeted scenario exposes. We report this as a real ~0 finding rather than
                  manufacturing a resilience win: on the current supplier catalog, cost and graph-aware routing do
                  not diverge enough to trade one for the other. This still quantifies the cost-vs-resilience
                  trade-off honestly — it just shows the trade-off is currently slack in one direction.
                </p>
              )}
            </div>
          </div>
        </motion.div>

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
            <p className="text-xs text-slate-500 mt-1">P10 · P50 · P90 delivery days, blind vs graph-aware MILP (n={summary.n_boms} BOMs)</p>
          </div>
          {summary.monte_carlo ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={mcData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                  label={{ value: 'ETA (days)', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 12 }}
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
            <div className="h-52 flex items-center justify-center text-slate-500 text-sm">
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
          <p className="text-xs text-slate-500 mb-4">Nominal-world deltas per reference BOM. Negative = graph-aware is cheaper/faster/less risky.</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-700">
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
              <span className="text-xs text-slate-500 uppercase tracking-wider">Blind MILP ({summary.tradeoff.losing_axis})</span>
              <span className="text-white tabular-nums font-semibold">
                {summary.tradeoff.baseline_value.toFixed(2)}
              </span>
            </div>
            <div className="text-slate-600">→</div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-amber-400 uppercase tracking-wider">Graph-Aware ({summary.tradeoff.losing_axis})</span>
              <span className="text-amber-400 tabular-nums font-semibold">
                {summary.tradeoff.graph_aware_value.toFixed(2)}
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
            <p className="text-xs text-slate-500 mt-1">
              Top-5 highest-betweenness distributors removed in order. Click a point to see which BOMs collapse.
            </p>
          </div>

          {fiedler && fiedler.points.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart
                  data={fiedlerData}
                  margin={{ top: 8, right: 16, left: 0, bottom: 24 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    label={{ value: 'Distributors removed', position: 'insideBottom', offset: -16, fill: '#94a3b8', fontSize: 12 }}
                  />
                  <YAxis
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    label={{ value: 'λ₂ (algebraic connectivity)', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 12 }}
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
                  <p className="text-slate-500 text-sm">Click a point to explore collapse impact.</p>
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
                      {selectedPoint && selectedPoint.collapsed_boms.length === 0 ? (
                        <p className="text-emerald-500 text-xs">
                          All {summary.n_boms} reference BOMs remain fulfillable after this removal.
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
            <div className="h-52 flex items-center justify-center text-slate-500 text-sm">
              Fiedler curve not computed for this run.
            </div>
          )}
        </motion.div>

      </div>
    </div>
  );
}
