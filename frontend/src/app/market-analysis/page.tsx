"use client";

import MarketAnalysis from "@/components/MarketAnalysis";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function MarketAnalysisPage() {
  const { can } = useEntitlements();
  if (!can("market.analysis.access")) {
    return <LockedFeature feature="market.analysis.access" requiredTier="Admin" />;
  }
  return <MarketAnalysis />;
}
