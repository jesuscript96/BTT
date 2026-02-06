"use client";

import React from 'react';
import { MonteCarloResult } from '@/types/backtest';
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine
} from 'recharts';

interface MonteCarloResultsProps {
    monteCarlo: MonteCarloResult;
    initialCapital: number;
}

export function MonteCarloResults({ monteCarlo, initialCapital }: MonteCarloResultsProps) {
    // Create distribution data for visualization
    const distributionData = [
        { label: '5th %ile', value: monteCarlo.percentile_5 },
        { label: '25th %ile', value: monteCarlo.percentile_25 },
        { label: 'Median', value: monteCarlo.median_final_balance },
        { label: '75th %ile', value: monteCarlo.percentile_75 },
        { label: '95th %ile', value: monteCarlo.percentile_95 },
    ];

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Monte Carlo Simulation</h2>
                <p className="text-sm text-gray-500">
                    1,000 simulations with randomized trade order
                </p>
            </div>

            {/* Key Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Worst Case</div>
                    <div className="text-lg font-semibold text-red-600">
                        ${monteCarlo.worst_final_balance.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {((monteCarlo.worst_final_balance - initialCapital) / initialCapital * 100).toFixed(1)}%
                    </div>
                </div>

                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Best Case</div>
                    <div className="text-lg font-semibold text-green-600">
                        ${monteCarlo.best_final_balance.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {((monteCarlo.best_final_balance - initialCapital) / initialCapital * 100).toFixed(1)}%
                    </div>
                </div>

                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Worst Drawdown</div>
                    <div className="text-lg font-semibold text-red-600">
                        -{monteCarlo.worst_drawdown_pct.toFixed(2)}%
                    </div>
                </div>

                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Probability of Ruin</div>
                    <div className="text-lg font-semibold text-yellow-600">
                        {monteCarlo.probability_of_ruin.toFixed(2)}%
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        (Balance &lt; 50% initial)
                    </div>
                </div>
            </div>

            {/* Distribution Chart */}
            <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-500 mb-3">Final Balance Distribution</h3>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={distributionData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                        <XAxis
                            dataKey="label"
                            stroke="#6b7280"
                            tick={{ fill: '#6b7280', fontSize: 12 }}
                        />
                        <YAxis
                            stroke="#6b7280"
                            tick={{ fill: '#6b7280', fontSize: 12 }}
                            tickFormatter={(value: number | undefined) => value !== undefined ? `$${(value / 1000).toFixed(0)}k` : '$0'}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#fff',
                                border: '1px solid #e5e7eb',
                                borderRadius: '8px',
                                color: '#000'
                            }}
                            formatter={(value: number | undefined) => {
                                if (value === undefined) return ['$0', 'Final Balance'];
                                return [`$${value.toLocaleString()}`, 'Final Balance'];
                            }}
                        />
                        <ReferenceLine
                            y={initialCapital}
                            stroke="#6b7280"
                            strokeDasharray="3 3"
                            label={{ value: 'Initial Capital', fill: '#6b7280', fontSize: 12 }}
                        />
                        <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* Percentile Table */}
            <div>
                <h3 className="text-sm font-medium text-gray-500 mb-3">Percentile Breakdown</h3>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead className="bg-gray-50 border-b border-gray-200">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                                    Percentile
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                                    Final Balance
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                                    Return %
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200">
                            {[
                                { label: '5th Percentile', value: monteCarlo.percentile_5 },
                                { label: '25th Percentile', value: monteCarlo.percentile_25 },
                                { label: '50th Percentile (Median)', value: monteCarlo.median_final_balance },
                                { label: '75th Percentile', value: monteCarlo.percentile_75 },
                                { label: '95th Percentile', value: monteCarlo.percentile_95 },
                            ].map((row, index) => (
                                <tr key={index} className="hover:bg-gray-50">
                                    <td className="px-4 py-3 text-gray-900">{row.label}</td>
                                    <td className="px-4 py-3 text-right font-medium text-gray-900">
                                        ${row.value.toLocaleString()}
                                    </td>
                                    <td className={`px-4 py-3 text-right font-medium ${row.value > initialCapital ? 'text-green-600' : 'text-red-600'
                                        }`}>
                                        {((row.value - initialCapital) / initialCapital * 100).toFixed(2)}%
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Interpretation */}
            <div className="mt-6 p-4 bg-blue-50 border border-blue-100 rounded-lg">
                <h4 className="text-sm font-medium text-blue-700 mb-2">Interpretation</h4>
                <p className="text-xs text-gray-600">
                    The Monte Carlo simulation randomizes the order of your trades 1,000 times to understand the range of possible outcomes.
                    The <strong>5th percentile</strong> represents the worst-case scenario (only 5% of simulations did worse),
                    while the <strong>95th percentile</strong> represents the best-case scenario (only 5% did better).
                </p>
            </div>
        </div>
    );
}
