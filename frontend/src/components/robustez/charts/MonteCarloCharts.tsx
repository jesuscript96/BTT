"use client";

import { useMemo } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { McBands, McHistogram } from "@/lib/api_robustez";

const W = 900;
const PAD = { t: 14, r: 14, b: 26, l: 60 };
// Modo «plano» (portfolio «En crudo», 20-sep-2026): sin la caja redondeada,
// con el marco cuadrado del area de dibujo y los margenes de `LinesChart`
// (t 12, b 30, l 62, r 74 para las cifras finales), para que los tres graficos
// del paso 3 tengan los mismos bordes y queden al mismo nivel. La leyenda o el
// pie los pone quien lo usa, con la misma fila que LinesChart.
const PAD_PLANO = { t: 12, r: 74, b: 30, l: 62 };
const PAD_PLANO_DIST = { t: 12, r: 14, b: 30, l: 14 };
type Pad = { t: number; r: number; b: number; l: number };

const money = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1000) return `${(v / 1000).toFixed(a >= 10_000 ? 0 : 1)}k`;
  return v.toFixed(0);
};

function Frame({
  children,
  height,
  caption,
  width = W,
  plano = false,
  pad = PAD,
}: {
  children: React.ReactNode;
  height: number;
  caption?: string;
  /** Ancho del viewBox: con el ancho real de la columna el dibujo sale a tamano real (no escala). */
  width?: number;
  /** Sin caja: solo el svg con el marco cuadrado del area de dibujo (ver PAD_PLANO). */
  plano?: boolean;
  pad?: Pad;
}) {
  if (plano) {
    return (
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block", background: color.bgBase }}>
        {children}
        <rect x={pad.l} y={pad.t} width={width - pad.l - pad.r} height={height - pad.t - pad.b} fill="none" stroke="var(--color-ec-border)" strokeWidth="1" />
      </svg>
    );
  }
  return (
    <div
      style={{
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        padding: "10px 12px 6px",
      }}
    >
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {children}
      </svg>
      {caption && (
        <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "2px 2px 4px" }}>
          {caption}
        </div>
      )}
    </div>
  );
}

/**
 * El "espagueti": trayectorias individuales al fondo, bandas de percentiles
 * encima y la curva real en cobre.
 *
 * Escala logaritmica: una estrategia que compone recorre dos ordenes de
 * magnitud y en lineal el abanico de los primeros meses se aplasta contra el
 * eje, que es justo donde se decide si sobrevives.
 */
