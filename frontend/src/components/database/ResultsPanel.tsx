'use client'

import { useState, useEffect } from 'react'
import { Download } from 'lucide-react'
import PassCriteriaFilters from './PassCriteriaFilters'
import StrategiesTable from './StrategiesTable'
import { searchStrategies, exportStrategies } from '@/lib/api'

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
    const [strategies, setStrategies] = useState<any[]>([])
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
            const data = await searchStrategies({
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

            const list = data?.strategies
            setStrategies(Array.isArray(list) ? list : [])
        } catch (error) {
            console.error('Error fetching strategies:', error)
            setStrategies([])
        } finally {
            setLoading(false)
        }
    }

    const handleExport = async () => {
        const ids = strategies.map((s: any) => s.id)
        try {
            const data = await exportStrategies(ids)
            const rows = data?.csv_data
            if (!Array.isArray(rows)) return
            const csv = rows.map((row: any[]) => row.join(',')).join('\n')
            const blob = new Blob([csv], { type: 'text/csv' })
            const url = window.URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = data?.filename ?? 'strategies.csv'
            a.click()
            window.URL.revokeObjectURL(url)
        } catch (e) {
            console.error('Export error:', e)
        }
    }

    return (
        <div className="h-full flex flex-col transition-colors duration-300">
            {/* Header */}
            <div style={{
              padding: '16px 20px',
              borderBottom: '0.5px solid var(--color-ec-border)',
              backgroundColor: 'var(--color-ec-bg-sidebar)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
            }}>
                <div>
                    <h2 style={{
                      fontFamily: 'var(--color-ec-serif)',
                      fontSize: 18,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-high)',
                      letterSpacing: '-0.3px',
                    }}>Featured Strategies</h2>
                    <p style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 10,
                      color: 'var(--color-ec-text-muted)',
                      marginTop: 3,
                    }}>
                        {strategies.length} strategies match your criteria
                    </p>
                </div>
                <button
                    onClick={handleExport}
                    disabled={strategies.length === 0}
                    style={{
                        background: 'var(--color-ec-copper)',
                        color: 'var(--color-ec-copper-text)',
                        border: 'none',
                        borderRadius: 5,
                        padding: '9px 16px',
                        fontFamily: "'General Sans', sans-serif",
                        fontSize: 11,
                        fontWeight: 700,
                        letterSpacing: '1.2px',
                        textTransform: 'uppercase',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                    }}
                >
                    <Download className="w-4 h-4" />
                    Export
                </button>
            </div>

            {/* Pass Criteria Filters */}
            <div style={{
              marginTop: 0,
              paddingTop: 14,
              paddingBottom: 14,
              paddingLeft: 20,
              paddingRight: 20,
              backgroundColor: 'var(--color-ec-bg-surface)',
              borderBottom: '0.5px solid var(--color-ec-border)',
            }}>
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
