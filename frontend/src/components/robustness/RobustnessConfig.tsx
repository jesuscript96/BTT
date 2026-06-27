"use client";

/**
 * Left panel: module selector + per-module configuration form.
 * Assembles the module-specific params and hands them to the client via onRun.
 */
import React, { useState } from "react";

export type ModuleKey = "montecarlo" | "wfo" | "sensitivity" | "blackswan";

export const MODULES: { key: ModuleKey; label: string }[] = [
  { key: "montecarlo", label: "Montecarlo" },
  { key: "wfo", label: "Walk-Forward" },
  { key: "sensitivity", label: "Sensibilidad" },
  { key: "blackswan", label: "Black Swan" },
];

const BORDER = "var(--color-ec-border)";
const SURFACE = "var(--color-ec-bg-surface)";
const MUTED = "var(--color-ec-text-muted)";
const TEXT = "var(--color-ec-text-primary)";
const COPPER = "var(--color-ec-copper)";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
      <span style={{ fontSize: 12, color: MUTED }}>{label}</span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--color-ec-bg-base)",
  border: `1px solid ${BORDER}`,
  borderRadius: 8,
  padding: "8px 10px",
  color: TEXT,
  fontSize: 13,
};

function Num({ value, onChange, step = 1, min }: { value: number; onChange: (v: number) => void; step?: number; min?: number }) {
  return (
    <input
      type="number"
      value={value}
      step={step}
      min={min}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      style={inputStyle}
    />
  );
}

