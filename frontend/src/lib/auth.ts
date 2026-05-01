import { create } from "zustand";
import { api, getToken, setToken } from "./api";
import type { AuthResponse, Me } from "./types";

interface AuthState {
  user: Me | null;
  ready: boolean;
  loading: boolean;
  error: string | null;
  bootstrap: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  ready: false,
  loading: false,
  error: null,

  bootstrap: async () => {
    if (!getToken()) {
      set({ ready: true });
      return;
    }
    try {
      const me = await api<Me>("/auth/me");
      set({ user: me, ready: true });
    } catch {
      setToken(null);
      set({ user: null, ready: true });
    }
  },

  login: async (username, password) => {
    set({ loading: true, error: null });
    try {
      const r = await api<AuthResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(r.access_token);
      set({
        user: { id: r.user_id, username: r.username, is_admin: r.is_admin },
        loading: false,
        error: null,
      });
    } catch (e: any) {
      set({ error: e.message || "Login failed", loading: false });
      throw e;
    }
  },

  register: async (username, password) => {
    set({ loading: true, error: null });
    try {
      const r = await api<AuthResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(r.access_token);
      set({
        user: { id: r.user_id, username: r.username, is_admin: r.is_admin },
        loading: false,
        error: null,
      });
    } catch (e: any) {
      set({ error: e.message || "Registration failed", loading: false });
      throw e;
    }
  },

  logout: () => {
    setToken(null);
    set({ user: null });
    location.href = "/login";
  },
}));
