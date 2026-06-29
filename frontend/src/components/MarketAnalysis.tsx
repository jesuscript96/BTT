"use client";

/**
 * Market Analysis — página de inteligencia de gappers small-cap.
 * Contrato/diseño: docs/market-analysis/PRD.md (MVP v1.0).
 *
 * Módulos servidos desde un único GET /api/market/screener (getMarketAnalysis):
 *   · MA-01 KPIs (6 + Close<VWAP placeholder Fase 2)
 *   · MA-02 Time Distribution (HOD/LOD/PMH, toggle 5D/30D/90D por histograma)
 *   · MA-05 MAE/MFE (toggle PM/RTH)
 *   · MA-06 Recent Gaps Up (tabla ordenable, paginada 50, click→ticker)
 * MA-04 Avg Change from Open (12 meses) llega en F2 (endpoint aggregate aparte).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { Filter, RotateCcw, TrendingDown } from "lucide-react";
import { color, font, Card, Button, Table, Th, Td, Tr, SegmentedControl, Input } from "@/components/ui";
import {
  getMarketAnalysis,
  getAvgChangeFromOpen,
  type MarketAnalysisResponse,
  type MaRecentGap,
  type MaHistogram,
  type MaMonthCurve,
} from "@/lib/api";

// ── helpers de formato ───────────────────────────────────────────────────────
const fmtPct = (v: number | null | undefined, dp = 1) =>
  v === null || v === undefined ? "—" : `${v.toFixed(dp)}%`;
const fmtInt = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : Math.round(v).toLocaleString("en-US");
const fmtPrice = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `$${v.toFixed(2)}`;
const fmtVol = (v: number) => {
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return `${Math.round(v)}`;
};

// ── tipos de filtros (estado de UI) ──────────────────────────────────────────
type Period = "1w" | "1m" | "3m" | "6m" | "1y";
type TriState = "all" | "yes" | "no";

interface Filters {
  period: Period;
  min_gap: string;
  min_open: string;
  max_open: string;
  min_volume: string;
  min_pm_volume: string;
  close_red: TriState;
  fade_threshold: string;
}

const DEFAULTS: Filters = {
  period: "1m",
  min_gap: "30",
  min_open: "",
  max_open: "",
  min_volume: "1000000",
  min_pm_volume: "",
  close_red: "all",
  fade_threshold: "50",
};

function buildParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  p.set("period", f.period);
  if (f.min_gap) p.set("min_gap_at_open_pct", f.min_gap);
  if (f.min_open) p.set("min_open", f.min_open);
  if (f.max_open) p.set("max_open", f.max_open);
  if (f.min_volume) p.set("min_volume", f.min_volume);
  if (f.min_pm_volume) p.set("min_pm_volume", f.min_pm_volume);
  if (f.fade_threshold) p.set("fade_threshold", f.fade_threshold);
  p.set("limit", "2000");
  return p;
}

function activeFilterCount(f: Filters): number {
  let n = 0;
  (Object.keys(DEFAULTS) as (keyof Filters)[]).forEach((k) => {
    if (k === "period") return; // el periodo siempre tiene valor, no cuenta como "filtro activo"
    if (f[k] !== DEFAULTS[k]) n += 1;
  });
  return n;
}

// ── componente principal ─────────────────────────────────────────────────────
export default function MarketAnalysis() {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>(DEFAULTS);
  const [data, setData] = useState<MarketAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const params = useMemo(() => buildParams(filters), [filters]);

  // setState solo dentro de los callbacks async (no en el cuerpo del efecto):
  // así no se disparan renders en cascada (regla react-hooks/set-state-in-effect).
  const load = useCallback(
    (signal?: AbortSignal) => {
      return getMarketAnalysis(params, signal)
        .then((res) => {
          // El filtro Close Red (toggle 3 estados) se aplica en cliente sobre records.
          setData(res);
          setError(null);
        })
        .catch((e) => {
          if ((e as Error)?.name === "AbortError") return;
          setError((e as Error)?.message || "Error cargando Market Analysis");
        })
        .finally(() => setLoading(false));
    },
    [params],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const recordsFiltered = useMemo(() => {
    if (!data) return [];
    if (filters.close_red === "all") return data.records;
    const wantRed = filters.close_red === "yes";
    return data.records.filter((r) => r.close_red === wantRed);
  }, [data, filters.close_red]);

  const nActive = activeFilterCount(filters);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100dvh", overflow: "hidden", background: color.bgBase, fontFamily: font.sans, color: color.textPrimary }}>
      {/* ── Header ── */}
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "14px 24px", borderBottom: `1px solid ${color.border}`, flexShrink: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <h1 style={{ fontFamily: font.serif, fontSize: 20, fontWeight: 500, color: color.textHigh, margin: 0 }}>Market Analysis</h1>
          <span style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 1, color: color.textMuted }}>
            Condiciones de mercado · gappers small-cap
            {data?.period ? ` · ${data.period.start} → ${data.period.end}` : ""}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <SegmentedControl<Period>
            options={[
              { id: "1w", label: "1S" },
              { id: "1m", label: "1M" },
              { id: "3m", label: "3M" },
              { id: "6m", label: "6M" },
              { id: "1y", label: "1A" },
            ]}
            value={filters.period}
            onChange={(period) => setFilters((f) => ({ ...f, period }))}
          />
          <Button variant="secondary" size="sm" onClick={() => setShowFilters((s) => !s)}>
            <Filter size={13} style={{ marginRight: 6 }} />
            Filtros{nActive ? ` · ${nActive}` : ""}
          </Button>
          {nActive > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setFilters((f) => ({ ...DEFAULTS, period: f.period }))}>
              <RotateCcw size={13} style={{ marginRight: 6 }} />
              Limpiar
            </Button>
          )}
        </div>
      </header>

      {/* ── Panel de filtros (colapsable) ── */}
      {showFilters && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, padding: "14px 24px", borderBottom: `1px solid ${color.border}`, background: color.bgSurface, flexShrink: 0 }}>
          <FilterNum label="Gap % mín" value={filters.min_gap} onChange={(v) => setFilters((f) => ({ ...f, min_gap: v }))} />
          <FilterNum label="Open mín ($)" value={filters.min_open} onChange={(v) => setFilters((f) => ({ ...f, min_open: v }))} />
          <FilterNum label="Open máx ($)" value={filters.max_open} onChange={(v) => setFilters((f) => ({ ...f, max_open: v }))} />
          <FilterNum label="Vol RTH mín" value={filters.min_volume} onChange={(v) => setFilters((f) => ({ ...f, min_volume: v }))} />
          <FilterNum label="Vol PM mín" value={filters.min_pm_volume} onChange={(v) => setFilters((f) => ({ ...f, min_pm_volume: v }))} />
          <FilterNum label="Fade umbral %" value={filters.fade_threshold} onChange={(v) => setFilters((f) => ({ ...f, fade_threshold: v }))} />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={labelStyle}>Close Red</label>
            <SegmentedControl<TriState>
              size="sm"
              options={[{ id: "all", label: "Todos" }, { id: "yes", label: "Sí" }, { id: "no", label: "No" }]}
              value={filters.close_red}
              onChange={(v) => setFilters((f) => ({ ...f, close_red: v }))}
            />
          </div>
        </div>
      )}

      {/* ── Cuerpo ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 24 }}>
        {error ? (
          <ErrorState message={error} onRetry={() => { setError(null); setLoading(true); void load(); }} />
        ) : loading && !data ? (
          <LoadingState />
        ) : data && recordsFiltered.length === 0 ? (
          <EmptyState onClear={() => setFilters((f) => ({ ...DEFAULTS, period: f.period }))} />
        ) : data ? (
          <>
            <KpiRow data={data} />
            <Section title="Distribución temporal" subtitle="¿Cuándo ocurre el HOD, el LOD y el PM High?">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
                <DistributionChart kind="hod" title="Distribución HOD" baseParams={params} fallback={data.distributions.hod_time} />
                <DistributionChart kind="lod" title="Distribución LOD" baseParams={params} fallback={data.distributions.lod_time} />
                <DistributionChart kind="pmh" title="Distribución PM High" baseParams={params} fallback={data.distributions.pmh_time} />
              </div>
            </Section>
            <MaeMfeSection data={data} />
            <Section title="Avg Change from Open" subtitle="Perfil medio del día por mes · últimos 12 meses naturales">
              <AvgChangeFromOpen baseParams={params} />
            </Section>
            <Section title="Recent Gaps Up" subtitle={`${recordsFiltered.length} gappers · click en ticker para abrir el detalle`}>
              <RecentGapsTable records={recordsFiltered} onTicker={(t) => router.push(`/analysis/${t}`)} />
            </Section>
          </>
        ) : null}
      </div>
    </div>
  );
}

// ── KPIs (MA-01) ─────────────────────────────────────────────────────────────
function KpiRow({ data }: { data: MarketAnalysisResponse }) {
  const k = data.kpis;
  const cards = [
    { label: "Gappers", v: fmtInt(k.gappers_count.value), prev: k.gappers_count.prev, raw: k.gappers_count.value },
    { label: "Avg Gap %", v: fmtPct(k.avg_gap_pct.value), prev: k.avg_gap_pct.prev, raw: k.avg_gap_pct.value },
    { label: "PM High Avg", v: fmtPrice(k.pm_high_average.value), prev: k.pm_high_average.prev, raw: k.pm_high_average.value },
    { label: "Close Red %", v: fmtPct(k.close_red_pct.value), prev: k.close_red_pct.prev, raw: k.close_red_pct.value },
    { label: "Close < VWAP %", v: "Fase 2", prev: null, raw: null, muted: true },
    { label: "Avg Fade PMH", v: fmtPct(k.avg_fade_from_pmh.value), prev: k.avg_fade_from_pmh.prev, raw: k.avg_fade_from_pmh.value },
    {
      label: "Max Fade PMH",
      v: fmtPct(k.max_fade_from_pmh.value),
      prev: null,
      raw: k.max_fade_from_pmh.value,
      hint: k.max_fade_from_pmh.ticker ? `${k.max_fade_from_pmh.ticker} · ${k.max_fade_from_pmh.date}` : undefined,
    },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
      {cards.map((c) => {
        const delta = c.raw != null && c.prev != null ? c.raw - c.prev : null;
        return (
          <Card key={c.label} padded style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, color: color.textMuted }}>{c.label}</span>
            <span style={{ fontSize: 22, fontWeight: 600, color: c.muted ? color.textMuted : color.textHigh, letterSpacing: "-0.5px" }} title={c.hint}>{c.v}</span>
            {delta != null ? (
              <span style={{ fontSize: 10, fontWeight: 600, color: delta >= 0 ? color.profit : color.loss }}>
                {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)} vs ant.
              </span>
            ) : (
              <span style={{ fontSize: 10, color: color.textMuted }}>{c.hint || " "}</span>
            )}
          </Card>
        );
      })}
    </div>
  );
}

// ── Time Distribution (MA-02) ────────────────────────────────────────────────
const DIST_WINDOWS = [
  { id: "5d", label: "5D" },
  { id: "30d", label: "30D" },
  { id: "90d", label: "90D" },
] as const;
type DistWindow = (typeof DIST_WINDOWS)[number]["id"];
const DIST_KEY = { hod: "hod_time", lod: "lod_time", pmh: "pmh_time" } as const;

function DistributionChart({
  kind,
  title,
  baseParams,
  fallback,
}: {
  kind: "hod" | "lod" | "pmh";
  title: string;
  baseParams: URLSearchParams;
  fallback: Record<string, number>;
}) {
  const [win, setWin] = useState<DistWindow>("30d");
  const [dist, setDist] = useState<Record<string, number>>(fallback);

  useEffect(() => {
    const ctrl = new AbortController();
    const p = new URLSearchParams(baseParams);
    p.set("period", win); // periodo independiente del selector global (PRD MA-02)
    getMarketAnalysis(p, ctrl.signal)
      .then((res) => setDist(res.distributions[DIST_KEY[kind]] || {}))
      .catch(() => {});
    return () => ctrl.abort();
  }, [kind, win, baseParams]);

  const entries = Object.entries(dist).sort((a, b) => a[0].localeCompare(b[0]));
  const chartData = entries.map(([franja, pct]) => ({ franja, pct }));
  const dominant = entries.reduce<[string, number]>((acc, e) => (e[1] > acc[1] ? e : acc), ["", 0]);

  return (
    <Card padded style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: font.serif, fontSize: 14, color: color.textHigh }}>{title}</span>
          <span style={{ fontSize: 10, fontWeight: 600, color: color.copper }}>
            {dominant[0] ? `${dominant[0]} · ${dominant[1].toFixed(1)}%` : "—"}
          </span>
        </div>
        <SegmentedControl<DistWindow> size="sm" options={DIST_WINDOWS.map((w) => ({ id: w.id, label: w.label }))} value={win} onChange={setWin} />
      </div>
      <div style={{ height: 180, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={color.border} vertical={false} />
            <XAxis dataKey="franja" stroke={color.textMuted} fontSize={8} tickLine={false} axisLine={false} interval={0} angle={-45} textAnchor="end" height={42} />
            <YAxis stroke={color.textMuted} fontSize={9} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${Number(v).toFixed(1)}%`, "% gappers"]} />
            <Bar dataKey="pct" fill={color.copper} radius={[2, 2, 0, 0]}>
              {chartData.map((d) => (
                <Cell key={d.franja} fill={d.franja === dominant[0] ? color.copperBright : color.copper} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

// ── MAE / MFE (MA-05) ────────────────────────────────────────────────────────
function MaeMfeSection({ data }: { data: MarketAnalysisResponse }) {
  const [mode, setMode] = useState<"rth" | "pm">("rth");
  const block = data.mae_mfe[mode];
  return (
    <Section
      title="MAE / MFE Distribution"
      subtitle={mode === "rth" ? "Referencia: open 09:30 (RTH)" : "Referencia: cierre día anterior (PM)"}
      right={
        <SegmentedControl<"rth" | "pm">
          size="sm"
          options={[{ id: "rth", label: "RTH" }, { id: "pm", label: "PM" }]}
          value={mode}
          onChange={setMode}
        />
      }
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
        <HistogramCard title="MAE — excursión adversa" hist={block.mae} />
        <HistogramCard title="MFE — excursión favorable" hist={block.mfe} />
      </div>
    </Section>
  );
}

function HistogramCard({ title, hist }: { title: string; hist: MaHistogram }) {
  const chartData = Object.entries(hist.buckets).map(([bucket, pct]) => ({ bucket, pct }));
  return (
    <Card padded style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={{ fontFamily: font.serif, fontSize: 14, color: color.textHigh }}>{title}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: color.copper }}>medio · {hist.mean.toFixed(1)}%</span>
      </div>
      <div style={{ display: "flex", gap: 12, fontSize: 9, color: color.textMuted }}>
        <span>P25 {hist.p25.toFixed(1)}%</span>
        <span>P50 {hist.p50.toFixed(1)}%</span>
        <span>P75 {hist.p75.toFixed(1)}%</span>
      </div>
      <div style={{ height: 180, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={color.border} vertical={false} />
            <XAxis dataKey="bucket" stroke={color.textMuted} fontSize={9} tickLine={false} axisLine={false} />
            <YAxis stroke={color.textMuted} fontSize={9} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${Number(v).toFixed(1)}%`, "% gappers"]} />
            <Bar dataKey="pct" fill={color.copper} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

// ── Avg Change from Open (MA-04) ─────────────────────────────────────────────
function AvgChangeFromOpen({ baseParams }: { baseParams: URLSearchParams }) {
  const [months, setMonths] = useState<MaMonthCurve[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    getAvgChangeFromOpen(baseParams, ctrl.signal)
      .then((res) => { setMonths(res); setFailed(false); })
      .catch((e) => { if ((e as Error)?.name !== "AbortError") setFailed(true); })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [baseParams]);

  if (loading) return <span style={{ fontSize: 11, color: color.textMuted }}>Cargando perfiles mensuales…</span>;
  if (failed || months.length === 0) return <span style={{ fontSize: 11, color: color.textMuted }}>Sin datos de perfil mensual.</span>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
      {months.map((m) => (
        <Card key={m.month} padded style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: color.textHigh }}>{m.label}</span>
            <span style={{ fontSize: 9, color: color.copper }}>gap {m.avg_gap_pct.toFixed(0)}%</span>
          </div>
          <div style={{ height: 90, width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={m.points} margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
                <YAxis stroke={color.textMuted} fontSize={7} tickLine={false} axisLine={false} width={28} />
                <XAxis dataKey="time" hide />
                <ReferenceLine y={0} stroke={color.border} strokeDasharray="2 2" />
                <ReferenceLine x="09:30" stroke={color.textMuted} strokeDasharray="3 3" />
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${Number(v).toFixed(2)}%`, "Δ open"]} />
                <Line type="monotone" dataKey="avg_change" stroke={color.copper} strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ── Recent Gaps Up (MA-06) ───────────────────────────────────────────────────
type SortField = keyof Pick<MaRecentGap, "ticker" | "date" | "gap_at_open_pct" | "open" | "vol_rth" | "vol_pm" | "hod" | "pmh">;
const PAGE_SIZE = 50;

function RecentGapsTable({ records, onTicker }: { records: MaRecentGap[]; onTicker: (t: string) => void }) {
  const [sortField, setSortField] = useState<SortField>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    const arr = [...records];
    arr.sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [records, sortField, sortDir]);

  const pageRows = sorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE) || 1;

  const sortBy = (f: SortField) => {
    if (f === sortField) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortField(f); setSortDir("desc"); }
    setPage(0);
  };

  const cols: { f: SortField; label: string; num?: boolean }[] = [
    { f: "ticker", label: "Ticker" },
    { f: "date", label: "Fecha" },
    { f: "gap_at_open_pct", label: "Gap %", num: true },
    { f: "open", label: "Open", num: true },
    { f: "vol_rth", label: "Vol RTH", num: true },
    { f: "vol_pm", label: "Vol PM", num: true },
    { f: "hod", label: "HOD", num: true },
    { f: "pmh", label: "PMH", num: true },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ overflowX: "auto" }}>
        <Table>
          <thead>
            <Tr>
              {cols.map((c) => (
                <Th key={c.f} onClick={() => sortBy(c.f)} style={{ cursor: "pointer", textAlign: c.num ? "right" : "left", whiteSpace: "nowrap" }}>
                  {c.label}{sortField === c.f ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </Th>
              ))}
              <Th style={{ textAlign: "center" }}>Close Red</Th>
            </Tr>
          </thead>
          <tbody>
            {pageRows.map((r) => (
              <Tr key={`${r.ticker}-${r.date}`} hoverable>
                <Td>
                  <button onClick={() => onTicker(r.ticker)} style={{ background: "none", border: "none", color: color.copper, fontWeight: 700, cursor: "pointer", fontFamily: font.sans, padding: 0 }}>
                    {r.ticker}
                  </button>
                </Td>
                <Td style={{ color: color.textMuted }}>{r.date}</Td>
                <Td style={{ textAlign: "right" }}>{r.gap_at_open_pct.toFixed(1)}%</Td>
                <Td style={{ textAlign: "right" }}>{fmtPrice(r.open)}</Td>
                <Td style={{ textAlign: "right" }}>{fmtVol(r.vol_rth)}</Td>
                <Td style={{ textAlign: "right" }}>{fmtVol(r.vol_pm)}</Td>
                <Td style={{ textAlign: "right" }}>{fmtPrice(r.hod)}</Td>
                <Td style={{ textAlign: "right" }}>{fmtPrice(r.pmh)}</Td>
                <Td style={{ textAlign: "center" }}>
                  <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: r.close_red ? color.loss : color.profit }} />
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      </div>
      {totalPages > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10, fontSize: 11, color: color.textMuted }}>
          <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Anterior</Button>
          <span>{page + 1} / {totalPages}</span>
          <Button variant="ghost" size="sm" disabled={page >= totalPages - 1} onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}>Siguiente</Button>
        </div>
      )}
    </div>
  );
}

// ── piezas comunes ───────────────────────────────────────────────────────────
function Section({ title, subtitle, right, children }: { title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <h2 style={{ fontFamily: font.serif, fontSize: 16, fontWeight: 500, color: color.textHigh, margin: 0 }}>{title}</h2>
          {subtitle && <span style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, color: color.textMuted }}>{subtitle}</span>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function FilterNum({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={labelStyle}>{label}</label>
      <Input type="number" value={value} onChange={(e) => onChange(e.target.value)} placeholder="—" />
    </div>
  );
}

function LoadingState() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 400, gap: 16, color: color.textMuted }}>
      <div style={{ width: 32, height: 32, border: `3px solid ${color.border}`, borderTop: `3px solid ${color.copper}`, borderRadius: "50%", animation: "ma-spin 1s linear infinite" }} />
      <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2 }}>Analizando gappers…</span>
      <style dangerouslySetInnerHTML={{ __html: "@keyframes ma-spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}" }} />
    </div>
  );
}

function EmptyState({ onClear }: { onClear: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 400, gap: 12, color: color.textMuted }}>
      <TrendingDown size={28} />
      <span style={{ fontSize: 13, color: color.textPrimary }}>Sin gappers para estos filtros.</span>
      <Button variant="secondary" size="sm" onClick={onClear}>Limpiar filtros</Button>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 400, gap: 12 }}>
      <span style={{ fontSize: 13, color: color.loss }}>No se pudo cargar Market Analysis.</span>
      <span style={{ fontSize: 11, color: color.textMuted, maxWidth: 420, textAlign: "center" }}>{message}</span>
      <Button variant="secondary" size="sm" onClick={onRetry}>Reintentar</Button>
    </div>
  );
}

const labelStyle: React.CSSProperties = { fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, color: color.textMuted };
const tooltipStyle: React.CSSProperties = { backgroundColor: color.bgSurface, border: `1px solid ${color.border}`, borderRadius: 6, padding: "6px 10px", fontFamily: font.sans, fontSize: 11, color: color.textPrimary };
