"use client";

import Screener from "@/components/Screener";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function ScreenerPage() {
  const { can } = useEntitlements();
  if (!can("screener.access")) {
    return <LockedFeature feature="screener.access" requiredTier="Admin" />;
  }
  return <Screener />;
}
