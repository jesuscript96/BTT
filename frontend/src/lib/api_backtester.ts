import axios from "axios";

/** Backend mounts routers at /api; accept env as origin only (e.g. Qlify/Hetzner URL without /api). */
function apiBaseUrl(): string {
  const fallback = "http://localhost:8010/api";
  const raw = process.env.NEXT_PUBLIC_API_URL;
  const s = (typeof raw === "string" && raw.trim() ? raw.trim() : fallback).replace(
    /\/+$/,
    ""
  );
  if (s.endsWith("/api")) return s;
  return `${s}/api`;
}

const api = axios.create({
  baseURL: apiBaseUrl(),
  timeout: 1800000, // 30 minutes to handle large GCS backtests
});

// Diagnostic logging for Production Network Error
console.log("[API] Base URL configured as:", apiBaseUrl());

// Inject the active Clerk session token on every request. Reads the global
// Clerk instance (set by ClerkProvider); no-op on the server / before load.
api.interceptors.request.use(async (config) => {
  if (typeof window !== "undefined") {
    try {
      const clerk = (window as unknown as {
        Clerk?: { session?: { getToken: () => Promise<string | null> } };
      }).Clerk;
      const token = await clerk?.session?.getToken?.();
      if (token) {
        config.headers = config.headers ?? {};
        (config.headers as Record<string, string>).Authorization = `Bearer ${token}`;
      }
    } catch {
      // No token available — let the request go out unauthenticated.
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // 401 → session expired or missing; bounce to sign-in.
    if (error.response?.status === 401 && typeof window !== "undefined") {
      if (!window.location.pathname.startsWith("/sign-in")) {
        window.location.href = "/sign-in";
      }
      return Promise.reject(error);
    }
    const isCancelled = error.response?.status === 400 &&
                        (error.response?.data?.detail === "Backtest cancelado" ||
                         error.response?.data?.message === "Backtest cancelado");
    if (!isCancelled) {
      console.error(
        `[API ERROR DIAGNOSTIC]\n` +
        `URL: ${error.config?.baseURL || ""}${error.config?.url || ""}\n` +
        `Method: ${error.config?.method?.toUpperCase() || "N/A"}\n` +
        `Status: ${error.response?.status || "N/A"}\n` +
        `Message: ${error.message || "N/A"}\n` +
        `Response Data:`,
        error.response?.data || "No data"
      );
    }
    return Promise.reject(error);
  }
);


export interface Dataset {
  id: string;
  name: string;
  pair_count: number;
  created_at: string;
  min_date?: string;
  max_date?: string;
  filters?: Record<string, any>;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  definition: any;
  // Some components also read these directly off the strategy (strategy.x),
  // falling back from strategy.definition?.x — the API returns both the wrapped
  // ({ definition: {...} }) and flat shapes. Keep optional+loose for both.
  risk_management?: any;
  bias?: any;
  apply_day?: any;
  entry_logic?: any;
  exit_logic?: any;
}

export interface TradeRecord {
  ticker: string;
  date: string;
  entry_time: string;
  exit_time: string;
  entry_idx: number;
  exit_idx: number;
  entry_time_epoch: number;
  exit_time_epoch: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  fees?: number;
  return_pct: number;
  direction: string;
  status: string;
  size: number;
  exit_reason: string;
  mae: number;
  mfe?: number;
  r_multiple: number | null;
  entry_hour: number;
  entry_weekday: number;
  gap_pct?: number | null;
}

export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number | null;
}

export interface EquityPoint {
  time: number;
  value: number;
}

export interface DayCandles {
  ticker: string;
  date: string;
  candles: CandleData[];
}

export interface DayEquity {
  ticker: string;
  date: string;
  equity: EquityPoint[];
}

export interface DayResult {
  ticker: string;
  date: string;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  win_rate_pct: number | null;
  total_trades: number;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  expectancy: number | null;
  best_trade_pct: number | null;
  worst_trade_pct: number | null;
  init_value: number | null;
  end_value: number | null;
  gap_pct?: number | null;
}

export interface AggregateMetrics {
  total_days: number;
  total_trades: number;
  win_rate_pct: number;
  avg_return_per_day_pct: number;
  total_return_pct: number;
  avg_sharpe: number;
  max_drawdown_pct: number;
  avg_profit_factor: number;
  avg_pnl: number;
  total_pnl: number;
  sortino_ratio: number;
  calmar_ratio: number;
  dd_return_ratio: number;
  r_squared: number;
  max_mae: number;
  max_profit_pct: number;
  avg_win: number;
  avg_loss: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  expectancy: number;
  payoff_ratio: number;
  avg_r_per_day: number;
  avg_r_ui: number;
}

export interface GlobalEquityPoint {
  time: number;
  value: number;
}

export interface DrawdownPoint {
  time: number;
  value: number;
}

export interface BacktestResult {
  aggregate_metrics: AggregateMetrics;
  day_results: DayResult[];
  trades: TradeRecord[];
  equity_curves: DayEquity[];
  global_equity: GlobalEquityPoint[];
  global_equity_expenses?: GlobalEquityPoint[];
  global_drawdown: DrawdownPoint[];
}

export interface WhatIfResult {
  trades: TradeRecord[];
  global_equity: GlobalEquityPoint[];
  global_drawdown: DrawdownPoint[];
  aggregate_metrics: AggregateMetrics;
}

export interface MonteCarloPercentileCurve {
  time: number;
  value: number;
}

export interface MonteCarloResult {
  percentiles: Record<string, MonteCarloPercentileCurve[]>;
  ruin_probability: number;
  worst_drawdown: number;
  median_drawdown: number;
  final_balance_percentiles: Record<string, number>;
}

export async function runMonteCarlo(params: {
  pnls: number[];
  init_cash: number;
  simulations?: number;
}): Promise<MonteCarloResult> {
  const { data } = await api.post("/montecarlo", params);
  return data;
}
export interface AvailableDateRange {
  min_date: string;
  max_date: string;
}

let cachedDatasets: Dataset[] | null = null;
let cachedDateRange: AvailableDateRange | null = null;

export function clearDatasetsCache() {
  cachedDatasets = null;
  cachedDateRange = null;
}

export async function fetchAvailableDateRange(): Promise<AvailableDateRange> {
  if (cachedDateRange) {
    return cachedDateRange;
  }
  try {
    const { data } = await api.get(`/market/available-date-range?t=${Date.now()}`);
    cachedDateRange = data;
    return data;
  } catch (err) {
    console.error("Failed to fetch available date range, using fallbacks:", err);
    return {
      min_date: "2022-01-01",
      max_date: new Date().toISOString().split("T")[0]
    };
  }
}

export async function fetchDatasets(): Promise<Dataset[]> {
  if (cachedDatasets) {
    return cachedDatasets;
  }
  const { data } = await api.get(`/data/datasets?t=${Date.now()}`);
  cachedDatasets = data;
  return data;
}

export async function fetchStrategies(): Promise<Strategy[]> {
  const { data } = await api.get(`/data/strategies?t=${Date.now()}`);
  return data;
}

export async function runBacktest(params: {
  dataset_id: string;
  strategy_id: string;
  init_cash: number;
  risk_r: number;
  risk_type?: string;
  size_by_sl?: boolean;
  fees: number;
  fee_type?: string;
  slippage: number;
  start_date?: string;
  end_date?: string;
  market_sessions?: string[];
  custom_start_time?: string;
  custom_end_time?: string;
  locates_cost?: number;
  locate_type?: "PERCENT" | "FLAT";
  look_ahead_prevention?: boolean;
}): Promise<BacktestResult> {
  const { data } = await api.post("/backtest", params);
  return data;
}

export async function runBacktestWithDefinition(params: {
  dataset_id: string;
  strategy_definition: Record<string, unknown>;
  init_cash: number;
  risk_r: number;
  risk_type?: string;
  fixed_ratio_delta?: number;
  size_by_sl?: boolean;
  fees: number;
  fee_type?: string;
  slippage: number;
  start_date?: string;
  end_date?: string;
  market_sessions?: string[];
  custom_start_time?: string;
  custom_end_time?: string;
  locates_cost?: number;
  look_ahead_prevention?: boolean;
  monthly_expenses?: number;
}): Promise<BacktestResult> {
  const { data } = await api.post("/backtest", params);
  return data;
}

export async function fetchDayCandles(
  dataset_id: string,
  ticker: string,
  date: string
): Promise<DayCandles> {
  const { data } = await api.get("/candles", {
    params: { dataset_id, ticker, date },
  });
  return data;
}

export interface MultiDayCandles {
  gap_day?: { date: string; candles: CandleData[] };
  gap_1_day?: { date: string; candles: CandleData[] };
  gap_2_day?: { date: string; candles: CandleData[] };
  [key: string]: { date: string; candles: CandleData[] } | undefined;
}

export async function fetchMultiDayCandles(
  dataset_id: string,
  ticker: string,
  date: string,
  apply_day: string,
  swing_active?: boolean,
  swing_target_day?: string
): Promise<MultiDayCandles> {
  const { data } = await api.get("/candles/multi", {
    params: { dataset_id, ticker, date, apply_day, swing_active, swing_target_day },
  });
  return data;
}


// --- Optimization Surface ---

export interface OptimizationParam {
  id: string;
  label: string;
  current_value: number;
  category: string;
  path: string;
  min: number;
  max: number;
  step: number;
}

export interface OptimizationParamConfig {
  id: string;
  label: string;
  path: string;
  min: number;
  max: number;
  steps: number;
}

export interface PlateauAnalysis {
  peak: { value: number | null; coordinates: Record<string, number> };
  robust_plateau: {
    mean_value: number | null;
    std_value: number | null;
    size: number;
    profit_factor: number | null;
    return_dd: number | null;
    total_return: number | null;
  };
  local_stability: {
    best_value: number | null;
    coordinates: Record<string, number>;
    profit_factor: number | null;
    return_dd: number | null;
  };
  robust_center: {
    coordinates: Record<string, number>;
    degradation_from_peak: number | null;
  };
}

export interface OptimizationResult {
  params: { id: string; label: string; values: number[] }[];
  grid: number[][];
  metric: string;
  metric_label: string;
  details: Record<string, number>[];
  shape: number[];
  plateau_analysis: PlateauAnalysis;
  plateau_analyses?: Record<string, PlateauAnalysis>;
  elapsed_seconds: number;
}

export async function fetchOptimizationParams(
  strategy_id: string,
  strategy_definition?: Record<string, unknown>
): Promise<{ parameters: OptimizationParam[]; strategy_name: string }> {
  const { data } = await api.post("/optimization/parameters", { strategy_id, strategy_definition });
  return data;
}

export async function runOptimizationSurface(params: {
  strategy_id: string;
  strategy_definition?: Record<string, unknown>;
  dataset_id: string;
  metric: string;
  param_configs: OptimizationParamConfig[];
  init_cash?: number;
  risk_r?: number;
  risk_type?: string;
  size_by_sl?: boolean;
  fees?: number;
  fee_type?: string;
  slippage?: number;
  start_date?: string;
  end_date?: string;
  market_sessions?: string[];
  custom_start_time?: string;
  custom_end_time?: string;
  locates_cost?: number;
  monthly_expenses?: number;
  fixed_ratio_delta?: number;
  look_ahead_prevention?: boolean;
  is_percent?: number;
  task_id?: string;
}): Promise<{ task_id: string; status: string }> {
  const { data } = await api.post("/optimization/surface", params);
  return data;
}

export async function fetchOptimizationProgress(task_id: string): Promise<number> {
  const { data } = await api.get(`/optimization/progress/${task_id}`);
  return data.progress;
}

export async function fetchOptimizationResult(task_id: string): Promise<OptimizationResult | { status: string; progress: number }> {
  const { data } = await api.get(`/optimization/result/${task_id}`);
  return data;
}

export interface PrecacheStatus {
  status: string;
  percent: number;
  current: number;
  total: number;
  error?: string;
}

export async function fetchPrecacheStatus(datasetId: string): Promise<PrecacheStatus> {
  const { data } = await api.get(`/queries/precache-status/${encodeURIComponent(datasetId)}?t=${Date.now()}`);
  return data;
}

export interface BacktestProgress {
  status: string;
  percent: number;
  current: number;
  total: number;
}

export async function fetchBacktestProgress(datasetId: string): Promise<BacktestProgress> {
  const { data } = await api.get(`/backtest/progress/${encodeURIComponent(datasetId)}?t=${Date.now()}`);
  return data;
}

export async function runWhatIf(params: {
  trades: TradeRecord[];
  init_cash: number;
  risk_r: number;
  params: Record<string, unknown>;
}): Promise<WhatIfResult> {
  const { data } = await api.post("/what-if", params);
  return data;
}

export async function cancelBacktest(datasetId: string): Promise<{ status: string }> {
  const { data } = await api.post(`/backtest/cancel/${encodeURIComponent(datasetId)}`);
  return data;
}

export async function cancelOptimization(task_id: string): Promise<{ status: string }> {
  const { data } = await api.post(`/optimization/cancel/${task_id}`);
  return data;
}


