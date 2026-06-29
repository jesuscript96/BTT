"use client";

/**
 * Market Analysis — primitivas de gráfico construidas con visx (@visx/*).
 *
 * Reemplazan a recharts SOLO en /market-analysis. Tres piezas pensadas como
 * dashboard, no como "una librería pintando datos":
 *   · TimingChart      — superpone HOD/LOD/PMH en un único eje intradía.
 *   · MaeMfeTornado    — histograma espejo (riesgo a la izquierda, recorrido a la derecha).
 *   · SeasonalityChart — las 12 curvas mensuales superpuestas, una resaltada.
 *
 * Todo el color/tipografía sale de los tokens del Design System (Edgecute):
 * cobre = acento de marca, profit/loss/info = series secundarias.
 */
import React, { useMemo, useCallback } from "react";
import { Group } from "@visx/group";
import { Bar, LinePath, AreaClosed, Line } from "@visx/shape";
import { scaleBand, scaleLinear, scalePoint } from "@visx/scale";
import { AxisBottom, AxisLeft } from "@visx/axis";
import { GridRows } from "@visx/grid";
import { LinearGradient } from "@visx/gradient";
import { curveMonotoneX } from "@visx/curve";
import { ParentSize } from "@visx/responsive";
import { useTooltip, TooltipWithBounds } from "@visx/tooltip";
import { localPoint } from "@visx/event";
import { color, font } from "@/components/ui";

// ── paleta de series (var(--…) válidos como fill/stroke SVG) ──────────────────
export const SERIES_COLOR = {
  hod: color.copper, // acento de marca → la serie protagonista (cuándo marca el máximo)
  lod: color.loss,
  pmh: color.info,
} as const;

const AXIS = color.textMuted;
const GRID = color.border;

const tooltipStyle: React.CSSProperties = {
  position: "absolute",
  pointerEvents: "none",
  background: color.bgElevated,
  border: `0.5px solid ${color.border}`,
  borderRadius: 8,
  padding: "8px 10px",
  fontFamily: font.sans,
  fontSize: 11,
  color: color.textPrimary,
  boxShadow: "0 8px 24px rgba(0,0,0,.45)",
  lineHeight: 1.5,
};

const axisLabelProps = (anchor: "middle" | "end" | "start" = "middle") =>
  ({ fill: AXIS, fontSize: 9, fontFamily: font.sans, textAnchor: anchor }) as const;

// ── util: ordenar franjas horarias "HH:MM" o "HH:MM-HH:MM" ────────────────────
function sortTimeKeys(keys: string[]): string[] {
  return [...keys].sort((a, b) => a.localeCompare(b));
}
const leadingNum = (s: string) => {
  const m = s.match(/-?\d+(\.\d+)?/);
  return m ? parseFloat(m[0]) : 0;
};

// ════════════════════════════════════════════════════════════════════════════
//  1 · TimingChart — HOD / LOD / PM High superpuestos
// ════════════════════════════════════════════════════════════════════════════
type TimingDatum = { franja: string; hod: number; lod: number; pmh: number };

export function TimingChart({
  hod,
  lod,
  pmh,
  height = 240,
}: {
  hod: Record<string, number>;
  lod: Record<string, number>;
  pmh: Record<string, number>;
  height?: number;
}) {
  const franjas = useMemo(
    () => sortTimeKeys(Array.from(new Set([...Object.keys(hod), ...Object.keys(lod), ...Object.keys(pmh)]))),
    [hod, lod, pmh],
  );
  const rows: TimingDatum[] = useMemo(
    () => franjas.map((f) => ({ franja: f, hod: hod[f] ?? 0, lod: lod[f] ?? 0, pmh: pmh[f] ?? 0 })),
    [franjas, hod, lod, pmh],
  );

  return (
    <div style={{ position: "relative", height }}>
      <ParentSize>
        {({ width }) => <TimingInner width={width} height={height} rows={rows} franjas={franjas} />}
      </ParentSize>
    </div>
  );
}

