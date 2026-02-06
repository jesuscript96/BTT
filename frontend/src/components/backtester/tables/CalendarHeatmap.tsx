"use client";

import React from 'react';
import { BacktestResult, Trade } from '@/types/backtest';

interface CalendarHeatmapProps {
    result: BacktestResult;
}

export function CalendarHeatmap({ result }: CalendarHeatmapProps) {
    // Group trades by date
    const tradesByDate: Record<string, { trades: number; totalR: number }> = {};

    result.trades.forEach(trade => {
        const date = new Date(trade.entry_time).toISOString().split('T')[0];
        if (!tradesByDate[date]) {
            tradesByDate[date] = { trades: 0, totalR: 0 };
        }
        tradesByDate[date].trades += 1;
        tradesByDate[date].totalR += trade.r_multiple || 0;
    });

    // Get date range
    const dates = Object.keys(tradesByDate).sort();
    if (dates.length === 0) {
        return (
            <div className="bg-white rounded-lg border border-gray-200 p-6">
                <p className="text-gray-500">No trade data available</p>
            </div>
        );
    }

    const startDate = new Date(dates[0]);
    const endDate = new Date(dates[dates.length - 1]);

    // Generate calendar grid
    const weeks: Date[][] = [];
    let currentDate = new Date(startDate);
    currentDate.setDate(currentDate.getDate() - currentDate.getDay()); // Start from Sunday

    while (currentDate <= endDate) {
        const week: Date[] = [];
        for (let i = 0; i < 7; i++) {
            week.push(new Date(currentDate));
            currentDate.setDate(currentDate.getDate() + 1);
        }
        weeks.push(week);
    }

    const getColorIntensity = (totalR: number) => {
        if (totalR > 5) return 'bg-green-600';
        if (totalR > 2) return 'bg-green-500';
        if (totalR > 0) return 'bg-green-400';
        if (totalR === 0) return 'bg-gray-700';
        if (totalR > -2) return 'bg-red-400';
        if (totalR > -5) return 'bg-red-500';
        return 'bg-red-600';
    };

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Calendar Heatmap</h2>
                <p className="text-sm text-gray-500">
                    Daily P&L visualization
                </p>
            </div>

            <div className="overflow-x-auto">
                <div className="inline-block min-w-full">
                    {/* Day labels */}
                    <div className="flex mb-2">
                        <div className="w-12"></div>
                        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
                            <div key={day} className="w-10 text-xs text-gray-500 text-center">
                                {day}
                            </div>
                        ))}
                    </div>

                    {/* Calendar grid */}
                    {weeks.map((week, weekIndex) => (
                        <div key={weekIndex} className="flex mb-1">
                            {/* Week number */}
                            <div className="w-12 text-xs text-gray-500 flex items-center">
                                {weekIndex === 0 || week[0].getDate() <= 7 ? week[0].toLocaleDateString('en-US', { month: 'short' }) : ''}
                            </div>

                            {week.map((date, dayIndex) => {
                                const dateStr = date.toISOString().split('T')[0];
                                const dayData = tradesByDate[dateStr];
                                const isInRange = date >= startDate && date <= endDate;

                                return (
                                    <div
                                        key={dayIndex}
                                        className="relative group"
                                    >
                                        <div
                                            className={`w-9 h-9 m-0.5 rounded ${dayData
                                                ? getColorIntensity(dayData.totalR)
                                                : isInRange
                                                    ? 'bg-gray-100'
                                                    : 'bg-transparent'
                                                } ${dayData ? 'cursor-pointer' : ''}`}
                                            title={dayData ? `${dateStr}: ${dayData.trades} trades, ${dayData.totalR.toFixed(2)}R` : ''}
                                        />

                                        {/* Tooltip */}
                                        {dayData && (
                                            <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 hidden group-hover:block z-10">
                                                <div className="bg-white text-gray-900 text-xs rounded py-2 px-3 whitespace-nowrap border border-gray-200 shadow-lg">
                                                    <div className="font-medium">{dateStr}</div>
                                                    <div className="text-gray-500">{dayData.trades} trades</div>
                                                    <div className={dayData.totalR > 0 ? 'text-green-600' : 'text-red-600'}>
                                                        {dayData.totalR > 0 ? '+' : ''}{dayData.totalR.toFixed(2)}R
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    ))}
                </div>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-2 mt-6 pt-6 border-t border-gray-200">
                <span className="text-xs text-gray-500">Less</span>
                <div className="w-4 h-4 bg-gray-100 rounded"></div>
                <div className="w-4 h-4 bg-red-600 rounded"></div>
                <div className="w-4 h-4 bg-red-400 rounded"></div>
                <div className="w-4 h-4 bg-green-400 rounded"></div>
                <div className="w-4 h-4 bg-green-600 rounded"></div>
                <span className="text-xs text-gray-500">More</span>
            </div>
        </div>
    );
}
