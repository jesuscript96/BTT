"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import {
  createChart,
  AreaSeries,
  BaselineSeries,
  LineSeries,
  LineStyle,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { GlobalEquityPoint, TradeRecord } from "@/lib/api_backtester";

interface OOSDegradationTabProps {
  fullGlobalEquity: GlobalEquityPoint[];
  fullGlobalDrawdown: GlobalEquityPoint[];
  fullTrades: TradeRecord[];
  initCash: number;
  riskR: number;
  isPercent: number;
  monthlyExpenses?: number;
  isDarkMode?: boolean;
  riskType?: string;
}

/* ── Metric calculator shared between IS and OOS ── */
function computeMetrics(
  trades: TradeRecord[],
  equityPoints: GlobalEquityPoint[],
  initCash: number,
  riskR: number,
) {
  const total = trades.length;
  const wins = trades.filter((t) => t.pnl > 0);
  const losses = trades.filter((t) => t.pnl < 0);
  const winRate = total > 0 ? (wins.length / total) * 100 : 0;
  const grossProfit = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));
  const profitFactor =
    grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
  const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);

  // Daily returns
  const dailyPnls = new Map<string, number>();
  trades.forEach((t) => {
    dailyPnls.set(t.date, (dailyPnls.get(t.date) || 0) + t.pnl);
  });
  const dailyReturns = Array.from(dailyPnls.values()).map(
    (p) => p / initCash,
  );
  const mean =
    dailyReturns.length > 0
      ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length
      : 0;
  const std =
    dailyReturns.length > 1
      ? Math.sqrt(
          dailyReturns.reduce((s, r) => s + (r - mean) ** 2, 0) /
            (dailyReturns.length - 1),
        )
      : 0;
  const downside = dailyReturns.filter((r) => r < 0);
  const downsideStd =
    downside.length > 1
      ? Math.sqrt(
          downside.reduce((s, r) => s + r ** 2, 0) / (downside.length - 1),
        )
      : 0;
  const sharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0;
  const sortino = downsideStd > 0 ? (mean / downsideStd) * Math.sqrt(252) : 0;

  return { winRate, profitFactor, sharpe, sortino, totalPnl, total };
}

function getQualityLevel(key: string, val: number): "very_good" | "good" | "mediocre" | "bad" {
  if (key === "winRate") {
    if (val >= 60) return "very_good";
    if (val >= 50) return "good";
    if (val >= 42) return "mediocre";
    return "bad";
  } else if (key === "profitFactor") {
    if (val >= 1.6) return "very_good";
    if (val >= 1.2) return "good";
    if (val >= 1.0) return "mediocre";
    return "bad";
  } else { // sharpe
    if (val >= 1.5) return "very_good";
    if (val >= 1.0) return "good";
    if (val >= 0.5) return "mediocre";
    return "bad";
  }
}

function getCurveState(key: "profitFactor" | "sharpe", val: number): "asc" | "med" | "desc" {
  if (key === "sharpe") {
    if (val >= 1.0) return "asc";
    if (val >= 0.0) return "med";
    return "desc";
  } else { // profitFactor
    if (val >= 1.2) return "asc";
    if (val >= 1.0) return "med";
    return "desc";
  }
}

