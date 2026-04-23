import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { AlertTriangle } from 'lucide-react';
import { benchmarkAPI } from '../services/api';
import { RISK_COLORS, riskLabel } from '../lib/risk';

// ── Types ─────────────────────────────────────────────────────────────────────
interface MonteCarloSummary {
  baseline_p10: number;
  baseline_p50: number;
  baseline_p90: number;
  graph_aware_p10: number;
  graph_aware_p50: number;
  graph_aware_p90: number;
  baseline_evar_95: number | null;
  graph_aware_evar_95: number | null;
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
  cost_delta_pct: number;
  eta_delta_pct: number;
  co2_delta_pct: number;
  cascade_risk_delta_pct: number;
  monte_carlo: MonteCarloSummary;
  tradeoff: TradeoffEntry;
  bom_deltas: BomDelta[];
  feeds_fallback: boolean;
  noise_floor_pct: number;
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
  const isLowConfidence =
    Math.abs(summary.cost_delta_pct) < summary.noise_floor_pct &&
    Math.abs(summary.cascade_risk_delta_pct) < summary.noise_floor_pct;

  const formattedTimestamp = summary.timestamp
    ? new Date(summary.timestamp).toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '—';

  // Monte Carlo chart data
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
  // Normalize tradeoff delta_pct to [0,1] range for RISK_COLORS classification
  const tradeoffRiskScore = Math.min(1.0, Math.abs(summary.tradeoff.delta_pct) / 20.0);
  const tradeoffRiskLevel = riskLabel(tradeoffRiskScore);
  const tradeoffColor = RISK_COLORS[tradeoffRiskLevel];

