"use client";

import React from "react";
import {
    XAxis, YAxis, Tooltip, ResponsiveContainer,
    Area, CartesianGrid, ReferenceLine, ComposedChart, Line, ReferenceArea
} from "recharts";
import { getTickerIntraday } from "@/lib/api";
import { MarketIntelligenceCharts } from "./MarketIntelligenceCharts";

interface DistributionItem {
    label: string;
    value: number;
}

interface DistributionStats {
    hod_time?: Record<string, number>;
    lod_time?: Record<string, number>;
    [key: string]: any;
}

interface StatsAverages {
    gap_at_open_pct: number;
    pmh_fade_to_open_pct: number;
    rth_run_pct: number;
    high_spike_pct: number;
    low_spike_pct: number;
    close_red: number;
    rth_range_pct: number;
    low_spike_prev_close_pct: number;
    [key: string]: number;
}

interface DashboardStats {
    count: number;
    avg: StatsAverages;
    p25: StatsAverages;
    p50: StatsAverages;
    p75: StatsAverages;
    distributions: DistributionStats;
}

interface TimeSeriesItem {
    time: string;
    avg_change: number;
    median_change?: number;
}

interface DashboardProps {
    stats: DashboardStats;
    data: unknown[];
    aggregateSeries?: TimeSeriesItem[] | null;
    isLoadingAggregate?: boolean;
}

type StatMode = 'avg' | 'p25' | 'p50' | 'p75';

// ─── Sidebar Metric Row (Clean & Premium, no rounded badge box) ───────
const SidebarMetricRow = ({ label, value, suffix = "%" }: { label: string; value: number | undefined; suffix?: string }) => {
    const safeValue = value ?? 0;
    const isNegative = safeValue < 0;
    const isZero = Math.abs(safeValue) < 0.0001;
    
    const formattedVal = isZero 
        ? `0.00${suffix}` 
        : `${safeValue > 0 ? '+' : ''}${safeValue.toFixed(2)}${suffix}`;
    
    let textColor = 'var(--color-ec-text-primary)';
    if (!isZero) {
        textColor = isNegative ? 'var(--color-ec-loss)' : 'var(--color-ec-profit)';
    }

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            padding: '4px 0',
            borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 30%, transparent)'
        }}>
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 8,
                fontWeight: 600,
                color: 'var(--color-ec-text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                marginBottom: 0
            }}>
                {label}
            </span>
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 12,
                fontWeight: 600,
                color: textColor
            }}>
                {formattedVal}
            </span>
        </div>
    );
};

// ─── Volume Metric Row (Large numbers format) ────────────────────────
const VolumeMetricRow = ({ label, value }: { label: string; value: number | undefined }) => {
    const formatted = formatLargeNumber(value ?? 0);
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            padding: '4px 0',
            borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 30%, transparent)'
        }}>
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 8,
                fontWeight: 600,
                color: 'var(--color-ec-text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                marginBottom: 0
            }}>
                {label}
            </span>
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--color-ec-text-primary)'
            }}>
                {formatted}
            </span>
        </div>
    );
};

// ─── Format large numbers ─────────────────────────────────────────────
const formatLargeNumber = (num: number) => {
    if (!num) return "0";
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
};

