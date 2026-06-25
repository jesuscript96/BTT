"use client";

import React, { type ReactNode } from "react";
import { color, font } from "./tokens";

export type Tone = "neutral" | "good" | "bad" | "warning" | "info" | "copper";

const TONES: Record<Tone, { fg: string; bd: string }> = {
  neutral: { fg: color.textSecondary, bd: color.border },
  good:    { fg: color.profit, bd: color.profit },
  bad:     { fg: color.loss, bd: color.loss },
  warning: { fg: color.warning, bd: color.warning },
  info:    { fg: color.info, bd: color.info },
  copper:  { fg: color.copperBright, bd: color.copper },
};

/** Rounded pill — status chips, tags. */
export function Pill({ children, tone = "neutral", style }: { children: ReactNode; tone?: Tone; style?: React.CSSProperties }) {
  const c = TONES[tone];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontFamily: font.sans, fontSize: 11, fontWeight: 600, color: c.fg, border: `0.5px solid ${c.bd}`, borderRadius: "var(--ec-radius-pill)", padding: "2px 9px", whiteSpace: "nowrap", ...style }}>
      {children}
    </span>
  );
}

/** Solid-tint badge — squarer than a pill, with a faint filled background. */
export function Badge({ children, tone = "neutral", style }: { children: ReactNode; tone?: Tone; style?: React.CSSProperties }) {
  const c = TONES[tone];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontFamily: font.sans, fontSize: 11, fontWeight: 600, color: c.fg, border: `0.5px solid ${c.bd}`, background: `color-mix(in srgb, transparent 90%, ${c.bd})`, borderRadius: "var(--ec-radius-xs)", padding: "2px 7px", whiteSpace: "nowrap", ...style }}>
      {children}
    </span>
  );
}

/** HTTP status code badge (green 2xx, red otherwise). */
export function StatusBadge({ status }: { status: number }) {
  const ok = status >= 200 && status < 300;
  const c = ok ? color.profit : color.loss;
  return (
    <span style={{ fontFamily: font.mono, fontSize: 12, fontWeight: 700, color: c, border: `1px solid ${c}`, borderRadius: "var(--ec-radius-sm)", padding: "2px 8px" }}>
      {status || "—"}
    </span>
  );
}

const METHOD_COLORS: Record<string, string> = {
  GET: color.profit,
  POST: color.copper,
  PUT: color.warning,
  PATCH: color.warning,
  DELETE: color.loss,
};
/** REST method badge (GET/POST/PUT/DELETE). */
export function MethodBadge({ method }: { method: string }) {
  const c = METHOD_COLORS[method.toUpperCase()] ?? color.textSecondary;
  return (
    <span style={{ fontFamily: font.mono, fontSize: 11, fontWeight: 700, letterSpacing: 0.4, color: c, border: `1px solid ${c}`, borderRadius: "var(--ec-radius-sm)", padding: "2px 7px", background: `color-mix(in srgb, transparent 88%, ${c})` }}>
      {method.toUpperCase()}
    </span>
  );
}
