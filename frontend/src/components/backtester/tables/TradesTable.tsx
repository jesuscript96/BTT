"use client";

import React, { useState } from 'react';
import { Trade } from '@/types/backtest';
import { ArrowUpDown } from 'lucide-react';

interface TradesTableProps {
    trades: Trade[];
}

type SortField = 'entry_time' | 'ticker' | 'r_multiple' | 'exit_reason';
type SortDirection = 'asc' | 'desc';

export function TradesTable({ trades }: TradesTableProps) {
    const [sortField, setSortField] = useState<SortField>('entry_time');
    const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
    const [currentPage, setCurrentPage] = useState(1);
    const tradesPerPage = 50;

    // Sort trades
    const sortedTrades = [...trades].sort((a, b) => {
        let aVal, bVal;

        switch (sortField) {
            case 'entry_time':
                aVal = new Date(a.entry_time).getTime();
                bVal = new Date(b.entry_time).getTime();
                break;
            case 'ticker':
                aVal = a.ticker;
                bVal = b.ticker;
                break;
            case 'r_multiple':
                aVal = a.r_multiple || 0;
                bVal = b.r_multiple || 0;
                break;
            case 'exit_reason':
                aVal = a.exit_reason || '';
                bVal = b.exit_reason || '';
                break;
            default:
                return 0;
        }

        if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    // Paginate
    const totalPages = Math.ceil(sortedTrades.length / tradesPerPage);
    const startIndex = (currentPage - 1) * tradesPerPage;
    const paginatedTrades = sortedTrades.slice(startIndex, startIndex + tradesPerPage);

    const handleSort = (field: SortField) => {
        if (sortField === field) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
        } else {
            setSortField(field);
            setSortDirection('desc');
        }
    };

    return (
        <div className="bg-white rounded-lg border border-gray-200">
            <div className="p-6 border-b border-gray-200">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Trades Log</h2>
                <p className="text-sm text-gray-500">
                    Detailed record of all {trades.length} trades
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead className="bg-gray-50 border-b border-gray-200">
                        <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('entry_time')}
                                    className="flex items-center gap-1 hover:text-gray-900"
                                >
                                    Date/Time
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('ticker')}
                                    className="flex items-center gap-1 hover:text-gray-900"
                                >
                                    Ticker
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Entry
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Exit
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('r_multiple')}
                                    className="flex items-center gap-1 hover:text-gray-900 ml-auto"
                                >
                                    R-Multiple
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Fees
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('exit_reason')}
                                    className="flex items-center gap-1 hover:text-gray-900"
                                >
                                    Reason
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Strategy
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                        {paginatedTrades.map((trade, index) => (
                            <tr
                                key={trade.id}
                                className={index % 2 === 0 ? 'bg-gray-50' : 'bg-white'}
                            >
                                <td className="px-4 py-3 text-sm text-gray-700">
                                    {new Date(trade.entry_time).toLocaleString()}
                                </td>
                                <td className="px-4 py-3 text-sm font-medium text-gray-900">
                                    {trade.ticker}
                                </td>
                                <td className="px-4 py-3 text-sm text-right text-gray-700">
                                    ${trade.entry_price.toFixed(2)}
                                </td>
                                <td className="px-4 py-3 text-sm text-right text-gray-700">
                                    ${trade.exit_price?.toFixed(2) || '-'}
                                </td>
                                <td className="px-4 py-3 text-sm text-right font-medium">
                                    <span className={
                                        trade.r_multiple && trade.r_multiple > 0
                                            ? 'text-green-600'
                                            : trade.r_multiple && trade.r_multiple < 0
                                                ? 'text-red-600'
                                                : 'text-gray-500'
                                    }>
                                        {trade.r_multiple ? `${trade.r_multiple > 0 ? '+' : ''}${trade.r_multiple.toFixed(2)}R` : '-'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-sm text-right text-gray-500">
                                    ${trade.fees.toFixed(2)}
                                </td>
                                <td className="px-4 py-3 text-sm">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded ${trade.exit_reason === 'TP' ? 'bg-green-100 text-green-700' :
                                        trade.exit_reason === 'SL' ? 'bg-red-100 text-red-700' :
                                            trade.exit_reason === 'TIME' ? 'bg-yellow-100 text-yellow-700' :
                                                'bg-gray-100 text-gray-600'
                                        }`}>
                                        {trade.exit_reason || '-'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-500 truncate max-w-xs">
                                    {trade.strategy_name}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
            <div className="p-4 border-t border-gray-200 flex items-center justify-between">
                <div className="text-sm text-gray-400">
                    Showing {startIndex + 1} to {Math.min(startIndex + tradesPerPage, trades.length)} of {trades.length} trades
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                        disabled={currentPage === 1}
                        className="px-3 py-1 bg-white border border-gray-300 rounded text-sm text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
                    >
                        Previous
                    </button>
                    <span className="px-3 py-1 text-sm text-gray-500">
                        Page {currentPage} of {totalPages}
                    </span>
                    <button
                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                        disabled={currentPage === totalPages}
                        className="px-3 py-1 bg-white border border-gray-300 rounded text-sm text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
                    >
                        Next
                    </button>
                </div>
            </div>
        </div>
    );
}
