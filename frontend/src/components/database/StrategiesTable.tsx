'use client'

import { useState } from 'react'
import { ArrowUpDown, ArrowUp, ArrowDown, ExternalLink } from 'lucide-react'
import { useRouter } from 'next/navigation'

interface StrategiesTableProps {
    strategies: any[]
    loading: boolean
}

type SortField = 'total_return_pct' | 'profit_factor' | 'win_rate' | 'max_drawdown_pct' | 'total_trades'
type SortDirection = 'asc' | 'desc'

export default function StrategiesTable({ strategies, loading }: StrategiesTableProps) {
    const router = useRouter()
    const [sortField, setSortField] = useState<SortField>('profit_factor')
    const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

    const handleSort = (field: SortField) => {
        if (sortField === field) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
        } else {
            setSortField(field)
            setSortDirection('desc')
        }
    }

    const sortedStrategies = [...strategies].sort((a, b) => {
        const aVal = a[sortField] || 0
        const bVal = b[sortField] || 0
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
    })

    const SortIcon = ({ field }: { field: SortField }) => {
        if (sortField !== field) return <ArrowUpDown className="w-4 h-4 text-gray-400" />
        return sortDirection === 'asc' ?
            <ArrowUp className="w-4 h-4 text-blue-600" /> :
            <ArrowDown className="w-4 h-4 text-blue-600" />
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
        )
    }

    if (strategies.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-64 text-gray-500">
                <p className="text-sm">No strategies found</p>
                <p className="text-xs mt-1">Adjust your Pass Criteria or run a new search</p>
            </div>
        )
    }

    return (
        <div className="overflow-x-auto rounded-xl border border-border/40 bg-card/10 backdrop-blur-sm shadow-2xl shadow-blue-900/5">
            <table className="w-full border-collapse">
                <thead>
                    <tr className="border-b border-border/60 bg-muted/30">
                        <th className="px-5 py-4 text-left">
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-500/50"></div>
                                <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest pl-1">Strategy ID</span>
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('total_return_pct')}
                            className="px-5 py-4 text-left cursor-pointer hover:bg-muted/50 transition-colors group"
                        >
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-green-500/50"></div>
                                <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest group-hover:text-foreground transition-colors">Return (%)</span>
                                <SortIcon field="total_return_pct" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('profit_factor')}
                            className="px-5 py-4 text-left cursor-pointer hover:bg-muted/50 transition-colors group"
                        >
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-purple-500/50"></div>
                                <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest group-hover:text-foreground transition-colors">Profit Factor</span>
                                <SortIcon field="profit_factor" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('win_rate')}
                            className="px-5 py-4 text-left cursor-pointer hover:bg-muted/50 transition-colors group"
                        >
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-400/50"></div>
                                <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest group-hover:text-foreground transition-colors">Win Rate</span>
                                <SortIcon field="win_rate" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('max_drawdown_pct')}
                            className="px-5 py-4 text-left cursor-pointer hover:bg-muted/50 transition-colors group"
                        >
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-red-500/50"></div>
                                <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest group-hover:text-foreground transition-colors">Max DD</span>
                                <SortIcon field="max_drawdown_pct" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('total_trades')}
                            className="px-5 py-4 text-left cursor-pointer hover:bg-muted/50 transition-colors group"
                        >
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-orange-400/50"></div>
                                <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest group-hover:text-foreground transition-colors">Trades</span>
                                <SortIcon field="total_trades" />
                            </div>
                        </th>
                        <th className="px-5 py-4 text-left">
                            <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest pl-1">Actions</span>
                        </th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-border/20">
                    {sortedStrategies.map((strategy, index) => (
                        <tr
                            key={strategy.id}
                            className={`
                                hover:bg-blue-500/[0.04] cursor-pointer transition-all duration-200 group
                                ${index % 2 === 0 ? 'bg-transparent' : 'bg-muted/[0.05]'}
                            `}
                            onClick={() => router.push(`/backtester/${strategy.id}`)}
                        >
                            <td className="px-5 py-4 text-xs text-muted-foreground font-black tracking-tighter group-hover:text-foreground transition-colors">
                                {strategy.id.slice(0, 12)}...
                            </td>
                            <td className={`px-5 py-4 text-sm font-black tracking-tight ${strategy.total_return_pct > 0 ? 'text-green-500' : 'text-red-500'}`}>
                                {strategy.total_return_pct > 0 ? '+' : ''}{strategy.total_return_pct?.toFixed(2)}%
                            </td>
                            <td className="px-5 py-4 text-sm text-foreground font-black tracking-tight">
                                {strategy.profit_factor?.toFixed(2)}
                            </td>
                            <td className="px-5 py-4 text-sm text-foreground font-black tracking-tight opacity-70">
                                {strategy.win_rate?.toFixed(1)}%
                            </td>
                            <td className="px-5 py-4 text-sm text-red-500/80 font-black tracking-tight">
                                -{strategy.max_drawdown_pct?.toFixed(2)}%
                            </td>
                            <td className="px-5 py-4 text-sm text-foreground/60 font-black tracking-tight">
                                {strategy.total_trades}
                            </td>
                            <td className="px-5 py-4">
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        router.push(`/backtester/${strategy.id}`)
                                    }}
                                    className="p-2 text-muted-foreground hover:text-blue-500 hover:bg-blue-500/10 rounded-lg transition-all"
                                >
                                    <ExternalLink className="w-4 h-4" />
                                </button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
