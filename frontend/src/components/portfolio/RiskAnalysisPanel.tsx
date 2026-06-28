"use client";

import React, { useState } from "react";
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import {
  runMontecarlo, getCorrelation, getAllocation, runScaling,
  type MontecarloResponse, type CorrelationResponse, type AllocationResponse, type ScalingResponse,
} from "@/lib/api_portfolio";
import { track, EVENTS } from "@/lib/analytics";
import { InfoTip, HelpBanner } from "./InfoTip";

type Model = "montecarlo" | "correlation" | "scaling" | "allocation";

interface Props {
  backtestIds: string[];
  onAddToRiskBox: (payload: { metrics?: Record<string, number>; weights?: Record<string, number>; note: string }) => void;
}

const card: React.CSSProperties = {
  background: "var(--color-ec-bg-surface)", border: "1px solid var(--color-ec-border)",
  borderRadius: 12, padding: 16,
};
const labelStyle: React.CSSProperties = { fontSize: 12, color: "var(--color-ec-text-secondary)", display: "block", marginBottom: 4 };
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", borderRadius: 8, fontSize: 13,
  background: "var(--color-ec-bg-base)", border: "1px solid var(--color-ec-border)", color: "var(--color-ec-text-high)",
};
const btn: React.CSSProperties = {
  width: "100%", padding: "10px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
  background: "var(--color-ec-copper)", color: "var(--color-ec-copper-text)", border: "none", cursor: "pointer",
};
const ghostBtn: React.CSSProperties = {
  ...btn, background: "transparent", color: "var(--color-ec-text-primary)", border: "1px solid var(--color-ec-border)",
};

function corrColor(v: number): string {
  const t = Math.max(-1, Math.min(1, v));
  return t >= 0 ? `rgba(201,77,63,${0.15 + 0.6 * t})` : `rgba(74,157,127,${0.15 + 0.6 * Math.abs(t)})`;
}

