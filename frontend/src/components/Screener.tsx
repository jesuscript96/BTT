"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  TrendingUp,
  TrendingDown,
  Sun,
  Moon,
  Loader2,
  AlertCircle,
  ChevronUp,
  ChevronDown,
  Wifi,
  WifiOff,
  Bell,
  BellRing,
  Plus,
  Trash2,
} from "lucide-react";
import {
  API_BASE,
  apiRequest,
  getTickerAnalysis,
  getTickerGapStats,
  getTickerFinvizNews,
} from "@/lib/api";
import type { ScreenerRecord } from "@/lib/api";
import { ChatBot } from "./ChatBot";
import { LocatesCalculator } from "./LocatesCalculator";
import { Pill, Badge, Modal, Button, Input, Select } from "@/components/ui";
import { track, EVENTS } from "@/lib/analytics";

// ─── Types ──────────────────────────────────────────────────
type TabKey = "premarket" | "gainers" | "losers" | "aftermarket";
type SortField = "ticker" | "price" | "change_pct" | "return_pct" | "gap_pct" | "volume" | "prev_volume" | "prev_close" | "open" | "high" | "low" | "pmh_gap_pct" | "amh_gap_pct" | "rvol" | "day_change_pct" | "day_volume" | "after_pct" | "after_volume" | "after_high" | "pre_pct" | "pre_volume" | "pre_high";
type SortDir = "asc" | "desc";

// Server-side tab identifiers expected by the live WebSocket (see screener.py).
const TAB_SERVER: Record<TabKey, string> = {
  premarket: "Premarket",
  gainers: "RTH Gainers",
  losers: "RTH Losers",
  aftermarket: "Aftermarket",
};

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

const fmtPct = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v.toFixed(2);
  return v > 0 ? `+${s}%` : `${s}%`;
};

const fmtVol = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
};

const fmtPrice = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
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
const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: "premarket", label: "Premarket", icon: <Sun style={{ width: 13, height: 13 }} /> },
  { key: "gainers", label: "RTH Gainers", icon: <TrendingUp style={{ width: 13, height: 13 }} /> },
  { key: "losers", label: "RTH Losers", icon: <TrendingDown style={{ width: 13, height: 13 }} /> },
  { key: "aftermarket", label: "Aftermarket", icon: <Moon style={{ width: 13, height: 13 }} /> },
];

// ─── Table Column Definitions (per tab, exactly as PRD §4.1) ─────────────────
type ColumnDef = { key: SortField; label: string; align: "left" | "right"; width: string };

const COL = {
  ticker: { key: "ticker", label: "Ticker", align: "left", width: "12%" } as ColumnDef,
  price: { key: "price", label: "Price", align: "right", width: "11%" } as ColumnDef,
  change_pct: { key: "change_pct", label: "Change %", align: "right", width: "11%" } as ColumnDef,
  return_pct: { key: "return_pct", label: "Return %", align: "right", width: "11%" } as ColumnDef,
  gap_pct: { key: "gap_pct", label: "Gap %", align: "right", width: "11%" } as ColumnDef,
  volume: { key: "volume", label: "Volume", align: "right", width: "12%" } as ColumnDef,
  day_volume: { key: "day_volume", label: "Volume", align: "right", width: "12%" } as ColumnDef,
  prev_close: { key: "prev_close", label: "Prev Close", align: "right", width: "11%" } as ColumnDef,
  high: { key: "high", label: "High", align: "right", width: "11%" } as ColumnDef,
  low: { key: "low", label: "Low", align: "right", width: "11%" } as ColumnDef,
  rvol: { key: "rvol", label: "RVol", align: "right", width: "11%" } as ColumnDef,
  pmh_gap_pct: { key: "pmh_gap_pct", label: "PMH Gap %", align: "right", width: "11%" } as ColumnDef,
  amh_gap_pct: { key: "amh_gap_pct", label: "AMH Gap %", align: "right", width: "11%" } as ColumnDef,
  // Day-vs-session metrics (screener-dia-sesion PRD):
  after_pct: { key: "after_pct", label: "Aftermarket %", align: "right", width: "12%" } as ColumnDef,
  after_volume: { key: "after_volume", label: "After Vol", align: "right", width: "11%" } as ColumnDef,
  after_high: { key: "after_high", label: "After High", align: "right", width: "10%" } as ColumnDef,
  pre_pct: { key: "pre_pct", label: "Premarket High Gap", align: "right", width: "16%" } as ColumnDef,
  pre_volume: { key: "pre_volume", label: "Pre Vol", align: "right", width: "11%" } as ColumnDef,
  pre_high: { key: "pre_high", label: "Pre High", align: "right", width: "10%" } as ColumnDef,
};

const COLUMNS_BY_TAB: Record<TabKey, ColumnDef[]> = {
  // Premarket tab: ranks by the pre-market peak gap; day change kept for context.
  premarket: [COL.ticker, COL.price, COL.pre_pct, COL.change_pct, COL.prev_close, COL.day_volume, COL.pre_volume, COL.pre_high],
  // Gap %, Return % y RVol retiradas (02/07): Gap % duplicaba Change %; Return/RVol
  // no aportaban señal accionable. Quedan las columnas núcleo, más anchas y legibles.
  gainers: [COL.ticker, COL.price, COL.prev_close, COL.change_pct, COL.volume],
  losers: [COL.ticker, COL.price, COL.prev_close, COL.change_pct, COL.volume],
  // Aftermarket tab: ranks by the real after-hours move (from the RTH close);
  // day volume is the gate, After Vol/High arrive only via the live WS.
  aftermarket: [COL.ticker, COL.price, COL.change_pct, COL.after_pct, COL.prev_close, COL.day_volume, COL.after_volume, COL.after_high],
};

