"use client";

/**
 * Market Analysis — dashboard de inteligencia de gappers small-cap.
 * Contrato/diseño: docs/market-analysis/PRD.md (MVP v1.0) + PRD_PATCH_v2.1.md.
 *
 * Gráficos construidos con visx (./market-analysis/charts) — reemplazan a recharts
 * SOLO en esta página. Layout pensado como panel (bento), no como pila de secciones:
 *   · KPI strip   — 5 tarjetas uniformes (§07)
 *   · Timing      — HOD/LOD/PM High superpuestos en un único eje intradía (MA-02)
 *   · Ventanas de Fade — caída media por franja de entrada, RTH (§04)
 *   · Seasonality — 12 curvas mensuales de Avg Change from Open, universo estándar (§06)
 * La página es informativa de condiciones de mercado: sin listado de tickers (§05).
 * Edgie recibe el contexto de filtros/periodo/datos vía evento window (§08).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Filter, RotateCcw, TrendingDown, Clock, ArrowLeftRight, CalendarDays } from "lucide-react";
import { color, font, Card, Button, Table, Th, Td, Tr, SegmentedControl, Input } from "@/components/ui";
import { TimingChart, SeasonalityChart, SERIES_COLOR } from "@/components/market-analysis/charts";
import { ChatBot } from "@/components/ChatBot";
import {
  getMarketAnalysis,
  getAvgChangeFromOpen,
  type MarketAnalysisResponse,
  type MaKpiValue,
  type MaFadeWindow,
  type MaMonthCurve,
} from "@/lib/api";

// ── helpers de formato ───────────────────────────────────────────────────────
const fmtPct = (v: number | null | undefined, dp = 1) =>
  v === null || v === undefined ? "—" : `${v.toFixed(dp)}%`;
const fmtInt = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : Math.round(v).toLocaleString("en-US");

// ── tipos de filtros (estado de UI) ──────────────────────────────────────────
type Period = "1w" | "1m" | "3m" | "6m" | "1y";
type TriState = "all" | "yes" | "no";

interface Filters {
  period: Period;
  min_gap: string;
  min_open: string;
  max_open: string;
  min_day_volume: string; // volumen del día = PM + RTH (principio 00; no incluye after-hours)
  min_pm_volume: string;
  close_red: TriState;
  fade_threshold: string;
}

const DEFAULTS: Filters = {
  period: "1m",
  min_gap: "30",
  min_open: "",
  max_open: "",
  min_day_volume: "1000000",
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
  if (f.min_day_volume) p.set("min_day_volume", f.min_day_volume);
  if (f.min_pm_volume) p.set("min_pm_volume", f.min_pm_volume);
  if (f.fade_threshold) p.set("fade_threshold", f.fade_threshold);
  // close_red server-side (§05): al no haber tabla, el filtro afecta a KPIs y módulos
  if (f.close_red !== "all") p.set("close_red", f.close_red);
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

  // §08 — contexto de página para Edgie: en cada payload se publica lo que el
  // usuario está viendo (periodo, filtros, KPIs, fades, exclusiones y una
  // muestra acotada de records). Al desmontar se limpia para no contaminar
  // otras páginas. ChatBot.tsx lo escucha e inyecta la sección en su prompt.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!data) return;
    const detail = {
      period: data.period,
      preset: filters.period,
      filters: {
        min_gap_pct: filters.min_gap, min_open: filters.min_open, max_open: filters.max_open,
        min_day_volume: filters.min_day_volume, min_pm_volume: filters.min_pm_volume,
        close_red: filters.close_red, fade_threshold: filters.fade_threshold,
      },
      kpis: data.kpis,
      fade_windows: data.fade_windows,
      quality_filters: data.quality_filters,
      distributions_hod_top: Object.entries(data.distributions.hod_time)
        .sort((a, b) => b[1] - a[1]).slice(0, 3),
      records_sample: data.records.slice(0, 20),
    };
    (window as unknown as Record<string, unknown>).__lastMarketAnalysisContext = detail;
    window.dispatchEvent(new CustomEvent("market-analysis-context", { detail }));
  }, [data, filters]);

  useEffect(() => () => {
    if (typeof window === "undefined") return;
    (window as unknown as Record<string, unknown>).__lastMarketAnalysisContext = null;
    window.dispatchEvent(new CustomEvent("market-analysis-context", { detail: null }));
  }, []);

  const isEmpty = data ? (data.kpis.gappers_count.value ?? 0) === 0 : false;
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
          <span style={{ fontSize: 11, fontWeight: 600, color: color.textMuted, background: color.bgSurface, padding: "4px 10px", borderRadius: 6, border: `1px solid ${color.border}` }}>1M</span>
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
          {/* Principio 00: el volumen del día es PM+RTH y la sesión se dice en la etiqueta */}
          <FilterNum label="Vol día (PM+RTH) mín" value={filters.min_day_volume} onChange={(v) => setFilters((f) => ({ ...f, min_day_volume: v }))} />
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
        ) : data && isEmpty ? (
          <EmptyState onClear={() => setFilters((f) => ({ ...DEFAULTS, period: f.period }))} />
        ) : data ? (
          <>
            <KpiStrip data={data} />
            <QualityLine qf={data.quality_filters} />

            <div className="ma-mid">
              <Panel
                icon={<Clock size={14} />}
                title="Distribución temporal"
                subtitle="Cuándo ocurre el HOD, el LOD y el PM High"
                right={<TimingLegend />}
              >
                <TimingModule baseParams={params} fallback={data.distributions} />
              </Panel>

              <FadeWindowsPanel data={data} />
            </div>

            <Panel
              icon={<CalendarDays size={14} />}
              title="Avg Change from Open"
              subtitle="Perfil intradía medio · 12 meses · universo estándar: gap ≥30% · vol día ≥1M · filtros de calidad"
            >
              <SeasonalityModule />
            </Panel>
          </>
        ) : null}
      </div>

      {/* §08 — Edgie flotante colapsable, mismo widget que el resto de la app */}
      <ChatBot />
    </div>
  );
}

