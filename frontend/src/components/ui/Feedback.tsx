"use client";

import React, { type ReactNode, type CSSProperties } from "react";
import { Loader2 } from "lucide-react";
import { color, font, motion } from "./tokens";

/** Spinning loader icon. */
export function Spinner({ size = 16, color: c = "var(--color-ec-copper)" }: { size?: number; color?: string }) {
  return <Loader2 size={size} style={{ animation: "ec-spin 0.7s linear infinite", color: c, flexShrink: 0 }} />;
}

/** Inline loading row with optional label. */
export function Loading({ label = "Cargando…", style }: { label?: string; style?: CSSProperties }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, color: color.textMuted, fontFamily: font.sans, fontSize: 13, padding: 20, ...style }}>
      <Spinner size={14} color={color.textMuted} />
      {label}
    </div>
  );
}

/** Three-dot blinking indicator (Edgie / chat typing). Uses dot-blink keyframe. */
export function LoadingDots({ color: c = "var(--color-ec-copper)" }: { color?: string }) {
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      {[0, 1, 2].map((i) => (
        <span key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: c, animation: `dot-blink 1.4s infinite ${i * 0.16}s` }} />
      ))}
    </span>
  );
}

/** Inline error box (loss-tinted surface). */
export function ErrorBox({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{ background: color.bgSurface, border: `0.5px solid ${color.loss}`, borderRadius: "var(--ec-radius-lg)", color: color.loss, fontFamily: font.sans, fontSize: 13, padding: 16, whiteSpace: "pre-wrap", ...style }}>
      {children}
    </div>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  style?: CSSProperties;
}
/** Centered empty/zero state for empty lists, tables, search results. */
export function EmptyState({ icon, title, description, action, style }: EmptyStateProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 10, padding: "48px 24px", ...style }}>
      {icon && <div style={{ color: color.textMuted, opacity: 0.8 }}>{icon}</div>}
      <div style={{ fontFamily: font.serif, fontSize: 18, fontWeight: 500, color: color.textHigh }}>{title}</div>
      {description && <div style={{ fontFamily: font.sans, fontSize: 13, color: color.textSecondary, maxWidth: 380, lineHeight: 1.5 }}>{description}</div>}
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

/** Shimmer placeholder block for loading skeletons. */
export function Skeleton({ width, height = 14, radius = "var(--ec-radius-xs)", style }: { width?: number | string; height?: number | string; radius?: string; style?: CSSProperties }) {
  return (
    <span
      style={{
        display: "block",
        width: width ?? "100%",
        height,
        borderRadius: radius,
        background: color.bgElevated,
        position: "relative",
        overflow: "hidden",
        ...style,
      }}
    >
      <span
        style={{
          position: "absolute",
          inset: 0,
          transform: "translateX(-100%)",
          background: `linear-gradient(90deg, transparent, ${color.surfaceHover}, transparent)`,
          animation: `ec-shimmer 1.4s ${motion.ease} infinite`,
        }}
      />
    </span>
  );
}
