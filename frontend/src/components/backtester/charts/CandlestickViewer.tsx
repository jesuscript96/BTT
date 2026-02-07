"use client";

import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, CandlestickData, UTCTimestamp, CandlestickSeries, SeriesMarker } from 'lightweight-charts';
import { Trade } from '@/types/backtest';

interface CandlestickViewerProps {
    ticker: string;
    dateFrom: string;
    dateTo: string;
    trades?: Trade[];
}

export function CandlestickViewer({ ticker, dateFrom, dateTo, trades = [] }: CandlestickViewerProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartApiRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<any>(null); // Use any for v5 compat if types are inconsistent
    const [isLoading, setIsLoading] = useState(false);

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
                textColor: '#6b7280',
            },
            grid: {
                vertLines: { color: '#f3f4f6' },
                horzLines: { color: '#f3f4f6' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 500,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: '#e5e7eb',
            },
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#10b981',
            downColor: '#ef4444',
            borderVisible: false,
            wickUpColor: '#10b981',
            wickDownColor: '#ef4444',
        });

        chartApiRef.current = chart;
        candleSeriesRef.current = candleSeries;

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    useEffect(() => {
        const fetchData = async () => {
            if (!candleSeriesRef.current) return;

            setIsLoading(true);
            try {
                // Buffer the range slightly to see context
                const fromDate = new Date(dateFrom);
                fromDate.setHours(fromDate.getHours() - 1);
                const toDate = new Date(dateTo);
                toDate.setHours(toDate.getHours() + 1);

                const response = await fetch(`/api/data/historical?ticker=${ticker}&date_from=${fromDate.toISOString()}&date_to=${toDate.toISOString()}`);
                const data = await response.json();

                if (Array.isArray(data) && data.length > 0) {
                    const candleData: CandlestickData[] = data.map(d => ({
                        time: d.time as UTCTimestamp,
                        open: d.open,
                        high: d.high,
                        low: d.low,
                        close: d.close,
                    }));

                    candleSeriesRef.current.setData(candleData);

                    // Add markers for trades
                    const markers: SeriesMarker<UTCTimestamp>[] = [];
                    trades.filter(t => t.ticker === ticker).forEach(trade => {
                        const entryTime = (new Date(trade.entry_time).getTime() / 1000) as UTCTimestamp;
                        markers.push({
                            time: entryTime,
                            position: 'belowBar',
                            color: '#3b82f6',
                            shape: 'arrowUp',
                            text: `Entry @ ${trade.entry_price.toFixed(2)}`,
                        });

                        if (trade.exit_time) {
                            const exitTime = (new Date(trade.exit_time).getTime() / 1000) as UTCTimestamp;
                            markers.push({
                                time: exitTime,
                                position: 'aboveBar',
                                color: trade.r_multiple && trade.r_multiple > 0 ? '#10b981' : '#ef4444',
                                shape: 'arrowDown',
                                text: `Exit @ ${trade.exit_price?.toFixed(2)} (${trade.exit_reason})`,
                            });
                        }
                    });

                    candleSeriesRef.current.setMarkers(markers.sort((a, b) => Number(a.time) - Number(b.time)));

                    if (chartApiRef.current) {
                        chartApiRef.current.timeScale().fitContent();
                    }
                }
            } catch (error) {
                console.error("Error fetching candlestick data:", error);
            } finally {
                setIsLoading(false);
            }
        };

        fetchData();
    }, [ticker, dateFrom, dateTo, trades]);

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
            <div className="mb-6 flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-bold text-gray-900 mb-1">
                        Chart: <span className="text-blue-600">{ticker}</span>
                    </h2>
                    <p className="text-sm text-gray-500">
                        {new Date(dateFrom).toLocaleDateString()} Trade Context
                    </p>
                </div>
                {isLoading && (
                    <div className="flex items-center gap-2 text-blue-600">
                        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
                        <span className="text-xs font-semibold">Loading Data...</span>
                    </div>
                )}
            </div>

            <div className="relative w-full border border-gray-100 rounded-lg overflow-hidden" ref={chartContainerRef}>
                {/* Chart renders here */}
            </div>
        </div>
    );
}
