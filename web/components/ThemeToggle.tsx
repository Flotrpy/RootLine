"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

// Light/dark switch. Follows the system until the visitor chooses; the
// choice is remembered in this browser only.
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem("rootline-theme");
    } catch {
      /* storage blocked: follow the system */
    }
    const system: Theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    setTheme(saved === "light" || saved === "dark" ? saved : system);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("rootline-theme", next);
    } catch {
      /* not remembered, still applied */
    }
  };

  return (
    <button
      type="button"
      className="theme"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      title="Theme"
    >
      <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
        <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10 3 A7 7 0 0 1 10 17 Z" fill="currentColor" />
      </svg>
    </button>
  );
}