// ─── Cell rendering (column-driven, P&L semantic colors) ────────────────────
const pctColor = (v: number | null | undefined): string =>
  v == null ? "var(--color-ec-text-secondary)"
    : v > 0 ? "var(--color-ec-profit)"
    : v < 0 ? "var(--color-ec-loss)"
    : "var(--color-ec-text-secondary)";

// Escala tipográfica del grid (27/06 — números/letras más grandes y legibles).
const CELL_FONT = 14;
const HEADER_FONT = 11.5;
const CELL_PAD = "8px 12px";

const CELL_BASE: React.CSSProperties = {
  padding: CELL_PAD,
  textAlign: "right",
  fontSize: CELL_FONT,
  fontWeight: 500,
  border: "1px solid rgba(255, 255, 255, 0.06)",
  fontVariantNumeric: "tabular-nums",
  fontFamily: "monospace",
};

function renderScreenerCell(col: ColumnDef, rec: ScreenerRecord, dir?: "up" | "down"): React.ReactNode {
  const k = col.key;
  if (k === "ticker") {
    return (
      <td key={k} style={{ ...CELL_BASE, textAlign: "left", fontWeight: 700, color: "var(--color-ec-text-high)" }}>
        {rec.ticker}
      </td>
    );
  }
  if (k === "price" || k === "prev_close" || k === "high" || k === "low" || k === "open" || k === "after_high" || k === "pre_high") {
    const v = rec[k] as number | undefined;
    return <td key={k} style={{ ...CELL_BASE, color: "var(--color-ec-text-high)" }}>{v != null ? `$${fmtPrice(v)}` : "—"}</td>;
  }
  if (k === "volume" || k === "prev_volume" || k === "day_volume" || k === "after_volume" || k === "pre_volume") {
    const v = rec[k] as number | undefined;
    return <td key={k} style={{ ...CELL_BASE, color: "var(--color-ec-text-secondary)" }}>{v != null ? fmtVol(v) : "—"}</td>;
  }
  if (k === "rvol") {
    const v = rec.rvol;
    return <td key={k} style={{ ...CELL_BASE, color: "var(--color-ec-text-high)" }}>{v != null ? `${v.toFixed(2)}×` : "—"}</td>;
  }
  // Percent columns: change_pct, return_pct, gap_pct, pmh_gap_pct, amh_gap_pct.
  const v = rec[k] as number | undefined;
  if (k === "change_pct") {
    // Marca ▲/▼ según la dirección del último tick + flash de color que se
    // reejecuta al remontar el span (key = valor): sube→verde, baja→rojo.
    const mark = dir === "up" ? "▲" : dir === "down" ? "▼" : "";
    return (
      <td key={k} style={{ ...CELL_BASE, fontWeight: 700, color: pctColor(v), overflow: "hidden" }}>
        <span
          key={`${rec.ticker}:${v ?? "na"}`}
          className={dir === "up" ? "scr-flash-up" : dir === "down" ? "scr-flash-down" : undefined}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, justifyContent: "flex-end" }}
        >
          {mark && (
            <span style={{ fontSize: CELL_FONT - 3, lineHeight: 1, color: dir === "up" ? "var(--color-ec-profit)" : "var(--color-ec-loss)" }}>
              {mark}
            </span>
          )}
          {v != null ? fmtPct(v) : "—"}
        </span>
      </td>
    );
  }
  return (
    <td key={k} style={{ ...CELL_BASE, fontWeight: 500, color: pctColor(v) }}>
      {v != null ? fmtPct(v) : "—"}
    </td>
  );
}

// ═══════════════════════════════════════════════════════════
//  ALARMAS (02/07) — sonido + toast al entrar en lista / cruzar umbral
// ═══════════════════════════════════════════════════════════
type AlarmField = "change_pct" | "price" | "volume" | "pmh_gap_pct" | "pre_pct";
type AlarmOp = "gte" | "lte";
interface AlarmRule { id: string; field: AlarmField; op: AlarmOp; value: number; }
interface AlarmConfig { soundEnabled: boolean; volume: number; rules: AlarmRule[]; }

const ALARM_FIELDS: { key: AlarmField; label: string }[] = [
  { key: "change_pct", label: "Change %" },
  { key: "price", label: "Precio $" },
  { key: "volume", label: "Volumen" },
  { key: "pmh_gap_pct", label: "PMH Gap %" },
  { key: "pre_pct", label: "Premarket High Gap" },
];

const DEFAULT_ALARM_CONFIG: AlarmConfig = { soundEnabled: false, volume: 0.5, rules: [] };
const ALARM_STORAGE_KEY = "screener.alarmConfig.v1";
const ALARM_COOLDOWN_MS = 15_000;

