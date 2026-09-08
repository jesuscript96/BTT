"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  type IChartApi,
  type CandlestickData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { createSeriesMarkers } from "lightweight-charts";
import { Ruler, Tag } from "lucide-react";
import type { CandleData, TradeRecord, EquityPoint, MultiDayCandles, Strategy } from "@/lib/api_backtester";
import {
  getIndicatorDef,
  createDefaultParams,
  type ActiveIndicator,
} from "@/lib/indicatorRegistry";
import IndicatorDropdown from "./IndicatorDropdown";
import {
  calculateSMA,
  calculateEMA,
  calculateWMA,
  calculateVWAP,
  calculateLinearRegression,
  calculateZigZag,
  calculateIchimoku,
  calculateParabolicSAR,
  calculateDonchian,
  calculateDarvasBoxes,
  calculateBollingerBands,
  calculateOpeningRange,
  calculateRSI,
  calculateStochastic,
  calculateMomentum,
  calculateCCI,
  calculateROC,
  calculateMACD,
  calculateDMI,
  calculateWilliamsR,
  calculateADX,
  calculateATR,
  calculateOBV,
  calculateAccDist,
  calculateVolume,
  calculateRVOL,
  calculateAccumulatedVolume,
  calculateAccumDollarVolume,
  calculateDollarVolume,
  calculateSqueeze,
  calculateSessionFade,
  calculateFade,
  calculateHeikinAshi,
} from "@/lib/indicators";

/**
 * Acciones legibles en las marcas del grafico.
 *
 * Antes se pintaba con `toFixed(0)` y una posicion fraccionaria salia como
 * "+0", que parecia que el añadido NO se habia ejecutado. Ocurre en cuanto el
 * riesgo por operacion es pequeño frente al precio: 1 $ sobre una accion de
 * 12 $ son 0,083 acciones — reales y compradas, pero invisibles al redondear.
 * Se muestran mas decimales cuanto menor es la cantidad.
 */
function fmtShares(n: number): string {
  const a = Math.abs(n);
  if (!Number.isFinite(n)) return "0";
  if (a >= 100) return n.toFixed(0);
  if (a >= 10) return n.toFixed(1);
  if (a >= 1) return n.toFixed(2);
  return n.toFixed(3);
}

// ---------------------------------------------------------------------------
// Color palettes for multi-instance indicators
// ---------------------------------------------------------------------------
const OVERLAY_PALETTES: Record<string, string[]> = {
  SMA: ["#f59e0b", "#d97706", "#b45309", "#78350f", "#92400e", "#451a03"],
  EMA: ["#a855f7", "#9333ea", "#7e22ce", "#581c87", "#6b21a8", "#4c1d95"],
  WMA: ["#f97316", "#ea580c", "#c2410c", "#9a3412", "#7c2d12", "#431407"],
  LINEAR_REGRESSION: ["#84cc16", "#65a30d", "#4d7c0f", "#3f6212"],
  RSI: ["#3b82f6", "#2563eb", "#1d4ed8", "#1e3a8a"],
  ATR: ["#8b5cf6", "#7c3aed", "#6d28d9", "#4c1d95"],
  MOMENTUM: ["#10b981", "#059669", "#047857", "#065f46"],
  CCI: ["#ec4899", "#db2777", "#be185d", "#9d174d"],
  ROC: ["#ef4444", "#dc2626", "#b91c1c", "#991b1b"],
  WILLIAMS_R: ["#f97316", "#ea580c", "#c2410c", "#9a3412"],
  ADX: ["#14b8a6", "#0d9488", "#0f766e", "#115e59"],
};

function getSeriesColor(indicatorId: string, instanceIndex: number): string {
  const palette = OVERLAY_PALETTES[indicatorId];
  if (palette) return palette[instanceIndex % palette.length];
  return ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6"][instanceIndex % 5];
}

