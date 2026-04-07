import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, AreaChart, Area,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, ReferenceLine,
} from 'recharts';
import { useAuthStore } from '../store/authStore';
import { useCartStore } from '../store/cartStore';
import { materialsAPI, hubsAPI } from '../services/api';

// ── Types ─────────────────────────────────────────────────────────────────────
interface Material {
  id: number;
  name: string;
  category: string;
  subcategory?: string;
  unit: string;
  current_price?: number;
  price_unit?: string;
  volatility_score: number;
  supply_risk_score: number;
}

interface Hub {
  id: number;
  name: string;
  city: string;
  state: string;
  hub_type?: string;
  specialization?: string;
  active_suppliers: number;
  risk_index: number;
}

interface PricePoint {
  date: string;
  price: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const CATEGORY_COLORS: Record<string, string> = {
  semiconductor: '#6366f1',
  rare_earth:    '#f59e0b',
  battery:       '#10b981',
  metal:         '#3b82f6',
  chemical:      '#ec4899',
  polymer:       '#8b5cf6',
};

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

// ── Mini Sparkline ────────────────────────────────────────────────────────────
function Sparkline({ data, color }: { data: PricePoint[]; color: string }) {
  if (!data.length) return <div className="h-10 flex items-center text-slate-600 text-xs">No data</div>;
  return (
    <ResponsiveContainer width="100%" height={40}>
      <AreaChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <defs>
          <linearGradient id={`sg-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.4} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="price"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#sg-${color.replace('#', '')})`}
          dot={false}
          isAnimationActive
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── Custom Scatter Tooltip ────────────────────────────────────────────────────
function RiskTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const rl = riskLabel((d.y + d.x) / 2);
  return (
    <div className="bg-slate-900 border border-slate-600 rounded-lg p-3 text-xs shadow-xl max-w-[180px]">
      <p className="text-white font-semibold mb-1 truncate">{d.name}</p>
      <p className="text-slate-400">Category: <span className="text-slate-200">{d.category}</span></p>
      <p className="text-slate-400">Volatility: <span className="text-yellow-400">{(d.x * 100).toFixed(0)}%</span></p>
      <p className="text-slate-400">Supply Risk: <span style={{ color: RISK_COLORS[rl] }}>{(d.y * 100).toFixed(0)}%</span></p>
      {d.price && <p className="text-slate-400">Price: <span className="text-green-400">${d.price.toFixed(2)}</span></p>}
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────
export const Dashboard = () => {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { items: cartItems } = useCartStore();

  const [materials, setMaterials] = useState<Material[]>([]);
  const [hubs, setHubs] = useState<Hub[]>([]);
  const [sparklines, setSparklines] = useState<Record<number, PricePoint[]>>({});
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [mRes, hRes] = await Promise.all([materialsAPI.list(), hubsAPI.list()]);
      const mats: Material[] = mRes.data;
      const hubList: Hub[] = hRes.data;
      setMaterials(mats);
      setHubs(hubList);

      // Fetch price history for top-5 most volatile materials
      const top5 = [...mats].sort((a, b) => b.volatility_score - a.volatility_score).slice(0, 5);
      const priceResults = await Promise.all(
        top5.map((m) => materialsAPI.priceHistory(m.id, 60).catch(() => ({ data: [] })))
      );
      const sparkMap: Record<number, PricePoint[]> = {};
      top5.forEach((m, i) => {
        sparkMap[m.id] = (priceResults[i].data as any[]).map((p: any) => ({
          date: p.date,
          price: p.price,
        }));
      });
      setSparklines(sparkMap);
    } catch {
      // silently fail — backend may be offline
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Derived data ────────────────────────────────────────────────────────────
  const highRisk = materials.filter((m) => m.supply_risk_score > 0.7).length;
  const avgRisk = materials.length
    ? (materials.reduce((s, m) => s + m.supply_risk_score, 0) / materials.length)
    : 0;
  const avgVolatility = materials.length
    ? (materials.reduce((s, m) => s + m.volatility_score, 0) / materials.length)
    : 0;

  // Risk matrix data for scatter chart
  const riskMatrix = materials.map((m) => ({
    x: parseFloat(m.volatility_score.toFixed(3)),
    y: parseFloat(m.supply_risk_score.toFixed(3)),
    z: m.current_price ? Math.log(m.current_price + 1) * 30 + 20 : 30,
    name: m.name,
    category: m.category,
    price: m.current_price,
  }));

  // Category distribution
  const catCounts = materials.reduce<Record<string, number>>((acc, m) => {
    acc[m.category] = (acc[m.category] || 0) + 1;
    return acc;
  }, {});
  const categoryData = Object.entries(catCounts).map(([name, value]) => ({ name, value }));

  // Category risk radar
  const catRisk = Object.entries(
    materials.reduce<Record<string, { risk: number; vol: number; count: number }>>((acc, m) => {
      if (!acc[m.category]) acc[m.category] = { risk: 0, vol: 0, count: 0 };
      acc[m.category].risk += m.supply_risk_score;
      acc[m.category].vol += m.volatility_score;
      acc[m.category].count += 1;
      return acc;
    }, {})
  ).map(([cat, d]) => ({
    category: cat.replace('_', ' '),
    'Supply Risk': parseFloat(((d.risk / d.count) * 100).toFixed(1)),
    'Volatility': parseFloat(((d.vol / d.count) * 100).toFixed(1)),
  }));

  // Top 5 volatile materials
  const top5Volatile = [...materials]
    .sort((a, b) => b.volatility_score - a.volatility_score)
    .slice(0, 5);

  // Hub risk distribution
  const hubRiskBins = [
    { label: 'Low (<0.3)', count: hubs.filter((h) => h.risk_index < 0.3).length, fill: '#10b981' },
    { label: 'Med (0.3–0.6)', count: hubs.filter((h) => h.risk_index >= 0.3 && h.risk_index < 0.6).length, fill: '#f59e0b' },
    { label: 'High (>0.6)', count: hubs.filter((h) => h.risk_index >= 0.6).length, fill: '#ef4444' },
  ];

  const NAV = [
    { title: 'Interactive Map', desc: '25 US production hubs, supplier arcs', icon: '🗺️', path: '/map', border: 'hover:border-blue-500 hover:bg-blue-500/5', badge: `${hubs.length} hubs` },
    { title: 'Material Scheduler', desc: 'Price forecasts, buy windows, rankings', icon: '📊', path: '/scheduler', border: 'hover:border-green-500 hover:bg-green-500/5', badge: `${materials.length} materials` },
    { title: 'Procurement Cart', desc: 'Build orders across suppliers', icon: '🛒', path: '/cart', border: 'hover:border-purple-500 hover:bg-purple-500/5', badge: cartItems.length > 0 ? `${cartItems.length} items` : 'Empty' },
    { title: 'Route Optimization', desc: 'OR-Tools VRP, Pareto frontier', icon: '🚀', path: '/checkout', border: 'hover:border-orange-500 hover:bg-orange-500/5', badge: 'VRP Solver' },
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
              Live Data
            </span>
          </div>
        </motion.div>

        {/* ── KPI Strip ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <KpiCard delay={0}    title="Materials"       value={loading ? '…' : materials.length}  sub="in procurement catalog"       accent="border-slate-700" />
          <KpiCard delay={0.05} title="Production Hubs" value={loading ? '…' : hubs.length}       sub="US facilities tracked"        accent="border-blue-500/30" />
          <KpiCard delay={0.1}  title="Avg Supply Risk" value={loading ? '…' : `${(avgRisk * 100).toFixed(0)}%`} sub={`${(avgVolatility * 100).toFixed(0)}% avg price volatility`} accent={avgRisk > 0.6 ? 'border-red-500/40' : avgRisk > 0.4 ? 'border-yellow-500/30' : 'border-green-500/30'} />
          <KpiCard delay={0.15} title="High-Risk Items"  value={loading ? '…' : highRisk}          sub="supply risk score > 70%"       accent="border-red-500/30" />
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
                <h3 className="text-white font-semibold text-sm">Risk Intelligence Matrix</h3>
                <p className="text-slate-500 text-xs mt-0.5">Volatility vs Supply Risk · bubble size = price magnitude</p>
              </div>
              <div className="flex gap-3 text-xs">
                {Object.entries(CATEGORY_COLORS).map(([cat, col]) => (
                  <span key={cat} className="flex items-center gap-1 text-slate-400">
                    <span className="w-2 h-2 rounded-full" style={{ background: col }} />
                    {cat.replace('_', ' ')}
                  </span>
                ))}
              </div>
            </div>
            {loading ? (
              <div className="h-52 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    type="number" dataKey="x" name="Volatility"
                    domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                    tick={{ fill: '#64748b', fontSize: 10 }} label={{ value: 'Price Volatility', position: 'insideBottom', offset: -8, fill: '#475569', fontSize: 10 }}
                  />
                  <YAxis
                    type="number" dataKey="y" name="Supply Risk"
                    domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                    tick={{ fill: '#64748b', fontSize: 10 }} label={{ value: 'Supply Risk', angle: -90, position: 'insideLeft', offset: 12, fill: '#475569', fontSize: 10 }}
                  />
                  <ZAxis type="number" dataKey="z" range={[20, 200]} />
                  <Tooltip content={<RiskTooltip />} cursor={{ stroke: '#334155', strokeDasharray: '4 4' }} />
                  {/* Quadrant reference lines */}
                  <ReferenceLine x={0.5} stroke="#334155" strokeDasharray="4 4" />
                  <ReferenceLine y={0.5} stroke="#334155" strokeDasharray="4 4" />
                  {Object.entries(CATEGORY_COLORS).map(([cat, color]) => (
                    <Scatter
                      key={cat}
                      name={cat}
                      data={riskMatrix.filter((d) => d.category === cat)}
                      fill={color}
                      fillOpacity={0.75}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            )}
            {/* Quadrant labels */}
            {!loading && (
              <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-slate-600">
                <span className="text-left pl-8">◄ Low Vol · Low Risk (Safe)</span>
                <span className="text-right pr-4">High Vol · High Risk (Critical) ►</span>
              </div>
            )}
          </motion.div>

          {/* Category Donut + Hub Risk */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.25, duration: 0.5 }}
            className="col-span-2 flex flex-col gap-4"
          >
            {/* Donut */}
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 flex-1 backdrop-blur-sm">
              <h3 className="text-white font-semibold text-sm mb-1">Category Breakdown</h3>
              <p className="text-slate-500 text-xs mb-3">{materials.length} materials across {categoryData.length} categories</p>
              {loading ? (
                <div className="h-32 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
              ) : (
                <div className="flex items-center gap-3">
                  <ResponsiveContainer width="60%" height={120}>
                    <PieChart>
                      <Pie data={categoryData} cx="50%" cy="50%" innerRadius={32} outerRadius={52} dataKey="value" strokeWidth={0}>
                        {categoryData.map((entry) => (
                          <Cell key={entry.name} fill={CATEGORY_COLORS[entry.name] ?? '#64748b'} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
                        formatter={(v: any, n: any) => [v, n]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex flex-col gap-1 flex-1">
                    {categoryData.sort((a, b) => b.value - a.value).map((d) => (
                      <div key={d.name} className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-1.5 text-slate-400">
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: CATEGORY_COLORS[d.name] ?? '#64748b' }} />
                          {d.name.replace('_', ' ')}
                        </span>
                        <span className="text-slate-300 tabular-nums">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Hub Risk Bars */}
            <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm">
              <h3 className="text-white font-semibold text-sm mb-1">Hub Risk Distribution</h3>
              <p className="text-slate-500 text-xs mb-3">{hubs.length} production facilities</p>
              {loading ? (
                <div className="h-16 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
              ) : (
                <ResponsiveContainer width="100%" height={60}>
                  <BarChart data={hubRiskBins} margin={{ top: 0, right: 0, left: -16, bottom: 0 }}>
                    <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {hubRiskBins.map((b, i) => <Cell key={i} fill={b.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </motion.div>
        </div>

        {/* ── Row 3: Market Pulse (top volatile) + Radar ───────────────────── */}
        <div className="grid grid-cols-5 gap-4 mb-6">

          {/* Top Volatile Materials with Sparklines */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5 }}
            className="col-span-3 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
          >
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-white font-semibold text-sm">Market Pulse</h3>
                <p className="text-slate-500 text-xs mt-0.5">Top 5 highest-volatility materials · 60-day price history</p>
              </div>
              <span className="text-xs text-slate-500">sorted by volatility score ↓</span>
            </div>
            {loading ? (
              <div className="h-40 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            ) : (
              <div className="space-y-3">
                {top5Volatile.map((m, i) => {
                  const rl = riskLabel(m.supply_risk_score);
                  const sdata = sparklines[m.id] ?? [];
                  const catColor = CATEGORY_COLORS[m.category] ?? '#64748b';
                  const pct = (m.volatility_score * 100).toFixed(0);
                  const riskColor = RISK_COLORS[rl];
                  // Price trend from sparkline
                  const trend = sdata.length >= 2
                    ? sdata[sdata.length - 1].price - sdata[0].price
                    : 0;
                  return (
                    <motion.div
                      key={m.id}
                      initial={{ opacity: 0, x: -12 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.35 + i * 0.06 }}
                      className="flex items-center gap-4 bg-slate-900/50 rounded-lg px-4 py-2.5"
                    >
                      {/* Rank */}
                      <span className="text-slate-600 text-xs w-4 flex-shrink-0">#{i + 1}</span>
                      {/* Name + category */}
                      <div className="w-44 flex-shrink-0">
                        <p className="text-white text-xs font-medium truncate">{m.name}</p>
                        <span
                          className="text-xs px-1.5 py-0.5 rounded text-white/80 font-medium"
                          style={{ background: catColor + '33', color: catColor }}
                        >
                          {m.category.replace('_', ' ')}
                        </span>
                      </div>
                      {/* Sparkline */}
                      <div className="flex-1 min-w-0">
                        <Sparkline data={sdata} color={catColor} />
                      </div>
                      {/* Scores */}
                      <div className="flex gap-4 flex-shrink-0 text-xs text-right">
                        <div>
                          <p className="text-slate-500">Volatility</p>
                          <p className="text-yellow-400 font-semibold">{pct}%</p>
                        </div>
                        <div>
                          <p className="text-slate-500">Risk</p>
                          <p className="font-semibold" style={{ color: riskColor }}>
                            {(m.supply_risk_score * 100).toFixed(0)}%
                          </p>
                        </div>
                        {sdata.length > 1 && (
                          <div>
                            <p className="text-slate-500">60d Δ</p>
                            <p className={trend >= 0 ? 'text-red-400' : 'text-green-400'}>
                              {trend >= 0 ? '+' : ''}{trend.toFixed(2)}
                            </p>
                          </div>
                        )}
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </motion.div>

          {/* Risk Radar by Category */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.35, duration: 0.5 }}
            className="col-span-2 bg-slate-800/60 border border-slate-700 rounded-xl p-5 backdrop-blur-sm"
          >
            <h3 className="text-white font-semibold text-sm mb-1">Risk Radar</h3>
            <p className="text-slate-500 text-xs mb-3">Avg risk & volatility per category</p>
            {loading ? (
              <div className="h-48 flex items-center justify-center text-slate-600 text-sm">Loading…</div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <RadarChart data={catRisk} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
                  <PolarGrid stroke="#1e293b" />
                  <PolarAngleAxis dataKey="category" tick={{ fill: '#64748b', fontSize: 9 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: '#334155', fontSize: 8 }} />
                  <Radar name="Supply Risk" dataKey="Supply Risk" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} strokeWidth={1.5} />
                  <Radar name="Volatility" dataKey="Volatility" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.15} strokeWidth={1.5} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            )}
            <div className="flex gap-4 justify-center text-xs text-slate-500 mt-1">
              <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-red-400 inline-block" /> Supply Risk</span>
              <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-yellow-400 inline-block" /> Volatility</span>
            </div>
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
            'Prophet ML price forecasting',
            'Monte Carlo ETA (n=1000)',
            'ESG carbon tracking',
            'Digital twin what-if scenarios',
            'Composite supplier risk scoring',
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
