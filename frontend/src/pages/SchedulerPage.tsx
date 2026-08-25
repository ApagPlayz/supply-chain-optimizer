import { useEffect, useState, useCallback } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { RefreshCw, Zap, ShieldCheck, ShieldAlert, CheckCircle2, AlertTriangle } from 'lucide-react';
import { componentsAPI, livePricesAPI, demandAPI } from '../services/api';
import type { LivePriceResponse, DemandBenchmarkResponse } from '../services/api';
import { useCartStore } from '../store/cartStore';

interface ComponentItem {
  id: number;
  mpn: string;
  manufacturer: string;
  manufacturer_country: string | null;
  category: string;
  description: string | null;
  risk_score: number;
  risk_factors: string[] | null;
  min_price: number | null;
  max_price: number | null;
  num_offers: number;
}

interface Offer {
  id: number;
  distributor_id: number;
  distributor_name: string;
  distributor_city: string | null;
  distributor_state: string | null;
  distributor_country: string | null;
  is_domestic: boolean;
  price: number;
  stock: number;
  sku: string | null;
  currency: string | null;
}

interface ComponentDetail {
  id: number;
  mpn: string;
  manufacturer: string;
  manufacturer_country: string | null;
  category: string;
  description: string | null;
  datasheets: string[] | null;
  risk_score: number;
  risk_factors: string[] | null;
  offers: Offer[];
}

// Component unit prices are genuinely sub-cent for passives (the catalog's
// cheapest real offer is $0.0031, and 46% of offers carry more than two
// decimals), so money is rendered with 2–4 decimals: always at least cents,
// extra digits only when the real price actually has them. That keeps
// "$16.16" from rendering as "$16.1600" while never rounding a part to $0.00.
const fmtUnitPrice = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;

// Whole-dollar money (line/order totals) always shows exactly two decimals.
const fmtUsd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const plural = (n: number, singular: string, pluralForm = `${singular}s`) =>
  `${n.toLocaleString()} ${n === 1 ? singular : pluralForm}`;

function riskColor(r: number) {
  if (r < 0.3) return 'text-green-400';
  if (r < 0.6) return 'text-yellow-400';
  return 'text-red-400';
}

function riskBadge(r: number) {
  if (r < 0.3) return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (r < 0.6) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  return 'bg-red-500/20 text-red-400 border-red-500/30';
}

