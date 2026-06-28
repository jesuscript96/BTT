"use client";

import React, { useState } from "react";
import { GLOSSARY, type GlossaryKey } from "./glossary";

/** Small "?" badge that reveals a didactic glossary entry (PRD §2.5). */
export function InfoTip({ topic }: { topic: GlossaryKey }) {
  const [open, setOpen] = useState(false);
  const g = GLOSSARY[topic];
  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Ayuda: ${g.title}`}
        style={{
          width: 16, height: 16, borderRadius: "50%", fontSize: 11, lineHeight: "16px",
          border: "1px solid var(--color-ec-border)", background: "var(--color-ec-bg-elevated)",
          color: "var(--color-ec-text-secondary)", cursor: "pointer", marginLeft: 6, padding: 0,
        }}
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          style={{
            position: "absolute", zIndex: 50, top: 22, left: 0, width: 320,
            padding: 12, borderRadius: 10, background: "var(--color-ec-bg-elevated)",
            border: "1px solid var(--color-ec-border)", boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            fontSize: 12, color: "var(--color-ec-text-primary)", lineHeight: 1.5,
          }}
        >
          <strong style={{ color: "var(--color-ec-text-high)" }}>{g.title}</strong>
          <div style={{ marginTop: 4 }}>{g.body}</div>
          {g.example && (
            <div style={{ marginTop: 6, color: "var(--color-ec-text-secondary)", fontStyle: "italic" }}>
              {g.example}
            </div>
          )}
        </span>
      )}
    </span>
  );
}

/** Persistent help banner (e.g. overfitting warning). */
export function HelpBanner({ topic }: { topic: GlossaryKey }) {
  const g = GLOSSARY[topic];
  return (
    <div
      style={{
        padding: "10px 12px", borderRadius: 8, fontSize: 12, lineHeight: 1.5,
        background: "rgba(201,162,63,0.08)", border: "1px solid rgba(201,162,63,0.25)",
        color: "var(--color-ec-text-secondary)",
      }}
    >
      <strong style={{ color: "var(--color-ec-warning)" }}>{g.title}.</strong> {g.body}
    </div>
  );
}
