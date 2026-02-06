"use client";

import React from 'react';

interface CorrelationMatrixProps {
    matrix: Record<string, Record<string, number>>;
    strategyNames: string[];
}

export function CorrelationMatrix({ matrix, strategyNames }: CorrelationMatrixProps) {
    const strategyIds = Object.keys(matrix);

    const getColorForCorrelation = (value: number) => {
        if (value >= 0.8) return 'bg-red-600';
        if (value >= 0.6) return 'bg-red-500';
        if (value >= 0.4) return 'bg-red-400';
        if (value >= 0.2) return 'bg-orange-400';
        if (value >= -0.2) return 'bg-gray-600';
        if (value >= -0.4) return 'bg-blue-400';
        if (value >= -0.6) return 'bg-blue-500';
        return 'bg-blue-600';
    };

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Strategy Correlation Matrix</h2>
                <p className="text-sm text-gray-500">
                    Correlation between strategy equity curves (-1 to +1)
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr>
                            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500"></th>
                            {strategyNames.map((name, index) => (
                                <th key={index} className="px-3 py-2 text-center text-xs font-medium text-gray-500">
                                    S{index + 1}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {strategyIds.map((id1, i) => (
                            <tr key={id1}>
                                <td className="px-3 py-2 text-xs font-medium text-gray-500">
                                    S{i + 1}
                                </td>
                                {strategyIds.map((id2, j) => {
                                    const correlation = matrix[id1][id2];
                                    return (
                                        <td key={id2} className="px-1 py-1">
                                            <div
                                                className={`w-16 h-12 flex items-center justify-center rounded ${getColorForCorrelation(correlation)} text-white font-medium text-xs`}
                                                title={`${strategyNames[i]} vs ${strategyNames[j]}: ${correlation.toFixed(3)}`}
                                            >
                                                {correlation.toFixed(2)}
                                            </div>
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Strategy Names Legend */}
            <div className="mt-6 pt-6 border-t border-gray-200">
                <h3 className="text-sm font-medium text-gray-500 mb-3">Strategy Names</h3>
                <div className="grid grid-cols-1 gap-2">
                    {strategyNames.map((name, index) => (
                        <div key={index} className="flex items-center gap-2">
                            <span className="text-xs font-medium text-gray-500 w-8">S{index + 1}:</span>
                            <span className="text-sm text-gray-900">{name}</span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Color Legend */}
            <div className="mt-6 pt-6 border-t border-gray-200">
                <h3 className="text-sm font-medium text-gray-500 mb-3">Correlation Scale</h3>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">-1.0</span>
                    <div className="flex-1 h-6 flex rounded overflow-hidden">
                        <div className="flex-1 bg-blue-600"></div>
                        <div className="flex-1 bg-blue-500"></div>
                        <div className="flex-1 bg-blue-400"></div>
                        <div className="flex-1 bg-gray-600"></div>
                        <div className="flex-1 bg-orange-400"></div>
                        <div className="flex-1 bg-red-400"></div>
                        <div className="flex-1 bg-red-500"></div>
                        <div className="flex-1 bg-red-600"></div>
                    </div>
                    <span className="text-xs text-gray-500">+1.0</span>
                </div>
                <div className="flex justify-between mt-2 text-xs text-gray-500">
                    <span>Negative (Diversified)</span>
                    <span>Positive (Correlated)</span>
                </div>
            </div>
        </div>
    );
}
