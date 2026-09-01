import { Fragment, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

interface AlternativeSupplier {
  name: string;
  lead_time_days: number;
  // Optional: only shown when a real cost delta is available. Never fabricated.
  cost_delta_pct?: number;
}

interface AffectedComponent {
  component_id: number;
  mpn: string;
  // Null when the catalogue has no priced offer for this line at all. Rendered as
  // "unknown" — the old table printed the literal string "Primary" for every row,
  // which was not a supplier, it was a placeholder presented as data.
  current_supplier: string | null;
  alternative_suppliers: AlternativeSupplier[];
}

interface BOMImpactTableProps {
  affectedComponents: AffectedComponent[];
  title?: string;
  /**
   * What "affected" means for the scenario being rendered — a distributor outage
   * orphans lines, a risk spike migrates them into a higher tier. Shown in the
   * empty state so "no components affected" reads as an answer rather than as a
   * table that failed to load.
   */
  emptyMessage?: string;
  /**
   * Replaces the bare "No components affected" count line. Zero orphaned lines is
   * NOT the same as zero impact, and the page shipped that conflation: this table
   * printed "No components affected" while the same response reported modelled
   * fulfilment falling 100% → 80%. When the caller can see that contradiction in
   * the served fields it passes a composed label here instead, so the count line
   * can never state more than the response supports.
   */
  emptyLabel?: ReactNode;
}

export function BOMImpactTable({
  affectedComponents,
  title = "Affected BOM Components",
  emptyMessage = "No BOM line is affected under this scenario.",
  emptyLabel,
}: BOMImpactTableProps) {
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const toggleRow = (componentId: number) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(componentId)) {
      newExpanded.delete(componentId);
    } else {
      newExpanded.add(componentId);
    }
    setExpandedRows(newExpanded);
  };

  // The header count and the rows are the SAME array, read once — they cannot
  // drift apart, and the count is never a different field's length.
  const rows = affectedComponents;
  const affectedLabel =
    rows.length === 0
      ? emptyLabel ?? "No components affected"
      : `${rows.length} component${rows.length === 1 ? "" : "s"} affected`;

  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-700">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="text-sm text-slate-400 mt-1">{affectedLabel}</p>
      </div>

      {/* Zero rows gets a sentence, not an empty table shell under a "0" count. */}
      {rows.length === 0 ? (
        <div className="px-6 py-6 text-sm text-slate-400">{emptyMessage}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/50 border-b border-slate-700">
              <tr>
                <th className="px-6 py-3 text-left text-slate-300 font-semibold">Component</th>
                <th className="px-6 py-3 text-left text-slate-300 font-semibold">Current Supplier</th>
                <th className="px-6 py-3 text-center text-slate-300 font-semibold">
                  Alternatives for this line
                </th>
                <th className="px-6 py-3 text-center text-slate-300 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {rows.map((comp) => {
                const alts = comp.alternative_suppliers;
                const expandable = alts.length > 0;
                return (
                  <Fragment key={comp.component_id}>
                    <tr
                      onClick={() => expandable && toggleRow(comp.component_id)}
                      className={`transition ${
                        expandable ? "hover:bg-slate-800/50 cursor-pointer" : ""
                      }`}
                    >
                      <td className="px-6 py-3 text-white font-medium">{comp.mpn}</td>
                      <td className="px-6 py-3 text-slate-400">
                        {comp.current_supplier ?? <span className="text-slate-500">unknown</span>}
                      </td>
                      <td className="px-6 py-3 text-center">
                        {alts.length === 0 ? (
                          <span className="text-red-400 font-medium">none available</span>
                        ) : (
                          <span className="text-slate-300">
                            {alts.length} option{alts.length === 1 ? "" : "s"}
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-3 text-center">
                        {expandable && (
                          <ChevronDown
                            size={18}
                            className={`transition transform ${
                              expandedRows.has(comp.component_id) ? "rotate-180" : ""
                            }`}
                          />
                        )}
                      </td>
                    </tr>
                    {expandable && expandedRows.has(comp.component_id) && (
                      <tr className="bg-slate-900/30">
                        <td colSpan={4} className="px-6 py-4">
                          <div className="space-y-2">
                            {alts.map((sup, idx) => (
                              <div
                                key={idx}
                                className="bg-slate-800/50 border border-slate-700 rounded p-3 flex justify-between items-center"
                              >
                                <div>
                                  <div className="text-white font-medium">{sup.name}</div>
                                  <div className="text-sm text-slate-400">
                                    Lead time: {sup.lead_time_days.toFixed(1)} days
                                  </div>
                                </div>
                                {sup.cost_delta_pct !== undefined && (
                                  <div
                                    className={`px-3 py-1 rounded text-sm font-semibold ${
                                      sup.cost_delta_pct > 0
                                        ? "bg-red-500/20 text-red-300"
                                        : "bg-green-500/20 text-green-300"
                                    }`}
                                  >
                                    {sup.cost_delta_pct > 0 ? "+" : ""}
                                    {sup.cost_delta_pct.toFixed(1)}%
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
