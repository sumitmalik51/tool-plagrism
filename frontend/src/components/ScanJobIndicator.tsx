"use client";

import { useRouter, usePathname } from "next/navigation";
import { Loader2, X } from "lucide-react";
import { useScanJobsStore } from "@/lib/stores/scan-jobs-store";

/** Floating pill that follows the user across every dashboard page while a
 *  scan job is running. Mounted once in the dashboard layout.
 *  (SSE subscription is mounted separately at the layout level so it keeps
 *  running even on pages where this pill is hidden.)
 */
export default function ScanJobIndicator() {
  const active = useScanJobsStore((s) => s.active);
  const clearActive = useScanJobsStore((s) => s.clearActive);

  const router = useRouter();
  const pathname = usePathname();

  if (!active) return null;
  // Hide indicator on the page that's already showing the full progress card.
  const hideOnDashboard =
    pathname === "/dashboard" && active.status !== "completed";
  if (hideOnDashboard) return null;
  // Don't keep the pill around once user has gone back and seen the result.
  if (active.status === "completed" && pathname === "/dashboard") return null;

  const isFailed = active.status === "failed";
  const isDone = active.status === "completed";
  const pct = isDone ? 100 : Math.max(2, active.progress?.percent ?? 4);

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm">
      <div className="bg-surface border border-border rounded-2xl shadow-2xl shadow-black/30 overflow-hidden backdrop-blur-md">
        <button
          type="button"
          onClick={() => router.push("/dashboard")}
          className="w-full flex items-center gap-3 px-4 py-3 hover:bg-bg/30 transition-colors text-left"
        >
          <div
            className={`w-9 h-9 rounded-lg grid place-items-center shrink-0 ${
              isFailed
                ? "bg-danger/15 text-danger"
                : isDone
                  ? "bg-success/15 text-success"
                  : "bg-accent/15 text-accent"
            }`}
          >
            {isFailed ? (
              <X className="w-4 h-4" />
            ) : isDone ? (
              <span className="text-xs font-bold">✓</span>
            ) : (
              <Loader2 className="w-4 h-4 animate-spin" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">
              {isFailed
                ? "Scan failed"
                : isDone
                  ? "Scan complete — view result"
                  : active.label || "Plagiarism scan in progress"}
            </p>
            <div className="flex items-center gap-2 mt-1">
              <div className="h-1 flex-1 bg-bg/60 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-500 ${
                    isFailed
                      ? "bg-danger"
                      : isDone
                        ? "bg-success"
                        : "bg-accent"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-[10px] text-muted tabular-nums w-8 text-right">
                {Math.round(pct)}%
              </span>
            </div>
          </div>
        </button>
        {(isDone || isFailed) && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              clearActive();
            }}
            className="absolute top-2 right-2 text-muted hover:text-txt p-1"
            aria-label="Dismiss"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
