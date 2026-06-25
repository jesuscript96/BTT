"use client";

import React, { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";
import { color, font, motion } from "./tokens";
import type { Tone } from "./Badge";

type ToastTone = Extract<Tone, "good" | "bad" | "warning" | "info"> | "neutral";

interface ToastItem {
  id: number;
  title: ReactNode;
  description?: ReactNode;
  tone: ToastTone;
}

interface ToastInput {
  title: ReactNode;
  description?: ReactNode;
  tone?: ToastTone;
  /** Auto-dismiss after ms. Default 4000. Pass 0 to require manual close. */
  duration?: number;
}

const ToastContext = createContext<((t: ToastInput) => void) | null>(null);

const TONE_META: Record<ToastTone, { icon: ReactNode; accent: string }> = {
  good:    { icon: <CheckCircle2 size={16} />, accent: color.profit },
  bad:     { icon: <XCircle size={16} />, accent: color.loss },
  warning: { icon: <AlertTriangle size={16} />, accent: color.warning },
  info:    { icon: <Info size={16} />, accent: color.info },
  neutral: { icon: <Info size={16} />, accent: color.textSecondary },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const remove = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);

  const push = useCallback((t: ToastInput) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, title: t.title, description: t.description, tone: t.tone ?? "neutral" }]);
    const duration = t.duration ?? 4000;
    if (duration > 0) setTimeout(() => remove(id), duration);
  }, [remove]);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        style={{
          position: "fixed",
          bottom: 20,
          right: 20,
          zIndex: 120,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          maxWidth: 360,
          pointerEvents: "none",
        }}
      >
        {items.map((t) => {
          const meta = TONE_META[t.tone];
          return (
            <div
              key={t.id}
              role="status"
              style={{
                pointerEvents: "auto",
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                background: color.bgSurface,
                border: `0.5px solid ${color.border}`,
                borderLeft: `2px solid ${meta.accent}`,
                borderRadius: "var(--ec-radius-lg)",
                boxShadow: "var(--ec-shadow-lg)",
                padding: "12px 14px",
                animation: `ec-toast-in ${motion.base} ${motion.ease}`,
              }}
            >
              <span style={{ color: meta.accent, flexShrink: 0, marginTop: 1 }}>{meta.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: font.sans, fontSize: 13, fontWeight: 600, color: color.textHigh }}>{t.title}</div>
                {t.description && <div style={{ fontFamily: font.sans, fontSize: 12, color: color.textSecondary, marginTop: 2, lineHeight: 1.45 }}>{t.description}</div>}
              </div>
              <button
                onClick={() => remove(t.id)}
                aria-label="Cerrar"
                style={{ background: "transparent", border: "none", color: color.textMuted, cursor: "pointer", padding: 2, flexShrink: 0 }}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

/** Returns a `toast({ title, tone })` dispatcher. Requires <ToastProvider>. */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
