import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, ReferenceLine,
} from 'recharts';
import { useAuthStore } from '../store/authStore';
import { useCartStore } from '../store/cartStore';
import { componentsAPI, distributorsAPI, feedsAPI } from '../services/api';

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

// ── Constants ─────────────────────────────────────────────────────────────────
const RISK_COLORS = {
  low:    '#10b981',
  medium: '#f59e0b',
  high:   '#ef4444',
};

function riskLabel(score: number) {
  if (score < 0.4) return 'low';
  if (score < 0.7) return 'medium';
  return 'high';
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

  const loadData = useCallback(async () => {
    try {
      const [cRes, dRes] = await Promise.all([componentsAPI.list(), distributorsAPI.list()]);
      setComponents(cRes.data);
      setDistributors(dRes.data);
    } catch {
      // silently fail — backend may be offline
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Live Feeds status ────────────────────────────────────────────────────────
  const [feedStatus, setFeedStatus] = useState<Array<{
    name: string;
    fetched_at: string | null;
    status: 'live' | 'stale' | 'unavailable';
    value_summary: string | null;
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
    const interval = setInterval(fetchFeeds, 60_000);
    return () => clearInterval(interval);
  }, []);

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
  const highRisk = components.filter((c) => c.risk_score > 0.7).length;
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
    category: c.category.split(' ')[0],
    price: c.min_price,
    offers: c.num_offers,
  }));

  // Category distribution
  const catCounts = components.reduce<Record<string, number>>((acc, c) => {
    const cat = c.category.split(' ').slice(0, 2).join(' ');
    acc[cat] = (acc[cat] || 0) + 1;
    return acc;
  }, {});
  const categoryData = Object.entries(catCounts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([name, value]) => ({ name, value }));

  const CATEGORY_COLORS = ['#6366f1', '#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#8b5cf6', '#ef4444', '#06b6d4', '#f97316', '#14b8a6'];

  // Category risk radar
  const catRisk = Object.entries(
    components.reduce<Record<string, { risk: number; count: number }>>((acc, c) => {
      const cat = c.category.split(' ').slice(0, 2).join(' ');
      if (!acc[cat]) acc[cat] = { risk: 0, count: 0 };
      acc[cat].risk += c.risk_score;
      acc[cat].count += 1;
      return acc;
    }, {})
  )
    .sort(([, a], [, b]) => b.count - a.count)
    .slice(0, 8)
    .map(([cat, d]) => ({
      category: cat,
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

  const NAV = [
    { title: 'Distributor Map', desc: `${distributors.length} distributors worldwide`, icon: '🗺️', path: '/map', border: 'hover:border-blue-500 hover:bg-blue-500/5', badge: `${distributors.length} distributors` },
    { title: 'Component Browser', desc: 'Real pricing from 92 distributors', icon: '📊', path: '/scheduler', border: 'hover:border-green-500 hover:bg-green-500/5', badge: `${components.length} components` },
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
            <span className="inline-flex items-center gap-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-xs px-3 py-1.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              Real Data
            </span>
          </div>
        </motion.div>

        {/* ── KPI Strip ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <KpiCard delay={0}    title="Components"      value={loading ? '…' : components.length}    sub="from HuggingFace dataset"      accent="border-slate-700" />
          <KpiCard delay={0.05} title="Distributors"    value={loading ? '…' : distributors.length}  sub={`${domesticDists} domestic, ${distributors.length - domesticDists} int'l`} accent="border-blue-500/30" />
          <KpiCard delay={0.1}  title="Avg Supply Risk" value={loading ? '…' : `${(avgRisk * 100).toFixed(0)}%`} sub="across all components" accent={avgRisk > 0.6 ? 'border-red-500/40' : avgRisk > 0.4 ? 'border-yellow-500/30' : 'border-green-500/30'} />
          <KpiCard delay={0.15} title="High-Risk Items"  value={loading ? '…' : highRisk}            sub="risk score > 70%"              accent="border-red-500/30" />
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
            {!loading && (
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
              <p className="text-slate-500 text-xs mb-3">{components.length} components across {Object.keys(catCounts).length} categories</p>
              {loading ? (
                <div className="h-32 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
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
              <p className="text-slate-500 text-xs mb-3">{distributors.length} distributors</p>
              {loading ? (
                <div className="h-16 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
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
              <p className="text-slate-500 text-xs mt-0.5">External signals refreshed every 15 minutes</p>
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
                    title={feed.fetched_at ? `Last fetched: ${feed.fetched_at}` : undefined}
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
            '791 real electronic components',
            'Monte Carlo ETA (n=1000)',
            '92 real distributors worldwide',
            'Digital twin what-if scenarios',
            'Competitive pricing from Nexar/Octopart',
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
