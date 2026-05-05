import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

interface MonteCarloChartProps {
  baselineP10: number;
  baselineP50: number;
  baselineP90: number;
  scenarioP10: number;
  scenarioP50: number;
  scenarioP90: number;
  title?: string;
}

export function MonteCarloChart({
  baselineP10,
  baselineP50,
  baselineP90,
  scenarioP10,
  scenarioP50,
  scenarioP90,
  title = "Fulfillment Rate Distribution",
}: MonteCarloChartProps) {
  const data = [
    {
      scenario: "Baseline",
      p10: baselineP10,
      p50: baselineP50,
      p90: baselineP90,
    },
    {
      scenario: "Current",
      p10: scenarioP10,
      p50: scenarioP50,
      p90: scenarioP90,
    },
  ];

  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm">
      <h3 className="text-lg font-semibold text-white mb-4">{title}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="scenario" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1e293b",
              border: "1px solid #475569",
              borderRadius: "8px",
            }}
            formatter={(value: number) => `${value.toFixed(1)}%`}
          />
          <Legend />
          <Area
            type="monotone"
            dataKey="p10"
            name="P10 (Worst Case)"
            stroke="#f87171"
            fill="#f87171"
            fillOpacity={0.2}
          />
          <Area
            type="monotone"
            dataKey="p50"
            name="P50 (Median)"
            stroke="#60a5fa"
            fill="#60a5fa"
            fillOpacity={0.2}
          />
          <Area
            type="monotone"
            dataKey="p90"
            name="P90 (Best Case)"
            stroke="#34d399"
            fill="#34d399"
            fillOpacity={0.2}
          />
        </AreaChart>
      </ResponsiveContainer>
      <div className="mt-4 grid grid-cols-3 gap-4 text-xs text-slate-400">
        <div>
          <span className="font-semibold text-red-400">P10:</span> Tail risk (worst 10%)
        </div>
        <div>
          <span className="font-semibold text-blue-400">P50:</span> Median outcome
        </div>
        <div>
          <span className="font-semibold text-green-400">P90:</span> Favorable outcome (best 10%)
        </div>
      </div>
    </div>
  );
}
