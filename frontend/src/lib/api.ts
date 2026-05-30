import { Strategy } from "@/types/strategy";
import type {
  BacktestRequest,
  BacktestResponse,
  BacktestResult,
} from "@/types/backtest";

// ─── Base URL ───────────────────────────────────────────────
const RAW_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8010/api";

const API_BASE = (() => {
  const trimmed = RAW_BASE.replace(/\/+$/, "");
  return trimmed.endsWith("/api") ? trimmed : `${trimmed}/api`;
})();

// ─── Centralized error class ─────────────────────────────────
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ─── Core request helper ────────────────────────────────────
async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`;

  const hasBody = !!options?.body;
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
        ...(options?.headers as Record<string, string> || {}),
      },
    });
  } catch (error) {
    throw new ApiError(0, "No se pudo conectar con el backend", error);
  }

  // 204 No Content → return null-ish
  if (response.status === 204) return undefined as unknown as T;

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in (data as Record<string, unknown>)
        ? (data as Record<string, unknown>).detail
        : data;
    const msg =
      typeof detail === "string"
        ? detail
        : `HTTP ${response.status}: ${response.statusText}`;
    throw new ApiError(response.status, msg, detail);
  }

  return data as T;
}

// ─── Strategies ─────────────────────────────────────────────
export function getStrategies(): Promise<Strategy[]> {
  return apiRequest<Strategy[]>("/strategies/");
}

export function getStrategy(id: string): Promise<Strategy> {
  return apiRequest<Strategy>(`/strategies/${encodeURIComponent(id)}`);
}

export function createStrategy(
  data: Strategy,
): Promise<Strategy> {
  return apiRequest<Strategy>("/strategies/", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deleteStrategy(id: string): Promise<void> {
  return apiRequest<void>(`/strategies/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

// ─── Queries (Datasets) ─────────────────────────────────────
export interface SavedQuery {
  id: string;
  name: string;
  filters: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export function getQueries(): Promise<SavedQuery[]> {
  return apiRequest<SavedQuery[]>("/queries/");
}

export function createQuery(
  data: { name: string; filters: Record<string, unknown> },
): Promise<SavedQuery> {
  return apiRequest<SavedQuery>("/queries/", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deleteQuery(id: string): Promise<void> {
  return apiRequest<void>(`/queries/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

// ─── Strategy Search ────────────────────────────────────────
export function searchStrategies(params: {
  search_mode: string;
  search_space: string;
  dataset_id: string;
  date_from: string;
  date_to: string;
  pass_criteria: Record<string, number | null>;
}): Promise<{ strategies: unknown[] }> {
  return apiRequest<{ strategies: unknown[] }>(
    "/strategy-search/filter",
    {
      method: "POST",
      body: JSON.stringify(params),
    },
  );
}

export function exportStrategies(
  ids: string[],
): Promise<{ csv_data: string[][]; filename: string }> {
  return apiRequest<{ csv_data: string[][]; filename: string }>(
    "/strategy-search/export",
    {
      method: "POST",
      body: JSON.stringify(ids),
    },
  );
}

// ─── Backtest ───────────────────────────────────────────────
export function runBacktest(
  data: BacktestRequest,
): Promise<BacktestResponse> {
  return apiRequest<BacktestResponse>("/backtest/run", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getBacktestStatus(
  runId: string,
): Promise<BacktestResponse> {
  return apiRequest<BacktestResponse>(
    `/backtest/status/${encodeURIComponent(runId)}`,
  );
}

export function getBacktestResults(
  runId: string,
): Promise<BacktestResult> {
  return apiRequest<BacktestResult>(
    `/backtest/results/${encodeURIComponent(runId)}`,
  );
}

// ─── Ticker Analysis ────────────────────────────────────────
export function getTickerAnalysis(
  ticker: string,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/ticker-analysis/${encodeURIComponent(ticker)}`,
  );
}

export function getTickerSecFilings(
  ticker: string,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/ticker-analysis/${encodeURIComponent(ticker)}/sec-filings`,
  );
}

export function getTickerChart(
  ticker: string,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/ticker-analysis/${encodeURIComponent(ticker)}/chart`,
  );
}

export function getTickerBalanceSheet(
  ticker: string,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/ticker-analysis/${encodeURIComponent(ticker)}/balance-sheet`,
  );
}

export function getTickerGapStats(
  ticker: string,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/ticker-analysis/${encodeURIComponent(ticker)}/gap-stats`,
  );
}

export function getTickerFinvizNews(
  ticker: string,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/ticker-analysis/${encodeURIComponent(ticker)}/finviz-news`,
  );
}


// ─── Market Data ────────────────────────────────────────────
export function getScreener(
  params: URLSearchParams | string,
  signal?: AbortSignal,
): Promise<unknown> {
  const qs = typeof params === "string" ? params : params.toString();
  return apiRequest<unknown>(`/market/screener?${qs}`, { signal });
}

export function getAggregateIntraday(
  params: URLSearchParams | string,
  signal?: AbortSignal,
): Promise<unknown> {
  const qs = typeof params === "string" ? params : params.toString();
  return apiRequest<unknown>(`/market/aggregate/intraday?${qs}`, { signal });
}

export function getMarketNews(): Promise<unknown> {
  return apiRequest<unknown>("/market/news");
}

export function getTickerIntraday(
  ticker: string,
  tradeDate?: string,
): Promise<unknown> {
  const base = `/market/ticker/${encodeURIComponent(ticker)}/intraday`;
  const url = tradeDate ? `${base}?trade_date=${encodeURIComponent(tradeDate)}` : base;
  return apiRequest<unknown>(url);
}

export function getMetricsHistory(
  ticker: string,
  limit = 1000,
): Promise<unknown> {
  return apiRequest<unknown>(
    `/market/ticker/${encodeURIComponent(ticker)}/metrics_history?limit=${limit}`,
  );
}

// ─── Historical Data ────────────────────────────────────────
export function getHistoricalData(params: {
  ticker: string;
  date_from: string;
  date_to: string;
  indicators?: string;
}): Promise<unknown> {
  const { ticker, date_from, date_to, indicators } = params;
  let url = `/data/historical?ticker=${encodeURIComponent(ticker)}&date_from=${encodeURIComponent(date_from)}&date_to=${encodeURIComponent(date_to)}`;
  if (indicators) url += `&indicators=${encodeURIComponent(indicators)}`;
  return apiRequest<unknown>(url);
}

// ─── Export ─────────────────────────────────────────────────
export function exportData(filters: unknown): Promise<Blob> {
  const url = `${API_BASE}/export`;
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  }).then((r) => {
    if (!r.ok) throw new ApiError(r.status, "Export failed");
    return r.blob();
  });
}
