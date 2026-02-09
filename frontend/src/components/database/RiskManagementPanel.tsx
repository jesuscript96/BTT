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
        <div className="p-6 space-y-6">
            {/* Header */}
            <div>
                <h2 className="text-lg font-semibold text-foreground">Risk Management</h2>
                <p className="text-sm text-muted-foreground mt-1">Configure exit rules</p>
            </div>

            {/* Stop Loss */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-sm font-medium text-foreground/80">
                        <span className="w-2 h-2 rounded-full bg-red-500"></span>
                        Stop Loss
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            stopLoss: { ...config.stopLoss, enabled: !config.stopLoss.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.stopLoss.enabled ? 'bg-red-600' : 'bg-muted'
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
                            className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-red-500"
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
                            className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-red-500"
                            step="0.1"
                            placeholder="Value"
                        />
                    </div>
                )}
            </div>

            {/* Take Profit */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-sm font-medium text-foreground/80">
                        <span className="w-2 h-2 rounded-full bg-green-500"></span>
                        Take Profit
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            takeProfit: { ...config.takeProfit, enabled: !config.takeProfit.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.takeProfit.enabled ? 'bg-green-600' : 'bg-muted'
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
                            className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-green-500"
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
                            className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-green-500"
                            step="0.1"
                            placeholder="Value"
                        />
                    </div>
                )}
            </div>

            {/* Partials */}
            <div className="space-y-3 pt-4 border-t border-border">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-sm font-medium text-foreground/80">
                        <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                        Partials
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            partials: { ...config.partials, enabled: !config.partials.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.partials.enabled ? 'bg-blue-600' : 'bg-muted'
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
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
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
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
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
                                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
                            />
                        </div>

                        {/* Total */}
                        <div className={`p-3 rounded-lg ${totalPartials === 100 ? 'bg-green-500/10 border border-green-500/20' : 'bg-yellow-500/10 border border-yellow-500/20'
                            }`}>
                            <div className="flex items-center justify-between text-sm">
                                <span className="font-medium text-foreground/80">Total</span>
                                <span className={totalPartials === 100 ? 'text-green-500 font-semibold' : 'text-yellow-500 font-semibold'}>
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
                    <label className="flex items-center gap-2 text-sm font-medium text-foreground/80">
                        <span className="w-2 h-2 rounded-full bg-purple-500"></span>
                        Trailing Stop
                    </label>
                    <button
                        onClick={() => onChange({
                            ...config,
                            trailingStop: { ...config.trailingStop, enabled: !config.trailingStop.enabled }
                        })}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.trailingStop.enabled ? 'bg-purple-600' : 'bg-muted'
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
                                className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-purple-500"
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
                                className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-purple-500"
                                step="0.1"
                                placeholder="Trail distance"
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* Equity Preview */}
            <div className="p-4 bg-muted border border-border rounded-lg space-y-2 mt-6">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Info className="w-4 h-4" />
                    Equity Preview
                </div>
                <div className="space-y-1 text-xs text-muted-foreground">
                    <div className="flex justify-between">
                        <span>Expected Value:</span>
                        <span className="font-semibold text-foreground">0.45R</span>
                    </div>
                    <div className="flex justify-between">
                        <span>Risk of Ruin:</span>
                        <span className="font-semibold text-red-500">2.3%</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
