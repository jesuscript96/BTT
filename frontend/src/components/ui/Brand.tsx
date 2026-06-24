"use client";

import React from "react";
import { color, font } from "./tokens";

/**
 * Edgecute isotipo. ALWAYS an SVG with these exact coordinates — never built
 * from divs. The bars use bg-base so they invert automatically between dark
 * (#16181A) and light (#F5F4F1) themes. Copper square is fixed.
 */
export function Isotipo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 90 90" style={{ flexShrink: 0 }} aria-hidden>
      <rect x="0" y="0" width="90" height="90" rx="8" fill={color.copper} />
      <rect x="20" y="18" width="52" height="10" fill="var(--color-ec-bg-base)" />
      <rect x="20" y="40" width="38" height="10" fill="var(--color-ec-bg-base)" />
      <rect x="20" y="62" width="52" height="10" fill="var(--color-ec-bg-base)" />
    </svg>
  );
}

/** Wordmark text. General Sans 700, tight tracking. */
export function Wordmark({ size = 17 }: { size?: number }) {
  return (
    <span style={{ fontFamily: font.sans, fontWeight: 700, fontSize: size, letterSpacing: "-0.6px", color: color.textHigh }}>
      Edgecute
    </span>
  );
}

/** Isotipo + wordmark lockup, 10px gap. */
export function Logo({ size = 24, showWordmark = true }: { size?: number; showWordmark?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <Isotipo size={size} />
      {showWordmark && <Wordmark size={Math.round(size * 0.71)} />}
    </span>
  );
}