function loadAlarmConfig(): AlarmConfig {
  if (typeof window === "undefined") return DEFAULT_ALARM_CONFIG;
  try {
    const raw = window.localStorage.getItem(ALARM_STORAGE_KEY);
    if (!raw) return DEFAULT_ALARM_CONFIG;
    const p = JSON.parse(raw);
    return {
      soundEnabled: !!p.soundEnabled,
      volume: typeof p.volume === "number" ? Math.min(1, Math.max(0, p.volume)) : 0.5,
      rules: Array.isArray(p.rules)
        ? p.rules
            .filter((r: unknown): r is AlarmRule =>
              !!r && typeof (r as AlarmRule).field === "string" && typeof (r as AlarmRule).op === "string")
            .map((r: AlarmRule) => ({ ...r, value: Number(r.value) || 0 }))
        : [],
    };
  } catch {
    return DEFAULT_ALARM_CONFIG;
  }
}

function saveAlarmConfig(cfg: AlarmConfig) {
  try { window.localStorage.setItem(ALARM_STORAGE_KEY, JSON.stringify(cfg)); } catch { /* ignore */ }
}

function matchesRules(rec: ScreenerRecord, rules: AlarmRule[]): boolean {
  // Sin reglas → cualquier entrante dispara. El sonido está OFF por defecto,
  // así que esto no genera ruido a menos que el usuario lo active a propósito.
  if (rules.length === 0) return true;
  return rules.every((r) => {
    const v = rec[r.field] as number | undefined;
    if (typeof v !== "number" || Number.isNaN(v)) return false;
    return r.op === "gte" ? v >= r.value : v <= r.value;
  });
}

// Beep vía WebAudio — sin assets binarios. La política de autoplay del navegador
// exige un gesto previo del usuario; activar el sonido en el modal (un click) es
// ese gesto y desbloquea el AudioContext.
let _audioCtx: AudioContext | null = null;
function playBeep(volume: number) {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    if (!_audioCtx) _audioCtx = new AC();
    const ctx = _audioCtx;
    if (ctx.state === "suspended") void ctx.resume();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, now);
    osc.frequency.setValueAtTime(1320, now + 0.09);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.02, volume), now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.3);
  } catch { /* ignore */ }
}

