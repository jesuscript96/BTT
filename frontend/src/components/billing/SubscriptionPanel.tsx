"use client";

/**
 * Subscription / billing section (Fase 2F). Renders the state returned by
 * GET /api/billing/me in the four states designed with Adrian: active, trial,
 * past_due and locked (paywall). Uses the Edgecute UI kit + tokens.
 */
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowUpRight, Check, Clock, CreditCard, Lock } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Card, CardTitle } from "@/components/ui/Card";
import { Pill, type Tone } from "@/components/ui/Badge";
import { color, font, hairline } from "@/components/ui/tokens";
import {
  billingApi,
  daysUntil,
  formatDate,
  formatMoney,
  type BillingInvoice,
  type BillingSummary,
} from "@/lib/billing";

// Módulos del producto (Fase 3): Ticker Analysis · Screener · Backtester · Baúl
// de estrategias. Market Analysis queda fuera.
const PLAN_FEATURES = [
  "Ticker Analysis",
  "Screener",
  "Backtester",
  "Baúl de estrategias",
  "Sin permanencia",
];

const label: React.CSSProperties = {
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: "0.6px",
  color: color.textSecondary,
  fontWeight: 500,
};
const bigVal: React.CSSProperties = {
  fontFamily: font.serif,
  fontSize: 24,
  fontWeight: 500,
  color: color.textHigh,
  lineHeight: 1.1,
};

function Divider() {
  return <div style={{ height: "0.5px", background: color.border, margin: "16px 0" }} />;
}

function SubStatusPill({ status }: { status: string }) {
  const map: Record<string, { tone: Tone; text: string }> = {
    active: { tone: "good", text: "Activa" },
    trialing: { tone: "copper", text: "En prueba" },
    past_due: { tone: "warning", text: "Pago pendiente" },
    canceled: { tone: "neutral", text: "Cancelada" },
    unpaid: { tone: "bad", text: "Impagada" },
  };
  const s = map[status] ?? { tone: "neutral" as Tone, text: status };
  return <Pill tone={s.tone}>{s.text}</Pill>;
}

function Banner({
  tone,
  icon,
  title,
  detail,
  action,
}: {
  tone: "copper" | "amber";
  icon: React.ReactNode;
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  const accent = tone === "copper" ? color.copper : color.warning;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 13,
        borderRadius: "var(--ec-radius-md)",
        padding: "13px 16px",
        background: `color-mix(in srgb, ${accent} 9%, ${color.bgSurface})`,
        border: `0.5px solid color-mix(in srgb, ${accent} 32%, transparent)`,
      }}
    >
      <div
        style={{
          flex: "0 0 auto",
          width: 32,
          height: 32,
          borderRadius: "50%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: `color-mix(in srgb, ${accent} 18%, transparent)`,
          color: accent,
        }}
      >
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <strong style={{ color: color.textHigh, fontWeight: 600, fontSize: 13.5 }}>{title}</strong>
        <div style={{ color: color.textSecondary, fontSize: 12.5, marginTop: 1 }}>{detail}</div>
      </div>
      {action}
    </div>
  );
}

function PaymentMethodCard({ summary }: { summary: BillingSummary }) {
  const pm = summary.payment_method;
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <CardTitle>Método de pago</CardTitle>
      </div>
      {pm && pm.last4 ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                fontFamily: font.mono,
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "1px",
                color: color.textHigh,
                background: color.bgElevated,
                border: hairline,
                borderRadius: "var(--ec-radius-sm)",
                padding: "7px 10px",
                textTransform: "uppercase",
              }}
            >
              {pm.brand || "Tarjeta"}
            </span>
            <span style={{ fontFamily: font.mono, fontSize: 13, color: color.textPrimary, letterSpacing: "1px", fontVariantNumeric: "tabular-nums" }}>
              ···· ···· ···· {pm.last4}
            </span>
          </div>
          {pm.exp_month && pm.exp_year ? (
            <div style={{ color: color.textSecondary, fontSize: 12, marginTop: 10 }}>
              Caduca {String(pm.exp_month).padStart(2, "0")} / {pm.exp_year}
            </div>
          ) : null}
        </>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: color.textSecondary, fontSize: 13 }}>
          <CreditCard size={16} strokeWidth={1.5} />
          Sin método de pago guardado
        </div>
      )}
    </Card>
  );
}

