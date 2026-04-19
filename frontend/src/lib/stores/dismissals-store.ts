"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

/**
 * Per-passage user verdicts. The backend gives us flagged passages; the user
 * gets to push back with one of:
 *   - "quotation"      → properly cited; should not count against the score
 *   - "prior_work"     → user's own previously published material
 *   - "false_positive" → bad source / topical overlap only
 *
 * State is persisted in localStorage so verdicts survive a refresh, and is
 * keyed by `${document_id}::${passage_index}` so two scans of the same doc
 * (re-runs) keep their dismissals straight while two different docs do not
 * collide.
 */

export type DismissalKind = "quotation" | "prior_work" | "false_positive";

interface DismissalsState {
  // documentId → passageIndex → kind
  dismissed: Record<string, Record<number, DismissalKind>>;
  set: (documentId: string, passageIndex: number, kind: DismissalKind) => void;
  clear: (documentId: string, passageIndex: number) => void;
  clearAll: (documentId: string) => void;
  get: (documentId: string, passageIndex: number) => DismissalKind | undefined;
}

export const useDismissalsStore = create<DismissalsState>()(
  persist(
    (set, get) => ({
      dismissed: {},
      set: (documentId, passageIndex, kind) =>
        set((s) => ({
          dismissed: {
            ...s.dismissed,
            [documentId]: {
              ...(s.dismissed[documentId] ?? {}),
              [passageIndex]: kind,
            },
          },
        })),
      clear: (documentId, passageIndex) =>
        set((s) => {
          const doc = { ...(s.dismissed[documentId] ?? {}) };
          delete doc[passageIndex];
          return {
            dismissed: { ...s.dismissed, [documentId]: doc },
          };
        }),
      clearAll: (documentId) =>
        set((s) => {
          const next = { ...s.dismissed };
          delete next[documentId];
          return { dismissed: next };
        }),
      get: (documentId, passageIndex) =>
        get().dismissed[documentId]?.[passageIndex],
    }),
    {
      name: "plagiarism-dismissals-v1",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);

/**
 * Compute a recomputed plagiarism score after the user has marked some
 * passages as dismissed. We approximate the agent-side score by taking the
 * *share* of similarity mass that remains after removing dismissed entries.
 *
 * This is intentionally simple: the original score is whatever the backend
 * computed; the adjusted score scales it by `1 - (dismissed_weight / total_weight)`
 * where weight is each passage's similarity_score. If the backend reported
 * 60% but half the similarity-weight has been dismissed as quotation, the
 * adjusted score reads 30%. This is shown as a *separate* "Adjusted" pill,
 * never as a replacement for the original verdict.
 */
export function adjustedScore(
  originalScore: number,
  passages: Array<{ similarity_score: number }>,
  dismissals: Record<number, DismissalKind> | undefined,
): number {
  if (!dismissals || Object.keys(dismissals).length === 0) return originalScore;
  if (passages.length === 0) return originalScore;
  let total = 0;
  let dismissed = 0;
  passages.forEach((p, i) => {
    const w = p.similarity_score ?? 0;
    total += w;
    if (dismissals[i] !== undefined) dismissed += w;
  });
  if (total <= 0) return originalScore;
  const remaining = Math.max(0, 1 - dismissed / total);
  return Math.round(originalScore * remaining * 10) / 10;
}

export const dismissalLabel: Record<DismissalKind, string> = {
  quotation: "Quotation",
  prior_work: "My prior work",
  false_positive: "Not a match",
};
