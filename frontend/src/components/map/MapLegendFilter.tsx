import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Layers, ChevronDown, ChevronUp, AlertCircle, AlertTriangle, XCircle, Info } from 'lucide-react';

export const HUB_TYPE_META: Record<string, { label: string; color: string }> = {
  semiconductor: { label: 'Semiconductor', color: '#3b82f6' },
  battery:       { label: 'Battery',       color: '#10b981' },
  rare_earth:    { label: 'Rare Earth',    color: '#f59e0b' },
  chemical:      { label: 'Chemical',      color: '#8b5cf6' },
  metal:         { label: 'Metal',         color: '#ef4444' },
  optical:       { label: 'Optical',       color: '#06b6d4' },
  pcb:           { label: 'PCB',           color: '#ec4899' },
  polymer:       { label: 'Polymer',       color: '#f97316' },
  distribution:  { label: 'Distribution',  color: '#6b7280' },
  thermal:       { label: 'Thermal',       color: '#14b8a6' },
};

const RISK_TIERS = [
  { id: 'low',      label: 'Low',      icon: <Info className="w-3 h-3" />,          color: 'text-green-400'  },
  { id: 'moderate', label: 'Moderate', icon: <AlertCircle className="w-3 h-3" />,   color: 'text-yellow-400' },
  { id: 'high',     label: 'High',     icon: <AlertTriangle className="w-3 h-3" />, color: 'text-orange-400' },
  { id: 'critical', label: 'Critical', icon: <XCircle className="w-3 h-3" />,       color: 'text-red-400'    },
];

interface MapLegendFilterProps {
  activeHubTypes: Set<string>;
  activeRiskTiers: Set<string>;
  onHubTypeToggle: (id: string) => void;
  onRiskTierToggle: (id: string) => void;
  showArcs: boolean;
  onToggleArcs: () => void;
  showDeckArcs: boolean;
  onToggleDeckArcs: () => void;
  hasRoute: boolean;
  hasFactory: boolean;
}

export default function MapLegendFilter({
  activeHubTypes,
  activeRiskTiers,
  onHubTypeToggle,
  onRiskTierToggle,
  showArcs,
  onToggleArcs,
  showDeckArcs,
  onToggleDeckArcs,
  hasRoute,
  hasFactory,
}: MapLegendFilterProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute bottom-4 left-4 z-10 w-72 pointer-events-auto"
    >
      <div className="bg-slate-900/95 backdrop-blur-md border border-slate-700/60 rounded-xl shadow-2xl overflow-hidden">
        {/* Header */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-400" />
            <span className="text-xs font-semibold text-slate-200 uppercase tracking-wide">
              Filters & Legend
            </span>
          </div>
          {collapsed
            ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" />
            : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />}
        </button>

        <AnimatePresence>
          {!collapsed && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-4 space-y-4 border-t border-slate-700/50">
                {/* Hub Types */}
                <div className="pt-3">
                  <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Hub Types
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(HUB_TYPE_META).map(([id, { label, color }]) => {
                      const active = activeHubTypes.has(id);
                      return (
                        <button
                          key={id}
                          onClick={() => onHubTypeToggle(id)}
                          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
                            active
                              ? 'bg-slate-700 text-slate-100 border border-slate-500 shadow-sm'
                              : 'bg-slate-800/50 text-slate-500 border border-slate-800'
                          }`}
                        >
                          <div
                            className="w-2 h-2 rounded-full flex-shrink-0 transition-colors"
                            style={{ backgroundColor: active ? color : '#475569' }}
                          />
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="h-px bg-slate-700/50" />

                {/* Risk Tiers */}
                <div>
                  <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Risk Tier
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {RISK_TIERS.map((rt) => {
                      const active = activeRiskTiers.has(rt.id);
                      return (
                        <button
                          key={rt.id}
                          onClick={() => onRiskTierToggle(rt.id)}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                            active
                              ? 'bg-slate-700 text-slate-100 border border-slate-500'
                              : 'bg-slate-800/50 text-slate-500 border border-slate-800'
                          }`}
                        >
                          <span className={active ? rt.color : 'text-slate-600'}>{rt.icon}</span>
                          {rt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Route arcs toggle */}
                {hasRoute && (
                  <>
                    <div className="h-px bg-slate-700/50" />
                    <button
                      onClick={onToggleArcs}
                      className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                        showArcs ? 'text-blue-400' : 'text-slate-500'
                      }`}
                    >
                      <div
                        className={`w-6 h-0.5 rounded-full transition-colors ${
                          showArcs ? 'bg-blue-500' : 'bg-slate-600'
                        }`}
                      />
                      {showArcs ? 'Hide' : 'Show'} route paths
                    </button>
                  </>
                )}

                <div className="h-px bg-slate-700/50" />
                <button
                  onClick={onToggleDeckArcs}
                  className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                    showDeckArcs ? 'text-amber-400' : 'text-slate-500'
                  }`}
                >
                  <div
                    className={`w-2.5 h-2.5 rounded-full transition-colors ${
                      showDeckArcs ? 'bg-amber-400' : 'bg-slate-600'
                    }`}
                  />
                  {showDeckArcs ? 'Hide' : 'Show'} hub risk arcs
                </button>

                {/* Factory marker */}
                {hasFactory && (
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <div className="w-3 h-3 rounded-full bg-white border-2 border-blue-500 flex-shrink-0" />
                    Your Factory
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
