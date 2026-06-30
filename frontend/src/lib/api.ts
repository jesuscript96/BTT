import { Strategy } from "@/types/strategy";
import type {
  BacktestRequest,
  BacktestResponse,
  BacktestResult,
} from "@/types/backtest";
import { clearDatasetsCache } from "./api_backtester";
import { track, EVENTS } from "./analytics";

// ─── Base URL ───────────────────────────────────────────────
const RAW_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8010/api";

export const API_BASE = (() => {
  const trimmed = RAW_BASE.replace(/\/+$/, "");
  return trimmed.endsWith("/api") ? trimmed : `${trimmed}/api`;
})();

// ─── Auth headers (Clerk) ───────────────────────────────────
// Reads the active Clerk session token from the global Clerk instance (set by
// ClerkProvider) and returns it as a Bearer header. Safe on the server / before
// Clerk loads: returns no Authorization header so public calls still work.
export async function getClerkToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  try {
    const clerk = (window as unknown as {
      Clerk?: { session?: { getToken: () => Promise<string | null> } };
    }).Clerk;
    const token = await clerk?.session?.getToken?.();
    return token ?? null;
  } catch {
    return null;
  }
}

export async function getAuthHeaders(): Promise<HeadersInit> {
  const token = await getClerkToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

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

// Format a FastAPI/pydantic error detail into a readable string.
// Pydantic returns an array of {loc, msg, type}; FastAPI's HTTPException returns a string.
function formatErrorDetail(detail: unknown, status: number, statusText: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const seen = new Set<string>();
    const fieldErrors: string[] = [];
    for (const e of detail) {
      if (!e || typeof e !== "object") continue;
      const item = e as { loc?: unknown[]; msg?: string };
      const msg = item.msg || "invalid";
      // Skip union-discriminator failures (Pydantic reports them for every untaken variant).
      if (/^Input should be '[a-z_]+'$/.test(msg)) continue;
      // Drop the union-variant tags from loc (e.g., "ConditionGroup" / "ComparisonCondition").
      const loc = (item.loc || []).filter(
        (p): p is string | number =>
          (typeof p === "string" || typeof p === "number") &&
          !(typeof p === "string" && /^[A-Z][a-zA-Z]+$/.test(p)),
      );
      // Drop the leading "body" segment if present.
      const path =
        loc[0] === "body" ? loc.slice(1).join(".") : loc.join(".");
      const key = `${path}::${msg}`;
      if (seen.has(key)) continue;
      seen.add(key);
      fieldErrors.push(path ? `${path}: ${msg}` : msg);
    }
    if (fieldErrors.length > 0) {
      return fieldErrors.slice(0, 5).join(" · ");
    }
  }
  return `HTTP ${status}${statusText ? `: ${statusText}` : ""}`;
}

// ─── Core request helper ────────────────────────────────────
export async function apiRequest<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const timeoutMs = options?.timeoutMs ?? 20_000; // Default 20s timeout

  const hasBody = !!options?.body;
  const token = await getClerkToken();
  let response: Response;
  try {
    // Wire up AbortController for timeout (skip if caller already provided a signal)
    const controller = new AbortController();
    const existingSignal = options?.signal;
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    // If caller already provided a signal, abort our controller when theirs fires
    if (existingSignal) {
      existingSignal.addEventListener("abort", () => controller.abort());
    }

    try {
      response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          ...(hasBody ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(options?.headers as Record<string, string> || {}),
        },
      });
    } finally {
      clearTimeout(timer);
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, `Request timed out after ${timeoutMs / 1000}s: ${path}`);
    }
    throw new ApiError(0, "No se pudo conectar con el backend", error);
  }

  // 401 Unauthorized → session expired or missing; bounce to sign-in.
  if (response.status === 401 && typeof window !== "undefined") {
    if (!window.location.pathname.startsWith("/sign-in")) {
      window.location.href = "/sign-in";
    }
    throw new ApiError(401, "Sesión expirada. Inicia sesión de nuevo.");
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
    const msg = formatErrorDetail(detail, response.status, response.statusText);
    throw new ApiError(response.status, msg, detail);
  }

  return data as T;
}

// ─── Ticker Logo ────────────────────────────────────────────
export interface TickerLogoData {
  ticker: string;
  logo_data_url: string | null;
  google_favicon_url: string;
  domain: string;
  source: "massive" | "google" | "none";
}

export function getTickerLogo(ticker: string): Promise<TickerLogoData> {
  return apiRequest<TickerLogoData>(`/ticker-analysis/${encodeURIComponent(ticker)}/logo`);
}

// ─── Strategies ─────────────────────────────────────────────
export function getStrategies(): Promise<Strategy[]> {
  return apiRequest<Strategy[]>(`/strategies/?t=${Date.now()}`);
}

export function getStrategy(id: string): Promise<Strategy> {
  return apiRequest<Strategy>(`/strategies/${encodeURIComponent(id)}`);
}

export async function createStrategy(
  data: Strategy,
): Promise<Strategy> {
  const res = await apiRequest<Strategy>("/strategies/", {
    method: "POST",
    body: JSON.stringify(data),
  });
  track(EVENTS.STRATEGY_CREATED, { name: data.name });
  return res;
}

