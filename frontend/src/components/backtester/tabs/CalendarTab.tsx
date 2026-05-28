"use client";

import { useMemo, useState } from "react";
import type { DayResult, TradeRecord } from "@/lib/api_backtester";

interface CalendarTabProps {
  dayResults: DayResult[];
  trades: TradeRecord[];
  isDarkMode?: boolean;
}

function pnlColor(pnl: number, maxAbs: number, isDarkMode: boolean): string {
  if (maxAbs === 0) return "transparent";
  const intensity = Math.min(Math.abs(pnl) / maxAbs, 1);
  if (pnl > 0) return isDarkMode
    ? `rgba(59,130,246,${0.12 + intensity * 0.4})`
    : `rgba(16,185,129,${0.12 + intensity * 0.45})`;
  if (pnl < 0) return isDarkMode
    ? `rgba(226,232,240,${0.08 + intensity * 0.25})`
    : `rgba(239,68,68,${0.12 + intensity * 0.45})`;
  return "transparent";
}

export default function CalendarTab({ dayResults, trades, isDarkMode = false }: CalendarTabProps) {
  const pnlByDate = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of trades) {
      if (!t.date) continue;
      map.set(t.date, (map.get(t.date) || 0) + t.pnl);
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

  const maxAbsPnl = useMemo(() => {
    const values = Array.from(pnlByDate.values());
    return values.length ? Math.max(...values.map(Math.abs), 1) : 1;
  }, [pnlByDate]);

  if (!dayResults.length) {
    return <p className="text-[11px] text-[var(--color-ec-text-muted)] font-mono">Sin resultados</p>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
      {months.map((monthStr) => {
        const [year, month] = monthStr.split("-").map(Number);
        const firstDay = new Date(year, month - 1, 1);
        const lastDay = new Date(year, month, 0);
        const startWeekday = (firstDay.getDay() + 6) % 7;

        const monthName = new Date(year, month - 1, 1).toLocaleString("es-ES", { month: "long", year: "numeric" });

        const days: (null | { date: string; pnl: number | null })[] = [];
        for (let i = 0; i < startWeekday; i++) days.push(null);
        for (let d = 1; d <= lastDay.getDate(); d++) {
          const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          const pnl = pnlByDate.get(dateStr) ?? null;
          days.push({ date: dateStr, pnl });
        }

        return (
          <div key={monthStr}>
            <div className="pb-1.5 mb-2" style={{ borderBottom: '0.5px solid rgba(255, 255, 255, 0.3)' }}>
              <span className="text-[11px] font-semibold uppercase tracking-tight" style={{ color: 'var(--color-ec-text-high)' }}>
                {monthName}
              </span>
            </div>
            <div className="grid grid-cols-7 gap-[3px]">
              {["L", "M", "X", "J", "V", "S", "D"].map((l) => (
                <div key={l} className="text-[12px] font-bold text-center mb-1 font-mono" style={{ color: 'var(--color-ec-text-primary)' }}>
                  {l}
                </div>
              ))}
              {days.map((day, i) => {
                if (!day) return <div key={`empty-${i}`} className="aspect-square" />;
                const dayNum = parseInt(day.date.split("-")[2]);
                const hasPnl = day.pnl !== null;

                return (
                  <div
                     key={day.date}
                     className="aspect-square rounded-[2px] flex items-center justify-center text-[11px] flex-col leading-none transition-colors"
                     title={hasPnl ? `${day.date}: $${day.pnl?.toFixed(2)}` : day.date}
                     style={{
                       backgroundColor: hasPnl ? pnlColor(day.pnl!, maxAbsPnl, isDarkMode) : "transparent",
                     }}
                  >
                     <span className={`font-mono font-semibold`} style={{ color: hasPnl ? 'var(--color-ec-text-primary)' : 'var(--color-ec-text-secondary)', opacity: hasPnl ? 1 : 0.7 }}>
                       {dayNum}
                     </span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
