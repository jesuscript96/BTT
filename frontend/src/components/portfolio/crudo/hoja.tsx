"use client";

// Primitivos "hoja de datos" de la vista En crudo: sin tarjetas ni esquinas
// redondeadas, separadores hairline, controles cuadrados, cifras grandes sobre
// el fondo y un «?» con explicacion en cada bloque. Son los mismos que usa la
// pagina del Genetico (app/genetico/page.tsx) — copiados, no importados,
// porque alli viven dentro de la pagina y no se exportan.

import React from "react";
import { color, font, hairline } from "@/components/ui/tokens";
import { Help } from "@/components/robustez/help";

export const control: React.CSSProperties = {
  background: color.bgSidebar, border: hairline, borderRadius: 0, color: color.textHigh,
  fontFamily: font.mono, fontSize: 12, padding: "5px 7px", width: "100%", outline: "none", height: 28,
};
export const etiqueta: React.CSSProperties = {
  fontFamily: font.sans, fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.textMuted,
};

export function Sec({ title, help, children, sinRelleno, right }: {
  title: string; help?: React.ReactNode; children: React.ReactNode; sinRelleno?: boolean; right?: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 14, border: `1px solid ${color.border}`, background: color.bgSurface }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderBottom: `1px solid ${color.border}`, background: color.bgElevated }}>
        <span style={{ ...etiqueta, color: color.textSecondary, fontSize: 10 }}>{title}</span>
        {help && <Help title={title}>{help}</Help>}
        {right && <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>{right}</div>}
      </div>
      <div style={{ padding: sinRelleno ? 0 : "2px 10px 6px" }}>{children}</div>
    </section>
  );
}

/** Un paso del flujo de trabajo (16-sep): caja numerada y plegable con una
 *  linea-resumen en la cabecera cuando esta plegada. Un paso «apagado» (el
 *  anterior no se ha calculado) se ve, pero no se abre: asi el recorrido se
 *  intuye sin leer nada. */