function TimingInner({
  width,
  height,
  rows,
  franjas,
}: {
  width: number;
  height: number;
  rows: TimingDatum[];
  franjas: string[];
}) {
  const m = { top: 12, right: 12, bottom: 34, left: 34 };
  const iw = Math.max(0, width - m.left - m.right);
  const ih = Math.max(0, height - m.top - m.bottom);

  const x = useMemo(() => scalePoint<string>({ domain: franjas, range: [0, iw], padding: 0.5 }), [franjas, iw]);
  const yMax = useMemo(() => Math.max(5, ...rows.flatMap((r) => [r.hod, r.lod, r.pmh])), [rows]);
  const y = useMemo(() => scaleLinear<number>({ domain: [0, yMax * 1.1], range: [ih, 0] }), [yMax, ih]);

  // etiquetas de eje X espaciadas para no amontonar
  const tickEvery = Math.max(1, Math.ceil(franjas.length / 9));
  const xTicks = franjas.filter((_, i) => i % tickEvery === 0);

  const { showTooltip, hideTooltip, tooltipData, tooltipLeft, tooltipTop, tooltipOpen } =
    useTooltip<TimingDatum>();

  const onMove = useCallback(
    (e: React.MouseEvent<SVGRectElement>) => {
      const px = (localPoint(e)?.x ?? 0) - m.left;
      let nearest = rows[0];
      let best = Infinity;
      rows.forEach((r) => {
        const d = Math.abs((x(r.franja) ?? 0) - px);
        if (d < best) { best = d; nearest = r; }
      });
      showTooltip({
        tooltipData: nearest,
        tooltipLeft: (x(nearest.franja) ?? 0) + m.left,
        tooltipTop: m.top,
      });
    },
    [rows, x, showTooltip, m.left, m.top],
  );

  const lineFor = (key: keyof Omit<TimingDatum, "franja">) =>
    rows.map((r) => ({ fx: (x(r.franja) ?? 0), fy: y(r[key]) }));

  if (iw <= 0) return null;

  return (
    <>
      <svg width={width} height={height}>
        <LinearGradient id="ma-hod-fill" from={SERIES_COLOR.hod} to={SERIES_COLOR.hod} fromOpacity={0.28} toOpacity={0.02} x1="0" y1="0" x2="0" y2="1" />
        <Group left={m.left} top={m.top}>
          <GridRows scale={y} width={iw} numTicks={4} stroke={GRID} strokeOpacity={0.55} />

          {/* HOD = serie protagonista: área cobre + línea */}
          <AreaClosed
            data={lineFor("hod")}
            x={(d) => d.fx}
            y={(d) => d.fy}
            yScale={y}
            curve={curveMonotoneX}
            fill="url(#ma-hod-fill)"
            stroke="transparent"
          />
          <LinePath data={lineFor("pmh")} x={(d) => d.fx} y={(d) => d.fy} curve={curveMonotoneX} stroke={SERIES_COLOR.pmh} strokeWidth={1.5} strokeOpacity={0.85} />
          <LinePath data={lineFor("lod")} x={(d) => d.fx} y={(d) => d.fy} curve={curveMonotoneX} stroke={SERIES_COLOR.lod} strokeWidth={1.5} strokeOpacity={0.85} />
          <LinePath data={lineFor("hod")} x={(d) => d.fx} y={(d) => d.fy} curve={curveMonotoneX} stroke={SERIES_COLOR.hod} strokeWidth={2} />

          {/* guía vertical + puntos en hover */}
          {tooltipOpen && tooltipData && (
            <>
              <Line from={{ x: x(tooltipData.franja) ?? 0, y: 0 }} to={{ x: x(tooltipData.franja) ?? 0, y: ih }} stroke={color.textSecondary} strokeWidth={1} strokeDasharray="3 3" />
              {(["hod", "lod", "pmh"] as const).map((k) => (
                <circle key={k} cx={x(tooltipData.franja) ?? 0} cy={y(tooltipData[k])} r={3} fill={SERIES_COLOR[k]} stroke={color.bgBase} strokeWidth={1.5} />
              ))}
            </>
          )}

          <AxisLeft scale={y} numTicks={4} hideAxisLine tickStroke={GRID} tickFormat={(v) => `${v}%`} tickLabelProps={() => axisLabelProps("end")} />
          <AxisBottom
            scale={x}
            top={ih}
            tickValues={xTicks}
            hideAxisLine
            tickStroke={GRID}
            tickLabelProps={() => ({ ...axisLabelProps("end"), angle: -40, dy: "0.25em", dx: "-0.25em" })}
          />

          <rect width={iw} height={ih} fill="transparent" onMouseMove={onMove} onMouseLeave={hideTooltip} />
        </Group>
      </svg>

      {tooltipOpen && tooltipData && (
        <TooltipWithBounds top={(tooltipTop ?? 0) + 8} left={tooltipLeft ?? 0} style={tooltipStyle}>
          <div style={{ fontWeight: 700, color: color.textHigh, marginBottom: 4 }}>{tooltipData.franja}</div>
          {([["hod", "HOD"], ["lod", "LOD"], ["pmh", "PM High"]] as const).map(([k, lbl]) => (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: SERIES_COLOR[k], display: "inline-block" }} />
              <span style={{ color: color.textMuted, flex: 1 }}>{lbl}</span>
              <span style={{ fontVariantNumeric: "tabular-nums", color: color.textHigh }}>{tooltipData[k].toFixed(1)}%</span>
            </div>
          ))}
        </TooltipWithBounds>
      )}
    </>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  2 · MaeMfeTornado — histograma espejo MAE (izq) / MFE (der)
