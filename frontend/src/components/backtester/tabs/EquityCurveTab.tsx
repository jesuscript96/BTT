"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import {
  createChart,
  AreaSeries,
  HistogramSeries,
  BaselineSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { GlobalEquityPoint, DrawdownPoint, TradeRecord, AggregateMetrics, WhatIfResult } from "@/lib/api_backtester";
import { runWhatIf } from "@/lib/api_backtester";


interface EquityCurveTabProps {
  globalEquity: GlobalEquityPoint[];
  globalDrawdown: DrawdownPoint[];
  trades: any[];
  metrics: Record<string, any> | null;
  initCash: number;
  riskR: number;
  monthlyExpenses?: number;
  isDarkMode?: boolean;
}

export default function EquityCurveTab({ globalEquity, globalDrawdown, trades, metrics, initCash, riskR, monthlyExpenses, isDarkMode = false }: EquityCurveTabProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const ddChartRef = useRef<IChartApi | null>(null);

  type ViewMode = "$" | "%" | "R";
  const [viewMode, setViewMode] = useState<ViewMode>("$");
  const [activeMainTab, setActiveMainTab] = useState<"equity" | "whatif">("equity");
  const [simLoading, setSimLoading] = useState(false);
  const [simResult, setSimResult] = useState<WhatIfResult | null>(null);

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
    if (!containerRef.current || !globalEquity.length) return;

    // Split container into two divs for the two charts
    containerRef.current.innerHTML = `
      <div id="equity-chart-container" style="width: 100%; height: 400px; margin-bottom: 1rem;"></div>
      <div id="dd-chart-container" style="width: 100%; height: 150px;"></div>
    `;

    const equityContainer = containerRef.current.querySelector("#equity-chart-container") as HTMLElement;
    const ddContainer = containerRef.current.querySelector("#dd-chart-container") as HTMLElement;

    // --- Equity Chart ---
    const chart = createChart(equityContainer, {
      width: equityContainer.clientWidth,
      height: 400,
      layout: {
        background: { color: isDarkMode ? "#18181a" : "#fafaf7" },
        textColor: isDarkMode ? "#f8fafc" : "#333"
      },
      grid: {
        vertLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
        horzLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
      },
      rightPriceScale: { borderColor: isDarkMode ? "#334155" : "#e2e8f0" },
      timeScale: { borderColor: isDarkMode ? "#334155" : "#e2e8f0", timeVisible: true },
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
    if (monthlyExpenses && monthlyExpenses > 0 && globalEquity.length > 0) {
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
        height: 150,
        layout: {
          background: { color: isDarkMode ? "#18181a" : "#fafaf7" },
          textColor: isDarkMode ? "#f8fafc" : "#333"
        },
        grid: {
          vertLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
          horzLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
        },
        rightPriceScale: { borderColor: isDarkMode ? "#334155" : "#e2e8f0" },
        timeScale: { borderColor: isDarkMode ? "#334155" : "#e2e8f0", timeVisible: true },
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
            // Since drawdown is negative %, (p.value/100) * initCash gives $ drawdown 
            // We use the account high water mark, but roughly p.value% of current is close enough
            // Since we don't have the HWM per day, we'll approximate absolute drawdown displacement
            // Actually, risk_r view for drawdown is just % DD converted to R units via initCash
            val = riskR > 0 ? ((p.value / 100) * initCash) / riskR : 0;
          } else if (viewMode === "$") {
            val = (p.value / 100) * initCash;
          }
          return { time: p.time as Time, value: val };
        })
      );

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
  }, [globalEquity, globalDrawdown, openPositions, viewMode, initCash, riskR, monthlyExpenses, isDarkMode, activeMainTab]);

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
    <div className="flex flex-col h-[675px]">
      {/* MAIN TAB SWITCHER */}
      <div className="px-1 flex items-center h-[30px]" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex h-full">
          <button
            onClick={() => setActiveMainTab("equity")}
            className={`px-3 flex items-center text-[10px] font-semibold uppercase tracking-[0.12em] transition-all border-b-2 h-full ${
              activeMainTab === "equity"
                ? "text-[var(--foreground)] border-[var(--foreground)]"
                : "text-[var(--muted)] border-transparent hover:text-[var(--foreground)]"
            }`}
          >
            Equity Curve
          </button>
          <button
            onClick={() => setActiveMainTab("whatif")}
            className={`px-3 flex items-center text-[10px] font-semibold uppercase tracking-[0.12em] transition-all border-b-2 h-full ${
              activeMainTab === "whatif"
                ? "text-[var(--foreground)] border-[var(--foreground)]"
                : "text-[var(--muted)] border-transparent hover:text-[var(--foreground)]"
            }`}
          >
            What if...
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeMainTab === "equity" ? (
          <div key="equity-tab" className="px-4 pt-4 pb-2">
            {globalDrawdown && globalDrawdown.length > 0 && (
              <div className="mb-3 flex items-center justify-between">
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide font-mono">
                      Max DD
                    </span>
                    <span className="text-[12px] font-bold font-mono text-[var(--danger)]">
                      {ddDisplay}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide font-mono">
                      Max Profit
                    </span>
                    <span className="text-[12px] font-bold font-mono text-[var(--success)]">
                      {profitDisplay}
                    </span>
                  </div>
                  {maxProfitWithExpenses !== null && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide font-mono">
                        Max Profit c/ Gastos
                      </span>
                      <span className="text-[12px] font-bold font-mono text-[var(--success)]">
                        {profitWithExpensesDisplay}
                      </span>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex p-0.5 text-[10px] ml-2">
                    {(["$", "%", "R"] as ViewMode[]).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setViewMode(mode)}
                        className={`px-2.5 py-1 font-mono transition-colors ${
                          viewMode === mode
                            ? "text-[var(--foreground)] font-bold"
                            : "text-[var(--muted)] hover:text-[var(--foreground)]"
                        }`}
                        style={viewMode === mode ? { borderBottom: '2px solid var(--foreground)' } : { borderBottom: '2px solid transparent' }}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
            <div ref={containerRef} className="h-[410px] w-full" />
            <div className="border-t border-[var(--border)] pt-2 mt-2">
               <div ref={ddContainerRef} className="h-[130px] w-full" />
            </div>
          </div>
        ) : (
          <div key="whatif-tab" className="flex h-full overflow-hidden">
            {/* LEFT COLUMN: SIMULATION SETTINGS */}
            <div className="w-1/2 flex flex-col border-r border-[var(--border)]">
              <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
                {/* Temporal Settings */}
                <div className="border-b border-[var(--border)] transition-all">
                  <button 
                    onClick={() => toggleSection("temporal")}
                    className="w-full px-4 py-3 flex items-center justify-between hover:bg-[var(--sidebar-bg)] transition-colors group"
                  >
                    <div className="flex items-center gap-2">
                       <span className="text-[10px] font-bold text-[var(--muted)] uppercase tracking-wider">1) Espacios Temporales</span>
                    </div>
                    <span className={`text-xs text-[var(--muted)] transform transition-transform ${openSections.includes("temporal") ? "rotate-180" : ""}`}>▼</span>
                  </button>
                  
                  {openSections.includes("temporal") && (
                    <div className="px-4 pb-4 space-y-4 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div>
                        <label className="text-[10px] font-medium text-[var(--muted)] mb-1.5 block">Excluir Días de la Semana</label>
                        <div className="flex gap-1">
                          {["L", "M", "X", "J", "V"].map((day, idx) => (
                            <button
                              key={day}
                              onClick={() => {
                                setExcludeDays(prev => prev.includes(idx) ? prev.filter(d => d !== idx) : [...prev, idx]);
                              }}
                              className={`flex-1 py-1.5 rounded text-[10px] font-bold border transition-all ${
                                excludeDays.includes(idx)
                                  ? "bg-red-100 border-red-200 text-red-600 shadow-inner"
                                  : "bg-[var(--card-bg)] border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)]"
                              }`}
                            >
                              {day}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <label className="text-[10px] font-medium text-[var(--muted)] mb-1.5 block">Excluir Meses del Año</label>
                        <div className="grid grid-cols-6 gap-1">
                          {["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"].map((month, idx) => (
                            <button
                              key={month}
                              onClick={() => {
                                setExcludeMonths(prev => prev.includes(idx) ? prev.filter(m => m !== idx) : [...prev, idx]);
                              }}
                              className={`py-1 rounded text-[9px] font-medium border transition-all ${
                                excludeMonths.includes(idx)
                                  ? "bg-red-100 border-red-200 text-red-600 shadow-inner"
                                  : "bg-[var(--card-bg)] border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)]"
                              }`}
                            >
                              {month}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <label className="text-[10px] font-medium text-[var(--muted)] mb-1.5 block">Excluir Rango de Horas</label>
                        <div className="flex items-center gap-4">
                          <div className="flex-1">
                            <label className="text-[10px] font-medium text-[var(--muted)] mb-1 block uppercase opacity-70">Desde:</label>
                            <input
                              type="time"
                              value={excludeHourStart}
                              onChange={(e) => setExcludeHourStart(e.target.value)}
                              className="w-full bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-[11px] outline-none focus:border-[var(--accent)]"
                            />
                          </div>
                          <div className="flex-1">
                            <label className="text-[10px] font-medium text-[var(--muted)] mb-1 block uppercase opacity-70">Hasta:</label>
                            <input
                              type="time"
                              value={excludeHourEnd}
                              onChange={(e) => setExcludeHourEnd(e.target.value)}
                              className="w-full bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-[11px] outline-none focus:border-[var(--accent)]"
                            />
                          </div>
                        </div>
                      </div>
                      
                      <div className="pt-3 mt-1 border-t border-[var(--border)]">
                        <div className="flex items-center justify-between">
                          <label className="text-[10px] font-medium text-[var(--muted)] hover:text-[var(--foreground)] transition-colors">Días aleatorios mensuales:</label>
                          <div className="flex items-center gap-2">
                             <input
                               type="number"
                               min="0"
                               max="31"
                               value={randomMonthlyDays}
                               onChange={(e) => setRandomMonthlyDays(Number(e.target.value))}
                               className="w-14 bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-[11px] text-center focus:border-[var(--accent)] outline-none"
                             />
                             <span className="text-[9px] text-[var(--muted)] opacity-60">días/m</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Daily Limit */}
                <div className="border-b border-[var(--border)]">
                  <button 
                    onClick={() => toggleSection("limit")}
                    className="w-full px-4 py-3 flex items-center justify-between hover:bg-[var(--sidebar-bg)] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                       <span className="text-[10px] font-bold text-[var(--muted)] uppercase tracking-wider">2) Límite operaciones</span>
                    </div>
                    <span className={`text-xs text-[var(--muted)] transform transition-transform ${openSections.includes("limit") ? "rotate-180" : ""}`}>▼</span>
                  </button>
                  
                  {openSections.includes("limit") && (
                    <div className="px-4 pb-4 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-[var(--muted)]">Máx. trades/día:</span>
                        <input
                          type="number"
                          min="0"
                          value={dailyMaxTrades}
                          onChange={(e) => setDailyMaxTrades(Number(e.target.value))}
                          className="w-16 bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-[11px] text-center outline-none focus:border-[var(--accent)]"
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-[var(--muted)]">Máx trades expuestos/día:</span>
                        <input
                          type="number"
                          min="0"
                          value={maxConcurrentTrades}
                          onChange={(e) => setMaxConcurrentTrades(Number(e.target.value))}
                          className="w-16 bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-[11px] text-center outline-none focus:border-[var(--accent)]"
                        />
                      </div>
                    </div>
                  )}
                       </div>

                {/* Stress Test & Black Swan */}
                <div className="border-b border-[var(--border)]">
                  <button 
                    onClick={() => toggleSection("stress")}
                    className="w-full px-4 py-3 flex items-center justify-between hover:bg-[var(--sidebar-bg)] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                       <span className="text-[10px] font-bold text-[var(--muted)] uppercase tracking-wider">3) Peor escenario y Black Swan</span>
                    </div>
                    <span className={`text-xs text-[var(--muted)] transform transition-transform ${openSections.includes("stress") ? "rotate-180" : ""}`}>▼</span>
                  </button>

                  {openSections.includes("stress") && (
                    <div className="px-4 pb-4 space-y-4 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-[10px] text-[var(--muted)] block mb-1">Omitir mejores trades (%):</label>
                          <input
                            type="number"
                            value={skipTopPct}
                            onChange={(e) => setSkipTopPct(Number(e.target.value))}
                            className="w-full bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-xs"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] text-[var(--muted)] block mb-1">Deslizamiento extra (%):</label>
                          <input
                            type="number"
                            step="0.01"
                            value={extraSlippage}
                            onChange={(e) => setExtraSlippage(Number(e.target.value))}
                            className="w-full bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-xs"
                          />
                        </div>
                      </div>
                      
                      <div className="border-t border-[var(--border)] pt-3">
                        <div className="flex items-center justify-between mb-2">
                           <label className="text-[10px] font-bold text-[var(--muted)] uppercase">Añadir Black Swans Aleatorios</label>
                        </div>
                        <div className="grid grid-cols-2 gap-3 mb-3">
                          <div>
                            <label className="text-[10px] text-[var(--muted)] block mb-1">Cantidad de Eventos:</label>
                            <input
                              type="number"
                              value={blackSwanCount}
                              onChange={(e) => setBlackSwanCount(Number(e.target.value))}
                              className="w-full bg-[var(--card-bg)] border border-[var(--border)] rounded px-2 py-1 text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] text-[var(--muted)] block mb-1">Pérdida por Evento (%):</label>
                            <div className="flex items-center gap-2">
                              <span className="text-[11px] font-bold text-red-500 min-w-[35px]">{blackSwanSize}%</span>
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
                          className="w-full accent-red-500 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                        />
                        <div className="flex justify-between text-[8px] text-[var(--muted)] mt-1 font-mono">
                          <span>50%</span>
                          <span>5000%</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Include Expenses Checkbox */}
                {!!monthlyExpenses && monthlyExpenses > 0 && (
                  <div className="px-4 py-3 border-b border-[var(--border)]">
                    <label className="flex items-center gap-2 cursor-pointer group">
                      <input
                        type="checkbox"
                        checked={includeExpensesInWhatIf}
                        onChange={(e) => setIncludeExpensesInWhatIf(e.target.checked)}
                        className="accent-[var(--accent)] w-3.5 h-3.5"
                      />
                      <span className="text-[10px] text-[var(--muted)] group-hover:text-[var(--foreground)] transition-colors">
                        Incluir costes fijos mensuales (${monthlyExpenses}/mes)
                      </span>
                    </label>
                  </div>
                )}

                {/* Final Execution Button */}
                <div className="p-5 mt-auto">
                  <button 
                    onClick={handleRunWhatIf}
                    disabled={simLoading}
                    className="w-full bg-[var(--foreground)] text-[var(--background)] py-2 text-[10px] font-mono font-semibold uppercase tracking-[0.15em] hover:opacity-80 transform active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <span className="text-sm">{simLoading ? "⏳" : "⚡"}</span>
                    {simLoading ? "Simulando..." : "Ejecutar Simulación What-if"}
                  </button>
                  <p className="text-center text-[8px] text-[var(--muted)] mt-2 italic opacity-60">
                    * Se aplicarán todas las condiciones seleccionadas simultáneamente
                  </p>
                </div>
              </div>
            </div>

            {/* RIGHT COLUMN: SIMULATION RESULTS */}
            <div className="w-1/2 h-full overflow-y-auto px-5 py-4 custom-scrollbar">
               <h4 className="text-[10px] font-semibold uppercase text-[var(--muted)] mb-4 flex items-center gap-2 font-mono tracking-[0.12em]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--muted)]"></span>
                Resultados Simulados
               </h4>
               
               <div className="w-full">
                  <div className="grid grid-cols-2 gap-x-10 gap-y-1.5 w-full max-w-[480px]">
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
                       { label: "R²", base: (metrics?.r_squared ?? 0).toFixed(4), sim: getSimValue("r_squared", v => v.toFixed(4)) },
                       { label: "DD/Return", base: (metrics?.dd_return_ratio ?? 0).toFixed(3), sim: getSimValue("dd_return_ratio", v => v.toFixed(3)) },
                       { label: "Max DD", base: `${(metrics?.max_drawdown_pct ?? 0).toFixed(2)}%`, sim: getSimValue("max_drawdown_pct", v => `${v.toFixed(2)}%`), danger: true },
                       { label: "Max Consec. Wins", base: metrics?.max_consecutive_wins ?? 0, sim: getSimValue("max_consecutive_wins") },
                       { label: "Max Consec. Losses", base: metrics?.max_consecutive_losses ?? 0, sim: getSimValue("max_consecutive_losses"), danger: true },
                     ].map((m, idx) => (
                       <div key={idx} className="flex items-baseline justify-between py-0.5 text-[11px]">
                          <span className="text-[var(--muted)] font-medium tracking-tight mr-4">{m.label}:</span>
                          <div className="flex items-center gap-3 font-mono">
                             <span className="opacity-25 text-[10px]">{m.base}</span>
                             <span className={m.danger && m.sim !== "---" ? "text-red-600 font-bold" : "text-[var(--accent)] font-bold"}>
                               {m.sim}
                             </span>
                          </div>
                       </div>
                     ))}
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

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 180,
      layout: {
        background: { color: isDarkMode ? "#18181a" : "#fafaf7" },
        textColor: isDarkMode ? "#94a3b8" : "#64748b",
      },
      grid: {
        vertLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
        horzLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
      },
      rightPriceScale: { borderColor: isDarkMode ? "#334155" : "#e2e8f0" },
      timeScale: {
        borderColor: isDarkMode ? "#334155" : "#e2e8f0",
        timeVisible: false,
      },
    });
    chartInstanceRef.current = chart;

    // 1. Original equity as ghost (faded, dashed)
    if (originalEquity.length > 0) {
      const ghostSeries = chart.addSeries(LineSeries, {
        color: isDarkMode ? "rgba(148,163,184,0.3)" : "rgba(100,116,139,0.25)",
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

    // 2. What If equity as solid area
    const simSeries = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      topColor: "rgba(59,130,246,0.35)",
      bottomColor: "rgba(59,130,246,0.05)",
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
        background: { color: isDarkMode ? "#18181a" : "#fafaf7" },
        textColor: isDarkMode ? "#94a3b8" : "#64748b",
      },
      grid: {
        vertLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
        horzLines: { color: isDarkMode ? "#303033" : "#f0f0f0" },
      },
      rightPriceScale: { borderColor: isDarkMode ? "#334155" : "#e2e8f0" },
      timeScale: {
        borderColor: isDarkMode ? "#334155" : "#e2e8f0",
        timeVisible: true,
      },
    });
    ddInstanceRef.current = ddChart;

    if (originalDrawdown && originalDrawdown.length > 0) {
      const origDdSeries = ddChart.addSeries(LineSeries, {
        color: isDarkMode ? "rgba(220,38,38,0.3)" : "rgba(220,38,38,0.25)",
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
        color: "rgba(220,38,38,0.5)",
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
      <div className="h-[140px] w-full bg-[var(--background)] flex items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 border border-[var(--border)] border-dashed opacity-20"></div>
        <div className="text-center">
          <div className="text-xl opacity-10 mb-2">📊</div>
          <p className="text-[8px] text-[var(--muted)] opacity-40 uppercase tracking-widest">
            Ejecuta una simulación para ver la curva comparativa
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-[2px] bg-gray-400 opacity-50" style={{ borderTop: "1px dashed" }}></div>
            <span className="text-[9px] text-[var(--muted)]">Original</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-[2px] bg-blue-500"></div>
            <span className="text-[9px] text-[var(--muted)]">What If</span>
          </div>
        </div>
        <div className="flex bg-[var(--sidebar-bg)] p-0.5 rounded text-[9px] border border-[var(--border)]">
          {(["$", "%", "R"] as WIViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setWiViewMode(mode)}
              className={`px-2 py-0.5 rounded transition-colors ${
                wiViewMode === mode
                  ? "bg-[var(--card-bg)] text-[var(--foreground)] shadow-sm font-bold"
                  : "text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>
      <div ref={chartContainerRef} className="h-[180px] w-full rounded-t border border-b-0 border-[var(--border)]" />
      <div ref={ddContainerRef} className="h-[80px] w-full rounded-b border border-[var(--border)]" />
    </div>
  );
}

