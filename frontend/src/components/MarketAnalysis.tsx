"use client";

/**
 * Market Analysis — dashboard de inteligencia de gappers small-cap.
 * Contrato/diseño: docs/market-analysis/PRD.md (MVP v1.0).
 *
 * Gráficos construidos con visx (./market-analysis/charts) — reemplazan a recharts
 * SOLO en esta página. Layout pensado como panel (bento), no como pila de secciones:
 *   · KPI strip   — pulso del periodo (hero Gappers + rail de métricas)
 *   · Timing      — HOD/LOD/PM High superpuestos en un único eje intradía (MA-02)
 *   · MAE / MFE   — histograma espejo riesgo↔recorrido (MA-05)
 *   · Seasonality — 12 curvas mensuales de Avg Change from Open (MA-04)
 *   · Recent Gaps — tabla ordenable (MA-06)
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Filter, RotateCcw, TrendingDown, Clock, ArrowLeftRight, CalendarDays, Table2, Activity } from "lucide-react";
import { color, font, Card, Button, Table, Th, Td, Tr, SegmentedControl, Input } from "@/components/ui";
import { TimingChart, MaeMfeTornado, SeasonalityChart, SERIES_COLOR } from "@/components/market-analysis/charts";
import {
  getMarketAnalysis,
  getAvgChangeFromOpen,
  type MarketAnalysisResponse,
  type MaRecentGap,
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

  const load = useCallback(
    (signal?: AbortSignal) => {
      return getMarketAnalysis(params, signal)
        .then((res) => { setData(res); setError(null); })
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
    <div className="ma-dash" style={{ display: "flex", flexDirection: "column", height: "100dvh", overflow: "hidden", background: color.bgBase, fontFamily: font.sans, color: color.textPrimary }}>
      <style dangerouslySetInnerHTML={{ __html: DASH_CSS }} />

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
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 18 }}>
        {error ? (
          <ErrorState message={error} onRetry={() => { setError(null); setLoading(true); void load(); }} />
        ) : loading && !data ? (
          <LoadingState />
        ) : data && recordsFiltered.length === 0 ? (
          <EmptyState onClear={() => setFilters((f) => ({ ...DEFAULTS, period: f.period }))} />
        ) : data ? (
          <>
            <KpiStrip data={data} />

            <div className="ma-mid">
              <Panel
                icon={<Clock size={14} />}
                title="Distribución temporal"
                subtitle="Cuándo ocurre el HOD, el LOD y el PM High"
                right={<TimingLegend />}
              >
                <TimingModule baseParams={params} fallback={data.distributions} />
              </Panel>

              <MaeMfePanel data={data} />
            </div>

            <Panel
              icon={<CalendarDays size={14} />}
              title="Avg Change from Open"
              subtitle="Perfil intradía medio · 12 meses superpuestos"
            >
              <SeasonalityModule baseParams={params} />
            </Panel>

            <Panel
              icon={<Table2 size={14} />}
              title="Recent Gaps Up"
              subtitle={`${recordsFiltered.length} gappers · click en el ticker para abrir el detalle`}
            >
              <RecentGapsTable records={recordsFiltered} onTicker={(t) => router.push(`/analysis/${t}`)} />
            </Panel>
          </>
        ) : null}
      </div>
    </div>
  );
}

// ── KPI strip (MA-01) ────────────────────────────────────────────────────────
function KpiStrip({ data }: { data: MarketAnalysisResponse }) {
  const k = data.kpis;
  const rail = [
    { label: "PM High Avg", v: fmtPrice(k.pm_high_average.value), raw: k.pm_high_average.value, prev: k.pm_high_average.prev },
    { label: "Close Red %", v: fmtPct(k.close_red_pct.value), raw: k.close_red_pct.value, prev: k.close_red_pct.prev },
    { label: "Avg Fade PMH", v: fmtPct(k.avg_fade_from_pmh.value), raw: k.avg_fade_from_pmh.value, prev: k.avg_fade_from_pmh.prev },
    {
      label: "Max Fade PMH",
      v: fmtPct(k.max_fade_from_pmh.value),
      raw: null as number | null, // sin "vs ant." — es un extremo puntual
      prev: null,
      hint: k.max_fade_from_pmh.ticker ? `${k.max_fade_from_pmh.ticker} · ${k.max_fade_from_pmh.date}` : undefined,
    },
    { label: "Close < VWAP %", v: "Fase 2", raw: null, prev: null, muted: true },
  ];

  return (
    <div className="ma-kpi-strip">
      {/* Hero — pulso del periodo */}
      <Card featured padded style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <Activity size={13} style={{ color: color.copper }} />
          <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2, color: color.copper }}>Pulso del periodo</span>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 18, flexWrap: "wrap" }}>
          <HeroStat label="Gappers" value={fmtInt(k.gappers_count.value)} raw={k.gappers_count.value} prev={k.gappers_count.prev} />
          <HeroStat label="Avg Gap" value={fmtPct(k.avg_gap_pct.value)} raw={k.avg_gap_pct.value} prev={k.avg_gap_pct.prev} />
        </div>
      </Card>

      {/* Rail — métricas secundarias */}
      <div className="ma-kpi-rail">
        {rail.map((c) => {
          const delta = c.raw != null && c.prev != null ? c.raw - c.prev : null;
          return (
            <Card key={c.label} padded style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, color: color.textMuted }}>{c.label}</span>
              <span style={{ fontSize: 20, fontWeight: 600, color: c.muted ? color.textMuted : color.textHigh, letterSpacing: "-0.5px", fontFamily: font.serif }} title={c.hint}>{c.v}</span>
              <DeltaLine delta={delta} hint={c.hint} />
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function HeroStat({ label, value, raw, prev }: { label: string; value: string; raw: number | null; prev?: number | null }) {
  const delta = raw != null && prev != null ? raw - prev : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5, color: color.textMuted }}>{label}</span>
      <span style={{ fontFamily: font.serif, fontSize: 38, fontWeight: 600, color: "#F0EEEA", letterSpacing: "-1px", lineHeight: 1 }}>{value}</span>
      <DeltaLine delta={delta} />
    </div>
  );
}

