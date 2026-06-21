"use client";

import { useMemo, useState, useEffect, useRef } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
  ScatterChart,
  Scatter,
} from "recharts";
import {
  createChart,
  AreaSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  ColorType,
  type IChartApi,
  type Time,
} from "lightweight-charts";
import type { TradeRecord, DayResult, GlobalEquityPoint, DrawdownPoint, AggregateMetrics, WhatIfResult } from "@/lib/api_backtester";
import { runWhatIf } from "@/lib/api_backtester";
import RollingEVChart from "@/components/backtester/RollingEVChart";
import InfoTooltip from "@/components/backtester/InfoTooltip";

interface ChartsTabProps {
  trades: TradeRecord[];
  dayResults: DayResult[];
  globalEquity: any[];
  globalDrawdown: any[];
  metrics: Record<string, any> | null;
  initCash: number;
  riskR: number;
  monthlyExpenses?: number;
  isDarkMode?: boolean;
}

const WEEKDAY_NAMES = ["Lun", "Mar", "Mie", "Jue", "Vie"];

/**
 * Enhanced Descriptive Statistics
 */
function calculateEnhancedStats(arr: number[]) {
  if (!arr.length) return { n: 0, mean: 0, median: 0, stdDev: 0, max: 0, min: 0, skewness: 0, kurtosis: 0, q1: 0, q3: 0, range: 0, iqr: 0 };

  const sorted = [...arr].sort((a, b) => a - b);
  const n = arr.length;
  const mean = arr.reduce((a, b) => a + b, 0) / n;

  // Percentiles
  const getPercentile = (p: number) => {
    const pos = (n - 1) * p;
    const base = Math.floor(pos);
    const rest = pos - base;
    if (sorted[base + 1] !== undefined) {
      return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
    } else {
      return sorted[base];
    }
  };

  const median = getPercentile(0.5);
  const q1 = getPercentile(0.25);
  const q3 = getPercentile(0.75);
  const iqr = q3 - q1;
  const max = sorted[n - 1];
  const min = sorted[0];
  const range = max - min;

  // Standard Deviation
  const variance = arr.reduce((s, v) => s + Math.pow(v - mean, 2), 0) / n;
  const stdDev = Math.sqrt(variance);

  // Skewness & Kurtosis
  let skewSum = 0;
  let kurtSum = 0;
  if (stdDev > 0) {
    for (const x of arr) {
      skewSum += Math.pow((x - mean) / stdDev, 3);
      kurtSum += Math.pow((x - mean) / stdDev, 4);
    }
  }
  const skewness = skewSum / n;
  const kurtosis = (kurtSum / n) - 3; // Excess Kurtosis

  return { n, mean, median, stdDev, max, min, skewness, kurtosis, q1, q3, range, iqr };
}

