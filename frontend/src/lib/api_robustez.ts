// Cliente de la pagina de Robustez.
//
// Deliberadamente NO usa `getSavedBacktests()` del Baul: ese endpoint devuelve
// el results_json completo de TODAS las corridas (48 MB con una sola estrategia
// guardada) y ni en localhost termina de descargarse. Aqui la lista es ligera y
// los trades se piden solo para la estrategia elegida.

import { apiRequest } from "./api";

export interface RobustezRunMeta {
  run_id: string;
  executed_at: string | null;
  total_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  /** Capital, comisiones, slippage, locates... con los que se ejecuto. */
  backtest_params: Record<string, unknown>;
}

export interface RobustezStrategy {
  id: string;
  name: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
  definition: Record<string, unknown>;
  run: RobustezRunMeta | null;
}

export interface RobustezTrade {
  ticker: string;
  date: string;
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  fees: number;
  return_pct: number;
  direction: string;
  size: number;
  exit_reason: string;
  mae: number;
  mfe: number;
  r_multiple: number;
  entry_hour: number;
  entry_weekday: number;
  gap_pct: number;
  stop_loss: number;
  /** R exacta derivada de pnl y la equity del dia. Ver attach_precise_r. */
  r_precise: number;
}

export interface EquityPointT {
  time: number;
  value: number;
}

export interface RobustezCompounding {
  /** true si el backtest arriesgaba un % del capital vivo (risk_type PERCENT). */
  is_percent_risk: boolean;
  risk_pct: number;
  init_cash: number;
  /** true si se pudo derivar la R exacta para todos los trades. */
  r_precise_exact: boolean;
}

export interface RobustezRun {
  run_id: string;
  executed_at: string | null;
  aggregate_metrics: Record<string, number>;
  backtest_params: Record<string, unknown>;
  global_equity: EquityPointT[];
  global_drawdown: EquityPointT[];
  trades: RobustezTrade[];
  compounding: RobustezCompounding;
}

export type McMethod = "bootstrap" | "permutacion";
export type CompoundMode = "compound" | "additive";

export interface McBands {
  p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[];
}

export interface McHistogram {
  counts: number[];
  edges: number[];
}

export interface MonteCarloOut {
  method: McMethod;
  mode: CompoundMode;
  risk_pct: number;
  simulations: number;
  n_trades: number;
  init_cash: number;
  bands_from: number;
  base_curve: number[];
  base_final: number;
  base_return_pct: number;
  base_max_drawdown: number;
  spaghetti: number[][];
  bands: McBands;
  final_balance: Record<string, number>;
  return_pct: Record<string, number>;
  drawdown: Record<string, number>;
  dd_tolerance: { p95: number; p99: number };
  prob_losing_pct: number;
  prob_ruin_pct: number;
  ruin_pct_threshold: number;
  hist_final: McHistogram;
  hist_drawdown: McHistogram;
  /** Recorrido del drawdown en el caso real y en tres escenarios simulados. */
  dd_paths?: {
    real: number[];
    p50: number[];
    p95: number[];
    p99: number[];
    levels: { real: number; p50: number; p95: number; p99: number };
  };
}

export interface StressMetrics {
  total_trades: number;
  total_return_pct: number;
  final_balance: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  sharpe: number;
  trading_days: number;
  /** Sesiones en las que de verdad se opero (las vacias no cuentan). */
  active_days: number;
}

export interface StressOut {
  mode: CompoundMode;
  risk_pct: number;
  init_cash: number;
  base: StressMetrics;
  stressed: StressMetrics;
  base_curve: Array<{ date: string; value: number }>;
  stressed_curve: Array<{ date: string; value: number }>;
  trades_removed: number;
  trades_kept: number;
}

export function listRobustezStrategies(): Promise<RobustezStrategy[]> {
  return apiRequest<RobustezStrategy[]>("/robustness/strategies");
}

export function getRobustezRun(strategyId: string): Promise<RobustezRun> {
  // Cargar ~3.500 trades por localhost va sobrado en 20 s, pero el default del
  // cliente es justo eso; se sube para no cortar corridas mas largas.
  return apiRequest<RobustezRun>(
    `/robustness/strategies/${encodeURIComponent(strategyId)}/run`,
    { timeoutMs: 120_000 },
  );
}

