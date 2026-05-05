import { type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';

interface ScenarioCardProps {
  title: string;
  loading: boolean;
  error: string | null;
  children: ReactNode;
}

export function ScenarioCard({ title, loading, error, children }: ScenarioCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
      className="bg-slate-800/70 border border-slate-700 rounded-xl p-6 backdrop-blur-sm"
    >
      <h3 className="text-lg font-semibold text-white mb-4">{title}</h3>

      {loading && (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-600 border-t-blue-400" />
          <span className="ml-3 text-slate-400">Recalculating...</span>
        </div>
      )}

      {error && (
        <div className="bg-red-500/20 border border-red-400 rounded px-4 py-3 text-red-300 flex gap-2">
          <AlertTriangle size={20} className="flex-shrink-0" />
          <div>
            <p className="font-semibold">Error</p>
            <p className="text-sm">{error}</p>
          </div>
        </div>
      )}

      {!loading && !error && children}
    </motion.div>
  );
}
