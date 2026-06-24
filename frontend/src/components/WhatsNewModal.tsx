"use client";

import { useEffect, useState } from "react";
import { useUser } from "@clerk/nextjs";
import { Sparkles, X } from "lucide-react";
import { LATEST_RELEASE } from "@/data/releases";
import { track, EVENTS } from "@/lib/analytics";

/**
 * "What's new" popup shown once per release, per user.
 *
 * The "seen" state lives in Clerk `unsafeMetadata.lastSeenReleaseId`, so it is
 * tied to the USER (survives new sessions and other devices) — not localStorage
 * per browser. It only appears when LATEST_RELEASE.id differs from what the user
 * has already seen, so it never shows on every login.
 */
export default function WhatsNewModal() {
  const { user, isLoaded } = useUser();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!isLoaded || !user || !LATEST_RELEASE) return;
    const seen = user.unsafeMetadata?.lastSeenReleaseId as string | undefined;
    if (seen !== LATEST_RELEASE.id) {
      setOpen(true);
      track(EVENTS.WHATSNEW_VIEWED, { release_id: LATEST_RELEASE.id });
    }
  }, [isLoaded, user]);

  async function dismiss() {
    setOpen(false);
    if (!user || !LATEST_RELEASE) return;
    try {
      await user.update({
        unsafeMetadata: {
          ...(user.unsafeMetadata ?? {}),
          lastSeenReleaseId: LATEST_RELEASE.id,
        },
      });
    } catch {
      // if persisting fails we simply may show it again next load — acceptable
    }
  }

  if (!open || !LATEST_RELEASE) return null;

  return (
    <div
      onClick={dismiss}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1001,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        fontFamily: "'General Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 440,
          background: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 10,
          padding: "24px 26px 22px",
          boxShadow: "0 18px 50px rgba(0,0,0,0.5)",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <Sparkles size={18} style={{ color: "var(--color-ec-copper)" }} />
            <span style={{ fontFamily: "'Fraunces', serif", fontSize: 19, fontWeight: 600, color: "var(--color-ec-text-high)", letterSpacing: "-0.3px" }}>
              {LATEST_RELEASE.title}
            </span>
          </div>
          <button onClick={dismiss} aria-label="Cerrar" style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--color-ec-text-muted)", padding: 4, lineHeight: 0 }}>
            <X size={18} />
          </button>
        </div>

        {LATEST_RELEASE.requestedByYou && (
          <div style={{ display: "inline-block", marginTop: 12, fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.4, color: "var(--color-ec-copper)", background: "rgba(216,122,61,0.1)", border: "0.5px solid rgba(216,122,61,0.3)", borderRadius: 4, padding: "3px 8px" }}>
            Lo pedisteis vosotros
          </div>
        )}

        <div style={{ fontSize: 11, color: "var(--color-ec-text-muted)", marginTop: 12 }}>{LATEST_RELEASE.date}</div>

        <ul style={{ listStyle: "none", padding: 0, margin: "14px 0 0" }}>
          {LATEST_RELEASE.items.map((it, i) => (
            <li key={i} style={{ display: "flex", gap: 9, fontSize: 13, color: "var(--color-ec-text-high)", lineHeight: 1.5, marginBottom: 9 }}>
              <span style={{ color: "var(--color-ec-copper)", flexShrink: 0 }}>›</span>
              <span>{it}</span>
            </li>
          ))}
        </ul>

        <button
          onClick={dismiss}
          style={{
            marginTop: 18,
            width: "100%",
            background: "var(--color-ec-copper)",
            color: "var(--color-ec-copper-text)",
            border: "none",
            borderRadius: 6,
            padding: "10px 16px",
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: 0.6,
            textTransform: "uppercase",
            cursor: "pointer",
            fontFamily: "'General Sans', sans-serif",
          }}
        >
          Entendido
        </button>
      </div>
    </div>
  );
}