// ═══════════════════════════════════════════════════════════
//  MAIN COMPONENT
// ═══════════════════════════════════════════════════════════
export default function Screener() {
  // ── Live data state ──
  const [records, setRecords] = useState<ScreenerRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [session, setSession] = useState<string>("closed");
  const [error, setError] = useState<string | null>(null);

  // ── UI state ──
  const [activeTab, setActiveTab] = useState<TabKey>("gainers");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>("change_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // ── Detail panel state ──
  const [tickerDetail, setTickerDetail] = useState<TickerDetail | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [gapLoading, setGapLoading] = useState(false);
  const [gapStatsResponse, setGapStatsResponse] = useState<GapStatsResponse | null>(null);
  // True while the background enrichment (Finviz float/sector/ownership) may
  // still land for the selected ticker — drives the "…" skeletons.
  const [enrichPending, setEnrichPending] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState<"day0" | "day1" | "day2">("day0");
  const [floatCollapsed, setFloatCollapsed] = useState(false);

  // ── Alarmas (02/07) ──
  const [alarmConfig, setAlarmConfig] = useState<AlarmConfig>(DEFAULT_ALARM_CONFIG);
  const [alarmModalOpen, setAlarmModalOpen] = useState(false);
  const [alarmToasts, setAlarmToasts] = useState<{ id: string; ticker: string; change: number }[]>([]);
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});

  const wsRef = useRef<WebSocket | null>(null);
  const activeTabRef = useRef<TabKey>(activeTab);
  activeTabRef.current = activeTab;

  // Refs para la evaluación de alarmas dentro del efecto [records] (sin closures obsoletas).
  const alarmConfigRef = useRef<AlarmConfig>(DEFAULT_ALARM_CONFIG);
  const prevTickersRef = useRef<Set<string>>(new Set());
  const prevChangeRef = useRef<Map<string, number>>(new Map());
  const prevMatchRef = useRef<Map<string, boolean>>(new Map());
  const lastAlarmRef = useRef<Map<string, number>>(new Map());

  // Hidratar la config de alarmas desde localStorage (solo cliente).
  useEffect(() => {
    const cfg = loadAlarmConfig();
    setAlarmConfig(cfg);
    alarmConfigRef.current = cfg;
  }, []);

  const updateAlarmConfig = useCallback((next: AlarmConfig) => {
    setAlarmConfig(next);
    alarmConfigRef.current = next;   // el efecto [records] lee del ref, no del estado
    saveAlarmConfig(next);
  }, []);

  // Detección de entrantes / cruces de umbral + dirección del tick (flash ▲▼).
  // Corre en cada snapshot del WS (1×/s). El primer snapshot tras cambiar de tab
  // (prevTickers vacío) es baseline: no dispara alarmas por la lista entera.
  useEffect(() => {
    const cfg = alarmConfigRef.current;
    const prevTickers = prevTickersRef.current;
    const prevChange = prevChangeRef.current;
    const prevMatch = prevMatchRef.current;

    const nextTickers = new Set<string>();
    const nextChange = new Map<string, number>();
    const nextMatch = new Map<string, boolean>();
    const dirs: Record<string, "up" | "down"> = {};
    const fired: ScreenerRecord[] = [];
    const isBaseline = prevTickers.size === 0;
    const now = Date.now();

    for (const r of records) {
      nextTickers.add(r.ticker);
      const cur = typeof r.change_pct === "number" ? r.change_pct : 0;
      nextChange.set(r.ticker, cur);
      const pc = prevChange.get(r.ticker);
      if (pc != null) {
        if (cur > pc) dirs[r.ticker] = "up";
        else if (cur < pc) dirs[r.ticker] = "down";
      }
      const match = matchesRules(r, cfg.rules);
      nextMatch.set(r.ticker, match);
      if (isBaseline) continue;

      const isEntrant = !prevTickers.has(r.ticker);
      const isCrosser = !isEntrant && match && !prevMatch.get(r.ticker);
      if ((isEntrant && match) || isCrosser) {
        const last = lastAlarmRef.current.get(r.ticker) || 0;
        if (now - last > ALARM_COOLDOWN_MS) {
          lastAlarmRef.current.set(r.ticker, now);
          fired.push(r);
        }
      }
    }

    prevTickersRef.current = nextTickers;
    prevChangeRef.current = nextChange;
    prevMatchRef.current = nextMatch;
    setFlashMap(dirs);

    if (fired.length) {
      if (cfg.soundEnabled) playBeep(cfg.volume);
      setAlarmToasts((prev) => {
        const add = fired.slice(0, 4).map((r) => ({ id: `${r.ticker}-${now}`, ticker: r.ticker, change: r.change_pct }));
        return [...add, ...prev].slice(0, 6);
      });
    }
  }, [records]);

  // Auto-descartar los toasts de alarma (uno cada 4 s mientras haya).
  useEffect(() => {
    if (alarmToasts.length === 0) return;
    const t = setTimeout(() => setAlarmToasts((p) => p.slice(0, p.length - 1)), 4000);
    return () => clearTimeout(t);
  }, [alarmToasts]);

  // Helpers de edición de reglas (persisten en localStorage vía updateAlarmConfig).
  const addRule = useCallback(() => {
    const cfg = alarmConfigRef.current;
    updateAlarmConfig({
      ...cfg,
      rules: [...cfg.rules, { id: `${Date.now()}-${cfg.rules.length}`, field: "change_pct", op: "gte", value: 20 }],
    });
  }, [updateAlarmConfig]);
  const updateRule = useCallback((id: string, patch: Partial<AlarmRule>) => {
    const cfg = alarmConfigRef.current;
    updateAlarmConfig({ ...cfg, rules: cfg.rules.map((r) => (r.id === id ? { ...r, ...patch } : r)) });
  }, [updateAlarmConfig]);
  const removeRule = useCallback((id: string) => {
    const cfg = alarmConfigRef.current;
    updateAlarmConfig({ ...cfg, rules: cfg.rules.filter((r) => r.id !== id) });
  }, [updateAlarmConfig]);
  const toggleSound = useCallback((on: boolean) => {
    const cfg = alarmConfigRef.current;
    updateAlarmConfig({ ...cfg, soundEnabled: on });
    if (on) playBeep(cfg.volume);   // el click desbloquea el AudioContext y confirma
  }, [updateAlarmConfig]);

  // ── Pre-warm on hover ────────────────────────────────────────────────────
  // Al pasar el ratón por una fila, precalentar en el backend (fase 1 síncrona
  // + fase 2 en background) ANTES del click. Para cuando el usuario clica
  // (~200 ms después) el panel ya está caliente → runner stats + chart al
  // instante. Fire-and-forget, dedup por ticker, sin analytics (no es un
  // "abrir ticker" real). Debounce 120 ms para no calentar filas que solo se
  // cruzan con el ratón. El backend deduplica el cómputo por ticker, así que
  // varios hovers del mismo símbolo cuestan una sola pasada.
  const warmedRef = useRef<Set<string>>(new Set());
  const warmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const warmTicker = useCallback((ticker: string) => {
    if (!ticker || warmedRef.current.has(ticker)) return;
    warmedRef.current.add(ticker);
    apiRequest(`/ticker-analysis/${encodeURIComponent(ticker)}`).catch(() => {});
    apiRequest(`/ticker-analysis/${encodeURIComponent(ticker)}/gap-stats`).catch(() => {});
  }, []);
  const scheduleWarm = useCallback((ticker: string) => {
    if (warmedRef.current.has(ticker)) return;
    if (warmTimerRef.current) clearTimeout(warmTimerRef.current);
    warmTimerRef.current = setTimeout(() => warmTicker(ticker), 120);
  }, [warmTicker]);
  const cancelWarm = useCallback(() => {
    if (warmTimerRef.current) { clearTimeout(warmTimerRef.current); warmTimerRef.current = null; }
  }, []);

  // ── Live WebSocket: one persistent connection, auto-reconnect on drop. The
  // backend streams the top-50 of the subscribed tab once per second. ──
  useEffect(() => {
    let stopped = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const url = `${API_BASE.replace(/^http/, "ws")}/screener/live`;

    const connect = () => {
      if (stopped) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        reconnectTimer = setTimeout(connect, 2000);
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (stopped) return;
        setConnected(true);
        ws.send(JSON.stringify({ action: "subscribe", tab: TAB_SERVER[activeTabRef.current] }));
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          // Ignore frames for a tab we just switched away from.
          if (msg.tab !== TAB_SERVER[activeTabRef.current]) return;
          setRecords(Array.isArray(msg.records) ? msg.records : []);
          if (typeof msg.session === "string") setSession(msg.session);
          setLoading(false);
          setError(null);
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        if (stopped) return;
        setConnected(false);
        setLoading(false); // leave the spinner; the empty-state explains + auto-reconnects
        reconnectTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => {
        try { ws.close(); } catch { /* noop */ }
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try { wsRef.current?.close(); } catch { /* noop */ }
    };
  }, []);

  // ── Re-subscribe when the active tab changes (no reconnect needed) ──
  useEffect(() => {
    setLoading(true);
    setRecords([]);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "subscribe", tab: TAB_SERVER[activeTab] }));
    }
    track(EVENTS.SCREENER_FILTER_APPLIED, { tab: TAB_SERVER[activeTab] });
  }, [activeTab]);

  // ── Fetch real ticker fundamentals when selection changes + feed Edgie ──
  useEffect(() => {
    if (!selectedTicker) {
      setTickerDetail(null);
      setGapStatsResponse(null);
      setProfileLoading(false);
      setGapLoading(false);
      return;
    }
    const ac = new AbortController();
    const signal = ac.signal;
    setProfileLoading(true);
    setGapLoading(true);
    setTickerDetail(null);
    setGapStatsResponse(null);

    // ALL fetches fire in PARALLEL (like TickerAnalysis.tsx), not chained.
    // Each passes { signal } so AbortController cancels them on ticker change.

    // 1) Profile + market fundamentals. Finviz is now INLINE server-side, so
    // the first response normally arrives complete (~300 ms). Only when
    // float/sector are still missing (rare: Finviz hiccup or no coverage) we
    // schedule short retries to pick up the background enrichment.
    getTickerAnalysis(selectedTicker, { signal })
      .then((d) => {
        const detail = d as TickerDetail;
        setTickerDetail(detail);
        const incomplete = detail?.market?.float_shares == null && !detail?.profile?.sector;
        setEnrichPending(incomplete);
        if (incomplete) scheduleEnrichRefetch();
        // Re-scope the floating Edgie assistant to this ticker
        window.dispatchEvent(new CustomEvent("ticker-loaded", {
          detail: { ticker: selectedTicker, data: detail, finvizNews: null, filings: null, secCompanyFacts: null },
        }));
      })
      .catch((e) => {
        if ((e as Error)?.name !== "AbortError") {
          setTickerDetail(null);
        }
      })
      .finally(() => { setProfileLoading(false); });

    // 2) News — PARALLEL, not chained after analysis
    getTickerFinvizNews(selectedTicker, { signal })
      .then((news) => {
        const items = Array.isArray(news) ? news : ((news as any)?.news ?? []);
        window.dispatchEvent(new CustomEvent("ticker-loaded", {
          detail: { ticker: selectedTicker, data: tickerDetail, finvizNews: items, filings: null, secCompanyFacts: null },
        }));
      })
      .catch(() => { /* news is optional, never block the panel */ });

    // 3) Gap stats — first visit returns a "calculating" placeholder while
    // the backend computes in background; poll until it settles. Cold
    // small-caps can take >1 min (GCS intraday reads), so allow ~75s;
    // a revisit re-polls anyway.
    const timers: ReturnType<typeof setTimeout>[] = [];
    const isCalculating = (g: GapStatsResponse | null): boolean =>
      !!g && (g.status === "calculating" || g.gap_stats?.status === "calculating");

    const pollGapStats = (attempt: number) => {
      const call = attempt === 0
        ? getTickerGapStats(selectedTicker, { signal })
        : apiRequest<GapStatsResponse>(`/ticker-analysis/${encodeURIComponent(selectedTicker)}/gap-stats`, { signal });
      call
        .then((g) => {
          const res = g as GapStatsResponse;
          setGapStatsResponse((prev) => {
            // Never replace real stats with a placeholder.
            if (prev && !isCalculating(prev) && isCalculating(res)) return prev;
            return res;
          });
          if (isCalculating(res) && attempt < 20) {
            setGapLoading(true);
            // La fase 1 del backend se publica a los ~2 s: el primer re-poll
            // corto la pinta cuanto antes; después cadencia normal.
            timers.push(setTimeout(() => pollGapStats(attempt + 1), attempt === 0 ? 1200 : 3000));
          } else {
            setGapLoading(false);
          }
        })
        .catch((e) => {
          if ((e as Error)?.name !== "AbortError") {
            if (attempt === 0) setGapStatsResponse(null);
            setGapLoading(false);
          }
        });
    };
    pollGapStats(0);

    // Adaptive enrichment refetch — ONLY scheduled when the first payload came
    // incomplete (rare now that Finviz runs inline server-side). Two quick,
    // silent retries pick up the background-merged payload (~2ms warm) without
    // re-firing analytics.
    const scheduleEnrichRefetch = (attempt = 0) => {
      timers.push(setTimeout(() => {
        apiRequest<TickerDetail>(`/ticker-analysis/${encodeURIComponent(selectedTicker)}`, { signal })
          .then((d) => {
            const enriched = d?.market?.float_shares != null || d?.profile?.sector;
            if (enriched) {
              setTickerDetail(d);
              setEnrichPending(false);
            } else if (attempt < 1) {
              scheduleEnrichRefetch(attempt + 1);
            } else {
              setEnrichPending(false); // nothing upstream — settle the dashes
            }
          })
          .catch(() => { setEnrichPending(false); });
      }, attempt === 0 ? 2000 : 5000));
    };

    return () => { ac.abort(); timers.forEach(clearTimeout); };
  }, [selectedTicker]);

  // ── Get current stats by active sub-tab ──
  const currentStats = gapStatsResponse
    ? activeSubTab === "day0"
      ? gapStatsResponse.gap_stats
      : activeSubTab === "day1"
        ? gapStatsResponse.gap_stats_plus_1
        : gapStatsResponse.gap_stats_plus_2
    : null;

  // ── Sort the received top-50 locally for instant response ──
  const sortedRecords = useCallback((): ScreenerRecord[] => {
    const recs = [...records];
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
  }, [records, sortField, sortDir]);

  // ── Handle column sort ──
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir(field === "ticker" ? "asc" : "desc");
    }
    track(EVENTS.SCREENER_FILTER_APPLIED, { sort: field });
  };

  // ── Handle tab change ──
  const handleTabChange = (tab: TabKey) => {
    setActiveTab(tab);
    setSelectedTicker(null);
    // Default sort per tab: the metric that defines each tab, most explosive first
    // (losers ascending = biggest drop first).
    if (tab === "losers") { setSortField("change_pct"); setSortDir("asc"); }
    else if (tab === "aftermarket") { setSortField("after_pct"); setSortDir("desc"); }
    else if (tab === "premarket") { setSortField("pre_pct"); setSortDir("desc"); }
    else { setSortField("change_pct"); setSortDir("desc"); }
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
      <style>{`
        @keyframes scrFlashUp { 0% { background: color-mix(in srgb, var(--color-ec-profit) 55%, transparent); } 100% { background: transparent; } }
        @keyframes scrFlashDown { 0% { background: color-mix(in srgb, var(--color-ec-loss) 55%, transparent); } 100% { background: transparent; } }
        .scr-flash-up { animation: scrFlashUp 0.7s ease-out; border-radius: 3px; padding: 1px 4px; }
        .scr-flash-down { animation: scrFlashDown 0.7s ease-out; border-radius: 3px; padding: 1px 4px; }
        @keyframes scrToastIn { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: translateX(0); } }
      `}</style>
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
          <Pill tone={connected ? "good" : "neutral"}>
            {connected ? <Wifi size={11} /> : <WifiOff size={11} />}
            {connected ? "LIVE" : "Desconectado"}
          </Pill>
          {session === "closed" && (
            <Pill tone="neutral">Cierre · congelado</Pill>
          )}
          <span style={{
            fontSize: 10,
            fontWeight: 500,
            color: "var(--color-ec-text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            {session === "pre" ? "Premarket" : session === "rth" ? "Mercado abierto" : session === "after" ? "Aftermarket" : "Mercado cerrado"} · {records.length} tickers
          </span>
        </div>

        {/* Alarmas */}
        <Button variant="secondary" size="sm" onClick={() => setAlarmModalOpen(true)}>
          {alarmConfig.soundEnabled
            ? <BellRing size={13} style={{ marginRight: 6, color: "var(--color-ec-copper)" }} />
            : <Bell size={13} style={{ marginRight: 6 }} />}
          Alarmas
          {alarmConfig.rules.length > 0 && (
            <Badge tone="neutral" style={{ marginLeft: 6 }}>{alarmConfig.rules.length}</Badge>
          )}
        </Button>
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
              return (
                <button
                  key={tab.key}
                  onClick={() => handleTabChange(tab.key)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "12px 16px",
                    border: "none",
                    borderBottom: isActive ? "2px solid var(--color-ec-copper)" : "2px solid transparent",
                    background: "transparent",
                    color: isActive ? "var(--color-ec-copper)" : "var(--color-ec-text-secondary)",
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "1.5px",
                    fontFamily: "'General Sans', sans-serif",
                    cursor: "pointer",
                    transition: "all 150ms ease",
                  }}
                >
                  {tab.icon}
                  {tab.label}
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
                    {COLUMNS_BY_TAB[activeTab].map((col) => (
                      <th
                        key={col.key}
                        onClick={() => handleSort(col.key)}
                        style={{
                          position: "sticky",
                          top: 0,
                          backgroundColor: "var(--color-ec-bg-surface)",
                          padding: CELL_PAD,
                          textAlign: col.align,
                          fontSize: HEADER_FONT,
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
                      <td colSpan={COLUMNS_BY_TAB[activeTab].length} style={{
                        padding: "60px 0",
                        textAlign: "center",
                        color: "var(--color-ec-text-muted)",
                        fontSize: 12,
                      }}>
                        {!connected
                          ? "Conectando al stream en tiempo real…"
                          : session === "closed"
                            ? "Mercado cerrado — sin movimientos ≥ 15% por ahora."
                            : "Sin tickers que cumplan los filtros ahora mismo."}
                      </td>
                    </tr>
                  ) : (
                    sortedRecords().map((rec, i) => {
                      const isSelected = selectedTicker === rec.ticker;
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
                            scheduleWarm(rec.ticker);
                          }}
                          onMouseLeave={(e) => {
                            if (!isSelected) {
                              e.currentTarget.style.backgroundColor = i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)";
                            }
                            cancelWarm();
                          }}
                        >
                          {COLUMNS_BY_TAB[activeTab].map((col) => renderScreenerCell(col, rec, flashMap[rec.ticker]))}
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
              <DetailSection title="Market Data" note="Datos combinados de varias fuentes; puede haber pequeñas discrepancias.">
                {profileLoading ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 0" }}>
                    <Loader2 style={{ width: 12, height: 12, color: "var(--color-ec-copper)", animation: "spin 1s linear infinite" }} />
                    <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)" }}>Loading market data...</span>
                  </div>
                ) : (
                  <DetailGrid>
                    <DetailItem label="Market Cap" value={fmtMarketCap(tickerDetail?.market?.market_cap)} />
                    <DetailItem label="Shares Out." value={fmtShares(tickerDetail?.market?.shares_outstanding)} prefix="" />
                    <DetailItem label="Float Shares" value={fmtShares(tickerDetail?.market?.float_shares)} prefix="" pending={enrichPending} />
                    <DetailItem
                      label="Institutional %"
                      value={tickerDetail?.market?.held_percent_institutions != null
                        ? `${(tickerDetail.market.held_percent_institutions * 100).toFixed(1)}%`
                        : "—"}
                      pending={enrichPending}
                    />
                    <DetailItem
                      label="Insider %"
                      value={tickerDetail?.market?.held_percent_insiders != null
                        ? `${(tickerDetail.market.held_percent_insiders * 100).toFixed(1)}%`
                        : "—"}
                      pending={enrichPending}
                    />
                    <DetailItem label="Price" value={tickerDetail?.market?.price != null ? `$${fmtPrice(tickerDetail.market.price)}` : "—"} />
                  </DetailGrid>
                )}
              </DetailSection>

              {/* ── Calculadora de locates (determinista; Entry pre-rellenado con el precio) ── */}
              <DetailSection title="Locates">
                <LocatesCalculator
                  key={selectedTicker}
                  initialEntry={tickerDetail?.market?.price ?? undefined}
                />
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
                      <DetailItem label="Sector" value={tickerDetail.profile.sector || "—"} pending={enrichPending} />
                      <DetailItem label="Industry" value={tickerDetail.profile.industry || "—"} pending={enrichPending} />
                      <DetailItem label="Exchange" value={tickerDetail.profile.exchange || "—"} />
                    </DetailGrid>
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

                {(gapLoading || gapStatsResponse?.status === "calculating" || currentStats?.status === "calculating")
                  && !(currentStats && currentStats.gap_days_count > 0) ? (
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
                    Sin estadísticas de runner (este ticker no tiene gaps ≥ 20% registrados).
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

              {/* ── Float Comparison (Collapsible) ── oculto de momento por decisión de producto */}
              {false && <div style={{
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
                    {(gapLoading || gapStatsResponse?.status === "calculating") && !gapStatsResponse?.know_the_float ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 0" }}>
                        <Loader2 style={{ width: 12, height: 12, color: "var(--color-ec-copper)", animation: "spin 1s linear infinite" }} />
                        <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)" }}>Loading float comparisons...</span>
                      </div>
                    ) : (
                      <KnowTheFloatTable floatData={gapStatsResponse?.know_the_float} />
                    )}
                  </div>
                )}
              </div>}

              {/* ── Screener Row Data ── */}
              {(() => {
                const rec = records.find((r) => r.ticker === selectedTicker) || null;
                if (!rec) return null;
                return (
                  <DetailSection title="Live Session">
                    <DetailGrid>
                      <DetailItem label="Last" value={`$${fmtPrice(rec.price)}`} />
                      <DetailItem label="Change %" value={fmtPct(rec.change_pct)} color={(rec.change_pct ?? 0) >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)"} />
                      <DetailItem label="Prev Close" value={`$${fmtPrice(rec.prev_close)}`} />
                      <DetailItem label="High" value={`$${fmtPrice(rec.high)}`} />
                      <DetailItem label="Low" value={`$${fmtPrice(rec.low)}`} />
                      <DetailItem label="Volume" value={fmtVol(rec.volume)} />
                      <DetailItem label="Gap %" value={fmtPct(rec.gap_pct)} color={(rec.gap_pct ?? 0) >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)"} />
                      <DetailItem label="Return %" value={fmtPct(rec.return_pct)} color={(rec.return_pct ?? 0) >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)"} />
                      <DetailItem label="RVol" value={rec.rvol != null ? `${rec.rvol.toFixed(2)}×` : "—"} />
                    </DetailGrid>
                  </DetailSection>
                );
              })()}
            </div>
          </div>
        )}
      </div>

      {/* ── Toasts de alarma (esquina inferior derecha) ── */}
      {alarmToasts.length > 0 && (
        <div style={{
          position: "absolute", right: 16, bottom: 16, zIndex: 60,
          display: "flex", flexDirection: "column", gap: 8, pointerEvents: "none",
        }}>
          {alarmToasts.map((t) => (
            <div key={t.id} style={{
              display: "flex", alignItems: "center", gap: 8, minWidth: 200,
              background: "var(--color-ec-bg-surface)",
              border: "1px solid var(--color-ec-copper)",
              borderLeft: "3px solid var(--color-ec-copper)",
              borderRadius: 6, padding: "9px 12px",
              boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
              animation: "scrToastIn 0.2s ease-out",
            }}>
              <BellRing size={14} style={{ color: "var(--color-ec-copper)", flexShrink: 0 }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ec-text-high)" }}>{t.ticker}</span>
              <span style={{ fontSize: 11, color: "var(--color-ec-text-muted)" }}>en lista</span>
              <span style={{
                fontSize: 13, fontWeight: 700, marginLeft: "auto", fontFamily: "monospace",
                color: (t.change ?? 0) >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
              }}>
                {fmtPct(t.change)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── Modal de configuración de alarmas ── */}
      <Modal
        open={alarmModalOpen}
        onClose={() => setAlarmModalOpen(false)}
        title="Alarmas del screener"
        eyebrow="Tiempo real"
        width={540}
        footer={<Button variant="primary" onClick={() => setAlarmModalOpen(false)}>Hecho</Button>}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Sonido */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ec-text-high)" }}>Sonido al saltar una alarma</span>
              <span style={{ fontSize: 11, color: "var(--color-ec-text-muted)" }}>Beep cuando un ticker entra en la lista o cruza un umbral.</span>
            </div>
            <input
              type="checkbox"
              checked={alarmConfig.soundEnabled}
              onChange={(e) => toggleSound(e.target.checked)}
              style={{ width: 18, height: 18, accentColor: "var(--color-ec-copper)", cursor: "pointer", flexShrink: 0 }}
            />
          </div>

          {/* Volumen */}
          {alarmConfig.soundEnabled && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", minWidth: 58 }}>Volumen</span>
              <input
                type="range" min={0} max={1} step={0.05} value={alarmConfig.volume}
                onChange={(e) => updateAlarmConfig({ ...alarmConfig, volume: Number(e.target.value) })}
                style={{ flex: 1, accentColor: "var(--color-ec-copper)" }}
              />
              <Button variant="ghost" size="sm" onClick={() => playBeep(alarmConfig.volume)}>Probar</Button>
            </div>
          )}

          <div style={{ height: 1, background: "var(--color-ec-border)" }} />

          {/* Reglas / filtros */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ec-text-high)" }}>Filtros (deben cumplirse todos)</span>
              <Button variant="secondary" size="sm" onClick={addRule}><Plus size={13} style={{ marginRight: 4 }} /> Añadir</Button>
            </div>
            {alarmConfig.rules.length === 0 ? (
              <span style={{ fontSize: 11, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
                Sin filtros: cualquier ticker que entre en la lista dispara la alarma. Añade condiciones sobre las columnas para acotarla.
              </span>
            ) : (
              alarmConfig.rules.map((r) => (
                <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ flex: 2 }}>
                    <Select value={r.field} onChange={(e) => updateRule(r.id, { field: e.target.value as AlarmField })}>
                      {ALARM_FIELDS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                    </Select>
                  </div>
                  <div style={{ width: 72 }}>
                    <Select value={r.op} onChange={(e) => updateRule(r.id, { op: e.target.value as AlarmOp })}>
                      <option value="gte">≥</option>
                      <option value="lte">≤</option>
                    </Select>
                  </div>
                  <Input
                    type="number" value={Number.isFinite(r.value) ? r.value : 0}
                    onChange={(e) => updateRule(r.id, { value: Number(e.target.value) })}
                    style={{ width: 96 }}
                  />
                  <button
                    onClick={() => removeRule(r.id)} title="Quitar filtro"
                    style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--color-ec-text-muted)", display: "flex", padding: 4 }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))
            )}
          </div>

          <span style={{ fontSize: 10.5, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
            El navegador solo reproduce sonido tras un clic tuyo; al activar el sonido aquí ya queda desbloqueado para esta sesión.
          </span>
        </div>
      </Modal>

      {/* Floating Edgie assistant — same component used in Ticker Analysis.
          Re-scopes to the selected ticker via the 'ticker-loaded' event. */}
      <ChatBot />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
//  SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════

function DetailSection({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
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
        {note && (
          <span style={{
            marginLeft: 6,
            fontWeight: 500,
            color: "var(--color-ec-text-muted)",
            textTransform: "none",
            letterSpacing: "0.2px",
          }}>
            {note}
          </span>
        )}
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

/** Pulsing dots shown while a value is still being enriched in background. */
function PendingDots() {
  return (
    <span className="animate-pulse" style={{ color: "var(--color-ec-copper)", letterSpacing: 2 }}>
      ···
    </span>
  );
}

function DetailItem({ label, value, color, prefix, pending }: {
  label: string;
  value: string;
  color?: string;
  prefix?: string;
  /** show pulsing dots instead of the em-dash while enrichment is in flight */
  pending?: boolean;
}) {
  if (pending && (value === "—" || value === "")) {
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
        <span style={{ fontSize: 10.5, fontWeight: 700 }}><PendingDots /></span>
      </div>
    );
  }
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
