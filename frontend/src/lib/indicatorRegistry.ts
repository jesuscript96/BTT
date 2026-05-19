/**
 * Central registry for all chart indicators.
 * Defines categories, display modes, parameter schemas, and metadata.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DisplayMode = "overlay" | "panel";

export type IndicatorCategory = "Trend" | "Momentum" | "Volatility" | "Volume";

export interface ParamDef {
  name: string;
  label: string;
  default: number;
  min?: number;
  max?: number;
  step?: number;
}

export interface IndicatorDef {
  id: string;
  label: string;
  category: IndicatorCategory;
  displayMode: DisplayMode;
  params: ParamDef[];
  /** Whether multiple instances can be added (e.g. two SMAs with different periods) */
  multi: boolean;
  /** Whether it produces multiple series (e.g. Bollinger = upper/middle/lower) */
  multiSeries?: boolean;
}

/** Runtime instance of an indicator on the chart */
export interface ActiveIndicator {
  indicatorId: string;
  instanceId: string;
  params: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const INDICATOR_REGISTRY: IndicatorDef[] = [
  // ===================== TREND (Overlay) =====================
  {
    id: "SMA",
    label: "SMA",
    category: "Trend",
    displayMode: "overlay",
    params: [{ name: "period", label: "Period", default: 20, min: 1, max: 500 }],
    multi: true,
  },
  {
    id: "EMA",
    label: "EMA",
    category: "Trend",
    displayMode: "overlay",
    params: [{ name: "period", label: "Period", default: 20, min: 1, max: 500 }],
    multi: true,
  },
  {
    id: "WMA",
    label: "WMA",
    category: "Trend",
    displayMode: "overlay",
    params: [{ name: "period", label: "Period", default: 20, min: 1, max: 500 }],
    multi: true,
  },
  {
    id: "VWAP",
    label: "VWAP",
    category: "Trend",
    displayMode: "overlay",
    params: [],
    multi: false,
  },
  {
    id: "LINEAR_REGRESSION",
    label: "Linear Regression",
    category: "Trend",
    displayMode: "overlay",
    params: [{ name: "period", label: "Period", default: 14, min: 2, max: 500 }],
    multi: true,
  },
  {
    id: "ICHIMOKU",
    label: "Ichimoku Clouds",
    category: "Trend",
    displayMode: "overlay",
    params: [
      { name: "tenkan", label: "Tenkan", default: 9, min: 1, max: 200 },
      { name: "kijun", label: "Kijun", default: 26, min: 1, max: 200 },
      { name: "senkou_b", label: "Senkou B", default: 52, min: 1, max: 200 },
    ],
    multi: false,
    multiSeries: true,
  },
  {
    id: "PARABOLIC_SAR",
    label: "Parabolic SAR",
    category: "Trend",
    displayMode: "overlay",
    params: [
      { name: "minAF", label: "Min AF", default: 0.02, min: 0.001, max: 0.1, step: 0.001 },
      { name: "maxAF", label: "Max AF", default: 0.2, min: 0.01, max: 1, step: 0.01 },
    ],
    multi: false,
  },

  // ===================== VOLATILITY (Overlay) =====================
  {
    id: "DONCHIAN",
    label: "Donchian Channel",
    category: "Volatility",
    displayMode: "overlay",
    params: [{ name: "period", label: "Period", default: 20, min: 1, max: 500 }],
    multi: false,
    multiSeries: true,
  },
  {
    id: "BOLLINGER",
    label: "Bollinger Bands",
    category: "Volatility",
    displayMode: "overlay",
    params: [
      { name: "period", label: "Period", default: 20, min: 1, max: 500 },
      { name: "stdDev", label: "Std Dev", default: 2, min: 0.1, max: 5, step: 0.1 },
    ],
    multi: false,
    multiSeries: true,
  },
  {
    id: "ZIGZAG",
    label: "Zig Zag",
    category: "Volatility",
    displayMode: "overlay",
    params: [{ name: "reversal", label: "% Reversal", default: 5, min: 0.1, max: 50, step: 0.1 }],
    multi: false,
  },
  {
    id: "OPENING_RANGE",
    label: "Opening Range",
    category: "Volatility",
    displayMode: "overlay",
    params: [{ name: "minutes", label: "Minutes", default: 5, min: 1, max: 390, step: 1 }],
    multi: false,
    multiSeries: true,
  },

  // ===================== MOMENTUM (Panel) =====================
  {
    id: "RSI",
    label: "RSI",
    category: "Momentum",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 14, min: 1, max: 200 }],
    multi: true,
  },
  {
    id: "STOCHASTIC",
    label: "Stochastic",
    category: "Momentum",
    displayMode: "panel",
    params: [
      { name: "kPeriod", label: "%K", default: 14, min: 1, max: 200 },
      { name: "dPeriod", label: "%D", default: 3, min: 1, max: 200 },
      { name: "dSlow", label: "%D Slow", default: 3, min: 1, max: 200 },
    ],
    multi: false,
    multiSeries: true,
  },
  {
    id: "MOMENTUM",
    label: "Momentum",
    category: "Momentum",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 10, min: 1, max: 200 }],
    multi: true,
  },
  {
    id: "CCI",
    label: "CCI",
    category: "Momentum",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 20, min: 1, max: 200 }],
    multi: true,
  },
  {
    id: "ROC",
    label: "ROC",
    category: "Momentum",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 12, min: 1, max: 200 }],
    multi: true,
  },
  {
    id: "MACD",
    label: "MACD",
    category: "Momentum",
    displayMode: "panel",
    params: [
      { name: "fast", label: "Fast", default: 12, min: 1, max: 200 },
      { name: "slow", label: "Slow", default: 26, min: 1, max: 200 },
      { name: "signal", label: "Signal", default: 9, min: 1, max: 200 },
    ],
    multi: false,
    multiSeries: true,
  },
  {
    id: "DMI",
    label: "DMI",
    category: "Momentum",
    displayMode: "panel",
    params: [
      { name: "diPeriod", label: "DI Period", default: 14, min: 1, max: 200 },
      { name: "adxPeriod", label: "ADX Period", default: 14, min: 1, max: 200 },
    ],
    multi: false,
    multiSeries: true,
  },
  {
    id: "WILLIAMS_R",
    label: "Williams %R",
    category: "Momentum",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 14, min: 1, max: 200 }],
    multi: true,
  },
  {
    id: "ADX",
    label: "ADX",
    category: "Momentum",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 14, min: 1, max: 200 }],
    multi: true,
  },

  // ===================== VOLATILITY (Panel) =====================
  {
    id: "ATR",
    label: "ATR",
    category: "Volatility",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 14, min: 1, max: 200 }],
    multi: true,
  },

  // ===================== VOLUME (Panel) =====================
  {
    id: "OBV",
    label: "OBV",
    category: "Volume",
    displayMode: "panel",
    params: [],
    multi: false,
  },
  {
    id: "VOL_AD",
    label: "Vol Acc/Dist",
    category: "Volume",
    displayMode: "panel",
    params: [],
    multi: false,
  },
  {
    id: "VOLUME",
    label: "Volume",
    category: "Volume",
    displayMode: "panel",
    params: [],
    multi: false,
  },
  {
    id: "RVOL",
    label: "RVOL",
    category: "Volume",
    displayMode: "panel",
    params: [{ name: "period", label: "Period", default: 14, min: 1, max: 200 }],
    multi: false,
  },
  {
    id: "ACCUMULATED_VOLUME",
    label: "Accum. Volume",
    category: "Volume",
    displayMode: "panel",
    params: [],
    multi: false,
  },
  {
    id: "HEIKIN_ASHI",
    label: "Heikin-Ashi",
    category: "Volume",
    displayMode: "panel",
    params: [],
    multi: false,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const _byId = new Map<string, IndicatorDef>();
for (const def of INDICATOR_REGISTRY) _byId.set(def.id, def);

export function getIndicatorDef(id: string): IndicatorDef | undefined {
  return _byId.get(id);
}

export function getIndicatorsByCategory(): Record<IndicatorCategory, IndicatorDef[]> {
  const grouped: Record<IndicatorCategory, IndicatorDef[]> = {
    Trend: [],
    Momentum: [],
    Volatility: [],
    Volume: [],
  };
  for (const def of INDICATOR_REGISTRY) {
    grouped[def.category].push(def);
  }
  return grouped;
}

export function createDefaultParams(def: IndicatorDef): Record<string, number> {
  const params: Record<string, number> = {};
  for (const p of def.params) {
    params[p.name] = p.default;
  }
  return params;
}
