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
import type { GlobalEquityPoint, DrawdownPoint, TradeRecord, AggregateMetrics, WhatIfResult } from "@/lib/api_backtester";
import { runWhatIf } from "@/lib/api_backtester";
import OOSDegradationTab from "./OOSDegradationTab";


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
}: EquityCurveTabProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const ddChartRef = useRef<IChartApi | null>(null);

  type ViewMode = "$" | "%" | "R";
  const [viewMode, setViewMode] = useState<ViewMode>("$");
  const [activeMainTab, setActiveMainTab] = useState<"equity" | "whatif" | "oos_degradation">("equity");
  const [simLoading, setSimLoading] = useState(false);
  const [simResult, setSimResult] = useState<WhatIfResult | null>(null);

  const [showEquityExpenses, setShowEquityExpenses] = useState(true);
  const [showDrawdownExpenses, setShowDrawdownExpenses] = useState(false);

  // --- What If Simulation States ---
  const [excludeDays, setExcludeDays] = useState<number[]>([]); // 0=Mon, 4=Fri
  const [excludeMonths, setExcludeMonths] = useState<number[]>([]); // 0=Jan
  const [excludeHourStart, setExcludeHourStart] = useState<string>("");
  const [excludeHourEnd, setExcludeHourEnd] = useState<string>("");
  const [includeExpensesInWhatIf, setIncludeExpensesInWhatIf] = useState(false);
  const [randomMonthlyDays, setRandomMonthlyDays] = useState<number>(0);
  const [dailyMaxTrades, setDailyMaxTrades] = useState<number>(0);
  const [maxConcurrentTrades, setMaxConcurrentTrades] = useState<number>(0);
  

  
  const [skipTopPct, setSkipTopPct] = useState<number>(0);
  const [extraSlippage, setExtraSlippage] = useState<number>(0);
  const [blackSwanCount, setBlackSwanCount] = useState<number>(0);
  const [blackSwanSize, setBlackSwanSize] = useState<number>(500); // % of loss

  // Accordion state
  const [openSections, setOpenSections] = useState<string[]>(["temporal"]);

  const toggleSection = (id: string) => {
    setOpenSections(prev => 
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    );
  };

  const handleRunWhatIf = async () => {
    if (!trades || trades.length === 0) return;
    setSimLoading(true);
    try {
      // Parse time strings to hour numbers for the backend
      const parseHour = (t: string) => {
        if (!t) return null;
        const parts = t.split(":");
        return parts.length >= 1 ? parseInt(parts[0], 10) : null;
      };

      const params = {
        exclude_days: excludeDays,
        exclude_months: excludeMonths,
        exclude_hour_start: parseHour(excludeHourStart),
        exclude_hour_end: parseHour(excludeHourEnd),
        random_monthly_days: randomMonthlyDays,
        daily_max_trades: dailyMaxTrades,
        max_concurrent_trades: maxConcurrentTrades,
        skip_top_pct: skipTopPct,
        extra_slippage: extraSlippage,
        black_swan_count: blackSwanCount,
        black_swan_pct: blackSwanSize,
        monthly_expenses: includeExpensesInWhatIf ? (monthlyExpenses || 0) : 0,
      };

      localStorage.setItem("current_whatif_params", JSON.stringify(params));

      const result = await runWhatIf({
        trades,
        init_cash: initCash,
        risk_r: riskR,
        params
      });
      setSimResult(result);
    } catch (error) {
      console.error("Simulation failed:", error);
      alert("Error en la simulación What-if. Revisa la consola.");
    } finally {
      setSimLoading(false);
    }
  };

  const getSimValue = (key: keyof AggregateMetrics, formatter?: (v: number) => string) => {
    if (!simResult || !simResult.aggregate_metrics) return "---";
    const val = simResult.aggregate_metrics[key] as number;
    if (val === undefined || val === null) return "---";
    return formatter ? formatter(val) : String(val);
  };


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
          val = riskR > 0 ? (p.value - initCash) / riskR : 0;
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
            val = riskR > 0 ? (netValue - initCash) / riskR : 0;
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
            // Convert % drawdown to absolute $ drawdown, then divide by R
            val = riskR > 0 ? ((p.value / 100) * initCash) / riskR : 0;
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
            val = riskR > 0 ? ddAbsolute / riskR : 0;
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

    chart.timeScale().fitContent();
    if (ddChart) ddChart.timeScale().fitContent();

    const handleResize = () => {
      if (equityContainer) {
        chart.applyOptions({ width: equityContainer.clientWidth });
      }
      if (ddContainer && ddChart) {
        ddChart.applyOptions({ width: ddContainer.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      if (ddChart) ddChart.remove();
      chartRef.current = null;
      ddChartRef.current = null;
    };
  }, [globalEquity, globalDrawdown, openPositions, viewMode, initCash, riskR, monthlyExpenses, isDarkMode, activeMainTab, showEquityExpenses, showDrawdownExpenses]);

  if (!globalEquity.length) {
    return <p className="text-sm text-[var(--muted)]">Sin datos de equity</p>;
  }

  const maxDD = globalDrawdown && globalDrawdown.length > 0
    ? Math.min(...globalDrawdown.map((d) => d.value))
    : 0;

  const maxProfit = globalEquity && globalEquity.length > 0
    ? Math.max(...globalEquity.map((p) => {
      if (viewMode === "%") return ((p.value / initCash) - 1) * 100;
      if (viewMode === "R") return riskR > 0 ? (p.value - initCash) / riskR : 0;
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
      if (viewMode === "R") return riskR > 0 ? (netValue - initCash) / riskR : 0;
      return netValue - initCash;
    }))
    : null;

  const ddDisplay = (() => {
    if (viewMode === "%") return `${maxDD.toFixed(2)}%`;
    if (viewMode === "$") return `$${((maxDD / 100) * initCash).toFixed(2)}`;
    if (viewMode === "R") return riskR > 0 ? `${((maxDD / 100) * initCash / riskR).toFixed(2)}R` : "0R";
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
            Equity Curve
          </button>
          <span style={{ width: 1, height: 14, backgroundColor: 'var(--color-ec-border)', opacity: 0.7, margin: '0 6px', flexShrink: 0 }}></span>
          <button
            onClick={() => setActiveMainTab("whatif")}
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
              color: activeMainTab === "whatif" ? "var(--color-ec-text-high)" : "var(--color-ec-text-muted)",
              background: 'transparent',
              borderTop: 'none',
              borderLeft: 'none',
              borderRight: 'none',
              borderBottom: activeMainTab === "whatif" ? '2px solid var(--color-ec-text-high)' : '2px solid transparent',
              cursor: 'pointer',
              transition: 'color 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (activeMainTab !== "whatif") e.currentTarget.style.color = "var(--color-ec-text-secondary)";
            }}
            onMouseLeave={(e) => {
              if (activeMainTab !== "whatif") e.currentTarget.style.color = "var(--color-ec-text-muted)";
            }}
          >
            What if...
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
              {/* Compact Terminal HUD Table for R-squared (R2) in the bottom-left corner (above TradingView logo / time scale) */}
              {metrics && metrics.r_squared !== undefined && (
                <div
                  style={{
                    position: "absolute",
                    bottom: 58,
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
                    minWidth: 120,
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
                        <td style={{ textAlign: "left", padding: "4px 0", color: "#ffffff" }}>
                          R²
                        </td>
                        <td style={{ textAlign: "right", padding: "4px 0", color: "#ffffff", fontWeight: 700, paddingLeft: 12 }}>
                          {(metrics.r_squared ?? 0).toFixed(4)}
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
        ) : activeMainTab === "whatif" ? (
          <div key="whatif-tab" style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: 'var(--color-ec-bg-base)', paddingLeft: '24px', paddingRight: '24px', paddingTop: '20px', paddingBottom: '20px', boxSizing: 'border-box' }}>
              <div className="flex-1 overflow-y-auto custom-scrollbar pr-1" style={{ width: '100%', height: '100%' }}>                {/* Temporal Settings */}
                <div style={{ borderBottom: '1px solid var(--color-ec-border)', paddingBottom: '16px', marginBottom: '16px' }}>
                  <button 
                    onClick={() => toggleSection("temporal")}
                    style={{
                      width: '100%',
                      paddingTop: '8px',
                      paddingBottom: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                    }}
                    className="hover:text-[var(--color-ec-text-primary)] transition-colors group"
                  >
                    <div className="flex items-center gap-2">
                       <span className="text-[10px] font-bold text-[var(--color-ec-text-primary)] uppercase tracking-wider">1) Espacios Temporales</span>
                    </div>
                    <span className={`text-xs text-[var(--color-ec-text-muted)] transform transition-transform ${openSections.includes("temporal") ? "rotate-180" : ""}`}>▼</span>
                  </button>
                  
                  {openSections.includes("temporal") && (
                    <div style={{ paddingBottom: '16px', paddingTop: '6px' }} className="space-y-5 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div>
                        <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] mb-1.5 block">Excluir Días de la Semana</label>
                        <div className="flex gap-1.5">
                          {["L", "M", "X", "J", "V"].map((day, idx) => (
                            <button
                              key={day}
                              onClick={() => {
                                setExcludeDays(prev => prev.includes(idx) ? prev.filter(d => d !== idx) : [...prev, idx]);
                              }}
                              className={`flex-1 py-1.5 rounded text-[10px] font-bold border transition-all ${
                                excludeDays.includes(idx)
                                  ? "bg-[color-mix(in_srgb,var(--color-ec-loss)_20%,transparent)] border-[var(--color-ec-loss)] text-[var(--color-ec-loss)] shadow-inner"
                                  : "bg-[var(--color-ec-bg-elevated)] border-[var(--color-ec-border)] text-[var(--color-ec-text-muted)] hover:border-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)]"
                              }`}
                            >
                              {day}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="pt-2">
                        <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] mb-1.5 block">Excluir Meses del Año</label>
                        <div className="grid grid-cols-6 gap-1.5">
                          {["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"].map((month, idx) => (
                            <button
                              key={month}
                              onClick={() => {
                                setExcludeMonths(prev => prev.includes(idx) ? prev.filter(m => m !== idx) : [...prev, idx]);
                              }}
                              className={`py-1 rounded text-[9px] font-medium border transition-all ${
                                excludeMonths.includes(idx)
                                  ? "bg-[color-mix(in_srgb,var(--color-ec-loss)_20%,transparent)] border-[var(--color-ec-loss)] text-[var(--color-ec-loss)] shadow-inner"
                                  : "bg-[var(--color-ec-bg-elevated)] border-[var(--color-ec-border)] text-[var(--color-ec-text-muted)] hover:border-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)]"
                              }`}
                            >
                              {month}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="pt-2">
                        <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] mb-1.5 block">Excluir Rango de Horas</label>
                        <div className="flex items-center gap-4">
                          <div className="flex-1">
                            <label className="text-[10px] font-medium text-[var(--color-ec-text-muted)] mb-1 block uppercase opacity-70">Desde:</label>
                            <input
                              type="time"
                              value={excludeHourStart}
                              onChange={(e) => setExcludeHourStart(e.target.value)}
                              className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                            />
                          </div>
                          <div className="flex-1">
                            <label className="text-[10px] font-medium text-[var(--color-ec-text-muted)] mb-1 block uppercase opacity-70">Hasta:</label>
                            <input
                              type="time"
                              value={excludeHourEnd}
                              onChange={(e) => setExcludeHourEnd(e.target.value)}
                              className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                            />
                          </div>
                        </div>
                      </div>
                      
                      <div className="border-t border-[var(--color-ec-border)]" style={{ marginTop: '18px', paddingTop: '12px', paddingBottom: '6px' }}>
                        <div className="flex items-center justify-between">
                          <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] transition-colors">Excluir días aleatorios mensuales:</label>
                          <div className="flex items-center gap-2">
                             <input
                               type="number"
                               min="0"
                               max="31"
                               value={randomMonthlyDays}
                               onChange={(e) => setRandomMonthlyDays(Number(e.target.value))}
                               className="w-14 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] focus:border-[var(--color-ec-copper)] outline-none"
                             />
                             <span className="text-[9px] text-[var(--color-ec-text-muted)] opacity-80">días/m</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
 
                {/* Daily Limit */}
                <div style={{ borderBottom: '1px solid var(--color-ec-border)', paddingBottom: '16px', marginBottom: '16px' }}>
                  <button 
                    onClick={() => toggleSection("limit")}
                    style={{
                      width: '100%',
                      paddingTop: '8px',
                      paddingBottom: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                    }}
                    className="hover:text-[var(--color-ec-text-primary)] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                       <span className="text-[10px] font-bold text-[var(--color-ec-text-primary)] uppercase tracking-wider">2) Límite operaciones</span>
                    </div>
                    <span className={`text-xs text-[var(--color-ec-text-muted)] transform transition-transform ${openSections.includes("limit") ? "rotate-180" : ""}`}>▼</span>
                  </button>
                  
                  {openSections.includes("limit") && (
                    <div style={{ paddingBottom: '16px', paddingTop: '6px' }} className="space-y-5 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-[var(--color-ec-text-secondary)]">Máx. trades/día:</span>
                        <input
                          type="number"
                          min="0"
                          value={dailyMaxTrades}
                          onChange={(e) => setDailyMaxTrades(Number(e.target.value))}
                          className="w-16 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-[var(--color-ec-text-secondary)]">Máx trades expuestos/día:</span>
                        <input
                          type="number"
                          min="0"
                          value={maxConcurrentTrades}
                          onChange={(e) => setMaxConcurrentTrades(Number(e.target.value))}
                          className="w-16 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                        />
                      </div>
                    </div>
                  )}
                </div>
 
                {/* Stress Test & Black Swan */}
                <div style={{ borderBottom: '1px solid var(--color-ec-border)', paddingBottom: '16px', marginBottom: '16px' }}>
                  <button 
                    onClick={() => toggleSection("stress")}
                    style={{
                      width: '100%',
                      paddingTop: '8px',
                      paddingBottom: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                    }}
                    className="hover:text-[var(--color-ec-text-primary)] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                       <span className="text-[10px] font-bold text-[var(--color-ec-text-primary)] uppercase tracking-wider">3) Peor escenario y Black Swan</span>
                    </div>
                    <span className={`text-xs text-[var(--color-ec-text-muted)] transform transition-transform ${openSections.includes("stress") ? "rotate-180" : ""}`}>▼</span>
                  </button>
 
                  {openSections.includes("stress") && (
                    <div style={{ paddingBottom: '16px', paddingTop: '6px' }} className="space-y-5 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-[10px] text-[var(--color-ec-text-secondary)] block mb-1">Omitir mejores trades (%):</label>
                          <input
                            type="number"
                            value={skipTopPct}
                            onChange={(e) => setSkipTopPct(Number(e.target.value))}
                            className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] text-[var(--color-ec-text-secondary)] block mb-1">Deslizamiento extra (%):</label>
                          <input
                            type="number"
                            step="0.01"
                            value={extraSlippage}
                            onChange={(e) => setExtraSlippage(Number(e.target.value))}
                            className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                          />
                        </div>
                      </div>
                      
                      <div className="border-t border-[var(--color-ec-border)]" style={{ marginTop: '18px', paddingTop: '12px', paddingBottom: '6px' }}>
                        <div className="flex items-center justify-between mb-2">
                           <label className="text-[10px] font-bold text-[var(--color-ec-text-secondary)] uppercase">Añadir Black Swans Aleatorios</label>
                        </div>
                        <div className="grid grid-cols-2 gap-3 mb-3">
                          <div>
                            <label className="text-[10px] text-[var(--color-ec-text-muted)] block mb-1">Cantidad de Eventos:</label>
                            <input
                              type="number"
                              value={blackSwanCount}
                              onChange={(e) => setBlackSwanCount(Number(e.target.value))}
                              className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] text-[var(--color-ec-text-muted)] block mb-1">Pérdida por Evento (%):</label>
                            <div className="flex items-center gap-2">
                              <span className="text-[11px] font-bold text-[var(--color-ec-loss)] min-w-[35px]">{blackSwanSize}%</span>
                            </div>
                          </div>
                        </div>
                        <input
                          type="range"
                          min="50"
                          max="5000"
                          step="50"
                          value={blackSwanSize}
                          onChange={(e) => setBlackSwanSize(Number(e.target.value))}
                          className="w-full accent-[var(--color-ec-loss)] h-1.5 bg-[var(--color-ec-bg-elevated)] rounded-lg appearance-none cursor-pointer"
                        />
                        <div className="flex justify-between text-[8px] text-[var(--color-ec-text-muted)] mt-1 font-mono">
                          <span>50%</span>
                          <span>5000%</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
 
                {/* Include Expenses Checkbox */}
                {!!monthlyExpenses && monthlyExpenses > 0 && (
                  <div style={{ marginBottom: '16px', paddingTop: '10px', paddingBottom: '10px', borderBottom: '1px solid var(--color-ec-border)' }}>
                    <label className="flex items-center gap-2.5 cursor-pointer group">
                      <input
                        type="checkbox"
                        checked={includeExpensesInWhatIf}
                        onChange={(e) => setIncludeExpensesInWhatIf(e.target.checked)}
                        className="accent-[var(--color-ec-copper)] w-3.5 h-3.5"
                      />
                      <span className="text-[10px] text-[var(--color-ec-text-secondary)] group-hover:text-[var(--color-ec-text-primary)] transition-colors">
                        Incluir costes fijos mensuales (${monthlyExpenses}/mes)
                      </span>
                    </label>
                  </div>
                )}
 
                {/* Final Execution Button */}
                <div style={{ paddingTop: '16px', paddingBottom: '32px', paddingRight: '4px' }}>
                  <button 
                    onClick={handleRunWhatIf}
                    disabled={simLoading}
                    className="w-full bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)] hover:bg-[var(--color-ec-copper-bright)] py-2.5 rounded-md text-[10px] font-sans font-bold uppercase tracking-[0.15em] transform active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <span className="text-sm">{simLoading ? "⏳" : "⚡"}</span>
                    {simLoading ? "Simulando..." : "Ejecutar Simulación What-if"}
                  </button>
                  <p className="text-center text-[8px] text-[var(--color-ec-text-muted)] mt-2 italic opacity-60">
                    * Se aplicarán todas las condiciones seleccionadas simultáneamente
                  </p>
                </div>
              </div>
            </div>

            {/* VERTICAL SEPARATOR */}
            <div style={{ width: '1px', alignSelf: 'stretch', backgroundColor: 'var(--color-ec-border)', flexShrink: 0, marginTop: '16px', marginBottom: '16px' }} />

            {/* RIGHT COLUMN: SIMULATION RESULTS */}
            <div className="flex-1 h-full overflow-y-auto custom-scrollbar" style={{ backgroundColor: 'var(--color-ec-bg-base)', paddingLeft: '24px', paddingRight: '24px', paddingTop: '24px', paddingBottom: '24px', boxSizing: 'border-box' }}>
               <h4 className="text-[10px] font-semibold uppercase text-[var(--color-ec-text-primary)] mb-5 flex items-center gap-2 font-mono tracking-[0.12em]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-ec-copper)]"></span>
                Resultados Simulados
               </h4>
               
               <div className="w-full">
                  <div className="w-full bg-[var(--color-ec-bg-surface)] border border-[var(--color-ec-border)] rounded-lg p-5 mb-6">
                    <div className="grid grid-cols-2 gap-x-10 gap-y-2.5 w-full max-w-[480px]">
                      {[
                        { label: "Días", base: metrics?.total_days ?? 0, sim: getSimValue("total_days") },
                        { label: "Trades", base: metrics?.total_trades ?? 0, sim: getSimValue("total_trades") },
                        { label: "Win Rate", base: `${(metrics?.win_rate_pct ?? 0).toFixed(1)}%`, sim: getSimValue("win_rate_pct", v => `${v.toFixed(1)}%`) },
                        { label: "Profit Factor", base: (metrics?.avg_profit_factor ?? 0).toFixed(3), sim: getSimValue("avg_profit_factor", v => v.toFixed(3)) },
                        { label: "Total Return", base: `${(metrics?.total_return_pct ?? 0).toFixed(2)}%`, sim: getSimValue("total_return_pct", v => `${v.toFixed(2)}%`) },
                        { label: "Max MAE", base: `${(metrics?.max_mae ?? 0).toFixed(2)}%`, sim: getSimValue("max_mae", v => `${v.toFixed(2)}%`) },
                        { label: "Avg Return/Día", base: `${(metrics?.avg_return_per_day_pct ?? 0).toFixed(3)}%`, sim: getSimValue("avg_return_per_day_pct", v => `${v.toFixed(3)}%`) },
                        { label: "Avg R/Día", base: `${(metrics?.avg_r_per_day ?? 0).toFixed(3)}R`, sim: getSimValue("avg_r_per_day", v => `${v.toFixed(3)}R`) },
                        { label: "Sharpe", base: (metrics?.avg_sharpe ?? 0).toFixed(3), sim: getSimValue("avg_sharpe", v => v.toFixed(3)) },
                        { label: "Sortino", base: (metrics?.sortino_ratio ?? 0).toFixed(3), sim: getSimValue("sortino_ratio", v => v.toFixed(3)) },
                        { label: "Calmar", base: (metrics?.calmar_ratio ?? 0).toFixed(3), sim: getSimValue("calmar_ratio", v => v.toFixed(3)) },
                        { label: "Avg Y/U.index", base: (metrics?.avg_r_ui ?? 0).toFixed(2), sim: getSimValue("avg_r_ui", v => v.toFixed(2)) },
                        { label: "DD/Return", base: (metrics?.dd_return_ratio ?? 0).toFixed(3), sim: getSimValue("dd_return_ratio", v => v.toFixed(3)) },
                        { label: "Max DD", base: `${(metrics?.max_drawdown_pct ?? 0).toFixed(2)}%`, sim: getSimValue("max_drawdown_pct", v => `${v.toFixed(2)}%`), danger: true },
                        { label: "Max Consec. Wins", base: metrics?.max_consecutive_wins ?? 0, sim: getSimValue("max_consecutive_wins") },
                        { label: "Max Consec. Losses", base: metrics?.max_consecutive_losses ?? 0, sim: getSimValue("max_consecutive_losses"), danger: true },
                      ].map((m, idx) => (
                        <div key={idx} className="flex items-baseline justify-between py-1.5 text-[11px] border-b border-[var(--color-ec-border)] border-dashed last:border-b-0">
                           <span className="text-[var(--color-ec-text-secondary)] font-medium tracking-tight mr-4">{m.label}:</span>
                           <div className="flex items-center gap-3 font-mono">
                              <span className="text-[10px] text-[var(--color-ec-text-primary)] font-medium">{m.base}</span>
                              <span className={m.danger && m.sim !== "---" ? "text-[var(--color-ec-loss)] font-bold" : "text-[var(--color-ec-copper-bright)] font-bold"}>
                                {m.sim}
                              </span>
                           </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                   {/* What If Equity Curve: Ghost original + simulated */}
                   <div className="mt-10 pt-6 border-t border-dashed border-[var(--border)] w-full">
                      <WhatIfEquityChart
                        originalEquity={globalEquity}
                        originalDrawdown={globalDrawdown}
                        simResult={simResult}
                        initCash={initCash}
                        riskR={riskR}
                        isDarkMode={isDarkMode}
                      />
                    </div>
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
              />
            </div>
          )}
      </div>
    </div>

  );
}

// ---------------------------------------------------------------------------
// What If Equity Chart — Ghost original + simulated
// ---------------------------------------------------------------------------

function WhatIfEquityChart({
  originalEquity,
  originalDrawdown,
  simResult,
  initCash,
  riskR,
  isDarkMode = false,
}: {
  originalEquity: GlobalEquityPoint[];
  originalDrawdown: DrawdownPoint[];
  simResult: WhatIfResult | null;
  initCash: number;
  riskR: number;
  isDarkMode?: boolean;
}) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const ddInstanceRef = useRef<IChartApi | null>(null);

  type WIViewMode = "$" | "%" | "R";
  const [wiViewMode, setWiViewMode] = useState<WIViewMode>("$");

  const transformEquity = (p: GlobalEquityPoint): number => {
    if (wiViewMode === "%") return ((p.value / initCash) - 1) * 100;
    if (wiViewMode === "R") return riskR > 0 ? (p.value - initCash) / riskR : 0;
    return p.value;
  };

  // Drawdown is natively in % from the backend
  const transformDrawdown = (p: DrawdownPoint): number => {
    if (wiViewMode === "$") return (p.value / 100) * initCash;
    if (wiViewMode === "R") return riskR > 0 ? ((p.value / 100) * initCash) / riskR : 0;
    return p.value; // Already in %
  };

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Clean up previous chart
    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }

    // Nothing to render if no simulation result
    if (!simResult || !simResult.global_equity || simResult.global_equity.length === 0) return;

    const container = chartContainerRef.current;

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

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 180,
      layout: {
        background: { type: ColorType.Solid, color: "#16181A" },
        textColor: "#8A8D92",
      },
      grid: {
        vertLines: { color: "#2C2F33" },
        horzLines: { color: "#2C2F33" },
      },
      rightPriceScale: { borderColor: "#2C2F33" },
      timeScale: {
        borderColor: "#2C2F33",
        timeVisible: false,
      },
      localization: {
        timeFormatter,
      },
    });
    chartInstanceRef.current = chart;

    if (originalEquity.length > 0) {
      const ghostSeries = chart.addSeries(LineSeries, {
        color: "rgba(138,141,146,0.3)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        crosshairMarkerVisible: false,
      });
      ghostSeries.setData(
        originalEquity.map((p) => ({
          time: p.time as Time,
          value: transformEquity(p),
        }))
      );
    }

    // 2. What If equity as solid area (using Edgecute copper #D87A3D)
    const simSeries = chart.addSeries(AreaSeries, {
      lineColor: "#D87A3D",
      topColor: "rgba(216,122,61,0.35)",
      bottomColor: "rgba(216,122,61,0.05)",
      lineWidth: 2,
    });
    simSeries.setData(
      simResult.global_equity.map((p: GlobalEquityPoint) => ({
        time: p.time as Time,
        value: transformEquity(p),
      }))
    );

    // --- Drawdown Chart ---
    if (!ddContainerRef.current) return;
    
    if (ddInstanceRef.current) {
      ddInstanceRef.current.remove();
      ddInstanceRef.current = null;
    }
    
    const ddContainer = ddContainerRef.current;
    const ddChart = createChart(ddContainer, {
      width: ddContainer.clientWidth,
      height: 80,
      layout: {
        background: { type: ColorType.Solid, color: "#16181A" },
        textColor: "#8A8D92",
      },
      grid: {
        vertLines: { color: "#2C2F33" },
        horzLines: { color: "#2C2F33" },
      },
      rightPriceScale: { borderColor: "#2C2F33" },
      timeScale: {
        borderColor: "#2C2F33",
        timeVisible: true,
      },
      localization: {
        timeFormatter,
      },
    });
    ddInstanceRef.current = ddChart;

    if (originalDrawdown && originalDrawdown.length > 0) {
      const origDdSeries = ddChart.addSeries(LineSeries, {
        color: "rgba(201,77,63,0.3)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        crosshairMarkerVisible: false,
      });
      origDdSeries.setData(
        originalDrawdown.map((p) => ({
          time: p.time as Time,
          value: transformDrawdown(p),
        }))
      );
    }
    
    if (simResult.global_drawdown) {
      const simDdSeries = ddChart.addSeries(HistogramSeries, {
        color: "rgba(201,77,63,0.5)",
      });
      simDdSeries.setData(
        simResult.global_drawdown.map((p) => ({
          time: p.time as Time,
          value: transformDrawdown(p),
        }))
      );
    }

    // Sync axes
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) ddChart.timeScale().setVisibleLogicalRange(range);
    });
    ddChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) chart.timeScale().setVisibleLogicalRange(range);
    });

    chart.timeScale().fitContent();
    ddChart.timeScale().fitContent();

    const handleResize = () => {
      if (container && ddContainer) {
        chart.applyOptions({ width: container.clientWidth });
        ddChart.applyOptions({ width: ddContainer.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartInstanceRef.current = null;
      if (ddInstanceRef.current) {
        ddInstanceRef.current.remove();
        ddInstanceRef.current = null;
      }
    };
  }, [originalEquity, originalDrawdown, simResult, initCash, riskR, isDarkMode, wiViewMode]);

  if (!simResult) {
    return (
      <div className="h-[140px] w-full bg-[var(--color-ec-bg-surface)] border border-[var(--color-ec-border)] border-dashed rounded-lg flex items-center justify-center relative overflow-hidden">
        <div className="text-center">
          <div className="text-xl opacity-20 mb-2">📊</div>
          <p className="text-[9px] text-[var(--color-ec-text-muted)] opacity-80 uppercase tracking-widest font-mono">
            Ejecuta una simulación para ver la curva comparativa
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3.5">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-[2px] bg-[var(--color-ec-text-muted)] opacity-50" style={{ borderTop: "1px dashed" }}></div>
            <span className="text-[9px] text-[var(--color-ec-text-secondary)] font-mono">Original</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-[2px] bg-[var(--color-ec-copper)]"></div>
            <span className="text-[9px] text-[var(--color-ec-text-primary)] font-mono font-semibold">What If</span>
          </div>
        </div>
        <div className="flex bg-[var(--color-ec-bg-sidebar)] p-0.5 rounded text-[9px] border border-[var(--color-ec-border)]">
          {(["$", "%", "R"] as WIViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setWiViewMode(mode)}
              className={`px-2.5 py-0.5 rounded transition-colors cursor-pointer ${
                wiViewMode === mode
                  ? "bg-[var(--color-ec-bg-elevated)] text-[var(--color-ec-text-high)] shadow-sm font-bold"
                  : "text-[var(--color-ec-text-muted)] hover:text-[var(--color-ec-text-primary)]"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>
      <div ref={chartContainerRef} className="h-[180px] w-full rounded-t border border-b-0 border-[var(--color-ec-border)]" />
      <div ref={ddContainerRef} className="h-[80px] w-full rounded-b border border-[var(--color-ec-border)]" />
    </div>
  );
}

