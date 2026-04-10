import { useEffect, useState, useCallback } from 'react';
import { componentsAPI } from '../services/api';
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
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [domesticOnly, setDomesticOnly] = useState(false);

  useEffect(() => {
    Promise.all([
      componentsAPI.list(),
      componentsAPI.categories(),
    ]).then(([cRes, catRes]) => {
      setComponents(cRes.data);
      setCategories(catRes.data);
      setLoading(false);
    });
  }, []);

  const selectComponent = useCallback(async (comp: ComponentItem) => {
    setSelectedOfferId(null);
    setQty(1);
    setAddedMsg('');
    setDetailLoading(true);
    const res = await componentsAPI.get(comp.id);
    setSelected(res.data);
    setDetailLoading(false);
  }, []);

  const selectedOffer = selected?.offers.find((o) => o.id === selectedOfferId) ?? null;

  const handleAddToCart = async () => {
    if (!selected || !selectedOffer) return;
    setAdding(true);
    try {
      await addItem({
        component_id: selected.id,
        distributor_id: selectedOffer.distributor_id,
        quantity: qty,
        unit_price: selectedOffer.price,
      });
      setAddedMsg('Added to cart!');
      setTimeout(() => setAddedMsg(''), 2500);
    } catch (err: any) {
      setAddedMsg(err.message || 'Failed to add to cart');
      setTimeout(() => setAddedMsg(''), 4000);
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
    <div className="flex h-full bg-slate-900 text-slate-100">
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
              onClick={() => selectComponent(comp)}
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
                    <div className="text-xs text-green-400 font-medium">${comp.min_price.toFixed(2)}</div>
                  )}
                  <div className="text-xs text-slate-500">{comp.num_offers} offers</div>
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
        {!selected && (
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
                      ? `$${selected.offers[0].price.toFixed(2)} – $${selected.offers[selected.offers.length - 1].price.toFixed(2)}`
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
                ) : (
                  <div className="space-y-2 max-h-[420px] overflow-y-auto">
                    {filteredOffers.map((offer, i) => (
                      <button
                        key={offer.id}
                        onClick={() => setSelectedOfferId(offer.id)}
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
                            ${offer.price.toFixed(4)}
                          </span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-slate-400">
                          <div>Stock: <span className="text-white">{offer.stock.toLocaleString()}</span></div>
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
            </div>

            {/* Right column: Order panel */}
            <div className="w-80 shrink-0 space-y-4">
              {/* Price display */}
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 text-center">
                {selectedOffer ? (
                  <>
                    <div className="text-xs text-slate-400 mb-1">{selectedOffer.distributor_name}</div>
                    <div className="text-3xl font-bold text-white">
                      ${selectedOffer.price.toFixed(4)}
                    </div>
                    <div className="text-slate-400 text-xs mt-0.5">per unit</div>
                    {cheapestOffer && selectedOffer.price > cheapestOffer.price && (
                      <div className="text-xs text-red-400 mt-1">
                        {((selectedOffer.price - cheapestOffer.price) / cheapestOffer.price * 100).toFixed(1)}% above best price (${cheapestOffer.price.toFixed(4)} at {cheapestOffer.distributor_name})
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
                      {cheapestOffer ? `$${cheapestOffer.price.toFixed(4)}` : '--'}
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

                  {selectedOffer.stock > 0 && qty > selectedOffer.stock && (
                    <div className="text-xs text-red-400">
                      Exceeds available stock ({selectedOffer.stock.toLocaleString()} units)
                    </div>
                  )}

                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">Estimated Total</span>
                    <span className="text-white font-bold text-lg">
                      ${(selectedOffer.price * qty).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </span>
                  </div>

                  <button
                    onClick={handleAddToCart}
                    disabled={adding}
                    className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white py-2.5 rounded-lg text-sm font-semibold transition-colors"
                  >
                    {adding ? 'Adding...' : 'Add to Cart'}
                  </button>

                  {addedMsg && (
                    <div className={`text-sm text-center ${addedMsg.includes('Added') ? 'text-green-400' : 'text-red-400'}`}>
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
  );
}
