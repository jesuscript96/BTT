"use client";

import { useEffect, useMemo, useState } from "react";
import type { DayResult, GlobalEquityPoint, TradeRecord } from "@/lib/api_backtester";
import { EXIT_COLORS } from "@/components/backtester/tabs/TradesTab";

interface CalendarTabProps {
  dayResults: DayResult[];
  trades: TradeRecord[];
  isDarkMode?: boolean;
  monthlyExpenses?: number;
  onSelectTrade?: (ticker: string, date: string) => void;
  /** El riesgo del panel de la izquierda. Con «Fixed Amount» son DÓLARES (1 R
   *  vale eso siempre); con «Percentage» es el PORCENTAJE del balance que se
   *  arriesga, y entonces 1 R vale distinto cada día. */
  riskR?: number;
  riskType?: string;
  /** La curva de equity diaria, para saber con qué balance empezó cada día.
   *  Solo hace falta con riesgo porcentual. */
  globalEquity?: GlobalEquityPoint[];
  initCash?: number;
}

type ModoVista = "profits" | "gastos" | "net";
/** En qué se leen las cifras. Es un eje APARTE del modo de vista: los tres
 *  modos se pueden mirar en dinero o en múltiplos de riesgo. */
type Unidad = "dinero" | "r";

function formatPnl(pnl: number, isGastos = false): string {
  const abs = Math.abs(pnl);
  if (isGastos) {
    if (abs >= 1000) {
      return `$${(abs / 1000).toFixed(2)}K`;
    }
    return `$${abs.toFixed(2)}`;
  }
  const sign = pnl >= 0 ? "+" : "-";
  if (abs >= 1000) {
    return `${sign} $${(abs / 1000).toFixed(2)}K`;
  }
  return `${sign} $${abs.toFixed(2)}`;
}

/** El valor de una casilla ya convertido, con su sufijo.
 *
 *  En R se escribe como múltiplo y NUNCA con el «$» delante: un «$1,50 R» es
 *  justo la confusión que haría leer el mes entero mal.
 */
