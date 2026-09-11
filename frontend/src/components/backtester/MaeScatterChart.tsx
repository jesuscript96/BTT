"use client";

import { useMemo, useState } from "react";
import {
    ScatterChart,
    Scatter,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine
} from "recharts";
import type { TradeRecord } from "@/lib/api_backtester";
import InfoTooltip from "@/components/backtester/InfoTooltip";

interface MaeScatterChartProps {
    trades: TradeRecord[];
    isDarkMode?: boolean;
}

/** Las dos vistas del gráfico: el MAE de siempre, o las mechas Black Swan. */
type Vista = "mae" | "bs";

/** Mecha (%) a partir de la cual una vela cuenta como Black Swan: el precio se
 *  duplica dentro del minuto. Es la línea verde discontinua de la vista BS. */
const BS_UMBRAL = 100;

// Simple Linear Regression calculation
function calculateRegression(points: { x: number, y: number }[]) {
    const n = points.length;
    if (n < 2) return null;

    let sumX = 0;
    let sumY = 0;
    let sumXY = 0;
    let sumXX = 0;

    for (const p of points) {
        sumX += p.x;
        sumY += p.y;
        sumXY += p.x * p.y;
        sumXX += p.x * p.x;
    }

    const denominator = n * sumXX - sumX * sumX;
    if (denominator === 0) return null;

    const slope = (n * sumXY - sumX * sumY) / denominator;
    const intercept = (sumY - slope * sumX) / n;

    let rSquared = 0;
    const meanY = sumY / n;
    let ssTot = 0;
    let ssRes = 0;
    for (const p of points) {
        const predictedY = slope * p.x + intercept;
        ssTot += Math.pow(p.y - meanY, 2);
        ssRes += Math.pow(p.y - predictedY, 2);
    }
    if (ssTot > 0) {
        rSquared = 1 - (ssRes / ssTot);
    }

    const minX = Math.min(...points.map(p => p.x));
    const maxX = Math.max(...points.map(p => p.x));

    return {
        m: slope,
        b: intercept,
        r2: rSquared,
        minX,
        maxX
    };
}

/** Hora (HH:MM) de un epoch en segundos, en el mismo reloj que las velas del lago. */
const horaDe = (epoch?: number) =>
    epoch != null ? new Date(epoch * 1000).toISOString().slice(11, 16) : null;

const CustomTooltip = ({ active, payload, isDarkMode, vista }: { active?: boolean, payload?: unknown[], isDarkMode?: boolean, vista: Vista }) => {
    if (active && payload && payload.length) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = (payload[0] as any).payload;
        if (!data.trade) return null;
        const t: TradeRecord = data.trade;

        const caja = {
            backgroundColor: isDarkMode ? '#1e293b' : '#fafaf7',
            border: '1px solid var(--border)',
            color: 'var(--text-data)'
        };

        if (vista === "bs") {
            const hora = horaDe(t.bs_wick_time_epoch);
            return (
                <div className="p-2 rounded text-[10px] font-mono" style={caja}>
                    <p className="font-semibold mb-0.5">{t.ticker} · {t.date}</p>
                    <p style={{ color: '#22c55e' }}>mecha: {data.y.toFixed(0)}%{hora ? ` a las ${hora}` : ''}</p>
                    <p>ret: {data.x.toFixed(2)}%</p>
                    <p>pnl: ${t.pnl.toFixed(2)}</p>
                    <p>salida: {t.exit_reason}{t.bs_modo ? ` · cerrado por BS${t.bs_slip_pct != null ? ` (+${t.bs_slip_pct.toFixed(0)}%)` : ''}` : ''}</p>
                </div>
            );
        }

        return (
            <div className="p-2 rounded text-[10px] font-mono" style={caja}>
                <p className="font-semibold mb-0.5">{t.direction} Trade · {t.ticker} {t.date}</p>
                <p>ret: {data.x.toFixed(2)}%</p>
                <p>mae: {data.y.toFixed(2)}%</p>
                <p>mfe: {t.mfe !== undefined ? `${t.mfe.toFixed(2)}%` : '-'}</p>
                <p>pnl: ${t.pnl.toFixed(2)}</p>
            </div>
        );
    }
    return null;
};

