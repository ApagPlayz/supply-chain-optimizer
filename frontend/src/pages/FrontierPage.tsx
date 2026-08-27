/**
 * The Price of Resilience — cost vs CVaR-95 efficient frontier.
 * =============================================================
 *
 * The first frontend surface for `POST /stochastic/frontier`. Until this page
 * existed the two-stage stochastic program — the strongest operations-research
 * work in the repository — had zero frontend callers and was invisible to
 * anyone who did not read the source.
 *
 * WHAT IT RENDERS
 * ---------------
 * The λ-sweep of `min (1−λ)·E[cost] + λ·CVaR₉₅[cost]`, plotted as the (expected
 * cost, tail risk) curve it traces out, with the knee highlighted and the
 * tradeoff stated in the only sentence that actually matters: how many dollars
 * of tail exposure one extra dollar of expected spend buys.
 *
 * NUMBERS POLICY
 * --------------
 * Every figure with a `$` on it is read out of the live API response. The only
 * hard-coded numbers on this page are the *offline study* figures quoted in the
 * explainer (387 λ-solves, 330 converged, 57 excluded, VSS $676), which come
 * from docs/CVAR_EFFICIENT_FRONTIER.md and are labelled as the offline study
 * rather than presented as something this request measured. Where that document
 * excludes non-converged solves, so does the text here.
 *
 * TIMEOUT
 * -------
 * This page does NOT use `services/api.ts`. That instance has a global 30s
 * timeout and the server's own sweep budget is 45s, so a cold solve aborts
 * client-side with ECONNABORTED while the server happily finishes and caches
 * the answer. `services/stochastic.ts` exists purely to give this one call a
 * 90s budget. See the header comment there.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot, ReferenceLine, Cell,
} from 'recharts';
import {
  AlertTriangle, CheckCircle2, ChevronRight, Database, Loader2, RefreshCw,
  ShieldCheck, TrendingDown,
} from 'lucide-react';
import {
  isTimeoutError,
  stochasticAPI,
  type CalibrationResponse,
  type FrontierPoint,
  type FrontierRequest,
  type FrontierResponse,
} from '../services/stochastic';

// ── The published instance ───────────────────────────────────────────────────
//
// `pcb_power_supply` at 10,000× volume — 60,000 units — against the SAN
// FRANCISCO depot. The depot is load-bearing, not scenery: it sets every
// distributor's freight distance, which drives the freight model, which changes
// the optimum. docs/cvar_frontier.json was generated at San Francisco; the
// endpoint DEFAULTS to the Memphis reference hub and would answer a different
// question (E = $147,272, four suppliers at λ = 0). So the depot is passed
// explicitly and this page reproduces the published frontier exactly.
//
// Component ids resolved by MPN against the live catalogue 2026-08-24:
//   429 LM317DCY · 431 TPS767D325PWP · 457 UA78M33CDCY · 442 OPA861ID
const PUBLISHED_ITEMS = [
  { component_id: 429, quantity: 20000, mpn: 'LM317DCY' },
  { component_id: 431, quantity: 10000, mpn: 'TPS767D325PWP' },
  { component_id: 457, quantity: 20000, mpn: 'UA78M33CDCY' },
  { component_id: 442, quantity: 10000, mpn: 'OPA861ID' },
];
const SF_DEPOT = { lat: 37.7749, lng: -122.4194 };

/** Server defaults, restated so "reset to published" is a real action. */
const PUBLISHED_ASSUMPTIONS = {
  base_annual_prob: 0.236827,
  horizon_days: 60,
  centrality_spread: 3.0,
};

const BASE_RATE_OPTIONS = [
  { value: 0.05, label: '5%' },
  { value: 0.10, label: '10%' },
  { value: 0.236827, label: '23.68% (cited)' },
  { value: 0.40, label: '40%' },
];
const SPREAD_OPTIONS = [
  { value: 1.0, label: '1.0 — centrality ignored' },
  { value: 3.0, label: '3.0 (published)' },
  { value: 6.0, label: '6.0 — centrality amplified' },
];
const HORIZON_OPTIONS = [
  { value: 30, label: '30 days' },
  { value: 60, label: '60 days (published)' },
  { value: 120, label: '120 days' },
];

// ── Formatters ───────────────────────────────────────────────────────────────
// Local by convention (BenchmarkPage/ResiliencePage/ModelCardPage each define
// their own). Every one falls back to an em dash rather than rendering a fake 0.

const fmtUsd = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v)
    ? '—'
    : `$${v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

const fmtPct = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(digits)}%`;

const fmtNum = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v)
    ? '—'
    : v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });

const fmtRatio = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? '—' : `$${v.toFixed(2)}`;

/**
 * Money axis ticks whose precision follows the DOMAIN SPAN, not the magnitude.
 *
 * The old formatter was a flat `$${(v/1000).toFixed(0)}k`. That reads fine on a
 * wide frontier ($147k → $183k) but collapses the moment the frontier is tight:
 * at a 5% base annual probability the whole CVaR axis lives inside ~$800, and
 * five ticks all rounded to the same thousand — a y-axis of five identical
 * "$188k" labels, and an x-axis reading "$182k, $182k, $183k, $183k, $183k".
 * A tick label that cannot distinguish its neighbours is not an axis.
 *
 * So: pick the unit and the decimals from how far apart the ticks actually are.
 * Recharts draws ~5 ticks, so the spacing is roughly span/5; below ~$2k of total
 * spread even a decimal on the "k" scale is noise, and whole dollars are both
 * shorter and exact.
 */
function makeMoneyTickFormatter(domain: [number, number]) {
  const span = Math.abs(domain[1] - domain[0]);

  if (!Number.isFinite(span) || span <= 0) return fmtUsd;

  // Tight domain: thousands can't resolve it. Show the real dollars.
  if (span < 2000) {
    return (v: number) => fmtUsd(v);
  }

  // Otherwise stay on the compact "k" scale, with just enough decimals that
  // adjacent ticks differ. ~5 ticks ⇒ a step of span/5 dollars.
  const stepInK = span / 1000 / 5;
  const decimals = stepInK >= 1 ? 0 : stepInK >= 0.1 ? 1 : 2;
  return (v: number) =>
    `$${(v / 1000).toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}k`;
}

// ── Small building blocks ────────────────────────────────────────────────────

