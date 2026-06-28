"use client";

import React from "react";

export interface SavedBacktest {
  id: string;
  strategy_names?: string[];
  total_trades?: number;
  win_rate?: number;
  total_return_pct?: number;
  sharpe_ratio?: number;
}

interface Props {
  rows: SavedBacktest[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  loading?: boolean;
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 12px",
  fontSize: 12,
  color: "var(--color-ec-text-secondary)",
  fontWeight: 500,
  borderBottom: "1px solid var(--color-ec-border)",
};
const td: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 13,
  color: "var(--color-ec-text-primary)",
  borderBottom: "1px solid var(--color-ec-border)",
};

function label(r: SavedBacktest): string {
  const names = r.strategy_names?.filter(Boolean) ?? [];
  return names.length ? names.join(" + ") : r.id.slice(0, 8);
}

function pnlColor(v?: number): string {
  if (v == null) return "var(--color-ec-text-muted)";
  return v >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)";
}

export default function PortfolioTable({ rows, selected, onToggle, loading }: Props) {
  if (loading) {
    return <div style={{ padding: 24, color: "var(--color-ec-text-secondary)" }}>Cargando el Baúl…</div>;
  }
  if (!rows.length) {
    return (
      <div style={{ padding: 24, color: "var(--color-ec-text-secondary)" }}>
        No hay backtests guardados en el Baúl. Ejecuta y guarda estrategias primero.
      </div>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ ...th, width: 40 }} />
            <th style={th}>Estrategia</th>
            <th style={th}>Trades</th>
            <th style={th}>Win Rate</th>
            <th style={th}>Total PnL</th>
            <th style={th}>Sharpe</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isSel = selected.has(r.id);
            return (
              <tr
                key={r.id}
                onClick={() => onToggle(r.id)}
                style={{
                  cursor: "pointer",
                  background: isSel ? "var(--color-ec-surface-hover)" : "transparent",
                }}
              >
                <td style={td}>
                  <input type="checkbox" checked={isSel} onChange={() => onToggle(r.id)} aria-label={`Seleccionar ${label(r)}`} />
                </td>
                <td style={{ ...td, color: "var(--color-ec-text-high)" }}>{label(r)}</td>
                <td style={td}>{r.total_trades ?? "—"}</td>
                <td style={td}>{r.win_rate != null ? `${r.win_rate.toFixed(1)}%` : "—"}</td>
                <td style={{ ...td, color: pnlColor(r.total_return_pct) }}>
                  {r.total_return_pct != null ? `${r.total_return_pct >= 0 ? "+" : ""}${r.total_return_pct.toFixed(2)}%` : "—"}
                </td>
                <td style={td}>{r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
