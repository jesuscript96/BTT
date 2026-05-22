"use client";

import React, { useState, useMemo } from 'react';
import {
    ComposedChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
    Scatter,
    Cell
} from 'recharts';
import regression from 'regression';

interface RegressionAnalysisProps {
    data: any[];
}

const AVAILABLE_METRICS = [
    { label: 'Gap %', value: 'gap_at_open_pct' },
    { label: 'Day Return %', value: 'day_return_pct' },
    { label: 'RTH Volume', value: 'rth_volume' },
    { label: 'PM Volume', value: 'pm_volume' },
    { label: 'High Spike %', value: 'high_spike_pct' },
    { label: 'Low Spike %', value: 'low_spike_pct' },
    { label: 'Pre-Market High', value: 'pm_high' },
    { label: 'Open Price', value: 'rth_open' },
    { label: 'Close Price', value: 'rth_close' },
    { label: 'RTH Range %', value: 'rth_range_pct' },
    { label: 'Time of HOD', value: 'hod_time' }, // Format issues potentially
    { label: 'Time of LOD', value: 'lod_time' },
];

export default function RegressionAnalysis({ data }: RegressionAnalysisProps) {
    const [xVariable, setXVariable] = useState<string>('gap_at_open_pct');
    const [yVariable, setYVariable] = useState<string>('day_return_pct');
    const [useCustomScales, setUseCustomScales] = useState(false);
    const [xMin, setXMin] = useState<string>('');
    const [xMax, setXMax] = useState<string>('');
    const [yMin, setYMin] = useState<string>('');
    const [yMax, setYMax] = useState<string>('');

    // --- Data Preparation ---
    const processedData = useMemo(() => {
        if (!data || data.length === 0) return { scatterData: [], trendData: [], r2: 0, formula: '' };

        // 1. Filter valid numbers
        const validPoints = data.filter(d =>
            typeof d[xVariable] === 'number' && !isNaN(d[xVariable]) &&
            typeof d[yVariable] === 'number' && !isNaN(d[yVariable])
        ).map(d => ({
            x: d[xVariable],
            y: d[yVariable],
            payload: d // Keep original for tooltip/color
        }));

        if (validPoints.length < 2) return { scatterData: [], trendData: [], r2: 0, formula: 'Not enough data' };

        // 2. Calculate Regression (Polynomial order 2)
        const regressionPoints = validPoints.map(p => [p.x, p.y]);
        const result = regression.polynomial(regressionPoints, { order: 2, precision: 4 });

        // 3. Generate Trendline Points (smooth curve)
        // Find min/max X to draw the line across the range
        const xValues = validPoints.map(p => p.x);
        const minX = Math.min(...xValues);
        const maxX = Math.max(...xValues);
        const range = maxX - minX;
        const step = range / 50; // 50 points for smoothness

        const trendData = [];
        for (let x = minX; x <= maxX; x += step) {
            const y = result.predict(x)[1];
            trendData.push({ x, y });
        }

        return {
            scatterData: validPoints,
            trendData: trendData.sort((a, b) => a.x - b.x),
            r2: result.r2,
            formula: result.string
        };

    }, [data, xVariable, yVariable]);

    // --- Helpers ---
    const formatValue = (val: number, key: string) => {
        if (key.includes('pct') || key.includes('percent')) return `${val.toFixed(2)}%`;
        if (key.includes('volume')) return `${(val / 1000000).toFixed(2)}M`;
        return val.toFixed(2);
    };

    const handleSwitch = () => {
        setXVariable(yVariable);
        setYVariable(xVariable);
    };

    return (
        <div className="flex flex-col md:flex-row gap-6 h-full min-h-[500px]">

            {/* Sidebar Controls */}
            <div className="w-full md:w-80 flex flex-col gap-8 p-6 bg-transparent border-r border-border/40 overflow-y-auto transition-colors">
                <div>
                    <h3 className="text-[10px] font-black uppercase text-muted-foreground tracking-widest pl-1">Linear Regression ({processedData.scatterData.length} SMPL)</h3>
                </div>

                <div className="space-y-6">
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest pl-1">Independent Variable (X)</label>
                        <select
                            className="w-full bg-background border border-border rounded px-3 py-2 text-xs font-bold text-foreground focus:ring-2 focus:ring-primary transition-colors"
                            value={xVariable}
                            onChange={(e) => setXVariable(e.target.value)}
                        >
                            {AVAILABLE_METRICS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest pl-1">Dependent Variable (Y)</label>
                        <select
                            className="w-full bg-background border border-border rounded px-3 py-2 text-xs font-bold text-foreground focus:ring-2 focus:ring-primary transition-colors"
                            value={yVariable}
                            onChange={(e) => setYVariable(e.target.value)}
                        >
                            {AVAILABLE_METRICS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                        </select>
                    </div>

                    <button
                        onClick={handleSwitch}
                        className="w-full py-2 px-4 bg-muted hover:bg-muted/80 text-foreground text-[10px] font-black uppercase tracking-widest rounded border border-border transition-all"
                    >
                        Switch variables
                    </button>
                </div>

                <div className="space-y-4 pt-6 border-t border-border/40">
                    <div className="flex items-center gap-3">
                        <input
                            type="checkbox"
                            id="customScales"
                            checked={useCustomScales}
                            onChange={(e) => setUseCustomScales(e.target.checked)}
                            className="w-3 h-3 rounded-sm border-border bg-background text-primary focus:ring-0"
                        />
                        <label htmlFor="customScales" className="text-[10px] font-black text-muted-foreground uppercase tracking-widest cursor-pointer">Scale Manual</label>
                    </div>

                    {useCustomScales && (
                        <div className="grid grid-cols-2 gap-2">
                            <div className='flex flex-col gap-1'>
                                <span className='text-[10px] text-muted-foreground'>X Min</span>
                                <input type="number" className="bg-background border border-border rounded px-2 py-1 text-xs" value={xMin} onChange={e => setXMin(e.target.value)} placeholder="Auto" />
                            </div>
                            <div className='flex flex-col gap-1'>
                                <span className='text-[10px] text-muted-foreground'>X Max</span>
                                <input type="number" className="bg-background border border-border rounded px-2 py-1 text-xs" value={xMax} onChange={e => setXMax(e.target.value)} placeholder="Auto" />
                            </div>
                            <div className='flex flex-col gap-1'>
                                <span className='text-[10px] text-muted-foreground'>Y Min</span>
                                <input type="number" className="bg-background border border-border rounded px-2 py-1 text-xs" value={yMin} onChange={e => setYMin(e.target.value)} placeholder="Auto" />
                            </div>
                            <div className='flex flex-col gap-1'>
                                <span className='text-[10px] text-muted-foreground'>Y Max</span>
                                <input type="number" className="bg-background border border-border rounded px-2 py-1 text-xs" value={yMax} onChange={e => setYMax(e.target.value)} placeholder="Auto" />
                            </div>
                        </div>
                    )}
                </div>

                <div className="mt-auto pt-8">
                    <div className="bg-transparent border-t border-border/40 py-6 space-y-2">
                        <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest pl-1">Correlation (R²)</div>
                        <div className="text-3xl font-black text-foreground tracking-tighter">{processedData.r2.toFixed(4)}</div>
                        <div className="text-[9px] font-bold text-muted-foreground mt-4 break-all opacity-60">{processedData.formula}</div>
                    </div>
                </div>
            </div>

            {/* Chart Area */}
            <div className="flex-1 p-6 relative min-h-[400px] bg-transparent">
                {/* Legend Header */}
                <div className="absolute top-6 right-8 flex gap-8 text-[10px] font-black uppercase tracking-widest bg-background/50 p-3 rounded backdrop-blur-md border border-border/40 z-10">
                    <div className="flex items-center gap-2">
                        <div className="w-4 h-0.5 bg-blue-500 rounded-full"></div>
                        <span className="text-muted-foreground">Quadratic Trend</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.3)]"></div>
                        <span className="text-muted-foreground">Close Grn</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.3)]"></div>
                        <span className="text-muted-foreground">Close Red</span>
                    </div>
                </div>

                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                        margin={{ top: 20, right: 20, bottom: 20, left: 20 }}
                    >
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.5} />
                        <XAxis
                            dataKey="x"
                            type="number"
                            name={xVariable}
                            unit={""}
                            domain={[
                                useCustomScales && xMin !== '' ? Number(xMin) : 'auto',
                                useCustomScales && xMax !== '' ? Number(xMax) : 'auto'
                            ]}
                            tickFormatter={(val) => formatValue(val, xVariable)}
                            stroke="var(--muted-foreground)"
                            label={{ value: AVAILABLE_METRICS.find(m => m.value === xVariable)?.label || xVariable, position: 'insideBottom', offset: -10, fill: 'var(--muted-foreground)', fontSize: 12 }}
                        />
                        <YAxis
                            dataKey="y"
                            type="number"
                            name={yVariable}
                            unit={""}
                            domain={[
                                useCustomScales && yMin !== '' ? Number(yMin) : 'auto',
                                useCustomScales && yMax !== '' ? Number(yMax) : 'auto'
                            ]}
                            tickFormatter={(val) => formatValue(val, yVariable)}
                            stroke="var(--muted-foreground)"
                            label={{ value: AVAILABLE_METRICS.find(m => m.value === yVariable)?.label || yVariable, angle: -90, position: 'insideLeft', fill: 'var(--muted-foreground)', fontSize: 12 }}
                        />
                        <Tooltip
                            cursor={{ strokeDasharray: '3 3' }}
                            content={({ active, payload }) => {
                                if (active && payload && payload.length) {
                                    const p = payload[0].payload;
                                    // If it's a scatter point, it has 'payload' property with full data
                                    const isPoint = p.payload;

                                    if (isPoint) {
                                        const d = p.payload;
                                        return (
                                            <div className="bg-popover border border-border p-3 rounded shadow-lg text-xs">
                                                <div className="font-bold text-popover-foreground mb-1">{d.ticker} - {d.date}</div>
                                                <div className="text-muted-foreground">{AVAILABLE_METRICS.find(m => m.value === xVariable)?.label}: <span className="text-foreground">{formatValue(d[xVariable], xVariable)}</span></div>
                                                <div className="text-muted-foreground">{AVAILABLE_METRICS.find(m => m.value === yVariable)?.label}: <span className="text-foreground">{formatValue(d[yVariable], yVariable)}</span></div>
                                                <div className="mt-2 pt-2 border-t border-border flex justify-between gap-4">
                                                    <span className={d.rth_close > d.rth_open ? "text-green-500" : "text-red-500"}>
                                                        {d.rth_close > d.rth_open ? "Green Day" : "Red Day"}
                                                    </span>
                                                </div>
                                            </div>
                                        );
                                    }
                                    return null;
                                }
                                return null;
                            }}
                        />

                        {/* Scatter Plot */}
                        <Scatter name="Data" data={processedData.scatterData} fill="#8884d8" shape="circle">
                            {processedData.scatterData.map((entry: any, index: number) => {
                                const isGreen = entry.payload.rth_close > entry.payload.prev_close; // Or open? Screenshot says "Close Green" vs "Close Red". Usually vs Prev Close or Open? 
                                // User screenshot says "Close Green" "Close Red". Usually means Close > Open (Candle color).
                                // Let's use Close > Open for Candle Color logic.
                                const candleGreen = entry.payload.rth_close > entry.payload.rth_open;
                                return <Cell key={`cell-${index}`} fill={candleGreen ? '#22c55e' : '#ef4444'} />; // Green-500 : Red-500
                            })}
                        </Scatter>

                        {/* Trendline */}
                        <Line
                            data={processedData.trendData}
                            type="monotone"
                            dataKey="y"
                            stroke="#3b82f6"
                            strokeWidth={2}
                            dot={false}
                            activeDot={false}
                            name="Quadratic Regression"
                        />

                    </ComposedChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
