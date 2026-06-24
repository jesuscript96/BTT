"use client";

import React, { useEffect, useRef, useState, type ReactNode } from "react";
import { Check } from "lucide-react";
import { color, font, motion } from "./tokens";

interface DropdownProps {
  /** Render-prop trigger; receives open state + toggle. */
  trigger: (args: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode;
  align?: "left" | "right";
  /** Menu width; defaults to auto (min 220). */
  width?: number;
}

/**
 * Anchored popover menu. Closes on outside-click and Escape. Panel uses the
 * elevated popover treatment: bg-surface, hairline border, shadow-lg.
 */
export function Dropdown({ trigger, children, align = "left", width }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            [align]: 0,
            minWidth: width ?? 220,
            width,
            background: color.bgSurface,
            border: `0.5px solid ${color.border}`,
            borderRadius: "var(--ec-radius-lg)",
            boxShadow: "var(--ec-shadow-lg)",
            zIndex: 50,
            overflow: "hidden",
            padding: 4,
            animation: `ec-pop-in ${motion.fast} ${motion.ease}`,
          } as React.CSSProperties}
          onClick={(e) => e.stopPropagation()}
        >
          {children}
        </div>
      )}
    </div>
  );
}

interface MenuItemProps {
  children: ReactNode;
  onSelect?: () => void;
  active?: boolean;
  disabled?: boolean;
  danger?: boolean;
  icon?: ReactNode;
  /** Show a check on the right when active (multi-select / toggle menus). */
  checkable?: boolean;
}
export function MenuItem({ children, onSelect, active, disabled, danger, icon, checkable }: MenuItemProps) {
  const fg = danger ? color.loss : active ? color.copperBright : color.textPrimary;
  return (
    <button
      role="menuitem"
      disabled={disabled}
      onClick={onSelect}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        textAlign: "left",
        padding: "7px 10px",
        borderRadius: "var(--ec-radius-sm)",
        border: "none",
        borderLeft: active ? `3px solid ${color.copper}` : "3px solid transparent",
        background: active ? "rgba(216,122,61,0.12)" : "transparent",
        color: fg,
        fontFamily: font.sans,
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: `background ${motion.fast} ${motion.ease}`,
      }}
      onMouseEnter={(e) => { if (!disabled && !active) { e.currentTarget.style.background = color.bgElevated; e.currentTarget.style.color = color.textHigh; } }}
      onMouseLeave={(e) => { if (!disabled && !active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = fg; } }}
    >
      {icon && <span style={{ display: "inline-flex", color: "inherit" }}>{icon}</span>}
      <span style={{ flex: 1 }}>{children}</span>
      {checkable && active && <Check size={14} />}
    </button>
  );
}

/** Sticky section header inside a menu/dropdown. */
export function MenuLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{ fontFamily: font.sans, fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: color.textSecondary, padding: "8px 10px 4px" }}>
      {children}
    </div>
  );
}

export function MenuSeparator() {
  return <div style={{ height: 0.5, background: color.border, margin: "4px 0" }} />;
}
