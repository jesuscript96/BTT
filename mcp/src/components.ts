/** The component catalog: each result piece is an independently-scaffoldable
 *  component. Picking a component decides which `include` sections its data needs
 *  (docs/b2d-gateway/04 §1) — so "I don't want everything" is the default and is
 *  what makes runtime payloads efficient. Templates are adapted from the real
 *  Edgecute frontend components and consume the API JSON 1:1.
 */

export interface RenderOptions {
  componentName?: string;
}

export interface ComponentSpec {
  id: string;
  module: string;
  title: string;
  description: string;
  /** Data sections this component needs (drives the API `include` param). */
  include: string[];
  /** Extra npm packages the generated component imports. */
  peerDeps: string[];
  defaultName: string;
  render: (opts: RenderOptions) => string;
}

function name(opts: RenderOptions, fallback: string): string {
  const n = (opts.componentName ?? fallback).replace(/[^A-Za-z0-9_]/g, "");
  return n.length > 0 ? n : fallback;
}

const equityChart: ComponentSpec = {
  id: "equity-chart",
  module: "backtest",
  title: "Equity curve",
  description: "Curva de equity (global_equity) con lightweight-charts.",
  include: ["equity"],
  peerDeps: ["lightweight-charts"],
  defaultName: "EquityChart",
  render: (o) => {
    const C = name(o, "EquityChart");
    return `import { useEffect, useRef } from "react";
import { createChart, type IChartApi } from "lightweight-charts";

export interface EquityPoint { time: number; value: number; }
export interface ${C}Props { data: EquityPoint[]; height?: number; }

/** Equity curve. Feed it \`result.global_equity\` (include=["equity"]). */
export function ${C}({ data, height = 320 }: ${C}Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      height,
      layout: { background: { color: "transparent" }, textColor: "#9aa0a6" },
      grid: { vertLines: { color: "#1f2329" }, horzLines: { color: "#1f2329" } },
      timeScale: { timeVisible: true },
    });
    const series = chart.addAreaSeries({ lineColor: "#D87A3D", topColor: "rgba(216,122,61,0.4)", bottomColor: "rgba(216,122,61,0.02)" });
    series.setData(data as never);
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [data, height]);
  return <div ref={ref} style={{ width: "100%" }} />;
}
`;
  },
};

const drawdownChart: ComponentSpec = {
  id: "drawdown-chart",
  module: "backtest",
  title: "Drawdown curve",
  description: "Curva de drawdown (global_drawdown).",
  include: ["equity"],
  peerDeps: ["lightweight-charts"],
  defaultName: "DrawdownChart",
  render: (o) => {
    const C = name(o, "DrawdownChart");
    return `import { useEffect, useRef } from "react";
import { createChart, type IChartApi } from "lightweight-charts";

export interface EquityPoint { time: number; value: number; }
export interface ${C}Props { data: EquityPoint[]; height?: number; }

/** Drawdown curve. Feed it \`result.global_drawdown\` (include=["equity"]). */
export function ${C}({ data, height = 200 }: ${C}Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      height,
      layout: { background: { color: "transparent" }, textColor: "#9aa0a6" },
      grid: { vertLines: { color: "#1f2329" }, horzLines: { color: "#1f2329" } },
      timeScale: { timeVisible: true },
    });
    const series = chart.addAreaSeries({ lineColor: "#c0443b", topColor: "rgba(192,68,59,0.05)", bottomColor: "rgba(192,68,59,0.4)" });
    series.setData(data as never);
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [data, height]);
  return <div ref={ref} style={{ width: "100%" }} />;
}
`;
  },
};

const metricCard: ComponentSpec = {
  id: "metric-card",
  module: "backtest",
  title: "Single metric card",
  description: "Una métrica suelta de aggregate_metrics (elige cuál).",
  include: ["metrics"],
  peerDeps: [],
  defaultName: "MetricCard",
  render: (o) => {
    const C = name(o, "MetricCard");
    return `export interface ${C}Props { label: string; value: number | null | undefined; suffix?: string; }

/** One metric from \`result.aggregate_metrics\` — pick exactly the one you want. */
export function ${C}({ label, value, suffix = "" }: ${C}Props) {
  const text = value === null || value === undefined ? "—" : \`\${value}\${suffix}\`;
  return (
    <div style={{ padding: 16, borderRadius: 12, background: "#15181d", minWidth: 140 }}>
      <div style={{ fontSize: 12, color: "#9aa0a6", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: "#e8eaed" }}>{text}</div>
    </div>
  );
}
`;
  },
};

