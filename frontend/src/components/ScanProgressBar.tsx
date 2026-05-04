"use client";

import { useEffect, useState } from "react";
import { Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { useScanJobsStore } from "@/lib/stores/scan-jobs-store";

interface Props {
  /** Optional override — defaults to the active job in the store. */
  showWhenIdle?: boolean;
}

const STAGE_DEFAULTS: Record<string, string> = {
  queued: "Queued for analysis…",
  upload: "Reading your document…",
  ingestion: "Extracting text…",
  detection: "Searching scholarly sources…",
  semantic: "Comparing semantic fingerprints…",
  web: "Crawling the open web…",
  academic: "Searching academic databases…",
  ai_detection: "Checking for AI-generated content…",
  aggregation: "Scoring and ranking matches…",
  done: "Done!",
};

export default function ScanProgressBar({ showWhenIdle = false }: Props) {
  const active = useScanJobsStore((s) => s.active);
  const [elapsed, setElapsed] = useState(0);
  const activeJobId = active?.job_id;
  const activeStatus = active?.status;
  const activeStartedAt = active?.started_at;

  useEffect(() => {
    if (!activeJobId || activeStatus === "completed" || activeStatus === "failed") {
      return;
    }
    const start = activeStartedAt ? activeStartedAt * 1000 : Date.now();
    const tick = () => setElapsed(Math.max(0, Date.now() - start));
    const firstTick = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, 1000);
    return () => {
      window.clearTimeout(firstTick);
      window.clearInterval(id);
    };
  }, [activeJobId, activeStatus, activeStartedAt]);

  if (!active && !showWhenIdle) return null;
  if (!active) return null;

  const isFailed = active.status === "failed";
  const isDone = active.status === "completed";
  const pct = isDone ? 100 : Math.max(2, active.progress?.percent ?? 4);
  const stage = active.progress?.stage ?? "queued";
  const message =
    active.progress?.message ||
    STAGE_DEFAULTS[stage] ||
    "Working on your scan…";
  const seconds = Math.floor(elapsed / 1000);
  const elapsedLabel =
    seconds < 60
      ? `${seconds}s`
      : `${Math.floor(seconds / 60)}m ${(seconds % 60).toString().padStart(2, "0")}s`;

  return (
    <div className="bg-surface border border-border rounded-2xl p-6 mb-8">
      <div className="flex items-start gap-4">
        <div
          className={`w-10 h-10 rounded-xl grid place-items-center shrink-0 ${
            isFailed
              ? "bg-danger/15 text-danger"
              : isDone
                ? "bg-success/15 text-success"
                : "bg-accent/15 text-accent"
          }`}
        >
          {isFailed ? (
            <AlertCircle className="w-5 h-5" />
          ) : isDone ? (
            <CheckCircle2 className="w-5 h-5" />
          ) : (
            <Loader2 className="w-5 h-5 animate-spin" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3 mb-2">
            <p className="text-sm font-medium truncate">
              {isFailed
                ? "Scan failed"
                : isDone
                  ? "Scan complete"
                  : message}
            </p>
            <span className="text-xs text-muted whitespace-nowrap tabular-nums">
              {isFailed
                ? active.error || "Unknown error"
                : `${Math.round(pct)}% · ${elapsedLabel}`}
            </span>
          </div>
          <div className="relative h-2.5 bg-bg/60 rounded-full overflow-hidden border border-border">
            {/* Filled portion */}
            <div
              className={`relative h-full rounded-full transition-[width] duration-700 ease-out ${
                isFailed
                  ? "bg-danger"
                  : isDone
                    ? "bg-success"
                    : "bg-gradient-to-r from-accent-l via-accent to-accent"
              }`}
              style={{ width: `${pct}%` }}
            >
              {/* Moving stripes — gives the "filling" texture while in-flight */}
              {!isFailed && !isDone && (
                <div className="absolute inset-0 progress-stripes rounded-full" />
              )}
              {/* Glowing leading edge */}
              {!isFailed && !isDone && (
                <div
                  className="absolute right-0 top-1/2 -translate-y-1/2 h-3 w-3 rounded-full bg-accent-l progress-glow"
                  style={{ boxShadow: "0 0 12px 2px rgb(var(--accent-rgb) / 0.7)" }}
                />
              )}
            </div>
            {/* Indeterminate sheen — sweeps across regardless of % */}
            {!isFailed && !isDone && (
              <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-full">
                <div
                  className="progress-indeterminate h-full w-1/4"
                  style={{
                    background:
                      "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.35) 50%, transparent 100%)",
                  }}
                />
              </div>
            )}
          </div>
          {!isFailed && !isDone && (
            <p className="text-xs text-muted mt-2">
              You can close this tab — we&apos;ll keep working in the background. Your
              result will appear here when ready.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
