"use client";

import { useMemo } from "react";
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
import type { TradeRecord, DayResult } from "@/lib/api_backtester";
import RollingEVChart from "@/components/backtester/RollingEVChart";

interface ChartsTabProps {
  trades: TradeRecord[];
  dayResults: DayResult[];
  riskR?: number;
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
  riskR = 100,
  isDarkMode = false,
}: ChartsTabProps) {

  const gridColor = isDarkMode ? "#303033" : "#f0eeea";
  const tickColor = isDarkMode ? "#94a3b8" : "#a8a29e";
  const tooltipBg = isDarkMode ? "#303033" : "#fafaf7";
  const barPositiveFill = isDarkMode ? "#3b82f6" : "#f1f5f9";
  const barPositiveStroke = isDarkMode ? "transparent" : "#1c1917";
  const barNegativeFill = isDarkMode ? "#e2e8f0" : "#18181a";
  const barNegativeStroke = isDarkMode ? "transparent" : "transparent";

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

  // --- Gap % vs PnL % scatter + linear regression ---
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
    return <p className="text-sm text-[var(--muted)]">Sin trades para analizar</p>;
  }

  // Helper for stats rendering
  const fmt = (v: number, pct = false) => `${v.toFixed(2)}${pct ? '%' : ''}`;

  return (
    <div className="space-y-8">

      {/* ROW 1: Rolling EV + EV by Time + EV by Day — borderless triptych */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-0 h-[280px] lg:h-[300px]" style={{ borderBottom: '1px solid var(--border)' }}>

        {/* Rolling EV */}
        <div className="h-full" style={{ borderRight: '1px solid var(--border)' }}>
          <RollingEVChart trades={trades} riskR={riskR} isDarkMode={isDarkMode} />
        </div>

        {/* EV por Tiempo (30m) */}
        <div className="flex flex-col h-full" style={{ borderRight: '1px solid var(--border)' }}>
          <div className="px-3 py-2 flex items-center">
            <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">EV por Tiempo (30m)</span>
          </div>
          <div className="flex-1 px-1 pb-1 min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={evByTime30Min} margin={{ top: 5, right: 8, bottom: 0, left: -28 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <Tooltip
                  contentStyle={{ fontSize: '10px', backgroundColor: tooltipBg, border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace' }}
                  formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'EV']}
                  cursor={{ fill: "rgba(120,113,108,0.04)" }}
                />
                <ReferenceLine y={0} stroke={tickColor} strokeWidth={0.5} />
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
            <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">EV por Dia</span>
          </div>
          <div className="flex-1 px-1 pb-1 min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={evByDay} margin={{ top: 5, right: 8, bottom: 0, left: -28 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 9, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <Tooltip
                  contentStyle={{ fontSize: '10px', backgroundColor: tooltipBg, border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace' }}
                  formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'EV']}
                  cursor={{ fill: "rgba(120,113,108,0.04)" }}
                />
                <ReferenceLine y={0} stroke={tickColor} strokeWidth={0.5} />
                <Bar dataKey="ev" radius={[1, 1, 0, 0]}>
                  {evByDay.map((entry, idx) => <Cell key={idx} fill={entry.ev >= 0 ? barPositiveFill : barNegativeFill} stroke={entry.ev >= 0 ? barPositiveStroke : barNegativeStroke} fillOpacity={isDarkMode ? 0.75 : 1} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ROW 2: Distributions side by side — no card wrappers */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-0">
        {/* PnL Distribution */}
        <div className="flex flex-col h-[280px]" style={{ borderRight: '1px solid var(--border)' }}>
          <div className="px-3 py-2">
            <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">
              Distribucion de Retornos (PnL %)
            </span>
          </div>
          <div className="flex-1 px-1 pb-1">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={pnlDistribution.data} margin={{ top: 8, right: 8, left: -28, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 7, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: tooltipBg, fontSize: '10px', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace' }}
                  cursor={{ fill: "rgba(120,113,108,0.04)" }}
                />
                <ReferenceLine x="0.00%" stroke={tickColor} strokeDasharray="3 3" strokeWidth={0.5} />
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
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">
              Consecutive Runs
            </span>
            <div className="flex gap-3 text-[8px] font-mono text-[var(--muted)]">
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-[3px] bg-emerald-500 rounded-sm"></span>W</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-[3px] bg-red-500 rounded-sm"></span>L</span>
            </div>
          </div>
          <div className="flex-1 px-1 pb-1">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={consecutiveRuns.data} margin={{ top: 8, right: 8, left: -28, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
                <XAxis
                  dataKey="length"
                  tick={{ fontSize: 9, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: tooltipBg, fontSize: '10px', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace' }}
                />
                <Bar dataKey="winRuns" name="Wins" fill={barPositiveFill} stroke={barPositiveStroke} fillOpacity={isDarkMode ? 0.7 : 1} radius={[1, 1, 0, 0]} />
                <Bar dataKey="lossRuns" name="Losses" fill={barNegativeFill} stroke={barNegativeStroke} fillOpacity={isDarkMode ? 0.7 : 1} radius={[1, 1, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Gap % vs PnL % Scatter */}
        <div className="flex flex-col h-[280px]">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">
              Gap % vs PnL %
            </span>
            {gapRegression && (
              <span className="text-[9px] font-mono text-[var(--muted)]">
                R² = {(gapRegression.r2 * 100).toFixed(1)}%
              </span>
            )}
          </div>
          <div className="flex-1 px-1 pb-1 relative">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 8, right: 8, left: -20, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                <XAxis
                  type="number"
                  dataKey="x"
                  name="Gap %"
                  tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }}
                  tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  name="PnL %"
                  tick={{ fontSize: 8, fill: tickColor, fontFamily: 'monospace' }}
                  tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ strokeDasharray: '3 3' }}
                  contentStyle={{ backgroundColor: tooltipBg, fontSize: '10px', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'monospace' }}
                  formatter={(value: any, name: any) => {
                    const numValue = typeof value === 'number' ? value : Number(value);
                    return [`${numValue.toFixed(2)}%`, name === 'x' ? 'Gap' : 'PnL'];
                  }}
                />
                <ReferenceLine y={0} stroke={isDarkMode ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)"} strokeWidth={1} />
                <ReferenceLine x={0} stroke={isDarkMode ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)"} strokeWidth={1} />
                <Scatter
                  name="Trades"
                  data={gapVsPnl}
                  shape={(props: { cx?: number; cy?: number }) => {
                    if (!props.cx || !props.cy) return <></>;
                    return <circle cx={props.cx} cy={props.cy} r={2} stroke={isDarkMode ? '#e2e8f0' : '#1c1917'} fill="transparent" strokeWidth={1} />;
                  }}
                  isAnimationActive={false}
                />
                {gapRegressionLine && (
                  <Scatter
                    data={gapRegressionLine}
                    shape={() => <></>}
                    line={{
                      stroke: isDarkMode ? '#e2e8f0' : '#1c1917',
                      strokeDasharray: '3 3',
                      strokeWidth: 1.5
                    }}
                    tooltipType="none"
                    isAnimationActive={false}
                  />
                )}
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ROW 3: Combined Statistics — single terminal-style table */}
      <div className="pt-4" style={{ borderTop: '1px solid var(--border)' }}>
        <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em] block mb-3">
          Descriptive Statistics
        </span>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] font-mono" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th className="text-left py-1.5 px-2 text-[var(--muted)] font-normal">metric</th>
                <th className="text-right py-1.5 px-2 text-[var(--muted)] font-normal">PnL %</th>
                <th className="text-right py-1.5 px-2 text-[var(--muted)] font-normal">Streaks (W)</th>
                <th className="text-right py-1.5 px-2 text-[var(--muted)] font-normal">Streaks (L)</th>
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
                  style={{ borderBottom: '1px solid color-mix(in srgb, var(--border) 30%, transparent)' }}
                >
                  <td className="py-1.5 px-2 text-[var(--muted)]">{row.label}</td>
                  <td className="py-1.5 px-2 text-right text-[var(--text-data)]">
                    {row.isInt ? row.pnl : (row.pnl).toFixed(row.prec ?? 2)}{row.isPct && !row.isInt ? '%' : ''}
                  </td>
                  <td className="py-1.5 px-2 text-right text-[var(--text-data)]">
                    {row.isInt ? row.w : (row.w).toFixed(row.prec ?? 2)}
                  </td>
                  <td className="py-1.5 px-2 text-right text-[var(--text-data)]">
                    {row.isInt ? row.l : (row.l).toFixed(row.prec ?? 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
