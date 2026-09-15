"use client";

// Calendario del portfolio en crudo: el mismo calendario del Backtester
// (Profits / Gastos / Profits − Gastos, en $ o en R, meses con la columna de
// semana, y el detalle del dia al pulsar) pero sobre el RESULTADO TOTAL del
// portfolio, con los trades del dia agrupados por estrategia.
//
// No hace falta volver a correr nada: el motor devuelve cada trade aceptado
// (ya re-dimensionado y filtrado por el tope) en columnas, con la R de su
// corrida — que es invariante al tamano porque PnL y riesgo escalan igual.
//
// La R del portfolio: como cada corrida tiene su propio riesgo por trade, no
// hay «1 R» comun. La R neta de un dia es la SUMA de las R de sus trades; el
// bruto se pasa a R trade a trade (riesgo = |PnL| / |R|); locates y gastos
// fijos, que no son de ningun trade, se pasan con el riesgo medio del dia.

import React, { Fragment, useEffect, useMemo, useState } from "react";
import { color, font, hairline } from "@/components/ui/tokens";
import { Help } from "@/components/robustez/help";
import type { RawOut } from "@/lib/api_portfolio_lab";
import { Toggle, colorSerie, etiqueta, n, tdNum, tdTxt, thL, thR } from "./hoja";

type Modo = "profits" | "gastos" | "net";
type Unidad = "dinero" | "r";

interface DiaStats {
  profits: number;
  gastos: number;
  net: number;
  profitsR: number;
  gastosR: number;
  netR: number;
  count: number;
  /** false si ningun trade del dia tenia R utilizable. */
  tieneR: boolean;
}

function fmtDinero(v: number, gastos: boolean): string {
  const a = Math.abs(v);
  const cuerpo = a >= 1000 ? `${n(a / 1000, 2)}K $` : `${n(a, 2)} $`;
  if (gastos) return cuerpo;
  return `${v >= 0 ? "+" : "−"}${cuerpo}`;
}
function fmtValor(v: number, modo: Modo, unidad: Unidad): string {
  if (unidad === "dinero") return fmtDinero(v, modo === "gastos");
  if (modo === "gastos") return `${n(Math.abs(v), 2)} R`;
  return `${v >= 0 ? "+" : "−"}${n(Math.abs(v), 2)} R`;
}

