import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { DollarSign, Leaf, Clock, MapPin, ChevronUp, ChevronDown } from 'lucide-react';

interface RouteMetricsBarProps {
  totalCostUsd: number;
  totalCo2eKg: number;
  etaP50: number;
  stopCount: number;
}

export default function RouteMetricsBar({
  totalCostUsd,
  totalCo2eKg,
  etaP50,
  stopCount,
}: RouteMetricsBarProps) {
  const [expanded, setExpanded] = useState(true);

  const metrics = [
    {
      label: 'Total Cost',
      value: `$${totalCostUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      icon: <DollarSign className="w-4 h-4" />,
      color: 'text-green-400',
    },
    {
      label: 'CO₂ Emissions',
      value: `${totalCo2eKg.toFixed(1)} kg`,
      icon: <Leaf className="w-4 h-4" />,
      color: 'text-emerald-400',
    },
    {
      label: 'P50 ETA',
      value: `${etaP50}d`,
      icon: <Clock className="w-4 h-4" />,
      color: 'text-blue-400',
    },
    {
      label: 'Stops',
      value: `${stopCount}`,
      icon: <MapPin className="w-4 h-4" />,
      color: 'text-purple-400',
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 pointer-events-auto"
    >
      <div className="bg-black/50 backdrop-blur-xl border border-white/10 rounded-2xl shadow-[0_8px_32px_rgba(0,0,0,0.5)] overflow-hidden">
        <AnimatePresence mode="wait">
          {expanded ? (
            <motion.div
              key="expanded"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25 }}
            >
              <div className="flex items-center gap-5 px-5 py-3 pr-10">
                <span className="text-xs font-semibold text-blue-400 tracking-wide uppercase whitespace-nowrap">
                  Optimized Route
                </span>
                <div className="w-px h-8 bg-white/10" />
                {metrics.map((m, i) => (
                  <div key={m.label} className="flex items-center gap-2.5">
                    <span className={m.color}>{m.icon}</span>
                    <div>
                      <div className="text-[10px] text-slate-400 leading-none mb-0.5">{m.label}</div>
                      <div className="text-sm text-white font-semibold">{m.value}</div>
                    </div>
                    {i < metrics.length - 1 && (
                      <div className="w-px h-8 bg-white/10 ml-2" />
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="collapsed"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="px-5 py-2.5 pr-10"
            >
              <span className="text-xs text-slate-400 font-medium">Optimized Route</span>
            </motion.div>
          )}
        </AnimatePresence>

        <button
          onClick={() => setExpanded(!expanded)}
          className="absolute top-2 right-2 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
          aria-label={expanded ? 'Minimize' : 'Expand'}
        >
          {expanded
            ? <ChevronUp className="w-3 h-3 text-slate-400" />
            : <ChevronDown className="w-3 h-3 text-slate-400" />}
        </button>
      </div>
    </motion.div>
  );
}
