// Cliente del laboratorio de Portfolio (/api/portfolio-lab).
//
// Igual que api_robustez: listado ligero con columnas tipadas, NUNCA el
// `results_json` entero (el endpoint del Baul viejo devolvia ~48 MB).
// El prefijo /api/portfolio (sin -lab) es del modulo de produccion del
// equipo y no se usa desde aqui.

import { apiRequest } from "./api";
import type { MonteCarloOut } from "./api_robustez";

/* ── Listado ─────────────────────────────────────────────────────── */

export interface PortfolioRunMeta {
  run_id: string;
  executed_at: string | null;
  total_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  backtest_params: Record<string, unknown>;
}

export interface PortfolioNormalization {
  normalized: boolean;
  /** false = la reconstruccion sera aproximada (la corrida llevaba slippage). */
  exact: boolean;
  issues: string[];
}

export type Bucket = "portfolio" | "incubadora";

export interface PortfolioStrategy {
  id: string;
  name: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
  definition: Record<string, unknown>;
  run: PortfolioRunMeta | null;
  buckets: Bucket[];
  normalization: PortfolioNormalization | null;
}

export function listPortfolioStrategies(): Promise<PortfolioStrategy[]> {
  return apiRequest<PortfolioStrategy[]>("/portfolio-lab/strategies");
}

export function setPortfolioAssignment(
  strategyId: string,
  bucket: Bucket,
  present: boolean,
): Promise<{ strategy_id: string; buckets: Bucket[] }> {
  return apiRequest("/portfolio-lab/assignments", {
    method: "POST",
    body: JSON.stringify({ strategy_id: strategyId, bucket, present }),
  });
}

/** Curva diaria de la ultima corrida (solo {time, value}, sin trades) —
 *  para el minigrafico del desplegable del baul. */
export function getPortfolioStrategyEquity(
  strategyId: string,
): Promise<{ run_id: string; equity: Array<{ time: number; value: number }> }> {
  return apiRequest(`/portfolio-lab/strategies/${strategyId}/equity`);
}

/* ── Imagen general (combine) ────────────────────────────────────── */

export interface CombineConfigIn {
  strategy_ids: string[];
  init_cash: number;
  risk_type: "FIXED" | "PERCENT";
  risk_r: number;
  fees: number;
  fee_type: "FLAT" | "PERCENT";
  /** En % REAL de la interfaz (0.1 = 0,1%); el backend convierte a fraccion. */
  slippage_pct: number;
  locates_cost: number;
  monthly_expenses: number;
  start_date?: string | null;
  end_date?: string | null;
}

export interface CombineMetrics {
  final_equity: number;
  total_return_pct: number;
  cagr_pct: number;
  max_drawdown_pct: number;
  longest_dd_days: number;
  longest_dd_pct_of_span: number;
  time_in_dd_pct: number;
  span_days: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  ulcer_index: number;
  n_trades: number;
  win_rate: number;
  profit_factor: number;
  expectancy_r: number;
  avg_win: number;
  avg_loss: number;
  payoff: number;
}

export interface CombineVar {
  var95: number;
  cvar95: number;
  var99: number;
  cvar99: number;
  hist_counts: number[];
  hist_edges: number[];
}

export interface CombineCorrelation {
  ids: string[];
  matrix: Array<Array<number | null>>;
  overlap_days: number[][];
  avg_pairwise: number | null;
  max_pair: { i: number; j: number; corr: number } | null;
  min_overlap_warning: boolean;
}

export interface CombinePerStrategy {
  run_id: string;
  name: string;
  alive_from: string | null;
  alive_to: string | null;
  pnl_daily: number[];
  r_daily: number[];
  totals: {
    pnl_net: number;
    cum_r: number;
    n_trades: number;
    win_rate: number;
    fees: number;
    slippage: number;
    locates: number;
  };
}

export interface CombineStrategyInfo {
  strategy_id: string;
  name: string;
  normalization: PortfolioNormalization;
  span: { start: string | null; end: string | null };
}

