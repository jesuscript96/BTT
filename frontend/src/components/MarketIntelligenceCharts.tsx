"use client";

import React from "react";
import Link from "next/link";
import { BarChart3, ArrowRight } from "lucide-react";

/**
 * DEPRECADO — el prototipo de gráficos de mercado se ha sustituido por la sección
 * dedicada **Market Analysis** (`/market-analysis`), que sirve los KPIs, las
 * distribuciones temporales, MAE/MFE y Recent Gaps desde el contrato del PRD.
 *
 * Este componente se conserva (mismo export) para no romper sus dos call-sites
 * (Dashboard empty-state y el home), pero YA NO consume `/api/market/screener`
 * ni `/aggregate/intraday`: tras reactivarse esos endpoints con el contrato nuevo,
 * el prototipo pintaba datos mal formados. Renderiza un CTA a la sección nueva.
 */
export const MarketIntelligenceCharts: React.FC = () => {
  return (
    <div
      style={{
        width: "100%",
        minHeight: 320,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px 0",
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          maxWidth: 440,
          width: "100%",
          background: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 12,
          padding: "32px 28px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          textAlign: "center",
          boxShadow: "0 2px 12px rgba(0,0,0,0.15)",
        }}
      >
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            background: "rgba(216,122,61,0.12)",
            border: "0.5px solid var(--color-ec-copper)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--color-ec-copper)",
          }}
        >
          <BarChart3 size={22} strokeWidth={1.8} />
        </div>
        <h3
          style={{
            fontFamily: "'Fraunces', serif",
            fontSize: 19,
            fontWeight: 500,
            color: "var(--color-ec-text-high)",
            margin: 0,
          }}
        >
          Market Analysis
        </h3>
        <p
          style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--color-ec-text-muted)",
            margin: 0,
          }}
        >
          La inteligencia de mercado vive ahora en su propia sección: KPIs de gappers,
          distribución de HOD/LOD/PMH, MAE/MFE y los últimos gaps.
        </p>
        <Link
          href="/market-analysis"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            marginTop: 4,
            padding: "9px 16px",
            borderRadius: 8,
            background: "var(--color-ec-copper)",
            color: "#1A0A00",
            fontFamily: "'General Sans', sans-serif",
            fontSize: 11,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 1,
            textDecoration: "none",
          }}
        >
          Abrir Market Analysis
          <ArrowRight size={14} strokeWidth={2.2} />
        </Link>
      </div>
    </div>
  );
};
