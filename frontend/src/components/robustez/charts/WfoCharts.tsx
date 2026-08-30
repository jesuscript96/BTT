"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { WfoWindow } from "@/lib/api_robustez";

// @ts-ignore — plotly.js no trae tipos; mismo tratamiento que el resto de la app.
const Plot = dynamic(
  async () => {
    // @ts-ignore
    const Plotly = await import("plotly.js-dist-min");
    // @ts-ignore
    const factory = await import("react-plotly.js/factory");
    return { default: (factory as any).default(Plotly) };
  },
  { ssr: false },
) as any;

const W = 900;
const H = 240;
const PAD = { t: 16, r: 14, b: 40, l: 52 };

/**
 * Barras pareadas por ventana: lo que rindio dentro de muestra contra lo que
 * rindio fuera. La lectura es la CAIDA de una a otra, no el valor absoluto.
 */
export function WfoWindowBars({
  windows,
  metricKey = "return_pct",
  metricLabel = "Retorno %",
}: {
  windows: WfoWindow[];
  metricKey?: "return_pct" | "sharpe" | "profit_factor";
  metricLabel?: string;
}) {
  const geom = useMemo(() => {
    const vals = windows.flatMap((w) => [
      Number(w.is[metricKey] ?? 0),
      Number(w.oos[metricKey] ?? 0),
    ]);
    if (!vals.length) return null;
    const lo = Math.min(0, ...vals);
    const hi = Math.max(0, ...vals);
    const span = hi - lo || 1;
    const innerW = W - PAD.l - PAD.r;
    const innerH = H - PAD.t - PAD.b;
    const slot = innerW / windows.length;
    const yOf = (v: number) => PAD.t + (1 - (v - lo) / span) * innerH;
    return { lo, hi, span, slot, yOf, y0: PAD.t + (1 - (0 - lo) / span) * innerH };
  }, [windows, metricKey]);

  if (!geom || !windows.length) return null;

  return (
    <div
      style={{
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        padding: "10px 12px 6px",
      }}
    >
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {[geom.lo, (geom.lo + geom.hi) / 2, geom.hi].map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={geom.yOf(t)}
              y2={geom.yOf(t)}
              stroke="var(--color-ec-border)"
              strokeWidth="0.5"
            />
            <text
              x={PAD.l - 7}
              y={geom.yOf(t) + 3}
              textAnchor="end"
              fontSize="9"
              fill="var(--color-ec-text-muted)"
              fontFamily="var(--color-ec-mono)"
            >
              {t.toFixed(1)}
            </text>
          </g>
        ))}

        <line x1={PAD.l} x2={W - PAD.r} y1={geom.y0} y2={geom.y0} stroke="var(--color-ec-text-muted)" strokeWidth="0.8" />

        {windows.map((w, i) => {
          const cx = PAD.l + i * geom.slot;
          const bw = geom.slot * 0.3;
          const isV = Number(w.is[metricKey] ?? 0);
          const oosV = Number(w.oos[metricKey] ?? 0);
          const bar = (v: number, x: number, fill: string) => {
            const y = geom.yOf(v);
            return <rect x={x} y={Math.min(y, geom.y0)} width={bw} height={Math.max(1.5, Math.abs(geom.y0 - y))} fill={fill} rx="1" />;
          };
          return (
            <g key={w.index}>
              {bar(isV, cx + geom.slot * 0.14, "var(--color-ec-info)")}
              {bar(oosV, cx + geom.slot * 0.5, oosV >= 0 ? "var(--color-ec-copper)" : "var(--color-ec-loss)")}
              <text
                x={cx + geom.slot / 2}
                y={H - PAD.b + 14}
                textAnchor="middle"
                fontSize="9"
                fill="var(--color-ec-text-muted)"
                fontFamily="var(--color-ec-mono)"
              >
                V{w.index}
              </text>
              <text
                x={cx + geom.slot / 2}
                y={H - PAD.b + 25}
                textAnchor="middle"
                fontSize="8"
                fill="var(--color-ec-text-muted)"
                fontFamily="var(--color-ec-mono)"
              >
                {w.oos_from.slice(2, 7)}
              </text>
            </g>
          );
        })}

        {[
          { c: "var(--color-ec-info)", label: "dentro de muestra (IS)" },
          { c: "var(--color-ec-copper)", label: "fuera de muestra (OOS)" },
        ].map((s, i) => (
          <g key={s.label} transform={`translate(${PAD.l + 6 + i * 180}, ${PAD.t - 4})`}>
            <rect x="0" y="-6" width="10" height="8" fill={s.c} rx="1" />
            <text x="15" y="1" fontSize="9.5" fill="var(--color-ec-text-secondary)" fontFamily="var(--color-ec-sans)">
              {s.label}
            </text>
          </g>
        ))}
      </svg>
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "2px 2px 4px" }}>
        {metricLabel} por ventana. Lo que importa es cuanto CAE la barra cobre respecto a la azul: esa
        caida es el sobreajuste.
      </div>
    </div>
  );
}

