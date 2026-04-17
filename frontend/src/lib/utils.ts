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
