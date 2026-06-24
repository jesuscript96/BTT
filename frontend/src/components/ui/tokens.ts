// Edgecute Design System — token mirror for inline styles.
//
// The single source of truth for *values* is `globals.css` (CSS custom
// properties). This module re-exports them as `var(--…)` references so React
// components written with inline `style={{}}` (the dominant convention in this
// codebase) can consume tokens without hardcoding hex codes.
//
// Rule: never write a raw hex/px design value in a component. Reach for a token
// here, or for the CSS variable directly.

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind-aware className combiner (clsx + tailwind-merge). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export const font = {
  sans: "var(--color-ec-sans)",
  serif: "var(--color-ec-serif)",
  mono: "var(--color-ec-mono)",
} as const;

export const color = {
  copper: "var(--color-ec-copper)",
  copperBright: "var(--color-ec-copper-bright)",
  copperText: "var(--color-ec-copper-text)",
  bgSidebar: "var(--color-ec-bg-sidebar)",
  bgBase: "var(--color-ec-bg-base)",
  bgSurface: "var(--color-ec-bg-surface)",
  bgElevated: "var(--color-ec-bg-elevated)",
  surfaceHover: "var(--color-ec-surface-hover)",
  border: "var(--color-ec-border)",
  textMuted: "var(--color-ec-text-muted)",
  textSecondary: "var(--color-ec-text-secondary)",
  textPrimary: "var(--color-ec-text-primary)",
  textHigh: "var(--color-ec-text-high)",
  profit: "var(--color-ec-profit)",
  loss: "var(--color-ec-loss)",
  warning: "var(--color-ec-warning)",
  info: "var(--color-ec-info)",
} as const;

export const radius = {
  xs: "var(--ec-radius-xs)",
  sm: "var(--ec-radius-sm)",
  md: "var(--ec-radius-md)",
  lg: "var(--ec-radius-lg)",
  xl: "var(--ec-radius-xl)",
  pill: "var(--ec-radius-pill)",
} as const;

export const space = {
  1: "var(--ec-space-1)",
  2: "var(--ec-space-2)",
  3: "var(--ec-space-3)",
  4: "var(--ec-space-4)",
  5: "var(--ec-space-5)",
  6: "var(--ec-space-6)",
  8: "var(--ec-space-8)",
  10: "var(--ec-space-10)",
  12: "var(--ec-space-12)",
} as const;

export const shadow = {
  sm: "var(--ec-shadow-sm)",
  md: "var(--ec-shadow-md)",
  lg: "var(--ec-shadow-lg)",
  xl: "var(--ec-shadow-xl)",
  ringCopper: "var(--ec-ring-copper)",
} as const;

export const z = {
  base: "var(--ec-z-base)",
  sticky: "var(--ec-z-sticky)",
  dropdown: "var(--ec-z-dropdown)",
  overlay: "var(--ec-z-overlay)",
  modal: "var(--ec-z-modal)",
  toast: "var(--ec-z-toast)",
  tooltip: "var(--ec-z-tooltip)",
} as const;

export const motion = {
  ease: "var(--ec-ease)",
  fast: "var(--ec-dur-fast)",
  base: "var(--ec-dur-base)",
  slow: "var(--ec-dur-slow)",
  slower: "var(--ec-dur-slower)",
} as const;

/** Standard hairline border used everywhere (0.5px). */
export const hairline = `0.5px solid ${color.border}`;

/** Default Lucide icon props: 1.5px stroke is the house style. */
export const iconProps = { strokeWidth: 1.5 } as const;
export const iconSize = { sm: 14, md: 16, lg: 18, xl: 20 } as const;
