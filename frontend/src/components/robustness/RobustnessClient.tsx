"use client";

/**
 * Robustness page orchestrator.
 *   • Top: select a saved strategy from the Baúl (backtest_results rows).
 *   • Bottom-left: module selector + config.
 *   • Bottom-right: results (spaghetti charts / matrices / metric cards).
 * Implements the 4 mandatory UI states (loading / empty / error / success) and
 * WFO polling. Emits PostHog events at every action site.
 */
import React, { useEffect, useRef, useState } from "react";
import { getSavedBacktests, ApiError } from "@/lib/api";
import { track, EVENTS } from "@/lib/analytics";
import {
  postMontecarlo,
  postSensitivity,
  postBlackSwan,
  startWalkForward,
  getWalkForwardResult,
  getWalkForwardProgress,
  type MontecarloRequest,
  type SensitivityRequest,
  type BlackSwanRequest,
  type WalkForwardRequest,
  type MontecarloResponse,
  type SensitivityResponse,
  type BlackSwanResponse,
  type WalkForwardResult,
} from "@/lib/api_robustness";
import { RobustnessConfig, type ModuleKey } from "./RobustnessConfig";
import { MontecarloCharts, SensitivityCharts, BlackSwanCharts, WalkForwardCharts } from "./RobustnessCharts";

interface SavedRun {
  id: string;
  strategy_names?: string[];
  total_trades?: number;
  win_rate?: number;
  total_return_pct?: number;
  total_return_r?: number;
  executed_at?: string;
}

type Result =
  | { module: "montecarlo"; data: MontecarloResponse }
  | { module: "sensitivity"; data: SensitivityResponse }
  | { module: "blackswan"; data: BlackSwanResponse }
  | { module: "wfo"; data: WalkForwardResult };

const MUTED = "var(--color-ec-text-muted)";
const TEXT = "var(--color-ec-text-primary)";
const BORDER = "var(--color-ec-border)";
const SURFACE = "var(--color-ec-bg-surface)";
const COPPER = "var(--color-ec-copper)";

