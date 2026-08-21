"use client";

/**
 * Billing API client (Fase 2F). Mirrors the backend app/billing surface.
 *
 * Dormant like the backend: BILLING_ENABLED (NEXT_PUBLIC_BILLING_ENABLED) gates
 * whether the billing UI is shown at all. Off by default → the billing section
 * and paywall are not rendered and these endpoints (which the backend only
 * mounts when its own BILLING_ENABLED is on) are never called. Flip both flags
 * together at cutover (Fase 2G).
 */
import { apiRequest } from "@/lib/api";

export const BILLING_ENABLED =
  process.env.NEXT_PUBLIC_BILLING_ENABLED === "true";

export interface BillingPlan {
  label: string;
  amount_cents: number;
  currency: string;
  interval: string;
}

export interface BillingSubscription {
  status: string; // trialing|active|past_due|canceled|unpaid|incomplete|incomplete_expired
  price_id: string | null;
  currency: string | null;
  trial_end: number | null;
  current_period_end: number | null;
  cancel_at_period_end: boolean;
  canceled_at: number | null;
}

export interface BillingGrant {
  grant_tier: string;
  reason: string | null;
  expires_at: number | null;
}

export interface BillingPaymentMethod {
  brand: string | null;
  last4: string | null;
  exp_month: number | null;
  exp_year: number | null;
}

export interface BillingInvoice {
  status: string; // paid|open|void|uncollectible|draft
  amount_due: number | null;
  amount_paid: number | null;
  currency: string | null;
  hosted_invoice_url: string | null;
  invoice_pdf: string | null;
  period_start: number | null;
  period_end: number | null;
  created_at: number;
}

// Server-computed screen selector (Fase 3). 1:1 with a UI state; the client
// never guesses new-vs-returning from partial signals.
export type BillingStage =
  | "admin"
  | "trialing"
  | "active"
  | "past_due"
  | "trial_grant"
  | "resubscribe" // returning user (baja→vuelve): re-subscribe, no trial
  | "onboarding"; // new user / REGISTRADO_SIN_TARJETA: add card to start trial

export interface BillingSummary {
  tier: string;
  access: boolean;
  stage: BillingStage;
  plan: BillingPlan;
  subscription: BillingSubscription | null;
  grant: BillingGrant | null;
  payment_method: BillingPaymentMethod | null;
  invoices: BillingInvoice[];
}

export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

export const billingApi = {
  me: () => apiRequest<BillingSummary>("/billing/me"),

  checkout: (body: { success_url?: string; cancel_url?: string; email?: string }) =>
    apiRequest<CheckoutResponse>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  portal: (body: { return_url?: string }) =>
    apiRequest<{ portal_url: string }>("/billing/portal", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  sync: (session_id: string) =>
    apiRequest<{ synced: boolean; status: string | null }>("/billing/checkout/sync", {
      method: "POST",
      body: JSON.stringify({ session_id }),
    }),
};

// ─── Formatting helpers (shared by the billing UI) ──────────────────────────

/** cents (e.g. 2900) → "29,00 €" for the given currency. */
export function formatMoney(cents: number | null, currency: string | null): string {
  if (cents == null) return "—";
  try {
    return new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency: (currency || "eur").toUpperCase(),
    }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(2)} €`;
  }
}

/** epoch seconds → "14 sept 2026". */
export function formatDate(epochSeconds: number | null): string {
  if (epochSeconds == null) return "—";
  try {
    return new Intl.DateTimeFormat("es-ES", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(epochSeconds * 1000));
  } catch {
    return "—";
  }
}

/** Whole days remaining until an epoch-seconds deadline (0 if past/absent). */
export function daysUntil(epochSeconds: number | null): number {
  if (epochSeconds == null) return 0;
  const ms = epochSeconds * 1000 - Date.now();
  if (ms <= 0) return 0;
  return Math.ceil(ms / 86_400_000);
}
