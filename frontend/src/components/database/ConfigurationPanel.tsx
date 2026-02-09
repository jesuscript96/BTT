'use client'

import { useState } from 'react'
import { Calendar, Play, Square, Save, FolderOpen } from 'lucide-react'

interface ConfigurationPanelProps {
    config: {
        mode: string
        space: string
        datasetId: string
        dateFrom: string
        dateTo: string
    }
    onChange: (config: any) => void
}

export default function ConfigurationPanel({ config, onChange }: ConfigurationPanelProps) {
    const [isRunning, setIsRunning] = useState(false)
    const [savedStrategiesCount, setCount] = useState(0)

    const handleRunSearch = () => {
        setIsRunning(true)
        // Trigger search logic
        setTimeout(() => setIsRunning(false), 2000)
    }

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div>
                <h2 className="text-lg font-semibold text-foreground">Strategy Searcher</h2>
                <p className="text-sm text-muted-foreground mt-1">Configure search parameters</p>
            </div>

            {/* Mode & Space */}
            <div className="space-y-3">
                <label className="flex items-center gap-2 text-sm font-medium text-foreground/80">
                    <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                    Mode & Space
                </label>

                <div className="space-y-2">
                    <select
                        value={config.mode}
                        onChange={(e) => onChange({ ...config, mode: e.target.value })}
                        className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                    >
                        <option>Consecutive Red</option>
                        <option>Gap & Fade</option>
                        <option>VWAP Rejection</option>
                        <option>High of Day Break</option>
                    </select>

                    <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-foreground">Consecutive red ==</span>
                        <input
                            type="number"
                            value={config.space}
                            onChange={(e) => onChange({ ...config, space: e.target.value })}
                            className="w-20 px-3 py-2 bg-background border border-border rounded-lg text-sm text-center text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                            min="1"
                            max="10"
                        />
                    </div>
                </div>
            </div>

            {/* Dataset Selection */}
            <div className="space-y-3">
                <label className="flex items-center gap-2 text-sm font-medium text-foreground/80">
                    <span className="w-2 h-2 rounded-full bg-green-500"></span>
                    Dataset
                </label>

                <select
                    value={config.datasetId}
                    onChange={(e) => onChange({ ...config, datasetId: e.target.value })}
                    className="w-full px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-green-500 focus:border-transparent transition-colors"
                >
                    <option value="">Select dataset...</option>
                    <option value="smallcaps_2023">Small Caps 2023-2024</option>
                    <option value="spy_1m">SPY 1m Historical</option>
                    <option value="custom_1">Custom Dataset 1</option>
                </select>
            </div>

            {/* Date Range */}
            <div className="space-y-3">
                <label className="text-sm font-medium text-foreground/80">Date Range</label>

                <div className="space-y-2">
                    <div>
                        <label className="text-xs text-muted-foreground mb-1 block">Start Date (In-Sample)</label>
                        <div className="relative">
                            <input
                                type="date"
                                value={config.dateFrom}
                                onChange={(e) => onChange({ ...config, dateFrom: e.target.value })}
                                className="w-full px-3 py-2 pl-9 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                            />
                            <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                        </div>
                    </div>

                    <div>
                        <label className="text-xs text-muted-foreground mb-1 block">End Date (Out-of-Sample)</label>
                        <div className="relative">
                            <input
                                type="date"
                                value={config.dateTo}
                                onChange={(e) => onChange({ ...config, dateTo: e.target.value })}
                                className="w-full px-3 py-2 pl-9 bg-background border border-border rounded-lg text-sm text-foreground focus:ring-2 focus:ring-blue-500 transition-colors"
                            />
                            <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                        </div>
                    </div>
                </div>
            </div>

            {/* Action Buttons */}
            <div className="space-y-2 pt-4 border-t border-border">
                <button
                    onClick={handleRunSearch}
                    disabled={isRunning}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-green-600 hover:bg-green-700 disabled:bg-muted disabled:text-muted-foreground text-white rounded-lg font-medium transition-colors shadow-sm"
                >
                    {isRunning ? (
                        <>
                            <Square className="w-4 h-4" />
                            Running...
                        </>
                    ) : (
                        <>
                            <Play className="w-4 h-4" />
                            Run Search
                        </>
                    )}
                </button>

                <div className="grid grid-cols-2 gap-2">
                    <button className="flex items-center justify-center gap-2 px-3 py-2 border border-border bg-card hover:bg-muted rounded-lg text-sm font-medium text-foreground transition-colors">
                        <Save className="w-4 h-4" />
                        Save Preset
                    </button>
                    <button className="flex items-center justify-center gap-2 px-3 py-2 border border-border bg-card hover:bg-muted rounded-lg text-sm font-medium text-foreground transition-colors">
                        <FolderOpen className="w-4 h-4" />
                        Load Preset
                    </button>
                </div>
            </div>

            {/* Progress Monitor */}
            <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg space-y-2">
                <div className="text-sm font-medium text-blue-500">Search Progress</div>
                <div className="text-xs text-blue-500/80">
                    {isRunning ? (
                        <span className="flex items-center gap-2">
                            <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></span>
                            Searching strategies...
                        </span>
                    ) : (
                        <span>{savedStrategiesCount} Saved Strategies</span>
                    )}
                </div>
            </div>
        </div>
    )
}
