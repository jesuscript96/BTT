"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { color, font, radius } from "@/components/ui/tokens";

// Mismo patron que OptimizationSurfaceTab: plotly no puede renderizarse en el
// servidor, asi que se carga solo en cliente y bajo demanda.
// plotly.js no trae tipos, de ahi los ts-ignore y el `as any` final.
const Plot = dynamic(
  async () => {
    // @ts-ignore
    const Plotly = await import("plotly.js-dist-min");
    // @ts-ignore
    const factory = await import("react-plotly.js/factory");
    const createPlotComponent = (factory as any).default;
    return { default: createPlotComponent(Plotly) };
  },
  { ssr: false, loading: () => <PlotSkeleton /> },
) as any;

function PlotSkeleton() {
  return (
    <div
      style={{
        height: 420,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        fontFamily: font.sans,
        fontSize: 12,
        color: color.textMuted,
      }}
    >
      Cargando el motor 3D…
    </div>
  );
}

/**
 * Paleta divergente centrada en cero, construida sobre los rojos y verdes del
 * design system.
 *
 * Es un degradado CONTINUO. Una version anterior metia un corte gris duro justo
 * en el cero para "marcar la frontera", y el resultado era una banda embarrada
 * que ensuciaba toda la superficie. La frontera ya la marcan el plano cero y las
 * curvas de nivel; el color solo tiene que decir de que lado estas.
 */
const DIVERGING: Array<[number, string]> = [
  [0.0, "#5A1E18"],
  [0.18, "#8E3227"],
  [0.36, "#C94D3F"],
  [0.47, "#8C5A50"],
  [0.5, "#3A3D41"],
  [0.53, "#4C7A69"],
  [0.64, "#4A9D7F"],
  [0.82, "#3B8168"],
  [1.0, "#256050"],
];

const PLOT_LAYOUT_BASE = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: "ui-monospace, Menlo, Consolas, monospace", size: 11, color: "#8A8D92" },
  margin: { l: 0, r: 0, t: 10, b: 0 },
  hoverlabel: {
    bgcolor: "#232528",
    bordercolor: "#D87A3D",
    font: { family: "ui-monospace, Menlo, Consolas, monospace", size: 11, color: "#E4E2DF" },
  },
};

const AXIS_3D = {
  gridcolor: "#2A2D31",
  gridwidth: 1,
  zerolinecolor: "#6A6D72",
  zerolinewidth: 1,
  showbackground: true,
  // Paredes apenas insinuadas: el fondo de la app se ve a traves y la figura
  // no queda encerrada en una caja.
  backgroundcolor: "rgba(20,22,24,0.42)",
  showspikes: false,
  titlefont: { size: 10.5, color: "#9A9DA2" },
  tickfont: { size: 9, color: "#707378" },
};

export interface MatrixData {
  locates_values: number[];
  slippage_values: number[];
  grids: Record<string, Array<Array<number | null>>>;
}

/** Punto en el que se ejecuto la estrategia de verdad. */
export interface OperatingPoint {
  locates: number;
  slippagePct: number;
}

/** Interpola bilinealmente el valor de la rejilla en un punto arbitrario. */
function sampleGrid(
  z: Array<Array<number | null>>,
  xs: number[],
  ys: number[],
  x: number,
  y: number,
): number | null {
  if (!z.length || !xs.length || !ys.length) return null;
  const findCell = (arr: number[], v: number) => {
    for (let i = 0; i < arr.length - 1; i++) if (v <= arr[i + 1]) return i;
    return Math.max(0, arr.length - 2);
  };
  const ix = findCell(xs, x);
  const iy = findCell(ys, y);
  const x0 = xs[ix];
  const x1 = xs[ix + 1] ?? x0;
  const y0 = ys[iy];
  const y1 = ys[iy + 1] ?? y0;
  const tx = x1 === x0 ? 0 : (x - x0) / (x1 - x0);
  const ty = y1 === y0 ? 0 : (y - y0) / (y1 - y0);
  const q = [z[iy]?.[ix], z[iy]?.[ix + 1], z[iy + 1]?.[ix], z[iy + 1]?.[ix + 1]];
  if (q.some((v) => v == null || !Number.isFinite(v))) return null;
  const [a, b, c, d] = q as number[];
  return a * (1 - tx) * (1 - ty) + b * tx * (1 - ty) + c * (1 - tx) * ty + d * tx * ty;
}

