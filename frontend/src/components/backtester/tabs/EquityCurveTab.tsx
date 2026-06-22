"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import {
  createChart,
  AreaSeries,
  HistogramSeries,
  BaselineSeries,
  LineSeries,
  LineStyle,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { GlobalEquityPoint, DrawdownPoint, TradeRecord, AggregateMetrics } from "@/lib/api_backtester";
import OOSDegradationTab from "./OOSDegradationTab";
import InfoTooltip from "../InfoTooltip";

function computeR2FromEquity(eqPoints: any[]): number {
  const N = eqPoints.length;
  if (N < 3) return 0;
  
  const y = eqPoints.map(p => p.value);
  
  const meanX = (N + 1) / 2;
  let sumY = 0;
  for (let i = 0; i < N; i++) sumY += y[i];
  const meanY = sumY / N;
  
  let num = 0;
  let denX = 0;
  for (let i = 0; i < N; i++) {
    const x = i + 1;
    num += (x - meanX) * (y[i] - meanY);
    denX += (x - meanX) * (x - meanX);
  }
  
  if (denX === 0) return 0;
  const slope = num / denX;
  const intercept = meanY - slope * meanX;
  
  let ssRes = 0;
  let ssTot = 0;
  for (let i = 0; i < N; i++) {
    const x = i + 1;
    const pred = slope * x + intercept;
    ssRes += Math.pow(y[i] - pred, 2);
    ssTot += Math.pow(y[i] - meanY, 2);
  }
  
  if (ssTot === 0) return 0;
  const r2 = 1 - (ssRes / ssTot);
  return Math.max(0, r2);
}

function computeKRatio(trades: any[]): number {
  const N = trades.length;
  if (N < 3) return 0;
  
  let accum = 0;
  const y: number[] = [];
  for (let i = 0; i < N; i++) {
    accum += (trades[i].r_multiple ?? 0);
    y.push(accum);
  }
  
  const meanX = (N + 1) / 2;
  let sumY = 0;
  for (let i = 0; i < N; i++) sumY += y[i];
  const meanY = sumY / N;
  
  let num = 0;
  let den = 0;
  for (let i = 0; i < N; i++) {
    const x = i + 1;
    num += (x - meanX) * (y[i] - meanY);
    den += (x - meanX) * (x - meanX);
  }
  
  if (den === 0) return 0;
  const slope = num / den;
  const intercept = meanY - slope * meanX;
  
  let sumSquares = 0;
  for (let i = 0; i < N; i++) {
    const x = i + 1;
    const pred = slope * x + intercept;
    sumSquares += (y[i] - pred) * (y[i] - pred);
  }
  
  const standardError = Math.sqrt(sumSquares / (N - 2));
  if (standardError === 0 || isNaN(standardError)) return 0;
  
  return (slope * Math.sqrt(N)) / standardError;
}

function computeSQN(trades: any[]): number {
  const N = trades.length;
  if (N === 0) return 0;
  
  const rMultiples = trades.map(t => t.r_multiple ?? 0);
  const sumR = rMultiples.reduce((s, r) => s + r, 0);
  const meanR = sumR / N;
  
  if (N < 2) return 0;
  
  const sumSquares = rMultiples.reduce((s, r) => s + Math.pow(r - meanR, 2), 0);
  const variance = sumSquares / (N - 1);
  const stdR = Math.sqrt(variance);
  
  if (stdR === 0) return 0;
  
  return (meanR / stdR) * Math.sqrt(N);
}

interface EquityCurveTabProps {
  globalEquity: GlobalEquityPoint[];
  globalDrawdown: DrawdownPoint[];
  trades: any[];
  metrics: Record<string, any> | null;
  initCash: number;
  riskR: number;
  monthlyExpenses?: number;
  isDarkMode?: boolean;
  isPercent: number;
  fullGlobalEquity: GlobalEquityPoint[];
  fullGlobalDrawdown: DrawdownPoint[];
  fullTrades: any[];
  riskType?: string;
}

