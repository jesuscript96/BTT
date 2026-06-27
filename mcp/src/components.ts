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

// ── Robustness module (docs/robustez) ──────────────────────────────────────
const montecarloSpaghetti: ComponentSpec = {
  id: "montecarlo-spaghetti",
  module: "robustness",
  title: "Monte Carlo spaghetti",
  description: "Curvas de capital por percentiles (p5..p95) de un bootstrap Montecarlo.",
  include: ["montecarlo"],
  peerDeps: ["recharts"],
  defaultName: "MontecarloSpaghetti",
  render: (o) => {
    const C = name(o, "MontecarloSpaghetti");
    return `import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export interface CurvePoint { time: number; value: number; }
export interface MontecarloResult { percentiles: Record<string, CurvePoint[]>; }

/** Spaghetti chart. Feed it the /robustness/montecarlo response. */
export function ${C}({ data, height = 300 }: { data: MontecarloResult; height?: number }) {
  const keys = Object.keys(data.percentiles);
  const len = keys.length ? data.percentiles[keys[0]].length : 0;
  const rows = Array.from({ length: len }, (_, i) => {
    const r: Record<string, number> = { idx: i };
    keys.forEach((k) => { r[k] = data.percentiles[k][i]?.value ?? 0; });
    return r;
  });
  const colors = ["#5B8BB0", "#8A8D92", "#4A9D7F", "#D87A3D", "#C94D3F"];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows}>
        <CartesianGrid stroke="#2C2F33" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="idx" tick={{ fill: "#6A6D72", fontSize: 11 }} />
        <YAxis tick={{ fill: "#6A6D72", fontSize: 11 }} />
        <Tooltip />
        {keys.map((k, i) => (
          <Line key={k} type="monotone" dataKey={k} stroke={colors[i % colors.length]} dot={false} strokeWidth={k === "p50" ? 2 : 1} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
`;
  },
};

const drawdownHistogram: ComponentSpec = {
  id: "drawdown-histogram",
  module: "robustness",
  title: "Drawdown distribution",
  description: "Distribución del drawdown máximo (mediana, P95, P99, peor) de un Montecarlo.",
  include: ["montecarlo"],
  peerDeps: ["recharts"],
  defaultName: "DrawdownHistogram",
  render: (o) => {
    const C = name(o, "DrawdownHistogram");
    return `import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export interface MontecarloResult {
  median_drawdown: number; extreme_drawdown_p95: number; extreme_drawdown_p99: number; worst_drawdown: number;
}

/** Drawdown bars. Feed it the /robustness/montecarlo response. */
export function ${C}({ data, height = 200 }: { data: MontecarloResult; height?: number }) {
  const rows = [
    { name: "Mediana", value: data.median_drawdown },
    { name: "P95", value: data.extreme_drawdown_p95 },
    { name: "P99", value: data.extreme_drawdown_p99 },
    { name: "Peor", value: data.worst_drawdown },
  ];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows}>
        <CartesianGrid stroke="#2C2F33" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="name" tick={{ fill: "#6A6D72", fontSize: 11 }} />
        <YAxis tick={{ fill: "#6A6D72", fontSize: 11 }} />
        <Tooltip />
        <Bar dataKey="value" fill="#C94D3F" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
`;
  },
};

const locateSensitivityChart: ComponentSpec = {
  id: "locate-sensitivity-chart",
  module: "robustness",
  title: "Locate sensitivity",
  description: "Equity bajo distintos costes de locate + umbral crítico (sensibilidad estocástica).",
  include: ["sensitivity"],
  peerDeps: ["recharts"],
  defaultName: "LocateSensitivityChart",
  render: (o) => {
    const C = name(o, "LocateSensitivityChart");
    return `import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from "recharts";

export interface CurvePoint { time: number; value: number; }
export interface SensitivityResult { critical_locate_threshold: number | null; curves: Record<string, CurvePoint[]>; }

/** Multi-line equity by locate cost. Feed it the /robustness/sensitivity response. */
export function ${C}({ data, height = 320 }: { data: SensitivityResult; height?: number }) {
  const keys = Object.keys(data.curves);
  const len = keys.length ? data.curves[keys[0]].length : 0;
  const rows = Array.from({ length: len }, (_, i) => {
    const r: Record<string, number> = { idx: i };
    keys.forEach((k) => { r[k] = data.curves[k][i]?.value ?? 0; });
    return r;
  });
  const colors = ["#5B8BB0", "#8A8D92", "#4A9D7F", "#C9A23F", "#D87A3D", "#C94D3F"];
  return (
    <div>
      {data.critical_locate_threshold !== null && (
        <div style={{ color: "#D87A3D", fontSize: 13, marginBottom: 8 }}>
          Umbral Crítico de Locates: {data.critical_locate_threshold.toFixed(2)}%
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows}>
          <CartesianGrid stroke="#2C2F33" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="idx" tick={{ fill: "#6A6D72", fontSize: 11 }} />
          <YAxis tick={{ fill: "#6A6D72", fontSize: 11 }} />
          <Tooltip />
          <Legend />
          {keys.map((k, i) => (
            <Line key={k} type="monotone" dataKey={k} stroke={colors[i % colors.length]} dot={false} strokeWidth={1.5} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
`;
  },
};

