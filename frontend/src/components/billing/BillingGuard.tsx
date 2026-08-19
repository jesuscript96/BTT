"use client";

/**
 * Paywall router (Fase 2G). When BILLING_ENABLED and the resolved tier is
 * "Locked" (no active subscription / grant / admin), send the user to /billing,
 * where the paywall + Checkout live. Renders nothing.
 *
 * Dormant by the flag: with NEXT_PUBLIC_BILLING_ENABLED off it never runs, so
 * navigation is unchanged. The backend gate is the real enforcement; this only
 * improves UX by routing Locked users to the paywall instead of letting product
 * pages render and their API calls 403.
 */
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { BILLING_ENABLED } from "@/lib/billing";
import { useEntitlements } from "@/lib/entitlements";

// Pages a Locked user may still reach (the paywall itself + auth).
const ALLOWED_PREFIXES = ["/billing", "/sign-in", "/sign-up"];

export function BillingGuard() {
  const pathname = usePathname();
  const router = useRouter();
  const { tier, loading } = useEntitlements();

  useEffect(() => {
    if (!BILLING_ENABLED || loading) return; // wait for the real tier (no optimism)
    if (tier !== "Locked") return;
    const allowed = ALLOWED_PREFIXES.some((p) => pathname?.startsWith(p));
    if (!allowed) router.replace("/billing");
  }, [tier, loading, pathname, router]);

  return null;
}
