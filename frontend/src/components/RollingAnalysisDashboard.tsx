"use client";

import { useState, useMemo, useEffect } from "react";
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid,
    Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from "recharts";

type MetricType = 'rth_range_pct' | 'return_close_vs_open_pct' | 'high_spike_pct' | 'low_spike_pct' | 'gap_extension_pct' | 'close_index_pct' | 'pmh_gap_pct' | 'pm_fade_at_open_pct';

interface DailyMetric {
    date: string;
    rth_range_pct: number;
    return_close_vs_open_pct: number;
    high_spike_pct: number;
    low_spike_pct: number;
    gap_extension_pct: number;
    close_index_pct: number;
    pmh_gap_pct: number;
    pm_fade_at_open_pct: number;
}

interface RollingAnalysisDashboardProps {
    ticker: string;
    startDate?: string;
    endDate?: string;
}

// Stats helper
const calculateRolling = (
    data: DailyMetric[],
    window: number,
    metric: MetricType,
    agg: 'mean' | 'median'
) => {
    if (!data || data.length === 0) return [];

    // We Map first, then calculate
    const values = data.map(d => d[metric]);
    const result = [];

    for (let i = 0; i < values.length; i++) {
        if (i < window - 1) {
            result.push(null);
            continue;
        }
        const slice = values.slice(i - window + 1, i + 1);
        if (agg === 'mean') {
            const sum = slice.reduce((a, b) => a + b, 0);
            result.push(sum / window);
        } else {
            // Median
            const sorted = [...slice].sort((a, b) => a - b);
            const mid = Math.floor(sorted.length / 2);
            result.push(sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2);
        }
    }
    return result;
};

