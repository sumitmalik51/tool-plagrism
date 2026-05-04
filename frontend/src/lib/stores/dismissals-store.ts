"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

import api from "@/lib/api";

/**
 * Per-passage user verdicts. The backend gives us flagged passages; the user
 * gets to push back with one of:
 *   - "quotation"      → properly cited; should not count against the score
 *   - "prior_work"     → user's own previously published material
 *   - "false_positive" → bad source / topical overlap only
 *
 * State is persisted in localStorage so verdicts survive a refresh, and is
 * also mirrored to the server (when authenticated) so the same verdicts
 * follow the user across devices and feed the PDF export.
 *
 * KEYING: We key dismissals by a stable hash of `passage.text + passage.source`
 * rather than by passage index. Index-based keys silently corrupt if the
 * server ever re-sorts, dedupes, or reshapes flagged_passages between scans
 * of the "same" document_id. Text+source is invariant under those changes.
 */

export type DismissalKind = "quotation" | "prior_work" | "false_positive";

interface DismissalsState {
  // documentId → passageKey → kind
  dismissed: Record<string, Record<string, DismissalKind>>;
  /** Per-document hydration status so callers don't refetch on every render. */
  hydrated: Record<string, "pending" | "ok" | "error">;
  set: (documentId: string, passageKey: string, kind: DismissalKind) => void;
  clear: (documentId: string, passageKey: string) => void;
  clearAll: (documentId: string) => void;
  get: (documentId: string, passageKey: string) => DismissalKind | undefined;
  /** Replace the local cache for a document with the server's authoritative copy. */
  hydrateFromServer: (documentId: string) => Promise<void>;
}

/** Internal helper — fire & forget; failures are logged but never thrown. */
function isAuthed(): boolean {
  if (typeof window === "undefined") return false;
  return !!localStorage.getItem("pg_token");
}

async function syncSet(documentId: string, key: string, kind: DismissalKind): Promise<void> {
  if (!isAuthed()) return;
  try {
    await api.post(`/api/v1/auth/scans/${encodeURIComponent(documentId)}/dismissals`, {
      passage_key: key,
      kind,
    });
  } catch {
    // Network / 404 / 401 — keep the local copy and let the next hydrate reconcile.
  }
}

async function syncClear(documentId: string, key: string): Promise<void> {
  if (!isAuthed()) return;
  try {
    await api.delete(
      `/api/v1/auth/scans/${encodeURIComponent(documentId)}/dismissals/${encodeURIComponent(key)}`,
    );
  } catch {
    // Keep the local copy; the next hydrate reconciles with the server.
  }
}

async function syncClearAll(documentId: string): Promise<void> {
  if (!isAuthed()) return;
  try {
    await api.delete(`/api/v1/auth/scans/${encodeURIComponent(documentId)}/dismissals`);
  } catch {
    // Keep the local copy; the next hydrate reconciles with the server.
  }
}

/**
 * Compute a stable, theme/locale-invariant key for a passage. Short enough
 * to be a JSON object key but distinct enough to avoid collisions inside a
 * single document (~10⁻⁹ collision probability for typical doc sizes).
 */
export function passageKey(passage: { text: string; source?: string | null }): string {
  // djb2 — simple, fast, no Web Crypto dependency (sync-safe in render).
  const input = `${passage.text ?? ""}\u0001${passage.source ?? ""}`;
  let h = 5381;
  for (let i = 0; i < input.length; i++) {
    h = ((h << 5) + h + input.charCodeAt(i)) | 0;
  }
  // Suffix with a tiny excerpt for human-debuggability of the localStorage blob.
  const excerpt = (passage.text ?? "").slice(0, 16).replace(/\s+/g, "_");
  return `${(h >>> 0).toString(36)}_${excerpt}`;
}