export interface CombineOut {
  config: Record<string, unknown>;
  calendar: string[];
  equity: number[];
  daily_pnl: number[];
  daily_r_net: number[];
  ruined: boolean;
  metrics: CombineMetrics;
  costs: { fees: number; slippage: number; locates: number; expenses: number };
  var: CombineVar | null;
  correlation: CombineCorrelation | null;
  per_strategy: CombinePerStrategy[];
  trades_seq: {
    dates: string[];
    strategy_idx: number[];
    r_net: number[];
    pnl_net: number[];
  };
  strategies: CombineStrategyInfo[];
}

export function runPortfolioCombine(body: CombineConfigIn): Promise<CombineOut> {
  return apiRequest<CombineOut>("/portfolio-lab/combine", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

/* ── Escalado y ponderacion (F2) ─────────────────────────────────── */

export type ScalingModel = "fixed" | "percent" | "fixed_ratio" | "kelly" | "combinatoria";
export type WeightModel = "equal" | "hrp" | "momentum" | "ev" | "dd";
export type RebalanceFreq = "D" | "W" | "M";

export interface ScalingCfg {
  model: ScalingModel;
  base_risk: number;
  pct: number;
  delta: number;
  kelly_mult: number;
  threshold_equity: number;
}

export interface WeightingCfg {
  model: WeightModel;
  floor: number;
  cap_strat_pct: number;
}

export interface ScalingReqIn {
  strategy_ids: string[];
  init_cash: number;
  fees: number;
  fee_type: "FLAT" | "PERCENT";
  slippage_pct: number;
  locates_cost: number;
  monthly_expenses: number;
  start_date?: string | null;
  end_date?: string | null;
  rebalance: RebalanceFreq;
  lookback_days: number;
  cap_global_pct: number;
  scaling: ScalingCfg;
  weighting: WeightingCfg;
}

export interface RebalancePoint {
  date: string;
  equity: number;
  x: number;
  x_pct: number;
  weights: number[];
  risks: number[];
  note: string | null;
  /** El modelo de pesos cayó a IGUALES por falta de muestra en la ventana. */
  w_fallback?: boolean;
}

export interface ScalingPerStrategy {
  run_id: string;
  name: string;
  pnl_net: number;
  cum_r: number;
  n_trades: number;
  win_rate: number;
  weight_now: number | null;
  risk_now: number | null;
}

export interface ScalingOut {
  config: Record<string, unknown>;
  calendar: string[];
  equity: number[];
  daily_pnl: number[];
  /** PnL diario en unidades del X vigente — el eje R del modelo. */
  daily_r_net: number[];
  ruined: boolean;
  metrics: CombineMetrics;
  var: CombineVar | null;
  correlation: CombineCorrelation | null;
  costs: { fees: number; slippage: number; locates: number; expenses: number };
  timeline: RebalancePoint[];
  now: RebalancePoint | null;
  per_strategy: ScalingPerStrategy[];
  n_rebalances: number;
  weight_fallbacks: number;
  kelly_notes: number;
  /** Rebalanceos en los que el tope global del usuario recortó el size. */
  cap_hits: number;
  strategies: CombineStrategyInfo[];
}

export function runPortfolioScaling(body: ScalingReqIn): Promise<ScalingOut> {
  return apiRequest<ScalingOut>("/portfolio-lab/scaling", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

export interface ScalingVariantIn {
  label: string;
  scaling?: ScalingCfg;
  weighting?: WeightingCfg;
}

export interface ScalingCompareResult {
  label: string;
  error?: string;
  metrics?: CombineMetrics;
  equity?: number[];
  calendar?: string[];
  daily_r_net?: number[];
  ruined?: boolean;
  now?: RebalancePoint | null;
  costs?: { fees: number; slippage: number; locates: number; expenses: number };
}

export function runPortfolioScalingCompare(
  body: ScalingReqIn & { variants: ScalingVariantIn[] },
): Promise<{ results: ScalingCompareResult[] }> {
  return apiRequest("/portfolio-lab/scaling/compare", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

/* ── Monitorizacion (F3) ─────────────────────────────────────────── */

export interface MonitorSnapshot {
  refreshed_at: string | null;
  start_date: string;
  equity: Array<{ time: number; value: number }>;
  n_trades: number | null;
  return_pct: number | null;
  max_dd_pct: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  dd_now_pct: number;
}

export interface MonitorStrategy {
  strategy_id: string;
  name: string;
  buckets: Bucket[];
  theoretical: {
    total_return_pct: number | null;
    max_drawdown_pct: number | null;
    total_trades: number | null;
    executed_at: string | null;
  };
  snapshot: MonitorSnapshot | null;
}

export function getPortfolioMonitor(): Promise<{ busy: boolean; task_id: string | null; strategies: MonitorStrategy[] }> {
  return apiRequest("/portfolio-lab/monitor");
}

export function refreshPortfolioMonitor(): Promise<{ task_id: string; n_strategies: number }> {
  return apiRequest("/portfolio-lab/monitor/refresh", { method: "POST", timeoutMs: 60_000 });
}

export function getPortfolioMonitorJob(taskId: string): Promise<{
  status: "running" | "done" | "error";
  progress: number;
  result?: { done: string[]; errors: Array<{ strategy_id: string; error: string }>; window_start: string };
  error?: string;
}> {
  return apiRequest(`/portfolio-lab/monitor/job/${taskId}`);
}

export interface RealControlIn {
  initial_capital: number;
  base_risk: number;
  model: "compound" | "fixed_ratio" | "kelly" | "dd";
  pct: number;
  delta: number;
  kelly_mult: number;
  dd_floor: number;
  lookback_days: number;
  cap_global_pct: number;
}

export interface RealControlOut {
  dates: string[];
  equity: number[];
  daily_pnl: number[];
  metrics: {
    n_days: number;
    total_pnl: number;
    return_pct: number;
    final_equity: number;
    max_dd_pct: number;
    dd_now_pct: number;
    win_days_pct: number;
    best_day: number;
    worst_day: number;
    avg_day: number;
    sharpe_d: number;
  };
  recommendation: {
    model: string;
    x: number;
    x_pct: number;
    vs_base: number | null;
    note: string | null;
  };
}

export function runRealControl(body: RealControlIn): Promise<RealControlOut> {
  return apiRequest("/portfolio-lab/monitor/control", { method: "POST", body: JSON.stringify(body), timeoutMs: 60_000 });
}

export interface WeightsNowOut {
  weights: number[];
  fallback: boolean;
  window: { from: string; to: string; sessions: number };
  strategies: Array<{ strategy_id: string; name: string; normalization: PortfolioNormalization }>;
}

export function runWeightsNow(body: {
  strategy_ids: string[];
  lookback_days: number;
  model: WeightModel;
  floor: number;
}): Promise<WeightsNowOut> {
  return apiRequest("/portfolio-lab/monitor/weights", { method: "POST", body: JSON.stringify(body), timeoutMs: 120_000 });
}

export function getRealPnl(): Promise<{ rows: Array<{ date: string; pnl: number }> }> {
  return apiRequest("/portfolio-lab/monitor/real");
}

export function saveRealPnl(rows: Array<{ date: string; pnl: number }>): Promise<{ saved: number; total: number }> {
  return apiRequest("/portfolio-lab/monitor/real", { method: "POST", body: JSON.stringify({ rows }) });
}

export function clearRealPnl(): Promise<{ cleared: boolean }> {
  return apiRequest("/portfolio-lab/monitor/real", { method: "DELETE" });
}

/* ── Monte Carlo ─────────────────────────────────────────────────── */

export interface PortfolioMcIn {
  /** Serie DIARIA del portfolio: daily_r_net (compound) o daily_pnl (additive). */
  values: number[];
  init_cash: number;
  simulations: number;
  method: "bootstrap" | "permutacion";
  mode: "compound" | "additive";
  risk_pct: number;
  ruin_pct: number;
  seed?: number | null;
}

export function runPortfolioMc(body: PortfolioMcIn): Promise<MonteCarloOut> {
  return apiRequest<MonteCarloOut>("/portfolio-lab/montecarlo", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}