// ─── Main Dashboard ───────────────────────────────────────────────────
export const Dashboard: React.FC<DashboardProps> = ({ stats, aggregateSeries, data, isLoadingAggregate }) => {
    const [mode, setMode] = React.useState<StatMode>('avg');

    const averages = stats?.[mode] ?? stats?.avg;

    // Empty State: Show Market Intelligence Charts
    if (!stats || !stats.avg) return (
        <div style={{ minHeight: '100%', fontFamily: "'General Sans', sans-serif" }}>
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '0.5px solid var(--color-ec-border)', padding: '20px 0 16px 0' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <h1 style={{
                            fontFamily: "'Fraunces', serif",
                            fontSize: 32,
                            fontWeight: 600,
                            color: 'var(--color-ec-text-high)',
                            letterSpacing: '-0.5px',
                            marginBottom: 4,
                        }}>MARKET INTELLIGENCE</h1>
                        <span style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 9,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: 2,
                            color: 'var(--color-ec-text-muted)',
                        }}>
                            REAL-TIME STATISTICAL DISTRIBUTIONS AND GAP COHORT ANALYSIS
                        </span>
                    </div>
                </div>
                <div style={{ flex: 1 }}>
                    <MarketIntelligenceCharts />
                </div>
            </div>
        </div>
    );

    return (
        <div style={{ minHeight: '100%', fontFamily: "'General Sans', sans-serif" }}>
            <div style={{
                display: 'flex',
                flexDirection: 'row',
                flexWrap: 'wrap',
                width: '100%',
                gap: 0,
            }}>
                {/* ═══ LEFT COLUMN: Sidebar Metrics ═══ */}
                <div style={{
                    flex: '1 1 280px',
                    minWidth: '260px',
                    maxWidth: '300px',
                    paddingRight: '20px',
                    borderRight: '1px solid var(--color-ec-border)',
                    boxSizing: 'border-box',
                }}>
                    {/* Header: Sample + Mode Selector */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '12px 0',
                        borderBottom: '1px solid var(--color-ec-border)',
                        marginBottom: '8px'
                    }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <div style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)' }}></div>
                                <span style={{ fontSize: '8px', fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>Total Sample</span>
                            </div>
                            <span style={{ fontSize: '15px', fontWeight: 700, color: 'var(--color-ec-text-high)', letterSpacing: '-0.3px' }}>{stats.count.toLocaleString()} REC</span>
                        </div>
                        
                        {/* Selector tabs */}
                        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                            {(['avg', 'p25', 'p50', 'p75'] as const).map((m) => (
                                <span
                                    key={m}
                                    onClick={() => setMode(m)}
                                    style={{
                                        cursor: 'pointer',
                                        color: mode === m ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-muted)',
                                        background: mode === m ? 'var(--color-ec-bg-elevated)' : 'transparent',
                                        padding: '4px 6px',
                                        borderRadius: '3px',
                                        fontSize: '8px',
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.5px',
                                        border: mode === m ? '1px solid var(--color-ec-copper)' : '1px solid transparent',
                                        transition: 'all 0.2s ease',
                                    }}
                                >
                                    {m === 'avg' ? 'AVG' : m === 'p25' ? '25th' : m === 'p50' ? 'MED' : '75th'}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Metrics Sections */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        
                        {/* SECTION 1: Core Movements */}
                        <div>
                            <div style={{
                                fontSize: '8px',
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                textTransform: 'uppercase',
                                letterSpacing: '1.5px',
                                paddingBottom: '2px',
                                borderBottom: '1px solid var(--color-ec-border)',
                                marginBottom: '2px'
                            }}>
                                Core Movements
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: '12px' }}>
                                <SidebarMetricRow label="Gap at Open" value={averages.gap_at_open_pct} />
                                <SidebarMetricRow label="PM High Gap" value={averages.pm_high_gap_pct} />
                                <SidebarMetricRow label="PM Fade Open" value={averages.pmh_fade_to_open_pct} />
                                <SidebarMetricRow label="PM High Break" value={averages.pm_high_break} />
                            </div>
                        </div>

                        {/* SECTION 2: Regular Session */}
                        <div>
                            <div style={{
                                fontSize: '8px',
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                textTransform: 'uppercase',
                                letterSpacing: '1.5px',
                                paddingBottom: '2px',
                                borderBottom: '1px solid var(--color-ec-border)',
                                marginBottom: '2px'
                            }}>
                                Regular Session (RTH)
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: '12px' }}>
                                <SidebarMetricRow label="RTH High Run" value={averages.rth_high_run_pct} />
                                <SidebarMetricRow label="RTH Fade Close" value={averages.rth_fade_to_close_pct} />
                                <SidebarMetricRow label="Close Red" value={averages.close_red} />
                                <SidebarMetricRow label="Range" value={averages.rth_range_pct} />
                            </div>
                        </div>

                        {/* SECTION 3: Spikes & Volatility */}
                        <div>
                            <div style={{
                                fontSize: '8px',
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                textTransform: 'uppercase',
                                letterSpacing: '1.5px',
                                paddingBottom: '2px',
                                borderBottom: '1px solid var(--color-ec-border)',
                                marginBottom: '4px'
                            }}>
                                Volatility & Spikes
                            </div>
                            {(() => {
                                const rawLowVal = averages.low_spike_pct ?? 0;
                                const lowVal = rawLowVal > 0 ? -rawLowVal : rawLowVal;
                                const highVal = averages.high_spike_pct ?? 0;

                                const lowValFormatted = `${lowVal.toFixed(2)}%`;
                                const highValFormatted = `${highVal >= 0 ? '+' : ''}${highVal.toFixed(2)}%`;

                                const maxVal = Math.max(Math.abs(lowVal), Math.abs(highVal), 1);
                                const leftWidth = (Math.abs(lowVal) / maxVal) * 50;
                                const rightWidth = (Math.abs(highVal) / maxVal) * 50;

                                return (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', padding: '6px 0' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600 }}>
                                            <span style={{ color: 'var(--color-ec-loss)' }}>{lowValFormatted}</span>
                                            <span style={{ fontSize: '7.5px', fontWeight: 600, color: 'var(--color-ec-text-muted)', letterSpacing: '0.5px' }}>LOW / HIGH SPIKE</span>
                                            <span style={{ color: 'var(--color-ec-profit)' }}>{highValFormatted}</span>
                                        </div>
                                        
                                        <div style={{
                                            height: '5px',
                                            width: '100%',
                                            backgroundColor: 'var(--color-ec-bg-elevated)',
                                            borderRadius: '2.5px',
                                            position: 'relative',
                                            overflow: 'hidden',
                                            marginTop: '2px'
                                        }}>
                                            <div style={{
                                                position: 'absolute',
                                                left: '50%',
                                                top: 0,
                                                bottom: 0,
                                                width: '1px',
                                                backgroundColor: 'rgba(255, 255, 255, 0.2)',
                                                zIndex: 2
                                            }} />
                                            <div style={{
                                                position: 'absolute',
                                                right: '50%',
                                                width: `${leftWidth}%`,
                                                height: '100%',
                                                backgroundColor: 'var(--color-ec-loss)',
                                                borderRadius: '2.5px 0 0 2.5px'
                                            }} />
                                            <div style={{
                                                position: 'absolute',
                                                left: '50%',
                                                width: `${rightWidth}%`,
                                                height: '100%',
                                                backgroundColor: 'var(--color-ec-profit)',
                                                borderRadius: '0 2.5px 2.5px 0'
                                            }} />
                                        </div>
                                    </div>
                                );
                            })()}
                        </div>

                        {/* SECTION 4: Volume Stats */}
                        <div>
                            <div style={{
                                fontSize: '8px',
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                textTransform: 'uppercase',
                                letterSpacing: '1.5px',
                                paddingBottom: '2px',
                                borderBottom: '1px solid var(--color-ec-border)',
                                marginBottom: '2px'
                            }}>
                                Volume
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: '12px' }}>
                                <VolumeMetricRow label="PM Volume" value={averages.avg_pm_volume} />
                                <VolumeMetricRow label="Avg Volume" value={averages.avg_volume} />
                            </div>
                        </div>

                    </div>
                </div>

                {/* ═══ RIGHT COLUMN: Chart ═══ */}
                <div style={{
                    flex: '1 1 500px',
                    minWidth: '320px',
                    paddingLeft: '20px',
                    boxSizing: 'border-box',
                    display: 'flex',
                    flexDirection: 'column',
                }}>
                    <div style={{ height: '480px', width: '100%' }}>
                        <IntradayDashboardChart data={data} aggregateSeries={aggregateSeries} isLoadingAggregate={isLoadingAggregate} />
                    </div>
                </div>
            </div>
        </div>
    );
};