function InvoicesCard({ invoices }: { invoices: BillingInvoice[] }) {
  if (!invoices.length) return null;
  const invTone = (status: string): Tone =>
    status === "paid" ? "good" : status === "open" ? "warning" : "bad";
  const invText = (status: string): string =>
    status === "paid" ? "Pagada" : status === "open" ? "Pendiente" : "Fallida";
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <CardTitle>Facturas</CardTitle>
        <span style={{ color: color.textSecondary, fontSize: 12 }}>
          {invoices.length} {invoices.length === 1 ? "factura" : "facturas"}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {invoices.map((inv, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "1.4fr 1fr auto auto",
              alignItems: "center",
              gap: 12,
              padding: "11px 2px",
              borderBottom: i < invoices.length - 1 ? `0.5px solid ${color.border}` : "none",
            }}
          >
            <span style={{ color: color.textPrimary, fontSize: 13 }}>{formatDate(inv.created_at)}</span>
            <span style={{ fontFamily: font.mono, fontSize: 13, color: color.textHigh, fontVariantNumeric: "tabular-nums" }}>
              {formatMoney(inv.amount_paid ?? inv.amount_due, inv.currency)}
            </span>
            <Pill tone={invTone(inv.status)} style={{ fontSize: 10.5, padding: "2px 8px" }}>
              {invText(inv.status)}
            </Pill>
            {inv.hosted_invoice_url ? (
              <a
                href={inv.hosted_invoice_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: color.copper, fontSize: 12.5, fontWeight: 600, textDecoration: "none" }}
              >
                Ver factura
              </a>
            ) : (
              <span />
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Paywall({ summary, onCheckout, busy }: { summary: BillingSummary; onCheckout: () => void; busy: boolean }) {
  return (
    <Card style={{ maxWidth: 520, margin: "0 auto", textAlign: "center", padding: "34px 26px" }}>
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
          margin: "0 auto 16px",
        }}
      >
        <Lock size={24} strokeWidth={2} />
      </div>
      <h2 style={{ fontFamily: font.serif, fontWeight: 500, fontSize: 23, color: color.textHigh, margin: "0 0 6px" }}>
        Añade tu tarjeta para empezar
      </h2>
      <p style={{ color: color.textSecondary, margin: "0 auto", maxWidth: 400, fontSize: 14 }}>
        Empieza tus 7 días gratis en Edgecute. No se te cobra hoy. Cancela cuando quieras.
      </p>
      <div style={{ margin: "14px 0 4px" }}>
        <span style={{ fontFamily: font.serif, fontSize: 34, color: color.textHigh, fontWeight: 500 }}>
          {formatMoney(summary.plan.amount_cents, summary.plan.currency)}
        </span>
        <span style={{ color: color.textSecondary, fontSize: 14 }}> / mes después de la prueba</span>
      </div>
      <ul
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "10px 18px",
          textAlign: "left",
          maxWidth: 420,
          margin: "18px auto",
          padding: 0,
        }}
      >
        {PLAN_FEATURES.map((f) => (
          <li key={f} style={{ listStyle: "none", display: "flex", alignItems: "center", gap: 9, color: color.textPrimary, fontSize: 13.5 }}>
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
      <Button variant="primary" size="lg" loading={busy} onClick={onCheckout} style={{ width: "100%", maxWidth: 300 }}>
        Añadir tarjeta y empezar
      </Button>
      <div style={{ color: color.textMuted, fontSize: 12, marginTop: 14 }}>
        Se pedirá una tarjeta. No se te cobrará durante los 7 días de prueba.
      </div>
    </Card>
  );
}

export default function SubscriptionPanel() {
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await billingApi.me());
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la facturación");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // setState only inside async callbacks (loading already starts true) so the
    // effect body has no synchronous setState. Manual retry uses load() below.
    let active = true;
    billingApi
      .me()
      .then((s) => { if (active) setSummary(s); })
      .catch((e) => { if (active) setError(e instanceof Error ? e.message : "No se pudo cargar la facturación"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const startCheckout = useCallback(async () => {
    setBusy(true);
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

  const openPortal = useCallback(async () => {
    setBusy(true);
    try {
      const res = await billingApi.portal({ return_url: `${window.location.origin}/billing` });
      window.location.href = res.portal_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo abrir el portal");
      setBusy(false);
    }
  }, []);

  if (loading) {
    return <div style={{ color: color.textSecondary, fontSize: 14, padding: "40px 0", textAlign: "center" }}>Cargando facturación…</div>;
  }
  if (error || !summary) {
    return (
      <Card style={{ textAlign: "center", padding: "28px 24px" }}>
        <div style={{ color: color.textHigh, fontSize: 14, marginBottom: 12 }}>{error || "Sin datos de facturación"}</div>
        <Button variant="secondary" onClick={() => void load()}>Reintentar</Button>
      </Card>
    );
  }

  // ── Locked → paywall ──
  if (!summary.access) {
    return <Paywall summary={summary} onCheckout={startCheckout} busy={busy} />;
  }

  const sub = summary.subscription;
  const isAdmin = summary.stage === "admin";
  const isComped = summary.stage === "comped";
  const isTrial =
    sub?.status === "trialing" || (summary.grant?.reason === "migration-trial" && !sub);
  const isPastDue = sub?.status === "past_due";
  const trialEnd = sub?.trial_end ?? summary.grant?.expires_at ?? null;
  const trialDays = daysUntil(trialEnd);

  const manageBtn = (
    <Button variant="secondary" onClick={openPortal} loading={busy} rightIcon={<ArrowUpRight size={14} strokeWidth={2} />}>
      Gestionar facturación
    </Button>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {isTrial ? (
        <Banner
          tone="copper"
          icon={<Clock size={17} strokeWidth={2} />}
          title={trialDays > 0 ? `Te quedan ${trialDays} ${trialDays === 1 ? "día" : "días"} de prueba` : "Tu prueba ha terminado"}
          detail={
            trialEnd
              ? `Tu prueba gratuita termina el ${formatDate(trialEnd)}. Suscríbete para no perder el acceso.`
              : "Suscríbete para conservar el acceso."
          }
          action={
            !sub ? (
              // Migration-grant user with no card yet → add a card to subscribe.
              <Button variant="primary" onClick={startCheckout} loading={busy}>
                Suscribirme
              </Button>
            ) : undefined
          }
        />
      ) : null}

      {isPastDue ? (
        <Banner
          tone="amber"
          icon={<AlertTriangle size={17} strokeWidth={2} />}
          title="No pudimos procesar tu último pago"
          detail="Lo reintentaremos automáticamente. Actualiza tu tarjeta para conservar el acceso."
          action={
            <Button variant="primary" onClick={openPortal} loading={busy}>
              Actualizar tarjeta
            </Button>
          }
        />
      ) : null}

      <Card featured>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
          <div>
            <div style={label}>Plan actual</div>
            <div style={{ ...bigVal, marginTop: 6 }}>Suscrito a Edgecute</div>
            <div style={{ color: color.textSecondary, fontSize: 13, marginTop: 3 }}>
              {PLAN_FEATURES.slice(0, 4).join(" · ")}
            </div>
          </div>
          {isAdmin ? (
            <Pill tone="copper">Acceso admin</Pill>
          ) : isComped ? (
            <Pill tone="copper">Cortesía</Pill>
          ) : sub ? (
            <SubStatusPill status={sub.status} />
          ) : summary.grant ? (
            <Pill tone="copper">En prueba</Pill>
          ) : null}
        </div>
        <Divider />
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
          <div>
            <div style={label}>{isTrial ? "Al terminar la prueba" : "Precio"}</div>
            <div style={{ marginTop: 5 }}>
              <span style={{ ...bigVal, fontSize: 20 }}>{formatMoney(isAdmin ? 0 : summary.plan.amount_cents, summary.plan.currency)}</span>
              <span style={{ color: color.textSecondary }}> / mes</span>
            </div>
          </div>
          <div>
            <div style={label}>{isAdmin || isComped ? "Estado" : isTrial ? "Primer cobro" : sub?.cancel_at_period_end ? "Acceso hasta" : "Próxima renovación"}</div>
            <div style={{ color: color.textPrimary, marginTop: 5 }}>
              {isAdmin
                ? "Acceso de administrador"
                : isComped
                  ? "Cortesía de Edgecute"
                  : formatDate(isTrial ? trialEnd : sub?.current_period_end ?? null)}
            </div>
          </div>
          {isAdmin || isComped ? null : manageBtn}
        </div>
        {sub?.cancel_at_period_end ? (
          <div style={{ color: color.warning, fontSize: 12.5, marginTop: 12 }}>
            Tu suscripción se cancelará al final del periodo actual.
          </div>
        ) : null}
      </Card>

      {isAdmin || isComped ? null : <PaymentMethodCard summary={summary} />}
      <InvoicesCard invoices={summary.invoices} />
    </div>
  );
}
