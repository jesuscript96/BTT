"use client";

import React from 'react';
import { BacktestResult } from '@/types/backtest';

interface PerformanceTableProps {
    result: BacktestResult;
}

export function PerformanceTable({ result }: PerformanceTableProps) {
    // Parse monthly returns into a structured format
    const monthlyData: Record<string, Record<string, number>> = {};

    Object.entries(result.monthly_returns).forEach(([key, value]) => {
        const [year, month] = key.split('-');
        if (!monthlyData[year]) {
            monthlyData[year] = {};
        }
        monthlyData[year][month] = value;
    });

    const years = Object.keys(monthlyData).sort().reverse();
    const months = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'];
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    const formatR = (value: number | undefined) => {
        if (value === undefined) return '-';
        const sign = value > 0 ? '+' : '';
        return `${sign}${value.toFixed(2)}R`;
    };

    const getCellColor = (value: number | undefined) => {
        if (value === undefined) return 'text-muted-foreground';
        if (value > 0) return 'text-green-500 bg-green-500/10';
        if (value < 0) return 'text-red-500 bg-red-500/10';
        return 'text-muted-foreground/50';
    };

    return (
        <div className="bg-card rounded-xl border border-border p-6 transition-colors shadow-sm">
            <div className="mb-6">
                <h2 className="text-xl font-bold text-foreground mb-2">Monthly Performance</h2>
                <p className="text-sm text-muted-foreground">
                    Returns in R-multiples by month and year
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-muted/50 border-b border-border">
                        <tr>
                            <th className="px-4 py-3 text-left text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                Year
                            </th>
                            {monthNames.map(month => (
                                <th key={month} className="px-3 py-3 text-center text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                    {month}
                                </th>
                            ))}
                            <th className="px-4 py-3 text-center text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                Total
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        {years.map(year => {
                            const yearTotal = months.reduce((sum, month) => {
                                return sum + (monthlyData[year][month] || 0);
                            }, 0);

                            return (
                                <tr key={year} className="hover:bg-muted/30 transition-colors">
                                    <td className="px-4 py-3 font-bold text-foreground">
                                        {year}
                                    </td>
                                    {months.map(month => {
                                        const value = monthlyData[year][month];
                                        return (
                                            <td
                                                key={month}
                                                className={`px-3 py-3 text-center font-medium ${getCellColor(value)}`}
                                            >
                                                {formatR(value)}
                                            </td>
                                        );
                                    })}
                                    <td className={`px-4 py-3 text-center font-bold ${getCellColor(yearTotal)}`}>
                                        {formatR(yearTotal)}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {/* Summary Stats */}
            <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-border">
                <div>
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1">Best Month</div>
                    <div className="text-xl font-black text-green-500">
                        {formatR(Math.max(...Object.values(result.monthly_returns)))}
                    </div>
                </div>
                <div>
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1">Worst Month</div>
                    <div className="text-xl font-black text-red-500">
                        {formatR(Math.min(...Object.values(result.monthly_returns)))}
                    </div>
                </div>
                <div>
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1">Avg Monthly Return</div>
                    <div className="text-xl font-black text-foreground">
                        {formatR(
                            Object.values(result.monthly_returns).reduce((a, b) => a + b, 0) /
                            Object.values(result.monthly_returns).length
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