const blackswanMatrix: ComponentSpec = {
  id: "blackswan-sensitivity-matrix",
  module: "robustness",
  title: "Black Swan matrix",
  description: "Matriz Tamaño de posición × Severidad coloreada por zona (verde/amarillo/rojo).",
  include: ["black_swan"],
  peerDeps: [],
  defaultName: "BlackSwanMatrix",
  render: (o) => {
    const C = name(o, "BlackSwanMatrix");
    return `export interface BlackSwanCell {
  position_size_pct: number; severity_multiplier: number; ruin_probability: number; max_drawdown: number; zone: "GREEN" | "YELLOW" | "RED";
}
export interface BlackSwanResult { sensitivity_matrix: BlackSwanCell[]; }

const ZONE: Record<string, string> = { GREEN: "#4A9D7F", YELLOW: "#D87A3D", RED: "#C94D3F" };

/** Capital sensitivity heat-matrix. Feed it the /robustness/black-swan response. */
export function ${C}({ data }: { data: BlackSwanResult }) {
  const positions = [...new Set(data.sensitivity_matrix.map((c) => c.position_size_pct))].sort((a, b) => a - b);
  const severities = [...new Set(data.sensitivity_matrix.map((c) => c.severity_multiplier))].sort((a, b) => a - b);
  const at = (p: number, s: number) => data.sensitivity_matrix.find((c) => c.position_size_pct === p && c.severity_multiplier === s);
  return (
    <table style={{ borderCollapse: "separate", borderSpacing: 4 }}>
      <thead><tr><th style={{ fontSize: 11, color: "#6A6D72" }}>Pos% \\ Sev×</th>{severities.map((s) => (<th key={s} style={{ fontSize: 11, color: "#6A6D72" }}>×{s}</th>))}</tr></thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p}>
            <td style={{ fontSize: 11, color: "#6A6D72" }}>{p}%</td>
            {severities.map((s) => { const c = at(p, s); return (
              <td key={s} title={c ? "Ruina " + c.ruin_probability + "% / DD " + c.max_drawdown + "%" : ""}
                  style={{ background: c ? ZONE[c.zone] : "transparent", color: "#0E0E0E", borderRadius: 8, padding: "12px 14px", textAlign: "center", fontWeight: 600, fontSize: 12 }}>
                {c ? c.ruin_probability + "%" : ""}
              </td>); })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
`;
  },
};

const wfeHeatmap: ComponentSpec = {
  id: "wfe-heatmap",
  module: "robustness",
  title: "Walk-Forward heatmap",
  description: "Mapa de calor paramétrico (score IS por combinación) del Walk-Forward.",
  include: ["walk_forward"],
  peerDeps: [],
  defaultName: "WfeHeatmap",
  render: (o) => {
    const C = name(o, "WfeHeatmap");
    return `export interface HeatCell { values: number[]; is_score: number; }
export interface WalkForwardResult { heatmap_matrix?: { parameters: string[]; data: HeatCell[] }; wfe?: number; win_rate_penalty?: number; }

/** WFO parameter heatmap. Feed it the /robustness/walk-forward result. */
export function ${C}({ data }: { data: WalkForwardResult }) {
  const heat = data.heatmap_matrix;
  if (!heat || heat.data.length === 0) return <div style={{ color: "#6A6D72" }}>Sin datos de heatmap.</div>;
  const scores = heat.data.map((d) => d.is_score);
  const min = Math.min(...scores), max = Math.max(...scores);
  const color = (v: number) => { const t = max === min ? 0.5 : (v - min) / (max - min); return t < 0.5 ? "#C94D3F" : t < 0.75 ? "#D87A3D" : "#4A9D7F"; };
  return (
    <div>
      <div style={{ color: "#8A8D92", fontSize: 12, marginBottom: 8 }}>WFE {data.wfe ?? 0}% · Win Rate Penalty {data.win_rate_penalty ?? 0}%</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {heat.data.map((d, i) => (
          <div key={i} title={heat.parameters.join("/") + ": " + d.values.join(", ")}
               style={{ background: color(d.is_score), color: "#0E0E0E", borderRadius: 6, padding: "10px 12px", fontSize: 11, fontWeight: 600, textAlign: "center", minWidth: 64 }}>
            {d.values.join("/")}<div style={{ fontWeight: 400, fontSize: 10 }}>{d.is_score}</div>
          </div>
        ))}
      </div>
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
  montecarloSpaghetti,
  drawdownHistogram,
  locateSensitivityChart,
  blackswanMatrix,
  wfeHeatmap,
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
    name: "robustness",
    description: "Stress-test de estrategias: Montecarlo, sensibilidad de locates y Black Swan.",
    status: "available",
  },
  { name: "screener", description: "Screener de universo (v2).", status: "planned" },
  { name: "ticker-analysis", description: "Análisis de ticker (v2).", status: "planned" },
];