export function SpaghettiChart({
  spaghetti,
  bands,
  baseCurve,
  initCash,
  xLabel = "trades →",
  width = 900,
  height = 300,
  caption = "Cada linea tenue es una historia alternativa. Las bandas son los percentiles 5–95 y 25–75; la linea cobre, lo que paso de verdad.",
  plano = false,
}: {
  spaghetti: number[][];
  bands: McBands;
  baseCurve: number[];
  initCash: number;
  /** Unidad del eje X: robustez remuestrea por trade, portfolio por dia. */
  xLabel?: string;
  width?: number;
  height?: number;
  caption?: string;
  /** Sin caja y con el marco cuadrado (paso 3 del crudo); la leyenda la pone quien lo usa. */
  plano?: boolean;
}) {
  const H = height;
  const W = width;
  const P: Pad = plano ? PAD_PLANO : PAD;
  const geom = useMemo(() => {
    const pool = [...bands.p5, ...bands.p95, ...baseCurve, initCash].filter((v) => Number.isFinite(v));
    if (!pool.length) return null;
    const floor = Math.max(1, initCash * 0.005);
    const lo = Math.log10(Math.max(floor, Math.min(...pool)));
    const hi = Math.log10(Math.max(...pool) * 1.05);
    const span = hi - lo || 1;
    const n = Math.max(baseCurve.length, bands.p50.length, 2);

    const xOf = (i: number) => P.l + (i / (n - 1)) * (W - P.l - P.r);
    const yOf = (v: number) =>
      P.t + (1 - (Math.log10(Math.max(v, floor)) - lo) / span) * (H - P.t - P.b);
    const line = (a: number[]) =>
      a.map((v, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join("");

    // Banda como area cerrada entre dos percentiles.
    const areaBetween = (top: number[], bot: number[]) =>
      line(top) +
      bot
        .map((v, i) => `L${xOf(bot.length - 1 - i).toFixed(1)},${yOf(bot[bot.length - 1 - i]).toFixed(1)}`)
        .join("") +
      "Z";

    const ticks: number[] = [];
    for (let e = Math.floor(lo); e <= Math.ceil(hi); e++) {
      const v = Math.pow(10, e);
      if (Math.log10(v) >= lo - 1e-9 && Math.log10(v) <= hi + 1e-9) ticks.push(v);
    }
    return { xOf, yOf, line, areaBetween, ticks, n };
  }, [spaghetti, bands, baseCurve, initCash, W, H, P]);

  if (!geom) return null;

  // Submuestreo del espagueti: 120 trayectorias de 3.500 puntos son 420k nodos
  // SVG y el navegador se arrastra. Con 40 lineas ya se lee la dispersion.
  const shown = spaghetti.slice(0, 40);

  return (
    <Frame
      height={H}
      width={W}
      caption={caption}
      plano={plano}
      pad={P}
    >
      {geom.ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={geom.yOf(t)} y2={geom.yOf(t)} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray={plano ? "2 4" : undefined} />
          <text
            x={P.l - 7}
            y={geom.yOf(t) + 3}
            textAnchor="end"
            fontSize={plano ? "9.5" : "9"}
            fill="var(--color-ec-text-muted)"
            fontFamily="var(--color-ec-mono)"
          >
            ${money(t)}
          </text>
        </g>
      ))}

      {shown.map((c, i) => (
        <path key={i} d={geom.line(c)} fill="none" stroke="var(--color-ec-info)" strokeWidth="0.4" opacity="0.16" />
      ))}

      <path d={geom.areaBetween(bands.p95, bands.p5)} fill="var(--color-ec-info)" opacity="0.10" />
      <path d={geom.areaBetween(bands.p75, bands.p25)} fill="var(--color-ec-info)" opacity="0.16" />
      <path d={geom.line(bands.p50)} fill="none" stroke="var(--color-ec-info)" strokeWidth="1.1" strokeDasharray="4 3" />

      <line
        x1={P.l}
        x2={W - P.r}
        y1={geom.yOf(initCash)}
        y2={geom.yOf(initCash)}
        stroke="var(--color-ec-text-muted)"
        strokeWidth="0.75"
        strokeDasharray="3 3"
      />

      <path d={geom.line(baseCurve)} fill="none" stroke="var(--color-ec-copper)" strokeWidth="1.6" />

      {[
        { c: "var(--color-ec-copper)", label: "curva real", dash: "" },
        { c: "var(--color-ec-info)", label: "mediana simulada", dash: "4 3" },
      ].map((s, i) => (
        <g key={s.label} transform={`translate(${P.l + 8}, ${P.t + 12 + i * 15})`}>
          <line x1="0" x2="16" y1="0" y2="0" stroke={s.c} strokeWidth="1.6" strokeDasharray={s.dash} />
          <text x="21" y="3.5" fontSize="9.5" fill="var(--color-ec-text-secondary)" fontFamily="var(--color-ec-sans)">
            {s.label}
          </text>
        </g>
      ))}

      {plano && (() => {
        // Cifras finales a la derecha, como en LinesChart: lo real y la mediana.
        const fin = [
          { v: baseCurve[baseCurve.length - 1], c: "var(--color-ec-copper)" },
          { v: bands.p50[bands.p50.length - 1], c: "var(--color-ec-info)" },
        ].filter((x) => Number.isFinite(x.v)).map((x) => ({ ...x, y: geom.yOf(x.v) })).sort((a, b) => a.y - b.y);
        for (let i = 1; i < fin.length; i++) if (fin[i].y - fin[i - 1].y < 11) fin[i].y = fin[i - 1].y + 11;
        return fin.map((x, i) => (
          <text key={i} x={W - P.r + 5} y={x.y + 3.5} fontSize="9.5" fill={x.c} fontFamily="var(--color-ec-mono)">${money(x.v)}</text>
        ));
      })()}

      <text
        x={W - P.r}
        y={plano ? H - P.b + 15 : H - 8}
        textAnchor="end"
        fontSize={plano ? "9.5" : "9"}
        fill="var(--color-ec-text-muted)"
        fontFamily={plano ? "var(--color-ec-mono)" : "var(--color-ec-sans)"}
      >
        {xLabel}
      </text>
    </Frame>
  );
}

