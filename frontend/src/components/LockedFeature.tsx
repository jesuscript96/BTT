"use client";

/**
 * Gates its children behind an entitlement. When the current tier can access
 * `feature`, the children render unchanged; otherwise a locked card is shown
 * inviting an upgrade to `requiredTier`.
 *
 * MVP: every feature is open, so children always render. The locked card only
 * appears once the backend policy starts returning a `false` for `feature`.
 */
import type { ReactNode } from "react";

import { Lock } from "lucide-react";

import { useEntitlements } from "@/lib/entitlements";

interface LockedFeatureProps {
  feature: string;
  requiredTier: string;
  children?: ReactNode;
}

export default function LockedFeature({
  feature,
  requiredTier,
  children,
}: LockedFeatureProps) {
  const { can } = useEntitlements();

  if (can(feature)) {
    return <>{children ?? null}</>;
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 12,
        padding: "32px 24px",
        textAlign: "center",
        backgroundColor: "var(--color-ec-bg-surface)",
        border: "0.5px solid var(--color-ec-border)",
        borderRadius: 10,
        color: "var(--color-ec-text-secondary)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 44,
          height: 44,
          borderRadius: "50%",
          backgroundColor: "var(--color-ec-bg-elevated)",
          color: "var(--color-ec-copper)",
        }}
      >
        <Lock size={20} strokeWidth={2} />
      </div>

      <p
        style={{
          margin: 0,
          fontSize: 14,
          fontWeight: 500,
          color: "var(--color-ec-text-high)",
        }}
      >
        Esta función requiere plan {requiredTier}
      </p>

      <button
        type="button"
        disabled
        title="Próximamente"
        style={{
          marginTop: 4,
          padding: "8px 18px",
          fontSize: 13,
          fontWeight: 600,
          borderRadius: 8,
          border: "none",
          cursor: "not-allowed",
          opacity: 0.6,
          backgroundColor: "var(--color-ec-copper)",
          color: "var(--color-ec-copper-text)",
        }}
      >
        Ver planes
      </button>
    </div>
  );
}
