"use client";

import React, { useState, useEffect } from 'react';
import {
    Activity, Users, ArrowUpRight, ArrowDownRight, ExternalLink, ChevronDown, ChevronUp, Search
} from 'lucide-react';
import { getTickerAnalysis, getTickerSecFilings } from '@/lib/api';

interface TickerAnalysisProps {
    ticker?: string;
    availableTickers: string[]; // For the combobox
}

// Sparkline Component implemented with native SVG to avoid React 19 hook mismatches in Recharts
const Sparkline = ({ data, color }: { data: any[], color: string }) => {
    if (!data || data.length === 0) {
        return (
            <div 
                className="animate-pulse" 
                style={{ 
                    height: '48px', 
                    width: '100%', 
                    backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                    borderRadius: '4px' 
                }} 
            />
        );
    }
    
    const values = data.map(d => d.value ?? 0);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min === 0 ? 1 : max - min;
    
    const points = data.map((d, index) => {
        const x = (index / (data.length - 1)) * 100;
        // Invert y because SVG y=0 is at the top, and we want high values at the top
        const y = 40 - (((d.value ?? 0) - min) / range) * 36 - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    
    const pathData = `M ${points.join(' L ')}`;
    
    return (
        <div style={{ height: '48px', width: '100%' }}>
            <svg className="w-full h-full" viewBox="0 0 100 40" preserveAspectRatio="none">
                <path
                    d={pathData}
                    fill="none"
                    stroke={color}
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
            </svg>
        </div>
    );
};

// Pure utility helpers for numbers and percentages
const formatNumber = (num: number | null) => {
    if (num === null || num === undefined) return '-';
    const isNeg = num < 0;
    const absNum = Math.abs(num);
    let formatted = '';
    if (absNum >= 1e9) formatted = `$ ${(absNum / 1e9).toFixed(2)} B`;
    else if (absNum >= 1e6) formatted = `$ ${(absNum / 1e6).toFixed(2)} M`;
    else if (absNum >= 1e3) formatted = `$ ${(absNum / 1e3).toFixed(2)} K`;
    else formatted = absNum.toFixed(2);
    
    return isNeg ? `-$ ${formatted.replace('$', '')}` : formatted;
};

const formatPercent = (num: number | null) => {
    if (num === null || num === undefined) return '-';
    return `${(num * 100).toFixed(2)}%`;
};

// SVG-based responsive Grouped Bar Chart supporting negative values
const formatAxisLabel = (num: number) => {
    const absNum = Math.abs(num);
    let formatted = '';
    if (absNum >= 1e9) formatted = `${(absNum / 1e9).toFixed(1)}B`;
    else if (absNum >= 1e6) formatted = `${(absNum / 1e6).toFixed(1)}M`;
    else if (absNum >= 1e3) formatted = `${(absNum / 1e3).toFixed(1)}K`;
    else formatted = absNum.toFixed(0);
    
    return `${num < 0 ? '-' : ''}$${formatted}`;
};

// SVG-based responsive Grouped Bar Chart supporting dual Y-axes (Left: Cash/Debt, Right: Working Capital)
const GroupedBarChart = ({ cashData, debtData, wcData }: { cashData: any[], debtData: any[], wcData: any[] }) => {
    if (!cashData && !debtData && !wcData) {
        return (
            <div 
                className="animate-pulse" 
                style={{ 
                    height: '160px', 
                    width: '100%', 
                    backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                    borderRadius: '4px' 
                }} 
            />
        );
    }

    const datesSet = new Set<string>();
    cashData?.forEach((item: any) => datesSet.add(item.date));
    debtData?.forEach((item: any) => datesSet.add(item.date));
    wcData?.forEach((item: any) => datesSet.add(item.date));

    const sortedDates = Array.from(datesSet).sort();

    if (sortedDates.length === 0) {
        return (
            <div style={{
                height: '160px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-ec-text-muted)',
                fontSize: '11px',
                fontWeight: 500
            }}>
                No historical data available.
            </div>
        );
    }

    // Left scale values (Cash, Debt)
    let maxLeftVal = 1;
    sortedDates.forEach(d => {
        const cashVal = cashData?.find((item: any) => item.date === d)?.value ?? 0;
        const debtVal = debtData?.find((item: any) => item.date === d)?.value ?? 0;
        maxLeftVal = Math.max(maxLeftVal, Math.abs(cashVal), Math.abs(debtVal));
    });

    // Right scale values (Working Capital)
    let maxRightVal = 1;
    let hasNegative = false;
    sortedDates.forEach(d => {
        const wcVal = wcData?.find((item: any) => item.date === d)?.value ?? 0;
        if (wcVal < 0) {
            hasNegative = true;
        }
        maxRightVal = Math.max(maxRightVal, Math.abs(wcVal));
    });

    const svgWidth = 500;
    const svgHeight = 220;
    const marginTop = 30;
    const marginBottom = 35;
    const marginLeft = 45;
    const marginRight = 45;
    
    const chartHeight = svgHeight - marginTop - marginBottom;
    const chartWidth = svgWidth - marginLeft - marginRight;

    const zeroY = hasNegative 
        ? marginTop + chartHeight / 2 
        : marginTop + chartHeight;
        
    const scaleLeft = hasNegative 
        ? (chartHeight / 2) / maxLeftVal 
        : chartHeight / maxLeftVal;

    const scaleRight = hasNegative 
        ? (chartHeight / 2) / maxRightVal 
        : chartHeight / maxRightVal;

    const groupWidth = chartWidth / sortedDates.length;
    const barWidth = 12;
    const barGap = 3;
    const totalBarsWidth = 3 * barWidth + 2 * barGap;

    const formatDateLabel = (dateStr: string) => {
        try {
            const date = new Date(dateStr);
            const month = date.toLocaleString('en-US', { month: 'short' });
            const year = date.getFullYear().toString().slice(-2);
            return `${month} '${year}`;
        } catch {
            return dateStr;
        }
    };

    return (
        <div style={{ width: '100%', height: '100%' }}>
            <svg className="w-full h-full" viewBox={`0 0 ${svgWidth} ${svgHeight}`} preserveAspectRatio="xMidYMid meet">
                {/* Horizontal reference lines */}
                {hasNegative ? (
                    <>
                        <line x1={marginLeft} y1={marginTop} x2={svgWidth - marginRight} y2={marginTop} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.2" />
                        <line x1={marginLeft} y1={marginTop + chartHeight} x2={svgWidth - marginRight} y2={marginTop + chartHeight} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.2" />
                    </>
                ) : (
                    <>
                        <line x1={marginLeft} y1={marginTop} x2={svgWidth - marginRight} y2={marginTop} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.2" />
                        <line x1={marginLeft} y1={marginTop + chartHeight / 2} x2={svgWidth - marginRight} y2={marginTop + chartHeight / 2} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.2" />
                    </>
                )}

                {/* Vertical Axis lines */}
                <line x1={marginLeft} y1={marginTop} x2={marginLeft} y2={marginTop + chartHeight} stroke="var(--color-ec-border)" strokeWidth="0.5" opacity="0.5" />
                <line x1={svgWidth - marginRight} y1={marginTop} x2={svgWidth - marginRight} y2={marginTop + chartHeight} stroke="var(--color-ec-border)" strokeWidth="0.5" opacity="0.5" />

                {/* Axis Titles */}
                <text
                    x={marginLeft}
                    y={marginTop - 12}
                    textAnchor="start"
                    fill="var(--color-ec-text-secondary)"
                    style={{
                        fontFamily: "'General Sans', sans-serif",
                        fontSize: '8px',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px'
                    }}
                >
                    Cash / Debt (L)
                </text>
                <text
                    x={svgWidth - marginRight}
                    y={marginTop - 12}
                    textAnchor="end"
                    fill="#60a5fa"
                    style={{
                        fontFamily: "'General Sans', sans-serif",
                        fontSize: '8px',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px'
                    }}
                >
                    Working Capital (R)
                </text>

                {/* Left Y-axis ticks and labels */}
                <text
                    x={marginLeft - 8}
                    y={marginTop + 4}
                    textAnchor="end"
                    fill="var(--color-ec-text-muted)"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '8px', fontWeight: 600 }}
                >
                    {formatAxisLabel(maxLeftVal)}
                </text>
                <text
                    x={marginLeft - 8}
                    y={zeroY + 3}
                    textAnchor="end"
                    fill="var(--color-ec-text-muted)"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '8px', fontWeight: 600 }}
                >
                    $0
                </text>
                {hasNegative && (
                    <text
                        x={marginLeft - 8}
                        y={marginTop + chartHeight + 2}
                        textAnchor="end"
                        fill="var(--color-ec-text-muted)"
                        style={{ fontFamily: "'General Sans', sans-serif", fontSize: '8px', fontWeight: 600 }}
                    >
                        {formatAxisLabel(-maxLeftVal)}
                    </text>
                )}

                {/* Right Y-axis ticks and labels */}
                <text
                    x={svgWidth - marginRight + 8}
                    y={marginTop + 4}
                    textAnchor="start"
                    fill="#60a5fa"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '8px', fontWeight: 600 }}
                >
                    {formatAxisLabel(maxRightVal)}
                </text>
                <text
                    x={svgWidth - marginRight + 8}
                    y={zeroY + 3}
                    textAnchor="start"
                    fill="#60a5fa"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '8px', fontWeight: 600 }}
                >
                    $0
                </text>
                {hasNegative && (
                    <text
                        x={svgWidth - marginRight + 8}
                        y={marginTop + chartHeight + 2}
                        textAnchor="start"
                        fill="#60a5fa"
                        style={{ fontFamily: "'General Sans', sans-serif", fontSize: '8px', fontWeight: 600 }}
                    >
                        {formatAxisLabel(-maxRightVal)}
                    </text>
                )}

                {/* Zero baseline line */}
                <line 
                    x1={marginLeft} 
                    y1={zeroY} 
                    x2={svgWidth - marginRight} 
                    y2={zeroY} 
                    stroke="var(--color-ec-border)" 
                    strokeWidth="1" 
                />

                {/* Bars & X-axis dates */}
                {sortedDates.map((d, index) => {
                    const cashVal = cashData?.find((item: any) => item.date === d)?.value ?? 0;
                    const debtVal = debtData?.find((item: any) => item.date === d)?.value ?? 0;
                    const wcVal = wcData?.find((item: any) => item.date === d)?.value ?? 0;

                    const groupStartX = marginLeft + index * groupWidth + (groupWidth - totalBarsWidth) / 2;

                    // Cash & Debt (scaled to Left axis)
                    const cashH = Math.abs(cashVal) * scaleLeft;
                    const cashY = cashVal >= 0 ? zeroY - cashH : zeroY;

                    const debtH = Math.abs(debtVal) * scaleLeft;
                    const debtY = debtVal >= 0 ? zeroY - debtH : zeroY;

                    // Working Capital (scaled to Right axis)
                    const wcH = Math.abs(wcVal) * scaleRight;
                    const wcY = wcVal >= 0 ? zeroY - wcH : zeroY;

                    return (
                        <g key={d}>
                            {/* Cash Bar */}
                            <rect
                                x={groupStartX}
                                y={cashY}
                                width={barWidth}
                                height={Math.max(cashH, 1)}
                                fill="var(--color-ec-profit)"
                                rx="1"
                                opacity="0.9"
                            />
                            {/* Debt Bar */}
                            <rect
                                x={groupStartX + barWidth + barGap}
                                y={debtY}
                                width={barWidth}
                                height={Math.max(debtH, 1)}
                                fill="var(--color-ec-loss)"
                                rx="1"
                                opacity="0.9"
                            />
                            {/* Working Capital Bar */}
                            <rect
                                x={groupStartX + 2 * (barWidth + barGap)}
                                y={wcY}
                                width={barWidth}
                                height={Math.max(wcH, 1)}
                                fill="#3b82f6"
                                rx="1"
                                opacity="0.9"
                            />

                            {/* X-axis date label - enlarged to 11px according to request */}
                            <text
                                x={marginLeft + index * groupWidth + groupWidth / 2}
                                y={svgHeight - 12}
                                textAnchor="middle"
                                fill="var(--color-ec-text-muted)"
                                style={{
                                    fontFamily: "'General Sans', sans-serif",
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.5px'
                                }}
                            >
                                {formatDateLabel(d)}
                            </text>
                        </g>
                    );
                })}
            </svg>
        </div>
    );
};