const CustomDot = (props: { cx?: number; cy?: number }) => {
    const { cx, cy } = props;
    if (!cx || !cy) return null;
    return <circle cx={cx} cy={cy} r={2} stroke="#D87A3D" fill="#D87A3D" />;
};

// Verde para la vista BS, para que al cambiar se vea de un vistazo que es
// otra cosa y no el MAE.
const GreenDot = (props: { cx?: number; cy?: number }) => {
    const { cx, cy } = props;
    if (!cx || !cy) return null;
    return <circle cx={cx} cy={cy} r={2} stroke="#22c55e" fill="#22c55e" />;
};

const formatTick = (v: number) => `${v.toFixed(0)}`;
const renderNullShape = () => null;

const TICK_STYLE = { fontSize: 9, fill: "#8A8D92", fontFamily: 'monospace' };
const CHART_MARGIN = { top: 10, right: 10, bottom: 0, left: -20 };
const TOOLTIP_CURSOR = { strokeDasharray: '3 3' };

export default function MaeScatterChart({ trades, isDarkMode }: MaeScatterChartProps) {
    const [vista, setVista] = useState<Vista>("mae");

    const processed = useMemo(() => {
        let sumMae = 0;
        let sumMfe = 0;
        let tradeCount = 0;
        const winners: { x: number, y: number, trade: TradeRecord }[] = [];
        const losers: { x: number, y: number, trade: TradeRecord }[] = [];

        for (const t of trades) {
            let maeVal = t.mae !== undefined && t.mae !== null ? t.mae : 0;
            maeVal = Math.abs(maeVal);

            let mfeVal = t.mfe !== undefined && t.mfe !== null ? t.mfe : 0;
            mfeVal = Math.abs(mfeVal);

            sumMae += maeVal;
            sumMfe += mfeVal;
            tradeCount++;

            const p = { x: t.return_pct || 0, y: maeVal, trade: t };
            if (t.pnl > 0) winners.push(p);
            else losers.push(p);
        }

        const winReg = calculateRegression(winners);
        const lossReg = calculateRegression(losers);

        const winLineData = winReg ? [
            { x: 0, y: winReg.m * 0 + winReg.b },
            { x: winReg.maxX, y: winReg.m * winReg.maxX + winReg.b }
        ] : null;

        const lossLineData = lossReg ? [
            { x: lossReg.minX, y: lossReg.m * lossReg.minX + lossReg.b },
            { x: 0, y: lossReg.m * 0 + lossReg.b }
        ] : null;

        return {
            winners,
            losers,
            winLineData,
            lossLineData,
            winR2: winReg?.r2,
            lossR2: lossReg?.r2,
            avgMae: tradeCount > 0 ? sumMae / tradeCount : 0,
            avgMfe: tradeCount > 0 ? sumMfe / tradeCount : 0
        };
    }, [trades]);

    // Vista BS: un punto por trade con la mecha adversa máxima que sufrió
    // estando dentro (`bs_wick_pct`, descriptivo, lo calcula el backend en
    // toda corrida nueva). Las corridas guardadas antes de existir el campo no
    // lo traen: se avisa en vez de pintar ceros.
    const bs = useMemo(() => {
        const puntos: { x: number, y: number, trade: TradeRecord }[] = [];
        let conDato = 0;
        let expuestas = 0;
        let max = 0;
        let cerradas = 0;
        for (const t of trades) {
            const w = t.bs_wick_pct;
            if (w == null) continue;
            conDato++;
            if (w >= BS_UMBRAL) expuestas++;
            if (w > max) max = w;
            if (t.bs_modo) cerradas++;
            puntos.push({ x: t.return_pct || 0, y: w, trade: t });
        }
        return { puntos, conDato, expuestas, max, cerradas };
    }, [trades]);

    const tooltipContent = useMemo(() => {
        return <CustomTooltip isDarkMode={isDarkMode} vista={vista} />;
    }, [isDarkMode, vista]);

    const lineStyle = useMemo(() => ({
        stroke: isDarkMode ? "#94a3b8" : "#44403c",
        strokeDasharray: "4 4",
        strokeWidth: 1.5
    }), [isDarkMode]);

    if (!trades.length) {
        return <div className="p-4 text-center text-[var(--muted)] text-[11px] font-mono">Sin datos</div>;
    }

    const dotColor = "#D87A3D"; // Color ec-copper de la app
    const bsColor = "#22c55e";
    const gridColor = "#2C2F33"; // Color ec-border
    const esBS = vista === "bs";

    return (
        <div className="flex flex-col h-full transition-colors relative">
            <div className="px-1 py-2 flex items-center justify-between">
                <span className="text-[10px] font-semibold text-[#ffffff] uppercase tracking-[0.12em] inline-flex items-center gap-1">
                    {esBS ? "Mechas BS vs Rets" : "MAE/MFE vs Rets"}
                    <InfoTooltip
                        position="left"
                        text={esBS
                            ? `Mecha Black Swan: la mayor distancia entre la apertura y el máximo (el mínimo, en largo) de una vela de 1 minuto mientras el trade estuvo dentro, en % de la apertura. Cruzada contra el retorno final de cada trade. La línea verde marca el ${BS_UMBRAL} % (el precio se duplica en un minuto): los puntos por encima son las veces que la estrategia estuvo expuesta a un mechazo. Es descriptivo: el motor no ha cambiado nada; el coste de BSwan del panel es lo que simula comérselos. Se mide sobre las velas del lago, que a veces esconden el pico real.`
                            : "MAE (Maximum Adverse Excursion): Máxima pérdida flotante temporal que sufrió cada operación durante su vida. MFE (Maximum Favorable Excursion): Máxima ganancia flotante temporal alcanzada. Este gráfico cruza el MAE/MFE contra el Retorno final (%) de cada trade. Ayuda a ver si cortamos las ganancias muy rápido (MFE alto y retorno bajo) o si dejamos correr demasiado las pérdidas (MAE alto)."}
                    />
                </span>
                <div className="flex items-center gap-4 text-[10px] text-[#ffffff] font-mono">
                    <div className="flex items-center gap-3 mr-2">
                        <span className="flex items-center gap-1 opacity-80">
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: esBS ? bsColor : dotColor }}></span>
                            {esBS ? "mechas" : "ops"}
                        </span>
                        <span className="flex items-center gap-1.5 opacity-85">
                            <span className="w-3 border-b border-dashed inline-block align-middle" style={{ borderColor: esBS ? bsColor : '#ffffff', marginBottom: '1px' }}></span>
                            {esBS ? `${BS_UMBRAL}% = BS` : "trend"}
                        </span>
                    </div>
                    {esBS ? (
                        <div className="flex gap-3">
                            <span title="Trades cuya mecha máxima estando dentro llegó al umbral, sobre los que traen el dato">
                                expuestas ≥{BS_UMBRAL}%: <strong className="text-[#ffffff]">{bs.expuestas}</strong> de {bs.conDato}
                            </span>
                            <span>máx: <strong className="text-[#ffffff]">{bs.max.toFixed(0)}%</strong></span>
                            {bs.cerradas > 0 && (
                                <span title="Trades que el coste de Black Swan cerró en esta corrida">
                                    cerradas por BS: <strong style={{ color: '#a855f7' }}>{bs.cerradas}</strong>
                                </span>
                            )}
                        </div>
                    ) : (
                        <div className="flex gap-3">
                            <span>avg mae: <strong className="text-[#ffffff]">{processed.avgMae.toFixed(2)}%</strong></span>
                            <span>avg mfe: <strong className="text-[#ffffff]">{processed.avgMfe.toFixed(2)}%</strong></span>
                        </div>
                    )}
                    {/* Conmutador MAE | BS. Pequeño a propósito: cabe en la
                        cabecera sin mover nada de lo que ya había. */}
                    <div className="flex" style={{ border: '1px solid var(--color-ec-border)' }}
                         title="Cambiar entre el MAE de la estrategia y las mechas Black Swan que sufrió cada trade">
                        {(["mae", "bs"] as const).map((v, i) => (
                            <button
                                key={v}
                                type="button"
                                onClick={() => setVista(v)}
                                style={{
                                    background: vista === v ? (v === "bs" ? "#16a34a" : "var(--color-ec-copper)") : "transparent",
                                    color: vista === v ? "#ffffff" : "var(--color-ec-text-secondary)",
                                    fontWeight: vista === v ? 700 : 400,
                                    border: 0, borderLeft: i ? '1px solid var(--color-ec-border)' : undefined,
                                    fontFamily: 'monospace', fontSize: 9, height: 18, lineHeight: '18px',
                                    padding: '0 6px', cursor: 'pointer', letterSpacing: '0.06em',
                                }}
                            >
                                {v === "mae" ? "MAE" : "BS"}
                            </button>
                        ))}
                    </div>
                </div>
            </div>
            <div className="flex-1 min-h-[140px] relative">
                {!esBS && (
                    <div className="absolute top-2 right-3 text-[9px] text-[#ffffff] flex flex-col items-end gap-0.5 pointer-events-none z-10 font-mono">
                        {processed.winR2 !== undefined && <span>W R² = {(processed.winR2 * 100).toFixed(1)}%</span>}
                        {processed.lossR2 !== undefined && <span>L R² = {(processed.lossR2 * 100).toFixed(1)}%</span>}
                    </div>
                )}
                {esBS && bs.conDato === 0 ? (
                    <div className="absolute inset-0 flex items-center justify-center text-center px-6 text-[10px] font-mono text-[var(--color-ec-text-muted)]">
                        Esta corrida no trae la mecha de cada trade (es anterior a esta vista). Vuelve a ejecutar el backtest para verla.
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <ScatterChart margin={CHART_MARGIN}>
                            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                            <XAxis
                                type="number"
                                dataKey="x"
                                name="Retorno"
                                unit="%"
                                tick={TICK_STYLE}
                                tickFormatter={formatTick}
                                axisLine={false}
                                tickLine={false}
                                height={25}
                            />
                            <YAxis
                                type="number"
                                dataKey="y"
                                name={esBS ? "Mecha" : "MAE"}
                                unit="%"
                                tick={TICK_STYLE}
                                tickFormatter={formatTick}
                                axisLine={false}
                                tickLine={false}
                            />
                            <Tooltip cursor={TOOLTIP_CURSOR} content={tooltipContent} />

                            <ReferenceLine y={0} stroke={gridColor} strokeWidth={1} />
                            <ReferenceLine x={0} stroke={isDarkMode ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)"} strokeWidth={1} />

                            {esBS && (
                                <ReferenceLine y={BS_UMBRAL} stroke={bsColor} strokeDasharray="4 4" strokeWidth={1} />
                            )}
                            {esBS && (
                                <Scatter name="Mechas" data={bs.puntos} shape={GreenDot} isAnimationActive={false} />
                            )}

                            {!esBS && (
                                <Scatter name="Perdedoras" data={processed.losers} shape={CustomDot} isAnimationActive={false} />
                            )}
                            {!esBS && (
                                <Scatter name="Ganadoras" data={processed.winners} shape={CustomDot} isAnimationActive={false} />
                            )}

                            {!esBS && processed.lossLineData && (
                                <Scatter
                                    data={processed.lossLineData}
                                    shape={renderNullShape}
                                    line={lineStyle}
                                    tooltipType="none"
                                    isAnimationActive={false}
                                />
                            )}
                            {!esBS && processed.winLineData && (
                                <Scatter
                                    data={processed.winLineData}
                                    shape={renderNullShape}
                                    line={lineStyle}
                                    tooltipType="none"
                                    isAnimationActive={false}
                                />
                            )}
                        </ScatterChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
}
