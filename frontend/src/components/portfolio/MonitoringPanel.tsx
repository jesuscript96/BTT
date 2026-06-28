"use client";

import React, { useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { track, EVENTS } from "@/lib/analytics";

interface EquityPoint { time: number; value: number }
export interface MonitoredBacktest {
  id: string;
  strategy_names?: string[];
  results_json?: { global_equity?: EquityPoint[] };
}

const card: React.CSSProperties = {
  background: "var(--color-ec-bg-surface)", border: "1px solid var(--color-ec-border)",
  borderRadius: 12, padding: 16,
};
const SERIES_COLORS = ["#D87A3D", "#4A9D7F", "#5B8BB0", "#C9A23F", "#C94D3F", "#8A8D92", "#E89C6A"];

function label(r: MonitoredBacktest): string {
  const names = r.strategy_names?.filter(Boolean) ?? [];
  return names.length ? names.join(" + ") : r.id.slice(0, 8);
}

export default function MonitoringPanel({ rows }: { rows: MonitoredBacktest[] }) {
  const [tab, setTab] = useState<"strategies" | "journal">("strategies");

  // Overlay the saved daily equity curves, aligned by date index (normalised to 100).
  const { merged, keys } = useMemo(() => {
    const keys = rows.map(label);
    const maxLen = Math.max(0, ...rows.map((r) => r.results_json?.global_equity?.length ?? 0));
    const merged = Array.from({ length: maxLen }, (_, i) => {
      const point: Record<string, number> = { i };
      rows.forEach((r, idx) => {
        const curve = r.results_json?.global_equity;
        if (curve && curve[i]) {
          const base = curve[0]?.value || 1;
          point[keys[idx]] = (curve[i].value / base) * 100;
        }
      });
      return point;
    });
    return { merged, keys };
  }, [rows]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <TabBtn active={tab === "strategies"} onClick={() => setTab("strategies")}>Seguimiento de estrategias</TabBtn>
        <TabBtn active={tab === "journal"} onClick={() => { setTab("journal"); track(EVENTS.PORTFOLIO_JOURNAL_VIEWED, { state: "coming_soon" }); }}>
          Seguimiento por Journal
        </TabBtn>
      </div>

      {tab === "strategies" ? (
        <div style={{ ...card, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: 13, color: "var(--color-ec-text-secondary)" }}>
              Curvas individuales solapadas (normalizadas a 100).
            </div>
            <button
              title="Re-ejecución en caliente de los últimos 3 meses — próximamente"
              disabled
              style={{ padding: "8px 12px", borderRadius: 8, fontSize: 12, background: "var(--color-ec-bg-elevated)", color: "var(--color-ec-text-muted)", border: "1px solid var(--color-ec-border)", cursor: "not-allowed" }}
            >
              Actualizar 3M · Próximamente
            </button>
          </div>
          {rows.length === 0 ? (
            <Empty text="Selecciona estrategias en el Baúl para solapar sus curvas." />
          ) : (
            <div style={{ height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={merged}>
                  <CartesianGrid stroke="var(--color-ec-border)" strokeDasharray="3 3" />
                  <XAxis dataKey="i" tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} width={48} />
                  <Tooltip contentStyle={{ background: "var(--color-ec-bg-elevated)", border: "1px solid var(--color-ec-border)", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {keys.map((k, idx) => (
                    <Line key={k} dataKey={k} stroke={SERIES_COLORS[idx % SERIES_COLORS.length]} dot={false} strokeWidth={1.5} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          {/* Individual equity cards, 2 per row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {rows.map((r, idx) => (
              <MiniEquity key={r.id} title={label(r)} curve={r.results_json?.global_equity ?? []} color={SERIES_COLORS[idx % SERIES_COLORS.length]} />
            ))}
          </div>
        </div>
      ) : (
        <div style={{ ...card }}>
          <ComingSoon />
        </div>
      )}
    </div>
  );
}

function MiniEquity({ title, curve, color }: { title: string; curve: EquityPoint[]; color: string }) {
  const data = curve.map((p, i) => ({ i, value: p.value }));
  return (
    <div style={{ background: "var(--color-ec-bg-base)", border: "1px solid var(--color-ec-border)", borderRadius: 10, padding: 10 }}>
      <div style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", marginBottom: 6, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</div>
      <div style={{ height: 90 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <Line dataKey="value" stroke={color} dot={false} strokeWidth={1.5} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ComingSoon() {
  return (
    <div style={{ textAlign: "center", padding: "40px 24px", color: "var(--color-ec-text-secondary)" }}>
      <div style={{ fontSize: 28, marginBottom: 8 }}>🔜</div>
      <div style={{ fontSize: 15, color: "var(--color-ec-text-high)", marginBottom: 8 }}>Seguimiento por Journal — Próximamente</div>
      <div style={{ fontSize: 13, maxWidth: 460, margin: "0 auto", lineHeight: 1.5 }}>
        Aquí podrás cargar la curva de equity real construida a partir de los PnLs de tu Journal de
        operaciones y aplicarle simuladores de escalado (Kelly, % fijo, parada por drawdown).
        Primero necesitas registrar trades reales en el Journal.
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} style={{
      padding: "8px 14px", borderRadius: 8, fontSize: 13, cursor: "pointer",
      background: active ? "var(--color-ec-bg-surface)" : "transparent",
      color: active ? "var(--color-ec-text-high)" : "var(--color-ec-text-secondary)",
      border: `1px solid ${active ? "var(--color-ec-border)" : "transparent"}`,
    }}>{children}</button>
  );
}

function Empty({ text }: { text: string }) {
  return <div style={{ padding: 24, textAlign: "center", color: "var(--color-ec-text-muted)", fontSize: 13 }}>{text}</div>;
}