export default function OOSDegradationTab({
  fullGlobalEquity,
  fullGlobalDrawdown,
  fullTrades,
  initCash,
  riskR,
  isPercent,
  monthlyExpenses,
  isDarkMode = false,
  riskType = "FIXED",
}: OOSDegradationTabProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const ddChartRef = useRef<IChartApi | null>(null);
  const [delimiterX, setDelimiterX] = useState<number | null>(null);

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
  const [showEquityExpenses, setShowEquityExpenses] = useState(true);
  const [showDrawdownExpenses, setShowDrawdownExpenses] = useState(false);

  const oosPercent = 100 - isPercent;
  const disabled = oosPercent < 10;

  // ── Compute IS/OOS split ──
  const { cutoffTime, isMetrics, oosMetrics } = useMemo(() => {
    if (!fullGlobalEquity || fullGlobalEquity.length < 2 || disabled) {
      return { cutoffTime: null, isMetrics: null, oosMetrics: null };
    }

    const cutoffIdx = Math.max(
      1,
      Math.floor(fullGlobalEquity.length * (isPercent / 100)),
    );
    const cTime = fullGlobalEquity[cutoffIdx - 1].time;

    const isTrades = fullTrades.filter((t) => t.entry_time_epoch <= cTime);
    const oosTrades = fullTrades.filter((t) => t.entry_time_epoch > cTime);

    const isEq = fullGlobalEquity.slice(0, cutoffIdx);
    const oosEq = fullGlobalEquity.slice(cutoffIdx - 1);

    const isM = computeMetrics(isTrades, isEq, initCash, riskR);
    const oosM = computeMetrics(oosTrades, oosEq, initCash, riskR);

    return { cutoffTime: cTime, isMetrics: isM, oosMetrics: oosM };
  }, [fullGlobalEquity, fullTrades, isPercent, initCash, riskR, disabled]);

  // ── Chart rendering ──
  useEffect(() => {
    if (disabled || !chartContainerRef.current || !ddContainerRef.current || !fullGlobalEquity?.length)
      return;

    // Cleanup previous charts
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }
    if (ddChartRef.current) {
      ddChartRef.current.remove();
      ddChartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
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
    });
    chartRef.current = chart;

    // Find cutoff index
    const cutoffIdx = Math.max(
      1,
      Math.floor(fullGlobalEquity.length * (isPercent / 100)),
    );

    // IS area (blue, matching EquityCurveTab)
    const isSeries = chart.addSeries(AreaSeries, {
      lineColor: "rgba(59, 130, 246, 0.9)",
      lineWidth: 2,
      topColor: "rgba(59, 130, 246, 0.4)",
      bottomColor: "rgba(59, 130, 246, 0.05)",
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: true,
    });
    isSeries.setData(
      fullGlobalEquity.slice(0, cutoffIdx).map((p) => {
        let val = p.value;
        if (viewMode === "%") {
          val = ((p.value / initCash) - 1) * 100;
        } else if (viewMode === "R") {
          val = getRValue(p.value);
        }
        return { time: p.time as Time, value: val };
      })
    );

    // OOS area (green)
    const oosSeries = chart.addSeries(AreaSeries, {
      lineColor: "rgba(56, 199, 135, 0.9)",
      lineWidth: 2,
      topColor: "rgba(56, 199, 135, 0.20)",
      bottomColor: "rgba(56, 199, 135, 0.02)",
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: true,
    });
    oosSeries.setData(
      fullGlobalEquity.slice(cutoffIdx - 1).map((p) => {
        let val = p.value;
        if (viewMode === "%") {
          val = ((p.value / initCash) - 1) * 100;
        } else if (viewMode === "R") {
          val = getRValue(p.value);
        }
        return { time: p.time as Time, value: val };
      })
    );

    // Expenses curve
    if (showEquityExpenses && monthlyExpenses && monthlyExpenses > 0 && fullGlobalEquity.length > 0) {
      const startTs = fullGlobalEquity[0].time as number;
      const sPerMonth = 30.436875 * 24 * 60 * 60;

      // IS Expenses (blue dotted)
      const isExpensesSeries = chart.addSeries(LineSeries, {
        color: "rgba(59, 130, 246, 0.7)",
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
      });
      isExpensesSeries.setData(
        fullGlobalEquity.slice(0, cutoffIdx).map((p) => {
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

      // OOS Expenses (green dotted)
      const oosExpensesSeries = chart.addSeries(LineSeries, {
        color: "rgba(56, 199, 135, 0.7)",
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
      });
      oosExpensesSeries.setData(
        fullGlobalEquity.slice(cutoffIdx - 1).map((p) => {
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

    // --- Drawdown Chart ---
    let ddChart: IChartApi | null = null;
    let drawdownSeries: ISeriesApi<"Baseline"> | null = null;

    if (fullGlobalDrawdown && fullGlobalDrawdown.length) {
      ddChart = createChart(ddContainerRef.current, {
        width: ddContainerRef.current.clientWidth,
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
        fullGlobalDrawdown.map((p) => {
          let val = p.value;
          if (viewMode === "R") {
            val = getDrawdownRValue(p.value);
          } else if (viewMode === "$") {
            val = (p.value / 100) * initCash;
          }
          return { time: p.time as Time, value: val };
        })
      );

      // Synced Drawdown Expenses
      if (showDrawdownExpenses && monthlyExpenses && monthlyExpenses > 0 && fullGlobalEquity.length > 0) {
        const ddExpensesSeries = ddChart.addSeries(LineSeries, {
          color: "#ef4444",
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
        });

        const startTs = fullGlobalEquity[0].time as number;
        const sPerMonth = 30.436875 * 24 * 60 * 60;

        const netEquityValues = fullGlobalEquity.map((p) => {
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
        if (!param.time || !isSeries) return;
        chart.setCrosshairPosition(param.point?.x || 0, param.time, isSeries);
      });
    }

    // Function to calculate and update vertical delimiter position
    const updateDelimiterPos = () => {
      if (!chart || !cutoffTime) {
        setDelimiterX(null);
        return;
      }
      const x = chart.timeScale().timeToCoordinate(cutoffTime as Time);
      setDelimiterX(x);
    };

    chart.timeScale().fitContent();
    if (ddChart) ddChart.timeScale().fitContent();
    requestAnimationFrame(updateDelimiterPos);

    // Subscribe to timescale changes to move the delimiter in real-time
    chart.timeScale().subscribeVisibleLogicalRangeChange(updateDelimiterPos);
    chart.timeScale().subscribeVisibleTimeRangeChange(updateDelimiterPos);

    // Resize observer
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
        chart.timeScale().fitContent();
        if (ddChart) {
          ddChart.applyOptions({ width: entry.contentRect.width });
          ddChart.timeScale().fitContent();
        }
        updateDelimiterPos();
      }
    });
    ro.observe(chartContainerRef.current);

    return () => {
      ro.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(updateDelimiterPos);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(updateDelimiterPos);
      chart.remove();
      if (ddChart) ddChart.remove();
      chartRef.current = null;
      ddChartRef.current = null;
    };
  }, [fullGlobalEquity, fullGlobalDrawdown, isPercent, disabled, cutoffTime, viewMode, showEquityExpenses, showDrawdownExpenses, initCash, riskR, monthlyExpenses, riskType]);

  // ── Disabled state ──
  if (disabled) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          padding: 40,
        }}
      >
        <div
          style={{
            textAlign: "center",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <span
            style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--color-ec-text-muted)",
            }}
          >
            ⛔ OOS insuficiente
          </span>
          <span
            style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 11,
              color: "var(--color-ec-text-muted)",
            }}
          >
            Se necesita un mínimo del 10% de datos Out-of-Sample para validar.
            <br />
            Ajusta el slider de IS-OOS a ≤ 90%.
          </span>
        </div>
      </div>
    );
  }

  // ── Metrics computation values ──
  const maxDD = fullGlobalDrawdown && fullGlobalDrawdown.length > 0
    ? Math.min(...fullGlobalDrawdown.map((d) => d.value))
    : 0;

  const maxProfit = fullGlobalEquity && fullGlobalEquity.length > 0
    ? Math.max(...fullGlobalEquity.map((p) => {
      if (viewMode === "%") return ((p.value / initCash) - 1) * 100;
      if (viewMode === "R") return getRValue(p.value);
      return p.value - initCash;
    }))
    : 0;

  const maxProfitWithExpenses = fullGlobalEquity && fullGlobalEquity.length > 0 && monthlyExpenses ? 
    Math.max(...fullGlobalEquity.map((p) => {
      const startTs = fullGlobalEquity[0].time as number;
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

  const metricRows = [
    { label: "Win Rate", key: "winRate", unit: "%", decimals: 1 },
    { label: "Profit Factor", key: "profitFactor", unit: "", decimals: 2 },
    { label: "Sharpe Ratio", key: "sharpe", unit: "", decimals: 2 },
  ] as const;

  return (
    <div className="px-6 pt-2 pb-1 h-full flex flex-col">
      {fullGlobalDrawdown && fullGlobalDrawdown.length > 0 && (
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

            {/* IS/OOS Legend in the top bar (blue for IS, green for OOS) */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginLeft: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 10, height: 3, backgroundColor: "rgba(59, 130, 246, 0.9)", borderRadius: 2 }} />
                <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 10, fontWeight: 600, color: "#3b82f6" }}>
                  IS ({isPercent}%)
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 10, height: 3, backgroundColor: "rgba(56, 199, 135, 0.9)", borderRadius: 2 }} />
                <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 10, fontWeight: 600, color: "var(--color-ec-profit)" }}>
                  OOS ({oosPercent}%)
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center" style={{ marginRight: 22 }}>
            <div style={{ display: "flex", gap: "4px" }}>
              {(["$", "%", "R"] as ViewMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  style={{
                    padding: "2px 4px",
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 12,
                    fontWeight: 700,
                    color: viewMode === mode ? "#ffffff" : "var(--color-ec-text-muted)",
                    background: "transparent",
                    borderTop: "none",
                    borderLeft: "none",
                    borderRight: "none",
                    borderBottom: viewMode === mode ? "2px solid #ffffff" : "2px solid transparent",
                    cursor: "pointer",
                    transition: "color 150ms ease, border-color 150ms ease",
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

      {/* Equity chart container wrapper with relative positioning for absolute vertical line and HUD terminal table */}
      <div style={{ position: "relative", width: "100%", height: 370 }}>
        <div
          ref={chartContainerRef}
          style={{
            width: "100%",
            height: "100%",
            borderRadius: 5,
            overflow: "hidden",
          }}
        />
        {/* Custom HTML/CSS-based vertical delimiter line + vertical OOS label on the right */}
        {delimiterX !== null && delimiterX >= 0 && (
          <>
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 26, // Keep above timescale labels
                left: delimiterX,
                width: "1px",
                borderLeft: "1.5px dashed rgba(255, 255, 255, 0.45)",
                pointerEvents: "none",
                zIndex: 10,
              }}
            />
            <div
              style={{
                position: "absolute",
                top: 20,
                left: delimiterX + 6,
                color: "rgba(56, 199, 135, 0.8)",
                fontSize: "10px",
                fontWeight: 800,
                fontFamily: "var(--color-ec-sans)",
                letterSpacing: "0.15em",
                pointerEvents: "none",
                zIndex: 10,
                writingMode: "vertical-rl",
                textTransform: "uppercase",
              }}
            >
              OOS
            </div>
          </>
        )}

        {/* Compact Terminal HUD Comparison Table (stamped onto the chart background) */}
        {isMetrics && oosMetrics && (
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
              pointerEvents: "none",
              zIndex: 15,
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "9px",
              color: "var(--color-ec-text-primary)",
              boxShadow: "none",
              lineHeight: 1.3,
              minWidth: 280,
            }}
          >
            <div style={{ fontWeight: 700, fontSize: "8px", color: "var(--color-ec-text-muted)", letterSpacing: "0.06em", marginBottom: 5, textTransform: "uppercase" }}>
              OOS DEGRADATION ANALYSIS
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "0.5px solid rgba(255, 255, 255, 0.15)", color: "#ffffff" }}>
                  <th style={{ textAlign: "left", paddingBottom: 3, fontWeight: 500, fontSize: "8px" }}>METRIC</th>
                  <th style={{ textAlign: "right", paddingBottom: 3, fontWeight: 500, fontSize: "8px" }}>IS</th>
                  <th style={{ textAlign: "right", paddingBottom: 3, fontWeight: 500, fontSize: "8px" }}>OOS</th>
                  <th style={{ textAlign: "right", paddingBottom: 3, fontWeight: 500, fontSize: "8px", paddingLeft: 6 }}>DEG. RATIO</th>
                </tr>
              </thead>
              <tbody>
                {metricRows.map((row) => {
                  const displayIsVal = isMetrics[row.key] as number;
                  const displayOosVal = oosMetrics[row.key] as number;

                  // Normalize percentages to decimal fractions for ratio calculation consistency
                  const normIsVal = row.key === "winRate" ? displayIsVal / 100 : displayIsVal;
                  const normOosVal = row.key === "winRate" ? displayOosVal / 100 : displayOosVal;

                  // Robust ratio calculation handling negative numbers
                  let ratio: number | null = null;
                  if (normIsVal !== 0 && isFinite(normIsVal) && isFinite(normOosVal)) {
                    if (normIsVal < 0) {
                      ratio = 1 - (normIsVal - normOosVal) / Math.abs(normIsVal);
                    } else {
                      ratio = normOosVal / normIsVal;
                    }
                  } else if (normIsVal === 0 && isFinite(normOosVal)) {
                    ratio = normOosVal >= 0 ? 1.0 : 0.0;
                  }

                  let ratioColor = "var(--color-ec-text-muted)";
                  let ratioLabel = "—";

                  if (row.key === "winRate") {
                    if (ratio !== null && isFinite(ratio)) {
                      if (ratio >= 0.80 && ratio <= 1.20) {
                        ratioColor = "var(--color-ec-profit)"; // Verde
                        ratioLabel = "Lineal";
                      } else if ((ratio >= 0.65 && ratio < 0.80) || (ratio > 1.20 && ratio <= 1.35)) {
                        ratioColor = "#e8a33a"; // Amarillo
                        ratioLabel = "No lineal";
                      } else {
                        ratioColor = "var(--color-ec-loss)"; // Rojo
                        ratioLabel = "No lineal";
                      }
                    }
                  } else {
                    const isState = getCurveState(row.key, displayIsVal);
                    const oosState = getCurveState(row.key, displayOosVal);

                    if (isState === "asc" && oosState === "asc") {
                      ratioColor = "var(--color-ec-profit)";
                      ratioLabel = "Óptimo";
                    } else if (isState === "asc" && oosState === "med") {
                      ratioColor = "#e8a33a";
                      ratioLabel = "Cuidado, posible overfit";
                    } else if (isState === "asc" && oosState === "desc") {
                      ratioColor = "var(--color-ec-loss)";
                      ratioLabel = "Overfit/No Edge";
                    } else if (isState === "med" && oosState === "asc") {
                      ratioColor = "#e8a33a";
                      ratioLabel = "Cuidado/No lineal";
                    } else if (isState === "med" && oosState === "med") {
                      ratioColor = "#e8a33a";
                      ratioLabel = "Cuidado";
                    } else if (isState === "med" && oosState === "desc") {
                      ratioColor = "var(--color-ec-loss)";
                      ratioLabel = "Sin Edge";
                    } else if (isState === "desc" && oosState === "asc") {
                      ratioColor = "var(--color-ec-loss)";
                      ratioLabel = "Sin Edge/No lineal";
                    } else if (isState === "desc" && oosState === "desc") {
                      ratioColor = "var(--color-ec-loss)";
                      ratioLabel = "Sin Edge";
                    } else if (isState === "desc" && oosState === "med") {
                      ratioColor = "var(--color-ec-loss)";
                      ratioLabel = "Sin Edge";
                    }
                  }

                  return (
                    <tr key={row.key} style={{ borderBottom: "0.5px solid rgba(255, 255, 255, 0.05)" }}>
                      <td style={{ textAlign: "left", padding: "4px 0", color: "#ffffff" }}>
                        {row.label}
                      </td>
                      <td style={{ textAlign: "right", padding: "4px 0", color: "#ffffff" }}>
                        {isFinite(displayIsVal) ? `${displayIsVal.toFixed(row.decimals)}${row.unit}` : "—"}
                      </td>
                      <td style={{ textAlign: "right", padding: "4px 0", color: "#ffffff" }}>
                        {isFinite(displayOosVal) ? `${displayOosVal.toFixed(row.decimals)}${row.unit}` : "—"}
                      </td>
                      <td style={{ textAlign: "right", padding: "4px 0", color: ratioColor, fontWeight: 700, paddingLeft: 6 }}>
                        {ratio !== null ? `${ratio.toFixed(2)} (${ratioLabel})` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Drawdown Chart synced underneath */}
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
  );
}
