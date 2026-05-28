"use client";

import { useMemo, useState, useRef, useEffect } from "react";
import {
  createChart,
  LineSeries,
  HistogramSeries,
  ColorType,
  type IChartApi,
  type Time,
} from "lightweight-charts";
import type { DayResult, TradeRecord } from "@/lib/api_backtester";

interface PerformanceTabProps {
  dayResults: DayResult[];
  trades: TradeRecord[];
  initCash: number;
  riskR: number;
  isDarkMode?: boolean;
}

const MONTHS = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
type GridMetric = "PnL %" | "PnL $" | "PnL R" | "Win Rate" | "Trades" | "Profit Factor";

interface CellData {
  pnl: number;
  trades: number;
  wins: number;
  grossProfit: number;
  grossLoss: number;
  dailyReturns: number[];
}

function emptyCell(): CellData {
  return { pnl: 0, trades: 0, wins: 0, grossProfit: 0, grossLoss: 0, dailyReturns: [] };
}

// Helper: Get ISO week string 'YYYY-Www'
function getFormatWeek(dateStr: string) {
  const d = new Date(dateStr);
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${weekNo.toString().padStart(2, "0")}`;
}

export default function PerformanceTab({ dayResults, trades, initCash, riskR, isDarkMode = false }: PerformanceTabProps) {
  const [metric, setMetric] = useState<GridMetric>("PnL %");
  const [rollingWindow, setRollingWindow] = useState(30); // days
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // --- 1. Data Processing for Grid ---
  // We need data structured by Year -> Month
  const gridData = useMemo(() => {
    const yearsMap = new Map<string, Map<string, CellData>>();
    let startYear = 9999;
    let endYear = 0;

    // Initialize all years/months found in trades or dayResults
    const allDates = [...trades.map(t => t.exit_time), ...dayResults.map(d => d.date)];
    for (const d of allDates) {
      if (!d) continue;
      const y = parseInt(d.substring(0, 4));
      if (y < startYear) startYear = y;
      if (y > endYear) endYear = y;
    }

    if (startYear <= endYear) {
      for (let y = startYear; y <= endYear; y++) {
        const mMap = new Map<string, CellData>();
        for (const m of MONTHS) {
          mMap.set(m, emptyCell());
        }
        mMap.set("YTD", emptyCell()); // The total for the year
        yearsMap.set(y.toString(), mMap);
      }
    }

    // Accumulate Daily Returns
    for (const dr of dayResults) {
      const y = dr.date.substring(0, 4);
      const m = dr.date.substring(5, 7);
      if (yearsMap.has(y)) {
        const mMap = yearsMap.get(y)!;
        mMap.get(m)!.dailyReturns.push(dr.total_return_pct || 0);
        mMap.get("YTD")!.dailyReturns.push(dr.total_return_pct || 0);
      }
    }

    // Accumulate Trades (PnL, wins, gross profit/loss)
    for (const t of trades) {
      const d = t.exit_time || t.entry_time;
      if (!d) continue;
      const y = d.substring(0, 4);
      const m = d.substring(5, 7);
      if (yearsMap.has(y)) {
        const mMap = yearsMap.get(y)!;
        const cell = mMap.get(m)!;
        const ytd = mMap.get("YTD")!;

        const isWin = t.pnl > 0;

        cell.trades++;
        ytd.trades++;

        cell.pnl += t.pnl;
        ytd.pnl += t.pnl;

        if (isWin) {
          cell.wins++;
          ytd.wins++;
          cell.grossProfit += t.pnl;
          ytd.grossProfit += t.pnl;
        } else {
          cell.grossLoss += Math.abs(t.pnl);
          ytd.grossLoss += Math.abs(t.pnl);
        }
      }
    }

    return yearsMap;
  }, [dayResults, trades]);

  // Render a specific cell based on the selected metric
  const renderCell = (cell: CellData) => {
    if (cell.dailyReturns.length === 0 && cell.trades === 0) return { text: "—", color: "transparent", tColor: "var(--color-ec-text-muted)" };

    let val = 0;
    let text = "";

    switch (metric) {
      case "PnL %":
        val = cell.dailyReturns.reduce((acc, r) => acc * (1 + r / 100), 1) * 100 - 100;
        text = `${val > 0 ? "+" : ""}${val.toFixed(2)}`;
        break;
      case "PnL $":
        val = cell.pnl;
        text = `${val >= 0 ? "+" : ""}${val.toFixed(0)}`;
        break;
      case "PnL R":
        val = riskR > 0 ? cell.pnl / riskR : 0;
        text = `${val >= 0 ? "+" : ""}${val.toFixed(2)}`;
        break;
      case "Win Rate":
        val = cell.trades > 0 ? (cell.wins / cell.trades) * 100 : 0;
        text = `${val.toFixed(1)}`;
        break;
      case "Trades":
        val = cell.trades;
        text = val.toString();
        break;
      case "Profit Factor":
        val = cell.grossLoss > 0 ? cell.grossProfit / cell.grossLoss : (cell.grossProfit > 0 ? 99 : 0);
        text = val.toFixed(2);
        // Custom coloring for PF: > 1.5 is green, < 1 is red
        let pfColor = "transparent";
        let pfText = "var(--text-data)";
        if (cell.trades > 0) {
          if (val >= 1.5) { pfColor = "rgba(16,185,129,0.08)"; pfText = "#10b981"; }
          else if (val >= 1.0) { pfColor = "rgba(16,185,129,0.03)"; pfText = "#10b981"; }
          else { pfColor = "rgba(239,68,68,0.06)"; pfText = "#ef4444"; }
        }
        return { text, color: pfColor, tColor: pfText };
    }

    // Default coloring for PnL/WinRate
    let bgColor = "transparent";
    let tColor = "var(--text-data)";

    if (metric.startsWith("PnL")) {
      if (val > 0) {
        bgColor = `rgba(16,185,129,${Math.min(val / (metric === "PnL %" ? 15 : 1500), 0.25)})`;
        tColor = "#10b981";
      } else if (val < 0) {
        bgColor = `rgba(239,68,68,${Math.min(Math.abs(val) / (metric === "PnL %" ? 15 : 1500), 0.25)})`;
        tColor = "#ef4444";
      }
    } else if (metric === "Win Rate") {
      if (cell.trades > 0) {
        if (val >= 50) {
          bgColor = `rgba(16,185,129,${Math.min((val - 50) / 80, 0.2)})`;
          tColor = "#10b981";
        } else {
          bgColor = `rgba(239,68,68,${Math.min((50 - val) / 80, 0.2)})`;
          tColor = "#ef4444";
        }
      }
    }

    return { text, color: bgColor, tColor };
  };

  // --- 2. Data Processing for Chart (Rolling Window) ---
  const chartData = useMemo(() => {
    if (!trades.length) return { wrData: [], pfData: [], trData: [] };

    // Sort trades by exit time
    const sortedTrades = [...trades]
      .filter(t => t.exit_time)
      .sort((a, b) => a.exit_time!.localeCompare(b.exit_time!));

    if (!sortedTrades.length) return { wrData: [], pfData: [], trData: [] };

    const wrData: { time: Time, value: number }[] = [];
    const pfData: { time: Time, value: number }[] = [];
    const trData: { time: Time, value: number, color: string }[] = [];

    // Get all unique exit dates
    const uniqueDates = Array.from(new Set(sortedTrades.map(t => t.exit_time!.substring(0, 10)))).sort();

    const windowMs = rollingWindow * 24 * 60 * 60 * 1000;

    for (const dateStr of uniqueDates) {
      const currentDate = new Date(dateStr);
      const startTime = currentDate.getTime() - windowMs;

      // Filter trades in window
      const windowTrades = sortedTrades.filter(t => {
        const tTime = new Date(t.exit_time!).getTime();
        return tTime > startTime && tTime <= currentDate.getTime();
      });

      // Require a minimum number of trades (up to 5) to avoid massive initial spikes in Win Rate & Profit Factor
      const minTradesReq = Math.min(5, Math.ceil(sortedTrades.length / 5));
      if (windowTrades.length < minTradesReq) continue;

      let wins = 0;
      let gp = 0;
      let gl = 0;
      for (const t of windowTrades) {
        if (t.pnl > 0) {
          wins++;
          gp += t.pnl;
        } else {
          gl += Math.abs(t.pnl);
        }
      }

      const wr = (wins / windowTrades.length) * 100;
      const pf = gl > 0 ? gp / gl : (gp > 0 ? 5 : 0);
      const time = (dateStr) as Time;

      wrData.push({ time, value: wr });
      pfData.push({ time, value: pf });
      // For trades histogram, we'll show actual count of trades on that specific day
      const dayTradesCount = sortedTrades.filter(t => t.exit_time!.startsWith(dateStr)).length;
      if (dayTradesCount > 0) {
        trData.push({ time, value: dayTradesCount, color: isDarkMode ? "rgba(148,163,184,0.4)" : "rgba(120,113,108,0.35)" });
      }
    }

    return { wrData, pfData, trData };
  }, [trades, rollingWindow, isDarkMode]);

  // --- 3. Chart Initialization ---
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const bgColor = "#16181A";
    const gridColor = "#2C2F33";
    const textColor = "#A0A3A8";

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 280,
      layout: {
        background: { type: ColorType.Solid, color: bgColor },
        textColor: textColor,
        fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      leftPriceScale: {
        borderVisible: false,
        visible: true,
        scaleMargins: { top: 0.6, bottom: 0 },
      },
      timeScale: { borderVisible: false, timeVisible: true },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    // Series 1: Trades (Left Axis, Histogram)
    const trSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'left',
      color: isDarkMode ? 'rgba(148,163,184,0.4)' : 'rgba(120,113,108,0.35)',
    });
    trSeries.setData(chartData.trData);

    // Series 2: Win Rate (Right Axis, Line)
    const wrSeries = chart.addSeries(LineSeries, {
      priceScaleId: 'right',
      color: '#10b981',
      lineWidth: 2,
    });
    wrSeries.setData(chartData.wrData);

    // Series 3: Profit Factor
    const pfSeries = chart.addSeries(LineSeries, {
      priceScaleId: 'pfScale',
      color: '#d97706',
      lineWidth: 2,
    });
    chart.priceScale('pfScale').applyOptions({
      visible: false,
      scaleMargins: { top: 0.1, bottom: 0.1 }
    });
    pfSeries.setData(chartData.pfData);

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [chartData, isDarkMode]);


  if (!dayResults.length) {
    return <p className="text-sm text-[var(--muted)]">Sin resultados</p>;
  }

  const years = Array.from(gridData.keys()).sort((a, b) => parseInt(b) - parseInt(a)); // Descending years

  return (
    <div className="space-y-12" style={{ paddingTop: 24 }}>

      {/* MONTHLY RETURNS — no card wrapper */}
      <div>
        <div className="flex items-center justify-between mb-5">
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-ec-text-primary)' }}>
            Monthly Returns
          </span>
          <div className="flex items-center gap-2.5 text-[10px]">
            {(["PnL %", "PnL $", "PnL R", "Win Rate", "Trades", "Profit Factor"] as GridMetric[]).map((m) => (
              <button
                key={m}
                onClick={() => setMetric(m)}
                className={`px-2.5 py-1 rounded-sm transition-all font-mono ${metric === m
                  ? "bg-[var(--foreground)] text-[var(--background)] font-semibold"
                  : "text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)]"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-center" style={{ borderCollapse: 'separate', borderSpacing: 0 }}>
            <thead>
              <tr>
                <th className="px-2 py-2 text-[10px] font-semibold uppercase tracking-wider text-left" style={{ borderBottom: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-primary)' }}>Year</th>
                {MONTH_NAMES.map(m => (
                  <th key={m} className="px-1 py-2 text-[10px] font-semibold uppercase tracking-wider" style={{ borderBottom: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-primary)' }}>{m}</th>
                ))}
                <th className="px-2 py-2 text-[10px] font-bold uppercase tracking-wider" style={{ borderBottom: '0.5px solid var(--color-ec-border)', borderLeft: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-high)' }}>YTD</th>
              </tr>
            </thead>
            <tbody>
              {years.map(year => {
                const mMap = gridData.get(year)!;
                const ytdCell = renderCell(mMap.get("YTD")!);
                return (
                  <tr key={year} className="group">
                    <td className="px-2 py-2.5 text-[12px] font-bold font-mono text-left" style={{ borderBottom: '0.5px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)', color: 'var(--color-ec-text-high)' }}>{year}</td>
                    {MONTHS.map(m => {
                      const c = renderCell(mMap.get(m)!);
                      return (
                        <td
                          key={m}
                          className="px-1 py-2.5 font-mono text-[12px] transition-colors"
                          style={{
                            backgroundColor: c.color,
                            color: c.tColor,
                            borderBottom: '0.5px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)',
                          }}
                        >
                          {c.text}
                        </td>
                      )
                    })}
                    <td
                      className="px-2 py-2.5 font-mono text-[12px] font-bold"
                      style={{
                        backgroundColor: ytdCell.color,
                        color: ytdCell.tColor,
                        borderLeft: '0.5px solid var(--color-ec-border)',
                        borderBottom: '0.5px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)',
                      }}
                    >
                      {ytdCell.text}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ROLLING METRICS — no card wrapper */}
      <div style={{ borderTop: '0.5px solid var(--color-ec-border)', paddingTop: 20, marginTop: 20 }}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-6">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-ec-text-primary)' }}>
              Rolling {rollingWindow}d
            </span>
            <div className="flex items-center gap-4 text-[9px] font-mono">
              <span className="flex items-center gap-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>
                <span className="inline-block w-3 h-[2px] rounded-full" style={{ backgroundColor: isDarkMode ? 'rgba(148,163,184,0.6)' : 'rgba(120,113,108,0.5)' }}></span>
                trades/d
              </span>
              <span className="flex items-center gap-1.5" style={{ color: '#10b981' }}>
                <span className="inline-block w-3 h-[2px] rounded-full bg-emerald-500"></span>
                win rate
              </span>
              <span className="flex items-center gap-1.5" style={{ color: '#d97706' }}>
                <span className="inline-block w-3 h-[2px] rounded-full bg-amber-600"></span>
                profit factor
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[9px] font-mono uppercase" style={{ color: 'var(--color-ec-text-primary)' }}>window</span>
            <input
              type="range"
              min="7"
              max="90"
              step="1"
              value={rollingWindow}
              onChange={(e) => setRollingWindow(parseInt(e.target.value))}
              className="w-24 accent-[var(--foreground)] h-[2px]"
              style={{ opacity: 0.6 }}
            />
            <span className="text-[10px] font-bold font-mono min-w-[28px] text-right" style={{ color: 'var(--color-ec-text-high)' }}>{rollingWindow}</span>
          </div>
        </div>
        <div ref={chartContainerRef} style={{ width: "100%", height: "280px", marginTop: 8 }} />
      </div>

    </div>
  );
}