// ── KPI strip (MA-01 · patch §03/§07: 5 tarjetas uniformes) ──────────────────
// Gappers Count y Avg Gap % llevan toggle PM/RTH VISIBLE (§07 — la distinción de
// sesión nunca es una decisión silenciosa del backend). "Pulso del Periodo" y las
// tarjetas Max Fade / Close<VWAP desaparecen (§03).
function KpiStrip({ data }: { data: MarketAnalysisResponse }) {
  const k = data.kpis;
  return (
    <div className="ma-kpi-rail">
      <SimpleKpiCard label="Gappers Count" kpi={k.gappers_count} fmt={fmtInt} sub="total de gappers del universo del periodo" />
      <SimpleKpiCard label="Avg Gap %" kpi={k.avg_gap_pct} fmt={(v) => fmtPct(v)} sub="open 09:30 vs cierre anterior" />
      <SimpleKpiCard label="PM High Gap %" kpi={k.pm_high_gap_pct} sub="media de (PMH − prev close) / prev close" />
      <SimpleKpiCard label="Close Red %" kpi={k.close_red_pct} sub="cierran por debajo del open" />
      <SimpleKpiCard label="Avg Fade desde PMH" kpi={k.avg_fade_from_pmh} sub="a cierre EOD · universo gap ≥ umbral" />
    </div>
  );
}

function SimpleKpiCard({ label, kpi, sub, fmt }: { label: string; kpi: MaKpiValue; sub?: string; fmt?: (v: number | null | undefined) => string }) {
  const delta = kpi.value != null && kpi.prev != null ? kpi.value - kpi.prev : null;
  const fmtFn = fmt || fmtPct;
  return (
    <Card padded style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, color: color.textMuted }}>{label}</span>
      <span style={{ fontSize: 20, fontWeight: 600, color: color.textHigh, letterSpacing: "-0.5px", fontFamily: font.serif }}>{fmtFn(kpi.value)}</span>
      <DeltaLine delta={delta} />
      <span style={{ fontSize: 9, color: color.textMuted, lineHeight: 1.3 }}>{sub || " "}</span>
    </Card>
  );
}

/** Exclusiones de calidad del universo (§01) — visibles, nunca silenciosas (principio 00). */
function QualityLine({ qf }: { qf: MarketAnalysisResponse["quality_filters"] }) {
  const total = qf.excluded_ticker_type + qf.excluded_gap_gt_1000 + qf.excluded_same_day_split
    + qf.excluded_reverse_split + (qf.excluded_black_swan ?? 0);
  const parts = [
    qf.excluded_reverse_split > 0 && `${qf.excluded_reverse_split} reverse split ≤5d`,
    qf.excluded_same_day_split > 0 && `${qf.excluded_same_day_split} split mismo día`,
    qf.excluded_gap_gt_1000 > 0 && `${qf.excluded_gap_gt_1000} gap >1000%`,
    (qf.excluded_black_swan ?? 0) > 0 && `${qf.excluded_black_swan} black swan 5min >300%`,
    qf.excluded_ticker_type > 0 && `${qf.excluded_ticker_type} tipo no operable`,
  ].filter(Boolean);
  return (
    <div style={{ fontSize: 10, color: color.textMuted, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: 1 }}>Calidad de datos</span>
      <span>
        {total > 0
          ? `${total} ticker-días excluidos del universo (${parts.join(" · ")})`
          : "sin exclusiones en este periodo"}
        {qf.excluded_black_swan === null ? " · black swan pendiente de backfill" : ""}
      </span>
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

// ── Timing (MA-02) — ventana fija 30D ───────────────────
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
  const [dist, setDist] = useState(fallback);

  useEffect(() => {
    const ctrl = new AbortController();
    const p = new URLSearchParams(baseParams);
    p.set("period", "30d");
    getMarketAnalysis(p, ctrl.signal)
      .then((res) => setDist(res.distributions))
      .catch(() => {});
    return () => ctrl.abort();
  }, [baseParams]);

  const dominant = (rec: Record<string, number>) =>
    Object.entries(rec).reduce<[string, number]>((acc, e) => (e[1] > acc[1] ? e : acc), ["—", 0]);
  const [domF, domP] = dominant(dist.hod_time);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 11, color: color.textSecondary }}>
          Pico HOD más probable: <strong style={{ color: color.copper }}>{domF}</strong>{domP ? ` · ${domP.toFixed(1)}%` : ""}
        </span>
        <span style={{ fontSize: 10, fontWeight: 600, color: color.textMuted, background: color.bgSurface, padding: "2px 8px", borderRadius: 4, border: `1px solid ${color.border}` }}>30D</span>
      </div>
      <TimingChart hod={dist.hod_time} lod={dist.lod_time} pmh={dist.pmh_time} height={240} />
    </div>
  );
}

