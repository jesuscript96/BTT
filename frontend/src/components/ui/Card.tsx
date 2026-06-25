"use client";

import React, { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { color, font, hairline, motion } from "./tokens";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Featured card: elevated bg, copper border + 2px copper left rail. */
  featured?: boolean;
  /** Apply hover elevation (bg shift). Use for clickable cards. */
  interactive?: boolean;
  padded?: boolean;
}

/**
 * Surface container. Normal = bg-surface + hairline border, radius md.
 * Featured = bg-elevated + copper border + copper left rail. Per design rule,
 * a featured card's TITLE must never be copper — only its border/eyebrow.
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { featured, interactive, padded = true, children, style, onMouseEnter, onMouseLeave, ...rest },
  ref,
) {
  const baseBg = featured ? color.bgElevated : color.bgSurface;
  return (
    <div
      ref={ref}
      style={{
        background: baseBg,
        border: featured ? `0.5px solid ${color.copper}` : hairline,
        borderLeft: featured ? `2px solid ${color.copper}` : hairline,
        borderRadius: "var(--ec-radius-md)",
        padding: padded ? "16px 18px" : 0,
        transition: `background ${motion.base} ${motion.ease}`,
        cursor: interactive ? "pointer" : undefined,
        ...style,
      }}
      onMouseEnter={(e) => {
        if (interactive) e.currentTarget.style.background = color.bgElevated;
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        if (interactive) e.currentTarget.style.background = baseBg;
        onMouseLeave?.(e);
      }}
      {...rest}
    >
      {children}
    </div>
  );
});

/** Copper uppercase eyebrow — for card "source" labels only. Copper is brand-only. */
export function Eyebrow({ children, bright, style }: { children: ReactNode; bright?: boolean; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        fontFamily: font.sans,
        fontSize: 9,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "2.5px",
        color: bright ? color.copperBright : color.copper,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Fraunces card title. Never copper, even on featured cards. */
export function CardTitle({ children, featured, style }: { children: ReactNode; featured?: boolean; style?: React.CSSProperties }) {
  return (
    <h3
      style={{
        fontFamily: font.serif,
        fontSize: 17,
        fontWeight: featured ? 600 : 500,
        color: featured ? "#F0EEEA" : color.textHigh,
        letterSpacing: "-0.2px",
        ...style,
      }}
    >
      {children}
    </h3>
  );
}

/** General Sans meta line (timestamps, sources, secondary detail). */
export function CardMeta({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ fontFamily: font.sans, fontSize: 10, fontWeight: 500, color: color.textMuted, ...style }}>
      {children}
    </div>
  );
}
