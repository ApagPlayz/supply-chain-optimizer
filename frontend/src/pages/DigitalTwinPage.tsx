import { useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import {
  TrendingUp, AlertTriangle, Settings,
  Send, RotateCcw,
} from 'lucide-react';
import { optimizeAPI } from '../services/api';
import { useCartStore } from '../store/cartStore';

interface ScenarioResult {
  scenario: {
    tariff_multiplier: number;
    distributor_failures: number;
    demand_spike: number;
  };
  base_total_cost: number;
  scenario_total_cost: number;
  cost_delta_pct: number;
  disrupted_items: number;
  eta_p50: number;
  eta_p90: number;
  item_breakdown: Array<{
    component: string;
    distributor: string;
    base_price: number;
    scenario_price: number | null;
    distributor_available: boolean;
    quantity: number;
    base_cost: number;
    scenario_cost: number | null;
  }>;
}

const PRESETS = [
  {
    label: 'US-China Trade War',
    description: '+25% tariffs on int\'l',
    icon: '🌏',
    params: { tariff_multiplier: 1.25, demand_spike: 1.0 },
  },
  {
    label: 'Port Strike',
    description: '+50% demand surge',
    icon: '⚓',
    params: { tariff_multiplier: 1.0, demand_spike: 1.5 },
  },
  {
    label: 'Distributor Failure',
    description: 'All cart distributors fail',
    icon: '⚠️',
    usesAllDistributors: true,
    params: { tariff_multiplier: 1.0, demand_spike: 1.0 },
  },
  {
    label: 'Semiconductor Shortage',
    description: '2x tariffs, 2x demand',
    icon: '💻',
    params: { tariff_multiplier: 2.0, demand_spike: 2.0 },
  },
];

export default function DigitalTwinPage() {
  const { items } = useCartStore();
  const [tariff, setTariff] = useState(1.0);
  const [demandSpike, setDemandSpike] = useState(1.0);
  const [distributorFailureIds, setDistributorFailureIds] = useState<number[]>([]);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const uniqueDistributors = Array.from(
    new Map(items.map((item) => [item.distributor_id, item]))
      .values()
  );

  const runScenario = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await optimizeAPI.scenario({
        tariff_multiplier: tariff,
        distributor_failure_ids: distributorFailureIds,
        demand_spike: demandSpike,
      });
      setResult(res.data as ScenarioResult);
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } };
      const detail = axiosErr.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? (detail as { msg: string }[]).map((d) => d.msg).join(', ')
        : typeof detail === 'string' ? detail : 'Scenario run failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const applyPreset = (preset: typeof PRESETS[number]) => {
    setTariff(preset.params.tariff_multiplier);
    setDemandSpike(preset.params.demand_spike);
    if ('usesAllDistributors' in preset && preset.usesAllDistributors) {
      setDistributorFailureIds(items.map((i) => i.distributor_id));
    } else {
      setDistributorFailureIds([]);
    }
  };

  const chartData = result?.item_breakdown.map((item) => ({
    name: item.component.split(' ').slice(0, 2).join(' '),
    base: item.base_cost,
    scenario: item.scenario_cost ?? 0,
  })) ?? [];

  const costDelta = result ? result.cost_delta_pct : 0;

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">Digital Twin Simulator</h1>
          <p className="text-slate-400">Test supply chain scenarios and measure impact on cost, risk, and delivery times</p>
        </div>

        {/* Main grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left panel: Controls */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
                <Settings className="w-4 h-4" />
                Scenario Controls
              </h2>

              {/* Presets */}
              <div className="mb-4 space-y-2">
                <label className="text-xs font-medium text-slate-400 uppercase">Quick Presets</label>
                <div className="grid grid-cols-2 gap-2">
                  {PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      onClick={() => applyPreset(preset)}
                      className="p-2 rounded-lg bg-slate-700/50 hover:bg-slate-700 border border-slate-600 text-left transition-colors"
                    >
                      <div className="text-lg mb-1">{preset.icon}</div>
                      <div className="text-[10px] font-medium text-white">{preset.label}</div>
                      <div className="text-[9px] text-slate-400">{preset.description}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="h-px bg-slate-700 mb-4" />

              {/* Tariff slider */}
              <div className="mb-4">
                <label className="text-xs font-medium text-slate-400 uppercase mb-2 block">
                  Tariff Impact: {tariff.toFixed(2)}x
                </label>
                <input
                  type="range"
                  min="1"
                  max="3"
                  step="0.05"
                  value={tariff}
                  onChange={(e) => setTariff(parseFloat(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
                  style={{
                    background: `linear-gradient(to right, #3b82f6 0%, #3b82f6 ${((tariff - 1) / 2) * 100}%, #334155 ${((tariff - 1) / 2) * 100}%, #334155 100%)`,
                  }}
                />
                <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                  <span>1.0x (baseline)</span>
                  <span>3.0x (severe)</span>
                </div>
              </div>

              {/* Demand slider */}
              <div className="mb-4">
                <label className="text-xs font-medium text-slate-400 uppercase mb-2 block">
                  Demand Surge: {demandSpike.toFixed(2)}x
                </label>
                <input
                  type="range"
                  min="1"
                  max="3"
                  step="0.05"
                  value={demandSpike}
                  onChange={(e) => setDemandSpike(parseFloat(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
                  style={{
                    background: `linear-gradient(to right, #10b981 0%, #10b981 ${((demandSpike - 1) / 2) * 100}%, #334155 ${((demandSpike - 1) / 2) * 100}%, #334155 100%)`,
                  }}
                />
                <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                  <span>1.0x (baseline)</span>
                  <span>3.0x (severe)</span>
                </div>
              </div>

              <div className="h-px bg-slate-700 mb-4" />

              {/* Distributor failures */}
              {items.length === 0 ? (
                <div className="text-xs text-slate-500 mb-4 p-2 bg-slate-700/20 rounded border border-slate-600">
                  Add items to cart to test distributor failure scenarios
                </div>
              ) : (
                <div className="mb-4">
                  <label className="text-xs font-medium text-slate-400 uppercase mb-2 block">
                    Distributor Failures
                  </label>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {uniqueDistributors.map((item) => (
                      <label key={item.distributor_id} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={distributorFailureIds.includes(item.distributor_id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setDistributorFailureIds([...distributorFailureIds, item.distributor_id]);
                            } else {
                              setDistributorFailureIds(distributorFailureIds.filter((id) => id !== item.distributor_id));
                            }
                          }}
                          className="w-3.5 h-3.5 rounded border-slate-600 cursor-pointer"
                        />
                        <span className="truncate">{item.distributor_name ?? `Distributor ${item.distributor_id}`}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {/* Action buttons */}
              <div className="space-y-2">
                <button
                  onClick={runScenario}
                  disabled={loading || items.length === 0}
                  className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white py-2.5 rounded-lg font-semibold text-sm transition-colors flex items-center justify-center gap-2"
                >
                  <Send className="w-4 h-4" />
                  {loading ? 'Running...' : 'Run Scenario'}
                </button>
                <button
                  onClick={() => {
                    setTariff(1.0);
                    setDemandSpike(1.0);
                    setDistributorFailureIds([]);
                    setResult(null);
                    setError(null);
                  }}
                  className="w-full bg-slate-700 hover:bg-slate-600 text-white py-2 rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-2"
                >
                  <RotateCcw className="w-3 h-3" />
                  Reset All
                </button>
              </div>
            </div>
          </div>

          {/* Right panel: Results */}
          <div className="lg:col-span-2 space-y-4">
            {error && (
              <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-sm text-red-300">
                {error}
              </div>
            )}

            {!result ? (
              <div className="bg-slate-800 border border-slate-700 rounded-xl p-8 flex items-center justify-center h-64">
                <div className="text-center">
                  <div className="text-4xl mb-3">🎯</div>
                  <div className="text-slate-400">No scenario run yet. Configure parameters and click "Run Scenario"</div>
                </div>
              </div>
            ) : (
              <>
                {/* Impact summary cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-3">
                    <div className="text-xs text-slate-400 mb-1">Base Cost</div>
                    <div className="text-lg font-bold text-white">${result.base_total_cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                  </div>
                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-3">
                    <div className="text-xs text-slate-400 mb-1">Scenario Cost</div>
                    <div className="text-lg font-bold text-white">${result.scenario_total_cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                  </div>
                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-3">
                    <div className="text-xs text-slate-400 mb-1">Cost Delta</div>
                    <div className={`text-lg font-bold flex items-center gap-1 ${costDelta > 0 ? 'text-red-400' : 'text-green-400'}`}>
                      {costDelta > 0 ? '+' : ''}{costDelta.toFixed(1)}%
                      {costDelta > 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingUp className="w-4 h-4 transform rotate-180" />}
                    </div>
                  </div>
                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-3">
                    <div className="text-xs text-slate-400 mb-1">Disrupted Items</div>
                    <div className={`text-lg font-bold flex items-center gap-1 ${result.disrupted_items > 0 ? 'text-orange-400' : 'text-green-400'}`}>
                      {result.disrupted_items}
                      {result.disrupted_items > 0 && <AlertTriangle className="w-4 h-4" />}
                    </div>
                  </div>
                </div>

                {/* ETA impact */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div className="text-xs font-medium text-slate-400 mb-3">ETA P50 (Median)</div>
                    <div className="text-2xl font-bold text-blue-400">{result.eta_p50}d</div>
                  </div>
                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div className="text-xs font-medium text-slate-400 mb-3">ETA P90 (Worst Case)</div>
                    <div className="text-2xl font-bold text-orange-400">{result.eta_p90}d</div>
                  </div>
                </div>

                {/* Cost breakdown chart */}
                {chartData.length > 0 && (
                  <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-white mb-3">Cost Impact per Component</h3>
                    <ResponsiveContainer width="100%" height={250}>
                      <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                        <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
                          formatter={(v) => `$${Number(v).toLocaleString()}`}
                        />
                        <Legend />
                        <Bar dataKey="base" fill="#3b82f6" name="Base Cost" />
                        <Bar dataKey="scenario" fill="#ef4444" name="Scenario Cost" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Item breakdown table */}
                <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 overflow-x-auto">
                  <h3 className="text-sm font-semibold text-white mb-3">Item Breakdown</h3>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-700">
                        <th className="text-left py-2 px-2">Component</th>
                        <th className="text-left py-2 px-2">Distributor</th>
                        <th className="text-right py-2 px-2">Base</th>
                        <th className="text-right py-2 px-2">Scenario</th>
                        <th className="text-right py-2 px-2">Change</th>
                        <th className="text-right py-2 px-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.item_breakdown.map((item, i) => {
                        const costChange = item.scenario_cost ? item.scenario_cost - item.base_cost : null;
                        const pctChange = item.base_cost > 0 && costChange ? (costChange / item.base_cost) * 100 : 0;
                        return (
                          <tr
                            key={i}
                            className={`border-b border-slate-700/50 ${
                              !item.distributor_available
                                ? 'bg-red-900/20'
                                : costChange && costChange > 0 ? 'bg-orange-900/10' : ''
                            }`}
                          >
                            <td className="py-2 px-2 text-slate-300 truncate max-w-[120px]">{item.component}</td>
                            <td className="py-2 px-2 text-slate-400 truncate max-w-[100px]">{item.distributor}</td>
                            <td className="py-2 px-2 text-right text-slate-400">${item.base_cost.toFixed(0)}</td>
                            <td className="py-2 px-2 text-right text-slate-400">
                              {item.scenario_cost ? `$${item.scenario_cost.toFixed(0)}` : '—'}
                            </td>
                            <td className={`py-2 px-2 text-right font-medium ${
                              !item.distributor_available ? 'text-red-400' :
                              costChange && costChange > 0 ? 'text-orange-400' : 'text-green-400'
                            }`}>
                              {costChange ? `${costChange > 0 ? '+' : ''}${pctChange.toFixed(0)}%` : '—'}
                            </td>
                            <td className="py-2 px-2 text-right">
                              {!item.distributor_available ? (
                                <span className="text-red-400 font-medium">Failed</span>
                              ) : (
                                <span className="text-green-400">OK</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
