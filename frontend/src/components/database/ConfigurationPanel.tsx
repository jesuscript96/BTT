'use client'

import { useState, useEffect } from 'react'
import { Calendar, Play, Square, Save, FolderOpen } from 'lucide-react'
import { getQueries } from '@/lib/api'
import { fetchAvailableDateRange } from '@/lib/api_backtester'

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

interface SavedDataset {
    id: string
    name: string
    filters: Record<string, unknown>
    created_at?: string
    updated_at?: string
}

export default function ConfigurationPanel({ config, onChange }: ConfigurationPanelProps) {
    const [isRunning, setIsRunning] = useState(false)
    const [savedStrategiesCount, setCount] = useState(0)
    const [savedDatasets, setSavedDatasets] = useState<SavedDataset[]>([])
    const [datasetsLoading, setDatasetsLoading] = useState(true)

    const [dbDateRange, setDbDateRange] = useState<any>({
        min_date: "2022-01-01",
        max_date: new Date().toISOString().split("T")[0]
    });

    useEffect(() => {
        let cancelled = false
        async function load() {
            try {
                const [data, range] = await Promise.all([
                    getQueries(),
                    fetchAvailableDateRange()
                ])
                if (!cancelled) {
                    setSavedDatasets(data)
                    if (range) {
                        setDbDateRange(range)
                    }
                }
            } catch (_) {
                if (!cancelled) setSavedDatasets([])
            } finally {
                if (!cancelled) setDatasetsLoading(false)
            }
        }
        load()
        return () => { cancelled = true }
    }, [])

    const handleRunSearch = () => {
        setIsRunning(true)
        // Trigger search logic
        setTimeout(() => setIsRunning(false), 2000)
    }

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
                }}>Strategy Searcher</h2>
                <p style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 10,
                  fontWeight: 400,
                  color: 'var(--color-ec-text-muted)',
                  marginTop: 3,
                }}>Configure search parameters</p>
            </div>

            {/* Mode & Space */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <label className="flex items-center gap-2" style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.15em',
                  color: 'var(--color-ec-text-muted)',
                }}>
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--color-ec-copper)' }}></span>
                    Mode & Space
                </label>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <select
                        value={config.mode}
                        onChange={(e) => onChange({ ...config, mode: e.target.value })}
                        style={{
                          width: '100%',
                          backgroundColor: 'var(--color-ec-bg-elevated)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 5,
                          padding: '7px 10px',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 12,
                          fontWeight: 500,
                          color: 'var(--color-ec-text-primary)',
                          outline: 'none',
                          cursor: 'pointer',
                        }}
                    >
                        <option>Consecutive Red</option>
                        <option>Gap & Fade</option>
                        <option>VWAP Rejection</option>
                        <option>High of Day Break</option>
                    </select>

                    <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', margin: '4px 0' }} />
                    <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-foreground">Consecutive red ==</span>
                        <input
                            type="number"
                            value={config.space}
                            onChange={(e) => onChange({ ...config, space: e.target.value })}
                            className="w-20 border"
                            style={{
                              backgroundColor: 'var(--color-ec-bg-elevated)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 5,
                              padding: '6px 8px',
                              fontFamily: 'var(--color-ec-sans)',
                              fontSize: 12,
                              fontWeight: 500,
                              color: 'var(--color-ec-text-primary)',
                              outline: 'none',
                              width: 60,
                            }}
                            min="1"
                            max="10"
                        />
                    </div>
                </div>
            </div>
            <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', margin: '0 -12px' }} />

            {/* Dataset Selection */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <label className="flex items-center gap-2" style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.15em',
                  color: 'var(--color-ec-text-muted)',
                }}>
                    <span className="w-2 h-2 rounded-full bg-ec-profit"></span>
                    Dataset
                </label>

                <select
                    value={config.datasetId}
                    onChange={(e) => onChange({ ...config, datasetId: e.target.value })}
                    style={{
                      width: '100%',
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '7px 10px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 12,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      outline: 'none',
                      cursor: 'pointer',
                    }}
                >
                    <option value="">Select dataset...</option>
                    {datasetsLoading ? (
                        <option value="" disabled>Loading...</option>
                    ) : (
                        savedDatasets.map((d) => (
                            <option key={d.id} value={d.id}>{d.name}</option>
                        ))
                    )}
                </select>
            </div>
            <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', margin: '0 -12px' }} />

            {/* Date Range */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <label style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.15em',
                  color: 'var(--color-ec-text-muted)',
                }}>Date Range</label>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <label style={{
                          display: 'block',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 9,
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          letterSpacing: '0.12em',
                          color: 'var(--color-ec-text-muted)',
                          marginBottom: 4,
                        }}>Start Date (In-Sample)</label>
                        <div className="relative">
                            <input
                                type="date"
                                value={config.dateFrom}
                                min={dbDateRange.min_date}
                                max={dbDateRange.max_date}
                                onChange={(e) => onChange({ ...config, dateFrom: e.target.value })}
                                className=""
                                style={{
                                  width: '100%',
                                  backgroundColor: 'var(--color-ec-bg-elevated)',
                                  border: '0.5px solid var(--color-ec-border)',
                                  borderRadius: 5,
                                  padding: '6px 8px 6px 34px',
                                  fontFamily: 'var(--color-ec-sans)',
                                  fontSize: 11,
                                  color: 'var(--color-ec-text-primary)',
                                  outline: 'none',
                                }}
                            />
                            <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                        </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <label style={{
                          display: 'block',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 9,
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          letterSpacing: '0.12em',
                          color: 'var(--color-ec-text-muted)',
                          marginBottom: 4,
                        }}>End Date (Out-of-Sample)</label>
                        <div className="relative">
                            <input
                                type="date"
                                value={config.dateTo}
                                min={config.dateFrom && config.dateFrom > dbDateRange.min_date ? config.dateFrom : dbDateRange.min_date}
                                max={dbDateRange.max_date}
                                onChange={(e) => onChange({ ...config, dateTo: e.target.value })}
                                className=""
                                style={{
                                  width: '100%',
                                  backgroundColor: 'var(--color-ec-bg-elevated)',
                                  border: '0.5px solid var(--color-ec-border)',
                                  borderRadius: 5,
                                  padding: '6px 8px 6px 34px',
                                  fontFamily: 'var(--color-ec-sans)',
                                  fontSize: 11,
                                  color: 'var(--color-ec-text-primary)',
                                  outline: 'none',
                                }}
                            />
                            <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                        </div>
                    </div>
                </div>
            </div>
            <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', margin: '0 -12px' }} />

            {/* Action Buttons */}
            <div style={{ 
              display: 'flex', 
              flexDirection: 'column', 
              gap: 8,
              paddingTop: 12,
              borderTop: '0.5px solid var(--color-ec-border)',
            }}>
                <button
                    onClick={handleRunSearch}
                    disabled={isRunning}
                    className="w-full"
                    style={{
                      width: '100%',
                      border: 'none',
                      cursor: isRunning ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 6,
                      letterSpacing: '1.2px',
                      textTransform: 'uppercase',
                      fontSize: 11,
                      fontWeight: 700,
                      fontFamily: 'var(--color-ec-sans)',
                      background: isRunning ? 'var(--color-ec-text-muted)' : 'var(--color-ec-copper)',
                      color: isRunning ? 'var(--color-ec-text-secondary)' : 'var(--color-ec-copper-text)',
                      borderRadius: 5,
                      padding: '9px 16px',
                    }}
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

                <div style={{ 
                  display: 'grid', 
                  gridTemplateColumns: '1fr 1fr', 
                  gap: 8 
                }}>
                    <button style={{
                      padding: '7px 12px',
                      backgroundColor: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '1.2px',
                      color: 'var(--color-ec-text-secondary)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 6,
                    }}>
                        <Save className="w-4 h-4" />
                        Save Preset
                    </button>
                    <button style={{
                      padding: '7px 12px',
                      backgroundColor: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '1.2px',
                      color: 'var(--color-ec-text-secondary)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 6,
                    }}>
                        <FolderOpen className="w-4 h-4" />
                        Load Preset
                    </button>
                </div>
            </div>

            {/* Progress Monitor */}
            <div style={{
              backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 10%, transparent)',
              border: '0.5px solid color-mix(in srgb, var(--color-ec-copper) 25%, transparent)',
              borderRadius: 5,
              padding: '10px 12px',
            }}>
                <div style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  fontWeight: 700,
                  color: 'var(--color-ec-copper)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.1em',
                }}>Search Progress</div>
                <div style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 10,
                  fontWeight: 400,
                  color: 'var(--color-ec-text-muted)',
                  marginTop: 3,
                }}>
                    {isRunning ? (
                        <span className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: 'var(--color-ec-copper)' }}></span>
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
