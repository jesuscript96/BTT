"use client";

import React, { useMemo } from 'react';
import {
    AreaChart,
    Area,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine
} from 'recharts';
import { BacktestResult } from '@/types/backtest';

interface DrawdownChartProps {
    result: BacktestResult;
}

export function DrawdownChart({ result }: DrawdownChartProps) {
    // Memoize data for Recharts to prevent re-calculations
    const data = useMemo(() => {
        return result.drawdown_series.map(point => ({
            timestamp: new Date(point.timestamp).toLocaleDateString(),
            drawdown: -point.drawdown_pct, // Negative for visual effect
            peak: point.peak
        }));
    }, [result.drawdown_series]);

    // Memoize max drawdown point
    const maxDDPoint = useMemo(() => {
        if (!result.drawdown_series || result.drawdown_series.length === 0) return null;
        return result.drawdown_series.reduce((max, point) =>
            point.drawdown_pct > max.drawdown_pct ? point : max
            , result.drawdown_series[0]);
    }, [result.drawdown_series]);

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Drawdown & Stagnation</h2>
                <p className="text-sm text-gray-500">
                    Distance from all-time high equity
                </p>
            </div>

            <ResponsiveContainer width="100%" height={400}>
                <AreaChart data={data}>
                    <defs>
                        <linearGradient id="colorDrawdown" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#ef4444" stopOpacity={0.1} />
                        </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis
                        dataKey="timestamp"
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                    />
                    <YAxis
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                        tickFormatter={(value) => `${value.toFixed(0)}%`}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#fff',
                            border: '1px solid #e5e7eb',
                            borderRadius: '8px',
                            color: '#000'
                        }}
                        formatter={(value: number | string) => [`${Math.abs(Number(value)).toFixed(2)}%`, 'Drawdown']}
                    />
                    <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="3 3" />
                    <Area
                        type="linear"
                        dataKey="drawdown"
                        stroke="#ef4444"
                        strokeWidth={2}
                        fillOpacity={1}
                        fill="url(#colorDrawdown)"
                    />
                </AreaChart>
            </ResponsiveContainer>

            {/* Drawdown Stats */}
            <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-gray-200">
                <div>
                    <div className="text-xs text-gray-500 mb-1">Max Drawdown</div>
                    <div className="text-lg font-semibold text-red-600">
                        -{result.max_drawdown_pct.toFixed(2)}%
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Max DD Value</div>
                    <div className="text-lg font-semibold text-red-600">
                        -${result.max_drawdown_value.toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Max DD Date</div>
                    <div className="text-sm font-medium text-gray-700">
                        {maxDDPoint ? new Date(maxDDPoint.timestamp).toLocaleDateString() : 'N/A'}
                    </div>
                </div>
            </div>
        </div>
    );
}