export default function ChartsTab({
  trades,
  dayResults,
  globalEquity,
  globalDrawdown,
  metrics,
  initCash,
  riskR = 100,
  monthlyExpenses = 0,
  isDarkMode = false,
}: ChartsTabProps) {

  const gridColor = "#2C2F33";
  const tickColor = "#ffffff";
  const tooltipBg = "#1C1E21";
  const barPositiveFill = "#10b981";
  const barPositiveStroke = "transparent";
  const barNegativeFill = "#ef4444";
  const barNegativeStroke = "transparent";

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
  const [simLoading, setSimLoading] = useState(false);
  const [simResult, setSimResult] = useState<WhatIfResult | null>(null);

  const toggleSection = (id: string) => {
    setOpenSections(prev =>
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    );
  };

  const handleRunWhatIf = async () => {
    if (!trades || trades.length === 0) return;
    setSimLoading(true);
    try {
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

  const pnlDistribution = useMemo(() => {
    const pnlPctCoords = trades.map(t => t.return_pct).filter((v): v is number => v !== undefined && v !== null);
    if (!pnlPctCoords.length) return { data: [], stats: null };

    const minPnl = Math.min(...pnlPctCoords);
    const maxPnl = Math.max(...pnlPctCoords);
    const range = Math.max(0.1, maxPnl - minPnl);

    let bucketSize = 0.05;
    if (range > 100) bucketSize = 5;
    else if (range > 50) bucketSize = 2;
    else if (range > 20) bucketSize = 1;
    else if (range > 10) bucketSize = 0.5;
    else if (range > 5) bucketSize = 0.25;
    else if (range > 2) bucketSize = 0.1;

    const minBucket = Math.floor(minPnl / bucketSize) * bucketSize;
    const maxBucket = Math.ceil(maxPnl / bucketSize) * bucketSize;

    const buckets = new Map<number, number>();
    for (let b = minBucket; b <= maxBucket + bucketSize / 2; b += bucketSize) {
      buckets.set(parseFloat(b.toFixed(2)), 0);
    }

    for (const p of pnlPctCoords) {
      const bucket = parseFloat((Math.floor(p / bucketSize) * bucketSize).toFixed(2));
      if (buckets.has(bucket)) {
        buckets.set(bucket, buckets.get(bucket)! + 1);
      }
    }

    const data = Array.from(buckets.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([val, count]) => ({
        label: `${val > 0 ? '+' : ''}${val.toFixed(2)}%`,
        value: count,
        num: val
      }))
      .filter(d => Math.abs(d.num) <= 100);

    const stats = calculateEnhancedStats(pnlPctCoords);
    return { data, stats };
  }, [trades]);

  const consecutiveRuns = useMemo(() => {
    let currentRun = 0;
    let isWinning: boolean | null = null;
    const winRuns: number[] = [];
    const lossRuns: number[] = [];

    for (const t of trades) {
      if (t.pnl > 0) {
        if (isWinning === true) currentRun++;
        else {
          if (isWinning === false && currentRun > 0) lossRuns.push(currentRun);
          isWinning = true;
          currentRun = 1;
        }
      } else if (t.pnl < 0) {
        if (isWinning === false) currentRun++;
        else {
          if (isWinning === true && currentRun > 0) winRuns.push(currentRun);
          isWinning = false;
          currentRun = 1;
        }
      }
    }
    if (isWinning === true && currentRun > 0) winRuns.push(currentRun);
    if (isWinning === false && currentRun > 0) lossRuns.push(currentRun);

    const winFreq = new Map<number, number>();
    const lossFreq = new Map<number, number>();
    for (const r of winRuns) winFreq.set(r, (winFreq.get(r) || 0) + 1);
    for (const r of lossRuns) lossFreq.set(r, (lossFreq.get(r) || 0) + 1);

    const maxRun = Math.max(...winRuns, ...lossRuns, 0);
    const data = [];
    const displayMax = Math.min(12, maxRun);
    for (let i = 1; i <= displayMax; i++) {
      data.push({
        length: i.toString(),
        winRuns: winFreq.get(i) || 0,
        lossRuns: lossFreq.get(i) || 0,
        num: i
      });
    }

    return {
      data,
      winStats: calculateEnhancedStats(winRuns),
      lossStats: calculateEnhancedStats(lossRuns)
    };
  }, [trades]);

  const evByTime30Min = useMemo(() => {
    const timeMap = new Map<string, { total: number; count: number }>();

    for (const t of trades) {
      const d = new Date(t.entry_time);
      const h = d.getHours();
      const m = d.getMinutes();
      const halfHour = m < 30 ? "00" : "30";
      const key = `${String(h).padStart(2, '0')}:${halfHour}`;

      if (!timeMap.has(key)) timeMap.set(key, { total: 0, count: 0 });
      const entry = timeMap.get(key)!;
      entry.total += t.pnl;
      entry.count++;
    }

    return Array.from(timeMap.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([time, data]) => ({
        time,
        ev: data.count > 0 ? data.total / data.count : 0,
        count: data.count,
      }));
  }, [trades]);

  const evByDay = useMemo(() => {
    const dayMap = new Map<number, { total: number; count: number }>();
    for (const t of trades) {
      const d = t.entry_weekday;
      if (d > 4) continue;
      if (!dayMap.has(d)) dayMap.set(d, { total: 0, count: 0 });
      const m = dayMap.get(d)!;
      m.total += t.pnl;
      m.count++;
    }
    return [0, 1, 2, 3, 4].map((d) => {
      const data = dayMap.get(d) || { total: 0, count: 0 };
      return {
        day: WEEKDAY_NAMES[d],
        ev: data.count > 0 ? data.total / data.count : 0,
        count: data.count,
      };
    });
  }, [trades]);

  const { gapVsPnl, gapRegression, gapRegressionLine } = useMemo(() => {
    const points: { x: number; y: number }[] = [];
    for (const d of dayResults) {
      if (d.gap_pct !== undefined && d.gap_pct !== null && d.total_return_pct !== undefined && d.total_return_pct !== null) {
        points.push({ x: d.gap_pct, y: d.total_return_pct });
      }
    }
    if (points.length < 2) return { gapVsPnl: points, gapRegression: null, gapRegressionLine: null };

    // Linear regression
    const n = points.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    for (const p of points) { sumX += p.x; sumY += p.y; sumXY += p.x * p.y; sumXX += p.x * p.x; }
    const denom = n * sumXX - sumX * sumX;
    if (denom === 0) return { gapVsPnl: points, gapRegression: null, gapRegressionLine: null };

    const slope = (n * sumXY - sumX * sumY) / denom;
    const intercept = (sumY - slope * sumX) / n;
    const meanY = sumY / n;
    let ssTot = 0, ssRes = 0;
    for (const p of points) { ssTot += (p.y - meanY) ** 2; ssRes += (p.y - (slope * p.x + intercept)) ** 2; }
    const r2 = ssTot > 0 ? 1 - ssRes / ssTot : 0;

    const minX = Math.min(...points.map(p => p.x));
    const maxX = Math.max(...points.map(p => p.x));
    const lineData = [
      { x: minX, y: slope * minX + intercept },
      { x: maxX, y: slope * maxX + intercept },
    ];

    return { gapVsPnl: points, gapRegression: { r2, slope, intercept }, gapRegressionLine: lineData };
  }, [trades]);

  if (!trades.length) {
    return <p className="text-sm text-[var(--muted)] pr-6">Sin trades para analizar</p>;
  }

  return (
    <div className="space-y-12 animate-in fade-in duration-300" style={{ paddingTop: 16 }}>
      
      {/* ── SECTION: WHAT IF SIMULATOR ── */}
      <div style={{
        backgroundColor: "var(--color-ec-bg-surface)",
        border: "1.5px solid var(--color-ec-border)",
        borderRadius: 8,
        padding: "24px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
          <span style={{ fontSize: 16 }}>⚡</span>
          <h3 style={{
            fontFamily: "Fraunces, serif",
            fontSize: 16,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: 0
          }}>
            What if...
          </h3>
          <InfoTooltip
            position="right"
            text="Simula escenarios alternativos aplicando filtros de tiempo, límites de operaciones y peores escenarios a tu backtest en tiempo real."
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Left Column: inputs (5 cols) */}
          <div className="lg:col-span-5 flex flex-col pr-4" style={{ borderRight: "0.5px solid var(--color-ec-border)" }}>
            
            {/* 1. Espacios Temporales */}
            <div style={{ borderBottom: "1.5px solid var(--color-ec-border)", paddingBottom: 16, marginBottom: 16 }}>
              <button
                type="button"
                onClick={() => toggleSection("temporal")}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                }}
                className="hover:text-[var(--color-ec-text-primary)] transition-colors group"
              >
                <span className="text-[10.5px] font-bold text-[var(--color-ec-text-primary)] uppercase tracking-wider">1) Espacios Temporales</span>
                <span className={`text-xs text-[var(--color-ec-text-muted)] transform transition-transform ${openSections.includes("temporal") ? "rotate-180" : ""}`}>▼</span>
              </button>
              
              {openSections.includes("temporal") && (
                <div className="space-y-4 pt-3 animate-in fade-in slide-in-from-top-1 duration-200">
                  <div>
                    <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] mb-1.5 block">Excluir Días de la Semana</label>
                    <div className="flex gap-1.5">
                      {["L", "M", "X", "J", "V"].map((day, idx) => (
                        <button
                          key={day}
                          type="button"
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

                  <div>
                    <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] mb-1.5 block">Excluir Meses del Año</label>
                    <div className="grid grid-cols-6 gap-1.5">
                      {["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"].map((month, idx) => (
                        <button
                          key={month}
                          type="button"
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

                  <div>
                    <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] mb-1.5 block">Excluir Rango de Horas</label>
                    <div className="flex items-center gap-4">
                      <div className="flex-1">
                        <label className="text-[9px] font-medium text-[var(--color-ec-text-muted)] mb-1 block uppercase opacity-70">Desde:</label>
                        <input
                          type="time"
                          value={excludeHourStart}
                          onChange={(e) => setExcludeHourStart(e.target.value)}
                          className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-[9px] font-medium text-[var(--color-ec-text-muted)] mb-1 block uppercase opacity-70">Hasta:</label>
                        <input
                          type="time"
                          value={excludeHourEnd}
                          onChange={(e) => setExcludeHourEnd(e.target.value)}
                          className="w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 py-1 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="border-t border-[var(--color-ec-border)] pt-3">
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] font-medium text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] transition-colors">Excluir días aleatorios/mes:</label>
                      <input
                        type="number"
                        min="0"
                        max="31"
                        value={randomMonthlyDays}
                        onChange={(e) => setRandomMonthlyDays(Number(e.target.value))}
                        className="w-16 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] focus:border-[var(--color-ec-copper)] outline-none"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 2. Límite operaciones */}
            <div style={{ borderBottom: "1.5px solid var(--color-ec-border)", paddingBottom: 16, marginBottom: 16 }}>
              <button
                type="button"
                onClick={() => toggleSection("limit")}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                }}
                className="hover:text-[var(--color-ec-text-primary)] transition-colors"
              >
                <span className="text-[10.5px] font-bold text-[var(--color-ec-text-primary)] uppercase tracking-wider">2) Límite operaciones</span>
                <span className={`text-xs text-[var(--color-ec-text-muted)] transform transition-transform ${openSections.includes("limit") ? "rotate-180" : ""}`}>▼</span>
              </button>
              
              {openSections.includes("limit") && (
                <div className="space-y-4 pt-3 animate-in fade-in slide-in-from-top-1 duration-200">
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

            {/* 3. Peor escenario y Black Swan */}
            <div style={{ borderBottom: "1.5px solid var(--color-ec-border)", paddingBottom: 16, marginBottom: 16 }}>
              <button
                type="button"
                onClick={() => toggleSection("stress")}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                }}
                className="hover:text-[var(--color-ec-text-primary)] transition-colors"
              >
                <span className="text-[10.5px] font-bold text-[var(--color-ec-text-primary)] uppercase tracking-wider">3) Peor escenario y Black Swan</span>
                <span className={`text-xs text-[var(--color-ec-text-muted)] transform transition-transform ${openSections.includes("stress") ? "rotate-180" : ""}`}>▼</span>
              </button>

              {openSections.includes("stress") && (
                <div className="space-y-4 pt-3 animate-in fade-in slide-in-from-top-1 duration-200">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--color-ec-text-secondary)]">Omitir mejores trades (%):</span>
                    <input
                      type="number"
                      value={skipTopPct}
                      onChange={(e) => setSkipTopPct(Number(e.target.value))}
                      className="w-16 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--color-ec-text-secondary)]">Deslizamiento extra (%):</span>
                    <input
                      type="number"
                      step="0.01"
                      value={extraSlippage}
                      onChange={(e) => setExtraSlippage(Number(e.target.value))}
                      className="w-16 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                    />
                  </div>
                  
                  <div className="border-t border-[var(--color-ec-border)] pt-3">
                    <label className="text-[10px] font-bold text-[var(--color-ec-text-secondary)] uppercase block mb-2">Añadir Black Swans Aleatorios</label>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] text-[var(--color-ec-text-muted)]">Cantidad de Eventos:</span>
                      <input
                        type="number"
                        value={blackSwanCount}
                        onChange={(e) => setBlackSwanCount(Number(e.target.value))}
                        className="w-16 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)]"
                      />
                    </div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] text-[var(--color-ec-text-muted)]">Pérdida por Evento:</span>
                      <span className="text-[11px] font-bold text-[var(--color-ec-loss)]">{blackSwanSize}%</span>
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

            {/* Expenses Option */}
            {!!monthlyExpenses && monthlyExpenses > 0 && (
              <div style={{ marginBottom: 16, paddingTop: 8, paddingBottom: 8 }}>
                <label className="flex items-center gap-2.5 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={includeExpensesInWhatIf}
                    onChange={(e) => setIncludeExpensesInWhatIf(e.target.checked)}
                    className="accent-[var(--color-ec-copper)] w-3.5 h-3.5 cursor-pointer"
                  />
                  <span className="text-[10px] text-[var(--color-ec-text-secondary)] group-hover:text-[var(--color-ec-text-primary)] transition-colors">
                    Incluir costes fijos mensuales (${monthlyExpenses}/mes)
                  </span>
                </label>
              </div>
            )}

            {/* Simulation button */}
            <div style={{ marginTop: "auto", paddingTop: 16 }}>
              <button
                type="button"
                onClick={handleRunWhatIf}
                disabled={simLoading}
                className="w-full bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)] hover:bg-[var(--color-ec-copper-bright)] py-2.5 rounded-md text-[10px] font-sans font-bold uppercase tracking-[0.15em] transform active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <span className="text-sm">{simLoading ? "⏳" : "⚡"}</span>
                {simLoading ? "Simulando..." : "Ejecutar Simulación What-if"}
              </button>
              <p className="text-center text-[8px] text-[var(--color-ec-text-muted)] mt-2 italic opacity-60">
                * Se aplicarán todas las condiciones de simulación simultáneamente
              </p>
            </div>

          </div>

          {/* Right Column: results & chart (7 cols) */}
          <div className="lg:col-span-7 flex flex-col gap-6">
            <h4 className="text-[10px] font-semibold uppercase text-[var(--color-ec-text-primary)] mb-0 flex items-center gap-2 font-mono tracking-[0.12em]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-ec-copper)]"></span>
              Resultados Simulados
            </h4>
            
            <div className="w-full">
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-4 gap-y-3.5 w-full">
                {[
                  { label: "Días", base: metrics?.total_days ?? 0, sim: getSimValue("total_days") },
                  { label: "Trades", base: metrics?.total_trades ?? 0, sim: getSimValue("total_trades") },
                  { label: "Win Rate", base: `${(metrics?.win_rate_pct ?? 0).toFixed(1)}%`, sim: getSimValue("win_rate_pct", v => `${v.toFixed(1)}%`) },
                  { label: "Profit Factor", base: (metrics?.avg_profit_factor ?? 0).toFixed(3), sim: getSimValue("avg_profit_factor", v => v.toFixed(3)) },
                  { label: "Total Return", base: `${(metrics?.total_return_pct ?? 0).toFixed(2)}%`, sim: getSimValue("total_return_pct", v => `${v.toFixed(2)}%`) },
                  { label: "Max DD", base: `${(metrics?.max_drawdown_pct ?? 0).toFixed(2)}%`, sim: getSimValue("max_drawdown_pct", v => `${v.toFixed(2)}%`), danger: true },
                  { label: "Avg R/Día", base: `${(metrics?.avg_r_per_day ?? 0).toFixed(3)}R`, sim: getSimValue("avg_r_per_day", v => `${v.toFixed(3)}R`) },
                  { label: "Sharpe", base: (metrics?.avg_sharpe ?? 0).toFixed(3), sim: getSimValue("avg_sharpe", v => v.toFixed(3)) },
                ].map((m, idx) => (
                  <div key={idx} className="flex flex-col p-2.5 rounded bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)]">
                    <span className="text-[9px] text-[var(--color-ec-text-secondary)] font-medium uppercase tracking-wider mb-1.5">{m.label}</span>
                    <div className="flex items-baseline justify-between font-mono">
                      <span className="text-[10px] text-[var(--color-ec-text-muted)]">{m.base}</span>
                      <span className={`text-[12px] font-bold ${m.danger && m.sim !== "---" ? "text-[var(--color-ec-loss)]" : "text-[var(--color-ec-copper-bright)]"}`}>
                        {m.sim}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Chart comparison */}
            <div className="border-t border-dashed border-[var(--color-ec-border)] pt-4 w-full">
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

      {/* ── SECTION: DESCRIPTIVE CHARTS ── */}
      {/* ROW 1: Rolling EV + EV by Time + EV by Day — borderless triptych */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-0 h-[280px] lg:h-[300px]" style={{ borderBottom: '1px solid var(--border)' }}>

        {/* Rolling EV */}
        <div className="h-full" style={{ borderRight: '1px solid var(--border)' }}>
          <RollingEVChart trades={trades} riskR={riskR} isDarkMode={isDarkMode} />
        </div>

        {/* EV por Tiempo (30m) */}
        <div className="flex flex-col h-full" style={{ borderRight: '1px solid var(--border)' }}>
          <div className="px-3 py-2 flex items-center">
            <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-8 inline-flex items-center gap-1">
              EV por Tiempo (30m)
              <InfoTooltip
                position="left"
                text="Esperanza Matemática (EV) promedio agrupada por la hora de entrada del trade (intervalos de 30 minutos). Sirve para identificar en qué franjas horarias las operaciones son rentables (barras verdes) o perdedoras (barras rojas) en promedio."
              />
            </span>
          </div>
          <div className="flex-1 px-4 pb-4 min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={evByTime30Min} margin={{ top: 16, right: 16, bottom: 16, left: 16 }}>
                <CartesianGrid stroke={gridColor} vertical={false} />
                <XAxis
                  dataKey="time"
                  tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={25}
                />
                <YAxis tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <Tooltip
                  contentStyle={{ fontSize: '10px', backgroundColor: tooltipBg, border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace', color: '#fff' }}
                  itemStyle={{ color: '#fff' }}
                  labelStyle={{ color: '#aaa' }}
                  formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'EV']}
                  cursor={{ fill: "rgba(120,113,108,0.04)" }}
                />
                <ReferenceLine y={0} stroke="#6A6D72" strokeWidth={0.5} />
                <Bar dataKey="ev" radius={[1, 1, 0, 0]}>
                  {evByTime30Min.map((entry, idx) => <Cell key={idx} fill={entry.ev >= 0 ? barPositiveFill : barNegativeFill} stroke={entry.ev >= 0 ? barPositiveStroke : barNegativeStroke} fillOpacity={isDarkMode ? 0.75 : 1} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* EV por Día */}
        <div className="flex flex-col h-full">
          <div className="px-3 py-2 flex items-center">
            <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-4 inline-flex items-center gap-1">
              EV por Dia
              <InfoTooltip
                position="left"
                text="Esperanza Matemática (EV) promedio por día de la semana de entrada. Ayuda a detectar si hay días específicos (como los lunes o viernes) en los que la estrategia rinde peor y convendría evitar operar."
              />
            </span>
          </div>
          <div className="flex-1 px-4 pb-4 min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={evByDay} margin={{ top: 16, right: 16, bottom: 16, left: 16 }}>
                <CartesianGrid stroke={gridColor} vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <Tooltip
                  contentStyle={{ fontSize: '10px', backgroundColor: tooltipBg, border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace', color: '#fff' }}
                  itemStyle={{ color: '#fff' }}
                  labelStyle={{ color: '#aaa' }}
                  formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'EV']}
                  cursor={{ fill: "rgba(120,113,108,0.04)" }}
                />
                <ReferenceLine y={0} stroke="#6A6D72" strokeWidth={0.5} />
                <Bar dataKey="ev" radius={[1, 1, 0, 0]}>
                  {evByDay.map((entry, idx) => <Cell key={idx} fill={entry.ev >= 0 ? barPositiveFill : barNegativeFill} stroke={entry.ev >= 0 ? barPositiveStroke : barNegativeStroke} fillOpacity={isDarkMode ? 0.75 : 1} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ROW 2: Distributions side by side — no card wrappers */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-0 mt-10">
        {/* PnL Distribution */}
        <div className="flex flex-col h-[280px]" style={{ borderRight: '1px solid var(--border)' }}>
          <div className="px-3 py-2">
            <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] inline-flex items-center gap-1">
              Distribucion de Retornos (PnL %)
              <InfoTooltip
                position="left"
                text="Histograma de frecuencias que agrupa los trades según su rentabilidad porcentual final. Ideal para ver la simetría del sistema (ej: si tienes muchos trades con ganancias moderadas o si hay pérdidas extremas anormales)."
              />
            </span>
          </div>
          <div className="flex-1 pl-1 pr-4 pb-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={pnlDistribution.data} margin={{ top: 16, right: 16, bottom: 16, left: -20 }}>
                <CartesianGrid stroke={gridColor} vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: tooltipBg, fontSize: '10px', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace', color: '#fff' }}
                  itemStyle={{ color: '#fff' }}
                  labelStyle={{ color: '#aaa' }}
                  cursor={{ fill: "rgba(120,113,108,0.04)" }}
                />
                <ReferenceLine x="0.00%" stroke="#6A6D72" strokeDasharray="3 3" strokeWidth={0.5} />
                <Bar dataKey="value" radius={[1, 1, 0, 0]}>
                  {pnlDistribution.data.map((entry, index) => (
                    <Cell key={index} fill={entry.num > 0 ? barPositiveFill : entry.num < 0 ? barNegativeFill : tickColor} stroke={entry.num > 0 ? barPositiveStroke : entry.num < 0 ? barNegativeStroke : 'transparent'} fillOpacity={isDarkMode ? 0.7 : 1} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Consecutive Runs */}
        <div className="flex flex-col h-[280px]" style={{ borderRight: '1px solid var(--border)' }}>
          <div className="px-3 pt-4 pb-1 flex items-center justify-between">
            <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-4 inline-flex items-center gap-1">
              Consecutive Runs
              <InfoTooltip
                position="left"
                text="Rachas Consecutivas. Muestra cuántas veces ocurrieron rachas seguidas de ganancias (verde) o pérdidas (rojo) de determinada longitud (1, 2, 3, etc. operaciones seguidas)."
              />
            </span>
            <div className="flex gap-3 text-[8px] font-mono text-[var(--color-ec-text-secondary)]">
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-[3px] bg-emerald-500 rounded-sm"></span>W</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-[3px] bg-red-500 rounded-sm"></span>L</span>
            </div>
          </div>
          <div className="flex-1 pl-1 pr-4 pb-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={consecutiveRuns.data} margin={{ top: 16, right: 16, bottom: 16, left: -20 }}>
                <CartesianGrid stroke={gridColor} vertical={false} />
                <XAxis
                  dataKey="length"
                  tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: tooltipBg, fontSize: '10px', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace', color: '#fff' }}
                  itemStyle={{ color: '#fff' }}
                  labelStyle={{ color: '#aaa' }}
                />
                <Bar dataKey="winRuns" name="Wins" fill={barPositiveFill} stroke={barPositiveStroke} fillOpacity={isDarkMode ? 0.7 : 1} radius={[1, 1, 0, 0]} />
                <Bar dataKey="lossRuns" name="Losses" fill={barNegativeFill} stroke={barNegativeStroke} fillOpacity={isDarkMode ? 0.7 : 1} radius={[1, 1, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Descriptive Statistics Table */}
        <div className="flex flex-col h-[280px]">
          <div className="py-2" style={{ paddingLeft: '40px' }}>
            <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] inline-flex items-center gap-1">
              Descriptive Statistics
              <InfoTooltip
                position="right"
                text="Estadísticas descriptivas detalladas de los retornos (PnL %) y rachas de victorias/pérdidas. Incluye medias, desviación estándar (volatilidad), asimetría (skewness) y curtosis (apuntamiento para detectar riesgo de black swan)."
              />
            </span>
          </div>
          <div className="flex-1 pr-6 pb-4 overflow-y-auto custom-scrollbar" style={{ paddingLeft: '40px', scrollbarWidth: 'none' }}>
            <table className="w-full text-[10px] font-mono" style={{ borderCollapse: 'collapse', tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '43%' }} />
                <col style={{ width: '19%' }} />
                <col style={{ width: '19%' }} />
                <col style={{ width: '19%' }} />
              </colgroup>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-ec-border)' }}>
                  <th className="text-left py-1.5 pl-6 pr-3 text-[var(--color-ec-text-secondary)] font-normal text-[9px]">metric</th>
                  <th className="text-right py-1.5 px-3 text-[var(--color-ec-text-secondary)] font-normal text-[9px]">PnL %</th>
                  <th className="text-right py-1.5 px-3 text-[var(--color-ec-text-secondary)] font-normal text-[9px]">Streaks (W)</th>
                  <th className="text-right py-1.5 px-3 text-[var(--color-ec-text-secondary)] font-normal text-[9px]">Streaks (L)</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { label: "N", pnl: pnlDistribution.stats?.n ?? 0, w: consecutiveRuns.winStats?.n ?? 0, l: consecutiveRuns.lossStats?.n ?? 0, isPct: false, isInt: true },
                  { label: "Mean", pnl: pnlDistribution.stats?.mean ?? 0, w: consecutiveRuns.winStats?.mean ?? 0, l: consecutiveRuns.lossStats?.mean ?? 0, isPct: true },
                  { label: "Median", pnl: pnlDistribution.stats?.median ?? 0, w: consecutiveRuns.winStats?.median ?? 0, l: consecutiveRuns.lossStats?.median ?? 0, isPct: true },
                  { label: "Std Dev", pnl: pnlDistribution.stats?.stdDev ?? 0, w: consecutiveRuns.winStats?.stdDev ?? 0, l: consecutiveRuns.lossStats?.stdDev ?? 0, isPct: true },
                  { label: "Q1 (25%)", pnl: pnlDistribution.stats?.q1 ?? 0, w: consecutiveRuns.winStats?.q1 ?? 0, l: consecutiveRuns.lossStats?.q1 ?? 0, isPct: true },
                  { label: "Q3 (75%)", pnl: pnlDistribution.stats?.q3 ?? 0, w: consecutiveRuns.winStats?.q3 ?? 0, l: consecutiveRuns.lossStats?.q3 ?? 0, isPct: true },
                  { label: "Max", pnl: pnlDistribution.stats?.max ?? 0, w: consecutiveRuns.winStats?.max ?? 0, l: consecutiveRuns.lossStats?.max ?? 0, isPct: true },
                  { label: "Min", pnl: pnlDistribution.stats?.min ?? 0, w: consecutiveRuns.winStats?.min ?? 0, l: consecutiveRuns.lossStats?.min ?? 0, isPct: true },
                  { label: "Range", pnl: pnlDistribution.stats?.range ?? 0, w: consecutiveRuns.winStats?.range ?? 0, l: consecutiveRuns.lossStats?.range ?? 0, isPct: true },
                  { label: "IQR", pnl: pnlDistribution.stats?.iqr ?? 0, w: consecutiveRuns.winStats?.iqr ?? 0, l: consecutiveRuns.lossStats?.iqr ?? 0, isPct: true },
                  { label: "Skewness", pnl: pnlDistribution.stats?.skewness ?? 0, w: consecutiveRuns.winStats?.skewness ?? 0, l: consecutiveRuns.lossStats?.skewness ?? 0, isPct: false, prec: 3 },
                  { label: "Kurtosis", pnl: pnlDistribution.stats?.kurtosis ?? 0, w: consecutiveRuns.winStats?.kurtosis ?? 0, l: consecutiveRuns.lossStats?.kurtosis ?? 0, isPct: false, prec: 3 },
                ].map((row, idx) => (
                  <tr
                    key={idx}
                    className="hover:bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)] transition-colors"
                    style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 30%, transparent)' }}
                  >
                    <td className="py-1 pl-6 pr-3" style={{ color: 'var(--color-ec-text-primary)' }}>{row.label}</td>
                    <td className="py-1 px-3 text-right" style={{ color: 'var(--color-ec-text-high)' }}>
                      {row.isInt ? row.pnl : (row.pnl).toFixed(row.prec ?? 2)}{row.isPct && !row.isInt ? '%' : ''}
                    </td>
                    <td className="py-1 px-3 text-right" style={{ color: 'var(--color-ec-text-high)' }}>
                      {row.isInt ? row.w : (row.w).toFixed(row.prec ?? 2)}
                    </td>
                    <td className="py-1 px-3 text-right" style={{ color: 'var(--color-ec-text-high)' }}>
                      {row.isInt ? row.l : (row.l).toFixed(row.prec ?? 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
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

  const transformDrawdown = (p: DrawdownPoint): number => {
    if (wiViewMode === "$") return (p.value / 100) * initCash;
    if (wiViewMode === "R") return riskR > 0 ? ((p.value / 100) * initCash) / riskR : 0;
    return p.value; // Already in %
  };

  useEffect(() => {
    if (!chartContainerRef.current) return;

    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }

    if (!simResult || !simResult.global_equity || simResult.global_equity.length === 0) return;

    const container = chartContainerRef.current;

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
        color: "rgba(255, 255, 255, 0.45)",
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

    if (!ddContainerRef.current) return;
    
    if (ddInstanceRef.current) {
      ddInstanceRef.current.remove();
      ddInstanceRef.current = null;
    }
    
    const ddContainer = ddContainerRef.current;
    const ddChart = createChart(ddContainer, {
      width: ddContainer.clientWidth,
      height: 80,
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
        chart.timeScale().fitContent();
        ddChart.applyOptions({ width: ddContainer.clientWidth });
        ddChart.timeScale().fitContent();
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
        <div className="flex gap-1 bg-[var(--color-ec-bg-sidebar)] p-0.5 rounded text-[9px] border border-[var(--color-ec-border)]">
          {(["$", "%", "R"] as WIViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setWiViewMode(mode)}
              className={`px-3 py-0.5 rounded transition-colors cursor-pointer ${
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
