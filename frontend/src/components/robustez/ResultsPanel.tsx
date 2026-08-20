"use client";

import React from "react";
import { color, font, radius } from "@/components/ui/tokens";
import { MODULES, type ModuleId } from "./ModuleRail";

interface Props {
  module: ModuleId;
  children: React.ReactNode;
}

export default function ResultsPanel({ module, children }: Props) {
  const def = MODULES.find((m) => m.id === module);
  return (
    <div
      style={{
        background: color.bgSurface,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        overflow: "hidden",
        minHeight: 380,
      }}
    >
      <div
        style={{
          padding: "10px 18px",
          borderBottom: `0.5px solid ${color.border}`,
          display: "flex",
          alignItems: "baseline",
          gap: 10,
        }}
      >
        <span
          style={{
            fontSize: 10,
            letterSpacing: "0.11em",
            textTransform: "uppercase",
            color: color.copper,
            fontFamily: font.sans,
          }}
        >
          {def?.label ?? "Resultados"}
        </span>
        <span style={{ fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>{def?.blurb}</span>
      </div>
      <div style={{ padding: "18px 18px 22px" }}>{children}</div>
    </div>
  );
}
