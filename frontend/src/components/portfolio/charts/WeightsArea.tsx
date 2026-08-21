"use client";

// Area apilada de los pesos por estrategia a lo largo de los rebalanceos.
// Cada banda es una estrategia (misma paleta que las curvas); la altura total
// es el 100% del presupuesto de riesgo repartido. Los huecos de una banda
// cuentan la historia: cuando un modelo dinamico castiga a una estrategia, su
// banda se estrecha.

import React, { useMemo } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { RebalancePoint } from "@/lib/api_portfolio_lab";
import { SERIES_PALETTE } from "./PortfolioCurves";

const W = 900;
const H = 200;
const PAD = { t: 12, r: 12, b: 26, l: 40 };

export function WeightsArea({
  timeline,
  names,
}: {
  timeline: RebalancePoint[];
  names: string[];
}) {
  const geom = useMemo(() => {
    if (timeline.length < 2) return null;
    const n = names.length;
    const m = timeline.length;
    const xOf = (i: number) => PAD.l + (i / (m - 1)) * (W - PAD.l - PAD.r);
    const yOf = (v: number) => PAD.t + (1 - v) * (H - PAD.t - PAD.b);

    // Bandas apiladas: acumulado de pesos por estrategia en cada rebalanceo.
    const bands: string[] = [];
    const base = new Array(m).fill(0);
    for (let s = 0; s < n; s++) {
      const top = base.map((b, i) => b + (timeline[i].weights[s] || 0));
      let path = "";
      for (let i = 0; i < m; i++) path += `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(top[i]).toFixed(1)}`;
      for (let i = m - 1; i >= 0; i--) path += `L${xOf(i).toFixed(1)},${yOf(base[i]).toFixed(1)}`;
      bands.push(path + "Z");
      for (let i = 0; i < m; i++) base[i] = top[i];
    }

    const count = Math.min(6, m);
    const xTicks = Array.from({ length: count }, (_, k) => Math.round((k / (count - 1)) * (m - 1)));
    return { bands, xOf, yOf, xTicks };
  }, [timeline, names]);

  if (!geom) {
    return (
      <div style={{ fontSize: 11.5, color: color.textMuted, fontFamily: font.sans, padding: "8px 2px" }}>
        Hacen falta al menos dos rebalanceos para dibujar la evolución de los pesos.
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          background: color.bgBase,
          border: `0.5px solid ${color.border}`,
          borderRadius: radius.md,
          padding: "10px 12px 6px",
        }}
      >
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
          {[0, 0.25, 0.5, 0.75, 1].map((v) => (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(v)} y2={geom.yOf(v)} stroke="var(--color-ec-border)" strokeWidth="0.5" />
              <text x={PAD.l - 6} y={geom.yOf(v) + 3} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
                {(v * 100).toFixed(0)}%
              </text>
            </g>
          ))}
          {geom.bands.map((d, s) => (
            <path key={s} d={d} fill={SERIES_PALETTE[s % SERIES_PALETTE.length]} opacity="0.55" stroke={SERIES_PALETTE[s % SERIES_PALETTE.length]} strokeWidth="0.5" />
          ))}
          {geom.xTicks.map((i) => (
            <text key={i} x={geom.xOf(i)} y={H - PAD.b + 14} textAnchor={i === 0 ? "start" : i === timeline.length - 1 ? "end" : "middle"} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
              {timeline[i].date}
            </text>
          ))}
        </svg>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", padding: "8px 4px 0", fontSize: 10.5, fontFamily: font.sans }}>
        {names.map((nm, s) => (
          <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
            <span style={{ width: 10, height: 10, background: SERIES_PALETTE[s % SERIES_PALETTE.length], opacity: 0.7, borderRadius: 2 }} />
            {nm}
          </span>
        ))}
      </div>
    </div>
  );
}