/**
 * Distribucion con marcas de referencia. `markers` pinta lineas verticales
 * etiquetadas (p. ej. el valor real, o el umbral de ruina).
 */
export function DistributionChart({
  hist,
  markers = [],
  barColor = "var(--color-ec-info)",
  fmtValue = (v: number) => `$${money(v)}`,
  caption,
  width = 900,
  height = 190,
  plano = false,
}: {
  hist: McHistogram;
  markers?: Array<{ value: number; label: string; color: string }>;
  barColor?: string;
  fmtValue?: (v: number) => string;
  caption?: string;
  width?: number;
  height?: number;
  /** Sin caja y con el marco cuadrado (paso 3 del crudo); el pie lo pone quien lo usa. */
  plano?: boolean;
}) {
  const H = height;
  const W = width;
  const P: Pad = plano ? PAD_PLANO_DIST : PAD;
  const { counts, edges } = hist;
  if (!counts.length || edges.length < 2) return null;

  const lo = edges[0];
  const hi = edges[edges.length - 1];
  const span = hi - lo || 1;
  const maxC = Math.max(...counts);
  const innerW = W - P.l - P.r;
  const xOf = (v: number) => P.l + ((v - lo) / span) * innerW;
  const yOf = (c: number) => P.t + (1 - c / maxC) * (H - P.t - P.b);

  return (
    <Frame height={H} width={W} caption={caption} plano={plano} pad={P}>
      {counts.map((c, i) => {
        const x0 = xOf(edges[i]);
        const x1 = xOf(edges[i + 1]);
        return (
          <rect
            key={i}
            x={x0}
            y={yOf(c)}
            width={Math.max(0.6, x1 - x0 - 0.8)}
            height={H - P.b - yOf(c)}
            fill={barColor}
            opacity="0.5"
          />
        );
      })}

      <line x1={P.l} x2={W - P.r} y1={H - P.b} y2={H - P.b} stroke="var(--color-ec-border)" strokeWidth="0.5" />

      {markers.map((m, i) => {
        if (m.value < lo || m.value > hi) return null;
        const x = xOf(m.value);
        return (
          <g key={i}>
            <line x1={x} x2={x} y1={P.t} y2={H - P.b} stroke={m.color} strokeWidth="1.1" strokeDasharray="3 2" />
            <text
              x={Math.min(x + 5, W - P.r - 4)}
              y={P.t + 10 + i * 13}
              fontSize="9.5"
              fill={m.color}
              fontFamily="var(--color-ec-mono)"
              textAnchor={x > W - 180 ? "end" : "start"}
            >
              {m.label}
            </text>
          </g>
        );
      })}

      {(plano && W < 360 ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1]).map((f) => {
        const v = lo + f * span;
        return (
          <text
            key={f}
            x={P.l + f * innerW}
            y={H - P.b + (plano ? 15 : 13)}
            textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"}
            fontSize="9"
            fill="var(--color-ec-text-muted)"
            fontFamily="var(--color-ec-mono)"
          >
            {fmtValue(v)}
          </text>
        );
      })}
    </Frame>
  );
}
