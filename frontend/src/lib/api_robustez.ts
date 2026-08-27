// Cliente de la pagina de Robustez.
//
// Deliberadamente NO usa `getSavedBacktests()` del Baul: ese endpoint devuelve
// el results_json completo de TODAS las corridas (48 MB con una sola estrategia
// guardada) y ni en localhost termina de descargarse. Aqui la lista es ligera y
// los trades se piden solo para la estrategia elegida.

import { apiRequest } from "./api";
import type { OptimizationParamUnit } from "./api_backtester";

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

/** Resumen de una muestra: lo que devuelve `_describe` en el backend. */
export interface McSample {
  n: number;
  mean: number;
  median: number;
  p5: number;
  p25: number;
  p75: number;
  p95: number;
  worst: number;
  best: number;
}

/**
 * Perdidas paso a paso del bootstrap.
 *
 * Un "paso" es la unidad remuestreada: una sesion o un trade, segun `unit`.
 * Ojo con la diferencia entre las dos familias: `step_*` describe UN paso
 * cualquiera, `worst_step_*` describe el PEOR paso de cada simulacion completa.
 */
export interface McLosses {
  unit: "day" | "trade";
  sampled_curves: number;
  sampled_steps: number;
  step_usd: McSample;
  step_pct: McSample;
  win_usd: McSample;
  loss_usd: McSample;
  win_pct: McSample;
  loss_pct: McSample;
  win_rate_pct: number;
  worst_step_usd: McSample;
  worst_step_pct: McSample;
  streak: {
    median: number;
    p95: number;
    p99: number;
    worst: number;
    mean: number;
    histogram: Array<{ length: number; count: number }>;
  };
  /** Cuantiles ordenados (501 puntos) para resolver umbrales por interpolacion. */
  grids: {
    step_usd: number[];
    step_pct: number[];
    worst_step_usd: number[];
    worst_step_pct: number[];
    max_dd_pct: number[];
  };
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
  /** Perdidas por paso y rejillas de probabilidad. */
  losses?: McLosses;
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
  unit?: "day" | "trade";
  seed?: number | null;
}): Promise<MonteCarloOut> {
  return apiRequest<MonteCarloOut>("/robustness/montecarlo", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}

/* ── Horizonte: probabilidad de ruina / objetivo en X dias ───────────── */

/** Curvas ACUMULADAS: `prob_*[i]` es el % de trayectorias que ya habia tocado
 *  ese nivel el dia `days[i]`. Van siempre en paralelo (mismo indice). */
export interface HorizonOut {
  days: number[];
  prob_ruin_pct: number[];
  prob_target_pct: number[];
  /** Objetivo alcanzado ANTES de arruinarse: el que aprueba un fondeo. */
  prob_target_alive_pct: number[];
  init_cash: number;
  ruin_pct: number;
  target_pct: number;
  ruin_level: number;
  target_level: number;
  max_days: number;
  simulations: number;
  sample_size: number;
}

export function runRobustezHorizon(body: {
  values: number[];
  init_cash: number;
  simulations: number;
  mode: CompoundMode;
  risk_pct: number;
  ruin_pct: number;
  target_pct: number;
  max_days: number;
  seed?: number | null;
}): Promise<HorizonOut> {
  return apiRequest<HorizonOut>("/robustness/montecarlo/horizon", {
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

/* ── Prueba de fondeo ────────────────────────────────────────────────── */

/** Reparto de desenlaces de un challenge, bajo una lectura (cierre o MAE). */
export interface FundingOutcome {
  pass_pct: number;
  fail_daily_pct: number;
  fail_dd_pct: number;
  /** Ni pasa ni rompe: se agoto el plazo o el histórico simulado. */
  unresolved_pct: number;
  sessions_to_pass: { n: number; p25?: number; p50?: number; p75?: number; min?: number; max?: number };
  session_of_breach: { n: number; p25?: number; p50?: number; p75?: number; min?: number; max?: number };
  final_return_pct: { p5: number; p50: number; p95: number };
}

export interface FundingOut {
  simulations: number;
  account: number;
  n_steps: number;
  history_days: number;
  mode: CompoundMode;
  risk_pct: number;
  /** Factor aplicado a la serie en aditivo para llevarla de `values_base_cash`
   *  a `account`. 1 = sin reescalar (o modo compuesto). */
  scale: number;
  values_base_cash: number | null;
  rules: {
    target_pct: number;
    target_usd: number;
    daily_loss_pct: number;
    daily_loss_usd: number;
    max_dd_pct: number;
    dd_basis: "percent" | "fixed";
    dd_usd_at_start: number;
    min_trading_days: number;
    min_trades: number;
    horizon_days: number | null;
  };
  /** Evaluado con el PnL de cierre de cada sesion. */
  closed: FundingOutcome;
  /** Evaluado incluyendo la peor excursion intradia. null si no se mando MAE. */
  mae: FundingOutcome | null;
}

export function runRobustezFunding(body: {
  values: number[];
  mae_fracs?: number[] | null;
  trades_per_day?: number[] | null;
  account: number;
  risk_pct: number;
  mode: CompoundMode;
  target_pct: number;
  daily_loss_pct: number;
  max_dd_pct: number;
  dd_basis: "percent" | "fixed";
  min_trading_days: number;
  min_trades: number;
  horizon_days?: number | null;
  simulations: number;
  seed?: number | null;
  /** Capital del backtest del que salen `values`. En ADITIVO reescala la serie
   *  de dolares a `account`; sin esto, cambiar la cuenta encogia las reglas
   *  pero no el tamaño de las apuestas. En compuesto se ignora. */
  values_base_cash?: number | null;
}): Promise<FundingOut> {
  return apiRequest<FundingOut>("/robustness/funding", {
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
  /** Unidad del barrido. `time_of_day` = MINUTOS DESDE MEDIANOCHE, que hay que
   *  pintar como HH:MM: un cierre a las 08:30 viaja como 510. El backend ya la
   *  mandaba (`extract_parameters`), pero este tipo no la declaraba y Walk
   *  Forward enseñaba el número crudo. */
  unit?: OptimizationParamUnit;
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