// ─── Intraday Chart (Pure inline styles & custom variables) ───────────
const IntradayDashboardChart = ({ data, aggregateSeries, isLoadingAggregate }: { data: any[], aggregateSeries?: TimeSeriesItem[] | null, isLoadingAggregate?: boolean }) => {
    const [chartData, setChartData] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [activeTicker, setActiveTicker] = React.useState<string>("");

    const [smoothing, setSmoothing] = React.useState<number>(1);
    const [sessions, setSessions] = React.useState({
        pre: false,
        market: true,
        post: false
    });

    const isAggregate = React.useMemo(
        () => !!(aggregateSeries && aggregateSeries.length > 0),
        [aggregateSeries]
    );

    React.useEffect(() => {
        if (aggregateSeries === null) return;
        if (!isAggregate && data && data.length > 0) {
            setActiveTicker(data[0].ticker);
        }
    }, [data, isAggregate, aggregateSeries]);

    React.useEffect(() => {
        if (isAggregate) {
            const processed = processData(aggregateSeries || []);
            setChartData(processed);
            return;
        }

        if (!activeTicker) return;
        setLoading(true);
        getTickerIntraday(activeTicker, data && data[0] && data[0].date ? data[0].date : undefined)
            .then((resData: unknown) => {
                const arr = resData as any[];
                const parsed = arr.map((d: any) => ({
                    ...d,
                    time: d.timestamp.split(' ')[1].substring(0, 5),
                    timeShort: d.timestamp.split(' ')[1].substring(0, 5)
                }));
                const processed = processData(parsed);
                setChartData(processed);
            })
            .catch(e => console.error("Chart fetch error", e))
            .finally(() => setLoading(false));
    }, [activeTicker, isAggregate, aggregateSeries, sessions, smoothing]);

    const processData = (raw: any[]) => {
        if (!raw || raw.length === 0) return [];

        const filtered = raw.filter(d => {
            const time = d.time || d.timeShort;
            if (!time) return true;

            if (time >= "04:00" && time < "09:30") return sessions.pre;
            if (time >= "09:30" && time < "16:00") return sessions.market;
            if (time >= "16:00" && time < "20:00") return sessions.post;
            return false;
        });

        if (smoothing <= 1) return filtered;

        return filtered.map((d, i, arr) => {
            const start = Math.max(0, i - Math.floor(smoothing / 2));
            const end = Math.min(arr.length, i + Math.ceil(smoothing / 2));
            const subset = arr.slice(start, end);

            const smoothed: any = { ...d };
            if (isAggregate) {
                smoothed.avg_change = subset.reduce((acc, curr) => acc + curr.avg_change, 0) / subset.length;
                smoothed.median_change = subset.reduce((acc, curr) => acc + (curr.median_change || 0), 0) / subset.length;
            } else {
                smoothed.close = subset.reduce((acc, curr) => acc + curr.close, 0) / subset.length;
            }
            return smoothed;
        });
    };

    if (!isAggregate && !activeTicker) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-ec-text-muted)',
                fontSize: '10px',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '1.5px',
                height: '100%'
            }}>
                No intraday data available for selection.
            </div>
        );
    }

    let minPrice: number, maxPrice: number;
    if (isAggregate) {
        const vals = chartData.flatMap(d => [d.avg_change, d.median_change].filter(v => v !== undefined));
        minPrice = vals.length ? Math.min(...vals) : -1;
        maxPrice = vals.length ? Math.max(...vals) : 1;
        const range = maxPrice - minPrice;
        minPrice -= range * 0.1 || 0.1;
        maxPrice += range * 0.1 || 0.1;
    } else {
        const prices = chartData.map(d => d.close);
        minPrice = prices.length ? Math.min(...prices) * 0.99 : 0;
        maxPrice = prices.length ? Math.max(...prices) * 1.01 : 0;
    }

    const pmHigh = !isAggregate && chartData.length > 0 ? chartData[0].pm_high : 0;
    const isChartLoading = loading || (isAggregate && isLoadingAggregate);

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            height: '100%',
            position: 'relative',
            boxSizing: 'border-box'
        }}>
            {/* Header controls & titles */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {isAggregate ? (
                            <>
                                <h3 style={{ fontFamily: "'Fraunces', serif", fontSize: '15px', fontWeight: 600, color: 'var(--color-ec-text-high)', letterSpacing: '-0.3px' }}>CHANGE VS. PM HIGH</h3>
                                <span style={{ fontSize: '9px', fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>(AGGREGATE)</span>
                            </>
                        ) : (
                            <>
                                <h3 style={{ fontFamily: "'Fraunces', serif", fontSize: '15px', fontWeight: 600, color: 'var(--color-ec-text-high)' }}>{activeTicker}</h3>
                                <span style={{ fontSize: '9px', fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>INTRADAY ACTION</span>
                            </>
                        )}
                    </div>
                    
                    {/* Legend */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '9px', fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        {isAggregate ? (
                            <>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                    <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)' }} /> 
                                    AVERAGE
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                    <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', border: '1px dashed var(--color-ec-text-secondary)' }} /> 
                                    MEDIAN
                                </div>
                            </>
                        ) : (
                            <>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                    <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--color-ec-profit)' }} /> 
                                    Price
                                </div>
                                {pmHigh > 0 && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                        <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', border: '1px dashed var(--color-ec-copper)' }} /> 
                                        PM High
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>

                {/* Session & Smoothing Controls */}
                <div style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '16px',
                    paddingBottom: '10px',
                    borderBottom: '1px solid var(--color-ec-border)'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ fontSize: '9px', fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>Sessions:</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={sessions.pre}
                                    onChange={(e) => setSessions(prev => ({ ...prev, pre: e.target.checked }))}
                                    style={{ display: 'none' }}
                                />
                                <div style={{ width: 11, height: 11, borderRadius: 2, border: '0.5px solid', borderColor: sessions.pre ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)', background: sessions.pre ? 'var(--color-ec-copper)' : 'transparent', transition: 'all 150ms' }} />
                                <span style={{ fontFamily: "'General Sans', sans-serif", fontSize: 10, fontWeight: 500, color: sessions.pre ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)' }}>Pre</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={sessions.market}
                                    onChange={(e) => setSessions(prev => ({ ...prev, market: e.target.checked }))}
                                    style={{ display: 'none' }}
                                />
                                <div style={{ width: 11, height: 11, borderRadius: 2, border: '0.5px solid', borderColor: sessions.market ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)', background: sessions.market ? 'var(--color-ec-copper)' : 'transparent', transition: 'all 150ms' }} />
                                <span style={{ fontFamily: "'General Sans', sans-serif", fontSize: 10, fontWeight: 500, color: sessions.market ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)' }}>Market</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={sessions.post}
                                    onChange={(e) => setSessions(prev => ({ ...prev, post: e.target.checked }))}
                                    style={{ display: 'none' }}
                                />
                                <div style={{ width: 11, height: 11, borderRadius: 2, border: '0.5px solid', borderColor: sessions.post ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)', background: sessions.post ? 'var(--color-ec-copper)' : 'transparent', transition: 'all 150ms' }} />
                                <span style={{ fontFamily: "'General Sans', sans-serif", fontSize: 10, fontWeight: 500, color: sessions.post ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)' }}>Post</span>
                            </label>
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '9px', fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>Smoothing:</span>
                        <input
                            type="range"
                            min="1"
                            max="20"
                            value={smoothing}
                            onChange={(e) => setSmoothing(parseInt(e.target.value))}
                            style={{
                                width: '80px',
                                height: '3px',
                                backgroundColor: 'var(--color-ec-bg-elevated)',
                                borderRadius: '9999px',
                                appearance: 'none',
                                WebkitAppearance: 'none',
                                cursor: 'pointer',
                                accentColor: 'var(--color-ec-copper)',
                            }}
                        />
                        <span style={{ fontSize: '10px', fontWeight: 700, color: 'var(--color-ec-text-high)', width: '14px', textAlign: 'right' }}>{smoothing}</span>
                    </div>
                </div>
            </div>

            {/* Chart display */}
            <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
                {isChartLoading ? (
                    <div style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        zIndex: 10,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: 'rgba(22, 24, 26, 0.7)',
                        backdropFilter: 'blur(4px)',
                    }}>
                        <div className="animate-spin" style={{
                            width: 24,
                            height: 24,
                            border: '3px solid var(--color-ec-border)',
                            borderTop: '3px solid var(--color-ec-copper)',
                            borderRadius: '50%',
                            marginBottom: 12
                        }} />
                        <div style={{
                            color: 'var(--color-ec-text-muted)',
                            fontSize: '9px',
                            textTransform: 'uppercase',
                            fontWeight: 700,
                            letterSpacing: '1px'
                        }}>
                            {isLoadingAggregate ? "Aggregating Intraday Data..." : "Loading Chart..."}
                        </div>
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={chartData} margin={{ top: 10, right: 5, left: 5, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-ec-border)" vertical={false} />
                            <XAxis
                                dataKey={isAggregate ? "time" : "timeShort"}
                                stroke="var(--color-ec-text-muted)"
                                fontSize={9}
                                tickLine={false}
                                axisLine={false}
                                minTickGap={40}
                                style={{ fontFamily: "'General Sans', sans-serif" }}
                            />
                            <YAxis
                                stroke="var(--color-ec-text-muted)"
                                fontSize={9}
                                tickLine={false}
                                axisLine={false}
                                domain={[minPrice, maxPrice]}
                                tickFormatter={(v) => v.toFixed(2) + (isAggregate ? "%" : "")}
                                orientation="right"
                                style={{ fontFamily: "'General Sans', sans-serif" }}
                            />
                            <Tooltip
                                contentStyle={{
                                    backgroundColor: 'var(--color-ec-bg-surface)',
                                    border: '1px solid var(--color-ec-border)',
                                    borderRadius: '6px',
                                    fontSize: '11px',
                                    fontFamily: "'General Sans', sans-serif",
                                    color: 'var(--color-ec-text-primary)',
                                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.5)'
                                }}
                                itemStyle={{ color: 'var(--color-ec-text-primary)' }}
                                labelStyle={{ color: 'var(--color-ec-text-muted)', fontWeight: 600, marginBottom: 4 }}
                                formatter={(value: any) => [value.toFixed(2) + (isAggregate ? "%" : ""), ""]}
                            />

                            {sessions.pre && (
                                <ReferenceArea x1="04:00" x2="09:30" fill="var(--color-ec-text-muted)" fillOpacity={0.04} />
                            )}
                            {sessions.market && (
                                <ReferenceArea x1="09:30" x2="16:00" fill="var(--color-ec-profit)" fillOpacity={0.02} />
                            )}
                            {sessions.post && (
                                <ReferenceArea x1="16:00" x2="20:00" fill="var(--color-ec-copper)" fillOpacity={0.04} />
                            )}

                            {isAggregate ? (
                                <>
                                    <Line type="monotone" dataKey="avg_change" stroke="var(--color-ec-copper)" strokeWidth={2.5} dot={false} name="Average" animationDuration={300} />
                                    <Line type="monotone" dataKey="median_change" stroke="var(--color-ec-text-secondary)" strokeWidth={1.5} strokeDasharray="4 4" dot={false} name="Median" animationDuration={300} />
                                </>
                            ) : (
                                <>
                                    {pmHigh > 0 && <ReferenceLine y={pmHigh} stroke="var(--color-ec-copper)" strokeDasharray="3 3" label={{ position: 'insideRight', value: 'PMH', fill: 'var(--color-ec-copper)', fontSize: 9, fontFamily: 'General Sans' }} />}
                                    <ReferenceLine x="09:30" stroke="var(--color-ec-border)" strokeDasharray="3 3" />
                                    <Area type="monotone" dataKey="close" stroke="var(--color-ec-profit)" strokeWidth={2} fillOpacity={0.06} fill="var(--color-ec-profit)" dot={false} animationDuration={300} />
                                </>
                            )}
                        </ComposedChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};
