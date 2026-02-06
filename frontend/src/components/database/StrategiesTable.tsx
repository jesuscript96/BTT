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
        <div className="overflow-x-auto">
            <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
                    <tr>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700">
                            Strategy ID
                        </th>
                        <th
                            onClick={() => handleSort('total_return_pct')}
                            className="px-4 py-3 text-left text-xs font-semibold text-gray-700 cursor-pointer hover:bg-gray-100"
                        >
                            <div className="flex items-center gap-1">
                                Total Return (%)
                                <SortIcon field="total_return_pct" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('profit_factor')}
                            className="px-4 py-3 text-left text-xs font-semibold text-gray-700 cursor-pointer hover:bg-gray-100"
                        >
                            <div className="flex items-center gap-1">
                                Profit Factor
                                <SortIcon field="profit_factor" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('win_rate')}
                            className="px-4 py-3 text-left text-xs font-semibold text-gray-700 cursor-pointer hover:bg-gray-100"
                        >
                            <div className="flex items-center gap-1">
                                Win Rate (%)
                                <SortIcon field="win_rate" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('max_drawdown_pct')}
                            className="px-4 py-3 text-left text-xs font-semibold text-gray-700 cursor-pointer hover:bg-gray-100"
                        >
                            <div className="flex items-center gap-1">
                                Max DD (%)
                                <SortIcon field="max_drawdown_pct" />
                            </div>
                        </th>
                        <th
                            onClick={() => handleSort('total_trades')}
                            className="px-4 py-3 text-left text-xs font-semibold text-gray-700 cursor-pointer hover:bg-gray-100"
                        >
                            <div className="flex items-center gap-1">
                                Trades
                                <SortIcon field="total_trades" />
                            </div>
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700">
                            Actions
                        </th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                    {sortedStrategies.map((strategy) => (
                        <tr
                            key={strategy.id}
                            className="hover:bg-gray-50 cursor-pointer transition-colors"
                            onClick={() => router.push(`/backtester/${strategy.id}`)}
                        >
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                                {strategy.id.slice(0, 8)}...
                            </td>
                            <td className={`px-4 py-3 text-sm font-semibold ${strategy.total_return_pct > 0 ? 'text-green-600' : 'text-red-600'
                                }`}>
                                {strategy.total_return_pct?.toFixed(2)}%
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-semibold">
                                {strategy.profit_factor?.toFixed(2)}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-900">
                                {strategy.win_rate?.toFixed(1)}%
                            </td>
                            <td className="px-4 py-3 text-sm text-red-600">
                                -{strategy.max_drawdown_pct?.toFixed(2)}%
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-900">
                                {strategy.total_trades}
                            </td>
                            <td className="px-4 py-3">
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        router.push(`/backtester/${strategy.id}`)
                                    }}
                                    className="text-blue-600 hover:text-blue-700"
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