export function RobustnessClient() {
  const [runs, setRuns] = useState<SavedRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [module, setModule] = useState<ModuleKey>("montecarlo");

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getSavedBacktests(100)
      .then((r) => setRuns(r.strategies || []))
      .catch(() => setError("No se pudieron cargar las estrategias del Baúl."))
      .finally(() => setLoadingRuns(false));
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const selectRun = (id: string) => {
    setSelected(id);
    setResult(null);
    setError(null);
    track(EVENTS.ROBUSTNESS_STRATEGY_SELECTED, { run_id: id });
  };

  const changeModule = (m: ModuleKey) => {
    setModule(m);
    setResult(null);
    setError(null);
    track(EVENTS.ROBUSTNESS_MODULE_VIEWED, { module: m });
  };

  const handleError = (e: unknown) => {
    const msg = e instanceof ApiError ? e.message : "Error al ejecutar el análisis.";
    setError(msg);
    setRunning(false);
    setProgress(null);
  };

  const onRun = async (params: Record<string, unknown>) => {
    if (!selected) return;
    setRunning(true);
    setError(null);
    setResult(null);
    setProgress(null);
    try {
      if (module === "montecarlo") {
        track(EVENTS.ROBUSTNESS_MONTECARLO_RUN, { run_id: selected, simulations: params.simulations, period_unit: params.period_unit });
        const data = await postMontecarlo({ run_id: selected, ...params } as MontecarloRequest);
        setResult({ module: "montecarlo", data });
      } else if (module === "sensitivity") {
        track(EVENTS.ROBUSTNESS_SENSITIVITY_RUN, { run_id: selected });
        const data = await postSensitivity({ run_id: selected, ...params } as SensitivityRequest);
        setResult({ module: "sensitivity", data });
      } else if (module === "blackswan") {
        track(EVENTS.ROBUSTNESS_BLACKSWAN_RUN, { run_id: selected, severity_multiplier: params.severity_multiplier });
        const data = await postBlackSwan({ run_id: selected, ...params } as BlackSwanRequest);
        setResult({ module: "blackswan", data });
      } else {
        track(EVENTS.ROBUSTNESS_WFO_RUN, { run_id: selected, metric: params.metric });
        await runWalkForward(params);
        return; // polling owns the running state
      }
      setRunning(false);
    } catch (e) {
      handleError(e);
    }
  };

  const runWalkForward = async (params: Record<string, unknown>) => {
    const { task_id } = await startWalkForward({ run_id: selected!, ...params } as WalkForwardRequest);
    setProgress(0);
    pollRef.current = setInterval(async () => {
      try {
        const res = await getWalkForwardResult(task_id);
        if (res.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          handleError(new ApiError(500, res.message || "El Walk-Forward falló."));
          return;
        }
        if (res.status === "completed" || res.wfe !== undefined) {
          if (pollRef.current) clearInterval(pollRef.current);
          setResult({ module: "wfo", data: res });
          setRunning(false);
          setProgress(null);
          return;
        }
        const p = await getWalkForwardProgress(task_id);
        setProgress(p.progress);
      } catch (e) {
        if (pollRef.current) clearInterval(pollRef.current);
        handleError(e);
      }
    }, 2000);
  };

  return (
    <div style={{ padding: "28px 32px", color: TEXT, maxWidth: 1400, margin: "0 auto" }}>
      <h1 style={{ fontFamily: "var(--font-fraunces, serif)", fontSize: 26, marginBottom: 4 }}>Robustez de Estrategias</h1>
      <p style={{ color: MUTED, fontSize: 13, marginBottom: 20 }}>
        Somete una estrategia del Baúl a Montecarlo, Walk-Forward, sensibilidad de costes y Cisnes Negros.
      </p>

      {/* [1] Baúl grid */}
      <div style={{ background: SURFACE, borderRadius: 12, padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 12, color: MUTED, marginBottom: 10 }}>1 · Selecciona una estrategia del Baúl</div>
        {loadingRuns ? (
          <SkeletonRows />
        ) : runs.length === 0 ? (
          <div style={{ color: MUTED, fontSize: 13, padding: 12 }}>No hay estrategias guardadas en el Baúl todavía.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ color: MUTED, textAlign: "left" }}>
                  {["Estrategia", "Trades", "Win Rate", "Retorno", "Ejecutado", ""].map((h) => (
                    <th key={h} style={{ padding: "6px 10px", fontWeight: 500, fontSize: 11 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} style={{ borderTop: `1px solid ${BORDER}`, background: selected === r.id ? "var(--color-ec-bg-elevated)" : "transparent" }}>
                    <td style={{ padding: "8px 10px" }}>{(r.strategy_names || []).join(", ") || r.id.slice(0, 8)}</td>
                    <td style={{ padding: "8px 10px" }}>{r.total_trades ?? "—"}</td>
                    <td style={{ padding: "8px 10px" }}>{r.win_rate != null ? `${r.win_rate.toFixed(1)}%` : "—"}</td>
                    <td style={{ padding: "8px 10px", color: (r.total_return_pct ?? 0) >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)" }}>
                      {r.total_return_pct != null ? `${r.total_return_pct.toFixed(1)}%` : "—"}
                    </td>
                    <td style={{ padding: "8px 10px", color: MUTED }}>{r.executed_at ? String(r.executed_at).slice(0, 10) : "—"}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <button
                        onClick={() => selectRun(r.id)}
                        style={{
                          background: selected === r.id ? COPPER : "transparent",
                          color: selected === r.id ? "#1A0A00" : TEXT,
                          border: `1px solid ${selected === r.id ? COPPER : BORDER}`,
                          borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer",
                        }}
                      >
                        {selected === r.id ? "Seleccionada" : "Seleccionar"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* [2]/[3] config + results */}
      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20, alignItems: "start" }}>
        <div style={{ background: SURFACE, borderRadius: 12, padding: 18 }}>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 14 }}>2 · Configuración</div>
          <RobustnessConfig module={module} onModuleChange={changeModule} onRun={onRun} running={running} disabled={!selected} />
        </div>

        <div style={{ background: SURFACE, borderRadius: 12, padding: 20, minHeight: 380 }}>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 14 }}>3 · Resultados</div>
          {running && <RunningState progress={progress} />}
          {!running && error && <ErrorState message={error} />}
          {!running && !error && !result && <EmptyState hasSelection={!!selected} />}
          {!running && !error && result?.module === "montecarlo" && <MontecarloCharts data={result.data} />}
          {!running && !error && result?.module === "sensitivity" && <SensitivityCharts data={result.data} />}
          {!running && !error && result?.module === "blackswan" && <BlackSwanCharts data={result.data} />}
          {!running && !error && result?.module === "wfo" && <WalkForwardCharts data={result.data} />}
        </div>
      </div>
    </div>
  );
}

const SkeletonRows = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    {[0, 1, 2].map((i) => (
      <div key={i} style={{ height: 32, borderRadius: 6, background: "var(--color-ec-bg-elevated)", opacity: 0.5 }} />
    ))}
  </div>
);

const RunningState = ({ progress }: { progress: number | null }) => (
  <div style={{ textAlign: "center", padding: "60px 0", color: MUTED }}>
    <div style={{ fontSize: 14, marginBottom: 12 }}>Ejecutando análisis…</div>
    {progress !== null && (
      <div style={{ maxWidth: 320, margin: "0 auto" }}>
        <div style={{ height: 8, background: "var(--color-ec-bg-base)", borderRadius: 4, overflow: "hidden" }}>
          <div style={{ width: `${progress}%`, height: "100%", background: COPPER, transition: "width .3s" }} />
        </div>
        <div style={{ fontSize: 12, marginTop: 6 }}>{progress.toFixed(0)}%</div>
      </div>
    )}
  </div>
);

const EmptyState = ({ hasSelection }: { hasSelection: boolean }) => (
  <div style={{ textAlign: "center", padding: "80px 20px", color: MUTED, fontSize: 14 }}>
    {hasSelection
      ? "Configura el módulo y pulsa “Ejecutar” para iniciar el análisis de robustez."
      : "Selecciona una estrategia del Baúl y pulsa “Ejecutar” para iniciar el análisis de robustez."}
  </div>
);

const ErrorState = ({ message }: { message: string }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, background: "rgba(201,77,63,0.12)", border: "1px solid var(--color-ec-loss)", borderRadius: 8, padding: "14px 16px", color: "var(--color-ec-loss)", fontSize: 13 }}>
    <span style={{ fontSize: 18 }}>⚠</span>
    <span>{message}</span>
  </div>
);
