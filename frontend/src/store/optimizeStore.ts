import { create } from 'zustand';

export interface RouteStop {
  order: number;
  supplier_id: number;
  supplier_name: string;
  city: string | null;
  state: string | null;
  lat: number;
  lng: number;
  material_names: string[];
  distance_km: number;
  leg_cost_usd: number;
  leg_co2e_kg: number;
}

export interface RouteAlternative {
  id: string;
  label: string;
  description: string;
  route: RouteStop[];
  total_cost_usd: number;
  total_transport_cost_usd: number;
  total_material_cost_usd: number;
  total_co2e_kg: number;
  total_distance_km: number;
  base_eta_days: number;
  eta_p10: number;
  eta_p50: number;
  eta_p90: number;
  monte_carlo_samples: number[];
  max_lead_time_days: number;
  stop_count: number;
  cost_rank: number;
  speed_rank: number;
  carbon_rank: number;
  distance_rank: number;
}

export interface MultiRouteResult {
  alternatives: RouteAlternative[];
  recommended_id: string;
}

interface OptimizeState {
  multiResult: MultiRouteResult | null;
  selectedId: string | null;
  setMultiResult: (r: MultiRouteResult) => void;
  setSelectedId: (id: string) => void;
  clearResult: () => void;
  /** Convenience: get the currently selected alternative */
  getSelected: () => RouteAlternative | null;
}

export const useOptimizeStore = create<OptimizeState>((set, get) => ({
  multiResult: null,
  selectedId: null,
  setMultiResult: (r) => set({ multiResult: r, selectedId: r.recommended_id }),
  setSelectedId: (id) => set({ selectedId: id }),
  clearResult: () => set({ multiResult: null, selectedId: null }),
  getSelected: () => {
    const { multiResult, selectedId } = get();
    if (!multiResult || !selectedId) return null;
    return multiResult.alternatives.find((a) => a.id === selectedId) ?? null;
  },
}));