const metricsGrid: ComponentSpec = {
  id: "metrics-grid",
  module: "backtest",
  title: "Metrics grid",
  description: "Grid configurable de aggregate_metrics (elige el subconjunto).",
  include: ["metrics"],
  peerDeps: [],
  defaultName: "MetricsGrid",
  render: (o) => {
    const C = name(o, "MetricsGrid");
    return `export type Metrics = Record<string, number | null>;
export interface MetricDef { key: string; label: string; suffix?: string; }
export interface ${C}Props { metrics: Metrics; fields?: MetricDef[]; }

const DEFAULT_FIELDS: MetricDef[] = [
  { key: "total_return_pct", label: "Return", suffix: "%" },
  { key: "win_rate_pct", label: "Win rate", suffix: "%" },
  { key: "total_trades", label: "Trades" },
  { key: "avg_sharpe", label: "Sharpe" },
  { key: "max_drawdown_pct", label: "Max DD", suffix: "%" },
  { key: "expectancy", label: "Expectancy" },
];

/** Configurable grid of \`result.aggregate_metrics\`. Pass \`fields\` to choose
 *  exactly which metrics to show — you don't have to render them all. */
export function ${C}({ metrics, fields = DEFAULT_FIELDS }: ${C}Props) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
      {fields.map((f) => {
        const v = metrics?.[f.key];
        const text = v === null || v === undefined ? "—" : \`\${v}\${f.suffix ?? ""}\`;
        return (
          <div key={f.key} style={{ padding: 16, borderRadius: 12, background: "#15181d" }}>
            <div style={{ fontSize: 12, color: "#9aa0a6", textTransform: "uppercase" }}>{f.label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#e8eaed" }}>{text}</div>
          </div>
        );
      })}
    </div>
  );
}
`;
  },
};

const tradesTable: ComponentSpec = {
  id: "trades-table",
  module: "backtest",
  title: "Trades table",
  description: "Tabla paginada de trades (columnas configurables).",
  include: ["trades"],
  peerDeps: [],
  defaultName: "TradesTable",
  render: (o) => {
    const C = name(o, "TradesTable");
    return `export interface Trade {
  ticker: string; date: string; entry_price?: number; exit_price?: number;
  pnl?: number; return_pct?: number; direction?: string; exit_reason?: string;
  r_multiple?: number | null; [k: string]: unknown;
}
export interface Column { key: keyof Trade | string; label: string; }
export interface ${C}Props { trades: Trade[]; columns?: Column[]; }

const DEFAULT_COLUMNS: Column[] = [
  { key: "ticker", label: "Ticker" }, { key: "date", label: "Date" },
  { key: "direction", label: "Side" }, { key: "entry_price", label: "Entry" },
  { key: "exit_price", label: "Exit" }, { key: "pnl", label: "PnL" },
  { key: "r_multiple", label: "R" }, { key: "exit_reason", label: "Exit" },
];

/** Trades table. Feed it \`result.trades.items\` (include=["trades"]). */
export function ${C}({ trades, columns = DEFAULT_COLUMNS }: ${C}Props) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, color: "#e8eaed" }}>
      <thead>
        <tr>{columns.map((c) => (
          <th key={String(c.key)} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "1px solid #2a2f36", color: "#9aa0a6" }}>{c.label}</th>
        ))}</tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i}>{columns.map((c) => (
            <td key={String(c.key)} style={{ padding: "8px 10px", borderBottom: "1px solid #1b1f25" }}>{String(t[c.key as string] ?? "—")}</td>
          ))}</tr>
        ))}
      </tbody>
    </table>
  );
}
`;
  },
};

