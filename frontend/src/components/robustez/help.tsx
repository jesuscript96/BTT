"use client";

import React from "react";
import { createPortal } from "react-dom";
import { color, font, radius } from "@/components/ui/tokens";

/* ────────────────────────────────────────────────────────────────
   Ayuda contextual, pestañas anidadas y variantes sin tarjeta.
   ──────────────────────────────────────────────────────────────── */

/**
 * Icono de ayuda con globo al pasar el puntero.
 *
 * Va por portal a `document.body` a proposito: los paneles de esta pagina
 * tienen scroll y `overflow` propio, y un globo posicionado dentro se recorta
 * justo cuando el icono esta cerca del borde — que es casi siempre.
 */
export function Help({
  children,
  title,
  width = 330,
}: {
  children: React.ReactNode;
  title?: string;
  width?: number;
}) {
  const [open, setOpen] = React.useState(false);
  const [pos, setPos] = React.useState({ top: 0, left: 0, above: true });
  const ref = React.useRef<HTMLSpanElement>(null);

  const place = React.useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const above = r.top > 240;
    setPos({
      top: above ? r.top - 8 : r.bottom + 8,
      left: Math.min(
        Math.max(r.left + r.width / 2, width / 2 + 10),
        window.innerWidth - width / 2 - 10,
      ),
      above,
    });
  }, [width]);

  React.useEffect(() => {
    if (!open) return;
    place();
    window.addEventListener("scroll", place, { capture: true, passive: true });
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, { capture: true });
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  return (
    <>
      <span
        ref={ref}
        tabIndex={0}
        role="button"
        aria-label={title ? `Ayuda: ${title}` : "Ayuda"}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 13,
          height: 13,
          borderRadius: "50%",
          border: `0.5px solid ${open ? color.copper : color.textMuted}`,
          color: open ? color.copper : color.textMuted,
          fontSize: 9,
          fontFamily: font.sans,
          lineHeight: 1,
          cursor: "help",
          flexShrink: 0,
          verticalAlign: "middle",
          transition: "color 120ms, border-color 120ms",
          outline: "none",
        }}
      >
        ?
      </span>
      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            role="tooltip"
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              transform: pos.above ? "translate(-50%, -100%)" : "translate(-50%, 0)",
              zIndex: 2000,
              width,
              background: color.bgElevated,
              border: `0.5px solid ${color.border}`,
              borderLeft: `2px solid ${color.copper}`,
              borderRadius: radius.md,
              boxShadow: "var(--ec-shadow-lg)",
              padding: "10px 13px",
              pointerEvents: "none",
            }}
          >
            {title && (
              <div
                style={{
                  fontSize: 10,
                  letterSpacing: "0.09em",
                  textTransform: "uppercase",
                  color: color.copper,
                  fontFamily: font.sans,
                  marginBottom: 6,
                }}
              >
                {title}
              </div>
            )}
            <div style={{ fontSize: 11.5, lineHeight: 1.55, fontFamily: font.sans, color: color.textPrimary }}>
              {children}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

/** Pestañas anidadas dentro del panel de resultados. */
export function SubTabs<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string }>;
}) {
  return (
    <div style={{ display: "flex", gap: 2, borderBottom: `0.5px solid ${color.border}`, marginBottom: 20 }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            style={{
              padding: "8px 16px",
              fontSize: 12.5,
              fontFamily: font.sans,
              background: "transparent",
              border: "none",
              borderBottom: `2px solid ${active ? color.copper : "transparent"}`,
              color: active ? color.textHigh : color.textMuted,
              cursor: "pointer",
              marginBottom: -0.5,
              transition: "color 120ms, border-color 120ms",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Metricas SIN tarjeta: directamente sobre el fondo.
 * Para datos de contexto (tiempos, recuentos) que no deben competir
 * visualmente con las cifras del analisis.
 */
export function PlainStats({
  items,
  min = 140,
}: {
  items: Array<{ label: string; value: string; sub?: string; help?: React.ReactNode; tone?: string }>;
  min?: number;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
        gap: "16px 28px",
        padding: "2px",
      }}
    >
      {items.map((it) => (
        <div key={it.label} style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              fontSize: 9,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: color.textMuted,
              fontFamily: font.sans,
            }}
          >
            {it.label}
            {it.help && <Help title={it.label}>{it.help}</Help>}
          </span>
          <span
            style={{
              fontSize: 17,
              fontFamily: font.mono,
              color: it.tone || color.textHigh,
              lineHeight: 1.15,
            }}
          >
            {it.value}
          </span>
          {it.sub && (
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{it.sub}</span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Aviso de que la configuracion cambio y lo que se ve en pantalla es viejo. */
export function StaleNotice({ onRun, label = "Re-ejecutar" }: { onRun?: () => void; label?: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        borderLeft: `2px solid ${color.warning}`,
        background: color.bgSurface,
        padding: "9px 13px",
        borderRadius: `0 ${radius.sm} ${radius.sm} 0`,
        fontSize: 11.5,
        fontFamily: font.sans,
        color: color.textSecondary,
        lineHeight: 1.5,
      }}
    >
      <span style={{ flex: 1 }}>
        Has cambiado la configuracion. Lo de abajo es el resultado <strong>anterior</strong> — vuelve a
        ejecutar para actualizarlo.
      </span>
      {onRun && (
        <button
          type="button"
          onClick={onRun}
          style={{
            padding: "5px 11px",
            fontSize: 11,
            fontFamily: font.sans,
            border: "none",
            borderRadius: radius.sm,
            background: color.copper,
            color: color.copperText,
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          {label}
        </button>
      )}
    </div>
  );
}

/** Veredicto: aprobado / con reservas / suspenso. */
export function Verdict({
  level,
  title,
  children,
}: {
  level: "pass" | "warn" | "fail";
  title: string;
  children: React.ReactNode;
}) {
  const tone = level === "pass" ? color.profit : level === "warn" ? color.warning : color.loss;
  const mark = level === "pass" ? "✓" : level === "warn" ? "!" : "✕";
  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        alignItems: "flex-start",
        background: color.bgSurface,
        border: `0.5px solid ${color.border}`,
        borderLeft: `2px solid ${tone}`,
        borderRadius: `0 ${radius.md} ${radius.md} 0`,
        padding: "14px 16px",
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 26,
          height: 26,
          borderRadius: "50%",
          border: `1px solid ${tone}`,
          color: tone,
          fontSize: 13,
          fontFamily: font.sans,
          flexShrink: 0,
        }}
      >
        {mark}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14, fontFamily: font.sans, color: tone, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12, fontFamily: font.sans, color: color.textSecondary, lineHeight: 1.6 }}>
          {children}
        </div>
      </div>
    </div>
  );
}