export function updateStrategy(
  id: string,
  data: Strategy,
): Promise<Strategy> {
  return apiRequest<Strategy>(`/strategies/${encodeURIComponent(id)}`, {
    method: "PUT",
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
  return apiRequest<SavedQuery[]>(`/queries/?t=${Date.now()}`);
}

export async function createQuery(
  data: { name: string; filters: Record<string, unknown> },
): Promise<SavedQuery> {
  const res = await apiRequest<SavedQuery>("/queries/", {
    method: "POST",
    body: JSON.stringify(data),
    timeoutMs: 300_000, // dataset_pairs insert + GCS upload can take minutes in prod
  });
  clearDatasetsCache();
  track(EVENTS.DATASET_CREATED, { name: data.name });
  return res;
}

export async function deleteQuery(id: string): Promise<void> {
  const res = await apiRequest<void>(`/queries/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  clearDatasetsCache();
  return res;
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
  track(EVENTS.STRATEGY_SEARCH_RUN, {
    mode: params.search_mode,
    space: params.search_space,
  });
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

export function getSavedBacktests(limit = 100): Promise<{ strategies: any[]; total_count: number }> {
  return apiRequest<{ strategies: any[]; total_count: number }>(`/strategy-search/list?limit=${limit}`);
}

export function saveBacktest(data: {
  strategy_ids: string[];
  results_json: Record<string, unknown>;
}): Promise<{ id: string; status: string }> {
  return apiRequest<{ id: string; status: string }>("/strategy-search/", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function toggleBacktestValidation(
  backtestId: string,
): Promise<{ status: string; is_validated: boolean }> {
  return apiRequest<{ status: string; is_validated: boolean }>(
    `/strategy-search/${encodeURIComponent(backtestId)}/toggle-validation`,
    {
      method: "POST",
    },
  );
}


// ─── Backtest ───────────────────────────────────────────────
export async function runBacktest(
  data: BacktestRequest,
): Promise<BacktestResponse> {
  const n = (data as { strategy_ids?: unknown[] }).strategy_ids?.length;
  track(EVENTS.BACKTEST_RUN, { strategies: n });
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
  track(EVENTS.TICKER_ANALYSIS_OPENED, { ticker });
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

// Transacciones de insiders (SEC Forms 3/4/5). Alimenta el informe de dilución
// de Edgie para que nombre a los directivos sin inventar.
export interface InsiderTransaction {
  name: string;
  role: string;
  form_type: string;
  date: string | null;
  code: string | null;
  code_label: string | null;
  shares: number | null;
  price: number | null;
  acquired_disposed: string | null;
}

export function getTickerInsiders(
  ticker: string,
): Promise<{ ticker: string; insiders: InsiderTransaction[] }> {
  return apiRequest<{ ticker: string; insiders: InsiderTransaction[] }>(
    `/ticker-analysis/${encodeURIComponent(ticker)}/insiders`,
  );
}


// ─── Social (Stocktwits) ────────────────────────────────────
// Todas estas llamadas pegan al backend (/api/market/social/*), que cachea con
// SWR y sanea el payload. El frontend nunca ve credenciales de Stocktwits.

export interface SocialTrendingItem {
  symbol: string;
  name: string;
  market_cap: number | null;
  daily_volume: number | null;
  trending_score: number | null;
  sentiment_score: number | null;
  price: number | null;
  change_pct: number | null;
}

export interface SocialSummary {
  symbol: string;
  why_trending: string | null;
  updated_at: string;
}

export interface SocialSentiment {
  symbol: string;
  sentiment_score: number;
  sentiment_label: "Bullish" | "Bearish" | "Neutral";
  message_volume_score: number;
  message_volume_label: "High" | "Medium" | "Low";
  updated_at: string;
}

export interface SocialStreamMessage {
  message_id: number | null;
  body: string;
  created_at: string;
  username: string;
  avatar_url: string;
  user_sentiment: "Bullish" | "Bearish" | null;
  likes_count: number;
}

export interface SocialNewsletterItem {
  title: string;
  published_at: string;
  author: string;
  content_html: string;
  charts: string[];
  link: string;
}

export function getSocialTrending(): Promise<SocialTrendingItem[]> {
  return apiRequest<SocialTrendingItem[]>("/market/social/trending");
}

export function getSocialSummary(symbol: string): Promise<SocialSummary> {
  return apiRequest<SocialSummary>(
    `/market/social/ticker/${encodeURIComponent(symbol)}/summary`,
  );
}

export function getSocialSentiment(symbol: string): Promise<SocialSentiment> {
  return apiRequest<SocialSentiment>(
    `/market/social/ticker/${encodeURIComponent(symbol)}/sentiment`,
  );
}

export function getSocialStream(
  symbol: string,
  limit = 15,
): Promise<SocialStreamMessage[]> {
  return apiRequest<SocialStreamMessage[]>(
    `/market/social/ticker/${encodeURIComponent(symbol)}/stream?limit=${limit}`,
  );
}

export function getSocialNewsletter(): Promise<SocialNewsletterItem[]> {
  return apiRequest<SocialNewsletterItem[]>("/market/social/newsletter");
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

// ─── Screener ───────────────────────────────────────────────
export interface ScreenerRecord {
  ticker: string;
  name: string;
  price: number;
  change_pct: number;
  return_pct: number;
  gap_pct: number;
  volume: number;
  prev_close: number;
  open: number;
  high: number;
  low: number;
  prev_volume: number;
  high_spike_pct: number;
  low_spike_pct: number;
  range_pct: number;
}

export interface ScreenerDailyResponse {
  date: string | null;
  total_records: number;
  gainers: ScreenerRecord[];
  losers: ScreenerRecord[];
  premarket: ScreenerRecord[];
  aftermarket: ScreenerRecord[];
}

export function getScreenerDaily(limit = 100): Promise<ScreenerDailyResponse> {
  return apiRequest<ScreenerDailyResponse>(
    `/screener/daily?limit=${limit}`,
    { timeoutMs: 60_000 },
  );
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
