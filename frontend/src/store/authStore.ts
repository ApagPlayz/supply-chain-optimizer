import { create } from 'zustand';
import { jwtDecode } from 'jwt-decode';
import Cookies from 'js-cookie';
import { authAPI } from '../services/api';

interface User {
  id: number;
  email: string;
  factory_name: string;
  latitude: number;
  longitude: number;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  setUser: (user: User) => void;
  login: (token: string, user: User) => void;
  logout: () => void;
  initializeAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isLoading: false,
  isAuthenticated: false,

  setToken: (token: string) => {
    Cookies.set('access_token', token, { expires: 7 });
    set({ token, isAuthenticated: true });
  },

  setUser: (user: User) => {
    set({ user });
  },

  login: (token: string, user: User) => {
    Cookies.set('access_token', token, { expires: 7 });
    set({ token, user, isAuthenticated: true });
  },

  logout: () => {
    Cookies.remove('access_token');
    set({ token: null, user: null, isAuthenticated: false });
  },

  initializeAuth: async () => {
    const token = Cookies.get('access_token');
    if (token) {
      try {
        jwtDecode<{ sub: number }>(token); // validate structure
        set({ token, isAuthenticated: true, isLoading: true });
        // Restore user profile so pages that need lat/lng work on refresh
        const res = await authAPI.me();
        set({ user: res.data, isLoading: false });
      } catch {
        Cookies.remove('access_token');
        set({ token: null, user: null, isAuthenticated: false, isLoading: false });
      }
    } else {
      set({ isLoading: false });
    }
  },
}));