export function runRobustezMonteCarlo(body: {
  values: number[];
  init_cash: number;
  simulations: number;
  method: McMethod;
  mode: CompoundMode;
  risk_pct: number;
  ruin_pct: number;
  seed?: number | null;
}): Promise<MonteCarloOut> {
  return apiRequest<MonteCarloOut>("/robustness/montecarlo", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

export function runRobustezStress(body: {
  trades: RobustezTrade[];
  params: Record<string, unknown>;
  init_cash: number;
  mode: CompoundMode;
  risk_pct: number;
  seed?: number | null;
}): Promise<StressOut> {
  return apiRequest<StressOut>("/robustness/stress", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

/* ── Modulos pesados (re-ejecutan backtests, van por tarea en 2o plano) ── */

export interface JobStatus {
  busy: boolean;
  task_id: string | null;
  kind: string | null;
  elapsed_s: number | null;
}

export interface JobPoll<T> {
  status: "running" | "done" | "error" | "cancelled";
  progress: number;
  result?: T;
  error?: string;
}

export interface LocateCurveOut {
  locates_cost: number;
  seconds: number;
  metrics: Record<string, number | null>;
  equity_by_time: Array<{ time: number; value: number }>;
  equity_by_trade: number[];
}

export interface LocatesCurvesOut {
  kind: "locates_curves";
  slippage: number;
  monthly_expenses: number;
  curves: LocateCurveOut[];
  load_seconds: number;
  sweep_seconds: number;
  n_groups: number;
  break_even: number | null;
}

export interface LocatesMatrixOut {
  kind: "locates_slippage_matrix";
  locates_values: number[];
  slippage_values: number[];
  monthly_expenses: number;
  grids: Record<string, Array<Array<number | null>>>;
  frontier: Array<{ slippage: number; break_even_locates: number | null }>;
  n_points: number;
  n_groups: number;
  load_seconds: number;
  sweep_seconds: number;
  seconds_per_point: number | null;
  first_point_seconds: number | null;
}

export function getRobustezJob(): Promise<JobStatus> {
  return apiRequest<JobStatus>("/robustness/job");
}

export function pollRobustezJob<T>(taskId: string): Promise<JobPoll<T>> {
  return apiRequest<JobPoll<T>>(`/robustness/job/${encodeURIComponent(taskId)}`);
}

export function cancelRobustezJob(taskId: string): Promise<{ status: string }> {
  return apiRequest<{ status: string }>(`/robustness/job/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
  });
}

export function startLocatesCurves(body: {
  strategy_id: string;
  locates_min: number;
  locates_max: number;
  locates_steps: number;
  slippage: number;
  monthly_expenses: number;
  start_date?: string | null;
  end_date?: string | null;
}): Promise<{ task_id: string; n_points: number }> {
  return apiRequest("/robustness/locates/curves", { method: "POST", body: JSON.stringify(body) });
}

export function startLocatesMatrix(body: {
  strategy_id: string;
  locates_min: number;
  locates_max: number;
  locates_steps: number;
  slippage_min: number;
  slippage_max: number;
  slippage_steps: number;
  monthly_expenses: number;
  start_date?: string | null;
  end_date?: string | null;
}): Promise<{ task_id: string; n_points: number }> {
  return apiRequest("/robustness/locates/matrix", { method: "POST", body: JSON.stringify(body) });
}

/* ── Walk-forward ────────────────────────────────────────────────── */

export interface WfoWindowMetrics {
  trades: number;
  return_pct: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  sharpe: number;
  expectancy?: number;
  total_r?: number;
}

export interface WfoWindow {
  index: number;
  is_from: string;
  is_to: string;
  oos_from: string;
  oos_to: string;
  is_days: number;
  oos_days: number;
  is: WfoWindowMetrics;
  oos: WfoWindowMetrics;
  efficiency: number | null;
  best_params?: number[];
  param_labels?: string[];
  trials?: Array<{ params: number[]; score: number | null; return_pct: number | null; trades: number | null }>;
}

export interface WfoParamValue {
  value: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  wins: number;
  windows_scored: number;
  plateau: number | null;
}

export interface WfoParamAnalysis {
  label: string;
  per_value: WfoParamValue[];
  /** El recomendado cayo en un extremo del rango barrido. */
  at_edge: boolean;
  range: [number, number];
  recommended: number | null;
  recommended_plateau: number | null;
  winner_dispersion: number;
  winner_values: number[];
  n_windows: number;
  stability: "estable" | "dudosa" | "ruido";
}

export interface WfoOut {
  kind: "wfo_fast" | "wfo_full";
  mode: "rolling" | "anchored";
  metric: string;
  windows: WfoWindow[];
  wfo_efficiency: number | null;
  wfo_efficiency_mean: number | null;
  windows_oos_positive: number;
  windows_total: number;
  consistency_pct: number;
  param_configs?: Array<{ path: string; label: string; values: number[] }>;
  param_analysis?: WfoParamAnalysis | null;
  n_backtests?: number;
  signal_cache_used?: boolean;
  load_seconds?: number;
  sweep_seconds?: number;
}

export interface OptimizableParam {
  id: string;
  label: string;
  current_value: number;
  category: string;
  path: string;
  min: number;
  max: number;
  step: number;
  cheap: boolean;
}

export function getStrategyParameters(strategyId: string): Promise<{ parameters: OptimizableParam[] }> {
  return apiRequest(`/robustness/strategies/${encodeURIComponent(strategyId)}/parameters`, {
    timeoutMs: 60_000,
  });
}

export function runWfoFast(body: {
  strategy_id: string;
  n_windows: number;
  oos_pct: number;
  anchored: boolean;
  metric: string;
}): Promise<WfoOut> {
  return apiRequest("/robustness/wfo/fast", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

export function startWfoFull(body: {
  strategy_id: string;
  params: Array<{ path: string; label: string; min: number; max: number; steps: number }>;
  n_windows: number;
  oos_pct: number;
  anchored: boolean;
  metric: string;
  start_date?: string | null;
  end_date?: string | null;
}): Promise<{ task_id: string; n_backtests: number }> {
  return apiRequest("/robustness/wfo/full", { method: "POST", body: JSON.stringify(body) });
}