// Unified Balance Sheet Trends Card component
const BalanceSheetTrendsCard = ({ data }: { data: any }) => {
    return (
        <div style={{
            padding: '12px 0',
            display: 'flex',
            flexDirection: 'column',
            gap: 16
        }}>
            <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 12,
                borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 30%, transparent)',
                paddingBottom: 12
            }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Cash</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-ec-profit)' }}>{formatNumber(data?.financials?.cash)}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Total Debt</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-ec-loss)' }}>{formatNumber(data?.financials?.total_debt)}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Working Capital</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: '#3b82f6' }}>{formatNumber(data?.financials?.working_capital)}</span>
                </div>
            </div>

            <div style={{ height: '180px' }}>
                <GroupedBarChart 
                    cashData={data?.charts?.cash_history} 
                    debtData={data?.charts?.debt_history} 
                    wcData={data?.charts?.working_capital_history} 
                />
            </div>

            <div style={{
                display: 'flex',
                justifyContent: 'center',
                gap: 16,
                fontSize: 8,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.5px'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 1.5, backgroundColor: 'var(--color-ec-profit)' }} />
                    <span style={{ color: 'var(--color-ec-text-muted)' }}>Cash</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 1.5, backgroundColor: 'var(--color-ec-loss)' }} />
                    <span style={{ color: 'var(--color-ec-text-muted)' }}>Debt</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 1.5, backgroundColor: '#3b82f6' }} />
                    <span style={{ color: 'var(--color-ec-text-muted)' }}>Working Capital</span>
                </div>
            </div>
        </div>
    );
};

