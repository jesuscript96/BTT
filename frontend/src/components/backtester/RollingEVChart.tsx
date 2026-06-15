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

interface RollingEVChartProps {
    trades: TradeRecord[];
    riskR: number;
    isDarkMode?: boolean;
}

export default function RollingEVChart({ trades, riskR, isDarkMode = false }: RollingEVChartProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const [rollingWindow, setRollingWindow] = useState(50);
    type RollingBasis = "trades" | "days";
    const [basis, setBasis] = useState<RollingBasis>("days");

    const evData = useMemo(() => {
        if (!trades.length) return [];
        const r = riskR > 0 ? riskR : 1;

        if (basis === "days") {
            // Group trades by day, compute daily EV, then rolling avg over days
            const dayTrades = new Map<string, TradeRecord[]>();
            for (const t of trades) {
                const d = new Date(t.exit_time);
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                if (!dayTrades.has(dateStr)) dayTrades.set(dateStr, []);
                dayTrades.get(dateStr)!.push(t);
            }

            const dailyEV: { date: string; ev: number }[] = [];
            for (const [date, dayT] of dayTrades) {
                const wins = dayT.filter((t) => t.pnl > 0);
                const losses = dayT.filter((t) => t.pnl <= 0);
                const pWin = wins.length / dayT.length;
                const pLoss = losses.length / dayT.length;
                const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + t.pnl / r, 0) / wins.length : 0;
                const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((s, t) => s + t.pnl / r, 0) / losses.length) : 0;
                dailyEV.push({ date, ev: pWin * avgWin - pLoss * avgLoss });
            }
            dailyEV.sort((a, b) => a.date.localeCompare(b.date));
            const reqDays = Math.min(rollingWindow, dailyEV.length);
            const result: { time: Time; value: number }[] = [];
            for (let i = 0; i < dailyEV.length; i++) {
                const start = Math.max(0, i - rollingWindow + 1);
                const slice = dailyEV.slice(start, i + 1);
                if (slice.length < reqDays) continue;
                const avg = slice.reduce((s, d) => s + d.ev, 0) / slice.length;
                result.push({ time: dailyEV[i].date as unknown as Time, value: avg });
            }
            return result;
        } else {
            // Rolling over individual trades
            const sorted = [...trades].sort(
                (a, b) => new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime()
            );
            const reqTrades = Math.min(rollingWindow, sorted.length);
            const raw: { date: string; value: number }[] = [];
            for (let i = 0; i < sorted.length; i++) {
                const start = Math.max(0, i - rollingWindow + 1);
                const slice = sorted.slice(start, i + 1);
                if (slice.length < reqTrades) continue;
                const wins = slice.filter((t) => t.pnl > 0);
                const losses = slice.filter((t) => t.pnl <= 0);
                const pWin = wins.length / slice.length;
                const pLoss = losses.length / slice.length;
                const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + t.pnl / r, 0) / wins.length : 0;
                const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((s, t) => s + t.pnl / r, 0) / losses.length) : 0;
                const ev = pWin * avgWin - pLoss * avgLoss;
                const d = new Date(sorted[i].exit_time);
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                raw.push({ date: dateStr, value: ev });
            }
            // Keep last per day, sorted
            const dayMap = new Map<string, number>();
            for (const p of raw) dayMap.set(p.date, p.value);
            return Array.from(dayMap.entries())
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([date, value]) => ({ time: date as unknown as Time, value }));
        }
    }, [trades, rollingWindow, riskR, basis]);



    useEffect(() => {
        if (!containerRef.current || !evData.length) return;

        const bgColor = "#16181A";
        const gridColor = "#2C2F33";
        const textColor = "#ffffff";

        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || 120,
            layout: {
                background: { type: ColorType.Solid, color: bgColor },
                textColor: textColor,
                fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
                fontSize: 10,
            },
            grid: {
                vertLines: { color: gridColor },
                horzLines: { color: gridColor },
            },
            rightPriceScale: {
                borderVisible: false,
                scaleMargins: {
                    top: 0.15,
                    bottom: 0.15,
                },
            },
            timeScale: { borderVisible: false, timeVisible: false },
            crosshair: { mode: 0 },
            localization: {
                timeFormatter: (time: Time) => {
                    if (typeof time === "string") return time;
                    if (typeof time === "object" && time !== null) {
                        const t = time as any;
                        if ("year" in t && "month" in t && "day" in t) {
                            return `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}`;
                        }
                    }
                    if (typeof time === "number") {
                        const date = new Date(time * 1000);
                        return date.toISOString().split("T")[0];
                    }
                    return String(time);
                },
            },
        });
        chartRef.current = chart;

        // BaselineSeries with gradient fill above/below zero — like equity/drawdown
        const series = chart.addSeries(BaselineSeries, {
            baseValue: { type: "price", price: 0 },
            topLineColor: "#10b981",
            topFillColor1: "rgba(16,185,129,0.18)",
            topFillColor2: "rgba(16,185,129,0.01)",
            bottomLineColor: "#ef4444",
            bottomFillColor1: "rgba(239,68,68,0.01)",
            bottomFillColor2: "rgba(239,68,68,0.18)",
            lineWidth: 2,
            priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        });
        series.setData(evData);

        // Ensure the full history is visible
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
    }, [evData, isDarkMode]);

    return (
        <div className="flex flex-col h-full transition-colors">
            <div className="px-3 py-2 flex items-center justify-between">
                <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-4 inline-flex items-center gap-1">
                    Rolling EV
                    <span className="ec-tooltip-container ec-tooltip-left">
                        <span
                            style={{ cursor: 'help', opacity: 0.6, fontSize: '8px', textTransform: 'none', letterSpacing: 'normal', userSelect: 'none' }}
                        >
                            (?)
                        </span>
                        <span className="ec-tooltip-text">
                            Esperanza Matemática (EV) móvil. Promedio continuo de la rentabilidad esperada por operación. Un EV positivo significa que el sistema genera beneficios a largo plazo.
                        </span>
                    </span>
                </span>
                <div className="flex items-center gap-3">
                    <div className="flex text-[9px] font-mono">
                        {([["trades", "T"], ["days", "D"]] as const).map(([val, label]) => (
                            <button
                                key={val}
                                onClick={() => setBasis(val)}
                                className={`px-1.5 py-0.5 transition-colors ${basis === val
                                    ? "text-[var(--color-ec-text-primary)] font-bold"
                                    : "text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)]"
                                    }`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-[8px] text-[var(--color-ec-text-secondary)] font-mono">W</span>
                        <input
                            type="number"
                            min={5}
                            max={500}
                            value={rollingWindow}
                            onChange={(e) => setRollingWindow(Math.max(5, Math.min(500, parseInt(e.target.value) || 50)))}
                            className="w-10 text-[10px] border-none bg-transparent text-center font-mono text-[var(--foreground)] outline-none"
                            style={{ borderBottom: '1px solid var(--color-ec-border)' }}
                        />
                    </div>
                </div>
            </div>
            <div ref={containerRef} className="flex-1 px-4 pb-4" style={{ minHeight: 100 }} />
        </div>
    );
}
