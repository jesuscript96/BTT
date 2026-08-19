"use client";

import { useEffect, useState } from "react";

import SubscriptionPanel from "@/components/billing/SubscriptionPanel";
import { color, font } from "@/components/ui/tokens";
import { BILLING_ENABLED, billingApi } from "@/lib/billing";

const container: React.CSSProperties = { maxWidth: 860, margin: "0 auto", padding: "26px 22px 60px" };

function Header() {
  return (
    <div style={{ marginBottom: 18 }}>
      <h1 style={{ fontFamily: font.serif, fontWeight: 500, fontSize: 25, color: color.textHigh, margin: "0 0 4px", letterSpacing: "0.2px" }}>
        Facturación
      </h1>
      <p style={{ margin: 0, color: color.textSecondary, fontSize: 13 }}>
        Gestiona tu suscripción, método de pago y facturas.
      </p>
    </div>
  );
}

export default function BillingPage() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // On return from Stripe Checkout the success_url carries ?session_id=… — confirm
    // the subscription synchronously (§4 step 5a) so access does not wait on the
    // webhook, then clean the URL so a refresh doesn't re-sync. setReady only runs
    // in async callbacks (no synchronous setState in the effect body).
    const sessionId = new URLSearchParams(window.location.search).get("session_id");
    if (sessionId && BILLING_ENABLED) {
      billingApi
        .sync(sessionId)
        .catch(() => {})
        .finally(() => {
          window.history.replaceState({}, "", "/billing");
          setReady(true);
        });
      return;
    }
    const t = setTimeout(() => setReady(true), 0);
    return () => clearTimeout(t);
  }, []);

  if (!BILLING_ENABLED) {
    return (
      <div style={container}>
        <Header />
        <div style={{ color: color.textSecondary, fontSize: 14 }}>La facturación aún no está disponible.</div>
      </div>
    );
  }

  return (
    <div style={container}>
      <Header />
      {ready ? (
        <SubscriptionPanel />
      ) : (
        <div style={{ color: color.textSecondary, fontSize: 14, padding: "40px 0", textAlign: "center" }}>
          Cargando facturación…
        </div>
      )}
    </div>
  );
}
