"use client";

// Curvas de uno o varios modelos superpuestas, con eleccion de eje:
//   $  — capital en escala LOGARITMICA (unica en la que se comparan modelos
//        que componen), con marcas 1-2-5 por decada para que el eje exista
//        aunque la curva no cruce ninguna potencia de 10
//   %  — retorno acumulado sobre el capital inicial, lineal
//   R  — R acumulada del modelo (PnL diario / X vigente), lineal
// `visible` permite encender/apagar modelos sin re-ejecutar nada.
// CompareDrawdown pinta las curvas "bajo el agua" de los mismos modelos.

import React, { useMemo, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { ScalingCompareResult } from "@/lib/api_portfolio_lab";
import { SERIES_PALETTE } from "./PortfolioCurves";

export type ModelYMode = "usd" | "pct" | "r";

const W = 900;
const H = 300;
const PAD = { t: 14, r: 14, b: 28, l: 66 };

const money = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(1)}B`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}mM`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (a >= 1000) return `$${(v / 1000).toFixed(0)}k`;
  return `$${v.toFixed(0)}`;
};

function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/** Marcas para el eje log, legibles en cualquier rango: 1-2-5 por decada y,
 *  si el rango es corto y salen pocas, se densifica con mas mantisas — un
 *  tramo de 10k a 40k merece mas de dos cifras en el eje. */
function log125Ticks(lo: number, hi: number): number[] {
  const build = (mantissas: number[]) => {
    const out: number[] = [];
    for (let e = Math.floor(Math.log10(lo)) - 1; e <= Math.ceil(Math.log10(hi)); e++) {
      for (const m of mantissas) {
        const v = m * Math.pow(10, e);
        if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v);
      }
    }
    return out;
  };
  let out = build([1, 2, 5]);
  if (out.length < 5) out = build([1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9]);
  // Si salen demasiadas (rango de muchas decadas), quedarse con ~8.
  if (out.length > 9) {
    const step = Math.ceil(out.length / 8);
    out = out.filter((_, i) => i % step === 0);
  }
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

function seriesFor(r: ScalingCompareResult, yMode: ModelYMode, initCash: number): number[] {
  if (yMode === "usd") return r.equity || [];
  if (yMode === "pct") return (r.equity || []).map((e) => (e / initCash - 1) * 100);
  return cumsum(r.daily_r_net || []);
}

function Legend({
  results,
  visible,
  onToggle,
}: {
  results: ScalingCompareResult[];
  visible?: boolean[];
  onToggle?: (i: number) => void;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", padding: "8px 4px 0", fontSize: 10.5, fontFamily: font.sans }}>
      {results.map((r, i) => {
        const on = visible ? visible[i] : true;
        const body = (
          <>
            <span style={{ width: 16, height: 0, borderTop: `2px solid ${SERIES_PALETTE[i % SERIES_PALETTE.length]}`, opacity: on ? 1 : 0.25 }} />
            <span style={{ color: on ? color.textSecondary : color.textMuted, textDecoration: on ? "none" : "line-through" }}>{r.label}</span>
          </>
        );
        return onToggle ? (
          <button
            key={r.label}
            type="button"
            onClick={() => onToggle(i)}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
          >
            {body}
          </button>
        ) : (
          <span key={r.label} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>{body}</span>
        );
      })}
      {onToggle && (
        <span style={{ color: color.textMuted, fontSize: 9.5 }}>· pulsa un modelo para ocultarlo</span>
      )}
    </div>
  );
}