export default function TickerAnalysis({ ticker: initialTicker, availableTickers }: TickerAnalysisProps) {
    const [selectedTicker, setSelectedTicker] = useState<string>(initialTicker || '');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState<any>(null);
    const [filings, setFilings] = useState<any>(null);
    const [showFullDesc, setShowFullDesc] = useState(false);
    const [logoFailed, setLogoFailed] = useState(false);

    // Update if prop changes
    useEffect(() => {
        if (initialTicker) setSelectedTicker(initialTicker);
    }, [initialTicker]);

    // Reset logoFailed when ticker changes
    useEffect(() => {
        setLogoFailed(false);
    }, [selectedTicker]);

    // Fetch Data
    useEffect(() => {
        if (!selectedTicker) return;

        const fetchData = async () => {
            setLoading(true);
            try {
                // Parallel fetching — each independent so one failure doesn't block the other
                try { setData(await getTickerAnalysis(selectedTicker)); } catch { /* ignore */ }
                try { setFilings(await getTickerSecFilings(selectedTicker)); } catch { /* ignore */ }

            } catch (error) {
                console.error("Error fetching ticker analysis:", error);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [selectedTicker]);

    // Empty state - Clean, centered search box
    if (!selectedTicker) {
        return (
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '60vh',
                fontFamily: "'General Sans', sans-serif",
                color: 'var(--color-ec-text-primary)',
                padding: '16px'
            }}>
                <div style={{
                    width: '100%',
                    maxWidth: '400px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 20,
                    textAlign: 'center'
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <h2 style={{
                            fontFamily: "'Fraunces', serif",
                            fontSize: 32,
                            fontWeight: 600,
                            color: 'var(--color-ec-text-high)',
                            letterSpacing: '-0.5px'
                        }}>TICKER ANALYSIS</h2>
                        <p style={{
                            fontSize: 10,
                            fontWeight: 600,
                            textTransform: 'uppercase',
                            letterSpacing: '1.5px',
                            color: 'var(--color-ec-text-muted)'
                        }}>
                            REAL-TIME METRICS & CORPORATE INFO
                        </p>
                    </div>
                    
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 10,
                        padding: '0 16px',
                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                        border: '1px solid var(--color-ec-border)',
                        borderRadius: 8,
                        height: 48,
                        width: '100%',
                        boxSizing: 'border-box'
                    }}>
                        <Search size={16} style={{ color: 'var(--color-ec-text-muted)', flexShrink: 0 }} />
                        <input
                            key="search-input-empty"
                            type="text"
                            list="ticker-options-empty"
                            placeholder="(busca un ticker)"
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    const val = (e.target as HTMLInputElement).value.toUpperCase().trim();
                                    if (val) setSelectedTicker(val);
                                }
                            }}
                            onChange={(e) => {
                                const val = e.target.value.toUpperCase().trim();
                                if (availableTickers.includes(val)) {
                                    setSelectedTicker(val);
                                }
                            }}
                            style={{
                                background: 'transparent',
                                border: 'none',
                                outline: 'none',
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 13,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-primary)',
                                textAlign: 'center',
                                width: '130px'
                            }}
                        />
                        <datalist id="ticker-options-empty">
                            {availableTickers.sort().map(t => <option key={t} value={t} />)}
                        </datalist>
                    </div>
                </div>
            </div>
        );
    }

    // Helpers (moved to top-level)

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 24,
            width: '100%',
            maxWidth: '1200px',
            margin: '0 auto',
            padding: '24px',
            boxSizing: 'border-box',
            fontFamily: "'General Sans', sans-serif",
            color: 'var(--color-ec-text-primary)',
            paddingBottom: '80px'
        }}>

            {/* Header & Search */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 16,
                borderBottom: '1px solid var(--color-ec-border)',
                paddingBottom: 16
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    {!logoFailed && data?.profile?.logo_url ? (
                        <img 
                            src={data.profile.logo_url} 
                            alt={selectedTicker} 
                            onError={() => setLogoFailed(true)}
                            style={{
                                width: 40,
                                height: 40,
                                borderRadius: 4,
                                backgroundColor: '#ffffff',
                                border: '1px solid var(--color-ec-border)',
                                objectFit: 'contain',
                                padding: '2px',
                                flexShrink: 0
                            }}
                        />
                    ) : (
                        <div style={{
                            width: 40,
                            height: 40,
                            borderRadius: 4,
                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                            border: '1px solid var(--color-ec-border)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontFamily: "'Fraunces', serif",
                            fontSize: 20,
                            fontWeight: 600,
                            color: 'var(--color-ec-copper-bright)',
                            flexShrink: 0
                        }}>
                            {selectedTicker[0]}
                        </div>
                    )}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <h1 style={{
                                fontFamily: "'Fraunces', serif",
                                fontSize: 28,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                                letterSpacing: '-0.5px'
                            }}>{selectedTicker}</h1>
                            <span style={{
                                fontSize: 8,
                                fontWeight: 700,
                                color: 'var(--color-ec-text-muted)',
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                padding: '2px 6px',
                                borderRadius: 3,
                                textTransform: 'uppercase',
                                letterSpacing: '1px'
                            }}>{data?.profile?.exchange || 'STOCK'}</span>
                        </div>
                        <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-ec-text-muted)' }}>
                            {data?.profile?.name || 'Loading profile...'}
                        </span>
                    </div>
                </div>

                {/* Search box */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    border: '1px solid var(--color-ec-border)',
                    borderRadius: 5,
                    padding: '0 10px',
                    height: 32,
                    width: 180,
                    boxSizing: 'border-box'
                }}>
                    <Search size={12} style={{ color: 'var(--color-ec-text-muted)', flexShrink: 0 }} />
                    <input
                        key="search-input-detail"
                        type="text"
                        list="ticker-options"
                        placeholder="Buscar ticker..."
                        value={selectedTicker || ''}
                        onChange={(e) => {
                            const val = e.target.value.toUpperCase().trim();
                            setSelectedTicker(val);
                        }}
                        style={{
                            background: 'transparent',
                            border: 'none',
                            outline: 'none',
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 11,
                            fontWeight: 500,
                            color: 'var(--color-ec-text-primary)',
                            width: '100%'
                        }}
                    />
                    <datalist id="ticker-options">
                        {availableTickers.sort().map(t => <option key={t} value={t} />)}
                    </datalist>
                </div>
            </div>

            {loading ? (
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                    gap: 24,
                    padding: '20px 0'
                }}>
                    {[1, 2, 3, 4, 5, 6].map(i => (
                        <div 
                            key={i} 
                            className="animate-pulse" 
                            style={{ 
                                height: '120px', 
                                backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)', 
                                borderRadius: '8px' 
                            }} 
                        />
                    ))}
                </div>
            ) : (
                <>
                    {/* Market Metrics Row */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                        gap: 24,
                        borderBottom: '1px solid var(--color-ec-border)',
                        paddingBottom: 20
                    }}>
                        <MetricCard title="Market Cap" value={formatNumber(data?.market?.market_cap)} icon={<Activity size={12} />} indicatorColor="var(--color-ec-copper)" />
                        <MetricCard title="Shares Outstanding" value={formatNumber(data?.market?.shares_outstanding).replace('$', '')} icon={<Users size={12} />} indicatorColor="var(--color-ec-copper)" />
                        <MetricCard 
                            title="Float Shares" 
                            value={formatNumber(data?.market?.float_shares).replace('$', '')} 
                            subtext={`${formatPercent(data?.market?.held_percent_insiders)} Insiders / ${formatPercent(data?.market?.held_percent_institutions)} Inst.`}
                            icon={<Users size={12} />} 
                            indicatorColor="var(--color-ec-copper)" 
                        />
                    </div>

                    {/* Columns Grid: Profile, Financials, Trends */}
                    <div className="ticker-analysis-grid border-b border-ec-border pb-8">
                        
                        {/* Col 1: Corporate Profile & Description */}
                        <div className="ticker-col-container ticker-col-1-container lg:pb-0 pb-6">
                            <div>
                                <h3 style={{
                                    fontFamily: "'General Sans', sans-serif",
                                    fontSize: 8,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-copper)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '1.5px',
                                    borderBottom: '1px solid var(--color-ec-border)',
                                    paddingBottom: 4,
                                    marginBottom: 12
                                }}>Corporate Info</h3>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                                    <InfoItem label="Sector" value={data?.profile?.sector} />
                                    <InfoItem label="Industry" value={data?.profile?.industry} />
                                    <InfoItem label="Employees" value={data?.profile?.employees?.toLocaleString()} />
                                    <InfoItem label="Country" value={data?.profile?.country} />
                                    <div style={{ gridColumn: 'span 2' }}>
                                        <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block', marginBottom: 2 }}>Website</span>
                                        {data?.profile?.website ? (
                                            <a 
                                                href={data.profile.website} 
                                                target="_blank" 
                                                rel="noopener noreferrer" 
                                                className="transition-colors hover:text-white" 
                                                style={{ 
                                                    fontSize: 12, 
                                                    fontWeight: 600, 
                                                    color: 'var(--color-ec-copper-bright)', 
                                                    textDecoration: 'none', 
                                                    display: 'flex', 
                                                    alignItems: 'center', 
                                                    gap: 4 
                                                }}
                                            >
                                                {data.profile.website} <ExternalLink size={10} />
                                            </a>
                                        ) : '-'}
                                    </div>
                                </div>
                            </div>

                            <div style={{ borderTop: '1px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)', paddingTop: 16 }}>
                                <h3 style={{
                                    fontFamily: "'General Sans', sans-serif",
                                    fontSize: 8,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-copper)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '1.5px',
                                    marginBottom: 10
                                }}>Description</h3>
                                <div style={{
                                    fontSize: 12,
                                    lineHeight: '1.6',
                                    color: 'var(--color-ec-text-secondary)',
                                    maxHeight: showFullDesc ? 'none' : '120px',
                                    overflow: 'hidden',
                                    position: 'relative'
                                }}>
                                    {data?.profile?.description || 'No description available.'}
                                    {!showFullDesc && data?.profile?.description && (
                                        <div style={{
                                            position: 'absolute',
                                            bottom: 0,
                                            left: 0,
                                            right: 0,
                                            height: '40px',
                                            background: 'linear-gradient(to top, var(--color-ec-bg-base), transparent)'
                                        }} />
                                    )}
                                </div>
                                {data?.profile?.description && (
                                    <button
                                        onClick={() => setShowFullDesc(!showFullDesc)}
                                        className="transition-colors hover:text-[var(--color-ec-copper-bright)]"
                                        style={{
                                            backgroundColor: 'transparent',
                                            border: 'none',
                                            cursor: 'pointer',
                                            fontFamily: "'General Sans', sans-serif",
                                            fontSize: 9,
                                            fontWeight: 700,
                                            textTransform: 'uppercase',
                                            letterSpacing: '1px',
                                            color: 'var(--color-ec-copper)',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 2,
                                            marginTop: 6,
                                            padding: 0
                                        }}
                                    >
                                        {showFullDesc ? 'Show Less' : 'Read More'} {showFullDesc ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* Col 2: Financial Stats & Price Performance */}
                        <div className="ticker-col-container ticker-col-2-container lg:py-0 py-6">
                            <div>
                                <h3 style={{
                                    fontFamily: "'General Sans', sans-serif",
                                    fontSize: 8,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-copper)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '1.5px',
                                    borderBottom: '1px solid var(--color-ec-border)',
                                    paddingBottom: 4,
                                    marginBottom: 8
                                }}>Financial Statistics</h3>
                                <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <StatRow label="Enterprise Value" value={formatNumber(data?.financials?.enterprise_value)} />
                                    <StatRow label="Total Cash" value={formatNumber(data?.financials?.cash)} />
                                    <StatRow label="Total Debt" value={formatNumber(data?.financials?.total_debt)} />
                                    <StatRow label="EBITDA" value={formatNumber(data?.financials?.ebitda)} />
                                    <StatRow label="EPS (TTM)" value={data?.financials?.eps?.toFixed(2) || '-'} />
                                </div>
                            </div>

                            <div style={{ borderTop: '1px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)', paddingTop: 16 }}>
                                <h3 style={{
                                    fontFamily: "'General Sans', sans-serif",
                                    fontSize: 8,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-copper)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '1.5px',
                                    marginBottom: 12
                                }}>Price Performance</h3>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                                    <PerfCard label="1 Week" value={data?.performance?.['1w']} />
                                    <PerfCard label="1 Month" value={data?.performance?.['1m']} />
                                    <PerfCard label="3 Month" value={data?.performance?.['3m']} />
                                    <PerfCard label="6 Month" value={data?.performance?.['6m']} />
                                    <PerfCard label="1 Year" value={data?.performance?.['1y']} />
                                    <PerfCard label="YTD" value={data?.performance?.['ytd']} />
                                </div>
                            </div>
                        </div>

                        {/* Col 3: Sparkline Trends (Cash, Debt, Working Capital) */}
                        <div className="ticker-col-container ticker-col-3-container lg:pt-0 pt-6">
                            <h3 style={{
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 8,
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                textTransform: 'uppercase',
                                letterSpacing: '1.5px',
                                borderBottom: '1px solid var(--color-ec-border)',
                                paddingBottom: 4,
                                marginBottom: 4
                            }}>Balance Sheet Trends</h3>
                            <BalanceSheetTrendsCard data={data} />
                        </div>
                    </div>

                    {/* SEC Filings Section */}
                    <div style={{ paddingTop: 8 }}>
                        <h3 style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 8,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            textTransform: 'uppercase',
                            letterSpacing: '1.5px',
                            marginBottom: 16
                        }}>Latest SEC Filings</h3>
                        
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                            gap: 24
                        }}>
                            <FilingList title="Financials (10-K/Q)" items={filings?.financials} />
                            <FilingList title="News & Events (8-K)" items={filings?.news} />
                            <FilingList title="Offerings (424B/S-1)" items={filings?.prospectuses} />
                            <FilingList title="Ownership (13G/D, 3/4)" items={filings?.ownership} />
                            <FilingList title="Proxies (14A)" items={filings?.proxies} />
                            <FilingList title="Other Forms" items={filings?.others} />
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

