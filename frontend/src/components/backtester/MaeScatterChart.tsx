"use client";

import { useMemo } from "react";
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

interface MaeScatterChartProps {
    trades: TradeRecord[];
    isDarkMode?: boolean;
}

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

const CustomTooltip = ({ active, payload, isDarkMode }: { active?: boolean, payload?: unknown[], isDarkMode?: boolean }) => {
    if (active && payload && payload.length) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = (payload[0] as any).payload;
        if (!data.trade) return null;

        return (
            <div
                className="p-2 rounded text-[10px] font-mono"
                style={{
                    backgroundColor: isDarkMode ? '#1e293b' : '#fafaf7',
                    border: '1px solid var(--border)',
                    color: 'var(--text-data)'
                }}
            >
                <p className="font-semibold mb-0.5">{data.trade.direction} Trade</p>
                <p>ret: {data.x.toFixed(2)}%</p>
                <p>mae: {data.y.toFixed(2)}%</p>
                <p>mfe: {data.trade.mfe !== undefined ? `${data.trade.mfe.toFixed(2)}%` : '-'}</p>
                <p>pnl: ${data.trade.pnl.toFixed(2)}</p>
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

const formatTick = (v: number) => `${v.toFixed(0)}`;
const renderNullShape = () => null;

const TICK_STYLE = { fontSize: 9, fill: "#8A8D92", fontFamily: 'monospace' };
const CHART_MARGIN = { top: 10, right: 10, bottom: 0, left: -20 };
const TOOLTIP_CURSOR = { strokeDasharray: '3 3' };

export default function MaeScatterChart({ trades, isDarkMode }: MaeScatterChartProps) {
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

    const tooltipContent = useMemo(() => {
        return <CustomTooltip isDarkMode={isDarkMode} />;
    }, [isDarkMode]);

    const lineStyle = useMemo(() => ({
        stroke: isDarkMode ? "#94a3b8" : "#44403c",
        strokeDasharray: "4 4",
        strokeWidth: 1.5
    }), [isDarkMode]);

    if (!trades.length) {
        return <div className="p-4 text-center text-[var(--muted)] text-[11px] font-mono">Sin datos</div>;
    }

    const dotColor = "#D87A3D"; // Color ec-copper de la app
    const gridColor = "#2C2F33"; // Color ec-border

    return (
        <div className="flex flex-col h-full transition-colors relative">
            <div className="px-1 py-2 flex items-center justify-between">
                <span className="text-[10px] font-semibold text-[#ffffff] uppercase tracking-[0.12em]">
                    MAE/MFE vs Rets
                </span>
                <div className="flex items-center gap-4 text-[10px] text-[#ffffff] font-mono">
                    <div className="flex items-center gap-3 mr-2">
                        <span className="flex items-center gap-1 opacity-80">
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: dotColor }}></span>
                            ops
                        </span>
                        <span className="flex items-center gap-1.5 opacity-85">
                            <span className="w-3 border-b border-dashed inline-block align-middle" style={{ borderColor: '#ffffff', marginBottom: '1px' }}></span>
                            trend
                        </span>
                    </div>
                    <div className="flex gap-3">
                        <span>avg mae: <strong className="text-[#ffffff]">{processed.avgMae.toFixed(2)}%</strong></span>
                        <span>avg mfe: <strong className="text-[#ffffff]">{processed.avgMfe.toFixed(2)}%</strong></span>
                    </div>
                </div>
            </div>
            <div className="flex-1 min-h-[140px] relative">
                <div className="absolute top-2 right-3 text-[9px] text-[#ffffff] flex flex-col items-end gap-0.5 pointer-events-none z-10 font-mono">
                    {processed.winR2 !== undefined && <span>W R² = {(processed.winR2 * 100).toFixed(1)}%</span>}
                    {processed.lossR2 !== undefined && <span>L R² = {(processed.lossR2 * 100).toFixed(1)}%</span>}
                </div>
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
                            name="MAE"
                            unit="%"
                            tick={TICK_STYLE}
                            tickFormatter={formatTick}
                            axisLine={false}
                            tickLine={false}
                        />
                        <Tooltip cursor={TOOLTIP_CURSOR} content={tooltipContent} />

                        <ReferenceLine y={0} stroke={gridColor} strokeWidth={1} />
                        <ReferenceLine x={0} stroke={isDarkMode ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)"} strokeWidth={1} />

                        <Scatter name="Perdedoras" data={processed.losers} shape={CustomDot} isAnimationActive={false} />
                        <Scatter name="Ganadoras" data={processed.winners} shape={CustomDot} isAnimationActive={false} />

                        {processed.lossLineData && (
                            <Scatter
                                data={processed.lossLineData}
                                shape={renderNullShape}
                                line={lineStyle}
                                tooltipType="none"
                                isAnimationActive={false}
                            />
                        )}
                        {processed.winLineData && (
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
            </div>
        </div>
    );
}
