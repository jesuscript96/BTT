"use client";

// Calendario de PnL diario del portfolio combinado. Mismo lenguaje visual que
// el calendario del Backtester (tarjetas por mes, L-V mas la columna semanal,
// celdas verdes/rojas) pero alimentado por la serie DIARIA que devuelve
// /combine — no necesita los trades individuales. El PnL de cada dia ya lleva
// todos los costes configurados, gastos fijos incluidos (se cargan al primer
// dia operado de cada mes, igual que hace el motor).

import React, { useMemo } from "react";
import { color, font, radius } from "@/components/ui/tokens";

function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl);
  const sign = pnl >= 0 ? "+" : "-";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(abs >= 100000 ? 0 : 2)}K`;
  return `${sign}$${abs.toFixed(2)}`;
}

const tint = (base: string, pct: number) => `color-mix(in srgb, ${base} ${pct}%, transparent)`;

export function PnlCalendar({
  dates,
  pnl,
  counts,
}: {
  dates: string[];
  pnl: number[];
  counts: number[];
}) {
  const byDate = useMemo(() => {
    const m = new Map<string, { pnl: number; count: number }>();
    dates.forEach((d, i) => m.set(d, { pnl: pnl[i] ?? 0, count: counts[i] ?? 0 }));
    return m;
  }, [dates, pnl, counts]);

  const months = useMemo(() => {
    const s = new Set<string>();
    for (const d of dates) s.add(d.slice(0, 7));
    return Array.from(s).sort();
  }, [dates]);

  if (!dates.length) return null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 14 }}>
      {months.map((monthStr) => {
        const [year, month] = monthStr.split("-").map(Number);
        const lastDay = new Date(year, month, 0);
        const startWeekday = (new Date(year, month - 1, 1).getDay() + 6) % 7;
        const monthName = new Date(year, month - 1, 1).toLocaleString("es-ES", { month: "long", year: "numeric" });

        const cells: (null | { date: string; pnl: number; count: number })[] = [];
        for (let i = 0; i < startWeekday; i++) cells.push(null);
        for (let d = 1; d <= lastDay.getDate(); d++) {
          const ds = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          const st = byDate.get(ds);
          cells.push({ date: ds, pnl: st ? st.pnl : NaN, count: st ? st.count : 0 });
        }
        while (cells.length % 7 !== 0) cells.push(null);
        const weeks: (typeof cells)[] = [];
        for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

        let mPnl = 0;
        let mCount = 0;
        for (const c of cells) {
          if (c && Number.isFinite(c.pnl)) {
            mPnl += c.pnl;
            mCount += c.count;
          }
        }
        const mTone = mPnl >= 0 ? color.profit : color.loss;

        return (
          <div
            key={monthStr}
            style={{
              background: color.bgSurface,
              border: `0.5px solid ${color.border}`,
              borderRadius: radius.md,
              padding: "12px 12px 9px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                gap: 8,
                paddingBottom: 7,
                marginBottom: 7,
                borderBottom: `0.5px solid ${color.border}`,
              }}
            >
              <span style={{ fontSize: 11.5, textTransform: "capitalize", letterSpacing: "0.04em", color: color.textHigh, fontFamily: font.sans }}>
                {monthName}
              </span>
              <span style={{ display: "inline-flex", gap: 8, alignItems: "baseline" }}>
                {mCount > 0 && (
                  <span style={{ fontSize: 9.5, color: color.textMuted, fontFamily: font.sans }}>{mCount} trades</span>
                )}
                <span style={{ fontSize: 11, fontFamily: font.mono, color: mTone }}>{formatPnl(mPnl)}</span>
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1px 1.1fr", gap: 3, marginBottom: 3 }}>
              {["L", "M", "X", "J", "V"].map((l) => (
                <div key={l} style={{ textAlign: "center", fontSize: 8, letterSpacing: "0.08em", color: color.textMuted, fontFamily: font.sans }}>
                  {l}
                </div>
              ))}
              <div />
              <div style={{ textAlign: "center", fontSize: 8, letterSpacing: "0.08em", color: color.textMuted, fontFamily: font.sans }}>
                SEM
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {weeks.map((week, wi) => {
                let wPnl = 0;
                let wHas = false;
                for (const c of week) {
                  if (c && Number.isFinite(c.pnl)) {
                    wPnl += c.pnl;
                    wHas = true;
                  }
                }
                const wTone = wPnl >= 0 ? color.profit : color.loss;
                return (
                  <div key={wi} style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1px 1.1fr", gap: 3 }}>
                    {week.slice(0, 5).map((c, ci) => {
                      if (!c) return <div key={ci} style={{ minHeight: 34 }} />;
                      const has = Number.isFinite(c.pnl);
                      const tone = has ? (c.pnl >= 0 ? color.profit : color.loss) : color.textMuted;
                      return (
                        <div
                          key={c.date}
                          title={has ? `${c.date}: ${formatPnl(c.pnl)} · ${c.count} trades` : c.date}
                          style={{
                            position: "relative",
                            minHeight: 34,
                            border: `0.5px solid ${has ? tint(tone, 55) : color.border}`,
                            background: has ? tint(tone, 8) : color.bgElevated,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            padding: "2px 1px",
                          }}
                        >
                          <span style={{ position: "absolute", top: 1, right: 3, fontSize: 7, color: has ? tone : color.textMuted, opacity: 0.8, fontFamily: font.sans }}>
                            {parseInt(c.date.slice(8), 10)}
                          </span>
                          {has ? (
                            <span style={{ fontSize: 8.5, fontFamily: font.mono, color: tone, lineHeight: 1 }}>
                              {formatPnl(c.pnl)}
                            </span>
                          ) : (
                            <span style={{ fontSize: 9, color: color.textMuted, opacity: 0.4 }}>—</span>
                          )}
                        </div>
                      );
                    })}
                    <div style={{ background: color.border }} />
                    <div
                      style={{
                        minHeight: 34,
                        border: wHas ? `0.5px dashed ${tint(wTone, 55)}` : `0.5px solid ${color.border}`,
                        background: wHas ? tint(wTone, 5) : "transparent",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {wHas && (
                        <span style={{ fontSize: 8.5, fontFamily: font.mono, color: wTone, lineHeight: 1 }}>
                          {formatPnl(wPnl)}
                        </span>
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
  );
}
