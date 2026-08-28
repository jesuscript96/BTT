"use client";

import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Pencil } from "lucide-react";
import { color, font, radius } from "@/components/ui/tokens";

/* ────────────────────────────────────────────────────────────────
   Piezas compartidas por los modulos de robustez.
   Todo sale de los tokens del design system: ni un hex suelto.
   ──────────────────────────────────────────────────────────────── */

export const fmt = {
  pct: (v: number | null | undefined, d = 2) =>
    v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "" : ""}${v.toFixed(d)}%`,
  num: (v: number | null | undefined, d = 2) =>
    v == null || !Number.isFinite(v) ? "—" : v.toFixed(d),
  money: (v: number | null | undefined, d = 0) =>
    v == null || !Number.isFinite(v)
      ? "—"
      : `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("es-ES", { maximumFractionDigits: d })}`,
  int: (v: number | null | undefined) =>
    v == null || !Number.isFinite(v) ? "—" : Math.round(v).toLocaleString("es-ES"),
};

/** Titulo de bloque, en cobre y versalitas. */
export function Eyebrow({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        fontSize: 10,
        letterSpacing: "0.11em",
        textTransform: "uppercase",
        color: color.copper,
        fontFamily: font.sans,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Cabecera de seccion dentro del panel de resultados. */
export function SectionHead({
  title,
  hint,
  right,
}: {
  title: string;
  hint?: string;
  right?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 14 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 15, fontFamily: font.sans, color: color.textHigh, marginBottom: hint ? 4 : 0 }}>
          {title}
        </div>
        {hint && (
          <div style={{ fontSize: 12, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5, maxWidth: 680 }}>
            {hint}
          </div>
        )}
      </div>
      {right}
    </div>
  );
}

/** Metrica destacada. `tone` colorea el valor; `hint` explica que mirar. */
export function MetricTile({
  label,
  value,
  sub,
  tone,
  hint,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div
      style={{
        background: color.bgSurface,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: color.textMuted,
          fontFamily: font.sans,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 20, fontFamily: font.mono, color: tone || color.textHigh, lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textSecondary }}>{sub}</div>}
      {hint && (
        <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.45, marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

export function TileGrid({ children, min = 150 }: { children: React.ReactNode; min?: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
        gap: 10,
      }}
    >
      {children}
    </div>
  );
}

/** Nota explicativa: "que valores mirar". Rail cobre a la izquierda. */
export function ReadingNote({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        borderLeft: `2px solid ${color.copper}`,
        background: color.bgSurface,
        padding: "10px 14px",
        borderRadius: `0 ${radius.sm} ${radius.sm} 0`,
        fontSize: 12,
        lineHeight: 1.6,
        fontFamily: font.sans,
        color: color.textSecondary,
      }}
    >
      {children}
    </div>
  );
}

/* ── Controles de configuracion (panel izquierdo) ───────────────── */

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textSecondary }}>{label}</span>
      {children}
      {hint && (
        <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.45 }}>{hint}</span>
      )}
    </label>
  );
}

const controlStyle: React.CSSProperties = {
  background: color.bgBase,
  border: `0.5px solid ${color.border}`,
  borderRadius: radius.sm,
  color: color.textHigh,
  fontFamily: font.mono,
  fontSize: 12.5,
  padding: "7px 9px",
  width: "100%",
  outline: "none",
};

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <input
      type="number"
      value={Number.isFinite(value) ? value : ""}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onChange={(e) => {
        const v = parseFloat(e.target.value);
        onChange(Number.isFinite(v) ? v : 0);
      }}
      style={{ ...controlStyle, opacity: disabled ? 0.5 : 1 }}
      onFocus={(e) => (e.currentTarget.style.borderColor = color.copper)}
      onBlur={(e) => (e.currentTarget.style.borderColor = color.border)}
    />
  );
}

export function TextInput({
  value,
  onChange,
  type = "text",
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  type?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type={type}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      style={{ ...controlStyle, opacity: disabled ? 0.5 : 1 }}
      onFocus={(e) => (e.currentTarget.style.borderColor = color.copper)}
      onBlur={(e) => (e.currentTarget.style.borderColor = color.border)}
    />
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  disabled,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string }>;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as T)}
      style={{ ...controlStyle, fontFamily: font.sans, cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1 }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} style={{ background: color.bgSurface }}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** Control segmentado: alterna entre pocas opciones sin abrir un desplegable. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string }>;
}) {
  return (
    <div
      style={{
        display: "flex",
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        overflow: "hidden",
      }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            style={{
              flex: 1,
              padding: "6px 10px",
              fontSize: 11.5,
              fontFamily: font.sans,
              border: "none",
              cursor: "pointer",
              background: active ? color.copper : "transparent",
              color: active ? color.copperText : color.textSecondary,
              transition: "background 120ms",
              whiteSpace: "nowrap",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function RunButton({
  onClick,
  loading,
  disabled,
  label,
  loadingLabel,
}: {
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  label: string;
  loadingLabel?: string;
}) {
  const off = disabled || loading;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={off}
      style={{
        width: "100%",
        padding: "9px 12px",
        fontSize: 12.5,
        fontFamily: font.sans,
        border: "none",
        borderRadius: radius.sm,
        cursor: off ? "default" : "pointer",
        background: off ? color.bgElevated : color.copper,
        color: off ? color.textMuted : color.copperText,
        transition: "background 120ms",
      }}
    >
      {loading ? loadingLabel || "Calculando…" : label}
    </button>
  );
}

/** Estado vacio / de espera del panel derecho. */
export function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: 260,
        padding: 32,
        textAlign: "center",
        fontFamily: font.sans,
        fontSize: 13,
        color: color.textMuted,
        lineHeight: 1.6,
      }}
    >
      <div style={{ maxWidth: 460 }}>{children}</div>
    </div>
  );
}

/** Nombre con lapiz de renombrado inline: clic en el lapiz lo convierte en un
 *  campo de texto, Enter/blur guarda (via `onRename`), Escape cancela. Lo
 *  usan el Baul de Portfolio (StrategyShelf) y el listado de Robustez
 *  (StrategyPicker), ambos con filas clicables — por eso corta la propagacion
 *  del click en todos sus eventos. */
export function RenameableName({
  name,
  onRename,
  textStyle,
}: {
  name: string;
  onRename: (newName: string) => Promise<void>;
  textStyle?: React.CSSProperties;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!editing) setValue(name);
  }, [name, editing]);

  const cancel = () => {
    setValue(name);
    setFailed(false);
    setEditing(false);
  };

  const commit = async () => {
    const trimmed = value.trim();
    if (!trimmed || trimmed === name) {
      cancel();
      return;
    }
    setSaving(true);
    setFailed(false);
    try {
      await onRename(trimmed);
      setEditing(false);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={value}
        disabled={saving}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          // La fila (StrategyShelf/StrategyPicker) es un role="button" que
          // escucha Espacio/Enter en su propio onKeyDown para desplegarse. Sin
          // cortar la propagacion aqui, cada Espacio burbujea hasta la fila,
          // que le hace preventDefault — el espacio nunca llega al input.
          e.stopPropagation();
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
        }}
        onBlur={commit}
        style={{
          fontSize: 12.5,
          fontFamily: font.sans,
          color: color.textHigh,
          background: color.bgBase,
          border: `0.5px solid ${failed ? color.loss : color.copper}`,
          borderRadius: radius.xs,
          padding: "1px 5px",
          outline: "none",
          minWidth: 140,
          maxWidth: 320,
        }}
      />
    );
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, minWidth: 0, ...textStyle }}>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
      <span
        title="Renombrar"
        onClick={(e) => {
          e.stopPropagation();
          setValue(name);
          setEditing(true);
        }}
        style={{ display: "inline-flex", cursor: "pointer", flexShrink: 0 }}
      >
        <Pencil style={{ width: 11, height: 11, strokeWidth: 1.5, color: color.textMuted }} />
      </span>
    </span>
  );
}

export function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        borderLeft: `2px solid ${color.loss}`,
        background: color.bgSurface,
        padding: "10px 14px",
        borderRadius: `0 ${radius.sm} ${radius.sm} 0`,
        fontSize: 12,
        fontFamily: font.sans,
        color: color.textPrimary,
        lineHeight: 1.55,
      }}
    >
      {children}
    </div>
  );
}

/** Barra de progreso para los modulos que re-ejecutan backtests. */
export function ProgressBar({ pct, label }: { pct: number; label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {label && (
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, fontFamily: font.sans }}>
          <span style={{ color: color.textSecondary }}>{label}</span>
          <span style={{ color: color.copper, fontFamily: font.mono }}>{pct.toFixed(0)}%</span>
        </div>
      )}
      <div style={{ height: 3, background: color.bgElevated, borderRadius: radius.pill, overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: `${Math.max(0, Math.min(100, pct))}%`,
            background: color.copper,
            transition: "width 300ms",
          }}
        />
      </div>
    </div>
  );
}

/** Tabla compacta y monoespaciada, para resultados numericos. */
export function DataTable({
  columns,
  rows,
  align,
}: {
  columns: string[];
  rows: React.ReactNode[][];
  align?: ("left" | "right")[];
}) {
  const at = (i: number) => align?.[i] || (i === 0 ? "left" : "right");
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: font.mono, fontSize: 12 }}>
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th
                key={c}
                style={{
                  textAlign: at(i),
                  padding: "6px 10px",
                  borderBottom: `0.5px solid ${color.border}`,
                  color: color.textMuted,
                  fontFamily: font.sans,
                  fontSize: 10,
                  letterSpacing: "0.07em",
                  textTransform: "uppercase",
                  fontWeight: 400,
                  whiteSpace: "nowrap",
                }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri}>
              {r.map((cell, ci) => (
                <td
                  key={ci}
                  style={{
                    textAlign: at(ci),
                    padding: "6px 10px",
                    borderBottom: `0.5px solid ${color.border}`,
                    color: color.textPrimary,
                    whiteSpace: "nowrap",
                  }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
