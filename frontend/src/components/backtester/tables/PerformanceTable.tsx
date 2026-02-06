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
        if (value === undefined) return 'text-gray-600';
        if (value > 0) return 'text-green-600 bg-green-50';
        if (value < 0) return 'text-red-600 bg-red-50';
        return 'text-gray-400';
    };

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Monthly Performance</h2>
                <p className="text-sm text-gray-500">
                    Returns in R-multiples by month and year
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200">
                        <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                                Year
                            </th>
                            {monthNames.map(month => (
                                <th key={month} className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                                    {month}
                                </th>
                            ))}
                            <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                                Total
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                        {years.map(year => {
                            const yearTotal = months.reduce((sum, month) => {
                                return sum + (monthlyData[year][month] || 0);
                            }, 0);

                            return (
                                <tr key={year} className="hover:bg-gray-50">
                                    <td className="px-4 py-3 font-medium text-gray-900">
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
            <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-gray-200">
                <div>
                    <div className="text-xs text-gray-500 mb-1">Best Month</div>
                    <div className="text-lg font-semibold text-green-600">
                        {formatR(Math.max(...Object.values(result.monthly_returns)))}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Worst Month</div>
                    <div className="text-lg font-semibold text-red-600">
                        {formatR(Math.min(...Object.values(result.monthly_returns)))}
                    </div>
                </div>
                <div>
                    <div className="text-xs text-gray-500 mb-1">Avg Monthly Return</div>
                    <div className="text-lg font-semibold text-gray-900">
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