  // KPI accent logic
  const costAccent = summary.cost_delta_pct < 0
    ? 'border-emerald-500/30'
    : summary.cost_delta_pct > 2
      ? 'border-amber-500/30'
      : 'border-slate-700';
  const riskAccent = summary.cascade_risk_delta_pct < 0
    ? 'border-emerald-500/30'
    : summary.cascade_risk_delta_pct > 2
      ? 'border-amber-500/30'
      : 'border-slate-700';
  const etaAccent = summary.eta_delta_pct < 0
    ? 'border-emerald-500/30'
    : summary.eta_delta_pct > 2
      ? 'border-amber-500/30'
      : 'border-slate-700';

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
            <h1 className="text-3xl font-semibold text-white">Benchmark: Graph-Aware vs Baseline</h1>
            <p className="text-sm text-slate-400 mt-1">
              10 reference BOMs · holdout set · seed=42 · run {summary.run_id} — {formattedTimestamp}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-xs px-3 py-1.5 rounded-full font-semibold uppercase tracking-wider">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              Holdout · Seed 42
            </span>
            {summary.feeds_fallback && (
              <span className="inline-flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs px-3 py-1.5 rounded-full font-semibold uppercase tracking-wider">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                Static Feeds
              </span>
            )}
            {isLowConfidence && (
              <span className="inline-flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs px-3 py-1.5 rounded-full font-semibold uppercase tracking-wider">
                Low confidence
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

        {/* ── Hero Headline ────────────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0, duration: 0.4, ease: 'easeOut' }}
          className="bg-slate-800/70 border border-slate-700 rounded-xl p-8 mb-5"
        >
          {isLowConfidence ? (
            <>
              <div
                className="text-amber-400 text-3xl font-semibold leading-tight tabular-nums flex items-center gap-3"
                aria-live="polite"
                role="status"
              >
                <AlertTriangle className="w-7 h-7 flex-shrink-0" />
                Deltas within noise floor (±{summary.noise_floor_pct}%)
              </div>
              <p className="text-sm text-slate-400 mt-2">
                graph-aware and baseline are statistically indistinguishable on this run — see tradeoff card below
              </p>
            </>
          ) : (
            <>
              <div
                className="text-5xl font-semibold leading-tight tabular-nums"
                aria-live="polite"
              >
                <span style={{ color: summary.cost_delta_pct < 0 ? '#10b981' : summary.cost_delta_pct > 0 ? '#ef4444' : '#94a3b8' }}>
                  {summary.cost_delta_pct > 0 ? '+' : ''}{summary.cost_delta_pct.toFixed(1)}% cost
                </span>
                <span className="text-slate-400 mx-3">·</span>
                <span style={{ color: summary.cascade_risk_delta_pct < 0 ? '#10b981' : summary.cascade_risk_delta_pct > 0 ? '#ef4444' : '#94a3b8' }}>
                  {summary.cascade_risk_delta_pct <= 0 ? '+' : ''}{(-summary.cascade_risk_delta_pct).toFixed(1)}% resilience
                </span>
              </div>
              <p className="text-sm text-slate-400 mt-2">
                at equal ETA across {summary.n_boms} reference BOMs
              </p>
            </>
          )}
        </motion.div>

        {/* ── KPI Row ──────────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-4 mb-5">
          <KpiCard
            title="COST Δ"
            value={`${summary.cost_delta_pct > 0 ? '+' : ''}${summary.cost_delta_pct.toFixed(1)}%`}
            sub="baseline → graph-aware comparison"
            accent={costAccent}
            delay={0.05}
          />
          <KpiCard
            title="RISK Δ"
            value={`${summary.cascade_risk_delta_pct > 0 ? '+' : ''}${summary.cascade_risk_delta_pct.toFixed(1)}%`}
            sub="cascade risk P95 reduced"
            accent={riskAccent}
            delay={0.1}
          />
          <KpiCard
            title="ETA Δ"
            value={`${summary.eta_delta_pct > 0 ? '+' : ''}${summary.eta_delta_pct.toFixed(1)}d`}
            sub="P50 delivery time, 10 BOMs"
            accent={etaAccent}
            delay={0.15}
          />
        </div>

        {/* ── Monte Carlo Grouped Bar Chart ────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2, duration: 0.5 }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
          aria-label="Monte Carlo cost inflation, baseline vs graph-aware across P10 P50 P90"
        >
          <div className="mb-4">
            <h2 className="text-3xl font-semibold text-slate-300">Monte Carlo cost inflation distribution</h2>
            <p className="text-xs text-slate-500 mt-1">P10 · P50 · P90 across 1,000 scenarios, paired per BOM (n=10)</p>
          </div>
          {summary.monte_carlo ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={mcData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                <YAxis
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                  label={{ value: 'Cost inflation (%)', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 12 }}
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

        {/* ── Tradeoff Card ────────────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25, duration: 0.4 }}
          className="bg-slate-800/60 border border-amber-500/20 rounded-xl p-5 mb-5"
        >
          <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">
            HONEST TRADEOFF
          </span>
          <h2 className="text-white text-3xl font-semibold mt-1">Where Graph-Aware Loses</h2>
          <p className="text-sm text-slate-300 leading-relaxed mt-3">
            {summary.tradeoff.narrative}
          </p>
          <div className="mt-4 flex items-center gap-6 text-sm">
            <div className="flex flex-col gap-1">
              <span className="text-xs text-slate-500 uppercase tracking-wider">Baseline ({summary.tradeoff.losing_axis})</span>
              <span className="text-white tabular-nums font-semibold">
                {summary.tradeoff.baseline_value.toFixed(2)}
              </span>
            </div>
            <div className="text-slate-600">→</div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-amber-400 uppercase tracking-wider">Graph-Aware ({summary.tradeoff.losing_axis})</span>
              <span className="text-amber-400 tabular-nums font-semibold">
                {summary.tradeoff.graph_aware_value.toFixed(2)}
                {summary.tradeoff.delta_pct > 0 && (
                  <span className="text-xs ml-1" style={{ color: tradeoffColor }}>
                    (+{summary.tradeoff.delta_pct.toFixed(1)}%)
                  </span>
                )}
              </span>
            </div>
          </div>
        </motion.div>

        {/* ── Fiedler Degradation Card ─────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.4 }}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5"
          aria-label="Network resilience under sequential distributor removal, 6 steps from 0 to 5 distributors removed"
        >
          <div className="mb-4">
            <h2 className="text-3xl font-semibold text-slate-300">
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
                          All 10 reference BOMs remain fulfillable after this removal.
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

