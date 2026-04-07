import { create } from 'zustand';
import { cartAPI } from '../services/api';

export interface CartItem {
  id: number;
  material_id: number;
  supplier_id: number;
  quantity: number;
  unit: string | null;
  unit_price: number | null;
  material_name: string | null;
  supplier_name: string | null;
}

interface CartState {
  items: CartItem[];
  loading: boolean;
  fetchCart: () => Promise<void>;
  addItem: (data: { material_id: number; supplier_id: number; quantity: number; unit?: string }) => Promise<void>;
  removeItem: (id: number) => Promise<void>;
  clearCart: () => Promise<void>;
}

export const useCartStore = create<CartState>((set) => ({
  items: [],
  loading: false,

  fetchCart: async () => {
    set({ loading: true });
    const res = await cartAPI.get();
    set({ items: res.data, loading: false });
  },

  addItem: async (data) => {
    await cartAPI.add(data);
    const res = await cartAPI.get();
    set({ items: res.data });
  },

  removeItem: async (id) => {
    await cartAPI.remove(id);
    set((s) => ({ items: s.items.filter((i) => i.id !== id) }));
  },

  clearCart: async () => {
    await cartAPI.clear();
    set({ items: [] });
  },
}));
