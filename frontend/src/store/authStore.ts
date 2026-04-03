import { create } from 'zustand';
import { jwtDecode } from 'jwt-decode';
import Cookies from 'js-cookie';

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
  initializeAuth: () => void;
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

  initializeAuth: () => {
    const token = Cookies.get('access_token');
    if (token) {
      try {
        const decoded = jwtDecode<{ sub: number }>(token);
        if (decoded) {
          set({ token, isAuthenticated: true, isLoading: false });
        }
      } catch (error) {
        Cookies.remove('access_token');
        set({ token: null, isAuthenticated: false, isLoading: false });
      }
    } else {
      set({ isLoading: false });
    }
  },
}));