const dayResultsTable: ComponentSpec = {
  id: "day-results-table",
  module: "backtest",
  title: "Day results table",
  description: "Tabla de resultados por día (day_results).",
  include: ["days"],
  peerDeps: [],
  defaultName: "DayResultsTable",
  render: (o) => {
    const C = name(o, "DayResultsTable");
    return `export interface DayResult {
  ticker: string; date: string; total_return_pct?: number | null;
  total_trades?: number | null; win_rate_pct?: number | null; gap_pct?: number | null;
  [k: string]: unknown;
}
export interface ${C}Props { days: DayResult[]; }

/** Per-day results table. Feed it \`result.day_results\` (include=["days"]). */
export function ${C}({ days }: ${C}Props) {
  const fmt = (v: unknown) => (v === null || v === undefined ? "—" : String(v));
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, color: "#e8eaed" }}>
      <thead><tr>
        {["Ticker", "Date", "Return %", "Trades", "Win %", "Gap %"].map((h) => (
          <th key={h} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "1px solid #2a2f36", color: "#9aa0a6" }}>{h}</th>
        ))}
      </tr></thead>
      <tbody>
        {days.map((d, i) => (
          <tr key={i}>
            <td style={{ padding: "8px 10px" }}>{d.ticker}</td>
            <td style={{ padding: "8px 10px" }}>{d.date}</td>
            <td style={{ padding: "8px 10px" }}>{fmt(d.total_return_pct)}</td>
            <td style={{ padding: "8px 10px" }}>{fmt(d.total_trades)}</td>
            <td style={{ padding: "8px 10px" }}>{fmt(d.win_rate_pct)}</td>
            <td style={{ padding: "8px 10px" }}>{fmt(d.gap_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
`;
  },
};

// ── Portfolio module ─────────────────────────────────────────────────────────
const portfolioEquityChart: ComponentSpec = {
  id: "portfolio-equity-chart",
  module: "portfolio",
  title: "Combined portfolio equity",
  description: "Curva de equity agregada de la cartera (combined_equity de /portfolio/combine).",
  include: ["combine"],
  peerDeps: ["lightweight-charts"],
  defaultName: "PortfolioEquityChart",
  render: (o) => {
    const C = name(o, "PortfolioEquityChart");
    return `import { useEffect, useRef } from "react";
import { createChart, type IChartApi } from "lightweight-charts";

export interface ${C}Props { timestamps: number[]; combinedEquity: number[]; height?: number; }

/** Feed it \`result.timestamps\` and \`result.combined_equity\` from POST /portfolio/combine. */
export function ${C}({ timestamps, combinedEquity, height = 320 }: ${C}Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      height,
      layout: { background: { color: "transparent" }, textColor: "#9aa0a6" },
      grid: { vertLines: { color: "#1f2329" }, horzLines: { color: "#1f2329" } },
      timeScale: { timeVisible: true },
    });
    const series = chart.addAreaSeries({ lineColor: "#D87A3D", topColor: "rgba(216,122,61,0.4)", bottomColor: "rgba(216,122,61,0.02)" });
    series.setData(timestamps.map((t, i) => ({ time: t as never, value: combinedEquity[i] })));
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [timestamps, combinedEquity, height]);
  return <div ref={ref} style={{ width: "100%" }} />;
}
`;
  },
};

const correlationHeatmap: ComponentSpec = {
  id: "correlation-heatmap",
  module: "portfolio",
  title: "Correlation heatmap",
  description: "Mapa de calor de correlación (Pearson/Spearman). Rojo=+1 (sin diversificación), verde=-1 (cobertura).",
  include: ["correlation"],
  peerDeps: [],
  defaultName: "CorrelationHeatmap",
  render: (o) => {
    const C = name(o, "CorrelationHeatmap");
    return `import React from "react";

export interface ${C}Props { labels: string[]; matrix: number[][]; }

/** color: +1 red (correlated), 0 neutral, -1 green (hedge). */
function cellColor(v: number): string {
  const t = Math.max(-1, Math.min(1, v));
  if (t >= 0) return "rgba(214,69,69," + (0.15 + 0.6 * t) + ")";
  return "rgba(63,168,105," + (0.15 + 0.6 * Math.abs(t)) + ")";
}

/** Feed it \`result.labels\` and \`result.pearson\` (or \`result.spearman\`) from POST /portfolio/correlation. */
export function ${C}({ labels, matrix }: ${C}Props) {
  return (
    <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr>
          <th />
          {labels.map((l) => (<th key={l} style={{ padding: 4, color: "#9aa0a6" }}>{l}</th>))}
        </tr>
      </thead>
      <tbody>
        {matrix.map((row, i) => (
          <tr key={labels[i]}>
            <td style={{ padding: 4, color: "#9aa0a6" }}>{labels[i]}</td>
            {row.map((v, j) => (
              <td key={j} style={{ padding: "8px 10px", textAlign: "center", background: cellColor(v), color: "#e8eaed" }}>
                {v.toFixed(2)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
`;
  },
};

