"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  Sun,
  Moon,
  Loader2,
  AlertCircle,
  ChevronUp,
  ChevronDown,
  Lock,
} from "lucide-react";
import {
  getScreenerDaily,
  getTickerAnalysis,
  getTickerGapStats,
} from "@/lib/api";
import type { ScreenerRecord, ScreenerDailyResponse } from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────
type TabKey = "gainers" | "losers" | "premarket" | "aftermarket";
type SortField = "ticker" | "price" | "change_pct" | "return_pct" | "gap_pct" | "volume" | "prev_volume" | "prev_close" | "open" | "high" | "low";
type SortDir = "asc" | "desc";

interface TickerDetail {
  profile?: {
    name?: string;
    sector?: string;
    industry?: string;
    exchange?: string;
    logo_url?: string;
  };
  market?: {
    market_cap?: number | null;
    shares_outstanding?: number | null;
    float_shares?: number | null;
    held_percent_institutions?: number | null;
    held_percent_insiders?: number | null;
    price?: number | null;
  };
}

interface ChartPoint {
  bin: string;
  avg_change_pct: number;
  is_premarket: boolean;
}

interface GapStatsData {
  gap_days_count: number;
  high_rth_spike_avg: number | null;
  pm_fade_avg: number | null;
  low_rth_spike_avg: number | null;
  rthh_fade_avg: number | null;
  neg_close_freq: number | null;
  close_above_pmh_freq: number | null;
  close_below_vwap_freq: number | null;
  price_change_chart: ChartPoint[];
  status?: string;
}

interface FloatSourceData {
  float?: string;
  short_percent?: string;
  outstanding?: string;
}

interface FloatData {
  [source: string]: FloatSourceData;
}

interface GapStatsResponse {
  know_the_float?: FloatData;
  gap_stats: GapStatsData;
  gap_stats_plus_1: GapStatsData;
  gap_stats_plus_2: GapStatsData;
  status?: string;
}

// ─── Formatting Helpers ─────────────────────────────────────
const fmtShares = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
};

const fmtPct = (v: number) => {
  const s = v.toFixed(2);
  return v > 0 ? `+${s}%` : `${s}%`;
};

const fmtVol = (v: number) => {
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
};

const fmtPrice = (v: number) => {
  if (v >= 1000) return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return v.toFixed(2);
};

const fmtMarketCap = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
};

