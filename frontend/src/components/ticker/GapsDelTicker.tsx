"use client";
// GAPS DEL TICKER (Jaume, 12-sep-2026). Lista de los dias de gap del ticker
// desde 2019, al estilo de la pestaña «Trades» del backtester, y al pulsar
// una fila se despliega debajo el MISMO grafico de «Analisis por trade» (con
// sus indicadores), en grande. Es solo visualizacion: no toca ningun dato ni
// ningun motor. Los dias salen del hot cache diario del backend (gap >= 10 %)
// y las velas del endpoint /candles del backtester, que lee el lago; el
// dataset que pide ese endpoint no se usa para nada fuera del mock, asi que
// se le pasa un nombre fijo.
import React, { Fragment, useEffect, useMemo, useState } from "react";
import { getTickerGapDays, type TickerGapDay } from "@/lib/api";
import { fetchDayCandles, type DayCandles } from "@/lib/api_backtester";
import PanelAnalisisTrade from "@/components/backtester/PanelAnalisisTrade";

type SortKey = keyof TickerGapDay;
type SortDir = "asc" | "desc";

const COLS: { key: SortKey; label: string; fmt: (v: number) => string; tono?: (v: number) => string; title?: string }[] = [
  { key: "date", label: "Fecha", fmt: (v) => String(v) },
  { key: "gap_pct", label: "Gap %", fmt: (v) => `${v.toFixed(1)}%`, tono: (v) => (v >= 0 ? "var(--success)" : "var(--danger)"),
    title: "Gap de la apertura de sesión sobre el cierre de ayer" },
  { key: "pmh_gap_pct", label: "PMH gap %", fmt: (v) => `${v.toFixed(1)}%`, tono: () => "var(--color-ec-copper)",
    title: "Máximo del premercado sobre el cierre de ayer" },
  { key: "prev_close", label: "Cierre ayer", fmt: (v) => `$${v.toFixed(2)}` },
  { key: "pm_high", label: "PM High", fmt: (v) => `$${v.toFixed(2)}` },
  { key: "open", label: "Open", fmt: (v) => `$${v.toFixed(2)}` },
  { key: "high", label: "High", fmt: (v) => `$${v.toFixed(2)}` },
  { key: "low", label: "Low", fmt: (v) => `$${v.toFixed(2)}` },
  { key: "close", label: "Close", fmt: (v) => `$${v.toFixed(2)}` },
  { key: "day_return_pct", label: "Día %", fmt: (v) => `${v.toFixed(1)}%`, tono: (v) => (v >= 0 ? "var(--success)" : "var(--danger)"),
    title: "Cierre sobre apertura de sesión" },
  { key: "pmh_fade_pct", label: "Fade PMH %", fmt: (v) => `${v.toFixed(1)}%`,
    title: "Cuánto cayó el cierre desde el máximo del premercado" },
  { key: "pm_volume", label: "Vol PM", fmt: fmtVol, title: "Volumen del premercado" },
  { key: "rth_volume", label: "Vol RTH", fmt: fmtVol, title: "Volumen de la sesión regular" },
];

function fmtVol(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v.toFixed(0);
}

