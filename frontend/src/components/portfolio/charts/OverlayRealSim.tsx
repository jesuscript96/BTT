"use client";

// Tu curva REAL contra el portfolio SIMULADO en el mismo tramo: dos lienzos
// (equity y drawdown) con las dos lineas superpuestas, para ver divergencias
// de rendimiento Y de sufrimiento. El simulado se alinea al calendario union;
// los dias en que una serie no tiene dato arrastran su ultimo valor.

import React, { useMemo } from "react";
import { color, font, radius } from "@/components/ui/tokens";

const W = 900;

function niceTicks(lo: number, hi: number, n = 4): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

function ddOf(series: number[]): number[] {
  let peak = series[0] || 1e-9;
  return series.map((v) => {
    if (v > peak) peak = v;
    return peak > 0 ? (v / peak - 1) * 100 : 0;
  });
}

function Panel({
  days,
  a,
  b,
  fmtY,
  yLabel,
  h,
  colorA = "var(--color-ec-copper)",
  colorB = "var(--color-ec-info)",
}: {
  days: string[];
  a: number[];
  b: number[];
  fmtY: (v: number) => string;
  yLabel: string;
  h: number;
  colorA?: string;
  colorB?: string;
}) {
  const PAD = { t: 12, r: 12, b: 26, l: 64 };
  const pool = [...a, ...b];
  let lo = Math.min(...pool);
  let hi = Math.max(...pool);
  if (!(hi > lo)) hi = lo + 1;
  const m = (hi - lo) * 0.06;
  lo -= m;
  hi += m;
  const xOf = (i: number) => PAD.l + (i / (days.length - 1)) * (W - PAD.l - PAD.r);
  const yOf = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (h - PAD.t - PAD.b);
  const line = (s: number[]) => s.map((v, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join("");
  const count = Math.min(6, days.length);
  const xTicks = Array.from({ length: count }, (_, k) => Math.round((k / (count - 1)) * (days.length - 1)));
  return (
    <div style={{ background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: "10px 12px 6px" }}>
      <svg viewBox={`0 0 ${W} ${h}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {niceTicks(lo, hi).map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yOf(t)} y2={yOf(t)} stroke="var(--color-ec-border)" strokeWidth="0.5" />
            <text x={PAD.l - 7} y={yOf(t) + 3} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
              {fmtY(t)}
            </text>
          </g>
        ))}
        <path d={line(b)} fill="none" stroke={colorB} strokeWidth="1.3" strokeDasharray="4 3" opacity="0.85" />
        <path d={line(a)} fill="none" stroke={colorA} strokeWidth="1.8" />
        {xTicks.map((i) => (
          <text key={i} x={xOf(i)} y={h - PAD.b + 14} textAnchor={i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
            {days[i]}
          </text>
        ))}
        <text x={12} y={PAD.t + 2} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-sans)" transform={`rotate(-90 12 ${PAD.t + 2})`} textAnchor="end">
          {yLabel}
        </text>
      </svg>
    </div>
  );
}

export function OverlayRealSim({
  realDates,
  realEquity,
  simDates,
  simEquity,
}: {
  realDates: string[];
  realEquity: number[];
  simDates: string[];
  simEquity: number[];
}) {
  const data = useMemo(() => {
    if (realDates.length < 2 || simDates.length < 2) return null;
    const days = Array.from(new Set([...realDates, ...simDates])).sort();
    const align = (dates: string[], vals: number[], start: number) => {
      const map = new Map(dates.map((d, i) => [d, vals[i]]));
      let last = start;
      return days.map((d) => {
        if (map.has(d)) last = map.get(d)!;
        return last;
      });
    };
    const a = align(realDates, realEquity, realEquity[0]);
    const b = align(simDates, simEquity, simEquity[0]);
    return { days, a, b, ddA: ddOf(a), ddB: ddOf(b) };
  }, [realDates, realEquity, simDates, simEquity]);

  if (!data) return null;

  const money = (v: number) => `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <Panel days={data.days} a={data.a} b={data.b} fmtY={money} yLabel="equity ($)" h={240} />
      {/* El drawdown va en ROJO (peticion expresa): continuo = real, punteado = simulado. */}
      <Panel
        days={data.days}
        a={data.ddA}
        b={data.ddB}
        fmtY={(v) => `${v.toFixed(0)}%`}
        yLabel="drawdown (%)"
        h={170}
        colorA="var(--color-ec-loss)"
        colorB="var(--color-ec-loss)"
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 18px", padding: "0 4px", fontSize: 10.5, fontFamily: font.sans }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
          <span style={{ width: 16, height: 0, borderTop: `2px solid ${color.copper}` }} />
          Tu equity real
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
          <span style={{ width: 16, height: 0, borderTop: `1.5px dashed ${color.info}` }} />
          Equity simulada (mismo tramo y capital)
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
          <span style={{ width: 16, height: 0, borderTop: `2px solid ${color.loss}` }} />
          DD real
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: color.textSecondary }}>
          <span style={{ width: 16, height: 0, borderTop: `1.5px dashed ${color.loss}` }} />
          DD simulado
        </span>
      </div>
    </div>
  );
}
