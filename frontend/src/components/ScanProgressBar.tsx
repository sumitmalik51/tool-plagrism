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

  useEffect(() => {
    if (!active || active.status === "completed" || active.status === "failed") {
      setElapsed(0);
      return;
    }
    const start = active.started_at ? active.started_at * 1000 : Date.now();
    const tick = () => setElapsed(Math.max(0, Date.now() - start));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [active?.job_id, active?.status, active?.started_at]);

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
          <div className="h-2 bg-bg/60 rounded-full overflow-hidden border border-border">
            <div
              className={`h-full transition-all duration-500 ease-out ${
                isFailed
                  ? "bg-danger"
                  : isDone
                    ? "bg-success"
                    : "bg-gradient-to-r from-accent/70 to-accent"
              }`}
              style={{ width: `${pct}%` }}
            />
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
