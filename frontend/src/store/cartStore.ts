import { create } from 'zustand';
import { cartAPI } from '../services/api';
import { useOptimizeStore } from './optimizeStore';

export interface CartItem {
  id: number;
  component_id: number;
  distributor_id: number;
  quantity: number;
  unit_price: number | null;
  mpn: string | null;
  manufacturer: string | null;
  category: string | null;
  distributor_name: string | null;
  distributor_city: string | null;
  distributor_state: string | null;
  distributor_country: string | null;
}

interface CartState {
  items: CartItem[];
  loading: boolean;
  error: string | null;
  fetchCart: () => Promise<void>;
  addItem: (data: { component_id: number; distributor_id: number; quantity: number; unit_price?: number }) => Promise<void>;
  removeItem: (id: number) => Promise<void>;
  clearCart: () => Promise<void>;
}

export const useCartStore = create<CartState>((set) => ({
  items: [],
  loading: false,
  error: null,

  fetchCart: async () => {
    set({ loading: true, error: null });
    try {
      const res = await cartAPI.get();
      set({ items: res.data, loading: false });
    } catch (err: any) {
      set({ loading: false, error: err.response?.data?.detail || 'Failed to load cart' });
    }
  },

  addItem: async (data) => {
    try {
      await cartAPI.add(data);
      const res = await cartAPI.get();
      set({ items: res.data, error: null });
      useOptimizeStore.getState().clearResult();
    } catch (err: any) {
      throw new Error(err.response?.data?.detail || 'Failed to add item');
    }
  },

  removeItem: async (id) => {
    await cartAPI.remove(id);
    set((s) => ({ items: s.items.filter((i) => i.id !== id) }));
    useOptimizeStore.getState().clearResult();
  },

  clearCart: async () => {
    await cartAPI.clear();
    set({ items: [] });
    useOptimizeStore.getState().clearResult();
  },
}));
