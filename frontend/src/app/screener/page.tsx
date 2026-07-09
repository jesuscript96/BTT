"use client";

import Screener from "@/components/Screener";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function ScreenerPage() {
  const { can, loading } = useEntitlements();
  // `can()` es optimista mientras carga: sin esta guarda pintaríamos el contenido
  // real un instante y lo cambiaríamos por LockedFeature al llegar el tier.
  if (loading) return null;
  if (!can("screener.access")) {
    return <LockedFeature feature="screener.access" requiredTier="Admin" />;
  }
  return <Screener />;
}