/** Delta vs periodo anterior — neutro a propósito (no implica bueno/malo). */
function DeltaLine({ delta, hint }: { delta: number | null; hint?: string }) {
  if (delta == null) return <span style={{ fontSize: 10, color: color.textMuted }}>{hint || " "}</span>;
  const up = delta >= 0;
  return (
    <span style={{ fontSize: 10, fontWeight: 600, color: color.textSecondary, display: "inline-flex", alignItems: "center", gap: 4, fontVariantNumeric: "tabular-nums" }}>
      <span style={{ color: up ? color.profit : color.loss }}>{up ? "▲" : "▼"}</span>
      {Math.abs(delta).toFixed(1)} <span style={{ color: color.textMuted, fontWeight: 500 }}>vs ant.</span>
    </span>
  );
}

// ── Timing (MA-02) — un único chart con ventana 5D/30D/90D ───────────────────
const DIST_WINDOWS = [
  { id: "5d", label: "5D" },
  { id: "30d", label: "30D" },
  { id: "90d", label: "90D" },
] as const;
type DistWindow = (typeof DIST_WINDOWS)[number]["id"];

function TimingLegend() {
  const items: [keyof typeof SERIES_COLOR, string][] = [["hod", "HOD"], ["lod", "LOD"], ["pmh", "PM High"]];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      {items.map(([k, lbl]) => (
        <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, color: color.textSecondary }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: SERIES_COLOR[k] }} />
          {lbl}
        </span>
      ))}
    </div>
  );
}

function TimingModule({ baseParams, fallback }: { baseParams: URLSearchParams; fallback: MarketAnalysisResponse["distributions"] }) {
  const [win, setWin] = useState<DistWindow>("30d");
  const [dist, setDist] = useState(fallback);

  useEffect(() => {
    const ctrl = new AbortController();
    const p = new URLSearchParams(baseParams);
    p.set("period", win); // ventana independiente del selector global (PRD MA-02)
    getMarketAnalysis(p, ctrl.signal)
      .then((res) => setDist(res.distributions))
      .catch(() => {});
    return () => ctrl.abort();
  }, [win, baseParams]);

  const dominant = (rec: Record<string, number>) =>
    Object.entries(rec).reduce<[string, number]>((acc, e) => (e[1] > acc[1] ? e : acc), ["—", 0]);
  const [domF, domP] = dominant(dist.hod_time);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 11, color: color.textSecondary }}>
          Pico HOD más probable: <strong style={{ color: color.copper }}>{domF}</strong>{domP ? ` · ${domP.toFixed(1)}%` : ""}
        </span>
        <SegmentedControl<DistWindow> size="sm" options={DIST_WINDOWS.map((w) => ({ id: w.id, label: w.label }))} value={win} onChange={setWin} />
      </div>
      <TimingChart hod={dist.hod_time} lod={dist.lod_time} pmh={dist.pmh_time} height={240} />
    </div>
  );
}

// ── MAE / MFE (MA-05) ────────────────────────────────────────────────────────
function MaeMfePanel({ data }: { data: MarketAnalysisResponse }) {
  const [mode, setMode] = useState<"rth" | "pm">("rth");
  const block = data.mae_mfe[mode];
  return (
    <Panel
      icon={<ArrowLeftRight size={14} />}
      title="MAE / MFE"
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
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <MaeMfeTornado mae={block.mae} mfe={block.mfe} height={256} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <StatTriplet title="MAE" hist={block.mae} tone={color.loss} />
          <StatTriplet title="MFE" hist={block.mfe} tone={color.copper} />
        </div>
      </div>
    </Panel>
  );
}

