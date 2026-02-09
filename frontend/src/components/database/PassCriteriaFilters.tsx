'use client'

import { RotateCcw } from 'lucide-react'

interface PassCriteriaFiltersProps {
    criteria: {
        minTrades: number
        minWinRate: number
        minProfitFactor: number
        minExpectedValue: number
        minNetProfit: number
    }
    onChange: (criteria: any) => void
}

export default function PassCriteriaFilters({ criteria, onChange }: PassCriteriaFiltersProps) {
    const handleReset = () => {
        onChange({
            minTrades: 0,
            minWinRate: 0,
            minProfitFactor: 0,
            minExpectedValue: 0,
            minNetProfit: 0
        })
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">Pass Criteria</h3>
                <button
                    onClick={handleReset}
                    className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-600 transition-colors"
                >
                    <RotateCcw className="w-3 h-3" />
                    Reset
                </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
                {/* Min Trades */}
                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Min Trades</label>
                    <input
                        type="number"
                        value={criteria.minTrades}
                        onChange={(e) => onChange({ ...criteria, minTrades: Number(e.target.value) })}
                        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                        min="0"
                        placeholder="0"
                    />
                </div>

                {/* Win Rate */}
                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Win Rate (%)</label>
                    <input
                        type="number"
                        value={criteria.minWinRate}
                        onChange={(e) => onChange({ ...criteria, minWinRate: Number(e.target.value) })}
                        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                        min="0"
                        max="100"
                        step="0.1"
                        placeholder="0"
                    />
                </div>

                {/* Profit Factor */}
                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Profit Factor ($PF$)</label>
                    <input
                        type="number"
                        value={criteria.minProfitFactor}
                        onChange={(e) => onChange({ ...criteria, minProfitFactor: Number(e.target.value) })}
                        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                        min="0"
                        step="0.1"
                        placeholder="0"
                    />
                </div>

                {/* Expected Value (Avg R) */}
                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Expected Value (R)</label>
                    <input
                        type="number"
                        value={criteria.minExpectedValue}
                        onChange={(e) => onChange({ ...criteria, minExpectedValue: Number(e.target.value) })}
                        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                        step="0.01"
                        placeholder="0"
                    />
                </div>

                {/* Net Profit (Total R) */}
                <div className="space-y-2 col-span-2">
                    <label className="text-xs font-medium text-muted-foreground">Net Profit (Total R)</label>
                    <input
                        type="number"
                        value={criteria.minNetProfit}
                        onChange={(e) => onChange({ ...criteria, minNetProfit: Number(e.target.value) })}
                        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                        step="1"
                        placeholder="0"
                    />
                </div>
            </div>
        </div>
    )
}