export function RobustnessConfig({
  module,
  onModuleChange,
  onRun,
  running,
  disabled,
}: {
  module: ModuleKey;
  onModuleChange: (m: ModuleKey) => void;
  onRun: (params: Record<string, unknown>) => void;
  running: boolean;
  disabled: boolean;
}) {
  // Shared / per-module state.
  const [initCash, setInitCash] = useState(10000);
  const [simulations, setSimulations] = useState(1000);
  const [ruinPct, setRuinPct] = useState(10);
  const [nTrades, setNTrades] = useState(500);
  const [periodUnit, setPeriodUnit] = useState<string>("");

  const [locMin, setLocMin] = useState(0.5);
  const [locMax, setLocMax] = useState(3.0);
  const [locStep, setLocStep] = useState(0.5);
  const [slipProb, setSlipProb] = useState(15);
  const [slipVal, setSlipVal] = useState(0.02);

  const [swanCount, setSwanCount] = useState(3);
  const [severity, setSeverity] = useState(10);

  const [datasetId, setDatasetId] = useState("");
  const [isPct, setIsPct] = useState(70);
  const [oosPct, setOosPct] = useState(30);
  const [stepPct, setStepPct] = useState(30);
  const [metric, setMetric] = useState("sharpe");
  const [paramPath, setParamPath] = useState("");
  const [paramMin, setParamMin] = useState(10);
  const [paramMax, setParamMax] = useState(50);
  const [paramSteps, setParamSteps] = useState(5);

  const run = () => {
    switch (module) {
      case "montecarlo":
        return onRun({
          init_cash: initCash,
          simulations,
          ruin_pct: ruinPct,
          n_trades_limit: nTrades,
          period_unit: periodUnit || null,
        });
      case "sensitivity":
        return onRun({
          locate_range: { min: locMin, max: locMax, step: locStep },
          slippage_probability: slipProb,
          slippage_value: slipVal,
          init_cash: initCash,
        });
      case "blackswan":
        return onRun({
          init_cash: initCash,
          black_swan_count: swanCount,
          severity_multiplier: severity,
          ruin_pct: ruinPct,
        });
      case "wfo":
        return onRun({
          dataset_id: datasetId,
          is_pct: isPct,
          oos_pct: oosPct,
          step_pct: stepPct,
          metric,
          init_cash: initCash,
          param_configs: paramPath
            ? [{ id: paramPath.split(".").pop() || "param", path: paramPath, min: paramMin, max: paramMax, steps: paramSteps }]
            : [],
        });
    }
  };

  return (
    <div>
      {/* Module selector */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 18 }}>
        {MODULES.map((m) => (
          <button
            key={m.key}
            onClick={() => onModuleChange(m.key)}
            style={{
              background: module === m.key ? COPPER : SURFACE,
              color: module === m.key ? "#1A0A00" : TEXT,
              border: `1px solid ${module === m.key ? COPPER : BORDER}`,
              borderRadius: 8,
              padding: "7px 12px",
              fontSize: 12,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            {m.label}
          </button>
        ))}
      </div>

      {module === "montecarlo" && (
        <>
          <Field label="Capital inicial ($)"><Num value={initCash} onChange={setInitCash} step={1000} /></Field>
          <Field label="Simulaciones"><Num value={simulations} onChange={setSimulations} step={100} /></Field>
          <Field label="% Ruina (capital restante)"><Num value={ruinPct} onChange={setRuinPct} /></Field>
          <Field label="N trades (retorno negativo)"><Num value={nTrades} onChange={setNTrades} step={50} /></Field>
          <Field label="Equivalencia temporal (opcional)">
            <select value={periodUnit} onChange={(e) => setPeriodUnit(e.target.value)} style={inputStyle}>
              <option value="">— (usar N trades)</option>
              <option value="mes">Mes</option>
              <option value="trimestre">Trimestre</option>
              <option value="año">Año</option>
            </select>
          </Field>
        </>
      )}

      {module === "sensitivity" && (
        <>
          <Field label="Locate min (%)"><Num value={locMin} onChange={setLocMin} step={0.5} /></Field>
          <Field label="Locate max (%)"><Num value={locMax} onChange={setLocMax} step={0.5} /></Field>
          <Field label="Locate step (%)"><Num value={locStep} onChange={setLocStep} step={0.5} /></Field>
          <Field label="Prob. slippage (%)"><Num value={slipProb} onChange={setSlipProb} /></Field>
          <Field label="Valor slippage ($)"><Num value={slipVal} onChange={setSlipVal} step={0.01} /></Field>
        </>
      )}

      {module === "blackswan" && (
        <>
          <Field label="Capital inicial ($)"><Num value={initCash} onChange={setInitCash} step={1000} /></Field>
          <Field label="Nº Cisnes Negros"><Num value={swanCount} onChange={setSwanCount} /></Field>
          <Field label="Multiplicador de severidad"><Num value={severity} onChange={setSeverity} /></Field>
          <Field label="% Ruina"><Num value={ruinPct} onChange={setRuinPct} /></Field>
        </>
      )}

      {module === "wfo" && (
        <>
          <div style={{ fontSize: 11, color: "var(--color-ec-warning)", marginBottom: 12 }}>
            ⚠ El Walk-Forward es un proceso pesado: puede tardar varios minutos.
          </div>
          <Field label="Dataset ID"><input value={datasetId} onChange={(e) => setDatasetId(e.target.value)} style={inputStyle} placeholder="small_caps_historical" /></Field>
          <Field label="In-Sample (%)"><Num value={isPct} onChange={setIsPct} /></Field>
          <Field label="Out-of-Sample (%)"><Num value={oosPct} onChange={setOosPct} /></Field>
          <Field label="Step (%)"><Num value={stepPct} onChange={setStepPct} /></Field>
          <Field label="Métrica">
            <select value={metric} onChange={(e) => setMetric(e.target.value)} style={inputStyle}>
              <option value="sharpe">Sharpe</option>
              <option value="sortino">Sortino</option>
              <option value="return">Retorno</option>
              <option value="profit_factor">Profit Factor</option>
            </select>
          </Field>
          <Field label="Parámetro a optimizar (path)"><input value={paramPath} onChange={(e) => setParamPath(e.target.value)} style={inputStyle} placeholder="definition.indicators[0].params.period" /></Field>
          <div style={{ display: "flex", gap: 8 }}>
            <Field label="Min"><Num value={paramMin} onChange={setParamMin} /></Field>
            <Field label="Max"><Num value={paramMax} onChange={setParamMax} /></Field>
            <Field label="Steps"><Num value={paramSteps} onChange={setParamSteps} /></Field>
          </div>
        </>
      )}

      <button
        onClick={run}
        disabled={running || disabled}
        style={{
          width: "100%",
          marginTop: 8,
          background: running || disabled ? SURFACE : COPPER,
          color: running || disabled ? MUTED : "#1A0A00",
          border: "none",
          borderRadius: 8,
          padding: "11px 0",
          fontSize: 13,
          fontWeight: 600,
          cursor: running || disabled ? "not-allowed" : "pointer",
        }}
      >
        {running ? "Ejecutando…" : disabled ? "Selecciona una estrategia" : "Ejecutar prueba de robustez"}
      </button>
    </div>
  );
}
