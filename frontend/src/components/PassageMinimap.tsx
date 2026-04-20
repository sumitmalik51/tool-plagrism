"use client";

import { useEffect, useState, useMemo } from "react";
import type { FlaggedPassage } from "@/lib/types";
import { passageBand } from "@/lib/utils";
import {
  passageKey,
  useDismissalsStore,
} from "@/lib/stores/dismissals-store";
import { passageAnchorId } from "@/lib/anchors";
import Tooltip from "@/components/ui/Tooltip";

interface PassageMinimapProps {
  documentId: string;
  passages: FlaggedPassage[];
}

/**
 * Sticky vertical minimap. One notch per passage colored by its severity band.
 * Click a notch to scroll to the matching PassageCard. Dismissed passages
 * render at reduced opacity. The bar is hidden on small viewports — it is a
 * pure desktop convenience and the passages already render below in a list.
 */
export default function PassageMinimap({
  documentId,
  passages,
}: PassageMinimapProps) {
  const dismissedMap = useDismissalsStore((s) => s.dismissed[documentId] ?? {});
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  const items = useMemo(
    () =>
      passages.map((p, i) => {
        const key = passageKey(p);
        const pct = (p.similarity_score ?? 0) * 100;
        return {
          i,
          key,
          band: passageBand(pct),
          pct,
          dismissed: !!dismissedMap[key],
          excerpt: (p.text ?? "").slice(0, 80),
        };
      }),
    [passages, dismissedMap],
  );

  // Track which passage is closest to the viewport center so the minimap can
  // highlight it. Uses IntersectionObserver to avoid scroll-listener thrash.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const visible = new Map<string, number>(); // key -> intersectionRatio
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const k = e.target.id.replace(/^passage-/, "");
          if (e.isIntersecting) visible.set(k, e.intersectionRatio);
          else visible.delete(k);
        }
        let bestKey: string | null = null;
        let bestRatio = 0;
        for (const [k, r] of visible) {
          if (r > bestRatio) {
            bestRatio = r;
            bestKey = k;
          }
        }
        if (bestKey) {
          const idx = items.findIndex((x) => x.key === bestKey);
          if (idx >= 0) setActiveIdx(idx);
        }
      },
      { rootMargin: "-30% 0px -50% 0px", threshold: [0, 0.25, 0.5, 1] },
    );
    for (const it of items) {
      const el = document.getElementById(passageAnchorId(it.key));
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <div
      aria-label="Passage minimap"
      className="hidden xl:flex fixed top-32 right-4 z-30 flex-col gap-1 py-2 px-1 bg-surface/80 backdrop-blur border border-border/40 rounded-lg max-h-[60vh] overflow-y-auto shadow-sm"
    >
      <span className="text-[9px] font-semibold uppercase tracking-wider text-muted px-1 mb-1">
        Map
      </span>
      {items.map((it) => (
        <Tooltip
          key={it.key}
          side="left"
          content={`#${it.i + 1} · ${it.band.label} · ${it.pct.toFixed(0)}%${
            it.dismissed ? " · dismissed" : ""
          }${it.excerpt ? ` — ${it.excerpt}…` : ""}`}
        >
          <button
            type="button"
            onClick={() => {
              const el = document.getElementById(passageAnchorId(it.key));
              el?.scrollIntoView({ behavior: "smooth", block: "center" });
              setActiveIdx(it.i);
            }}
            aria-label={`Jump to passage ${it.i + 1}, ${it.band.label} ${it.pct.toFixed(0)}%`}
            className={`block w-3 h-2 rounded-sm transition-all ${it.band.dotClass} ${
              it.dismissed ? "opacity-30" : ""
            } ${
              activeIdx === it.i
                ? "ring-2 ring-accent ring-offset-1 ring-offset-bg scale-110"
                : "hover:scale-110"
            }`}
          />
        </Tooltip>
      ))}
    </div>
  );
}
