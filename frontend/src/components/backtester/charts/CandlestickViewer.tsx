"use client";

import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, CandlestickData, UTCTimestamp, CandlestickSeries, SeriesMarker, LineData, HistogramData, LineSeries, HistogramSeries } from 'lightweight-charts';
import { Trade } from '@/types/backtest';
import { IndicatorConfig, IndicatorType, Strategy } from '@/types/strategy';
import { Plus, X } from 'lucide-react';
import { API_URL } from '@/config/constants';

interface CandlestickViewerProps {
    ticker: string;
    dateFrom: string;
    dateTo: string;
    trades?: Trade[];
    trade?: Trade;
}

const getColor = (str: string) => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
    return '#' + '00000'.substring(0, 6 - c.length) + c;
};

export function CandlestickViewer({ ticker, dateFrom, dateTo, trades = [], trade }: CandlestickViewerProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartApiRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<any>(null); // Use any for v5 compat if types are inconsistent
    const indicatorSeriesRef = useRef<Map<string, ISeriesApi<"Line" | "Histogram">>>(new Map());
    const tradeLineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

    const [isLoading, setIsLoading] = useState(false);
    const [chartError, setChartError] = useState<string | null>(null);

    // Indicators
    const [strategy, setStrategy] = useState<Strategy | null>(null);
    const [selectedIndicators, setSelectedIndicators] = useState<IndicatorConfig[]>([]);
    const [showIndicatorMenu, setShowIndicatorMenu] = useState(false);

    const availableIndicators: IndicatorConfig[] = [
        { name: IndicatorType.SMA, period: 20 },
        { name: IndicatorType.SMA, period: 50 },
        { name: IndicatorType.SMA, period: 200 },
        { name: IndicatorType.EMA, period: 9 },
        { name: IndicatorType.EMA, period: 21 },
        { name: IndicatorType.VWAP },
        { name: IndicatorType.RSI, period: 14 },
        { name: IndicatorType.MACD },
        { name: IndicatorType.ATR, period: 14 },
    ];

    // Fetch Strategy to extract indicators
    useEffect(() => {
        if (!trade?.strategy_id) return;

        const fetchStrategy = async () => {
            try {
                const res = await fetch(`${API_URL}/strategies/${trade.strategy_id}`);
                if (res.ok) {
                    const contentType = res.headers.get("content-type");
                    if (contentType && contentType.indexOf("application/json") !== -1) {
                        const strat: Strategy = await res.json();
                        setStrategy(strat);

                        const extract = (group: any): IndicatorConfig[] => {
                            let inds: IndicatorConfig[] = [];
                            if (!group || !group.conditions) return inds;
                            for (const cond of group.conditions) {
                                if (cond.type === "group") {
                                    inds = [...inds, ...extract(cond)];
                                } else if (cond.type === "indicator_comparison") {
                                    if (cond.source && typeof cond.source !== "number") inds.push(cond.source as IndicatorConfig);
                                    if (cond.target && typeof cond.target !== "number") inds.push(cond.target as IndicatorConfig);
                                } else if (cond.type === "price_level_distance") {
                                    inds.push({ name: cond.level as IndicatorType });
                                }
                            }
                            return inds;
                        };

                        const extracted = [
                            ...extract(strat.entry_logic?.root_condition),
                            ...extract(strat.exit_logic?.root_condition)
                        ];

                        const unique = Array.from(new Map(extracted.map(ind => [JSON.stringify(ind), ind])).values());
                        const plottable = unique.filter((ind: IndicatorConfig) =>
                            !["Close", "Open", "High", "Low", "Volume", "Time of Day", "Consecutive Red Candles", "Consecutive Higher Highs", "Consecutive Lower Lows"].includes(ind.name)
                        );

                        setSelectedIndicators(plottable);
                    }
                }
            } catch (e) {
                console.error("Error fetching strategy for indicators", e);
            }
        };
        fetchStrategy();
    }, [trade?.strategy_id]);

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
            if (!candleSeriesRef.current || !chartApiRef.current) return;

            setIsLoading(true);
            try {
                // Buffer the range slightly to see context
                const fromDate = new Date(dateFrom);
                fromDate.setHours(fromDate.getHours() - 1);
                const toDate = new Date(dateTo);
                toDate.setHours(toDate.getHours() + 1);

                const indQuery = selectedIndicators.length > 0 ? `&indicators=${encodeURIComponent(JSON.stringify(selectedIndicators))}` : '';
                const url = `${API_URL}/data/historical?ticker=${ticker}&date_from=${fromDate.toISOString()}&date_to=${toDate.toISOString()}${indQuery}`;
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to fetch data: ${response.statusText}`);
                }
                const contentType = response.headers.get("content-type");
                if (!contentType || contentType.indexOf("application/json") === -1) {
                    const text = await response.text();
                    console.error("Non-JSON response:", text);
                    throw new Error("Received non-JSON response from server");
                }
                const data = await response.json();

                if (Array.isArray(data) && data.length > 0) {
                    try {
                        setChartError(null); // Clear previous errors
                        const candleData: CandlestickData[] = data
                            .filter(d => d.open !== null && d.high !== null && d.low !== null && d.close !== null)
                            .map(d => ({
                                time: d.time as UTCTimestamp,
                                open: d.open,
                                high: d.high,
                                low: d.low,
                                close: d.close,
                            }));

                        candleSeriesRef.current.setData(candleData);

                        // Add markers for trades
                        const markers: SeriesMarker<UTCTimestamp>[] = [];
                        trades.filter(t => t.ticker === ticker).forEach(t => {
                            const tEntryTime = Math.floor(new Date(t.entry_time).getTime() / 1000);
                            let startIndex = candleData.findIndex(d => Number(d.time) >= tEntryTime);
                            if (startIndex === -1 && candleData.length > 0) startIndex = candleData.length - 1;
                            if (startIndex !== -1) {
                                markers.push({
                                    time: candleData[startIndex].time as UTCTimestamp,
                                    position: 'belowBar',
                                    color: '#3b82f6',
                                    shape: 'arrowUp',
                                    text: `Entry @ ${t.entry_price.toFixed(2)}`,
                                });
                            }

                            if (t.exit_time) {
                                const tExitTime = Math.floor(new Date(t.exit_time).getTime() / 1000);
                                let endIndex = candleData.findIndex(d => Number(d.time) >= tExitTime);
                                if (endIndex === -1 && candleData.length > 0 && tExitTime > Number(candleData[candleData.length - 1].time)) {
                                    endIndex = candleData.length - 1;
                                }
                                if (endIndex !== -1) {
                                    markers.push({
                                        time: candleData[endIndex].time as UTCTimestamp,
                                        position: 'aboveBar',
                                        color: t.r_multiple && t.r_multiple > 0 ? '#10b981' : '#ef4444',
                                        shape: 'arrowDown',
                                        text: `Exit @ ${t.exit_price?.toFixed(2)} (${t.exit_reason})`,
                                    });
                                }
                            }
                        });

                        candleSeriesRef.current.setMarkers(markers.sort((a, b) => Number(a.time) - Number(b.time)));

                        // Clear old indicator series
                        indicatorSeriesRef.current.forEach(series => chartApiRef.current?.removeSeries(series));
                        indicatorSeriesRef.current.clear();

                        // Plot indicators
                        selectedIndicators.forEach(ind => {
                            const colName = ind.period && !["VWAP", "MACD"].includes(ind.name) ? `${ind.name}_${ind.period}` : ind.name;
                            const isHistogram = ind.name === "MACD" || (ind.name as string) === "VOLUME";

                            let series;
                            if (isHistogram) {
                                series = chartApiRef.current?.addSeries(HistogramSeries, {
                                    color: '#3b82f6',
                                    priceFormat: { type: 'volume' },
                                    priceScaleId: '',
                                });
                                chartApiRef.current?.priceScale('').applyOptions({
                                    scaleMargins: { top: 0.8, bottom: 0 },
                                });
                            } else {
                                series = chartApiRef.current?.addSeries(LineSeries, {
                                    color: getColor(colName),
                                    lineWidth: 2,
                                    title: colName,
                                });
                            }

                            if (series) {
                                const seriesData = data
                                    .filter((d: any) => d[colName] !== null && d[colName] !== undefined)
                                    .map((d: any) => ({
                                        time: d.time as UTCTimestamp,
                                        value: Number(d[colName]),
                                        color: isHistogram ? (d.open <= d.close ? '#10b981' : '#ef4444') : undefined
                                    }));
                                series.setData(seriesData as any);
                                indicatorSeriesRef.current.set(colName, series);
                            }
                        });

                        // Draw Line connecting Entry and Exit for the selected trade
                        if (tradeLineSeriesRef.current) {
                            chartApiRef.current.removeSeries(tradeLineSeriesRef.current);
                            tradeLineSeriesRef.current = null;
                        }

                        if (trade && trade.exit_time) {
                            const tEntryTime = Math.floor(new Date(trade.entry_time).getTime() / 1000);
                            const tExitTime = Math.floor(new Date(trade.exit_time).getTime() / 1000);

                            // Find closest candles to use exact times from the dataset
                            const startIndex = candleData.findIndex(d => Number(d.time) >= tEntryTime);
                            let endIndex = candleData.findIndex(d => Number(d.time) >= tExitTime);

                            // If exit is beyond our data view, just draw to the end of the available points
                            if (endIndex === -1 && startIndex !== -1 && tExitTime > Number(candleData[candleData.length - 1].time)) {
                                endIndex = candleData.length - 1;
                            }

                            if (startIndex !== -1 && endIndex !== -1 && endIndex > startIndex) {
                                tradeLineSeriesRef.current = chartApiRef.current.addSeries(LineSeries, {
                                    color: trade.r_multiple && trade.r_multiple > 0 ? '#10b981' : '#ef4444',
                                    lineWidth: 2,
                                    lineStyle: 3, // Dashed
                                    lastValueVisible: false,
                                    priceLineVisible: false,
                                    crosshairMarkerVisible: false,
                                });

                                const tradeData = candleData.slice(startIndex, endIndex + 1);
                                const startPx = trade.entry_price;
                                const endPx = trade.exit_price!;
                                const startTime = Number(tradeData[0].time);
                                const endTime = Number(tradeData[tradeData.length - 1].time);

                                const lineData = tradeData.map(d => {
                                    const ratio = (Number(d.time) - startTime) / (endTime - startTime);
                                    return {
                                        time: d.time as UTCTimestamp,
                                        value: startPx + (endPx - startPx) * ratio
                                    };
                                });

                                tradeLineSeriesRef.current.setData(lineData as any);
                            }
                        }

                        if (chartApiRef.current) {
                            chartApiRef.current.timeScale().fitContent();
                        }
                    } catch (err: any) {
                        console.error("Charting error:", err);
                        setChartError(err.message || String(err));
                    }
                } else {
                    candleSeriesRef.current.setData([]);
                    setChartError("No data available for the selected period.");
                }
            } catch (error) {
                console.error("Error fetching candlestick data:", error);
                setChartError((error as Error).message || "An unknown error occurred while fetching data.");
            } finally {
                setIsLoading(false);
            }
        };

        fetchData();
    }, [ticker, dateFrom, dateTo, trades, trade, selectedIndicators]);

    const toggleIndicator = (ind: IndicatorConfig) => {
        setSelectedIndicators(prev => {
            const exists = prev.some(p => p.name === ind.name && p.period === ind.period);
            if (exists) {
                return prev.filter(p => !(p.name === ind.name && p.period === ind.period));
            } else {
                return [...prev, ind];
            }
        });
        setShowIndicatorMenu(false);
    };

    return (
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
            <div className="mb-6 flex justify-between items-start">
                <div>
                    <h2 className="text-xl font-bold text-gray-900 mb-1 flex items-center gap-3">
                        <span>Chart: <span className="text-blue-600">{ticker}</span></span>
                        {trade && (
                            <span className={`text-[10px] uppercase font-black px-2 py-0.5 rounded border ${trade.r_multiple && trade.r_multiple > 0 ? 'bg-green-50 text-green-600 border-green-200' :
                                'bg-red-50 text-red-600 border-red-200'
                                }`}>
                                {trade.strategy_name} ({trade.r_multiple ? trade.r_multiple.toFixed(2) + 'R' : ''})
                            </span>
                        )}
                    </h2>
                    <p className="text-sm text-gray-500">
                        {new Date(dateFrom).toLocaleDateString()} Trade Context
                    </p>

                    {/* Active Indicators Pills */}
                    <div className="flex flex-wrap gap-2 mt-3 relative">
                        {selectedIndicators.map((ind, i) => {
                            const label = ind.period && !["VWAP", "MACD"].includes(ind.name) ? `${ind.name} ${ind.period}` : ind.name;
                            return (
                                <div key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-50 border border-blue-100 text-xs font-semibold text-blue-700">
                                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: getColor(label.replace(" ", "_")) }}></span>
                                    {label}
                                    <button onClick={() => toggleIndicator(ind)} className="hover:text-blue-900 ml-1">
                                        <X className="w-3 h-3" />
                                    </button>
                                </div>
                            );
                        })}

                        <div className="relative">
                            <button
                                onClick={() => setShowIndicatorMenu(!showIndicatorMenu)}
                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-gray-50 border border-gray-200 text-xs font-semibold text-gray-600 hover:bg-gray-100 transition-colors"
                            >
                                <Plus className="w-3 h-3" /> Add
                            </button>

                            {showIndicatorMenu && (
                                <div className="absolute top-full left-0 mt-1 w-48 bg-white rounded-lg shadow-xl border border-gray-100 py-1 z-50">
                                    {availableIndicators.map((ind, i) => {
                                        const label = ind.period && !["VWAP", "MACD"].includes(ind.name) ? `${ind.name} ${ind.period}` : ind.name;
                                        const isActive = selectedIndicators.some(p => p.name === ind.name && p.period === ind.period);
                                        return (
                                            <button
                                                key={i}
                                                onClick={() => toggleIndicator(ind)}
                                                className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 flex items-center justify-between ${isActive ? 'text-blue-600 font-bold bg-blue-50/50' : 'text-gray-700'}`}
                                            >
                                                {label}
                                                {isActive && <span className="text-blue-600 text-xs">✓</span>}
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
                {isLoading && (
                    <div className="flex items-center gap-2 text-blue-600">
                        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
                        <span className="text-xs font-semibold">Loading Data...</span>
                    </div>
                )}
            </div>

            {chartError && (
                <div className="bg-red-50 border border-red-200 text-red-600 p-4 rounded-md mb-4 text-sm font-mono whitespace-pre-wrap">
                    Lightweight Charts Error:<br />{chartError}
                </div>
            )}

            <div className="relative w-full border border-gray-100 rounded-lg overflow-hidden" ref={chartContainerRef}>
                {/* Chart renders here */}
            </div>
        </div>
    );
}
