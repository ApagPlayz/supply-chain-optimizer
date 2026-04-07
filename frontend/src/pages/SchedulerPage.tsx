import { useEffect, useState, useCallback } from 'react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Area, AreaChart
} from 'recharts';
import { materialsAPI } from '../services/api';
import { useCartStore } from '../store/cartStore';

interface Material {
  id: number;
  name: string;
  category: string;
  subcategory: string | null;
  unit: string;
  description: string | null;
  current_price: number | null;
  price_unit: string | null;
  volatility_score: number;
  supply_risk_score: number;
}

interface PricePoint {
  date: string;
  price: number;
  source: string | null;
}

interface ForecastPoint {
  forecast_date: string;
  predicted_price: number;
  lower_ci: number | null;
  upper_ci: number | null;
}

interface SupplierRec {
  id: number;
  name: string;
  city: string | null;
  state: string | null;
  lead_time_days: number;
  reliability_score: number;
  risk_score: number;
  price_competitiveness: number;
  composite_score: number;
  is_domestic: boolean;
}


function ScoreBar({ value, color = 'bg-blue-500' }: { value: number; color?: string }) {
  return (
    <div className="w-full bg-slate-700 rounded-full h-1.5">
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${value * 100}%` }} />
    </div>
  );
}

function riskColor(r: number) {
  if (r < 0.3) return 'text-green-400';
  if (r < 0.6) return 'text-yellow-400';
  return 'text-red-400';
}

function volColor(v: number) {
  if (v < 0.4) return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (v < 0.65) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  return 'bg-red-500/20 text-red-400 border-red-500/30';
}

export default function SchedulerPage() {
  const { addItem } = useCartStore();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCat, setSelectedCat] = useState('All');
  const [search, setSearch] = useState('');
  const [selectedMat, setSelectedMat] = useState<Material | null>(null);
  const [history, setHistory] = useState<PricePoint[]>([]);
  const [forecast, setForecast] = useState<ForecastPoint[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierRec[]>([]);
  const [qty, setQty] = useState(1);
  const [selectedSupplierId, setSelectedSupplierId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [addedMsg, setAddedMsg] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    Promise.all([
      materialsAPI.list(),
      materialsAPI.categories(),
    ]).then(([mRes, cRes]) => {
      setMaterials(mRes.data);
      setCategories(cRes.data);
      setLoading(false);
    });
  }, []);

  const selectMaterial = useCallback(async (mat: Material) => {
    setSelectedMat(mat);
    setSelectedSupplierId(null);
    setQty(1);
    setAddedMsg('');
    setDetailLoading(true);
    const [hRes, fRes, sRes] = await Promise.all([
      materialsAPI.priceHistory(mat.id, 90),
      materialsAPI.forecast(mat.id),
      materialsAPI.suppliers(mat.id),
    ]);
    setHistory(hRes.data);
    setForecast(fRes.data);
    setSuppliers(sRes.data);
    setDetailLoading(false);
  }, []);

  const handleAddToCart = async () => {
    if (!selectedMat || !selectedSupplierId) return;
    setAdding(true);
    try {
      await addItem({ material_id: selectedMat.id, supplier_id: selectedSupplierId, quantity: qty });
      setAddedMsg('Added to cart!');
      setTimeout(() => setAddedMsg(''), 2500);
    } finally {
      setAdding(false);
    }
  };

  // Filter + search
  const visible = materials.filter((m) => {
    const catOk = selectedCat === 'All' || m.category === selectedCat;
    const searchOk = !search || m.name.toLowerCase().includes(search.toLowerCase());
    return catOk && searchOk;
  });

  // Combine history + forecast for chart
  const chartData = [
    ...history.map((h) => ({
      date: new Date(h.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      price: h.price,
      type: 'history',
    })),
    ...forecast.slice(0, 30).map((f) => ({
      date: new Date(f.forecast_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      price: f.predicted_price,
      lower: f.lower_ci ?? undefined,
      upper: f.upper_ci ?? undefined,
      type: 'forecast',
    })),
  ];

  // Best buy window: find local min in next 30 forecast days
  const bestBuyDay = forecast.slice(0, 30).reduce<{ idx: number; price: number } | null>(
    (best, f, i) => (!best || f.predicted_price < best.price ? { idx: i, price: f.predicted_price } : best),
    null
  );

  return (
    <div className="flex h-full bg-slate-900 text-slate-100">
      {/* Left panel: material list */}
      <div className="w-72 border-r border-slate-700 flex flex-col">
        {/* Search + filter */}
        <div className="p-3 border-b border-slate-700 space-y-2">
          <input
            type="text"
            placeholder="Search materials…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
          />
          <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
            {['All', ...categories].map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCat(cat)}
                className={`text-xs px-2 py-0.5 rounded capitalize transition-colors ${
                  selectedCat === cat
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                {cat.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>

        {/* Material list */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="p-4 text-center text-slate-400 text-sm">Loading materials…</div>
          )}
          {visible.map((mat) => (
            <button
              key={mat.id}
              onClick={() => selectMaterial(mat)}
              className={`w-full text-left px-3 py-2.5 border-b border-slate-700/50 hover:bg-slate-700/40 transition-colors ${
                selectedMat?.id === mat.id ? 'bg-slate-700/60 border-l-2 border-l-blue-500' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-1">
                <div className="text-sm text-white font-medium leading-tight truncate">{mat.name}</div>
                {mat.current_price && (
                  <div className="text-xs text-slate-300 shrink-0">
                    {mat.price_unit?.split('/')[0] || '$'}{mat.current_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-slate-400 capitalize">{mat.category.replace('_', ' ')}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded border ${volColor(mat.volatility_score)}`}>
                  {mat.volatility_score < 0.4 ? 'Stable' : mat.volatility_score < 0.65 ? 'Volatile' : 'High Vol'}
                </span>
              </div>
            </button>
          ))}
          {!loading && visible.length === 0 && (
            <div className="p-4 text-center text-slate-500 text-sm">No materials found</div>
          )}
        </div>
        <div className="px-3 py-2 text-xs text-slate-500 border-t border-slate-700">
          {visible.length} of {materials.length} materials
        </div>
      </div>

      {/* Right panel: detail */}
      <div className="flex-1 overflow-y-auto p-5">
        {!selectedMat && (
          <div className="h-full flex items-center justify-center text-slate-500">
            <div className="text-center">
              <div className="text-4xl mb-3">⚙️</div>
              <div className="text-lg font-medium text-slate-400">Select a material</div>
              <div className="text-sm mt-1">Browse {materials.length} tech manufacturing materials</div>
            </div>
          </div>
        )}

        {selectedMat && (
          <div className="max-w-4xl space-y-5">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-xl font-bold text-white">{selectedMat.name}</h1>
                <p className="text-slate-400 text-sm mt-0.5 capitalize">
                  {selectedMat.category.replace('_', ' ')}
                  {selectedMat.subcategory ? ` › ${selectedMat.subcategory}` : ''}
                </p>
                {selectedMat.description && (
                  <p className="text-slate-400 text-sm mt-1">{selectedMat.description}</p>
                )}
              </div>
              {selectedMat.current_price && (
                <div className="text-right">
                  <div className="text-2xl font-bold text-white">
                    ${selectedMat.current_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-slate-400 text-xs">{selectedMat.price_unit}</div>
                </div>
              )}
            </div>

            {/* Risk metrics */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">Price Volatility</div>
                <div className={`text-sm font-semibold mb-1.5 ${volColor(selectedMat.volatility_score).split(' ')[1]}`}>
                  {(selectedMat.volatility_score * 100).toFixed(0)}%
                </div>
                <ScoreBar value={selectedMat.volatility_score} color="bg-yellow-500" />
              </div>
              <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">Supply Risk</div>
                <div className={`text-sm font-semibold mb-1.5 ${riskColor(selectedMat.supply_risk_score)}`}>
                  {(selectedMat.supply_risk_score * 100).toFixed(0)}%
                </div>
                <ScoreBar value={selectedMat.supply_risk_score} color="bg-red-500" />
              </div>
            </div>

            {/* Best Buy alert */}
            {bestBuyDay && forecast.length > 0 && (
              <div className="bg-green-900/30 border border-green-700/50 rounded-lg p-3 flex items-center gap-3">
                <div className="text-green-400 text-2xl">💡</div>
                <div>
                  <div className="text-green-300 font-medium text-sm">Best Buy Window</div>
                  <div className="text-slate-300 text-sm">
                    Lowest forecast price in 30 days:{' '}
                    <strong>${forecast[bestBuyDay.idx]?.predicted_price.toFixed(2)}</strong> on{' '}
                    {new Date(forecast[bestBuyDay.idx]?.forecast_date).toLocaleDateString('en-US', {
                      month: 'short', day: 'numeric'
                    })}
                    {' '}(day {bestBuyDay.idx + 1})
                  </div>
                </div>
              </div>
            )}

            {/* Price chart */}
            <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-white">90-Day Price History + 30-Day Forecast</h3>
                <div className="flex items-center gap-4 text-xs text-slate-400">
                  <span className="flex items-center gap-1"><span className="w-4 h-0.5 bg-blue-400 inline-block" /> History</span>
                  <span className="flex items-center gap-1"><span className="w-4 h-0.5 bg-green-400 inline-block" /> Forecast</span>
                </div>
              </div>
              {detailLoading ? (
                <div className="h-40 flex items-center justify-center text-slate-500 text-sm">Loading chart…</div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: 10 }}>
                    <defs>
                      <linearGradient id="histGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="fcGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: '#94a3b8', fontSize: 10 }}
                      tickLine={false}
                      interval={Math.floor(chartData.length / 6)}
                    />
                    <YAxis
                      tick={{ fill: '#94a3b8', fontSize: 10 }}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(v) => `$${v.toLocaleString()}`}
                      width={60}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
                      labelStyle={{ color: '#94a3b8', fontSize: 11 }}
                      itemStyle={{ color: '#e2e8f0', fontSize: 12 }}
                      formatter={(v) => [`$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`, 'Price']}
                    />
                    {history.length > 0 && (
                      <ReferenceLine x={history[history.length - 1]?.date && new Date(history[history.length - 1].date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} stroke="#64748b" strokeDasharray="4 4" label={{ value: 'Today', fill: '#64748b', fontSize: 10 }} />
                    )}
                    <Area
                      type="monotone"
                      dataKey="price"
                      stroke="#3b82f6"
                      strokeWidth={1.5}
                      fill="url(#histGrad)"
                      dot={false}
                      connectNulls
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Supplier recommendations */}
            <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
              <h3 className="text-sm font-semibold text-white mb-3">
                Supplier Recommendations
                <span className="ml-2 text-xs text-slate-400 font-normal">
                  Score = 40% price · 30% reliability · 20% speed · 10% risk
                </span>
              </h3>
              {detailLoading ? (
                <div className="text-slate-500 text-sm text-center py-4">Loading suppliers…</div>
              ) : (
                <div className="space-y-2">
                  {suppliers.slice(0, 8).map((sup, i) => (
                    <button
                      key={sup.id}
                      onClick={() => setSelectedSupplierId(sup.id)}
                      className={`w-full text-left rounded-lg p-3 border transition-colors ${
                        selectedSupplierId === sup.id
                          ? 'bg-blue-900/40 border-blue-500/60'
                          : 'bg-slate-700/40 border-slate-600/40 hover:bg-slate-700/60'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {i === 0 && (
                            <span className="text-xs bg-green-600 text-white px-1.5 py-0.5 rounded font-medium">
                              #1 Rec
                            </span>
                          )}
                          <span className="text-sm font-medium text-white">{sup.name}</span>
                          {sup.is_domestic && (
                            <span className="text-xs text-blue-400">🇺🇸 Domestic</span>
                          )}
                        </div>
                        <div className="text-sm font-bold text-green-400">
                          {(sup.composite_score * 100).toFixed(0)}pts
                        </div>
                      </div>
                      <div className="grid grid-cols-4 gap-2 mt-2 text-xs text-slate-400">
                        <div>Lead: <span className="text-white">{sup.lead_time_days}d</span></div>
                        <div>Reliability: <span className="text-white">{(sup.reliability_score * 100).toFixed(0)}%</span></div>
                        <div>Price: <span className="text-white">{(sup.price_competitiveness * 100).toFixed(0)}%</span></div>
                        <div>Risk: <span className={riskColor(sup.risk_score)}>{(sup.risk_score * 100).toFixed(0)}%</span></div>
                      </div>
                    </button>
                  ))}
                  {suppliers.length === 0 && (
                    <div className="text-slate-500 text-sm text-center py-4">No suppliers found for this material</div>
                  )}
                </div>
              )}
            </div>

            {/* Add to cart */}
            {selectedSupplierId && (
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <h3 className="text-sm font-semibold text-white mb-3">Add to Cart</h3>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-slate-400">Quantity ({selectedMat.unit})</label>
                    <input
                      type="number"
                      min={0.1}
                      step={1}
                      value={qty}
                      onChange={(e) => setQty(parseFloat(e.target.value) || 1)}
                      className="w-24 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  {selectedMat.current_price && (
                    <div className="text-sm text-slate-300">
                      Estimated: <strong className="text-white">
                        ${(selectedMat.current_price * qty).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </strong>
                    </div>
                  )}
                  <button
                    onClick={handleAddToCart}
                    disabled={adding}
                    className="ml-auto bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
                  >
                    {adding ? 'Adding…' : 'Add to Cart'}
                  </button>
                  {addedMsg && <span className="text-green-400 text-sm">{addedMsg}</span>}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