export default function RiskAnalysisPanel({ backtestIds, onAddToRiskBox }: Props) {
  const [model, setModel] = useState<Model>("montecarlo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // params
  const [simulations, setSimulations] = useState(1000);
  const [initCash, setInitCash] = useState(10000);
  const [allocMethod, setAllocMethod] = useState<"leaders" | "hrp">("hrp");
  const [lookback, setLookback] = useState(15);
  const [corrKind, setCorrKind] = useState<"pearson" | "spearman">("pearson");
  const [scalingMode, setScalingMode] = useState<"kelly" | "fixed_pct" | "drawdown_stop">("kelly");

  // results
  const [mc, setMc] = useState<MontecarloResponse | null>(null);
  const [corr, setCorr] = useState<CorrelationResponse | null>(null);
  const [alloc, setAlloc] = useState<AllocationResponse | null>(null);
  const [scaling, setScaling] = useState<ScalingResponse | null>(null);

  const canRun = backtestIds.length > 0 && !busy;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      if (model === "montecarlo") {
        const r = await runMontecarlo(backtestIds, null, simulations, initCash);
        setMc(r);
        track(EVENTS.PORTFOLIO_MONTECARLO_RUN, { simulations, init_cash: initCash, n_strategies: backtestIds.length });
      } else if (model === "correlation") {
        if (backtestIds.length < 2) throw new Error("Necesitas al menos 2 estrategias.");
        const r = await getCorrelation(backtestIds);
        setCorr(r);
        track(EVENTS.PORTFOLIO_CORRELATION_VIEWED, { n_strategies: backtestIds.length });
      } else if (model === "allocation") {
        const r = await getAllocation(backtestIds, allocMethod, lookback, null, initCash);
        setAlloc(r);
        track(EVENTS.PORTFOLIO_ALLOCATION_COMPUTED, { method: allocMethod, lookback_days: lookback });
      } else {
        const r = await runScaling(backtestIds, null, scalingMode, { initCash });
        setScaling(r);
        track(EVENTS.PORTFOLIO_SCALING_RUN, { mode: scalingMode });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al ejecutar el modelo.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) 2fr", gap: 16, alignItems: "start" }}>
      {/* 1/3 controls */}
      <div style={{ ...card, display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ec-text-high)", marginBottom: 8 }}>Modelos</div>
          {([
            ["montecarlo", "Montecarlo"],
            ["correlation", "Matriz de correlación"],
            ["scaling", "Escalado de cuenta"],
            ["allocation", "Asignación de capital"],
          ] as [Model, string][]).map(([m, lbl]) => (
            <label key={m} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", cursor: "pointer", fontSize: 13, color: "var(--color-ec-text-primary)" }}>
              <input type="radio" name="risk-model" checked={model === m} onChange={() => setModel(m)} />
              {lbl}
            </label>
          ))}
        </div>

        {model === "montecarlo" && (
          <>
            <div><span style={labelStyle}>Simulaciones</span>
              <input style={inputStyle} type="number" min={100} max={10000} value={simulations} onChange={(e) => setSimulations(Number(e.target.value))} /></div>
            <div><span style={labelStyle}>Capital inicial ($)</span>
              <input style={inputStyle} type="number" min={100} value={initCash} onChange={(e) => setInitCash(Number(e.target.value))} /></div>
          </>
        )}
        {model === "correlation" && (
          <div>
            <span style={labelStyle}>Coeficiente <InfoTip topic="correlation" /></span>
            <select style={inputStyle} value={corrKind} onChange={(e) => setCorrKind(e.target.value as "pearson" | "spearman")}>
              <option value="pearson">Pearson (lineal)</option>
              <option value="spearman">Spearman (no lineal)</option>
            </select>
          </div>
        )}
        {model === "scaling" && (
          <div>
            <span style={labelStyle}>Modo <InfoTip topic="kelly" /></span>
            <select style={inputStyle} value={scalingMode} onChange={(e) => setScalingMode(e.target.value as typeof scalingMode)}>
              <option value="kelly">Kelly (medio)</option>
              <option value="fixed_pct">% fijo</option>
              <option value="drawdown_stop">Parada por drawdown</option>
            </select>
          </div>
        )}
        {model === "allocation" && (
          <>
            <div>
              <span style={labelStyle}>Método <InfoTip topic="hrp" /></span>
              <select style={inputStyle} value={allocMethod} onChange={(e) => setAllocMethod(e.target.value as "leaders" | "hrp")}>
                <option value="hrp">HRP</option>
                <option value="leaders">Líderes</option>
              </select>
            </div>
            {allocMethod === "leaders" && (
              <div><span style={labelStyle}>Ventana (días)</span>
                <input style={inputStyle} type="number" min={2} value={lookback} onChange={(e) => setLookback(Number(e.target.value))} /></div>
            )}
          </>
        )}

        <button style={canRun ? btn : { ...btn, opacity: 0.5, cursor: "not-allowed" }} disabled={!canRun} onClick={run}>
          {busy ? "Ejecutando…" : "Ejecutar"}
        </button>
        {error && <div style={{ fontSize: 12, color: "var(--color-ec-loss)" }}>{error}</div>}
      </div>

      {/* 2/3 viz */}
      <div style={{ ...card, minHeight: 360, display: "flex", flexDirection: "column", gap: 14 }}>
        {model === "montecarlo" && <MontecarloViz data={mc} initCash={initCash} onAdd={onAddToRiskBox} />}
        {model === "correlation" && <CorrelationViz data={corr} kind={corrKind} />}
        {model === "scaling" && <ScalingViz data={scaling} onAdd={onAddToRiskBox} />}
        {model === "allocation" && <AllocationViz data={alloc} onAdd={onAddToRiskBox} />}
      </div>
    </div>
  );
}

function MetricRow({ label, value }: { label: React.ReactNode; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "4px 0", borderBottom: "1px solid var(--color-ec-border)" }}>
      <span style={{ color: "var(--color-ec-text-secondary)" }}>{label}</span>
      <span style={{ color: "var(--color-ec-text-high)" }}>{value}</span>
    </div>
  );
}

function MontecarloViz({ data, initCash, onAdd }: { data: MontecarloResponse | null; initCash: number; onAdd: Props["onAddToRiskBox"] }) {
  if (!data) return <Placeholder text="Ejecuta la simulación de Montecarlo sobre los retornos diarios agregados." />;
  const len = data.percentiles.p50?.length ?? 0;
  const rows = Array.from({ length: len }, (_, i) => ({
    i,
    p5: data.percentiles.p5?.[i], p25: data.percentiles.p25?.[i], p50: data.percentiles.p50?.[i],
    p75: data.percentiles.p75?.[i], p95: data.percentiles.p95?.[i],
  }));
  return (
    <>
      <div style={{ height: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows}>
            <CartesianGrid stroke="var(--color-ec-border)" strokeDasharray="3 3" />
            <XAxis dataKey="i" tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} />
            <YAxis tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} width={56} />
            <Tooltip contentStyle={{ background: "var(--color-ec-bg-elevated)", border: "1px solid var(--color-ec-border)", fontSize: 12 }} />
            <Line dataKey="p95" stroke="#5B8BB0" dot={false} strokeWidth={1} />
            <Line dataKey="p75" stroke="#4A9D7F" dot={false} strokeWidth={1} />
            <Line dataKey="p50" stroke="var(--color-ec-copper)" dot={false} strokeWidth={2} />
            <Line dataKey="p25" stroke="#C9A23F" dot={false} strokeWidth={1} />
            <Line dataKey="p5" stroke="#C94D3F" dot={false} strokeWidth={1} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <MetricRow label={<>VaR 95% <InfoTip topic="var" /></>} value={`${data.var_95_pct}% · $${data.var_95_usd}`} />
          <MetricRow label="VaR 99%" value={`${data.var_99_pct}% · $${data.var_99_usd}`} />
        </div>
        <div>
          <MetricRow label={<>CVaR 95% <InfoTip topic="cvar" /></>} value={`${data.cvar_95_pct}% · $${data.cvar_95_usd}`} />
          <MetricRow label="CVaR 99%" value={`${data.cvar_99_pct}% · $${data.cvar_99_usd}`} />
        </div>
      </div>
      <MetricRow label="Probabilidad de ruina" value={`${data.ruin_probability}%`} />
      <button style={ghostBtn} onClick={() => onAdd({
        metrics: { var_95_usd: data.var_95_usd, cvar_95_usd: data.cvar_95_usd, ruin_probability: data.ruin_probability },
        note: `Montecarlo · VaR95 $${data.var_95_usd} · ruina ${data.ruin_probability}%`,
      })}>Agregar a cuadro de riesgo</button>
    </>
  );
}

