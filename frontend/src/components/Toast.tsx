"use client";

import { X, CheckCircle, AlertTriangle, AlertCircle, Info } from "lucide-react";
import { useToastStore, type ToastType } from "@/lib/stores/toast-store";

const icons: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle className="w-5 h-5 text-ok" />,
  error: <AlertCircle className="w-5 h-5 text-danger" />,
  warning: <AlertTriangle className="w-5 h-5 text-warn" />,
  info: <Info className="w-5 h-5 text-accent-l" />,
};

const bgColors: Record<ToastType, string> = {
  success: "border-ok/30",
  error: "border-danger/30",
  warning: "border-warn/30",
  info: "border-accent/30",
};

export default function ToastContainer() {
  const { toasts, remove } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-start gap-3 p-4 bg-surface border ${bgColors[toast.type]} rounded-xl shadow-xl ${
            toast.exiting ? "toast-exit" : "toast-enter"
          }`}
        >
          <div className="shrink-0 mt-0.5">{icons[toast.type]}</div>
          <p className="text-sm text-txt flex-1">{toast.message}</p>
          <button
            onClick={() => remove(toast.id)}
            className="shrink-0 text-muted hover:text-txt transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
