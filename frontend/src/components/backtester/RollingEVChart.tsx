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
import InfoTooltip from "@/components/backtester/InfoTooltip";

interface RollingEVChartProps {
    trades: TradeRecord[];
    riskR: number;
    isDarkMode?: boolean;
}

/** Esperanza matemática de un conjunto de operaciones, en R.
 *
 *      EV = P(gana) × media(R | gana) − P(pierde) × |media(R | pierde)|
 *
 * UNA SOLA definición para los dos modos del gráfico. Estaba duplicada, y esa
 * duplicación es la que dejó pasar que el modo «días» promediara EV diarios en
 * vez de operaciones — media de medias, con un día de una operación pesando
 * igual que uno de diez.
 */
function ev(ts: TradeRecord[]): number {
    if (!ts.length) return 0;
    const wins = ts.filter((t) => t.pnl > 0);
    const losses = ts.filter((t) => t.pnl <= 0);
    const media = (xs: TradeRecord[]) =>
        xs.length ? xs.reduce((s, t) => s + (t.r_multiple ?? 0), 0) / xs.length : 0;
    return (wins.length / ts.length) * media(wins)
         - (losses.length / ts.length) * Math.abs(media(losses));
}

export default function RollingEVChart({ trades, riskR, isDarkMode = false }: RollingEVChartProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const [rollingWindow, setRollingWindow] = useState(50);
    const [inputValue, setInputValue] = useState("50");
    type RollingBasis = "trades" | "days";
    const [basis, setBasis] = useState<RollingBasis>("days");

    useEffect(() => {
        setInputValue(String(rollingWindow));
    }, [rollingWindow]);

    const evData = useMemo(() => {
        if (!trades.length) return [];

        if (basis === "days") {
            // Ventana de N DÍAS, con TODAS las operaciones de esos días juntas.
            //
            // ANTES se sacaba el EV de cada día y luego se promediaban esos EV,
            // o sea MEDIA DE MEDIAS: un día con una operación pesaba igual que
            // uno con diez. Con 1 trade de +1,0R el lunes y 10 de −0,2R el
            // martes daba +0,400 R cuando lo real es −0,091 R — cambiaba hasta
            // el SIGNO, y un mes de días flojos con una ganadora suelta se
            // pintaba como rentable. (Corregido el 2026-09-03 a petición de
            // Jaume: «usar el cálculo en base a los trades que ha habido esos
            // días, independientemente de si han sido 1, 3 o 33».)
            const dayTrades = new Map<string, TradeRecord[]>();
            for (const t of trades) {
                const d = new Date(t.exit_time);
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                if (!dayTrades.has(dateStr)) dayTrades.set(dateStr, []);
                dayTrades.get(dateStr)!.push(t);
            }
            const dias = Array.from(dayTrades.keys()).sort((a, b) => a.localeCompare(b));
            const reqDays = Math.min(rollingWindow, dias.length);
            const result: { time: Time; value: number }[] = [];
            for (let i = 0; i < dias.length; i++) {
                const start = Math.max(0, i - rollingWindow + 1);
                const ventana = dias.slice(start, i + 1);
                if (ventana.length < reqDays) continue;
                // Todas las operaciones de la ventana, en un solo montón.
                const delTramo = ventana.flatMap((d) => dayTrades.get(d)!);
                result.push({ time: dias[i] as unknown as Time, value: ev(delTramo) });
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
                const d = new Date(sorted[i].exit_time);
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                raw.push({ date: dateStr, value: ev(slice) });
            }
            // Keep last per day, sorted
            const dayMap = new Map<string, number>();
            for (const p of raw) dayMap.set(p.date, p.value);
            return Array.from(dayMap.entries())
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([date, value]) => ({ time: date as unknown as Time, value }));
        }
    }, [trades, rollingWindow, basis]);



    useEffect(() => {
        if (!containerRef.current || !evData.length) return;

        const bgColor = "#16181A";
        const gridColor = "#2C2F33";
        const textColor = "#ffffff";

        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || 120,
            handleScale: {
                mouseWheel: false,
                pinch: false,
                axisPressedMouseMove: {
                    time: false,
                    price: false,
                },
                axisDoubleClickReset: false,
            },
            handleScroll: {
                mouseWheel: false,
                pressedMouseMove: false,
                horzTouchDrag: false,
                vertTouchDrag: false,
            },
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
                    <InfoTooltip
                        position="left"
                        text="Esperanza Matemática (EV) móvil. Promedio continuo de la rentabilidad esperada por operación. Un EV positivo significa que el sistema genera beneficios a largo plazo."
                    />
                </span>
                <div className="flex items-center gap-3">
                    <div className="flex text-[10px] font-mono gap-2.5">
                        {([["trades", "T"], ["days", "D"]] as const).map(([val, label]) => (
                            <button
                                key={val}
                                onClick={() => setBasis(val)}
                                className={`px-2 py-0.5 rounded transition-colors ${basis === val
                                    ? "text-[var(--color-ec-text-primary)] font-bold bg-[rgba(216,122,61,0.15)] border border-[rgba(216,122,61,0.3)]"
                                    : "text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] border border-transparent"
                                    }`}
                                style={{ cursor: 'pointer' }}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-[8px] text-[var(--color-ec-text-secondary)] font-mono">W</span>
                        <input
                            type="number"
                            value={inputValue}
                            onChange={(e) => {
                                const valStr = e.target.value;
                                setInputValue(valStr);
                                const parsed = parseInt(valStr);
                                if (!isNaN(parsed) && parsed >= 5 && parsed <= 500) {
                                    setRollingWindow(parsed);
                                }
                            }}
                            onBlur={() => {
                                const parsed = parseInt(inputValue);
                                if (isNaN(parsed) || parsed < 5) {
                                    setRollingWindow(5);
                                    setInputValue("5");
                                } else if (parsed > 500) {
                                    setRollingWindow(500);
                                    setInputValue("500");
                                } else {
                                    setRollingWindow(parsed);
                                    setInputValue(String(parsed));
                                }
                            }}
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
