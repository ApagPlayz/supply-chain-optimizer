import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCartStore } from '../store/cartStore';

export default function CartPage() {
  const navigate = useNavigate();
  const { items, loading, fetchCart, removeItem, clearCart } = useCartStore();

  useEffect(() => {
    fetchCart();
  }, [fetchCart]);

  const totalCost = items.reduce((sum, i) => sum + (i.unit_price ?? 0) * i.quantity, 0);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-bold text-white">Procurement Cart</h1>
          {items.length > 0 && (
            <button
              onClick={() => clearCart()}
              className="text-xs text-red-400 hover:text-red-300 transition-colors"
            >
              Clear all
            </button>
          )}
        </div>

        {loading && (
          <div className="text-center text-slate-400 py-10">Loading cart…</div>
        )}

        {!loading && items.length === 0 && (
          <div className="text-center py-16 text-slate-500">
            <div className="text-5xl mb-4">🛒</div>
            <div className="text-lg font-medium text-slate-400">Your cart is empty</div>
            <div className="text-sm mt-1 mb-6">Go to the Scheduler to add materials</div>
            <button
              onClick={() => navigate('/scheduler')}
              className="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded text-sm font-medium transition-colors"
            >
              Browse Materials
            </button>
          </div>
        )}

        {!loading && items.length > 0 && (
          <>
            <div className="space-y-2 mb-6">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-4 bg-slate-800 border border-slate-700 rounded-lg p-4"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-white font-medium text-sm truncate">
                      {item.material_name ?? `Material #${item.material_id}`}
                    </div>
                    <div className="text-slate-400 text-xs mt-0.5">
                      Supplier: {item.supplier_name ?? `#${item.supplier_id}`}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-white text-sm font-medium">
                      {item.quantity} {item.unit ?? 'units'}
                    </div>
                    {item.unit_price && (
                      <div className="text-slate-400 text-xs">
                        @ ${item.unit_price.toLocaleString(undefined, { maximumFractionDigits: 2 })} / {item.unit}
                      </div>
                    )}
                    <div className="text-blue-400 text-sm font-semibold">
                      ${((item.unit_price ?? 0) * item.quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                  <button
                    onClick={() => removeItem(item.id)}
                    className="text-slate-500 hover:text-red-400 transition-colors text-lg leading-none ml-2"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>

            {/* Summary */}
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-400">Materials subtotal</span>
                <span className="text-white">${totalCost.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between text-sm mb-3">
                <span className="text-slate-400">Items</span>
                <span className="text-white">{items.length}</span>
              </div>
              <div className="border-t border-slate-700 pt-3 flex items-center justify-between">
                <div className="text-slate-300 text-sm">
                  Proceed to checkout to run route optimization
                </div>
                <button
                  onClick={() => navigate('/checkout')}
                  className="bg-green-600 hover:bg-green-500 text-white px-6 py-2.5 rounded font-medium text-sm transition-colors"
                >
                  Optimize & Checkout →
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
