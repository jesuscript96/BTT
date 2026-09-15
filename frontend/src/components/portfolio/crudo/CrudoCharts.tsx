"use client";

// Graficos de la vista En crudo, en SVG a mano como el resto de Robustez y
// Portfolio: viewBox fijo, tokens del sistema, marco alrededor del area de
// dibujo, rejilla en los dos ejes, marcas de ano, etiqueta del valor final
// en el borde derecho de cada serie y cursor con lectura de todas a la vez.
// Ningun dato se interpola: todas las series comparten el mismo calendario
// (el de la suma) y un dia sin operar arrastra el valor anterior (§4.13).

import React, { useMemo, useState } from "react";
import { color, font, hairline } from "@/components/ui/tokens";
import { n, usdCorto } from "./hoja";

export interface Serie {
  name: string;
  values: number[];
  color: string;
  /** Grosor de linea; la suma va mas gruesa. */
  width?: number;
}

export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!(hi > lo)) return [lo];
  const span = hi - lo;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/** Indices donde cambia el ano (para las lineas verticales) y unas seis
 *  marcas de fecha repartidas (§4.10: ni una ni cincuenta). */
function xMarks(labels: string[]) {
  const years: number[] = [];
  for (let i = 1; i < labels.length; i++) if (labels[i].slice(0, 4) !== labels[i - 1].slice(0, 4)) years.push(i);
  const len = labels.length;
  const c = Math.min(6, len);
  const ticks = len < 2 ? (len ? [0] : []) : Array.from({ length: c }, (_, k) => Math.round((k / (c - 1)) * (len - 1)));
  return { years, ticks };
}

function rango(series: Serie[], conCero: boolean) {
  const pool: number[] = conCero ? [0] : [];
  for (const s of series) for (const v of s.values) if (Number.isFinite(v)) pool.push(v);
  const lo = pool.length ? Math.min(...pool) : 0;
  let hi = pool.length ? Math.max(...pool) : 1;
  if (!(hi > lo)) hi = lo + 1;
  const m = (hi - lo) * 0.06;
  return { lo: lo - m, hi: hi + m };
}

const W = 1000;
const MONO = "var(--color-ec-mono)";
const PAD_PNL = { t: 12, r: 74, b: 30, l: 62 };
const PAD_EXP = { t: 14, r: 18, b: 30, l: 56 };

/**
 * Panel tecnico: PnL acumulado arriba y drawdown debajo, con el mismo eje de
 * tiempo. Cada serie lleva su drawdown (sobre su propia curva) en su color;
 * la suma, en cobre. Cursor comun a los dos paneles.
 */
