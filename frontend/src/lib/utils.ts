import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function scoreColor(score: number): string {
  if (score <= 20) return "text-ok";
  if (score <= 50) return "text-warn";
  return "text-danger";
}

export function scoreBgColor(score: number): string {
  if (score <= 20) return "bg-ok";
  if (score <= 50) return "bg-warn";
  return "bg-danger";
}

export function riskBadgeColor(risk: string): string {
  switch (risk.toUpperCase()) {
    case "LOW":
      return "bg-ok/20 text-ok";
    case "MEDIUM":
      return "bg-warn/20 text-warn";
    case "HIGH":
      return "bg-danger/20 text-danger";
    default:
      return "bg-muted/20 text-muted";
  }
}

/**
 * Document-level risk thresholds. Mirror `risk_threshold_*` in
 * `app/config.py` and `classify_risk` in `app/services/confidence.py`.
 * Surfaced in tooltips so the Risk badge isn't a black box.
 */
export const RISK_THRESHOLDS = {
  medium: 30, // ≥ 30% → MEDIUM
  high: 60, // ≥ 60% AND confidence ≥ 40% → HIGH
} as const;

export const RISK_TOOLTIP =
  `LOW < ${RISK_THRESHOLDS.medium}% · MEDIUM ${RISK_THRESHOLDS.medium}-${RISK_THRESHOLDS.high - 1}% · ` +
  `HIGH ≥ ${RISK_THRESHOLDS.high}% (with confidence ≥ 40%). ` +
  `Based on document-level overlap and agent agreement. ` +
  `This is a flag for human review, not a verdict.`;

export function formatDate(date: string | Date): string {
  return new Date(date).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function truncate(str: string, len: number): string {
  return str.length > len ? str.slice(0, len) + "…" : str;
}

export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

// ---------------------------------------------------------------------------
// Passage-level severity bands (DECOUPLED from document-level scoreColor).
// scoreColor() colors a 60% document plagiarism rate the same red as a 95%
// verbatim copy of a sentence — fine at the document level, alarming at the
// per-passage level. passageBand() gives passages their own scale where
// "moderate semantic similarity" is amber-neutral, not red-danger.
// ---------------------------------------------------------------------------

export type PassageSeverity = "weak" | "moderate" | "strong" | "verbatim";

export interface PassageBand {
  severity: PassageSeverity;
  /** Short label rendered as a chip ("Weak similarity", "Strong match"). */
  label: string;
  /** Tailwind color class for inline text (the chip and percentage). */
  textClass: string;
  /** Tailwind class for the left-border + faint background tint. */
  borderClass: string;
  bgClass: string;
  /**
   * Tailwind class for a small severity dot indicator.
   * Always a literal class name — never derived via .replace() at runtime,
   * so Tailwind's JIT can statically detect it.
   */
  dotClass: string;
  /** Severity dots (●●●○ etc.) — accessibility for colorblind users. */
  dots: string;
}

export function passageBand(score: number): PassageBand {
  // score is on a 0-100 scale (e.g. similarity_score * 100)
  if (score >= 90) {
    return {
      severity: "verbatim",
      label: "Near-verbatim",
      textClass: "text-danger",
      borderClass: "border-danger",
      bgClass: "bg-danger/10",
      dotClass: "bg-danger",
      dots: "●●●",
    };
  }
  if (score >= 70) {
    return {
      severity: "strong",
      label: "Strong match",
      textClass: "text-danger/90",
      borderClass: "border-danger/70",
      bgClass: "bg-danger/5",
      dotClass: "bg-danger/80",
      dots: "●●●",
    };
  }
  if (score >= 40) {
    return {
      severity: "moderate",
      label: "Moderate similarity",
      textClass: "text-warn",
      borderClass: "border-warn/60",
      bgClass: "bg-warn/5",
      dotClass: "bg-warn",
      dots: "●●○",
    };
  }
  return {
    severity: "weak",
    label: "Weak similarity",
    textClass: "text-muted",
    borderClass: "border-border",
    bgClass: "bg-surface2/40",
    dotClass: "bg-muted",
    dots: "●○○",
  };
}

/**
 * Generate a plain-language explanation for why a passage was flagged.
 * Use the backend-provided `reason` if present; otherwise derive copy from
 * the severity band so users never see the legacy "closely matches" string.
 */
export function passageExplanation(
  reason: string | undefined,
  score: number,
): string {
  if (reason && reason.trim()) return reason.trim();
  const band = passageBand(score);
  switch (band.severity) {
    case "verbatim":
      return "Near-verbatim overlap with the source — substantial copied text.";
    case "strong":
      return "Strong textual overlap with the source — substantial shared phrasing.";
    case "moderate":
      return "Reworded version of a passage from the source — same structure, different words.";
    case "weak":
    default:
      return (
        "Discusses the same idea as the source. No shared phrases — likely " +
        "independent writing on a common topic."
      );
  }
}
