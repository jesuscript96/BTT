'use client'

import { useState } from 'react'
import { Info } from 'lucide-react'

interface RiskManagementPanelProps {
    config: {
        stopLoss: { enabled: boolean; type: string; value: number }
        takeProfit: { enabled: boolean; type: string; value: number }
        partials: {
            enabled: boolean
            tp1: { percent: number; rMultiple: number }
            tp2: { percent: number; rMultiple: number }
            tp3: { percent: number; rMultiple: number }
        }
        trailingStop: { enabled: boolean; activation: number; trail: number }
    }
    onChange: (config: any) => void
}

export default function RiskManagementPanel({ config, onChange }: RiskManagementPanelProps) {
    const totalPartials = config.partials.tp1.percent + config.partials.tp2.percent + config.partials.tp3.percent

    return (
        <div style={{ padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Header */}
            <div>
                <h2 style={{
                  fontFamily: 'var(--color-ec-serif)',
                  fontSize: 18,
                  fontWeight: 600,
                  color: 'var(--color-ec-text-high)',
                  letterSpacing: '-0.3px',
                }}>Risk Management</h2>
                <p style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 10,
                  fontWeight: 400,
                  color: 'var(--color-ec-text-muted)',
                  marginTop: 3,
                }}>Configure exit rules</p>
            </div>

            {/* Stop Loss */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2" style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.15em',
                      color: 'var(--color-ec-text-muted)',
                    }}>
                        <span className="w-2 h-2 rounded-full bg-ec-loss"></span>
                        Stop Loss
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            stopLoss: { ...config.stopLoss, enabled: !config.stopLoss.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.stopLoss.enabled ? 'bg-ec-loss' : 'bg-muted'
                            }`}
                    >
                        <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${config.stopLoss.enabled ? 'translate-x-6' : 'translate-x-1'
                                }`}
                        />
                    </button>
                </div>

                {config.stopLoss.enabled && (
                    <div className="space-y-2 pl-4">
                        <select
                            value={config.stopLoss.type}
                            onChange={(e) => onChange({
                                ...config,
                                stopLoss: { ...config.stopLoss, type: e.target.value }
                            })}
                            className="w-full"
                            style={{
                              backgroundColor: 'var(--color-ec-bg-elevated)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 5,
                              padding: '7px 10px',
                              fontFamily: 'var(--color-ec-sans)',
                              fontSize: 12,
                              fontWeight: 500,
                              color: 'var(--color-ec-text-primary)',
                              outline: 'none',
                            }}
                        >
                            <option value="fixed">Fixed ($)</option>
                            <option value="percent">Percent (%)</option>
                            <option value="atr">ATR Multiple</option>
                            <option value="structure">Structure</option>
                        </select>

                        <input
                            type="number"
                            value={config.stopLoss.value}
                            onChange={(e) => onChange({
                                ...config,
                                stopLoss: { ...config.stopLoss, value: Number(e.target.value) }
                            })}
                            className="w-full"
                            style={{
                              backgroundColor: 'var(--color-ec-bg-elevated)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 5,
                              padding: '7px 10px',
                              fontFamily: 'var(--color-ec-sans)',
                              fontSize: 12,
                              fontWeight: 500,
                              color: 'var(--color-ec-text-primary)',
                              outline: 'none',
                            }}
                            step="0.1"
                            placeholder="Value"
                        />
                    </div>
                )}
            </div>

            {/* Take Profit */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2" style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.15em',
                      color: 'var(--color-ec-text-muted)',
                    }}>
                        <span className="w-2 h-2 rounded-full bg-ec-profit"></span>
                        Take Profit
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            takeProfit: { ...config.takeProfit, enabled: !config.takeProfit.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.takeProfit.enabled ? 'bg-ec-copper' : 'bg-muted'
                            }`}
                    >
                        <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${config.takeProfit.enabled ? 'translate-x-6' : 'translate-x-1'
                                }`}
                        />
                    </button>
                </div>

                {config.takeProfit.enabled && (
                    <div className="space-y-2 pl-4">
                        <select
                            value={config.takeProfit.type}
                            onChange={(e) => onChange({
                                ...config,
                                takeProfit: { ...config.takeProfit, type: e.target.value }
                            })}
                            className="w-full"
                            style={{
                              backgroundColor: 'var(--color-ec-bg-elevated)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 5,
                              padding: '7px 10px',
                              fontFamily: 'var(--color-ec-sans)',
                              fontSize: 12,
                              fontWeight: 500,
                              color: 'var(--color-ec-text-primary)',
                              outline: 'none',
                            }}
                        >
                            <option value="fixed">Fixed ($)</option>
                            <option value="percent">Percent (%)</option>
                            <option value="atr">ATR Multiple</option>
                            <option value="structure">Structure</option>
                        </select>

                        <input
                            type="number"
                            value={config.takeProfit.value}
                            onChange={(e) => onChange({
                                ...config,
                                takeProfit: { ...config.takeProfit, value: Number(e.target.value) }
                            })}
                            className="w-full"
                            style={{
                              backgroundColor: 'var(--color-ec-bg-elevated)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 5,
                              padding: '7px 10px',
                              fontFamily: 'var(--color-ec-sans)',
                              fontSize: 12,
                              fontWeight: 500,
                              color: 'var(--color-ec-text-primary)',
                              outline: 'none',
                            }}
                            step="0.1"
                            placeholder="Value"
                        />
                    </div>
                )}
            </div>

            {/* Partials */}
            <div className="space-y-3 pt-4 border-t border-border">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2" style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.15em',
                      color: 'var(--color-ec-text-muted)',
                    }}>
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--color-ec-copper)' }}></span>
                        Partials
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            partials: { ...config.partials, enabled: !config.partials.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.partials.enabled ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'
                            }`}
                    >
                        <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${config.partials.enabled ? 'translate-x-6' : 'translate-x-1'
                                }`}
                        />
                    </button>
                </div>

                {config.partials.enabled && (
                    <div className="space-y-4 pl-4">
                        {/* TP1 */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between text-xs">
                                <span className="font-medium text-foreground/80">TP1 - {config.partials.tp1.rMultiple}R</span>
                                <span className="text-muted-foreground">{config.partials.tp1.percent}%</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                value={config.partials.tp1.percent}
                                onChange={(e) => onChange({
                                    ...config,
                                    partials: {
                                        ...config.partials,
                                        tp1: { ...config.partials.tp1, percent: Number(e.target.value) }
                                    }
                                })}
                                style={{
                              width: '100%',
                              height: 8,
                              backgroundColor: 'var(--color-ec-bg-sidebar)',
                              borderRadius: 5,
                              appearance: 'none',
                              cursor: 'pointer',
                              accentColor: 'var(--color-ec-copper)',
                            }}
                            />
                        </div>

                        {/* TP2 */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between text-xs">
                                <span className="font-medium text-foreground/80">TP2 - {config.partials.tp2.rMultiple}R</span>
                                <span className="text-muted-foreground">{config.partials.tp2.percent}%</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                value={config.partials.tp2.percent}
                                onChange={(e) => onChange({
                                    ...config,
                                    partials: {
                                        ...config.partials,
                                        tp2: { ...config.partials.tp2, percent: Number(e.target.value) }
                                    }
                                })}
                                style={{
                              width: '100%',
                              height: 8,
                              backgroundColor: 'var(--color-ec-bg-sidebar)',
                              borderRadius: 5,
                              appearance: 'none',
                              cursor: 'pointer',
                              accentColor: 'var(--color-ec-copper)',
                            }}
                            />
                        </div>

                        {/* TP3 */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between text-xs">
                                <span className="font-medium text-foreground/80">TP3 - {config.partials.tp3.rMultiple}R</span>
                                <span className="text-muted-foreground">{config.partials.tp3.percent}%</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                value={config.partials.tp3.percent}
                                onChange={(e) => onChange({
                                    ...config,
                                    partials: {
                                        ...config.partials,
                                        tp3: { ...config.partials.tp3, percent: Number(e.target.value) }
                                    }
                                })}
                                style={{
                              width: '100%',
                              height: 8,
                              backgroundColor: 'var(--color-ec-bg-sidebar)',
                              borderRadius: 5,
                              appearance: 'none',
                              cursor: 'pointer',
                              accentColor: 'var(--color-ec-copper)',
                            }}
                            />
                        </div>

                        {/* Total */}
                        <div style={totalPartials === 100 ? {
                          padding: '12px',
                          borderRadius: 5,
                          backgroundColor: 'color-mix(in srgb, var(--color-ec-profit) 10%, transparent)',
                          border: '0.5px solid color-mix(in srgb, var(--color-ec-profit) 20%, transparent)',
                        } : {
                          padding: '12px',
                          borderRadius: 5,
                          backgroundColor: 'color-mix(in srgb, var(--color-ec-text-muted) 10%, transparent)',
                          border: '0.5px solid color-mix(in srgb, var(--color-ec-text-muted) 20%, transparent)',
                        }}>
                            <div className="flex items-center justify-between text-sm">
                                <span className="font-medium text-foreground/80">Total</span>
                                <span style={totalPartials === 100 ? { color: 'var(--color-ec-profit)', fontWeight: 600 } : { color: 'var(--color-ec-text-muted)', fontWeight: 600 }}>
                                    {totalPartials}%
                                </span>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Trailing Stop */}
            <div className="space-y-3 pt-4 border-t border-border">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2" style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.15em',
                      color: 'var(--color-ec-text-muted)',
                    }}>
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--color-ec-text-muted)' }}></span>
                        Trailing Stop
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            trailingStop: { ...config.trailingStop, enabled: !config.trailingStop.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.trailingStop.enabled ? 'bg-[var(--color-ec-text-secondary)]' : 'bg-muted'
                            }`}
                    >
                        <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${config.trailingStop.enabled ? 'translate-x-6' : 'translate-x-1'
                                }`}
                        />
                    </button>
                </div>

                {config.trailingStop.enabled && (
                    <div className="space-y-2 pl-4">
                        <div>
                            <label className="text-xs text-muted-foreground mb-1 block">Activation (R)</label>
                            <input
                                type="number"
                                value={config.trailingStop.activation}
                                onChange={(e) => onChange({
                                    ...config,
                                    trailingStop: { ...config.trailingStop, activation: Number(e.target.value) }
                                })}
                                className="w-full"
                                style={{
                                  backgroundColor: 'var(--color-ec-bg-elevated)',
                                  border: '0.5px solid var(--color-ec-border)',
                                  borderRadius: 5,
                                  padding: '7px 10px',
                                  fontFamily: 'var(--color-ec-sans)',
                                  fontSize: 12,
                                  fontWeight: 500,
                                  color: 'var(--color-ec-text-primary)',
                                  outline: 'none',
                                }}
                                step="0.1"
                                placeholder="Activation R"
                            />
                        </div>

                        <div>
                            <label className="text-xs text-muted-foreground mb-1 block">Trail Distance (R)</label>
                            <input
                                type="number"
                                value={config.trailingStop.trail}
                                onChange={(e) => onChange({
                                    ...config,
                                    trailingStop: { ...config.trailingStop, trail: Number(e.target.value) }
                                })}
                                className="w-full"
                                style={{
                                  backgroundColor: 'var(--color-ec-bg-elevated)',
                                  border: '0.5px solid var(--color-ec-border)',
                                  borderRadius: 5,
                                  padding: '7px 10px',
                                  fontFamily: 'var(--color-ec-sans)',
                                  fontSize: 12,
                                  fontWeight: 500,
                                  color: 'var(--color-ec-text-primary)',
                                  outline: 'none',
                                }}
                                step="0.1"
                                placeholder="Trail distance"
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* Equity Preview */}
            <div style={{
              backgroundColor: 'var(--color-ec-bg-elevated)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 5,
              padding: '10px 12px',
              marginTop: 8,
            }}>
                <div className="flex items-center gap-2" style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.15em',
                  color: 'var(--color-ec-text-muted)',
                  marginBottom: 8,
                }}>
                    <Info className="w-4 h-4" style={{ color: 'inherit' }} />
                    Equity Preview
                </div>
                <div className="space-y-1">
                    <div className="flex justify-between">
                        <span style={{ fontSize: 9, fontFamily: 'var(--color-ec-sans)', color: 'var(--color-ec-text-muted)' }}>Expected Value:</span>
                        <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--color-ec-sans)', color: 'var(--color-ec-text-primary)' }}>0.45R</span>
                    </div>
                    <div className="flex justify-between">
                        <span style={{ fontSize: 9, fontFamily: 'var(--color-ec-sans)', color: 'var(--color-ec-text-muted)' }}>Risk of Ruin:</span>
                        <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--color-ec-sans)', color: 'var(--color-ec-loss)' }}>2.3%</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
