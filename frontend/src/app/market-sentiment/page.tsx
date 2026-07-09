"use client";

import MarketSentiment from "@/components/MarketSentiment";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function MarketSentimentPage() {
  const { can, loading } = useEntitlements();
  // `can()` es optimista mientras carga: sin esta guarda pintaríamos el contenido
  // real un instante y lo cambiaríamos por LockedFeature al llegar el tier.
  if (loading) return null;
  if (!can("market.sentiment.access")) {
    return <LockedFeature feature="market.sentiment.access" requiredTier="Admin" />;
  }
  return <MarketSentiment />;
}
