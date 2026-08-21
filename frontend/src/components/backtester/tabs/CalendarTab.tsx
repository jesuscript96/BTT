"use client";

import { useEffect, useMemo, useState } from "react";
import type { DayResult, TradeRecord } from "@/lib/api_backtester";
import { EXIT_COLORS, shortExitReason } from "@/components/backtester/tabs/TradesTab";

interface CalendarTabProps {
  dayResults: DayResult[];
  trades: TradeRecord[];
  isDarkMode?: boolean;
  monthlyExpenses?: number;
  onSelectTrade?: (ticker: string, date: string) => void;
}

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

export default function CalendarTab({ dayResults, trades, monthlyExpenses = 0, onSelectTrade }: CalendarTabProps) {
  // Default "net": es la vista que coincide con RETURN/total_pnl. El modo
  // "profits" muestra el PnL BRUTO (suma las fees de vuelta al pnl), así que
  // una estrategia perdedora neta puede verse ganadora en esa vista.
  const [viewMode, setViewMode] = useState<"profits" | "gastos" | "net">("net");
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

    return map;
  }, [trades, viewMode, monthlyExpenses]);

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
      }}>
        {(["profits", "gastos", "net"] as const).map((mode) => {
          const isActive = viewMode === mode;
          const label = mode === "profits" ? "Profits (brutos)" : mode === "gastos" ? "Gastos" : "Profits - Gastos";
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
                      {formatPnl(monthPnl, viewMode === "gastos")}
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
                                  {formatPnl(day.pnl!, viewMode === "gastos")}
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
                              {formatPnl(wPnl, viewMode === "gastos")}
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
                              {(t.exit_reasons && t.exit_reasons.length >= 2) ? (
                                <span className="inline-flex items-center gap-1" title={t.exit_reasons.join(" → ")}>
                                  {t.exit_reasons.map((r, i) => {
                                    const st = EXIT_COLORS[r] || { bg: "rgba(148,163,184,0.12)", text: "var(--color-ec-text-primary)" };
                                    return (
                                      <span key={i} className="inline-flex items-center gap-1">
                                        {i > 0 && <span className="text-[9px] text-[var(--color-ec-text-muted)]">→</span>}
                                        <span
                                          className="inline-block px-1.5 py-0.5 rounded-sm text-[10px] font-medium"
                                          style={{ backgroundColor: st.bg, color: st.text }}
                                        >
                                          {shortExitReason(r)}
                                        </span>
                                      </span>
                                    );
                                  })}
                                </span>
                              ) : (
                                <span
                                  className="inline-block px-1.5 py-0.5 rounded-sm text-[10px] font-medium"
                                  style={{ backgroundColor: exitStyle.bg, color: exitStyle.text }}
                                >
                                  {t.exit_reason}
                                </span>
                              )}
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

