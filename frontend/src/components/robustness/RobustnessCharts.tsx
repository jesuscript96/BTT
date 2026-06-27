"use client";

/**
 * Robustness result visualizations (recharts) + metric cards with tooltips and
 * trading-semantic colors. Charts sit directly on the page background (few
 * borders) per the PDF brief / design system.
 */
import React, { useMemo, useState } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import type {
  MontecarloResponse,
  SensitivityResponse,
  BlackSwanResponse,
  WalkForwardResult,
  CurvePoint,
} from "@/lib/api_robustness";

const PROFIT = "var(--color-ec-profit)";
const LOSS = "var(--color-ec-loss)";
const COPPER = "var(--color-ec-copper)";
const MUTED = "var(--color-ec-text-muted)";
const TEXT = "var(--color-ec-text-primary)";
const SURFACE = "var(--color-ec-bg-surface)";
const BORDER = "var(--color-ec-border)";

const SPAGHETTI = ["#5B8BB0", "#8A8D92", PROFIT, COPPER, LOSS];

/** Color a risk metric green/copper/red by its value and thresholds (PRD §4.3). */
export function riskColor(value: number, kind: "ror" | "wfe"): string {
  if (kind === "wfe") {
    if (value >= 50) return PROFIT;
    if (value >= 40) return COPPER;
    return LOSS;
  }
  if (value < 5) return PROFIT;
  if (value <= 20) return COPPER;
  return LOSS;
}

function zoneColor(zone: string): string {
  return zone === "GREEN" ? PROFIT : zone === "YELLOW" ? COPPER : LOSS;
}

// ─── Metric card with hover tooltip ──────────────────────────
export function MetricCard({
  label,
  value,
  suffix = "",
  color = TEXT,
  hint,
}: {
  label: string;
  value: string | number;
  suffix?: string;
  color?: string;
  hint?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div
      style={{
        position: "relative",
        background: SURFACE,
        borderRadius: 10,
        padding: "14px 16px",
        minWidth: 150,
        flex: "1 1 150px",
      }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 12, color: MUTED, letterSpacing: 0.3 }}>{label}</span>
        {hint && <span style={{ fontSize: 11, color: MUTED, cursor: "help" }}>ⓘ</span>}
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color, marginTop: 4 }}>
        {value}
        <span style={{ fontSize: 14, color: MUTED }}>{suffix}</span>
      </div>
      {hint && show && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 20,
            marginTop: 6,
            width: 260,
            background: "var(--color-ec-bg-elevated)",
            border: `1px solid ${BORDER}`,
            borderRadius: 8,
            padding: "10px 12px",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--color-ec-text-secondary)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          }}
        >
          {hint}
        </div>
      )}
    </div>
  );
}

const SectionTitle = ({ children }: { children: React.ReactNode }) => (
  <h3 style={{ fontSize: 13, color: MUTED, margin: "8px 0 12px", fontWeight: 500, letterSpacing: 0.4 }}>
    {children}
  </h3>
);

function curvesToRows(curves: Record<string, CurvePoint[]>): { rows: Record<string, number>[]; keys: string[] } {
  const keys = Object.keys(curves);
  const len = keys.length ? curves[keys[0]].length : 0;
  const rows: Record<string, number>[] = [];
  for (let i = 0; i < len; i++) {
    const row: Record<string, number> = { idx: i };
    for (const k of keys) row[k] = curves[k]?.[i]?.value ?? 0;
    rows.push(row);
  }
  return { rows, keys };
}