// Sub-components with clean unboxed styling
const MetricCard = ({ title, value, subtext, icon, indicatorColor }: any) => (
    <div style={{
        padding: '12px 0',
        borderBottom: '1px solid var(--color-ec-border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 4
    }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {indicatorColor && <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: indicatorColor }} />}
                <span style={{
                    fontFamily: "'General Sans', sans-serif",
                    fontSize: 8,
                    fontWeight: 700,
                    color: 'var(--color-ec-text-secondary)',
                    textTransform: 'uppercase',
                    letterSpacing: '1px'
                }}>{title}</span>
            </div>
            <span style={{ color: 'var(--color-ec-text-muted)', opacity: 0.6 }}>{icon}</span>
        </div>
        <div style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 20,
            fontWeight: 700,
            color: 'var(--color-ec-text-primary)',
            letterSpacing: '-0.5px'
        }}>{value}</div>
        {subtext && <div style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 9,
            fontWeight: 600,
            color: 'var(--color-ec-text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.5px'
        }}>{subtext}</div>}
    </div>
);

const InfoItem = ({ label, value }: any) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 8,
            fontWeight: 700,
            color: 'var(--color-ec-text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.5px'
        }}>{label}</span>
        <span style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--color-ec-text-primary)'
        }}>{value || '-'}</span>
    </div>
);