export function CalendarioCrudo({ out, names }: { out: RawOut; names: string[] }) {
  const [modo, setModo] = useState<Modo>("net");
  const [unidad, setUnidad] = useState<Unidad>("dinero");
  const [dia, setDia] = useState<string | null>(null);

  useEffect(() => {
    if (!dia) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDia(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dia]);

  // Indices de trades por dia (los trades vienen en columnas, ordenados).
  const porDia = useMemo(() => {
    const m = new Map<string, number[]>();
    const T = out.trades;
    for (let k = 0; k < T.date.length; k++) {
      const d = T.date[k];
      const cur = m.get(d);
      if (cur) cur.push(k);
      else m.set(d, [k]);
    }
    return m;
  }, [out.trades]);

  const stats = useMemo(() => {
    const T = out.trades;
    const idxDia = new Map(out.calendar.map((d, i) => [d, i] as [string, number]));
    const gastosMes = out.config.monthly_expenses || 0;
    const primerDiaMes = new Set<string>();
    {
      const vistos = new Set<string>();
      for (const d of out.calendar) {
        const mes = d.slice(0, 7);
        if (!vistos.has(mes)) {
          vistos.add(mes);
          primerDiaMes.add(d);
        }
      }
    }
    const m = new Map<string, DiaStats>();
    for (const d of out.calendar) {
      const ks = porDia.get(d) || [];
      let profits = 0, fees = 0, net = 0, sumR = 0, profitsR = 0, sumRiesgo = 0, nRiesgo = 0;
      for (const k of ks) {
        const pnl = T.pnl[k], fee = T.fees[k], r = T.r[k];
        profits += pnl + fee;
        fees += fee;
        net += pnl;
        sumR += r;
        if (r !== 0 && pnl !== 0) {
          const riesgo = Math.abs(pnl) / Math.abs(r);
          profitsR += (pnl + fee) / riesgo;
          sumRiesgo += riesgo;
          nRiesgo += 1;
        }
      }
      const i = idxDia.get(d)!;
      let locates = 0;
      let fijo = primerDiaMes.has(d) ? gastosMes : 0;
      for (const p of out.per_strategy) {
        locates += p.locates_daily[i] || 0;
        fijo += p.expenses_daily?.[i] || 0;   // los gastos fijos de cada corrida
      }
      const gastos = fees + locates + fijo;
      const netTotal = net - locates - fijo;
      const riesgoMedio = nRiesgo ? sumRiesgo / nRiesgo : 0;
      const extraR = riesgoMedio > 0 ? (locates + fijo) / riesgoMedio : 0;
      const netR = sumR - extraR;
      m.set(d, {
        profits, gastos, net: netTotal,
        profitsR, netR, gastosR: profitsR - netR,
        count: ks.length, tieneR: nRiesgo > 0,
      });
    }
    return m;
  }, [out, porDia]);

  const valorDe = (s: DiaStats): number =>
    unidad === "dinero"
      ? modo === "profits" ? s.profits : modo === "gastos" ? s.gastos : s.net
      : modo === "profits" ? s.profitsR : modo === "gastos" ? s.gastosR : s.netR;

  const meses = useMemo(() => {
    const set = new Set<string>();
    for (const d of out.calendar) set.add(d.slice(0, 7));
    return Array.from(set).sort();
  }, [out.calendar]);

  const tono = (v: number, tiene: boolean) => {
    if (!tiene) return color.textMuted;
    if (modo === "gastos") return v > 0 ? color.loss : color.textMuted;
    return v >= 0 ? color.profit : color.loss;
  };
  const fondo = (v: number, tiene: boolean) => {
    if (!tiene) return color.bgElevated;
    if (modo === "gastos") return v > 0 ? "rgba(201, 77, 63, 0.08)" : color.bgElevated;
    return v >= 0 ? "rgba(74, 157, 127, 0.08)" : "rgba(201, 77, 63, 0.08)";
  };

  return (
    <div>
      {/* Modo y unidad */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12 }}>
        <div style={{ width: 330 }}>
          <Toggle
            value={modo}
            onChange={setModo}
            options={[
              { value: "profits", label: "Profits" },
              { value: "gastos", label: "Gastos" },
              { value: "net", label: "Profits − Gastos" },
            ]}
          />
        </div>
        <div style={{ width: 110 }}>
          <Toggle value={unidad} onChange={setUnidad} options={[{ value: "dinero", label: "$" }, { value: "r", label: "R" }]} />
        </div>
        <span style={{ ...etiqueta, display: "inline-flex", alignItems: "center", gap: 5 }}>
          {unidad === "r" ? "R de cada corrida" : "dólares del portfolio"}
          <Help title="Unidad R en el portfolio">
            Cada trade conserva la <strong>R de su corrida</strong> (PnL neto / riesgo del stop), que no
            cambia al re-dimensionarlo: PnL y riesgo escalan igual. La R neta de un día es la suma de
            las R de sus trades. Como cada estrategia tiene su propio riesgo por trade, no hay un «1 R»
            común: el bruto se pasa a R trade a trade, y los locates y gastos fijos —que no son de
            ningún trade— con el riesgo medio del día.
          </Help>
        </span>
        <span style={{ marginLeft: "auto", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
          pulsa un día para ver sus trades por estrategia
        </span>
      </div>

      {/* Meses */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 12 }}>
        {meses.map((mesStr) => {
          const [y, mo] = mesStr.split("-").map(Number);
          const primero = new Date(y, mo - 1, 1);
          const ultimo = new Date(y, mo, 0);
          const inicioSemana = (primero.getDay() + 6) % 7;
          const nombreMes = primero.toLocaleString("es-ES", { month: "long", year: "numeric" });

          type Celda = null | { date: string; v: number | null; count: number; tiene: boolean };
          const celdas: Celda[] = [];
          for (let i = 0; i < inicioSemana; i++) celdas.push(null);
          for (let d = 1; d <= ultimo.getDate(); d++) {
            const ds = `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const s = stats.get(ds);
            celdas.push({ date: ds, v: s ? valorDe(s) : null, count: s ? s.count : 0, tiene: !!s && (unidad === "dinero" || s.tieneR) });
          }
          while (celdas.length % 7) celdas.push(null);
          const semanas: Celda[][] = [];
          for (let i = 0; i < celdas.length; i += 7) semanas.push(celdas.slice(i, i + 7));

          let mesV = 0, mesTr = 0;
          for (const c of celdas) if (c && c.count > 0) { mesV += c.v || 0; mesTr += c.count; }

          return (
            <div key={mesStr} style={{ border: `1px solid ${color.border}`, background: color.bgSurface, padding: "10px 10px 8px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", paddingBottom: 6, marginBottom: 6, borderBottom: hairline }}>
                <span style={{ ...etiqueta, color: color.textHigh, fontSize: 10 }}>{nombreMes}</span>
                <span style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  {mesTr > 0 && <span style={{ fontSize: 10, fontFamily: font.sans, color: color.textMuted }}>{mesTr} trades</span>}
                  {mesTr > 0 && (
                    <span style={{ fontSize: 11.5, fontFamily: font.mono, color: tono(mesV, true) }}>{fmtValor(mesV, modo, unidad)}</span>
                  )}
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1px 1.1fr", gap: 3, marginBottom: 3 }}>
                {["Lun", "Mar", "Mié", "Jue", "Vie"].map((l) => (
                  <div key={l} style={{ textAlign: "center", fontSize: 8, fontWeight: 700, color: color.textMuted, textTransform: "uppercase", letterSpacing: "0.08em" }}>{l}</div>
                ))}
                <div />
                <div style={{ textAlign: "center", fontSize: 8, fontWeight: 700, color: color.textMuted, textTransform: "uppercase", letterSpacing: "0.08em" }}>Sem</div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {semanas.map((sem, wi) => {
                  let wV = 0, wTr = 0, wHay = false;
                  for (const c of sem) if (c && c.count > 0) { wV += c.v || 0; wTr += c.count; wHay = true; }
                  return (
                    <div key={wi} style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1px 1.1fr", gap: 3 }}>
                      {sem.slice(0, 5).map((c, i) => {
                        if (!c) return <div key={`e${i}`} style={{ minHeight: 40 }} />;
                        const hay = c.count > 0;
                        const v = c.v || 0;
                        const acento = hay ? tono(v, c.tiene) : "transparent";
                        return (
                          <div
                            key={c.date}
                            title={hay ? `${c.date}: ${c.count} trades · ${fmtValor(v, modo, unidad)}` : c.date}
                            onClick={hay ? () => setDia(c.date) : undefined}
                            style={{
                              position: "relative", minHeight: 40,
                              border: `0.5px solid ${hay ? acento : color.border}`,
                              background: hay ? fondo(v, c.tiene) : color.bgElevated,
                              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                              gap: 1, padding: "3px 2px", cursor: hay ? "pointer" : "default",
                            }}
                          >
                            <span style={{ position: "absolute", top: 2, right: 4, fontSize: 8, fontWeight: 600, color: hay ? acento : color.textMuted, opacity: hay ? 1 : 0.7 }}>
                              {parseInt(c.date.slice(8), 10)}
                            </span>
                            {hay ? (
                              <>
                                <span style={{ fontSize: 9, fontWeight: 700, color: acento, fontFamily: font.mono, lineHeight: 1, whiteSpace: "nowrap" }}>
                                  {c.tiene ? fmtValor(v, modo, unidad) : "—"}
                                </span>
                                <span style={{ fontSize: 7.5, fontWeight: 600, color: acento, opacity: 0.75, fontFamily: font.sans, lineHeight: 1 }}>
                                  {c.count} {c.count === 1 ? "trade" : "trades"}
                                </span>
                              </>
                            ) : (
                              <span style={{ fontSize: 10, color: color.textMuted, opacity: 0.45 }}>—</span>
                            )}
                          </div>
                        );
                      })}
                      <div style={{ background: color.border }} />
                      <div style={{ minHeight: 40, border: wHay ? `0.5px dashed ${tono(wV, true)}` : `0.5px solid ${color.border}`, background: wHay ? fondo(wV, true) : "transparent", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 1 }}>
                        {wHay && (
                          <>
                            <span style={{ fontSize: 9, fontWeight: 800, fontFamily: font.mono, lineHeight: 1, color: tono(wV, true), whiteSpace: "nowrap" }}>{fmtValor(wV, modo, unidad)}</span>
                            <span style={{ fontSize: 7, fontWeight: 600, lineHeight: 1, opacity: 0.7, color: tono(wV, true) }}>{wTr} tr</span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {dia && <DetalleDia out={out} names={names} dia={dia} idx={porDia.get(dia) || []} stats={stats.get(dia)} onClose={() => setDia(null)} />}
    </div>
  );
}

/** El dia desplegado: sus trades, agrupados por estrategia, con subtotales. */
function DetalleDia({ out, names, dia, idx, stats, onClose }: {
  out: RawOut; names: string[]; dia: string; idx: number[]; stats?: DiaStats; onClose: () => void;
}) {
  const T = out.trades;
  const grupos = useMemo(() => {
    const m = new Map<number, number[]>();
    for (const k of idx) {
      const cur = m.get(T.si[k]);
      if (cur) cur.push(k);
      else m.set(T.si[k], [k]);
    }
    return Array.from(m.entries()).sort((a, b) => a[0] - b[0]);
  }, [idx, T]);
  const etiquetaDia = new Date(`${dia}T12:00:00`).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "short", year: "numeric" });
  const i = out.calendar.indexOf(dia);
  const locates = out.per_strategy.reduce((a, p) => a + (p.locates_daily[i] || 0), 0);
  const fijos = out.per_strategy.reduce((a, p) => a + (p.expenses_daily?.[i] || 0), 0);

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 24 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: color.bgSurface, border: `1px solid ${color.border}`, width: "100%", maxWidth: 1100, maxHeight: "85vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 24px 64px rgba(0,0,0,0.5)" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, padding: "10px 14px", borderBottom: `1px solid ${color.border}`, background: color.bgElevated }}>
          <span style={{ fontSize: 12.5, fontWeight: 700, textTransform: "capitalize", color: color.textHigh, fontFamily: font.sans }}>{etiquetaDia}</span>
          <span style={{ fontSize: 10.5, color: color.textMuted, fontFamily: font.sans }}>{idx.length} {idx.length === 1 ? "trade" : "trades"} · {grupos.length} {grupos.length === 1 ? "estrategia" : "estrategias"}</span>
          {stats && (
            <>
              <span style={{ fontSize: 11, fontFamily: font.mono, color: color.textSecondary }}>bruto <span style={{ color: stats.profits >= 0 ? color.profit : color.loss }}>{fmtDinero(stats.profits, false)}</span></span>
              <span style={{ fontSize: 11, fontFamily: font.mono, color: color.textSecondary }}>gastos <span style={{ color: color.loss }}>{fmtDinero(stats.gastos, true)}</span></span>
              <span style={{ fontSize: 12, fontFamily: font.mono, fontWeight: 700, color: stats.net >= 0 ? color.profit : color.loss }}>{fmtDinero(stats.net, false)}</span>
              {stats.tieneR && <span style={{ fontSize: 11, fontFamily: font.mono, color: stats.netR >= 0 ? color.profit : color.loss }}>{stats.netR >= 0 ? "+" : "−"}{n(Math.abs(stats.netR), 2)} R</span>}
            </>
          )}
          <button onClick={onClose} aria-label="Cerrar" style={{ marginLeft: "auto", background: "transparent", border: "none", color: color.textMuted, fontSize: 16, cursor: "pointer", lineHeight: 1 }}>✕</button>
        </div>
        <div style={{ overflow: "auto", flex: 1 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ position: "sticky", top: 0, background: color.bgSurface, zIndex: 1 }}>
              <tr>
                <th style={thL}>Ticker</th>
                <th style={thL}>Lado</th>
                <th style={thL}>Entrada</th>
                <th style={thL}>Salida</th>
                <th style={thR}>Entry $</th>
                <th style={thR}>Exit $</th>
                <th style={thR}>Acciones</th>
                <th style={thR}>Nocional</th>
                <th style={thR}>PnL</th>
                <th style={thR}>Comis.</th>
                <th style={thR}>R</th>
                <th style={thL}>Motivo</th>
              </tr>
            </thead>
            <tbody>
              {grupos.map(([si, ks]) => {
                const sub = ks.reduce((a, k) => a + T.pnl[k], 0);
                const subR = ks.reduce((a, k) => a + T.r[k], 0);
                const loc = out.per_strategy[si]?.locates_daily[i] || 0;
                const fijo = out.per_strategy[si]?.expenses_daily?.[i] || 0;
                return (
                  <Fragment key={si}>
                    <tr>
                      <td colSpan={12} style={{ ...tdTxt, background: color.bgElevated, padding: "5px 8px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                          <span style={{ width: 10, height: 10, background: colorSerie(si), display: "inline-block" }} />
                          <span style={{ fontWeight: 600 }}>{names[si]}</span>
                          <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.textMuted }}>{ks.length} tr</span>
                          <span style={{ fontFamily: font.mono, fontSize: 11, color: sub >= 0 ? color.profit : color.loss }}>{fmtDinero(sub, false)}</span>
                          <span style={{ fontFamily: font.mono, fontSize: 10.5, color: subR >= 0 ? color.profit : color.loss }}>{subR >= 0 ? "+" : "−"}{n(Math.abs(subR), 2)} R</span>
                          {loc > 0 && <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.loss }}>locates {fmtDinero(loc, true)}</span>}
                          {fijo > 0 && <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.loss }}>gastos fijos del mes {fmtDinero(fijo, true)}</span>}
                        </span>
                      </td>
                    </tr>
                    {ks.map((k) => (
                      <tr key={k}>
                        <td style={{ ...tdTxt, fontWeight: 600 }}>{T.ticker[k]}</td>
                        <td style={{ ...tdTxt, color: T.dir[k] === "S" ? color.loss : color.profit }}>{T.dir[k] === "S" ? "Short" : "Long"}</td>
                        <td style={{ ...tdTxt, fontFamily: font.mono }}>{T.entry[k]}</td>
                        <td style={{ ...tdTxt, fontFamily: font.mono }}>{T.exit[k]}</td>
                        <td style={tdNum}>{n(T.entry_px[k], 2)}</td>
                        <td style={tdNum}>{n(T.exit_px[k], 2)}</td>
                        <td style={tdNum}>{n(T.size[k], 0)}</td>
                        <td style={tdNum}>{n(T.notional[k], 0)}</td>
                        <td style={{ ...tdNum, color: T.pnl[k] >= 0 ? color.profit : color.loss }}>{T.pnl[k] >= 0 ? "+" : ""}{n(T.pnl[k], 2)}</td>
                        <td style={{ ...tdNum, color: color.textMuted }}>{n(T.fees[k], 2)}</td>
                        <td style={{ ...tdNum, color: T.r[k] >= 0 ? color.profit : color.loss }}>{n(T.r[k], 2)}</td>
                        <td style={{ ...tdTxt, color: color.textSecondary }}>{T.reason[k]}</td>
                      </tr>
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {(locates > 0 || fijos > 0) && (
            <p style={{ margin: 0, padding: "8px 12px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, borderTop: hairline }}>
              Los locates son los que cobró la corrida de cada estrategia (fijos o aleatorios, por ticker y día); los
              gastos fijos de cada corrida se cargan el primer día operado de cada mes en que la estrategia está viva.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