export function Paso({ num, title, help, summary, open, onToggle, disabled, disabledNote, right, children, sinRelleno }: {
  num: number; title: string; help?: React.ReactNode; summary?: React.ReactNode; open: boolean; onToggle: () => void;
  disabled?: boolean; disabledNote?: string; right?: React.ReactNode; children: React.ReactNode; sinRelleno?: boolean;
}) {
  const vivo = open && !disabled;
  return (
    <section id={`paso-${num}`} style={{ marginBottom: 14, border: `1px solid ${vivo ? color.copper : color.border}`, background: color.bgSurface, opacity: disabled ? 0.55 : 1 }}>
      <div
        role="button"
        onClick={() => { if (!disabled) onToggle(); }}
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 10px", borderBottom: vivo ? `1px solid ${color.border}` : "none", background: color.bgElevated, cursor: disabled ? "not-allowed" : "pointer", userSelect: "none" }}
      >
        <span style={{ width: 20, height: 20, display: "inline-flex", alignItems: "center", justifyContent: "center", background: vivo ? color.copper : "transparent", border: `1px solid ${vivo ? color.copper : color.textMuted}`, color: vivo ? "#1A0A00" : color.textSecondary, fontFamily: font.mono, fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{num}</span>
        <span style={{ ...etiqueta, color: color.textHigh, fontSize: 10.5, whiteSpace: "nowrap" }}>{title}</span>
        {help && <span onClick={(e) => e.stopPropagation()}><Help title={title}>{help}</Help></span>}
        <span style={{ fontFamily: font.sans, fontSize: 11, color: disabled ? color.textMuted : color.textSecondary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>
          {disabled ? disabledNote : summary}
        </span>
        {right && !disabled && <div onClick={(e) => e.stopPropagation()} style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>{right}</div>}
        <span style={{ marginLeft: right && !disabled ? 0 : "auto", fontFamily: font.mono, fontSize: 11, color: color.textMuted, flexShrink: 0 }}>{vivo ? "▾" : "▸"}</span>
      </div>
      {vivo && <div style={{ padding: sinRelleno ? 0 : "2px 10px 8px" }}>{children}</div>}
    </section>
  );
}

/** La tira de arriba: los pasos y en cual estas. Pulsar uno lo abre. */
export function PasoBar({ pasos, activo, onGo }: { pasos: Array<{ num: number; label: string; hecho: boolean; disponible: boolean }>; activo: number; onGo: (num: number) => void }) {
  return (
    <div style={{ display: "flex", border: hairline, marginBottom: 14, background: color.bgSurface }}>
      {pasos.map((p, i) => {
        const on = p.num === activo;
        return (
          <button key={p.num} type="button" disabled={!p.disponible} onClick={() => onGo(p.num)} style={{
            flex: 1, display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", background: on ? color.bgElevated : "transparent",
            border: "none", borderLeft: i ? hairline : "none", borderBottom: on ? `2px solid ${color.copper}` : "2px solid transparent",
            cursor: p.disponible ? "pointer" : "not-allowed", opacity: p.disponible ? 1 : 0.45, textAlign: "left",
          }}>
            <span style={{ width: 18, height: 18, display: "inline-flex", alignItems: "center", justifyContent: "center", background: p.hecho ? color.copper : "transparent", border: `1px solid ${p.hecho || on ? color.copper : color.textMuted}`, color: p.hecho ? "#1A0A00" : on ? color.copperText : color.textMuted, fontFamily: font.mono, fontSize: 10.5, fontWeight: 700, flexShrink: 0 }}>{p.hecho ? "✓" : p.num}</span>
            <span style={{ fontFamily: font.sans, fontSize: 11.5, fontWeight: on ? 600 : 500, color: on ? color.textHigh : p.hecho ? color.textPrimary : color.textSecondary, whiteSpace: "nowrap" }}>{p.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Pestañas dentro de un paso (las vistas de un mismo resultado). */
export function SubTabs<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: Array<{ value: T; label: string }> }) {
  return (
    <div style={{ display: "flex", gap: 0, borderBottom: hairline, marginBottom: 8 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button key={o.value} type="button" onClick={() => onChange(o.value)} style={{
            padding: "6px 12px", background: "transparent", border: "none", borderBottom: on ? `2px solid ${color.copper}` : "2px solid transparent",
            marginBottom: -1, color: on ? color.textHigh : color.textSecondary, fontFamily: font.sans, fontSize: 11.5, fontWeight: on ? 600 : 500, cursor: "pointer", whiteSpace: "nowrap",
          }}>{o.label}</button>
        );
      })}
    </div>
  );
}

/** Parrafo de lectura: lo que significa lo que se ve, en cristiano. */
export function Nota({ children, tone }: { children: React.ReactNode; tone?: "warning" | "loss" }) {
  return (
    <p style={{ margin: "6px 0 2px", fontSize: 11, fontFamily: font.sans, color: tone === "warning" ? color.warning : tone === "loss" ? color.loss : color.textSecondary, lineHeight: 1.55 }}>{children}</p>
  );
}

export function Row({ label, help, children, wide }: { label: string; help?: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: wide ? "1fr" : "150px 1fr", gap: wide ? 4 : 10, alignItems: "center", padding: "5px 0", borderBottom: hairline }}>
      <span style={{ ...etiqueta, display: "flex", alignItems: "center", gap: 5 }}>{label}{help && <Help title={label}>{help}</Help>}</span>
      <div>{children}</div>
    </div>
  );
}

export function Num({ value, onChange, min, max, step, disabled, placeholder, style }: {
  value: number | ""; onChange: (v: number | "") => void; min?: number; max?: number; step?: number; disabled?: boolean; placeholder?: string; style?: React.CSSProperties;
}) {
  return (
    <input
      type="number"
      style={{ ...control, opacity: disabled ? 0.5 : 1, ...style }}
      value={value}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    />
  );
}

export function Toggle<T extends string>({ value, onChange, options, disabled }: { value: T; onChange: (v: T) => void; options: Array<{ value: T; label: string }>; disabled?: boolean }) {
  return (
    <div style={{ display: "flex", border: hairline, opacity: disabled ? 0.5 : 1 }}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button key={o.value} type="button" disabled={disabled} onClick={() => onChange(o.value)} style={{
            flex: 1, height: 26, minWidth: 0, padding: "0 8px", background: on ? color.bgElevated : "transparent", color: on ? color.textHigh : color.textSecondary,
            border: "none", borderLeft: i ? hairline : "none", borderBottom: on ? `2px solid ${color.copper}` : "2px solid transparent",
            fontFamily: font.sans, fontSize: 11.5, cursor: disabled ? "default" : "pointer",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{o.label}</button>
        );
      })}
    </div>
  );
}

export function Btn({ onClick, children, danger, primary, disabled, title }: { onClick: () => void; children: React.ReactNode; danger?: boolean; primary?: boolean; disabled?: boolean; title?: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title} style={{
      background: primary ? color.copper : "transparent",
      color: primary ? "#1A0A00" : danger ? color.loss : color.textPrimary,
      border: primary ? `1px solid ${color.copper}` : `1px solid ${danger ? color.loss : color.border}`,
      borderRadius: 0, padding: "5px 12px", fontFamily: font.sans, fontSize: 11.5, fontWeight: primary ? 600 : 500,
      cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.45 : 1, height: 28, whiteSpace: "nowrap",
    }}>{children}</button>
  );
}

export function Stat({ label, value, sub, help, tone, big }: { label: string; value: string; sub?: string; help?: React.ReactNode; tone?: "profit" | "loss" | "warning"; big?: boolean }) {
  const c = tone === "profit" ? color.profit : tone === "loss" ? color.loss : tone === "warning" ? color.warning : color.textHigh;
  return (
    <div style={{ padding: "6px 18px 6px 0", borderRight: hairline, minWidth: 110 }}>
      <div style={{ ...etiqueta, display: "flex", alignItems: "center", gap: 5 }}>{label}{help && <Help title={label}>{help}</Help>}</div>
      <div style={{ fontFamily: font.mono, fontSize: big ? 22 : 18, lineHeight: 1.2, color: c, marginTop: 2, whiteSpace: "nowrap" }}>{value}</div>
      {sub && <div style={{ fontFamily: font.sans, fontSize: 10.5, color: color.textMuted, whiteSpace: "nowrap" }}>{sub}</div>}
    </div>
  );
}

/* ── Formato (propio, sin ICU: identico en servidor y cliente) ─────── */

const miles = (entero: string) => entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
export const n = (v: number | null | undefined, d = 2) => {
  if (v === null || v === undefined || Number.isNaN(v) || !Number.isFinite(v)) return "—";
  // Por encima de un billon el numero ya no se lee con puntos de miles: va en
  // notacion cientifica (pasa al componer un % por trade con miles de trades).
  if (Math.abs(v) >= 1e12) return `${v < 0 ? "−" : ""}${Math.abs(v).toExponential(2).replace(".", ",").replace("e+", "·10^")}`;
  const [ent, dec] = Math.abs(v).toFixed(d).split(".");
  return `${v < 0 ? "−" : ""}${miles(ent)}${dec ? `,${dec}` : ""}`;
};
export const usd = (v: number | null | undefined, d = 0) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : `${n(v, d)} $`);
export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : `${n(v, d)} %`);
/** Dolares compactos para ejes: 1,2k · 350 · 2,5M. */
export const usdCorto = (v: number) => {
  const a = Math.abs(v);
  const s = v < 0 ? "−" : "";
  if (a >= 1e12) return `${s}${a.toExponential(1).replace(".", ",").replace("e+", "·10^")}`;
  if (a >= 1e9) return `${s}${n(a / 1e9, a >= 1e10 ? 0 : 1)}B`;
  if (a >= 1e6) return `${s}${n(a / 1e6, a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `${s}${n(a / 1e3, a >= 1e4 ? 0 : 1)}k`;
  return `${s}${n(a, 0)}`;
};

/* ── Estilos de tabla (hoja de datos) ─────────────────────────────── */

export const thL: React.CSSProperties = { textAlign: "left", padding: "5px 8px", fontSize: 9, fontWeight: 700, letterSpacing: "0.8px", textTransform: "uppercase", color: color.textMuted, borderBottom: `1px solid ${color.border}`, whiteSpace: "nowrap", fontFamily: font.sans };
export const thR: React.CSSProperties = { ...thL, textAlign: "right" };
export const tdTxt: React.CSSProperties = { fontSize: 11.5, padding: "4px 8px", color: color.textHigh, borderBottom: hairline, fontFamily: font.sans, whiteSpace: "nowrap" };
export const tdNum: React.CSSProperties = { ...tdTxt, textAlign: "right", fontFamily: font.mono, color: color.textPrimary };

/** Paleta de las series. Sin cobre ni naranjas: la linea del portfolio
 *  combinado va siempre en cobre y ninguna estrategia debe parecersele. */
export const PALETA = [
  color.info,
  color.profit,
  "#9B8CE6",
  "#5FB7C9",
  "#D97B9A",
  color.warning,
  "#7FA65A",
  "#6E8FD9",
  color.loss,
  "#8899AA",
  "#C9A85F",
  "#4FA3A0",
  "#B07CC6",
];
export const colorSerie = (i: number) => PALETA[i % PALETA.length];
