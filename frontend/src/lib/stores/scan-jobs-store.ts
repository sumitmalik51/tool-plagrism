"use client";

import { create } from "zustand";
import api from "@/lib/api";
import type { AnalysisResult } from "@/lib/types";

const STORAGE_KEY = "pg_active_scan_job";

export interface ScanJobProgress {
  stage: string;
  message: string;
  percent: number;
}

export type ScanJobStatus = "queued" | "running" | "completed" | "failed";

export interface ScanJob {
  job_id: string;
  document_id: string;
  kind: "text" | "file" | "google_doc";
  label: string;
  status: ScanJobStatus;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
  progress: ScanJobProgress | null;
  result?: AnalysisResult;
}

interface ScanJobsState {
  active: ScanJob | null;
  setActive: (job: ScanJob) => void;
  updateActive: (patch: Partial<ScanJob>) => void;
  clearActive: () => void;
  loadFromStorage: () => void;
  refreshActive: () => Promise<ScanJob | null>;
}

function persist(job: ScanJob | null) {
  if (typeof window === "undefined") return;
  try {
    if (
      job &&
      (job.status === "queued" || job.status === "running") &&
      !job.job_id.startsWith("pending-")
    ) {
      // Only persist real, server-known running jobs.
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          job_id: job.job_id,
          document_id: job.document_id,
          kind: job.kind,
          label: job.label,
          created_at: job.created_at,
        }),
      );
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* ignore quota/serialisation errors */
  }
}

export const useScanJobsStore = create<ScanJobsState>((set, get) => ({
  active: null,

  setActive: (job) => {
    persist(job);
    set({ active: job });
  },

  updateActive: (patch) => {
    const current = get().active;
    if (!current) return;
    const next = { ...current, ...patch } as ScanJob;
    persist(next);
    set({ active: next });
  },

  clearActive: () => {
    persist(null);
    set({ active: null });
  },

  loadFromStorage: () => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const stub = JSON.parse(raw) as Pick<
        ScanJob,
        "job_id" | "document_id" | "kind" | "label" | "created_at"
      >;
      set({
        active: {
          ...stub,
          status: "running",
          started_at: stub.created_at,
          completed_at: null,
          error: null,
          progress: null,
        },
      });
      // Fire-and-forget refresh to get true status.
      void get().refreshActive();
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  },

  refreshActive: async () => {
    const current = get().active;
    if (!current) return null;
    // Don't try to fetch a placeholder job that doesn't exist on the server yet.
    if (current.job_id.startsWith("pending-")) return current;
    try {
      const res = await api.get(`/api/v1/jobs/${current.job_id}`);
      const fresh = res.data as ScanJob;
      const merged: ScanJob = { ...current, ...fresh };
      persist(merged);
      set({ active: merged });
      return merged;
    } catch {
      // Job no longer in memory (server restart, etc) — drop it.
      persist(null);
      set({ active: null });
      return null;
    }
  },
}));
