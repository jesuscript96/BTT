"use client";

import MarketAnalysis from "@/components/MarketAnalysis";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function MarketAnalysisAdjustedPage() {
  const { can, loading } = useEntitlements();
  if (loading) return null;
  if (!can("market.analysis.access")) {
    return <LockedFeature feature="market.analysis.access" requiredTier="Admin" />;
  }
  return <MarketAnalysis adjusted />;
}
