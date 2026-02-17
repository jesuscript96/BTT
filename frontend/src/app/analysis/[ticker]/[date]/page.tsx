"use client";

import React, { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { createChart, ColorType, IChartApi, CandlestickSeries, HistogramSeries, LineSeries } from "lightweight-charts";
import { X, ExternalLink, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { API_URL } from "@/config/constants";

export default function AnalysisPage() {
    const params = useParams();
    const ticker = params.ticker as string;
    const date = params.date as string;

    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const [intradayData, setIntradayData] = useState<any[]>([]);
    const [metrics, setMetrics] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    // Fetch Intraday Data & Metrics
    useEffect(() => {
        if (!ticker || !date) return;

        setLoading(true);

        const fetchIntraday = fetch(`${API_URL}/market/ticker/${ticker}/intraday?trade_date=${date}`).then(res => res.json());
        const fetchMetrics = fetch(`${API_URL}/market/screener?ticker=${ticker}&start_date=${date}&end_date=${date}`).then(res => res.json());

        Promise.all([fetchIntraday, fetchMetrics])
            .then(([chartData, screenerData]) => {
                // Transform data for lightweight-charts
                const formatted = chartData.map((d: any) => ({
                    time: Math.floor(new Date(d.timestamp).getTime() / 1000),
                    open: d.open,
                    high: d.high,
                    low: d.low,
                    close: d.close,
                    volume: d.volume
                })).sort((a: any, b: any) => a.time - b.time);

                // Deduplicate
                const unique = formatted.filter((v: any, i: number, a: any[]) =>
                    i === 0 || v.time > a[i - 1].time
                );

                setIntradayData(unique);

                // Extract metrics from screener results
                const records = Array.isArray(screenerData) ? screenerData : (screenerData.records || []);
                if (records.length > 0) {
                    setMetrics(records[0]);
                }
            })
            .catch(err => console.error("Analysis page fetch error:", err))
            .finally(() => setLoading(false));
    }, [ticker, date]);

    // Initialize/Update Chart
    useEffect(() => {
        if (!chartContainerRef.current || intradayData.length === 0) return;

        const isDark = document.documentElement.classList.contains('dark');
        const themeColors = {
            background: isDark ? '#0f172a' : '#ffffff',
            text: isDark ? '#94a3b8' : '#475569',
            grid: isDark ? '#1e293b' : '#f1f5f9',
            candleUp: '#22c55e',
            candleDown: '#ef4444',
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
            height: window.innerHeight - 200,
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
            priceScaleId: '',
        });

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

        if (metrics?.open) {
            candleSeries.createPriceLine({
                price: metrics.open,
                color: '#60a5fa',
                lineWidth: 2,
                lineStyle: 0,
                axisLabelVisible: true,
                title: 'Open Price',
            });
        }

        chart.timeScale().fitContent();
        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({
                    width: chartContainerRef.current.clientWidth,
                    height: window.innerHeight - 200
                });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [intradayData, metrics]);

    const formatPct = (val: number | undefined) => {
        if (val === undefined) return "--";
        const sign = val >= 0 ? "+" : "";
        return `${sign}${val.toFixed(1)}%`;
    };

    const formatVol = (num: number | undefined) => {
        if (num === undefined) return "--";
        if (num >= 1000000) return (num / 1000000).toFixed(1) + "m";
        if (num >= 1000) return (num / 1000).toFixed(1) + "k";
        return num.toString();
    };

    const displayDate = new Date(date);
    const day = displayDate.getDate();
    const month = displayDate.toLocaleString('default', { month: 'short' }).toUpperCase();
    const year = displayDate.getFullYear();

    return (
        <div className="min-h-screen bg-slate-950 flex flex-col font-sans">
            {/* Header */}
            <div className="p-6 bg-slate-900 border-b border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-6 shadow-xl">
                <div className="flex items-center gap-6">
                    <Link href="/" className="p-2 hover:bg-slate-800 rounded-full transition-colors text-slate-400 hover:text-white">
                        <ArrowLeft className="w-6 h-6" />
                    </Link>
                    <div className="flex items-center gap-4">
                        <div className="flex flex-col items-center justify-center p-2 bg-slate-800 rounded-lg w-16 h-16 border border-slate-700">
                            <span className="text-[10px] font-bold text-slate-500 leading-none">{month}</span>
                            <span className="text-2xl font-black text-white leading-none my-0.5">{day}</span>
                            <span className="text-[10px] font-bold text-slate-500 leading-none">{year}</span>
                        </div>
                        <div className="flex flex-col">
                            <div className="flex items-center gap-2">
                                <div className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
                                <h1 className="text-4xl font-black tracking-tighter text-white uppercase">{ticker}</h1>
                            </div>
                            <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest mt-1">Intraday Analysis</span>
                        </div>
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-x-10 gap-y-4">
                    <MetricItem label="PM HIGH" value={formatPct(metrics?.pmh_gap_pct)} color={metrics?.pmh_gap_pct >= 0 ? "text-green-400" : "text-red-400"} />
                    <MetricItem label="PM FADE" value={formatPct(metrics?.pmh_fade_pct)} color={metrics?.pmh_fade_pct >= 0 ? "text-green-400" : "text-red-400"} />
                    <MetricItem label="GAP" value={formatPct(metrics?.gap_at_open_pct)} color={metrics?.gap_at_open_pct >= 0 ? "text-green-400" : "text-red-400"} />
                    <MetricItem label="FADE" value={formatPct(metrics?.rth_fade_pct)} color={metrics?.rth_fade_pct >= 0 ? "text-green-400" : "text-red-400"} />
                    <MetricItem label="VOLUME" value={formatVol(metrics?.volume)} color="text-blue-400 underline decoration-2 underline-offset-4" />
                </div>
            </div>

            {/* Main View */}
            <div className="flex-1 p-6 relative">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 z-20 backdrop-blur-sm">
                        <div className="flex flex-col items-center gap-4">
                            <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
                            <span className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400">Loading Market Data</span>
                        </div>
                    </div>
                )}
                <div className="w-full h-full bg-slate-900/50 rounded-2xl border border-slate-800 p-2 overflow-hidden shadow-2xl">
                    <div ref={chartContainerRef} className="w-full h-full" />
                </div>
            </div>

            {/* Footer */}
            <div className="p-4 bg-slate-900 border-t border-slate-800 flex items-center justify-between px-10">
                <div className="flex items-center gap-6 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                    <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-green-500" /> Candles</span>
                    <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded bg-blue-500/40" /> Volume</span>
                </div>
                <div className="flex items-center gap-4">
                    <span className="text-[10px] font-black text-slate-600 tracking-tighter uppercase mr-4">BTT Trading Console v2.0</span>
                    <button className="flex items-center gap-2 text-[10px] font-black uppercase tracking-tighter text-blue-400 hover:text-blue-300 transition-colors">
                        EXPORT DATA <ExternalLink className="w-3 h-3" />
                    </button>
                </div>
            </div>
        </div>
    );
}

const MetricItem = ({ label, value, color }: { label: string; value: string; color: string }) => (
    <div className="flex flex-col items-end">
        <span className="text-[10px] font-black text-slate-500 tracking-widest uppercase mb-1">{label}</span>
        <span className={`text-2xl font-black ${color} tabular-nums tracking-tighter`}>{value}</span>
    </div>
);
