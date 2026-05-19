"use client";

import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, BaselineSeries, BaselineData, UTCTimestamp } from 'lightweight-charts';
import { BacktestResult } from '@/types/backtest';

interface DrawdownChartProps {
    result: BacktestResult;
}

export function DrawdownChart({ result }: DrawdownChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartApiRef = useRef<IChartApi | null>(null);
    const baselineSeriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);

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
                textColor: 'rgba(156, 163, 175, 0.8)',
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
            },
            crosshair: {
                mode: 0,
                vertLine: { labelBackgroundColor: '#ef4444' },
                horzLine: { labelBackgroundColor: '#ef4444' },
            },
        });

        // Using Baseline series for drawdown (Red for negative, transparent for 0)
        const baselineSeries = chart.addSeries(BaselineSeries, {
            baseValue: { type: 'price', price: 0 },
            topFillColor1: 'rgba(239, 68, 68, 0.05)',
            topFillColor2: 'rgba(239, 68, 68, 0.05)',
            topLineColor: '#ef4444',
            bottomFillColor1: 'rgba(239, 68, 68, 0.2)',
            bottomFillColor2: 'rgba(239, 68, 68, 0.05)',
            bottomLineColor: '#ef4444',
            lineWidth: 2,
            priceFormat: {
                type: 'price',
                precision: 2,
                minMove: 0.01,
            },
        });

        chartApiRef.current = chart;
        baselineSeriesRef.current = baselineSeries;

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    useEffect(() => {
        if (baselineSeriesRef.current && result.drawdown_series) {
            const chartData: BaselineData[] = result.drawdown_series.map(point => ({
                time: (new Date(point.timestamp).getTime() / 1000) as UTCTimestamp,
                value: -point.drawdown_pct,
            })).sort((a, b) => Number(a.time) - Number(b.time));

            const uniqueData = chartData.filter((item, index, self) =>
                index === self.findIndex((t) => t.time === item.time)
            );

            baselineSeriesRef.current.setData(uniqueData);

            if (chartApiRef.current) {
                chartApiRef.current.timeScale().fitContent();
            }
        }
    }, [result.drawdown_series]);

    return (
        <div className="bg-card rounded-xl border border-border p-6 shadow-sm transition-colors">
            <div className="mb-6">
                <h2 className="text-xl font-black text-foreground mb-1">Drawdown & Stagnation</h2>
                <p className="text-sm text-muted-foreground">
                    Portfolio depth from all-time highs
                </p>
            </div>

            <div className="relative w-full overflow-hidden" ref={chartContainerRef}>
                {/* Chart renders here */}
            </div>

            <div className="grid grid-cols-3 gap-4 mt-8 pt-6 border-t border-border">
                <div className="p-3 rounded-xl bg-red-500/5">
                    <div className="text-[9px] font-black text-red-500 uppercase tracking-widest mb-1">Max Drawdown</div>
                    <div className="text-lg font-black text-red-500 tabular-nums">
                        -{result.max_drawdown_pct.toFixed(2)}%
                    </div>
                </div>
                <div className="p-3 rounded-xl bg-muted/30">
                    <div className="text-[9px] font-black text-muted-foreground uppercase tracking-widest mb-1">Max DD Value</div>
                    <div className="text-lg font-black text-foreground tabular-nums">
                        -${result.max_drawdown_value.toLocaleString()}
                    </div>
                </div>
                <div className="p-3 rounded-xl bg-orange-500/5">
                    <div className="text-[9px] font-black text-orange-500 uppercase tracking-widest mb-1">Recovery status</div>
                    <div className="text-sm font-black text-orange-500 uppercase tracking-tight">
                        {result.drawdown_series[result.drawdown_series.length - 1]?.drawdown_pct === 0
                            ? "At Peak"
                            : "Recovering"}
                    </div>
                </div>
            </div>
        </div>
    );
}
