import { useEffect, useState, useMemo } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import { materialsAPI } from '../services/api';
import { useOptimizeStore } from '../store/optimizeStore';
import { Leaf, AlertTriangle, Target } from 'lucide-react';

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


export default function ESGDashboard() {
  const { multiResult } = useOptimizeStore();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([materialsAPI.list(), materialsAPI.categories()])
      .then(([mRes]) => {
        setMaterials(mRes.data);
        setLoading(false);
      });
  }, []);

  const alternatives = multiResult?.alternatives ?? [];
  const cheapest = alternatives.find((a) => a.id === 'cheapest');
  const greenest = alternatives.find((a) => a.id === 'greenest');
  const balanced = alternatives.find((a) => a.id === 'balanced');

  // Pareto frontier data
  const paretoData = useMemo(
    () =>
      alternatives.map((a) => ({
        x: a.total_cost_usd,
        y: a.total_co2e_kg,
        name: a.label,
        id: a.id,
        strategy: a.id,
      })),
    [alternatives]
  );

  // Material risk matrix
  const riskMatrixData = useMemo(
    () =>
      materials.map((m) => ({
        x: m.volatility_score,
        y: m.supply_risk_score,
        name: m.name,
        category: m.category,
        z: 40,
      })),
    [materials]
  );

  // Supply risk by category
  const riskByCategory = useMemo(() => {
    const groups: Record<string, number[]> = {};
    materials.forEach((m) => {
      if (!groups[m.category]) groups[m.category] = [];
      groups[m.category].push(m.supply_risk_score);
    });
    return Object.entries(groups)
      .map(([cat, scores]) => ({
        category: cat,
        avgRisk: scores.reduce((a, b) => a + b, 0) / scores.length,
        count: scores.length,
      }))
      .sort((a, b) => b.avgRisk - a.avgRisk);
  }, [materials]);

  // ESG Score calculation
  const esgScore = useMemo(() => {
    if (!multiResult || !materials.length) return null;

    const greenestCo2 = greenest?.total_co2e_kg ?? 0;
    const cheapestCo2 = cheapest?.total_co2e_kg ?? 1;
    // Carbon efficiency: how much better is greenest vs cheapest (0-1)
    const carbonEfficiency = cheapestCo2 > 0 ? Math.min(1, greenestCo2 / cheapestCo2) : 0;

    // Resilience: inverse average supply risk
    const avgSupplyRisk = materials.reduce((s, m) => s + m.supply_risk_score, 0) / materials.length;
    const resilience = 1 - avgSupplyRisk;

    // Geographic diversification (unique states / total items)
    const uniqueStates = new Set(multiResult.alternatives[0]?.route.map((stop) => stop.state).filter(Boolean)).size;
    const totalStops = multiResult.alternatives[0]?.route.length ?? 1;
    const diversification = Math.min(1, uniqueStates / Math.max(1, totalStops));

    const composite = (carbonEfficiency * 0.4 + resilience * 0.35 + diversification * 0.25) * 100;

    return {
      score: Math.round(composite),
      carbonEfficiency: Math.round(carbonEfficiency * 100),
      resilience: Math.round(resilience * 100),
      diversification: Math.round(diversification * 100),
    };
  }, [multiResult, materials, greenest, cheapest]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <span className="text-slate-400 text-sm">Loading ESG dashboard...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2 flex items-center gap-2">
            <Leaf className="w-8 h-8 text-emerald-400" />
            ESG & Sustainability Dashboard
          </h1>
          <p className="text-slate-400">Track carbon footprint, supply chain resilience, and sustainability metrics</p>
        </div>

        {/* ESG Score Card */}
        {esgScore ? (
          <div className="mb-8 bg-gradient-to-br from-emerald-900/30 to-slate-800 border border-emerald-700/50 rounded-xl p-8">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-emerald-300 uppercase mb-2">Your ESG Score</h2>
                <div className="text-5xl font-bold text-white mb-2">
                  {esgScore.score} <span className="text-2xl text-slate-400">/ 100</span>
                </div>
                <div className="text-sm text-emerald-300">
                  {esgScore.score >= 70
                    ? '🟢 Excellent - Leading sustainable practices'
                    : esgScore.score >= 40
                    ? '🟡 Good - Room for improvement'
                    : '🔴 At Risk - Urgent action needed'}
                </div>
              </div>
              <div className="space-y-3">
                <div className="bg-slate-800/60 rounded-lg p-3 text-center border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1">Carbon Efficiency</div>
                  <div className="text-2xl font-bold text-blue-400">{esgScore.carbonEfficiency}%</div>
                </div>
                <div className="bg-slate-800/60 rounded-lg p-3 text-center border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1">Resilience</div>
                  <div className="text-2xl font-bold text-emerald-400">{esgScore.resilience}%</div>
                </div>
                <div className="bg-slate-800/60 rounded-lg p-3 text-center border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1">Diversification</div>
                  <div className="text-2xl font-bold text-amber-400">{esgScore.diversification}%</div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="mb-8 bg-slate-800 border border-slate-700 rounded-xl p-8 text-center">
            <Target className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <div className="text-slate-400">
              <div className="font-medium mb-1">No ESG score yet</div>
              <div className="text-sm">Run an optimization on the Checkout page to generate your ESG metrics</div>
            </div>
          </div>
        )}

        {/* Carbon KPI Row */}
        {alternatives.length > 0 && (
          <div className="mb-8 grid grid-cols-1 md:grid-cols-3 gap-4">
            {cheapest && (
              <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                <div className="text-xs text-slate-400 uppercase mb-2">Cheapest Strategy</div>
                <div className="text-3xl font-bold text-green-400 mb-1">{cheapest.total_co2e_kg.toFixed(1)} kg</div>
                <div className="text-xs text-slate-500">CO2 Emissions</div>
              </div>
            )}
            {balanced && (
              <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                <div className="text-xs text-slate-400 uppercase mb-2">Balanced Strategy</div>
                <div className="text-3xl font-bold text-purple-400 mb-1">{balanced.total_co2e_kg.toFixed(1)} kg</div>
                <div className="text-xs text-slate-500">CO2 Emissions</div>
              </div>
            )}
            {greenest && (
              <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
                <div className="text-xs text-slate-400 uppercase mb-2">Greenest Strategy</div>
                <div className="text-3xl font-bold text-emerald-400 mb-1">{greenest.total_co2e_kg.toFixed(1)} kg</div>
                <div className="text-xs text-slate-500">CO2 Emissions</div>
              </div>
            )}
          </div>
        )}

        {/* Charts grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Cost vs Carbon Pareto Frontier */}
          {paretoData.length > 0 && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-white mb-4">Cost vs Carbon Trade-off</h2>
              <ResponsiveContainer width="100%" height={250}>
                <ScatterChart margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="x"
                    type="number"
                    name="Cost"
                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                    label={{ value: 'Cost ($)', position: 'insideBottomRight', offset: -5, fill: '#94a3b8', fontSize: 11 }}
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    name="CO2"
                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                    label={{ value: 'CO2 (kg)', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }}
                  />
                  <ZAxis range={[60, 60]} />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                    labelStyle={{ color: '#94a3b8' }}
                    formatter={(value: any) => typeof value === 'number' ? value.toFixed(1) : value}
                  />
                  <Scatter
                    name="Route Strategies"
                    data={paretoData}
                    fill="#3b82f6"
                    shape="circle"
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Supply Risk by Category */}
          {riskByCategory.length > 0 && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-white mb-4">Supply Risk by Category</h2>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart
                  data={riskByCategory}
                  layout="vertical"
                  margin={{ top: 5, right: 20, left: 100, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                  <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <YAxis
                    dataKey="category"
                    type="category"
                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                    width={95}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                    formatter={(value) => `${(Number(value) * 100).toFixed(0)}%`}
                  />
                  <Bar
                    dataKey="avgRisk"
                    fill="#ef4444"
                    radius={[0, 4, 4, 0]}
                    name="Avg Risk"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Material Risk Matrix */}
        {riskMatrixData.length > 0 && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-6">
            <h2 className="text-sm font-semibold text-white mb-4">Material Risk Matrix</h2>
            <div className="relative">
              <ResponsiveContainer width="100%" height={300}>
                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="x"
                    type="number"
                    name="Volatility"
                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                    label={{ value: 'Price Volatility', position: 'insideBottomRight', offset: -5, fill: '#94a3b8' }}
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    name="Supply Risk"
                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                    label={{ value: 'Supply Risk', angle: -90, position: 'insideLeft', fill: '#94a3b8' }}
                  />
                  <ZAxis range={[40, 40]} />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                    labelStyle={{ color: '#94a3b8' }}
                    content={({ payload }) => {
                      if (!payload || !payload.length) return null;
                      const data = payload[0].payload;
                      return (
                        <div className="text-xs">
                          <div className="font-semibold">{data.name}</div>
                          <div className="text-slate-400">{data.category}</div>
                        </div>
                      );
                    }}
                  />
                  <Scatter
                    name="Materials"
                    data={riskMatrixData}
                    fill="#3b82f6"
                    shape="circle"
                  />
                </ScatterChart>
              </ResponsiveContainer>
              {/* Quadrant labels */}
              <div className="absolute inset-0 pointer-events-none text-[11px] font-semibold">
                <div className="absolute top-4 left-4 text-emerald-500">Safe Zone</div>
                <div className="absolute top-4 right-4 text-amber-500 text-right">Watch</div>
                <div className="absolute bottom-4 left-4 text-orange-500">Hedge</div>
                <div className="absolute bottom-4 right-4 text-red-500 text-right">Critical</div>
              </div>
            </div>
          </div>
        )}

        {/* Empty state */}
        {materials.length === 0 && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-8 text-center">
            <AlertTriangle className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <div className="text-slate-400">No materials data available</div>
          </div>
        )}
      </div>
    </div>
  );
}
