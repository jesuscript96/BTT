"use client";

import { useMemo, useState, Fragment } from "react";
import type { DayResult, TradeRecord } from "@/lib/api_backtester";

interface CalendarTabProps {
  dayResults: DayResult[];
  trades: TradeRecord[];
  isDarkMode?: boolean;
}

function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl);
  const sign = pnl >= 0 ? "+" : "-";
  if (abs >= 1000) {
    return `${sign}$${(abs / 1000).toFixed(2)} K`;
  }
  return `${sign}$${abs.toFixed(2)}`;
}

export default function CalendarTab({ dayResults, trades, isDarkMode = false }: CalendarTabProps) {
  const statsByDate = useMemo(() => {
    const map = new Map<string, { pnl: number; count: number }>();
    for (const t of trades) {
      if (!t.date) continue;
      const cur = map.get(t.date) || { pnl: 0, count: 0 };
      map.set(t.date, {
        pnl: cur.pnl + t.pnl,
        count: cur.count + 1
      });
    }
    return map;
  }, [trades]);

  const months = useMemo(() => {
    const set = new Set<string>();
    for (const dr of dayResults) {
      set.add(dr.date.slice(0, 7));
    }
    return Array.from(set).sort();
  }, [dayResults]);

  if (!dayResults.length) {
    return <p className="text-[11px] text-[var(--color-ec-text-muted)] font-mono">Sin resultados</p>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3 gap-8" style={{ paddingTop: 24 }}>
      {months.map((monthStr) => {
        const [year, month] = monthStr.split("-").map(Number);
        const firstDay = new Date(year, month - 1, 1);
        const lastDay = new Date(year, month, 0);
        const startWeekday = (firstDay.getDay() + 6) % 7; // Monday = 0

        const monthName = new Date(year, month - 1, 1).toLocaleString("es-ES", { month: "long", year: "numeric" });

        const days: (null | { date: string; pnl: number | null; count: number })[] = [];
        for (let i = 0; i < startWeekday; i++) days.push(null);
        for (let d = 1; d <= lastDay.getDate(); d++) {
          const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          const stats = statsByDate.get(dateStr);
          days.push({
            date: dateStr,
            pnl: stats ? stats.pnl : null,
            count: stats ? stats.count : 0
          });
        }

        // Pad the end of the days array to make it a multiple of 7
        const totalCells = Math.ceil(days.length / 7) * 7;
        while (days.length < totalCells) {
          days.push(null);
        }

        // Group into weeks
        const weeks: (null | { date: string; pnl: number | null; count: number })[][] = [];
        for (let i = 0; i < days.length; i += 7) {
          weeks.push(days.slice(i, i + 7));
        }

        // Total Month PNL
        let monthTotalPnl = 0;
        for (const d of days) {
          if (d && d.pnl !== null) {
            monthTotalPnl += d.pnl;
          }
        }

        return (
          <div key={monthStr} className="p-5 rounded-lg bg-[var(--color-ec-bg-surface)] border border-[var(--color-ec-border)] shadow-md flex flex-col">
            {/* Title / Summary */}
            <div className="pb-2.5 mb-3 border-b border-[var(--color-ec-border)] flex justify-between items-center">
              <span className="text-[12px] font-bold uppercase tracking-wider text-[var(--color-ec-text-high)]">
                {monthName}
              </span>
              {monthTotalPnl !== 0 && (
                <span className={`text-[11px] font-mono font-bold ${monthTotalPnl >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                  {monthTotalPnl >= 0 ? "+" : ""}{formatPnl(monthTotalPnl)}
                </span>
              )}
            </div>

            {/* Grid */}
            <div className="grid grid-cols-8 gap-[5px] flex-1">
              {/* Day headers */}
              {["L", "M", "X", "J", "V", "S", "D", "Sem"].map((l) => (
                <div key={l} className="text-[10px] font-bold text-center mb-1 font-mono text-[var(--color-ec-text-secondary)]">
                  {l}
                </div>
              ))}

              {/* Render weeks */}
              {weeks.map((week, weekIdx) => {
                // Calculate week totals
                let weeklyPnl = 0;
                let weeklyCount = 0;
                let hasWeeklyTrades = false;
                for (const day of week) {
                  if (day && day.count > 0) {
                    weeklyPnl += day.pnl || 0;
                    weeklyCount += day.count;
                    hasWeeklyTrades = true;
                  }
                }

                return (
                  <Fragment key={`week-${weekIdx}`}>
                    {/* Render the 7 days of the week */}
                    {week.map((day, i) => {
                      if (!day) return <div key={`empty-${weekIdx}-${i}`} className="aspect-[1.25] bg-transparent" />;
                      const dayNum = parseInt(day.date.split("-")[2]);

                      const isPositive = day.pnl! >= 0;
                      const boxBg = day.count > 0
                        ? isPositive
                          ? (isDarkMode ? "rgba(16, 185, 129, 0.12)" : "rgba(16, 185, 129, 0.08)")
                          : (isDarkMode ? "rgba(244, 63, 94, 0.12)" : "rgba(244, 63, 94, 0.08)")
                        : "transparent";

                      const boxBorder = day.count > 0
                        ? isPositive
                          ? (isDarkMode ? "rgba(16, 185, 129, 0.25)" : "rgba(16, 185, 129, 0.2)")
                          : (isDarkMode ? "rgba(244, 63, 94, 0.25)" : "rgba(244, 63, 94, 0.2)")
                        : "transparent";

                      const textColor = day.count > 0
                        ? isPositive
                          ? (isDarkMode ? "rgb(52, 211, 153)" : "rgb(5, 150, 105)")
                          : (isDarkMode ? "rgb(251, 113, 133)" : "rgb(225, 29, 72)")
                        : (isDarkMode ? "rgba(255, 255, 255, 0.4)" : "rgba(0, 0, 0, 0.4)");

                      return (
                        <div
                          key={day.date}
                          className="relative aspect-[1.25] rounded-[4px] border p-1 flex flex-col justify-end transition-colors cursor-default"
                          title={day.count > 0 ? `${day.date}: ${day.count} trades, PnL: ${day.pnl?.toFixed(2)}` : day.date}
                          style={{
                            backgroundColor: boxBg,
                            borderColor: boxBorder,
                          }}
                        >
                          <span 
                            className="absolute top-1 right-1 text-[8px] font-semibold opacity-60"
                            style={{ color: isDarkMode ? "rgba(255, 255, 255, 0.6)" : "rgba(0, 0, 0, 0.6)" }}
                          >
                            {dayNum}
                          </span>
                          {day.count > 0 && (
                            <div className="flex flex-col items-start leading-none gap-0.5">
                              <span className="text-[7.5px] font-semibold opacity-85" style={{ color: textColor }}>
                                {day.count} tr.
                              </span>
                              <span className="text-[8.5px] font-bold tracking-tighter" style={{ color: textColor }}>
                                {formatPnl(day.pnl!)}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {/* Render weekly total box */}
                    {(() => {
                      const isPositive = weeklyPnl >= 0;
                      const boxBg = hasWeeklyTrades
                        ? isPositive
                          ? (isDarkMode ? "rgba(16, 185, 129, 0.08)" : "rgba(16, 185, 129, 0.05)")
                          : (isDarkMode ? "rgba(244, 63, 94, 0.08)" : "rgba(244, 63, 94, 0.05)")
                        : "transparent";

                      const boxBorder = hasWeeklyTrades
                        ? isPositive
                          ? (isDarkMode ? "rgba(16, 185, 129, 0.3)" : "rgba(16, 185, 129, 0.25)")
                          : (isDarkMode ? "rgba(244, 63, 94, 0.3)" : "rgba(244, 63, 94, 0.25)")
                        : "transparent";

                      const textColor = hasWeeklyTrades
                        ? isPositive
                          ? (isDarkMode ? "rgb(52, 211, 153)" : "rgb(5, 150, 105)")
                          : (isDarkMode ? "rgb(251, 113, 133)" : "rgb(225, 29, 72)")
                        : "transparent";

                      return (
                        <div
                          key={`week-total-${weekIdx}`}
                          className="aspect-[1.25] rounded-[4px] border p-1 flex flex-col justify-end transition-colors cursor-default"
                          title={hasWeeklyTrades ? `Semana ${weekIdx + 1}: ${weeklyCount} trades, PnL: ${weeklyPnl.toFixed(2)}` : `Semana ${weekIdx + 1}`}
                          style={{
                            backgroundColor: boxBg,
                            borderStyle: hasWeeklyTrades ? "dashed" : "solid",
                            borderColor: boxBorder,
                          }}
                        >
                          {hasWeeklyTrades && (
                            <div className="flex flex-col items-start leading-none gap-0.5">
                              <span className="text-[7.5px] font-bold opacity-80" style={{ color: textColor }}>
                                {weeklyCount} tr.
                              </span>
                              <span className="text-[8.5px] font-extrabold tracking-tighter" style={{ color: textColor }}>
                                {formatPnl(weeklyPnl)}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </Fragment>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