function KpiCard({
  title, value, sub, accent, delay = 0,
}: {
  title: string; value: string; sub: string; accent: string; delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: 'easeOut' }}
      className={`bg-slate-800/70 border rounded-xl p-4 flex flex-col gap-1 backdrop-blur-sm ${accent}`}
    >
      {/* `uppercase` would render a lambda in the title as Λ — a different symbol. */}
      <span
        className={`text-slate-400 text-xs font-semibold tracking-wider ${
          /λ/.test(String(title)) ? 'normal-case' : 'uppercase'
        }`}
      >
        {title}
      </span>
      <span className="text-3xl font-semibold text-white tabular-nums">{value}</span>
      <span className="text-slate-400 text-xs leading-relaxed">{sub}</span>
    </motion.div>
  );
}

function SectionCard({
  eyebrow, title, subtitle, children, className = '',
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5 ${className}`}>
      {eyebrow && (
        <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">{eyebrow}</span>
      )}
      <h2 className="text-white text-xl font-semibold mt-1">{title}</h2>
      {subtitle && <p className="text-xs text-slate-400 mt-1 mb-4 leading-relaxed">{subtitle}</p>}
      {!subtitle && <div className="mb-4" />}
      {children}
    </div>
  );
}

// ── Chart tooltips ───────────────────────────────────────────────────────────

interface ChartPoint extends FrontierPoint {
  isKnee: boolean;
}

/**
 * Recharts types a custom tooltip's `payload` very loosely. Everything these
 * two tooltips touch is the datum, so narrow to exactly that rather than
 * reaching for `any`.
 */
interface TooltipProps {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}

function FrontierTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-slate-900 border border-slate-600 rounded-lg p-3 text-xs shadow-xl max-w-[260px]">
      <p className="text-white font-semibold mb-1.5">
        λ = {d.lambda}
        {d.isKnee && <span className="ml-2 text-amber-400 font-bold uppercase tracking-wider text-[11px]">knee</span>}
        {d.dominated && <span className="ml-2 text-red-400 font-bold uppercase tracking-wider text-[11px]">dominated</span>}
      </p>
      <p className="text-slate-400">Expected cost: <span className="text-slate-100 tabular-nums">{fmtUsd(d.expected_cost_usd)}</span></p>
      <p className="text-slate-400">CVaR-95: <span className="text-amber-300 tabular-nums">{fmtUsd(d.cvar_95_usd)}</span></p>
      <p className="text-slate-400">VaR-95: <span className="text-slate-300 tabular-nums">{fmtUsd(d.var_95_usd)}</span></p>
      <p className="text-slate-400">Tail premium: <span className="text-slate-300 tabular-nums">{fmtUsd(d.tail_premium_usd)}</span></p>
      <p className="text-slate-400 mt-1">Suppliers: <span className="text-blue-400">{d.n_suppliers}</span> <span className="text-slate-400">[{d.supplier_ids.join(', ')}]</span></p>
      <p className="text-slate-400 mt-1 text-xs">
        {d.solver_status} · gap {fmtPct(d.mip_gap_pct, 3)} · {d.solve_seconds.toFixed(2)}s · {d.n_atoms_in_tail} atoms in tail
      </p>
    </div>
  );
}

function TailTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-slate-900 border border-slate-600 rounded-lg p-3 text-xs shadow-xl">
      <p className="text-white font-semibold mb-1">λ = {d.lambda}</p>
      <p className="text-slate-400">Tail premium (CVaR-95 − E): <span className="text-amber-300 tabular-nums">{fmtUsd(d.tail_premium_usd)}</span></p>
      <p className="text-slate-400">Suppliers used: <span className="text-blue-400">{d.n_suppliers}</span></p>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

type Assumptions = typeof PUBLISHED_ASSUMPTIONS;

export default function FrontierPage() {
  const [data, setData] = useState<FrontierResponse | null>(null);
  const [calibration, setCalibration] = useState<CalibrationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [form, setForm] = useState<Assumptions>(PUBLISHED_ASSUMPTIONS);
  /** The assumptions the currently-displayed result was solved with. */
  const [solvedWith, setSolvedWith] = useState<Assumptions>(PUBLISHED_ASSUMPTIONS);

  const timerRef = useRef<number | null>(null);

  const solve = useCallback(async (assumptions: Assumptions) => {
    setLoading(true);
    setError(null);
    setElapsed(0);
    const startedAt = Date.now();
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = window.setInterval(
      () => setElapsed(Math.round((Date.now() - startedAt) / 1000)),
      1000,
    );

    const body: FrontierRequest = {
      items: PUBLISHED_ITEMS.map(({ component_id, quantity }) => ({ component_id, quantity })),
      depot_lat: SF_DEPOT.lat,
      depot_lng: SF_DEPOT.lng,
      ...assumptions,
    };

    try {
      const res = await stochasticAPI.frontier(body);
      setData(res.data);
      setSolvedWith(assumptions);
    } catch (err: unknown) {
      const axiosErr = err as {
        response?: { status: number; data?: { detail?: string | { message?: string } } };
      };
      // Distinguish the three failures that actually happen here, because the
      // advice differs for each. A generic "something went wrong" would be
      // worse than useless on an endpoint whose first call can take two
      // minutes on a cold container.
      if (isTimeoutError(err)) {
        setError(
          `The request timed out after 90 seconds without a reply. Two things cause this: the ` +
          `demo backend was asleep (Render spins it down when idle and the container takes about ` +
          `two minutes to wake), or the solve ran long. Either way the server often finishes and ` +
          `caches the result anyway — press Retry and it usually comes back instantly.`,
        );
      } else if (axiosErr.response) {
        const detail = axiosErr.response.data?.detail;
        const asText =
          typeof detail === 'string'
            ? detail
            : detail?.message ?? JSON.stringify(detail ?? axiosErr.response.data ?? {});
        setError(`The API returned HTTP ${axiosErr.response.status}. ${asText}`);
      } else {
        setError(
          `Could not reach the optimization API — no response at all. The demo backend sleeps ` +
          `when idle and takes about two minutes to wake; press Retry once it is up.`,
        );
      }
    } finally {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setLoading(false);
    }
  }, []);

  // Auto-solve the published instance on mount, so the page never lands empty.
  // The server caches for ~1h, so in practice this is an instant cache hit and
  // the loading state below is what a *changed assumption* looks like.
  useEffect(() => {
    void solve(PUBLISHED_ASSUMPTIONS);
    stochasticAPI
      .calibration()
      .then((r) => setCalibration(r.data))
      .catch(() => setCalibration(null)); // secondary panel; never blocks the page
    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
    };
  }, [solve]);

  const isPublished =
    solvedWith.base_annual_prob === PUBLISHED_ASSUMPTIONS.base_annual_prob &&
    solvedWith.horizon_days === PUBLISHED_ASSUMPTIONS.horizon_days &&
    solvedWith.centrality_spread === PUBLISHED_ASSUMPTIONS.centrality_spread;

  const dirty =
    form.base_annual_prob !== solvedWith.base_annual_prob ||
    form.horizon_days !== solvedWith.horizon_days ||
    form.centrality_spread !== solvedWith.centrality_spread;

  // ── Derived chart data ─────────────────────────────────────────────────────
  const rec = data?.recommendation;
  const kneeLambda = rec?.available ? rec.knee_lambda : null;

  const chartPoints: ChartPoint[] = (data?.frontier ?? [])
    .map((p) => ({ ...p, isKnee: kneeLambda != null && p.lambda === kneeLambda }))
    .sort((a, b) => a.expected_cost_usd - b.expected_cost_usd);

  const kneePoint = chartPoints.find((p) => p.isKnee) ?? null;
  const dominatedPoints = chartPoints.filter((p) => p.dominated);
  const riskNeutral = data?.frontier.find((p) => p.lambda === 0) ?? null;

  // Axis domains. The server 503s rather than returning an empty frontier, but
  // Math.min(...[]) is Infinity and would paint a NaN chart, so the fallbacks are
  // real rather than decorative.
  const costs = chartPoints.map((p) => p.expected_cost_usd);
  const cvars = chartPoints.map((p) => p.cvar_95_usd);
  const padX = costs.length ? (Math.max(...costs) - Math.min(...costs)) * 0.12 || 500 : 0;
  const padY = cvars.length ? (Math.max(...cvars) - Math.min(...cvars)) * 0.15 || 500 : 0;
  const xDomain: [number, number] = costs.length
    ? [Math.min(...costs) - padX, Math.max(...costs) + padX]
    : [0, 1];
  const yDomain: [number, number] = cvars.length
    ? [Math.min(...cvars) - padY, Math.max(...cvars) + padY]
    : [0, 1];

  // One formatter per axis, each told the span it has to resolve (see
  // makeMoneyTickFormatter — a narrow frontier used to render identical ticks).
  const xTickFormatter = makeMoneyTickFormatter(xDomain);
  const yTickFormatter = makeMoneyTickFormatter(yDomain);

  // λ-ordered copy for the tail-premium bar chart.
  const tailBars: ChartPoint[] = (data?.frontier ?? [])
    .map((p) => ({ ...p, isKnee: kneeLambda != null && p.lambda === kneeLambda }))
    .sort((a, b) => a.lambda - b.lambda);

  // A bar chart is anchored at zero, so [0, max] is the span the ticks must
  // resolve — tail premiums are often only a few hundred dollars, which the old
  // "k" formatter flattened to "$0k, $0k, $1k, $1k".
  const tailMax = tailBars.length ? Math.max(...tailBars.map((p) => p.tail_premium_usd)) : 0;
  const tailTickFormatter = makeMoneyTickFormatter([0, tailMax]);

  const poolCalibrated = calibration && data
    ? calibration.distributors.filter((d) =>
        data.frontier.some((p) => p.supplier_ids.includes(d.distributor_id)))
    : [];

  return (
    <div className="min-h-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full">
      <div className="max-w-7xl mx-auto px-6 py-8">

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex items-start justify-between gap-4 mb-6"
        >
          <div>
            <h1 className="text-3xl font-semibold text-white">The Price of Resilience</h1>
            <p className="text-sm text-slate-400 mt-1">
              Cost vs CVaR₉₅ efficient frontier · two-stage stochastic program with recourse ·
              OR-Tools CP-SAT
            </p>
          </div>
          {data && (
            <div className="flex flex-col items-end gap-1.5 shrink-0">
              <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-xs px-3 py-1.5 rounded-full font-semibold uppercase tracking-wider">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                {data.solver.points_solved}/{data.solver.points_requested}{' '}
                <span className="normal-case">λ</span> solved
              </span>
              <span className="text-[11px] text-slate-400 tabular-nums">
                {data.cached
                  ? 'served from the 1h result cache'
                  : `solved live in ${data.solver.sweep_wall_seconds.toFixed(1)}s`}
              </span>
            </div>
          )}
        </motion.div>

        {/* ── What am I looking at ───────────────────────────────────────── */}
        <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-2">
            <ShieldCheck className="w-4 h-4 text-sky-400" /> What am I looking at?
          </h2>
          <div className="text-sm text-slate-300 leading-relaxed space-y-2 max-w-4xl">
            <p>
              Sourcing a bill of materials is usually solved for one number: cheapest expected
              cost. That silently picks a risk appetite of zero. This page solves it for the whole
              curve instead — every point below is a <em>different sourcing plan</em>, produced by
              minimising{' '}
              <code className="bg-slate-800 px-1 rounded text-slate-300">(1−λ)·E[cost] + λ·CVaR₉₅[cost]</code>{' '}
              at a different risk weight λ.
            </p>
            <p>
              <span className="text-slate-100 font-medium">CVaR₉₅</span> is the mean cost of the
              worst 5% of disruption scenarios. Unlike variance it only penalises the downside, it
              is a <em>coherent</em> risk measure (Artzner et al. 1999), and it stays linear — so
              CP-SAT solves it exactly rather than approximately. The model is genuinely two-stage:
              suppliers are chosen before anyone knows who fails, and then the model{' '}
              <em>re-optimises</em> — emergency re-procurement, air freight, or writing units off at
              a stockout penalty — once the failures are observed. That recourse decision is what
              the flat 15% risk surcharge this replaced never had.
            </p>
            <p className="text-slate-400">
              Read the chart left-to-right as buying insurance: moving right costs more in
              expectation, moving down removes tail risk. The <span className="text-amber-400 font-medium">amber knee</span>{' '}
              is where the exchange rate between the two collapses, and it is the recommendation.
            </p>
          </div>
        </div>

        {/* ── Assumptions + solve control ────────────────────────────────── */}
        <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap mb-3">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                The assumption, as a dial
              </span>
              <h2 className="text-white text-xl font-semibold mt-1">Disruption probabilities</h2>
              <p className="text-xs text-slate-400 mt-1 max-w-3xl leading-relaxed">
                These are an <span className="text-slate-300">assumption, not a measurement</span> —
                the weakest input in the whole subsystem, so it is exposed rather than buried. The
                base rate is a <em>firm-level</em> disruption frequency used here per supplier,
                which likely overstates individual supplier risk. Change any of these and re-solve;
                if the recommendation moves a lot between spread 1.0 and 3.0, it is being driven by
                the graph assumption rather than by the cost data.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Annual base rate
              </span>
              <select
                value={form.base_annual_prob}
                disabled={loading}
                onChange={(e) => setForm({ ...form, base_annual_prob: Number(e.target.value) })}
                className="min-h-[44px] bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded px-3 py-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {BASE_RATE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Centrality spread
              </span>
              <select
                value={form.centrality_spread}
                disabled={loading}
                onChange={(e) => setForm({ ...form, centrality_spread: Number(e.target.value) })}
                className="min-h-[44px] bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded px-3 py-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {SPREAD_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Exposure window
              </span>
              <select
                value={form.horizon_days}
                disabled={loading}
                onChange={(e) => setForm({ ...form, horizon_days: Number(e.target.value) })}
                className="min-h-[44px] bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded px-3 py-2 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {HORIZON_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>

            <button
              onClick={() => void solve(form)}
              disabled={loading}
              className="w-full px-4 py-2 min-h-[44px] rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-400 text-white font-semibold transition inline-flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Solving…
                </>
              ) : dirty ? (
                <>
                  <RefreshCw className="w-4 h-4" /> Solve with these
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4" /> Re-solve
                </>
              )}
            </button>
          </div>

          {/* Honest loading copy — this endpoint is genuinely slow the first time. */}
          {loading && (
            <div className="mt-4 flex items-start gap-3 bg-slate-900/60 border border-slate-700/60 rounded-lg p-3">
              <Loader2 className="w-4 h-4 text-blue-400 animate-spin shrink-0 mt-0.5" />
              <div className="text-[12px] text-slate-400 leading-relaxed">
                <p className="text-slate-200 font-medium">
                  Solving a two-stage stochastic program — 7 λ points, one CP-SAT solve each,
                  then an exact recourse re-solve on every scenario atom to score the plan.
                </p>
                <p className="mt-1">
                  The first run takes up to a minute, and the server caches the answer for about an
                  hour after that. If the demo backend was asleep, add roughly two minutes for the
                  container to wake up.{' '}
                  <span className="tabular-nums text-slate-400">Elapsed {elapsed}s.</span>
                </p>
              </div>
            </div>
          )}

          {!loading && !isPublished && data && (
            <div className="mt-4 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2">
              Showing a <strong>flexed</strong> instance (base rate{' '}
              {(solvedWith.base_annual_prob * 100).toFixed(2)}%, spread {solvedWith.centrality_spread},{' '}
              {solvedWith.horizon_days}-day window) — not the published assumptions. Figures below
              are live from this solve; the offline study numbers quoted in the explainer still
              refer to the published setting.{' '}
              <button
                onClick={() => { setForm(PUBLISHED_ASSUMPTIONS); void solve(PUBLISHED_ASSUMPTIONS); }}
                className="underline decoration-dotted underline-offset-2 hover:text-amber-200"
              >
                Reset to published
              </button>
            </div>
          )}
        </div>

        {/* ── Error ──────────────────────────────────────────────────────── */}
        {error && (
          <div className="bg-red-500/20 border border-red-400 rounded-lg px-4 py-3 text-red-300 flex gap-3 mb-5">
            <AlertTriangle size={20} className="flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold">Frontier solve failed</p>
              <p className="text-sm mt-1 leading-relaxed">{error}</p>
              <button
                onClick={() => void solve(form)}
                disabled={loading}
                className="mt-3 bg-slate-800 border border-slate-700 px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-950"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {/* ── Skeleton while the very first solve runs ───────────────────── */}
        {!data && loading && (
          <div className="flex flex-col items-center justify-center h-72 gap-4">
            <div className="w-8 h-8 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
            <p className="text-sm text-slate-400">Building the frontier…</p>
          </div>
        )}

        {/* ── Results ────────────────────────────────────────────────────── */}
        {data && (
          <>
            {/* Headline KPIs */}
            {rec?.available ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-5">
                <KpiCard
                  title="Tail removed per $1 spent"
                  value={fmtRatio(rec.cvar_removed_per_dollar_spent)}
                  sub={`Up to the knee. Past it the same dollar buys only ${fmtRatio(rec.cvar_removed_per_dollar_spent_beyond_knee)}.`}
                  accent="border-emerald-500/40"
                  delay={0.02}
                />
                <KpiCard
                  title="Extra expected cost"
                  value={fmtUsd(rec.extra_expected_cost_usd)}
                  sub={`${fmtPct(rec.extra_expected_cost_pct)} of spend on a ${fmtNum(data.instance.total_units)}-unit build.`}
                  accent="border-amber-500/30"
                  delay={0.06}
                />
                <KpiCard
                  title="CVaR₉₅ exposure removed"
                  value={fmtUsd(rec.cvar_reduction_usd)}
                  sub={`${fmtPct(rec.cvar_reduction_pct)} off the risk-neutral tail of ${fmtUsd(riskNeutral?.cvar_95_usd)}.`}
                  accent="border-indigo-500/30"
                  delay={0.10}
                />
                <KpiCard
                  title="Recommended λ"
                  value={String(rec.knee_lambda)}
                  sub={`${rec.n_suppliers} suppliers [${rec.supplier_ids?.join(', ')}] instead of the risk-neutral ${riskNeutral?.n_suppliers}.`}
                  accent="border-sky-500/30"
                  delay={0.14}
                />
              </div>
            ) : (
              <div className="rounded-xl p-5 mb-5 border bg-amber-500/5 border-amber-500/20">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">
                      No knee on this frontier
                    </span>
                    <p className="text-sm text-slate-300 leading-relaxed mt-2">{rec?.statement}</p>
                    <p className="text-xs text-slate-400 mt-2">
                      A flat frontier is a finding, not a failure: it says this BOM has no
                      cost-vs-tail-risk tradeoff to buy at these assumptions.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* The recommendation, in words */}
            {rec?.available && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.16, duration: 0.4 }}
                className="rounded-xl p-5 mb-5 border bg-emerald-500/5 border-emerald-500/20"
              >
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                      The recommendation
                    </span>
                    <p className="text-sm text-slate-200 leading-relaxed mt-2">
                      Source this BOM at <strong className="text-white">λ = {rec.knee_lambda}</strong>.
                      It costs <strong className="text-white">{fmtUsd(rec.extra_expected_cost_usd)}</strong> more
                      per {fmtNum(data.instance.total_units)}-unit build in expectation —{' '}
                      {fmtPct(rec.extra_expected_cost_pct)} of spend — and removes{' '}
                      <strong className="text-white">{fmtUsd(rec.cvar_reduction_usd)}</strong> of
                      CVaR₉₅ exposure. Every dollar of that premium buys{' '}
                      <strong className="text-emerald-300">{fmtRatio(rec.cvar_removed_per_dollar_spent)}</strong> of
                      tail reduction; past the knee the same dollar buys{' '}
                      <strong className="text-amber-300">{fmtRatio(rec.cvar_removed_per_dollar_spent_beyond_knee)}</strong>.
                      Stop at the knee.
                    </p>
                    <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                      The knee is located by maximum perpendicular distance to the chord joining the
                      extreme non-dominated points (the Kneedle / L-method criterion, Satopää et al.
                      2011), on min-max normalised axes so the answer does not depend on the currency
                      unit.
                    </p>
                  </div>
                </div>
              </motion.div>
            )}

            {/* ── The frontier chart ─────────────────────────────────────── */}
            <SectionCard
              eyebrow="The frontier"
              title="Expected cost vs CVaR₉₅ tail exposure"
              subtitle={`Each dot is a complete sourcing plan at one risk weight λ. Down and to the left is better; nothing sits there, which is exactly why there is a tradeoff. ${data.frontier_shape.statement}`}
            >
              <ResponsiveContainer width="100%" height={380}>
                <LineChart data={chartPoints} margin={{ top: 32, right: 32, left: 12, bottom: 28 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    type="number"
                    dataKey="expected_cost_usd"
                    domain={xDomain}
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    tickFormatter={xTickFormatter}
                    label={{
                      value: 'Expected cost  →  (more expensive)',
                      position: 'insideBottom', offset: -12, fill: '#64748b', fontSize: 12,
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="cvar_95_usd"
                    domain={yDomain}
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    tickFormatter={yTickFormatter}
                    label={{
                      value: 'CVaR₉₅ tail exposure  ↓  (safer)',
                      angle: -90, position: 'insideLeft', offset: 4, fill: '#64748b', fontSize: 12,
                    }}
                  />
                  <Tooltip content={<FrontierTooltip />} cursor={{ stroke: '#334155', strokeDasharray: '4 4' }} />
                  {riskNeutral && (
                    <ReferenceLine
                      y={riskNeutral.cvar_95_usd}
                      stroke="#475569"
                      strokeDasharray="4 4"
                      label={{
                        value: 'risk-neutral tail',
                        position: 'insideTopRight', fill: '#64748b', fontSize: 12,
                      }}
                    />
                  )}
                  <Line
                    type="linear"
                    dataKey="cvar_95_usd"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={{ r: 5, fill: '#6366f1', stroke: '#0f172a', strokeWidth: 2 }}
                    activeDot={{ r: 7 }}
                    isAnimationActive={false}
                  />
                  {/* Dominated points get a red ring: they pay more AND carry more tail. */}
                  {dominatedPoints.map((p) => (
                    <ReferenceDot
                      key={`dom-${p.lambda}`}
                      x={p.expected_cost_usd}
                      y={p.cvar_95_usd}
                      r={9}
                      fill="none"
                      stroke="#ef4444"
                      strokeWidth={2}
                    />
                  ))}
                  {/* The knee. */}
                  {kneePoint && (
                    <ReferenceDot
                      x={kneePoint.expected_cost_usd}
                      y={kneePoint.cvar_95_usd}
                      r={9}
                      fill="#f59e0b"
                      stroke="#0f172a"
                      strokeWidth={2}
                      label={{
                        value: `knee  λ=${kneePoint.lambda}`,
                        position: 'top', fill: '#fbbf24', fontSize: 12, offset: 12,
                      }}
                    />
                  )}
                </LineChart>
              </ResponsiveContainer>

              <div className="flex flex-wrap items-center gap-4 mt-3 text-[11px] text-slate-400">
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-indigo-500" /> λ point (one sourcing plan)
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500" /> knee — the recommendation
                </span>
                {dominatedPoints.length > 0 && (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full border-2 border-red-500" /> dominated —
                    strictly worse on both axes
                  </span>
                )}
              </div>

              {dominatedPoints.length > 0 && (
                <p className="text-xs text-slate-400 mt-3 leading-relaxed max-w-4xl">
                  <span className="text-slate-400 font-medium">Why a dominated point is kept rather than deleted:</span>{' '}
                  at λ = 1 the objective is CVaR alone, so any plan attaining the minimum CVaR is
                  optimal and the expected cost is broken arbitrarily. It is flagged{' '}
                  <code className="bg-slate-800 px-1 rounded">dominated</code> in the API response
                  instead of being quietly dropped. This is also the honest limitation of a
                  weighted-sum scalarization: sweeping λ recovers only Pareto points on the{' '}
                  <em>convex hull</em> of the (E, CVaR) image, so this frontier is a subset of the
                  true efficient set, never a superset.
                </p>
              )}
            </SectionCard>

            {/* ── Tail premium by λ ──────────────────────────────────────── */}
            <SectionCard
              eyebrow="What risk aversion actually buys"
              title="Tail premium by risk weight"
              subtitle="CVaR₉₅ minus expected cost — how much worse the bad 5% is than the average case. The amber bar is the knee."
            >
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={tailBars} margin={{ top: 8, right: 16, left: 8, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="lambda"
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    label={{ value: 'λ  (risk weight)', position: 'insideBottom', offset: -10, fill: '#64748b', fontSize: 12 }}
                  />
                  <YAxis
                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                    tickFormatter={tailTickFormatter}
                  />
                  <Tooltip content={<TailTooltip />} cursor={{ fill: '#1e293b', fillOpacity: 0.4 }} />
                  <Bar dataKey="tail_premium_usd" radius={[4, 4, 0, 0]}>
                    {tailBars.map((p) => (
                      <Cell
                        key={`tail-${p.lambda}`}
                        fill={p.isKnee ? '#f59e0b' : p.dominated ? '#64748b' : '#6366f1'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </SectionCard>

            {/* ── The table ──────────────────────────────────────────────── */}
            <SectionCard
              eyebrow="Every point, with its solve quality"
              title="The λ sweep"
              subtitle="A frontier point is only a frontier point if the solver proved its first-stage choice near-optimal, so the status and MIP gap are published per point rather than summarised away."
            >
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-400 border-b border-slate-700">
                      {/* normal-case: `uppercase` renders λ as Λ, a different symbol entirely,
    on a page written for readers who know the difference. */}
                      <th className="text-left font-semibold normal-case tracking-wider py-2 pr-3">λ</th>
                      <th className="text-right font-semibold uppercase tracking-wider py-2 px-3">E[cost]</th>
                      <th className="text-right font-semibold uppercase tracking-wider py-2 px-3">CVaR₉₅</th>
                      <th className="text-right font-semibold uppercase tracking-wider py-2 px-3">VaR₉₅</th>
                      <th className="text-right font-semibold uppercase tracking-wider py-2 px-3">Tail premium</th>
                      <th className="text-center font-semibold uppercase tracking-wider py-2 px-3">Suppliers</th>
                      <th
                        className="text-right font-semibold uppercase tracking-wider py-2 px-3"
                        title="Probability-weighted scenario atoms landing in the worst-5% tail — not equally weighted, so a count is not a percentage. The largest single atom can carry a disproportionate share of the tail's probability mass."
                      >
                        Atoms in 5% tail
                      </th>
                      <th className="text-left font-semibold uppercase tracking-wider py-2 px-3">Status</th>
                      <th className="text-right font-semibold uppercase tracking-wider py-2 px-3">Gap</th>
                      <th className="text-right font-semibold uppercase tracking-wider py-2 pl-3">Solve</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {tailBars.map((p) => (
                      <tr
                        key={p.lambda}
                        className={`border-b border-slate-800 ${
                          p.isKnee ? 'bg-amber-500/10 text-amber-100' : 'text-slate-300'
                        }`}
                      >
                        <td className="py-2 pr-3 font-semibold">
                          {p.lambda}
                          {p.isKnee && <span className="ml-2 text-[11px] uppercase tracking-wider text-amber-400 font-bold">knee</span>}
                          {p.dominated && <span className="ml-2 text-[11px] uppercase tracking-wider text-red-400 font-bold">dominated</span>}
                        </td>
                        <td className="py-2 px-3 text-right">{fmtUsd(p.expected_cost_usd)}</td>
                        <td className="py-2 px-3 text-right">{fmtUsd(p.cvar_95_usd)}</td>
                        <td className="py-2 px-3 text-right text-slate-400">{fmtUsd(p.var_95_usd)}</td>
                        <td className="py-2 px-3 text-right">{fmtUsd(p.tail_premium_usd)}</td>
                        <td className="py-2 px-3 text-center">
                          <span className="text-blue-400 font-semibold">{p.n_suppliers}</span>
                          <span className="text-slate-400 ml-1.5">[{p.supplier_ids.join(', ')}]</span>
                        </td>
                        <td className="py-2 px-3 text-right text-slate-400">{p.n_atoms_in_tail}</td>
                        <td className={`py-2 px-3 ${p.solver_status === 'OPTIMAL' ? 'text-emerald-400' : 'text-amber-400'}`}>
                          {p.solver_status}
                        </td>
                        <td className="py-2 px-3 text-right text-slate-400">{fmtPct(p.mip_gap_pct, 3)}</td>
                        <td className="py-2 pl-3 text-right text-slate-400">{p.solve_seconds.toFixed(2)}s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {data.partial && (
                <div className="mt-4 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 leading-relaxed">
                  <strong>Partial frontier:</strong> {data.solver.points_solved} of{' '}
                  {data.solver.points_requested} λ points solved inside the service's search
                  budget. The missing points are absent because <em>this service ran out of
                  compute</em>, not because no plan exists at those risk appetites. The sweep runs
                  descending in λ, so it is the risk-neutral end that is lost first — read any knee
                  against a truncated baseline with that in mind.
                  {data.unsolved_points.length > 0 && (
                    <span className="block mt-1 text-amber-300/80">
                      Unsolved: {data.unsolved_points.map((u) => `λ=${u.lambda} (${u.solver_status})`).join(', ')}
                    </span>
                  )}
                </div>
              )}
            </SectionCard>

            {/* ── Solve quality + how it was measured ────────────────────── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">
              <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-1">
                  <TrendingDown className="w-4 h-4 text-sky-400" /> How these numbers were measured
                </h2>
                <p className="text-xs text-slate-400 mb-4 leading-relaxed">
                  Reported statistics never come from the solver's own recourse variables — every
                  figure above is produced by re-solving each scenario's second stage exactly and
                  independently for the returned plan.
                </p>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
                  <dt className="text-slate-400">Solver</dt>
                  <dd className="text-slate-300 text-right">{data.solver.engine}</dd>
                  <dt className="text-slate-400">Search workers</dt>
                  <dd className="text-slate-300 text-right tabular-nums">{data.solver.num_search_workers}</dd>
                  <dt className="text-slate-400">Worst MIP gap in this sweep</dt>
                  <dd className="text-slate-300 text-right tabular-nums">{fmtPct(data.solver.worst_mip_gap_pct, 4)}</dd>
                  <dt className="text-slate-400">Any point hit the time limit?</dt>
                  <dd className={`text-right ${data.solver.any_point_hit_time_limit ? 'text-amber-400' : 'text-emerald-400'}`}>
                    {data.solver.any_point_hit_time_limit ? 'yes' : 'no'}
                  </dd>
                  <dt className="text-slate-400">Sweep wall clock</dt>
                  <dd className="text-slate-300 text-right tabular-nums">{data.solver.sweep_wall_seconds.toFixed(2)}s</dd>
                  <dt className="text-slate-400">Scenario support</dt>
                  <dd className="text-slate-300 text-right tabular-nums">
                    {data.scenarios.evaluation_set.kind} · {fmtNum(data.scenarios.evaluation_set.n_atoms)} atoms
                  </dd>
                  <dt className="text-slate-400">Plan chosen on</dt>
                  {/*
                    The solver optimises on the enumerated support when it fits the
                    variable budget. On that path there are no draws at all, so the
                    old wording rendered "64 distinct of 0 draws".
                  */}
                  <dd className="text-slate-300 text-right tabular-nums">
                    {data.scenarios.solve_set.exact
                      ? `exact · ${fmtNum(data.scenarios.solve_set.n_atoms_weighted ?? data.scenarios.solve_set.n_distinct)} atoms`
                      : `${fmtNum(data.scenarios.solve_set.n_distinct)} distinct of ${fmtNum(data.scenarios.n_draws)} draws`}
                  </dd>
                  <dt className="text-slate-400">P(no disruption)</dt>
                  {/* 5 decimals: on the exact path this is a computed probability,
                      not a 200-draw frequency, so the extra digits are meaningful. */}
                  <dd className="text-slate-300 text-right tabular-nums">
                    {data.scenarios.p_no_disruption.toFixed(
                      data.scenarios.solve_set.exact ? 5 : 3,
                    )}
                  </dd>
                </dl>
                <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-3 mt-4">
                  <p className="text-xs text-slate-400 leading-relaxed">
                    {data.scenarios.evaluation_set.note}
                  </p>
                </div>
                {data.scenarios.solve_set.thinned && (
                  <p className="text-xs text-amber-400 mt-2 leading-relaxed">
                    {data.scenarios.solve_set.note}
                  </p>
                )}
              </div>

              <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-1">
                  <Database className="w-4 h-4 text-sky-400" /> The instance
                </h2>
                <p className="text-xs text-slate-400 mb-4 leading-relaxed">
                  A power-supply BOM at production volume. The tradeoff only exists at volume — at
                  prototype quantities the fixed per-supplier charge decides everything and every λ
                  returns the same plan.
                </p>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
                  <dt className="text-slate-400">BOM lines</dt>
                  <dd className="text-slate-300 text-right tabular-nums">{data.instance.n_lines}</dd>
                  <dt className="text-slate-400">Total units</dt>
                  <dd className="text-slate-300 text-right tabular-nums">{fmtNum(data.instance.total_units)}</dd>
                  <dt className="text-slate-400">Strategy</dt>
                  <dd className="text-slate-300 text-right">{data.instance.strategy}</dd>
                  <dt className="text-slate-400">Domestic only</dt>
                  <dd className="text-slate-300 text-right">{data.instance.us_only ? 'yes' : 'no'}</dd>
                  <dt className="text-slate-400">Depot</dt>
                  <dd className="text-slate-300 text-right tabular-nums">
                    {data.instance.depot_lat.toFixed(4)} / {data.instance.depot_lng.toFixed(4)}
                  </dd>
                  <dt className="text-slate-400">Suppliers in pool</dt>
                  <dd className="text-slate-300 text-right tabular-nums">{data.calibration.n_distributors_in_pool}</dd>
                </dl>
                <div className="flex flex-wrap gap-1.5 mt-4">
                  {PUBLISHED_ITEMS.map((it) => (
                    <span
                      key={it.component_id}
                      className="text-[11px] font-mono bg-slate-900/70 border border-slate-700 rounded px-2 py-1 text-slate-400"
                    >
                      {it.mpn} × {fmtNum(it.quantity)}
                    </span>
                  ))}
                </div>
                <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-3 mt-4">
                  <p className="text-xs text-slate-400 leading-relaxed">{data.instance.depot_note}</p>
                </div>
              </div>
            </div>

            {/* ── Calibration (secondary panel) ──────────────────────────── */}
            <SectionCard
              eyebrow="The weakest input, published rather than buried"
              title="Disruption probability calibration"
              subtitle="Where the failure probabilities come from, and what they replaced. The predecessor read a min-max normalised betweenness score directly as a probability — which by construction made the single most central distributor fail in 100% of scenarios, because a min-max rescale always attains 1.0 at its maximum. A centrality rank is not a probability."
            >
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Pool minimum
                  </span>
                  <div className="text-2xl font-bold text-white tabular-nums mt-1">
                    {fmtPct(data.calibration.p_disruption_min * 100)}
                  </div>
                  <span className="text-xs text-slate-400">least central supplier</span>
                </div>
                <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Pool median
                  </span>
                  <div className="text-2xl font-bold text-white tabular-nums mt-1">
                    {fmtPct(data.calibration.p_disruption_median * 100)}
                  </div>
                  <span className="text-xs text-slate-400">
                    not guaranteed to equal the base rate — the pool&apos;s geometric mean does, by construction
                  </span>
                </div>
                <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Pool maximum
                  </span>
                  <div className="text-2xl font-bold text-white tabular-nums mt-1">
                    {fmtPct(data.calibration.p_disruption_max * 100)}
                  </div>
                  <span className="text-xs text-slate-400">most central supplier — nowhere near 1.0</span>
                </div>
              </div>

              <p className="text-xs text-slate-400 leading-relaxed mb-4 max-w-4xl">
                Over a {data.calibration.horizon_days}-day purchase-order window, at a{' '}
                {(data.calibration.base_annual_prob * 100).toFixed(2)}% annual base rate and a
                centrality spread of {data.calibration.centrality_spread}. The base rate sets the{' '}
                <span className="text-slate-200">level</span> of risk and is cited; betweenness
                rank only sets its <span className="text-slate-200">shape</span> across suppliers,
                bounded so the most central supplier gets spread × the base rate and the least
                central 1/spread ×. That separation is the fix: a bounded rank transform cannot hand
                any supplier a probability of 1.0.
              </p>

              {calibration && (
                <>
                  <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-3 mb-4">
                    <p className="text-xs text-slate-400 leading-relaxed">
                      <span className="text-slate-200 font-medium">Base rate source.</span>{' '}
                      {calibration.base_rate_source.citation} — “{calibration.base_rate_source.quote}”.{' '}
                      {calibration.base_rate_source.derivation}.
                    </p>
                    <p className="text-xs text-amber-400/90 mt-2 leading-relaxed">
                      <span className="font-medium">Known weakness, stated rather than hidden:</span>{' '}
                      {calibration.base_rate_source.known_weakness}
                    </p>
                  </div>

                  {poolCalibrated.length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-slate-400 border-b border-slate-700">
                            <th className="text-left font-semibold uppercase tracking-wider py-2 pr-3">Distributor</th>
                            <th className="text-right font-semibold uppercase tracking-wider py-2 px-3">Betweenness</th>
                            <th className="text-right font-semibold uppercase tracking-wider py-2 pl-3">
                              p(disruption), network-wide rank
                            </th>
                          </tr>
                        </thead>
                        <tbody className="tabular-nums">
                          {[...poolCalibrated]
                            .sort((a, b) => b.betweenness_normalized - a.betweenness_normalized)
                            .map((d) => (
                              <tr key={d.distributor_id} className="border-b border-slate-800 text-slate-300">
                                <td className="py-2 pr-3">
                                  {d.distributor_name}
                                  <span className="text-slate-400 ml-2 text-[11px]">#{d.distributor_id}</span>
                                </td>
                                <td className="py-2 px-3 text-right text-slate-400">
                                  {d.betweenness_normalized.toFixed(6)}
                                </td>
                                <td className="py-2 pl-3 text-right">
                                  {(d.p_disruption_over_horizon * 100).toFixed(2)}%
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-3 mt-4">
                    <p className="text-xs text-slate-400 leading-relaxed">
                      <span className="text-amber-400 font-medium">Scope note — the two sets of
                      probabilities on this page are not the same numbers.</span>{' '}
                      The tiles above are the rank transform computed over{' '}
                      <strong>this BOM's {data.calibration.n_distributors_in_pool}-supplier pool</strong>,
                      which is what the frontier actually solved with. The table is{' '}
                      <code className="bg-slate-800 px-1 rounded">GET /stochastic/calibration</code>,
                      which ranks all {fmtNum(calibration.distributors.length)} distributors in the
                      graph and therefore compresses these six together near the top. Both are
                      correct; they answer different questions, and conflating them would be exactly
                      the kind of quiet substitution this section exists to prevent.
                    </p>
                  </div>
                </>
              )}
            </SectionCard>

            {/* ── Offline study + caveats ────────────────────────────────── */}
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 mb-5">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-2">
                <Database className="w-4 h-4 text-sky-400" /> The offline study behind this page
              </h2>
              <p className="text-sm text-slate-300 leading-relaxed max-w-4xl">
                The seven λ points above are a live request. They sit on top of a much larger
                offline study (<code className="bg-slate-800 px-1 rounded">docs/CVAR_EFFICIENT_FRONTIER.md</code>)
                of <strong className="text-white">387 λ-solves</strong> across ten reference BOMs
                and a 36-cell sensitivity grid. Of those,{' '}
                <strong className="text-white">330 converged</strong> and{' '}
                <strong className="text-amber-300">57 did not</strong> — the non-converged solves are
                kept in the artifact but <em>excluded from every knee, every reported spread and
                every headline figure</em>, because a plan whose objective could be 93% away from
                the unknown optimum tells you nothing about the price of resilience. The arm this
                page reproduces was fully proved: 27 of 27 λ-solves returned{' '}
                <code className="bg-slate-800 px-1 rounded">OPTIMAL</code> at a worst MIP gap of
                0.082%.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Value of the stochastic solution
                  </span>
                  <div className="text-2xl font-bold text-white tabular-nums mt-1">$676</div>
                  <span className="text-xs text-slate-400 leading-relaxed block mt-1">
                    0.37% of spend. Deliberately <em>small</em>: the deterministic optimizer was
                    already close to the risk-neutral optimum. Everything this model adds, it adds
                    in the tail.
                  </span>
                </div>
                <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Sensitivity grid
                  </span>
                  <div className="text-2xl font-bold text-white tabular-nums mt-1">31 / 36</div>
                  <span className="text-xs text-slate-400 leading-relaxed block mt-1">
                    cells where a knee still exists when the probability assumptions are flexed —
                    and 11 of 12 in the arm that removes centrality from the model entirely.
                  </span>
                </div>
                <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    The 15% surcharge it replaced
                  </span>
                  <div className="text-2xl font-bold text-white tabular-nums mt-1">λ ≈ 0.10</div>
                  <span className="text-xs text-slate-400 leading-relaxed block mt-1">
                    The shipped heuristic is not dominated — it lands <em>on</em> this curve. What it
                    cannot do is tell you that, or let you move.
                  </span>
                </div>
              </div>
            </div>

            {/* Caveats, collapsed. */}
            <details className="mb-10 group">
              <summary className="min-h-[44px] flex items-center text-xs text-slate-400 hover:text-slate-300 cursor-pointer inline-flex items-center gap-1.5 list-none marker:content-['']">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-slate-400" />
                <span className="underline decoration-dotted underline-offset-2">
                  What this model does not capture ({data.caveats.length} caveats, returned by the API itself)
                </span>
                <ChevronRight className="w-3 h-3 transition-transform group-open:rotate-90" />
              </summary>
              <div className="mt-2 bg-slate-900/60 border border-slate-700/60 rounded-lg p-4 space-y-3">
                {data.caveats.map((c, i) => (
                  <p key={i} className="text-xs text-slate-400 leading-relaxed">
                    <span className="text-slate-400 mr-1.5">{i + 1}.</span>{c}
                  </p>
                ))}
                <p className="text-xs text-slate-400 leading-relaxed border-t border-slate-800 pt-3">
                  <span className="text-slate-200 font-medium">Net direction of bias.</span> Supplier
                  outages are binary (overstates individual scenario severity), but failures are drawn{' '}
                  <em>independently</em>, emergency prices are catalogue plus a fixed premium, and
                  qualifying a supplier not opened in stage one is free. Correlated disruptions are
                  exactly what makes real tails fat. On balance the tail reported here is, if
                  anything, <span className="text-amber-300">optimistic</span>.
                </p>
              </div>
            </details>
          </>
        )}

        {/* Nothing to show and not loading — only reachable if the first solve errored. */}
        {!data && !loading && !error && (
          <div className="flex flex-col items-center justify-center h-72 gap-3">
            <p className="text-sm text-slate-400">No frontier computed yet.</p>
            <button
              onClick={() => void solve(form)}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold transition"
            >
              Solve the frontier
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
