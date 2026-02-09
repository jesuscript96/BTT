'use client'

import { useState, useEffect } from 'react'
import { Download } from 'lucide-react'
import PassCriteriaFilters from './PassCriteriaFilters'
import StrategiesTable from './StrategiesTable'

interface ResultsPanelProps {
    searchConfig: any
    passCriteria: {
        minTrades: number
        minWinRate: number
        minProfitFactor: number
        minExpectedValue: number
        minNetProfit: number
    }
    onPassCriteriaChange: (criteria: any) => void
}

export default function ResultsPanel({
    searchConfig,
    passCriteria,
    onPassCriteriaChange
}: ResultsPanelProps) {
    const [strategies, setStrategies] = useState([])
    const [loading, setLoading] = useState(false)

    // Fetch strategies when criteria change (debounced)
    useEffect(() => {
        const timer = setTimeout(() => {
            fetchStrategies()
        }, 300)

        return () => clearTimeout(timer)
    }, [passCriteria, searchConfig])

    const fetchStrategies = async () => {
        setLoading(true)
        try {
            const response = await fetch('http://localhost:8000/api/strategy-search/filter', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    search_mode: searchConfig.mode,
                    search_space: searchConfig.space,
                    dataset_id: searchConfig.datasetId,
                    date_from: searchConfig.dateFrom,
                    date_to: searchConfig.dateTo,
                    pass_criteria: {
                        min_trades: passCriteria.minTrades || null,
                        min_win_rate: passCriteria.minWinRate || null,
                        min_profit_factor: passCriteria.minProfitFactor || null,
                        min_expected_value: passCriteria.minExpectedValue || null,
                        min_net_profit: passCriteria.minNetProfit || null
                    }
                })
            })

            const data = await response.json()
            setStrategies(data.strategies || [])
        } catch (error) {
            console.error('Error fetching strategies:', error)
            setStrategies([])
        } finally {
            setLoading(false)
        }
    }

    const handleExport = async () => {
        const ids = strategies.map((s: any) => s.id)
        const response = await fetch('http://localhost:8000/api/strategy-search/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(ids)
        })
        const data = await response.json()

        // Convert to CSV and download
        const csv = data.csv_data.map((row: any[]) => row.join(',')).join('\n')
        const blob = new Blob([csv], { type: 'text/csv' })
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = data.filename
        a.click()
    }

    return (
        <div className="h-full flex flex-col transition-colors duration-300">
            {/* Header */}
            <div className="p-6 border-b border-border bg-card/30">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-lg font-semibold text-foreground">Featured Strategies</h2>
                        <p className="text-sm text-muted-foreground mt-1">
                            {strategies.length} strategies match your criteria
                        </p>
                    </div>
                    <button
                        onClick={handleExport}
                        disabled={strategies.length === 0}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-muted disabled:text-muted-foreground text-white rounded-lg text-sm font-medium transition-colors shadow-md"
                    >
                        <Download className="w-4 h-4" />
                        Export
                    </button>
                </div>
            </div>

            {/* Pass Criteria Filters */}
            <div className="p-6 bg-muted/30 border-b border-border">
                <PassCriteriaFilters
                    criteria={passCriteria}
                    onChange={onPassCriteriaChange}
                />
            </div>

            {/* Strategies Table */}
            <div className="flex-1 overflow-auto">
                <StrategiesTable
                    strategies={strategies}
                    loading={loading}
                />
            </div>
        </div>
    )
}
