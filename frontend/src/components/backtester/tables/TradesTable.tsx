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
        <div className="bg-[#0f1419] rounded-lg border border-gray-800">
            <div className="p-6 border-b border-gray-800">
                <h2 className="text-xl font-semibold text-white mb-2">Trades Log</h2>
                <p className="text-sm text-gray-400">
                    Detailed record of all {trades.length} trades
                </p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead className="bg-[#1a1f2e] border-b border-gray-800">
                        <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('entry_time')}
                                    className="flex items-center gap-1 hover:text-white"
                                >
                                    Date/Time
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('ticker')}
                                    className="flex items-center gap-1 hover:text-white"
                                >
                                    Ticker
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                                Entry
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                                Exit
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('r_multiple')}
                                    className="flex items-center gap-1 hover:text-white ml-auto"
                                >
                                    R-Multiple
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                                Fees
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                                <button
                                    onClick={() => handleSort('exit_reason')}
                                    className="flex items-center gap-1 hover:text-white"
                                >
                                    Reason
                                    <ArrowUpDown className="w-3 h-3" />
                                </button>
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                                Strategy
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                        {paginatedTrades.map((trade, index) => (
                            <tr
                                key={trade.id}
                                className={index % 2 === 0 ? 'bg-[#0a0e1a]' : 'bg-[#0f1419]'}
                            >
                                <td className="px-4 py-3 text-sm text-gray-300">
                                    {new Date(trade.entry_time).toLocaleString()}
                                </td>
                                <td className="px-4 py-3 text-sm font-medium text-white">
                                    {trade.ticker}
                                </td>
                                <td className="px-4 py-3 text-sm text-right text-gray-300">
                                    ${trade.entry_price.toFixed(2)}
                                </td>
                                <td className="px-4 py-3 text-sm text-right text-gray-300">
                                    ${trade.exit_price?.toFixed(2) || '-'}
                                </td>
                                <td className="px-4 py-3 text-sm text-right font-medium">
                                    <span className={
                                        trade.r_multiple && trade.r_multiple > 0
                                            ? 'text-green-400'
                                            : trade.r_multiple && trade.r_multiple < 0
                                                ? 'text-red-400'
                                                : 'text-gray-400'
                                    }>
                                        {trade.r_multiple ? `${trade.r_multiple > 0 ? '+' : ''}${trade.r_multiple.toFixed(2)}R` : '-'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-sm text-right text-gray-400">
                                    ${trade.fees.toFixed(2)}
                                </td>
                                <td className="px-4 py-3 text-sm">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded ${trade.exit_reason === 'TP' ? 'bg-green-900/30 text-green-400' :
                                            trade.exit_reason === 'SL' ? 'bg-red-900/30 text-red-400' :
                                                trade.exit_reason === 'TIME' ? 'bg-yellow-900/30 text-yellow-400' :
                                                    'bg-gray-800 text-gray-400'
                                        }`}>
                                        {trade.exit_reason || '-'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-400 truncate max-w-xs">
                                    {trade.strategy_name}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
            <div className="p-4 border-t border-gray-800 flex items-center justify-between">
                <div className="text-sm text-gray-400">
                    Showing {startIndex + 1} to {Math.min(startIndex + tradesPerPage, trades.length)} of {trades.length} trades
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                        disabled={currentPage === 1}
                        className="px-3 py-1 bg-[#1a1f2e] border border-gray-700 rounded text-sm text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#252a3a]"
                    >
                        Previous
                    </button>
                    <span className="px-3 py-1 text-sm text-gray-400">
                        Page {currentPage} of {totalPages}
                    </span>
                    <button
                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                        disabled={currentPage === totalPages}
                        className="px-3 py-1 bg-[#1a1f2e] border border-gray-700 rounded text-sm text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#252a3a]"
                    >
                        Next
                    </button>
                </div>
            </div>
        </div>
    );
}