export function CompareCurves({
  results,
  initCash,
  yMode = "usd",
  visible,
  onToggle,
}: {
  results: ScalingCompareResult[];
  initCash: number;
  yMode?: ModelYMode;
  visible?: boolean[];
  onToggle?: (i: number) => void;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const shown = results
    .map((r, i) => ({ r, i }))
    .filter(({ r, i }) => !r.error && r.equity && r.equity.length > 1 && (visible ? visible[i] : true));

  const geom = useMemo(() => {
    if (!shown.length) return null;
    const cal = shown[0].r.calendar || [];
    const n = Math.max(...shown.map(({ r }) => r.equity!.length), 2);
    const xOf = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);

    if (yMode === "usd") {
      const floor = Math.max(1, initCash * 0.002);
      const pool = shown.flatMap(({ r }) => r.equity!).concat([initCash]);
      const loV = Math.max(floor, Math.min(...pool));
      const hiV = Math.max(...pool) * 1.05;
      const lo = Math.log10(loV);
      const span = Math.log10(hiV) - lo || 1;
      const yOf = (v: number) => PAD.t + (1 - (Math.log10(Math.max(v, floor)) - lo) / span) * (H - PAD.t - PAD.b);
      return { xOf, yOf, ticks: log125Ticks(loV, hiV), cal, n, fmtY: money, zero: initCash };
    }

    const series = shown.map(({ r }) => seriesFor(r, yMode, initCash));
    const pool = series.flat().concat([0]);
    let lo = Math.min(...pool);
    let hi = Math.max(...pool);
    if (!(hi > lo)) hi = lo + 1;
    const m = (hi - lo) * 0.05;
    lo -= m;
    hi += m;
    const yOf = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
    const fmtY = (v: number) => (yMode === "pct" ? `${v.toFixed(0)}%` : `${v.toFixed(0)}R`);
    return { xOf, yOf, ticks: niceTicks(lo, hi), cal, n, fmtY, zero: 0 };
  }, [shown, initCash, yMode]);

  if (!geom) {
    return (
      <div style={{ fontSize: 11.5, color: color.textMuted, fontFamily: font.sans, padding: "10px 2px" }}>
        No hay ningún modelo visible — enciende alguno en la leyenda.
      </div>
    );
  }

  const line = (a: number[]) => a.map((v, i) => `${i === 0 ? "M" : "L"}${geom.xOf(i).toFixed(1)},${geom.yOf(v).toFixed(1)}`).join("");
  // count >= 2 SIEMPRE: con un solo dia, k/(count-1) daba 0/0 = NaN en el SVG.
  const count = Math.max(2, Math.min(6, geom.cal.length));
  const xTicks = geom.cal.length > 1
    ? Array.from({ length: count }, (_, k) => Math.round((k / (count - 1)) * (geom.cal.length - 1)))
    : [];

  const fmtHover = (v: number) =>
    yMode === "usd"
      ? `$${v.toLocaleString("es-ES", { maximumFractionDigits: 0 })}`
      : yMode === "pct"
        ? `${v.toFixed(2)}%`
        : `${v.toFixed(2)}R`;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((fx - PAD.l) / (W - PAD.l - PAD.r)) * (geom.n - 1));
    setHoverIdx(i >= 0 && i < geom.cal.length ? i : null);
  };

  return (
    <div>
      <div style={{ position: "relative", background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: "10px 12px 6px" }}>
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
                {geom.fmtY(t)}
              </text>
            </g>
          ))}
          <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(geom.zero)} y2={geom.yOf(geom.zero)} stroke="var(--color-ec-text-muted)" strokeWidth="0.75" strokeDasharray="3 3" />
          {shown.map(({ r, i }) => (
            <path key={r.label} d={line(seriesFor(r, yMode, initCash))} fill="none" stroke={SERIES_PALETTE[i % SERIES_PALETTE.length]} strokeWidth="1.4" />
          ))}
          {xTicks.map((i) => (
            <text key={i} x={geom.xOf(i)} y={H - PAD.b + 14} textAnchor={i === 0 ? "start" : i === geom.cal.length - 1 ? "end" : "middle"} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
              {geom.cal[i]}
            </text>
          ))}
          {hoverIdx != null && (
            <line x1={geom.xOf(hoverIdx)} x2={geom.xOf(hoverIdx)} y1={PAD.t} y2={H - PAD.b} stroke="var(--color-ec-text-secondary)" strokeWidth="0.6" strokeDasharray="2 2" />
          )}
          <text x={12} y={PAD.t + 2} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-sans)" transform={`rotate(-90 12 ${PAD.t + 2})`} textAnchor="end">
            {yMode === "usd" ? "capital (escala log)" : yMode === "pct" ? "retorno acumulado (%)" : "R acumulada del modelo"}
          </text>
        </svg>
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
            <div style={{ color: color.textMuted, fontFamily: font.sans, marginBottom: 3 }}>{geom.cal[hoverIdx]}</div>
            {shown.map(({ r, i }) => {
              const v = seriesFor(r, yMode, initCash)[hoverIdx];
              return (
                <div key={r.label} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <span style={{ color: SERIES_PALETTE[i % SERIES_PALETTE.length], overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 150 }}>
                    {r.label}
                  </span>
                  <span>{v != null && Number.isFinite(v) ? fmtHover(v) : "—"}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <Legend results={results} visible={visible} onToggle={onToggle} />
    </div>
  );
}

/** Curvas "bajo el agua" de los mismos modelos: % de caida desde el maximo. */
export function CompareDrawdown({
  results,
  visible,
  onToggle,
}: {
  results: ScalingCompareResult[];
  visible?: boolean[];
  onToggle?: (i: number) => void;
}) {
  const HH = 220;
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const shown = results
    .map((r, i) => ({ r, i }))
    .filter(({ r, i }) => !r.error && r.equity && r.equity.length > 1 && (visible ? visible[i] : true));

  const geom = useMemo(() => {
    if (!shown.length) return null;
    const cal = shown[0].r.calendar || [];
    const dds = shown.map(({ r }) => {
      let peak = Math.max(r.equity![0], 1e-9);
      return r.equity!.map((v) => {
        if (v > peak) peak = v;
        return peak > 0 ? (v / peak - 1) * 100 : 0;
      });
    });
    const minDd = Math.min(-1, ...dds.flat());
    const n = Math.max(...dds.map((d) => d.length), 2);
    const xOf = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const yOf = (v: number) => PAD.t + (v / minDd) * (HH - PAD.t - PAD.b);
    return { dds, xOf, yOf, ticks: niceTicks(minDd, 0, 4), cal };
  }, [shown]);

  if (!geom) return null;

  const line = (a: number[]) => a.map((v, i) => `${i === 0 ? "M" : "L"}${geom.xOf(i).toFixed(1)},${geom.yOf(v).toFixed(1)}`).join("");
  // count >= 2 SIEMPRE: con un solo dia, k/(count-1) daba 0/0 = NaN en el SVG.
  const count = Math.max(2, Math.min(6, geom.cal.length));
  const xTicks = geom.cal.length > 1
    ? Array.from({ length: count }, (_, k) => Math.round((k / (count - 1)) * (geom.cal.length - 1)))
    : [];

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = ((e.clientX - rect.left) / rect.width) * W;
    const n = Math.max(...geom.dds.map((d) => d.length), 2);
    const i = Math.round(((fx - PAD.l) / (W - PAD.l - PAD.r)) * (n - 1));
    setHoverIdx(i >= 0 && i < geom.cal.length ? i : null);
  };

  return (
    <div>
      <div style={{ position: "relative", background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: "10px 12px 6px" }}>
        <svg
          viewBox={`0 0 ${W} ${HH}`}
          style={{ width: "100%", height: "auto", display: "block" }}
          onMouseMove={onMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {geom.ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(t)} y2={geom.yOf(t)} stroke="var(--color-ec-border)" strokeWidth="0.5" />
              <text x={PAD.l - 7} y={geom.yOf(t) + 3} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
                {t.toFixed(0)}%
              </text>
            </g>
          ))}
          {shown.map(({ r, i }, k) => (
            <path key={r.label} d={line(geom.dds[k])} fill="none" stroke={SERIES_PALETTE[i % SERIES_PALETTE.length]} strokeWidth="1.2" />
          ))}
          {xTicks.map((i) => (
            <text key={i} x={geom.xOf(i)} y={HH - PAD.b + 14} textAnchor={i === 0 ? "start" : i === geom.cal.length - 1 ? "end" : "middle"} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
              {geom.cal[i]}
            </text>
          ))}
          {hoverIdx != null && (
            <line x1={geom.xOf(hoverIdx)} x2={geom.xOf(hoverIdx)} y1={PAD.t} y2={HH - PAD.b} stroke="var(--color-ec-text-secondary)" strokeWidth="0.6" strokeDasharray="2 2" />
          )}
          <text x={12} y={PAD.t + 2} fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-sans)" transform={`rotate(-90 12 ${PAD.t + 2})`} textAnchor="end">
            drawdown (%)
          </text>
        </svg>
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
              minWidth: 140,
            }}
          >
            <div style={{ color: color.textMuted, fontFamily: font.sans, marginBottom: 3 }}>{geom.cal[hoverIdx]}</div>
            {shown.map(({ r, i }, k) => (
              <div key={r.label} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <span style={{ color: SERIES_PALETTE[i % SERIES_PALETTE.length], overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 150 }}>
                  {r.label}
                </span>
                <span>{geom.dds[k][hoverIdx] != null ? `${geom.dds[k][hoverIdx].toFixed(2)}%` : "—"}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <Legend results={results} visible={visible} onToggle={onToggle} />
    </div>
  );
}
