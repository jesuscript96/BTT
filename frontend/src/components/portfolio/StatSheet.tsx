"use client";

// Rejilla de metricas COMPACTA, estilo celdas de hoja de calculo: filas finas
// etiqueta|valor con separadores hairline, agrupadas en columnas. Sustituye a
// las tarjetas grandes (MetricTile) alli donde hay muchas cifras y poco sitio
// — peticion expresa del usuario: mas dato por caja, menos caja.

import React from "react";
import { color, font, radius } from "@/components/ui/tokens";
import { Help } from "@/components/robustez/help";

export interface StatRow {
  label: string;
  value: string;
  /** Dato secundario pegado al valor, en gris ("$68.167", "107 de 499"). */
  sub?: string;
  tone?: string;
  help?: React.ReactNode;
}

export function StatSheet({ groups }: { groups: Array<{ title: string; rows: StatRow[] }> }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(240px, 1fr))`,
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        overflow: "hidden",
      }}
    >
      {groups.map((g, gi) => (
        <div key={g.title} style={{ borderLeft: gi === 0 ? "none" : `0.5px solid ${color.border}`, minWidth: 0 }}>
          <div
            style={{
              padding: "5px 12px",
              fontSize: 9,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: color.copper,
              fontFamily: font.sans,
              borderBottom: `0.5px solid ${color.border}`,
              background: color.bgSurface,
            }}
          >
            {g.title}
          </div>
          {g.rows.map((r, ri) => (
            <div
              key={r.label}
              style={{
                display: "flex",
                alignItems: "baseline",
                justifyContent: "space-between",
                gap: 10,
                padding: "3.5px 12px",
                borderBottom: ri === g.rows.length - 1 ? "none" : `0.5px solid ${color.border}`,
                minHeight: 22,
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  fontSize: 10,
                  fontFamily: font.sans,
                  color: color.textMuted,
                  whiteSpace: "nowrap",
                }}
              >
                {r.label}
                {r.help && <Help title={r.label}>{r.help}</Help>}
              </span>
              <span style={{ display: "inline-flex", alignItems: "baseline", gap: 7, minWidth: 0 }}>
                {r.sub && (
                  <span style={{ fontSize: 9.5, fontFamily: font.mono, color: color.textMuted, whiteSpace: "nowrap" }}>
                    {r.sub}
                  </span>
                )}
                <span style={{ fontSize: 12, fontFamily: font.mono, color: r.tone || color.textHigh, whiteSpace: "nowrap" }}>
                  {r.value}
                </span>
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Linea de cifras directamente sobre el fondo, sin recuadro. Para datos que
 *  deben estar pero no competir (VaR/CVaR, tiempos, recuentos). */
export function InlineStats({
  items,
  center,
}: {
  items: Array<{ label: string; value: string; tone?: string; help?: React.ReactNode }>;
  center?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 22px", padding: "2px 2px 0", justifyContent: center ? "center" : "flex-start" }}>
      {items.map((it) => (
        <span key={it.label} style={{ display: "inline-flex", alignItems: "baseline", gap: 7 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: 9.5,
              letterSpacing: "0.07em",
              textTransform: "uppercase",
              color: color.textMuted,
              fontFamily: font.sans,
            }}
          >
            {it.label}
            {it.help && <Help title={it.label}>{it.help}</Help>}
          </span>
          <span style={{ fontSize: 12, fontFamily: font.mono, color: it.tone || color.textPrimary }}>{it.value}</span>
        </span>
      ))}
    </div>
  );
}