const StatRow = ({ label, value }: any) => (
    <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 0',
        borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 30%, transparent)'
    }}>
        <span style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 10,
            fontWeight: 500,
            color: 'var(--color-ec-text-secondary)',
            textTransform: 'uppercase',
            letterSpacing: '0.5px'
        }}>{label}</span>
        <span style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 12,
            fontWeight: 700,
            color: 'var(--color-ec-text-primary)'
        }}>{value}</span>
    </div>
);

const PerfCard = ({ label, value }: any) => {
    if (value === null || value === undefined) {
        return (
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '8px',
                border: '1px solid var(--color-ec-border)',
                borderRadius: '4px',
                opacity: 0.5
            }}>
                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</span>
                <span style={{ fontSize: 12, fontWeight: 600 }}>-</span>
            </div>
        );
    }

    const isPos = value >= 0;
    const color = isPos ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)';
    
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: '8px',
            border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
            backgroundColor: `color-mix(in srgb, ${color} 4%, transparent)`,
            borderRadius: '4px'
        }}>
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 8,
                fontWeight: 600,
                color: 'var(--color-ec-text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                marginBottom: 2
            }}>{label}</span>
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 12,
                fontWeight: 700,
                color: color,
                display: 'flex',
                alignItems: 'center',
                gap: 2
            }}>
                {isPos ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                {Math.abs(value).toFixed(2)}%
            </span>
        </div>
    );
};

