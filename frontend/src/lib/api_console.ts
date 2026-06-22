// Client for the developer console (control plane). Clerk-authed, talks to
// /api/console/* on the backend. Reuses the shared API base + Clerk auth headers.
import { API_BASE, getAuthHeaders } from "./api";

const CONSOLE_BASE = `${API_BASE}/console`;

export interface PlanInfo {
  name: string;
  limits: { max_ticker_days_per_run: number; rate_limit_rpm: number };
  price: number | null;
}

export interface KeyInfo {
  id: string;
  prefix: string;
  label: string | null;
  status: "active" | "revoked";
  is_test: boolean;
  plan: string;
  created_at: number;
  last_used_at: number | null;
}

export interface Activity {
  module: string;
  action: string;
  ticker_days: number;
  trades: number;
  ts: number;
  key_prefix: string;
}

export interface OnboardingStep {
  id: string;
  label: string;
  done: boolean;
}

export interface Overview {
  owner_id: string;
  plan: PlanInfo;
  usage_period: { label: string; since: number; runs: number; ticker_days: number; trades: number };
  keys: { total: number; active: number };
  activity: Activity[];
  onboarding: OnboardingStep[];
  docs_url: string;
}

export interface UsageReport {
  this_month: { label: string; runs: number; ticker_days: number; trades: number };
  all_time: { label: string; runs: number; ticker_days: number; trades: number };
  activity: Activity[];
}

export interface Billing {
  plan: PlanInfo;
  usage_this_month: { runs: number; ticker_days: number; trades: number };
  invoices: unknown[];
  stripe: { connected: boolean; note: string };
  upgrade_url: string | null;
}

export interface CreatedKey {
  key: KeyInfo;
  token: string;
  token_shown_once: boolean;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${CONSOLE_BASE}${path}`, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } });
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const d = await res.json();
      detail = typeof d?.detail === "string" ? d.detail : detail;
    } catch {
      /* keep generic */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const consoleApi = {
  overview: () => req<Overview>("/overview"),
  listKeys: () => req<{ keys: KeyInfo[] }>("/keys"),
  createKey: (label: string | null, test: boolean) =>
    req<CreatedKey>("/keys", { method: "POST", body: JSON.stringify({ label, test }) }),
  revokeKey: (id: string) => req<{ ok: boolean }>(`/keys/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  usage: () => req<UsageReport>("/usage"),
  billing: () => req<Billing>("/billing"),
  playgroundIndicators: (category?: string) =>
    req<{ indicators: Array<{ name: string; category: string; params: string[] }> }>(
      `/playground/indicators${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),
  playgroundValidate: (strategy: unknown) =>
    req<{ valid: boolean; errors: Array<{ path: string; message: string }> }>("/playground/validate", {
      method: "POST",
      body: JSON.stringify({ strategy }),
    }),
};
