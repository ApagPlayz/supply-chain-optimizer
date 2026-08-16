import { useEffect, useState } from 'react';
import { componentsAPI } from '../services/api';

/**
 * Per-BOM-line baseline-vs-scenario cost breakdown for a distributor-failure scenario.
 *
 * This is the one idea worth keeping from the deleted Digital Twin page. That version
 * read `item_breakdown` from a legacy endpoint the backend itself marked "simplified",
 * which did no re-sourcing — it just re-priced whatever was already in the cart.
 *
 * This version recomputes the line from the real offer table: for each component it
 * takes the cheapest real distributor offer, then the cheapest offer that REMAINS once
 * the failed distributor is removed. So the "scenario" column is an actual re-sourcing
 * decision against real prices, and a line with no surviving supplier is shown as
 * unsourceable rather than silently priced.
 */

interface Offer {
  distributor_id: number;
  distributor_name: string;
  price: number | null;
  stock: number | null;
}

interface Row {
  componentId: number;
  mpn: string;
  quantity: number;
  supplierCount: number;
  basePrice: number | null;
  baseSupplier: string | null;
  scenarioPrice: number | null;
  scenarioSupplier: string | null;
  soleSourced: boolean;
}

interface Props {
  bomComponentIds: number[];
  mpnById: Record<number, string>;
  quantityById?: Record<number, number>;
  failedDistributorId: number;
  failedDistributorName: string;
}

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function cheapest(offers: Offer[]): Offer | null {
  const priced = offers.filter((o) => typeof o.price === 'number' && o.price > 0);
  if (priced.length === 0) return null;
  return priced.reduce((a, b) => ((b.price as number) < (a.price as number) ? b : a));
}

