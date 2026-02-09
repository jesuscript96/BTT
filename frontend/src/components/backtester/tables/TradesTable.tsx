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
                        className="absolute top-4 right-4 z-10 p-2 bg-card rounded-full shadow-lg border border-border hover:bg-muted text-muted-foreground transition-all"
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

            <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden transition-colors">
                <div className="p-6 border-b border-border flex justify-between items-center bg-card/50 backdrop-blur-sm">
                    <div>
                        <h2 className="text-xl font-bold text-foreground mb-1">Trades Log</h2>
                        <p className="text-sm text-muted-foreground">
                            Detailed record of {trades.length} trades. Click 📈 to view chart.
                        </p>
                    </div>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-muted/50 border-b border-border">
                            <tr>
                                <th className="px-4 py-3 text-center text-[10px] font-black text-muted-foreground uppercase tracking-widest w-10">
                                    #
                                </th>
                                <th className="px-4 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                                    <button
                                        onClick={() => handleSort('entry_time')}
                                        className="flex items-center gap-1 hover:text-foreground transition-colors"
                                    >
                                        Date/Time
                                        <ArrowUpDown className="w-3 h-3" />
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                                    <button
                                        onClick={() => handleSort('ticker')}
                                        className="flex items-center gap-1 hover:text-foreground transition-colors"
                                    >
                                        Ticker
                                        <ArrowUpDown className="w-3 h-3" />
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-right text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                                    Entry
                                </th>
                                <th className="px-4 py-3 text-right text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                                    Exit
                                </th>
                                <th className="px-4 py-3 text-right text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                                    <button
                                        onClick={() => handleSort('r_multiple')}
                                        className="flex items-center gap-1 hover:text-foreground transition-colors ml-auto"
                                    >
                                        R-Multiple
                                        <ArrowUpDown className="w-3 h-3" />
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                                    Reason
                                </th>
                                <th className="px-4 py-3 text-center text-[10px] font-black text-muted-foreground uppercase tracking-widest w-16">
                                    Graph
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border/50">
                            {paginatedTrades.map((trade, index) => (
                                <tr
                                    key={trade.id}
                                    className={`hover:bg-blue-500/5 transition-colors group ${selectedTrade?.id === trade.id ? 'bg-blue-500/10 ring-1 ring-inset ring-blue-500/20' :
                                        index % 2 === 0 ? 'bg-muted/10' : 'bg-transparent'
                                        }`}
                                >
                                    <td className="px-4 py-3 text-[10px] font-mono text-muted-foreground/30 text-center">
                                        {startIndex + index + 1}
                                    </td>
                                    <td className="px-4 py-3 text-xs text-muted-foreground font-medium whitespace-nowrap">
                                        {new Date(trade.entry_time).toLocaleString('en-US', {
                                            month: 'short',
                                            day: 'numeric',
                                            hour: '2-digit',
                                            minute: '2-digit'
                                        })}
                                    </td>
                                    <td className="px-4 py-3 text-sm font-black text-foreground">
                                        {trade.ticker}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-right text-foreground font-mono">
                                        ${trade.entry_price.toFixed(2)}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-right text-foreground font-mono">
                                        ${trade.exit_price?.toFixed(2) || '-'}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-right font-black tabular-nums">
                                        <span className={
                                            trade.r_multiple && trade.r_multiple > 0
                                                ? 'text-green-500'
                                                : trade.r_multiple && trade.r_multiple < 0
                                                    ? 'text-red-500'
                                                    : 'text-muted-foreground/50'
                                        }>
                                            {trade.r_multiple ? `${trade.r_multiple > 0 ? '+' : ''}${trade.r_multiple.toFixed(2)}R` : '-'}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-sm">
                                        <span className={`inline-flex px-2 py-0.5 text-[9px] font-black rounded uppercase tracking-widest ${trade.exit_reason === 'TP' ? 'bg-green-500/10 text-green-500 border border-green-500/20' :
                                            trade.exit_reason === 'SL' ? 'bg-red-500/10 text-red-500 border border-red-500/20' :
                                                trade.exit_reason === 'TIME' ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20' :
                                                    'bg-muted text-muted-foreground border border-border'
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
                <div className="p-4 border-t border-border flex items-center justify-between bg-muted/30">
                    <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">
                        Showing {startIndex + 1}-{Math.min(startIndex + tradesPerPage, trades.length)} of {trades.length}
                    </div>
                    <div className="flex gap-2 items-center">
                        <button
                            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                            disabled={currentPage === 1}
                            className="p-2 transition-all bg-background border border-border rounded-lg text-muted-foreground disabled:opacity-30 disabled:cursor-not-allowed hover:border-blue-500 hover:text-blue-500 shadow-sm"
                        >
                            <span className="sr-only">Previous</span>
                            &larr;
                        </button>
                        <span className="px-4 text-[11px] font-black text-foreground tabular-nums">
                            {currentPage} / {totalPages}
                        </span>
                        <button
                            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                            disabled={currentPage === totalPages}
                            className="p-2 transition-all bg-background border border-border rounded-lg text-muted-foreground disabled:opacity-30 disabled:cursor-not-allowed hover:border-blue-500 hover:text-blue-500 shadow-sm"
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
