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
    const data = useMemo(() => {
        return result.equity_curve.map(point => ({
            timestamp: new Date(point.timestamp).toLocaleDateString(),
            balance: point.balance,
            positions: point.open_positions || 0
        }));
    }, [result.equity_curve]);

    return (
        <div className="bg-[#0f1419] rounded-lg border border-gray-800 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-white mb-2">Portfolio Equity Curve</h2>
                <p className="text-sm text-gray-400">
                    Track your portfolio balance over time
                </p>
            </div>

            <ResponsiveContainer width="100%" height={400}>
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis
                        dataKey="timestamp"
                        stroke="#6b7280"
                        tick={{ fill: '#9ca3af', fontSize: 12 }}
                    />
                    <YAxis
                        stroke="#6b7280"
                        tick={{ fill: '#9ca3af', fontSize: 12 }}
                        tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#1f2937',
                            border: '1px solid #374151',
                            borderRadius: '8px',
                            color: '#fff'
                        }}
                        formatter={(value: number | string) => [`$${Number(value).toLocaleString()}`, 'Balance']}
                    />
                    <Legend
                        wrapperStyle={{ color: '#9ca3af' }}
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
            <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-gray-800">
                <div>
                    <div className="text-xs text-gray-500 mb-1">Starting Balance</div>
                    <div className="text-lg font-semibold text-white">
                        ${result.initial_capital.toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Ending Balance</div>
                    <div className="text-lg font-semibold text-teal-400">
                        ${result.final_balance.toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Total Profit/Loss</div>
                    <div className={`text-lg font-semibold ${result.final_balance > result.initial_capital ? 'text-green-400' : 'text-red-400'
                        }`}>
                        ${(result.final_balance - result.initial_capital).toLocaleString()}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Return on Capital</div>
                    <div className={`text-lg font-semibold ${result.total_return_pct > 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                        {result.total_return_pct.toFixed(2)}%
                    </div>
                </div>
            </div>
        </div>
    );
}
