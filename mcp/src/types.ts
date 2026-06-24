/** Public API DTOs (subset). The full, authoritative types are emitted by the
 *  `generate_api_client` tool from the live OpenAPI; these mirror them for the
 *  MCP's own typed client. */

export interface EquityPoint {
  time: number;
  value: number;
}

export interface AggregateMetrics {
  [key: string]: number | null;
}

export interface Trade {
  ticker: string;
  date: string;
  entry_time?: string;
  exit_time?: string;
  entry_price?: number;
  exit_price?: number;
  pnl?: number;
  return_pct?: number;
  direction?: string;
  exit_reason?: string;
  r_multiple?: number | null;
  [key: string]: unknown;
}

export interface TradesPage {
  items: Trade[];
  page: { limit: number; returned: number; total: number; next_cursor: string | null };
  export_url?: string | null;
}

export interface DayResult {
  ticker: string;
  date: string;
  [key: string]: unknown;
}

export interface BacktestResult {
  aggregate_metrics?: AggregateMetrics;
  global_equity?: EquityPoint[];
  global_drawdown?: EquityPoint[];
  day_results?: DayResult[];
  trades?: TradesPage;
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  meta?: Record<string, unknown>;
  result?: BacktestResult;
}

export interface UniversePreview {
  ticker_days: number;
  tickers: number;
  within_cap: boolean;
  cap: number;
}

export interface StrategyValidation {
  valid: boolean;
  errors: Array<{ path: string; message: string }>;
}

export interface IndicatorCatalogEntry {
  name: string;
  category: string;
  params: string[];
}