export default function EquityCurveTab({
  globalEquity,
  globalDrawdown,
  trades,
  metrics,
  initCash,
  riskR,
  monthlyExpenses,
  isDarkMode = false,
  isPercent,
  fullGlobalEquity,
  fullGlobalDrawdown,
  fullTrades,
  riskType = "FIXED",
}: EquityCurveTabProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef = useRef<HTMLDivElement>(null);
  const ddLabelRef = useRef<HTMLDivElement>(null);
  const ddLineStartRef = useRef<HTMLDivElement>(null);
  const ddLineEndRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const ddChartRef = useRef<IChartApi | null>(null);

  type ViewMode = "$" | "%" | "R";
  const [viewMode, setViewMode] = useState<ViewMode>("$");

  const getRValue = (val: number) => {
    if (riskType === "PERCENT") {
      const ratio = Math.max(0.0001, val / initCash);
      const ln_base = Math.log(1 + riskR / 100);
      return ln_base > 0 ? Math.log(ratio) / ln_base : 0;
    } else {
      return riskR > 0 ? (val - initCash) / riskR : 0;
    }
  };

  const getDrawdownRValue = (ddPct: number) => {
    if (riskType === "PERCENT") {
      return riskR > 0 ? ddPct / riskR : 0;
    } else {
      return riskR > 0 ? ((ddPct / 100) * initCash) / riskR : 0;
    }
  };
  const [activeMainTab, setActiveMainTab] = useState<"equity" | "oos_degradation">("equity");

  const [showEquityExpenses, setShowEquityExpenses] = useState(true);
  const [showDrawdownExpenses, setShowDrawdownExpenses] = useState(false);
  const [showMaxDDPeriod, setShowMaxDDPeriod] = useState(false);

  // Calcular el período de drawdown más largo en base a duración temporal
  const maxDrawdownPeriod = useMemo(() => {
    if (!globalEquity || globalEquity.length < 2) return null;
    
    let maxVal = -Infinity;
    let currentStreakStart: any = null;
    const streaks: Array<{ start: number; end: number; duration: number }> = [];
    
    for (let i = 0; i < globalEquity.length; i++) {
      const p = globalEquity[i];
      const val = p.value;
      
      if (val >= maxVal) {
        if (currentStreakStart !== null) {
          streaks.push({
            start: currentStreakStart.time as number,
            end: p.time as number,
            duration: (p.time as number) - (currentStreakStart.time as number)
          });
          currentStreakStart = null;
        }
        maxVal = val;
      } else {
        if (currentStreakStart === null && i > 0) {
          currentStreakStart = globalEquity[i - 1];
        }
      }
    }
    
    // Si la curva termina en drawdown (no recuperada al final del periodo)
    if (currentStreakStart !== null) {
      const lastPoint = globalEquity[globalEquity.length - 1];
      streaks.push({
        start: currentStreakStart.time as number,
        end: lastPoint.time as number,
        duration: (lastPoint.time as number) - (currentStreakStart.time as number)
      });
    }
    
    if (streaks.length === 0) return null;
    
    let maxStreak = streaks[0];
    for (const s of streaks) {
      if (s.duration > maxStreak.duration) {
        maxStreak = s;
      }
    }
    return maxStreak;
  }, [globalEquity]);

  // Calcular R2, K-Ratio y SQN basados únicamente en el In-Sample (IS)
  const { isR2, isKRatio, isSQN } = useMemo(() => {
    if (!fullGlobalEquity || fullGlobalEquity.length < 2 || !fullTrades || fullTrades.length === 0) {
      return { isR2: 0, isKRatio: 0, isSQN: 0 };
    }
    const cutoffIdx = Math.max(
      1,
      Math.floor(fullGlobalEquity.length * (isPercent / 100)),
    );
    const cTime = fullGlobalEquity[cutoffIdx - 1].time;
    const isTrades = fullTrades.filter((t) => t.entry_time_epoch <= cTime);
    const isEq = fullGlobalEquity.slice(0, cutoffIdx);
    
    return {
      isR2: computeR2FromEquity(isEq),
      isKRatio: computeKRatio(isTrades),
      isSQN: computeSQN(isTrades),
    };
  }, [fullGlobalEquity, fullTrades, isPercent]);

  const openPositions = useMemo(() => {
    if (!globalEquity.length || !trades.length) return [];
    const timeSet = new Set(globalEquity.map((p) => p.time));
    const counts = new Map<number, number>();
    for (const t of timeSet) counts.set(t, 0);

    for (const trade of trades) {
      const entryTs = Math.floor(new Date(trade.entry_time).getTime() / 1000);
      const exitTs = Math.floor(new Date(trade.exit_time).getTime() / 1000);
      for (const t of timeSet) {
        if (t >= entryTs && t <= exitTs) {
          counts.set(t, (counts.get(t) || 0) + 1);
        }
      }
    }
    return globalEquity.map((p) => ({
      time: p.time as Time,
      value: counts.get(p.time) || 0,
      color:
        (counts.get(p.time) || 0) > 0
          ? "rgba(59,130,246,0.25)"
          : "rgba(59,130,246,0.05)",
    }));
  }, [globalEquity, trades]);



  useEffect(() => {
    if (!containerRef.current || !ddContainerRef.current || !globalEquity.length) return;

    containerRef.current.innerHTML = "";
    ddContainerRef.current.innerHTML = "";

    const equityContainer = containerRef.current;
    const ddContainer = ddContainerRef.current;

    // Common time formatter for showing only date
    const timeFormatter = (time: any) => {
      if (typeof time === "number") {
        const date = new Date(time * 1000);
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
      }
      return String(time);
    };

    // --- Equity Chart ---
    const chart = createChart(equityContainer, {
      width: equityContainer.clientWidth,
      height: 370,
      handleScale: {
        mouseWheel: false,
        pinch: false,
        axisPressedMouseMove: {
          time: false,
          price: false,
        },
        axisDoubleClickReset: false,
      },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: false,
        horzTouchDrag: false,
        vertTouchDrag: false,
      },
      layout: {
        background: { type: ColorType.Solid, color: "#16181A" },
        textColor: "#8A8D92",
      },
      grid: {
        vertLines: { color: "#2C2F33" },
        horzLines: { color: "#2C2F33" },
      },
      rightPriceScale: { borderColor: "#2C2F33" },
      timeScale: { borderColor: "#2C2F33", timeVisible: false },
      localization: {
        timeFormatter,
      },
    });
    chartRef.current = chart;

    const equitySeries = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      topColor: "rgba(59,130,246,0.4)",
      bottomColor: "rgba(59,130,246,0.05)",
      lineWidth: 2,
    });
    equitySeries.setData(
      globalEquity.map((p) => {
        let val = p.value;
        if (viewMode === "%") {
          val = ((p.value / initCash) - 1) * 100;
        } else if (viewMode === "R") {
          val = getRValue(p.value);
        }
        return { time: p.time as Time, value: val };
      })
    );

    // --- Monthly Expenses Curve ---
    if (showEquityExpenses && monthlyExpenses && monthlyExpenses > 0 && globalEquity.length > 0) {
      const expensesSeries = chart.addSeries(LineSeries, {
        color: "#3b82f6",
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
      });

      const startTs = globalEquity[0].time as number;
      const sPerMonth = 30.436875 * 24 * 60 * 60; // Average seconds per month

      expensesSeries.setData(
        globalEquity.map((p) => {
          const monthsElapsed = ((p.time as number) - startTs) / sPerMonth;
          const netValue = p.value - (monthlyExpenses * monthsElapsed);
          
          let val = netValue;
          if (viewMode === "%") {
            val = ((netValue / initCash) - 1) * 100;
          } else if (viewMode === "R") {
            val = getRValue(netValue);
          }
          return { time: p.time as Time, value: val };
        })
      );
    }

    if (openPositions.length) {
      const posSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "positions",
      });
      chart.priceScale("positions").applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
      });
      posSeries.setData(openPositions);
    }

    // --- Drawdown Chart ---
    let ddChart: IChartApi | null = null;
    let drawdownSeries: ISeriesApi<"Baseline"> | null = null;

    if (globalDrawdown && globalDrawdown.length) {
      ddChart = createChart(ddContainer, {
        width: ddContainer.clientWidth,
        height: 120,
        handleScale: {
          mouseWheel: false,
          pinch: false,
          axisPressedMouseMove: {
            time: false,
            price: false,
          },
          axisDoubleClickReset: false,
        },
        handleScroll: {
          mouseWheel: false,
          pressedMouseMove: false,
          horzTouchDrag: false,
          vertTouchDrag: false,
        },
        layout: {
          background: { type: ColorType.Solid, color: "#16181A" },
          textColor: "#8A8D92",
        },
        grid: {
          vertLines: { color: "#2C2F33" },
          horzLines: { color: "#2C2F33" },
        },
        rightPriceScale: { borderColor: "#2C2F33" },
        timeScale: { borderColor: "#2C2F33", timeVisible: false },
        localization: {
          timeFormatter,
        },
      });
      ddChartRef.current = ddChart;

      drawdownSeries = ddChart.addSeries(BaselineSeries, {
        baseValue: { type: "price", price: 0 },
        topLineColor: "rgba(16,185,129,0.5)",
        topFillColor1: "rgba(16,185,129,0.05)",
        topFillColor2: "rgba(16,185,129,0.02)",
        bottomLineColor: "#ef4444",
        bottomFillColor1: "rgba(239,68,68,0.05)",
        bottomFillColor2: "rgba(239,68,68,0.4)",
        lineWidth: 2,
      });

      drawdownSeries.setData(
        globalDrawdown.map((p) => {
          let val = p.value; // Drawdown is natively in % from the backend
          if (viewMode === "R") {
            val = getDrawdownRValue(p.value);
          } else if (viewMode === "$") {
            val = (p.value / 100) * initCash;
          }
          return { time: p.time as Time, value: val };
        })
      );

      // --- Drawdown with Expenses Series ---
      if (showDrawdownExpenses && monthlyExpenses && monthlyExpenses > 0 && globalEquity.length > 0) {
        const ddExpensesSeries = ddChart.addSeries(LineSeries, {
          color: "#ef4444",
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
        });

        const startTs = globalEquity[0].time as number;
        const sPerMonth = 30.436875 * 24 * 60 * 60; // Average seconds per month

        const netEquityValues = globalEquity.map((p) => {
          const monthsElapsed = ((p.time as number) - startTs) / sPerMonth;
          const netValue = p.value - (monthlyExpenses * monthsElapsed);
          return { time: p.time, value: netValue };
        });

        let netHighWaterMark = netEquityValues[0].value;
        const netDrawdown = netEquityValues.map((p) => {
          if (p.value > netHighWaterMark) {
            netHighWaterMark = p.value;
          }
          const ddAbsolute = p.value - netHighWaterMark;
          const ddPct = netHighWaterMark > 0 ? (ddAbsolute / netHighWaterMark) * 100 : 0;

          let val = ddPct;
          if (viewMode === "R") {
            val = riskType === "PERCENT" ? ddPct / riskR : (riskR > 0 ? ddAbsolute / riskR : 0);
          } else if (viewMode === "$") {
            val = ddAbsolute;
          }
          return { time: p.time as Time, value: val };
        });

        ddExpensesSeries.setData(netDrawdown);
      }

      // Synchronize horizontal scrolling
      chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range && ddChart) {
          ddChart.timeScale().setVisibleLogicalRange(range);
        }
      });

      ddChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) {
          chart.timeScale().setVisibleLogicalRange(range);
        }
      });

      // Synchronize crosshair
      chart.subscribeCrosshairMove((param) => {
        if (!param.time || !ddChart || !drawdownSeries) return;
        ddChart.setCrosshairPosition(param.point?.x || 0, param.time, drawdownSeries);
      });

      ddChart.subscribeCrosshairMove((param) => {
        if (!param.time || !equitySeries) return;
        chart.setCrosshairPosition(param.point?.x || 0, param.time, equitySeries);
      });
    }

    // --- Max Drawdown Period Overlay ---
    if (showMaxDDPeriod && maxDrawdownPeriod) {
      const ddPeriodSeries = chart.addSeries(AreaSeries, {
        lineColor: "transparent",    // Elimina cualquier borde superior horizontal
        topColor: "rgba(239, 68, 68, 0.16)",  // Relleno superior un poco más visible
        bottomColor: "rgba(239, 68, 68, 0.04)", // Relleno inferior un poco más visible
        lineWidth: 1,                // Grosor válido en TS, pero invisible por lineColor: transparent
        priceScaleId: "dd_period_scale",
        lastValueVisible: false,  // Evita mostrar cifra en el eje Y
        priceLineVisible: false,   // Evita mostrar línea horizontal de precio
      });
      
      chart.priceScale("dd_period_scale").applyOptions({
        autoScale: true,          // Habilitar autoscale con los límites de la serie (0.0 y 1.0)
        scaleMargins: { top: 0, bottom: 0 }, // Ocupar 100% de la altura
        visible: false,          // No mostrar escala numérica
      });

      const startIndex = globalEquity.findIndex(p => (p.time as number) === maxDrawdownPeriod.start);
      const endIndex = globalEquity.findIndex(p => (p.time as number) === maxDrawdownPeriod.end);
      
      const ddPeriodData: any[] = [];
      if (startIndex >= 0 && endIndex >= 0) {
        // Punto inicial en 0.0 para anclar la escala en la base
        if (startIndex > 0) {
          ddPeriodData.push({ time: globalEquity[startIndex - 1].time as Time, value: 0.0 });
        }
        // Puntos de la banda en 1.0
        for (let i = startIndex; i <= endIndex; i++) {
          ddPeriodData.push({ time: globalEquity[i].time as Time, value: 1.0 });
        }
        // Punto final en 0.0 para cerrar
        if (endIndex < globalEquity.length - 1) {
          ddPeriodData.push({ time: globalEquity[endIndex + 1].time as Time, value: 0.0 });
        }
      }

      if (ddPeriodData.length > 0) {
        ddPeriodSeries.setData(ddPeriodData);
      }
    }

    const updateLabelPosition = () => {
      if (!chartRef.current || !maxDrawdownPeriod) return;
      const timeScale = chartRef.current.timeScale();
      const containerWidth = equityContainer?.clientWidth || 0;

      // Línea de Inicio
      if (ddLineStartRef.current) {
        const coordStart = timeScale.timeToCoordinate(maxDrawdownPeriod.start as Time);
        if (coordStart !== null && coordStart >= 0 && coordStart <= containerWidth) {
          ddLineStartRef.current.style.left = `${coordStart}px`;
          ddLineStartRef.current.style.display = "block";
        } else {
          ddLineStartRef.current.style.display = "none";
        }
      }

      // Línea de Fin y Etiqueta
      const coordEnd = timeScale.timeToCoordinate(maxDrawdownPeriod.end as Time);
      if (coordEnd !== null && coordEnd >= 0 && coordEnd <= containerWidth) {
        if (ddLineEndRef.current) {
          ddLineEndRef.current.style.left = `${coordEnd}px`;
          ddLineEndRef.current.style.display = "block";
        }
        if (ddLabelRef.current) {
          ddLabelRef.current.style.left = `${coordEnd - 3}px`; // Pegado a la línea derecha
          ddLabelRef.current.style.display = "block";
        }
      } else {
        if (ddLineEndRef.current) ddLineEndRef.current.style.display = "none";
        if (ddLabelRef.current) ddLabelRef.current.style.display = "none";
      }
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(updateLabelPosition);

    chart.timeScale().fitContent();
    if (ddChart) ddChart.timeScale().fitContent();

    // Posicionar etiqueta flotante al inicio
    setTimeout(updateLabelPosition, 50);

    const handleResize = () => {
      if (equityContainer) {
        chart.applyOptions({ width: equityContainer.clientWidth });
        chart.timeScale().fitContent();
      }
      if (ddContainer && ddChart) {
        ddChart.applyOptions({ width: ddContainer.clientWidth });
        ddChart.timeScale().fitContent();
      }
      updateLabelPosition();
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      if (ddChart) ddChart.remove();
      chartRef.current = null;
      ddChartRef.current = null;
    };
  }, [globalEquity, globalDrawdown, openPositions, viewMode, initCash, riskR, monthlyExpenses, isDarkMode, activeMainTab, showEquityExpenses, showDrawdownExpenses, showMaxDDPeriod, maxDrawdownPeriod, riskType]);

  if (!globalEquity.length) {
    return <p className="text-sm text-[var(--muted)]">Sin datos de equity</p>;
  }

  const maxDD = globalDrawdown && globalDrawdown.length > 0
    ? Math.min(...globalDrawdown.map((d) => d.value))
    : 0;

  const maxProfit = globalEquity && globalEquity.length > 0
    ? Math.max(...globalEquity.map((p) => {
      if (viewMode === "%") return ((p.value / initCash) - 1) * 100;
      if (viewMode === "R") return getRValue(p.value);
      return p.value - initCash;
    }))
    : 0;

  const maxProfitWithExpenses = globalEquity && globalEquity.length > 0 && monthlyExpenses ? 
    Math.max(...globalEquity.map((p) => {
      const startTs = globalEquity[0].time as number;
      const sPerMonth = 30.436875 * 24 * 60 * 60;
      const monthsElapsed = ((p.time as number) - startTs) / sPerMonth;
      const netValue = p.value - (monthlyExpenses * monthsElapsed);
      
      if (viewMode === "%") return ((netValue / initCash) - 1) * 100;
      if (viewMode === "R") return getRValue(netValue);
      return netValue - initCash;
    }))
    : null;

  const ddDisplay = (() => {
    if (viewMode === "%") return `${maxDD.toFixed(2)}%`;
    if (viewMode === "$") return `$${((maxDD / 100) * initCash).toFixed(2)}`;
    if (viewMode === "R") return `${getDrawdownRValue(maxDD).toFixed(2)}R`;
    return `${maxDD.toFixed(2)}%`;
  })();

  const profitDisplay = (() => {
    if (viewMode === "%") return `${maxProfit.toFixed(2)}%`;
    if (viewMode === "$") return `$${maxProfit.toFixed(2)}`;
    if (viewMode === "R") return `${maxProfit.toFixed(2)}R`;
    return `${maxProfit.toFixed(2)}`;
  })();

  const profitWithExpensesDisplay = (() => {
    if (maxProfitWithExpenses === null) return "";
    if (viewMode === "%") return `${maxProfitWithExpenses.toFixed(2)}%`;
    if (viewMode === "$") return `$${maxProfitWithExpenses.toFixed(2)}`;
    if (viewMode === "R") return `${maxProfitWithExpenses.toFixed(2)}R`;
    return `${maxProfitWithExpenses.toFixed(2)}`;
  })();

  return (
    <div className="flex flex-col h-full">
      {/* MAIN TAB SWITCHER */}
      <div style={{ borderBottom: '0.5px solid var(--color-ec-border)', height: 32, display: 'flex', alignItems: 'center', padding: '0 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', height: '100%', gap: 0 }}>
          <button
            onClick={() => setActiveMainTab("equity")}
            style={{
              padding: '0 10px 0 0',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 11,
              fontWeight: 700,
              textTransform: 'uppercase' as const,
              letterSpacing: '0.15em',
              color: activeMainTab === "equity" ? "var(--color-ec-text-high)" : "var(--color-ec-text-muted)",
              background: 'transparent',
              borderTop: 'none',
              borderLeft: 'none',
              borderRight: 'none',
              borderBottom: activeMainTab === "equity" ? '2px solid var(--color-ec-text-high)' : '2px solid transparent',
              cursor: 'pointer',
              transition: 'color 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (activeMainTab !== "equity") e.currentTarget.style.color = "var(--color-ec-text-secondary)";
            }}
            onMouseLeave={(e) => {
              if (activeMainTab !== "equity") e.currentTarget.style.color = "var(--color-ec-text-muted)";
            }}
          >
            IS Equity Curve
          </button>
          <span style={{ width: 1, height: 14, backgroundColor: 'var(--color-ec-border)', opacity: 0.7, margin: '0 6px', flexShrink: 0 }}></span>
          <button
            onClick={() => setActiveMainTab("oos_degradation")}
            style={{
              padding: '0 10px',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 11,
              fontWeight: 700,
              textTransform: 'uppercase' as const,
              letterSpacing: '0.15em',
              color: activeMainTab === "oos_degradation" ? "var(--color-ec-text-high)" : "var(--color-ec-text-muted)",
              background: 'transparent',
              borderTop: 'none',
              borderLeft: 'none',
              borderRight: 'none',
              borderBottom: activeMainTab === "oos_degradation" ? '2px solid var(--color-ec-text-high)' : '2px solid transparent',
              cursor: 'pointer',
              transition: 'color 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (activeMainTab !== "oos_degradation") e.currentTarget.style.color = "var(--color-ec-text-secondary)";
            }}
            onMouseLeave={(e) => {
              if (activeMainTab !== "oos_degradation") e.currentTarget.style.color = "var(--color-ec-text-muted)";
            }}
          >
            OOS degradation
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeMainTab === "equity" ? (
          <div key="equity-tab" className="px-6 pt-2 pb-1 h-full flex flex-col">
            {globalDrawdown && globalDrawdown.length > 0 && (
              <div className="mt-1 mb-1 flex items-center justify-between">
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wide font-mono" style={{ color: "#ffffff" }}>
                      Max DD
                    </span>
                    <span className="text-[12px] font-bold font-mono" style={{ color: "var(--color-ec-loss)" }}>
                      {ddDisplay}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wide font-mono" style={{ color: "#ffffff" }}>
                      Max Profit
                    </span>
                    <span className="text-[12px] font-bold font-mono" style={{ color: "var(--color-ec-profit)" }}>
                      {profitDisplay}
                    </span>
                  </div>
                  {maxProfitWithExpenses !== null && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] uppercase tracking-wide font-mono" style={{ color: "#ffffff" }}>
                        Max Profit c/ Gastos
                      </span>
                      <span className="text-[12px] font-bold font-mono" style={{ color: "var(--color-ec-profit)" }}>
                        {profitWithExpensesDisplay}
                      </span>
                    </div>
                  )}
                  {!!monthlyExpenses && monthlyExpenses > 0 && (
                    <label className="flex items-center gap-1.5 cursor-pointer select-none ml-2">
                      <input
                        type="checkbox"
                        checked={showEquityExpenses}
                        onChange={(e) => setShowEquityExpenses(e.target.checked)}
                        className="accent-[var(--color-ec-copper)] w-3.5 h-3.5 cursor-pointer"
                      />
                      <span className="text-[10px] font-mono text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] transition-colors">
                        Mostrar gastos
                      </span>
                    </label>
                  )}
                  {maxDrawdownPeriod && (
                    <label className="flex items-center gap-1.5 cursor-pointer select-none ml-2">
                      <input
                        type="checkbox"
                        checked={showMaxDDPeriod}
                        onChange={(e) => setShowMaxDDPeriod(e.target.checked)}
                        className="accent-[var(--color-ec-copper)] w-3.5 h-3.5 cursor-pointer"
                      />
                      <span className="text-[10px] font-mono text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] transition-colors">
                        Max DD Period
                      </span>
                    </label>
                  )}
                </div>

                <div className="flex items-center" style={{ marginRight: 22 }}>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    {(["$", "%", "R"] as ViewMode[]).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setViewMode(mode)}
                        style={{
                          padding: '2px 4px',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 12,
                          fontWeight: 700,
                          color: viewMode === mode ? "#ffffff" : "var(--color-ec-text-muted)",
                          background: 'transparent',
                          borderTop: 'none',
                          borderLeft: 'none',
                          borderRight: 'none',
                          borderBottom: viewMode === mode ? "2px solid #ffffff" : "2px solid transparent",
                          cursor: 'pointer',
                          transition: 'color 150ms ease, border-color 150ms ease',
                        }}
                        onMouseEnter={(e) => {
                          if (viewMode !== mode) e.currentTarget.style.color = "var(--color-ec-text-secondary)";
                        }}
                        onMouseLeave={(e) => {
                          if (viewMode !== mode) e.currentTarget.style.color = "var(--color-ec-text-muted)";
                        }}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
            <div style={{ position: "relative", width: "100%", height: 370 }}>
              <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
              {showMaxDDPeriod && maxDrawdownPeriod && (
                <>
                  <div
                    ref={ddLineStartRef}
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 26, // Para que se detenga arriba del eje de tiempo
                      width: "1px",
                      backgroundColor: "rgba(239, 68, 68, 0.45)", // Borde rojo más visible
                      pointerEvents: "none",
                      zIndex: 13,
                      display: "none",
                    }}
                  />
                  <div
                    ref={ddLineEndRef}
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 26,
                      width: "1px",
                      backgroundColor: "rgba(239, 68, 68, 0.45)", // Borde rojo más visible
                      pointerEvents: "none",
                      zIndex: 13,
                      display: "none",
                    }}
                  />
                  <div
                    ref={ddLabelRef}
                    style={{
                      position: "absolute",
                      top: 110, // Posicionado en la parte alta
                      left: 0,
                      transform: "rotate(-90deg)",
                      transformOrigin: "left bottom",
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: "8px",
                      fontWeight: 700,
                      letterSpacing: "0.1em",
                      color: "rgba(239, 68, 68, 0.75)",
                      pointerEvents: "none",
                      whiteSpace: "nowrap",
                      zIndex: 14,
                      display: "none",
                    }}
                  >
                    MAX DRAWDOWN PERIOD
                  </div>
                </>
              )}
              {/* Compact Terminal HUD Table for R-squared (R2) in the bottom-left corner (above TradingView logo / time scale) */}
              {metrics && metrics.r_squared !== undefined && (
                <div
                  style={{
                    position: "absolute",
                    bottom: 32, // Bajar a la esquina inferior izquierda tras ocultar el logo de TradingView
                    left: 12,
                    backgroundColor: "transparent",
                    backdropFilter: "none",
                    border: "none",
                    borderRadius: 0,
                    padding: "0",
                    pointerEvents: "auto",
                    zIndex: 15,
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "9px",
                    color: "var(--color-ec-text-primary)",
                    boxShadow: "none",
                    lineHeight: 1.3,
                    minWidth: 150,
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: "8px", color: "var(--color-ec-text-muted)", letterSpacing: "0.06em", marginBottom: 5, textTransform: "uppercase" }}>
                    SYSTEM STABILITY
                  </div>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "0.5px solid rgba(255, 255, 255, 0.15)", color: "#ffffff" }}>
                        <th style={{ textAlign: "left", paddingBottom: 3, fontWeight: 500, fontSize: "8px" }}>METRIC</th>
                        <th style={{ textAlign: "right", paddingBottom: 3, fontWeight: 500, fontSize: "8px", paddingLeft: 12 }}>VALUE</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr style={{ borderBottom: "0.5px solid rgba(255, 255, 255, 0.05)" }}>
                        <td style={{ textAlign: "left", padding: "4px 0", color: "#ffffff", display: "flex", alignItems: "center" }}>
                          <span>R² (IS)</span>
                          <InfoTooltip 
                            title="R² (In-Sample)"
                            text={"¿Cómo de recta es la subida de tu dinero? Mide la consistencia del crecimiento. Si el gráfico subiera en una línea recta perfecta, el valor sería 1.00. Un valor alto significa que ganas de forma constante mes a mes, sin dar saltos locos ni quedarte estancado.\n\nBaremos: >0.90 Excelente (crecimiento lineal) | 0.75-0.90 Bueno | 0.60-0.75 Mediocre (baches y estancamientos) | <0.60 Malo (crecimiento caótico)."} 
                            position="top-right-aligned" 
                          />
                        </td>
                        <td style={{ textAlign: "right", padding: "4px 0", color: "#ffffff", fontWeight: 700, paddingLeft: 12 }}>
                          {isR2.toFixed(4)}
                        </td>
                      </tr>
                      <tr style={{ borderBottom: "0.5px solid rgba(255, 255, 255, 0.05)" }}>
                        <td style={{ textAlign: "left", padding: "4px 0", color: "#ffffff", display: "flex", alignItems: "center" }}>
                          <span>K-Ratio (IS)</span>
                          <InfoTooltip 
                            title="K-Ratio (In-Sample)"
                            text={"Mide si la ganancia es constante en el tiempo y no se debe a un golpe de suerte. Es clave contra el overfit (sobreajuste): castiga los saltos irregulares o depender de un solo trade gigante. Es ideal para evaluar estrategias de 'Win Rate' (curvas suaves y lineales) pero menos representativo en estrategias de 'Risk Reward' (ganancias escalonadas con saltos bruscos).\n\nBaremos: >1.5 Excelente (regularidad legendaria) | 1.0-1.5 Bueno (consistencia sólida) | 0.5-1.0 Mediocre (periodos planos largos) | <0.5 Malo (errático)."} 
                            position="top-right-aligned" 
                            width="320px"
                          />
                        </td>
                        <td style={{ textAlign: "right", padding: "4px 0", color: "#ffffff", fontWeight: 700, paddingLeft: 12 }}>
                          {isKRatio.toFixed(4)}
                        </td>
                      </tr>
                      <tr style={{ borderBottom: "0.5px solid rgba(255, 255, 255, 0.05)" }}>
                        <td style={{ textAlign: "left", padding: "4px 0", color: "#ffffff", display: "flex", alignItems: "center" }}>
                          <span>SQN (IS)</span>
                          <InfoTooltip 
                            title="SQN (In-Sample)"
                            text={"¿Cómo de fácil y seguro es operar este sistema? Mide la relación entre lo que ganas por trade frente a la volatilidad de tus resultados, ajustado por cuántas operaciones haces. Te dice si puedes aumentar el tamaño de tus posiciones con confianza.\n\nBaremos: >3.0 Excelente (máquina de imprimir dinero) | 2.0-3.0 Bueno (muy operable) | 1.5-2.0 Mediocre (operable pero requiere precaución) | <1.5 Malo (difícil de operar)."} 
                            position="top-right-aligned" 
                          />
                        </td>
                        <td style={{ textAlign: "right", padding: "4px 0", color: "#ffffff", fontWeight: 700, paddingLeft: 12 }}>
                          {isSQN.toFixed(2)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="border-t border-[var(--border)] pt-2 mt-auto">
               <div className="flex items-center gap-4 mb-1.5 px-1">
                 <span className="text-[10px] uppercase tracking-wide font-mono text-[#ffffff]">
                   Drawdown
                 </span>
                 {!!monthlyExpenses && monthlyExpenses > 0 && (
                   <label className="flex items-center gap-1.5 cursor-pointer select-none">
                     <input
                       type="checkbox"
                       checked={showDrawdownExpenses}
                       onChange={(e) => setShowDrawdownExpenses(e.target.checked)}
                       className="accent-[var(--color-ec-copper)] w-3.5 h-3.5 cursor-pointer"
                     />
                     <span className="text-[10px] font-mono text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] transition-colors">
                       Mostrar gastos
                     </span>
                   </label>
                 )}
               </div>
               <div ref={ddContainerRef} className="h-[120px] w-full" />
            </div>
          </div>
                ) : (
          <div key="oos-degradation-tab" style={{ height: "100%", overflow: "hidden" }}>
            <OOSDegradationTab
              fullGlobalEquity={fullGlobalEquity}
              fullGlobalDrawdown={fullGlobalDrawdown}
              fullTrades={fullTrades}
              initCash={initCash}
              riskR={riskR}
              isPercent={isPercent}
              monthlyExpenses={monthlyExpenses}
              isDarkMode={isDarkMode}
              riskType={riskType}
            />
          </div>
        )}
      </div>
    </div>
  );
}
