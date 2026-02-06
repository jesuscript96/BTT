"use client";

import React, { useMemo } from 'react';
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer
} from 'recharts';
import { BacktestResult } from '@/types/backtest';

interface EquityCurveChartProps {
    result: BacktestResult;
}

export function EquityCurveChart({ result }: EquityCurveChartProps) {
    // Memoize data for Recharts
    // Memoize data for Recharts, with downsampling for performance
    const data = useMemo(() => {
        if (!result || !result.equity_curve) {
            console.error("EquityCurveChart: No equity curve data found", result);
            return [];
        }
        console.log("EquityCurveChart: Raw points:", result.equity_curve.length);
        const rawData = result.equity_curve;
        const maxPoints = 1000; // Max points Recharts can handle smoothly

        let processedData = rawData;

        if (rawData.length > maxPoints) {
            const step = Math.ceil(rawData.length / maxPoints);
            processedData = rawData.filter((_, index) => index % step === 0);
        }

        return processedData.map(point => ({
            timestamp: new Date(point.timestamp).toLocaleDateString(),
            balance: point.balance,
            positions: point.open_positions || 0
        }));
    }, [result.equity_curve]);

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Portfolio Equity Curve</h2>
                <p className="text-sm text-gray-500">
                    Track your portfolio balance over time
                </p>
            </div>

            <ResponsiveContainer width="100%" height={400}>
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis
                        dataKey="timestamp"
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                    />
                    <YAxis
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                        tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#fff',
                            border: '1px solid #e5e7eb',
                            borderRadius: '8px',
                            color: '#000'
                        }}
                        formatter={(value: number | string) => [`$${Number(value).toLocaleString()}`, 'Balance']}
                    />
                    <Legend
                        wrapperStyle={{ color: '#6b7280' }}
                    />
                    <Line
                        type="monotone"
                        dataKey="balance"
                        stroke="#3b82f6"
                        strokeWidth={2}
                        dot={false}
                        name="Portfolio Balance"
                    />
                </LineChart>
            </ResponsiveContainer>

            {/* Summary Stats Below Chart */}
            <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-gray-200">
                <div>
                    <div className="text-xs text-gray-500 mb-1">Starting Balance</div>
                    <div className="text-lg font-semibold text-gray-900">
                        ${result.initial_capital.toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Ending Balance</div>
                    <div className="text-lg font-semibold text-teal-600">
                        ${result.final_balance.toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Total Profit/Loss</div>
                    <div className={`text-lg font-semibold ${result.final_balance > result.initial_capital ? 'text-green-600' : 'text-red-600'
                        }`}>
                        ${(result.final_balance - result.initial_capital).toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Return on Capital</div>
                    <div className={`text-lg font-semibold ${result.total_return_pct > 0 ? 'text-green-600' : 'text-red-600'
                        }`}>
                        {result.total_return_pct.toFixed(2)}%
                    </div>
                </div>
            </div>
        </div>
    );
}
