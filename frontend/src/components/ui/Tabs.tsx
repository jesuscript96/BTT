"use client";

import React, { type ReactNode } from "react";
import { color, font, motion } from "./tokens";

export interface TabDef<T extends string> {
  id: T;
  label: ReactNode;
  icon?: ReactNode;
}

interface TabsProps<T extends string> {
  tabs: TabDef<T>[];
  value: T;
  onChange: (id: T) => void;
}

/**
 * Folder-style tab bar. Active tab: 3-sided hairline border + 2px copper
 * bottom edge that "merges" into the content panel below. Sits on a hairline
 * baseline that spans the full width.
 */
export function Tabs<T extends string>({ tabs, value, onChange }: TabsProps<T>) {
  return (
    <div role="tablist" style={{ display: "flex", gap: 4, borderBottom: `0.5px solid ${color.border}` }}>
      {tabs.map((tab) => {
        const active = value === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 34,
              padding: "0 14px",
              fontFamily: font.sans,
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.02em",
              cursor: "pointer",
              color: active ? color.textHigh : color.textMuted,
              background: active ? color.bgSurface : "transparent",
              borderTopLeftRadius: "var(--ec-radius-sm)",
              borderTopRightRadius: "var(--ec-radius-sm)",
              borderTop: `0.5px solid ${active ? color.border : "transparent"}`,
              borderLeft: `0.5px solid ${active ? color.border : "transparent"}`,
              borderRight: `0.5px solid ${active ? color.border : "transparent"}`,
              borderBottom: active ? `2px solid ${color.copper}` : "2px solid transparent",
              marginBottom: -0.5,
              transition: `color ${motion.base} ${motion.ease}`,
            }}
            onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = color.textSecondary; }}
            onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = color.textMuted; }}
          >
            {tab.icon}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

interface SegmentedProps<T extends string> {
  options: Array<{ id: T; label: ReactNode }>;
  value: T;
  onChange: (id: T) => void;
  size?: "sm" | "md";
}

/** Compact pill-group toggle (language pickers, view modes). One active fill. */
export function SegmentedControl<T extends string>({ options, value, onChange, size = "md" }: SegmentedProps<T>) {
  const pad = size === "sm" ? "4px 9px" : "5px 11px";
  const fs = size === "sm" ? 11 : 12;
  return (
    <div style={{ display: "inline-flex", gap: 2, background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: "var(--ec-radius-md)", padding: 2 }}>
      {options.map((o) => {
        const active = value === o.id;
        return (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            style={{
              padding: pad,
              fontFamily: font.sans,
              fontSize: fs,
              fontWeight: 600,
              borderRadius: "var(--ec-radius-sm)",
              border: "none",
              cursor: "pointer",
              background: active ? color.bgElevated : "transparent",
              color: active ? color.textHigh : color.textSecondary,
              transition: `background ${motion.fast} ${motion.ease}, color ${motion.fast} ${motion.ease}`,
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