const fmtStatPct = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(2)}%`;
};

// ─── AvgPriceChangeChart (Copied from TickerAnalysis.tsx) ────
const AvgPriceChangeChart = ({ data }: { data?: ChartPoint[] }) => {
  if (!data || data.length === 0) {
    return (
      <div style={{
        height: '110px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--color-ec-text-muted)',
        fontSize: '10px',
        border: '1px dashed rgba(255, 255, 255, 0.1)',
        borderRadius: '4px',
        width: '100%'
      }}>
        No hay datos de intradía
      </div>
    );
  }

  const viewBoxW = 240;
  const viewBoxH = 150;
  const paddingLeft = 32;
  const paddingRight = 8;
  const paddingTop = 8;
  const paddingBottom = 20;

  const W = viewBoxW - paddingLeft - paddingRight;
  const H = viewBoxH - paddingTop - paddingBottom;

  const values = data.map(d => d.avg_change_pct);
  let minY = Math.min(0, ...values);
  let maxY = Math.max(0, ...values);
  
  if (maxY - minY < 1.0) {
    const center = (maxY + minY) / 2;
    minY = center - 0.5;
    maxY = center + 0.5;
  } else {
    const diff = maxY - minY;
    minY -= diff * 0.15;
    maxY += diff * 0.15;
  }

  const points = data.map((d, i) => {
    const x = paddingLeft + (i / (data.length - 1)) * W;
    const y_pct = (d.avg_change_pct - minY) / (maxY - minY);
    const y = paddingTop + H - (y_pct * H);
    return { x, y, ...d };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const bottomY = paddingTop + H;
  const fillPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${bottomY.toFixed(1)} L ${points[0].x.toFixed(1)} ${bottomY.toFixed(1)} Z`;

  let lastPreIdx = -1;
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i].is_premarket) {
      lastPreIdx = i;
      break;
    }
  }
  const preWidth = lastPreIdx >= 0 ? (lastPreIdx / (data.length - 1)) * W : 0;

  const yTicks = [minY, 0, maxY].filter((v, idx, self) => self.indexOf(v) === idx);

  const getClosestIndex = (timeStr: string) => {
    let minDiff = Infinity;
    let index = -1;
    data.forEach((d, idx) => {
      const start = d.bin.split('-')[0];
      const [h, m] = start.split(':').map(Number);
      const [th, tm] = timeStr.split(':').map(Number);
      const diff = Math.abs((h * 60 + m) - (th * 60 + tm));
      if (diff < minDiff) {
        minDiff = diff;
        index = idx;
      }
    });
    return index;
  };

  const xTickLabels = ["04:00", "09:30", "16:00"];
  const xTicks = xTickLabels.map(label => {
    const idx = getClosestIndex(label);
    return {
      x: idx >= 0 ? paddingLeft + (idx / (data.length - 1)) * W : 0,
      label
    };
  });

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <svg width="100%" height="100%" viewBox={`0 0 ${viewBoxW} ${viewBoxH}`} style={{ overflow: 'visible' }}>
        <defs>
          <linearGradient id="screener-price-change-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-ec-copper)" stopOpacity="0.15" />
            <stop offset="100%" stopColor="var(--color-ec-copper)" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {preWidth > 0 && (
          <>
            <rect
              x={paddingLeft}
              y={paddingTop}
              width={preWidth}
              height={H}
              fill="rgba(255, 255, 255, 0.02)"
            />
            <line
              x1={paddingLeft + preWidth}
              y1={paddingTop}
              x2={paddingLeft + preWidth}
              y2={paddingTop + H}
              stroke="rgba(255, 255, 255, 0.1)"
              strokeWidth="0.8"
              strokeDasharray="2,2"
            />
            <text
              x={paddingLeft + preWidth / 2}
              y={paddingTop + 10}
              textAnchor="middle"
              fill="var(--color-ec-text-muted)"
              style={{ fontSize: 8, fontWeight: 700, letterSpacing: '0.5px' }}
            >
              PRE
            </text>
            <text
              x={paddingLeft + preWidth + (W - preWidth) / 2}
              y={paddingTop + 10}
              textAnchor="middle"
              fill="var(--color-ec-text-muted)"
              style={{ fontSize: 8, fontWeight: 700, letterSpacing: '0.5px' }}
            >
              RTH
            </text>
          </>
        )}

        {/* Grid lines */}
        {yTicks.map((tick, i) => {
          const y_pct = (tick - minY) / (maxY - minY);
          const y = paddingTop + H - (y_pct * H);
          return (
            <line
              key={i}
              x1={paddingLeft}
              y1={y}
              x2={paddingLeft + W}
              y2={y}
              stroke={tick === 0 ? "rgba(255,255,255,0.2)" : "rgba(255,255,255,0.04)"}
              strokeWidth={tick === 0 ? "1" : "0.5"}
            />
          );
        })}

        {/* Fill Area */}
        <path d={fillPath} fill="url(#screener-price-change-grad)" />

        {/* Line */}
        <path d={linePath} fill="none" stroke="var(--color-ec-copper)" strokeWidth="1.5" />

        {/* Y Axis Ticks */}
        {yTicks.map((tick, i) => {
          const y_pct = (tick - minY) / (maxY - minY);
          const y = paddingTop + H - (y_pct * H);
          return (
            <text
              key={i}
              x={paddingLeft - 6}
              y={y + 3}
              textAnchor="end"
              fill="var(--color-ec-text-muted)"
              style={{ fontSize: 7.5, fontFamily: 'monospace' }}
            >
              {tick > 0 ? `+${tick.toFixed(1)}%` : `${tick.toFixed(1)}%`}
            </text>
          );
        })}

        {/* X Axis Ticks */}
        {xTicks.map((tick, i) => (
          <g key={i}>
            <line
              x1={tick.x}
              y1={paddingTop + H}
              x2={tick.x}
              y2={paddingTop + H + 4}
              stroke="rgba(255,255,255,0.15)"
              strokeWidth="0.8"
            />
            <text
              x={tick.x}
              y={paddingTop + H + 12}
              textAnchor="middle"
              fill="var(--color-ec-text-muted)"
              style={{ fontSize: 7.5, fontFamily: 'monospace' }}
            >
              {tick.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
};

const isEtfOrWarrant = (ticker: string, detail: TickerDetail | null) => {
  if (ticker.endsWith("W")) return true;
  const name = detail?.profile?.name || "";
  if (/(etf|trust|fund|yieldshares|shares 2x|daily target|2x long|2x short|short)/i.test(name)) return true;
  if (detail?.profile?.sector === null && detail?.market?.market_cap === null) return true;
  return false;
};

// ─── Float Comparison Table ───
const KnowTheFloatTable = ({ floatData }: { floatData?: FloatData }) => {
  if (!floatData || Object.keys(floatData).length === 0) {
    return (
      <div style={{
        height: '110px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--color-ec-text-muted)',
        fontSize: '10px',
        border: '1px dashed var(--color-ec-border)',
        borderRadius: '4px',
        width: '100%'
      }}>
        No hay datos de float comparisons
      </div>
    );
  }

  // Dilution Tracker retirado: no tenemos acceso a esa fuente (siempre salía vacío).
  const sources = ["Yahoo Finance", "Finviz", "Wall Street Journal"];

  return (
    <div style={{ overflowX: 'auto', width: '100%' }} className="custom-scrollbar">
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: "'General Sans', sans-serif" }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--color-ec-border)', textAlign: 'left' }}>
            <th style={{ padding: '4px 4px 4px 0', color: 'var(--color-ec-text-secondary)', fontSize: 8, fontWeight: 600 }}>Source</th>
            <th style={{ padding: '4px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 8, fontWeight: 600, textAlign: 'right' }}>Float</th>
            <th style={{ padding: '4px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 8, fontWeight: 600, textAlign: 'right' }}>Short I.%</th>
            <th style={{ padding: '4px 0 4px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 8, fontWeight: 600, textAlign: 'right' }}>Outstanding</th>
          </tr>
        </thead>
        <tbody>
          {sources.map(src => {
            const sData = (floatData && floatData[src]) || { float: '-', short_percent: '-', outstanding: '-' };
            return (
              <tr key={src} style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)' }}>
                <td style={{ padding: '4px 4px 4px 0', fontWeight: 600, color: 'var(--color-ec-text-secondary)' }}>{src}</td>
                <td style={{ padding: '4px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-text-high)', fontFamily: 'monospace' }}>{sData.float || '-'}</td>
                <td style={{ padding: '4px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-loss)', fontFamily: 'monospace' }}>{sData.short_percent || '-'}</td>
                <td style={{ padding: '4px 0 4px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-text-high)', fontFamily: 'monospace' }}>{sData.outstanding || '-'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

// ─── Tab Definitions ────────────────────────────────────────
const TABS: { key: TabKey; label: string; icon: React.ReactNode; disabled?: boolean }[] = [
  { key: "gainers", label: "Top Gainers", icon: <TrendingUp style={{ width: 13, height: 13 }} /> },
  { key: "losers", label: "Top Losers", icon: <TrendingDown style={{ width: 13, height: 13 }} /> },
  { key: "premarket", label: "Premarket", icon: <Sun style={{ width: 13, height: 13 }} />, disabled: true },
  { key: "aftermarket", label: "Aftermarket", icon: <Moon style={{ width: 13, height: 13 }} />, disabled: true },
];

// ─── Table Column Definitions ───────────────────────────────
const COLUMNS: { key: SortField; label: string; align: "left" | "right"; width: string }[] = [
  { key: "ticker", label: "Ticker", align: "left", width: "8%" },
  { key: "price", label: "Price", align: "right", width: "9%" },
  { key: "change_pct", label: "Change %", align: "right", width: "9%" },
  { key: "return_pct", label: "Return %", align: "right", width: "9%" },
  { key: "gap_pct", label: "Gap %", align: "right", width: "8%" },
  { key: "volume", label: "Volume", align: "right", width: "11%" },
  { key: "prev_volume", label: "Prev Vol", align: "right", width: "11%" },
  { key: "prev_close", label: "Prev Close", align: "right", width: "9%" },
  { key: "open", label: "Open", align: "right", width: "8%" },
  { key: "high", label: "High", align: "right", width: "9%" },
  { key: "low", label: "Low", align: "right", width: "9%" },
];

// ─── Mock Data for Blurred Screener ───
const MOCK_SCREENER_DATA: ScreenerDailyResponse = {
  date: "2026-06-19",
  total_records: 46,
  gainers: [
    { ticker: "SPCB", name: "SuperCom Ltd.", price: 3.42, change_pct: 42.50, return_pct: 38.10, gap_pct: 3.10, volume: 12450800, prev_close: 2.40, open: 2.47, high: 3.65, low: 2.45, prev_volume: 850000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 50.0 },
    { ticker: "CNM", name: "Core & Main, Inc.", price: 48.75, change_pct: 12.45, return_pct: 9.30, gap_pct: 2.88, volume: 4820100, prev_close: 43.35, open: 44.60, high: 49.20, low: 44.50, prev_volume: 1200000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 10.5 },
    { ticker: "NVDA", name: "NVIDIA Corporation", price: 127.40, change_pct: 6.85, return_pct: 5.20, gap_pct: 1.57, volume: 42500000, prev_close: 119.23, open: 121.10, high: 128.50, low: 120.80, prev_volume: 38000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 6.3 },
    { ticker: "TSLA", name: "Tesla, Inc.", price: 184.50, change_pct: 4.12, return_pct: 3.80, gap_pct: 0.30, volume: 82000000, prev_close: 177.20, open: 177.73, high: 186.40, low: 176.80, prev_volume: 95000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 5.4 },
    { ticker: "AAPL", name: "Apple Inc.", price: 214.30, change_pct: 2.34, return_pct: 1.95, gap_pct: 0.38, volume: 51200000, prev_close: 209.40, open: 210.20, high: 215.10, low: 209.80, prev_volume: 48000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 2.5 },
    { ticker: "MSFT", name: "Microsoft Corporation", price: 442.15, change_pct: 1.85, return_pct: 1.50, gap_pct: 0.25, volume: 22400000, prev_close: 434.12, open: 435.20, high: 443.50, low: 434.80, prev_volume: 20000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 2.0 },
    { ticker: "AMZN", name: "Amazon.com, Inc.", price: 189.20, change_pct: 1.62, return_pct: 1.20, gap_pct: 0.42, volume: 38500000, prev_close: 186.18, open: 186.96, high: 189.80, low: 186.50, prev_volume: 35000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 1.8 },
    { ticker: "META", name: "Meta Platforms, Inc.", price: 504.60, change_pct: 1.45, return_pct: 1.10, gap_pct: 0.35, volume: 18200000, prev_close: 497.39, open: 499.10, high: 506.20, low: 498.80, prev_volume: 16000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 1.5 },
    { ticker: "GOOGL", name: "Alphabet Inc.", price: 176.45, change_pct: 1.28, return_pct: 0.95, gap_pct: 0.33, volume: 29400000, prev_close: 174.22, open: 174.80, high: 177.20, low: 174.50, prev_volume: 25000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 1.5 },
    { ticker: "AMD", name: "Advanced Micro Devices", price: 161.80, change_pct: 3.82, return_pct: 2.90, gap_pct: 0.90, volume: 52400000, prev_close: 155.85, open: 157.25, high: 162.50, low: 156.80, prev_volume: 48000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 3.6 },
    { ticker: "NFLX", name: "Netflix, Inc.", price: 685.20, change_pct: 2.15, return_pct: 1.80, gap_pct: 0.35, volume: 4100000, prev_close: 670.78, open: 673.10, high: 688.50, low: 672.40, prev_volume: 3800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 2.4 },
    { ticker: "SMCI", name: "Super Micro Computer", price: 920.40, change_pct: 8.45, return_pct: 6.90, gap_pct: 1.55, volume: 9800000, prev_close: 848.70, open: 861.80, high: 932.00, low: 860.50, prev_volume: 8500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 8.3 },
    { ticker: "AVGO", name: "Broadcom Inc.", price: 1645.20, change_pct: 4.88, return_pct: 4.10, gap_pct: 0.95, volume: 3200000, prev_close: 1568.60, open: 1583.50, high: 1650.00, low: 1580.00, prev_volume: 2900000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 4.4 },
    { ticker: "PLTR", name: "Palantir Technologies", price: 25.84, change_pct: 5.12, return_pct: 4.80, gap_pct: 0.50, volume: 38200000, prev_close: 24.58, open: 24.70, high: 26.10, low: 24.62, prev_volume: 25000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 6.0 },
    { ticker: "MU", name: "Micron Technology", price: 139.50, change_pct: 6.10, return_pct: 5.40, gap_pct: 1.10, volume: 18400000, prev_close: 131.48, open: 132.92, high: 141.20, low: 132.50, prev_volume: 14000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 6.5 },
    { ticker: "ARM", name: "Arm Holdings plc", price: 158.20, change_pct: 7.25, return_pct: 6.80, gap_pct: 1.20, volume: 11200000, prev_close: 147.50, open: 149.27, high: 160.50, low: 149.00, prev_volume: 9800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 7.7 },
    { ticker: "QCOM", name: "Qualcomm Incorporated", price: 212.40, change_pct: 3.15, return_pct: 2.80, gap_pct: 0.40, volume: 8900000, prev_close: 205.91, open: 206.73, high: 214.20, low: 206.50, prev_volume: 7200000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 3.7 },
    { ticker: "MARA", name: "Marathon Digital", price: 19.85, change_pct: 11.20, return_pct: 9.80, gap_pct: 2.10, volume: 28400000, prev_close: 17.85, open: 18.22, high: 20.40, low: 18.15, prev_volume: 15000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 12.3 },
    { ticker: "RIOT", name: "Riot Platforms, Inc.", price: 10.45, change_pct: 9.42, return_pct: 8.50, gap_pct: 1.80, volume: 19200000, prev_close: 9.55, open: 9.72, high: 10.75, low: 9.68, prev_volume: 11000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 11.0 },
    { ticker: "ASTS", name: "AST SpaceMobile", price: 12.18, change_pct: 18.25, return_pct: 15.40, gap_pct: 3.50, volume: 15600000, prev_close: 10.30, open: 10.66, high: 12.75, low: 10.55, prev_volume: 4500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 20.8 },
    { ticker: "LUNR", name: "Intuitive Machines", price: 5.62, change_pct: 14.70, return_pct: 12.10, gap_pct: 2.50, volume: 8400000, prev_close: 4.90, open: 5.02, high: 5.85, low: 5.00, prev_volume: 2100000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 17.0 },
    { ticker: "DJT", name: "Trump Media & Tech", price: 34.50, change_pct: 8.15, return_pct: 7.20, gap_pct: 1.50, volume: 14500000, prev_close: 31.90, open: 32.38, high: 35.80, low: 32.20, prev_volume: 9800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 11.1 },
    { ticker: "MSTR", name: "MicroStrategy Inc.", price: 1480.00, change_pct: 9.63, return_pct: 8.10, gap_pct: 2.00, volume: 2200000, prev_close: 1350.00, open: 1377.00, high: 1495.00, low: 1375.00, prev_volume: 1800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 8.7 },
    { ticker: "TEM", name: "Tempus AI, Inc.", price: 36.42, change_pct: 16.36, return_pct: 14.10, gap_pct: 2.80, volume: 5400000, prev_close: 31.30, open: 32.18, high: 37.50, low: 32.10, prev_volume: 1500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 16.8 },
    { ticker: "HOLO", name: "MicroCloud Hologram", price: 1.84, change_pct: 24.32, return_pct: 21.00, gap_pct: 4.10, volume: 38500000, prev_close: 1.48, open: 1.54, high: 1.98, low: 1.52, prev_volume: 4500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 30.2 },
    { ticker: "SOUN", name: "SoundHound AI, Inc.", price: 4.88, change_pct: 8.44, return_pct: 7.50, gap_pct: 1.20, volume: 16200000, prev_close: 4.50, open: 4.55, high: 4.98, low: 4.53, prev_volume: 9800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 9.9 }
  ],
  losers: [
    { ticker: "GME", name: "GameStop Corp.", price: 24.15, change_pct: -15.40, return_pct: -14.20, gap_pct: -1.40, volume: 18500000, prev_close: 28.55, open: 28.15, high: 28.30, low: 23.80, prev_volume: 32000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 15.8 },
    { ticker: "AMC", name: "AMC Entertainment Holdings", price: 4.62, change_pct: -8.70, return_pct: -8.10, gap_pct: -0.65, volume: 9800000, prev_close: 5.06, open: 5.03, high: 5.05, low: 4.58, prev_volume: 12000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 9.3 },
    { ticker: "BABA", name: "Alibaba Group Holding", price: 74.80, change_pct: -3.12, return_pct: -2.80, gap_pct: -0.32, volume: 14200000, prev_close: 77.21, open: 76.96, high: 77.10, low: 74.50, prev_volume: 12000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 3.5 },
    { ticker: "NIO", name: "NIO Inc.", price: 4.35, change_pct: -5.43, return_pct: -4.90, gap_pct: -0.53, volume: 32400000, prev_close: 4.60, open: 4.58, high: 4.59, low: 4.31, prev_volume: 25000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 6.1 },
    { ticker: "INTC", name: "Intel Corporation", price: 30.25, change_pct: -2.85, return_pct: -2.30, gap_pct: -0.55, volume: 48000000, prev_close: 31.14, open: 30.97, high: 31.05, low: 30.15, prev_volume: 35000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 2.9 },
    { ticker: "WBD", name: "Warner Bros. Discovery", price: 7.14, change_pct: -4.16, return_pct: -3.80, gap_pct: -0.36, volume: 28500000, prev_close: 7.45, open: 7.42, high: 7.44, low: 7.10, prev_volume: 2200000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 4.6 },
    { ticker: "PFE", name: "Pfizer Inc.", price: 27.85, change_pct: -1.94, return_pct: -1.50, gap_pct: -0.44, volume: 19500000, prev_close: 28.40, open: 28.28, high: 28.35, low: 27.75, prev_volume: 18000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 2.1 },
    { ticker: "COIN", name: "Coinbase Global, Inc.", price: 224.50, change_pct: -6.45, return_pct: -5.80, gap_pct: -0.65, volume: 8200000, prev_close: 239.98, open: 238.42, high: 239.00, low: 222.10, prev_volume: 7500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 7.1 },
    { ticker: "UPST", name: "Upstart Holdings, Inc.", price: 21.40, change_pct: -12.15, return_pct: -11.00, gap_pct: -2.30, volume: 6400000, prev_close: 24.36, open: 23.80, high: 23.95, low: 21.15, prev_volume: 4500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 13.1 },
    { ticker: "CVNA", name: "Carvana Co.", price: 108.50, change_pct: -7.42, return_pct: -6.80, gap_pct: -1.10, volume: 5800000, prev_close: 117.20, open: 115.90, high: 116.10, low: 107.80, prev_volume: 4800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 7.7 },
    { ticker: "BYND", name: "Beyond Meat, Inc.", price: 6.84, change_pct: -9.80, return_pct: -8.90, gap_pct: -1.50, volume: 4100000, prev_close: 7.58, open: 7.47, high: 7.49, low: 6.78, prev_volume: 3200000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 10.5 },
    { ticker: "SPCE", name: "Virgin Galactic", price: 1.15, change_pct: -14.18, return_pct: -12.50, gap_pct: -2.80, volume: 15400000, prev_close: 1.34, open: 1.30, high: 1.31, low: 1.12, prev_volume: 8500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 16.0 },
    { ticker: "NKLA", name: "Nikola Corporation", price: 8.24, change_pct: -11.40, return_pct: -10.10, gap_pct: -1.90, volume: 11800000, prev_close: 9.30, open: 9.12, high: 9.15, low: 8.18, prev_volume: 9200000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 11.8 },
    { ticker: "MULN", name: "Mullen Automotive", price: 2.10, change_pct: -18.60, return_pct: -16.40, gap_pct: -3.80, volume: 22400000, prev_close: 2.58, open: 2.48, high: 2.49, low: 2.05, prev_volume: 18500000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 21.0 },
    { ticker: "RIVN", name: "Rivian Automotive", price: 10.82, change_pct: -5.18, return_pct: -4.60, gap_pct: -0.80, volume: 14500000, prev_close: 11.41, open: 11.32, high: 11.35, low: 10.75, prev_volume: 12000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 5.5 },
    { ticker: "LCID", name: "Lucid Group, Inc.", price: 2.48, change_pct: -4.62, return_pct: -4.10, gap_pct: -0.50, volume: 16800000, prev_close: 2.60, open: 2.59, high: 2.60, low: 2.45, prev_volume: 14000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 5.7 },
    { ticker: "HOOD", name: "Robinhood Markets", price: 20.15, change_pct: -3.59, return_pct: -3.10, gap_pct: -0.40, volume: 12400000, prev_close: 20.90, open: 20.82, high: 20.85, low: 20.02, prev_volume: 11000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 4.1 },
    { ticker: "PLUG", name: "Plug Power Inc.", price: 2.34, change_pct: -8.23, return_pct: -7.50, gap_pct: -1.10, volume: 18900000, prev_close: 2.55, open: 2.52, high: 2.53, low: 2.31, prev_volume: 15000000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 8.7 },
    { ticker: "RUN", name: "Sunrun Inc.", price: 12.40, change_pct: -6.41, return_pct: -5.90, gap_pct: -0.90, volume: 9200000, prev_close: 13.25, open: 13.13, high: 13.15, low: 12.32, prev_volume: 7800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 6.7 },
    { ticker: "ENPH", name: "Enphase Energy", price: 114.50, change_pct: -5.84, return_pct: -5.20, gap_pct: -0.80, volume: 4500000, prev_close: 121.60, open: 120.63, high: 120.70, low: 113.80, prev_volume: 3800000, high_spike_pct: 0, low_spike_pct: 0, range_pct: 6.0 }
  ],
  premarket: [],
  aftermarket: []
};

const MOCK_TICKER_DETAIL_SPCB: TickerDetail = {
  profile: {
    name: "SuperCom Ltd.",
    sector: "Technology",
    industry: "Security Software & Services",
    exchange: "NASDAQ",
    logo_url: ""
  },
  market: {
    market_cap: 35200000,
    shares_outstanding: 10290000,
    float_shares: 8900000,
    held_percent_institutions: 8.5,
    held_percent_insiders: 12.4,
    price: 3.42
  }
};

const MOCK_GAP_STATS_SPCB: GapStatsResponse = {
  know_the_float: {
    "Yahoo Finance": { float: "8.85M", short_percent: "13.9%", outstanding: "10.29M" },
    "Finviz": { float: "8.90M", short_percent: "14.2%", outstanding: "10.29M" },
    "Wall Street Journal": { float: "8.90M", short_percent: "14.0%", outstanding: "10.29M" }
  },
  gap_stats: {
    gap_days_count: 24,
    high_rth_spike_avg: 42.50,
    pm_fade_avg: -15.20,
    low_rth_spike_avg: -2.10,
    rthh_fade_avg: 35.80,
    neg_close_freq: 65.0,
    close_above_pmh_freq: 28.0,
    close_below_vwap_freq: 58.0,
    price_change_chart: [
      { bin: "09:30", avg_change_pct: 12.4, is_premarket: false },
      { bin: "10:00", avg_change_pct: 28.5, is_premarket: false },
      { bin: "11:00", avg_change_pct: 35.2, is_premarket: false },
      { bin: "12:00", avg_change_pct: 22.1, is_premarket: false },
      { bin: "13:00", avg_change_pct: 18.4, is_premarket: false },
      { bin: "14:00", avg_change_pct: 15.2, is_premarket: false },
      { bin: "15:00", avg_change_pct: 25.8, is_premarket: false },
      { bin: "16:00", avg_change_pct: 38.1, is_premarket: false }
    ]
  },
  gap_stats_plus_1: {
    gap_days_count: 24,
    high_rth_spike_avg: 8.50,
    pm_fade_avg: -5.10,
    low_rth_spike_avg: -6.40,
    rthh_fade_avg: 4.20,
    neg_close_freq: 72.0,
    close_above_pmh_freq: 12.0,
    close_below_vwap_freq: 75.0,
    price_change_chart: []
  },
  gap_stats_plus_2: {
    gap_days_count: 24,
    high_rth_spike_avg: 3.10,
    pm_fade_avg: -2.30,
    low_rth_spike_avg: -8.90,
    rthh_fade_avg: 1.50,
    neg_close_freq: 80.0,
    close_above_pmh_freq: 5.0,
    close_below_vwap_freq: 85.0,
    price_change_chart: []
  }
};

const MOCK_TICKER_DETAIL_CNM: TickerDetail = {
  profile: {
    name: "Core & Main, Inc.",
    sector: "Industrials",
    industry: "Industrial Distribution",
    exchange: "NYSE",
    logo_url: ""
  },
  market: {
    market_cap: 10400000000,
    shares_outstanding: 213000000,
    float_shares: 185000000,
    held_percent_institutions: 94.2,
    held_percent_insiders: 1.8,
    price: 48.75
  }
};

const MOCK_GAP_STATS_CNM: GapStatsResponse = {
  know_the_float: {
    "Yahoo Finance": { float: "184.60M", short_percent: "4.5%", outstanding: "213.00M" },
    "Finviz": { float: "185.00M", short_percent: "4.8%", outstanding: "213.00M" },
    "Wall Street Journal": { float: "185.00M", short_percent: "4.7%", outstanding: "213.00M" }
  },
  gap_stats: {
    gap_days_count: 15,
    high_rth_spike_avg: 12.45,
    pm_fade_avg: -4.30,
    low_rth_spike_avg: -1.15,
    rthh_fade_avg: 10.20,
    neg_close_freq: 48.0,
    close_above_pmh_freq: 35.0,
    close_below_vwap_freq: 42.0,
    price_change_chart: [
      { bin: "09:30", avg_change_pct: 3.1, is_premarket: false },
      { bin: "10:00", avg_change_pct: 6.4, is_premarket: false },
      { bin: "11:00", avg_change_pct: 9.8, is_premarket: false },
      { bin: "12:00", avg_change_pct: 8.5, is_premarket: false },
      { bin: "13:00", avg_change_pct: 7.9, is_premarket: false },
      { bin: "14:00", avg_change_pct: 8.2, is_premarket: false },
      { bin: "15:00", avg_change_pct: 10.4, is_premarket: false },
      { bin: "16:00", avg_change_pct: 12.45, is_premarket: false }
    ]
  },
  gap_stats_plus_1: {
    gap_days_count: 15,
    high_rth_spike_avg: 3.20,
    pm_fade_avg: -1.10,
    low_rth_spike_avg: -2.30,
    rthh_fade_avg: 1.80,
    neg_close_freq: 55.0,
    close_above_pmh_freq: 20.0,
    close_below_vwap_freq: 60.0,
    price_change_chart: []
  },
  gap_stats_plus_2: {
    gap_days_count: 15,
    high_rth_spike_avg: 1.50,
    pm_fade_avg: -0.50,
    low_rth_spike_avg: -3.80,
    rthh_fade_avg: 0.80,
    neg_close_freq: 58.0,
    close_above_pmh_freq: 15.0,
    close_below_vwap_freq: 65.0,
    price_change_chart: []
  }
};

const getMockDetail = (ticker: string): TickerDetail => {
  if (ticker === "CNM") return MOCK_TICKER_DETAIL_CNM;
  if (ticker === "SPCB") return MOCK_TICKER_DETAIL_SPCB;

  const allRecords = [...MOCK_SCREENER_DATA.gainers, ...MOCK_SCREENER_DATA.losers];
  const rec = allRecords.find(r => r.ticker === ticker);
  const name = rec ? rec.name : `${ticker} Inc.`;
  const price = rec ? rec.price : 10.0;

  return {
    profile: {
      name: name,
      sector: "Technology",
      industry: "Software & Services",
      exchange: ticker.length === 3 ? "NYSE" : "NASDAQ",
      logo_url: ""
    },
    market: {
      market_cap: price * 125000000,
      shares_outstanding: 125000000,
      float_shares: 98000000,
      held_percent_institutions: 0.65,
      held_percent_insiders: 0.12,
      price: price
    }
  };
};

const getMockGapStats = (ticker: string): GapStatsResponse => {
  if (ticker === "CNM") return MOCK_GAP_STATS_CNM;
  if (ticker === "SPCB") return MOCK_GAP_STATS_SPCB;

  const allRecords = [...MOCK_SCREENER_DATA.gainers, ...MOCK_SCREENER_DATA.losers];
  const rec = allRecords.find(r => r.ticker === ticker);
  const change = rec ? rec.change_pct : 15.0;

  return {
    know_the_float: {
      "Yahoo Finance": { float: "95.2M", short_percent: "8.5%", outstanding: "125.0M" },
      "Finviz": { float: "98.0M", short_percent: "8.2%", outstanding: "125.0M" },
      "Wall Street Journal": { float: "98.0M", short_percent: "8.3%", outstanding: "125.0M" }
    },
    gap_stats: {
      gap_days_count: 12,
      high_rth_spike_avg: Math.abs(change) * 1.2,
      pm_fade_avg: -Math.abs(change) * 0.4,
      low_rth_spike_avg: -1.5,
      rthh_fade_avg: Math.abs(change) * 0.8,
      neg_close_freq: change > 0 ? 55.0 : 45.0,
      close_above_pmh_freq: change > 0 ? 30.0 : 20.0,
      close_below_vwap_freq: 52.0,
      price_change_chart: [
        { bin: "09:30", avg_change_pct: change * 0.2, is_premarket: false },
        { bin: "10:00", avg_change_pct: change * 0.6, is_premarket: false },
        { bin: "12:00", avg_change_pct: change * 0.8, is_premarket: false },
        { bin: "16:00", avg_change_pct: change, is_premarket: false }
      ]
    },
    gap_stats_plus_1: {
      gap_days_count: 12,
      high_rth_spike_avg: 4.5,
      pm_fade_avg: -2.0,
      low_rth_spike_avg: -3.5,
      rthh_fade_avg: 2.1,
      neg_close_freq: 60.0,
      close_above_pmh_freq: 15.0,
      close_below_vwap_freq: 65.0,
      price_change_chart: []
    },
    gap_stats_plus_2: {
      gap_days_count: 12,
      high_rth_spike_avg: 2.1,
      pm_fade_avg: -1.0,
      low_rth_spike_avg: -5.0,
      rthh_fade_avg: 0.8,
      neg_close_freq: 62.0,
      close_above_pmh_freq: 10.0,
      close_below_vwap_freq: 70.0,
      price_change_chart: []
    }
  };
};

// ═══════════════════════════════════════════════════════════
//  MAIN COMPONENT
// ═══════════════════════════════════════════════════════════
export default function Screener() {
  // ── Data state ──
  const [data, setData] = useState<ScreenerDailyResponse | null>(MOCK_SCREENER_DATA);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── UI state ──
  const [activeTab, setActiveTab] = useState<TabKey>("gainers");
  const [selectedTicker, setSelectedTicker] = useState<string | null>("SPCB");
  const [sortField, setSortField] = useState<SortField>("change_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // ── Detail panel state ──
  const [tickerDetail, setTickerDetail] = useState<TickerDetail | null>(MOCK_TICKER_DETAIL_SPCB);
  const [profileLoading, setProfileLoading] = useState(false);
  const [gapLoading, setGapLoading] = useState(false);
  const [gapStatsResponse, setGapStatsResponse] = useState<GapStatsResponse | null>(MOCK_GAP_STATS_SPCB);
  const [activeSubTab, setActiveSubTab] = useState<"day0" | "day1" | "day2">("day0");
  const [floatCollapsed, setFloatCollapsed] = useState(false); // floats uncollapsed so they are visible

  // ── Fetch screener data ──
  useEffect(() => {
    // Usar directamente los mocks locales estáticos para que se renderice instantáneamente de forma completa
    setData(MOCK_SCREENER_DATA);
    setSelectedTicker("SPCB");
    setLoading(false);
    setError(null);
  }, []);

  // ── Fetch ticker detail when selection changes ──
  useEffect(() => {
    if (!selectedTicker) {
      setTickerDetail(null);
      setGapStatsResponse(null);
      setProfileLoading(false);
      setGapLoading(false);
      return;
    }

    // Usar datos mockeados dinámicos locales síncronamente
    setTickerDetail(getMockDetail(selectedTicker));
    setGapStatsResponse(getMockGapStats(selectedTicker));
    setProfileLoading(false);
    setGapLoading(false);
  }, [selectedTicker]);

  // ── Get current stats by active sub-tab ──
  const currentStats = gapStatsResponse
    ? activeSubTab === "day0"
      ? gapStatsResponse.gap_stats
      : activeSubTab === "day1"
        ? gapStatsResponse.gap_stats_plus_1
        : gapStatsResponse.gap_stats_plus_2
    : null;

  // ── Get current tab records ──
  const getRecords = useCallback((): ScreenerRecord[] => {
    if (!data) return [];
    return data[activeTab] || [];
  }, [data, activeTab]);

  // ── Sort records ──
  const sortedRecords = useCallback((): ScreenerRecord[] => {
    const recs = [...getRecords()];
    recs.sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const na = typeof av === "number" ? av : 0;
      const nb = typeof bv === "number" ? bv : 0;
      return sortDir === "asc" ? na - nb : nb - na;
    });
    return recs;
  }, [getRecords, sortField, sortDir]);

  // ── Handle column sort ──
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir(field === "ticker" ? "asc" : "desc");
    }
  };

  // ── Handle tab change ──
  const handleTabChange = (tab: TabKey) => {
    setActiveTab(tab);
    setSelectedTicker(null);
    // Reset sort to default for each tab
    if (tab === "gainers") { setSortField("change_pct"); setSortDir("desc"); }
    else if (tab === "losers") { setSortField("change_pct"); setSortDir("asc"); }
    else { setSortField("volume"); setSortDir("desc"); }
  };

  // ═══════════════════════════════════════════════════════
  //  RENDER
  // ═══════════════════════════════════════════════════════
  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100dvh",
      fontFamily: "'General Sans', sans-serif",
      backgroundColor: "var(--color-ec-bg-base)",
      overflow: "hidden",
      position: "relative",
    }}>
      {/* ── Header ── */}
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px 24px",
        borderBottom: "1px solid var(--color-ec-border)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h1 style={{
            fontSize: 18,
            fontWeight: 700,
            color: "var(--color-ec-text-high)",
            margin: 0,
            letterSpacing: "-0.3px",
          }}>
            Screener
          </h1>
          {data?.date && (
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              color: "var(--color-ec-copper)",
              backgroundColor: "rgba(216,122,61,0.1)",
              padding: "3px 8px",
              borderRadius: 4,
              letterSpacing: "0.5px",
              textTransform: "uppercase",
            }}>
              {data.date}
            </span>
          )}
          {data && (
            <span style={{
              fontSize: 10,
              fontWeight: 500,
              color: "var(--color-ec-text-muted)",
            }}>
              {data.total_records} tickers
            </span>
          )}
        </div>
      </header>

      {/* ── Body ── */}
      <div style={{
        flex: 1,
        display: "flex",
        minHeight: 0,
        overflow: "hidden",
      }}>
        {/* ══════════════════════════════════════════════════
             LEFT PANEL — Table
           ══════════════════════════════════════════════════ */}
        <div style={{
          flex: selectedTicker ? "1 1 calc(100% - 440px)" : "1 1 100%",
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
          borderRight: selectedTicker ? "1px solid var(--color-ec-border)" : "none",
          transition: "flex 250ms ease",
        }}>
          {/* Tabs */}
          <div style={{
            display: "flex",
            gap: 0,
            padding: "0 24px",
            borderBottom: "1px solid var(--color-ec-border)",
            flexShrink: 0,
          }}>
            {TABS.map((tab) => {
              const isActive = activeTab === tab.key;
              const isDisabled = tab.disabled;
              return (
                <button
                  key={tab.key}
                  onClick={() => !isDisabled && handleTabChange(tab.key)}
                  disabled={isDisabled}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "12px 16px",
                    border: "none",
                    borderBottom: isActive ? "2px solid var(--color-ec-copper)" : "2px solid transparent",
                    background: "transparent",
                    color: isDisabled
                      ? "var(--color-ec-text-muted)"
                      : isActive
                        ? "var(--color-ec-copper)"
                        : "var(--color-ec-text-secondary)",
                    fontSize: 9.5,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "1.5px",
                    fontFamily: "'General Sans', sans-serif",
                    cursor: isDisabled ? "not-allowed" : "pointer",
                    transition: "all 150ms ease",
                    opacity: isDisabled ? 0.4 : 1,
                  }}
                >
                  {tab.icon}
                  {tab.label}
                  {isDisabled && (
                    <span style={{
                      fontSize: 7.5,
                      fontWeight: 700,
                      color: "var(--color-ec-text-muted)",
                      backgroundColor: "var(--color-ec-bg-elevated)",
                      padding: "1px 4px",
                      borderRadius: 2,
                      textTransform: "uppercase",
                      letterSpacing: "0.5px",
                      marginLeft: 4,
                    }}>
                      Soon
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Table */}
          <div style={{ flex: 1, overflow: "auto", padding: 0 }} className="custom-scrollbar">
            {loading ? (
              <div style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
                gap: 12,
              }}>
                <Loader2
                  style={{
                    width: 28,
                    height: 28,
                    color: "var(--color-ec-copper)",
                    animation: "spin 1s linear infinite",
                  }}
                />
                <span style={{ fontSize: 12, color: "var(--color-ec-text-secondary)" }}>
                  Loading screener data…
                </span>
                <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
              </div>
            ) : error ? (
              <div style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
                gap: 10,
              }}>
                <AlertCircle style={{ width: 24, height: 24, color: "var(--color-ec-loss)" }} />
                <span style={{ fontSize: 12, color: "var(--color-ec-loss)" }}>{error}</span>
              </div>
            ) : (
              <table style={{
                width: "100%",
                borderCollapse: "collapse",
                tableLayout: "fixed",
              }}>
                {/* Table Header */}
                <thead>
                  <tr>
                    {COLUMNS.map((col) => (
                      <th
                        key={col.key}
                        onClick={() => handleSort(col.key)}
                        style={{
                          position: "sticky",
                          top: 0,
                          backgroundColor: "var(--color-ec-bg-surface)",
                          padding: "4px 8px",
                          textAlign: col.align,
                          fontSize: 9,
                          fontWeight: 700,
                          color: sortField === col.key ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)",
                          textTransform: "uppercase",
                          letterSpacing: "0.5px",
                          cursor: "pointer",
                          userSelect: "none",
                          width: col.width,
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          borderBottom: "2px solid var(--color-ec-border)",
                          whiteSpace: "nowrap",
                          transition: "color 150ms ease",
                          zIndex: 2,
                        }}
                      >
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                          {col.label}
                          {sortField === col.key && (
                            sortDir === "asc"
                              ? <ChevronUp style={{ width: 10, height: 10 }} />
                              : <ChevronDown style={{ width: 10, height: 10 }} />
                          )}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>

                {/* Table Body */}
                <tbody>
                  {sortedRecords().length === 0 ? (
                    <tr>
                      <td colSpan={COLUMNS.length} style={{
                        padding: "60px 0",
                        textAlign: "center",
                        color: "var(--color-ec-text-muted)",
                        fontSize: 12,
                      }}>
                        {activeTab === "premarket" || activeTab === "aftermarket"
                          ? "Coming soon — real-time data integration required."
                          : "No records found for this category."}
                      </td>
                    </tr>
                  ) : (
                    sortedRecords().map((rec, i) => {
                      const isSelected = selectedTicker === rec.ticker;
                      const changeColor = rec.change_pct > 0
                        ? "var(--color-ec-profit)"
                        : rec.change_pct < 0
                          ? "var(--color-ec-loss)"
                          : "var(--color-ec-text-secondary)";
                      const gapColor = rec.gap_pct > 0
                        ? "var(--color-ec-profit)"
                        : rec.gap_pct < 0
                          ? "var(--color-ec-loss)"
                          : "var(--color-ec-text-secondary)";
                      const returnColor = rec.return_pct > 0
                        ? "var(--color-ec-profit)"
                        : rec.return_pct < 0
                          ? "var(--color-ec-loss)"
                          : "var(--color-ec-text-secondary)";

                      return (
                        <tr
                          key={rec.ticker}
                          onClick={() => setSelectedTicker(rec.ticker)}
                          style={{
                            cursor: "pointer",
                            backgroundColor: isSelected
                              ? "rgba(216,122,61,0.08)"
                              : i % 2 === 0
                                ? "transparent"
                                : "rgba(255,255,255,0.01)",
                            transition: "background-color 120ms ease",
                          }}
                          onMouseEnter={(e) => {
                            if (!isSelected) e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.03)";
                          }}
                          onMouseLeave={(e) => {
                            if (!isSelected) {
                              e.currentTarget.style.backgroundColor = i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)";
                            }
                          }}
                        >
                          {/* Ticker */}
                          <td style={{
                            padding: "4px 8px",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontSize: 10.5,
                            fontWeight: 700,
                            color: "var(--color-ec-text-high)",
                            fontFamily: "monospace",
                          }}>
                            {rec.ticker}
                          </td>

                          {/* Price */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-high)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            ${fmtPrice(rec.price)}
                          </td>

                          {/* Change % */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 700,
                            color: changeColor,
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {fmtPct(rec.change_pct)}
                          </td>

                          {/* Return % */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: returnColor,
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {fmtPct(rec.return_pct)}
                          </td>

                          {/* Gap % */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: gapColor,
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {fmtPct(rec.gap_pct)}
                          </td>

                          {/* Volume */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {fmtVol(rec.volume)}
                          </td>

                          {/* Prev Vol */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {rec.prev_volume ? fmtVol(rec.prev_volume) : "—"}
                          </td>

                          {/* Prev Close */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {rec.prev_close ? `$${fmtPrice(rec.prev_close)}` : "—"}
                          </td>

                          {/* Open */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {rec.open ? `$${fmtPrice(rec.open)}` : "—"}
                          </td>

                          {/* High */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {rec.high ? `$${fmtPrice(rec.high)}` : "—"}
                          </td>

                          {/* Low */}
                          <td style={{
                            padding: "4px 8px",
                            textAlign: "right",
                            fontSize: 10.5,
                            fontWeight: 500,
                            color: "var(--color-ec-text-secondary)",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "monospace",
                          }}>
                            {rec.low ? `$${fmtPrice(rec.low)}` : "—"}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* ══════════════════════════════════════════════════
             RIGHT PANEL — Ticker Detail
           ══════════════════════════════════════════════════ */}
        {selectedTicker && (
          <div
            style={{
              flex: "0 0 440px",
              display: "flex",
              flexDirection: "column",
              overflow: "auto",
              backgroundColor: "var(--color-ec-bg-base)",
            }}
            className="custom-scrollbar"
          >
            {/* Detail Header */}
            <div style={{
              padding: "8px 16px",
              borderBottom: "1px solid var(--color-ec-border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexShrink: 0,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {tickerDetail?.profile?.logo_url && (
                  <img
                    src={tickerDetail.profile.logo_url}
                    alt=""
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: 4,
                      objectFit: "contain",
                      backgroundColor: "var(--color-ec-bg-elevated)",
                    }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <h2 style={{
                      fontFamily: "'Fraunces', serif",
                      fontSize: 22,
                      fontWeight: 600,
                      color: "var(--color-ec-text-high)",
                      margin: 0,
                      letterSpacing: "-0.5px",
                      lineHeight: "1.1",
                    }}>
                      {selectedTicker}
                    </h2>
                    {tickerDetail?.profile?.exchange && (
                      <span style={{
                        fontSize: 8,
                        fontWeight: 700,
                        color: "var(--color-ec-text-muted)",
                        backgroundColor: "var(--color-ec-bg-elevated)",
                        border: "0.5px solid var(--color-ec-border)",
                        padding: "1px 5px",
                        borderRadius: 3,
                        textTransform: "uppercase",
                        letterSpacing: "1px",
                        lineHeight: "1",
                      }}>
                        {tickerDetail.profile.exchange}
                      </span>
                    )}
                  </div>
                  <span style={{
                    fontSize: 10,
                    fontWeight: 500,
                    color: "var(--color-ec-text-muted)",
                    lineHeight: "1.2",
                  }}>
                    {tickerDetail?.profile?.name || ""}
                  </span>
                </div>
              </div>
              {/* Close button */}
              <button
                onClick={() => setSelectedTicker(null)}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--color-ec-text-muted)",
                  cursor: "pointer",
                  fontSize: 16,
                  padding: "4px 8px",
                  borderRadius: 4,
                  transition: "all 150ms ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = "var(--color-ec-text-high)";
                  e.currentTarget.style.backgroundColor = "var(--color-ec-bg-elevated)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = "var(--color-ec-text-muted)";
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                ✕
              </button>
            </div>

            <div style={{
              display: "flex",
              flexDirection: "column",
              gap: 0,
              padding: 0,
            }}>
              {/* ── Market Data Section ── */}
              <DetailSection title="Market Data">
                {profileLoading ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 0" }}>
                    <Loader2 style={{ width: 12, height: 12, color: "var(--color-ec-copper)", animation: "spin 1s linear infinite" }} />
                    <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)" }}>Loading market data...</span>
                  </div>
                ) : (
                  <DetailGrid>
                    <DetailItem label="Market Cap" value={fmtMarketCap(tickerDetail?.market?.market_cap)} />
                    <DetailItem label="Shares Out." value={fmtShares(tickerDetail?.market?.shares_outstanding)} prefix="" />
                    <DetailItem label="Float Shares" value={fmtShares(tickerDetail?.market?.float_shares)} prefix="" />
                    <DetailItem
                      label="Institutional %"
                      value={tickerDetail?.market?.held_percent_institutions != null
                        ? `${(tickerDetail.market.held_percent_institutions * 100).toFixed(1)}%`
                        : "—"}
                    />
                    <DetailItem
                      label="Insider %"
                      value={tickerDetail?.market?.held_percent_insiders != null
                        ? `${(tickerDetail.market.held_percent_insiders * 100).toFixed(1)}%`
                        : "—"}
                    />
                    <DetailItem label="Price" value={tickerDetail?.market?.price != null ? `$${fmtPrice(tickerDetail.market.price)}` : "—"} />
                  </DetailGrid>
                )}
              </DetailSection>

              {/* ── Profile Section ── */}
              <DetailSection title="Profile">
                {profileLoading ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 0" }}>
                    <Loader2 style={{ width: 12, height: 12, color: "var(--color-ec-copper)", animation: "spin 1s linear infinite" }} />
                    <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)" }}>Loading profile...</span>
                  </div>
                ) : tickerDetail?.profile ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <DetailGrid>
                      <DetailItem label="Sector" value={tickerDetail.profile.sector || "—"} />
                      <DetailItem label="Industry" value={tickerDetail.profile.industry || "—"} />
                      <DetailItem label="Exchange" value={tickerDetail.profile.exchange || "—"} />
                    </DetailGrid>
                    {isEtfOrWarrant(selectedTicker, tickerDetail) && (
                      <div style={{
                        fontSize: 9,
                        color: "var(--color-ec-text-muted)",
                        backgroundColor: "rgba(255, 255, 255, 0.02)",
                        padding: "6px 8px",
                        borderRadius: 4,
                        border: "1px solid rgba(255, 255, 255, 0.05)",
                        marginTop: 4,
                        lineHeight: "1.3"
                      }}>
                        ℹ️ Este ticker es un ETF o Warrant. Los datos de sector, industria y float no aplican.
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 10, color: "var(--color-ec-text-muted)" }}>No profile data available.</div>
                )}
              </DetailSection>

              {/* ── Runner Stats Section ── */}
              <div style={{
                padding: "8px 16px",
                borderBottom: "1px solid var(--color-ec-border)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}>
                <div style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}>
                  <span style={{
                    fontSize: 8,
                    fontWeight: 700,
                    color: "var(--color-ec-copper)",
                    textTransform: "uppercase",
                    letterSpacing: "1.5px",
                  }}>
                    Runner Stats (PMH ≥ 20%) {currentStats && currentStats.gap_days_count > 0 ? `(${currentStats.gap_days_count} runners)` : ""}
                  </span>

                  {/* Day offset sub-tabs */}
                  <div style={{ display: 'flex', gap: 3 }}>
                    {(['day0', 'day1', 'day2'] as const).map(tab => {
                      const label = tab === 'day0' ? 'D0' : tab === 'day1' ? 'D+1' : 'D+2';
                      const isActive = activeSubTab === tab;
                      return (
                        <button
                          key={tab}
                          onClick={() => setActiveSubTab(tab)}
                          style={{
                            background: isActive ? 'var(--color-ec-copper)' : 'transparent',
                            border: 'none',
                            borderRadius: 2,
                            color: isActive ? '#ffffff' : 'var(--color-ec-text-secondary)',
                            fontSize: 7.5,
                            fontWeight: 700,
                            padding: '1px 4px',
                            cursor: 'pointer',
                            textTransform: 'uppercase',
                            letterSpacing: '0.3px',
                            transition: 'all 120ms ease'
                          }}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {gapLoading ? (
                  <div style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 6,
                    padding: "24px 0",
                  }}>
                    <Loader2
                      style={{
                        width: 16,
                        height: 16,
                        color: "var(--color-ec-copper)",
                        animation: "spin 1s linear infinite",
                      }}
                    />
                    <span style={{ fontSize: 9, color: "var(--color-ec-text-secondary)" }}>
                      Calculating runner stats…
                    </span>
                  </div>
                ) : !currentStats || currentStats.gap_days_count === 0 ? (
                  <div style={{
                    padding: "16px 12px",
                    textAlign: "center",
                    color: "var(--color-ec-text-muted)",
                    fontSize: 9.5,
                    border: "1px dashed var(--color-ec-border)",
                    borderRadius: 4,
                    lineHeight: "1.3"
                  }}>
                    {isEtfOrWarrant(selectedTicker, tickerDetail)
                      ? "Runner stats no calculados para ETFs o Warrants."
                      : "Sin estadísticas de runner (este ticker no tiene gaps ≥ 20% registrados)."}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {/* Split metrics left + chart right */}
                    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", width: "100%" }}>
                      {/* Metrics left */}
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, width: "32%", flexShrink: 0 }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                          <span style={{ fontSize: 7.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>High RTH Spike</span>
                          <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--color-ec-text-high)", fontFamily: "monospace" }}>{fmtStatPct(currentStats.high_rth_spike_avg)}</span>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                          <span style={{ fontSize: 7.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>% PM Fade</span>
                          <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--color-ec-text-high)", fontFamily: "monospace" }}>{fmtStatPct(currentStats.pm_fade_avg)}</span>
                        </div>
                        <div style={{ borderTop: "1px solid rgba(255,255,255,0.05)", margin: "1px 0" }} />
                        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                          <span style={{ fontSize: 7.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Low RTH Spike</span>
                          <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--color-ec-text-high)", fontFamily: "monospace" }}>{fmtStatPct(currentStats.low_rth_spike_avg)}</span>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                          <span style={{ fontSize: 7.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>% RTHH Fade</span>
                          <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--color-ec-text-high)", fontFamily: "monospace" }}>{fmtStatPct(currentStats.rthh_fade_avg)}</span>
                        </div>
                      </div>

                      {/* Chart right */}
                      <div style={{ width: "68%", flexShrink: 0, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                        <span style={{ fontSize: 7.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Precio medio vs Open</span>
                        <div style={{ height: "125px", width: "100%" }}>
                          <AvgPriceChangeChart data={currentStats.price_change_chart} />
                        </div>
                      </div>
                    </div>

                    {/* Frequencies and progress bars */}
                    <div style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      borderTop: "1px solid rgba(255, 255, 255, 0.05)",
                      paddingTop: 6,
                      maxWidth: "360px",
                      width: "100%",
                    }}>
                      {/* Negative Close Frequency */}
                      {(() => {
                        const negClose = currentStats.neg_close_freq ?? 0;
                        const posClose = 100 - negClose;
                        return (
                          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                            <span style={{ fontSize: 8, fontWeight: 700, color: "var(--color-ec-text-secondary)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Avg. close direction</span>
                            <div style={{
                              height: 16,
                              width: "100%",
                              backgroundColor: "var(--color-ec-bg-sidebar)",
                              borderRadius: 4,
                              overflow: "hidden",
                              display: "flex",
                              fontSize: 8.5,
                              fontWeight: 700
                            }}>
                              {negClose > 0 && (
                                <div style={{
                                  height: "100%",
                                  width: `${negClose}%`,
                                  backgroundColor: "var(--color-ec-loss)",
                                  color: "#ffffff",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  transition: "width 0.3s ease",
                                  textShadow: "0 1px 2px rgba(0,0,0,0.4)"
                                }}>
                                  {negClose >= 10 ? `${negClose.toFixed(1)}%` : ""}
                                </div>
                              )}
                              {posClose > 0 && (
                                <div style={{
                                  height: "100%",
                                  width: `${posClose}%`,
                                  backgroundColor: "var(--color-ec-profit)",
                                  color: "#ffffff",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  transition: "width 0.3s ease",
                                  textShadow: "0 1px 2px rgba(0,0,0,0.4)"
                                }}>
                                  {posClose >= 10 ? `${posClose.toFixed(1)}%` : ""}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Close Above PMH Frequency */}
                      {currentStats.close_above_pmh_freq !== null && currentStats.close_above_pmh_freq !== undefined && (() => {
                        const val = currentStats.close_above_pmh_freq ?? 0;
                        const restVal = 100 - val;
                        return (
                          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                            <span style={{ fontSize: 8, fontWeight: 700, color: "var(--color-ec-text-secondary)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Avg. close above PMH</span>
                            <div style={{
                              height: 16,
                              width: "100%",
                              backgroundColor: "var(--color-ec-bg-sidebar)",
                              borderRadius: 4,
                              overflow: "hidden",
                              display: "flex",
                              fontSize: 8.5,
                              fontWeight: 700
                            }}>
                              {restVal > 0 && (
                                <div style={{
                                  height: "100%",
                                  width: `${restVal}%`,
                                  backgroundColor: "var(--color-ec-loss)",
                                  color: "#ffffff",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  transition: "width 0.3s ease",
                                  textShadow: "0 1px 2px rgba(0,0,0,0.4)"
                                }}>
                                  {restVal >= 10 ? `${restVal.toFixed(1)}%` : ""}
                                </div>
                              )}
                              {val > 0 && (
                                <div style={{
                                  height: "100%",
                                  width: `${val}%`,
                                  backgroundColor: "var(--color-ec-profit)",
                                  color: "#ffffff",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  transition: "width 0.3s ease",
                                  textShadow: "0 1px 2px rgba(0,0,0,0.4)"
                                }}>
                                  {val >= 10 ? `${val.toFixed(1)}%` : ""}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Close Below VWAP Frequency */}
                      {(() => {
                        const val = currentStats.close_below_vwap_freq ?? 0;
                        const restVal = 100 - val;
                        return (
                          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                            <span style={{ fontSize: 8, fontWeight: 700, color: "var(--color-ec-text-secondary)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Close Below VWAP</span>
                            <div style={{
                              height: 16,
                              width: "100%",
                              backgroundColor: "var(--color-ec-bg-sidebar)",
                              borderRadius: 4,
                              overflow: "hidden",
                              display: "flex",
                              fontSize: 8.5,
                              fontWeight: 700
                            }}>
                              {val > 0 && (
                                <div style={{
                                  height: "100%",
                                  width: `${val}%`,
                                  backgroundColor: "var(--color-ec-loss)",
                                  color: "#ffffff",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  transition: "width 0.3s ease",
                                  textShadow: "0 1px 2px rgba(0,0,0,0.4)"
                                }}>
                                  {val >= 10 ? `${val.toFixed(1)}%` : ""}
                                </div>
                              )}
                              {restVal > 0 && (
                                <div style={{
                                  height: "100%",
                                  width: `${restVal}%`,
                                  backgroundColor: "var(--color-ec-profit)",
                                  color: "#ffffff",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  transition: "width 0.3s ease",
                                  textShadow: "0 1px 2px rgba(0,0,0,0.4)"
                                }}>
                                  {restVal >= 10 ? `${restVal.toFixed(1)}%` : ""}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                )}
              </div>

              {/* ── Float Comparison (Collapsible) ── */}
              <div style={{
                padding: "8px 16px",
                borderBottom: "1px solid var(--color-ec-border)",
              }}>
                <button
                  onClick={() => setFloatCollapsed(!floatCollapsed)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    width: "100%",
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <span style={{
                    fontSize: 8,
                    fontWeight: 700,
                    color: "var(--color-ec-copper)",
                    textTransform: "uppercase",
                    letterSpacing: "1.5px",
                  }}>
                    Comparativa de floats
                  </span>
                  <span style={{
                    fontSize: 10,
                    color: "var(--color-ec-text-muted)",
                    fontWeight: 700,
                  }}>
                    {floatCollapsed ? "▼" : "▲"}
                  </span>
                </button>

                {!floatCollapsed && (
                  <div style={{ marginTop: 8 }}>
                    {gapLoading && !gapStatsResponse?.know_the_float ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 0" }}>
                        <Loader2 style={{ width: 12, height: 12, color: "var(--color-ec-copper)", animation: "spin 1s linear infinite" }} />
                        <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)" }}>Loading float comparisons...</span>
                      </div>
                    ) : (
                      <KnowTheFloatTable floatData={gapStatsResponse?.know_the_float} />
                    )}
                  </div>
                )}
              </div>

              {/* ── Screener Row Data ── */}
              {(() => {
                const rec = data ? (data[activeTab] || []).find((r) => r.ticker === selectedTicker) : null;
                if (!rec) return null;
                return (
                  <DetailSection title="Today's Session">
                    <DetailGrid>
                      <DetailItem label="Open" value={`$${fmtPrice(rec.open)}`} />
                      <DetailItem label="High" value={`$${fmtPrice(rec.high)}`} />
                      <DetailItem label="Low" value={`$${fmtPrice(rec.low)}`} />
                      <DetailItem label="Close" value={`$${fmtPrice(rec.price)}`} />
                      <DetailItem label="Prev Close" value={`$${fmtPrice(rec.prev_close)}`} />
                      <DetailItem label="Volume" value={fmtVol(rec.volume)} />
                      <DetailItem label="Gap %" value={fmtPct(rec.gap_pct)} color={rec.gap_pct >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)"} />
                      <DetailItem label="Return %" value={fmtPct(rec.return_pct)} color={rec.return_pct >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)"} />
                    </DetailGrid>
                  </DetailSection>
                );
              })()}
            </div>
          </div>
        )}
      </div>

      {/* ── Coming Soon Overlay ── */}
      <div style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        backdropFilter: "blur(2.5px)",
        backgroundColor: "rgba(22, 24, 26, 0.45)",
        padding: "24px",
      }}>
        <div style={{
          backgroundColor: "rgba(28, 30, 33, 0.92)",
          backdropFilter: "blur(12px)",
          border: "1px solid var(--color-ec-border)",
          boxShadow: "0 16px 40px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05)",
          borderRadius: "12px",
          padding: "32px 28px",
          maxWidth: "360px",
          width: "100%",
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "18px",
        }}>
          {/* Lock Badge */}
          <div style={{
            width: "48px",
            height: "48px",
            borderRadius: "50%",
            backgroundColor: "rgba(216, 122, 61, 0.1)",
            border: "1px solid var(--color-ec-copper)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--color-ec-copper)",
            boxShadow: "0 0 16px rgba(216, 122, 61, 0.2)",
            marginBottom: "2px",
          }}>
            <Lock style={{ width: 20, height: 20, strokeWidth: 2 }} />
          </div>

          {/* Title / Text Info */}
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <h2 style={{
              fontFamily: "'Fraunces', serif",
              fontSize: "26px",
              fontWeight: 600,
              color: "var(--color-ec-text-high)",
              margin: 0,
              letterSpacing: "-0.4px",
              lineHeight: "1.1",
            }}>
              Coming <em style={{ fontStyle: "italic", color: "var(--color-ec-copper)" }}>Soon</em>
            </h2>
            <h3 style={{
              fontFamily: "'General Sans', sans-serif",
              fontSize: "11.5px",
              fontWeight: 600,
              color: "var(--color-ec-text-primary)",
              textTransform: "uppercase",
              letterSpacing: "0.8px",
              margin: "6px 0 0 0",
              lineHeight: "1.4",
            }}>
              Herramientas de market análisis y screening avanzadas
            </h3>
            <p style={{
              fontFamily: "'General Sans', sans-serif",
              fontSize: "11px",
              fontWeight: 400,
              color: "var(--color-ec-text-secondary)",
              lineHeight: "1.5",
              margin: 0,
              padding: "0 4px",
            }}>
              Datos en streaming en tiempo real y alertas customizadas muy pronto
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
//  SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      padding: "8px 16px",
      borderBottom: "1px solid var(--color-ec-border)",
    }}>
      <span style={{
        fontSize: 8,
        fontWeight: 700,
        color: "var(--color-ec-copper)",
        textTransform: "uppercase",
        letterSpacing: "1.5px",
        display: "block",
        marginBottom: 6,
      }}>
        {title}
      </span>
      {children}
    </div>
  );
}

function DetailGrid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "4px 12px",
    }}>
      {children}
    </div>
  );
}

function DetailItem({ label, value, color, prefix }: {
  label: string;
  value: string;
  color?: string;
  prefix?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <span style={{
        fontSize: 7.5,
        fontWeight: 700,
        color: "var(--color-ec-text-muted)",
        textTransform: "uppercase",
        letterSpacing: "0.5px",
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 10.5,
        fontWeight: 700,
        color: color || "var(--color-ec-text-high)",
      }}>
        {prefix !== undefined ? `${prefix}${value}` : value}
      </span>
    </div>
  );
}