function formatValor(v: number, modo: ModoVista, unidad: Unidad): string {
  if (unidad === "dinero") return formatPnl(v, modo === "gastos");
  if (modo === "gastos") return `${Math.abs(v).toFixed(2)} R`;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)} R`;
}

/** El día (YYYY-MM-DD) de un punto de la curva de equity.
 *
 *  Los puntos vienen en epoch de UTC a medianoche, así que se lee en UTC: con
 *  `new Date(...).getDate()` en un huso al oeste, el 5 de enero se leería como
 *  el 4 y la R se asignaría al día anterior.
 */
function diaDeEpoch(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(0, 10);
}

/** Lo que vale 1 R, en dólares, para cada día operado.
 *
 *  DOS CASOS, y el segundo es el que pidió Jaume (2026-09-04: «si pongo % de
 *  equity no debería dar problema tampoco, simplemente evoluciona la R con la
 *  cuenta»). Tenía razón: la R no desaparece, cambia.
 *
 *   · Riesgo fijo   → 1 R vale lo mismo todos los días.
 *   · % de equity   → el motor arriesga ese % del balance de APERTURA del día,
 *                     así que 1 R es constante DENTRO de un día y cambia de un
 *                     día a otro. El balance de apertura es el punto ANTERIOR
 *                     de la curva diaria; el del primer día es el capital
 *                     inicial. Es la misma cuenta que hace `r_precise` en
 *                     `robustness_service.py`, verificada allí contra una
 *                     corrida real con un 0,000009 % de desvío.
 *
 *  Que 1 R sea constante dentro del día es lo que hace que esto encaje en un
 *  calendario: se convierte cada día por su R y luego se suman las R para la
 *  semana y el mes. Sumar dólares y dividir al final por una R «media» daría
 *  otro número, y no el bueno.
 */
function valorRPorDia(
  dias: string[], riskR: number, riskType: string | undefined,
  globalEquity: GlobalEquityPoint[], initCash: number,
): Map<string, number> {
  const m = new Map<string, number>();
  const esPct = riskType === "Percentage";
  if (!esPct) {
    for (const d of dias) m.set(d, riskR);
    return m;
  }
  const frac = riskR / 100;
  let previo = initCash;
  for (const p of globalEquity) {
    if (p?.time == null) continue;
    m.set(diaDeEpoch(p.time), frac * previo);      // apertura = cierre del anterior
    previo = Number(p.value) || previo;
  }
  return m;
}

export default function CalendarTab({
  dayResults, trades, monthlyExpenses = 0, onSelectTrade, riskR = 0, riskType,
  globalEquity = [], initCash = 0,
}: CalendarTabProps) {
  const [viewMode, setViewMode] = useState<ModoVista>("profits");
  /** Dinero o múltiplos de riesgo. Eje aparte del modo: los tres modos se
   *  pueden mirar en las dos unidades. */
  const [unidad, setUnidad] = useState<Unidad>("dinero");

  const esPct = riskType === "Percentage";
  /** Con riesgo porcentual hace falta la curva para saber con qué balance
   *  empezó cada día; sin ella no se puede convertir y no se ofrece. */
  const puedeR = riskR > 0 && (!esPct || globalEquity.length > 0);
  const unidadReal: Unidad = puedeR ? unidad : "dinero";
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  // Cerrar el detalle de día con Escape
  useEffect(() => {
    if (!selectedDate) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedDate(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedDate]);

  const tradesByDate = useMemo(() => {
    const map = new Map<string, TradeRecord[]>();
    for (const t of trades) {
      if (!t.date) continue;
      const cur = map.get(t.date);
      if (cur) cur.push(t);
      else map.set(t.date, [t]);
    }
    return map;
  }, [trades]);

  const statsByDate = useMemo(() => {
    // 1. Group trade calculations first
    const map = new Map<string, { pnl: number; count: number }>();
    const uniqueDatesSet = new Set<string>();

    for (const t of trades) {
      if (!t.date) continue;
      uniqueDatesSet.add(t.date);
      
      const cur = map.get(t.date) || { pnl: 0, count: 0 };
      
      let val = 0;
      if (viewMode === "profits") {
        val = t.pnl + (t.fees || 0);
      } else if (viewMode === "gastos") {
        val = t.fees || 0;
      } else {
        val = t.pnl; // net
      }

      map.set(t.date, { pnl: cur.pnl + val, count: cur.count + 1 });
    }

    // 2. Add monthly expenses if applicable (only to the first trading day of each month)
    if (monthlyExpenses > 0 && (viewMode === "gastos" || viewMode === "net")) {
      const sortedDates = Array.from(uniqueDatesSet).sort();
      const seenMonths = new Set<string>();
      for (const d of sortedDates) {
        const m = d.slice(0, 7);
        if (!seenMonths.has(m)) {
          seenMonths.add(m);
          
          const cur = map.get(d) || { pnl: 0, count: 0 };
          const expenseAdjustment = viewMode === "gastos" ? monthlyExpenses : -monthlyExpenses;
          map.set(d, { pnl: cur.pnl + expenseAdjustment, count: cur.count });
        }
      }
    }

    // 3. A múltiplos de riesgo, si toca.
    //
    // SE CONVIERTE AQUÍ, POR DÍA, y no al pintar. Con riesgo porcentual 1 R
    // vale distinto cada día, así que la R de una semana es la SUMA de las R
    // de sus días — no el dinero de la semana partido por una R «media», que
    // daría otro número. Convirtiendo aquí, las sumas de semana y mes que
    // vienen después salen bien solas y no hay que tocarlas.
    if (unidadReal === "r") {
      const rs = valorRPorDia([...map.keys()], riskR, riskType, globalEquity, initCash);
      for (const [d, v] of map) {
        const r = rs.get(d) || 0;
        // Sin R para ese día (un hueco en la curva) se deja a 0 en vez de
        // dividir por cero: mejor una casilla vacía que un Infinity.
        map.set(d, { ...v, pnl: r > 0 ? v.pnl / r : 0 });
      }
    }

    return map;
  }, [trades, viewMode, monthlyExpenses, unidadReal, riskR, riskType, globalEquity, initCash]);

  const months = useMemo(() => {
    const set = new Set<string>();
    for (const dr of dayResults) set.add(dr.date.slice(0, 7));
    return Array.from(set).sort();
  }, [dayResults]);

  if (!dayResults.length) {
    return <p className="text-[11px] text-[var(--color-ec-text-muted)] font-mono">Sin resultados</p>;
  }

  return (
    <div style={{ paddingTop: 20 }}>
      {/* ── View Mode Selector ── */}
      <div style={{
        display: "flex",
        gap: 24,
        marginBottom: 24,
        borderBottom: "1px solid var(--color-ec-border)",
        paddingBottom: 0,
        alignItems: "center",
      }}>
        {(["profits", "gastos", "net"] as const).map((mode) => {
          const isActive = viewMode === mode;
          const label = mode === "profits" ? "Profits" : mode === "gastos" ? "Gastos" : "Profits - Gastos";
          return (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              style={{
                padding: "8px 0",
                fontSize: 11,
                fontWeight: isActive ? 700 : 500,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                fontFamily: "var(--font-sans)",
                border: "none",
                borderBottom: isActive ? "2px solid var(--color-ec-copper)" : "2px solid transparent",
                background: "transparent",
                color: isActive ? "var(--color-ec-text-high)" : "var(--color-ec-text-muted)",
                cursor: "pointer",
                transition: "all 0.15s ease",
                marginBottom: -1, // overlaps the borderBottom
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.color = "var(--color-ec-text-secondary)";
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.color = "var(--color-ec-text-muted)";
                }
              }}
            >
              {label}
            </button>
          );
        })}

        {/* ── Unidad: dinero o R ──────────────────────────────────────────
            Va a la DERECHA y separado de los modos porque es otro eje: no se
            elige «Profits o R», se elige «Profits, y en qué lo leo». Solo
            aparece si hay una R fija que aplicar. */}
        {puedeR && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, paddingBottom: 6 }}>
            <span
              title={esPct
                ? `1 R = ${riskR} % del balance con el que empieza cada día, así que vale distinto cada día: el motor dimensiona así. La R de una semana es la suma de las R de sus días.`
                : `1 R = ${riskR.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $, el riesgo fijo del panel de la izquierda.`}
              style={{
                fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase",
                fontFamily: "var(--font-sans)", color: "var(--color-ec-text-muted)",
                cursor: "help",
              }}
            >{esPct ? `1 R = ${riskR} % diario` : `1 R = $${riskR.toFixed(0)}`}</span>
            <div style={{ display: "flex", border: "1px solid var(--color-ec-border)", borderRadius: 2 }}>
              {(["dinero", "r"] as const).map((u, i) => (
                <button
                  key={u}
                  onClick={() => setUnidad(u)}
                  style={{
                    padding: "3px 10px", fontSize: 10.5, fontFamily: "var(--font-mono, monospace)",
                    border: "none", borderLeft: i ? "1px solid var(--color-ec-border)" : "none",
                    background: unidadReal === u ? "var(--color-ec-copper)" : "transparent",
                    color: unidadReal === u ? "#fff" : "var(--color-ec-text-muted)",
                    cursor: "pointer",
                  }}
                >{u === "dinero" ? "$" : "R"}</button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Calendars Grid ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {months.map((monthStr) => {
          const [year, month] = monthStr.split("-").map(Number);
          const firstDay = new Date(year, month - 1, 1);
          const lastDay = new Date(year, month, 0);
          const startWeekday = (firstDay.getDay() + 6) % 7;

          const monthName = new Date(year, month - 1, 1).toLocaleString("es-ES", { month: "long", year: "numeric" });

          // Build full 7-day array
          const allDays: (null | { date: string; pnl: number | null; count: number; weekday: number })[] = [];
          for (let i = 0; i < startWeekday; i++) allDays.push(null);
          for (let d = 1; d <= lastDay.getDate(); d++) {
            const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const stats = statsByDate.get(dateStr);
            const wd = (new Date(year, month - 1, d).getDay() + 6) % 7; // 0=Mon..6=Sun
            allDays.push({ date: dateStr, pnl: stats ? stats.pnl : null, count: stats ? stats.count : 0, weekday: wd });
          }
          const totalCells = Math.ceil(allDays.length / 7) * 7;
          while (allDays.length < totalCells) allDays.push(null);

          // Group into weeks
          const weeks: typeof allDays[] = [];
          for (let i = 0; i < allDays.length; i += 7) weeks.push(allDays.slice(i, i + 7));

          // Monthly totals
          let monthPnl = 0;
          let monthTrades = 0;
          for (const d of allDays) {
            if (d && d.count > 0) {
              monthPnl += d.pnl || 0;
              monthTrades += d.count;
            }
          }

          const mHasGastos = viewMode === "gastos" && monthPnl > 0;
          const mIsWin = viewMode === "gastos" ? !mHasGastos : monthPnl >= 0;
          const mColor = viewMode === "gastos"
            ? (mHasGastos ? "var(--color-ec-loss)" : "var(--color-ec-text-muted)")
            : (mIsWin ? "var(--color-ec-profit)" : "var(--color-ec-loss)");

          return (
            <div
              key={monthStr}
              style={{
                background: "var(--color-ec-bg-surface)",
                border: "0.5px solid var(--color-ec-border)",
                borderRadius: 8,
                padding: "14px 14px 10px",
                display: "flex",
                flexDirection: "column",
                gap: 0,
              }}
            >
              {/* ── Header ── */}
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                paddingBottom: 8, marginBottom: 8,
                borderBottom: "0.5px solid var(--color-ec-border)",
              }}>
                <span style={{ fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-ec-text-high)" }}>
                  {monthName}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {monthTrades > 0 && (
                    <span style={{ fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-muted)", fontFamily: "var(--font-sans)" }}>
                      {monthTrades} trades
                    </span>
                  )}
                  {(monthPnl !== 0 || (viewMode === "gastos" && monthTrades > 0)) && (
                    <span style={{
                      fontSize: 12, fontWeight: 800, fontFamily: "monospace", letterSpacing: "-0.03em",
                      color: mColor,
                    }}>
                      {formatValor(monthPnl, viewMode, unidadReal)}
                    </span>
                  )}
                </div>
              </div>

              {/* ── Day Headers (L M X J V · Sem) ── */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1px 1.1fr", gap: 4, marginBottom: 4 }}>
                {["Lun", "Mar", "Mié", "Jue", "Vie"].map((l) => (
                  <div key={l} style={{
                    textAlign: "center", fontSize: 8, fontWeight: 700, color: "var(--color-ec-text-muted)",
                    textTransform: "uppercase", letterSpacing: "0.08em", padding: "0 0 2px",
                  }}>
                    {l}
                  </div>
                ))}
                <div /> {/* Separator column placeholder */}
                <div style={{
                  textAlign: "center", fontSize: 8, fontWeight: 700, color: "var(--color-ec-text-muted)",
                  textTransform: "uppercase", letterSpacing: "0.08em", padding: "0 0 2px",
                }}>
                  Sem
                </div>
              </div>

              {/* ── Weeks ── */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {weeks.map((week, weekIdx) => {
                  let wPnl = 0, wCount = 0, wHas = false;
                  for (const d of week) {
                    if (d && d.count > 0) {
                      wPnl += d.pnl || 0;
                      wCount += d.count;
                      wHas = true;
                    }
                  }
                  const weekDays = week.slice(0, 5); // Mon–Fri

                  const wHasGastos = viewMode === "gastos" && wPnl > 0;
                  const wIsWin = viewMode === "gastos" ? !wHasGastos : wPnl >= 0;
                  const wBorderColor = viewMode === "gastos"
                    ? (wHasGastos ? "var(--color-ec-loss)" : "var(--color-ec-border)")
                    : (wIsWin ? "var(--color-ec-profit)" : "var(--color-ec-loss)");
                  const wBackground = wHas
                    ? (viewMode === "gastos"
                        ? (wHasGastos ? "rgba(201, 77, 63, 0.05)" : "transparent")
                        : (wIsWin ? "rgba(74, 157, 127, 0.05)" : "rgba(201, 77, 63, 0.05)"))
                    : "transparent";

                  return (
                    <div key={`w-${weekIdx}`} style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1px 1.1fr", gap: 4 }}>
                      {weekDays.map((day, i) => {
                        if (!day) return <div key={`e-${weekIdx}-${i}`} style={{ minHeight: 44 }} />;
                        const dayNum = parseInt(day.date.split("-")[2]);
                        const hasData = day.count > 0;
                        
                        const hasGastos = viewMode === "gastos" && (day.pnl || 0) > 0;
                        const isWin = viewMode === "gastos" ? !hasGastos : (day.pnl || 0) >= 0;

                        const profit = "var(--color-ec-profit)";
                        const loss = "var(--color-ec-loss)";
                        const textMuted = "var(--color-ec-text-muted)";
                        
                        const accentColor = hasData 
                          ? (viewMode === "gastos" 
                              ? (hasGastos ? loss : textMuted)
                              : (isWin ? profit : loss))
                          : "transparent";

                        return (
                          <div
                            key={day.date}
                            title={hasData ? `${day.date}: ${day.count} trades · Valor: $${day.pnl?.toFixed(2)} — click para ver los trades` : day.date}
                            onClick={hasData ? () => setSelectedDate(day.date) : undefined}
                            onMouseEnter={(e) => {
                              if (hasData) e.currentTarget.style.filter = "brightness(1.3)";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.filter = "";
                            }}
                            style={{
                              position: "relative",
                              minHeight: 44,
                              borderRadius: 0,
                              border: `0.5px solid ${hasData ? accentColor : "var(--color-ec-border)"}`,
                              background: hasData
                                ? (viewMode === "gastos"
                                    ? (hasGastos ? "rgba(201, 77, 63, 0.08)" : "var(--color-ec-bg-elevated)")
                                    : (isWin ? "rgba(74, 157, 127, 0.08)" : "rgba(201, 77, 63, 0.08)"))
                                : "var(--color-ec-bg-elevated)",
                              display: "flex",
                              flexDirection: "column",
                              alignItems: "center",
                              justifyContent: "center",
                              gap: 2,
                              padding: "3px 2px",
                              cursor: hasData ? "pointer" : "default",
                              transition: "border-color 0.15s, background 0.15s, filter 0.15s",
                            }}
                          >
                            {/* Day number */}
                            <span style={{
                              position: "absolute", top: 2, right: 4,
                              fontSize: 8, fontWeight: 600,
                              color: hasData ? accentColor : "var(--color-ec-text-muted)",
                              opacity: hasData ? 1 : 0.7,
                            }}>
                              {dayNum}
                            </span>

                            {hasData ? (
                              <div style={{
                                display: "flex", flexDirection: "column", alignItems: "center", gap: 1,
                                background: viewMode === "gastos"
                                  ? (hasGastos ? "rgba(201, 77, 63, 0.12)" : "rgba(120, 120, 120, 0.12)")
                                  : (isWin ? "rgba(74, 157, 127, 0.12)" : "rgba(201, 77, 63, 0.12)"),
                                borderRadius: 0,
                                padding: "3px 6px 2px",
                                width: "90%",
                              }}>
                                <span style={{
                                  fontSize: 9, fontWeight: 700, color: accentColor, letterSpacing: "-0.02em",
                                  fontFamily: "monospace", lineHeight: 1,
                                }}>
                                  {formatValor(day.pnl!, viewMode, unidadReal)}
                                </span>
                                <span style={{
                                  fontSize: 7.5, fontWeight: 600, color: accentColor, opacity: 0.75,
                                  fontFamily: "var(--font-sans)", lineHeight: 1,
                                }}>
                                  {day.count} {day.count === 1 ? "trade" : "trades"}
                                </span>
                              </div>
                            ) : (
                              <span style={{ fontSize: 10, fontWeight: 500, color: "var(--color-ec-text-muted)", opacity: 0.45 }}>
                                —
                              </span>
                            )}
                          </div>
                        );
                      })}

                      {/* ── Separator Line ── */}
                      <div style={{ background: "var(--color-ec-border)" }} />

                      {/* ── Weekly Summary ── */}
                      <div
                        title={wHas ? `Sem ${weekIdx + 1}: ${wCount} trades · Valor: $${wPnl.toFixed(2)}` : `Sem ${weekIdx + 1}`}
                        style={{
                          minHeight: 44,
                          borderRadius: 0,
                          border: wHas ? `0.5px dashed ${wBorderColor}` : "0.5px solid var(--color-ec-border)",
                          background: wBackground,
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: 1,
                          padding: "3px 2px",
                          cursor: "default",
                        }}
                      >
                        {wHas && (
                          <>
                            <span style={{
                              fontSize: 9, fontWeight: 800, letterSpacing: "-0.02em", fontFamily: "monospace", lineHeight: 1,
                              color: viewMode === "gastos"
                                ? (wHasGastos ? "var(--color-ec-loss)" : "var(--color-ec-text-muted)")
                                : (wIsWin ? "var(--color-ec-profit)" : "var(--color-ec-loss)"),
                            }}>
                              {formatValor(wPnl, viewMode, unidadReal)}
                            </span>
                            <span style={{
                              fontSize: 7, fontWeight: 600, lineHeight: 1, opacity: 0.7,
                              color: viewMode === "gastos"
                                ? (wHasGastos ? "var(--color-ec-loss)" : "var(--color-ec-text-muted)")
                                : (wIsWin ? "var(--color-ec-profit)" : "var(--color-ec-loss)"),
                            }}>
                              {wCount} tr
                            </span>
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

      {/* ── Detalle de trades del día (modal) ── */}
      {selectedDate && (() => {
        const dayTrades = [...(tradesByDate.get(selectedDate) || [])].sort(
          (a, b) => String(a.entry_time).localeCompare(String(b.entry_time))
        );
        const dayPnl = dayTrades.reduce((acc, t) => acc + t.pnl, 0);
        const rValues = dayTrades.map((t) => t.r_multiple).filter((r): r is number => r !== null);
        const avgR = rValues.length ? rValues.reduce((a, b) => a + b, 0) / rValues.length : null;
        const dateLabel = new Date(`${selectedDate}T12:00:00`).toLocaleDateString("es-ES", {
          weekday: "long", day: "numeric", month: "short", year: "numeric",
        });

        return (
          <div
            onClick={() => setSelectedDate(null)}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0, 0, 0, 0.65)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 100,
              padding: 24,
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                background: "var(--color-ec-bg-surface, #1a1a1a)",
                border: "0.5px solid var(--color-ec-border)",
                borderRadius: 8,
                width: "100%",
                maxWidth: 980,
                maxHeight: "85vh",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
                boxShadow: "0 24px 64px rgba(0, 0, 0, 0.5)",
              }}
            >
              {/* Header del modal */}
              <div style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "14px 18px",
                borderBottom: "0.5px solid var(--color-ec-border)",
              }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: 13, fontWeight: 700, textTransform: "capitalize",
                    color: "var(--color-ec-text-high)",
                  }}>
                    {dateLabel}
                  </span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-muted)", fontFamily: "var(--font-sans)" }}>
                    {dayTrades.length} {dayTrades.length === 1 ? "trade" : "trades"}
                  </span>
                  <span style={{
                    fontSize: 12, fontWeight: 800, fontFamily: "monospace",
                    color: dayPnl >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
                  }}>
                    {formatPnl(dayPnl)}
                  </span>
                  {avgR !== null && (
                    <span style={{
                      fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                      color: avgR >= 0 ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
                    }}>
                      avg {avgR.toFixed(2)}R
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setSelectedDate(null)}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--color-ec-text-muted)",
                    fontSize: 16,
                    cursor: "pointer",
                    padding: "4px 8px",
                    lineHeight: 1,
                  }}
                  aria-label="Cerrar"
                >
                  ✕
                </button>
              </div>

              {/* Tabla de trades del día (mismo formato que la pestaña Trades) */}
              <div className="overflow-x-auto overflow-y-auto" style={{ flex: 1 }}>
                <table className="w-full text-[11px] font-mono" style={{ borderCollapse: "collapse" }}>
                  <thead className="sticky top-0" style={{ background: "var(--color-ec-bg-surface, #1a1a1a)", zIndex: 10 }}>
                    <tr>
                      {["Ticker", "Entrada", "Salida", "Entry $", "Exit $", "Size", "PnL", "R", "MAE%", "MFE%", "Exit"].map((h) => (
                        <th
                          key={h}
                          className="px-4 py-2 text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-wider"
                          style={{ textAlign: h === "Ticker" || h === "Entrada" || h === "Salida" || h === "Exit" ? "left" : "right", borderBottom: "0.5px solid var(--color-ec-border)" }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dayTrades.map((t, i) => {
                      const exitStyle = EXIT_COLORS[t.exit_reason] || { bg: "rgba(148,163,184,0.12)", text: "var(--color-ec-text-primary)" };
                      return (
                        <tr
                          key={i}
                          className="hover:bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)] transition-colors"
                          style={{ borderBottom: "1px solid color-mix(in srgb, var(--border) 30%, transparent)" }}
                        >
                          <td className="px-4 py-1.5 font-semibold">
                            <span
                              onClick={() => {
                                setSelectedDate(null);
                                onSelectTrade?.(t.ticker, t.date);
                              }}
                              className="hover:text-[var(--color-ec-copper-bright)] hover:underline transition-colors cursor-pointer"
                              style={{ color: "var(--color-ec-text-high)" }}
                            >
                              {t.ticker}
                            </span>
                          </td>
                          <td className="px-4 py-1.5" style={{ color: "var(--color-ec-text-primary)" }}>
                            {t.entry_time.split(" ").pop()?.slice(0, 8)}
                          </td>
                          <td className="px-4 py-1.5" style={{ color: "var(--color-ec-text-primary)" }}>
                            {t.exit_time.split(" ").pop()?.slice(0, 8)}
                          </td>
                          <td className="px-4 py-1.5" style={{ color: "var(--color-ec-text-primary)", textAlign: "right" }}>
                            ${t.entry_price.toFixed(2)}
                          </td>
                          <td className="px-4 py-1.5" style={{ color: "var(--color-ec-text-primary)", textAlign: "right" }}>
                            ${t.exit_price.toFixed(2)}
                          </td>
                          <td className="px-4 py-1.5" style={{ color: "var(--color-ec-text-primary)", textAlign: "right" }}>
                            {t.size.toFixed(2)}
                          </td>
                          <td className={`px-4 py-1.5 font-semibold ${t.pnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}`} style={{ textAlign: "right" }}>
                            {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                          </td>
                          <td className={`px-4 py-1.5 ${(t.r_multiple || 0) >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}`} style={{ textAlign: "right" }}>
                            {t.r_multiple !== null ? `${t.r_multiple.toFixed(2)}R` : "—"}
                          </td>
                          <td className="px-4 py-1.5 text-[var(--danger)]" style={{ textAlign: "right" }}>
                            {t.mae != null ? `${t.mae.toFixed(2)}%` : "—"}
                          </td>
                          <td className="px-4 py-1.5 text-[var(--success)]" style={{ textAlign: "right" }}>
                            {t.mfe != null ? `${t.mfe.toFixed(2)}%` : "—"}
                          </td>
                          <td className="px-4 py-1.5">
                            <span className="inline-flex items-center gap-1">
                              {t.n_executions != null && t.n_executions > 1 && (
                                <span
                                  title={`${t.n_executions} ejecuciones agrupadas (parciales + cierre)`}
                                  style={{
                                    fontSize: 8, fontWeight: 700, color: "var(--color-ec-text-muted)",
                                    border: "0.5px solid var(--color-ec-border)",
                                    borderRadius: 3, padding: "0 3px", fontFamily: "var(--font-sans)",
                                  }}
                                >
                                  ×{t.n_executions}
                                </span>
                              )}
                              <span
                                className="inline-block px-1.5 py-0.5 rounded-sm text-[10px] font-medium"
                                style={{ backgroundColor: exitStyle.bg, color: exitStyle.text }}
                              >
                                {t.exit_reason}
                              </span>
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