export function PnlDdChart({
  labels,
  pnl,
  dd,
  yFormat,
  hoverFormat,
  height = 420,
}: {
  labels: string[];
  pnl: Serie[];
  dd: Serie[];
  yFormat: (v: number) => string;
  hoverFormat: (v: number) => string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const H = height;
  const PAD = PAD_PNL;
  const GAP = 26;                       // hueco entre paneles (con el eje x del de arriba)
  const hTop = Math.round((H - PAD.t - PAD.b - GAP) * 0.68);
  const hBot = H - PAD.t - PAD.b - GAP - hTop;
  const yTop0 = PAD.t;
  const yBot0 = PAD.t + hTop + GAP;

  const geom = useMemo(() => {
    const len = Math.max(labels.length, 2);
    const xOf = (i: number) => PAD_PNL.l + (i / (len - 1)) * (W - PAD_PNL.l - PAD_PNL.r);
    const rt = rango(pnl, true);
    const rb = { lo: Math.min(-1, ...dd.flatMap((s) => s.values.filter(Number.isFinite))) * 1.06, hi: 0 };
    const yTop = (v: number) => yTop0 + (1 - (v - rt.lo) / (rt.hi - rt.lo)) * hTop;
    const yBot = (v: number) => yBot0 + (1 - (v - rb.lo) / (rb.hi - rb.lo)) * hBot;
    const path = (a: number[], y: (v: number) => number) => {
      let d = "";
      for (let i = 0; i < a.length; i++) {
        const v = a[i];
        if (!Number.isFinite(v)) continue;
        d += `${d ? "L" : "M"}${xOf(i).toFixed(1)},${y(v).toFixed(1)}`;
      }
      return d;
    };
    const area = (a: number[], y: (v: number) => number, base: number) => {
      const p = path(a, y);
      if (!p) return "";
      let last = a.length - 1;
      while (last > 0 && !Number.isFinite(a[last])) last--;
      let first = 0;
      while (first < a.length && !Number.isFinite(a[first])) first++;
      return `${p}L${xOf(last).toFixed(1)},${y(base).toFixed(1)}L${xOf(first).toFixed(1)},${y(base).toFixed(1)}Z`;
    };
    return { xOf, yTop, yBot, path, area, tTicks: niceTicks(rt.lo, rt.hi, 5), bTicks: niceTicks(rb.lo, 0, 3), ...xMarks(labels) };
  }, [labels, pnl, dd, hTop, hBot, yTop0, yBot0]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((fx - PAD.l) / (W - PAD.l - PAD.r)) * (labels.length - 1));
    setHover(i >= 0 && i < labels.length ? i : null);
  };

  // Etiquetas de valor final en el borde derecho, sin que se pisen.
  const endLabels = useMemo(() => {
    const items = pnl
      .map((s) => ({ s, v: s.values[s.values.length - 1] }))
      .filter((x) => Number.isFinite(x.v))
      .map((x) => ({ ...x, y: geom.yTop(x.v) }))
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < 11) items[i].y = items[i - 1].y + 11;
    return items;
  }, [pnl, geom]);

  const frame = (y0: number, h: number) => (
    <rect x={PAD.l} y={y0} width={W - PAD.l - PAD.r} height={h} fill="none" stroke={color.border} strokeWidth={1} />
  );

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block", background: color.bgBase }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {/* ── Panel de arriba: PnL acumulado ── */}
        {geom.tTicks.map((t) => (
          <g key={`t${t}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={geom.yTop(t)} y2={geom.yTop(t)} stroke={color.border} strokeWidth={Math.abs(t) < 1e-9 ? 1 : 0.5} strokeDasharray={Math.abs(t) < 1e-9 ? undefined : "2 4"} />
            <text x={PAD.l - 7} y={geom.yTop(t) + 3.5} textAnchor="end" fontSize={9.5} fontFamily={MONO} fill={color.textMuted}>{yFormat(t)}</text>
          </g>
        ))}
        {geom.years.map((i) => (
          <line key={`y${i}`} x1={geom.xOf(i)} x2={geom.xOf(i)} y1={yTop0} y2={yBot0 + hBot} stroke={color.border} strokeWidth={0.8} strokeDasharray="1 3" />
        ))}
        {pnl.map((s) => (
          <path key={s.name} d={geom.path(s.values, geom.yTop)} fill="none" stroke={s.color} strokeWidth={s.width ?? 1} strokeLinejoin="round" />
        ))}
        {endLabels.map(({ s, v, y }) => (
          <text key={s.name} x={W - PAD.r + 5} y={y + 3.5} fontSize={9.5} fontFamily={MONO} fill={s.color}>{yFormat(v)}</text>
        ))}
        {frame(yTop0, hTop)}
        <text x={PAD.l + 6} y={yTop0 + 12} fontSize={9} fontFamily="var(--color-ec-sans)" fill={color.textMuted} letterSpacing="0.8">PNL ACUMULADO</text>

        {/* Eje x entre paneles */}
        {geom.ticks.map((i) => (
          <text key={`x${i}`} x={geom.xOf(i)} y={yTop0 + hTop + 15} textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"} fontSize={9.5} fontFamily={MONO} fill={color.textMuted}>{labels[i]}</text>
        ))}

        {/* ── Panel de abajo: drawdown ── */}
        {geom.bTicks.map((t) => (
          <g key={`b${t}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={geom.yBot(t)} y2={geom.yBot(t)} stroke={color.border} strokeWidth={0.5} strokeDasharray="2 4" />
            <text x={PAD.l - 7} y={geom.yBot(t) + 3.5} textAnchor="end" fontSize={9.5} fontFamily={MONO} fill={color.textMuted}>{n(t, 0)} %</text>
          </g>
        ))}
        {dd.map((s) => (
          <g key={s.name}>
            {s.width && s.width > 1.5 && <path d={geom.area(s.values, geom.yBot, 0)} fill={s.color} opacity={0.12} />}
            <path d={geom.path(s.values, geom.yBot)} fill="none" stroke={s.color} strokeWidth={s.width ?? 0.9} strokeLinejoin="round" />
          </g>
        ))}
        {frame(yBot0, hBot)}
        <text x={PAD.l + 6} y={yBot0 + 12} fontSize={9} fontFamily="var(--color-ec-sans)" fill={color.textMuted} letterSpacing="0.8">DRAWDOWN</text>
        {geom.ticks.map((i) => (
          <text key={`xb${i}`} x={geom.xOf(i)} y={yBot0 + hBot + 15} textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"} fontSize={9.5} fontFamily={MONO} fill={color.textMuted}>{labels[i].slice(0, 7)}</text>
        ))}

        {/* Cursor en los dos paneles */}
        {hover != null && (
          <g>
            <line x1={geom.xOf(hover)} x2={geom.xOf(hover)} y1={yTop0} y2={yBot0 + hBot} stroke={color.textSecondary} strokeWidth={0.7} strokeDasharray="3 3" />
            {pnl.map((s) => Number.isFinite(s.values[hover]) && <circle key={s.name} cx={geom.xOf(hover)} cy={geom.yTop(s.values[hover])} r={2.4} fill={s.color} stroke={color.bgBase} />)}
            {dd.map((s) => Number.isFinite(s.values[hover]) && <circle key={s.name} cx={geom.xOf(hover)} cy={geom.yBot(s.values[hover])} r={2.2} fill={s.color} stroke={color.bgBase} />)}
          </g>
        )}
      </svg>

      {/* Lectura: valor final o el del cursor, PnL y drawdown de cada serie. */}
      <div style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: "2px 12px", padding: "6px 4px 2px", borderTop: hairline, alignItems: "baseline" }}>
        <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.textMuted }}>{hover != null ? labels[hover] : "final"}</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "3px 16px" }}>
          {pnl.map((s, k) => {
            const v = hover != null ? s.values[hover] : s.values[s.values.length - 1];
            const d = dd[k] ? (hover != null ? dd[k].values[hover] : dd[k].values[dd[k].values.length - 1]) : NaN;
            return (
              <span key={s.name} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10.5, fontFamily: font.sans, color: color.textSecondary }}>
                <span style={{ width: 12, height: 0, borderTop: `${s.width && s.width > 1.5 ? 2.5 : 1.5}px solid ${s.color}` }} />
                <span style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                <span style={{ fontFamily: font.mono, color: Number.isFinite(v) ? (v >= 0 ? color.textHigh : color.loss) : color.textMuted }}>{Number.isFinite(v) ? hoverFormat(v) : "—"}</span>
                {Number.isFinite(d) && <span style={{ fontFamily: font.mono, color: color.loss, fontSize: 10 }}>{n(d, 1)} %</span>}
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * Cuanto del capital DEL DIA estaba metido en posiciones a la vez (%): el
 * mayor nocional abierto simultaneamente en el dia, partido por el capital
 * con el que empezo ese dia la suma. La linea del 100 % es el capital entero.
 */
export function ExposureChart({
  labels,
  pct,
  usd,
  maxOpen,
  height = 200,
}: {
  labels: string[];
  pct: number[];
  usd: number[];
  maxOpen: number[];
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const H = height;
  const PAD = PAD_EXP;
  const geom = useMemo(() => {
    const hi = Math.max(10, ...pct.filter(Number.isFinite)) * 1.08;
    const len = Math.max(labels.length, 2);
    const xOf = (i: number) => PAD_EXP.l + (i / (len - 1)) * (W - PAD_EXP.l - PAD_EXP.r);
    const yOf = (v: number) => PAD_EXP.t + (1 - v / hi) * (H - PAD_EXP.t - PAD_EXP.b);
    let line = "";
    for (let i = 0; i < pct.length; i++) line += `${line ? "L" : "M"}${xOf(i).toFixed(1)},${yOf(pct[i]).toFixed(1)}`;
    const area = line ? `${line}L${xOf(pct.length - 1).toFixed(1)},${H - PAD_EXP.b}L${xOf(0).toFixed(1)},${H - PAD_EXP.b}Z` : "";
    const marks = xMarks(labels);
    return { hi, xOf, yOf, area, line, ticks: niceTicks(0, hi, 4), years: marks.years, xt: marks.ticks };
  }, [labels, pct, H]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((fx - PAD.l) / (W - PAD.l - PAD.r)) * (labels.length - 1));
    setHover(i >= 0 && i < labels.length ? i : null);
  };
  const iMax = pct.reduce((b, v, i) => (v > pct[b] ? i : b), 0);
  const k = hover ?? iMax;

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block", background: color.bgBase }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {geom.ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(t)} y2={geom.yOf(t)} stroke={color.border} strokeWidth={0.5} strokeDasharray="2 4" />
            <text x={PAD.l - 7} y={geom.yOf(t) + 3.5} textAnchor="end" fontSize={9.5} fontFamily={MONO} fill={color.textMuted}>{n(t, 0)} %</text>
          </g>
        ))}
        {geom.years.map((i) => (
          <line key={i} x1={geom.xOf(i)} x2={geom.xOf(i)} y1={PAD.t} y2={H - PAD.b} stroke={color.border} strokeWidth={0.8} strokeDasharray="1 3" />
        ))}
        <path d={geom.area} fill={color.info} opacity={0.15} />
        <path d={geom.line} fill="none" stroke={color.info} strokeWidth={1} />
        {geom.hi > 100 && (
          <g>
            <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(100)} y2={geom.yOf(100)} stroke={color.warning} strokeWidth={1} strokeDasharray="6 4" />
            <text x={W - PAD.r - 4} y={geom.yOf(100) - 4} textAnchor="end" fontSize={9.5} fontFamily="var(--color-ec-sans)" fill={color.warning}>100 % = todo el capital del día</text>
          </g>
        )}
        <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={H - PAD.t - PAD.b} fill="none" stroke={color.border} strokeWidth={1} />
        {geom.xt.map((i) => (
          <text key={`x${i}`} x={geom.xOf(i)} y={H - PAD.b + 15} textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"} fontSize={9.5} fontFamily={MONO} fill={color.textMuted}>{labels[i]}</text>
        ))}
        {hover != null && (
          <g>
            <line x1={geom.xOf(hover)} x2={geom.xOf(hover)} y1={PAD.t} y2={H - PAD.b} stroke={color.textSecondary} strokeWidth={0.7} strokeDasharray="3 3" />
            <circle cx={geom.xOf(hover)} cy={geom.yOf(pct[hover])} r={2.6} fill={color.info} stroke={color.bgBase} />
          </g>
        )}
      </svg>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 18px", padding: "6px 4px 2px", borderTop: hairline, fontSize: 10.5, fontFamily: font.sans, color: color.textSecondary }}>
        <span style={{ fontFamily: font.mono, color: color.textMuted, minWidth: 90 }}>{hover != null ? labels[hover] : `máximo · ${labels[iMax] || ""}`}</span>
        <span>del capital del día <span style={{ fontFamily: font.mono, color: pct[k] > 100 ? color.warning : color.textHigh }}>{n(pct[k], 0)} %</span></span>
        <span>en posiciones <span style={{ fontFamily: font.mono, color: color.textHigh }}>{usdCorto(usd[k] || 0)} $</span></span>
        <span>a la vez <span style={{ fontFamily: font.mono, color: color.textHigh }}>{maxOpen[k] || 0}</span> posiciones</span>
      </div>
    </div>
  );
}