export const useDismissalsStore = create<DismissalsState>()(
  persist(
    (set, get) => ({
      dismissed: {},
      hydrated: {},
      set: (documentId, key, kind) => {
        set((s) => ({
          dismissed: {
            ...s.dismissed,
            [documentId]: {
              ...(s.dismissed[documentId] ?? {}),
              [key]: kind,
            },
          },
        }));
        // Fire-and-forget: server is best-effort; localStorage is the cache.
        void syncSet(documentId, key, kind);
      },
      clear: (documentId, key) => {
        set((s) => {
          const doc = { ...(s.dismissed[documentId] ?? {}) };
          delete doc[key];
          return {
            dismissed: { ...s.dismissed, [documentId]: doc },
          };
        });
        void syncClear(documentId, key);
      },
      clearAll: (documentId) => {
        set((s) => {
          const next = { ...s.dismissed };
          delete next[documentId];
          return { dismissed: next };
        });
        void syncClearAll(documentId);
      },
      get: (documentId, key) => get().dismissed[documentId]?.[key],
      hydrateFromServer: async (documentId) => {
        if (!isAuthed()) return;
        const status = get().hydrated[documentId];
        if (status === "pending" || status === "ok") return;
        set((s) => ({ hydrated: { ...s.hydrated, [documentId]: "pending" } }));
        try {
          const r = await api.get<{
            dismissals: Record<string, { kind: DismissalKind }>;
          }>(`/api/v1/auth/scans/${encodeURIComponent(documentId)}/dismissals`);
          const remote: Record<string, DismissalKind> = {};
          for (const [k, v] of Object.entries(r.data?.dismissals ?? {})) {
            if (v && (v.kind === "quotation" || v.kind === "prior_work" || v.kind === "false_positive")) {
              remote[k] = v.kind;
            }
          }
          set((s) => {
            const local = s.dismissed[documentId] ?? {};
            // Server is authoritative; any local-only keys (made while
            // offline) are pushed up so they're not silently lost.
            const merged = { ...local, ...remote };
            for (const [k, kind] of Object.entries(local)) {
              if (!(k in remote)) void syncSet(documentId, k, kind);
            }
            return {
              dismissed: { ...s.dismissed, [documentId]: merged },
              hydrated: { ...s.hydrated, [documentId]: "ok" },
            };
          });
        } catch {
          set((s) => ({ hydrated: { ...s.hydrated, [documentId]: "error" } }));
        }
      },
    }),
    {
      name: "plagiarism-dismissals-v1",
      version: 2,
      storage: createJSONStorage(() => localStorage),
      // Don't persist the per-document hydration map — it's transient.
      partialize: (s) => ({ dismissed: s.dismissed }) as Pick<DismissalsState, "dismissed">,
      // v1 → v2: keys changed from numeric passage indices to stable
      // text+source hashes. We can't safely remap without the report, so
      // we drop v1 dismissals on first load. A one-time loss of local-only
      // verdicts is preferable to silently mis-attributing them.
      migrate: (_persisted, version) => {
        if (version < 2) return { dismissed: {} } as Pick<DismissalsState, "dismissed">;
        return _persisted as Pick<DismissalsState, "dismissed">;
      },
    },
  ),
);

/**
 * Compute a recomputed plagiarism score after the user has marked some
 * passages as dismissed. Scales the original score by `1 - dismissed/total`
 * where weight is each passage's similarity_score.
 */
export function adjustedScore(
  originalScore: number,
  passages: Array<{ text: string; source?: string | null; similarity_score: number }>,
  dismissals: Record<string, DismissalKind> | undefined,
): number {
  if (!dismissals || Object.keys(dismissals).length === 0) return originalScore;
  if (passages.length === 0) return originalScore;
  let total = 0;
  let dismissed = 0;
  for (const p of passages) {
    const w = p.similarity_score ?? 0;
    total += w;
    if (dismissals[passageKey(p)] !== undefined) dismissed += w;
  }
  if (total <= 0) return originalScore;
  const remaining = Math.max(0, 1 - dismissed / total);
  return Math.round(originalScore * remaining * 10) / 10;
}

/** Returns the set of `source` URLs/names that have *every* passage dismissed. */
export function fullyDismissedSources(
  passages: Array<{ text: string; source?: string | null }>,
  dismissals: Record<string, DismissalKind> | undefined,
): Set<string> {
  if (!dismissals || Object.keys(dismissals).length === 0) return new Set();
  const bySource = new Map<string, { total: number; dismissed: number }>();
  for (const p of passages) {
    const src = p.source ?? "";
    if (!src) continue;
    const slot = bySource.get(src) ?? { total: 0, dismissed: 0 };
    slot.total += 1;
    if (dismissals[passageKey(p)] !== undefined) slot.dismissed += 1;
    bySource.set(src, slot);
  }
  const out = new Set<string>();
  bySource.forEach((v, k) => {
    if (v.total > 0 && v.dismissed === v.total) out.add(k);
  });
  return out;
}

export const dismissalLabel: Record<DismissalKind, string> = {
  quotation: "Quotation",
  prior_work: "My prior work",
  false_positive: "Not a match",
};
