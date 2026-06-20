"use client";

import { useMemo, useState } from "react";
import type { DayResult, TradeRecord } from "@/lib/api_backtester";

interface CalendarTabProps {
  dayResults: DayResult[];
  trades: TradeRecord[];
  isDarkMode?: boolean;
  monthlyExpenses?: number;
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

export default function CalendarTab({ dayResults, trades, monthlyExpenses = 0 }: CalendarTabProps) {
  const [viewMode, setViewMode] = useState<"profits" | "gastos" | "net">("profits");

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
                            title={hasData ? `${day.date}: ${day.count} trades · Valor: $${day.pnl?.toFixed(2)}` : day.date}
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
                              cursor: "default",
                              transition: "border-color 0.15s, background 0.15s",
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
    </div>
  );
}

