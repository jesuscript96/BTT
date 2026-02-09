"use client";

import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, LineData, UTCTimestamp, LineSeries } from 'lightweight-charts';
import { BacktestResult } from '@/types/backtest';

interface EquityCurveChartProps {
    result: BacktestResult;
}

export function EquityCurveChart({ result }: EquityCurveChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartApiRef = useRef<IChartApi | null>(null);
    const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const handleResize = () => {
            if (chartApiRef.current && chartContainerRef.current) {
                chartApiRef.current.applyOptions({
                    width: chartContainerRef.current.clientWidth
                });
            }
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: 'rgba(156, 163, 175, 0.8)', // text-muted-foreground approximate
            },
            grid: {
                vertLines: { color: 'rgba(156, 163, 175, 0.1)' },
                horzLines: { color: 'rgba(156, 163, 175, 0.1)' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: 'rgba(156, 163, 175, 0.2)',
            },
            rightPriceScale: {
                borderColor: 'rgba(156, 163, 175, 0.2)',
                scaleMargins: {
                    top: 0.1,
                    bottom: 0.1,
                },
            },
            crosshair: {
                mode: 0, // Normal
                vertLine: {
                    labelBackgroundColor: '#3b82f6',
                },
                horzLine: {
                    labelBackgroundColor: '#3b82f6',
                },
            },
        });

        const lineSeries = chart.addSeries(LineSeries, {
            color: '#3b82f6',
            lineWidth: 2,
            crosshairMarkerVisible: true,
            priceFormat: {
                type: 'price',
                precision: 0,
                minMove: 1,
            },
        });

        chartApiRef.current = chart;
        lineSeriesRef.current = lineSeries;

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    useEffect(() => {
        if (lineSeriesRef.current && result.equity_curve) {
            // Preparing data for lightweight-charts
            // NOTE: No downsampling needed here as this canvas library handles 100k+ points easily
            const chartData: LineData[] = result.equity_curve.map(point => ({
                time: (new Date(point.timestamp).getTime() / 1000) as UTCTimestamp,
                value: point.balance,
            })).sort((a, b) => Number(a.time) - Number(b.time));

            // Removal of duplicates if any (strictly required by library)
            const uniqueData = chartData.filter((item, index, self) =>
                index === self.findIndex((t) => t.time === item.time)
            );

            lineSeriesRef.current.setData(uniqueData);

            if (chartApiRef.current) {
                chartApiRef.current.timeScale().fitContent();
            }
        }
    }, [result.equity_curve]);

    return (
        <div className="bg-card rounded-xl border border-border p-6 shadow-sm transition-colors">
            <div className="mb-6 flex justify-between items-end">
                <div>
                    <h2 className="text-xl font-black text-foreground mb-1">Portfolio Equity Curve</h2>
                    <p className="text-sm text-muted-foreground">
                        High-precision performance visualization
                    </p>
                </div>
                <div className="text-right">
                    <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Balance</span>
                    <div className="text-2xl font-black text-blue-600">
                        ${result.final_balance.toLocaleString()}
                    </div>
                </div>
            </div>

            <div className="relative w-full overflow-hidden" ref={chartContainerRef}>
                {/* Chart renders here */}
            </div>

            {/* Performance KPIs Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-8 pt-6 border-t border-border">
                <div className="p-3 rounded-xl bg-muted/30">
                    <div className="text-[9px] font-black text-muted-foreground uppercase tracking-widest mb-1">Starting Capital</div>
                    <div className="text-lg font-black text-foreground tabular-nums">
                        ${result.initial_capital.toLocaleString()}
                    </div>
                </div>
                <div className="p-3 rounded-xl bg-green-500/5">
                    <div className="text-[9px] font-black text-green-500 uppercase tracking-widest mb-1">Total Return</div>
                    <div className={`text-lg font-black tabular-nums ${result.total_return_pct >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                        {result.total_return_pct >= 0 ? '+' : ''}{result.total_return_pct.toFixed(2)}%
                    </div>
                </div>
                <div className="p-3 rounded-xl bg-blue-500/5">
                    <div className="text-[9px] font-black text-blue-500 uppercase tracking-widest mb-1">Return in R</div>
                    <div className="text-lg font-black text-blue-500 tabular-nums">
                        {result.total_return_r >= 0 ? '+' : ''}{result.total_return_r.toFixed(2)}R
                    </div>
                </div>
                <div className="p-3 rounded-xl bg-purple-500/5">
                    <div className="text-[9px] font-black text-purple-500 uppercase tracking-widest mb-1">Sharpe Ratio</div>
                    <div className="text-lg font-black text-purple-500 tabular-nums">
                        {result.sharpe_ratio.toFixed(2)}
                    </div>
                </div>
            </div>
        </div>
    );
}
