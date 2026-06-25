"use client";

import React, { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { color, font, motion } from "./tokens";
import { IconButton } from "./Button";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  /** Eyebrow above the title (copper uppercase). */
  eyebrow?: ReactNode;
  children: ReactNode;
  /** Footer actions row (right-aligned). */
  footer?: ReactNode;
  width?: number;
  /** Disable closing on backdrop click (e.g. destructive confirmations). */
  disableBackdropClose?: boolean;
}

/**
 * Centered modal dialog. Dark-copper treatment: surface panel, xl radius,
 * xl shadow, blurred backdrop. Closes on Escape and backdrop click.
 */
export function Modal({ open, onClose, title, eyebrow, children, footer, width = 460, disableBackdropClose }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => { if (!disableBackdropClose && e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        background: "rgba(0,0,0,0.55)",
        backdropFilter: "blur(3px)",
        animation: `ec-fade-in ${motion.fast} ${motion.ease}`,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: width,
          maxHeight: "calc(100dvh - 32px)",
          display: "flex",
          flexDirection: "column",
          background: color.bgSurface,
          border: `0.5px solid ${color.border}`,
          borderRadius: "var(--ec-radius-xl)",
          boxShadow: "var(--ec-shadow-xl)",
          overflow: "hidden",
          animation: `ec-pop-in ${motion.base} ${motion.ease}`,
        }}
      >
        {(title || eyebrow) && (
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "18px 20px", borderBottom: `0.5px solid ${color.border}` }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {eyebrow && <span style={{ fontFamily: font.sans, fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "2px", color: color.copper }}>{eyebrow}</span>}
              {title && <h2 style={{ fontFamily: font.serif, fontSize: 20, fontWeight: 600, color: color.textHigh, letterSpacing: "-0.3px" }}>{title}</h2>}
            </div>
            <IconButton label="Cerrar" dimension={28} onClick={onClose}><X size={16} /></IconButton>
          </div>
        )}

        <div style={{ padding: 20, overflowY: "auto", fontFamily: font.sans, fontSize: 13, color: color.textPrimary, lineHeight: 1.55 }}>
          {children}
        </div>

        {footer && (
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "14px 20px", borderTop: `0.5px solid ${color.border}`, background: color.bgBase }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
