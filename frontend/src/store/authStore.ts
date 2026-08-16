import { create } from 'zustand';
import { jwtDecode } from 'jwt-decode';
import Cookies from 'js-cookie';
import { authAPI, type AuthUser } from '../services/api';

type User = AuthUser;

interface AuthState {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /**
   * False until `initializeAuth()` has finished deciding whether the stored cookie
   * represents a real session. Routing MUST wait on this: treating "not yet
   * resolved" as "not authenticated" is what bounced logged-in users to /login on
   * every refresh and deep link.
   */
  authResolved: boolean;
  setToken: (token: string) => void;
  setUser: (user: User) => void;
  login: (token: string, user: User) => void;
  /** Store the token, then fetch the real profile from GET /auth/me. */
  loginWithToken: (token: string) => Promise<void>;
  logout: () => void;
  initializeAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isLoading: false,
  isAuthenticated: false,
  authResolved: false,

  setToken: (token: string) => {
    Cookies.set('access_token', token, { expires: 7 });
    set({ token, isAuthenticated: true });
  },

  setUser: (user: User) => {
    set({ user });
  },

  login: (token: string, user: User) => {
    Cookies.set('access_token', token, { expires: 7 });
    set({ token, user, isAuthenticated: true, authResolved: true });
  },

  // The only honest way to populate the user: ask the API who this token belongs to.
  // Login/Register used to invent `{id:1, factory_name:'', latitude:0, longitude:0}`,
  // which put every real account's depot in the Gulf of Guinea.
  loginWithToken: async (token: string) => {
    Cookies.set('access_token', token, { expires: 7 });
    set({ token, isAuthenticated: true, isLoading: true });
    try {
      const res = await authAPI.me();
      set({ user: res.data, isLoading: false, authResolved: true });
    } catch (err) {
      set({ isLoading: false, authResolved: true });
      throw err;
    }
  },

  logout: () => {
    Cookies.remove('access_token');
    set({ token: null, user: null, isAuthenticated: false, authResolved: true });
  },

  initializeAuth: async () => {
    const token = Cookies.get('access_token');
    if (!token) {
      set({ isLoading: false, authResolved: true });
      return;
    }
    try {
      jwtDecode<{ sub: number }>(token); // throws if the cookie isn't a JWT at all
    } catch {
      Cookies.remove('access_token');
      set({ token: null, user: null, isAuthenticated: false, isLoading: false, authResolved: true });
      return;
    }
    set({ token, isAuthenticated: true, isLoading: true });
    try {
      // Restore user profile so pages that need lat/lng work on refresh
      const res = await authAPI.me();
      set({ user: res.data, isLoading: false, authResolved: true });
    } catch (err) {
      // A 401 means the token is genuinely dead — drop it. Anything else (backend
      // down, network blip) must NOT sign the user out; the axios interceptor
      // already handles real 401s globally.
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401 || status === 403) {
        Cookies.remove('access_token');
        set({ token: null, user: null, isAuthenticated: false, isLoading: false, authResolved: true });
      } else {
        set({ isLoading: false, authResolved: true });
      }
    }
  },
}));
