"use client";

import React, { useState } from 'react';
import { Trade } from '@/types/backtest';
import { ArrowUpDown, ChartBar as ChartIcon, X } from 'lucide-react';
import { CandlestickViewer } from '../charts/CandlestickViewer';

interface TradesTableProps {
    trades: Trade[];
}

type SortField = 'entry_time' | 'ticker' | 'r_multiple' | 'exit_reason';
type SortDirection = 'asc' | 'desc';

export function TradesTable({ trades }: TradesTableProps) {
    const [sortField, setSortField] = useState<SortField>('entry_time');
    const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
    const [currentPage, setCurrentPage] = useState(1);
    const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
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
        <div className="space-y-6">
            {/* Candlestick Viewer (Conditionally Rendered) */}
            {selectedTrade && (
                <div className="relative">
                    <button
                        onClick={() => setSelectedTrade(null)}
                        className="absolute top-4 right-4 z-10 p-2 bg-white rounded-full shadow-md border border-gray-200 hover:bg-gray-50 text-gray-500"
                        title="Close Chart"
                    >
                        <X className="w-5 h-5" />
                    </button>
                    <CandlestickViewer
                        ticker={selectedTrade.ticker}
                        dateFrom={selectedTrade.entry_time}
                        dateTo={selectedTrade.exit_time || selectedTrade.entry_time}
                        trades={trades} // Pass all trades to show multiple markers if nearby
                    />
                </div>
            )}

            <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
                <div className="p-6 border-b border-gray-200 flex justify-between items-center bg-white">
                    <div>
                        <h2 className="text-xl font-bold text-gray-900 mb-1">Trades Log</h2>
                        <p className="text-sm text-gray-500">
                            Detailed record of {trades.length} trades. Click 📈 to view chart.
                        </p>
                    </div>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-gray-50 border-b border-gray-200">
                            <tr>
                                <th className="px-4 py-3 text-center text-xs font-bold text-gray-400 uppercase tracking-wider w-10">
                                    #
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    <button
                                        onClick={() => handleSort('entry_time')}
                                        className="flex items-center gap-1 hover:text-gray-900"
                                    >
                                        Date/Time
                                        <ArrowUpDown className="w-3 h-3" />
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    <button
                                        onClick={() => handleSort('ticker')}
                                        className="flex items-center gap-1 hover:text-gray-900"
                                    >
                                        Ticker
                                        <ArrowUpDown className="w-3 h-3" />
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    Entry
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    Exit
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    <button
                                        onClick={() => handleSort('r_multiple')}
                                        className="flex items-center gap-1 hover:text-gray-900 ml-auto"
                                    >
                                        R-Multiple
                                        <ArrowUpDown className="w-3 h-3" />
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    Reason
                                </th>
                                <th className="px-4 py-3 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    Chart
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100 italic-rows">
                            {paginatedTrades.map((trade, index) => (
                                <tr
                                    key={trade.id}
                                    className={`hover:bg-blue-50/30 transition-colors group ${selectedTrade?.id === trade.id ? 'bg-blue-50 ring-1 ring-inset ring-blue-100' :
                                            index % 2 === 0 ? 'bg-gray-50/30' : 'bg-white'
                                        }`}
                                >
                                    <td className="px-4 py-3 text-[10px] font-mono text-gray-300 text-center">
                                        {startIndex + index + 1}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-600 font-medium whitespace-nowrap">
                                        {new Date(trade.entry_time).toLocaleString('en-US', {
                                            month: 'short',
                                            day: 'numeric',
                                            hour: '2-digit',
                                            minute: '2-digit'
                                        })}
                                    </td>
                                    <td className="px-4 py-3 text-sm font-bold text-gray-900">
                                        {trade.ticker}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-right text-gray-700 font-mono">
                                        ${trade.entry_price.toFixed(2)}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-right text-gray-700 font-mono">
                                        ${trade.exit_price?.toFixed(2) || '-'}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-right font-black">
                                        <span className={
                                            trade.r_multiple && trade.r_multiple > 0
                                                ? 'text-teal-600'
                                                : trade.r_multiple && trade.r_multiple < 0
                                                    ? 'text-rose-600'
                                                    : 'text-gray-400'
                                        }>
                                            {trade.r_multiple ? `${trade.r_multiple > 0 ? '+' : ''}${trade.r_multiple.toFixed(2)}R` : '-'}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-sm">
                                        <span className={`inline-flex px-2 py-0.5 text-[10px] font-bold rounded uppercase tracking-tighter ${trade.exit_reason === 'TP' ? 'bg-teal-100 text-teal-700' :
                                                trade.exit_reason === 'SL' ? 'bg-rose-100 text-rose-700' :
                                                    trade.exit_reason === 'TIME' ? 'bg-amber-100 text-amber-700' :
                                                        'bg-gray-100 text-gray-600'
                                            }`}>
                                            {trade.exit_reason || '-'}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        <button
                                            onClick={() => setSelectedTrade(trade)}
                                            className={`p-1.5 rounded-lg transition-all ${selectedTrade?.id === trade.id
                                                    ? 'bg-blue-600 text-white shadow-sm'
                                                    : 'text-gray-400 hover:bg-white hover:text-blue-600 hover:shadow-sm border border-transparent hover:border-gray-200'
                                                }`}
                                        >
                                            <ChartIcon className="w-4 h-4" />
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Pagination */}
                <div className="p-4 border-t border-gray-100 flex items-center justify-between bg-gray-50/50">
                    <div className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
                        Showing {startIndex + 1} - {Math.min(startIndex + tradesPerPage, trades.length)} of {trades.length}
                    </div>
                    <div className="flex gap-2 items-center">
                        <button
                            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                            disabled={currentPage === 1}
                            className="p-2 transition-all bg-white border border-gray-200 rounded-lg text-gray-600 disabled:opacity-30 disabled:cursor-not-allowed hover:border-blue-300 hover:text-blue-600 shadow-sm"
                        >
                            <X className="w-4 h-4 rotate-180" /> {/* Using X as a placeholder for arrow if lucide not available but it is */}
                            {/* Actually I'll use text if unsure but Lucide is there */}
                            <span className="sr-only">Previous</span>
                            &larr;
                        </button>
                        <span className="px-4 text-sm font-bold text-gray-700">
                            {currentPage} / {totalPages}
                        </span>
                        <button
                            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                            disabled={currentPage === totalPages}
                            className="p-2 transition-all bg-white border border-gray-200 rounded-lg text-gray-600 disabled:opacity-30 disabled:cursor-not-allowed hover:border-blue-300 hover:text-blue-600 shadow-sm"
                        >
                            <span className="sr-only">Next</span>
                            &rarr;
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
