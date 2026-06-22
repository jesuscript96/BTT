/** Typed HTTP client for the Edgecute Backtest API.
 *
 *  - Bearer API key from env.
 *  - Exponential backoff on 429/5xx.
 *  - Translates the API's error envelope into EdgecuteApiError; NEVER surfaces
 *    a raw body/stack.
 */
import type {
  IndicatorCatalogEntry,
  JobStatus,
  StrategyValidation,
  UniversePreview,
} from "./types.js";

export class EdgecuteApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: unknown,
  ) {
    super(message);
    this.name = "EdgecuteApiError";
  }
}

export interface ClientOptions {
  apiBase: string;
  apiKey?: string | undefined;
  fetchImpl?: typeof fetch;
  maxRetries?: number;
  retryBaseMs?: number;
  sleepImpl?: (ms: number) => Promise<void>;
}

const RETRYABLE = new Set([429, 500, 502, 503, 504]);

function defaultSleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export class EdgecuteClient {
  private readonly apiBase: string;
  private readonly apiKey: string | undefined;
  private readonly fetchImpl: typeof fetch;
  private readonly maxRetries: number;
  private readonly retryBaseMs: number;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(opts: ClientOptions) {
    this.apiBase = opts.apiBase.replace(/\/+$/, "");
    this.apiKey = opts.apiKey;
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.maxRetries = opts.maxRetries ?? 3;
    this.retryBaseMs = opts.retryBaseMs ?? 400;
    this.sleep = opts.sleepImpl ?? defaultSleep;
  }

  hasKey(): boolean {
    return Boolean(this.apiKey);
  }

  isTestKey(): boolean {
    return Boolean(this.apiKey?.startsWith("ek_test_"));
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    if (!this.apiKey) {
      throw new EdgecuteApiError(
        "unauthorized",
        "Falta EDGECUTE_API_KEY en el entorno del MCP.",
        401,
      );
    }
    const url = `${this.apiBase}${path}`;
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
    };

    let attempt = 0;
    // One initial try + up to maxRetries retries on transient failures.
    for (;;) {
      let res: Response;
      try {
        res = await this.fetchImpl(url, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (err) {
        if (attempt < this.maxRetries) {
          await this.sleep(this.retryBaseMs * 2 ** attempt);
          attempt++;
          continue;
        }
        throw new EdgecuteApiError("network_error", "No se pudo contactar con la API.", 0);
      }

      if (res.ok) {
        return (await res.json()) as T;
      }

      if (RETRYABLE.has(res.status) && attempt < this.maxRetries) {
        await this.sleep(this.retryBaseMs * 2 ** attempt);
        attempt++;
        continue;
      }

      // Parse the structured error envelope without leaking raw text.
      let code = "api_error";
      let message = `Error ${res.status}`;
      let details: unknown;
      try {
        const data = (await res.json()) as { error?: { code?: string; message?: string; details?: unknown } };
        if (data?.error) {
          code = data.error.code ?? code;
          message = data.error.message ?? message;
          details = data.error.details;
        }
      } catch {
        /* keep generic message */
      }
      throw new EdgecuteApiError(code, message, res.status, details);
    }
  }

  // ── Endpoints ──────────────────────────────────────────────────────────────
  health(): Promise<{ status: string }> {
    return this.request("GET", "/health");
  }

  listIndicators(category?: string): Promise<{ indicators: IndicatorCatalogEntry[] }> {
    const q = category ? `?category=${encodeURIComponent(category)}` : "";
    return this.request("GET", `/catalog/indicators${q}`);
  }

  validateStrategy(strategy: unknown): Promise<StrategyValidation> {
    return this.request("POST", "/strategies/validate", strategy);
  }

  previewUniverse(spec: unknown): Promise<UniversePreview> {
    return this.request("POST", "/universe/preview", spec);
  }

  runBacktest(body: unknown): Promise<JobStatus> {
    return this.request("POST", "/backtests", body);
  }

  getBacktest(jobId: string): Promise<JobStatus> {
    return this.request("GET", `/backtests/${encodeURIComponent(jobId)}`);
  }

  fetchOpenApi(): Promise<unknown> {
    return this.request("GET", "/openapi.json");
  }
}
