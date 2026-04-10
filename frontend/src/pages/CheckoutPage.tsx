import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {
  DollarSign, Zap, Leaf, Scale, Check, TrendingDown, TrendingUp,
  Clock, Truck, ArrowRight, MapPin, ChevronDown, ChevronUp, Star,
} from 'lucide-react';
import { optimizeAPI } from '../services/api';
import { useCartStore } from '../store/cartStore';
import { useOptimizeStore } from '../store/optimizeStore';

const STRATEGY_META: Record<string, { icon: typeof DollarSign; color: string; gradient: string }> = {
  cheapest: { icon: DollarSign, color: 'text-green-400', gradient: 'from-green-500/20 to-green-600/5' },
  fastest:  { icon: Zap,        color: 'text-blue-400',  gradient: 'from-blue-500/20 to-blue-600/5' },
  greenest: { icon: Leaf,       color: 'text-emerald-400', gradient: 'from-emerald-500/20 to-emerald-600/5' },
  balanced: { icon: Scale,      color: 'text-purple-400', gradient: 'from-purple-500/20 to-purple-600/5' },
};

function RankBadge({ rank, total }: { rank: number; total: number }) {
  if (rank === 1) return <span className="text-[10px] font-bold text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded">BEST</span>;
  if (rank === total) return <span className="text-[10px] font-medium text-red-400/70 bg-red-400/10 px-1.5 py-0.5 rounded">{rank}th</span>;
  return <span className="text-[10px] font-medium text-slate-400 bg-slate-600/30 px-1.5 py-0.5 rounded">{rank}{rank === 2 ? 'nd' : 'rd'}</span>;
}

function DeltaIndicator({ value, baseline, unit, invert = false }: { value: number; baseline: number; unit: string; invert?: boolean }) {
  if (baseline === 0) return null;
  const pct = ((value - baseline) / baseline) * 100;
  const isGood = invert ? pct > 0 : pct < 0;
  if (Math.abs(pct) < 0.5) return <span className="text-[10px] text-slate-500">same</span>;
  return (
    <span className={`text-[10px] font-medium flex items-center gap-0.5 ${isGood ? 'text-green-400' : 'text-red-400'}`}>
      {isGood ? <TrendingDown className="w-2.5 h-2.5" /> : <TrendingUp className="w-2.5 h-2.5" />}
      {pct > 0 ? '+' : ''}{pct.toFixed(1)}% {unit}
    </span>
  );
}

function MetricRow({ label, value, rank, total, delta }: {
  label: string; value: string; rank: number; total: number; delta?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-slate-400">{label}</span>
      <div className="flex items-center gap-2">
        {delta}
        <span className="text-sm font-semibold text-white">{value}</span>
        <RankBadge rank={rank} total={total} />
      </div>
    </div>
  );
}