export default function GapsDelTicker({ ticker }: { ticker: string }) {
  // El padre monta el componente con `key={ticker}`: al cambiar de ticker se
  // vuelve a montar limpio, asi que aqui no hay que vaciar nada a mano.
  const [dias, setDias] = useState<TickerGapDay[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [velas, setVelas] = useState<DayCandles | null>(null);
  const [cargandoVelas, setCargandoVelas] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [busca, setBusca] = useState("");
  const [visibles, setVisibles] = useState(15);
  const [plegado, setPlegado] = useState(false);

  // Lista de dias del ticker (una llamada, del hot cache del backend).
  useEffect(() => {
    if (!ticker) return;
    let cancelado = false;
    const ctrl = new AbortController();
    getTickerGapDays(ticker, { signal: ctrl.signal })
      .then((r) => { if (!cancelado) setDias(r?.days || []); })
      .catch((e) => { if (!cancelado && e?.name !== "AbortError") setError(String(e?.message || e)); })
      .finally(() => { if (!cancelado) setCargando(false); });
    return () => { cancelado = true; ctrl.abort(); };
  }, [ticker]);

  // Velas del dia desplegado. Un solo dia abierto a la vez; el estado de
  // carga lo pone el click (abrirDia), aqui solo se pide y se recoge.
  useEffect(() => {
    if (!abierta || !ticker) return;
    let cancelado = false;
    const fecha = abierta;
    fetchDayCandles("ticker-analysis", ticker, fecha)
      .then((d) => { if (!cancelado) setVelas(d); })
      .catch(() => { if (!cancelado) setVelas({ ticker, date: fecha, candles: [] }); })
      .finally(() => { if (!cancelado) setCargandoVelas(false); });
    return () => { cancelado = true; };
  }, [abierta, ticker]);

  const abrirDia = (fecha: string) => {
    if (abierta === fecha) { setAbierta(null); setVelas(null); setCargandoVelas(false); return; }
    setVelas(null); setCargandoVelas(true); setAbierta(fecha);
  };

  const filtradas = useMemo(() => {
    const q = busca.trim().toLowerCase();
    const out = q ? dias.filter((d) => d.date.toLowerCase().includes(q)) : dias.slice();
    out.sort((a, b) => {
      const av = a[sortKey]; const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
    return out;
  }, [dias, busca, sortKey, sortDir]);

  const ordenar = (k: SortKey) => {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir(k === "date" ? "desc" : "desc"); }
  };

  const resumen = useMemo(() => {
    if (!dias.length) return null;
    const gaps = dias.map((d) => d.gap_pct ?? 0);
    const pmh = dias.map((d) => d.pmh_gap_pct ?? 0);
    const anyos = new Set(dias.map((d) => d.date.slice(0, 4)));
    return {
      n: dias.length,
      desde: dias[dias.length - 1]?.date,
      hasta: dias[0]?.date,
      anyos: anyos.size,
      gapMax: Math.max(...gaps),
      pmhMax: Math.max(...pmh),
      rojos: dias.filter((d) => (d.day_return_pct ?? 0) < 0).length,
    };
  }, [dias]);

  if (!ticker) return null;

  const et: React.CSSProperties = {
    fontFamily: "var(--color-ec-sans)", fontSize: 9, fontWeight: 700,
    textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--color-ec-text-muted)",
  };

  return (
    <div style={{ marginBottom: 20, border: "1px solid var(--color-ec-border)", background: "var(--color-ec-bg-surface)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
                    padding: "8px 12px", borderBottom: plegado ? undefined : "0.5px solid var(--color-ec-border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button type="button" onClick={() => setPlegado(!plegado)}
                  title={plegado ? "Desplegar la lista de gaps" : "Plegar la lista de gaps"}
                  style={{ background: "none", border: 0, cursor: "pointer", color: "var(--color-ec-copper)",
                           fontFamily: "var(--color-ec-mono)", fontSize: 12, padding: 0, width: 14 }}>
            {plegado ? "▸" : "▾"}
          </button>
          <span style={{ ...et, color: "var(--color-ec-copper)" }}>Gaps de {ticker} desde 2019</span>
          {resumen && (
            <span style={{ fontFamily: "var(--color-ec-mono)", fontSize: 10, color: "var(--color-ec-text-secondary)" }}
                  title="Días con gap ≥ 10 % sobre el cierre de ayer, que es el umbral con el que el lago guarda los gappers">
              <strong style={{ color: "var(--color-ec-text-high)" }}>{resumen.n}</strong> días · {resumen.desde} → {resumen.hasta}
              {" "}· gap máx <strong style={{ color: "var(--color-ec-text-high)" }}>{resumen.gapMax.toFixed(0)}%</strong>
              {" "}· PMH máx <strong style={{ color: "var(--color-ec-copper)" }}>{resumen.pmhMax.toFixed(0)}%</strong>
              {" "}· cerró en rojo <strong style={{ color: "var(--danger)" }}>{resumen.rojos}</strong> de {resumen.n}
            </span>
          )}
          {cargando && <span style={{ fontFamily: "var(--color-ec-mono)", fontSize: 10, color: "var(--color-ec-text-muted)" }}>cargando…</span>}
          {error && <span style={{ fontFamily: "var(--color-ec-mono)", fontSize: 10, color: "var(--danger)" }}>{error}</span>}
        </div>
        {!plegado && (
          <input type="text" placeholder="filtrar por fecha (2025, 2025-07…)" value={busca}
                 onChange={(e) => { setBusca(e.target.value); setVisibles(15); }}
                 className="px-2 py-1 text-[11px] font-mono bg-transparent focus:outline-none"
                 style={{ border: "none", borderBottom: "1px solid var(--color-ec-border)", color: "var(--foreground)", width: 200 }} />
        )}
      </div>

      {!plegado && (
        <>
          {!cargando && !dias.length && !error && (
            <div style={{ padding: "14px 12px", fontFamily: "var(--color-ec-mono)", fontSize: 11, color: "var(--color-ec-text-muted)" }}>
              Sin días de gap (≥ 10 %) para {ticker} en el lago.
            </div>
          )}
          {dias.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table className="w-full text-[11px] font-mono" style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--color-ec-border)" }}>
                    <th style={{ width: 18 }} />
                    {COLS.map((c) => (
                      <th key={String(c.key)} onClick={() => ordenar(c.key)} title={c.title}
                          className="px-3 py-1.5 text-left cursor-pointer select-none"
                          style={{ ...et, letterSpacing: "0.08em", whiteSpace: "nowrap",
                                   color: sortKey === c.key ? "var(--color-ec-text-high)" : "var(--color-ec-text-muted)" }}>
                        {c.label}{sortKey === c.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtradas.slice(0, visibles).map((d) => {
                    const esta = abierta === d.date;
                    return (
                      <Fragment key={d.date}>
                        <tr onClick={() => abrirDia(d.date)}
                            className="cursor-pointer"
                            style={{ borderBottom: "0.5px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)",
                                     background: esta ? "rgba(216, 122, 61, 0.08)" : "transparent" }}
                            title={esta ? "Cerrar el gráfico" : "Ver el gráfico intradía de este día aquí mismo"}>
                          <td style={{ padding: "0 0 0 8px", color: "var(--color-ec-copper)", fontSize: 10 }}>{esta ? "▾" : "▸"}</td>
                          {COLS.map((c) => {
                            const v = d[c.key];
                            const num = typeof v === "number" ? v : null;
                            const texto = v == null ? "—" : c.key === "date" ? String(v) : (num != null ? c.fmt(num) : String(v));
                            const tono = num != null && c.tono ? c.tono(num) : (c.key === "date" ? "var(--color-ec-text-high)" : "var(--color-ec-text-primary)");
                            return (
                              <td key={String(c.key)} className="px-3 py-1.5" style={{ color: tono, whiteSpace: "nowrap",
                                                                                     fontWeight: c.key === "date" ? 600 : 400 }}>
                                {texto}
                              </td>
                            );
                          })}
                        </tr>
                        {esta && (
                          <tr>
                            <td colSpan={COLS.length + 1} style={{ padding: "10px 16px 18px", background: "var(--color-ec-bg-sidebar)" }}>
                              <PanelAnalisisTrade
                                dayCandles={velas}
                                activeStrategy={null}
                                currentTrades={[]}
                                currentEquity={[]}
                                candlesLoading={cargandoVelas}
                                loadProgress={cargandoVelas ? 50 : 100}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {filtradas.length > visibles && (
            <div className="flex items-center justify-center gap-3 py-2">
              <span className="text-[10px] font-mono" style={{ color: "var(--color-ec-text-muted)" }}>
                mostrando {Math.min(visibles, filtradas.length)} de {filtradas.length}
              </span>
              <button onClick={() => setVisibles((v) => v + 30)}
                      className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider cursor-pointer"
                      style={{ border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-secondary)", background: "transparent" }}>
                Mostrar más (+30)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
