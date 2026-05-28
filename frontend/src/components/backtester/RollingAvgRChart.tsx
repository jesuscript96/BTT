"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import {
    createChart,
    BaselineSeries,
    ColorType,
    type IChartApi,
    type Time,
} from "lightweight-charts";
import type { TradeRecord } from "@/lib/api_backtester";

interface RollingAvgRChartProps {
    trades: TradeRecord[];
    isDarkMode?: boolean;
}

export default function RollingAvgRChart({ trades, isDarkMode = false }: RollingAvgRChartProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const [rollingWindow, setRollingWindow] = useState(50);
    type RollingBasis = "trades" | "days";
    const [basis, setBasis] = useState<RollingBasis>("trades");

    const rData = useMemo(() => {
        if (!trades.length) return [];

        if (basis === "days") {
            const dayTrades = new Map<string, TradeRecord[]>();
            for (const t of trades) {
                const d = new Date(t.exit_time);
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                if (!dayTrades.has(dateStr)) dayTrades.set(dateStr, []);
                dayTrades.get(dateStr)!.push(t);
            }

            const dailyR: { date: string; avgR: number }[] = [];
            for (const [date, dayT] of dayTrades) {
                const validR = dayT.map(t => t.r_multiple).filter((r): r is number => r !== null);
                if (validR.length === 0) continue;
                const avgR = validR.reduce((s, r) => s + r, 0) / validR.length;
                dailyR.push({ date, avgR });
            }
            dailyR.sort((a, b) => a.date.localeCompare(b.date));

            // Lower requirement to show data even with few points
            const minDaysReq = 1;
            const result: { time: Time; value: number }[] = [];
            for (let i = 0; i < dailyR.length; i++) {
                const start = Math.max(0, i - rollingWindow + 1);
                const slice = dailyR.slice(start, i + 1);
                if (slice.length < minDaysReq) continue;
                const avg = slice.reduce((s, d) => s + d.avgR, 0) / slice.length;
                result.push({ time: dailyR[i].date as unknown as Time, value: avg });
            }
            return result;
        } else {
            const sorted = [...trades].sort(
                (a, b) => new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime()
            );
            const minTradesReq = 1;
            const raw: { date: string; value: number }[] = [];
            for (let i = 0; i < sorted.length; i++) {
                const start = Math.max(0, i - rollingWindow + 1);
                const slice = sorted.slice(start, i + 1);
                if (slice.length < minTradesReq) continue;

                const validR = slice.map(t => t.r_multiple).filter((r): r is number => r !== null);
                const avgR = validR.length > 0 ? validR.reduce((s, r) => s + r, 0) / validR.length : 0;

                const d = new Date(sorted[i].exit_time);
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                raw.push({ date: dateStr, value: avgR });
            }
            const dayMap = new Map<string, number>();
            for (const p of raw) dayMap.set(p.date, p.value);
            return Array.from(dayMap.entries())
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([date, value]) => ({ time: date as unknown as Time, value }));
        }
    }, [trades, rollingWindow, basis]);

    useEffect(() => {
        if (!containerRef.current || !rData.length) return;

        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || 120,
            layout: {
                background: { type: ColorType.Solid, color: "#16181A" },
                textColor: "#8A8D92"
            },
            grid: {
                vertLines: { color: "#2C2F33" },
                horzLines: { color: "#2C2F33" },
            },
            rightPriceScale: { borderColor: "#2C2F33" },
            timeScale: { borderColor: "#2C2F33", timeVisible: true },
            crosshair: { mode: 0 },
        });
        chartRef.current = chart;

        const series = chart.addSeries(BaselineSeries, {
            baseValue: { type: "price", price: 0 },
            topLineColor: "#8b5cf6",
            topFillColor1: "rgba(139, 92, 246, 0.3)",
            topFillColor2: "rgba(139, 92, 246, 0.02)",
            bottomLineColor: "#ef4444",
            bottomFillColor1: "rgba(239, 68, 68, 0.02)",
            bottomFillColor2: "rgba(239, 68, 68, 0.3)",
            lineWidth: 2,
        });
        series.setData(rData);

        chart.timeScale().fitContent();

        const el = containerRef.current;
        const handleResize = () => {
            if (el) {
                chart.applyOptions({
                    width: el.clientWidth,
                    height: el.clientHeight || 120,
                });
                chart.timeScale().fitContent();
            }
        };
        globalThis.addEventListener("resize", handleResize);
        const resizeObserver = new ResizeObserver(handleResize);
        resizeObserver.observe(el);

        return () => {
            resizeObserver.disconnect();
            globalThis.removeEventListener("resize", handleResize);
            chart.remove();
            chartRef.current = null;
        };
    }, [rData, isDarkMode]);

    return (
        <div className="bg-[var(--card-bg)] rounded border border-[var(--border)] shadow-sm overflow-hidden flex flex-col h-full transition-colors">
            <div className="bg-[var(--sidebar-bg)] border-b border-[var(--border)] px-3 py-1.5 flex items-center justify-between">
                <h2 className="text-[11px] font-bold uppercase tracking-wider text-[var(--foreground)]">
                    Rolling Avg R
                </h2>
                <div className="flex items-center gap-3">
                    <div className="flex bg-[var(--sidebar-bg)] rounded text-[10px] border border-[var(--border)]">
                        {([["trades", "Trades"], ["days", "Días"]] as const).map(([val, label]) => (
                            <button
                                key={val}
                                onClick={() => setBasis(val)}
                                className={`px-2 py-0.5 rounded transition-colors font-medium border-none ${basis === val
                                    ? "bg-[var(--card-bg)] text-[var(--foreground)] shadow-sm"
                                    : "text-gray-400 hover:text-[var(--foreground)]"
                                    }`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-1.5">
                        <span className="text-[9px] text-[var(--muted)] uppercase">Window</span>
                        <input
                            type="number"
                            min={5}
                            max={500}
                            value={rollingWindow}
                            onChange={(e) => setRollingWindow(Math.max(5, Math.min(500, parseInt(e.target.value) || 50)))}
                            className="w-12 text-xs border border-[var(--border)] rounded px-1.5 py-0.5 text-center font-mono bg-[var(--card-muted-bg)] text-[var(--foreground)]"
                        />
                    </div>
                </div>
            </div>
            <div ref={containerRef} className="flex-1" style={{ minHeight: 100 }} />
        </div>
    );
}
