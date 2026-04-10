import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, X } from 'lucide-react';

interface DistributorPin {
  id: number;
  name: string;
  city: string | null;
  state: string | null;
  country: string;
  latitude: number;
  longitude: number;
  is_domestic: boolean;
  total_offers: number;
  total_stock: number;
}

interface Props {
  distributors: DistributorPin[];
  onSelect: (dist: DistributorPin) => void;
}

function useDebounce<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

const container = {
  hidden: { opacity: 0, height: 0 },
  show: {
    opacity: 1,
    height: 'auto',
    transition: { height: { duration: 0.3 }, staggerChildren: 0.04 },
  },
  exit: {
    opacity: 0,
    height: 0,
    transition: { height: { duration: 0.25 }, opacity: { duration: 0.15 } },
  },
};

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2 } },
  exit: { opacity: 0, y: -6, transition: { duration: 0.15 } },
};

export default function DistributorSearchBar({ distributors, onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [focused, setFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const debouncedQuery = useDebounce(query, 200);

  const results = debouncedQuery.trim()
    ? distributors
        .filter((d) => d.name.toLowerCase().includes(debouncedQuery.toLowerCase().trim()))
        .slice(0, 8)
    : focused
    ? distributors.slice(0, 8)
    : [];

  const showDropdown = focused && results.length > 0;

  const handleSelect = useCallback(
    (dist: DistributorPin) => {
      onSelect(dist);
      setQuery('');
      setFocused(false);
      setActiveIndex(-1);
      inputRef.current?.blur();
    },
    [onSelect]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDropdown) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(results[activeIndex]);
    } else if (e.key === 'Escape') {
      setQuery('');
      setFocused(false);
      setActiveIndex(-1);
      inputRef.current?.blur();
    }
  };

  return (
    <div className="w-full max-w-sm mx-auto">
      {/* Input */}
      <div className="relative">
        <div className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none">
          <Search className="w-4 h-4 text-slate-400" />
        </div>
        <input
          ref={inputRef}
          type="text"
          placeholder="Search distributors..."
          value={query}
          onChange={(e) => { setQuery(e.target.value); setActiveIndex(-1); }}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          onKeyDown={handleKeyDown}
          className="w-full pl-9 pr-8 py-2 h-9 text-sm rounded-lg bg-black/60 backdrop-blur-md border border-white/10 text-white placeholder-slate-400 focus:outline-none focus:border-blue-500/60 focus:bg-black/70 transition-all shadow-lg"
        />
        <AnimatePresence mode="popLayout">
          {query.length > 0 && (
            <motion.button
              key="clear"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.15 }}
              onClick={() => { setQuery(''); setActiveIndex(-1); inputRef.current?.focus(); }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </motion.button>
          )}
        </AnimatePresence>
      </div>

      {/* Dropdown */}
      <AnimatePresence>
        {showDropdown && (
          <motion.div
            variants={container}
            initial="hidden"
            animate="show"
            exit="exit"
            className="absolute mt-1.5 w-full max-w-sm rounded-xl border border-white/10 bg-black/80 backdrop-blur-xl shadow-2xl overflow-hidden z-50"
          >
            <motion.ul className="py-1">
              {results.map((dist, idx) => (
                <motion.li
                  key={dist.id}
                  variants={item}
                  layout
                  onMouseDown={() => handleSelect(dist)}
                  onMouseEnter={() => setActiveIndex(idx)}
                  className={`flex items-center justify-between px-3 py-2 cursor-pointer transition-colors ${
                    activeIndex === idx ? 'bg-white/10' : 'hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {/* Domestic / international dot */}
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: dist.is_domestic ? '#3b82f6' : '#f59e0b' }}
                    />
                    <div className="min-w-0">
                      <span className="text-sm font-medium text-white truncate block">{dist.name}</span>
                      <span className="text-xs text-slate-400 truncate block">
                        {[dist.city, dist.state, dist.country].filter(Boolean).join(', ')}
                      </span>
                    </div>
                  </div>
                  <span className="ml-2 flex-shrink-0 text-[10px] text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded font-medium">
                    {dist.total_offers} offers
                  </span>
                </motion.li>
              ))}
            </motion.ul>
            <div className="px-3 py-1.5 border-t border-white/5 flex items-center justify-between text-[10px] text-slate-600">
              <span>↑↓ navigate</span>
              <span>↵ fly to · ESC close</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
