"use client";

// Grafico principal de la imagen general: una linea por estrategia y la
// combinada destacada en cobre. Todas las series son PnL ACUMULADO desde cero
// (en $, % del capital o R) para que la comparacion entre estrategias y total
// sea directa — el balance absoluto ya esta en las metricas.
//
// SVG a mano, misma convencion que los charts de robustez (W=900, viewBox
// fijo, tokens del design system). Leccion de MEMORIA §4.13 aplicada: TODAS
// las series comparten el mismo eje (el calendario del combinado), un dia sin
// operar arrastra el valor anterior.

import React, { useMemo, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { CombineOut } from "@/lib/api_portfolio_lab";

export type YMode = "usd" | "pct" | "r";
export type XMode = "fecha" | "trades";

const W = 900;
const H = 320;
const PAD = { t: 16, r: 16, b: 36, l: 66 };

/** Paleta para las lineas de estrategia (la combinada siempre va en cobre). */
export const SERIES_PALETTE = [
  color.info,
  color.profit,
  color.warning,
  color.copperBright,
  color.textSecondary,
  color.loss,
];

function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!(hi > lo)) return [lo];
  const span = hi - lo;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

function cumsum(a: number[]): number[] {
  const out = new Array(a.length);
  let acc = 0;
  for (let i = 0; i < a.length; i++) {
    acc += a[i];
    out[i] = acc;
  }
  return out;
}

