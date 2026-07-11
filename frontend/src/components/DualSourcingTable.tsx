import { type DualSourceEntry } from '../services/api';

interface DualSourcingTableProps {
  entries: DualSourceEntry[];
  noRegretCount: number;
  hedgeCount: number;
  supplierDevelopmentCount: number;
}

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const TIER_STYLE: Record<string, string> = {
  'no-regret': 'bg-green-500/20 text-green-300 border border-green-700',
  hedge: 'bg-amber-500/20 text-amber-300 border border-amber-700',
  'supplier-development': 'bg-red-500/20 text-red-300 border border-red-700',
};

const TIER_LABEL: Record<string, string> = {
  'no-regret': 'No-Regret',
  hedge: 'Hedge',
  'supplier-development': 'Supplier Dev',
};

function TierBadge({ tier }: { tier: string }) {
  return (
    <span
      className={`px-2 py-1 rounded text-xs font-semibold whitespace-nowrap ${
        TIER_STYLE[tier] || 'bg-slate-700 text-slate-300 border border-slate-600'
      }`}
    >
      {TIER_LABEL[tier] || tier}
    </span>
  );
}

export function DualSourcingTable({
  entries,
  noRegretCount,
  hedgeCount,
  supplierDevelopmentCount,
}: DualSourcingTableProps) {
  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-700 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">Dual-Sourcing Plan</h3>
          <p className="text-sm text-slate-400 mt-1">
            Single-source components ranked by the payoff of qualifying a second source.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-3 py-1 rounded text-xs font-semibold bg-green-500/20 text-green-300 border border-green-700">
            No-Regret: {noRegretCount}
          </span>
          <span className="px-3 py-1 rounded text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-700">
            Hedge: {hedgeCount}
          </span>
          <span className="px-3 py-1 rounded text-xs font-semibold bg-red-500/20 text-red-300 border border-red-700">
            Supplier Dev: {supplierDevelopmentCount}
          </span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/50 border-b border-slate-700">
            <tr>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">MPN / Category</th>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">Current Source</th>
              <th className="px-4 py-3 text-left text-slate-300 font-semibold">Recommended 2nd Source</th>
              <th className="px-4 py-3 text-right text-slate-300 font-semibold">Incremental $/unit</th>
              <th className="px-4 py-3 text-right text-slate-300 font-semibold">Risk Reduction $</th>
              <th className="px-4 py-3 text-right text-slate-300 font-semibold">Risk Reduction / $</th>
              <th className="px-4 py-3 text-center text-slate-300 font-semibold">Tier</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {entries.map((e) => (
              <tr key={e.component_id} className="hover:bg-slate-800/50 transition">
                <td className="px-4 py-3">
                  <div className="text-white font-medium">{e.mpn}</div>
                  <div className="text-xs text-slate-400">{e.category}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="text-slate-200">{e.current_supplier}</div>
                  <div className="text-xs text-slate-400 tabular-nums">{usd(e.current_price_usd)}</div>
                </td>
                <td className="px-4 py-3">
                  {e.recommended_second_source ? (
                    <>
                      <div className="text-slate-200">{e.recommended_second_source}</div>
                      {e.second_source_price_usd !== null && (
                        <div className="text-xs text-slate-400 tabular-nums">
                          {usd(e.second_source_price_usd)}
                        </div>
                      )}
                    </>
                  ) : (
                    <span className="text-slate-500">n/a</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                  {usd(e.incremental_unit_cost_usd)}
                </td>
                <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                  {usd(e.risk_reduction_usd)}
                </td>
                <td className="px-4 py-3 text-right text-slate-200 tabular-nums">
                  {e.risk_reduction_per_dollar !== null ? e.risk_reduction_per_dollar.toFixed(2) : (
                    <span className="text-slate-500">n/a</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  <TierBadge tier={e.tier} />
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                  No single-source components found for this scope.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