/**
 * La matriz clasica del walk-forward: cada ventana contra cada valor del
 * parametro, coloreada por la metrica. Un parametro robusto forma una BANDA
 * de color estable a lo largo de todas las ventanas; uno sobreajustado da un
 * mosaico donde el optimo salta de sitio cada vez.
 */
export function WfoParamMatrix({
  windows,
  paramValues,
  paramLabel,
  paramIndex = 0,
  metricLabel,
  view,
  formatValue,
}: {
  windows: WfoWindow[];
  paramValues: number[];
  paramLabel: string;
  /** Que posicion de la combinacion pinta esta matriz. Barriendo un solo
   *  parametro es 0 y no cambia nada. */
  paramIndex?: number;
  metricLabel: string;
  view: "3d" | "heatmap";
  /** Como se lee un valor del eje. Un parametro de HORA viaja en minutos desde
   *  medianoche (08:30 = 510) y sin esto los ejes pintaban el 510 crudo. */
  formatValue?: (v: number) => string;
}) {
  // Marcas del eje X. Solo se tocan si hay formateador: sin el, todo se queda
  // EXACTAMENTE como estaba (Plotly elige sus propias marcas).
  const ejeX = formatValue
    ? { tickmode: "array" as const, tickvals: paramValues, ticktext: paramValues.map(formatValue) }
    : {};
  // El globo del raton lee `%{x}` crudo, asi que la version formateada viaja
  // aparte en `customdata` (una fila por ventana, un valor por punto).
  const customX = formatValue
    ? windows.map(() => paramValues.map(formatValue))
    : undefined;
  const marcaX = formatValue ? "%{customdata}" : "%{x}";
  const z = useMemo(
    () =>
      windows.map((w) =>
        paramValues.map((v) => {
          // Con un solo parametro hay UNA prueba por valor y esto es lo de
          // siempre. Con varios hay una por combinacion del resto: se toma la
          // mejor, que es lo que ese valor daba de si.
          const puntos = (w.trials || [])
            .filter((tr) => Math.abs((tr.params?.[paramIndex] ?? NaN) - v) < 1e-6)
            .map((tr) => tr.score)
            .filter((s): s is number => s != null && Number.isFinite(s));
          return puntos.length ? Math.max(...puntos) : null;
        }),
      ),
    [windows, paramValues, paramIndex],
  );

  const flat = z.flat().filter((v): v is number => v != null && Number.isFinite(v));
  if (!flat.length) return null;
  const lo = Math.min(...flat);
  const hi = Math.max(...flat);
  const centered = lo < 0 && hi > 0;
  const absMax = Math.max(Math.abs(lo), Math.abs(hi)) || 1;

  const scale: Array<[number, string]> = centered
    ? [
        [0, "#7B2D26"],
        [0.35, "#C94D3F"],
        [0.5, "#2C2F33"],
        [0.65, "#4A9D7F"],
        [1, "#2E6B57"],
      ]
    : [
        [0, "#2C2F33"],
        [0.5, "#D87A3D"],
        [1, "#E89C6A"],
      ];

  const yLabels = windows.map((w) => `V${w.index}`);
  const base = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "ui-monospace, Menlo, Consolas, monospace", size: 11, color: "#8A8D92" },
  };
  const colorbar = {
    title: { text: metricLabel, font: { size: 10, color: "#8A8D92" } },
    thickness: 10,
    len: 0.7,
    tickfont: { size: 9, color: "#6A6D72" },
    outlinewidth: 0,
  };

  const marks = windows
    .map((w, i) => ({ x: w.best_params?.[0], y: yLabels[i] }))
    .filter((m) => m.x != null);

  return (
    <div style={{ background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: 6 }}>
      {view === "3d" ? (
        <Plot
          data={[
            {
              type: "surface",
              x: paramValues,
              y: windows.map((w) => w.index),
              z,
              colorscale: scale,
              cmin: centered ? -absMax : lo,
              cmax: centered ? absMax : hi,
              colorbar,
              contours: { z: { show: true, usecolormap: true, project: { z: true }, width: 1 } },
              ...(customX ? { customdata: customX } : {}),
              hovertemplate: `${paramLabel}: ${marcaX}<br>ventana %{y}<br>${metricLabel}: %{z:.3f}<extra></extra>`,
            },
          ]}
          layout={{
            ...base,
            height: 440,
            margin: { l: 0, r: 0, t: 10, b: 0 },
            scene: {
              xaxis: {
                title: { text: paramLabel, font: { size: 11, color: "#8A8D92" } },
                gridcolor: "#2C2F33",
                showbackground: true,
                backgroundcolor: "rgba(28,30,33,0.35)",
                tickfont: { size: 9.5, color: "#6A6D72" },
                ...ejeX,
              },
              yaxis: {
                title: { text: "Ventana", font: { size: 11, color: "#8A8D92" } },
                gridcolor: "#2C2F33",
                showbackground: true,
                backgroundcolor: "rgba(28,30,33,0.35)",
                tickfont: { size: 9.5, color: "#6A6D72" },
              },
              zaxis: {
                title: { text: metricLabel, font: { size: 11, color: "#8A8D92" } },
                gridcolor: "#2C2F33",
                showbackground: true,
                backgroundcolor: "rgba(28,30,33,0.35)",
                tickfont: { size: 9.5, color: "#6A6D72" },
              },
              camera: { eye: { x: 1.75, y: -1.6, z: 0.85 } },
              aspectratio: { x: 1, y: 1, z: 0.6 },
            },
          }}
          config={{ displayModeBar: true, displaylogo: false, responsive: true }}
          style={{ width: "100%" }}
          useResizeHandler
        />
      ) : (
        <Plot
          data={[
            {
              type: "heatmap",
              x: paramValues,
              y: yLabels,
              z,
              colorscale: scale,
              zmin: centered ? -absMax : lo,
              zmax: centered ? absMax : hi,
              colorbar,
              ...(customX ? { customdata: customX } : {}),
              hovertemplate: `${paramLabel}: ${marcaX}<br>%{y}<br>${metricLabel}: %{z:.3f}<extra></extra>`,
            },
            {
              type: "scatter",
              mode: "markers",
              x: marks.map((m) => m.x),
              y: marks.map((m) => m.y),
              marker: { symbol: "circle-open", size: 13, color: "#E4E2DF", line: { width: 2 } },
              hovertemplate: "optimo de la ventana<extra></extra>",
              showlegend: false,
            },
          ]}
          layout={{
            ...base,
            height: 300,
            margin: { l: 52, r: 10, t: 10, b: 46 },
            xaxis: {
              title: { text: paramLabel, font: { size: 11, color: "#8A8D92" } },
              gridcolor: "#2C2F33",
              tickfont: { size: 9.5, color: "#6A6D72" },
              ...ejeX,
            },
            yaxis: { gridcolor: "#2C2F33", tickfont: { size: 9.5, color: "#6A6D72" }, autorange: "reversed" },
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: "100%" }}
          useResizeHandler
        />
      )}
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "0 6px 6px" }}>
        {view === "heatmap" && "El circulo marca el valor ganador de cada ventana. "}
        Si el optimo se queda en la misma zona ventana tras ventana, el parametro es robusto. Si salta
        de un extremo a otro, lo que estas optimizando es ruido.
      </div>
    </div>
  );
}