// ── Demand model panel ──────────────────────────────────────────────────────
// Fed by demandAPI.benchmark() — the real intermittent-demand method
// benchmark that replaced the retired per-part forecasts API surface. It is a
// fleet-wide benchmark of demand *methods* on the Monash car-parts panel, not
// a per-part forecast for these electronic components (no public per-SKU
// demand series exists for them). See backend/app/api/demand.py.
function DemandModelPanel() {
  const [state, setState] = useState<'loading' | 'unavailable' | 'error' | 'loaded'>('loading');
  const [data, setData] = useState<DemandBenchmarkResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    demandAPI
      .benchmark()
      .then((res) => {
        setData(res.data);
        setState('loaded');
      })
      .catch((err: unknown) => {
        const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
        if (axiosErr?.response?.status === 503) {
          setErrorMsg(axiosErr.response?.data?.detail || 'Demand benchmark not available in this deployment.');
          setState('unavailable');
        } else {
          setErrorMsg('Failed to load demand benchmark.');
          setState('error');
        }
      });
  }, []);

  if (state === 'loading') {
    return (
      <div className="border-b border-slate-700 bg-slate-800/60 px-5 py-3 text-xs text-slate-500">
        Loading demand model benchmark…
      </div>
    );
  }

  if (state === 'unavailable' || state === 'error') {
    return (
      <div className="border-b border-slate-700 bg-slate-800/60 px-5 py-3">
        <div className="flex items-center gap-2 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>
            {state === 'unavailable'
              ? 'Demand model benchmark not available in this deployment.'
              : 'Demand model benchmark failed to load.'}
            {errorMsg ? ` ${errorMsg}` : ''}
          </span>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const crpsMcb = data.mcb.find((m) => m.metric === 'crps') ?? null;
  const rankChartData = data.methods.map((m) => ({
    name: m.name,
    'Rank (MASE)': m.rank_mase,
    'Rank (CRPS)': m.rank_crps,
  }));

  return (
    <div className="border-b border-slate-700 bg-slate-800/40">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-700/30 transition-colors"
      >
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white">Demand model</div>
          <div className="text-xs text-slate-400 truncate mt-0.5">{data.headline}</div>
        </div>
        <span className="text-xs text-slate-500 shrink-0 ml-3">{expanded ? 'Hide details −' : 'Show details +'}</span>
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4">
          {/* Framing */}
          <p className="text-xs text-slate-400 bg-slate-900/40 border border-slate-700/60 rounded-lg p-3">
            This is a benchmark of intermittent-demand <em>methods</em>, scored on a real spare-parts
            sales panel (car parts, not electronics) — it is not a per-part demand forecast for the
            components in this catalog. No public per-SKU demand series exists for these electronic
            components, so none is claimed here.
          </p>

          {/* Point vs proper-scoring winner callout */}
          <div
            className={`flex items-start gap-2 text-xs rounded-lg p-3 border ${
              data.ranking_changed
                ? 'bg-amber-500/5 border-amber-500/20 text-amber-300'
                : 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300'
            }`}
          >
            {data.ranking_changed ? (
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            ) : (
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            )}
            <span>
              {data.ranking_changed ? (
                <>
                  The point-accuracy (MASE) winner is <strong>{data.point_winner}</strong>, but the
                  proper-scoring (CRPS) winner is <strong>{data.distributional_winner}</strong> — picking
                  by MASE alone would choose the wrong method for modeling the full demand distribution.
                </>
              ) : (
                <>
                  The ranking is unchanged under proper scoring — MASE and CRPS agree that{' '}
                  <strong>{data.point_winner}</strong> is best.
                </>
              )}
            </span>
          </div>

          {/* Leaderboard */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 uppercase tracking-wider border-b border-slate-700">
                  <th className="text-left py-1.5 pr-3">Method</th>
                  <th className="text-right py-1.5 px-2">MASE mean</th>
                  <th className="text-right py-1.5 px-2">MASE median</th>
                  <th className="text-right py-1.5 px-2">CRPS mean</th>
                  <th className="text-right py-1.5 px-2">SPL mean</th>
                  <th className="text-right py-1.5 px-2">Rank (MASE)</th>
                  <th className="text-right py-1.5 pl-2">Rank (CRPS)</th>
                </tr>
              </thead>
              <tbody>
                {data.methods.map((m) => (
                  <tr key={m.name} className="border-b border-slate-800">
                    <td className="py-1.5 pr-3">
                      <span
                        className="text-white cursor-help border-b border-dotted border-slate-600"
                        title={m.assumption}
                      >
                        {m.name}
                      </span>
                      {m.name === data.point_winner && (
                        <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
                          MASE best
                        </span>
                      )}
                      {m.name === data.distributional_winner && (
                        <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                          CRPS best
                        </span>
                      )}
                    </td>
                    <td className="text-right py-1.5 px-2 text-slate-300">{m.mase_mean.toFixed(3)}</td>
                    <td className="text-right py-1.5 px-2 text-slate-300">{m.mase_median.toFixed(3)}</td>
                    <td className="text-right py-1.5 px-2 text-slate-300">{m.crps_mean.toFixed(3)}</td>
                    <td className="text-right py-1.5 px-2 text-slate-300">{m.spl_mean.toFixed(3)}</td>
                    <td className="text-right py-1.5 px-2 text-slate-400">{m.rank_mase.toFixed(2)}</td>
                    <td className="text-right py-1.5 pl-2 text-slate-400">{m.rank_crps.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mean rank comparison — real returned numbers, no synthetic data */}
          <div className="bg-slate-900/40 border border-slate-700/60 rounded-lg p-3">
            <div className="text-xs text-slate-400 mb-2">Mean Friedman rank by metric (lower = better)</div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={rankChartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    border: '1px solid #475569',
                    borderRadius: '8px',
                    padding: '12px',
                    fontSize: '12px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                <Bar dataKey="Rank (MASE)" fill="#60a5fa" />
                <Bar dataKey="Rank (CRPS)" fill="#34d399" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* MCB — CRPS */}
          {crpsMcb && (
            <div className="text-xs text-slate-400 bg-slate-900/40 border border-slate-700/60 rounded-lg p-3">
              <span className="text-slate-300 font-medium">
                Friedman rank test (Nemenyi critical differences), CRPS:{' '}
              </span>
              n = {crpsMcb.n_series} series, p ={' '}
              {crpsMcb.friedman_p < 0.001 ? '< 0.001' : crpsMcb.friedman_p.toFixed(4)}, critical difference ={' '}
              {crpsMcb.critical_difference.toFixed(3)}.
            </div>
          )}

          {/* Dataset provenance */}
          <div className="text-xs text-slate-500 bg-slate-900/40 border border-slate-700/60 rounded-lg p-3 space-y-1">
            <div>
              <span className="text-slate-300 font-medium">{data.dataset.name}</span> — {data.dataset.source} (
              {data.dataset.license})
            </div>
            <div>
              {data.dataset.n_series.toLocaleString()} series × {data.dataset.series_length} periods,{' '}
              {(data.dataset.nonzero_fraction * 100).toFixed(1)}% non-zero
            </div>
            <div className="font-mono text-[11px] text-slate-500 mt-1.5 bg-slate-950/60 rounded px-2 py-1 overflow-x-auto">
              {data.reproduce_command}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SchedulerPage() {
  const { addItem } = useCartStore();
  const [components, setComponents] = useState<ComponentItem[]>([]);
  const [categories, setCategories] = useState<{ name: string; count: number }[]>([]);
  const [selectedCat, setSelectedCat] = useState('All');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<ComponentDetail | null>(null);
  const [qty, setQty] = useState(1);
  const [selectedOfferId, setSelectedOfferId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [addedMsg, setAddedMsg] = useState('');
  // Errors get their own state: a success message may fade, a failure must not.
  const [addError, setAddError] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [failedComponent, setFailedComponent] = useState<ComponentItem | null>(null);
  const [domesticOnly, setDomesticOnly] = useState(false);

  // ── Live pricing (Nexar / DigiKey / OEMsecrets / TrustedParts) ─────────────
  // Pulled on demand — the static offers above are a frozen 2024 HuggingFace
  // snapshot; this hits real distributor APIs right now.
  const [liveState, setLiveState] = useState<'idle' | 'loading' | 'loaded' | 'not_found' | 'unconfigured' | 'error'>('idle');
  const [liveData, setLiveData] = useState<LivePriceResponse | null>(null);
  const [liveErrorMsg, setLiveErrorMsg] = useState<string>('');
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');

  useEffect(() => {
    Promise.all([
      componentsAPI.list(),
      componentsAPI.categories(),
    ]).then(([cRes, catRes]) => {
      setComponents(cRes.data);
      setCategories(catRes.data);
      setLoading(false);
    }).catch((err) => {
      console.error('Initial load failed:', err);
      setLoading(false);
    });
  }, []);

  const selectComponent = useCallback(async (comp: ComponentItem) => {
    setSelectedOfferId(null);
    setQty(1);
    setAddedMsg('');
    setAddError('');
    setDetailLoading(true);
    setDetailError(null);
    // Reset live-price state — it's per-component and must not leak across selections.
    setLiveState('idle');
    setLiveData(null);
    setLiveErrorMsg('');
    setSyncMsg('');
    try {
      const res = await componentsAPI.get(comp.id);
      setSelected(res.data);
      setFailedComponent(null);
    } catch (err: unknown) {
      // Without this the request could reject, leave "Loading offers..." on screen
      // forever and surface as an unhandled promise rejection.
      const axiosErr = err as { response?: { status?: number; data?: { detail?: unknown } } };
      const detail = axiosErr?.response?.data?.detail;
      setSelected(null);
      setFailedComponent(comp);
      setDetailError(
        typeof detail === 'string' && detail.trim()
          ? detail
          : `Could not load offers for ${comp.mpn}${axiosErr?.response?.status ? ` (HTTP ${axiosErr.response.status})` : ''}.`,
      );
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const fetchLivePrices = useCallback(async () => {
    if (!selected) return;
    setLiveState('loading');
    setLiveErrorMsg('');
    try {
      const res = await livePricesAPI.get(selected.mpn);
      setLiveData(res.data);
      setLiveState('loaded');
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: unknown } } };
      const status = axiosErr?.response?.status;
      const detail = axiosErr?.response?.data?.detail;
      if (status === 404) {
        setLiveState('not_found');
        setLiveErrorMsg(typeof detail === 'string' ? detail : `No live offers found for ${selected.mpn} today.`);
      } else if (status === 503) {
        setLiveState('unconfigured');
        setLiveErrorMsg(typeof detail === 'string' ? detail : 'No live pricing sources configured.');
      } else {
        setLiveState('error');
        setLiveErrorMsg(typeof detail === 'string' ? detail : 'Live price lookup failed — try again.');
      }
    }
  }, [selected]);

  const syncToDatabase = useCallback(async () => {
    if (!selected) return;
    setSyncing(true);
    setSyncMsg('');
    try {
      const res = await livePricesAPI.sync(selected.mpn);
      const { db_offers_updated = 0, db_offers_created = 0 } = res.data;
      if (db_offers_updated || db_offers_created) {
        setSyncMsg(`Saved: ${plural(db_offers_updated, 'offer')} updated, ${db_offers_created} created.`);
        // Re-pull the component so the static offers list reflects the new prices.
        const refreshed = await componentsAPI.get(selected.id);
        setSelected(refreshed.data);
      } else {
        setSyncMsg(res.data.message || 'No matching distributors in the catalog to update.');
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setSyncMsg(axiosErr?.response?.data?.detail || 'Sync failed — try again.');
    } finally {
      setSyncing(false);
    }
  }, [selected]);

  const selectedOffer = selected?.offers.find((o) => o.id === selectedOfferId) ?? null;

  // The server rejects these with a 422 (see POST /api/v1/cart). Knowing why the
  // button is dead is the difference between "out of stock" and "the site is
  // broken", so the same rule is evaluated here and stated on the button.
  const outOfStock = !!selectedOffer && selectedOffer.stock === 0;
  const overStock = !!selectedOffer && selectedOffer.stock > 0 && qty > selectedOffer.stock;
  const canAdd = !!selectedOffer && !outOfStock && !overStock && qty >= 1;

  const handleAddToCart = async () => {
    if (!selected || !selectedOffer || !canAdd) return;
    setAdding(true);
    setAddError('');
    try {
      await addItem({
        component_id: selected.id,
        distributor_id: selectedOffer.distributor_id,
        quantity: qty,
        unit_price: selectedOffer.price,
      });
      setAddedMsg('Added to cart!');
      setTimeout(() => setAddedMsg(''), 2500);
    } catch (err: unknown) {
      // Stays on screen until the next attempt — no timer, no silent 422.
      setAddError(err instanceof Error && err.message ? err.message : 'Failed to add to cart');
      setAddedMsg('');
    } finally {
      setAdding(false);
    }
  };

  // Filter + search
  const visible = components.filter((c) => {
    const catOk = selectedCat === 'All' || c.category === selectedCat;
    const searchOk =
      !search ||
      c.mpn.toLowerCase().includes(search.toLowerCase()) ||
      c.manufacturer.toLowerCase().includes(search.toLowerCase()) ||
      (c.description || '').toLowerCase().includes(search.toLowerCase());
    return catOk && searchOk;
  });

  // Filter offers by domestic preference
  const filteredOffers = selected
    ? selected.offers.filter((o) => !domesticOnly || o.is_domestic)
    : [];

  const cheapestOffer = filteredOffers.length > 0 ? filteredOffers[0] : null;

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-100">
      <DemandModelPanel />
      <div className="flex flex-1 min-h-0">
      {/* Left panel: component list */}
      <div className="w-80 border-r border-slate-700 flex flex-col">
        <div className="p-3 border-b border-slate-700 space-y-2">
          <input
            type="text"
            placeholder="Search components, MPN, manufacturer..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
          />
          <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
            <button
              onClick={() => setSelectedCat('All')}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                selectedCat === 'All' ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              All ({components.length})
            </button>
            {categories.map((cat) => (
              <button
                key={cat.name}
                onClick={() => setSelectedCat(cat.name)}
                className={`text-xs px-2 py-0.5 rounded transition-colors ${
                  selectedCat === cat.name ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                {cat.name} ({cat.count})
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading && <div className="p-4 text-center text-slate-400 text-sm">Loading components...</div>}
          {visible.map((comp) => (
            <button
              key={comp.id}
              onClick={() => { void selectComponent(comp); }}
              className={`w-full text-left px-3 py-2.5 border-b border-slate-700/50 hover:bg-slate-700/40 transition-colors ${
                selected?.id === comp.id ? 'bg-slate-700/60 border-l-2 border-l-blue-500' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-1">
                <div>
                  <div className="text-sm text-white font-medium leading-tight">{comp.mpn}</div>
                  <div className="text-xs text-slate-400">{comp.manufacturer}</div>
                </div>
                <div className="text-right shrink-0">
                  {comp.min_price != null && (
                    <div className="text-xs text-green-400 font-medium">{fmtUnitPrice(comp.min_price)}</div>
                  )}
                  <div className="text-xs text-slate-500">{plural(comp.num_offers, 'offer')}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-slate-500 truncate">{comp.category}</span>
                {comp.risk_score > 0.5 && (
                  <span className={`text-xs px-1.5 py-0.5 rounded border ${riskBadge(comp.risk_score)}`}>
                    Risk
                  </span>
                )}
              </div>
            </button>
          ))}
          {!loading && visible.length === 0 && (
            <div className="p-4 text-center text-slate-500 text-sm">No components found</div>
          )}
        </div>
        <div className="px-3 py-2 text-xs text-slate-500 border-t border-slate-700">
          {visible.length} of {components.length} components
        </div>
      </div>

      {/* Right panel: detail */}
      <div className="flex-1 overflow-y-auto p-5">
        {!selected && detailLoading && (
          <div className="h-full flex items-center justify-center">
            <div className="w-7 h-7 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          </div>
        )}

        {/* Component detail failed to load — an explicit, recoverable state rather
            than a stuck "Loading offers..." with a rejected promise behind it. */}
        {!selected && !detailLoading && detailError && (
          <div className="h-full flex items-center justify-center" data-testid="component-detail-error">
            <div className="max-w-md text-center bg-red-900/20 border border-red-700/50 rounded-lg p-5">
              <div className="text-sm font-semibold text-red-300">Couldn&apos;t load this component</div>
              <div className="text-xs text-red-200/80 mt-1.5">{detailError}</div>
              {failedComponent && (
                <button
                  onClick={() => { void selectComponent(failedComponent); }}
                  className="mt-4 inline-flex items-center gap-1.5 bg-red-600/80 hover:bg-red-500 text-white text-xs font-medium px-3 py-1.5 rounded transition-colors"
                >
                  Retry
                </button>
              )}
            </div>
          </div>
        )}

        {!selected && !detailLoading && !detailError && (
          <div className="h-full flex items-center justify-center text-slate-500">
            <div className="text-center">
              <div className="text-4xl mb-3">&#9881;</div>
              <div className="text-lg font-medium text-slate-400">Select a component</div>
              <div className="text-sm mt-1">Browse {components.length} electronic components with real distributor pricing</div>
            </div>
          </div>
        )}

        {selected && (
          <div className="flex gap-5">
            {/* Left column: info + offers */}
            <div className="flex-1 min-w-0 space-y-5">
              {/* Header */}
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-xl font-bold text-white">{selected.mpn}</h1>
                  {selected.manufacturer_country && (
                    <span className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded">
                      {selected.manufacturer_country}
                    </span>
                  )}
                </div>
                <p className="text-slate-400 text-sm mt-0.5">
                  {selected.manufacturer} &middot; {selected.category}
                </p>
                {selected.description && (
                  <p className="text-slate-500 text-sm mt-1">{selected.description}</p>
                )}
              </div>

              {/* Risk + metadata */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1">Risk Score</div>
                  <div className={`text-lg font-bold ${riskColor(selected.risk_score)}`}>
                    {(selected.risk_score * 100).toFixed(0)}%
                  </div>
                </div>
                <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1">Distributors</div>
                  <div className="text-lg font-bold text-white">{selected.offers.length}</div>
                </div>
                <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1">Price Range</div>
                  <div className="text-sm font-bold text-white">
                    {selected.offers.length > 0
                      ? `${fmtUnitPrice(selected.offers[0].price)} – ${fmtUnitPrice(selected.offers[selected.offers.length - 1].price)}`
                      : 'N/A'}
                  </div>
                </div>
              </div>

              {/* Risk factors */}
              {selected.risk_factors && selected.risk_factors.length > 0 && (
                <div className="flex gap-2 flex-wrap">
                  {selected.risk_factors.map((rf) => (
                    <span key={rf} className="text-xs bg-red-900/30 border border-red-700/50 text-red-300 px-2 py-1 rounded">
                      {rf.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              )}

              {/* Distributor offers table */}
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-white">
                    Distributor Offers ({filteredOffers.length})
                  </h3>
                  <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={domesticOnly}
                      onChange={(e) => setDomesticOnly(e.target.checked)}
                      className="rounded bg-slate-700 border-slate-600"
                    />
                    US Domestic Only
                  </label>
                </div>
                {detailLoading ? (
                  <div className="text-slate-500 text-sm text-center py-4">Loading offers...</div>
                ) : detailError ? (
                  <div className="text-center py-4">
                    <div className="text-red-300 text-sm">{detailError}</div>
                    {failedComponent && (
                      <button
                        onClick={() => { void selectComponent(failedComponent); }}
                        className="mt-2 text-xs text-red-200 underline hover:text-white"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[420px] overflow-y-auto">
                    {filteredOffers.map((offer, i) => (
                      <button
                        key={offer.id}
                        onClick={() => { setSelectedOfferId(offer.id); setAddError(''); setAddedMsg(''); }}
                        className={`w-full text-left rounded-lg p-3 border transition-colors ${
                          selectedOfferId === offer.id
                            ? 'bg-blue-900/40 border-blue-500/60'
                            : 'bg-slate-700/40 border-slate-600/40 hover:bg-slate-700/60'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {i === 0 && (
                              <span className="text-xs bg-green-600 text-white px-1.5 py-0.5 rounded font-medium">
                                Best Price
                              </span>
                            )}
                            <span className="text-sm font-medium text-white">{offer.distributor_name}</span>
                            {offer.is_domestic && (
                              <span className="text-xs text-blue-400">US</span>
                            )}
                            {!offer.is_domestic && (
                              <span className="text-xs text-slate-500">{offer.distributor_country}</span>
                            )}
                          </div>
                          <span className="text-sm font-bold text-green-400">
                            {fmtUnitPrice(offer.price)}
                          </span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-slate-400">
                          <div>
                            Stock:{' '}
                            {offer.stock === 0
                              ? <span className="text-amber-300 font-medium">0 · out of stock</span>
                              : <span className="text-white">{offer.stock.toLocaleString()}</span>}
                          </div>
                          <div>SKU: <span className="text-white">{offer.sku || '—'}</span></div>
                          <div>
                            {offer.distributor_city && offer.distributor_state
                              ? `${offer.distributor_city}, ${offer.distributor_state}`
                              : offer.distributor_country || '—'}
                          </div>
                        </div>
                        {cheapestOffer && offer.price > cheapestOffer.price && (
                          <div className="text-xs text-red-400 mt-1">
                            +{((offer.price - cheapestOffer.price) / cheapestOffer.price * 100).toFixed(1)}% vs best price
                          </div>
                        )}
                      </button>
                    ))}
                    {filteredOffers.length === 0 && (
                      <div className="text-slate-500 text-sm text-center py-4">
                        No {domesticOnly ? 'domestic ' : ''}distributors found
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Live pricing — real-time multi-distributor lookup, on demand */}
              <div className="mt-5">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h3 className="text-sm font-semibold text-white flex items-center gap-1.5">
                      <Zap className="w-3.5 h-3.5 text-amber-400" />
                      Live Pricing
                    </h3>
                    <p className="text-slate-500 text-xs mt-0.5">
                      Offers above are a frozen 2024 snapshot (CC-BY-4.0). This pulls today&rsquo;s real prices
                      from Nexar, DigiKey, OEMsecrets &amp; TrustedParts.
                    </p>
                  </div>
                  <button
                    onClick={fetchLivePrices}
                    disabled={liveState === 'loading'}
                    className="shrink-0 inline-flex items-center gap-1.5 bg-amber-500/10 hover:bg-amber-500/20 disabled:opacity-50 border border-amber-500/30 text-amber-400 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${liveState === 'loading' ? 'animate-spin' : ''}`} />
                    {liveState === 'loading' ? 'Fetching live prices…' : liveState === 'loaded' ? 'Refresh live price' : 'Get live price'}
                  </button>
                </div>

                {liveState === 'idle' && (
                  <div className="text-slate-500 text-xs bg-slate-800/40 border border-slate-700/60 border-dashed rounded-lg p-3 text-center">
                    Not fetched yet — click &ldquo;Get live price&rdquo; to query real distributor APIs for {selected.mpn}.
                  </div>
                )}

                {(liveState === 'not_found' || liveState === 'unconfigured' || liveState === 'error') && (
                  <div className="text-xs bg-slate-800/60 border border-slate-700 rounded-lg p-3 text-slate-400">
                    {liveState === 'unconfigured' ? (
                      <>No live pricing sources configured on the backend. {liveErrorMsg}</>
                    ) : liveState === 'not_found' ? (
                      <>{liveErrorMsg} This part may not be carried by the currently-configured distributors.</>
                    ) : (
                      <span className="text-red-400">{liveErrorMsg}</span>
                    )}
                  </div>
                )}

                {liveState === 'loaded' && liveData && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="inline-flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[11px] px-2 py-0.5 rounded-full">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 motion-safe:animate-pulse" />
                        Live &middot; fetched just now
                      </span>
                      <span className="text-[11px] text-slate-500">
                        {plural(liveData.total_offers, 'offer')} from {liveData.sources_used.join(', ') || '—'}
                      </span>
                    </div>
                    {liveData.offers.length > 0 && (
                      <div className="flex items-center justify-between mb-2 gap-2">
                        <button
                          onClick={syncToDatabase}
                          disabled={syncing}
                          className="text-[11px] inline-flex items-center gap-1.5 text-slate-400 hover:text-white disabled:opacity-50 transition-colors"
                          title="Write these live prices into the component's catalog offers"
                        >
                          {syncing ? 'Saving to catalog…' : 'Save live prices to catalog →'}
                        </button>
                        {syncMsg && <span className="text-[11px] text-slate-500">{syncMsg}</span>}
                      </div>
                    )}
                    {liveData.offers.length === 0 ? (
                      <div className="text-slate-500 text-xs text-center py-3">No live offers returned for this part.</div>
                    ) : (
                      <div className="space-y-2 max-h-[320px] overflow-y-auto">
                        {liveData.offers.map((offer, i) => (
                          <div key={`${offer.distributor}-${offer.sku}-${i}`} className="rounded-lg p-3 border border-amber-700/30 bg-amber-950/10">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className="text-sm font-medium text-white truncate">{offer.distributor}</span>
                                <span className="text-[10px] uppercase tracking-wide text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded shrink-0">{offer.source}</span>
                                {offer.is_authorized ? (
                                  <span title="Authorized distributor" className="shrink-0"><ShieldCheck className="w-3.5 h-3.5 text-green-400" /></span>
                                ) : (
                                  <span title="Unauthorized / gray-market channel" className="shrink-0"><ShieldAlert className="w-3.5 h-3.5 text-yellow-500" /></span>
                                )}
                              </div>
                              <span className="text-sm font-bold text-amber-400 shrink-0">
                                {offer.price > 0 ? fmtUnitPrice(offer.price) : '—'}
                              </span>
                            </div>
                            <div className="grid grid-cols-2 gap-x-3 gap-y-1 mt-2 text-xs text-slate-400">
                              <div>Stock: <span className="text-white">{offer.stock.toLocaleString()}</span></div>
                              <div>MOQ: <span className="text-white">{offer.moq.toLocaleString()}</span></div>
                              <div>SKU: <span className="text-white">{offer.sku || '—'}</span></div>
                              <div>Lead time: <span className="text-white">{offer.lead_time_weeks != null ? `${offer.lead_time_weeks}w` : '—'}</span></div>
                              {offer.lifecycle_status && (
                                <div className="col-span-2">Lifecycle: <span className="text-white">{offer.lifecycle_status}</span></div>
                              )}
                            </div>
                            {offer.price_breaks && offer.price_breaks.length > 0 && (
                              <div className="flex flex-wrap gap-1.5 mt-2">
                                {offer.price_breaks.slice(0, 5).map((pb, j) => {
                                  const qty = pb.quantity ?? pb.qty ?? pb.break_quantity;
                                  const price = pb.price ?? pb.unit_price;
                                  if (qty == null || price == null) return null;
                                  return (
                                    <span key={j} className="text-[10px] text-slate-400 bg-slate-800/70 px-1.5 py-0.5 rounded">
                                      {String(qty)}+ @ {fmtUnitPrice(Number(price))}
                                    </span>
                                  );
                                })}
                              </div>
                            )}
                            {offer.datasheet_url && (
                              <a href={offer.datasheet_url} target="_blank" rel="noopener noreferrer" className="text-[11px] text-blue-400 hover:underline mt-2 inline-block">
                                Datasheet
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Right column: Order panel */}
            <div className="w-80 shrink-0 space-y-4">
              {/* Price display */}
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 text-center">
                {selectedOffer ? (
                  <>
                    <div className="text-xs text-slate-400 mb-1">{selectedOffer.distributor_name}</div>
                    <div className="text-3xl font-bold text-white">
                      {fmtUnitPrice(selectedOffer.price)}
                    </div>
                    <div className="text-slate-400 text-xs mt-0.5">per unit</div>
                    {cheapestOffer && selectedOffer.price > cheapestOffer.price && (
                      <div className="text-xs text-red-400 mt-1">
                        {((selectedOffer.price - cheapestOffer.price) / cheapestOffer.price * 100).toFixed(1)}% above best price ({fmtUnitPrice(cheapestOffer.price)} at {cheapestOffer.distributor_name})
                      </div>
                    )}
                    {cheapestOffer && selectedOffer.id === cheapestOffer.id && (
                      <div className="text-xs text-green-400 mt-1">Best available price</div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="text-xs text-slate-400 mb-1">Best Available Price</div>
                    <div className="text-3xl font-bold text-white">
                      {cheapestOffer ? fmtUnitPrice(cheapestOffer.price) : '--'}
                    </div>
                    <div className="text-slate-400 text-xs mt-0.5">
                      {cheapestOffer ? `at ${cheapestOffer.distributor_name}` : 'per unit'}
                    </div>
                    <div className="text-xs text-slate-500 mt-1">Select a distributor to order</div>
                  </>
                )}
              </div>

              {/* Order form */}
              {selectedOffer && (
                <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 space-y-3">
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">Quantity (units)</label>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={qty}
                      onChange={(e) => setQty(parseInt(e.target.value) || 1)}
                      className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  {outOfStock && (
                    <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-2.5 py-2 leading-relaxed">
                      <span className="font-semibold">Out of stock</span> at {selectedOffer.distributor_name}.
                      Pick another distributor above — the server will reject this line.
                    </div>
                  )}

                  {overStock && (
                    <div className="text-xs text-red-400">
                      Exceeds available stock ({plural(selectedOffer.stock, 'unit')})
                    </div>
                  )}

                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">Estimated Total</span>
                    <span className="text-white font-bold text-lg">
                      {fmtUsd(selectedOffer.price * qty)}
                    </span>
                  </div>

                  <button
                    onClick={handleAddToCart}
                    disabled={adding || !canAdd}
                    title={outOfStock ? `${selectedOffer.distributor_name} has no stock for this part` : undefined}
                    className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed text-white py-2.5 rounded-lg text-sm font-semibold transition-colors"
                    data-testid="add-to-cart"
                  >
                    {adding ? 'Adding...' : outOfStock ? 'Out of Stock' : overStock ? 'Reduce Quantity' : 'Add to Cart'}
                  </button>

                  {addError && (
                    <div
                      className="text-xs text-red-200 bg-red-900/30 border border-red-700/50 rounded px-2.5 py-2 leading-relaxed"
                      role="alert"
                      data-testid="add-to-cart-error"
                    >
                      {addError}
                    </div>
                  )}

                  {addedMsg && (
                    <div className="text-sm text-center text-green-400" role="status">
                      {addedMsg}
                    </div>
                  )}
                </div>
              )}

              {/* Component info card */}
              {selected.datasheets && selected.datasheets.length > 0 && (
                <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                  <h4 className="text-xs text-slate-400 mb-2">Datasheets</h4>
                  {selected.datasheets.map((url, i) => (
                    <a
                      key={i}
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-400 hover:underline block truncate"
                    >
                      Datasheet {i + 1}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