/**
 * Superficie 3D: X = coste de locates, Y = slippage, Z = la metrica elegida.
 *
 * Tres cosas que no son decorativas:
 *   - el plano Z=0 translucido: donde la superficie lo atraviesa esta la
 *     frontera de rentabilidad, que es a lo que se viene aqui;
 *   - las curvas de nivel proyectadas en la base, que dibujan esa frontera
 *     vista desde arriba sin tener que girar la figura;
 *   - el marcador del punto en el que se ejecuto la estrategia de verdad, para
 *     ver de un vistazo cuanto margen queda hasta el borde.
 */
export function LocatesSlippageSurface({
  data,
  metricKey,
  metricLabel,
  showZeroPlane,
  operating,
}: {
  data: MatrixData;
  metricKey: string;
  metricLabel: string;
  showZeroPlane: boolean;
  operating?: OperatingPoint;
}) {
  const z = data.grids[metricKey] || [];

  const { zmin, zmax, hasSignChange } = useMemo(() => {
    const flat = z.flat().filter((v): v is number => v != null && Number.isFinite(v));
    if (!flat.length) return { zmin: 0, zmax: 1, hasSignChange: false };
    const lo = Math.min(...flat);
    const hi = Math.max(...flat);
    return { zmin: lo, zmax: hi, hasSignChange: lo < 0 && hi > 0 };
  }, [z]);

  // Centrar la paleta en cero para que el color diga "gana o pierde" y no solo
  // "mas o menos". Sin esto, una superficie toda negativa se pintaria verde.
  const absMax = Math.max(Math.abs(zmin), Math.abs(zmax)) || 1;
  const centered = hasSignChange;

  const traces: any[] = [
    {
      type: "surface",
      x: data.locates_values,
      y: data.slippage_values,
      z,
      colorscale: DIVERGING,
      cmin: centered ? -absMax : zmin,
      cmax: centered ? absMax : zmax,
      showscale: true,
      opacity: 1,
      // Iluminacion mate: da relieve a la pendiente sin brillos plasticos.
      lighting: { ambient: 0.78, diffuse: 0.5, specular: 0.02, roughness: 1, fresnel: 0.05 },
      lightposition: { x: 140, y: -120, z: 220 },
      colorbar: {
        title: { text: metricLabel, font: { size: 10, color: "#9A9DA2" }, side: "right" },
        thickness: 8,
        len: 0.5,
        y: 0.52,
        tickfont: { size: 9, color: "#707378" },
        outlinewidth: 0,
        bgcolor: "rgba(0,0,0,0)",
      },
      contours: {
        // Solo curvas de nivel proyectadas en la BASE: son la frontera vista
        // desde arriba y no ensucian la superficie. Los contornos en las
        // paredes (x / y) se quitaron: solo añadian ruido.
        z: {
          show: true,
          usecolormap: false,
          color: "rgba(228,226,223,0.22)",
          project: { z: true },
          width: 1.5,
          highlight: true,
          highlightcolor: "#E89C6A",
          highlightwidth: 2,
        },
      },
      hovertemplate:
        "<b>locates</b> $%{x:.2f} / 100 acc<br><b>slippage</b> %{y:.2f}%<br><b>" +
        metricLabel +
        "</b> %{z:.2f}<extra></extra>",
    },
  ];

  if (showZeroPlane && hasSignChange) {
    traces.push({
      type: "surface",
      x: data.locates_values,
      y: data.slippage_values,
      z: data.slippage_values.map(() => data.locates_values.map(() => 0)),
      showscale: false,
      opacity: 0.16,
      colorscale: [
        [0, "#D4D2CF"],
        [1, "#D4D2CF"],
      ],
      hoverinfo: "skip",
      contours: { z: { show: false } },
      lighting: { ambient: 1, diffuse: 0, specular: 0 },
    });
  }

  // Donde estas tu: el coste de locates y el slippage con los que corrio el
  // backtest guardado, con una plomada hasta el plano cero para ver el margen.
  if (operating) {
    const zv = sampleGrid(z, data.locates_values, data.slippage_values, operating.locates, operating.slippagePct);
    const inside =
      operating.locates >= Math.min(...data.locates_values) &&
      operating.locates <= Math.max(...data.locates_values) &&
      operating.slippagePct >= Math.min(...data.slippage_values) &&
      operating.slippagePct <= Math.max(...data.slippage_values);
    if (zv != null && inside) {
      traces.push({
        type: "scatter3d",
        mode: "lines",
        x: [operating.locates, operating.locates],
        y: [operating.slippagePct, operating.slippagePct],
        z: [0, zv],
        line: { color: "#E89C6A", width: 2, dash: "dot" },
        hoverinfo: "skip",
        showlegend: false,
      });
      traces.push({
        type: "scatter3d",
        mode: "markers",
        x: [operating.locates],
        y: [operating.slippagePct],
        z: [zv],
        marker: {
          size: 7,
          color: "#E89C6A",
          symbol: "diamond",
          line: { color: "#16181A", width: 1.5 },
        },
        hovertemplate:
          "<b>tu configuracion</b><br>locates $" +
          operating.locates +
          "<br>slippage " +
          operating.slippagePct.toFixed(3) +
          "%<br>" +
          metricLabel +
          " %{z:.2f}<extra></extra>",
        showlegend: false,
      });
    }
  }

  return (
    <div style={{ background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: 6 }}>
      <Plot
        data={traces}
        layout={{
          ...PLOT_LAYOUT_BASE,
          height: 480,
          scene: {
            xaxis: { ...AXIS_3D, title: { text: "Locates  ($ / 100 acc)" } },
            yaxis: { ...AXIS_3D, title: { text: "Slippage  (%)" } },
            zaxis: { ...AXIS_3D, title: { text: metricLabel } },
            camera: { eye: { x: 1.55, y: -1.78, z: 0.7 }, up: { x: 0, y: 0, z: 1 } },
            aspectratio: { x: 1.1, y: 1, z: 0.58 },
          },
        }}
        config={{ displayModeBar: true, displaylogo: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "0 6px 6px", lineHeight: 1.5 }}>
        Arrastra para girar.{" "}
        {showZeroPlane && hasSignChange
          ? "El plano gris es el cero: donde la superficie lo atraviesa, la estrategia deja de ganar. Las curvas de nivel de la base son esa misma frontera vista desde arriba."
          : "La metrica no cambia de signo en este rango."}
        {operating ? " El rombo cobre marca la configuracion con la que corriste el backtest." : ""}
      </div>
    </div>
  );
}

