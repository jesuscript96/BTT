"use client";

import React, { useState, useEffect, useRef } from 'react';
import {
    Activity, Users, ArrowUpRight, ArrowDownRight, ExternalLink, ChevronDown, ChevronUp, Search
} from 'lucide-react';
import { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts';
import {
    getTickerAnalysis,
    getTickerSecFilings,
    getTickerChart,
    getTickerBalanceSheet,
    getTickerGapStats,
    getTickerFinvizNews,
    getTickerLogo,
    type TickerLogoData
} from '@/lib/api';

interface TickerAnalysisProps {
    ticker?: string;
    availableTickers: string[]; // For the combobox
}

interface TickerAnalysisData {
    profile?: {
        sector?: string | null;
        industry?: string | null;
        website?: string | null;
        description?: string | null;
        employees?: number | null;
        country?: string | null;
        exchange?: string | null;
        name?: string | null;
        logo_url?: string | null;
    };
    market?: {
        market_cap?: number | null;
        shares_outstanding?: number | null;
        float_shares?: number | null;
        held_percent_insiders?: number | null;
        held_percent_institutions?: number | null;
        price?: number | null;
    };
    financials?: {
        enterprise_value?: number | null;
        cash?: number | null;
        total_debt?: number | null;
        eps?: number | null;
        working_capital?: number | null;
        ebitda?: number | null;
    };
    performance?: {
        [key: string]: number | null;
    };
    charts?: {
        cash_history?: FinancialHistoryPoint[];
        debt_history?: FinancialHistoryPoint[];
        working_capital_history?: FinancialHistoryPoint[];
    };
    daily_history?: DailyDataPoint[];
    know_the_float?: FloatData;
    gap_stats?: GapStats;
    gap_stats_plus_1?: GapStats;
    gap_stats_plus_2?: GapStats;
}

interface FilingsData {
    financials?: FilingItem[];
    news?: FilingItem[];
    prospectuses?: FilingItem[];
    ownership?: FilingItem[];
    proxies?: FilingItem[];
    others?: FilingItem[];
}

interface DailyDataPoint {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

interface FinvizNewsItem {
    date: string;
    time: string;
    title: string;
    link: string;
    source: string;
    sentiment?: string | null;
    description?: string;
    image_url?: string;
}

function SentimentBadge({ sentiment }: { sentiment?: string | null }) {
    if (!sentiment) return null;
    const s = sentiment.toLowerCase();
    const map: Record<string, { bg: string; fg: string; label: string }> = {
        positive: { bg: 'rgba(34,197,94,0.18)', fg: '#22c55e', label: 'BULLISH' },
        bullish:  { bg: 'rgba(34,197,94,0.18)', fg: '#22c55e', label: 'BULLISH' },
        negative: { bg: 'rgba(239,68,68,0.18)', fg: '#ef4444', label: 'BEARISH' },
        bearish:  { bg: 'rgba(239,68,68,0.18)', fg: '#ef4444', label: 'BEARISH' },
        neutral:  { bg: 'rgba(148,163,184,0.18)', fg: '#94a3b8', label: 'NEUTRAL' },
    };
    const cfg = map[s];
    if (!cfg) return null;
    return (
        <span style={{
            fontSize: 8,
            fontWeight: 700,
            padding: '1px 5px',
            borderRadius: 3,
            backgroundColor: cfg.bg,
            color: cfg.fg,
            letterSpacing: '0.5px',
            flexShrink: 0,
        }}>
            {cfg.label}
        </span>
    );
}

interface FloatSourceData {
    float?: string;
    short_percent?: string;
    outstanding?: string;
}

interface FloatData {
    [source: string]: FloatSourceData;
}

interface ChartPoint {
    bin: string;
    avg_change_pct: number;
    is_premarket: boolean;
}

interface GapStats {
    source: string;
    gap_days_count: number;
    high_rth_spike_avg: number | null;
    low_rth_spike_avg: number | null;
    pm_fade_avg: number | null;
    rthh_fade_avg: number | null;
    neg_close_freq: number | null;
    close_above_pmh_freq: number | null;
    close_below_vwap_freq: number | null;
    price_change_chart?: ChartPoint[];
}

interface FinancialHistoryPoint {
    date: string;
    value: number | null;
}

interface MetricCardProps {
    title: string;
    value: string;
    subtext?: string;
    icon?: React.ReactNode;
    indicatorColor?: string;
}

interface InfoItemProps {
    label: string;
    value?: string | number | null;
}

interface StatRowProps {
    label: string;
    value: string | number | null;
}

interface PerfCardProps {
    label: string;
    value?: number | null;
}

interface FilingItem {
    type: string;
    title: string;
    date: string;
    link: string;
}

interface FilingListProps {
    title: string;
    items?: FilingItem[];
}

// Pure utility helpers for numbers and percentages
const formatNumber = (num: number | null | undefined) => {
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

const formatPercent = (num: number | null | undefined) => {
    if (num === null || num === undefined) return '-';
    return `${(num * 100).toFixed(2)}%`;
};

// Helper to parse Lightweight Charts time objects or YYYY-MM-DD strings to millisecond timestamps
const getTimestamp = (t: any): number | null => {
    if (!t) return null;
    if (typeof t === 'string') {
        const parts = t.split('-');
        if (parts.length === 3) {
            return Date.UTC(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        }
        return new Date(t).getTime();
    }
    if (typeof t === 'number') {
        if (t < 5e10) return t * 1000; // UNIX timestamp in seconds
        return t; // UNIX timestamp in ms
    }
    if (t.year && t.month && t.day) {
        return Date.UTC(t.year, t.month - 1, t.day);
    }
    return null;
};

// Lightweight-charts Daily Candlestick Stock Chart
const DailyStockChart = ({ 
    dailyData,
    finvizNews,
    filings
}: { 
    dailyData?: DailyDataPoint[];
    finvizNews?: FinvizNewsItem[];
    filings?: FilingsData | null;
}) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [activeTab, setActiveTab] = useState<'chart' | 'gapList'>('chart');
    const [expandedDate, setExpandedDate] = useState<string | null>(null);

    // Keep chart references in refs so we can access them in the redraw function
    // without triggering full chart rebuilds on zoom/pan updates.
    const chartRef = useRef<any>(null);
    const candleSeriesRef = useRef<any>(null);

    const redrawVolumeProfile = () => {
        const chart = chartRef.current;
        const candleSeries = candleSeriesRef.current;
        const canvas = canvasRef.current;
        if (!chart || !candleSeries || !canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (!dailyData || dailyData.length === 0) return;

        // Set up High-DPI scaling
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        // Get visible logical/time range
        const visibleRange = chart.timeScale().getVisibleRange();
        if (!visibleRange) return;

        const fromTs = getTimestamp(visibleRange.from);
        const toTs = getTimestamp(visibleRange.to);
        if (!fromTs || !toTs) return;

        // Filter daily data points within the visible range
        const visibleData = dailyData.filter(d => {
            const ts = getTimestamp(d.time);
            return ts !== null && ts >= fromTs && ts <= toTs;
        });

        if (visibleData.length === 0) return;

        // Calculate visible price range
        let minPrice = Infinity;
        let maxPrice = -Infinity;
        for (const d of visibleData) {
            if (d.low < minPrice) minPrice = d.low;
            if (d.high > maxPrice) maxPrice = d.high;
        }

        if (minPrice === Infinity || maxPrice === -Infinity || minPrice === maxPrice) return;

        // Distribute prices into 24 equal buckets
        const numBuckets = 24;
        const bucketSize = (maxPrice - minPrice) / numBuckets;
        const buckets = Array.from({ length: numBuckets }, () => ({
            volume: 0,
            upVolume: 0,
            downVolume: 0
        }));

        for (const d of visibleData) {
            const overlappingIndices: number[] = [];
            for (let i = 0; i < numBuckets; i++) {
                const bMin = minPrice + i * bucketSize;
                const bMax = bMin + bucketSize;
                if (d.low <= bMax && d.high >= bMin) {
                    overlappingIndices.push(i);
                }
            }

            if (overlappingIndices.length > 0) {
                // Distribute volume equally among all buckets overlapping the daily candle range
                const volPerBucket = d.volume / overlappingIndices.length;
                for (const idx of overlappingIndices) {
                    buckets[idx].volume += volPerBucket;
                    if (d.close >= d.open) {
                        buckets[idx].upVolume += volPerBucket;
                    } else {
                        buckets[idx].downVolume += volPerBucket;
                    }
                }
            }
        }

        // Find Point of Control (POC) bucket (max volume)
        let maxBucketVol = 0;
        let pocIndex = 0;
        for (let i = 0; i < numBuckets; i++) {
            if (buckets[i].volume > maxBucketVol) {
                maxBucketVol = buckets[i].volume;
                pocIndex = i;
            }
        }

        if (maxBucketVol === 0) return;

        // Render horizontal bars on the left side (up to 30% of chart width)
        const maxBarWidth = rect.width * 0.3;

        for (let i = 0; i < numBuckets; i++) {
            const bMin = minPrice + i * bucketSize;
            const bMax = bMin + bucketSize;

            const yMin = candleSeries.priceToCoordinate(bMin);
            const yMax = candleSeries.priceToCoordinate(bMax);

            if (yMin !== null && yMax !== null) {
                const y = yMax;
                const height = yMin - yMax;

                if (height <= 0) continue;

                const b = buckets[i];
                const barWidth = (b.volume / maxBucketVol) * maxBarWidth;

                if (i === pocIndex) {
                    // Highlight POC bucket in copper
                    ctx.fillStyle = 'rgba(216, 122, 61, 0.25)';
                    ctx.fillRect(0, y, barWidth, height);
                    ctx.strokeStyle = 'rgba(216, 122, 61, 0.6)';
                    ctx.lineWidth = 1;
                    ctx.strokeRect(0, y, barWidth, height);
                } else {
                    // Render split volume (up vs down)
                    const upWidth = b.volume > 0 ? (b.upVolume / b.volume) * barWidth : 0;
                    const downWidth = barWidth - upWidth;

                    // Green for up/buy volume
                    ctx.fillStyle = 'rgba(74, 157, 127, 0.25)';
                    ctx.fillRect(0, y, upWidth, height);

                    // Red for down/sell volume
                    ctx.fillStyle = 'rgba(201, 77, 63, 0.25)';
                    ctx.fillRect(upWidth, y, downWidth, height);
                }
            }
        }

        // Draw POC reference line across the chart
        const pocPrice = minPrice + pocIndex * bucketSize + bucketSize / 2;
        const pocY = candleSeries.priceToCoordinate(pocPrice);
        if (pocY !== null) {
            ctx.beginPath();
            ctx.setLineDash([4, 4]);
            ctx.strokeStyle = 'rgba(216, 122, 61, 0.8)';
            ctx.lineWidth = 1.5;
            ctx.moveTo(0, pocY);
            ctx.lineTo(rect.width - 60, pocY);
            ctx.stroke();
            ctx.setLineDash([]); // Reset dash

            // Draw POC text label
            ctx.fillStyle = '#D87A3D';
            ctx.font = 'bold 9px "General Sans", sans-serif';
            ctx.fillText('POC', rect.width - 55, pocY + 3);
        }
    };

    // Keep chart container layout in sync when tabs change
    useEffect(() => {
        if (activeTab === 'chart') {
            const timer = setTimeout(() => {
                const chart = chartRef.current;
                if (chart && chartContainerRef.current) {
                    chart.applyOptions({ width: chartContainerRef.current.clientWidth });
                }
                redrawVolumeProfile();
            }, 50);
            return () => clearTimeout(timer);
        }
    }, [activeTab]);

    useEffect(() => {
        if (!chartContainerRef.current || !dailyData || dailyData.length === 0) return;

        chartContainerRef.current.innerHTML = '';

        const chart = createChart(chartContainerRef.current, {
            width: chartContainerRef.current.clientWidth,
            height: 480,
            layout: {
                background: { type: ColorType.Solid, color: '#16181A' },
                textColor: '#ffffff',
                fontFamily: "'General Sans', sans-serif",
                fontSize: 10
            },
            grid: {
                vertLines: { color: '#2C2F33' },
                horzLines: { color: '#2C2F33' }
            },
            crosshair: { mode: 0 },
            rightPriceScale: {
                borderColor: '#2C2F33',
            },
            timeScale: {
                borderColor: '#2C2F33',
                timeVisible: false,
            },
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#10b981',
            downColor: '#ef4444',
            borderDownColor: '#ef4444',
            borderUpColor: '#10b981',
            wickDownColor: '#ef4444',
            wickUpColor: '#10b981',
        });

        const formattedCandles = dailyData.map(d => ({
            time: d.time,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
        }));
        candleSeries.setData(formattedCandles);

        // Save chart/series in refs
        chartRef.current = chart;
        candleSeriesRef.current = candleSeries;

        // Set markers for gap days (gap_pct >= 20.0%)
        const markers = [];
        for (let i = 1; i < dailyData.length; i++) {
            const prevClose = dailyData[i - 1].close;
            const currentOpen = dailyData[i].open;
            if (prevClose > 0) {
                const gapPct = ((currentOpen - prevClose) / prevClose) * 100;
                if (gapPct >= 20.0) {
                    markers.push({
                        time: dailyData[i].time,
                        position: 'aboveBar' as const,
                        color: '#D87A3D',
                        shape: 'arrowDown' as const,
                        text: `GAP (${gapPct.toFixed(0)}%)`,
                        size: 2,
                    });
                }
            }
        }
        if (markers.length > 0) {
            createSeriesMarkers(candleSeries, markers);
        }

        // Volume overlay
        const volumeSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
        });
        const formattedVolume = dailyData.map(d => ({
            time: d.time,
            value: d.volume,
            color: d.close >= d.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)',
        }));
        volumeSeries.setData(formattedVolume);

        // Calculate and plot VWAP (Volume Weighted Average Price)
        let cumulativeVolume = 0;
        let cumulativeTPV = 0;
        const vwapData = dailyData.map(d => {
            const tp = (d.high + d.low + d.close) / 3;
            cumulativeVolume += d.volume;
            cumulativeTPV += tp * d.volume;
            return {
                time: d.time,
                value: cumulativeVolume > 0 ? (cumulativeTPV / cumulativeVolume) : tp
            };
        });

        const vwapSeries = chart.addSeries(LineSeries, {
            color: '#D87A3D',
            lineWidth: 2,
            title: 'VWAP',
        });
        vwapSeries.setData(vwapData);

        chart.timeScale().fitContent();

        // Subscribe to range/zoom updates
        chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            redrawVolumeProfile();
        });

        // Trigger an initial redraw after the chart layouts
        const timer = setTimeout(() => {
            redrawVolumeProfile();
        }, 50);

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
                setTimeout(redrawVolumeProfile, 0);
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            clearTimeout(timer);
            window.removeEventListener('resize', handleResize);
            chart.remove();
            chartRef.current = null;
            candleSeriesRef.current = null;
        };
    }, [dailyData]);

    if (!dailyData || dailyData.length === 0) {
        return (
            <div style={{
                height: '420px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-ec-text-muted)',
                fontSize: '11px',
                border: '1px dashed var(--color-ec-border)',
                borderRadius: '6px'
            }}>
                No daily chart data available.
            </div>
        );
    }

    // Calculate gap days from dailyData (gap_pct >= 20.0%)
    const gaps: Array<{
        time: string;
        gapPct: number;
        open: number;
        high: number;
        low: number;
        close: number;
        isPositive: boolean;
    }> = [];
    
    if (dailyData && dailyData.length > 1) {
        for (let i = 1; i < dailyData.length; i++) {
            const prevClose = dailyData[i - 1].close;
            const d = dailyData[i];
            if (prevClose > 0) {
                const gapPct = ((d.open - prevClose) / prevClose) * 100;
                if (gapPct >= 20.0) {
                    gaps.push({
                        time: d.time,
                        gapPct,
                        open: d.open,
                        high: d.high,
                        low: d.low,
                        close: d.close,
                        isPositive: d.close >= d.open
                    });
                }
            }
        }
    }
    // Sort gaps descending by date (most recent first)
    gaps.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                borderBottom: '1px solid var(--color-ec-border)',
                paddingBottom: 4
            }}>
                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
                    Daily Stock Chart
                </span>

                {/* Sub-tabs toggle */}
                <div style={{ display: 'flex', gap: 4 }}>
                    {(['chart', 'gapList'] as const).map(tab => {
                        const label = tab === 'chart' ? 'Chart' : 'Gap List';
                        const isActive = activeTab === tab;
                        return (
                            <button
                                key={tab}
                                onClick={() => setActiveTab(tab)}
                                style={{
                                    background: isActive ? 'var(--color-ec-copper)' : 'transparent',
                                    border: 'none',
                                    borderRadius: 3,
                                    color: isActive ? '#ffffff' : 'var(--color-ec-text-secondary)',
                                    fontSize: 8,
                                    fontWeight: 700,
                                    padding: '2px 6px',
                                    cursor: 'pointer',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.5px',
                                    transition: 'all 150ms ease'
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-high)';
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-secondary)';
                                }}
                            >
                                {label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Chart view container (always in DOM to keep zoom/pan layout state) */}
            <div style={{ 
                position: 'relative', 
                width: '100%', 
                height: '480px',
                display: activeTab === 'chart' ? 'block' : 'none'
            }}>
                <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
                <canvas ref={canvasRef} style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 10 }} />
            </div>

            {/* Gap List view container */}
            {activeTab === 'gapList' && (
                <div style={{ 
                    overflowY: 'auto', 
                    width: '100%', 
                    height: '480px',
                    border: '1px solid var(--color-ec-border)',
                    borderRadius: 6,
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    padding: '8px 12px'
                }}>
                    {gaps.length === 0 ? (
                        <div style={{
                            height: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: 'var(--color-ec-text-muted)',
                            fontSize: '11px'
                        }}>
                            No gap days detected (gap &ge; 20.0%).
                        </div>
                    ) : (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: "'General Sans', sans-serif" }}>
                            <thead>
                                <tr style={{ borderBottom: '1px solid var(--color-ec-border)', textAlign: 'left', position: 'sticky', top: 0, backgroundColor: 'var(--color-ec-bg-sidebar)', zIndex: 1 }}>
                                    <th style={{ padding: '6px 4px 6px 0', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600 }}>Date</th>
                                    <th style={{ padding: '6px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Gap %</th>
                                    <th style={{ padding: '6px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Open</th>
                                    <th style={{ padding: '6px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>High</th>
                                    <th style={{ padding: '6px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Low</th>
                                    <th style={{ padding: '6px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Close</th>
                                    <th style={{ padding: '6px 0 6px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Close Dir</th>
                                </tr>
                            </thead>
                            <tbody>
                                {gaps.map((gap, index) => {
                                    const isExpanded = expandedDate === gap.time;
                                    let dayNews = finvizNews?.filter(item => item.date === gap.time) || [];
                                    if (dayNews.length === 0 && filings) {
                                        const dateFilings: any[] = [];
                                        if (filings.news) {
                                            filings.news.forEach((f: any) => {
                                                if (f.date === gap.time) {
                                                    dateFilings.push({
                                                        time: "SEC",
                                                        source: f.type,
                                                        title: f.title,
                                                        link: f.link
                                                    });
                                                }
                                            });
                                        }
                                        if (filings.prospectuses) {
                                            filings.prospectuses.forEach((f: any) => {
                                                if (f.date === gap.time) {
                                                    dateFilings.push({
                                                        time: "SEC",
                                                        source: f.type,
                                                        title: f.title,
                                                        link: f.link
                                                    });
                                                }
                                            });
                                        }
                                        dayNews = dateFilings;
                                    }

                                    return (
                                        <React.Fragment key={index}>
                                            <tr 
                                                onClick={() => setExpandedDate(isExpanded ? null : gap.time)}
                                                style={{ 
                                                    borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                                                    cursor: 'pointer',
                                                    backgroundColor: isExpanded ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                                                    transition: 'background-color 150ms ease'
                                                }}
                                                onMouseEnter={(e) => {
                                                    if (!isExpanded) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
                                                }}
                                                onMouseLeave={(e) => {
                                                    if (!isExpanded) e.currentTarget.style.backgroundColor = 'transparent';
                                                }}
                                            >
                                                <td style={{ padding: '6px 4px 6px 0', fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>{gap.time}</td>
                                                <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-copper-bright)' }}>+{gap.gapPct.toFixed(2)}%</td>
                                                <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 500, color: 'var(--color-ec-text-high)' }}>${gap.open.toFixed(2)}</td>
                                                <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 500, color: 'var(--color-ec-text-secondary)' }}>${gap.high.toFixed(2)}</td>
                                                <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 500, color: 'var(--color-ec-text-secondary)' }}>${gap.low.toFixed(2)}</td>
                                                <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 500, color: 'var(--color-ec-text-high)' }}>${gap.close.toFixed(2)}</td>
                                                <td style={{ 
                                                    padding: '6px 0 6px 4px', 
                                                    textAlign: 'right', 
                                                    fontWeight: 700, 
                                                    color: gap.isPositive ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)' 
                                                }}>
                                                    {gap.isPositive ? 'Positive' : 'Negative'}
                                                </td>
                                            </tr>
                                            {isExpanded && (
                                                <tr style={{ backgroundColor: 'var(--color-ec-bg-base)' }}>
                                                    <td colSpan={7} style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-ec-border)' }}>
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                                            <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                                                News for {gap.time}
                                                            </span>
                                                            {dayNews.length === 0 ? (
                                                                <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>
                                                                    No news
                                                                </span>
                                                            ) : (
                                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
                                                                    {dayNews.map((news, nIdx) => (
                                                                        <div key={nIdx} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 10 }}>
                                                                            <span style={{ color: 'var(--color-ec-text-muted)', fontWeight: 600, flexShrink: 0 }}>
                                                                                {news.time}
                                                                            </span>
                                                                            {news.source && (
                                                                                <span style={{ color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, flexShrink: 0 }}>
                                                                                    [{news.source}]
                                                                                </span>
                                                                            )}
                                                                            <SentimentBadge sentiment={news.sentiment} />
                                                                            <a
                                                                                href={news.link}
                                                                                target="_blank"
                                                                                rel="noopener noreferrer"
                                                                                style={{
                                                                                    color: 'var(--color-ec-copper-bright)',
                                                                                    textDecoration: 'none',
                                                                                    fontWeight: 500,
                                                                                    lineHeight: 1.3
                                                                                }}
                                                                                onClick={(e) => e.stopPropagation()} // Prevent collapsing when clicking the link
                                                                                className="hover:underline hover:text-white transition-colors"
                                                                            >
                                                                                {news.title}
                                                                            </a>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </td>
                                                </tr>
                                            )}
                                        </React.Fragment>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>
            )}
        </div>
    );
};

// KnowTheFloat comparison table
const KnowTheFloatTable = ({ floatData }: { floatData?: FloatData }) => {
    if (!floatData || Object.keys(floatData).length === 0) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px', borderBottom: '1px solid var(--color-ec-border)', paddingBottom: 4 }}>
                    Float Comparison
                </span>
                <div style={{
                    height: '130px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--color-ec-text-muted)',
                    fontSize: '11px',
                    border: '1px dashed var(--color-ec-border)',
                    borderRadius: '6px'
                }}>
                    No float comparisons available for this ticker.
                </div>
            </div>
        );
    }

    const sources = ["Yahoo Finance", "Finviz", "Wall Street Journal", "Dilution Tracker"];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
            <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px', borderBottom: '1px solid var(--color-ec-border)', paddingBottom: 4 }}>
                Float Comparison
            </span>
            <div style={{ overflowX: 'auto', width: '100%', height: '130px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: "'General Sans', sans-serif" }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--color-ec-border)', textAlign: 'left' }}>
                            <th style={{ padding: '4px 4px 4px 0', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600 }}>Source</th>
                            <th style={{ padding: '4px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Float</th>
                            <th style={{ padding: '4px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Short I.%</th>
                            <th style={{ padding: '4px 0 4px 4px', color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, textAlign: 'right' }}>Outstanding</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sources.map(src => {
                            const sData = (floatData && floatData[src]) || { float: '-', short_percent: '-', outstanding: '-' };
                            return (
                                <tr key={src} style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)' }}>
                                    <td style={{ padding: '4px 4px 4px 0', fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>{src}</td>
                                    <td style={{ padding: '4px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-text-high)' }}>{sData.float || '-'}</td>
                                    <td style={{ padding: '4px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-loss)' }}>{sData.short_percent || '-'}</td>
                                    <td style={{ padding: '4px 0 4px 4px', textAlign: 'right', fontWeight: 600, color: 'var(--color-ec-text-high)' }}>{sData.outstanding || '-'}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

const AvgPriceChangeChart = ({ data }: { data?: ChartPoint[] }) => {
    if (!data || data.length === 0) {
        return (
            <div style={{
                height: '170px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-ec-text-muted)',
                fontSize: '13px',
                border: '1px dashed rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                width: '100%'
            }}>
                No hay datos de intradía
            </div>
        );
    }

    const viewBoxW = 240;
    const viewBoxH = 150;
    const paddingLeft = 48;
    const paddingRight = 10;
    const paddingTop = 8;
    const paddingBottom = 28;

    const W = viewBoxW - paddingLeft - paddingRight;
    const H = viewBoxH - paddingTop - paddingBottom;

    const values = data.map(d => d.avg_change_pct);
    let minY = Math.min(0, ...values);
    let maxY = Math.max(0, ...values);
    
    if (maxY - minY < 1.0) {
        const center = (maxY + minY) / 2;
        minY = center - 0.5;
        maxY = center + 0.5;
    } else {
        const diff = maxY - minY;
        minY -= diff * 0.15;
        maxY += diff * 0.15;
    }

    const points = data.map((d, i) => {
        const x = paddingLeft + (i / (data.length - 1)) * W;
        const y_pct = (d.avg_change_pct - minY) / (maxY - minY);
        const y = paddingTop + H - (y_pct * H);
        return { x, y, ...d };
    });

    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
    
    // Closed path for fill (going down to bottom of plot area)
    const bottomY = paddingTop + H;
    const fillPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${bottomY.toFixed(1)} L ${points[0].x.toFixed(1)} ${bottomY.toFixed(1)} Z`;

    // Last premarket index
    let lastPreIdx = -1;
    for (let i = data.length - 1; i >= 0; i--) {
        if (data[i].is_premarket) {
            lastPreIdx = i;
            break;
        }
    }
    const preWidth = lastPreIdx >= 0 ? (lastPreIdx / (data.length - 1)) * W : 0;

    // Y-Axis Ticks (3 ticks: min, 0, max)
    const yTicks = [minY, 0, maxY].filter((v, idx, self) => self.indexOf(v) === idx);

    // X-Axis Ticks (e.g. show 04:00, 09:30, 16:00)
    const getClosestIndex = (timeStr: string) => {
        let minDiff = Infinity;
        let index = -1;
        data.forEach((d, idx) => {
            const start = d.bin.split('-')[0];
            const [h, m] = start.split(':').map(Number);
            const [th, tm] = timeStr.split(':').map(Number);
            const diff = Math.abs((h * 60 + m) - (th * 60 + tm));
            if (diff < minDiff) {
                minDiff = diff;
                index = idx;
            }
        });
        return index;
    };

    const xTickLabels = ["04:00", "09:30", "16:00"];
    const xTicks = xTickLabels.map(label => {
        const idx = getClosestIndex(label);
        return {
            x: idx >= 0 ? paddingLeft + (idx / (data.length - 1)) * W : 0,
            label
        };
    });

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            <svg width="100%" height="100%" viewBox={`0 0 ${viewBoxW} ${viewBoxH}`} style={{ overflow: 'visible' }}>
                <defs>
                    <linearGradient id="price-change-grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--color-ec-copper)" stopOpacity="0.15" />
                        <stop offset="100%" stopColor="var(--color-ec-copper)" stopOpacity="0.0" />
                    </linearGradient>
                </defs>

                {/* Shaded Premarket Area */}
                {preWidth > 0 && (
                    <>
                        <rect
                            x={paddingLeft}
                            y={paddingTop}
                            width={preWidth}
                            height={H}
                            fill="rgba(255, 255, 255, 0.02)"
                        />
                        <line
                            x1={paddingLeft + preWidth}
                            y1={paddingTop}
                            x2={paddingLeft + preWidth}
                            y2={paddingTop + H}
                            stroke="rgba(255, 255, 255, 0.1)"
                            strokeWidth="0.8"
                            strokeDasharray="2,2"
                        />
                        <text
                            x={paddingLeft + preWidth / 2}
                            y={paddingTop + 10}
                            textAnchor="middle"
                            fill="var(--color-ec-text-muted)"
                            style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.5px' }}
                        >
                            PRE
                        </text>
                        <text
                            x={paddingLeft + preWidth + (W - preWidth) / 2}
                            y={paddingTop + 10}
                            textAnchor="middle"
                            fill="var(--color-ec-text-muted)"
                            style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.5px' }}
                        >
                            RTH
                        </text>
                    </>
                )}

                {/* Horizontal grid lines */}
                {yTicks.map((tickVal, idx) => {
                    const y_pct = (tickVal - minY) / (maxY - minY);
                    const y = paddingTop + H - (y_pct * H);
                    const isZero = Math.abs(tickVal) < 0.0001;
                    return (
                        <g key={idx}>
                            <line
                                x1={paddingLeft}
                                y1={y}
                                x2={paddingLeft + W}
                                y2={y}
                                stroke={isZero ? "rgba(255, 255, 255, 0.15)" : "rgba(255, 255, 255, 0.05)"}
                                strokeWidth={isZero ? 1.0 : 0.5}
                                strokeDasharray={isZero ? undefined : "2,4"}
                            />
                            <text
                                x={paddingLeft - 8}
                                y={y + 4}
                                textAnchor="end"
                                fill="var(--color-ec-text-muted)"
                                style={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 600 }}
                            >
                                {tickVal >= 0 ? '+' : ''}{tickVal.toFixed(1)}%
                            </text>
                        </g>
                    );
                })}

                {/* Closed Area Fill */}
                <path d={fillPath} fill="url(#price-change-grad)" />

                {/* Line Path */}
                <path
                    d={linePath}
                    fill="none"
                    stroke="var(--color-ec-copper)"
                    strokeWidth="1.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />

                {/* X-Axis Labels */}
                {xTicks.map((tick, idx) => (
                    <g key={idx}>
                        <line
                            x1={tick.x}
                            y1={paddingTop + H}
                            x2={tick.x}
                            y2={paddingTop + H + 3}
                            stroke="rgba(255, 255, 255, 0.2)"
                            strokeWidth="0.8"
                        />
                        <text
                            x={tick.x}
                            y={paddingTop + H + 16}
                            textAnchor="middle"
                            fill="var(--color-ec-text-secondary)"
                            style={{ fontSize: 11, fontWeight: 600 }}
                        >
                            {tick.label}
                        </text>
                    </g>
                ))}
            </svg>
        </div>
    );
};

// Gap day statistics sub-component
const GapStatsSection = ({ 
    gapStats, 
    gapStatsPlus1, 
    gapStatsPlus2 
}: { 
    gapStats?: GapStats; 
    gapStatsPlus1?: GapStats; 
    gapStatsPlus2?: GapStats; 
}) => {
    const [activeSubTab, setActiveSubTab] = useState<'day0' | 'day1' | 'day2'>('day0');
    
    const currentStats = 
        activeSubTab === 'day0' ? gapStats : 
        activeSubTab === 'day1' ? gapStatsPlus1 : 
        gapStatsPlus2;

    if (!gapStats || gapStats.gap_days_count === 0) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%', fontFamily: "'General Sans', sans-serif" }}>
                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px', borderBottom: '1px solid var(--color-ec-border)', paddingBottom: 4 }}>
                    Runner Stats (PMH ≥ 20%)
                </span>
                <div style={{
                    height: '140px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--color-ec-text-muted)',
                    fontSize: '11px',
                    border: '1px dashed var(--color-ec-border)',
                    borderRadius: '6px'
                }}>
                    No gap stats available for this ticker.
                </div>
            </div>
        );
    }

    const formatVal = (val: number | null | undefined) => {
        if (val === null || val === undefined) return '-';
        return `${val.toFixed(2)}%`;
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%', fontFamily: "'General Sans', sans-serif" }}>
            <div style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                alignItems: 'center', 
                borderBottom: '1px solid var(--color-ec-border)', 
                paddingBottom: 4 
            }}>
                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
                    Runner Stats (PMH ≥ 20%) {currentStats && currentStats.gap_days_count > 0 ? `(${currentStats.gap_days_count} runners)` : ''}
                </span>
                
                {/* Day offset sub-tabs */}
                <div style={{ display: 'flex', gap: 4 }}>
                    {(['day0', 'day1', 'day2'] as const).map(tab => {
                        const label = tab === 'day0' ? 'Day 0' : tab === 'day1' ? 'Day +1' : 'Day +2';
                        const isActive = activeSubTab === tab;
                        return (
                            <button
                                key={tab}
                                onClick={() => setActiveSubTab(tab)}
                                style={{
                                    background: isActive ? 'var(--color-ec-copper)' : 'transparent',
                                    border: 'none',
                                    borderRadius: 3,
                                    color: isActive ? '#ffffff' : 'var(--color-ec-text-secondary)',
                                    fontSize: 8,
                                    fontWeight: 700,
                                    padding: '2px 6px',
                                    cursor: 'pointer',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.5px',
                                    transition: 'all 150ms ease'
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-high)';
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-secondary)';
                                }}
                            >
                                {label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {!currentStats || currentStats.gap_days_count === 0 ? (
                <div style={{
                    height: '140px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--color-ec-text-muted)',
                    fontSize: '11px',
                    border: '1px dashed var(--color-ec-border)',
                    borderRadius: '6px',
                    marginTop: 4
                }}>
                    No stats available for this offset.
                </div>
            ) : (
                <>
                    {/* Split metrics on left, Avg Price Change Chart on right */}
                    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', width: '100%' }}>
                        {/* Metrics Column (Left side, width ~38%) */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '38%', flexShrink: 0 }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>High RTH Spike</span>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-ec-text-high)' }}>{formatVal(currentStats.high_rth_spike_avg)}</span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>% PM Fade</span>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-ec-text-high)' }}>{formatVal(currentStats.pm_fade_avg)}</span>
                            </div>
                            <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', margin: '2px 0' }} />
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Low RTH Spike</span>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-ec-text-high)' }}>{formatVal(currentStats.low_rth_spike_avg)}</span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>% RTHH Fade</span>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-ec-text-high)' }}>{formatVal(currentStats.rthh_fade_avg)}</span>
                            </div>
                        </div>

                        {/* Chart Area (Right side, width ~62%) */}
                        <div style={{ width: '62%', flexShrink: 0, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
                            <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Precio medio desde el Open</span>
                            <div style={{ height: '170px', width: '100%' }}>
                                <AvgPriceChangeChart data={currentStats.price_change_chart} />
                            </div>
                        </div>
                    </div>

                    {/* Frequencies and Progress Bars */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)', paddingTop: 4, marginTop: -4 }}>
                        {/* Negative Close Frequency (Bidirectional Bar) */}
                        {(() => {
                            const negClose = currentStats.neg_close_freq ?? 0;
                            const posClose = 100 - negClose;
                            return (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontWeight: 700 }}>
                                        <span style={{ color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Avg. close direction</span>
                                    </div>
                                    <div style={{
                                        height: 14,
                                        width: '100%',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        borderRadius: 4,
                                        overflow: 'hidden',
                                        display: 'flex',
                                        fontFamily: "'General Sans', sans-serif",
                                        fontSize: 8.5,
                                        fontWeight: 700
                                    }}>
                                        {negClose > 0 && (
                                            <div style={{
                                                height: '100%',
                                                width: `${negClose}%`,
                                                backgroundColor: 'var(--color-ec-loss)',
                                                color: '#ffffff',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'width 0.3s ease',
                                                textShadow: '0 1px 2px rgba(0,0,0,0.4)'
                                            }}>
                                                {negClose >= 10 ? `${negClose.toFixed(1)}%` : ''}
                                            </div>
                                        )}
                                        {posClose > 0 && (
                                            <div style={{
                                                height: '100%',
                                                width: `${posClose}%`,
                                                backgroundColor: 'var(--color-ec-profit)',
                                                color: '#ffffff',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'width 0.3s ease',
                                                textShadow: '0 1px 2px rgba(0,0,0,0.4)'
                                            }}>
                                                {posClose >= 10 ? `${posClose.toFixed(1)}%` : ''}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })()}

                        {/* Close Above PMH Frequency */}
                        {currentStats.close_above_pmh_freq !== null && currentStats.close_above_pmh_freq !== undefined && (() => {
                            const val = currentStats.close_above_pmh_freq ?? 0;
                            const restVal = 100 - val;
                            return (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontWeight: 700 }}>
                                        <span style={{ color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Avg. close above PMH</span>
                                    </div>
                                    <div style={{
                                        height: 14,
                                        width: '100%',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        borderRadius: 4,
                                        overflow: 'hidden',
                                        display: 'flex',
                                        fontFamily: "'General Sans', sans-serif",
                                        fontSize: 8.5,
                                        fontWeight: 700
                                    }}>
                                        {restVal > 0 && (
                                            <div style={{
                                                height: '100%',
                                                width: `${restVal}%`,
                                                backgroundColor: 'var(--color-ec-loss)',
                                                color: '#ffffff',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'width 0.3s ease',
                                                textShadow: '0 1px 2px rgba(0,0,0,0.4)'
                                            }}>
                                                {restVal >= 10 ? `${restVal.toFixed(1)}%` : ''}
                                            </div>
                                        )}
                                        {val > 0 && (
                                            <div style={{
                                                height: '100%',
                                                width: `${val}%`,
                                                backgroundColor: 'var(--color-ec-profit)',
                                                color: '#ffffff',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'width 0.3s ease',
                                                textShadow: '0 1px 2px rgba(0,0,0,0.4)'
                                            }}>
                                                {val >= 10 ? `${val.toFixed(1)}%` : ''}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })()}

                        {/* Close Below VWAP Frequency */}
                        {(() => {
                            const val = currentStats.close_below_vwap_freq ?? 0;
                            const restVal = 100 - val;
                            return (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontWeight: 700 }}>
                                        <span style={{ color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Close Below VWAP</span>
                                    </div>
                                    <div style={{
                                        height: 14,
                                        width: '100%',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        borderRadius: 4,
                                        overflow: 'hidden',
                                        display: 'flex',
                                        fontFamily: "'General Sans', sans-serif",
                                        fontSize: 8.5,
                                        fontWeight: 700
                                    }}>
                                        {val > 0 && (
                                            <div style={{
                                                height: '100%',
                                                width: `${val}%`,
                                                backgroundColor: 'var(--color-ec-loss)',
                                                color: '#ffffff',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'width 0.3s ease',
                                                textShadow: '0 1px 2px rgba(0,0,0,0.4)'
                                            }}>
                                                {val >= 10 ? `${val.toFixed(1)}%` : ''}
                                            </div>
                                        )}
                                        {restVal > 0 && (
                                            <div style={{
                                                height: '100%',
                                                width: `${restVal}%`,
                                                backgroundColor: 'var(--color-ec-profit)',
                                                color: '#ffffff',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'width 0.3s ease',
                                                textShadow: '0 1px 2px rgba(0,0,0,0.4)'
                                            }}>
                                                {restVal >= 10 ? `${restVal.toFixed(1)}%` : ''}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })()}
                    </div>
                </>
            )}
        </div>
    );
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

// SVG-based Cash & Debt grouped bar chart
const CashDebtChart = ({ cashData, debtData }: { cashData: FinancialHistoryPoint[], debtData: FinancialHistoryPoint[] }) => {
    if (!cashData && !debtData) {
        return (
            <div 
                className="animate-pulse" 
                style={{ 
                    height: '130px', 
                    width: '100%', 
                    backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                    borderRadius: '4px' 
                }} 
            />
        );
    }

    const datesSet = new Set<string>();
    cashData?.forEach((item: FinancialHistoryPoint) => datesSet.add(item.date));
    debtData?.forEach((item: FinancialHistoryPoint) => datesSet.add(item.date));
    const sortedDates = Array.from(datesSet).sort();

    if (sortedDates.length === 0) {
        return (
            <div style={{
                height: '130px',
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

    let maxVal = 1;
    sortedDates.forEach(d => {
        const cashVal = cashData?.find((item: FinancialHistoryPoint) => item.date === d)?.value ?? 0;
        const debtVal = debtData?.find((item: FinancialHistoryPoint) => item.date === d)?.value ?? 0;
        maxVal = Math.max(maxVal, Math.abs(cashVal), Math.abs(debtVal));
    });

    const svgWidth = 500;
    const svgHeight = 140;
    const marginTop = 10;
    const marginBottom = 25;
    const marginLeft = 52;
    const marginRight = 15;
    
    const chartHeight = svgHeight - marginTop - marginBottom;
    const chartWidth = svgWidth - marginLeft - marginRight;
    const zeroY = marginTop + chartHeight;
    const scale = chartHeight / maxVal;

    const groupWidth = chartWidth / sortedDates.length;
    const barWidth = 16;
    const barGap = 4;
    const totalBarsWidth = 2 * barWidth + barGap;

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
                <line x1={marginLeft} y1={marginTop} x2={svgWidth - marginRight} y2={marginTop} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.2" />
                <line x1={marginLeft} y1={marginTop + chartHeight / 2} x2={svgWidth - marginRight} y2={marginTop + chartHeight / 2} stroke="var(--color-ec-border)" strokeWidth="0.5" strokeDasharray="3 3" opacity="0.2" />

                <line x1={marginLeft} y1={marginTop} x2={marginLeft} y2={marginTop + chartHeight} stroke="var(--color-ec-border)" strokeWidth="0.5" opacity="0.5" />

                <text
                    x={marginLeft - 8}
                    y={marginTop + 5}
                    textAnchor="end"
                    fill="var(--color-ec-text-muted)"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600 }}
                >
                    {formatAxisLabel(maxVal)}
                </text>
                <text
                    x={marginLeft - 8}
                    y={zeroY + 4}
                    textAnchor="end"
                    fill="var(--color-ec-text-muted)"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600 }}
                >
                    $0
                </text>

                <line x1={marginLeft} y1={zeroY} x2={svgWidth - marginRight} y2={zeroY} stroke="var(--color-ec-border)" strokeWidth="1" />

                {sortedDates.map((d, index) => {
                    const cashVal = cashData?.find((item: FinancialHistoryPoint) => item.date === d)?.value ?? 0;
                    const debtVal = debtData?.find((item: FinancialHistoryPoint) => item.date === d)?.value ?? 0;
                    const groupStartX = marginLeft + index * groupWidth + (groupWidth - totalBarsWidth) / 2;

                    const cashH = cashVal * scale;
                    const cashY = zeroY - cashH;

                    const debtH = debtVal * scale;
                    const debtY = zeroY - debtH;

                    return (
                        <g key={d}>
                            <rect x={groupStartX} y={cashY} width={barWidth} height={Math.max(cashH, 1)} fill="var(--color-ec-profit)" rx="1" opacity="0.9" />
                            <rect x={groupStartX + barWidth + barGap} y={debtY} width={barWidth} height={Math.max(debtH, 1)} fill="var(--color-ec-loss)" rx="1" opacity="0.9" />

                            <text
                                x={marginLeft + index * groupWidth + groupWidth / 2}
                                y={svgHeight - 6}
                                textAnchor="middle"
                                fill="var(--color-ec-text-muted)"
                                style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}
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

// SVG-based Working Capital bar chart (supports negative values)
const WorkingCapitalChart = ({ wcData }: { wcData: FinancialHistoryPoint[] }) => {
    if (!wcData) {
        return (
            <div 
                className="animate-pulse" 
                style={{ 
                    height: '130px', 
                    width: '100%', 
                    backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                    borderRadius: '4px' 
                }} 
            />
        );
    }

    const datesSet = new Set<string>();
    wcData?.forEach((item: FinancialHistoryPoint) => datesSet.add(item.date));
    const sortedDates = Array.from(datesSet).sort();

    if (sortedDates.length === 0) {
        return (
            <div style={{
                height: '130px',
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

    let maxVal = 1;
    let hasNegative = false;
    sortedDates.forEach(d => {
        const wcVal = wcData?.find((item: FinancialHistoryPoint) => item.date === d)?.value ?? 0;
        if (wcVal < 0) hasNegative = true;
        maxVal = Math.max(maxVal, Math.abs(wcVal));
    });

    const svgWidth = 500;
    const svgHeight = 140;
    const marginTop = 10;
    const marginBottom = 25;
    const marginLeft = 52;
    const marginRight = 15;
    
    const chartHeight = svgHeight - marginTop - marginBottom;
    const chartWidth = svgWidth - marginLeft - marginRight;

    const zeroY = hasNegative ? marginTop + chartHeight / 2 : marginTop + chartHeight;
    const scale = hasNegative ? (chartHeight / 2) / maxVal : chartHeight / maxVal;

    const groupWidth = chartWidth / sortedDates.length;
    const barWidth = 18;

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

                <line x1={marginLeft} y1={marginTop} x2={marginLeft} y2={marginTop + chartHeight} stroke="var(--color-ec-border)" strokeWidth="0.5" opacity="0.5" />

                <text
                    x={marginLeft - 8}
                    y={marginTop + 5}
                    textAnchor="end"
                    fill="var(--color-ec-text-muted)"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600 }}
                >
                    {formatAxisLabel(maxVal)}
                </text>
                <text
                    x={marginLeft - 8}
                    y={zeroY + 4}
                    textAnchor="end"
                    fill="var(--color-ec-text-muted)"
                    style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600 }}
                >
                    $0
                </text>
                {hasNegative && (
                    <text
                        x={marginLeft - 8}
                        y={marginTop + chartHeight + 3}
                        textAnchor="end"
                        fill="var(--color-ec-text-muted)"
                        style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600 }}
                    >
                        {formatAxisLabel(-maxVal)}
                    </text>
                )}

                <line x1={marginLeft} y1={zeroY} x2={svgWidth - marginRight} y2={zeroY} stroke="var(--color-ec-border)" strokeWidth="1" />

                {sortedDates.map((d, index) => {
                    const wcVal = wcData?.find((item: FinancialHistoryPoint) => item.date === d)?.value ?? 0;
                    const groupStartX = marginLeft + index * groupWidth + (groupWidth - barWidth) / 2;

                    const wcH = Math.abs(wcVal) * scale;
                    const wcY = wcVal >= 0 ? zeroY - wcH : zeroY;

                    return (
                        <g key={d}>
                            <rect x={groupStartX} y={wcY} width={barWidth} height={Math.max(wcH, 1)} fill="#3b82f6" rx="1" opacity="0.9" />

                            <text
                                x={marginLeft + index * groupWidth + groupWidth / 2}
                                y={svgHeight - 6}
                                textAnchor="middle"
                                fill="var(--color-ec-text-muted)"
                                style={{ fontFamily: "'General Sans', sans-serif", fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}
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

// Unified Balance Sheet Trends Card component containing two separate charts
const BalanceSheetTrendsCard = ({ data }: { data: TickerAnalysisData | null }) => {
    return (
        <div style={{
            padding: '8px 0',
            display: 'flex',
            flexDirection: 'column',
            gap: 24
        }}>
            {/* Cash & Debt Chart Section */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                    paddingBottom: 6
                }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Cash & Total Debt</span>
                    <div style={{ display: 'flex', gap: 12, fontSize: 10, fontWeight: 700 }}>
                        <span style={{ color: 'var(--color-ec-profit)' }}>C: {formatNumber(data?.financials?.cash ?? null)}</span>
                        <span style={{ color: 'var(--color-ec-loss)' }}>D: {formatNumber(data?.financials?.total_debt ?? null)}</span>
                    </div>
                </div>
                <div style={{ height: '130px' }}>
                    <CashDebtChart cashData={data?.charts?.cash_history ?? []} debtData={data?.charts?.debt_history ?? []} />
                </div>
            </div>

            {/* Working Capital Chart Section */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                    paddingBottom: 6
                }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Working Capital</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#3b82f6' }}>{formatNumber(data?.financials?.working_capital ?? null)}</span>
                </div>
                <div style={{ height: '130px' }}>
                    <WorkingCapitalChart wcData={data?.charts?.working_capital_history ?? []} />
                </div>
            </div>
        </div>
    );
};

export default function TickerAnalysis({ ticker: initialTicker, availableTickers }: TickerAnalysisProps) {
    const [selectedTicker, setSelectedTicker] = useState<string>(initialTicker || '');
    const [loadingAnalysis, setLoadingAnalysis] = useState(false);
    const [loadingChart, setLoadingChart] = useState(false);
    const [loadingGap, setLoadingGap] = useState(false);
    const [data, setData] = useState<TickerAnalysisData | null>(null);
    const [filings, setFilings] = useState<FilingsData | null>(null);
    const [finvizNews, setFinvizNews] = useState<FinvizNewsItem[]>([]);
    const [showFullDesc, setShowFullDesc] = useState(false);
    const [logoFailed, setLogoFailed] = useState(false);
    const [logoUrlIndex, setLogoUrlIndex] = useState(0);
    const [logoData, setLogoData] = useState<TickerLogoData | null>(null);
    // Text in the detail-view search box; decoupled from selectedTicker so
    // typing doesn't fire the full 6-endpoint fetch on every keystroke
    const [searchText, setSearchText] = useState<string>(initialTicker || '');

    // Adjust state when props/state change during render (standard React pattern)
    const [prevInitialTicker, setPrevInitialTicker] = useState(initialTicker);
    if (initialTicker !== prevInitialTicker) {
        setPrevInitialTicker(initialTicker);
        setSelectedTicker(initialTicker || '');
    }

    const [prevSelectedTicker, setPrevSelectedTicker] = useState(selectedTicker);
    if (selectedTicker !== prevSelectedTicker) {
        setPrevSelectedTicker(selectedTicker);
        setSearchText(selectedTicker || '');
        setLogoFailed(false);
        setLogoUrlIndex(0);
        setLogoData(null);
    }

    // Fetch logo data (Massive branding with Google favicon fallback)
    useEffect(() => {
        if (!selectedTicker) {
            setLogoData(null);
            return;
        }
        let cancelled = false;
        getTickerLogo(selectedTicker)
            .then(d => { if (!cancelled) setLogoData(d); })
            .catch(() => { if (!cancelled) setLogoData(null); });
        return () => { cancelled = true; };
    }, [selectedTicker]);

    // Cascade: Massive proxied data URL → Google favicon → first-letter avatar
    const logoCandidates = React.useMemo(() => {
        const candidates: string[] = [];
        if (logoData?.logo_data_url) candidates.push(logoData.logo_data_url);
        if (logoData?.google_favicon_url) candidates.push(logoData.google_favicon_url);
        return candidates;
    }, [logoData]);

    const currentLogoUrl = logoCandidates[logoUrlIndex];

    // Fetch Data — progressive: each endpoint resolves independently and merges
    // its slice into state, so fast sources (hot cache, DB) render immediately
    // instead of waiting for the slowest external (yfinance/Finviz/SEC).
    useEffect(() => {
        if (!selectedTicker) return;
        let cancelled = false;

        setData(null);
        setFilings(null);
        setFinvizNews([]);
        setLoadingAnalysis(true);
        setLoadingChart(true);
        setLoadingGap(true);

        const merge = (patch: Partial<TickerAnalysisData>) => {
            if (cancelled) return;
            setData(prev => ({ ...(prev ?? {}), ...patch }));
        };

        getTickerAnalysis(selectedTicker)
            .then(v => {
                if (cancelled) return;
                const val = v as TickerAnalysisData;
                // Preserve working_capital if balance-sheet already merged it
                setData(prev => ({
                    ...(prev ?? {}),
                    ...val,
                    financials: {
                        ...(val.financials ?? {}),
                        ...(prev?.financials?.working_capital !== undefined
                            ? { working_capital: prev.financials.working_capital }
                            : {}),
                    },
                }));
            })
            .catch(e => console.error("Error fetching ticker analysis:", e))
            .finally(() => { if (!cancelled) setLoadingAnalysis(false); });

        getTickerChart(selectedTicker)
            .then(v => merge(v as object))
            .catch(e => console.error("Error fetching ticker chart:", e))
            .finally(() => { if (!cancelled) setLoadingChart(false); });

        getTickerBalanceSheet(selectedTicker)
            .then(v => {
                if (cancelled) return;
                const bsVal = v as { charts?: any; working_capital?: number | null };
                setData(prev => ({
                    ...(prev ?? {}),
                    charts: bsVal.charts,
                    financials: {
                        ...(prev?.financials ?? {}),
                        working_capital: bsVal.working_capital,
                    },
                }));
            })
            .catch(e => console.error("Error fetching balance sheet:", e));

        getTickerGapStats(selectedTicker)
            .then(v => merge(v as object))
            .catch(e => console.error("Error fetching gap stats:", e))
            .finally(() => { if (!cancelled) setLoadingGap(false); });

        getTickerSecFilings(selectedTicker)
            .then(v => { if (!cancelled) setFilings(v as FilingsData); })
            .catch(e => { console.error("Error fetching SEC filings:", e); if (!cancelled) setFilings(null); });

        getTickerFinvizNews(selectedTicker)
            .then(v => {
                if (cancelled) return;
                const payload = v as FinvizNewsItem[] | { news?: FinvizNewsItem[] };
                const items = Array.isArray(payload) ? payload : (payload.news ?? []);
                setFinvizNews(items);
            })
            .catch(e => { console.error("Error fetching Finviz news:", e); if (!cancelled) setFinvizNews([]); });

        return () => { cancelled = true; };
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
                            onBlur={(e) => {
                                const val = e.target.value.toUpperCase().trim();
                                if (val) setSelectedTicker(val);
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

    const getLatestNewsItem = () => {
        const items: any[] = [];
        if (finvizNews && finvizNews.length > 0) {
            items.push(...finvizNews);
        }
        if (filings?.news) {
            filings.news.forEach((f: any) => {
                items.push({
                    date: f.date,
                    time: "SEC",
                    source: f.type,
                    title: f.title,
                    link: f.link
                });
            });
        }
        if (filings?.prospectuses) {
            filings.prospectuses.forEach((f: any) => {
                items.push({
                    date: f.date,
                    time: "SEC",
                    source: f.type,
                    title: f.title,
                    link: f.link
                });
            });
        }

        if (items.length === 0) return null;

        // Sort by date descending
        items.sort((a, b) => {
            const dateA = new Date(`${a.date} ${a.time === 'SEC' ? '00:00' : a.time}`).getTime();
            const dateB = new Date(`${b.date} ${b.time === 'SEC' ? '00:00' : b.time}`).getTime();
            return dateB - dateA;
        });

        return items[0];
    };

    const latestNews = getLatestNewsItem();

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
                    {!logoFailed && currentLogoUrl ? (
                        <img 
                            src={currentLogoUrl} 
                            alt={selectedTicker} 
                            onError={() => {
                                if (logoUrlIndex < logoCandidates.length - 1) {
                                    setLogoUrlIndex(prev => prev + 1);
                                } else {
                                    setLogoFailed(true);
                                }
                            }}
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
                        value={searchText}
                        onChange={(e) => {
                            const val = e.target.value.toUpperCase().trim();
                            setSearchText(val);
                            // Only trigger the full data fetch on an exact match —
                            // firing per keystroke burned 6 API calls per letter
                            if (availableTickers.includes(val)) {
                                setSelectedTicker(val);
                            }
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                const val = (e.target as HTMLInputElement).value.toUpperCase().trim();
                                if (val) setSelectedTicker(val);
                            }
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

                <>
                    {/* Market Metrics Row */}
                    {loadingAnalysis && !data?.market ? (
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                            gap: 24,
                            paddingBottom: 0
                        }}>
                            {[1, 2, 3].map(i => (
                                <div
                                    key={i}
                                    className="animate-pulse"
                                    style={{
                                        height: '64px',
                                        backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                                        borderRadius: '8px'
                                    }}
                                />
                            ))}
                        </div>
                    ) : (
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                        gap: 24,
                        paddingBottom: 0
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
                    )}

                    {/* Latest News Banner */}
                    {latestNews && (
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            padding: '8px 12px',
                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                            borderLeft: '2px solid var(--color-ec-copper)',
                            borderBottom: '1px solid var(--color-ec-border)',
                            borderRadius: '0 4px 4px 0',
                            fontSize: 11,
                            fontFamily: "'General Sans', sans-serif",
                            margin: '0 0 -8px 0'
                        }}>
                            <span style={{ 
                                fontSize: 8, 
                                fontWeight: 700, 
                                color: 'var(--color-ec-copper)', 
                                textTransform: 'uppercase', 
                                letterSpacing: '1px',
                                flexShrink: 0
                            }}>
                                Latest News ({latestNews.date}):
                            </span>
                            {latestNews.source && (
                                <span style={{ color: 'var(--color-ec-text-secondary)', fontSize: 9, fontWeight: 600, flexShrink: 0 }}>
                                    [{latestNews.source}]
                                </span>
                            )}
                            <SentimentBadge sentiment={latestNews.sentiment} />
                            <a
                                href={latestNews.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{
                                    color: 'var(--color-ec-text-primary)',
                                    textDecoration: 'none',
                                    fontWeight: 600,
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    width: '100%'
                                }}
                                className="hover:text-[var(--color-ec-copper-bright)] transition-colors"
                            >
                                {latestNews.title}
                            </a>
                            <ExternalLink size={10} style={{ color: 'var(--color-ec-text-muted)', flexShrink: 0 }} />
                        </div>
                    )}

                    {/* Middle Row: Daily Stock Chart & Know The Float Table */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 border-b border-ec-border pb-6 pt-4" style={{ borderColor: 'var(--color-ec-border)' }}>
                        <div className="lg:col-span-2">
                            {loadingChart && !data?.daily_history?.length ? (
                                <div
                                    className="animate-pulse"
                                    style={{
                                        height: '480px',
                                        backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                                        borderRadius: '8px'
                                    }}
                                />
                            ) : (
                                <DailyStockChart dailyData={data?.daily_history} finvizNews={finvizNews} filings={filings} />
                            )}
                        </div>
                        <div className="lg:col-span-1 flex flex-col lg:min-h-[480px] h-auto gap-6 justify-start">
                            {loadingGap && !data?.know_the_float ? (
                                <div
                                    className="animate-pulse"
                                    style={{
                                        height: '100%',
                                        minHeight: '200px',
                                        backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                                        borderRadius: '8px'
                                    }}
                                />
                            ) : (
                            <>
                            <KnowTheFloatTable floatData={data?.know_the_float} />
                            <GapStatsSection
                                gapStats={data?.gap_stats}
                                gapStatsPlus1={data?.gap_stats_plus_1}
                                gapStatsPlus2={data?.gap_stats_plus_2}
                            />
                            </>
                            )}
                        </div>
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
        </div>
    );
}

// Sub-components with clean unboxed styling
const MetricCard = ({ title, value, subtext, icon, indicatorColor }: MetricCardProps) => (
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

const InfoItem = ({ label, value }: InfoItemProps) => (
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

const StatRow = ({ label, value }: StatRowProps) => (
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

const PerfCard = ({ label, value }: PerfCardProps) => {
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

const FilingList = ({ title, items }: FilingListProps) => {
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
                {items.map((item: FilingItem, i: number) => (
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