export default function CheckoutPage() {
  const navigate = useNavigate();
  const { items, clearCart, fetchCart } = useCartStore();
  const { multiResult, selectedId, setMultiResult, setSelectedId } = useOptimizeStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cartLoading, setCartLoading] = useState(true);
  const [expandedCard, setExpandedCard] = useState<string | null>(null);

  // Fetch cart on mount
  useEffect(() => {
    fetchCart().finally(() => setCartLoading(false));
  }, [fetchCart]);

  // Auto-run optimization after cart loads
  useEffect(() => {
    if (cartLoading || items.length === 0 || multiResult) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    optimizeAPI.vrp()
      .then((res) => {
        if (!cancelled) setMultiResult(res.data);
      })
      .catch((err) => {
        if (!cancelled) {
          const detail = err.response?.data?.detail;
          const message = Array.isArray(detail)
            ? detail.map((d: { msg: string }) => d.msg).join(', ')
            : typeof detail === 'string'
            ? detail
            : 'Optimization failed';
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [items.length, cartLoading]);

  const alternatives = multiResult?.alternatives ?? [];
  const selected = alternatives.find((a) => a.id === selectedId) ?? null;
  const total = alternatives.length;

  // Find baseline (balanced) for delta comparisons
  const baseline = alternatives.find((a) => a.id === 'balanced');

  // Monte Carlo histogram for selected route
  const histogramData = useMemo(() => {
    if (!selected?.monte_carlo_samples) return [];
    const samples = selected.monte_carlo_samples;
    const min = Math.min(...samples);
    const max = Math.max(...samples);
    const bins = 20;
    const binSize = (max - min) / bins;
    const counts = Array(bins).fill(0);
    samples.forEach((s) => {
      const idx = Math.min(Math.floor((s - min) / binSize), bins - 1);
      counts[idx]++;
    });
    return counts.map((count, i) => ({
      day: (min + i * binSize + binSize / 2).toFixed(1),
      count,
    }));
  }, [selected]);

  if (cartLoading) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
      </div>
    );
  }

  if (items.length === 0 && !multiResult) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-center">
          <div className="text-5xl mb-4">
            <Truck className="w-12 h-12 text-slate-600 mx-auto" />
          </div>
          <div className="text-lg font-medium text-slate-400">No items in cart</div>
          <button onClick={() => navigate('/cart')} className="mt-4 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors">
            Go to Cart
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-white">Route Optimization</h1>
            <p className="text-sm text-slate-400 mt-0.5">Compare strategies and select the best route for your supply chain</p>
          </div>
          <button onClick={() => navigate('/cart')} className="text-xs text-slate-400 hover:text-white transition-colors">
            ← Back to Cart
          </button>
        </div>

        {/* Loading state */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-24">
            <div className="relative">
              <div className="w-16 h-16 rounded-full border-2 border-slate-700" />
              <div className="absolute inset-0 w-16 h-16 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
            </div>
            <p className="text-blue-400 text-sm mt-4 font-medium">Running multi-objective VRP solver...</p>
            <p className="text-slate-500 text-xs mt-1">Generating 4 route strategies with Monte Carlo simulation</p>
          </div>
        )}

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-sm text-red-300">
            {error}
            <button onClick={() => window.location.reload()} className="ml-3 underline hover:text-white">Retry</button>
          </div>
        )}

        {/* Route alternative cards */}
        {alternatives.length > 0 && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
              {alternatives.map((alt) => {
                const meta = STRATEGY_META[alt.id] || STRATEGY_META.balanced;
                const Icon = meta.icon;
                const isSelected = selectedId === alt.id;
                const isRecommended = multiResult?.recommended_id === alt.id;
                const isExpanded = expandedCard === alt.id;

                return (
                  <div
                    key={alt.id}
                    className={`relative rounded-xl border transition-all cursor-pointer ${
                      isSelected
                        ? 'border-blue-500 bg-gradient-to-b from-blue-500/10 to-slate-800 shadow-lg shadow-blue-500/10'
                        : 'border-slate-700 bg-slate-800 hover:border-slate-600'
                    }`}
                    onClick={() => setSelectedId(alt.id)}
                  >
                    {/* Recommended badge */}
                    {isRecommended && (
                      <div className="absolute -top-2.5 left-4 flex items-center gap-1 bg-purple-600 text-white text-[10px] font-semibold px-2 py-0.5 rounded-full">
                        <Star className="w-2.5 h-2.5" /> RECOMMENDED
                      </div>
                    )}

                    <div className="p-4">
                      {/* Strategy header */}
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <div className={`p-1.5 rounded-lg bg-gradient-to-br ${meta.gradient}`}>
                            <Icon className={`w-4 h-4 ${meta.color}`} />
                          </div>
                          <div>
                            <div className="text-sm font-semibold text-white">{alt.label}</div>
                            <div className="text-[10px] text-slate-500">{alt.description}</div>
                          </div>
                        </div>
                        {isSelected && <Check className="w-4 h-4 text-blue-400" />}
                      </div>

                      {/* Key metrics */}
                      <div className="space-y-0.5 border-t border-slate-700/50 pt-3">
                        <MetricRow
                          label="Total Cost"
                          value={`$${alt.total_cost_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                          rank={alt.cost_rank}
                          total={total}
                          delta={baseline && alt.id !== 'balanced' ? <DeltaIndicator value={alt.total_cost_usd} baseline={baseline.total_cost_usd} unit="cost" /> : undefined}
                        />
                        <MetricRow
                          label="Median ETA"
                          value={`${alt.eta_p50}d`}
                          rank={alt.speed_rank}
                          total={total}
                          delta={baseline && alt.id !== 'balanced' ? <DeltaIndicator value={alt.eta_p50} baseline={baseline.eta_p50} unit="time" /> : undefined}
                        />
                        <MetricRow
                          label="CO2 Emissions"
                          value={`${alt.total_co2e_kg.toFixed(1)} kg`}
                          rank={alt.carbon_rank}
                          total={total}
                          delta={baseline && alt.id !== 'balanced' ? <DeltaIndicator value={alt.total_co2e_kg} baseline={baseline.total_co2e_kg} unit="CO2" /> : undefined}
                        />
                        <MetricRow
                          label="Distance"
                          value={`${alt.total_distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} km`}
                          rank={alt.distance_rank}
                          total={total}
                        />
                      </div>

                      {/* Expand toggle */}
                      <button
                        onClick={(e) => { e.stopPropagation(); setExpandedCard(isExpanded ? null : alt.id); }}
                        className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 mt-2 transition-colors"
                      >
                        {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        {isExpanded ? 'Less detail' : 'More detail'}
                      </button>

                      {/* Expanded details */}
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-slate-700/50 space-y-2 text-xs">
                          <div className="flex justify-between text-slate-400">
                            <span>Transport Cost</span>
                            <span className="text-white">${alt.total_transport_cost_usd.toFixed(0)}</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Component Cost</span>
                            <span className="text-white">${alt.total_component_cost_usd.toFixed(0)}</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Int'l Stops</span>
                            <span className="text-white">{alt.international_stops}</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Best Case (P10)</span>
                            <span className="text-green-400">{alt.eta_p10}d</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Worst Case (P90)</span>
                            <span className="text-red-400">{alt.eta_p90}d</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Stops</span>
                            <span className="text-white">{alt.stop_count}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Selected route detail section */}
            {selected && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                {/* Route stops */}
                <div className="lg:col-span-2 bg-slate-800 border border-slate-700 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <MapPin className="w-4 h-4 text-blue-400" />
                      {selected.label} Route — {selected.stop_count} Stops
                    </h3>
                    <button
                      onClick={() => navigate('/map')}
                      className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                    >
                      View on Map <ArrowRight className="w-3 h-3" />
                    </button>
                  </div>

                  <div className="space-y-1">
                    {/* Depot start */}
                    <div className="flex items-center gap-3 py-2 px-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                      <div className="w-6 h-6 rounded-full bg-blue-600 text-white text-[10px] flex items-center justify-center shrink-0 font-bold">
                        HQ
                      </div>
                      <span className="text-xs text-blue-300 font-medium">Your Factory (Depot)</span>
                    </div>

                    {selected.route.map((stop, i) => (
                      <div key={stop.distributor_id} className="flex items-start gap-3 py-2 px-3 rounded-lg hover:bg-slate-700/30 transition-colors">
                        <div className="flex flex-col items-center">
                          <div className="w-6 h-6 rounded-full bg-slate-700 text-white text-[10px] flex items-center justify-center shrink-0 font-bold border border-slate-600">
                            {stop.order}
                          </div>
                          {i < selected.route.length - 1 && (
                            <div className="w-px h-4 bg-slate-700 mt-1" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <div className="truncate">
                              <span className="text-sm text-white font-medium">{stop.distributor_name}</span>
                              <span className="text-xs text-slate-500 ml-2">
                                {stop.city}, {stop.state}
                                {stop.country && stop.country !== 'USA' && (
                                  <span className="text-slate-600"> ({stop.country})</span>
                                )}
                              </span>
                            </div>
                            <div className="flex items-center gap-3 text-xs text-slate-400 shrink-0 ml-3">
                              <span>{stop.distance_km.toFixed(0)} km</span>
                              <span className="text-blue-300">${stop.leg_cost_usd.toFixed(0)}</span>
                              <span className="text-emerald-300">{stop.leg_co2e_kg.toFixed(2)} kg</span>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {stop.components.map((c, j) => (
                              <span key={j} className="text-[10px] bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded">
                                {c}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    ))}

                    {/* Return */}
                    <div className="flex items-center gap-3 py-2 px-3 rounded-lg bg-slate-700/20 border border-slate-700/50">
                      <div className="w-6 h-6 rounded-full bg-slate-700 text-slate-400 text-[10px] flex items-center justify-center shrink-0 font-bold border border-slate-600">
                        <ArrowRight className="w-3 h-3" />
                      </div>
                      <span className="text-xs text-slate-500">Return to Depot</span>
                    </div>
                  </div>
                </div>

                {/* Side panel: Monte Carlo + actions */}
                <div className="space-y-4">
                  {/* ETA distribution */}
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
                      <Clock className="w-4 h-4 text-blue-400" />
                      Delivery Time Distribution
                    </h3>
                    <p className="text-[10px] text-slate-500 mb-3">1000 Monte Carlo simulations</p>

                    <div className="grid grid-cols-3 gap-2 mb-3">
                      {[
                        { label: 'Best', value: selected.eta_p10, color: 'text-green-400' },
                        { label: 'Median', value: selected.eta_p50, color: 'text-blue-400' },
                        { label: 'Worst', value: selected.eta_p90, color: 'text-red-400' },
                      ].map(({ label, value, color }) => (
                        <div key={label} className="bg-slate-700/40 rounded-lg p-2 text-center">
                          <div className="text-[10px] text-slate-500">{label}</div>
                          <div className={`text-lg font-bold ${color}`}>{value}d</div>
                        </div>
                      ))}
                    </div>

                    <ResponsiveContainer width="100%" height={120}>
                      <BarChart data={histogramData} margin={{ top: 0, right: 5, bottom: 0, left: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="day" tick={{ fill: '#94a3b8', fontSize: 9 }} />
                        <YAxis tick={false} axisLine={false} width={0} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
                          formatter={(v) => [Number(v), 'Simulations']}
                          labelFormatter={(l) => `~${l} days`}
                        />
                        <Bar dataKey="count" radius={[2, 2, 0, 0]} fill="#3b82f6" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Comparison summary */}
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-3">Strategy Comparison</h3>
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr className="text-slate-500">
                          <th className="text-left pb-2 font-medium">Strategy</th>
                          <th className="text-right pb-2 font-medium">Cost</th>
                          <th className="text-right pb-2 font-medium">ETA</th>
                          <th className="text-right pb-2 font-medium">CO2</th>
                        </tr>
                      </thead>
                      <tbody>
                        {alternatives.map((alt) => (
                          <tr
                            key={alt.id}
                            className={`border-t border-slate-700/50 cursor-pointer hover:bg-slate-700/20 ${
                              alt.id === selectedId ? 'bg-blue-500/5' : ''
                            }`}
                            onClick={() => setSelectedId(alt.id)}
                          >
                            <td className="py-1.5 text-slate-300 font-medium">
                              {alt.id === selectedId && <span className="text-blue-400 mr-1">●</span>}
                              {alt.label}
                            </td>
                            <td className={`py-1.5 text-right ${alt.cost_rank === 1 ? 'text-green-400 font-bold' : 'text-slate-400'}`}>
                              ${alt.total_cost_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                            </td>
                            <td className={`py-1.5 text-right ${alt.speed_rank === 1 ? 'text-green-400 font-bold' : 'text-slate-400'}`}>
                              {alt.eta_p50}d
                            </td>
                            <td className={`py-1.5 text-right ${alt.carbon_rank === 1 ? 'text-green-400 font-bold' : 'text-slate-400'}`}>
                              {alt.total_co2e_kg.toFixed(1)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Actions */}
                  <div className="space-y-2">
                    <button
                      onClick={() => navigate('/map')}
                      className="w-full bg-blue-600 hover:bg-blue-500 text-white py-2.5 rounded-lg font-semibold text-sm transition-colors flex items-center justify-center gap-2"
                    >
                      <MapPin className="w-4 h-4" /> View Route on Map
                    </button>
                    <button
                      onClick={() => { clearCart(); navigate('/dashboard'); }}
                      className="w-full bg-green-600 hover:bg-green-500 text-white py-2.5 rounded-lg font-semibold text-sm transition-colors flex items-center justify-center gap-2"
                    >
                      <Check className="w-4 h-4" /> Confirm Order
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