// ════════════════════════════════════════════════════════════════════════════
type Hist = { buckets: Record<string, number>; p25: number; p50: number; p75: number; mean: number };
type TornadoTip = { bucket: string; side: "MAE" | "MFE"; pct: number };

export function MaeMfeTornado({ mae, mfe, height = 260 }: { mae: Hist; mfe: Hist; height?: number }) {
  const buckets = useMemo(() => {
    const keys = Array.from(new Set([...Object.keys(mae.buckets), ...Object.keys(mfe.buckets)]));
    return keys.sort((a, b) => leadingNum(a) - leadingNum(b));
  }, [mae.buckets, mfe.buckets]);

  return (
    <div style={{ position: "relative", height }}>
      <ParentSize>
        {({ width }) => <TornadoInner width={width} height={height} buckets={buckets} mae={mae} mfe={mfe} />}
      </ParentSize>
    </div>
  );
}

function TornadoInner({
  width,
  height,
  buckets,
  mae,
  mfe,
}: {
  width: number;
  height: number;
  buckets: string[];
  mae: Hist;
  mfe: Hist;
}) {
  const m = { top: 18, right: 8, bottom: 8, left: 8 };
  const gutter = 58;
  const iw = Math.max(0, width - m.left - m.right);
  const ih = Math.max(0, height - m.top - m.bottom);
  const halfW = Math.max(0, (iw - gutter) / 2);

  const yb = useMemo(() => scaleBand<string>({ domain: buckets, range: [0, ih], padding: 0.28 }), [buckets, ih]);
  const maxPct = useMemo(
    () => Math.max(1, ...buckets.map((b) => Math.max(mae.buckets[b] ?? 0, mfe.buckets[b] ?? 0))),
    [buckets, mae.buckets, mfe.buckets],
  );
  // escala compartida → la asimetría riesgo/recorrido se ve de un vistazo
  const sLeft = useMemo(() => scaleLinear<number>({ domain: [0, maxPct], range: [halfW, 0] }), [maxPct, halfW]);
  const sRight = useMemo(() => scaleLinear<number>({ domain: [0, maxPct], range: [0, halfW] }), [maxPct, halfW]);

  const leftX0 = 0;
  const rightX0 = halfW + gutter;
  const bw = yb.bandwidth();

  const { showTooltip, hideTooltip, tooltipData, tooltipLeft, tooltipTop, tooltipOpen } = useTooltip<TornadoTip>();
  const tip = (e: React.MouseEvent, t: TornadoTip) => {
    const p = localPoint(e);
    showTooltip({ tooltipData: t, tooltipLeft: p?.x ?? 0, tooltipTop: p?.y ?? 0 });
  };

  if (iw <= 0) return null;

  return (
    <>
      <svg width={width} height={height}>
        <LinearGradient id="ma-mae-grad" from={color.loss} to={color.loss} fromOpacity={0.95} toOpacity={0.5} x1="1" x2="0" />
        <LinearGradient id="ma-mfe-grad" from={color.copper} to={color.copperBright} fromOpacity={0.95} toOpacity={0.6} x1="0" x2="1" />
        <Group left={m.left} top={m.top}>
          {/* cabeceras de lado */}
          <text x={leftX0 + halfW} y={-6} textAnchor="end" fill={color.loss} fontSize={9} fontFamily={font.sans} fontWeight={700} letterSpacing={1}>MAE · ADVERSO</text>
          <text x={rightX0} y={-6} textAnchor="start" fill={color.copper} fontSize={9} fontFamily={font.sans} fontWeight={700} letterSpacing={1}>MFE · FAVORABLE</text>

          {buckets.map((b) => {
            const yPos = yb(b) ?? 0;
            const maeV = mae.buckets[b] ?? 0;
            const mfeV = mfe.buckets[b] ?? 0;
            const maeW = halfW - sLeft(maeV);
            const mfeW = sRight(mfeV);
            return (
              <Group key={b} top={yPos}>
                <Bar x={leftX0 + sLeft(maeV)} y={0} width={maeW} height={bw} rx={2} fill="url(#ma-mae-grad)"
                  onMouseMove={(e) => tip(e, { bucket: b, side: "MAE", pct: maeV })} onMouseLeave={hideTooltip} />
                <Bar x={rightX0} y={0} width={mfeW} height={bw} rx={2} fill="url(#ma-mfe-grad)"
                  onMouseMove={(e) => tip(e, { bucket: b, side: "MFE", pct: mfeV })} onMouseLeave={hideTooltip} />
                {/* etiqueta de bucket en el canalón central */}
                <text x={leftX0 + halfW + gutter / 2} y={bw / 2} textAnchor="middle" dominantBaseline="middle"
                  fill={color.textSecondary} fontSize={9} fontFamily={font.mono}>{b}</text>
              </Group>
            );
          })}
        </Group>
      </svg>

      {tooltipOpen && tooltipData && (
        <TooltipWithBounds top={tooltipTop} left={tooltipLeft} style={tooltipStyle}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, display: "inline-block", background: tooltipData.side === "MAE" ? color.loss : color.copper }} />
            <span style={{ color: color.textHigh, fontWeight: 700 }}>{tooltipData.side}</span>
            <span style={{ color: color.textMuted }}>· {tooltipData.bucket}</span>
          </div>
          <div style={{ marginTop: 2, color: color.textHigh, fontVariantNumeric: "tabular-nums" }}>{tooltipData.pct.toFixed(1)}% de gappers</div>
        </TooltipWithBounds>
      )}
    </>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  3 · SeasonalityChart — 12 curvas mensuales superpuestas, una resaltada