export default function RollingAnalysisDashboard({ ticker, startDate, endDate }: RollingAnalysisDashboardProps) {
    const [rawData, setRawData] = useState<DailyMetric[]>([]);
    const [loading, setLoading] = useState(true);

    // Controls
    const [selectedMetric, setSelectedMetric] = useState<MetricType>('rth_range_pct');
    const [aggregation, setAggregation] = useState<'mean' | 'median'>('median');
    const [shortWindow, setShortWindow] = useState(25); // User screenshot showed 25
    const [longWindow, setLongWindow] = useState(200);
    const [timespan, setTimespan] = useState('All'); // '1M', '3M', '6M', '1Y', 'All'

    // Load Data
    useEffect(() => {
        async function fetchData() {
            try {
                setLoading(true);
                const res = await fetch(`http://localhost:8000/api/market/ticker/${ticker}/metrics_history?limit=1000`);
                if (!res.ok) throw new Error("Failed to load metrics");
                const json = await res.json();
                setRawData(json);
            } catch (e) {
                console.error(e);
            } finally {
                setLoading(false);
            }
        }
        if (ticker) fetchData();
    }, [ticker]);

    // Chart Data Preparation
    const chartData = useMemo(() => {
        if (!rawData.length) return [];

        // 1. Calculate Rolling Series on FULL Data (to ensure accuracy of first points in range)
        const shortSeries = calculateRolling(rawData, shortWindow, selectedMetric, aggregation);
        const longSeries = calculateRolling(rawData, longWindow, selectedMetric, aggregation);

        const combined = rawData.map((d, i) => ({
            date: d.date,
            value: d[selectedMetric],
            short: shortSeries[i],
            long: longSeries[i],
        }));

        // 2. Filter Display Data
        let filtered = combined;

        // Priority 1: Global Props (startDate / endDate)
        if (startDate || endDate) {
            if (startDate) filtered = filtered.filter(d => d.date >= startDate);
            if (endDate) filtered = filtered.filter(d => d.date <= endDate);
        }
        // Priority 2: Local Timespan (only if no global dates?) 
        // User asked "Why is there data prior to my filter". 
        // So global filter should override "All". 
        // But if user clicks local buttons, what happens? 
        // Let's assume Global Filter acts as a "Bound", and Timespan acts as a "Zoom" within that? 
        // Or simpler: If Global Filer is present, ignore Timespan state (or set it to Custom).
        // Let's implement: If startDate/endDate provided, use them. Else use timespan logic.
        else {
            const now = new Date();
            let cutoff = new Date("2000-01-01");
            if (timespan === '1M') cutoff = new Date(now.setMonth(now.getMonth() - 1));
            else if (timespan === '3M') cutoff = new Date(now.setMonth(now.getMonth() - 3));
            else if (timespan === '6M') cutoff = new Date(now.setMonth(now.getMonth() - 6));
            else if (timespan === '1Y') cutoff = new Date(now.setFullYear(now.getFullYear() - 1));

            if (timespan !== 'All') {
                const limitDate = cutoff.toISOString().split('T')[0];
                filtered = filtered.filter(d => d.date >= limitDate);
            }
        }

        return filtered;

    }, [rawData, timespan, shortWindow, longWindow, selectedMetric, aggregation, startDate, endDate]);

    const METRICS: { label: string, value: MetricType }[] = [
        { label: 'RTH Range %', value: 'rth_range_pct' },
        { label: 'Return Close vs Open %', value: 'return_close_vs_open_pct' },
        { label: 'High Spikes %', value: 'high_spike_pct' },
        { label: 'Low Spikes %', value: 'low_spike_pct' },
        { label: 'Gap Extension %', value: 'gap_extension_pct' },
        { label: 'Close Index %', value: 'close_index_pct' },
        { label: 'PMH Gap %', value: 'pmh_gap_pct' },
        { label: 'PM Fade at Open %', value: 'pm_fade_at_open_pct' },
    ];


    if (loading) return <div className="p-8 text-center text-muted-foreground animate-pulse">Loading Metrics...</div>;

    return (
        <div className="flex flex-col gap-6 p-4 bg-card rounded-xl text-card-foreground border border-border">

            {/* Controls */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-4 bg-muted/30 rounded-lg border border-border">

                {/* Metric Selector */}
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground uppercase font-mono">Metric</span>
                    <select
                        className="bg-background border border-border rounded p-2 text-sm focus:outline-none focus:border-ring text-foreground"
                        value={selectedMetric}
                        onChange={(e) => setSelectedMetric(e.target.value as MetricType)}
                    >
                        {METRICS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                </div>

                {/* Rolling Windows & Aggregation */}
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground uppercase font-mono">Rolling Windows</span>
                    <div className="flex gap-2 items-center">
                        <input
                            type="number"
                            className="w-16 bg-background border border-border rounded p-1 text-sm text-center text-foreground focus:outline-none focus:border-ring"
                            value={shortWindow} onChange={e => setShortWindow(Number(e.target.value))}
                        />
                        <span className="text-muted-foreground">/</span>
                        <input
                            type="number"
                            className="w-16 bg-background border border-border rounded p-1 text-sm text-center text-foreground focus:outline-none focus:border-ring"
                            value={longWindow} onChange={e => setLongWindow(Number(e.target.value))}
                        />
                        <button
                            onClick={() => setAggregation(prev => prev === 'mean' ? 'median' : 'mean')}
                            className="ml-auto px-2 py-1 bg-blue-500/10 text-blue-500 text-xs rounded border border-blue-500/20 hover:bg-blue-500/20 transition-colors"
                        >
                            {aggregation.toUpperCase()}
                        </button>
                    </div>
                </div>

                {/* Timespan */}
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground uppercase font-mono">Timespan</span>
                    <div className="flex gap-1">
                        {['1M', '3M', '6M', '1Y', 'All'].map(t => (
                            <button
                                key={t}
                                onClick={() => setTimespan(t)}
                                className={`px-3 py-1 text-xs rounded border transition-colors ${timespan === t
                                    ? 'bg-blue-600 border-blue-500 text-white'
                                    : 'bg-background border-border text-muted-foreground hover:bg-muted hover:text-foreground'
                                    }`}
                            >
                                {t}
                            </button>
                        ))}
                    </div>
                </div>

            </div>

            {/* Chart */}
            <div className="h-[400px] w-full bg-muted/10 rounded-lg border border-border p-4 relative">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 20, right: 30, left: 10, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} opacity={0.5} />
                        <XAxis
                            dataKey="date"
                            stroke="var(--muted-foreground)"
                            tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
                            minTickGap={40}
                            tickLine={false}
                            axisLine={false}
                        />
                        <YAxis
                            stroke="var(--muted-foreground)"
                            tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
                            tickFormatter={(v) => typeof v === 'number' ? `${v.toFixed(1)}%` : ''}
                            tickLine={false}
                            axisLine={false}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: 'var(--card)',
                                borderColor: 'var(--border)',
                                color: 'var(--card-foreground)',
                                borderRadius: '8px',
                                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'
                            }}
                            itemStyle={{ color: 'var(--foreground)' }}
                            formatter={(val: number | undefined) => (val !== undefined && val !== null) ? val.toFixed(2) + '%' : ''}
                            labelStyle={{ color: 'var(--muted-foreground)', marginBottom: '4px' }}
                            cursor={{ stroke: 'var(--muted-foreground)', strokeWidth: 1, strokeDasharray: '4 4' }}
                        />
                        <Legend wrapperStyle={{ paddingTop: '10px' }} />

                        <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="3 3" />

                        {/* Short Term Line */}
                        <Line
                            type="monotone"
                            dataKey="short"
                            stroke="#3b82f6" // Blue is generally safe for both modes, or use var(--ring)
                            strokeWidth={2}
                            dot={false}
                            name={`Rolling ${shortWindow} (${aggregation})`}
                            isAnimationActive={false}
                        />

                        {/* Long Term Line */}
                        <Line
                            type="monotone"
                            dataKey="long"
                            stroke="#f59e0b" // Orange/Amber
                            strokeWidth={2}
                            strokeDasharray="4 4"
                            dot={false}
                            name={`Rolling ${longWindow} (${aggregation})`}
                            isAnimationActive={false}
                        />

                    </LineChart>
                </ResponsiveContainer>
            </div>

        </div>
    );
}