export function PortfolioCurves({
  out,
  yMode,
  xMode,
}: {
  out: CombineOut;
  yMode: YMode;
  xMode: XMode;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const data = useMemo(() => {
    const init = Number(out.config?.init_cash) || 10000;
    const names = out.per_strategy.map((p) => p.name);

    let labels: string[];
    let combined: number[];
    let per: number[][];

    if (xMode === "fecha") {
      labels = out.calendar;
      const perPnl = out.per_strategy.map((p) => cumsum(p.pnl_daily));
      const perR = out.per_strategy.map((p) => cumsum(p.r_daily));
      if (yMode === "usd") {
        combined = out.equity.map((e) => e - init);
        per = perPnl;
      } else if (yMode === "pct") {
        combined = out.equity.map((e) => (e / init - 1) * 100);
        per = perPnl.map((s) => s.map((v) => (v / init) * 100));
      } else {
        const n = out.calendar.length;
        const total = new Array(n).fill(0);
        for (const s of out.per_strategy) for (let i = 0; i < n; i++) total[i] += s.r_daily[i];
        combined = cumsum(total);
        per = perR;
      }
    } else {
      const seq = out.trades_seq;
      labels = seq.dates;
      const vals = yMode === "r" ? seq.r_net : seq.pnl_net;
      combined = cumsum(vals);
      per = out.per_strategy.map((_, si) => {
        const s = new Array(vals.length);
        let acc = 0;
        for (let i = 0; i < vals.length; i++) {
          if (seq.strategy_idx[i] === si) acc += vals[i];
          s[i] = acc;
        }
        return s;
      });
      if (yMode === "pct") {
        combined = combined.map((v) => (v / init) * 100);
        per = per.map((s) => s.map((v) => (v / init) * 100));
      }
    }
    return { labels, combined, per, names };
  }, [out, yMode, xMode]);

  const geom = useMemo(() => {
    const pool = [...data.combined, ...data.per.flat(), 0];
    let lo = Math.min(...pool);
    let hi = Math.max(...pool);
    if (!(hi > lo)) hi = lo + 1;
    const margin = (hi - lo) * 0.05;
    lo -= margin;
    hi += margin;
    const n = Math.max(data.labels.length, 2);
    const xOf = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const yOf = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
    const line = (a: number[]) =>
      a.map((v, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join("");
    return { lo, hi, n, xOf, yOf, line, ticks: niceTicks(lo, hi) };
  }, [data]);

  const fmtY = (v: number) =>
    yMode === "usd"
      ? `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(Math.abs(v) >= 10000 ? 0 : 1)}k` : v.toFixed(0)}`
      : yMode === "pct"
        ? `${v.toFixed(0)}%`
        : `${v.toFixed(1)}R`;

  const fmtHover = (v: number) =>
    yMode === "usd" ? `$${v.toLocaleString("es-ES", { maximumFractionDigits: 0 })}` : yMode === "pct" ? `${v.toFixed(2)}%` : `${v.toFixed(2)}R`;

  // Seis marcas de fecha en el eje X (leccion de §4.10).
  const xTicks = useMemo(() => {
    const n = data.labels.length;
    if (n < 2) return [];
    const count = Math.min(6, n);
    return Array.from({ length: count }, (_, k) => Math.round((k / (count - 1)) * (n - 1)));
  }, [data.labels]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((fx - PAD.l) / (W - PAD.l - PAD.r)) * (geom.n - 1));
    setHoverIdx(i >= 0 && i < data.labels.length ? i : null);
  };

  return (
    <div>
      <div
        style={{
          position: "relative",
          background: color.bgBase,
          border: `0.5px solid ${color.border}`,
          borderRadius: radius.md,
          padding: "10px 12px 6px",
        }}
      >
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: "100%", height: "auto", display: "block" }}
          onMouseMove={onMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {geom.ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(t)} y2={geom.yOf(t)} stroke="var(--color-ec-border)" strokeWidth="0.5" />
              <text x={PAD.l - 7} y={geom.yOf(t) + 3} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
                {fmtY(t)}
              </text>
            </g>
          ))}

          {/* Linea de cero, para ver de un vistazo cuando el PnL es negativo. */}
          {geom.lo < 0 && geom.hi > 0 && (
            <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(0)} y2={geom.yOf(0)} stroke="var(--color-ec-text-muted)" strokeWidth="0.75" strokeDasharray="3 3" />
          )}

          {xTicks.map((i) => (
            <text key={i} x={geom.xOf(i)} y={H - PAD.b + 14} textAnchor={i === 0 ? "start" : i === data.labels.length - 1 ? "end" : "middle"} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
              {data.labels[i]}
            </text>
          ))}

          {data.per.map((s, si) => (
            <path key={si} d={geom.line(s)} fill="none" stroke={SERIES_PALETTE[si % SERIES_PALETTE.length]} strokeWidth="1" opacity="0.75" />
          ))}
          <path d={geom.line(data.combined)} fill="none" stroke="var(--color-ec-copper)" strokeWidth="1.9" />

          {hoverIdx != null && (
            <line x1={geom.xOf(hoverIdx)} x2={geom.xOf(hoverIdx)} y1={PAD.t} y2={H - PAD.b} stroke="var(--color-ec-text-secondary)" strokeWidth="0.6" strokeDasharray="2 2" />
          )}

          <text x={W - PAD.r} y={H - 6} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-sans)">
            {xMode === "fecha" ? "sesiones →" : "trades →"}
          </text>
          <text x={12} y={PAD.t + 2} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-sans)" transform={`rotate(-90 12 ${PAD.t + 2})`} textAnchor="end">
            {yMode === "usd" ? "PnL acumulado ($)" : yMode === "pct" ? "PnL acumulado (% del capital)" : "R acumulada"}
          </text>
        </svg>

        {/* Lectura del punto bajo el cursor: las dos escalas a la vez tapaban
            el lienzo, asi que va en una esquina fija. */}
        {hoverIdx != null && (
          <div
            style={{
              position: "absolute",
              top: 8,
              right: 10,
              background: color.bgElevated,
              border: `0.5px solid ${color.border}`,
              borderRadius: radius.sm,
              padding: "7px 10px",
              fontSize: 10.5,
              fontFamily: font.mono,
              color: color.textPrimary,
              pointerEvents: "none",
              minWidth: 150,
            }}
          >
            <div style={{ color: color.textMuted, fontFamily: font.sans, marginBottom: 3 }}>{data.labels[hoverIdx]}</div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, color: color.copper }}>
              <span>Portfolio</span>
              <span>{fmtHover(data.combined[hoverIdx])}</span>
            </div>
            {data.per.map((s, si) => (
              <div key={si} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <span style={{ color: SERIES_PALETTE[si % SERIES_PALETTE.length], overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 150 }}>
                  {data.names[si]}
                </span>
                <span>{fmtHover(s[hoverIdx])}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Leyenda DEBAJO del lienzo (leccion de §4.15: dentro la tapan las curvas). */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", padding: "8px 4px 0", fontSize: 10.5, fontFamily: font.sans }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
          <span style={{ width: 16, height: 0, borderTop: `2px solid ${color.copper}` }} />
          Portfolio combinado
        </span>
        {data.names.map((n, si) => (
          <span key={si} style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
            <span style={{ width: 16, height: 0, borderTop: `1.5px solid ${SERIES_PALETTE[si % SERIES_PALETTE.length]}` }} />
            {n}
          </span>
        ))}
      </div>
    </div>
  );
}
