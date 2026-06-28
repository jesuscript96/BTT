"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { getSavedBacktests } from "@/lib/api";
import { combinePortfolio, type CombineResponse } from "@/lib/api_portfolio";
import { track, EVENTS } from "@/lib/analytics";
import PortfolioTable, { type SavedBacktest } from "@/components/portfolio/PortfolioTable";
import RiskAnalysisPanel from "@/components/portfolio/RiskAnalysisPanel";
import MonitoringPanel, { type MonitoredBacktest } from "@/components/portfolio/MonitoringPanel";

type Tab = "portfolio" | "risk" | "monitoring";
interface RiskBoxItem { note: string; metrics?: Record<string, number>; weights?: Record<string, number> }

const card: React.CSSProperties = {
  background: "var(--color-ec-bg-surface)", border: "1px solid var(--color-ec-border)",
  borderRadius: 12, padding: 16,
};

export default function PortfolioPage() {
  const [rows, setRows] = useState<(SavedBacktest & MonitoredBacktest)[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<Tab>("portfolio");
  const [combined, setCombined] = useState<CombineResponse | null>(null);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [riskBox, setRiskBox] = useState<RiskBoxItem[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const res = await getSavedBacktests(200);
        setRows((res.strategies ?? []) as (SavedBacktest & MonitoredBacktest)[]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo cargar el Baúl.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const selectedIds = useMemo(() => Array.from(selected), [selected]);
  const selectedRows = useMemo(() => rows.filter((r) => selected.has(r.id)), [rows, selected]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function build() {
    if (!selectedIds.length) return;
    setBuilding(true);
    setError(null);
    try {
      const res = await combinePortfolio(selectedIds, null, 10000);
      setCombined(res);
      track(EVENTS.PORTFOLIO_BUILT, { n_strategies: selectedIds.length, weighting: "equal" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo construir la cartera.");
    } finally {
      setBuilding(false);
    }
  }

  function addToRiskBox(item: RiskBoxItem) {
    setRiskBox((prev) => [...prev, item]);
    if (item.weights) track(EVENTS.PORTFOLIO_WEIGHTS_SAVED, { n_strategies: Object.keys(item.weights).length });
  }

  return (
    <div style={{ padding: 24, maxWidth: 1280, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <header>
        <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 26, color: "var(--color-ec-text-high)", margin: 0 }}>Portfolio</h1>
        <p style={{ fontSize: 13, color: "var(--color-ec-text-secondary)", marginTop: 4 }}>
          Combina estrategias del Baúl, analiza el riesgo de la cartera y simula la gestión monetaria.
        </p>
      </header>

      {/* Baúl table */}
      <section style={card}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-ec-text-high)", marginBottom: 12 }}>
          Estrategias guardadas (Baúl)
        </div>
        <PortfolioTable rows={rows} selected={selected} onToggle={toggle} loading={loading} />
        <div style={{ marginTop: 14, display: "flex", gap: 12, alignItems: "center" }}>
          <button
            onClick={build}
            disabled={!selectedIds.length || building}
            style={{
              padding: "10px 18px", borderRadius: 8, fontSize: 13, fontWeight: 600,
              background: selectedIds.length ? "var(--color-ec-copper)" : "var(--color-ec-bg-elevated)",
              color: selectedIds.length ? "var(--color-ec-copper-text)" : "var(--color-ec-text-muted)",
              border: "none", cursor: selectedIds.length ? "pointer" : "not-allowed",
            }}
          >
            {building ? "Construyendo…" : `Construir portfolio de estrategias${selectedIds.length ? ` (${selectedIds.length})` : ""}`}
          </button>
          {error && <span style={{ fontSize: 12, color: "var(--color-ec-loss)" }}>{error}</span>}
        </div>
      </section>

      {/* Tabs */}
      <nav style={{ display: "flex", gap: 8, borderBottom: "1px solid var(--color-ec-border)" }}>
        {([["portfolio", "Portfolio"], ["risk", "Análisis de Riesgo"], ["monitoring", "Seguimiento"]] as [Tab, string][]).map(([t, lbl]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "10px 16px", fontSize: 13, cursor: "pointer", background: "transparent",
              border: "none", borderBottom: `2px solid ${tab === t ? "var(--color-ec-copper)" : "transparent"}`,
              color: tab === t ? "var(--color-ec-text-high)" : "var(--color-ec-text-secondary)",
            }}
          >
            {lbl}
          </button>
        ))}
      </nav>

      {tab === "portfolio" && (
        <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={card}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-ec-text-high)", marginBottom: 12 }}>Curva combinada</div>
            {combined ? (
              <div style={{ height: 300 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={combined.combined_equity.map((value, i) => ({ i, value, dd: combined.combined_drawdown[i] }))}>
                    <CartesianGrid stroke="var(--color-ec-border)" strokeDasharray="3 3" />
                    <XAxis dataKey="i" tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} />
                    <YAxis tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} width={60} />
                    <Tooltip contentStyle={{ background: "var(--color-ec-bg-elevated)", border: "1px solid var(--color-ec-border)", fontSize: 12 }} />
                    <Area dataKey="value" name="Equity" stroke="var(--color-ec-copper)" fill="rgba(216,122,61,0.15)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div style={{ padding: 32, textAlign: "center", color: "var(--color-ec-text-muted)", fontSize: 13 }}>
                Selecciona estrategias y pulsa “Construir portfolio”.
              </div>
            )}
          </div>

          {/* Risk box */}
          <div style={card}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-ec-text-high)", marginBottom: 12 }}>Cuadro de Riesgo</div>
            {combined ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
                <Stat label="PnL Total" value={`${combined.metrics.total_return_pct >= 0 ? "+" : ""}${combined.metrics.total_return_pct}%`} positive={combined.metrics.total_return_pct >= 0} />
                <Stat label="Drawdown Máx" value={`${combined.metrics.max_drawdown_pct}%`} positive={false} />
                <Stat label="Sharpe" value={`${combined.metrics.sharpe_ratio}`} />
                <Stat label="Volatilidad" value={`${combined.metrics.volatility_pct}%`} />
                <Stat label="Win Rate (días)" value={`${combined.metrics.win_rate_pct}%`} />
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "var(--color-ec-text-muted)" }}>Aún sin cartera construida.</div>
            )}
            {combined && (
              <div style={{ marginTop: 12, fontSize: 12, color: "var(--color-ec-text-secondary)" }}>
                Pesos: {Object.entries(combined.weights).map(([id, w]) => `${id.slice(0, 6)} ${(w * 100).toFixed(0)}%`).join(" · ")}
              </div>
            )}
            {riskBox.length > 0 && (
              <div style={{ marginTop: 12, borderTop: "1px solid var(--color-ec-border)", paddingTop: 12 }}>
                <div style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", marginBottom: 6 }}>Añadido desde subpáginas</div>
                {riskBox.map((item, i) => (
                  <div key={i} style={{ fontSize: 12, color: "var(--color-ec-text-primary)", padding: "3px 0" }}>• {item.note}</div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {tab === "risk" && (
        selectedIds.length ? (
          <RiskAnalysisPanel backtestIds={selectedIds} onAddToRiskBox={addToRiskBox} />
        ) : (
          <div style={{ ...card, textAlign: "center", color: "var(--color-ec-text-muted)", fontSize: 13, padding: 32 }}>
            Selecciona al menos una estrategia del Baúl para analizar el riesgo.
          </div>
        )
      )}

      {tab === "monitoring" && <MonitoringPanel rows={selectedRows} />}
    </div>
  );
}

function Stat({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  const color = positive === undefined ? "var(--color-ec-text-high)" : positive ? "var(--color-ec-profit)" : "var(--color-ec-loss)";
  return (
    <div style={{ padding: 14, borderRadius: 10, background: "var(--color-ec-bg-base)", border: "1px solid var(--color-ec-border)" }}>
      <div style={{ fontSize: 12, color: "var(--color-ec-text-secondary)" }}>{label}</div>
      <div style={{ fontSize: 20, color, marginTop: 4 }}>{value}</div>
    </div>
  );
}
