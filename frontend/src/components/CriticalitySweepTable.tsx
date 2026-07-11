import { type CriticalityEntry } from '../services/api';

interface CriticalitySweepTableProps {
  entries: CriticalityEntry[];
  maxSpendAtRisk: number;
  networkWide: boolean;
}

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

/** REI (Relative Exposure Index, 0-1) rendered as a small inline bar + number. */
function ReiBar({ rei }: { rei: number }) {
  const pct = Math.max(0, Math.min(1, rei)) * 100;
  const barColor = rei > 0.7 ? 'bg-red-400' : rei > 0.4 ? 'bg-amber-400' : 'bg-blue-400';
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-300 tabular-nums w-10 text-right">{rei.toFixed(2)}</span>
    </div>
  );
}

export function CriticalitySweepTable({
  entries,
  maxSpendAtRisk,
  networkWide,
}: CriticalitySweepTableProps) {
  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-700 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">Criticality Sweep</h3>
          <p className="text-sm text-slate-400 mt-1">
            Distributors ranked by single-source exposure they create across the network.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`px-3 py-1 rounded text-xs font-semibold uppercase tracking-wider ${
              networkWide
                ? 'bg-blue-500/20 text-blue-300 border border-blue-700'
                : 'bg-purple-500/20 text-purple-300 border border-purple-700'
            }`}
          >
            {networkWide ? 'Network-wide' : 'BOM-scoped'}
          </span>
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wider text-slate-400">Max Spend at Risk</div>
            <div className="text-white font-semibold tabular-nums">{usd(maxSpendAtRisk)}</div>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/50 border-b border-slate-700">
            <tr>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">#</th>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">Distributor</th>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">Country</th>
              <th className="px-4 py-3 text-right text-slate-300 font-semibold">Orphan Components</th>
              <th className="px-4 py-3 text-right text-slate-300 font-semibold">Spend at Risk</th>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">REI</th>
              <th className="px-4 py-3 text-right text-slate-300 font-semibold">Betweenness</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {entries.map((e, idx) => (
              <tr
                key={e.distributor_id}
                className={e.rei > 0.7 ? 'bg-red-500/5' : ''}
              >
                <td className="px-4 py-3 text-slate-400 tabular-nums">{idx + 1}</td>
                <td className="px-4 py-3 text-white font-medium">
                  {e.name}
                  {!e.is_domestic && (
                    <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-700 text-slate-300">
                      Intl
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-400">{e.country || '—'}</td>
                <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                  {e.orphan_component_count}
                </td>
                <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                  {usd(e.spend_at_risk_usd)}
                </td>
                <td className="px-4 py-3">
                  <ReiBar rei={e.rei} />
                </td>
                <td className="px-4 py-3 text-right text-slate-400 tabular-nums">
                  {e.betweenness.toFixed(4)}
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                  No exposure found for this scope.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
