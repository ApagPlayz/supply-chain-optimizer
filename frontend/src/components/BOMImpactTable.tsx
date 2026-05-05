import { Fragment, useState } from 'react';
import { ChevronDown } from 'lucide-react';

interface AlternativeSupplier {
  name: string;
  lead_time_days: number;
  cost_delta_pct: number;
}

interface AffectedComponent {
  component_id: number;
  mpn: string;
  current_supplier: string;
  alternative_suppliers: AlternativeSupplier[];
}

interface BOMImpactTableProps {
  affectedComponents: AffectedComponent[];
  title?: string;
}

export function BOMImpactTable({
  affectedComponents,
  title = "Affected BOM Components",
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

  return (
    <div className="bg-slate-800/70 border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-700">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="text-sm text-slate-400 mt-1">
          {affectedComponents.length} component(s) affected
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/50 border-b border-slate-700">
            <tr>
              <th className="px-6 py-3 text-left text-slate-300 font-semibold">Component</th>
              <th className="px-6 py-3 text-left text-slate-300 font-semibold">Current Supplier</th>
              <th className="px-6 py-3 text-center text-slate-300 font-semibold">Alternatives</th>
              <th className="px-6 py-3 text-center text-slate-300 font-semibold" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {affectedComponents.map((comp) => (
              <Fragment key={comp.component_id}>
                <tr
                  onClick={() => toggleRow(comp.component_id)}
                  className="hover:bg-slate-800/50 cursor-pointer transition"
                >
                  <td className="px-6 py-3 text-white font-medium">{comp.mpn}</td>
                  <td className="px-6 py-3 text-slate-400">{comp.current_supplier}</td>
                  <td className="px-6 py-3 text-center text-slate-300">
                    {comp.alternative_suppliers.length} option(s)
                  </td>
                  <td className="px-6 py-3 text-center">
                    <ChevronDown
                      size={18}
                      className={`transition transform ${
                        expandedRows.has(comp.component_id) ? "rotate-180" : ""
                      }`}
                    />
                  </td>
                </tr>
                {expandedRows.has(comp.component_id) && (
                  <tr className="bg-slate-900/30">
                    <td colSpan={4} className="px-6 py-4">
                      <div className="space-y-2">
                        {comp.alternative_suppliers.map((sup, idx) => (
                          <div
                            key={idx}
                            className="bg-slate-800/50 border border-slate-700 rounded p-3 flex justify-between items-center"
                          >
                            <div>
                              <div className="text-white font-medium">{sup.name}</div>
                              <div className="text-sm text-slate-400">
                                Lead time: {sup.lead_time_days} days
                              </div>
                            </div>
                            <div
                              className={`px-3 py-1 rounded text-sm font-semibold ${
                                sup.cost_delta_pct > 0
                                  ? "bg-red-500/20 text-red-300"
                                  : "bg-green-500/20 text-green-300"
                              }`}
                            >
                              {sup.cost_delta_pct > 0 ? "+" : ""}{sup.cost_delta_pct.toFixed(1)}%
                            </div>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
