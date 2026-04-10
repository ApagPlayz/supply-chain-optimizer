import axios from 'axios';
import Cookies from 'js-cookie';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
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

export default api;
