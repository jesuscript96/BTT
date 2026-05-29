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
                <h3 style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.12em',
                  color: 'var(--color-ec-text-muted)',
                }}>Pass Criteria</h3>
                <button
                    onClick={handleReset}
                    className="flex items-center gap-1"
                    style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 10,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-muted)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      transition: 'color 150ms ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-ec-copper)')}
                    onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-ec-text-muted)')}
                >
                    <RotateCcw className="w-3 h-3" />
                    Reset
                </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
                {/* Min Trades */}
                <div className="space-y-2">
                    <label style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.12em',
                      color: 'var(--color-ec-text-muted)',
                      marginBottom: 5,
                      display: 'block',
                    }}>Min Trades</label>
                    <input
                        type="number"
                        value={criteria.minTrades}
                        onChange={(e) => onChange({ ...criteria, minTrades: Number(e.target.value) })}
                        className="w-full"
                    style={{
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '6px 10px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      outline: 'none',
                    }}
                        min="0"
                        placeholder="0"
                    />
                </div>

                {/* Win Rate */}
                <div className="space-y-2">
                    <label style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.12em',
                      color: 'var(--color-ec-text-muted)',
                      marginBottom: 5,
                      display: 'block',
                    }}>Win Rate (%)</label>
                    <input
                        type="number"
                        value={criteria.minWinRate}
                        onChange={(e) => onChange({ ...criteria, minWinRate: Number(e.target.value) })}
                        className="w-full"
                    style={{
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '6px 10px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      outline: 'none',
                    }}
                        min="0"
                        max="100"
                        step="0.1"
                        placeholder="0"
                    />
                </div>

                {/* Profit Factor */}
                <div className="space-y-2">
                    <label style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.12em',
                      color: 'var(--color-ec-text-muted)',
                      marginBottom: 5,
                      display: 'block',
                    }}>Profit Factor ($PF$)</label>
                    <input
                        type="number"
                        value={criteria.minProfitFactor}
                        onChange={(e) => onChange({ ...criteria, minProfitFactor: Number(e.target.value) })}
                        className="w-full"
                    style={{
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '6px 10px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      outline: 'none',
                    }}
                        min="0"
                        step="0.1"
                        placeholder="0"
                    />
                </div>

                {/* Expected Value (Avg R) */}
                <div className="space-y-2">
                    <label style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.12em',
                      color: 'var(--color-ec-text-muted)',
                      marginBottom: 5,
                      display: 'block',
                    }}>Expected Value (R)</label>
                    <input
                        type="number"
                        value={criteria.minExpectedValue}
                        onChange={(e) => onChange({ ...criteria, minExpectedValue: Number(e.target.value) })}
                        className="w-full"
                    style={{
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '6px 10px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      outline: 'none',
                    }}
                        step="0.01"
                        placeholder="0"
                    />
                </div>

                {/* Net Profit (Total R) */}
                <div className="space-y-2 col-span-2">
                    <label style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.12em',
                      color: 'var(--color-ec-text-muted)',
                      marginBottom: 5,
                      display: 'block',
                    }}>Net Profit (Total R)</label>
                    <input
                        type="number"
                        value={criteria.minNetProfit}
                        onChange={(e) => onChange({ ...criteria, minNetProfit: Number(e.target.value) })}
                        className="w-full"
                    style={{
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '6px 10px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      outline: 'none',
                    }}
                        step="1"
                        placeholder="0"
                    />
                </div>
            </div>
        </div>
    )
}
