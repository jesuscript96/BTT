"use client";

import React from 'react';
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    Cell
} from 'recharts';

interface RMultipleHistogramProps {
    distribution: Record<string, number>;
}

export function RMultipleHistogram({ distribution }: RMultipleHistogramProps) {
    // Convert distribution to array and sort
    const data = Object.entries(distribution).map(([bucket, count]) => ({
        bucket,
        count,
        isPositive: bucket.startsWith('+')
    }));

    // Sort by R value
    const sortOrder = ['-3R', '-2R', '-1R', '0R', '+1R', '+2R', '+3R', '+4R', '+5R+'];
    data.sort((a, b) => sortOrder.indexOf(a.bucket) - sortOrder.indexOf(b.bucket));

    const totalTrades = data.reduce((sum, item) => sum + item.count, 0);

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">R-Multiple Distribution</h2>
                <p className="text-sm text-gray-500">
                    Frequency of trades by R-multiple outcome
                </p>
            </div>

            <ResponsiveContainer width="100%" height={350}>
                <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis
                        dataKey="bucket"
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                    />
                    <YAxis
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                        label={{ value: 'Number of Trades', angle: -90, position: 'insideLeft', fill: '#6b7280' }}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#fff',
                            border: '1px solid #e5e7eb',
                            borderRadius: '8px',
                            color: '#000'
                        }}
                        formatter={(value: number | undefined) => {
                            if (value === undefined) return [0, 'Trades'];
                            return [value, 'Trades'];
                        }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                        {data.map((entry, index) => (
                            <Cell
                                key={`cell-${index}`}
                                fill={entry.isPositive ? '#10b981' : '#ef4444'}
                            />
                        ))}
                    </Bar>
                </BarChart>
            </ResponsiveContainer>

            {/* Distribution Stats */}
            <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-gray-200">
                <div>
                    <div className="text-xs text-gray-500 mb-1">Total Trades</div>
                    <div className="text-lg font-semibold text-gray-900">
                        {totalTrades}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Winning Trades</div>
                    <div className="text-lg font-semibold text-green-600">
                        {data.filter(d => d.isPositive).reduce((sum, d) => sum + d.count, 0)}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Losing Trades</div>
                    <div className="text-lg font-semibold text-red-600">
                        {data.filter(d => !d.isPositive && d.bucket !== '0R').reduce((sum, d) => sum + d.count, 0)}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Breakeven Trades</div>
                    <div className="text-lg font-semibold text-gray-500">
                        {distribution['0R'] || 0}
                    </div>
                </div>
            </div>
        </div>
    );
}
