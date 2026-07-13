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
    getTickerInsiders,
    API_BASE,
    getAuthHeaders,
    type TickerLogoData
} from '@/lib/api';
import { ChatBot } from './ChatBot';

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
        equity_history?: FinancialHistoryPoint[];
        shares_outstanding_history?: FinancialHistoryPoint[];
    };
    daily_history?: DailyDataPoint[];
    know_the_float?: FloatData;
    short_interest?: ShortInterestData | null;
    gap_stats?: GapStats;
    gap_stats_plus_1?: GapStats;
    gap_stats_plus_2?: GapStats;
    gap_dates?: string[];
}

// Short interest oficial FINRA (vía Massive API), quincenal.
interface ShortInterestData {
    short_interest?: number | null;
    days_to_cover?: number | null;
    avg_daily_volume?: number | null;
    settlement_date?: string | null;
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
    filings,
    gapDates
}: { 
    dailyData?: DailyDataPoint[];
    finvizNews?: FinvizNewsItem[];
    filings?: FilingsData | null;
    gapDates?: string[];
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
            height: 470,
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

        if (formattedCandles.length > 0) {
            const lastCandle = formattedCandles[formattedCandles.length - 1];
            const lastDate = new Date(lastCandle.time as string);
            
            // Calculate 6 months ago
            const sixMonthsAgo = new Date(lastDate);
            sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
            const sixMonthsAgoStr = sixMonthsAgo.toISOString().split('T')[0];
            
            // Find first candle date that is >= sixMonthsAgoStr
            const fromCandle = formattedCandles.find(c => (c.time as string) >= sixMonthsAgoStr) || formattedCandles[0];
            
            setTimeout(() => {
                try {
                    chart.timeScale().setVisibleRange({
                        from: fromCandle.time,
                        to: lastCandle.time
                    });
                } catch (e) {
                    console.warn("Could not set initial chart visible range:", e);
                }
            }, 50);
        }

        // Set markers for gap days based on registered gapDates
        const markers = [];
        const gapDatesSet = new Set(gapDates || []);
        
        for (let i = 1; i < dailyData.length; i++) {
            const dateStr = dailyData[i].time;
            if (gapDatesSet.has(dateStr)) {
                markers.push({
                    time: dateStr,
                    position: 'aboveBar' as const,
                    color: '#D87A3D', // Opaque copper circle
                    shape: 'circle' as const,
                    size: 0.75,
                    text: '', // No text
                });
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
    }, [dailyData, gapDates]);

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

    // Calculate gap days from dailyData based on registered gapDates
    const gaps: Array<{
        time: string;
        gapPct: number;
        open: number;
        high: number;
        low: number;
        close: number;
        isPositive: boolean;
    }> = [];
    
    const gapDatesSet = new Set(gapDates || []);
    
    if (dailyData && dailyData.length > 1) {
        for (let i = 1; i < dailyData.length; i++) {
            const prevClose = dailyData[i - 1].close;
            const d = dailyData[i];
            if (gapDatesSet.has(d.time)) {
                const gapPct = prevClose > 0 ? ((d.open - prevClose) / prevClose) * 100 : 0;
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
                        const label = tab === 'chart' ? 'Chart' : `Gap List (${gaps.length})`;
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
                height: '350px',
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
                    height: '350px',
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
                            No se encontraron gaps registrados para este ticker.
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
                                                <td style={{
                                                    padding: '6px 4px',
                                                    textAlign: 'right',
                                                    fontWeight: 600,
                                                    color: gap.gapPct >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)'
                                                }}>
                                                    {gap.gapPct >= 0 ? '+' : ''}{gap.gapPct.toFixed(2)}%
                                                </td>
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

// KnowTheFloat comparison table (+ short interest oficial FINRA vía Massive)
const KnowTheFloatTable = ({ floatData, shortInterest }: { floatData?: FloatData; shortInterest?: ShortInterestData | null }) => {
    const fmtShares = (n?: number | null) => {
        if (n === null || n === undefined) return '-';
        if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
        if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
        if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
        return `${n}`;
    };

    // Línea de short interest oficial: se muestra aunque el scrape de float
    // falle (es el único dato determinista de esta tarjeta).
    const finraLine = shortInterest && shortInterest.short_interest != null ? (
        <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            fontSize: 10, padding: '4px 6px', borderRadius: 4,
            border: '0.5px solid var(--color-ec-copper)',
            color: 'var(--color-ec-text-primary)',
        }}>
            <span style={{ fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '0.5px', fontSize: 8 }}>
                Short Int. FINRA
            </span>
            <span style={{ fontWeight: 700, color: 'var(--color-ec-loss)' }}>{fmtShares(shortInterest.short_interest)} sh</span>
            <span>DTC {shortInterest.days_to_cover != null ? Number(shortInterest.days_to_cover).toFixed(1) : '-'}</span>
            <span style={{ color: 'var(--color-ec-text-muted)' }}>{shortInterest.settlement_date ?? ''}</span>
        </div>
    ) : null;

    if (!floatData || Object.keys(floatData).length === 0) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px', borderBottom: '1px solid var(--color-ec-border)', paddingBottom: 4 }}>
                    Float Comparison
                </span>
                {finraLine}
                <div style={{
                    height: finraLine ? '104px' : '130px',
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

    // Dilution Tracker retirado: no tenemos acceso a esa fuente (siempre salía vacío).
    const sources = ["Yahoo Finance", "Finviz", "Wall Street Journal"];

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
            {finraLine}
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
    const paddingBottom = 20;

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
                            y={paddingTop + H + 13}
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
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: 2, marginTop: -16 }}>
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
                                        height: 16,
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
                                        height: 16,
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
                                        height: 16,
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

// Tabla compacta del histórico trimestral de balance (pestaña "Balance").
// Muestra la evolución de Cash, Debt, Working Capital, Equity y Shares; resalta
// en rojo los trimestres con un incremento de Shares > 15% (dilución severa).
const BalanceSheetTable = ({ charts }: { charts?: TickerAnalysisData['charts'] }) => {
    const fmtMoney = (v: number | null | undefined): string => {
        if (v === null || v === undefined || Number.isNaN(v)) return '—';
        const neg = v < 0;
        const a = Math.abs(v);
        let s: string;
        if (a >= 1e9) s = `${(a / 1e9).toFixed(1)}B`;
        else if (a >= 1e6) s = `${(a / 1e6).toFixed(1)}M`;
        else if (a >= 1e3) s = `${(a / 1e3).toFixed(1)}K`;
        else s = a.toFixed(0);
        return `${neg ? '-' : ''}$${s}`;
    };
    const fmtShares = (v: number | null | undefined): string => {
        if (v === null || v === undefined || Number.isNaN(v)) return '—';
        const a = Math.abs(v);
        if (a >= 1e9) return `${(a / 1e9).toFixed(1)}B`;
        if (a >= 1e6) return `${(a / 1e6).toFixed(1)}M`;
        if (a >= 1e3) return `${(a / 1e3).toFixed(1)}K`;
        return a.toFixed(0);
    };

    const toMap = (arr?: FinancialHistoryPoint[]) => {
        const m = new Map<string, number | null>();
        (arr ?? []).forEach(p => { if (p && p.date) m.set(p.date, p.value ?? null); });
        return m;
    };
    const cash = toMap(charts?.cash_history);
    const debt = toMap(charts?.debt_history);
    const wc = toMap(charts?.working_capital_history);
    const equity = toMap(charts?.equity_history);
    const shares = toMap(charts?.shares_outstanding_history);

    const dates = Array.from(new Set([
        ...cash.keys(), ...debt.keys(), ...wc.keys(), ...equity.keys(), ...shares.keys(),
    ])).sort((a, b) => (a < b ? 1 : -1)); // descendente: más reciente primero

    if (dates.length === 0) {
        return (
            <div style={{ textAlign: 'center', color: 'var(--color-ec-text-muted)', fontSize: 11, fontStyle: 'italic', padding: '16px 0' }}>
                Sin datos de balance trimestral disponibles para este ticker.
            </div>
        );
    }

    const thStyle: React.CSSProperties = {
        fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.5px',
        padding: '6px 8px', borderBottom: '0.5px solid var(--color-ec-border)',
    };
    const tdStyle: React.CSSProperties = {
        fontSize: 12, color: 'var(--color-ec-text-primary)',
        padding: '6px 8px', borderBottom: '0.5px solid color-mix(in srgb, var(--color-ec-border) 50%, transparent)',
        fontFamily: 'ui-monospace, monospace', textAlign: 'right',
    };

    return (
        <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', backgroundColor: 'var(--color-ec-bg-base)' }}>
                <thead>
                    <tr>
                        <th style={{ ...thStyle, textAlign: 'left' }}>Periodo</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Cash</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Debt</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Working Cap.</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Equity</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Shares</th>
                    </tr>
                </thead>
                <tbody>
                    {dates.map((d, idx) => {
                        const curShares = shares.get(d);
                        // Comparar con el trimestre anterior (la fila siguiente, más antigua).
                        const prevShares = idx < dates.length - 1 ? shares.get(dates[idx + 1]) : null;
                        const severeDilution =
                            typeof curShares === 'number' && typeof prevShares === 'number' &&
                            prevShares > 0 && (curShares - prevShares) / prevShares > 0.15;
                        return (
                            <tr key={d}>
                                <td style={{ ...tdStyle, textAlign: 'left', fontFamily: "'General Sans', sans-serif", color: 'var(--color-ec-text-secondary)' }}>{d}</td>
                                <td style={tdStyle}>{fmtMoney(cash.get(d))}</td>
                                <td style={tdStyle}>{fmtMoney(debt.get(d))}</td>
                                <td style={tdStyle}>{fmtMoney(wc.get(d))}</td>
                                <td style={tdStyle}>{fmtMoney(equity.get(d))}</td>
                                <td style={{
                                    ...tdStyle,
                                    color: severeDilution ? 'var(--color-ec-loss)' : 'var(--color-ec-text-primary)',
                                    fontWeight: severeDilution ? 700 : 400,
                                }} title={severeDilution ? 'Incremento de acciones > 15% vs trimestre anterior (dilución severa)' : undefined}>
                                    {fmtShares(curShares)}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
};

// Tabla de Estructura Accionarial (Ownership) del reporte de Edgie.
// Ordena personas físicas primero (insiders) y luego instituciones, cada grupo
// descendente por % de participación. Lee aiMetrics.ownership_list.
interface OwnershipEntry {
    name?: string;
    type?: 'PERSON' | 'INSTITUTION' | string;
    percentage?: number | null;
    details?: string;
    source?: string;
    date?: string;
}
const OwnershipTable = ({ list }: { list?: OwnershipEntry[] }) => {
    if (!Array.isArray(list) || list.length === 0) return null;

    const byPct = (a: OwnershipEntry, b: OwnershipEntry) => (b.percentage ?? -1) - (a.percentage ?? -1);
    const persons = list.filter(e => e.type === 'PERSON').sort(byPct);
    const institutions = list.filter(e => e.type !== 'PERSON').sort(byPct);
    const ordered = [...persons, ...institutions];

    const thStyle: React.CSSProperties = {
        fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.5px',
        padding: '6px 8px', borderBottom: '0.5px solid var(--color-ec-border)', textAlign: 'left',
    };
    const tdStyle: React.CSSProperties = {
        fontSize: 12, color: 'var(--color-ec-text-primary)', padding: '6px 8px',
        borderBottom: '0.5px solid color-mix(in srgb, var(--color-ec-border) 50%, transparent)',
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
                Estructura Accionarial y Transacciones (Ownership)
            </span>
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', backgroundColor: 'var(--color-ec-bg-base)' }}>
                    <thead>
                        <tr>
                            <th style={thStyle}>Accionista</th>
                            <th style={thStyle}>Tipo</th>
                            <th style={{ ...thStyle, textAlign: 'right' }}>%</th>
                            <th style={thStyle}>Acción / Detalle</th>
                            <th style={thStyle}>Fuente</th>
                            <th style={thStyle}>Fecha</th>
                        </tr>
                    </thead>
                    <tbody>
                        {ordered.map((e, i) => {
                            const isPerson = e.type === 'PERSON';
                            return (
                                <tr key={`${e.name}-${i}`}>
                                    <td style={{ ...tdStyle, fontWeight: 600, color: 'var(--color-ec-text-high)' }}>{e.name ?? '—'}</td>
                                    <td style={tdStyle}>
                                        <span style={{
                                            fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3,
                                            backgroundColor: isPerson ? 'rgba(216, 122, 61, 0.1)' : 'rgba(255, 255, 255, 0.05)',
                                            color: isPerson ? 'var(--color-ec-copper)' : 'var(--color-ec-text-primary)',
                                        }}>
                                            {isPerson ? 'PERSONA' : 'INSTITUCIÓN'}
                                        </span>
                                    </td>
                                    <td style={{ ...tdStyle, textAlign: 'right', fontFamily: 'ui-monospace, monospace' }}>
                                        {typeof e.percentage === 'number' ? `${e.percentage.toFixed(1)}%` : '—'}
                                    </td>
                                    <td style={{ ...tdStyle, color: 'var(--color-ec-text-secondary)' }}>{e.details ?? '—'}</td>
                                    <td style={{ ...tdStyle, fontSize: 11, color: 'var(--color-ec-text-muted)' }}>{e.source ?? '—'}</td>
                                    <td style={{ ...tdStyle, fontSize: 11, color: 'var(--color-ec-text-muted)', fontFamily: 'ui-monospace, monospace' }}>{e.date ?? '—'}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

// Sección de Warrants (techos de peligro y zonas de volatilidad) del reporte.
// Lee aiMetrics.warrants_triggers.
interface WarrantTrigger {
    type?: 'EXERCISE' | 'REDEMPTION' | string;
    price?: number | null;
    shares?: number | null;
    notes?: string;
}
const WarrantsSection = ({ triggers }: { triggers?: WarrantTrigger[] }) => {
    if (!Array.isArray(triggers) || triggers.length === 0) return null;
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
                Warrants — Niveles de Precio Críticos
            </span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {triggers.map((w, i) => {
                    const isRedemption = w.type === 'REDEMPTION';
                    return (
                        <div key={i} style={{
                            display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                            borderRadius: 4, border: '1px solid var(--color-ec-border)',
                            backgroundColor: isRedemption ? 'rgba(201, 77, 63, 0.06)' : 'rgba(216, 122, 61, 0.06)',
                        }}>
                            <span style={{
                                fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 3,
                                color: isRedemption ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)',
                                border: `0.5px solid ${isRedemption ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)'}`,
                            }}>
                                {isRedemption ? 'REDEMPTION' : 'EXERCISE'}
                            </span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-ec-text-high)', fontFamily: 'ui-monospace, monospace' }}>
                                {typeof w.price === 'number' ? `$${w.price.toFixed(2)}` : '—'}
                            </span>
                            <span style={{ fontSize: 11, color: 'var(--color-ec-text-secondary)', lineHeight: 1.3 }}>{w.notes ?? ''}</span>
                        </div>
                    );
                })}
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
    // Edgie AI — Dilution & Runner Assessment (manual trigger via button)
    const [aiAnalysis, setAiAnalysis] = useState<string | null>(null);
    const [aiLoading, setAiLoading] = useState<boolean>(false);
    const [aiError, setAiError] = useState<string | null>(null);
    const [aiMetrics, setAiMetrics] = useState<any | null>(null);
    // true si el informe mostrado salió de la caché del día (backend) → se
    // ofrece "Regenerar" para forzar una pasada nueva del LLM.
    const [aiFromCache, setAiFromCache] = useState<boolean>(false);
    const [activeSecTab, setActiveSecTab] = useState<'filings' | 'balance'>('filings');
  /* POST-MVP AGENTIC - descomentar cuando se active ChatBotAgentic.tsx (ver docs/plan_asistente_edgie.md)
    // ── Edgie assistant integration (AssistantBus) ───────────────
    useAssistantAction({
        name: 'ticker.load',
        description:
            'Carga un ticker en la página de Ticker Analysis: métricas, gap stats, SEC filings, noticias e informe IA. ' +
            'Al terminar, la base de conocimiento del ticker queda disponible en la conversación.',
        parameters: TickerLoadSchema,
        confirm: 'auto',
        handler: async (args) => {
            const t = String(args.ticker || '').toUpperCase().trim();
            if (!t) return { ok: false, error: 'Ticker vacío.' };
            setSelectedTicker(t);

            // Wait for the page to finish loading so the tool result can carry
            // the key metrics and the model can answer in the same turn.
            const payload = await new Promise<any>((resolve) => {
                const timer = setTimeout(() => { cleanup(); resolve(null); }, 20000);
                const onLoaded = (e: Event) => {
                    const detail = (e as CustomEvent).detail;
                    if (detail?.ticker === t) { cleanup(); resolve(detail); }
                };
                const cleanup = () => {
                    clearTimeout(timer);
                    window.removeEventListener('ticker-loaded', onLoaded);
                };
                window.addEventListener('ticker-loaded', onLoaded);
            });

            if (!payload) {
                return { ok: true, result: `Cargando ${t}; los datos aún no han terminado de llegar (sigue cargando en segundo plano).` };
            }
            const market = payload.data?.market ?? {};
            const profile = payload.data?.profile ?? {};
            return {
                ok: true,
                result: {
                    ticker: t,
                    name: profile.name ?? null,
                    price: market.price ?? null,
                    market_cap: market.market_cap ?? null,
                    float_shares: market.float_shares ?? null,
                    shares_outstanding: market.shares_outstanding ?? null,
                    note: 'Base de conocimiento completa cargada (perfil, métricas, gap stats, filings, noticias).',
                },
            };
        },
    });

    useAssistantContext('ticker.page', () => ({
        selectedTicker: selectedTicker || null,
        loading: loadingAnalysis,
        aiReport: aiMetrics
            ? { metrics: aiMetrics, ready: true }
            : { ready: false, loading: aiLoading, error: aiError },
    }));
  */

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
    // its slice into state, so fast sources (Massive/SEC/hot cache) render as
    // they arrive. On ticker change the in-flight requests are ABORTED (not
    // just ignored) so they stop occupying connections.
    useEffect(() => {
        if (!selectedTicker) return;
        let cancelled = false;
        const ac = new AbortController();
        const signal = ac.signal;

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

        getTickerAnalysis(selectedTicker, { signal })
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
            .catch(e => { if (!cancelled) console.error("Error fetching ticker analysis:", e); })
            .finally(() => { if (!cancelled) setLoadingAnalysis(false); });

        getTickerChart(selectedTicker, { signal })
            .then(v => merge(v as object))
            .catch(e => { if (!cancelled) console.error("Error fetching ticker chart:", e); })
            .finally(() => { if (!cancelled) setLoadingChart(false); });

        getTickerBalanceSheet(selectedTicker, { signal })
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
            .catch(e => { if (!cancelled) console.error("Error fetching balance sheet:", e); });

        // Gap stats: primera visita el backend responde "calculating" y computa
        // en background EN DOS FASES — la fase 1 (números de runner stats +
        // float, sin chart) se publica a los ~2 s y HAY QUE PINTARLA (antes se
        // descartaba y el usuario esperaba 20-120 s mirando un spinner). El
        // poll es corto y fijo (2s, luego 4s, tope ~2 min), sin backoff
        // exponencial: con backoff, una fase 2 lista en el segundo 29 no se
        // veía hasta el poll del segundo 60.
        let pollTimer: NodeJS.Timeout;
        let pollAttempt = 0;
        const fetchGapStats = () => {
            getTickerGapStats(selectedTicker, { signal })
                .then(v => {
                    if (cancelled) return;
                    const res = v as any;
                    const calculating = res && res.status === "calculating";
                    const hasStats = (res?.gap_stats?.gap_days_count ?? 0) > 0
                        || Object.keys(res?.know_the_float ?? {}).length > 0;
                    if (res && (!calculating || hasStats)) {
                        merge(res);           // fase 1: pinta números aunque el chart siga en cámara
                    }
                    if (calculating && pollAttempt < 30) {
                        setLoadingGap(!hasStats); // spinner solo si aún no hay NADA que enseñar
                        pollAttempt += 1;
                        pollTimer = setTimeout(fetchGapStats, pollAttempt === 1 ? 2000 : 4000);
                    } else {
                        setLoadingGap(false);
                    }
                })
                .catch(e => {
                    if (cancelled) return;
                    console.error("Error fetching gap stats:", e);
                    setLoadingGap(false);
                });
        };
        fetchGapStats();

        getTickerSecFilings(selectedTicker, { signal })
            .then(v => { if (!cancelled) setFilings(v as FilingsData); })
            .catch(e => { if (!cancelled) { console.error("Error fetching SEC filings:", e); setFilings(null); } });

        getTickerFinvizNews(selectedTicker, { signal })
            .then(v => {
                if (cancelled) return;
                const payload = v as FinvizNewsItem[] | { news?: FinvizNewsItem[] };
                const items = Array.isArray(payload) ? payload : (payload.news ?? []);
                setFinvizNews(items);
            })
            .catch(e => { if (!cancelled) { console.error("Error fetching Finviz news:", e); setFinvizNews([]); } });

        // Prefetch de insiders (fire-and-forget): calienta la caché SWR para que
        // el informe de Edgie no pague las rondas a SEC al pulsar el botón.
        getTickerInsiders(selectedTicker, { signal }).catch(() => { /* prefetch */ });

        return () => {
            cancelled = true;
            ac.abort();
            if (pollTimer) clearTimeout(pollTimer);
        };
    }, [selectedTicker]);

    // Feed Edgie (ChatBot) the loaded ticker knowledge base. main fetches data
    // progressively, so re-dispatch whenever a piece settles; Edgie reads the
    // latest snapshot when the user sends a message.
    useEffect(() => {
        if (!selectedTicker || !data) return;
        window.dispatchEvent(new CustomEvent('ticker-loaded', {
            detail: {
                ticker: selectedTicker,
                data,
                filings,
                finvizNews,
                secCompanyFacts: null, // opcional, no disponible en main
            },
        }));
    }, [selectedTicker, data, filings, finvizNews]);

    // ── Edgie AI — Dilution & Runner Assessment ──────────────────
    // Builds a quantitative prompt from the loaded ticker data and asks the
    // backend AI Gateway (/api/assistant/chat, key server-side) for a dilution
    // report. Manual trigger (button) so the LLM call only fires on demand.
    const triggerAiAnalysis = async (
        tickerName: string,
        combinedData: TickerAnalysisData,
        resolvedFilings: FilingsData | null,
        resolvedNews: FinvizNewsItem[],
        resolvedSecFacts: any,
        force: boolean = false
    ) => {
        if (!tickerName) return;

        setAiLoading(true);
        setAiError(null);
        setAiAnalysis(null);
        setAiMetrics(null);
        setAiFromCache(false);

        try {
            // Build the quantitative user prompt
            let userPrompt = `Generate a Dilution Risk & Runner Assessment report for ticker: ${tickerName.toUpperCase()}.\n`;

            const profile = combinedData.profile || {};
            const market = combinedData.market || {};
            const financials = (combinedData as any).financials || {};
            const gapStats = ((combinedData as any).gap_stats || {}) as any;
            const gapStats1 = ((combinedData as any).gap_stats_plus_1 || {}) as any;
            const gapStats2 = ((combinedData as any).gap_stats_plus_2 || {}) as any;

            userPrompt += `\n### Profile: Name: ${profile.name}, Sector: ${profile.sector}, Industry: ${profile.industry}\n`;
            userPrompt += `\n### Market Metrics: Price: $${market.price}, Market Cap: $${market.market_cap}, Outstanding Shares: ${market.shares_outstanding}, Float Shares: ${market.float_shares}, Insiders: ${(market as any).held_percent_insiders}, Institutions: ${(market as any).held_percent_institutions}\n`;
            userPrompt += `\n### Balance Sheet: Enterprise Value: $${financials.enterprise_value}, Cash: $${financials.cash}, Debt: $${financials.total_debt}, EBITDA: $${financials.ebitda}, EPS: ${financials.eps}, Working Capital: $${financials.working_capital}\n`;

            // Add Gap Stats
            userPrompt += `\n### Gap Stats:\n- Offset 0: Gap days count: ${gapStats.gap_days_count || 0}, High Spike Avg: ${gapStats.high_rth_spike_avg}%, Low Spike Avg: ${gapStats.low_rth_spike_avg}%, Neg Close Freq: ${gapStats.neg_close_freq}%\n`;
            userPrompt += `- Offset +1: High Spike Avg: ${gapStats1.high_rth_spike_avg}%, Neg Close Freq: ${gapStats1.neg_close_freq}%\n`;
            userPrompt += `- Offset +2: High Spike Avg: ${gapStats2.high_rth_spike_avg}%, Neg Close Freq: ${gapStats2.neg_close_freq}%\n`;

            // Add Filings
            if (resolvedFilings) {
                userPrompt += `\n### Recent Filings:\n`;
                Object.entries(resolvedFilings).forEach(([cat, items]) => {
                    if (Array.isArray(items) && items.length > 0) {
                        const fileLines = items.slice(0, 5).map((item: any) => `- [${item.type}] ${item.title} (${item.date})`).join('\n');
                        userPrompt += `${cat.toUpperCase()}:\n${fileLines}\n`;
                    }
                });
            }

            // Add SEC Facts (optional — not available in this build, guarded)
            if (resolvedSecFacts && resolvedSecFacts.facts) {
                userPrompt += `\n### SEC EDGAR XBRL Facts:\n`;
                userPrompt += `CIK: ${resolvedSecFacts.cik}, Company: ${resolvedSecFacts.company_name}\n`;
                Object.entries(resolvedSecFacts.facts).forEach(([conceptName, factObj]: [string, any]) => {
                    const label = factObj.label || conceptName;
                    const history = factObj.history || [];
                    if (history.length > 0) {
                        const historyStr = history.map((h: any) => `${h.date} (${h.form}): ${h.value} ${h.unit}`).join(' | ');
                        userPrompt += `- ${conceptName} (${label}): ${historyStr}\n`;
                    }
                });
            }

            // Add Management & Insiders (yfinance officers roster + SEC Form 3/4/5 insider transactions).
            // Feeds ownership_list / directors so Edgie reports real names instead of guessing.
            const officers = (profile as any).officers;
            if (Array.isArray(officers) && officers.length > 0) {
                userPrompt += `\n### Management (Company Officers):\n`;
                officers.slice(0, 12).forEach((o: any) => {
                    const title = o.title || o.position || '—';
                    const pay = o.totalPay != null ? ` (totalPay: $${o.totalPay})` : '';
                    userPrompt += `- ${o.name}: ${title}${pay}\n`;
                });
            }
            // Insiders (SEC Forms 3/4/5) — fetched lazily here so the manual report
            // is the only thing that pays the SEC round-trips; tolerant to failure.
            let insiders: any[] = [];
            try {
                const res = await getTickerInsiders(tickerName.toUpperCase());
                insiders = Array.isArray(res?.insiders) ? res.insiders : [];
            } catch (e) {
                console.warn('No se pudieron cargar insiders (Forms 3/4/5):', e);
            }
            if (Array.isArray(insiders) && insiders.length > 0) {
                userPrompt += `\n### Insiders (SEC Forms 3/4/5 — recent transactions):\n`;
                insiders.slice(0, 20).forEach((t: any) => {
                    const role = t.role || '—';
                    const action = t.acquired_disposed === 'A' ? 'ACQUIRED' : t.acquired_disposed === 'D' ? 'DISPOSED' : (t.code_label || t.code || '—');
                    const shares = t.shares != null ? `${t.shares} sh` : '—';
                    const price = t.price != null ? ` @ $${t.price}` : '';
                    userPrompt += `- [${t.date || '—'}] ${t.name} (${role}): ${action} ${shares}${price} [code ${t.code || '—'}]\n`;
                });
            }
            if ((!Array.isArray(officers) || officers.length === 0) && (!Array.isArray(insiders) || insiders.length === 0)) {
                userPrompt += `\n### Management & Insiders: No officer roster or SEC Form 3/4/5 insider data available for this ticker.\n`;
            }

            const systemPrompt =
                "You are Edgie AI, an expert quantitative data processor integrated into a professional short-selling trading terminal.\n" +
                "Your task is to analyze the provided financial metrics, SEC filings history (especially S-1, S-3 shelf registrations, and 424B offerings), and SEC EDGAR XBRL facts for the ticker.\n" +
                "You must construct a highly dense, structured, raw data report focused on Dilution Risk, Share Structure, Cash Runway, Ownership and Squeeze probability.\n\n" +
                "CRITICAL OUTPUT FORMATTING:\n" +
                "You MUST prepend your response with a structured JSON block enclosed in <edgie_metrics>...</edgie_metrics> XML tags.\n" +
                "The JSON must be VALID (no comments, no trailing commas) with the following keys and type values:\n" +
                "{\n" +
                "  \"dilution_rating\": \"LOW\" | \"MEDIUM\" | \"HIGH\" | \"CRITICAL\",\n" +
                "  \"dilution_score\": number (0 to 100 representing the probability of immediate dilution),\n" +
                "  \"cash_runway_months\": number | null (estimated cash runway in months),\n" +
                "  \"float_percentage\": number | null (float shares as % of outstanding shares, from 0 to 100),\n" +
                "  \"runner_assessment\": \"FADER\" | \"SQUEEZE\" | \"NEUTRAL\",\n" +
                "  \"shelf_capacity_usd\": number | null (remaining shelf capacity in USD, or null),\n" +
                "  \"pending_s1\": boolean (true if there is a pending S-1 registration, false otherwise),\n" +
                "  \"active_atm_usd\": number | null (size in USD of an ATM offering ONLY if declared Effective/Active; null if none or Pending),\n" +
                "  \"hired_banks\": string[] (normalized names of placement agents / underwriters found in S-1, F-1, S-3, F-3, 424B, or ATM 8-K/6-K. Empty array if none),\n" +
                "  \"ownership_list\": [ { \"name\": string, \"type\": \"PERSON\" | \"INSTITUTION\", \"percentage\": number | null, \"details\": string, \"source\": string, \"date\": string } ],\n" +
                "  \"warrants_triggers\": [ { \"type\": \"EXERCISE\" | \"REDEMPTION\", \"price\": number, \"shares\": number | null, \"notes\": string } ],\n" +
                "  \"nasdaq_compliance\": { \"below_one_dollar_days\": number | null, \"below_ten_cents_days\": number | null, \"equity_usd\": number | null, \"market_cap_usd\": number | null, \"compliance_risk\": \"OK\" | \"WARNING\" | \"DEFICIENT\" | \"DELISTING\" }\n" +
                "}\n\n" +
                "After the </edgie_metrics> tag, output your detailed qualitative analysis in clean Spanish Markdown, using headers, bullet lists, and tables.\n\n" +
                "ADVANCED DILUTION RULES (apply rigorously):\n" +
                "A. PLACEMENT AGENTS: In the Underwriting / Plan of Distribution sections of S-1/F-1/S-3/F-3 and 424B prospectuses, identify the hired bank (e.g. H.C. Wainwright, Maxim Group, Aegis Capital, Roth Capital). Return normalized names in hired_banks. The presence of these toxic placement agents raises the dilution rating. Honor any 'CONTEXTO HISTÓRICO DE BANCOS DILUSORES' provided in the conversation.\n" +
                "B. ACTIVE ATM: Detect At-The-Market offerings in 8-K/6-K. Mark as high danger ONLY if Effective/Active (set active_atm_usd). If Pending SEC approval, treat as informational (active_atm_usd = null) and say it is pending.\n" +
                "C. TOXIC CONVERTIBLES: If 8-K, Schedule 13G or Exhibits 4.1/10.1 contain variable-price discounts over future VWAP (e.g. 'convertible at a 20% discount of the lowest VWAP of the last 5 trading days'), flag MAXIMUM alert: funds are mathematically incentivized to crush the price in premarket. Search terms: 'Warrant Agency Agreement', 'Convertible Note', 'Securities Purchase Agreement'.\n" +
                "D. WARRANT PRICE TRIGGERS: Add to warrants_triggers an EXERCISE entry at the warrant exercise price (the 'danger ceiling' funds push toward to exercise and dump) and a REDEMPTION entry for call/redemption clauses (e.g. 'redemption if closing price exceeds $7.50 for 10 consecutive days').\n" +
                "E. STRUCTURAL/REGULATORY FILTERS: (1) JURISDICTION & CONTROL (the real danger): Cayman/BVI/PRC incorporation, operations in China/Hong Kong/Asia, ADR/foreign issuer (F-1/F-3/6-K/20-F), or Chinese/Asian individuals controlling management/board => HIGH governance & pump-and-dump risk. THIS — not a small float — is what you must warn about. (2) FLOAT SIZE — do not get this backwards: a SMALL float is NORMAL and EXPECTED for these setups and is NOT a red flag by itself; our users actively look for low-float names, so do NOT frame a small float as dangerous. The genuine structural danger is MICROFLOAT (< 1,000,000 shares) => extreme manipulation/squeeze risk. A larger/high float is relatively SAFER (harder to squeeze) — state it neutrally, not as a positive catalyst. (3) BABY SHELF RULE (S-3/F-3 Instruction I.B.6) — DO THE MATH: if public float < $75M, the company can only sell via shelf/ATM up to 33.3% of public float per rolling 12 months (public float based on the highest closing price of the last 60 days). When this applies, COMPUTE and report: the price needed to cross a $75M market cap (= 75,000,000 / shares_outstanding), the gap from the current price (absolute and %), and the read that — being below that level and capped at 33% — the company/insiders are incentivised to let the price PUMP toward that target to unlock full ($75M+) dilution capacity before issuing (a POSSIBLE LONG / pump-to-unlock-dilution scenario, stated as a structural observation, NOT advice). If shares_outstanding is unknown, say it is not calculable rather than inventing it.\n" +
                "F. NASDAQ COMPLIANCE — ONLY IF PRICE-RELEVANT: discuss the $1.00 minimum-bid rule (deficiency if closes < $1.00 for 30 consecutive business days; 180-day grace; cured by >$1.00 for 10+ days) and the sudden-death $0.10 rule (below $0.10 for 10 consecutive business days => immediate suspension/delisting) ONLY when the current price is below $2.00 or within ~25% of the threshold. If the price is comfortably above (e.g. $10), DO NOT mention the $1.00 / $0.10 rules at all — it is irrelevant noise; set nasdaq_compliance.compliance_risk = OK and omit it from the markdown. Still verify the other listing standards (MVLS >= $35M, Stockholders' Equity >= $2.5M, MVPHS > $1M, >= 500,000 public float shares) and fill nasdaq_compliance accordingly.\n\n" +
                "CRITICAL CONTENT RULES:\n" +
                "1. NO CHATTY INTRODUCTIONS OR GREETINGS. Do NOT say 'Hola', 'Aquí tienes...', 'Espero que te sirva...', etc. Start immediately with the <edgie_metrics> tag.\n" +
                "2. NO CANDLESTICK / PRICE-ACTION PREDICTIONS. Do NOT interpret candle patterns (e.g. inverted hammer, gap-up with long wick) as dilution signals. ONLY use structural price levels derived from warrants (exercise/redemption prices), regulatory thresholds (Nasdaq $1.00 cure price, $0.10, $75M baby-shelf) and support/resistance tied to those levels.\n" +
                "3. ALWAYS format key data comparisons into Markdown Tables. Avoid giant paragraphs of text. Use bulleted lists for key bullet statistics.\n" +
                "4. STRUCTURE THE MARKDOWN: Start with a section titled 'Resumen' (max 2 paragraphs) with practical conclusions and the critical price levels for the trader. Then a section titled 'Desarrollo de las conclusiones' with the details (offerings, cash runway, dilution rating rationale, ownership, warrants, Nasdaq compliance, runner squeezability).\n" +
                "5. Always respond in Spanish (the markdown part), matching the language of the application. Make sure the numbers are exact as given in the facts. If a datum is unknown, use null in the JSON and '—' in the markdown rather than inventing it.\n" +
                "6. SQUEEZE LOGIC (our users trade SHORT, get the direction right): a short squeeze forms with a SMALL/MICRO float plus high short interest, NOT with a large float. Set runner_assessment = SQUEEZE when the float is small/micro and there is no active dilution mechanism to absorb buying; = FADER when active dilution mechanisms (effective ATM, toxic convertibles, effective shelf with capacity) cap the upside; = NEUTRAL otherwise. NEVER describe a large float as squeeze-prone.\n" +
                "7. DATA, NOT OPINIONS: you are a data processor, not an advisor. Report facts, exact figures and structural price levels. Do NOT give trading or position-management advice — no 'no te cases con la posición', no 'revisa tu stop loss', no buy/sell/hold recommendations — beyond the neutral structural reads defined above (squeeze/fader classification, pump-to-unlock, warrant exercise/redemption levels, regulatory thresholds). When in doubt, give the datum and stop.\n" +
                "8. OWNERSHIP & DIRECTORS: fill ownership_list and any mention of directors/officers/insiders ONLY from the 'Management & Insiders' data provided in the user message (company officers roster + SEC Form 3/4/5 insider transactions). If that section is empty or absent, state that director/insider data is not available — NEVER invent names.";

            // Via the backend AI Gateway (/api/assistant/dilution-report) — provider key
            // stays server-side. Este endpoint inyecta el histórico de bancos dilusores
            // antes de llamar al LLM y registra los nuevos bancos detectados tras la respuesta.
            const response = await fetch(`${API_BASE}/assistant/dilution-report`, {
                method: 'POST',
                headers: await getAuthHeaders(),
                body: JSON.stringify({
                    ticker: tickerName.toUpperCase(),
                    messages: [
                        { role: 'system', content: systemPrompt },
                        { role: 'user', content: userPrompt },
                    ],
                    temperature: 0.1,
                    stream: false,
                    force,
                    page: '/ticker-analysis/ai-report',
                }),
            });
            if (response.status === 503) {
                const e: any = new Error('NO_KEY');
                e.name = 'NoKeyError';
                throw e;
            }
            if (!response.ok) {
                let msg = `HTTP ${response.status}`;
                try { const ed = await response.json(); msg = ed.detail || msg; } catch { /* ignore */ }
                throw new Error(msg);
            }
            const respData = await response.json();
            setAiFromCache(!!respData.cached);
            const reply = respData.choices?.[0]?.message?.content || 'No received analysis.';

            let parsedMetrics = null;
            let displayReply = reply;

            const regex = /<edgie_metrics>([\s\S]*?)<\/edgie_metrics>/;
            const match = reply.match(regex);
            if (match) {
                try {
                    parsedMetrics = JSON.parse(match[1].trim());
                    displayReply = reply.replace(regex, '').trim();
                } catch (e) {
                    console.error("Failed to parse edgie_metrics JSON", e);
                }
            }

            setAiAnalysis(displayReply);
            setAiMetrics(parsedMetrics);
        } catch (err: any) {
            console.error("AI processing error:", err);
            if (err.name === 'NoKeyError') {
                setAiError("NO_KEY");
            } else {
                setAiError(err.message || "Error al conectar con el gateway de IA.");
            }
        } finally {
            setAiLoading(false);
        }
    };

    const renderAiContent = (content: string) => {
        if (!content) return null;

        const lines = content.split('\n');
        let insideTable = false;
        let tableHeaders: string[] = [];
        let tableRows: string[][] = [];

        const elements: React.ReactNode[] = [];

        const parseLineWithBolds = (text: string) => {
            const parts = text.split('**');
            return parts.map((part, index) => {
                if (index % 2 === 1) {
                    return <strong key={index} style={{ color: 'var(--color-ec-text-high)', fontWeight: 700 }}>{part}</strong>;
                }
                return part;
            });
        };

        let i = 0;
        while (i < lines.length) {
            const line = lines[i];

            // Handle Table
            if (line.trim().startsWith('|')) {
                if (!insideTable) {
                    insideTable = true;
                    tableHeaders = line.split('|').map(s => s.trim()).filter(Boolean);
                    tableRows = [];
                    if (i + 1 < lines.length && lines[i + 1].includes('---')) {
                        i += 2;
                        continue;
                    }
                    i++;
                    continue;
                } else {
                    const row = line.split('|').map(s => s.trim()).filter(Boolean);
                    if (row.length > 0) {
                        tableRows.push(row);
                    }
                    i++;
                    continue;
                }
            } else {
                if (insideTable) {
                    const tableKey = `table-${i}`;
                    elements.push(
                        <div key={tableKey} style={{ overflowX: 'auto', margin: '14px 0', border: '1px solid var(--color-ec-border)', borderRadius: '6px', backgroundColor: 'var(--color-ec-bg-sidebar)' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', textAlign: 'left' }}>
                                <thead>
                                    <tr style={{ borderBottom: '1.5px solid var(--color-ec-border)', backgroundColor: 'rgba(216, 122, 61, 0.05)' }}>
                                        {tableHeaders.map((h, hIdx) => (
                                            <th key={hIdx} style={{ padding: '8px 12px', color: 'var(--color-ec-text-secondary)', fontWeight: 600, fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {tableRows.map((r, rIdx) => (
                                        <tr key={rIdx} style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)' }}>
                                            {r.map((cell, cIdx) => (
                                                <td key={cIdx} style={{ padding: '8px 12px', color: 'var(--color-ec-text-primary)' }}>{parseLineWithBolds(cell)}</td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    );
                    insideTable = false;
                }
            }

            if (line.startsWith('### ')) {
                elements.push(
                    <h4 key={i} style={{ color: 'var(--color-ec-copper-bright)', fontSize: '12px', fontWeight: 700, margin: '18px 0 6px 0', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        {line.replace('### ', '')}
                    </h4>
                );
            } else if (line.startsWith('## ')) {
                elements.push(
                    <h3 key={i} style={{ color: 'var(--color-ec-copper-bright)', fontSize: '13px', fontWeight: 700, margin: '22px 0 10px 0', borderBottom: '1px solid var(--color-ec-border)', paddingBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        {line.replace('## ', '')}
                    </h3>
                );
            } else if (line.startsWith('# ')) {
                elements.push(
                    <h2 key={i} style={{ color: 'var(--color-ec-text-high)', fontSize: '15px', fontWeight: 700, margin: '26px 0 12px 0', fontFamily: "'Fraunces', serif" }}>
                        {line.replace('# ', '')}
                    </h2>
                );
            } else if (line.startsWith('- ') || line.startsWith('* ')) {
                const listText = line.substring(2);
                elements.push(
                    <ul key={i} style={{ margin: '4px 0 4px 16px', paddingLeft: 0, listStyleType: 'disc' }}>
                        <li style={{ fontSize: '11px', color: 'var(--color-ec-text-primary)', lineHeight: 1.5 }}>
                            {parseLineWithBolds(listText)}
                        </li>
                    </ul>
                );
            } else if (line.trim() === '') {
                elements.push(<div key={i} style={{ height: '4px' }} />);
            } else {
                elements.push(
                    <p key={i} style={{ fontSize: '11px', color: 'var(--color-ec-text-primary)', lineHeight: 1.5, margin: '6px 0' }}>
                        {parseLineWithBolds(line)}
                    </p>
                );
            }

            i++;
        }

        if (insideTable) {
            elements.push(
                <div key="table-end" style={{ overflowX: 'auto', margin: '14px 0', border: '1px solid var(--color-ec-border)', borderRadius: '6px', backgroundColor: 'var(--color-ec-bg-sidebar)' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', textAlign: 'left' }}>
                        <thead>
                            <tr style={{ borderBottom: '1.5px solid var(--color-ec-border)', backgroundColor: 'rgba(216, 122, 61, 0.05)' }}>
                                {tableHeaders.map((h, hIdx) => (
                                    <th key={hIdx} style={{ padding: '8px 12px', color: 'var(--color-ec-text-secondary)', fontWeight: 600, fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {tableRows.map((r, rIdx) => (
                                <tr key={rIdx} style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 20%, transparent)' }}>
                                    {r.map((cell, cIdx) => (
                                        <td key={cIdx} style={{ padding: '8px 12px', color: 'var(--color-ec-text-primary)' }}>{parseLineWithBolds(cell)}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            );
        }

        return elements;
    };

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

                    {/* Middle Row: Daily Stock Chart & Know The Float Table */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 border-b border-ec-border pb-0 pt-4" style={{ borderColor: 'var(--color-ec-border)', paddingBottom: '40px' }}>
                        <div className="lg:col-span-2 flex flex-col">
                            {loadingChart && !data?.daily_history?.length ? (
                                <div
                                    className="animate-pulse"
                                    style={{
                                        height: '425px',
                                        backgroundColor: 'color-mix(in srgb, var(--color-ec-border) 20%, transparent)',
                                        borderRadius: '8px'
                                    }}
                                />
                            ) : (
                                <>
                                    <DailyStockChart
                                        dailyData={data?.daily_history}
                                        finvizNews={finvizNews}
                                        filings={filings}
                                        gapDates={data?.gap_dates}
                                    />
                                    
                                    {/* Latest News Banner rendered below the chart component */}
                                    {latestNews && (
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 8,
                                            padding: '6px 10px',
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '1px solid var(--color-ec-border)',
                                            borderLeft: '2px solid var(--color-ec-copper)',
                                            borderRadius: '4px',
                                            fontSize: 11,
                                            fontFamily: "'General Sans', sans-serif",
                                            marginTop: '12px',
                                            marginBottom: '12px',
                                            width: '100%',
                                            boxSizing: 'border-box',
                                            flexShrink: 0
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
                                </>
                            )
                            }
                        </div>
                        <div className="lg:col-span-1 flex flex-col h-auto gap-6 justify-start">
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
                            {/* Float Comparison oculto de momento por decisión de producto */}
                            {false && <KnowTheFloatTable floatData={data?.know_the_float} shortInterest={data?.short_interest} />}
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

                    {/* SEC Filings Section con pestañas Filings / Balance */}
                    <div style={{ paddingTop: 8 }}>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: 8,
                            marginBottom: 16
                        }}>
                            <h3 style={{
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 8,
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                textTransform: 'uppercase',
                                letterSpacing: '1.5px',
                                margin: 0
                            }}>Latest SEC Filings</h3>

                            {/* Tab Bar */}
                            <div style={{ display: 'flex', gap: 4 }}>
                                {(['filings', 'balance'] as const).map(tab => (
                                    <button
                                        key={tab}
                                        onClick={() => setActiveSecTab(tab)}
                                        style={{
                                            backgroundColor: activeSecTab === tab ? 'var(--color-ec-bg-sidebar)' : 'transparent',
                                            border: '1px solid var(--color-ec-border)',
                                            borderRadius: '4px',
                                            color: activeSecTab === tab ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)',
                                            fontSize: '10px',
                                            fontWeight: 600,
                                            padding: '4px 12px',
                                            cursor: 'pointer',
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.5px',
                                            transition: 'all 150ms ease'
                                        }}
                                    >
                                        {tab === 'filings' ? 'Filings' : 'Balance'}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {activeSecTab === 'filings' ? (
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
                        ) : (
                            <BalanceSheetTable charts={data?.charts} />
                        )}
                    </div>

                    {/* Edgie AI Dilution & Runner Assessment Section */}
                    <div style={{
                        borderTop: '1px solid var(--color-ec-border)',
                        paddingTop: 24,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 16
                    }}>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: 12
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <svg width="24" height="24" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <rect x="6" y="9" width="20" height="15" rx="3.5" fill="#1C1E21" stroke="var(--color-ec-copper)" strokeWidth="1.5"/>
                                    <rect x="3" y="14" width="3" height="5" rx="1.5" fill="#2C2F33" stroke="var(--color-ec-copper)" strokeWidth="1"/>
                                    <rect x="26" y="14" width="3" height="5" rx="1.5" fill="#2C2F33" stroke="var(--color-ec-copper)" strokeWidth="1"/>
                                    <path d="M16 9V5M16 5C17.1046 5 18 4.10457 18 3C18 1.89543 17.1046 1 16 1C14.8954 1 14 1.89543 14 3C14 4.10457 14.8954 5 16 5Z" fill="var(--color-ec-copper-bright)"/>
                                    <circle cx="11" cy="15" r="2" fill="var(--color-ec-copper-bright)"/>
                                    <circle cx="21" cy="15" r="2" fill="var(--color-ec-copper-bright)"/>
                                    <rect x="11" y="19" width="10" height="1.5" rx="0.75" fill="var(--color-ec-copper)"/>
                                </svg>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
                                        Edgie AI Processing
                                    </span>
                                    <h3 style={{
                                        fontFamily: "'Fraunces', serif",
                                        fontSize: 18,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-high)',
                                        margin: 0
                                    }}>Dilution &amp; Runner Assessment</h3>
                                </div>
                            </div>

                            {/* Manual Refresh Button */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                {aiFromCache && !aiLoading && (
                                    <span style={{
                                        fontSize: 8, fontWeight: 700, letterSpacing: '0.5px',
                                        textTransform: 'uppercase', color: 'var(--color-ec-copper)',
                                        border: '0.5px solid var(--color-ec-copper)',
                                        borderRadius: 3, padding: '2px 6px',
                                    }}>
                                        Informe de hoy (caché)
                                    </span>
                                )}
                                {aiFromCache && !aiLoading && (
                                    <button
                                        onClick={() => triggerAiAnalysis(selectedTicker, data!, filings, finvizNews, null, true)}
                                        disabled={!data}
                                        style={{
                                            backgroundColor: 'transparent',
                                            border: '1px solid var(--color-ec-copper)',
                                            borderRadius: '4px',
                                            color: 'var(--color-ec-copper)',
                                            fontSize: '10px',
                                            fontWeight: 600,
                                            padding: '6px 12px',
                                            cursor: !data ? 'default' : 'pointer',
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.5px',
                                            transition: 'all 150ms ease'
                                        }}
                                    >
                                        Regenerar
                                    </button>
                                )}
                                <button
                                    onClick={() => triggerAiAnalysis(selectedTicker, data!, filings, finvizNews, null)}
                                    disabled={aiLoading || !data}
                                    style={{
                                        backgroundColor: aiLoading ? 'rgba(255, 255, 255, 0.03)' : 'transparent',
                                        border: '1px solid var(--color-ec-border)',
                                        borderRadius: '4px',
                                        color: aiLoading ? 'var(--color-ec-text-muted)' : 'var(--color-ec-text-primary)',
                                        fontSize: '10px',
                                        fontWeight: 600,
                                        padding: '6px 12px',
                                        cursor: aiLoading || !data ? 'default' : 'pointer',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.5px',
                                        transition: 'all 150ms ease'
                                    }}
                                    className="hover:bg-[var(--color-ec-bg-sidebar)] hover:text-white"
                                >
                                    {aiLoading ? 'Procesando...' : 'Re-procesar datos'}
                                </button>
                            </div>
                        </div>

                        {/* Main Report Container */}
                        <div style={{
                            minHeight: '160px',
                            border: '1px solid var(--color-ec-border)',
                            borderRadius: '8px',
                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                            padding: '20px',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: aiLoading || aiError || !aiAnalysis ? 'center' : 'flex-start',
                            position: 'relative'
                        }}>
                            {aiLoading && (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, width: '100%' }}>
                                    <div style={{ display: 'flex', gap: 4 }}>
                                        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)', animation: 'dot-blink 1.2s infinite' }} />
                                        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)', animation: 'dot-blink 1.2s infinite 0.3s' }} />
                                        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)', animation: 'dot-blink 1.2s infinite 0.6s' }} />
                                    </div>
                                    <span style={{ fontSize: '11px', color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>
                                        Edgie está procesando métricas financieras, filings históricos y hechos XBRL de la SEC para {selectedTicker}...
                                    </span>
                                </div>
                            )}

                            {aiError === "NO_KEY" && (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, textAlign: 'center', maxWidth: '400px', margin: '0 auto' }}>
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-ec-copper)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <circle cx="12" cy="12" r="10"/>
                                        <line x1="12" y1="8" x2="12" y2="12"/>
                                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                                    </svg>
                                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-ec-text-high)' }}>Clave API de DeepSeek Faltante</span>
                                    <span style={{ fontSize: '11px', color: 'var(--color-ec-text-muted)', lineHeight: 1.4 }}>
                                        El servidor no tiene configurada la clave de DeepSeek (DEEPSEEK_API_KEY). Configúrala en el servidor para activar el procesado de Edgie en esta sección.
                                    </span>
                                </div>
                            )}

                            {aiError && aiError !== "NO_KEY" && (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, textAlign: 'center', color: 'var(--color-ec-loss)' }}>
                                    <span style={{ fontSize: '11px', fontWeight: 600 }}>Error al procesar el análisis de Edgie AI:</span>
                                    <span style={{ fontSize: '10px', opacity: 0.8 }}>{aiError}</span>
                                    <button
                                        onClick={() => triggerAiAnalysis(selectedTicker, data!, filings, finvizNews, null)}
                                        style={{
                                            backgroundColor: 'transparent',
                                            border: '1px solid var(--color-ec-loss)',
                                            borderRadius: '4px',
                                            color: 'var(--color-ec-loss)',
                                            fontSize: '9px',
                                            padding: '4px 10px',
                                            marginTop: 6,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Intentar de nuevo
                                    </button>
                                </div>
                            )}

                            {!aiLoading && !aiError && !aiAnalysis && (
                                <div style={{ textAlign: 'center', color: 'var(--color-ec-text-muted)', fontSize: '11px', fontStyle: 'italic' }}>
                                    Ningún reporte procesado. Haz clic en &quot;Re-procesar datos&quot; para iniciar.
                                </div>
                            )}

                            {!aiLoading && !aiError && aiAnalysis && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                                    {/* Visual Infographics Dashboard */}
                                    {aiMetrics && (
                                        <div style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                            gap: 12,
                                            borderBottom: '1.5px solid var(--color-ec-border)',
                                            paddingBottom: 16,
                                            marginBottom: 8
                                        }}>
                                            {/* Card 1: Dilution Score Gauge */}
                                            <div style={{
                                                backgroundColor: 'var(--color-ec-bg-base)',
                                                border: '1px solid var(--color-ec-border)',
                                                borderRadius: '6px',
                                                padding: '10px',
                                                display: 'flex',
                                                flexDirection: 'column',
                                                gap: 6
                                            }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                                        Probabilidad de Dilución
                                                    </span>
                                                    <span style={{
                                                        fontSize: 9,
                                                        fontWeight: 800,
                                                        color: aiMetrics.dilution_rating === 'LOW' ? 'var(--color-ec-profit)' :
                                                               aiMetrics.dilution_rating === 'MEDIUM' ? 'var(--color-ec-copper-bright)' :
                                                               'var(--color-ec-loss)',
                                                        backgroundColor: 'rgba(255, 255, 255, 0.02)',
                                                        padding: '2px 6px',
                                                        borderRadius: '3px',
                                                        border: `0.5px solid color-mix(in srgb, ${
                                                            aiMetrics.dilution_rating === 'LOW' ? 'var(--color-ec-profit)' :
                                                            aiMetrics.dilution_rating === 'MEDIUM' ? 'var(--color-ec-copper-bright)' :
                                                            'var(--color-ec-loss)'
                                                        } 40%, transparent)`
                                                    }}>
                                                        {aiMetrics.dilution_rating}
                                                    </span>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                                                    <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-ec-text-high)', fontFamily: "'Fraunces', serif" }}>
                                                        {aiMetrics.dilution_score}%
                                                    </span>
                                                    <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)' }}>score</span>
                                                </div>
                                                <div style={{ height: '4px', width: '100%', backgroundColor: 'rgba(255, 255, 255, 0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                                                    <div style={{
                                                        height: '100%',
                                                        width: `${aiMetrics.dilution_score}%`,
                                                        backgroundColor: aiMetrics.dilution_score < 40 ? 'var(--color-ec-profit)' :
                                                                         aiMetrics.dilution_score < 75 ? 'var(--color-ec-copper)' :
                                                                         'var(--color-ec-loss)',
                                                        borderRadius: '3px',
                                                        transition: 'width 800ms cubic-bezier(0.16, 1, 0.3, 1)'
                                                    }} />
                                                </div>
                                            </div>

                                            {/* Card 2: Cash Runway Status */}
                                            <div style={{
                                                backgroundColor: 'var(--color-ec-bg-base)',
                                                border: '1px solid var(--color-ec-border)',
                                                borderRadius: '6px',
                                                padding: '10px',
                                                display: 'flex',
                                                flexDirection: 'column',
                                                gap: 6
                                            }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                                        Supervivencia de Caja
                                                    </span>
                                                    <span style={{
                                                        fontSize: 9,
                                                        fontWeight: 800,
                                                        color: aiMetrics.cash_runway_months === null ? 'var(--color-ec-text-muted)' :
                                                               aiMetrics.cash_runway_months > 12 ? 'var(--color-ec-profit)' :
                                                               aiMetrics.cash_runway_months >= 6 ? 'var(--color-ec-copper-bright)' :
                                                               'var(--color-ec-loss)'
                                                    }}>
                                                        {aiMetrics.cash_runway_months === null ? 'N/A' :
                                                         aiMetrics.cash_runway_months > 12 ? 'SEGURO' :
                                                         aiMetrics.cash_runway_months >= 6 ? 'PREVENCIÓN' : 'CRÍTICO'}
                                                    </span>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                                                    <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-ec-text-high)', fontFamily: "'Fraunces', serif" }}>
                                                        {aiMetrics.cash_runway_months !== null ? `${aiMetrics.cash_runway_months} m` : 'N/A'}
                                                    </span>
                                                    <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)' }}>de runway</span>
                                                </div>
                                                <div style={{ height: '4px', width: '100%', backgroundColor: 'rgba(255, 255, 255, 0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                                                    {aiMetrics.cash_runway_months !== null && (
                                                        <div style={{
                                                            height: '100%',
                                                            width: `${Math.min((aiMetrics.cash_runway_months / 18) * 100, 100)}%`,
                                                            backgroundColor: aiMetrics.cash_runway_months < 6 ? 'var(--color-ec-loss)' :
                                                                             aiMetrics.cash_runway_months < 12 ? 'var(--color-ec-copper)' :
                                                                             'var(--color-ec-profit)',
                                                            borderRadius: '3px',
                                                            transition: 'width 800ms cubic-bezier(0.16, 1, 0.3, 1)'
                                                        }} />
                                                    )}
                                                </div>
                                            </div>

                                            {/* Card 3: Float Structure Comparison */}
                                            <div style={{
                                                backgroundColor: 'var(--color-ec-bg-base)',
                                                border: '1px solid var(--color-ec-border)',
                                                borderRadius: '6px',
                                                padding: '10px',
                                                display: 'flex',
                                                flexDirection: 'column',
                                                gap: 6
                                            }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                    <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                                        Estructura del Float
                                                    </span>
                                                    <span style={{ fontSize: 9, fontWeight: 800, color: 'var(--color-ec-copper-bright)' }}>
                                                        {aiMetrics.float_percentage !== null ? `${aiMetrics.float_percentage.toFixed(0)}% float` : 'N/A'}
                                                    </span>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                                                    <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-ec-text-high)', fontFamily: "'Fraunces', serif" }}>
                                                        {aiMetrics.float_percentage !== null ? `${(100 - aiMetrics.float_percentage).toFixed(0)}%` : 'N/A'}
                                                    </span>
                                                    <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)' }}>locked/insiders</span>
                                                </div>
                                                <div style={{ height: '4px', width: '100%', backgroundColor: 'rgba(255, 255, 255, 0.05)', borderRadius: '3px', overflow: 'hidden', display: 'flex' }}>
                                                    {aiMetrics.float_percentage !== null && (
                                                        <>
                                                            <div style={{ height: '100%', width: `${aiMetrics.float_percentage}%`, backgroundColor: 'var(--color-ec-copper-bright)' }} title="Float Shares" />
                                                            <div style={{ height: '100%', width: `${100 - aiMetrics.float_percentage}%`, backgroundColor: 'rgba(255, 255, 255, 0.2)' }} title="Locked/Insider Shares" />
                                                        </>
                                                    )}
                                                </div>
                                            </div>

                                            {/* Card 4: Runner Squeezability assessment */}
                                            <div style={{
                                                backgroundColor: 'var(--color-ec-bg-base)',
                                                border: '1px solid var(--color-ec-border)',
                                                borderRadius: '6px',
                                                padding: '10px',
                                                display: 'flex',
                                                flexDirection: 'column',
                                                justifyContent: 'space-between',
                                                gap: 6
                                            }}>
                                                <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                                    Runner Bias &amp; Squeezability
                                                </span>
                                                <div style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: 8,
                                                    padding: '8px 12px',
                                                    borderRadius: '4px',
                                                    backgroundColor: aiMetrics.runner_assessment === 'SQUEEZE' ? 'rgba(74, 157, 127, 0.06)' :
                                                                   aiMetrics.runner_assessment === 'FADER' ? 'rgba(201, 77, 63, 0.06)' :
                                                                   'rgba(255, 255, 255, 0.02)',
                                                    border: `1px solid color-mix(in srgb, ${
                                                        aiMetrics.runner_assessment === 'SQUEEZE' ? 'var(--color-ec-profit)' :
                                                        aiMetrics.runner_assessment === 'FADER' ? 'var(--color-ec-loss)' :
                                                        'var(--color-ec-border)'
                                                    } 30%, transparent)`
                                                }}>
                                                    {aiMetrics.runner_assessment === 'SQUEEZE' ? (
                                                        <>
                                                            <span style={{ fontSize: '14px' }}>🚀</span>
                                                            <span style={{ fontSize: '11px', fontWeight: 800, color: 'var(--color-ec-profit)', letterSpacing: '0.5px' }}>MEGA SQUEEZE</span>
                                                        </>
                                                    ) : aiMetrics.runner_assessment === 'FADER' ? (
                                                        <>
                                                            <span style={{ fontSize: '14px' }}>🛡️</span>
                                                            <span style={{ fontSize: '11px', fontWeight: 800, color: 'var(--color-ec-loss)', letterSpacing: '0.5px' }}>ALL-DAY FADER</span>
                                                        </>
                                                    ) : (
                                                        <>
                                                            <span style={{ fontSize: '14px' }}>⚖️</span>
                                                            <span style={{ fontSize: '11px', fontWeight: 800, color: 'var(--color-ec-text-primary)', letterSpacing: '0.5px' }}>NEUTRAL</span>
                                                        </>
                                                    )}
                                                </div>
                                                <span style={{ fontSize: '9px', color: 'var(--color-ec-text-muted)', lineHeight: 1.3 }}>
                                                    {aiMetrics.runner_assessment === 'SQUEEZE' ? 'Float ajustado, sin registro activo. Peligro de squeeze.' :
                                                     aiMetrics.runner_assessment === 'FADER' ? 'Presión vendedora garantizada. Registro shelf o S-1 activo.' :
                                                     'Estructura mixta o balanceada.'}
                                                </span>
                                            </div>
                                        </div>
                                    )}
                                    {aiMetrics?.ownership_list && <OwnershipTable list={aiMetrics.ownership_list} />}
                                    {aiMetrics?.warrants_triggers && <WarrantsSection triggers={aiMetrics.warrants_triggers} />}
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                        {renderAiContent(aiAnalysis)}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </>
            <ChatBot />
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
