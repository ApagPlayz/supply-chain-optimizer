import axios from 'axios';
import Cookies from 'js-cookie';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000, // 30 second timeout for all requests
});

api.interceptors.request.use((config) => {
  const token = Cookies.get('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      Cookies.remove('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authAPI = {
  register: (data: { email: string; password: string; factory_name: string; latitude: number; longitude: number }) =>
    api.post('/auth/register', data),
  login: (data: { email: string; password: string }) => api.post('/auth/login', data),
  demoLogin: () => api.post('/auth/demo'),
  me: () => api.get('/auth/me'),
};

// ── Components ───────────────────────────────────────────────────────────────
export const componentsAPI = {
  list: (params?: { category?: string; manufacturer?: string; search?: string }) =>
    api.get('/components', { params }),
  categories: () => api.get('/components/categories'),
  manufacturers: () => api.get('/components/manufacturers'),
  stats: () => api.get('/components/stats'),
  get: (id: number) => api.get(`/components/${id}`),
  offers: (id: number, params?: { sort_by?: string; domestic_only?: boolean }) =>
    api.get(`/components/${id}/offers`, { params }),
};

// ── Distributors ─────────────────────────────────────────────────────────────
export const distributorsAPI = {
  list: (params?: { domestic_only?: boolean }) => api.get('/distributors', { params }),
  get: (id: number) => api.get(`/distributors/${id}`),
};

// ── Cart ──────────────────────────────────────────────────────────────────────
export const cartAPI = {
  get: () => api.get('/cart'),
  add: (data: { component_id: number; distributor_id: number; quantity: number; unit_price?: number }) =>
    api.post('/cart', data),
  remove: (itemId: number) => api.delete(`/cart/${itemId}`),
  clear: () => api.delete('/cart'),
};

// ── Optimization ──────────────────────────────────────────────────────────────
export const optimizeAPI = {
  vrp: () => api.post('/optimize/vrp'),
  scenario: (params: {
    tariff_multiplier?: number;
    distributor_failure_ids?: number[];
    demand_spike?: number;
  }) => api.post('/optimize/scenario', params),
  hubs: () => api.get('/optimize/hubs'),
};

export interface HubOut {
  id: number;
  name: string;
  operator: string | null;
  hub_type: string | null;
  city: string | null;
  state: string | null;
  latitude: number;
  longitude: number;
}

export async function getCrossDockHubs(): Promise<HubOut[]> {
  const { data } = await api.get('/optimize/hubs');
  return data as HubOut[];
}

// ── Feeds ─────────────────────────────────────────────────────────────────────
export const feedsAPI = {
  getStatus: () => api.get('/feeds/status'),
};

// ── Graph ──────────────────────────────────────────────────────────────────────
export const graphAPI = {
  metrics: () => api.get('/graph/metrics'),
  simulate: (bom_component_ids: number[]) =>
    api.post('/graph/simulate', { bom_component_ids }),
};

// ── Benchmark ─────────────────────────────────────────────────────────────────
export const benchmarkAPI = {
  summary: (runId?: number) =>
    api.get('/benchmark/summary', runId !== undefined ? { params: { run_id: runId } } : {}),
  fiedlerCurve: () =>
    api.get('/benchmark/fiedler-curve'),
  cascadeHeatmap: () =>
    api.get('/benchmark/cascade-heatmap'),
  singleSourceComponents: () =>
    api.get('/benchmark/single-source-components'),
};

// ── Forecasts ─────────────────────────────────────────────────────────────────
export interface ForecastPoint {
  forecast_date: string;
  predicted_demand: number;
  lower_bound: number | null;
  upper_bound: number | null;
}

export interface ForecastData {
  component_id: number;
  forecast_points: ForecastPoint[];   // 12 entries
  weeks_until_stockout: number | null;
}

export const forecastsAPI = {
  all: () => api.get<ForecastData[]>('/forecasts/all'),
};

// ── Resilience Scenarios ──────────────────────────────────────────────────────
export interface ScenarioResponse {
  baseline_cost_usd: number;
  scenario_cost_usd: number;
  cost_delta_pct: number;
  baseline_eta_days: number;
  scenario_eta_days: number;
  eta_delta_days: number;
  baseline_risk_score: number;
  scenario_risk_score: number;
  risk_delta: number;
  // Dollar-denominated tail-risk framing (P3): EVaR-95 cost multiplier of the
  // worst-5% Monte Carlo scenarios, and the extra USD it puts at risk on this BOM.
  baseline_evar_95: number;
  procurement_spend_at_risk_usd: number;
  baseline_fulfillment_p10: number;
  baseline_fulfillment_p50: number;
  baseline_fulfillment_p90: number;
  scenario_fulfillment_p10: number;
  scenario_fulfillment_p50: number;
  scenario_fulfillment_p90: number;
  affected_bom_ids: number[];
  affected_suppliers: string[];
}

export interface DeliveryTargetResponse extends ScenarioResponse {
  suppliers_capable: Array<{ name: string; lead_time_days: number; cost_per_component_avg: number }>;
  suppliers_cannot_meet: Array<{ name: string; min_lead_time_days: number; reason: string }>;
}

export interface DistributorFailureRequest {
  distributor_id: number;
  bom_component_ids: number[];
}

export interface GeopoliticalRiskRequest {
  risk_multiplier: number;
  bom_component_ids: number[];
}

export interface DeliveryTargetRequest {
  target_delivery_days: number;
  bom_component_ids: number[];
}

// Abort controller helper for requests
function withAbortController<T>(
  promise: Promise<T>,
  signal?: AbortSignal
): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      if (signal) {
        signal.addEventListener('abort', () => {
          reject(new Error('Request aborted'));
        });
      }
    }),
  ]);
}

export const resilienceAPI = {
  distributorFailure: async (
    req: DistributorFailureRequest,
    signal?: AbortSignal
  ): Promise<ScenarioResponse> => {
    try {
      const response = await withAbortController(
        api.post<ScenarioResponse>('/resilience/distributor-failure', req, { signal }),
        signal
      );
      return response.data;
    } catch (error: any) {
      if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
        throw new Error('Request timeout — please try again');
      }
      if (error.message?.includes('aborted')) {
        throw new Error('Request cancelled');
      }
      throw error;
    }
  },

  geopoliticalRisk: async (
    req: GeopoliticalRiskRequest,
    signal?: AbortSignal
  ): Promise<ScenarioResponse> => {
    try {
      const response = await withAbortController(
        api.post<ScenarioResponse>('/resilience/geopolitical-risk', req, { signal }),
        signal
      );
      return response.data;
    } catch (error: any) {
      if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
        throw new Error('Request timeout — please try again');
      }
      if (error.message?.includes('aborted')) {
        throw new Error('Request cancelled');
      }
      throw error;
    }
  },

  deliveryTarget: async (
    req: DeliveryTargetRequest,
    signal?: AbortSignal
  ): Promise<DeliveryTargetResponse> => {
    try {
      const response = await withAbortController(
        api.post<DeliveryTargetResponse>('/resilience/delivery-target', req, { signal }),
        signal
      );
      return response.data;
    } catch (error: any) {
      if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
        throw new Error('Request timeout — please try again');
      }
      if (error.message?.includes('aborted')) {
        throw new Error('Request cancelled');
      }
      throw error;
    }
  },
};

export default api;
