"use client";

import React, { useEffect, useRef } from "react";
import { createChart, ColorType, IChartApi, ISeriesApi, SeriesType, CandlestickSeries, HistogramSeries, LineSeries } from "lightweight-charts";
import { X, ExternalLink } from "lucide-react";
import { API_URL } from "@/config/constants";

interface CandleChartModalProps {
    isOpen: boolean;
    onClose: () => void;
    ticker: string;
    date: string;
    metrics: {
        pmh_gap_pct: number;
        pmh_fade_pct: number;
        gap_at_open_pct: number;
        rth_fade_pct: number;
        volume: number;
        open?: number;
    };
}

export const CandleChartModal: React.FC<CandleChartModalProps> = ({ isOpen, onClose, ticker, date, metrics }) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const [intradayData, setIntradayData] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(false);

    // Fetch data when modal opens
    useEffect(() => {
        if (!isOpen || !ticker || !date) return;

        setLoading(true);
        fetch(`${API_URL}/market/ticker/${ticker}/intraday?trade_date=${date}`)
            .then(res => res.json())
            .then(data => {
                // Transform data for lightweight-charts
                // data is {timestamp, open, high, low, close, volume, vwap}
                const formatted = data.map((d: any) => ({
                    time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                    open: d.open,
                    high: d.high,
                    low: d.low,
                    close: d.close,
                    volume: d.volume,
                    vwap: d.vwap
                })).sort((a: any, b: any) => a.time - b.time);

                // Deduplicate by time for lightweight-charts strictness
                const unique = formatted.filter((v: any, i: number, a: any[]) =>
                    i === 0 || v.time > a[i - 1].time
                );

                setIntradayData(unique);
            })
            .catch(err => console.error("Modal chart fetch error:", err))
            .finally(() => setLoading(false));
    }, [isOpen, ticker, date]);

    // Initialize/Update Chart
    useEffect(() => {
        if (!chartContainerRef.current || intradayData.length === 0) return;

        const isDark = document.documentElement.classList.contains('dark');
        const themeColors = {
            background: isDark ? '#111827' : '#ffffff',
            text: isDark ? '#9ca3af' : '#4b5563',
            grid: isDark ? '#1f2937' : '#f3f4f6',
            candleUp: '#22c55e',
            candleDown: '#ef4444',
            vwap: isDark ? '#ffffff' : '#3b82f6',
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: themeColors.background },
                textColor: themeColors.text,
            },
            grid: {
                vertLines: { color: themeColors.grid },
                horzLines: { color: themeColors.grid },
            },
            width: chartContainerRef.current.clientWidth,
            height: 500,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: themeColors.grid,
            },
            rightPriceScale: {
                borderColor: themeColors.grid,
                autoScale: true,
            }
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: themeColors.candleUp,
            downColor: themeColors.candleDown,
            borderVisible: false,
            wickUpColor: themeColors.candleUp,
            wickDownColor: themeColors.candleDown,
        });

        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: '#3b82f6',
            priceFormat: { type: 'volume' },
            priceScaleId: '', // Separate scale
        });

        const vwapSeries = chart.addSeries(LineSeries, {
            color: themeColors.vwap,
            lineWidth: 1,
            lineStyle: 2, // Dashed
            title: 'VWAP',
        });

        // Price Scale for volume
        chart.priceScale('').applyOptions({
            scaleMargins: {
                top: 0.8,
                bottom: 0,
            },
        });

        candleSeries.setData(intradayData);
        volumeSeries.setData(intradayData.map(d => ({
            time: d.time,
            value: d.volume,
            color: d.close >= d.open ? themeColors.candleUp + '80' : themeColors.candleDown + '80'
        })));
        vwapSeries.setData(intradayData.map(d => ({
            time: d.time,
            value: d.vwap
        })));

        // Reference Line for Open Price
        if (metrics.open) {
            candleSeries.createPriceLine({
                price: metrics.open,
                color: '#60a5fa',
                lineWidth: 2,
                lineStyle: 0, // Solid
                axisLabelVisible: true,
                title: 'Open Price',
            });
        }

        chart.timeScale().fitContent();
        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [intradayData, metrics.open]);

    if (!isOpen) return null;

    const formatPct = (val: number) => {
        const sign = val >= 0 ? "+" : "";
        return `${sign}${val.toFixed(1)}%`;
    };

    const formatVol = (num: number) => {
        if (num >= 1000000) return (num / 1000000).toFixed(1) + "m";
        if (num >= 1000) return (num / 1000).toFixed(1) + "k";
        return num.toString();
    };

    const displayDate = new Date(date);
    const day = displayDate.getDate();
    const month = displayDate.toLocaleString('default', { month: 'short' }).toUpperCase();
    const year = displayDate.getFullYear();

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 md:p-10 animate-in fade-in duration-200">
            <div className="bg-card border border-border w-full max-w-6xl rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">

                {/* Header matching reference */}
                <div className="p-6 bg-card border-b border-border flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                        <div className="flex flex-col items-center justify-center p-2 bg-muted rounded-lg w-16 h-16 border border-border/50">
                            <span className="text-[10px] font-bold text-muted-foreground leading-none">{month}</span>
                            <span className="text-2xl font-black text-foreground leading-none my-0.5">{day}</span>
                            <span className="text-[10px] font-bold text-muted-foreground leading-none">{year}</span>
                        </div>
                        <div className="flex flex-col">
                            <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                                <h2 className="text-3xl font-black tracking-tighter text-foreground uppercase">{ticker}</h2>
                            </div>
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
                        <MetricItem label="PM HIGH" value={formatPct(metrics.pmh_gap_pct)} color={metrics.pmh_gap_pct >= 0 ? "text-green-500" : "text-red-500"} />
                        <MetricItem label="PM FADE" value={formatPct(metrics.pmh_fade_pct)} color={metrics.pmh_fade_pct >= 0 ? "text-green-500" : "text-red-500"} />
                        <MetricItem label="GAP" value={formatPct(metrics.gap_at_open_pct)} color={metrics.gap_at_open_pct >= 0 ? "text-green-500" : "text-red-500"} />
                        <MetricItem label="FADE" value={formatPct(metrics.rth_fade_pct)} color={metrics.rth_fade_pct >= 0 ? "text-green-500" : "text-red-500"} />
                        <MetricItem label="VOL" value={formatVol(metrics.volume)} color="text-blue-500 underline decoration-2 underline-offset-4" />

                        <button onClick={onClose} className="ml-4 p-2 hover:bg-muted rounded-full transition-colors text-muted-foreground hover:text-foreground">
                            <X className="w-6 h-6" />
                        </button>
                    </div>
                </div>

                {/* Chart Content */}
                <div className="flex-1 bg-background p-4 relative min-h-[500px]">
                    {loading && (
                        <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-10 backdrop-blur-[1px]">
                            <div className="flex flex-col items-center gap-3">
                                <div className="w-10 h-10 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
                                <span className="text-xs font-black uppercase tracking-widest text-muted-foreground">Loading Tapes...</span>
                            </div>
                        </div>
                    )}
                    <div ref={chartContainerRef} className="w-full h-full" />
                </div>

                {/* Footer Controls */}
                <div className="p-4 bg-muted/30 border-t border-border flex items-center justify-between px-8">
                    <div className="flex items-center gap-4 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-500" /> Candles</span>
                        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded bg-blue-500/50" /> Volume</span>
                        <span className="flex items-center gap-1.5"><span className="w-2 h-2 border border-blue-500 border-dashed" /> VWAP</span>
                    </div>
                    <button className="flex items-center gap-2 text-[10px] font-black uppercase tracking-tighter text-blue-500 hover:text-blue-600 transition-colors">
                        PRO VIEW <ExternalLink className="w-3 h-3" />
                    </button>
                </div>
            </div>
        </div>
    );
};

const MetricItem = ({ label, value, color }: { label: string; value: string; color: string }) => (
    <div className="flex flex-col items-end">
        <span className="text-[10px] font-black text-muted-foreground tracking-widest uppercase">{label}</span>
        <span className={`text-xl font-black ${color} tabular-nums`}>{value}</span>
    </div>
);