const montecarloSpaghetti: ComponentSpec = {
  id: "montecarlo-spaghetti",
  module: "portfolio",
  title: "Monte Carlo percentile bands",
  description: "Bandas de percentiles (p5..p95) de la simulación de Montecarlo de la cartera.",
  include: ["montecarlo"],
  peerDeps: ["lightweight-charts"],
  defaultName: "MontecarloChart",
  render: (o) => {
    const C = name(o, "MontecarloChart");
    return `import { useEffect, useRef } from "react";
import { createChart, type IChartApi } from "lightweight-charts";

export interface ${C}Props { percentiles: Record<string, number[]>; height?: number; }

const COLORS: Record<string, string> = { p5: "#d64545", p25: "#d8a13d", p50: "#D87A3D", p75: "#3fa869", p95: "#3f7fa8" };

/** Feed it \`result.percentiles\` from POST /portfolio/montecarlo. */
export function ${C}({ percentiles, height = 360 }: ${C}Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      height,
      layout: { background: { color: "transparent" }, textColor: "#9aa0a6" },
      grid: { vertLines: { color: "#1f2329" }, horzLines: { color: "#1f2329" } },
    });
    for (const key of Object.keys(percentiles)) {
      const s = chart.addLineSeries({ color: COLORS[key] ?? "#888", lineWidth: key === "p50" ? 2 : 1 });
      s.setData(percentiles[key].map((value, i) => ({ time: (i + 1) as never, value })));
    }
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [percentiles, height]);
  return <div ref={ref} style={{ width: "100%" }} />;
}
`;
  },
};

const portfolioRiskGrid: ComponentSpec = {
  id: "portfolio-risk-grid",
  module: "portfolio",
  title: "Portfolio risk metrics",
  description: "Cuadro de métricas de la cartera (Sharpe, MaxDD, PnL%, VaR/CVaR).",
  include: ["combine"],
  peerDeps: [],
  defaultName: "PortfolioRiskGrid",
  render: (o) => {
    const C = name(o, "PortfolioRiskGrid");
    return `import React from "react";

export interface ${C}Props { metrics: Record<string, number>; }

const LABELS: Record<string, string> = {
  total_return_pct: "PnL %", max_drawdown_pct: "Drawdown máx %", sharpe_ratio: "Sharpe",
  volatility_pct: "Volatilidad %", win_rate_pct: "Win rate %", profit_factor: "Profit factor",
};

/** Feed it \`result.metrics\` from POST /portfolio/combine. */
export function ${C}({ metrics }: ${C}Props) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
      {Object.entries(LABELS).filter(([k]) => k in metrics).map(([k, label]) => (
        <div key={k} style={{ padding: 12, borderRadius: 10, background: "#15181d", border: "1px solid #1f2329" }}>
          <div style={{ fontSize: 12, color: "#9aa0a6" }}>{label}</div>
          <div style={{ fontSize: 20, color: "#e8eaed" }}>{metrics[k]}</div>
        </div>
      ))}
    </div>
  );
}
`;
  },
};

export const COMPONENTS: ComponentSpec[] = [
  equityChart,
  drawdownChart,
  metricCard,
  metricsGrid,
  tradesTable,
  dayResultsTable,
  portfolioEquityChart,
  correlationHeatmap,
  montecarloSpaghetti,
  portfolioRiskGrid,
];

export function listComponents(module?: string): ComponentSpec[] {
  return module ? COMPONENTS.filter((c) => c.module === module) : COMPONENTS;
}

export function getComponent(id: string): ComponentSpec | undefined {
  return COMPONENTS.find((c) => c.id === id);
}

export const MODULES = [
  {
    name: "backtest",
    description: "Backtests de gaps/short-selling: métricas, equity, trades, días.",
    status: "available",
  },
  {
    name: "portfolio",
    description: "Cartera de estrategias: equity agregada, Monte Carlo/VaR/CVaR, correlación y asignación (Líderes/HRP).",
    status: "available",
  },
  { name: "screener", description: "Screener de universo (v2).", status: "planned" },
  { name: "ticker-analysis", description: "Análisis de ticker (v2).", status: "planned" },
];
