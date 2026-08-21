"use client";

// Matriz de correlacion entre estrategias, sobre su R diaria normalizada.
//
// Convencion de color pensada para carteras: correlacion ALTA = malo (rojo,
// no diversifica), correlacion baja o negativa = bueno (verde). La celda
// ademas escribe el numero — el color orienta, la cifra decide.
//
// La correlacion se calcula solo sobre el tramo en que AMBAS estrategias
// existian; si ese solape es corto (<60 sesiones) la celda lleva asterisco.

import React from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { CombineCorrelation } from "@/lib/api_portfolio_lab";

const CELL = 64;
const LABEL_W = 130;
const LABEL_H = 30;

export function CorrelationMatrix({
  corr,
  names,
}: {
  corr: CombineCorrelation;
  names: string[];
}) {
  const n = names.length;
  const W = LABEL_W + n * CELL + 8;
  const H = LABEL_H + n * CELL + 8;

  const cellFill = (v: number | null) => {
    if (v == null) return "var(--color-ec-bg-elevated)";
    // v=+1 -> rojo pleno; v=-1 -> verde pleno; v=0 -> neutro. Se mezcla el
    // token con transparente para no escribir ningun hex fuera del sistema.
    const a = Math.round(Math.min(1, Math.abs(v)) * 55);
    const base = v >= 0 ? "var(--color-ec-loss)" : "var(--color-ec-profit)";
    return `color-mix(in srgb, ${base} ${a}%, transparent)`;
  };

  const short = (s: string) => (s.length > 16 ? `${s.slice(0, 15)}…` : s);

  return (
    <div
      style={{
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        padding: "10px 12px",
        overflowX: "auto",
      }}
    >
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, height: "auto", display: "block" }}>
        {names.map((nm, j) => (
          <text
            key={`c${j}`}
            x={LABEL_W + j * CELL + CELL / 2}
            y={LABEL_H - 9}
            textAnchor="middle"
            fontSize="9"
            fill="var(--color-ec-text-secondary)"
            fontFamily="var(--color-ec-sans)"
          >
            {short(nm)}
          </text>
        ))}
        {names.map((nm, i) => (
          <text
            key={`r${i}`}
            x={LABEL_W - 8}
            y={LABEL_H + i * CELL + CELL / 2 + 3}
            textAnchor="end"
            fontSize="9.5"
            fill="var(--color-ec-text-secondary)"
            fontFamily="var(--color-ec-sans)"
          >
            {short(nm)}
          </text>
        ))}

        {names.map((_, i) =>
          names.map((__, j) => {
            const v = corr.matrix[i]?.[j] ?? null;
            const overlap = corr.overlap_days[i]?.[j] ?? 0;
            const lowOverlap = i !== j && overlap > 0 && overlap < 60;
            return (
              <g key={`${i}-${j}`}>
                <rect
                  x={LABEL_W + j * CELL + 1.5}
                  y={LABEL_H + i * CELL + 1.5}
                  width={CELL - 3}
                  height={CELL - 3}
                  rx={3}
                  fill={i === j ? "var(--color-ec-bg-elevated)" : cellFill(v)}
                  stroke="var(--color-ec-border)"
                  strokeWidth="0.5"
                />
                <text
                  x={LABEL_W + j * CELL + CELL / 2}
                  y={LABEL_H + i * CELL + CELL / 2 + 3.5}
                  textAnchor="middle"
                  fontSize="11"
                  fill={i === j ? "var(--color-ec-text-muted)" : "var(--color-ec-text-high)"}
                  fontFamily="var(--color-ec-mono)"
                >
                  {i === j ? "—" : v == null ? "s/d" : `${v.toFixed(2)}${lowOverlap ? "*" : ""}`}
                </text>
              </g>
            );
          }),
        )}
      </svg>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 18px", paddingTop: 8, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
        <span>
          <span style={{ color: color.profit }}>verde</span> = descorrelacionada (diversifica) ·{" "}
          <span style={{ color: color.loss }}>rojo</span> = correlacionada (duplica riesgo)
        </span>
        {corr.min_overlap_warning && <span>* solape corto (&lt;60 sesiones comunes): fiabilidad baja</span>}
      </div>
    </div>
  );
}
