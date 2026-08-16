import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, ReferenceLine,
} from 'recharts';
import { TrendingUp, TrendingDown, Minus, ExternalLink, RefreshCw } from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import { useCartStore } from '../store/cartStore';
import { componentsAPI, distributorsAPI, feedsAPI, marketAPI } from '../services/api';
import type {
  MarketSummaryResponse, AlertsResponse, CommodityResponse, MarketStatusResponse,
} from '../services/api';
import { RISK_COLORS, riskLabel } from '../lib/risk';

// ── Types ─────────────────────────────────────────────────────────────────────
interface ComponentItem {
  id: number;
  mpn: string;
  manufacturer: string;
  category: string;
  description: string | null;
  risk_score: number;
  risk_factors: Record<string, unknown> | null;
  min_price: number | null;
  max_price: number | null;
  num_offers: number;
}

interface DistributorItem {
  id: number;
  name: string;
  city: string | null;
  state: string | null;
  country: string;
  is_domestic: boolean;
  total_offers: number;
  total_stock: number;
}

// ── Animated KPI Card ─────────────────────────────────────────────────────────
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
      <span className="text-slate-400 text-xs font-medium uppercase tracking-wider">{title}</span>
      <span className="text-3xl font-bold text-white tabular-nums">{value}</span>
      <span className="text-slate-500 text-xs">{sub}</span>
    </motion.div>
  );
}

// ── Explicit degraded/error state for a data section ─────────────────────────
// Used wherever a chart or list would otherwise render an empty/zero state
// that's indistinguishable from "backend returned real data, there's just
// nothing here." Never let a failed fetch look like a confident zero.
function DataUnavailable({ height = 'h-40' }: { height?: string }) {
  return (
    <div className={`${height} flex flex-col items-center justify-center gap-1 text-center px-4`}>
      <span className="text-red-400 text-xs font-medium">Data unavailable</span>
      <span className="text-slate-600 text-[11px]">Backend unreachable — not shown as zero</span>
    </div>
  );
}

// Truncate a category label to a fixed character length with an ellipsis,
// instead of grabbing the first N words (which produced labels like
// "Analog to" or "DSPs -" for names such as "DSPs - Digital Signal Processors").
const CATEGORY_LABEL_MAX = 22;
const truncateLabel = (s: string): string => (
  s.length > CATEGORY_LABEL_MAX ? `${s.slice(0, CATEGORY_LABEL_MAX - 1).trimEnd()}…` : s
);

// Live Feeds poll cadence — copy that references this ("every N minutes")
// is derived from this constant so it can never drift from the real interval.
const FEED_POLL_INTERVAL_MS = 60_000;
const FEED_POLL_LABEL = FEED_POLL_INTERVAL_MS % 60_000 === 0
  ? `${FEED_POLL_INTERVAL_MS / 60_000} minute${FEED_POLL_INTERVAL_MS / 60_000 === 1 ? '' : 's'}`
  : `${FEED_POLL_INTERVAL_MS / 1000} seconds`;

