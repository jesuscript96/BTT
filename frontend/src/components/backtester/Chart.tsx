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
  calculateHeikinAshi,
} from "@/lib/indicators";

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
type Timeframe = "1m" | "5m" | "15m" | "1h";
const TIMEFRAME_MINUTES: Record<Timeframe, number> = { "1m": 1, "5m": 5, "15m": 15, "1h": 60 };

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

  const applyDay = useMemo(() => {
    if (activeStrategy?.definition && typeof activeStrategy.definition === 'object') {
      const def = activeStrategy.definition as any;
      if (def.apply_day) {
        return def.apply_day as string;
      }
    }
    return "gap_day";
  }, [activeStrategy]);

  const isMultiView = useMemo(() => {
    return multiDayEnabled && !!multiDayCandles && (applyDay === "gap_1_day" || applyDay === "gap_2_day");
  }, [multiDayEnabled, multiDayCandles, applyDay]);

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

    const activeCharts: IChartApi[] = [];
    const activeSubCharts: IChartApi[] = [];

    const renderChartInstance = (
      container: HTMLDivElement | null,
      panelContainer: HTMLDivElement | null,
      dayCandlesList: CandleData[],
      dayTrades: TradeRecord[],
      dayEquity: EquityPoint[],
      showTrades: boolean
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
      });
      activeCharts.push(chart);

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981", downColor: "#ef4444",
        borderDownColor: "#ef4444", borderUpColor: "#10b981",
        wickDownColor: "#ef4444", wickUpColor: "#10b981",
      });
      candleSeries.setData(candleData);

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

      // Trade markers (snap to nearest aggregated candle time)
      if (showTrades && dayTrades.length > 0) {
        const candleTimes = deduped.map(c => c.time as number);
        const candleTimeSet = new Set(candleTimes);

        const markers: SeriesMarker<Time>[] = [];
        const entryTimeSet = new Set<string>();
        for (const t of dayTrades) {
          const entrySnap = timeframe === "1m" ? t.entry_time_epoch : snapToCandle(t.entry_time_epoch, candleTimes);
          const exitSnap = timeframe === "1m" ? t.exit_time_epoch : snapToCandle(t.exit_time_epoch, candleTimes);

          if (entrySnap && candleTimeSet.has(entrySnap)) {
            const entryKey = `${entrySnap}`;
            if (!entryTimeSet.has(entryKey)) {
              entryTimeSet.add(entryKey);
              const isLong = t.direction.toLowerCase().includes("long");
              markers.push({
                time: entrySnap as unknown as Time,
                position: isLong ? "belowBar" : "aboveBar",
                color: isLong ? "#10b981" : "#ef4444",
                shape: isLong ? "arrowUp" : "arrowDown",
                text: `${isLong ? "L" : "S"} $${t.entry_price.toFixed(2)}`,
              });
            }
          }
          if (exitSnap && candleTimeSet.has(exitSnap) && t.status === "Closed") {
            markers.push({
              time: exitSnap as unknown as Time,
              position: "aboveBar",
              color: t.pnl >= 0 ? "#10b981" : "#ef4444",
              shape: "circle",
              text: `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)} (${t.exit_reason})`,
            });
          }
        }
        markers.sort((a, b) => (a.time as number) - (b.time as number));
        createSeriesMarkers(candleSeries, markers);
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
            const d = calculateSMA(dayCandlesList, ai.params.period ?? 20);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "EMA": {
            const d = calculateEMA(dayCandlesList, ai.params.period ?? 20);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "WMA": {
            const d = calculateWMA(dayCandlesList, ai.params.period ?? 20);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "VWAP": {
            const d = calculateVWAP(dayCandlesList);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color: "#d4a017", lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "LINEAR_REGRESSION": {
            const d = calculateLinearRegression(dayCandlesList, ai.params.period ?? 14);
            if (d.length > 0) { const s = chart.addSeries(LineSeries, { color, lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "ZIGZAG": {
            const d = calculateZigZag(dayCandlesList, ai.params.reversal ?? 5);
            if (d.length > 1) { const s = chart.addSeries(LineSeries, { color: "#e11d48", lineWidth: 2 }); s.setData(d); }
            break;
          }
          case "ICHIMOKU": {
            const d = calculateIchimoku(dayCandlesList, ai.params.tenkan ?? 9, ai.params.kijun ?? 26, ai.params.senkou_b ?? 52);
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
            const d = calculateParabolicSAR(dayCandlesList, ai.params.minAF ?? 0.02, ai.params.maxAF ?? 0.2);
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
            const d = calculateDonchian(dayCandlesList, ai.params.period ?? 20);
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
          case "BOLLINGER": {
            const d = calculateBollingerBands(dayCandlesList, ai.params.period ?? 20, ai.params.stdDev ?? 2);
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
            const d = calculateOpeningRange(dayCandlesList, ai.params.minutes ?? 5);
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
                const d = calculateRSI(dayCandlesList, inst.params.period ?? 14);
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
                const d = calculateStochastic(dayCandlesList, inst.params.kPeriod ?? 14, inst.params.dPeriod ?? 3, inst.params.dSlow ?? 3);
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
                const d = calculateMomentum(dayCandlesList, inst.params.period ?? 10);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "CCI": {
                const d = calculateCCI(dayCandlesList, inst.params.period ?? 20);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 100, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
                  s.createPriceLine({ price: -100, color: "#10b981", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ROC": {
                const d = calculateROC(dayCandlesList, inst.params.period ?? 12);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 0, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "MACD": {
                const d = calculateMACD(dayCandlesList, inst.params.fast ?? 12, inst.params.slow ?? 26, inst.params.signal ?? 9);
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
                const d = calculateDMI(dayCandlesList, inst.params.diPeriod ?? 14, inst.params.adxPeriod ?? 14);
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
                const d = calculateWilliamsR(dayCandlesList, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: -20, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
                  s.createPriceLine({ price: -80, color: "#10b981", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ADX": {
                const d = calculateADX(dayCandlesList, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 25, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ATR": {
                const d = calculateATR(dayCandlesList, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: clr, lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "OBV": {
                const d = calculateOBV(dayCandlesList);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "VOL_AD": {
                const d = calculateAccDist(dayCandlesList);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#84cc16", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "VOLUME": {
                const d = calculateVolume(dayCandlesList);
                if (d.length > 0) {
                  const s = subChart.addSeries(HistogramSeries, { priceFormat: { type: "volume" } });
                  s.setData(d);
                }
                break;
              }
              case "RVOL": {
                const d = calculateRVOL(dayCandlesList, inst.params.period ?? 14);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2 });
                  s.setData(d);
                  s.createPriceLine({ price: 1, color: "#9ca3af", lineWidth: 1, lineStyle: 2 });
                }
                break;
              }
              case "ACCUMULATED_VOLUME": {
                const d = calculateAccumulatedVolume(dayCandlesList);
                if (d.length > 0) {
                  const s = subChart.addSeries(LineSeries, { color: "#10b981", lineWidth: 2 });
                  s.setData(d);
                }
                break;
              }
              case "HEIKIN_ASHI": {
                const d = calculateHeikinAshi(dayCandlesList);
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
          [],
          [],
          false
        );
      }

      if (applyDay === "gap_1_day") {
        if (multiDayCandles.gap_1_day?.candles) {
          renderChartInstance(
            chartContainerRef2.current,
            panelContainerRef2.current,
            multiDayCandles.gap_1_day.candles,
            trades,
            equity,
            true
          );
        }
      } else if (applyDay === "gap_2_day") {
        if (multiDayCandles.gap_1_day?.candles) {
          renderChartInstance(
            chartContainerRef2.current,
            panelContainerRef2.current,
            multiDayCandles.gap_1_day.candles,
            [],
            [],
            false
          );
        }
        if (multiDayCandles.gap_2_day?.candles) {
          renderChartInstance(
            chartContainerRef3.current,
            panelContainerRef3.current,
            multiDayCandles.gap_2_day.candles,
            trades,
            equity,
            true
          );
        }
      }
    } else {
      if (candles && candles.length > 0) {
        const mainChart = renderChartInstance(
          chartContainerRef.current,
          panelContainerRef.current,
          candles,
          trades,
          equity,
          true
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
      window.removeEventListener("resize", handleResize);
      for (const sc of activeSubCharts) { try { sc.remove(); } catch {} }
      for (const c of activeCharts) { try { c.remove(); } catch {} }
      chartRef.current = null;
    };
  }, [candles, trades, equity, activeIndicators, timeframe, isMultiView, multiDayCandles, applyDay, ticker, date]);

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
            {(["1m", "5m", "15m", "1h"] as Timeframe[]).map(tf => (
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
          {(applyDay === "gap_1_day" || applyDay === "gap_2_day") && (
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
              <span>{multiDayEnabled ? "Vista Simple" : "Comparar GAPs"}</span>
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
          <div ref={chartContainerRef} style={{ width: "100%", height: "400px" }} />
          <div ref={panelContainerRef} />
        </>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'row', gap: 0, width: '100%', borderTop: '1px solid var(--color-ec-border)' }}>
          {/* Panel 1: Gap Day */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <div style={{ padding: '6px 12px', backgroundColor: 'var(--color-ec-bg-sidebar)', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', borderBottom: '1px solid var(--color-ec-border)', fontFamily: 'var(--color-ec-sans)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Día del Gap ({multiDayCandles?.gap_day?.date || ""})
            </div>
            <div ref={chartContainerRef1} style={{ width: "100%", height: "400px" }} />
            <div ref={panelContainerRef1} />
          </div>

          {/* Panel 2: GAP +1 Day */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderLeft: '1px solid var(--color-ec-border)' }}>
            <div style={{ padding: '6px 12px', backgroundColor: 'var(--color-ec-bg-sidebar)', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', borderBottom: '1px solid var(--color-ec-border)', fontFamily: 'var(--color-ec-sans)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              {applyDay === "gap_2_day" ? "Día GAP + 1" : "Día del Trade (GAP + 1)"} ({multiDayCandles?.gap_1_day?.date || ""})
            </div>
            <div ref={chartContainerRef2} style={{ width: "100%", height: "400px" }} />
            <div ref={panelContainerRef2} />
          </div>

          {/* Panel 3: GAP +2 Day */}
          {applyDay === "gap_2_day" && (
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