/** Mapa de calor plano: mismo dato, mas facil de leer un valor concreto. */
export function LocatesSlippageHeatmap({
  data,
  metricKey,
  metricLabel,
  operating,
}: {
  data: MatrixData;
  metricKey: string;
  metricLabel: string;
  operating?: OperatingPoint;
}) {
  const z = data.grids[metricKey] || [];
  const flat = z.flat().filter((v): v is number => v != null && Number.isFinite(v));
  const lo = flat.length ? Math.min(...flat) : 0;
  const hi = flat.length ? Math.max(...flat) : 1;
  const centered = lo < 0 && hi > 0;
  const absMax = Math.max(Math.abs(lo), Math.abs(hi)) || 1;

  const traces: any[] = [
    {
      type: "heatmap",
      x: data.locates_values,
      y: data.slippage_values,
      z,
      colorscale: DIVERGING,
      zmin: centered ? -absMax : lo,
      zmax: centered ? absMax : hi,
      colorbar: {
        title: { text: metricLabel, font: { size: 10, color: "#A8ABB0" } },
        thickness: 9,
        len: 0.8,
        tickfont: { size: 9, color: "#7A7D82" },
        outlinewidth: 0,
      },
      hovertemplate:
        "<b>locates</b> $%{x}<br><b>slippage</b> %{y}%<br><b>" + metricLabel + "</b> %{z:.2f}<extra></extra>",
    },
  ];

  // Frontera de rentabilidad, dibujada como curva de nivel en cero.
  if (centered) {
    traces.push({
      type: "contour",
      x: data.locates_values,
      y: data.slippage_values,
      z,
      showscale: false,
      contours: { coloring: "none", start: 0, end: 0, size: 1 },
      line: { color: "#E89C6A", width: 2 },
      hoverinfo: "skip",
    });
  }

  if (operating) {
    traces.push({
      type: "scatter",
      mode: "markers+text",
      x: [operating.locates],
      y: [operating.slippagePct],
      marker: { size: 11, color: "#E89C6A", symbol: "diamond", line: { color: "#16181A", width: 1.5 } },
      text: ["aqui estas"],
      textposition: "top center",
      textfont: { size: 9.5, color: "#E89C6A" },
      hovertemplate: "tu configuracion<extra></extra>",
      showlegend: false,
    });
  }

  return (
    <div style={{ background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: 6 }}>
      <Plot
        data={traces}
        layout={{
          ...PLOT_LAYOUT_BASE,
          height: 340,
          margin: { l: 58, r: 10, t: 10, b: 44 },
          xaxis: {
            title: { text: "Locates ($/100 acc)", font: { size: 11, color: "#A8ABB0" } },
            gridcolor: "#2C2F33",
            tickfont: { size: 9.5, color: "#7A7D82" },
          },
          yaxis: {
            title: { text: "Slippage (%)", font: { size: 11, color: "#A8ABB0" } },
            gridcolor: "#2C2F33",
            tickfont: { size: 9.5, color: "#7A7D82" },
          },
          showlegend: false,
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "0 6px 6px" }}>
        La linea cobre es la frontera: a su derecha la estrategia ya no gana.
      </div>
    </div>
  );
}
/* ── Curvas 2D: una por cada coste de locates ─────────────────────── */

