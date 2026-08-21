"use client";

/**
 * Onboarding / access gate (Fase 3).
 *
 * The card is required at the FIRST login, not from inside a browsable panel.
 * When BILLING_ENABLED and the user has no access (tier "Locked"), this renders
 * a FULL-SCREEN blocking overlay over the whole app (sidebar included) — option
 * A: no escape until a card is added. It replaces the old "redirect Locked users
 * to /billing" behavior.
 *
 * Two copies, driven by the server-computed `stage`:
 *   - onboarding  → new user (never subscribed): start the free trial.
 *   - resubscribe → returning user (baja→vuelve): re-subscribe, no trial framing.
 * The trial-vs-charge decision itself is server-side (anti-recycle); this only
 * chooses the wording.
 *
 * Dormant by the flag: with NEXT_PUBLIC_BILLING_ENABLED off it never fetches and
 * renders nothing, so navigation is unchanged. The backend gate is the real
 * enforcement (product endpoints 403 for Locked); this overlay is the UX.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, CreditCard, Lock } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { color, font } from "@/components/ui/tokens";
import { BILLING_ENABLED, billingApi, formatMoney, type BillingSummary } from "@/lib/billing";

// Default trial length shown in the new-user copy. The authoritative window
// (incl. per-user preferential days, Path B) is decided by Stripe at Checkout.
const TRIAL_DAYS = 7;

const MODULES = ["Ticker Analysis", "Screener", "Backtester"];

export function BillingGuard() {
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  // Dormant → already "ready" (renders nothing), so the effect never setStates
  // synchronously. Active → starts false until /me resolves.
  const [ready, setReady] = useState(!BILLING_ENABLED);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!BILLING_ENABLED) return; // dormant: ready is already true
    let active = true;

    // Checkout return (success_url carries session_id): materialize the
    // subscription now, then hard-reload without the param so the new tier
    // propagates everywhere (useEntitlements, product pages) and the gate lifts.
    const sessionId = new URLSearchParams(window.location.search).get("session_id");
    if (sessionId) {
      billingApi
        .sync(sessionId)
        .catch(() => {/* best-effort; the webhook is the durable path */})
        .finally(() => {
          window.location.replace(window.location.origin + window.location.pathname);
        });
      return () => { active = false; };
    }

    billingApi
      .me()
      .then((s) => { if (active) setSummary(s); })
      .catch((e) => { if (active) setError(e instanceof Error ? e.message : "No se pudo verificar tu suscripción"); })
      .finally(() => { if (active) setReady(true); });
    return () => { active = false; };
  }, []);

  const startCheckout = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const origin = window.location.origin;
      const res = await billingApi.checkout({
        success_url: `${origin}/billing?session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${origin}/billing?checkout=cancel`,
      });
      window.location.href = res.checkout_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo iniciar el pago");
      setBusy(false);
    }
  }, []);

  // Dormant, still verifying, or the user has access → render nothing (no flash
  // on loading; the backend gate protects endpoints meanwhile).
  if (!BILLING_ENABLED || !ready || !summary || summary.access) return null;

  const returning = summary.stage === "resubscribe";
  const price = formatMoney(summary.plan.amount_cents, summary.plan.currency);

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
        background: "color-mix(in srgb, var(--color-ec-bg-base) 88%, black)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        overflowY: "auto",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          background: color.bgSurface,
          border: `0.5px solid ${color.border}`,
          borderRadius: "var(--ec-radius-lg, 16px)",
          padding: "34px 30px",
          textAlign: "center",
          boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
        }}
      >
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: "50%",
            background: color.bgElevated,
            color: color.copper,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "0 auto 18px",
          }}
        >
          {returning ? <Lock size={24} strokeWidth={2} /> : <CreditCard size={24} strokeWidth={2} />}
        </div>

        <h2 style={{ fontFamily: font.serif, fontWeight: 500, fontSize: 24, color: color.textHigh, margin: "0 0 8px" }}>
          {returning ? "Reactiva tu suscripción" : "Añade tu tarjeta para empezar"}
        </h2>
        <p style={{ color: color.textSecondary, margin: "0 auto", maxWidth: 400, fontSize: 14, lineHeight: 1.5 }}>
          {returning
            ? "Vuelve a suscribirte a Edgecute para recuperar el acceso completo. Sin permanencia; cancela cuando quieras."
            : `Empieza tus ${TRIAL_DAYS} días gratis. No se te cobra hoy — al terminar la prueba, ${price}/mes. Cancela cuando quieras.`}
        </p>

        <div style={{ margin: "16px 0 4px" }}>
          <span style={{ fontFamily: font.serif, fontSize: 34, color: color.textHigh, fontWeight: 500 }}>{price}</span>
          <span style={{ color: color.textSecondary, fontSize: 14 }}>
            {returning ? " / mes" : " / mes después de la prueba"}
          </span>
        </div>

        <ul
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            textAlign: "left",
            maxWidth: 300,
            margin: "18px auto 6px",
            padding: 0,
          }}
        >
          {MODULES.map((f) => (
            <li key={f} style={{ listStyle: "none", display: "flex", alignItems: "center", gap: 10, color: color.textPrimary, fontSize: 14 }}>
              <span
                style={{
                  flex: "0 0 auto",
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: `color-mix(in srgb, ${color.profit} 20%, transparent)`,
                  color: color.profit,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Check size={11} strokeWidth={3} />
              </span>
              {f}
            </li>
          ))}
        </ul>

        {error ? (
          <div style={{ color: color.warning, fontSize: 12.5, margin: "10px 0 0" }}>{error}</div>
        ) : null}

        <Button
          variant="primary"
          size="lg"
          loading={busy}
          onClick={startCheckout}
          style={{ width: "100%", marginTop: 18 }}
        >
          {returning ? "Suscribirme" : "Añadir tarjeta y empezar"}
        </Button>

        <div style={{ color: color.textMuted, fontSize: 12, marginTop: 14 }}>
          {returning
            ? "Se te cobrará al confirmar. Sin periodo de prueba."
            : `Se pedirá una tarjeta. No se te cobrará durante los ${TRIAL_DAYS} días de prueba.`}
        </div>
      </div>
    </div>
  );
}
