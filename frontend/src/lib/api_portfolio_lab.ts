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
  // 120 s y no los 20 por defecto: nada mas arrancar la app, el backend y el
  // bot leen el lago del disco mecanico y la primera llamada del dia puede
  // tardar mas de 20 s (15-sep-2026). El backend ademas cachea los
  // parametros de cada corrida, asi que las siguientes van en 1-3 s.
  return apiRequest<PortfolioStrategy[]>("/portfolio-lab/strategies", { timeoutMs: 120_000 });
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

/* ── Borrado ─────────────────────────────────────────────────────── */

export interface DeletionPreview {
  id: string;
  name: string;
  /** Corridas que son solo suyas. */
  runs_own: number;
  /** Corridas de CARTERA que la incluian: tambien se borran. */
  runs_portfolio: number;
  buckets: string[];
}

export interface DeleteStrategyOut {
  deleted: boolean;
  id: string;
  name: string;
  runs_deleted: number;
  runs_portfolio_deleted: number;
  /** Ficheros .result/.equity borrados del disco. */
  files_deleted: number;
  buckets_cleared: string[];
}

/** Que desapareceria al borrarla. Solo lectura. */
export function previewStrategyDeletion(strategyId: string): Promise<DeletionPreview> {
  return apiRequest<DeletionPreview>(
    `/portfolio-lab/strategies/${encodeURIComponent(strategyId)}/deletion-preview`,
  );
}

