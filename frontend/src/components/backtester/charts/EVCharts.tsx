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

interface EVChartsProps {
    evByTime: Record<string, number>;
    evByDay: Record<string, number>;
}

export function EVCharts({ evByTime, evByDay }: EVChartsProps) {
    // Format time data
    const timeData = Object.entries(evByTime)
        .map(([time, ev]) => ({ time, ev }))
        .sort((a, b) => a.time.localeCompare(b.time));

    // Format day data
    const dayOrder = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
    const dayData = dayOrder
        .filter(day => evByDay[day] !== undefined)
        .map(day => ({ day, ev: evByDay[day] }));

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* EV by Entry Time */}
            <div className="bg-[#0f1419] rounded-lg border border-gray-800 p-6">
                <div className="mb-6">
                    <h3 className="text-lg font-semibold text-white mb-2">Expected Value by Entry Time</h3>
                    <p className="text-sm text-gray-400">
                        Average R-multiple by hour of entry
                    </p>
                </div>

                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={timeData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                        <XAxis
                            dataKey="time"
                            stroke="#6b7280"
                            tick={{ fill: '#9ca3af', fontSize: 11 }}
                        />
                        <YAxis
                            stroke="#6b7280"
                            tick={{ fill: '#9ca3af', fontSize: 12 }}
                            tickFormatter={(value) => `${value.toFixed(1)}R`}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#1f2937',
                                border: '1px solid #374151',
                                borderRadius: '8px',
                                color: '#fff'
                            }}
                            formatter={(value: number) => [`${value.toFixed(2)}R`, 'Avg R-Multiple']}
                        />
                        <Bar dataKey="ev" radius={[4, 4, 0, 0]}>
                            {timeData.map((entry, index) => (
                                <Cell
                                    key={`cell-${index}`}
                                    fill={entry.ev > 0 ? '#10b981' : '#ef4444'}
                                />
                            ))}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* EV by Day of Week */}
            <div className="bg-[#0f1419] rounded-lg border border-gray-800 p-6">
                <div className="mb-6">
                    <h3 className="text-lg font-semibold text-white mb-2">Expected Value by Day of Week</h3>
                    <p className="text-sm text-gray-400">
                        Average R-multiple by trading day
                    </p>
                </div>

                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={dayData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                        <XAxis
                            dataKey="day"
                            stroke="#6b7280"
                            tick={{ fill: '#9ca3af', fontSize: 11 }}
                            tickFormatter={(value) => value.substring(0, 3)}
                        />
                        <YAxis
                            stroke="#6b7280"
                            tick={{ fill: '#9ca3af', fontSize: 12 }}
                            tickFormatter={(value) => `${value.toFixed(1)}R`}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#1f2937',
                                border: '1px solid #374151',
                                borderRadius: '8px',
                                color: '#fff'
                            }}
                            formatter={(value: number) => [`${value.toFixed(2)}R`, 'Avg R-Multiple']}
                        />
                        <Bar dataKey="ev" radius={[4, 4, 0, 0]}>
                            {dayData.map((entry, index) => (
                                <Cell
                                    key={`cell-${index}`}
                                    fill={entry.ev > 0 ? '#10b981' : '#ef4444'}
                                />
                            ))}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
