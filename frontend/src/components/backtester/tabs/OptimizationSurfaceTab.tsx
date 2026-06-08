"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import {
  fetchOptimizationParams,
  runOptimizationSurface,
  fetchOptimizationProgress,
  fetchOptimizationResult,
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

    let pollInterval: number | undefined;
    let visualInterval: number | undefined;

    const cleanup = () => {
      if (pollInterval) window.clearInterval(pollInterval);
      if (visualInterval) window.clearInterval(visualInterval);
    };

    try {
      await runOptimizationSurface({
        strategy_id: strategyId,
        strategy_definition: strategyDefinition,
        dataset_id: datasetId,
        metric,
        param_configs: configs,
        task_id: taskId,
        ...backtestParams,
      });

      // Visual progress timer: climb asymptotically towards 95%
      visualInterval = window.setInterval(() => {
        setVisualProgress((prev) => {
          if (prev < 95) {
            const remaining = 95 - prev;
            const step = Math.max(0.05, remaining * 0.015);
            return prev + step;
          }
          return prev;
        });
      }, 150);

      pollInterval = window.setInterval(async () => {
        try {
          const res = await fetchOptimizationResult(taskId);
          if ("status" in res && res.status === "running") {
            setProgress(res.progress);
            setVisualProgress((prev) => Math.max(prev, res.progress));
          } else {
            cleanup();
            setProgress(100);
            setVisualProgress(100);
            // Small delay so user sees 100% complete
            setTimeout(() => {
              setResult(res as OptimizationResult);
              setLoading(false);
            }, 300);
          }
        } catch (e: any) {
          cleanup();
          console.error("Error polling optimization result", e);
          const msg = e.response?.data?.detail || e.message || "Error al recuperar resultados de optimización";
          setError(msg);
          setLoading(false);
        }
      }, 800);

    } catch (err: any) {
      cleanup();
      console.error("Error starting optimization:", err);
      const msg = err.response?.data?.detail || err.message || "Error al iniciar la optimización";
      setError(msg);
      setLoading(false);
    }
  };

  // Plotly data
  const plotData = useMemo(() => {
    if (!result) return null;
    const p = result.params;
    const metricLabel = METRIC_OPTIONS.find((m) => m.value === result.metric)?.label || result.metric;

    const bg = "#16181A";
    const fg = "#D4D2CF";
    const gridColor = "#2C2F33";

    if (mode === "2D" && p.length === 2) {
      const z = result.grid;
      const x = p[0].values;
      const y = p[1].values;

      return {
        data: [
          {
            z,
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
      const rawZ = result.grid as (number | null)[][];
      const validVals = rawZ.flat().filter((v): v is number => v !== null && !isNaN(v));
      const minVal = validVals.length > 0 ? Math.min(...validVals) : 0;
      const z = rawZ.map((row) => row.map((v) => (v === null ? minVal : v)));

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
  }, [result, mode, isDarkMode]);

  const pa = result?.plateau_analysis;

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
            />
          )}
          {paramY && (
            <RangeSlider
              label={getParamById(paramY)?.label || "Y"}
              value={rangeY}
              onChange={setRangeY}
              param={getParamById(paramY)}
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
                  optimizing...
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
                {gridSteps * gridSteps} backtests
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

function RangeSlider({
  label,
  value,
  onChange,
  param,
}: {
  label: string;
  value: [number, number];
  onChange: (v: [number, number]) => void;
  param?: OptimizationParam;
}) {
  const step = param?.step || 1;
  return (
    <div>
      <label className="text-[9px] text-[var(--color-ec-text-secondary)] block mb-1.5 font-mono uppercase">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={value[0]}
          step={step}
          onChange={(e) => onChange([Number(e.target.value), value[1]])}
          className="w-20 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1.5 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono"
        />
        <span className="text-[9px] text-[var(--color-ec-text-secondary)] font-mono">→</span>
        <input
          type="number"
          value={value[1]}
          step={step}
          onChange={(e) => onChange([value[0], Number(e.target.value)])}
          className="w-20 bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded px-2 py-1.5 text-[11px] text-center text-[var(--color-ec-text-high)] outline-none focus:border-[var(--color-ec-copper)] font-mono"
        />
      </div>
      {param && (
        <p className="text-[9px] text-[var(--color-ec-text-muted)] mt-1 font-mono opacity-60">
          current: {param.current_value} | step: {step}
        </p>
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