function CorrelationViz({ data, kind }: { data: CorrelationResponse | null; kind: "pearson" | "spearman" }) {
  if (!data) return <Placeholder text="Selecciona ≥2 estrategias y ejecuta para ver la matriz de correlación." />;
  const matrix = kind === "pearson" ? data.pearson : data.spearman;
  return (
    <>
      <HelpBanner topic="overfitting" />
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr><th />{data.labels.map((l) => <th key={l} style={{ padding: 6, color: "var(--color-ec-text-secondary)", maxWidth: 90, overflow: "hidden", textOverflow: "ellipsis" }}>{l}</th>)}</tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={i}>
                <td style={{ padding: 6, color: "var(--color-ec-text-secondary)", maxWidth: 90, overflow: "hidden", textOverflow: "ellipsis" }}>{data.labels[i]}</td>
                {row.map((v, j) => (
                  <td key={j} style={{ padding: "10px 12px", textAlign: "center", background: corrColor(v), color: "var(--color-ec-text-high)" }}>{v.toFixed(2)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: "var(--color-ec-text-muted)" }}>Rojo = +1 (sin diversificación) · Verde = -1 (cobertura). Días sin operación = 0%.</div>
    </>
  );
}

function ScalingViz({ data, onAdd }: { data: ScalingResponse | null; onAdd: Props["onAddToRiskBox"] }) {
  if (!data) return <Placeholder text="Simula cómo habría ido tu cuenta aplicando Kelly, % fijo o parada por drawdown." />;
  const rows = data.equity.map((value, i) => ({ i, value }));
  return (
    <>
      <div style={{ height: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows}>
            <CartesianGrid stroke="var(--color-ec-border)" strokeDasharray="3 3" />
            <XAxis dataKey="i" tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} />
            <YAxis tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} width={56} />
            <Tooltip contentStyle={{ background: "var(--color-ec-bg-elevated)", border: "1px solid var(--color-ec-border)", fontSize: 12 }} />
            <Area dataKey="value" stroke="var(--color-ec-copper)" fill="rgba(216,122,61,0.15)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <MetricRow label="PnL %" value={`${data.metrics.total_return_pct}%`} />
      <MetricRow label="Drawdown máx %" value={`${data.metrics.max_drawdown_pct}%`} />
      <button style={ghostBtn} onClick={() => onAdd({ metrics: data.metrics, note: "Escalado de cuenta" })}>Agregar a cuadro de riesgo</button>
    </>
  );
}

function AllocationViz({ data, onAdd }: { data: AllocationResponse | null; onAdd: Props["onAddToRiskBox"] }) {
  if (!data) return <Placeholder text="Calcula pesos óptimos (HRP o Líderes) y compáralos con tu cartera." />;
  const rows = data.comparison_equity.map((value, i) => ({ i, value }));
  return (
    <>
      <div style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows}>
            <CartesianGrid stroke="var(--color-ec-border)" strokeDasharray="3 3" />
            <XAxis dataKey="i" tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} />
            <YAxis tick={{ fontSize: 10, fill: "var(--color-ec-text-muted)" }} width={56} />
            <Tooltip contentStyle={{ background: "var(--color-ec-bg-elevated)", border: "1px solid var(--color-ec-border)", fontSize: 12 }} />
            <Area dataKey="value" stroke="var(--color-ec-copper)" fill="rgba(216,122,61,0.15)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", marginBottom: 6 }}>Pesos sugeridos</div>
        {Object.entries(data.weights).map(([id, w]) => (
          <MetricRow key={id} label={id.slice(0, 8)} value={`${(w * 100).toFixed(1)}%`} />
        ))}
      </div>
      <button style={ghostBtn} onClick={() => onAdd({ weights: data.weights, metrics: data.metrics, note: "Pesos guardados desde Asignación" })}>
        Guardar pesos en cuadro de riesgo
      </button>
    </>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", color: "var(--color-ec-text-muted)", fontSize: 13, padding: 24 }}>
      {text}
    </div>
  );
}
