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

// ── Hubs ──────────────────────────────────────────────────────────────────────
export const hubsAPI = {
  list: () => api.get('/hubs'),
  get: (id: number) => api.get(`/hubs/${id}`),
  nearby: (lat: number, lng: number, radius_km = 500) =>
    api.post('/hubs/nearby', { latitude: lat, longitude: lng, radius_km }),
};

// ── Materials ─────────────────────────────────────────────────────────────────
export const materialsAPI = {
  list: (params?: { category?: string; search?: string }) => api.get('/materials', { params }),
  categories: () => api.get('/materials/categories'),
  get: (id: number) => api.get(`/materials/${id}`),
  priceHistory: (id: number, days = 90) => api.get(`/materials/${id}/price-history`, { params: { days } }),
  forecast: (id: number) => api.get(`/materials/${id}/forecast`),
  suppliers: (id: number) => api.get(`/materials/${id}/suppliers`),
};

// ── Cart ──────────────────────────────────────────────────────────────────────
export const cartAPI = {
  get: () => api.get('/cart'),
  add: (data: { material_id: number; supplier_id: number; quantity: number; unit?: string }) =>
    api.post('/cart', data),
  remove: (itemId: number) => api.delete(`/cart/${itemId}`),
  clear: () => api.delete('/cart'),
};

// ── Optimization ──────────────────────────────────────────────────────────────
export const optimizeAPI = {
  vrp: () => api.post('/optimize/vrp'),
  scenario: (params: {
    tariff_multiplier?: number;
    port_closure_ids?: number[];
    supplier_failure_ids?: number[];
    demand_spike?: number;
  }) => api.post('/optimize/scenario', params),
};

export default api;
