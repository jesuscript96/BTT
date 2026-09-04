"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import {
    createChart,
    BaselineSeries,
    LineSeries,
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

type Unidad = "R" | "pct";

/** Recorrido de UNA operación, en la unidad pedida.
 *
 *  R    múltiplos de riesgo — «cuántos riesgos gano por operación»
 *  pct  % del precio de entrada — «cuánto se movió el precio a mi favor»
 *
 * NO SON CONVERTIBLES ENTRE SÍ con un factor fijo: dependen de la distancia al
 * stop de cada operación. 0,15 R puede ser un 6 % en una entrada con el stop
 * lejos y un 1 % en otra con el stop pegado.
 *
 * El % se saca de `entry_price`/`exit_price` y NO de `r_multiple`: el motor
 * guarda ese campo redondeado a dos decimales, y sobre operaciones de céntimos
 * el redondeo se come justo el margen que se quiere medir (un fade de locates
 * ronda el 1 %).
 */
function recorrido(t: TradeRecord, u: Unidad): number {
    if (u === "R") return t.r_multiple ?? 0;
    const entrada = t.avg_entry_price ?? t.entry_price;
    if (!entrada) return 0;
    const bruto = (t.exit_price - entrada) / entrada * 100;
    // En corto se gana cuando el precio baja.
    return String(t.direction).toLowerCase().startsWith("short") ? -bruto : bruto;
}

/** Esperanza matemática de un conjunto de operaciones.
 *
 *      EV = P(gana) × media(gana) − P(pierde) × |media(pierde)|
 *
 * UNA SOLA definición para los dos modos del gráfico. Estaba duplicada, y esa
 * duplicación es la que dejó pasar que el modo «días» promediara EV diarios en
 * vez de operaciones — media de medias, con un día de una operación pesando
 * igual que uno de diez.
 */
