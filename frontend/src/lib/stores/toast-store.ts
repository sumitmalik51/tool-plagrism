"use client";

import { create } from "zustand";

export type ToastType = "success" | "error" | "warning" | "info";

interface Toast {
  id: string;
  type: ToastType;
  message: string;
  exiting?: boolean;
}

interface ToastState {
  toasts: Toast[];
  add: (type: ToastType, message: string) => void;
  remove: (id: string) => void;
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],

  add: (type, message) => {
    const id = crypto.randomUUID();
    set((s) => ({ toasts: [...s.toasts, { id, type, message }] }));

    // Auto-dismiss after 4s
    setTimeout(() => {
      set((s) => ({
        toasts: s.toasts.map((t) =>
          t.id === id ? { ...t, exiting: true } : t
        ),
      }));
      setTimeout(() => {
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
      }, 300);
    }, 4000);
  },

  remove: (id) => {
    set((s) => ({
      toasts: s.toasts.map((t) =>
        t.id === id ? { ...t, exiting: true } : t
      ),
    }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 300);
  },
}));
