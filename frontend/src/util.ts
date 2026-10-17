import type { Density, Motion } from "./types";

// Zone colours: distinct on top of camera photos in both themes.
export const PALETTE = ["#58a6ff", "#f78166", "#3fb950", "#d29922", "#bc8cff", "#39c5cf", "#ff7b72", "#e3b341"];

export const DENSITY_LEVELS: Density[] = ["empty", "light", "moderate", "heavy"];
export const MOTION_STATES: Motion[] = ["none", "stopped", "slow", "moving"];

export const DENSITY_LABEL: Record<string, string> = {
  empty: "Empty",
  light: "Light",
  moderate: "Moderate",
  heavy: "Heavy",
  unknown: "Learning",
};
export const MOTION_LABEL: Record<string, string> = {
  none: "No traffic",
  stopped: "Stopped",
  slow: "Slow / partly stopped",
  moving: "Moving",
  unknown: "Flow unknown",
};
export const DENSITY_COLOR: Record<string, string> = {
  empty: "#8b949e",
  light: "#3fb950",
  moderate: "#d29922",
  heavy: "#f85149",
  unknown: "#8b949e",
};
export const MOTION_COLOR: Record<string, string> = { stopped: "#f85149", slow: "#db6d28", moving: "#3fb950" };

/** Colour used for drawing tools on top of camera images (independent of theme). */
export const DRAW_COLOR = "#58a6ff";

export type Theme = "system" | "light" | "dark";

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem("tw-theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(t: Theme) {
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  try {
    localStorage.setItem("tw-theme", t);
  } catch {
    /* storage unavailable; theme still applies for this session */
  }
}

export const DIRECTIONS = ["NB", "SB", "EB", "WB", "Inner loop", "Outer loop", "Toward camera", "Away from camera", "Ramp", "Express"];

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function timeUntil(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const s = Math.round((new Date(iso).getTime() - now) / 1000);
  if (s <= 0) return "now";
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function fmtInterval(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec % 60 === 0) return `${sec / 60} min`;
  return `${(sec / 60).toFixed(1)} min`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : `${v.toFixed(digits)}%`;
}