// ─── Module 1 — Monte Carlo ──────────────────────────────────
export function MontecarloCharts({ data }: { data: MontecarloResponse }) {
  const { rows, keys } = useMemo(() => curvesToRows(data.percentiles), [data]);
  const ddRows = [
    { name: "Mediana", value: data.median_drawdown },
    { name: "P95", value: data.extreme_drawdown_p95 },
    { name: "P99", value: data.extreme_drawdown_p99 },
    { name: "Peor", value: data.worst_drawdown },
  ];
  return (
    <div>
      <SectionTitle>Curvas de capital (espagueti por percentiles)</SectionTitle>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke={BORDER} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="idx" tick={{ fill: MUTED, fontSize: 11 }} />
          <YAxis tick={{ fill: MUTED, fontSize: 11 }} width={56} />
          <Tooltip contentStyle={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, color: TEXT }} />
          {keys.map((k, i) => (
            <Line key={k} type="monotone" dataKey={k} stroke={SPAGHETTI[i % SPAGHETTI.length]} dot={false} strokeWidth={k === "p50" ? 2 : 1} />
          ))}
        </LineChart>
      </ResponsiveContainer>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 16 }}>
        <MetricCard label="Riesgo de Ruina (RoR)" value={data.ruin_probability} suffix="%" color={riskColor(data.ruin_probability, "ror")}
          hint="Probabilidad de que el capital toque tu umbral de ruina en alguna de las simulaciones. Ej: 1.25% = 12 de cada 1000 curvas se arruinaron." />
        <MetricCard label="Retorno negativo" value={data.probability_negative_return} suffix="%" color={riskColor(data.probability_negative_return, "ror")}
          hint={`% de curvas que terminan bajo el saldo inicial tras ${data.n_trades_calculated} trades. Mide la paciencia que exige la estrategia.`} />
        <MetricCard label="Drawdown P95" value={data.extreme_drawdown_p95} suffix="%" color={LOSS}
          hint="Drawdown extremo esperado: solo el 5% de los escenarios fue peor que esto." />
        <MetricCard label="Drawdown P99" value={data.extreme_drawdown_p99} suffix="%" color={LOSS}
          hint="Cola del 1%: el peor 1% de escenarios superó este drawdown." />
      </div>

      <SectionTitle>Distribución del drawdown máximo</SectionTitle>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={ddRows} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={BORDER} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: MUTED, fontSize: 11 }} />
          <YAxis tick={{ fill: MUTED, fontSize: 11 }} width={56} />
          <Tooltip contentStyle={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, color: TEXT }} />
          <Bar dataKey="value" fill={LOSS} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Module 3 — Sensitivity ──────────────────────────────────
