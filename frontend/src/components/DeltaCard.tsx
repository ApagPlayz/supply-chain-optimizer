interface DeltaCardProps {
  label: string;
  baseline: number;
  scenario: number;
  delta_pct: number;
  unit?: string;
  accent?: string; // e.g., "border-blue-500", "border-green-500"
  isBad?: boolean; // if true, positive delta is red (cost increase); if false, positive delta is green (good)
}

export function DeltaCard({
  label,
  baseline,
  scenario,
  delta_pct,
  unit = "",
  accent = "border-slate-600",
  isBad = true,
}: DeltaCardProps) {
  const deltaColor = isBad
    ? delta_pct > 0 ? "text-red-400" : "text-green-400"
    : delta_pct > 0 ? "text-green-400" : "text-red-400";

  const badgeColor = isBad
    ? delta_pct > 0 ? "bg-red-500/20 text-red-300 border-red-400" : "bg-green-500/20 text-green-300 border-green-400"
    : delta_pct > 0 ? "bg-green-500/20 text-green-300 border-green-400" : "bg-red-500/20 text-red-300 border-red-400";

  const arrow = delta_pct > 0 ? "↑" : delta_pct < 0 ? "↓" : "→";

  return (
    <div className={`bg-slate-800/50 border ${accent} rounded-lg p-4 flex justify-between items-center`}>
      <div className="flex flex-col gap-1">
        <span className="text-slate-400 text-xs font-semibold uppercase">{label}</span>
        <div className="flex gap-4">
          <div>
            <span className="text-slate-500 text-xs">Baseline</span>
            <span className="block text-xl font-semibold text-white">
              {baseline.toFixed(1)}{unit}
            </span>
          </div>
          <div>
            <span className="text-slate-500 text-xs">Scenario</span>
            <span className="block text-xl font-semibold text-white">
              {scenario.toFixed(1)}{unit}
            </span>
          </div>
        </div>
      </div>
      <div className={`border rounded-lg px-3 py-2 text-center ${badgeColor}`}>
        <div className={`text-2xl font-bold ${deltaColor}`}>
          {arrow} {Math.abs(delta_pct).toFixed(1)}%
        </div>
        <div className="text-xs font-semibold mt-1">Delta</div>
      </div>
    </div>
  );
}
