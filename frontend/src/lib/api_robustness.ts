/**
 * Typed client for the Robustness module (docs/robustez/PRD_ROBUSTEZ.md §3).
 * Reuses the core request helper, base URL and Clerk auth from ./api.
 */
import { apiRequest } from "./api";

export interface CurvePoint {
  time: number;
  value: number;
}

// ─── Module 1 — Monte Carlo ──────────────────────────────────
export interface MontecarloRequest {
  run_id: string;
  init_cash?: number;
  simulations?: number;
  ruin_pct?: number;
  n_trades_limit?: number;
  period_unit?: "mes" | "trimestre" | "año" | null;
}

export interface MontecarloResponse {
  simulations_run: number;
  ruin_probability: number;
  worst_drawdown: number;
  median_drawdown: number;
  extreme_drawdown_p95: number;
  extreme_drawdown_p99: number;
  probability_negative_return: number;
  n_trades_calculated: number;
  percentiles: Record<string, CurvePoint[]>;
}

// ─── Module 3 — Sensitivity ──────────────────────────────────
export interface SensitivityRequest {
  run_id: string;
  locate_range?: { min: number; max: number; step: number };
  slippage_probability?: number;
  slippage_value?: number;
  init_cash?: number;
}

export interface SensitivityResponse {
  critical_locate_threshold: number | null;
  curves: Record<string, CurvePoint[]>;
}

// ─── Module 4 — Black Swan ───────────────────────────────────
export interface BlackSwanRequest {
  run_id: string;
  init_cash?: number;
  black_swan_count?: number;
  severity_multiplier?: number;
  ruin_pct?: number;
}

export interface BlackSwanCell {
  position_size_pct: number;
  severity_multiplier: number;
  ruin_probability: number;
  max_drawdown: number;
  zone: "GREEN" | "YELLOW" | "RED";
}

export interface BlackSwanResponse {
  time_to_recovery_trades: number;
  post_swan_ruin_risk_100t: number;
  sensitivity_matrix: BlackSwanCell[];
}

// ─── Module 2 — Walk-Forward ─────────────────────────────────
export interface WfoParamConfig {
  id: string;
  path: string;
  min?: number;
  max?: number;
  steps?: number;
  values?: number[];
}

export interface WalkForwardRequest {
  run_id: string;
  dataset_id: string;
  is_pct?: number;
  oos_pct?: number;
  step_pct?: number;
  metric?: string;
  init_cash?: number;
  param_configs?: WfoParamConfig[];
}

export interface WalkForwardResult {
  status: "completed" | "running" | "error";
  progress: number;
  wfe?: number;
  win_rate_penalty?: number;
  oos_max_drawdown?: number;
  is_metrics?: Record<string, number>;
  oos_metrics?: Record<string, number>;
  heatmap_matrix?: { parameters: string[]; data: { values: number[]; is_score: number }[] };
  windows?: number;
  code?: string;
  message?: string;
}

// ─── Calls ───────────────────────────────────────────────────
export function postMontecarlo(req: MontecarloRequest): Promise<MontecarloResponse> {
  return apiRequest<MontecarloResponse>("/robustness/montecarlo", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function postSensitivity(req: SensitivityRequest): Promise<SensitivityResponse> {
  return apiRequest<SensitivityResponse>("/robustness/sensitivity", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function postBlackSwan(req: BlackSwanRequest): Promise<BlackSwanResponse> {
  return apiRequest<BlackSwanResponse>("/robustness/black-swan", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function startWalkForward(
  req: WalkForwardRequest,
): Promise<{ task_id: string; status: string; progress: number }> {
  return apiRequest("/robustness/walk-forward", {
    method: "POST",
    body: JSON.stringify(req),
    // WFO is heavy; give the enqueue call room although it returns immediately.
    timeoutMs: 30_000,
  });
}

export function getWalkForwardProgress(taskId: string): Promise<{ progress: number }> {
  return apiRequest(`/robustness/walk-forward/progress/${encodeURIComponent(taskId)}`);
}

export function getWalkForwardResult(taskId: string): Promise<WalkForwardResult> {
  return apiRequest(`/robustness/walk-forward/result/${encodeURIComponent(taskId)}`);
}
