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
            <div className="bg-card rounded-xl border border-border p-6 transition-colors shadow-sm">
                <div className="mb-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Expected Value by Entry Time</h3>
                    <p className="text-sm text-gray-500">
                        Average R-multiple by hour of entry
                    </p>
                </div>

                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={timeData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(156, 163, 175, 0.1)" vertical={false} />
                        <XAxis
                            dataKey="time"
                            stroke="rgba(156, 163, 175, 0.5)"
                            tick={{ fill: 'rgba(156, 163, 175, 0.8)', fontSize: 10, fontWeight: 700 }}
                            axisLine={false}
                            tickLine={false}
                        />
                        <YAxis
                            stroke="rgba(156, 163, 175, 0.5)"
                            tick={{ fill: 'rgba(156, 163, 175, 0.8)', fontSize: 10, fontWeight: 700 }}
                            axisLine={false}
                            tickLine={false}
                            tickFormatter={(value: number | undefined) => value !== undefined ? `${value.toFixed(1)}R` : '0R'}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: 'var(--card)',
                                border: '1px solid var(--border)',
                                borderRadius: '12px',
                                color: 'var(--foreground)',
                                fontSize: '11px',
                                fontWeight: 'bold',
                                boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
                                backdropFilter: 'blur(8px)'
                            }}
                            itemStyle={{ color: 'var(--foreground)' }}
                            formatter={(value: number | undefined) => {
                                if (value === undefined) return ['0R', 'Avg R-Multiple'];
                                return [`${value.toFixed(2)}R`, 'Avg R-Multiple'];
                            }}
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
            <div className="bg-card rounded-xl border border-border p-6 transition-colors shadow-sm">
                <div className="mb-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Expected Value by Day of Week</h3>
                    <p className="text-sm text-gray-500">
                        Average R-multiple by trading day
                    </p>
                </div>

                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={dayData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(156, 163, 175, 0.1)" vertical={false} />
                        <XAxis
                            dataKey="day"
                            stroke="rgba(156, 163, 175, 0.5)"
                            tick={{ fill: 'rgba(156, 163, 175, 0.8)', fontSize: 10, fontWeight: 700 }}
                            tickFormatter={(value) => value.substring(0, 3)}
                            axisLine={false}
                            tickLine={false}
                        />
                        <YAxis
                            stroke="rgba(156, 163, 175, 0.5)"
                            tick={{ fill: 'rgba(156, 163, 175, 0.8)', fontSize: 10, fontWeight: 700 }}
                            axisLine={false}
                            tickLine={false}
                            tickFormatter={(value: number | undefined) => value !== undefined ? `${value.toFixed(1)}R` : '0R'}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: 'var(--card)',
                                border: '1px solid var(--border)',
                                borderRadius: '12px',
                                color: 'var(--foreground)',
                                fontSize: '11px',
                                fontWeight: 'bold',
                                boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
                                backdropFilter: 'blur(8px)'
                            }}
                            itemStyle={{ color: 'var(--foreground)' }}
                            formatter={(value: number | undefined) => {
                                if (value === undefined) return ['0R', 'Avg R-Multiple'];
                                return [`${value.toFixed(2)}R`, 'Avg R-Multiple'];
                            }}
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
