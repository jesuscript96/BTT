/**
 * Portfolio module API client. Mirrors backend/app/routers/portfolio.py.
 * See docs/portfolio/03_CONTRATO_DATOS.md.
 */
import { apiRequest } from "./api";

export interface PortfolioMetrics {
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  volatility_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  n_days: number;
  /** Metrics is a numeric bag; extra keys may appear depending on the model. */
  [key: string]: number;
}

export interface CombineResponse {
  timestamps: number[];
  combined_equity: number[];
  combined_drawdown: number[];
  metrics: PortfolioMetrics;
  weights: Record<string, number>;
}

export interface MontecarloResponse {
  percentiles: Record<string, number[]>;
  var_95_pct: number;
  var_95_usd: number;
  var_99_pct: number;
  var_99_usd: number;
  cvar_95_pct: number;
  cvar_95_usd: number;
  cvar_99_pct: number;
  cvar_99_usd: number;
  ruin_probability: number;
}

export interface CorrelationResponse {
  labels: string[];
  pearson: number[][];
  spearman: number[][];
}

export interface AllocationResponse {
  weights: Record<string, number>;
  comparison_equity: number[];
  comparison_drawdown: number[];
  metrics: PortfolioMetrics;
}

export interface ScalingResponse {
  equity: number[];
  drawdown: number[];
  metrics: PortfolioMetrics;
}

const post = <T>(path: string, body: unknown): Promise<T> =>
  apiRequest<T>(path, { method: "POST", body: JSON.stringify(body) });

export function combinePortfolio(
  backtestIds: string[],
  weights?: Record<string, number> | null,
  initCash = 10000,
): Promise<CombineResponse> {
  return post<CombineResponse>("/portfolio/combine", {
    backtest_ids: backtestIds,
    weights: weights ?? null,
    init_cash: initCash,
  });
}

export function runMontecarlo(
  backtestIds: string[],
  weights: Record<string, number> | null,
  simulations: number,
  initCash: number,
): Promise<MontecarloResponse> {
  return post<MontecarloResponse>("/portfolio/montecarlo", {
    backtest_ids: backtestIds,
    weights,
    simulations,
    init_cash: initCash,
  });
}

export function getCorrelation(backtestIds: string[]): Promise<CorrelationResponse> {
  return post<CorrelationResponse>("/portfolio/correlation", { backtest_ids: backtestIds });
}

export function getAllocation(
  backtestIds: string[],
  method: "leaders" | "hrp",
  lookbackDays = 15,
  leadersWeights?: number[] | null,
  initCash = 10000,
): Promise<AllocationResponse> {
  return post<AllocationResponse>("/portfolio/allocation", {
    backtest_ids: backtestIds,
    method,
    lookback_days: lookbackDays,
    leaders_weights: leadersWeights ?? null,
    init_cash: initCash,
  });
}

export function runScaling(
  backtestIds: string[],
  weights: Record<string, number> | null,
  mode: "kelly" | "fixed_pct" | "drawdown_stop",
  opts: { initCash?: number; kellyFraction?: number; fixedPct?: number; ddStopPct?: number } = {},
): Promise<ScalingResponse> {
  return post<ScalingResponse>("/portfolio/scaling", {
    backtest_ids: backtestIds,
    weights,
    mode,
    init_cash: opts.initCash ?? 10000,
    kelly_fraction: opts.kellyFraction ?? 0.5,
    fixed_pct: opts.fixedPct ?? null,
    dd_stop_pct: opts.ddStopPct ?? -20,
  });
}
