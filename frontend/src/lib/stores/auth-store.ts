"use client";

import { create } from "zustand";
import api from "@/lib/api";
import type { User, LoginRequest, SignupRequest } from "@/lib/types";

interface AuthState {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  login: (credentials: LoginRequest) => Promise<void>;
  signup: (data: SignupRequest) => Promise<void>;
  googleLogin: (credential: string, referralCode?: string) => Promise<void>;
  logout: () => void;
  loadFromStorage: () => void;
  fetchUser: () => Promise<void>;
  setUser: (user: User) => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: null,
  refreshToken: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (credentials) => {
    const { data } = await api.post("/api/v1/auth/login", credentials);
    const { user, token, refresh_token } = data;

    localStorage.setItem("pg_token", token);
    if (refresh_token) localStorage.setItem("pg_refresh_token", refresh_token);
    localStorage.setItem("pg_user", JSON.stringify(user));

    set({
      user,
      token,
      refreshToken: refresh_token || null,
      isAuthenticated: true,
      isLoading: false,
    });
  },

  signup: async (signupData) => {
    const { data } = await api.post("/api/v1/auth/signup", signupData);
    const { user, token, refresh_token } = data;

    localStorage.setItem("pg_token", token);
    if (refresh_token) localStorage.setItem("pg_refresh_token", refresh_token);
    localStorage.setItem("pg_user", JSON.stringify(user));

    set({
      user,
      token,
      refreshToken: refresh_token || null,
      isAuthenticated: true,
      isLoading: false,
    });
  },

  googleLogin: async (credential, referralCode) => {
    const { data } = await api.post("/api/v1/auth/google", {
      credential,
      referral_code: referralCode,
    });
    const { user, token, refresh_token } = data;

    localStorage.setItem("pg_token", token);
    if (refresh_token) localStorage.setItem("pg_refresh_token", refresh_token);
    localStorage.setItem("pg_user", JSON.stringify(user));

    set({
      user,
      token,
      refreshToken: refresh_token || null,
      isAuthenticated: true,
      isLoading: false,
    });
  },

  logout: () => {
    localStorage.removeItem("pg_token");
    localStorage.removeItem("pg_refresh_token");
    localStorage.removeItem("pg_user");
    set({
      user: null,
      token: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,
    });
  },

  loadFromStorage: () => {
    if (typeof window === "undefined") {
      set({ isLoading: false });
      return;
    }

    const token = localStorage.getItem("pg_token");
    const refreshToken = localStorage.getItem("pg_refresh_token");
    const userStr = localStorage.getItem("pg_user");

    if (token && userStr) {
      try {
        const user = JSON.parse(userStr) as User;
        set({
          user,
          token,
          refreshToken,
          isAuthenticated: true,
          isLoading: false,
        });
      } catch {
        set({ isLoading: false });
      }
    } else {
      set({ isLoading: false });
    }
  },

  fetchUser: async () => {
    try {
      const { data } = await api.get("/api/v1/auth/me");
      const user = data as User;
      localStorage.setItem("pg_user", JSON.stringify(user));
      set({ user });
    } catch {
      get().logout();
    }
  },

  setUser: (user) => {
    localStorage.setItem("pg_user", JSON.stringify(user));
    set({ user });
  },
}));