// ════════════════════════════════════════════════════════════════════════════
type MonthCurve = { month: string; label: string; avg_gap_pct: number; points: { time: string; avg_change: number }[] };
type SeasonTip = { time: string; value: number };

export function SeasonalityChart({
  months,
  highlight,
  height = 260,
}: {
  months: MonthCurve[];
  highlight: string; // month key resaltado
  height?: number;
}) {
  return (
    <div style={{ position: "relative", height }}>
      <ParentSize>
        {({ width }) => <SeasonInner width={width} height={height} months={months} highlight={highlight} />}
      </ParentSize>
    </div>
  );
}

function SeasonInner({ width, height, months, highlight }: { width: number; height: number; months: MonthCurve[]; highlight: string }) {
  const m = { top: 12, right: 14, bottom: 28, left: 38 };
  const iw = Math.max(0, width - m.left - m.right);
  const ih = Math.max(0, height - m.top - m.bottom);

  const sel = months.find((mm) => mm.month === highlight) ?? months[months.length - 1];
  const times = useMemo(() => sel?.points.map((p) => p.time) ?? [], [sel]);

  const x = useMemo(() => scalePoint<string>({ domain: times, range: [0, iw], padding: 0 }), [times, iw]);
  const [yMin, yMax] = useMemo(() => {
    const vals = months.flatMap((mm) => mm.points.map((p) => p.avg_change));
    const lo = Math.min(0, ...vals);
    const hi = Math.max(0, ...vals);
    const pad = (hi - lo) * 0.08 || 1;
    return [lo - pad, hi + pad];
  }, [months]);
  const y = useMemo(() => scaleLinear<number>({ domain: [yMin, yMax], range: [ih, 0] }), [yMin, yMax, ih]);

  const tickEvery = Math.max(1, Math.ceil(times.length / 7));
  const xTicks = times.filter((_, i) => i % tickEvery === 0);

  const { showTooltip, hideTooltip, tooltipData, tooltipLeft, tooltipTop, tooltipOpen } = useTooltip<SeasonTip>();
  const onMove = useCallback(
    (e: React.MouseEvent<SVGRectElement>) => {
      if (!sel) return;
      const px = (localPoint(e)?.x ?? 0) - m.left;
      let nearest = sel.points[0];
      let best = Infinity;
      sel.points.forEach((p) => {
        const d = Math.abs((x(p.time) ?? 0) - px);
        if (d < best) { best = d; nearest = p; }
      });
      showTooltip({ tooltipData: { time: nearest.time, value: nearest.avg_change }, tooltipLeft: (x(nearest.time) ?? 0) + m.left, tooltipTop: y(nearest.avg_change) + m.top });
    },
    [sel, x, y, showTooltip, m.left, m.top],
  );

  if (iw <= 0 || !sel) return null;
  const openX = x("09:30");

  return (
    <>
      <svg width={width} height={height}>
        <Group left={m.left} top={m.top}>
          <GridRows scale={y} width={iw} numTicks={4} stroke={GRID} strokeOpacity={0.5} />
          {/* línea cero */}
          <Line from={{ x: 0, y: y(0) }} to={{ x: iw, y: y(0) }} stroke={color.textMuted} strokeWidth={1} strokeDasharray="2 3" />
          {/* marca apertura 09:30 */}
          {openX != null && (
            <Line from={{ x: openX, y: 0 }} to={{ x: openX, y: ih }} stroke={color.copper} strokeWidth={1} strokeOpacity={0.35} strokeDasharray="3 3" />
          )}

          {/* curvas no seleccionadas, tenues */}
          {months.filter((mm) => mm.month !== sel.month).map((mm) => (
            <LinePath
              key={mm.month}
              data={mm.points}
              x={(p) => x(p.time) ?? 0}
              y={(p) => y(p.avg_change)}
              curve={curveMonotoneX}
              stroke={color.textSecondary}
              strokeWidth={1}
              strokeOpacity={0.16}
            />
          ))}
          {/* curva resaltada */}
          <LinePath data={sel.points} x={(p) => x(p.time) ?? 0} y={(p) => y(p.avg_change)} curve={curveMonotoneX} stroke={color.copper} strokeWidth={2.25} />

          {tooltipOpen && tooltipData && (
            <>
              <Line from={{ x: x(tooltipData.time) ?? 0, y: 0 }} to={{ x: x(tooltipData.time) ?? 0, y: ih }} stroke={color.textSecondary} strokeWidth={1} strokeDasharray="3 3" />
              <circle cx={x(tooltipData.time) ?? 0} cy={y(tooltipData.value)} r={3.5} fill={color.copper} stroke={color.bgBase} strokeWidth={1.5} />
            </>
          )}

          <AxisLeft scale={y} numTicks={4} hideAxisLine tickStroke={GRID} tickFormat={(v) => `${Number(v).toFixed(0)}%`} tickLabelProps={() => axisLabelProps("end")} />
          <AxisBottom scale={x} top={ih} tickValues={xTicks} hideAxisLine tickStroke={GRID} tickLabelProps={() => axisLabelProps("middle")} />

          <rect width={iw} height={ih} fill="transparent" onMouseMove={onMove} onMouseLeave={hideTooltip} />
        </Group>
      </svg>

      {tooltipOpen && tooltipData && (
        <TooltipWithBounds top={tooltipTop} left={tooltipLeft} style={tooltipStyle}>
          <div style={{ fontWeight: 700, color: color.textHigh }}>{sel.label} · {tooltipData.time}</div>
          <div style={{ color: tooltipData.value >= 0 ? color.profit : color.loss, fontVariantNumeric: "tabular-nums", marginTop: 2 }}>
            {tooltipData.value >= 0 ? "+" : ""}{tooltipData.value.toFixed(2)}% vs open
          </div>
        </TooltipWithBounds>
      )}
    </>
  );
}
