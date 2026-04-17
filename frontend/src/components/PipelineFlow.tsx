"use client";

import { useEffect, useRef, useState } from "react";

const STAGES = ["Input", "Scan", "Verify", "Attribute", "Report"] as const;
const CYCLE_MS = 6000; // full loop duration — slower = smoother

export default function PipelineFlow() {
  // progress is a continuous value in [0, STAGES.length)
  const [progress, setProgress] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    const tick = (t: number) => {
      if (startRef.current === null) startRef.current = t;
      const elapsed = (t - startRef.current) % CYCLE_MS;
      setProgress((elapsed / CYCLE_MS) * STAGES.length);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div className="flex items-center justify-center gap-1 sm:gap-2 mb-20 text-[11px] uppercase tracking-wider overflow-x-auto pb-2">
      {STAGES.map((stage, i) => {
        // distance from the traveling head (0 = exactly on, 1 = one stage away)
        const d = Math.abs(progress - i);
        // smooth bell around the head (0..1)
        const intensity = Math.max(0, 1 - d);
        const isReport = stage === "Report";

        const lit = intensity > 0.5;
        const passed = progress > i + 0.5;

        // gentle scale bump
        const scale = 1 + intensity * 0.08;
        const glow = intensity * 0.22;

        let pillClass =
          "relative px-3 py-1.5 rounded-full whitespace-nowrap border will-change-transform ";
        if (lit) {
          pillClass += isReport
            ? "bg-ok/20 text-ok border-ok/60 "
            : "bg-txt text-bg border-txt ";
        } else if (passed) {
          pillClass += isReport
            ? "border-ok/30 text-ok bg-transparent "
            : "border-transparent bg-txt/10 text-txt ";
        } else {
          pillClass += "border-border/60 text-muted/70 bg-transparent ";
        }

        return (
          <div key={stage} className="flex items-center gap-1 sm:gap-2">
            <span
              className={pillClass}
              style={{
                transform: `scale(${scale})`,
                transition:
                  "background-color 600ms ease, color 600ms ease, border-color 600ms ease, box-shadow 600ms ease",
                boxShadow: lit
                  ? isReport
                    ? `0 0 0 4px rgba(34,197,94,${0.08 + glow})`
                    : `0 0 0 4px rgba(255,255,255,${0.04 + glow})`
                  : "none",
              }}
            >
              {intensity > 0.7 && (
                <span
                  aria-hidden
                  className="absolute inset-0 rounded-full pointer-events-none"
                  style={{
                    background: isReport
                      ? "rgba(34,197,94,0.35)"
                      : "rgba(255,255,255,0.35)",
                    opacity: (intensity - 0.7) * 1.2,
                    transform: `scale(${1 + (intensity - 0.7) * 0.6})`,
                    filter: "blur(5px)",
                  }}
                />
              )}
              <span className="relative">{stage}</span>
            </span>

            {i < STAGES.length - 1 && (
              <Connector progress={progress} index={i} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function Connector({ progress, index }: { progress: number; index: number }) {
  const local = progress - index; // -x before, 0..1 while crossing, >1 after
  const fill = Math.max(0, Math.min(1, local));
  const crossing = local > 0 && local < 1;

  return (
    <div className="relative h-px w-8 sm:w-12 shrink-0 overflow-hidden rounded-full bg-border/40">
      <span
        className="absolute inset-y-0 left-0 bg-txt/70"
        style={{ width: `${fill * 100}%` }}
      />
      {crossing && (
        <span
          aria-hidden
          className="absolute top-1/2 -translate-y-1/2 h-[3px] w-6 rounded-full pointer-events-none"
          style={{
            left: `calc(${local * 100}% - 12px)`,
            background:
              "radial-gradient(ellipse at center, rgba(255,255,255,0.9), rgba(255,255,255,0) 70%)",
            filter: "blur(1px)",
          }}
        />
      )}
    </div>
  );
}
