"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "dark" | "light";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem("theme") as Theme | null;
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme: Theme, withTransition = false) {
  const html = document.documentElement;
  if (withTransition) {
    html.classList.add("theme-transition");
    // Remove the transition helper after the switch settles, so normal component
    // transitions (e.g. hover) don't get globally overridden.
    window.setTimeout(() => html.classList.remove("theme-transition"), 320);
  }
  html.setAttribute("data-theme", theme);
}

export default function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const initial = getInitialTheme();
    setTheme(initial);
    applyTheme(initial, false);
    setMounted(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next, true);
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* ignore */
    }
  }

  // Avoid hydration mismatch: render a neutral placeholder until mounted.
  if (!mounted) {
    return (
      <button
        aria-label="Toggle theme"
        className={`relative w-9 h-9 rounded-full border border-border/60 ${className}`}
      />
    );
  }

  const isDark = theme === "dark";

  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
      title={`Switch to ${isDark ? "light" : "dark"} mode`}
      className={`relative w-9 h-9 rounded-full border border-border/60 hover:border-txt/40 hover:bg-surface/60 transition-all overflow-hidden group ${className}`}
    >
      <Sun
        className={`absolute inset-0 m-auto w-4 h-4 text-txt transition-all duration-500 ${
          isDark
            ? "opacity-0 rotate-90 scale-50"
            : "opacity-100 rotate-0 scale-100"
        }`}
      />
      <Moon
        className={`absolute inset-0 m-auto w-4 h-4 text-txt transition-all duration-500 ${
          isDark
            ? "opacity-100 rotate-0 scale-100"
            : "opacity-0 -rotate-90 scale-50"
        }`}
      />
    </button>
  );
}