export function BomCostBreakdownTable({
  bomComponentIds,
  mpnById,
  quantityById,
  failedDistributorId,
  failedDistributorName,
}: Props) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (bomComponentIds.length === 0) return;
      setLoading(true);
      setError(null);
      try {
        const results = await Promise.all(
          bomComponentIds.map(async (id) => {
            const res = await componentsAPI.offers(id);
            const offers: Offer[] = Array.isArray(res.data) ? res.data : [];
            const base = cheapest(offers);
            const survivors = offers.filter((o) => o.distributor_id !== failedDistributorId);
            const scenario = cheapest(survivors);
            return {
              componentId: id,
              mpn: mpnById[id] || `Component ${id}`,
              quantity: quantityById?.[id] ?? 1,
              supplierCount: offers.length,
              basePrice: base?.price ?? null,
              baseSupplier: base?.distributor_name ?? null,
              scenarioPrice: scenario?.price ?? null,
              scenarioSupplier: scenario?.distributor_name ?? null,
              soleSourced: offers.length > 0 && survivors.length === 0,
            } as Row;
          })
        );
        if (!cancelled) setRows(results);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to load offer prices');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [bomComponentIds, failedDistributorId, mpnById, quantityById]);

  if (loading) {
    return (
      <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 text-sm text-slate-400">
        Re-pricing each BOM line against the surviving distributors…
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-800/70 border border-red-700/50 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-white mb-1">Line-by-line cost impact</h3>
        <p className="text-sm text-red-300">Could not load offer prices: {error}</p>
      </div>
    );
  }

  if (!rows || rows.length === 0) return null;

  const unsourceable = rows.filter((r) => r.soleSourced);
  const reSourced = rows.filter(
    (r) => !r.soleSourced && r.baseSupplier !== r.scenarioSupplier && r.scenarioPrice != null
  );

  // Totals compare LIKE FOR LIKE — only the lines that survive in both states.
  // Summing the baseline of a line that becomes unsourceable against a scenario
  // total of $0 produces a large NEGATIVE percentage, i.e. a total supply failure
  // rendering as a cost saving. The value that disappears is reported separately.
  const survivors = rows.filter((r) => !r.soleSourced);
  const baseTotal = survivors.reduce((s, r) => s + (r.basePrice ?? 0) * r.quantity, 0);
  const scenarioTotal = survivors.reduce((s, r) => s + (r.scenarioPrice ?? 0) * r.quantity, 0);
  const strandedSpend = unsourceable.reduce((s, r) => s + (r.basePrice ?? 0) * r.quantity, 0);
  const allBaseTotal = rows.reduce((s, r) => s + (r.basePrice ?? 0) * r.quantity, 0);

  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm">
      <h3 className="text-lg font-semibold text-white mb-1">Line-by-line cost impact</h3>
      <p className="text-xs text-slate-400 mb-4">
        Cheapest real distributor offer per line, before and after removing{' '}
        <span className="text-slate-200 font-medium">{failedDistributorName}</span>. Prices are
        actual offers from the catalogue, not modelled — a line with no surviving offer is
        marked unsourceable rather than given a price.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 border-b border-slate-700">
              <th className="text-left py-2 px-2">Component</th>
              <th className="text-right py-2 px-2">Qty</th>
              <th className="text-left py-2 px-2">Baseline supplier</th>
              <th className="text-right py-2 px-2">Baseline</th>
              <th className="text-left py-2 px-2">Re-sourced to</th>
              <th className="text-right py-2 px-2">Scenario</th>
              <th className="text-right py-2 px-2">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const baseLine = (r.basePrice ?? 0) * r.quantity;
              const scenLine = r.scenarioPrice != null ? r.scenarioPrice * r.quantity : null;
              const change = scenLine != null ? scenLine - baseLine : null;
              const pct = change != null && baseLine > 0 ? (change / baseLine) * 100 : null;
              return (
                <tr
                  key={r.componentId}
                  className={`border-b border-slate-700/50 ${
                    r.soleSourced ? 'bg-red-900/20' : change && change > 0 ? 'bg-orange-900/10' : ''
                  }`}
                >
                  <td className="py-2 px-2 text-slate-200 font-medium">
                    {r.mpn}
                    <span className="block text-[10px] text-slate-500">
                      {r.supplierCount} offer{r.supplierCount === 1 ? '' : 's'}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right text-slate-400 tabular-nums">{r.quantity}</td>
                  <td className="py-2 px-2 text-slate-400 truncate max-w-[140px]">
                    {r.baseSupplier ?? '—'}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300 tabular-nums">
                    {r.basePrice != null ? usd(baseLine) : '—'}
                  </td>
                  <td className="py-2 px-2 truncate max-w-[140px]">
                    {r.soleSourced ? (
                      <span className="text-red-400 font-medium">no surviving supplier</span>
                    ) : r.baseSupplier === r.scenarioSupplier ? (
                      <span className="text-slate-500">unaffected</span>
                    ) : (
                      <span className="text-amber-300">{r.scenarioSupplier}</span>
                    )}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300 tabular-nums">
                    {scenLine != null ? usd(scenLine) : '—'}
                  </td>
                  <td
                    className={`py-2 px-2 text-right font-medium tabular-nums ${
                      r.soleSourced
                        ? 'text-red-400'
                        : change && change > 0
                          ? 'text-orange-400'
                          : change && change < 0
                            ? 'text-green-400'
                            : 'text-slate-500'
                    }`}
                  >
                    {r.soleSourced
                      ? 'unsourceable'
                      : pct == null
                        ? '—'
                        : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="text-slate-300 font-semibold border-t border-slate-700">
              <td className="py-2 px-2" colSpan={3}>
                Surviving lines ({survivors.length} of {rows.length})
              </td>
              <td className="py-2 px-2 text-right tabular-nums">{usd(baseTotal)}</td>
              <td />
              <td className="py-2 px-2 text-right tabular-nums">{usd(scenarioTotal)}</td>
              <td
                className={`py-2 px-2 text-right tabular-nums ${
                  scenarioTotal > baseTotal ? 'text-orange-400' : 'text-slate-400'
                }`}
              >
                {baseTotal > 0
                  ? `${scenarioTotal - baseTotal > 0 ? '+' : ''}${(((scenarioTotal - baseTotal) / baseTotal) * 100).toFixed(1)}%`
                  : '—'}
              </td>
            </tr>
            {unsourceable.length > 0 && (
              <tr className="text-red-300 font-semibold">
                <td className="py-2 px-2" colSpan={3}>
                  Stranded — no supplier at any price ({unsourceable.length} line
                  {unsourceable.length === 1 ? '' : 's'})
                </td>
                <td className="py-2 px-2 text-right tabular-nums">{usd(strandedSpend)}</td>
                <td />
                <td className="py-2 px-2 text-right text-red-400">unsourceable</td>
                <td className="py-2 px-2 text-right tabular-nums text-red-400">
                  {allBaseTotal > 0
                    ? `${((strandedSpend / allBaseTotal) * 100).toFixed(0)}% of BOM`
                    : '—'}
                </td>
              </tr>
            )}
          </tfoot>
        </table>
      </div>

      {unsourceable.length > 0 && (
        <p className="text-xs text-red-300 mt-3">
          {usd(strandedSpend)} of this BOM — {((strandedSpend / allBaseTotal) * 100).toFixed(0)}%
          of its baseline value — has no supplier at all without {failedDistributorName}. The
          percentage above deliberately compares only the {survivors.length} surviving lines: a
          stranded line has no scenario price, and counting it as $0 would make a total supply
          failure look like a saving.
        </p>
      )}
      {unsourceable.length === 0 && reSourced.length > 0 && (
        <p className="text-xs text-slate-400 mt-3">
          Every line survives; {reSourced.length} re-source to a different distributor.
        </p>
      )}
    </div>
  );
}

export default BomCostBreakdownTable;