export function SensitivityCharts({ data }: { data: SensitivityResponse }) {
  const { rows, keys } = useMemo(() => curvesToRows(data.curves), [data]);
  return (
    <div>
      {data.critical_locate_threshold !== null && (
        <div style={{ marginBottom: 14 }}>
          <MetricCard label="Umbral Crítico de Locates" value={data.critical_locate_threshold.toFixed(2)} suffix="%" color={COPPER}
            hint="Coste de locate (%/acción) a partir del cual la estrategia deja de ser rentable: su Net Profit neto llega a 0." />
        </div>
      )}
      {data.critical_locate_threshold === null && (
        <div style={{ color: MUTED, fontSize: 13, marginBottom: 12 }}>Umbral crítico: N/A (sin operaciones en corto).</div>
      )}
      <SectionTitle>Equity bajo distintos costes de locate</SectionTitle>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke={BORDER} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="idx" tick={{ fill: MUTED, fontSize: 11 }} />
          <YAxis tick={{ fill: MUTED, fontSize: 11 }} width={56} />
          <Tooltip contentStyle={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: 8, color: TEXT }} />
          <Legend wrapperStyle={{ fontSize: 11, color: MUTED }} />
          {keys.map((k, i) => (
            <Line key={k} type="monotone" dataKey={k} stroke={SPAGHETTI[i % SPAGHETTI.length]} dot={false} strokeWidth={1.5} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Module 4 — Black Swan ───────────────────────────────────
export function BlackSwanCharts({ data }: { data: BlackSwanResponse }) {
  const positions = Array.from(new Set(data.sensitivity_matrix.map((c) => c.position_size_pct))).sort((a, b) => a - b);
  const severities = Array.from(new Set(data.sensitivity_matrix.map((c) => c.severity_multiplier))).sort((a, b) => a - b);
  const cell = (p: number, s: number) => data.sensitivity_matrix.find((c) => c.position_size_pct === p && c.severity_multiplier === s);
  return (
    <div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
        <MetricCard label="Tiempo de Recuperación (TTR)" value={data.time_to_recovery_trades} suffix=" trades" color={COPPER}
          hint="Media de trades necesarios para recuperar el pico de capital previo al Cisne Negro." />
        <MetricCard label="Riesgo de Ruina post-Swan (100t)" value={data.post_swan_ruin_risk_100t} suffix="%" color={riskColor(data.post_swan_ruin_risk_100t, "ror")}
          hint="Probabilidad de tocar la ruina en los 100 trades siguientes tras recibir el impacto directo de un Cisne Negro." />
      </div>
      <SectionTitle>Matriz de sensibilidad: Tamaño de posición × Severidad</SectionTitle>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "separate", borderSpacing: 4 }}>
          <thead>
            <tr>
              <th style={{ fontSize: 11, color: MUTED, fontWeight: 500, padding: 6 }}>Pos % \ Sev ×</th>
              {severities.map((s) => (
                <th key={s} style={{ fontSize: 11, color: MUTED, fontWeight: 500, padding: 6 }}>×{s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p}>
                <td style={{ fontSize: 11, color: MUTED, padding: 6 }}>{p}%</td>
                {severities.map((s) => {
                  const c = cell(p, s);
                  if (!c) return <td key={s} />;
                  return (
                    <td
                      key={s}
                      title={`Ruina ${c.ruin_probability}% · DD ${c.max_drawdown}%`}
                      style={{
                        background: zoneColor(c.zone),
                        color: "#0E0E0E",
                        borderRadius: 8,
                        padding: "12px 14px",
                        textAlign: "center",
                        minWidth: 92,
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      {c.ruin_probability}%
                      <div style={{ fontSize: 10, fontWeight: 400, opacity: 0.8 }}>DD {c.max_drawdown}%</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Module 2 — Walk-Forward ─────────────────────────────────
export function WalkForwardCharts({ data }: { data: WalkForwardResult }) {
  const wfe = data.wfe ?? 0;
  const wrp = data.win_rate_penalty ?? 0;
  const heat = data.heatmap_matrix;
  const scores = heat?.data.map((d) => d.is_score) ?? [];
  const min = Math.min(...(scores.length ? scores : [0]));
  const max = Math.max(...(scores.length ? scores : [1]));
  const heatColor = (v: number) => {
    const t = max === min ? 0.5 : (v - min) / (max - min);
    // copper(low) → profit(high)
    return t < 0.5 ? LOSS : t < 0.75 ? COPPER : PROFIT;
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
        <MetricCard label="Walk-Forward Efficiency (WFE)" value={wfe} suffix="%" color={riskColor(wfe, "wfe")}
          hint="Rendimiento OOS dividido por el IS (×100). <50% = inestable: la estrategia rinde mucho peor fuera de muestra (overfitting)." />
        <MetricCard label="Win Rate Penalty" value={wrp} suffix="%" color={riskColor(20 - wrp, "ror")}
          hint="Degradación del % de acierto entre entrenamiento (IS) y prueba ciega (OOS). Cuanto mayor, más optimista era el IS." />
        <MetricCard label="Max Drawdown OOS" value={data.oos_max_drawdown ?? 0} suffix="%" color={LOSS}
          hint="Drawdown máximo registrado exclusivamente en los periodos Out-of-Sample concatenados." />
      </div>
      {heat && heat.data.length > 0 && (
        <>
          <SectionTitle>Mapa de calor paramétrico (score IS por combinación de {heat.parameters.join(", ")})</SectionTitle>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {heat.data.map((d, i) => (
              <div
                key={i}
                title={`${heat.parameters.join("/")}: ${d.values.join(", ")} · score ${d.is_score}`}
                style={{
                  background: heatColor(d.is_score),
                  color: "#0E0E0E",
                  borderRadius: 6,
                  padding: "10px 12px",
                  fontSize: 11,
                  fontWeight: 600,
                  minWidth: 64,
                  textAlign: "center",
                }}
              >
                {d.values.join("/")}
                <div style={{ fontSize: 10, fontWeight: 400 }}>{d.is_score}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
