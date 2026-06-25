"use client";

import MarketSentiment from "@/components/MarketSentiment";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function MarketSentimentPage() {
  const { can } = useEntitlements();
  if (!can("market.sentiment.access")) {
    return <LockedFeature feature="market.sentiment.access" requiredTier="Admin" />;
  }
  return <MarketSentiment />;
}
