import { motion, AnimatePresence } from 'framer-motion';
import { X, AlertCircle, AlertTriangle, XCircle, Info, Star } from 'lucide-react';
import { HUB_TYPE_META } from './MapLegendFilter';

interface Supplier {
  id: number;
  name: string;
  lead_time_days: number;
  reliability_score: number;
  risk_score: number;
  is_domestic: boolean;
}

interface Hub {
  id: number;
  name: string;
  city: string;
  state: string;
  latitude: number;
  longitude: number;
  hub_type: string;
  specialization: string;
  active_suppliers: number;
  risk_index: number;
  suppliers?: Supplier[];
}

interface HubDetailSidebarProps {
  hub: Hub | null;
  hubDetail: Hub | null;
  open: boolean;
  onClose: () => void;
}

function RiskBadge({ value }: { value: number }) {
  if (value < 0.25) return (
    <span className="flex items-center gap-1 text-green-400 text-xs font-medium">
      <Info className="w-3 h-3" /> Low
    </span>
  );
  if (value < 0.5) return (
    <span className="flex items-center gap-1 text-yellow-400 text-xs font-medium">
      <AlertCircle className="w-3 h-3" /> Moderate
    </span>
  );
  if (value < 0.75) return (
    <span className="flex items-center gap-1 text-orange-400 text-xs font-medium">
      <AlertTriangle className="w-3 h-3" /> High
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-red-400 text-xs font-medium">
      <XCircle className="w-3 h-3" /> Critical
    </span>
  );
}

function ReliabilityBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.8 ? '#10b981' : score >= 0.6 ? '#f59e0b' : '#ef4444';
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] text-slate-400 w-7 text-right">{pct}%</span>
    </div>
  );
}

export default function HubDetailSidebar({ hub, hubDetail, open, onClose }: HubDetailSidebarProps) {
  const meta = hub ? (HUB_TYPE_META[hub.hub_type] ?? { label: hub.hub_type, color: '#64748b' }) : null;

  // Compute avg lead time from suppliers
  const avgLead = hubDetail?.suppliers?.length
    ? Math.round(
        hubDetail.suppliers.reduce((s, sup) => s + sup.lead_time_days, 0) /
          hubDetail.suppliers.length
      )
    : null;

  return (
    <AnimatePresence>
      {open && hub && (
        <motion.div
          key="sidebar"
          initial={{ x: '100%', opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: '100%', opacity: 0 }}
          transition={{ type: 'spring', stiffness: 320, damping: 32 }}
          className="absolute top-0 right-0 h-full w-80 bg-slate-900/98 backdrop-blur-md border-l border-slate-700/60 shadow-2xl z-20 flex flex-col overflow-hidden pointer-events-auto"
        >
          {/* Header */}
          <div className="flex items-start justify-between p-5 border-b border-slate-700/50">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <div
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: meta?.color }}
                />
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider capitalize">
                  {meta?.label} Hub
                </span>
              </div>
              <h2 className="text-sm font-semibold text-white leading-tight truncate">{hub.name}</h2>
              <p className="text-xs text-slate-400 mt-0.5">{hub.city}, {hub.state}</p>
            </div>
            <button
              onClick={onClose}
              className="ml-3 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors flex-shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* KPI Grid */}
          <div className="grid grid-cols-3 gap-2 p-4 border-b border-slate-700/50">
            <div className="bg-slate-800/60 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-white">{hub.active_suppliers}</div>
              <div className="text-[10px] text-slate-400 mt-0.5">Suppliers</div>
            </div>
            <div className="bg-slate-800/60 rounded-lg p-3 text-center">
              <div className="text-lg font-bold">
                <RiskBadge value={hub.risk_index} />
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">Risk</div>
            </div>
            <div className="bg-slate-800/60 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-white">
                {avgLead !== null ? `${avgLead}d` : '—'}
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">Avg Lead</div>
            </div>
          </div>

          {/* Risk Score Bar */}
          <div className="px-4 py-3 border-b border-slate-700/50">
            <div className="flex justify-between items-center mb-1.5">
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Risk Index</span>
              <span className="text-xs text-slate-300">{(hub.risk_index * 100).toFixed(0)}%</span>
            </div>
            <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${hub.risk_index * 100}%` }}
                transition={{ duration: 0.6, delay: 0.2 }}
                className="h-full rounded-full"
                style={{
                  background: hub.risk_index < 0.25
                    ? '#10b981'
                    : hub.risk_index < 0.5
                    ? '#f59e0b'
                    : hub.risk_index < 0.75
                    ? '#f97316'
                    : '#ef4444',
                }}
              />
            </div>
          </div>

          {/* Specializations */}
          <div className="px-4 py-3 border-b border-slate-700/50">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Primary Materials
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(hub.specialization || '').split(',').map((s, i) => (
                <span
                  key={i}
                  className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-700/70 text-slate-300 border border-slate-600/50"
                >
                  {s.trim()}
                </span>
              ))}
            </div>
          </div>

          {/* Supplier List */}
          <div className="flex-1 overflow-y-auto">
            <div className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                  Top Suppliers
                </div>
                {hubDetail?.suppliers && (
                  <span className="text-[10px] text-slate-500">
                    {Math.min(hubDetail.suppliers.length, 8)} of {hubDetail.suppliers.length}
                  </span>
                )}
              </div>

              {!hubDetail ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="bg-slate-800/40 rounded-lg p-3 animate-pulse h-14" />
                  ))}
                </div>
              ) : (
                <div className="space-y-2">
                  {(hubDetail.suppliers ?? []).slice(0, 8).map((sup, idx) => (
                    <motion.div
                      key={sup.id}
                      initial={{ opacity: 0, x: 12 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: idx * 0.04 }}
                      className="bg-slate-800/50 border border-slate-700/40 rounded-lg p-3 hover:bg-slate-800 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <span className="text-xs text-white font-medium leading-tight truncate">
                          {sup.name}
                        </span>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          {sup.is_domestic ? (
                            <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">
                              DOM
                            </span>
                          ) : (
                            <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-slate-700 text-slate-400 border border-slate-600">
                              INT
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1.5">
                        <span>Lead: <span className="text-slate-300">{sup.lead_time_days}d</span></span>
                        <span className="flex items-center gap-1">
                          <Star className="w-2.5 h-2.5 text-slate-500" />
                          Reliability
                        </span>
                      </div>
                      <ReliabilityBar score={sup.reliability_score} />
                    </motion.div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
