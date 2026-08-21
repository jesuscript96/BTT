"use client";

import { useEffect, useState } from "react";

import SubscriptionPanel from "@/components/billing/SubscriptionPanel";
import { color, font } from "@/components/ui/tokens";
import { BILLING_ENABLED } from "@/lib/billing";

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
    // The Checkout return (?session_id=…) is handled globally by BillingGuard,
    // which syncs and hard-reloads so the new tier propagates everywhere — so
    // this page no longer needs to sync. It just renders the panel once mounted.
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