/** IRREVERSIBLE: borra la estrategia, sus corridas propias y sus asignaciones. */
export function deletePortfolioStrategy(strategyId: string): Promise<DeleteStrategyOut> {
  return apiRequest<DeleteStrategyOut>(`/portfolio-lab/strategies/${encodeURIComponent(strategyId)}`, {
    method: "DELETE",
    timeoutMs: 60_000,
  });
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

/* ── Portfolio EN CRUDO (sin normalizar, con tope de exposicion) ──── */

/** Ejecucion de UNA estrategia dentro del portfolio: lo del panel izquierdo
 *  del backtester, fijado aqui (lo de la corrida se resetea). */
export interface RawExec {
  /** auto: el modo lo decide la ESTRATEGIA (su «Tamaño por SL»: riesgo al stop
   *  o capital metido); aqui solo se pone el R. capital/risk lo fuerzan;
   *  as_saved deja el trade tal cual la corrida. */
  sizing: "auto" | "capital" | "risk" | "as_saved";
  size_value: number;
  size_unit: "usd" | "pct";
  /** $ por accion (FLAT) o % del valor operado (PERCENT), en los dos lados. */
  fees: number;
  fee_type: "FLAT" | "PERCENT";
  /** % del precio en cada lado. */
  slippage_pct: number;
  locates: "none" | "fixed" | "random";
  /** $ por paquete de 100 acciones (fixed). */
  locates_cost: number;
  locates_min: number;
  locates_max: number;
  locates_seed: number;
}

export const RAW_EXEC_DEFAULT: RawExec = {
  sizing: "auto",
  // 1 % del capital del dia: con varios trades al dia y PF > 1, un 5 %
  // compuesto cada dia explota a cifras de 10^25 (la trampa de «1B»).
  size_value: 1,
  size_unit: "pct",
  fees: 0,
  fee_type: "FLAT",
  slippage_pct: 0,
  locates: "none",
  locates_cost: 0,
  locates_min: 1,
  locates_max: 10,
  locates_seed: 1,
};

/** Puerta por EV del portfolio: la cuenta del backtester (locates_gate) con
 *  los paquetes DE MAS respecto a lo ya alquilado hoy por cualquiera. */
export interface RawGateIn {
  /** ev: EV rodante de la estrategia vs fade (EV por defecto hasta que hay
   *  historia; ventana 0 = todo el historico); ev_fixed: SIEMPRE se compara
   *  ev_fixed_pct con el fade (el EV medido en IS, para ver OOS). */
  mode?: "ev" | "ev_fixed";
  /** Que medida se enfrenta al fade (17-sep): ev | mfe | fade. */
  metric?: "ev" | "mfe" | "fade";
  ev_fixed_pct?: number;
  ventana: number;
  por: "trades" | "dias";
  ev_defecto_pct: number;
  min_trades: number;
}

/** Hasta que precio compensan los locates (17-sep). */
export interface RawLocatesAnalysis {
  packages: number;
  shorts: number;
  pnl_shorts_pre_locates: number;
  pnl_total_pre_locates: number;
  /** PnL de los cortos antes de locates / paquetes: a ese $ por paquete el portfolio se queda a cero. */
  breakeven_price: number;
  paid: number;
  avg_price_paid: number;
  mean_move_pct: number;
  per_strategy: Array<{ idx: number; name: string; shorts: number; packages: number; pnl_pre_locates: number; breakeven_price: number | null; paid: number }>;
  curve: Array<{ price: number; net_shorts: number; net_total: number }>;
  fade_buckets: Array<{ lo: number; hi: number | null; n: number; move_pct: number; net_mean: number; net_total: number; win_pct: number }> | null;
  fade_rule: Array<{ fade_max_pct: number; taken: number; net_est: number }> | null;
  net_now?: number;
  best_fade_max_pct?: number | null;
}

/** Locates de la CUENTA (un broker para todas). Con este bloque, lo de las
 *  filas se ignora. shared: un alquiler por ticker-dia sobre el maximo en
 *  corto A LA VEZ sumando estrategias (la que cubre libera; la siguiente que
 *  cabe va gratis). */
export interface RawLocatesIn {
  mode: "none" | "fixed" | "random";
  cost: number;
  min: number;
  max: number;
  seed: number;
  shared: boolean;
  gate: RawGateIn | null;
  /** Banda de N semillas sobre los mismos paquetes (solo aleatorios). */
  band_seeds: number;
}

/** Escalado y pesos sobre las corridas en crudo: riesgo TOTAL por trade
 *  (X) repartido entre estrategias (i arriesga X * w_i, sum w = 1); el tope
 *  recorta la SUMA. Los R de las filas se ignoran. */
export interface RawScalingIn {
  model: "fixed" | "percent" | "kelly" | "fixed_ratio";
  base_risk: number;
  pct: number;
  delta: number;
  kelly_mult: number;
  /** per_strategy: la Kelly de cada estrategia, suma topada en proporcion;
   *  global: la Kelly del conjunto repartida por las Kellys propias. */
  kelly_scope?: "per_strategy" | "global";
  cap_pct: number;
  /** Tope POR ESTRATEGIA por trade (% del capital del dia; 0 = sin), antes del de la suma. */
  cap_strategy_pct?: number;
  rebalance: RebalanceFreq;
  lookback_days: number;
  weighting: WeightModel;
  floor: number;
}

export interface RawConfigIn {
  strategy_ids: string[];
  /** Capital del portfolio: base del compound (% por trade), del retorno y
   *  del Monte Carlo. El capital con el que se guardo cada corrida NO interviene. */
  capital: number;
  per_strategy: Record<string, RawExec>;
  default_exec?: RawExec;
  /** Tope de nocional abierto a la vez entre TODAS las estrategias (0 = sin tope). */
  max_exposure_usd: number;
  /** Lo mismo en % del capital DEL DIA; si viene > 0 manda sobre el de $. */
  max_exposure_pct?: number;
  cap_mode: "skip" | "trim";
  /** Solo una estrategia abierta a la vez por accion: entra la primera que da
   *  senal y las demas no entran en ese ticker hasta que sale. */
  one_per_ticker?: boolean;
  /** Tope POR ACCION (19-sep): lo abierto a la vez en un mismo ticker sumando
   *  estrategias, % del equity del dia (0 = sin tope), en riesgo o nocional. */
  max_ticker_pct?: number;
  /** trade = el tope es lo que arriesga UN trade de la estrategia que entra (su Kelly o su % por trade); el numero no se usa. */
  ticker_cap_basis?: "risk" | "notional" | "trade";
  /** Gastos fijos del portfolio (una cuenta); los de las corridas no cuentan. */
  monthly_expenses: number;
  locates?: RawLocatesIn | null;
  scaling?: RawScalingIn | null;
  /** Criterios de margen y buying power del broker (19-sep). Apagado = nada cambia. */
  margin?: { enabled: boolean; broker: string; capacity_pct: number } | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface RawLocatesReport {
  mode: "none" | "fixed" | "random" | "per_row";
  shared: boolean;
  gate: boolean;
  ticker_days: number;
  packages: number;
  cost: number;
  gate_out: number;
  gate_free: number;
}

export interface RawLocatesBand {
  seeds: number;
  seed_actual: number;
  final: { p05: number; p25: number; p50: number; p75: number; p95: number };
  max_dd_pct: { p05: number; p50: number; p95: number };
  cost: { p05: number; p50: number; p95: number };
  bands: { p05: number[]; p50: number[]; p95: number[] };
}

export interface RawScalingPeriod {
  period: string;
  from: string;
  alive: number;
  weights: number[];
  weights_fallback: boolean;
  /** Kelly EXACTA de la ventana (la f que maximiza el log-crecimiento empirico), % del capital por trade. */
  kelly_raw_pct: number | null;
  /** La aproximacion mu/sigma^2, solo para compararla. */
  kelly_quad_pct?: number | null;
  /** Lo que PEDIA el modelo (tras la fraccion de Kelly), % del capital del dia. */
  x_pct: number | null;
  /** Lo APLICADO el primer dia del periodo, tras el tope del usuario. */
  applied_pct?: number | null;
  /** Riesgo por trade aplicado de cada estrategia (% del capital del dia) y su Kelly propia. */
  risk_pct?: number[];
  kelly_por_estrategia_pct?: Array<number | null>;
  note: string | null;
  capped?: boolean;
  /** Ese periodo alguna estrategia pedia mas que el tope por estrategia. */
  capped_strategy?: boolean;
  /** Unidad de la fraccion de cada estrategia: risk (al stop) | capital (en posicion). */
  bases?: Array<"risk" | "capital">;
}

export interface RawScalingToday {
  date: string;
  equity: number;
  window: { from: string; to: string };
  model: RawScalingIn["model"];
  kelly_scope?: "per_strategy" | "global" | null;
  /** Kelly global exacta (solo con kelly_scope = global). */
  kelly_raw_pct: number | null;
  kelly_quad_pct?: number | null;
  kelly_mult: number;
  x_pct: number;
  cap_pct: number;
  applied_pct: number;
  applied_usd: number;
  capped: boolean;
  capped_strategy?: boolean;
  cap_strategy_pct?: number;
  note: string | null;
  weights_fallback: boolean;
  per_strategy: Array<{
    idx: number; name: string; alive: boolean;
    /** Kelly propia exacta (% del capital por trade) y su aproximacion mu/sigma^2. */
    kelly_pct?: number | null; kelly_quad_pct?: number | null;
    /** Lo que pedia (tras la fraccion) y lo aplicado (tras el tope), % del capital del dia. */
    asked_pct?: number; weight: number; risk_pct: number; risk_usd: number;
    /** risk: % del capital al stop; capital: % del capital en posicion (la corrida dimensiono por capital). */
    basis?: "risk" | "capital";
  }>;
}

export interface RawScalingOut {
  cfg: RawScalingIn;
  periods: RawScalingPeriod[];
  today: RawScalingToday;
  no_stop: number;
  no_weight: number;
}

/** Con que se corrio la corrida guardada (para la fila del selector). */
export interface RawConditions {
  init_cash: number;
  risk_type: string;
  risk_r: number;
  fees: number;
  fee_type: string;
  slippage: number;
  locates_cost: number;
  locate_type: string;
  monthly_expenses: number;
  locates_random?: boolean;
  locates_random_min?: number;
  locates_random_max?: number;
  locates_seed?: number;
  size_by_sl: boolean;
  start_date: string | null;
  end_date: string | null;
}

export interface RawCapReport {
  taken: number;
  skipped: number;
  trimmed: number;
  unsized: number;
  /** Senales que no entraron porque otra estrategia ya estaba dentro del ticker. */
  blocked?: number;
  /** Cortos que la puerta por EV dejo fuera / que cabian en lo alquilado (gratis). */
  gate_out?: number;
  gate_free?: number;
  /** Escalado: sin stop (no se puede dimensionar por riesgo) / con peso 0. */
  no_stop?: number;
  no_weight?: number;
  notional_usd?: number;
}

export interface RawPerStrategy {
  strategy_id: string;
  run_id: string;
  name: string;
  alive_from: string | null;
  alive_to: string | null;
  conditions: RawConditions;
  /** La ejecucion con la que se ha calculado (la fijada aqui). */
  exec?: RawExec;
  capital_base?: number;
  pnl_daily: number[];
  trades_daily: number[];
  locates_daily: number[];
  /** Gastos fijos de la propia corrida, el primer dia operado de cada mes vivo. */
  expenses_daily?: number[];
  metrics: CombineMetrics | null;
  totals: {
    pnl_net: number;
    gross?: number;
    expenses?: number;
    n_trades: number;
    win_rate: number;
    profit_factor: number;
    fees: number;
    slippage?: number;
    locates: number;
    avg_notional: number;
    /** Trades sin stop guardado (R = 0) y con stop aproximado (el ultimo, no el inicial). */
    sin_stop?: number;
    stop_aprox?: number;
  };
  cap_report: RawCapReport;
}

export interface RawKelly {
  ok: boolean;
  reason?: string;
  mu_daily_pct?: number[];
  sigma_daily_pct?: number[];
  days?: number[];
  /** Veces el tamano ACTUAL de cada estrategia (1 = dejarla igual). */
  f?: number[];
  f_half?: number[];
  f_quarter?: number[];
  growth_daily_pct_full?: number;
  growth_daily_pct_half?: number;
}

/** Trades aceptados, en columnas (ver portfolio_lab_raw.simulate). */
export interface RawTrades {
  date: string[];
  si: number[];
  ticker: string[];
  dir: string[];
  entry: string[];
  exit: string[];
  entry_px: number[];
  exit_px: number[];
  size: number[];
  notional: number[];
  pnl: number[];
  fees: number[];
  /** Locate cobrado a este trade (tal cual la corrida; 0 si re-dimensionado). */
  locate?: number[];
  /** Fade necesario del corto (% del precio) y sus paquetes de mas. */
  fade?: number[];
  packages?: number[];
  r: number[];
  reason: string[];
}

export interface RawOut {
  config: {
    capital: number;
    default_exec?: RawExec;
    max_exposure_usd: number;
    max_exposure_pct?: number;
    cap_mode: "skip" | "trim";
    one_per_ticker?: boolean;
    max_ticker_pct?: number;
    ticker_cap_basis?: "risk" | "notional" | "trade";
    monthly_expenses: number;
    locates?: RawLocatesIn | null;
    scaling?: RawScalingIn | null;
    start_date: string | null;
    end_date: string | null;
  };
  /** 16-sep: locates de la cuenta, banda y escalado (solo en el backend nuevo). */
  locates_report?: RawLocatesReport;
  locates_band?: RawLocatesBand | null;
  locates_analysis?: RawLocatesAnalysis | null;
  scaling?: RawScalingOut | null;
  ruined?: boolean;
  /** Percentiles del sorteo de locates aleatorios de esta llamada. */
  locates_random?: { n: number; media?: number; p10?: number; p50?: number; p90?: number; min?: number; max?: number } | null;
  calendar: string[];
  equity: number[];
  daily_pnl: number[];
  exposure: {
    peak_daily: number[];
    max_open_daily: number[];
    max_usd: number;
    cap_usd: number;
  };
  cap_report: RawCapReport;
  /** Margen y BP (solo con el bloque activo): trades fuera/recortados por margen y el pico de margen usado. */
  margin_report?: { enabled: boolean; broker: string; capacity_pct: number; skipped: number; trimmed: number; pico_medio_pct: number; pico_max_pct: number } | null;
  /** Tope por accion (solo con el tope > 0): trades fuera/recortados y los sin stop (en riesgo no se pueden medir). */
  ticker_cap_report?: { pct: number; basis: "risk" | "notional" | "trade"; skipped: number; trimmed: number; sin_stop: number } | null;
  metrics: CombineMetrics;
  costs: { fees: number; slippage?: number; locates: number; expenses: number };
  var: CombineVar | null;
  correlation: CombineCorrelation | null;
  kelly: RawKelly | null;
  per_strategy: RawPerStrategy[];
  trades_seq: { dates: string[]; strategy_idx: number[]; pnl_net: number[] };
  trades: RawTrades;
}

export function runPortfolioRaw(body: RawConfigIn): Promise<RawOut> {
  return apiRequest<RawOut>("/portfolio-lab/raw", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
}
