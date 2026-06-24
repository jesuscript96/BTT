"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import {
  fetchOptimizationParams,
  runOptimizationSurface,
  fetchOptimizationProgress,
  fetchOptimizationResult,
  cancelOptimization,
  type OptimizationParam,
  type OptimizationResult,
  type OptimizationParamConfig,
} from "@/lib/api_backtester";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = dynamic(
  async () => {
    // @ts-ignore
    const Plotly = await import("plotly.js-dist-min");
    // @ts-ignore
    const factory = await import("react-plotly.js/factory");
    const createPlotComponent = (factory as any).default;
    return { default: createPlotComponent(Plotly) };
  },
  { ssr: false }
) as any;

const METRIC_OPTIONS = [
  { value: "sharpe", label: "Sharpe Ratio" },
  { value: "total_return", label: "Total Return %" },
  { value: "expectancy", label: "Expected Value (EV)" },
  { value: "dd_return", label: "DD / Return" },
  { value: "avg_r_ui", label: "AVG Y/U.Index" },
];

interface OptimizationSurfaceTabProps {
  strategyId: string;
  strategyDefinition?: Record<string, unknown>;
  datasetId: string;
  isDarkMode?: boolean;
  backtestParams?: Record<string, unknown>;
}

export default function OptimizationSurfaceTab({
  strategyId,
  strategyDefinition,
  datasetId,
  isDarkMode = false,
  backtestParams = {},
}: OptimizationSurfaceTabProps) {
  const [params, setParams] = useState<OptimizationParam[]>([]);
  const [strategyName, setStrategyName] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingParams, setLoadingParams] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [visualProgress, setVisualProgress] = useState<number>(0);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  const pollIntervalRef = useRef<number | null>(null);

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        window.clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const startPolling = useCallback((taskId: string, currentMetric: string) => {
    setActiveTaskId(taskId);
    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current);
    }

    let consecutiveErrors = 0;
    const maxErrors = 5;

    const interval = window.setInterval(async () => {
      try {
        const res = await fetchOptimizationResult(taskId);
        consecutiveErrors = 0; // Reset error count on successful request

        if ("status" in res && res.status === "running") {
          setProgress(res.progress);
          setVisualProgress((prev) => {
            if (res.progress <= 0) {
              return Math.min(8, prev + 1);
            } else if (res.progress <= 1) {
              return Math.min(15, prev + 1.5);
            } else if (res.progress <= 2) {
              return Math.min(25, Math.max(prev, 15) + 1.2);
            } else if (res.progress <= 5) {
              return Math.min(35, Math.max(prev, 25) + 1.0);
            } else {
              const scaled = 35 + (65 * (res.progress - 5)) / 95;
              return Math.max(prev, scaled);
            }
          });
        } else {
          if (pollIntervalRef.current) window.clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
          localStorage.removeItem("active_optimization_task");
          setActiveTaskId(null);
          setProgress(100);
          setVisualProgress(100);
          setTimeout(() => {
            setResult(res as OptimizationResult);
            setLoading(false);
          }, 300);
        }
      } catch (e: any) {
        consecutiveErrors++;
        console.warn(`Error polling optimization result (attempt ${consecutiveErrors}/${maxErrors}):`, e);

        if (consecutiveErrors >= maxErrors) {
          if (pollIntervalRef.current) window.clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
          localStorage.removeItem("active_optimization_task");
          setActiveTaskId(null);
          console.error("Error polling optimization result", e);
          const msg = e.response?.data?.detail || e.message || "Error al recuperar resultados de optimización";
          setError(msg);
          setLoading(false);
        }
      }
    }, 800);

    pollIntervalRef.current = interval;
  }, []);

  // Config state
  const [mode, setMode] = useState<"2D" | "3D">("2D");
  const [metric, setMetric] = useState("sharpe");
  const [paramX, setParamX] = useState("");
  const [paramY, setParamY] = useState("");
  const [gridSteps, setGridSteps] = useState(10);

  // Range state per axis
  const [rangeX, setRangeX] = useState<[number, number]>([0, 20]);
  const [rangeY, setRangeY] = useState<[number, number]>([0, 20]);

  // Load parameters when strategy changes
  useEffect(() => {
    if (!strategyId) return;

    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    setLoadingParams(true);
    setError(null);
    setResult(null); // Clear old optimization result when strategy changes
    setParamX("");
    setParamY("");
    fetchOptimizationParams(strategyId, strategyDefinition)
      .then((res) => {
        setParams(res.parameters);
        setStrategyName(res.strategy_name);
        if (res.parameters.length >= 2) {
          setParamX(res.parameters[0].id);
          setParamY(res.parameters[1].id);
          setRangeX([res.parameters[0].min, res.parameters[0].max]);
          setRangeY([res.parameters[1].min, res.parameters[1].max]);
        }
      })
      .catch(() => setError("Error loading strategy parameters"))
      .finally(() => setLoadingParams(false));
  }, [strategyId, strategyDefinition]);

  // Load active task from localStorage on mount/strategy change
  useEffect(() => {
    if (!strategyId || !datasetId) return;
    const rawTask = localStorage.getItem("active_optimization_task");
    if (!rawTask) return;
    try {
      const taskState = JSON.parse(rawTask);
      if (taskState.strategyId === strategyId && taskState.datasetId === datasetId) {
        setMetric(taskState.metric);
        setParamX(taskState.paramX);
        setParamY(taskState.paramY);
        setRangeX(taskState.rangeX);
        setRangeY(taskState.rangeY);
        setGridSteps(taskState.gridSteps);
        
        // Start polling the existing taskId
        startPolling(taskState.taskId, taskState.metric);
      }
    } catch (e) {
      console.warn("Failed to parse active optimization task from localStorage", e);
      localStorage.removeItem("active_optimization_task");
    }
  }, [strategyId, datasetId, startPolling]);

  // Update ranges when param selection changes
  const getParamById = useCallback(
    (id: string) => params.find((p) => p.id === id),
    [params]
  );

  useEffect(() => {
    const p = getParamById(paramX);
    if (p) setRangeX([p.min, p.max]);
  }, [paramX, getParamById]);

  useEffect(() => {
    const p = getParamById(paramY);
    if (p) setRangeY([p.min, p.max]);
  }, [paramY, getParamById]);

  const handleRun = async () => {
    if (!paramX || !paramY) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setProgress(0);
    setVisualProgress(0);

    const taskId = `opt_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

    const pX = getParamById(paramX);
    const pY = getParamById(paramY);
    if (!pX || !pY) {
      setLoading(false);
      return;
    }

    const configs: OptimizationParamConfig[] = [
      { id: pX.id, label: pX.label, path: pX.path, min: rangeX[0], max: rangeX[1], steps: gridSteps },
      { id: pY.id, label: pY.label, path: pY.path, min: rangeY[0], max: rangeY[1], steps: gridSteps },
    ];

    try {
      const taskState = {
        taskId,
        strategyId,
        strategyDefinition,
        datasetId,
        metric,
        paramX,
        paramY,
        rangeX,
        rangeY,
        gridSteps
      };
      localStorage.setItem("active_optimization_task", JSON.stringify(taskState));

      await runOptimizationSurface({
        strategy_id: strategyId,
        strategy_definition: strategyDefinition,
        dataset_id: datasetId,
        metric,
        param_configs: configs,
        task_id: taskId,
        ...backtestParams,
      });

      startPolling(taskId, metric);

    } catch (err: any) {
      if (pollIntervalRef.current) window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
      localStorage.removeItem("active_optimization_task");
      setActiveTaskId(null);
      console.error("Error starting optimization:", err);
      const msg = err.response?.data?.detail || err.message || "Error al iniciar la optimización";
      setError(msg);
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!activeTaskId) return;
    try {
      await cancelOptimization(activeTaskId);
    } catch (e) {
      console.warn("Error cancelando la optimización:", e);
    }
    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    localStorage.removeItem("active_optimization_task");
    setActiveTaskId(null);
    setProgress(0);
    setVisualProgress(0);
    setLoading(false);
    setError("Optimización cancelada por el usuario.");
  };

  // Plotly data
  const plotData = useMemo(() => {
    if (!result) return null;
    const p = result.params;
    const metricLabel = METRIC_OPTIONS.find((m) => m.value === metric)?.label || metric;

    const bg = "#16181A";
    const fg = "#D4D2CF";
    const gridColor = "#2C2F33";

    // Reconstruct the 2D grid for the currently selected metric from the details list
    const shape = result.shape;
    const details = result.details;
    const rows = shape[0];
    const cols = shape[1];

    const grid: (number | null)[][] = [];
    for (let c = 0; c < cols; c++) {
      const row: (number | null)[] = [];
      for (let r = 0; r < rows; r++) {
        const idx = r * cols + c;
        const val = details[idx]?.[metric];
        row.push(val !== undefined && val !== null && !isNaN(val) ? val : null);
      }
      grid.push(row);
    }

    if (mode === "2D" && p.length === 2) {
      const x = p[0].values;
      const y = p[1].values;

      return {
        data: [
          {
            z: grid,
            x,
            y,
            type: "contour" as const,
            colorscale: "Viridis",
            contours: { coloring: "heatmap" as const, showlabels: true },
            colorbar: {
              title: { text: metricLabel, font: { color: fg, size: 10 } },
              tickfont: { color: fg, size: 9 },
            },
            hovertemplate:
              `${p[0].label}: %{x:.2f}<br>${p[1].label}: %{y:.2f}<br>${metricLabel}: %{z:.4f}<extra></extra>`,
          },
        ],
        layout: {
          paper_bgcolor: bg,
          plot_bgcolor: bg,
          font: { color: fg, family: "'JetBrains Mono', monospace", size: 10 },
          xaxis: { title: { text: p[0].label }, gridcolor: gridColor, color: fg },
          yaxis: { title: { text: p[1].label }, gridcolor: gridColor, color: fg },
          margin: { l: 60, r: 20, t: 30, b: 60 },
          autosize: true,
        },
      };
    }

    if (mode === "3D" && p.length === 2) {
      // For 3D surface, replace nulls to avoid WebGL crashes (uniformMatrix4fv error)
      const validVals = grid.flat().filter((v): v is number => v !== null && !isNaN(v));
      const minVal = validVals.length > 0 ? Math.min(...validVals) : 0;
      const z = grid.map((row) => row.map((v) => (v === null ? minVal : v)));

      const x = p[0].values;
      const y = p[1].values;

      return {
        data: [
          {
            z,
            x,
            y,
            type: "surface" as const,
            colorscale: "Viridis",
            colorbar: {
              title: { text: metricLabel, font: { color: fg, size: 10 } },
              tickfont: { color: fg, size: 9 },
            },
            hovertemplate:
              `${p[0].label}: %{x:.2f}<br>${p[1].label}: %{y:.2f}<br>${metricLabel}: %{z:.4f}<extra></extra>`,
            lighting: { ambient: 0.6, diffuse: 0.5, specular: 0.3, roughness: 0.8 },
          },
        ],
        layout: {
          paper_bgcolor: bg,
          plot_bgcolor: bg,
          font: { color: fg, family: "'JetBrains Mono', monospace", size: 10 },
          scene: {
            xaxis: { title: { text: p[0].label }, gridcolor: gridColor, color: fg, backgroundcolor: bg },
            yaxis: { title: { text: p[1].label }, gridcolor: gridColor, color: fg, backgroundcolor: bg },
            zaxis: { title: { text: metricLabel }, gridcolor: gridColor, color: fg, backgroundcolor: bg },
            bgcolor: bg,
          },
          margin: { l: 0, r: 0, t: 30, b: 0 },
          autosize: true,
        },
      };
    }

    return null;
  }, [result, mode, metric, isDarkMode]);

  const pa = result?.plateau_analyses?.[metric] || result?.plateau_analysis;

  if (!strategyId || !datasetId) {
    return (
      <div className="flex items-center justify-center h-40">
        <p className="text-[11px] text-[var(--color-ec-text-secondary)] font-mono">
          Ejecuta un backtest para acceder a la Optimization Surface
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6" style={{ paddingTop: '20px' }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-semibold text-[var(--color-ec-text-secondary)] uppercase tracking-[0.12em]">
            Optimization Surface
          </span>
          {strategyName && (
            <span className="text-[10px] text-[var(--color-ec-text-muted)] font-mono opacity-80">{strategyName}</span>
          )}
        </div>
      </div>

      {/* Configuration — flat grid, no card wrapper */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-4">
        {/* Mode toggle */}
        <div>
          <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase">Modo</label>
          <div className="flex bg-[var(--color-ec-bg-elevated)] rounded border border-[var(--color-ec-border)] h-[28px] p-[2px]" style={{ marginTop: '2px' }}>
            {(["2D", "3D"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 flex items-center justify-center text-[10px] font-mono font-bold rounded transition-colors cursor-pointer ${
                  mode === m
                    ? "bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)] shadow-sm"
                    : "text-[var(--color-ec-text-muted)] hover:text-[var(--color-ec-text-primary)]"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        {/* Metric */}
        <div>
          <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase">Metrica</label>
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="w-full h-[28px] bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono cursor-pointer"
            style={{ marginTop: '2px' }}
          >
            {METRIC_OPTIONS.map((o) => (
              <option key={o.value} value={o.value} className="bg-[var(--color-ec-bg-elevated)] text-[var(--color-ec-text-high)]">{o.label}</option>
            ))}
          </select>
        </div>

        {/* Param X */}
        <div>
          <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase">Eje X</label>
          <select
            value={paramX}
            onChange={(e) => setParamX(e.target.value)}
            className="w-full h-[28px] bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono cursor-pointer"
            style={{ marginTop: '2px' }}
          >
            {params.filter((p) => p.id !== paramY).map((p) => (
              <option key={p.id} value={p.id} className="bg-[var(--color-ec-bg-elevated)] text-[var(--color-ec-text-high)]">{p.label}</option>
            ))}
          </select>
        </div>

        {/* Param Y */}
        <div>
          <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase">Eje Y</label>
          <select
            value={paramY}
            onChange={(e) => setParamY(e.target.value)}
            className="w-full h-[28px] bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono cursor-pointer"
            style={{ marginTop: '2px' }}
          >
            {params.filter((p) => p.id !== paramX).map((p) => (
              <option key={p.id} value={p.id} className="bg-[var(--color-ec-bg-elevated)] text-[var(--color-ec-text-high)]">{p.label}</option>
            ))}
          </select>
        </div>

        {/* Grid steps */}
        <div>
          <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase">Resolución</label>
          <select
            value={gridSteps}
            onChange={(e) => setGridSteps(Number(e.target.value))}
            className="w-full h-[28px] bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2.5 text-[11px] text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono cursor-pointer"
            style={{ marginTop: '2px' }}
          >
            {[5, 8, 10, 12, 15, 20].map((n) => (
              <option key={n} value={n} className="bg-[var(--color-ec-bg-elevated)] text-[var(--color-ec-text-high)]">{n}×{n} ({n*n} pts)</option>
            ))}
          </select>
        </div>

        {/* Run button */}
        <div>
          <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 opacity-0 pointer-events-none font-mono uppercase">Accion</label>
          <button
            onClick={handleRun}
            disabled={loading || !paramX || !paramY}
            className="w-full h-[28px] bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)] hover:bg-[var(--color-ec-copper-bright)] rounded text-[11px] font-mono font-bold uppercase tracking-[0.1em] flex items-center justify-center transform active:scale-[0.98] transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
            style={{ marginTop: '2px' }}
          >
            {loading ? "..." : "Ejecutar"}
          </button>
        </div>
      </div>

      {/* Range sliders */}
      {(paramX || paramY) && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4" style={{ marginTop: '20px' }}>
          {paramX && (
            <RangeSlider
              label={getParamById(paramX)?.label || "X"}
              value={rangeX}
              onChange={setRangeX}
              param={getParamById(paramX)}
              gridSteps={gridSteps}
            />
          )}
          {paramY && (
            <RangeSlider
              label={getParamById(paramY)?.label || "Y"}
              value={rangeY}
              onChange={setRangeY}
              param={getParamById(paramY)}
              gridSteps={gridSteps}
            />
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="py-2" style={{ borderTop: '1px solid rgba(239,68,68,0.3)' }}>
          <p className="text-[11px] text-[var(--danger)] font-mono">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center h-64">
          <div className="text-center space-y-4 w-full max-w-xs px-6">
            <svg className="animate-spin h-5 w-5 text-[var(--color-ec-text-secondary)] mx-auto" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <div className="space-y-3">
              <div className="flex justify-between items-end mb-1">
                <p className="text-[11px] font-mono text-[var(--color-ec-text-primary)]">
                  {progress <= 5 ? "Cargando dataset..." : "Optimizando..."}
                </p>
                <span className="text-[11px] font-mono text-[var(--color-ec-text-high)] font-bold">
                  {Math.round(visualProgress)}%
                </span>
              </div>
              <div className="h-[2px] w-full bg-[var(--color-ec-border)] overflow-hidden">
                <div
                  className="h-full bg-[var(--color-ec-copper)] transition-all duration-300 ease-out"
                  style={{ width: `${visualProgress}%` }}
                />
              </div>
              <p className="text-[9px] text-[var(--color-ec-text-muted)] uppercase tracking-wider font-mono">
                {progress <= 5
                  ? "Inicializando datos de mercado..."
                  : `Procesando: ${Math.min(gridSteps * gridSteps, Math.round(((progress - 5) / 95) * (gridSteps * gridSteps)))} / ${gridSteps * gridSteps} backtests`}
              </p>
            </div>
            {activeTaskId && (
              <button
                onClick={handleCancel}
                className="mt-4 px-4 py-2 bg-transparent border border-[var(--color-ec-border)] hover:border-[var(--color-ec-copper)] rounded text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ec-text-muted)] hover:text-[var(--color-ec-text-primary)] transition-all cursor-pointer mx-auto flex items-center justify-center"
              >
                Cancelar optimización
              </button>
            )}
          </div>
        </div>
      )}

      {/* Informative introductory panel shown when not loading and no result exists */}
      {!result && !loading && (
        <div 
          className="max-w-4xl mx-auto w-full flex flex-col items-center justify-center text-center pb-16 px-6 animate-in fade-in slide-in-from-bottom-4 duration-300"
          style={{ marginTop: '32px' }}
        >
          
          {/* Warning banner - simple warning text, no background box */}
          <div className="w-full flex flex-col items-center justify-center text-center space-y-2" style={{ marginBottom: '3px' }}>
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-[var(--color-ec-loss)] font-mono flex items-center justify-center gap-1.5">
              <span>⚠️</span> Advertencia de Tiempo de Ejecución
            </h4>
            <p className="text-[11px] text-[var(--color-ec-text-secondary)] leading-relaxed max-w-xl text-center">
              Este modelo de optimización requiere <strong>una gran cantidad de tiempo</strong> de procesamiento. Para generar la superficie, el servidor debe simular <strong>un backtest completo por cada combinación de la cuadrícula</strong> (por ejemplo, una resolución de 10×10 ejecuta 100 simulaciones).
            </p>
          </div>

          {/* Three columns directly on the background */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10 text-center w-full" style={{ marginTop: '3px' }}>
            {/* Column 1: Qué va a hacer */}
            <div className="space-y-3">
              <div className="flex flex-col items-center gap-1.5">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-[rgba(212,143,56,0.1)] text-[var(--color-ec-copper)] text-[10px] font-bold font-mono">1</span>
                <h4 className="text-[11px] font-bold uppercase tracking-wider text-[var(--color-ec-text-primary)] font-mono">¿Qué hace esto?</h4>
              </div>
              <p className="text-[11px] text-[var(--color-ec-text-muted)] leading-relaxed">
                Cruza dos variables de tu estrategia para evaluar su rendimiento en todas las combinaciones posibles.
                <span className="text-[9px] text-[var(--color-ec-copper)] font-mono block mt-2 opacity-90">
                  <strong>Ejemplo:</strong> Probar periodos de SMA de 10 a 50 contra valores de Stop Loss de 1% a 5%.
                </span>
              </p>
            </div>

            {/* Column 2: Qué vas a ver */}
            <div className="space-y-3">
              <div className="flex flex-col items-center gap-1.5">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-[rgba(212,143,56,0.1)] text-[var(--color-ec-copper)] text-[10px] font-bold font-mono">2</span>
                <h4 className="text-[11px] font-bold uppercase tracking-wider text-[var(--color-ec-text-primary)] font-mono">¿Qué vas a ver?</h4>
              </div>
              <p className="text-[11px] text-[var(--color-ec-text-muted)] leading-relaxed">
                Un mapa topográfico interactivo en 3D o 2D. Las "montañas" son zonas rentables y los "valles" representan pérdidas.
                <span className="text-[9px] text-[var(--color-ec-copper)] font-mono block mt-2 opacity-90">
                  <strong>Ejemplo:</strong> Verás si el Sharpe Ratio de tu estrategia sube o baja al variar conjuntamente la SMA y el Stop Loss.
                </span>
              </p>
            </div>

            {/* Column 3: Para qué sirve */}
            <div className="space-y-3">
              <div className="flex flex-col items-center gap-1.5">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-[rgba(212,143,56,0.1)] text-[var(--color-ec-copper)] text-[10px] font-bold font-mono">3</span>
                <h4 className="text-[11px] font-bold uppercase tracking-wider text-[var(--color-ec-text-primary)] font-mono">¿Para qué sirve?</h4>
              </div>
              <p className="text-[11px] text-[var(--color-ec-text-muted)] leading-relaxed">
                Sirve para encontrar <strong>plateaus (zonas estables)</strong> en lugar de picos aislados (sobreajuste), lo que da robustez en real.
                <span className="text-[9px] text-[var(--color-ec-copper)] font-mono block mt-2 opacity-90">
                  <strong>Ejemplo:</strong> Si tu estrategia funciona bien en SMA 20, 21 y 22, es robusta. Si solo funciona en SMA 20, es sobreajuste.
                </span>
              </p>
            </div>
          </div>

        </div>
      )}

      {/* Results */}
      {result && plotData && !loading && (
        <div className="flex gap-6 flex-col lg:flex-row">
          {/* Chart */}
          <div className="lg:w-2/3 min-h-[500px] flex flex-col">
            <Plot
              data={plotData.data}
              layout={{
                ...plotData.layout,
                autosize: true,
              }}
              config={{
                responsive: true,
                displayModeBar: true,
                displaylogo: false,
                modeBarButtonsToRemove: ["sendDataToCloud", "lasso2d", "select2d"],
              }}
              useResizeHandler
              style={{ width: "100%", flex: 1, minHeight: "500px" }}
            />
          </div>

          {/* Analysis panel */}
          <div className="lg:w-1/3 space-y-4">
            {/* Elapsed */}
            <div className="text-[10px] text-[var(--color-ec-text-secondary)] text-right font-mono">
              {result.elapsed_seconds}s / {result.shape.reduce((a: number, b: number) => a * b, 1)} runs
            </div>

            {/* Peak */}
            {pa?.peak && (
              <AnalysisCard
                title="Peak"
                isDarkMode={isDarkMode}
                items={[
                  { label: "Value", value: fmt(pa.peak.value) },
                  ...Object.entries(pa.peak.coordinates).map(([k, v]) => ({
                    label: k,
                    value: fmt(v),
                  })),
                ]}
              />
            )}

            {/* Robust Plateau */}
            {pa?.robust_plateau && (
              <AnalysisCard
                title="Robust Plateau"
                subtitle="Lowest sensitivity region"
                isDarkMode={isDarkMode}
                items={[
                  { label: "Mean", value: fmt(pa.robust_plateau.mean_value) },
                  { label: "Std Dev", value: fmt(pa.robust_plateau.std_value) },
                  { label: "Size", value: String(pa.robust_plateau.size) },
                  { label: "PF", value: fmt(pa.robust_plateau.profit_factor) },
                  { label: "DD/Ret", value: fmt(pa.robust_plateau.return_dd) },
                  { label: "Return %", value: fmt(pa.robust_plateau.total_return) },
                ]}
              />
            )}

            {/* Local Stability */}
            {pa?.local_stability && (
              <AnalysisCard
                title="Local Stability"
                subtitle="Neighbor-averaged maximum"
                isDarkMode={isDarkMode}
                items={[
                  { label: "Value", value: fmt(pa.local_stability.best_value) },
                  ...Object.entries(pa.local_stability.coordinates).map(([k, v]) => ({
                    label: k,
                    value: fmt(v),
                  })),
                  { label: "PF", value: fmt(pa.local_stability.profit_factor) },
                  { label: "DD/Ret", value: fmt(pa.local_stability.return_dd) },
                ]}
              />
            )}

            {/* Robust Center */}
            {pa?.robust_center && (
              <AnalysisCard
                title="Robust Center"
                subtitle="Geometric center of stable plateau"
                isDarkMode={isDarkMode}
                items={[
                  ...Object.entries(pa.robust_center.coordinates).map(([k, v]) => ({
                    label: k,
                    value: fmt(v),
                  })),
                  {
                    label: "Degradation",
                    value: fmt(pa.robust_center.degradation_from_peak),
                    highlight: true,
                  },
                ]}
              />
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {loadingParams && (
        <div className="flex items-center justify-center h-40">
          <p className="text-[11px] text-[var(--color-ec-text-secondary)] animate-pulse font-mono">
            detecting parameters...
          </p>
        </div>
      )}

      {!result && !loading && !loadingParams && params.length > 0 && (
        <div className="flex items-center justify-center h-40" style={{ borderTop: '1px dashed var(--color-ec-border)' }}>
          <div className="text-center space-y-1">
            <p className="text-[11px] text-[var(--color-ec-text-secondary)] font-mono">
              Select parameters and run optimization
            </p>
            <p className="text-[9px] text-[var(--color-ec-text-muted)] font-mono opacity-80">
              {params.length} parameters detected
            </p>
          </div>
        </div>
      )}

      {!loadingParams && params.length === 0 && (
        <div className="flex items-center justify-center h-40">
          <p className="text-[11px] text-[var(--color-ec-text-secondary)] font-mono">
            No optimizable parameters detected
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function isIntegerParam(param: OptimizationParam) {
  if (!param) return false;
  const keys = param.path.split(".");
  const lastKey = keys[keys.length - 1];
  const intKeys = [
    "period", "period2", "period3", "offset", "consecutive_count", 
    "time_hour", "time_minute", "days_lookback", "orb_minutes", 
    "time_from_hour", "time_from_minute", "range_minutes", 
    "deviationLevel", "sma_period", "lookback"
  ];
  return intKeys.includes(lastKey) || param.step === 1;
}

function isVolumeParam(param?: { id: string; label: string; path?: string }) {
  if (!param) return false;
  const id = (param.id || "").toLowerCase();
  const label = (param.label || "").toLowerCase();
  const path = (param.path || "").toLowerCase();
  return (
    id.includes("volume") ||
    id.includes("volumen") ||
    id.includes("acumulated") ||
    id.includes("accumulated") ||
    id.includes("cum_volume") ||
    id.includes("vol_") ||
    label.includes("volume") ||
    label.includes("volumen") ||
    label.includes("acumulado") ||
    label.includes("acumulada") ||
    path.includes("volume") ||
    path.includes("volumen") ||
    path.includes("acumulated") ||
    path.includes("accumulated")
  );
}

function RangeSlider({
  label,
  value,
  onChange,
  param,
  gridSteps,
}: {
  label: string;
  value: [number, number];
  onChange: (v: [number, number]) => void;
  param?: OptimizationParam;
  gridSteps: number;
}) {
  const isVolume = isVolumeParam(param);
  const scale = isVolume ? 1000000 : 1;
  const displayLabel = isVolume ? `${label} (M)` : label;

  const [localMin, setLocalMin] = useState(() => (value[0] / scale).toString());
  const [localMax, setLocalMax] = useState(() => (value[1] / scale).toString());

  useEffect(() => {
    const currentVal = parseFloat(localMin);
    const targetVal = value[0] / scale;
    if (isNaN(currentVal) || currentVal !== targetVal) {
      setLocalMin(targetVal.toString());
    }
  }, [value[0], scale]);

  useEffect(() => {
    const currentVal = parseFloat(localMax);
    const targetVal = value[1] / scale;
    if (isNaN(currentVal) || currentVal !== targetVal) {
      setLocalMax(targetVal.toString());
    }
  }, [value[1], scale]);

  const step = param?.step || 1;
  const rangeWidth = value[1] - value[0];
  const intervalWidth = gridSteps * step;

  // Check if rangeWidth is a multiple of intervalWidth (handling floating point precision)
  const ratio = rangeWidth / intervalWidth;
  const isMultiple = rangeWidth > 0 && Math.abs(ratio - Math.round(ratio)) < 1e-9;

  let limitWarning = "";
  if (value[0] >= value[1]) {
    limitWarning = "El valor mínimo debe ser estrictamente menor que el máximo.";
  }

  let warningMessage = "";
  let suggestions: number[] = [];
  if (!limitWarning && !isMultiple && rangeWidth > 0) {
    const kLow = Math.max(1, Math.floor(rangeWidth / intervalWidth));
    const kHigh = Math.ceil(rangeWidth / intervalWidth);
    const maxLow = Number((value[0] + kLow * intervalWidth).toFixed(4));
    const maxHigh = Number((value[0] + kHigh * intervalWidth).toFixed(4));
    suggestions = Array.from(new Set([maxLow, maxHigh])).filter((m) => m !== value[1] && m > value[0]);
    warningMessage = isVolume
      ? `El rango (${rangeWidth / scale}M) debe ser múltiplo de ${intervalWidth / scale}M (para que los saltos sean múltiplos de ${step / scale}M).`
      : `El rango (${rangeWidth}) debe ser múltiplo de ${intervalWidth} (para que los saltos sean múltiplos de ${step}).`;
  }

  return (
    <div className="flex flex-col space-y-2 p-3 bg-[var(--color-ec-bg-elevated)] rounded border border-[var(--color-ec-border)]">
      <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase font-semibold tracking-wider">{displayLabel}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          step="any"
          value={localMin}
          onChange={(e) => {
            const valStr = e.target.value;
            setLocalMin(valStr);
            const num = parseFloat(valStr);
            if (!isNaN(num)) {
              onChange([num * scale, value[1]]);
            }
          }}
          className="w-20 bg-[var(--color-ec-bg)] border border-[var(--color-ec-border)] rounded px-2 py-1.5 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono"
        />
        <span className="text-[9px] text-[var(--color-ec-text-secondary)] font-mono font-bold">→</span>
        <input
          type="number"
          step="any"
          value={localMax}
          onChange={(e) => {
            const valStr = e.target.value;
            setLocalMax(valStr);
            const num = parseFloat(valStr);
            if (!isNaN(num)) {
              onChange([value[0], num * scale]);
            }
          }}
          className="w-20 bg-[var(--color-ec-bg)] border border-[var(--color-ec-border)] rounded px-2 py-1.5 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono"
        />
      </div>
      {param && (
        <p className="text-[9px] text-[var(--color-ec-text-muted)] font-mono opacity-80">
          Actual: <span className="text-[var(--color-ec-text-primary)] font-bold">{isVolume ? `${param.current_value / scale}M` : param.current_value}</span> | Paso base: {isVolume ? `${step / scale}M` : step}
        </p>
      )}
      {limitWarning && (
        <div className="mt-2 p-2 bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.3)] rounded text-[9px] font-mono text-red-500">
          <p className="font-semibold">⚠️ {limitWarning}</p>
        </div>
      )}
      {warningMessage && (
        <div className="mt-2 p-2 bg-[rgba(245,158,11,0.08)] border border-[rgba(245,158,11,0.3)] rounded text-[9px] font-mono text-amber-500">
          <p className="font-semibold mb-1">⚠️ {warningMessage}</p>
          {suggestions.length > 0 && (
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <span>Sugerir Max:</span>
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => onChange([value[0], s])}
                  className="px-1.5 py-0.5 bg-amber-500/20 hover:bg-amber-500/35 text-amber-400 rounded cursor-pointer border border-amber-500/30 transition-all active:scale-[0.95] font-bold"
                >
                  {isVolume ? `${s / scale}M` : s} (Rango: {isVolume ? `${(s - value[0]) / scale}M` : s - value[0]})
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AnalysisCard({
  title,
  subtitle,
  items,
  isDarkMode,
}: {
  title: string;
  subtitle?: string;
  items: { label: string; value: string; highlight?: boolean }[];
  isDarkMode?: boolean;
}) {
  return (
    <div className="py-2" style={{ borderTop: '1px solid var(--color-ec-border)' }}>
      <p className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.1em] mb-0.5 font-mono">{title}</p>
      {subtitle && (
        <p className="text-[9px] text-[var(--color-ec-text-muted)] mb-2 font-mono opacity-80">{subtitle}</p>
      )}
      <div className="space-y-0.5">
        {items.map((item, i) => (
          <div key={i} className="flex justify-between items-center py-0.5">
            <span className="text-[10px] text-[var(--color-ec-text-secondary)] font-mono">{item.label}</span>
            <span
              className={`text-[11px] font-mono ${
                item.highlight
                  ? "text-[var(--color-ec-copper-bright)] font-semibold"
                  : "text-[var(--color-ec-text-primary)]"
              }`}
            >
              {item.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (Math.abs(v) >= 1) return v.toFixed(2);
  return v.toFixed(4);
}