// ── Ventanas de Fade (patch §04 — sustituye a MAE/MFE) ───────────────────────
// "MAE/MFE no tiene sentido sin un trade abierto." Entrada = close de la vela de
// la franja (RTH) o el PM High (modo PM); salida = close EOD. Toggle PM/RTH visible.
function FadeWindowsPanel({ data }: { data: MarketAnalysisResponse }) {
  const fw = data.fade_windows;
  const rows = fw.rth;
  return (
    <Panel
      icon={<ArrowLeftRight size={14} />}
      title="Ventanas de Fade"
      subtitle="Caída media de los gappers por franja de entrada · RTH"
      right={
        <span style={{ fontSize: 10, fontWeight: 600, color: color.textMuted, background: color.bgSurface, padding: "2px 8px", borderRadius: 4, border: `1px solid ${color.border}` }}>RTH</span>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <span style={{ fontSize: 11, color: color.textSecondary }}>
          Entrada: close de la vela de la franja · salida: close EOD (15:59)
        </span>
        <Table>
          <thead>
            <Tr>
              <Th>Franja</Th>
              <Th style={{ textAlign: "right" }}>Avg Fade %</Th>
              <Th style={{ textAlign: "right" }}>% favorable short</Th>
              <Th style={{ textAlign: "right" }}>N</Th>
            </Tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Tr key={r.franja}>
                <Td style={{ fontWeight: 600, color: color.textHigh }}>{r.franja}</Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: (r.avg_fade_pct ?? 0) > 0 ? color.copperBright : color.textPrimary }}
                    title={r.pending_backfill ? "Backfill del derivado en curso — franja disponible en cuanto termine" : undefined}>
                  {r.pending_backfill ? "—" : fmtPct(r.avg_fade_pct)}
                </Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}
                    title={r.pending_backfill ? "Backfill del derivado en curso" : undefined}>
                  {r.pending_backfill ? "—" : fmtPct(r.pct_favorable, 0)}
                </Td>
                <Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: color.textMuted }}>{r.n}</Td>
              </Tr>
            ))}
          </tbody>
        </Table>
        <span style={{ fontSize: 10, color: color.textMuted }}>
          Fade = (entrada − salida) / entrada × 100 · favorable = el precio cayó desde la franja hasta el cierre
        </span>
      </div>
    </Panel>
  );
}

// ── Avg Change from Open (MA-04) ─────────────────────────────────────────────
// Curvas precalculadas sobre el UNIVERSO ESTÁNDAR (patch §06 / Q3): no obedecen a
// los filtros globales — la independencia se declara en el subtítulo del panel.
function SeasonalityModule() {
  const [months, setMonths] = useState<MaMonthCurve[]>([]);
  const [highlight, setHighlight] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    getAvgChangeFromOpen("", ctrl.signal)
      .then((res) => {
        setMonths(res);
        setHighlight(res.length ? res[res.length - 1].month : "");
        setFailed(false);
      })
      .catch((e) => { if ((e as Error)?.name !== "AbortError") setFailed(true); })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, []);

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
// §07: las 5 tarjetas KPI comparten formato — un único grid uniforme, sin hero.
const DASH_CSS = `
@keyframes ma-spin { 0% { transform: rotate(0); } 100% { transform: rotate(360deg); } }
.ma-dash .ma-kpi-rail { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.ma-dash .ma-mid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 1180px) {
  .ma-dash .ma-kpi-rail { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 1000px) {
  .ma-dash .ma-mid { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .ma-dash .ma-kpi-rail { grid-template-columns: repeat(2, 1fr); }
}
`;