const SparklineCard = ({ title, value, data, color, indicatorColor }: any) => (
    <div style={{
        padding: '12px 0',
        borderBottom: '1px solid var(--color-ec-border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 8
    }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {indicatorColor && <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: indicatorColor }} />}
            <span style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 8,
                fontWeight: 700,
                color: 'var(--color-ec-text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '1px'
            }}>{title}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
            <div style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 20,
                fontWeight: 700,
                color: 'var(--color-ec-text-primary)',
                letterSpacing: '-0.5px'
            }}>{value}</div>
        </div>
        <div style={{ marginTop: 4 }}>
            <Sparkline data={data} color={color} />
        </div>
    </div>
);

const FilingList = ({ title, items }: any) => {
    if (!items || items.length === 0) return null;
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            maxHeight: '260px',
            overflowY: 'auto',
            paddingRight: 6
        }}>
            <h4 style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: 9,
                fontWeight: 700,
                color: 'var(--color-ec-copper)',
                textTransform: 'uppercase',
                letterSpacing: '1px',
                position: 'sticky',
                top: 0,
                backgroundColor: 'var(--color-ec-bg-base)',
                padding: '4px 0',
                margin: 0,
                borderBottom: '1px solid var(--color-ec-border)',
                zIndex: 5
            }}>{title}</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {items.map((item: any, i: number) => (
                    <a 
                        key={i}
                        href={item.link} 
                        target="_blank" 
                        rel="noopener noreferrer" 
                        className="transition-all hover:bg-[var(--color-ec-bg-sidebar)]"
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 2,
                            padding: '6px 8px',
                            borderRadius: '4px',
                            borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                            textDecoration: 'none'
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                            <span style={{
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 11,
                                fontWeight: 700,
                                color: 'var(--color-ec-copper-bright)'
                            }}>{item.type}</span>
                            <span style={{
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 9,
                                color: 'var(--color-ec-text-muted)'
                            }}>{item.date}</span>
                        </div>
                        <div style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 10,
                            color: 'var(--color-ec-text-secondary)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            opacity: 0.85
                        }} title={item.title}>
                            {item.title}
                        </div>
                    </a>
                ))}
            </div>
        </div>
    );
};