// ── Custom Scatter Tooltip ────────────────────────────────────────────────────
function RiskTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const rl = riskLabel(d.y);
  return (
    <div className="bg-slate-900 border border-slate-600 rounded-lg p-3 text-xs shadow-xl max-w-[200px]">
      <p className="text-white font-semibold mb-1 truncate">{d.name}</p>
      <p className="text-slate-400">Category: <span className="text-slate-200">{d.category}</span></p>
      <p className="text-slate-400">Risk: <span style={{ color: RISK_COLORS[rl] }}>{(d.y * 100).toFixed(0)}%</span></p>
      <p className="text-slate-400">Offers: <span className="text-blue-400">{d.offers}</span></p>
      {d.price && <p className="text-slate-400">Min Price: <span className="text-green-400">${d.price.toFixed(4)}</span></p>}
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────
export const Dashboard = () => {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { items: cartItems } = useCartStore();

  const [components, setComponents] = useState<ComponentItem[]>([]);
  const [distributors, setDistributors] = useState<DistributorItem[]>([]);
  const [loading, setLoading] = useState(true);
  // True only after a fetch attempt actually failed — never inferred from
  // empty data, so a slow-but-working backend never gets flagged as down.
  const [dataError, setDataError] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [cRes, dRes] = await Promise.all([componentsAPI.list(), distributorsAPI.list()]);
      setComponents(cRes.data);
      setDistributors(dRes.data);
      setDataError(false);
    } catch {
      // Backend unreachable/errored — surface it explicitly rather than
      // leaving components/distributors at [] and letting every KPI below
      // render a confident-looking zero.
      setDataError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Live Feeds status ────────────────────────────────────────────────────────
  const [feedStatus, setFeedStatus] = useState<Array<{
    name: string;
    fetched_at: string | null;
    // 'inactive' = credential not configured, feed never ran (detail says which
    // env var is missing). Distinct from 'unavailable' = tried and failed.
    status: 'live' | 'stale' | 'inactive' | 'unavailable';
    value_summary: string | null;
    detail?: string | null;
  }>>([]);
  const [feedError, setFeedError] = useState(false);

  useEffect(() => {
    const fetchFeeds = async () => {
      try {
        const res = await feedsAPI.getStatus();
        setFeedStatus(res.data);
        setFeedError(false);
      } catch {
        setFeedError(true);
      }
    };
    fetchFeeds();
    const interval = setInterval(fetchFeeds, FEED_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  // ── Market Intelligence (GDI / disruption alerts / commodities) ────────────
  // Backed by app/api/market_intelligence.py — every field is real SupplyMaven
  // data or an honest `available: false`. SUPPLYMAVEN_API_KEY is not currently
  // configured, so this renders the inactive state below until a key is added.
  const [marketSummary, setMarketSummary] = useState<MarketSummaryResponse | null>(null);
  const [marketAlerts, setMarketAlerts] = useState<AlertsResponse | null>(null);
  const [marketCommodities, setMarketCommodities] = useState<CommodityResponse | null>(null);
  const [marketStatus, setMarketStatus] = useState<MarketStatusResponse | null>(null);
  const [marketLoading, setMarketLoading] = useState(true);
  const [marketError, setMarketError] = useState(false);
  const [alertsExpanded, setAlertsExpanded] = useState(false);
  const [gdiRefreshing, setGdiRefreshing] = useState(false);

  // Refreshes just the GDI score/pillars via GET /market/disruption-index —
  // deliberately NOT re-calling /market/summary, which also re-fetches alerts
  // and trade-policy data upstream. A score-only refresh shouldn't burn 3x the
  // SupplyMaven API quota for data the user didn't ask to update.
  const refreshGdi = useCallback(async () => {
    setGdiRefreshing(true);
    try {
      const res = await marketAPI.disruptionIndex();
      setMarketSummary((prev) => (prev ? { ...prev, gdi: res.data } : prev));
    } catch {
      // leave the previous GDI reading in place on failure
    } finally {
      setGdiRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const loadMarket = async () => {
      try {
        const [summaryRes, statusRes] = await Promise.all([
          marketAPI.summary(),
          marketAPI.status(),
        ]);
        setMarketSummary(summaryRes.data);
        setMarketStatus(statusRes.data);
        setMarketError(false);
        // Only pull the heavier alert/commodity breakdowns when there's a live
        // key behind them — an unconfigured source returns instantly anyway,
        // but there's nothing to show, so skip the extra round trips.
        if (summaryRes.data.gdi.available) {
          const [alertsRes, commoditiesRes] = await Promise.all([
            marketAPI.alerts(),
            marketAPI.commodities(),
          ]);
          setMarketAlerts(alertsRes.data);
          setMarketCommodities(commoditiesRes.data);
        }
      } catch {
        // Market intelligence is supplementary and never blocks the rest of
        // the dashboard, but the failure still has to be visible — an empty
        // section here reads as "nothing to report" instead of "couldn't load".
        setMarketError(true);
      } finally {
        setMarketLoading(false);
      }
    };
    loadMarket();
  }, []);

  const gdiColor = (score: number | null): string => {
    if (score === null) return '#64748b';
    if (score < 30) return '#4ade80';
    if (score < 60) return '#fbbf24';
    return '#f87171';
  };

  const formatFeedTime = (isoString: string | null): string => {
    if (!isoString) return '\u2014';
    const date = new Date(isoString);
    const diffMs = Date.now() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 60) return `${diffMin}m ago`;
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
    }).format(date) + ' UTC';
  };

  // ── Derived data ────────────────────────────────────────────────────────────
  // >= 0.7 to match riskLabel()'s own "high" boundary (score < 0.7 => medium,
  // else high) — a strict > 0.7 filter disagreed with the "Highest Risk
  // Components" list below, which can show an item sitting at exactly 70%.
  const highRisk = components.filter((c) => riskLabel(c.risk_score) === 'high').length;
  const avgRisk = components.length
    ? (components.reduce((s, c) => s + c.risk_score, 0) / components.length)
    : 0;
  const domesticDists = distributors.filter((d) => d.is_domestic).length;

  // Risk matrix data for scatter chart — risk_score vs num_offers
  const riskMatrix = components.slice(0, 200).map((c) => ({
    x: c.num_offers / Math.max(1, ...components.map((cc) => cc.num_offers)),
    y: c.risk_score,
    z: c.min_price ? Math.log(c.min_price + 1) * 30 + 20 : 30,
    name: c.mpn,
    category: truncateLabel(c.category),
    price: c.min_price,
    offers: c.num_offers,
  }));

  // Category distribution — grouped by the full category name (not a
  // first-two-words truncation, which collapsed distinct categories like
  // "DSPs - Digital Signal Processors" into "DSPs -" and undercounted the
  // real category total the API reports). Labels are only truncated for
  // display via truncateLabel().
  const catCounts = components.reduce<Record<string, number>>((acc, c) => {
    acc[c.category] = (acc[c.category] || 0) + 1;
    return acc;
  }, {});
  const categoryData = Object.entries(catCounts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([name, value]) => ({ name: truncateLabel(name), value }));

  const CATEGORY_COLORS = ['#6366f1', '#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#8b5cf6', '#ef4444', '#06b6d4', '#f97316', '#14b8a6'];

  // Category risk radar — same full-name grouping as catCounts above.
  const catRisk = Object.entries(
    components.reduce<Record<string, { risk: number; count: number }>>((acc, c) => {
      const cat = c.category;
      if (!acc[cat]) acc[cat] = { risk: 0, count: 0 };
      acc[cat].risk += c.risk_score;
      acc[cat].count += 1;
      return acc;
    }, {})
  )
    .sort(([, a], [, b]) => b.count - a.count)
    .slice(0, 8)
    .map(([cat, d]) => ({
      category: truncateLabel(cat),
      'Supply Risk': parseFloat(((d.risk / d.count) * 100).toFixed(1)),
    }));

  // Distributor country distribution
  const countryBins = distributors.reduce<Record<string, number>>((acc, d) => {
    acc[d.country] = (acc[d.country] || 0) + 1;
    return acc;
  }, {});
  const countryData = Object.entries(countryBins)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6)
    .map(([label, count], i) => ({ label, count, fill: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }));

  // NAV badges/desc read live counts from state, never a hardcoded snapshot —
  // and fall back to an honest "Unavailable" instead of a confident "0" when
  // the underlying fetch failed (dataError).
  const NAV = [
    { title: 'Distributor Map', desc: dataError ? 'Distributors worldwide' : `${distributors.length} distributors worldwide`, icon: '🗺️', path: '/map', border: 'hover:border-blue-500 hover:bg-blue-500/5', badge: dataError ? 'Unavailable' : `${distributors.length} distributors` },
    { title: 'Component Browser', desc: dataError ? 'Real pricing from live distributors' : `Real pricing from ${distributors.length} distributors`, icon: '📊', path: '/scheduler', border: 'hover:border-green-500 hover:bg-green-500/5', badge: dataError ? 'Unavailable' : `${components.length} components` },
    { title: 'Bill of Materials', desc: 'Build orders across distributors', icon: '🛒', path: '/cart', border: 'hover:border-purple-500 hover:bg-purple-500/5', badge: cartItems.length > 0 ? `${cartItems.length} items` : 'Empty' },
    { title: 'Route Optimization', desc: 'OR-Tools VRP, Monte Carlo ETA', icon: '🚀', path: '/checkout', border: 'hover:border-orange-500 hover:bg-orange-500/5', badge: 'VRP Solver' },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 overflow-y-auto h-full">
      <div className="max-w-7xl mx-auto px-6 py-8">

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex items-start justify-between mb-8"
        >
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">
              Supply Chain Intelligence
            </h1>
            <p className="text-slate-400 mt-1 text-sm">
              Welcome back, <span className="text-white font-medium">{user?.factory_name}</span>
              {user && (
                <span className="text-slate-600 ml-2">
                  {user.latitude?.toFixed(2)}°N {Math.abs(user.longitude ?? 0).toFixed(2)}°W
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {loading ? (
              <span className="inline-flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 text-slate-400 text-xs px-3 py-1.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse" />
                Loading…
              </span>
            ) : dataError ? (
              <span className="inline-flex items-center gap-1.5 bg-red-500/10 border border-red-500/30 text-red-400 text-xs px-3 py-1.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                Data unavailable — backend unreachable
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-xs px-3 py-1.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                Real Data
              </span>
            )}
          </div>
        </motion.div>

        {/* ── KPI Strip ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <KpiCard delay={0}    title="Components"      value={loading ? '…' : dataError ? '—' : components.length}    sub={dataError ? 'fetch failed' : 'from HuggingFace dataset'}      accent={dataError ? 'border-red-500/30' : 'border-slate-700'} />
          <KpiCard delay={0.05} title="Distributors"    value={loading ? '…' : dataError ? '—' : distributors.length}  sub={dataError ? 'fetch failed' : `${domesticDists} domestic, ${distributors.length - domesticDists} int'l`} accent={dataError ? 'border-red-500/30' : 'border-blue-500/30'} />
          <KpiCard delay={0.1}  title="Avg Supply Risk" value={loading ? '…' : dataError ? '—' : `${(avgRisk * 100).toFixed(0)}%`} sub={dataError ? 'fetch failed' : 'across all components'} accent={dataError ? 'border-red-500/30' : avgRisk > 0.6 ? 'border-red-500/40' : avgRisk > 0.4 ? 'border-yellow-500/30' : 'border-green-500/30'} />
          <KpiCard delay={0.15} title="High-Risk Items"  value={loading ? '…' : dataError ? '—' : highRisk}            sub={dataError ? 'fetch failed' : 'risk score ≥ 70%'}              accent="border-red-500/30" />
        </div>

        {/* ── Row 2: Risk Matrix + Category Distribution ─────────────────── */}
        <div className="grid grid-cols-5 gap-4 mb-6">

          {/* Risk Matrix Scatter */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2, duration: 0.5 }}
            className="col-span-3 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
          >
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-white font-semibold text-sm">Component Risk Matrix</h3>
                <p className="text-slate-500 text-xs mt-0.5">Offer availability vs Supply Risk · bubble size = price</p>
              </div>
            </div>
            {loading ? (
              <div className="h-52 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            ) : dataError ? (
              <DataUnavailable height="h-52" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    type="number" dataKey="x" name="Offer Availability"
                    domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                    tick={{ fill: '#64748b', fontSize: 10 }} label={{ value: 'Offer Availability', position: 'insideBottom', offset: -8, fill: '#475569', fontSize: 10 }}
                  />
                  <YAxis
                    type="number" dataKey="y" name="Supply Risk"
                    domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                    tick={{ fill: '#64748b', fontSize: 10 }} label={{ value: 'Supply Risk', angle: -90, position: 'insideLeft', offset: 12, fill: '#475569', fontSize: 10 }}
                  />
                  <ZAxis type="number" dataKey="z" range={[20, 200]} />
                  <Tooltip content={<RiskTooltip />} cursor={{ stroke: '#334155', strokeDasharray: '4 4' }} />
                  <ReferenceLine x={0.5} stroke="#334155" strokeDasharray="4 4" />
                  <ReferenceLine y={0.5} stroke="#334155" strokeDasharray="4 4" />
                  <Scatter
                    name="Components"
                    data={riskMatrix}
                    fill="#6366f1"
                    fillOpacity={0.6}
                  />
                </ScatterChart>
              </ResponsiveContainer>
            )}
            {!loading && !dataError && (
              <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-slate-600">
                <span className="text-left pl-8">◄ Few Offers · Low Risk (Niche)</span>
                <span className="text-right pr-4">Many Offers · High Risk (Critical) ►</span>
              </div>
            )}
          </motion.div>

          {/* Category Donut + Distributor Countries */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.25, duration: 0.5 }}
            className="col-span-2 flex flex-col gap-4"
          >
            {/* Donut */}
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 flex-1 backdrop-blur-sm">
              <h3 className="text-white font-semibold text-sm mb-1">Top Categories</h3>
              <p className="text-slate-500 text-xs mb-3">
                {dataError ? 'Unavailable' : `${components.length} components across ${Object.keys(catCounts).length} categories`}
              </p>
              {loading ? (
                <div className="h-32 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
              ) : dataError ? (
                <DataUnavailable height="h-32" />
              ) : (
                <div className="flex items-center gap-3">
                  <ResponsiveContainer width="60%" height={120}>
                    <PieChart>
                      <Pie data={categoryData} cx="50%" cy="50%" innerRadius={32} outerRadius={52} dataKey="value" strokeWidth={0}>
                        {categoryData.map((_, i) => (
                          <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
                        formatter={(v: any, n: any) => [v, n]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex flex-col gap-1 flex-1">
                    {categoryData.slice(0, 6).map((d, i) => (
                      <div key={d.name} className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-1.5 text-slate-400 truncate">
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />
                          {d.name}
                        </span>
                        <span className="text-slate-300 tabular-nums ml-1">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Distributor countries */}
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm">
              <h3 className="text-white font-semibold text-sm mb-1">Distributor Countries</h3>
              <p className="text-slate-500 text-xs mb-3">{dataError ? 'Unavailable' : `${distributors.length} distributors`}</p>
              {loading ? (
                <div className="h-16 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
              ) : dataError ? (
                <DataUnavailable height="h-16" />
              ) : (
                <ResponsiveContainer width="100%" height={60}>
                  <BarChart data={countryData} margin={{ top: 0, right: 0, left: -16, bottom: 0 }}>
                    <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {countryData.map((b, i) => <Cell key={i} fill={b.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </motion.div>
        </div>

        {/* ── Row 3: Risk Radar ───────────────────── */}
        <div className="grid grid-cols-5 gap-4 mb-6">
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.3, duration: 0.5 }}
            className="col-span-3 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
          >
            <h3 className="text-white font-semibold text-sm mb-1">Risk Radar by Category</h3>
            <p className="text-slate-500 text-xs mb-3">Avg supply risk per top category</p>
            {loading ? (
              <div className="h-48 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            ) : dataError ? (
              <DataUnavailable height="h-48" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <RadarChart data={catRisk} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
                  <PolarGrid stroke="#1e293b" />
                  <PolarAngleAxis dataKey="category" tick={{ fill: '#64748b', fontSize: 9 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: '#334155', fontSize: 8 }} />
                  <Radar name="Supply Risk" dataKey="Supply Risk" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} strokeWidth={1.5} />
                  <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }} />
                </RadarChart>
              </ResponsiveContainer>
            )}
          </motion.div>

          {/* Top risky components */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35, duration: 0.5 }}
            className="col-span-2 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
          >
            <h3 className="text-white font-semibold text-sm mb-1">Highest Risk Components</h3>
            <p className="text-slate-500 text-xs mb-3">Top 5 by risk score</p>
            {loading ? (
              <div className="h-40 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            ) : dataError ? (
              <DataUnavailable height="h-40" />
            ) : (
              <div className="space-y-2">
                {[...components]
                  .sort((a, b) => b.risk_score - a.risk_score)
                  .slice(0, 5)
                  .map((c, i) => {
                    const rl = riskLabel(c.risk_score);
                    return (
                      <motion.div
                        key={c.id}
                        initial={{ opacity: 0, x: 12 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.4 + i * 0.06 }}
                        className="flex items-center justify-between bg-slate-900/50 rounded-lg px-3 py-2"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-white text-xs font-medium truncate">{c.mpn}</p>
                          <p className="text-slate-500 text-[10px] truncate">{c.manufacturer}</p>
                        </div>
                        <div className="flex items-center gap-3 text-xs shrink-0 ml-2">
                          <span className="text-slate-400">{c.num_offers} offers</span>
                          <span className="font-semibold" style={{ color: RISK_COLORS[rl] }}>
                            {(c.risk_score * 100).toFixed(0)}%
                          </span>
                        </div>
                      </motion.div>
                    );
                  })}
              </div>
            )}
          </motion.div>
        </div>

        {/* ── Live Feeds Status ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-5 gap-4 mb-6">
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.5, duration: 0.5 }}
            className="col-span-5 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
            aria-live="polite"
          >
            <div className="mb-3">
              <h3 className="text-white font-semibold text-sm">Live Feeds</h3>
              <p className="text-slate-500 text-xs mt-0.5">External signals refreshed every {FEED_POLL_LABEL}</p>
            </div>
            {feedError ? (
              <p className="text-slate-500 text-xs py-2">Feed status unavailable. Refresh to retry.</p>
            ) : (
              <div className="space-y-0">
                {(feedStatus.length > 0 ? feedStatus : [
                  { name: 'GPR Index', fetched_at: null, status: 'unavailable' as const, value_summary: null },
                  { name: 'ACLED Conflict', fetched_at: null, status: 'unavailable' as const, value_summary: null },
                  { name: 'IMF PortWatch', fetched_at: null, status: 'unavailable' as const, value_summary: null },
                  { name: 'FRED Freight', fetched_at: null, status: 'unavailable' as const, value_summary: null },
                ]).map((feed) => (
                  <div
                    key={feed.name}
                    className="flex items-center justify-between py-2 hover:bg-slate-900/50 rounded px-2 -mx-2"
                    title={
                      feed.detail
                        ? feed.detail
                        : feed.fetched_at
                          ? `Last fetched: ${feed.fetched_at}`
                          : undefined
                    }
                  >
                    <span className="text-xs font-semibold text-slate-200">{feed.name}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-[11px] text-slate-400 tabular-nums">
                        {formatFeedTime(feed.fetched_at)}
                      </span>
                      {feed.status === 'live' && (
                        <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[11px] px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-400 motion-safe:animate-pulse" />
                          Live
                        </span>
                      )}
                      {feed.status === 'stale' && (
                        <span className="inline-flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[11px] px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                          Stale
                        </span>
                      )}
                      {feed.status === 'inactive' && (
                        <span className="inline-flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 text-slate-400 text-[11px] px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full border border-slate-500 bg-transparent" />
                          Inactive (no key)
                        </span>
                      )}
                      {feed.status === 'unavailable' && (
                        <span className="inline-flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 text-slate-400 text-[11px] px-2 py-0.5 rounded-full">
                          <span className="w-1.5 h-1.5 rounded-full border border-slate-500 bg-transparent" />
                          Unavailable
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        </div>

        {/* ── Market Intelligence (GDI / disruption / commodities) ────────────── */}
        <div className="grid grid-cols-5 gap-4 mb-6">
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.55, duration: 0.5 }}
            className="col-span-5 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
            aria-live="polite"
          >
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-white font-semibold text-sm">Market Intelligence</h3>
                {/* No polling here — this section is fetched once, on page load. */}
                <p className="text-slate-500 text-xs mt-0.5">Global Disruption Index via SupplyMaven &middot; fetched on page load</p>
              </div>
              {!marketLoading && marketSummary && (
                marketSummary.gdi.available ? (
                  <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[11px] px-2 py-0.5 rounded-full">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400 motion-safe:animate-pulse" />
                    Live
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 text-slate-400 text-[11px] px-2 py-0.5 rounded-full">
                    <span className="w-1.5 h-1.5 rounded-full border border-slate-500 bg-transparent" />
                    Inactive (no key)
                  </span>
                )
              )}
            </div>

            {marketLoading && (
              <div className="h-24 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            )}

            {!marketLoading && marketError && (
              <DataUnavailable height="h-24" />
            )}

            {!marketLoading && !marketError && marketSummary && !marketSummary.gdi.available && (
              <div className="bg-slate-900/40 border border-slate-700/60 border-dashed rounded-lg p-4 text-sm text-slate-400">
                <p>
                  <span className="text-slate-300 font-medium">SUPPLYMAVEN_API_KEY</span> is not configured, so the
                  Global Disruption Index, live disruption alerts, and commodity prices below are inactive — no
                  placeholder numbers are shown in their place.
                </p>
                {marketStatus?.supplymaven?.register_url && (
                  <a
                    href={marketStatus.supplymaven.register_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-blue-400 hover:underline text-xs mt-2"
                  >
                    Get a SupplyMaven key <ExternalLink className="w-3 h-3" />
                  </a>
                )}
                <p className="text-xs text-slate-600 mt-2">
                  The moment a key is added, real GDI scores, alerts and commodity prices appear here — no code changes needed.
                </p>
              </div>
            )}

            {!marketLoading && marketSummary && marketSummary.gdi.available && (
              <div className="space-y-4">
                {/* Stat strip */}
                <div className="grid grid-cols-4 gap-3">
                  <div className="bg-slate-900/50 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-slate-500 text-[10px] uppercase tracking-wider">GDI Score</span>
                      <button
                        onClick={refreshGdi}
                        disabled={gdiRefreshing}
                        title="Refresh just the GDI score"
                        className="text-slate-600 hover:text-slate-300 disabled:opacity-40 transition-colors"
                      >
                        <RefreshCw className={`w-3 h-3 ${gdiRefreshing ? 'animate-spin' : ''}`} />
                      </button>
                    </div>
                    <div className="text-2xl font-bold tabular-nums" style={{ color: gdiColor(marketSummary.gdi.gdi_score) }}>
                      {marketSummary.gdi.gdi_score?.toFixed(1) ?? '—'}
                    </div>
                  </div>
                  <div className="bg-slate-900/50 rounded-lg p-3">
                    <div className="text-slate-500 text-[10px] uppercase tracking-wider mb-1">Trend</div>
                    <div className="text-sm font-semibold text-white flex items-center gap-1.5 mt-1.5">
                      {marketSummary.gdi.trend === 'up' && <TrendingUp className="w-4 h-4 text-red-400" />}
                      {marketSummary.gdi.trend === 'down' && <TrendingDown className="w-4 h-4 text-green-400" />}
                      {(!marketSummary.gdi.trend || marketSummary.gdi.trend === 'stable') && <Minus className="w-4 h-4 text-slate-400" />}
                      {marketSummary.gdi.trend ?? 'stable'}
                    </div>
                  </div>
                  <div className="bg-slate-900/50 rounded-lg p-3">
                    <div className="text-slate-500 text-[10px] uppercase tracking-wider mb-1">Disruption Alerts</div>
                    <div className="text-2xl font-bold tabular-nums text-white">
                      {marketSummary.alerts_count}
                      {marketSummary.critical_alerts > 0 && (
                        <span className="text-sm text-red-400 ml-1.5">({marketSummary.critical_alerts} critical)</span>
                      )}
                    </div>
                  </div>
                  <div className="bg-slate-900/50 rounded-lg p-3">
                    <div className="text-slate-500 text-[10px] uppercase tracking-wider mb-1">Tariff Multiplier</div>
                    <div className="text-2xl font-bold tabular-nums text-white">{marketSummary.tariff_multiplier.toFixed(2)}x</div>
                  </div>
                </div>

                {/* GDI pillar breakdown */}
                <div>
                  <div className="text-slate-500 text-[10px] uppercase tracking-wider mb-2">Pillar Breakdown</div>
                  <div className="space-y-1.5">
                    {([
                      ['Transportation', marketSummary.gdi.transportation],
                      ['Energy', marketSummary.gdi.energy],
                      ['Materials', marketSummary.gdi.materials],
                      ['Macro', marketSummary.gdi.macro],
                    ] as const).map(([label, value]) => (
                      <div key={label} className="flex items-center gap-2">
                        <span className="text-xs text-slate-400 w-28 shrink-0">{label}</span>
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden bg-slate-900/60 ring-1 ring-slate-700/50">
                          <div
                            className="h-full transition-all"
                            style={{ width: `${Math.min(100, value ?? 0)}%`, background: gdiColor(value) }}
                          />
                        </div>
                        <span className="text-xs text-slate-300 tabular-nums w-10 text-right">{value?.toFixed(0) ?? '—'}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Alerts list */}
                {marketAlerts && marketAlerts.alerts.length > 0 && (
                  <div>
                    <button
                      onClick={() => setAlertsExpanded((v) => !v)}
                      className="text-xs text-slate-400 hover:text-white transition-colors mb-2"
                    >
                      {alertsExpanded ? 'Hide' : 'View'} {marketAlerts.alerts.length} disruption alert{marketAlerts.alerts.length === 1 ? '' : 's'} {alertsExpanded ? '▲' : '▼'}
                    </button>
                    {alertsExpanded && (
                      <div className="space-y-1.5 max-h-48 overflow-y-auto">
                        {marketAlerts.alerts.map((a, i) => (
                          <div key={i} className="flex items-center justify-between bg-slate-900/50 rounded-lg px-3 py-2 text-xs">
                            <div className="min-w-0 flex-1">
                              <span className="text-slate-200 font-medium truncate">{a.title}</span>
                              {a.region && <span className="text-slate-500 ml-2">{a.region}</span>}
                            </div>
                            <span className={`shrink-0 ml-2 px-1.5 py-0.5 rounded ${
                              a.severity.toLowerCase() === 'critical' ? 'bg-red-500/20 text-red-400' :
                              a.severity.toLowerCase() === 'high' ? 'bg-orange-500/20 text-orange-400' :
                              'bg-slate-700 text-slate-400'
                            }`}>
                              {a.severity}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Commodity prices — semiconductor-relevant first */}
                {marketCommodities && marketCommodities.prices.length > 0 && (
                  <div>
                    <div className="text-slate-500 text-[10px] uppercase tracking-wider mb-2">Commodity Prices</div>
                    <div className="flex flex-wrap gap-1.5">
                      {[...marketCommodities.prices]
                        .sort((a, b) => (a.relevance === 'direct' ? -1 : 1) - (b.relevance === 'direct' ? -1 : 1))
                        .slice(0, 10)
                        .map((c) => (
                          <span
                            key={c.name}
                            className={`text-[11px] px-2 py-1 rounded-full border ${
                              c.relevance === 'direct'
                                ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300'
                                : 'bg-slate-700/40 border-slate-600/40 text-slate-400'
                            }`}
                            title={c.relevance === 'direct' ? 'Directly relevant to semiconductor manufacturing' : 'Indirect relevance'}
                          >
                            {c.name} ${c.price.toFixed(2)}
                            {c.change_24h_pct != null && (
                              <span className={c.change_24h_pct >= 0 ? 'text-red-400' : 'text-green-400'}>
                                {' '}{c.change_24h_pct >= 0 ? '+' : ''}{c.change_24h_pct.toFixed(1)}%
                              </span>
                            )}
                          </span>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        </div>

        {/* ── Row 4: Navigation Cards ───────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {NAV.map((item, i) => (
            <motion.button
              key={item.path}
              onClick={() => navigate(item.path)}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 + i * 0.05, duration: 0.4 }}
              whileHover={{ scale: 1.02, y: -2 }}
              whileTap={{ scale: 0.98 }}
              className={`text-left bg-slate-800/60 rounded-xl p-4 border border-slate-700 cursor-pointer transition-colors duration-200 backdrop-blur-sm ${item.border}`}
            >
              <div className="flex items-start justify-between mb-2">
                <span className="text-2xl">{item.icon}</span>
                <span className="text-xs bg-slate-700/80 text-slate-400 px-2 py-0.5 rounded-full">{item.badge}</span>
              </div>
              <h3 className="text-white font-semibold text-sm mb-1">{item.title}</h3>
              <p className="text-slate-500 text-xs leading-relaxed">{item.desc}</p>
            </motion.button>
          ))}
        </div>

        {/* ── Footer: Capability Pills ─────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="flex flex-wrap gap-2"
        >
          {[
            'Multi-objective VRP (cost + time + CO₂)',
            dataError ? 'Real electronic components' : `${components.length} real electronic components`,
            'Monte Carlo ETA (n=1000)',
            dataError ? 'Real distributors worldwide' : `${distributors.length} real distributors worldwide`,
            'Digital twin what-if scenarios',
            'Real pricing — static 2024 snapshot (CC-BY-4.0)',
          ].map((cap) => (
            <span key={cap} className="text-xs bg-slate-800/60 border border-slate-700 text-slate-500 px-3 py-1 rounded-full">
              {cap}
            </span>
          ))}
        </motion.div>
      </div>
    </div>
  );
};