function ev(ts: TradeRecord[], u: Unidad = "R"): number {
    if (!ts.length) return 0;
    const wins = ts.filter((t) => t.pnl > 0);
    const losses = ts.filter((t) => t.pnl <= 0);
    const media = (xs: TradeRecord[]) =>
        xs.length ? xs.reduce((s, t) => s + recorrido(t, u), 0) / xs.length : 0;
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
    /** R (múltiplos de riesgo) o % del precio de entrada. El % es el que sirve
     *  para decidir si compensan los locates: se compara con el fade, que
     *  también va en % del precio. */
    const [unidad, setUnidad] = useState<Unidad>("R");
    /** «MEDIA MADRE»: media móvil SOBRE la curva del rolling, para ver la
     *  tendencia de fondo sin el zigzag. 0 = apagada.
     *
     *  Es una media de una media, y eso está bien AQUÍ y mal en el cálculo del
     *  EV: allí promediar EV diarios daba peso igual a un día de una operación
     *  y a uno de diez (era el bug del modo «días»). Esta suaviza una curva ya
     *  calculada, que es otra cosa — no cambia ningún EV, solo dibuja encima. */
    const [mm, setMm] = useState(0);
    const [mmInput, setMmInput] = useState("0");

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
                result.push({ time: dias[i] as unknown as Time, value: ev(delTramo, unidad) });
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
                raw.push({ date: dateStr, value: ev(slice, unidad) });
            }
            // Keep last per day, sorted
            const dayMap = new Map<string, number>();
            for (const p of raw) dayMap.set(p.date, p.value);
            return Array.from(dayMap.entries())
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([date, value]) => ({ time: date as unknown as Time, value }));
        }
    }, [trades, rollingWindow, basis, unidad]);



    /** La curva suavizada. Media móvil simple de los últimos `mm` puntos. */
    const mmData = useMemo(() => {
        if (mm < 2 || evData.length < mm) return [];
        const out: { time: Time; value: number }[] = [];
        for (let i = mm - 1; i < evData.length; i++) {
            let suma = 0;
            for (let j = i - mm + 1; j <= i; j++) suma += evData[j].value;
            out.push({ time: evData[i].time, value: suma / mm });
        }
        return out;
    }, [evData, mm]);

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

        // La media madre, encima y en cobre: es una lectura de apoyo, no el
        // dato. Línea fina para que no compita con la curva real.
        if (mmData.length) {
            const smm = chart.addSeries(LineSeries, {
                color: "#D87A3D",
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            });
            smm.setData(mmData);
        }

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
    }, [evData, mmData, isDarkMode]);

    return (
        <div className="flex flex-col h-full transition-colors">
            <div className="px-3 py-2 flex items-center justify-between">
                <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-4 inline-flex items-center gap-1">
                    Rolling EV <span style={{ opacity: 0.6, fontWeight: 400 }}>
                        ({unidad === "R" ? "en R" : "en % del precio"})
                    </span>
                    <InfoTooltip
                        position="left"
                        text={unidad === "R"
                            ? "Esperanza Matemática (EV) móvil, en MÚLTIPLOS DE RIESGO: 0,15 significa que ganas de media 0,15 veces tu riesgo por operación. Con riesgo 300 $, son 45 $. OJO: no es un %, y no se puede copiar al campo EV del cuadro de mandos."
                            : "Esperanza Matemática (EV) móvil, en % DEL PRECIO DE ENTRADA: cuánto se mueve el precio a tu favor de media. ESTE es el que se compara con el coste de los locates y el que va en el campo EV del cuadro de mandos."}
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
                    {/* UNIDAD. R y % NO son la misma medida escalada: dependen
                        de la distancia al stop de cada operación. El % es el que
                        sirve para decidir sobre locates, porque el coste del
                        locate también es un % del precio. */}
                    <div className="flex text-[10px] font-mono gap-2.5">
                        {([["R", "R"], ["pct", "%"]] as const).map(([val, label]) => (
                            <button
                                key={val}
                                onClick={() => setUnidad(val)}
                                title={val === "R"
                                    ? "En múltiplos de riesgo: cuántos riesgos ganas por operación"
                                    : "En % del precio de entrada: cuánto se mueve el precio a tu favor. Es el que se compara con el coste de los locates."}
                                className={`px-2 py-0.5 rounded transition-colors ${unidad === val
                                    ? "text-[var(--color-ec-text-primary)] font-bold bg-[rgba(216,122,61,0.15)] border border-[rgba(216,122,61,0.3)]"
                                    : "text-[var(--color-ec-text-secondary)] hover:text-[var(--color-ec-text-primary)] border border-transparent"
                                    }`}
                                style={{ cursor: 'pointer' }}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    {/* MEDIA MADRE: media móvil SOBRE la curva del rolling,
                        en cobre y fina. Sirve para ver la tendencia de fondo sin
                        el zigzag — con ventanas cortas la curva baila y cuesta
                        decidir si la estrategia va a mejor o a peor. 0 = apagada.

                        Vale para los dos modos (T y D): suaviza la curva ya
                        calculada, no vuelve a promediar operaciones. */}
                    <div className="flex items-center gap-1">
                        <span
                            className="text-[8px] text-[var(--color-ec-copper)] font-mono font-bold"
                            title="Media Madre: media móvil sobre la curva, para ver la tendencia sin el zigzag. 0 la apaga."
                        >MM</span>
                        <input
                            type="number"
                            value={mmInput}
                            min={0}
                            max={200}
                            onChange={(e) => {
                                const v = e.target.value;
                                setMmInput(v);
                                const n = parseInt(v);
                                setMm(!isNaN(n) && n >= 2 && n <= 200 ? n : 0);
                            }}
                            onBlur={() => setMmInput(String(mm || 0))}
                            title="Periodo de la media madre (0 = apagada)"
                            className="w-9 text-[10px] border-none bg-transparent text-center font-mono text-[var(--foreground)] outline-none"
                            style={{ borderBottom: '1px solid var(--color-ec-border)' }}
                        />
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
