import { create } from 'zustand';

export interface RouteStop {
  order: number;
  distributor_id: number;
  distributor_name: string;
  city: string | null;
  state: string | null;
  country: string | null;
  lat: number;
  lng: number;
  components: string[];
  distance_km: number;
  leg_cost_usd: number;
  leg_co2e_kg: number;
}

export interface CostBreakdown {
  component_cost: number;
  transport_cost: number;
  holding_cost: number;
  total: number;
}

export interface StrategyMath {
  weights: { cost: number; time: number; carbon: number };
  raw_objective_values: { cost: number; time: number; carbon: number };
  normalized_objective_values: { cost: number; time: number; carbon: number };
  weighted_total: number;
  citations: string[];
}

export interface CrossDockInfo {
  enabled: boolean;
  hub_id?: number | null;
  hub_name?: string | null;
  hub_city?: string | null;
  hub_state?: string | null;
  hub_lat?: number | null;
  hub_lng?: number | null;
  savings_vs_direct_pct: number;
  direct_cost_usd: number;
  consolidated_cost_usd: number;
  rationale: string;
}

export interface SourcingAssignment {
  component_id: number;
  mpn: string;
  distributor_id: number;
  distributor_name: string;
  quantity: number;
  unit_price_usd: number;
  line_total_usd: number;
}

export interface OutlierDropLog {
  component_id: number;
  mpn: string;
  dropped_distributor_id: number;
  dropped_price_usd: number;
  median_price_usd: number;
  reason: string;
}

export interface RouteAlternative {
  id: string;
  label: string;
  description: string;
  route: RouteStop[];
  total_cost_usd: number;
  total_transport_cost_usd: number;
  total_component_cost_usd: number;
  total_co2e_kg: number;
  total_distance_km: number;
  base_eta_days: number;
  eta_p10: number;
  eta_p50: number;
  eta_p90: number;
  monte_carlo_samples: number[];
  stop_count: number;
  international_stops: number;
  cost_rank: number;
  speed_rank: number;
  carbon_rank: number;
  distance_rank: number;
  cost_breakdown?: CostBreakdown | null;
  strategy_math?: StrategyMath | null;
  cross_dock?: CrossDockInfo | null;
  sourcing?: SourcingAssignment[];
}

export interface MultiRouteResult {
  alternatives: RouteAlternative[];
  recommended_id: string;
  outlier_drops?: OutlierDropLog[];
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
