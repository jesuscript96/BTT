"use client";

import MarketAnalysis from "@/components/MarketAnalysis";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function MarketAnalysisPage() {
  const { can, loading } = useEntitlements();
  // `can()` es optimista mientras carga: sin esta guarda pintaríamos el contenido
  // real un instante y lo cambiaríamos por LockedFeature al llegar el tier.
  if (loading) return null;
  if (!can("market.analysis.access")) {
    return <LockedFeature feature="market.analysis.access" requiredTier="Admin" />;
  }
  return <MarketAnalysis />;
}