export interface LocateCurve {
  locates_cost: number;
  metrics: Record<string, number | null>;
  equity_by_time: Array<{ time: number; value: number }>;
  equity_by_trade: number[];
}

const W = 900;
const H = 300;
const PAD = { t: 14, r: 96, b: 26, l: 60 };

const money = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1000) return `${(v / 1000).toFixed(a >= 10_000 ? 0 : 1)}k`;
  return v.toFixed(0);
};

/**
 * Una curva de equity por coste de locates, en escala logaritmica.
 *
 * El color va de cobre (locates baratos) a rojo (caros), asi que se ve de un
 * vistazo a partir de que coste la curva se despega hacia abajo.
 */
export function LocatesCurvesChart({
  curves,
  axis,
  initCash,
}: {
  curves: LocateCurve[];
  axis: "time" | "trade";
  initCash: number;
}) {
  const geom = useMemo(() => {
    const series = curves.map((c) =>
      axis === "time" ? c.equity_by_time.map((p) => p.value) : c.equity_by_trade,
    );
    const all = series.flat().filter((v) => Number.isFinite(v));
    if (!all.length) return null;

    const floor = Math.max(1, initCash * 0.02);
    const lo = Math.log10(Math.max(floor, Math.min(...all, initCash)));
    const hi = Math.log10(Math.max(...all, initCash * 1.05));
    const span = hi - lo || 1;
    const n = Math.max(...series.map((s) => s.length), 2);

    const xOf = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const yOf = (v: number) =>
      PAD.t + (1 - (Math.log10(Math.max(v, floor)) - lo) / span) * (H - PAD.t - PAD.b);
    const line = (a: number[]) =>
      a.map((v, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join("");

    const ticks: number[] = [];
    for (let e = Math.floor(lo); e <= Math.ceil(hi); e++) {
      const v = Math.pow(10, e);
      if (Math.log10(v) >= lo - 1e-9 && Math.log10(v) <= hi + 1e-9) ticks.push(v);
    }
    return { series, xOf, yOf, line, ticks, n };
  }, [curves, axis, initCash]);

  if (!geom) return null;

  const tone = (i: number) => {
    const f = curves.length > 1 ? i / (curves.length - 1) : 0;
    // cobre (barato) -> rojo (caro)
    const r = Math.round(216 + (201 - 216) * f);
    const g = Math.round(122 + (77 - 122) * f);
    const b = Math.round(61 + (63 - 61) * f);
    return `rgb(${r},${g},${b})`;
  };

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
        {geom.ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={geom.yOf(t)} y2={geom.yOf(t)} stroke="var(--color-ec-border)" strokeWidth="0.5" />
            <text x={PAD.l - 7} y={geom.yOf(t) + 3} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-mono)">
              ${money(t)}
            </text>
          </g>
        ))}

        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={geom.yOf(initCash)}
          y2={geom.yOf(initCash)}
          stroke="var(--color-ec-text-muted)"
          strokeWidth="0.75"
          strokeDasharray="3 3"
        />

        {geom.series.map((s, i) => (
          <path key={i} d={geom.line(s)} fill="none" stroke={tone(i)} strokeWidth="1.2" />
        ))}

        {/* Leyenda: coste de locates al final de cada curva */}
        {geom.series.map((s, i) => {
          const last = s[s.length - 1];
          if (!Number.isFinite(last)) return null;
          return (
            <text
              key={`l${i}`}
              x={W - PAD.r + 6}
              y={geom.yOf(last) + 3}
              fontSize="9.5"
              fill={tone(i)}
              fontFamily="var(--color-ec-mono)"
            >
              ${curves[i].locates_cost}
            </text>
          );
        })}

        <text x={W - PAD.r} y={H - 7} textAnchor="end" fontSize="9" fill="var(--color-ec-text-muted)" fontFamily="var(--color-ec-sans)">
          {axis === "time" ? "tiempo →" : "trades →"}
        </text>
      </svg>
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "2px 2px 4px" }}>
        Escala logaritmica. Cada curva es un coste de locates ($ por cada 100 acciones); la etiqueta de
        la derecha lo indica. La linea de puntos es el capital inicial.
      </div>
    </div>
  );
}