// ---------------------------------------------------------------------------
// Candle aggregation (frontend-only, no backend changes)
// ---------------------------------------------------------------------------
type Timeframe = "1m" | "5m" | "15m" | "30m" | "1h";
const TIMEFRAME_MINUTES: Record<Timeframe, number> = { "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60 };

function aggregateCandles(candles: CandleData[], tf: Timeframe): CandleData[] {
  if (tf === "1m" || candles.length === 0) return candles;
  const minutes = TIMEFRAME_MINUTES[tf];
  const buckets = new Map<number, CandleData[]>();
  for (const c of candles) {
    // Round down to nearest bucket boundary (epoch seconds)
    const bucketKey = Math.floor(c.time / (minutes * 60)) * (minutes * 60);
    if (!buckets.has(bucketKey)) buckets.set(bucketKey, []);
    buckets.get(bucketKey)!.push(c);
  }
  const result: CandleData[] = [];
  for (const [bucketTime, group] of buckets) {
    result.push({
      time: bucketTime,
      open: group[0].open,
      high: Math.max(...group.map(c => c.high)),
      low: Math.min(...group.map(c => c.low)),
      close: group[group.length - 1].close,
      volume: group.reduce((sum, c) => sum + c.volume, 0),
    });
  }
  return result.sort((a, b) => a.time - b.time);
}

/** Find the closest candle time for a given epoch timestamp */
function snapToCandle(epoch: number, candleTimes: number[]): number | null {
  if (candleTimes.length === 0) return null;
  let best = candleTimes[0];
  let bestDist = Math.abs(epoch - best);
  for (const t of candleTimes) {
    const d = Math.abs(epoch - t);
    if (d < bestDist) { best = t; bestDist = d; }
  }
  return best;
}

// ---------------------------------------------------------------------------
// Props & Component
// ---------------------------------------------------------------------------
interface ChartProps {
  candles: CandleData[];
  multiDayCandles?: MultiDayCandles | null;
  activeStrategy?: Strategy | null;
  trades: TradeRecord[];
  equity: EquityPoint[];
  ticker: string;
  date: string;
}

/** Volumen de la vela y acumulados del día, sobre la franja del histograma.
 *
 *  V   volumen de la vela donde está el cursor
 *  AV  volumen acumulado del día hasta ahí
 *  ADV dollar volume acumulado — Σ(precio × volumen) barra a barra, que es la
 *      cuenta del motor para `Accumulated Dollar Volume`, NO Σvolumen × último
 *      precio (con el precio moviéndose no es lo mismo).
 *
 *  SIN CURSOR ENSEÑA LOS TOTALES DEL DÍA, no guiones: si hubiera que barrer
 *  con el ratón hasta el final solo para saber cuánto se movió el día, la
 *  etiqueta no serviría de nada al abrir el gráfico.
 */
function EtiquetaVolumen({ acum, totales }: {
  acum: { v: number; av: number; adv: number } | null;
  totales: { av: number; adv: number } | null;
}) {
  if (!acum && !totales) return null;
  const n = (x: number) => x.toLocaleString("es-ES", { maximumFractionDigits: 0 });
  const money = (x: number) =>
    x >= 1e9 ? `${(x / 1e9).toFixed(2)} B`
      : x >= 1e6 ? `${(x / 1e6).toFixed(2)} M`
        : x >= 1e3 ? `${(x / 1e3).toFixed(1)} K`
          : n(x);
  const av = acum ? acum.av : totales!.av;
  const adv = acum ? acum.adv : totales!.adv;

  const Dato = ({ etiqueta, valor, tono }: { etiqueta: string; valor: string; tono?: string }) => (
    <span style={{ display: "inline-flex", gap: 5, alignItems: "baseline" }}>
      {/* La sigla más pequeña y apagada que el número: es la referencia, no el
          dato. Si pesaran igual, la fila se leería como texto en vez de como
          una lectura de instrumento. */}
      <span style={{ color: "var(--color-ec-text-muted)", fontSize: 10, fontWeight: 700, letterSpacing: "0.5px" }}>
        {etiqueta}
      </span>
      <b style={{ color: tono || "var(--color-ec-text-primary)", fontWeight: 600, fontSize: 12 }}>{valor}</b>
    </span>
  );

  return (
    // A LA ALTURA DEL EJE X, ocupando su grosor. La franja del eje temporal de
    // `lightweight-charts` mide 26-28 px y está vacía a la izquierda (las
    // primeras marcas de hora empiezan más adentro), así que la etiqueta cabe
    // ahí sin tapar nada y se lee en la misma línea que las horas — que es
    // donde el ojo ya está mirando cuando recorre el gráfico.
    //
    // Sin fondo ni borde: al ir sobre el eje y no sobre las velas, una caja
    // flotando ahí parecería un elemento pegado por encima.
    <div style={{
      position: "absolute", left: 10, bottom: 1, height: 24,
      pointerEvents: "none", zIndex: 3,
      display: "flex", gap: 16, alignItems: "center",
      // FONDO OPACO, no traslúcido. Va sobre el eje temporal, y las horas de
      // detrás son texto del mismo cuerpo y del mismo gris: con transparencia
      // los dígitos se solapaban y no se leía ni una cosa ni la otra.
      padding: "0 10px",
      background: "var(--color-ec-bg-base)",
      border: "0.5px solid var(--color-ec-border)",
      borderRadius: 2,
      fontFamily: "var(--color-ec-mono)", fontSize: 12,
      whiteSpace: "nowrap",
    }}>
      {acum
        ? <Dato etiqueta="V" valor={n(acum.v)} />
        : <span style={{ color: "var(--color-ec-text-muted)", fontSize: 10, fontWeight: 700, letterSpacing: "0.5px" }}>DÍA</span>}
      <Dato etiqueta="AV" valor={n(av)} />
      <Dato etiqueta="ADV" valor={`$${money(adv)}`} tono="var(--color-ec-copper)" />
    </div>
  );
}

export default function Chart({
  candles,
  multiDayCandles = null,
  activeStrategy = null,
  trades,
  equity,
  ticker,
  date,
}: ChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>("1m");
  const aggregatedCandles = useMemo(() => aggregateCandles(candles, timeframe), [candles, timeframe]);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const panelContainerRef = useRef<HTMLDivElement>(null);

  // Refs for multi-chart view
  const chartContainerRef1 = useRef<HTMLDivElement>(null);
  const panelContainerRef1 = useRef<HTMLDivElement>(null);
  const chartContainerRef2 = useRef<HTMLDivElement>(null);
  const panelContainerRef2 = useRef<HTMLDivElement>(null);
  const chartContainerRef3 = useRef<HTMLDivElement>(null);
  const panelContainerRef3 = useRef<HTMLDivElement>(null);

  const [multiDayEnabled, setMultiDayEnabled] = useState(false);

  // ── Regla de medición (estilo TradingView) ─────────────────────────────
  // Con la regla activada, arrastrar sobre el gráfico mide Δprecio/Δ% y nº
  // de velas entre dos puntos (clic para borrar). El render del chart no
  // depende del toggle: los handlers leen el ref y el gráfico no se
  // reconstruye al activarla.
  const [measureEnabled, setMeasureEnabled] = useState(false);
  /** Si los marcadores llevan su texto ("L $4,12", "+$83 (TP)"…) o solo el
   *  símbolo. Con muchas entradas los textos se pisan unos a otros y tapan las
   *  velas; apagarlos deja ver dónde entró y salió sin perder el gráfico. */
  const [datosEntradas, setDatosEntradas] = useState(true);
  const datosEntradasRef = useRef(true);
  /** Los marcadores tal cual se calcularon, CON su texto. Se guardan para poder
   *  repintarlos al pulsar el botón sin rehacer el gráfico entero — rehacerlo
   *  perdería el zoom y la posición, que es justo lo que estás mirando cuando
   *  decides quitar el texto porque no se lee. */
  const marcadoresRef = useRef<any[]>([]);
  const markersApiRef = useRef<any>(null);
  /** Volumen y dollar volume ACUMULADOS del día hasta donde está el cursor.
   *  Etiqueta fija sobre la franja de volumen: no se pinta uno por vela (eso
   *  sería ilegible) sino un solo par de números que cambia al mover el ratón. */
  const [acum, setAcum] = useState<{ v: number; av: number; adv: number } | null>(null);
  /** Totales del día. Es lo que se enseña cuando el cursor NO está sobre el
   *  gráfico: dejar guiones obligaría a barrer con el ratón solo para saber
   *  cuánto se movió el día. */
  const [totales, setTotales] = useState<{ av: number; adv: number } | null>(null);
  const measureEnabledRef = useRef(false);
  const measureClearFnsRef = useRef<Array<() => void>>([]);
  const dayChartsRef = useRef<IChartApi[]>([]);

  const applyDay = useMemo(() => {
    if (activeStrategy?.definition && typeof activeStrategy.definition === 'object') {
      const def = activeStrategy.definition as any;
      if (def.apply_day) {
        return def.apply_day as string;
      }
    }
    if (activeStrategy && typeof activeStrategy === 'object') {
      const s = activeStrategy as any;
      if (s.apply_day) {
        return s.apply_day as string;
      }
    }
    return "gap_day";
  }, [activeStrategy]);

  const swingActive = useMemo(() => {
    const rm = (activeStrategy?.definition?.risk_management || (activeStrategy as any)?.risk_management) as any;
    return rm?.swing_option?.active || false;
  }, [activeStrategy]);

  const swingTargetDay = useMemo(() => {
    const rm = (activeStrategy?.definition?.risk_management || (activeStrategy as any)?.risk_management) as any;
    return rm?.swing_option?.target_day || "gap_1_day";
  }, [activeStrategy]);

  const isMultiView = useMemo(() => {
    const isMultiEnabled = applyDay === "gap_1_day" || applyDay === "gap_2_day" || swingActive;
    return multiDayEnabled && !!multiDayCandles && isMultiEnabled;
  }, [multiDayEnabled, multiDayCandles, applyDay, swingActive]);

  const chartRef = useRef<IChartApi | null>(null);
  const subChartsRef = useRef<IChartApi[]>([]);

  // ---------------------------------------------------------------------------
  // Persistent indicator state
  // ---------------------------------------------------------------------------
  const [activeIndicators, setActiveIndicators] = useState<ActiveIndicator[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const saved = window.localStorage.getItem("chart_active_indicators_v2");
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("chart_active_indicators_v2", JSON.stringify(activeIndicators));
    }
  }, [activeIndicators]);

  // Handlers
  const handleAdd = useCallback((indicatorId: string) => {
    const def = getIndicatorDef(indicatorId);
    if (!def) return;

    const existing = activeIndicators.filter(a => a.indicatorId === indicatorId);
    if (!def.multi && existing.length > 0) {
      // Toggle off
      setActiveIndicators(prev => prev.filter(a => a.indicatorId !== indicatorId));
      return;
    }

    setActiveIndicators(prev => [
      ...prev,
      {
        indicatorId,
        instanceId: Math.random().toString(36).substring(2, 9),
        params: createDefaultParams(def),
      },
    ]);
  }, [activeIndicators]);

  const handleAddInstance = useCallback((indicatorId: string) => {
    const def = getIndicatorDef(indicatorId);
    if (!def) return;
    setActiveIndicators(prev => [
      ...prev,
      {
        indicatorId,
        instanceId: Math.random().toString(36).substring(2, 9),
        params: createDefaultParams(def),
      },
    ]);
  }, []);

  const handleRemove = useCallback((instanceId: string) => {
    setActiveIndicators(prev => prev.filter(a => a.instanceId !== instanceId));
  }, []);

  const handleUpdateParam = useCallback((instanceId: string, paramName: string, value: number) => {
    setActiveIndicators(prev =>
      prev.map(a =>
        a.instanceId === instanceId
          ? { ...a, params: { ...a.params, [paramName]: value } }
          : a
      )
    );
  }, []);

  // Compute panels needed
  const panelIndicators = activeIndicators.filter(a => {
    const def = getIndicatorDef(a.indicatorId);
    return def && def.displayMode === "panel";
  });
  // Group panel indicators by type (same type shares a panel if multi)
  const panelGroups: { indicatorId: string; instances: ActiveIndicator[] }[] = [];
  const panelMap = new Map<string, ActiveIndicator[]>();
  for (const pi of panelIndicators) {
    if (!panelMap.has(pi.indicatorId)) panelMap.set(pi.indicatorId, []);
    panelMap.get(pi.indicatorId)!.push(pi);
  }
  for (const [id, insts] of panelMap) panelGroups.push({ indicatorId: id, instances: insts });

  // ---------------------------------------------------------------------------
  // Chart rendering effect
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Cleanup of any active charts
    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
    for (const sc of subChartsRef.current) { try { sc.remove(); } catch {} }
    subChartsRef.current = [];
    dayChartsRef.current = [];
    measureClearFnsRef.current = [];
    const cleanupFns: Array<() => void> = [];

    const activeCharts: IChartApi[] = [];
    const activeSubCharts: IChartApi[] = [];

    const renderChartInstance = (
      container: HTMLDivElement | null,
      panelContainer: HTMLDivElement | null,
      dayCandlesList: CandleData[],
      dayTrades: TradeRecord[],
      dayEquity: EquityPoint[],
      showTrades: boolean,
      dayDateStr?: string
    ) => {
      if (!container || dayCandlesList.length === 0) return null;

      const dayAggregated = aggregateCandles(dayCandlesList, timeframe);
      const sorted = [...dayAggregated].sort((a, b) => a.time - b.time);
      const deduped = sorted.filter((c, i) => i === 0 || c.time !== sorted[i - 1].time);

      if (deduped.length === 0) return null;

      const candleData: CandlestickData<Time>[] = deduped.map(c => ({
        time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close,
      }));

      // Create main chart
      const chart = createChart(container, {
        width: container.clientWidth,
        height: 400,
        layout: { background: { type: ColorType.Solid, color: "#16181A" }, textColor: "#ffffff" },
        grid: { vertLines: { color: "#2C2F33" }, horzLines: { color: "#2C2F33" } },
        crosshair: { mode: 0 },
        rightPriceScale: { borderColor: "#2C2F33" },
        timeScale: { borderColor: "#2C2F33", timeVisible: true, secondsVisible: false },
        // Con la regla activada, el arrastre mide en vez de desplazar el
        // eje temporal (la regla re-aplica esto al alternarla).
        handleScroll: { pressedMouseMove: !measureEnabledRef.current },
        handleScale: { axisPressedMouseMove: !measureEnabledRef.current },
      });
      activeCharts.push(chart);
      dayChartsRef.current.push(chart);

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981", downColor: "#ef4444",
        borderDownColor: "#ef4444", borderUpColor: "#10b981",
        wickDownColor: "#ef4444", wickUpColor: "#10b981",
      });
      candleSeries.setData(candleData);

      // ACUMULADOS DEL DÍA, precalculados. Se recorren una vez aquí en vez de
      // sumar en cada movimiento del ratón: con un día de premercado son cientos
      // de velas y el crosshair dispara muchas veces por segundo.
      //
      // El dollar volume es Σ(precio × volumen) barra a barra, NO
      // (Σvolumen × último precio): con el precio moviéndose no es lo mismo, y
      // es la misma cuenta que usa el motor para `Accumulated Dollar Volume`.
      {
        const porTiempo = new Map<number, { v: number; av: number; adv: number }>();
        let av = 0, adv = 0;
        for (const c of deduped) {
          av += c.volume;
          adv += c.close * c.volume;
          porTiempo.set(c.time as number, { v: c.volume, av, adv });
        }
        setTotales({ av, adv });
        chart.subscribeCrosshairMove((param: any) => {
          const t = param?.time;
          if (t == null) { setAcum(null); return; }
          // El `time` puede llegar como número o como objeto de fecha según la
          // escala; se prueban los dos antes de rendirse.
          setAcum(porTiempo.get(t as number)
            ?? porTiempo.get(Number(t))
            ?? null);
        });
      }

      // Volume on main chart
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" }, priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      volumeSeries.setData(deduped.map(c => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)",
      })));

      // ── Regla de medición (estilo TradingView) ─────────────────────────
      // Overlay propio sobre el contenedor + conversión de coordenadas con
      // la API del chart. Sin la regla activada los handlers son no-op y el
      // gráfico se comporta como siempre.
      {
        const overlay = document.createElement("div");
        overlay.style.cssText =
          "position:absolute;inset:0;pointer-events:none;z-index:20;overflow:hidden;";
        const box = document.createElement("div");
        box.style.cssText =
          "position:absolute;display:none;border:1px solid #3b82f6;background:rgba(59,130,246,0.13);";
        const label = document.createElement("div");
        label.style.cssText =
          "position:absolute;display:none;white-space:nowrap;background:#16181A;border:1px solid #3b82f6;" +
          "border-radius:4px;padding:4px 8px;font:600 11px/1.5 sans-serif;color:#e5e7eb;pointer-events:none;";
        overlay.appendChild(box);
        overlay.appendChild(label);
        const prevPosition = container.style.position;
        container.style.position = "relative";
        container.appendChild(overlay);

        const times = deduped.map(c => c.time as number);
        const xToTime = (x: number): number => {
          const t = chart.timeScale().coordinateToTime(x) as number | null;
          if (t !== null && t !== undefined) return t;
          // Fuera del rango de datos: clamp a la primera/última vela.
          const first = chart.timeScale().timeToCoordinate(times[0] as Time);
          const last = chart.timeScale().timeToCoordinate(times[times.length - 1] as Time);
          if (first === null || last === null) return times[0];
          return x < (first as number) ? times[0] : times[times.length - 1];
        };
        const nearestIdx = (t: number) => {
          let lo = 0, hi = times.length - 1;
          while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (times[mid] < t) lo = mid + 1; else hi = mid;
          }
          if (lo > 0 && Math.abs(times[lo - 1] - t) < Math.abs(times[lo] - t)) return lo - 1;
          return lo;
        };

        let drag: { x: number; y: number; time: number; price: number } | null = null;
        let frozen = false;

        const clear = () => {
          box.style.display = "none";
          label.style.display = "none";
          frozen = false;
        };
        measureClearFnsRef.current.push(clear);

        const fmtPrice = (v: number) => {
          const a = Math.abs(v);
          if (a >= 100) return v.toFixed(2);
          if (a >= 1) return v.toFixed(3);
          return v.toFixed(4);
        };

        const renderMeasure = (end: { x: number; y: number; time: number; price: number }) => {
          if (!drag) return;
          const x1 = Math.min(drag.x, end.x), x2 = Math.max(drag.x, end.x);
          const y1 = Math.min(drag.y, end.y), y2 = Math.max(drag.y, end.y);
          box.style.display = "block";
          box.style.left = `${x1}px`;
          box.style.top = `${y1}px`;
          box.style.width = `${Math.max(x2 - x1, 1)}px`;
          box.style.height = `${Math.max(y2 - y1, 1)}px`;

          const dp = end.price - drag.price;
          const dpct = drag.price !== 0 ? (dp / drag.price) * 100 : 0;
          const bars = Math.abs(nearestIdx(end.time) - nearestIdx(drag.time));
          const mins = Math.round(Math.abs(end.time - drag.time) / 60);
          const dur = mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins}m`;
          const up = dp >= 0;
          label.style.display = "block";
          label.style.color = up ? "#10b981" : "#ef4444";
          label.innerHTML =
            `${up ? "+" : ""}${fmtPrice(dp)} (${up ? "+" : ""}${dpct.toFixed(2)}%)` +
            `<span style="color:#9ca3af">&nbsp;&nbsp;${bars} velas · ${dur}</span>`;
          // Pegada a la esquina superior del rectángulo, sin salirse del chart.
          label.style.left = `${Math.max(Math.min(x1 + 6, container.clientWidth - 190), 4)}px`;
          label.style.top = `${Math.max(y1 - 22, 2)}px`;
        };

        const pointFrom = (e: MouseEvent) => {
          const rect = container.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;
          const price = candleSeries.coordinateToPrice(y);
          return {
            x, y,
            time: xToTime(x),
            price: price === null ? (drag?.price ?? deduped[deduped.length - 1].close) : price,
          };
        };

        const onDown = (e: MouseEvent) => {
          if (!measureEnabledRef.current || e.button !== 0) return;
          clear(); // un clic también borra la medición congelada anterior
          drag = pointFrom(e);
        };
        const onMove = (e: MouseEvent) => {
          if (!measureEnabledRef.current || !drag || frozen) return;
          renderMeasure(pointFrom(e));
        };
        const onUp = () => {
          if (!drag) return;
          frozen = true; // queda fija hasta el próximo clic/arrastre
          drag = null;
        };

        container.addEventListener("mousedown", onDown);
        container.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);

        cleanupFns.push(() => {
          container.removeEventListener("mousedown", onDown);
          container.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          overlay.remove();
          container.style.position = prevPosition;
        });
      }

      // Trade markers (snap to nearest aggregated candle time)
      if (showTrades && dayTrades.length > 0) {
        const candleTimes = deduped.map(c => c.time as number);
        const candleTimeSet = new Set(candleTimes);

        interface RawMarker {
          time: number;
          position: "aboveBar" | "belowBar";
          color: string;
          shape: "circle" | "square" | "arrowUp" | "arrowDown";
          text: string;
          isEntry: boolean;
        }

        const rawMarkers: RawMarker[] = [];
        for (const t of dayTrades) {
          const entryDate = t.entry_time.split(" ")[0];
          const exitDate = t.exit_time.split(" ")[0];

          if (dayDateStr) {
            // Only add entry marker if entryDate matches dayDateStr
            if (entryDate === dayDateStr) {
              const entrySnap = snapToCandle(t.entry_time_epoch, candleTimes);
              if (entrySnap && candleTimeSet.has(entrySnap)) {
                const isLong = t.direction.toLowerCase().includes("long");
                rawMarkers.push({
                  time: entrySnap,
                  position: isLong ? "belowBar" : "aboveBar",
                  color: isLong ? "#10b981" : "#ef4444",
                  shape: isLong ? "arrowUp" : "arrowDown",
                  text: `${isLong ? "L" : "S"} $${t.entry_price.toFixed(2)}`,
                  isEntry: true,
                });
              }
            }

            // Only add exit marker if exitDate matches dayDateStr
            if (exitDate === dayDateStr && t.status === "Closed") {
              const exitSnap = snapToCandle(t.exit_time_epoch, candleTimes);
              if (exitSnap && candleTimeSet.has(exitSnap)) {
                rawMarkers.push({
                  time: exitSnap,
                  position: "aboveBar",
                  color: t.pnl >= 0 ? "#10b981" : "#ef4444",
                  shape: "circle",
                  text: `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)} (${t.exit_reason})`,
                  isEntry: false,
                });
              }
            }
          } else {
            const entrySnap = snapToCandle(t.entry_time_epoch, candleTimes);
            const exitSnap = snapToCandle(t.exit_time_epoch, candleTimes);

            if (entrySnap && candleTimeSet.has(entrySnap) && Math.abs(t.entry_time_epoch - entrySnap) < 43200) {
              const isLong = t.direction.toLowerCase().includes("long");
              rawMarkers.push({
                time: entrySnap,
                position: isLong ? "belowBar" : "aboveBar",
                color: isLong ? "#10b981" : "#ef4444",
                shape: isLong ? "arrowUp" : "arrowDown",
                text: `${isLong ? "L" : "S"} $${t.entry_price.toFixed(2)}`,
                isEntry: true,
              });
            }
            if (exitSnap && candleTimeSet.has(exitSnap) && t.status === "Closed" && Math.abs(t.exit_time_epoch - exitSnap) < 43200) {
              rawMarkers.push({
                time: exitSnap,
                position: "aboveBar",
                color: t.pnl >= 0 ? "#10b981" : "#ef4444",
                shape: "circle",
                text: `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)} (${t.exit_reason})`,
                isEntry: false,
              });
            }
          }

          // --- Ejecuciones intermedias -------------------------------------
          // Añadidos y reducciones de piramidación y take profits parciales.
          // La entrada y el cierre final ya llevan su marcador arriba, así que
          // aquí solo se pinta lo que ocurre EN MEDIO — que antes era
          // invisible: un `add` no genera trade propio y la fusión de legs se
          // llevaba por delante los parciales.
          for (const ex of (t.executions || [])) {
            if (ex.kind === "entry") continue;
            if (ex.time_epoch === t.exit_time_epoch) continue; // es el cierre
            // El mismo criterio de día que la entrada y la salida (comparar
            // fechas UTC aquí desalinearía el día de sesión); y `snapToCandle`
            // descarta solo lo que no caiga en una vela del gráfico.
            if (dayDateStr && entryDate !== dayDateStr && exitDate !== dayDateStr) continue;
            const snap = snapToCandle(ex.time_epoch, candleTimes);
            if (!snap || !candleTimeSet.has(snap)) continue;
            const isAdd = ex.kind === "add";
            const isLong = t.direction.toLowerCase().includes("long");
            rawMarkers.push({
              time: snap,
              position: isAdd ? (isLong ? "belowBar" : "aboveBar") : "aboveBar",
              // Cobre para los añadidos (aumentan la posición) y ámbar para
              // las salidas parciales, para no confundirlos con la entrada ni
              // con el cierre.
              color: isAdd ? "#c87941" : "#d9a441",
              shape: isAdd ? (isLong ? "arrowUp" : "arrowDown") : "square",
              text: isAdd
                ? `+${fmtShares(ex.size ?? 0)} @ $${ex.price.toFixed(2)}`
                : `−${fmtShares(ex.size ?? 0)} @ $${ex.price.toFixed(2)}${ex.label ? ` (${ex.label})` : ""}`,
              isEntry: false,
            });
          }
        }

        // Group markers by time
        const grouped = new Map<number, RawMarker[]>();
        for (const m of rawMarkers) {
          if (!grouped.has(m.time)) {
            grouped.set(m.time, []);
          }
          grouped.get(m.time)!.push(m);
        }

        const markers: SeriesMarker<Time>[] = [];
        for (const [time, group] of grouped) {
          if (group.length === 1) {
            const m = group[0];
            markers.push({
              time: m.time as unknown as Time,
              position: m.position,
              color: m.color,
              shape: m.shape,
              text: m.text,
            });
          } else {
            // Sort: entries before exits
            group.sort((a, b) => (a.isEntry ? 0 : 1) - (b.isEntry ? 0 : 1));

            const combinedText = group.map(m => m.text).join(" | ");

            const firstColor = group[0].color;
            const allSameColor = group.every(m => m.color === firstColor);
            const mergedColor = allSameColor ? firstColor : "var(--color-ec-copper)";

            const firstShape = group[0].shape;
            const allSameShape = group.every(m => m.shape === firstShape);
            const mergedShape = allSameShape ? firstShape : "square";

            // If there's an entry, use its position. Otherwise, default to aboveBar
            const entryMarker = group.find(m => m.isEntry);
            const mergedPosition = entryMarker ? entryMarker.position : "aboveBar";

            markers.push({
              time: time as unknown as Time,
              position: mergedPosition,
              color: mergedColor,
              shape: mergedShape,
              text: combinedText,
            });
          }
        }

        markers.sort((a, b) => (a.time as number) - (b.time as number));
        // Con el botón «Datos» apagado los marcadores van SIN texto: los
        // símbolos se quedan —hay que seguir viendo dónde entró y salió— pero
        // el texto desaparece, que es lo que se pisa cuando hay muchas
        // operaciones seguidas y acaba tapando las velas.
        marcadoresRef.current = markers;
        markersApiRef.current = createSeriesMarkers(
          candleSeries,
          datosEntradasRef.current ? markers : markers.map(m => ({ ...m, text: "" })),
        );

        // Líneas del Stop Loss de cada trade del día: discontinuas, en rojo
        // y con el precio en el eje. Antes el SL solo existía en la tabla y
        // no podía verse sobre las velas (p. ej. para comprobar de un vistazo
        // que el nivel queda en el lado correcto de la entrada).
        for (const t of dayTrades) {
          if (!t.stop_loss || t.stop_loss <= 0) continue;
          const tEntryDate = t.entry_time.split(" ")[0];
          const tExitDate = t.exit_time.split(" ")[0];
          if (dayDateStr && tEntryDate !== dayDateStr && tExitDate !== dayDateStr) continue;
          candleSeries.createPriceLine({
            price: t.stop_loss,
            color: "#ef4444",
            lineWidth: 1,
            lineStyle: 2, // discontinua
            axisLabelVisible: true,
            title: "SL",
          });
        }
      }

      // ========== OVERLAY INDICATORS ==========
      const overlayIndicators = activeIndicators.filter(a => {
        const def = getIndicatorDef(a.indicatorId);
        return def && def.displayMode === "overlay";
      });

      const overlayCounters: Record<string, number> = {};

      for (const ai of overlayIndicators) {
        const idx = overlayCounters[ai.indicatorId] ?? 0;
        overlayCounters[ai.indicatorId] = idx + 1;
        const color = getSeriesColor(ai.indicatorId, idx);

        switch (ai.indicatorId) {
          case "SMA": {
            const d = calculateSMA(deduped, ai.params.period ?? 20);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "EMA": {
            const d = calculateEMA(deduped, ai.params.period ?? 20);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "WMA": {
            const d = calculateWMA(deduped, ai.params.period ?? 20);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "VWAP": {
            const d = calculateVWAP(deduped);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color: "#d4a017", lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "LINEAR_REGRESSION": {
            const d = calculateLinearRegression(deduped, ai.params.period ?? 14);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "ZIGZAG": {
            const d = calculateZigZag(deduped, ai.params.reversal ?? 5);
            if (d.length > 1) { const s = chart.addSeries(LineSeries, { color: "#e11d48", lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "ICHIMOKU": {
            const d = calculateIchimoku(deduped, ai.params.tenkan ?? 9, ai.params.kijun ?? 26, ai.params.senkou_b ?? 52);
            if (d.length > 0) {
              const cloudSeries = chart.addSeries(CandlestickSeries, {
                upColor: "rgba(16, 185, 129, 0.15)",
                downColor: "rgba(239, 68, 68, 0.15)",
                borderVisible: false,
                wickVisible: false,
                lastValueVisible: false,
                priceLineVisible: false,
              });
              const cloudData = d.filter(p => p.senkouA !== null && p.senkouB !== null).map(p => ({
                time: p.time,
                open: p.senkouA!,
                close: p.senkouB!,
                high: Math.max(p.senkouA!, p.senkouB!),
                low: Math.min(p.senkouA!, p.senkouB!),
              }));
              cloudSeries.setData(cloudData);

              const tenkanData = d.filter(p => p.tenkan !== null).map(p => ({ time: p.time, value: p.tenkan! }));
              if (tenkanData.length) { chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 1 }).setData(tenkanData); }
              const kijunData = d.filter(p => p.kijun !== null).map(p => ({ time: p.time, value: p.kijun! }));
              if (kijunData.length) { chart.addSeries(LineSeries, { color: "#dc2626", lineWidth: 1 }).setData(kijunData); }
              const senkouAData = d.filter(p => p.senkouA !== null).map(p => ({ time: p.time, value: p.senkouA! }));
              if (senkouAData.length) { chart.addSeries(LineSeries, { color: "rgba(16, 185, 129, 0.5)", lineWidth: 1 }).setData(senkouAData); }
              const senkouBData = d.filter(p => p.senkouB !== null).map(p => ({ time: p.time, value: p.senkouB! }));
              if (senkouBData.length) { chart.addSeries(LineSeries, { color: "rgba(239, 68, 68, 0.5)", lineWidth: 1 }).setData(senkouBData); }
              const chikouData = d.filter(p => p.chikou !== null).map(p => ({ time: p.time, value: p.chikou! }));
              if (chikouData.length) { chart.addSeries(LineSeries, { color: "#7c3aed", lineWidth: 1, lineStyle: 2 }).setData(chikouData); }
            }
            break;
          }
          case "PARABOLIC_SAR": {
            const d = calculateParabolicSAR(deduped, ai.params.minAF ?? 0.02, ai.params.maxAF ?? 0.2);
            if (d.length > 0) {
              const s = chart.addSeries(LineSeries, {
                color: "transparent", lineWidth: 1,
                pointMarkersVisible: true, pointMarkersRadius: 2,
                lastValueVisible: false, priceLineVisible: false,
              });
              s.setData(d.map(p => ({ ...p, color: "#06b6d4" })));
            }
            break;
          }
          case "DONCHIAN": {
            const d = calculateDonchian(deduped, ai.params.period ?? 20);
            if (d.length > 0) {
              const sU = chart.addSeries(LineSeries, { color: "#0ea5e9", lineWidth: 1 });
              sU.setData(d.map(p => ({ time: p.time, value: p.upper })));
              const sL = chart.addSeries(LineSeries, { color: "#0ea5e9", lineWidth: 1 });
              sL.setData(d.map(p => ({ time: p.time, value: p.lower })));
              const sM = chart.addSeries(LineSeries, { color: "#0ea5e9", lineWidth: 1, lineStyle: 2 });
              sM.setData(d.map(p => ({ time: p.time, value: p.middle })));
            }
            break;
          }
          case "DARVAS": {
            // El RECTANGULO COMPLETO de cada caja, desde la vela cuyo maximo es
            // el techo (el pico) hasta la vela que la rompe con su cierre.
            //
            // Dos tonos con significado:
            //   - ATENUADO  (origen -> consolidacion): la caja en formacion. El
            //     techo ya esta puesto pero el suelo aun se esta buscando; solo
            //     se conoce a posteriori, y el motor NO emite nivel ahi (seria
            //     lookahead). Es seguro pintarlo: durante la formacion el precio
            //     nunca sale de los niveles (un maximo por encima cancela la
            //     caja y un minimo por debajo desplaza el suelo), asi que aqui
            //     no puede haber ninguna señal que el motor "se pierda".
            //   - SOLIDO (consolidacion -> ruptura): la caja operativa. Como
            //     dentro de la caja los cierres no salen, LA SEÑAL ES SIEMPRE
            //     EL BORDE DERECHO del tramo solido: la vela que la mata.
            //
            // Cada linea son DOS puntos al mismo nivel -> horizontal y estatica
            // por construccion. Una serie por tramo: el primer intento uso una
            // sola serie con "whitespace" y lightweight-charts NO corta la
            // linea en el whitespace (solo reserva el hueco en el eje), asi que
            // los techos de todas las cajas salian unidos en diagonal.
            const boxes = calculateDarvasBoxes(deduped, ai.params.period ?? 3);
            const solido = {
              color: "#f59e0b", lineWidth: 2 as const,
              lastValueVisible: false, priceLineVisible: false,
            };
            const tenue = { ...solido, color: "rgba(245, 158, 11, 0.35)" };
            for (const b of boxes) {
              for (const nivel of [b.upper, b.lower]) {
                if (b.consolidated !== b.from) {
                  const f = chart.addSeries(LineSeries, tenue);
                  f.setData([{ time: b.from, value: nivel }, { time: b.consolidated, value: nivel }]);
                }
                const a = chart.addSeries(LineSeries, solido);
                a.setData([{ time: b.consolidated, value: nivel }, { time: b.to, value: nivel }]);
              }
            }
            break;
          }
          case "BOLLINGER": {
            const d = calculateBollingerBands(deduped, ai.params.period ?? 20, ai.params.stdDev ?? 2);
            if (d.length > 0) {
              const sU = chart.addSeries(LineSeries, { color: "#6366f1", lineWidth: 1 });
              sU.setData(d.map(p => ({ time: p.time, value: p.upper })));
              const sL = chart.addSeries(LineSeries, { color: "#6366f1", lineWidth: 1 });
              sL.setData(d.map(p => ({ time: p.time, value: p.lower })));
              const sM = chart.addSeries(LineSeries, { color: "#6366f1", lineWidth: 1, lineStyle: 2 });
              sM.setData(d.map(p => ({ time: p.time, value: p.middle })));
            }
            break;
          }
          case "OPENING_RANGE": {
            const d = calculateOpeningRange(deduped, ai.params.minutes ?? 5);
            if (d.length > 0) {
              const sU = chart.addSeries(LineSeries, { color: "#d946ef", lineWidth: 1 });
              sU.setData(d.map(p => ({ time: p.time, value: p.upper })));
              const sL = chart.addSeries(LineSeries, { color: "#d946ef", lineWidth: 1 });
              sL.setData(d.map(p => ({ time: p.time, value: p.lower })));
            }
            break;
          }
        }
      }

      // ========== PANEL SUB-CHARTS ==========
      const createSubChart = (containerDiv: HTMLDivElement, height: number = 120): IChartApi => {
        const subChart = createChart(containerDiv, {
          width: containerDiv.clientWidth, height,
          layout: { background: { type: ColorType.Solid, color: "#16181A" }, textColor: "#ffffff", fontSize: 10 },
          grid: { vertLines: { color: "#2C2F33" }, horzLines: { color: "#2C2F33" } },
          crosshair: { mode: 0 },
          rightPriceScale: { borderColor: "#2C2F33" },
          timeScale: { borderColor: "#2C2F33", timeVisible: true, secondsVisible: false, visible: false },
        });
        chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
          if (range) subChart.timeScale().setVisibleLogicalRange(range);
        });
        subChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
          if (range) chart.timeScale().setVisibleLogicalRange(range);
        });
        activeSubCharts.push(subChart);
        return subChart;
      };

      if (panelContainer) {
        panelContainer.innerHTML = "";

        const panelIndicators = activeIndicators.filter(a => {
          const def = getIndicatorDef(a.indicatorId);
          return def && def.displayMode === "panel";
        });

        const panelGroups: { indicatorId: string; instances: ActiveIndicator[] }[] = [];
        const panelMap = new Map<string, ActiveIndicator[]>();
        for (const pi of panelIndicators) {
          if (!panelMap.has(pi.indicatorId)) panelMap.set(pi.indicatorId, []);
          panelMap.get(pi.indicatorId)!.push(pi);
        }
        for (const [id, insts] of panelMap) panelGroups.push({ indicatorId: id, instances: insts });

        for (const group of panelGroups) {
          const def = getIndicatorDef(group.indicatorId);
          if (!def) continue;

          const wrapper = document.createElement("div");
          wrapper.className = "border-t border-[var(--color-ec-border)]";

          const label = document.createElement("div");
          label.className = "px-3 py-0.5 bg-[var(--color-ec-bg-sidebar)] text-[10px] font-semibold text-[var(--color-ec-text-muted)] tracking-wider";
          label.textContent = def.label + " " + group.instances.map(i => {
            const paramStr = def.params.map(p => i.params[p.name]).join(",");
            return paramStr ? `(${paramStr})` : "";
          }).join(" ");
          wrapper.appendChild(label);

          const chartDiv = document.createElement("div");
          chartDiv.style.width = "100%";
          chartDiv.style.height = "120px";
          wrapper.appendChild(chartDiv);
          panelContainer.appendChild(wrapper);

          const subChart = createSubChart(chartDiv);
          let instanceIdx = 0;

          for (const inst of group.instances) {
            const clr = getSeriesColor(inst.indicatorId, instanceIdx++);

            switch (inst.indicatorId) {
              case "RSI": {
                const d = calculateRSI(deduped, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  if (instanceIdx === 1) {
                    s.createPriceLine({ price: 70, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
                    s.createPriceLine({ price: 30, color: "#10b981", lineWidth: 1, lineStyle: 2 });
                  }
                }
                break;
              }
              case "STOCHASTIC": {
                const d = calculateStochastic(deduped, inst.params.kPeriod ?? 14, inst.params.dPeriod ?? 3, inst.params.dSlow ?? 3);
                if (d.length > 0) {
                  const sK = subChart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 2 });
                  sK.setData(d.map(p => ({ time: p.time, value: p.k })));
                  const sD = subChart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1 });
                  sD.setData(d.map(p => ({ time: p.time, value: p.d })));
                  if (instanceIdx === 1) {
                    sK.createPriceLine({ price: 80, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
                    sK.createPriceLine({ price: 20, color: "#10b981", lineWidth: 1, lineStyle: 2 });
                  }
                }
                break;
              }
              case "MOMENTUM": {
                const d = calculateMomentum(deduped, inst.params.period ?? 10);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "CCI": {
                const d = calculateCCI(deduped, inst.params.period ?? 20);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 100, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
                  s.createPriceLine({ price: -100, color: "#10b981", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ROC": {
                const d = calculateROC(deduped, inst.params.period ?? 12);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "MACD": {
                const d = calculateMACD(deduped, inst.params.fast ?? 12, inst.params.slow ?? 26, inst.params.signal ?? 9);
                if (d.length > 0) {
                  const sM = subChart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 2 });
                  sM.setData(d.map(p => ({ time: p.time, value: p.macd })));
                  const sS = subChart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1 });
                  sS.setData(d.map(p => ({ time: p.time, value: p.signal })));
                  const sH = subChart.addSeries(HistogramSeries, {});
                  sH.setData(d.map(p => ({
                    time: p.time, value: p.histogram,
                    color: p.histogram >= 0 ? "rgba(16,185,129,0.5)" : "rgba(239,68,68,0.5)",
                  })));
                }
                break;
              }
              case "DMI": {
                const d = calculateDMI(deduped, inst.params.diPeriod ?? 14, inst.params.adxPeriod ?? 14);
                if (d.length > 0) {
                  const sP = subChart.addSeries(LineSeries, { color: "#16a34a", lineWidth: 2 });
                  sP.setData(d.map(p => ({ time: p.time, value: p.plusDI })));
                  const sM = subChart.addSeries(LineSeries, { color: "#dc2626", lineWidth: 2 });
                  sM.setData(d.map(p => ({ time: p.time, value: p.minusDI })));
                  const sA = subChart.addSeries(LineSeries, { color: "#6366f1", lineWidth: 1, lineStyle: 2 });
                  sA.setData(d.map(p => ({ time: p.time, value: p.adx })));
                }
                break;
              }
              case "WILLIAMS_R": {
                const d = calculateWilliamsR(deduped, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: -20, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
                  s.createPriceLine({ price: -80, color: "#10b981", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ADX": {
                const d = calculateADX(deduped, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 25, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ATR": {
                const d = calculateATR(deduped, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "OBV": {
                const d = calculateOBV(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "VOL_AD": {
                const d = calculateAccDist(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#84cc16", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "VOLUME": {
                const d = calculateVolume(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(HistogramSeries, { priceFormat: { type: "volume" } });
                  s.setData(d);
                }
                break;
              }
              case "RVOL": {
                const d = calculateRVOL(deduped, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 1, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ACCUMULATED_VOLUME": {
                const d = calculateAccumulatedVolume(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#10b981", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "ACCUM_DOLLAR_VOLUME": {
                const d = calculateAccumDollarVolume(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#0ea5e9", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "DOLLAR_VOLUME": {
                const d = calculateDollarVolume(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(HistogramSeries, { color: "#38bdf8" });
                  s.setData(d);
                }
                break;
              }
              case "SQUEEZE": {
                // Se pinta CON SIGNO (+ sube, - baja) y con una linea en 0:
                // asi se ve de un vistazo hacia donde fue el disparo. En las
                // condiciones el desplegable de direccion lo devuelve siempre
                // en positivo, que es el mismo numero con el signo cambiado.
                const d = calculateSqueeze(deduped, inst.params.minutes ?? 5);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#c026d3", lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              // Los fades se pintan con la linea del 0: por encima es caida y
              // por debajo es que el precio esta sobre la referencia, que es
              // justo lo que se quiere ver de un vistazo.
              case "SESSION_FADE_PM":
              case "SESSION_FADE_RTH":
              case "SESSION_FADE_FULL": {
                const d = calculateSessionFade(
                  deduped,
                  inst.indicatorId === "SESSION_FADE_RTH" ? "rth"
                    : inst.indicatorId === "SESSION_FADE_FULL" ? "full" : "pm",
                );
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#f97316", lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "FADE_PREV_MAX":
              case "FADE_VWAP": {
                const d = calculateFade(
                  deduped, inst.indicatorId === "FADE_VWAP" ? "vwap_cross" : "previous_max",
                );
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#e11d48", lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "HEIKIN_ASHI": {
                const d = calculateHeikinAshi(deduped);
                if (d.length > 0) {
                  const s = subChart.addSeries(CandlestickSeries, {
                    upColor: "#10b981", downColor: "#ef4444",
                    borderDownColor: "#ef4444", borderUpColor: "#10b981",
                    wickDownColor: "#ef4444", wickUpColor: "#10b981",
                  });
                  s.setData(d.map(p => ({
                    time: p.time, open: p.open, high: p.high, low: p.low, close: p.close,
                  })));
                }
                break;
              }
            }
          }
          subChart.timeScale().fitContent();
        }
      }

      chart.timeScale().fitContent();
      return chart;
    };

    // Render single or multiple charts depending on isMultiView
    if (isMultiView && multiDayCandles) {
      if (multiDayCandles.gap_day?.candles) {
        renderChartInstance(
          chartContainerRef1.current,
          panelContainerRef1.current,
          multiDayCandles.gap_day.candles,
          trades,
          equity,
          true,
          multiDayCandles.gap_day.date
        );
      }

      const showPanel2 = applyDay === "gap_1_day" || applyDay === "gap_2_day" || swingActive;
      if (showPanel2 && multiDayCandles.gap_1_day?.candles) {
        renderChartInstance(
          chartContainerRef2.current,
          panelContainerRef2.current,
          multiDayCandles.gap_1_day.candles,
          trades,
          equity,
          true,
          multiDayCandles.gap_1_day.date
        );
      }

      const showPanel3 = applyDay === "gap_2_day" || (swingActive && swingTargetDay === "gap_2_day");
      if (showPanel3 && multiDayCandles.gap_2_day?.candles) {
        renderChartInstance(
          chartContainerRef3.current,
          panelContainerRef3.current,
          multiDayCandles.gap_2_day.candles,
          trades,
          equity,
          true,
          multiDayCandles.gap_2_day.date
        );
      }
    } else {
      if (candles && candles.length > 0) {
        const mainChart = renderChartInstance(
          chartContainerRef.current,
          panelContainerRef.current,
          candles,
          trades,
          equity,
          true,
          date
        );
        if (mainChart) chartRef.current = mainChart;
      }
    }

    // Resize handler
    const handleResize = () => {
      for (const c of activeCharts) {
        if (isMultiView) {
          if (chartContainerRef1.current && activeCharts[0] === c) c.applyOptions({ width: chartContainerRef1.current.clientWidth });
          if (chartContainerRef2.current && activeCharts[1] === c) c.applyOptions({ width: chartContainerRef2.current.clientWidth });
          if (chartContainerRef3.current && activeCharts[2] === c) c.applyOptions({ width: chartContainerRef3.current.clientWidth });
        } else {
          if (chartContainerRef.current) c.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      }
      for (const sc of activeSubCharts) {
        if (isMultiView) {
          if (chartContainerRef1.current) sc.applyOptions({ width: chartContainerRef1.current.clientWidth });
        } else {
          if (chartContainerRef.current) sc.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      for (const fn of cleanupFns) fn();
      window.removeEventListener("resize", handleResize);
      for (const sc of activeSubCharts) { try { sc.remove(); } catch {} }
      for (const c of activeCharts) { try { c.remove(); } catch {} }
      chartRef.current = null;
    };
  }, [candles, trades, equity, activeIndicators, timeframe, isMultiView, multiDayCandles, applyDay, ticker, date, swingActive, swingTargetDay]);

  // Botón «Datos»: repinta los marcadores con o sin texto, en el sitio.
  useEffect(() => {
    datosEntradasRef.current = datosEntradas;
    const api = markersApiRef.current;
    const ms = marcadoresRef.current;
    if (!api || !ms.length) return;
    api.setMarkers(datosEntradas ? ms : ms.map((m: any) => ({ ...m, text: "" })));
  }, [datosEntradas]);

  // Toggle de la regla: sincroniza el ref, cambia el cursor y hace que el
  // arrastre mida (en vez de desplazar la escala) mientras esté activa.
  useEffect(() => {
    measureEnabledRef.current = measureEnabled;
    for (const c of dayChartsRef.current) {
      c.applyOptions({
        handleScroll: { pressedMouseMove: !measureEnabled },
        handleScale: { axisPressedMouseMove: !measureEnabled },
      });
    }
    for (const cont of [chartContainerRef, chartContainerRef1, chartContainerRef2, chartContainerRef3]) {
      if (cont.current) cont.current.style.cursor = measureEnabled ? "crosshair" : "";
    }
    if (!measureEnabled) {
      for (const clear of measureClearFnsRef.current) clear();
    }
  }, [measureEnabled]);

  return (
    <div className="bg-[var(--card-bg)] rounded-lg border border-[var(--border)] overflow-hidden" style={{ marginTop: 24 }}>

      {/* TOOLBAR */}
      <div 
        style={{
          padding: '4px 12px 4px 24px',
          borderBottom: '1px solid var(--color-ec-border)',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          backgroundColor: 'var(--color-ec-bg-sidebar)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={{ fontWeight: 700, fontSize: '18px', color: 'var(--color-ec-text-high)' }}>{ticker}</span>
          <span style={{ fontSize: '13px', color: 'var(--color-ec-text-primary)' }}>{date}</span>
          {(() => {
            const entryLogic = (activeStrategy?.definition as any)?.entry_logic;
            const windows = entryLogic?.entry_time_windows;
            if (windows && windows.length > 0) {
              return (
                <span style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  backgroundColor: 'rgba(216, 122, 61, 0.12)',
                  color: 'var(--color-ec-copper)',
                  padding: '2px 8px',
                  borderRadius: 4,
                  border: '0.5px solid rgba(216, 122, 61, 0.3)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4
                }}>
                  ⏱️ Horas Entrada: {windows.map((w: any) => `${w.from_time}-${w.to_time}`).join(", ")}
                </span>
              );
            }
            return null;
          })()}
          <div 
            style={{ 
              display: 'flex', 
              gap: '3px', 
              backgroundColor: 'var(--color-ec-bg-surface)', 
              border: '1px solid var(--color-ec-border)', 
              borderRadius: '5px', 
              padding: '2px 3px' 
            }}
          >
            {(["1m", "5m", "15m", "30m", "1h"] as Timeframe[]).map(tf => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                style={{
                  fontSize: '11px',
                  padding: '3px 8px',
                  borderRadius: '3px',
                  fontWeight: 500,
                  border: 'none',
                  cursor: 'pointer',
                  backgroundColor: timeframe === tf ? 'var(--color-ec-copper)' : 'transparent',
                  color: timeframe === tf ? '#fff' : 'var(--color-ec-text-secondary)',
                  transition: 'all 150ms ease',
                }}
              >
                {tf}
              </button>
            ))}
          </div>
          <button
            onClick={() => setMeasureEnabled(v => !v)}
            title="Regla: arrastra sobre el gráfico para medir Δ$ y Δ% entre dos puntos. Clic para borrar la medición."
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '3px 10px',
              height: '26px',
              backgroundColor: measureEnabled ? 'var(--color-ec-copper)' : 'transparent',
              border: '1.5px solid var(--color-ec-border)',
              borderRadius: 5,
              fontSize: 10,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: measureEnabled ? '#fff' : 'var(--color-ec-text-secondary)',
              cursor: 'pointer',
              transition: 'all 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (!measureEnabled) e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
            }}
            onMouseLeave={(e) => {
              if (!measureEnabled) e.currentTarget.style.borderColor = 'var(--color-ec-border)';
            }}
          >
            <Ruler size={12} /> Regla
          </button>
          <button
            onClick={() => setDatosEntradas(v => !v)}
            title="Muestra u oculta el texto de cada operación (precio de entrada, PnL, motivo de salida). Los símbolos de entrada, salida y pirámide se quedan siempre."
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '3px 10px',
              height: '26px',
              backgroundColor: datosEntradas ? 'var(--color-ec-copper)' : 'transparent',
              border: '1.5px solid var(--color-ec-border)',
              borderRadius: 5,
              fontSize: 10,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: datosEntradas ? '#fff' : 'var(--color-ec-text-secondary)',
              cursor: 'pointer',
              transition: 'all 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (!datosEntradas) e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
            }}
            onMouseLeave={(e) => {
              if (!datosEntradas) e.currentTarget.style.borderColor = 'var(--color-ec-border)';
            }}
          >
            <Tag size={12} /> Datos
          </button>
          {(applyDay === "gap_1_day" || applyDay === "gap_2_day" || swingActive) && (
            <button
              onClick={() => setMultiDayEnabled(!multiDayEnabled)}
              style={{
                padding: '5px 12px',
                height: '30px',
                backgroundColor: multiDayEnabled ? 'var(--color-ec-copper)' : 'transparent',
                border: '1.5px solid var(--color-ec-border)',
                borderRadius: 5,
                fontSize: 10,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: multiDayEnabled ? '#fff' : 'var(--color-ec-text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                transition: 'all 150ms ease',
              }}
              onMouseEnter={(e) => {
                if (!multiDayEnabled) e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
              }}
              onMouseLeave={(e) => {
                if (!multiDayEnabled) e.currentTarget.style.borderColor = 'var(--color-ec-border)';
              }}
            >
              <span>{multiDayEnabled ? "Vista Simple" : (swingActive ? "Ver Días Swing" : "Comparar GAPs")}</span>
            </button>
          )}
        </div>

        <IndicatorDropdown
          activeIndicators={activeIndicators}
          onAdd={handleAdd}
          onRemove={handleRemove}
          onAddInstance={handleAddInstance}
          onUpdateParam={handleUpdateParam}
        />
      </div>

      {/* CHART CONTAINERS */}
      {!isMultiView ? (
        <>
          {/* La etiqueta va DENTRO del contenedor, abajo a la izquierda: ahí
              está la franja del volumen (el histograma ocupa el 15 % inferior)
              y no tapa ni las velas ni los marcadores. `pointerEvents: none`
              para no robarle el ratón al gráfico. */}
          <div style={{ position: "relative", width: "100%" }}>
            <div ref={chartContainerRef} style={{ width: "100%", height: "400px" }} />
            <EtiquetaVolumen acum={acum} totales={totales} />
          </div>
          <div ref={panelContainerRef} />
        </>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'row', gap: 0, width: '100%', borderTop: '1px solid var(--color-ec-border)' }}>
          {/* Panel 1: Gap Day */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <div style={{ padding: '6px 12px', backgroundColor: 'var(--color-ec-bg-sidebar)', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', borderBottom: '1px solid var(--color-ec-border)', fontFamily: 'var(--color-ec-sans)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Día del Gap ({multiDayCandles?.gap_day?.date || ""})
            </div>
            {/* Solo en el primer panel: los tres charts comparten el mismo
                estado de acumulados, asi que repetirla en los otros dos
                enseñaria el mismo numero tres veces. */}
            <div style={{ position: "relative", width: "100%" }}>
              <div ref={chartContainerRef1} style={{ width: "100%", height: "400px" }} />
              <EtiquetaVolumen acum={acum} totales={totales} />
            </div>
            <div ref={panelContainerRef1} />
          </div>

          {/* Panel 2: GAP +1 Day */}
          {(applyDay === "gap_1_day" || applyDay === "gap_2_day" || swingActive) && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderLeft: '1px solid var(--color-ec-border)' }}>
              <div style={{ padding: '6px 12px', backgroundColor: 'var(--color-ec-bg-sidebar)', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', borderBottom: '1px solid var(--color-ec-border)', fontFamily: 'var(--color-ec-sans)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                {applyDay === "gap_2_day" ? "Día GAP + 1" : "Día del Trade (GAP + 1)"} ({multiDayCandles?.gap_1_day?.date || ""})
              </div>
              <div ref={chartContainerRef2} style={{ width: "100%", height: "400px" }} />
              <div ref={panelContainerRef2} />
            </div>
          )}

          {/* Panel 3: GAP +2 Day */}
          {(applyDay === "gap_2_day" || (swingActive && swingTargetDay === "gap_2_day")) && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderLeft: '1px solid var(--color-ec-border)' }}>
              <div style={{ padding: '6px 12px', backgroundColor: 'var(--color-ec-bg-sidebar)', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', borderBottom: '1px solid var(--color-ec-border)', fontFamily: 'var(--color-ec-sans)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Día del Trade (GAP + 2) ({multiDayCandles?.gap_2_day?.date || ""})
              </div>
              <div ref={chartContainerRef3} style={{ width: "100%", height: "400px" }} />
              <div ref={panelContainerRef3} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