function StatTriplet({ title, hist, tone }: { title: string; hist: MarketAnalysisResponse["mae_mfe"]["rth"]["mae"]; tone: string }) {
  return (
    <div style={{ border: `0.5px solid ${color.border}`, borderRadius: 8, padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 1, color: tone }}>{title}</span>
        <span style={{ fontSize: 11, color: color.textHigh, fontVariantNumeric: "tabular-nums" }}>x̄ {hist.mean.toFixed(1)}%</span>
      </div>
      <div style={{ display: "flex", gap: 10, fontSize: 9, color: color.textMuted, fontVariantNumeric: "tabular-nums" }}>
        <span>P25 {hist.p25.toFixed(1)}</span>
        <span>P50 {hist.p50.toFixed(1)}</span>
        <span>P75 {hist.p75.toFixed(1)}</span>
      </div>
    </div>
  );
}

// ── Avg Change from Open (MA-04) ─────────────────────────────────────────────
function SeasonalityModule({ baseParams }: { baseParams: URLSearchParams }) {
  const [months, setMonths] = useState<MaMonthCurve[]>([]);
  const [highlight, setHighlight] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    getAvgChangeFromOpen(baseParams, ctrl.signal)
      .then((res) => {
        setMonths(res);
        setHighlight(res.length ? res[res.length - 1].month : "");
        setFailed(false);
      })
      .catch((e) => { if ((e as Error)?.name !== "AbortError") setFailed(true); })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [baseParams]);

  if (loading) return <ChartSkeleton label="Cargando perfiles mensuales…" />;
  if (failed || months.length === 0)
    return <div style={{ minHeight: 120, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, color: color.textMuted }}>Sin datos de perfil mensual.</div>;

  const sel = months.find((m) => m.month === highlight) ?? months[months.length - 1];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: color.textSecondary }}>
          Resaltado: <strong style={{ color: color.copper }}>{sel.label}</strong>
          <span style={{ color: color.textMuted }}> · avg gap {sel.avg_gap_pct.toFixed(0)}%</span>
        </span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {months.map((m) => {
            const active = m.month === highlight;
            return (
              <button
                key={m.month}
                onClick={() => setHighlight(m.month)}
                style={{
                  fontFamily: font.sans, fontSize: 10, fontWeight: 600, cursor: "pointer",
                  padding: "3px 9px", borderRadius: 999,
                  border: `0.5px solid ${active ? color.copper : color.border}`,
                  background: active ? "rgba(216,122,61,0.12)" : "transparent",
                  color: active ? color.copperBright : color.textMuted,
                  transition: "all .15s ease",
                }}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      </div>
      <SeasonalityChart months={months} highlight={highlight} height={260} />
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
                <Td style={{ textAlign: "right", color: color.copperBright, fontVariantNumeric: "tabular-nums" }}>{r.gap_at_open_pct.toFixed(1)}%</Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmtPrice(r.open)}</Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmtVol(r.vol_rth)}</Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmtVol(r.vol_pm)}</Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmtPrice(r.hod)}</Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmtPrice(r.pmh)}</Td>
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
function Panel({ icon, title, subtitle, right, children }: { icon?: React.ReactNode; title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card padded style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          {icon && <span style={{ color: color.copper, display: "flex", marginTop: 1 }}>{icon}</span>}
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <h2 style={{ fontFamily: font.serif, fontSize: 16, fontWeight: 500, color: color.textHigh, margin: 0, letterSpacing: "-0.2px" }}>{title}</h2>
            {subtitle && <span style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, color: color.textMuted }}>{subtitle}</span>}
          </div>
        </div>
        {right}
      </div>
      {children}
    </Card>
  );
}

function ChartSkeleton({ label }: { label: string }) {
  return (
    <div style={{ minHeight: 200, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, color: color.textMuted }}>
      <div style={{ width: 24, height: 24, border: `2px solid ${color.border}`, borderTop: `2px solid ${color.copper}`, borderRadius: "50%", animation: "ma-spin 1s linear infinite" }} />
      <span style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 1.5 }}>{label}</span>
    </div>
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

// Layout responsivo del dashboard (media queries → no se pueden hacer inline).
const DASH_CSS = `
@keyframes ma-spin { 0% { transform: rotate(0); } 100% { transform: rotate(360deg); } }
.ma-dash .ma-kpi-strip { display: grid; grid-template-columns: minmax(230px, 0.85fr) minmax(0, 2.3fr); gap: 14px; }
.ma-dash .ma-kpi-rail { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.ma-dash .ma-mid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 1180px) {
  .ma-dash .ma-kpi-rail { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 1000px) {
  .ma-dash .ma-mid { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .ma-dash .ma-kpi-strip { grid-template-columns: 1fr; }
  .ma-dash .ma-kpi-rail { grid-template-columns: repeat(2, 1fr); }
}
`;
