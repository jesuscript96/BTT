"use client";

import React from "react";
import {
    XAxis, YAxis, Tooltip, ResponsiveContainer,
    Area, CartesianGrid, ReferenceLine, ComposedChart, Line, ReferenceArea
} from "recharts";
import { Info, Clock } from "lucide-react";
import { API_URL } from "@/config/constants";

interface DistributionItem {
    label: string;
    value: number;
}

interface DistributionStats {
    hod_time?: Record<string, number>;
    lod_time?: Record<string, number>;
    [key: string]: any;
}

interface StatsAverages {
    gap_at_open_pct: number;
    pmh_fade_to_open_pct: number;
    rth_run_pct: number;
    high_spike_pct: number;
    low_spike_pct: number;
    close_red: number;
    rth_range_pct: number;
    low_spike_prev_close_pct: number;
    [key: string]: number;
}

interface DashboardStats {
    count: number;
    avg: StatsAverages;
    p25: StatsAverages;
    p50: StatsAverages;
    p75: StatsAverages;
    distributions: DistributionStats;
}

interface TimeSeriesItem {
    time: string;
    avg_change: number;
    median_change?: number;
}

interface DashboardProps {
    stats: DashboardStats;
    data: unknown[];
    aggregateSeries?: TimeSeriesItem[];
}

type StatMode = 'avg' | 'p25' | 'p50' | 'p75';

export const Dashboard: React.FC<DashboardProps> = ({ stats, aggregateSeries, data }) => {
    const [mode, setMode] = React.useState<StatMode>('avg');

    if (!stats || !stats.avg) return (
        <div className="p-20 text-center text-muted-foreground bg-background min-h-screen">
            Apply filters to see performance analysis
        </div>
    );

    const averages = stats[mode] || stats.avg;

    return (
        <div className="p-6 bg-background space-y-6 min-h-screen font-sans transition-colors duration-300">
            {/* Top Row: Metrics & Main Chart */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
                {/* Left Column: Metrics & List Info */}
                <div className="md:col-span-4 bg-transparent border-r border-border/40 p-6 space-y-12">
                    {/* Section: Sample Summary */}
                    <div className="flex flex-col gap-6">
                        <div className="flex items-center justify-between border-b border-border/40 pb-6">
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                                    <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Total Sample</span>
                                </div>
                                <span className="text-2xl font-black text-foreground tracking-tight truncate pl-3.5">{stats.count} RECORDS</span>
                            </div>
                            <div className="flex gap-3 text-[9px] font-black uppercase tracking-widest items-center">
                                {['avg', 'p25', 'p50', 'p75'].map((m) => (
                                    <span
                                        key={m}
                                        onClick={() => setMode(m as any)}
                                        className={`cursor-pointer transition-all ${mode === m ? 'text-blue-500 bg-blue-500/10 px-1.5 py-0.5 rounded' : 'text-muted-foreground/50 hover:text-foreground'}`}
                                    >
                                        {m === 'avg' ? 'AVG' : m === 'p25' ? '25th' : m === 'p50' ? 'MED' : '75th'}
                                    </span>
                                ))}
                            </div>
                        </div>

                        <div className="flex items-center gap-12 pl-3.5">
                            <div className="flex flex-col gap-1 relative">
                                <div className="absolute -left-3.5 top-0 bottom-0 w-0.5 bg-green-500/30 rounded-full"></div>
                                <div className="flex items-center gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                                    <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Bullish</span>
                                </div>
                                <span className="text-3xl font-black text-foreground tracking-tight">85.3%</span>
                            </div>
                            <div className="flex flex-col gap-1 border-l border-border/40 pl-12 opacity-80 relative">
                                <div className="flex items-center gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-purple-500"></div>
                                    <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">PMH BREAKER</span>
                                </div>
                                <span className="text-3xl font-black text-foreground tracking-tight">
                                    75th
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Section: Detailed Metrics */}
                    <div className="flex flex-col gap-8 pt-2">
                        <div className="flex items-center gap-2 border-b border-border/20 pb-4">
                            <div className="w-1.5 h-1.5 rounded-full bg-red-500"></div>
                            <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Performance Metrics</span>
                        </div>
                        <div className="grid grid-cols-2 gap-x-12 gap-y-10 pl-3.5">
                            <MetricIndicator label="PM High Gap" value={averages.pm_high_gap_pct} color="#3b82f6" />
                            <MetricIndicator label="PM Fade To Open" value={averages.pmh_fade_to_open_pct} color="#ef4444" />
                            <MetricIndicator label="Gap at Open" value={averages.gap_at_open_pct} color="#22c55e" />
                            <MetricIndicator label="RTH High Fade to Close" value={averages.rth_fade_to_close_pct} color="#ef4444" />
                            <MetricIndicator label="RTH High Run" value={averages.rth_high_run_pct} color="#3b82f6" />
                            <MetricIndicator label="PM High Break" value={averages.pm_high_break} color="#3b82f6" />
                            <MetricIndicator label="Close Red" value={averages.close_red} color="#ef4444" />
                            <MetricIndicator label="Low Spike" value={averages.low_spike_pct} color="#9ca3af" />
                            <MetricIndicator label="Range" value={averages.rth_range_pct} color="#8b5cf6" />
                            <MetricIndicator label="Low Spike vs prev. close" value={averages.low_spike_prev_close_pct} color="#f59e0b" />
                        </div>
                    </div>

                    {/* Section: Context Logs */}
                    <div className="space-y-8 pt-8 border-t border-border/20">
                        <div className="space-y-4">
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-amber-500"></div>
                                <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Volume stats</p>
                            </div>
                            <div className="pl-3.5 space-y-3">
                                <MetricRow label="Premarket Volume" value={formatLargeNumber(averages.avg_pm_volume)} />
                                <MetricRow label="Volume" value={formatLargeNumber(averages.avg_volume)} />
                            </div>
                        </div>

                        <div className="space-y-4">
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-cyan-500"></div>
                                <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Volatility context</p>
                            </div>
                            <div className="pl-3.5 space-y-3">
                                <MetricRow label="High Spike %" value={`${averages.high_spike_pct?.toFixed(2) || "0.00"}%`} />
                                <MetricRow label="Low Spike %" value={`${averages.low_spike_pct?.toFixed(2) || "0.00"}%`} />
                                <MetricRow label="Range %" value={`${averages.rth_range_pct?.toFixed(2) || "0.00"}%`} />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Column: Main Area Chart */}
                <div className="md:col-span-8 h-[500px] bg-transparent p-6">
                    <IntradayDashboardChart data={data} aggregateSeries={aggregateSeries} />
                </div>
            </div>
        </div>
    );
};

const MetricIndicator = ({ label, value, color }: { label: string; value: number | undefined; color: string }) => {
    const safeValue = value ?? 0;
    const isNegative = safeValue < 0;
    return (
        <div className="flex flex-col gap-1 group">
            <div className="flex items-center gap-2">
                <div className="w-1 h-3 rounded-full" style={{ backgroundColor: isNegative ? '#ef4444' : color }}></div>
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{label}</span>
            </div>
            <div className="pl-3">
                <span className={`text-xl font-black tracking-tight ${isNegative ? 'text-red-500' : 'text-foreground'}`}>
                    {safeValue >= 0 ? `${safeValue.toFixed(2)}%` : `${safeValue.toFixed(2)}%`}
                </span>
            </div>
        </div>
    );
};

const formatLargeNumber = (num: number) => {
    if (!num) return "0";
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return num.toFixed(0);
};

const transformDist = (dist: Record<string, number> | undefined) => {
    if (!dist) return [];
    return Object.entries(dist)
        .sort((a, b) => b[1] - a[1]) // Sort by count desc
        .map(([label, count]) => ({ label, value: count }))
        .slice(0, 10);
};

const getDefaultHOD = (dist: Record<string, number> | undefined) => {
    if (!dist || Object.keys(dist).length === 0) return "--:--";
    return Object.entries(dist).sort((a, b) => b[1] - a[1])[0][0];
};

const MetricRow = ({ label, value }: { label: string; value: string | undefined }) => (
    <div className="flex justify-between items-center text-[11px]">
        <span className="text-muted-foreground font-medium">{label}</span>
        <span className="text-foreground font-bold">{value}</span>
    </div>
);

const HorizontalDistributionCard = ({ title, value, data, icon }: { title: string; value: string; data: DistributionItem[]; icon: React.ReactNode }) => (
    <div className="bg-card border border-border p-5 rounded-xl space-y-5 shadow-sm hover:shadow-md transition-all">
        <div className="flex justify-between items-start">
            <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground uppercase font-bold tracking-[0.1em]">{title}</p>
                <p className="text-2xl font-black text-foreground tracking-tighter">{value}</p>
            </div>
            <div className="text-muted-foreground bg-muted p-1.5 rounded-full">{icon}</div>
        </div>
        <div className="space-y-1 mt-2">
            <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest mb-2">Distribution</p>
            <div className="h-40 overflow-y-auto pr-2 custom-scrollbar">
                {data.map((item, idx) => (
                    <div key={idx} className="flex items-center gap-3 mb-1.5">
                        <span className="text-[9px] text-muted-foreground font-bold w-16 truncate">{item.label}</span>
                        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                            <div
                                className="h-full bg-blue-500/60 rounded-full"
                                style={{ width: `${Math.min(item.value, 100)}%` }}
                            />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    </div>
);

const rangeDistribution = [
    { label: "0% - 10%", value: 85 },
    { label: "10% - 20%", value: 70 },
    { label: "20% - 30%", value: 65 },
    { label: "30% - 40%", value: 40 },
    { label: "40% - 50%", value: 30 },
    { label: "50% - 60%", value: 25 },
    { label: "60% - 70%", value: 15 },
    { label: "70% - 80%", value: 10 },
    { label: "80% - 90%", value: 8 },
    { label: ">100%", value: 25 },
];

const timeDistribution = [
    { label: "09:30 - 10:00", value: 90 },
    { label: "10:00 - 10:30", value: 35 },
    { label: "10:30 - 11:00", value: 25 },
    { label: "11:00 - 11:30", value: 20 },
    { label: "11:30 - 12:00", value: 15 },
    { label: "12:00 - 12:30", value: 10 },
    { label: "12:30 - 13:00", value: 12 },
    { label: "13:00 - 13:30", value: 18 },
    { label: "13:30 - 14:00", value: 22 },
    { label: "14:00 - 14:30", value: 28 },
    { label: "14:30 - 15:00", value: 32 },
    { label: "15:00 - 15:30", value: 45 },
    { label: "15:30 - 16:00", value: 80 },
];

const lowSpikeDistribution = rangeDistribution.map(d => ({ ...d, value: Math.floor(((d.value * 0.4) + 10) % 100) }));
const lodTimeDistribution = timeDistribution.map(d => ({ ...d, value: Math.floor(((d.value * 0.7) + 20) % 100) }));

const returnDistribution = [
    { label: "+100%", value: 5 },
    { label: "80 to 100%", value: 8 },
    { label: "60 to 80%", value: 12 },
    { label: "40 to 60%", value: 15 },
    { label: "20 to 40%", value: 25 },
    { label: "0 to 20%", value: 85 },
    { label: "0 to -20%", value: 40 },
    { label: "-20 to -40%", value: 15 },
    { label: "-40 to -60%", value: 5 },
];

const IntradayDashboardChart = ({ data, aggregateSeries }: { data: any[], aggregateSeries?: TimeSeriesItem[] }) => {
    const [chartData, setChartData] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [activeTicker, setActiveTicker] = React.useState<string>("");

    // Smoothing & Session state
    const [smoothing, setSmoothing] = React.useState<number>(1);
    const [sessions, setSessions] = React.useState({
        pre: false,
        market: true,
        post: false
    });

    const isAggregate = aggregateSeries && aggregateSeries.length > 0;

    // Effect to update ticker when data changes (Only if NOT aggregate mode)
    React.useEffect(() => {
        if (!isAggregate && data && data.length > 0) {
            setActiveTicker(data[0].ticker);
        }
    }, [data, isAggregate]);

    React.useEffect(() => {
        if (isAggregate) {
            // Processing Aggregate Data
            const processed = processData(aggregateSeries || []);
            setChartData(processed);
            return;
        }

        if (!activeTicker) return;
        setLoading(true);
        let url = `${API_URL}/market/ticker/${activeTicker}/intraday`;
        if (data && data[0] && data[0].date) {
            url += `?trade_date=${data[0].date}`;
        }

        fetch(url)
            .then(res => res.json())
            .then(resData => {
                const parsed = resData.map((d: any) => ({
                    ...d,
                    time: d.timestamp.split(' ')[1].substring(0, 5),
                    timeShort: d.timestamp.split(' ')[1].substring(0, 5)
                }));
                const processed = processData(parsed);
                setChartData(processed);
            })
            .catch(e => console.error("Chart fetch error", e))
            .finally(() => setLoading(false));
    }, [activeTicker, isAggregate, aggregateSeries, sessions, smoothing]);

    // Data Processing: Filter Sessions & Apply Smoothing
    const processData = (raw: any[]) => {
        if (!raw || raw.length === 0) return [];

        // 1. Filter Sessions
        const filtered = raw.filter(d => {
            const time = d.time || d.timeShort;
            if (!time) return true;

            if (time >= "04:00" && time < "09:30") return sessions.pre;
            if (time >= "09:30" && time < "16:00") return sessions.market;
            if (time >= "16:00" && time < "20:00") return sessions.post;
            return false;
        });

        if (smoothing <= 1) return filtered;

        // 2. Apply Smoothing (Simple Moving Average)
        return filtered.map((d, i, arr) => {
            const start = Math.max(0, i - Math.floor(smoothing / 2));
            const end = Math.min(arr.length, i + Math.ceil(smoothing / 2));
            const subset = arr.slice(start, end);

            const smoothed: any = { ...d };
            if (isAggregate) {
                smoothed.avg_change = subset.reduce((acc, curr) => acc + curr.avg_change, 0) / subset.length;
                smoothed.median_change = subset.reduce((acc, curr) => acc + (curr.median_change || 0), 0) / subset.length;
            } else {
                smoothed.close = subset.reduce((acc, curr) => acc + curr.close, 0) / subset.length;
            }
            return smoothed;
        });
    };

    if (!isAggregate && !activeTicker) {
        return (
            <div className="xl:col-span-7 bg-transparent border border-border p-8 flex items-center justify-center text-muted-foreground text-[10px] font-black uppercase tracking-widest">
                No intraday data available for selection.
            </div>
        );
    }

    // Min/Max for domain
    let minPrice: number, maxPrice: number;
    if (isAggregate) {
        // Find min/max of avg_change and median_change
        const vals = chartData.flatMap(d => [d.avg_change, d.median_change].filter(v => v !== undefined));
        minPrice = vals.length ? Math.min(...vals) : -1;
        maxPrice = vals.length ? Math.max(...vals) : 1;
        // Add some padding
        const range = maxPrice - minPrice;
        minPrice -= range * 0.1 || 0.1;
        maxPrice += range * 0.1 || 0.1;
    } else {
        const prices = chartData.map(d => d.close);
        minPrice = prices.length ? Math.min(...prices) * 0.99 : 0;
        maxPrice = prices.length ? Math.max(...prices) * 1.01 : 0;
    }

    // PM High check only for single ticker
    const pmHigh = !isAggregate && chartData.length > 0 ? chartData[0].pm_high : 0;

    return (
        <div className="xl:col-span-7 bg-transparent border-t border-border/40 p-8 space-y-8">
            <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        {isAggregate ? (
                            <>
                                <h3 className="text-lg font-black text-foreground tracking-tight">CHANGE VS. OPEN PRICE</h3>
                                <span className="text-[10px] font-bold uppercase text-muted-foreground tracking-wider">({data.length} EXTENSIONS AGGREGATE)</span>
                            </>
                        ) : (
                            <>
                                <h3 className="text-lg font-black text-foreground tracking-tight">{activeTicker}</h3>
                                <span className="text-[10px] font-bold uppercase text-muted-foreground tracking-wider">INTRADAY ACTION</span>
                            </>
                        )}
                    </div>
                    <div className="flex items-center gap-4 text-[10px] font-bold uppercase text-muted-foreground">
                        {isAggregate ? (
                            <>
                                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-600" /> AVERAGE</div>
                                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full border border-blue-400 border-dashed" /> MEDIAN</div>
                            </>
                        ) : (
                            <>
                                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-600" /> Price</div>
                                {pmHigh > 0 && <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-purple-500" /> PM High</div>}
                            </>
                        )}
                    </div>
                </div>

                {/* Session & Smoothing Controls */}
                <div className="flex flex-wrap items-center gap-6 pb-2 border-b border-border/40">
                    <div className="flex items-center gap-3">
                        <span className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Sessions:</span>
                        <div className="flex items-center gap-4">
                            <label className="flex items-center gap-2 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    checked={sessions.pre}
                                    onChange={(e) => setSessions(prev => ({ ...prev, pre: e.target.checked }))}
                                    className="hidden"
                                />
                                <div className={`w-3 h-3 rounded-sm border transition-all ${sessions.pre ? 'bg-blue-600 border-blue-600' : 'border-muted-foreground/30 group-hover:border-muted-foreground'}`} />
                                <span className={`text-[10px] font-bold uppercase ${sessions.pre ? 'text-foreground' : 'text-muted-foreground'}`}>Pre</span>
                            </label>
                            <label className="flex items-center gap-2 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    checked={sessions.market}
                                    onChange={(e) => setSessions(prev => ({ ...prev, market: e.target.checked }))}
                                    className="hidden"
                                />
                                <div className={`w-3 h-3 rounded-sm border transition-all ${sessions.market ? 'bg-blue-600 border-blue-600' : 'border-muted-foreground/30 group-hover:border-muted-foreground'}`} />
                                <span className={`text-[10px] font-bold uppercase ${sessions.market ? 'text-foreground' : 'text-muted-foreground'}`}>Market</span>
                            </label>
                            <label className="flex items-center gap-2 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    checked={sessions.post}
                                    onChange={(e) => setSessions(prev => ({ ...prev, post: e.target.checked }))}
                                    className="hidden"
                                />
                                <div className={`w-3 h-3 rounded-sm border transition-all ${sessions.post ? 'bg-blue-600 border-blue-600' : 'border-muted-foreground/30 group-hover:border-muted-foreground'}`} />
                                <span className={`text-[10px] font-bold uppercase ${sessions.post ? 'text-foreground' : 'text-muted-foreground'}`}>Post</span>
                            </label>
                        </div>
                    </div>

                    <div className="flex items-center gap-3">
                        <span className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Smoothing:</span>
                        <input
                            type="range"
                            min="1"
                            max="20"
                            value={smoothing}
                            onChange={(e) => setSmoothing(parseInt(e.target.value))}
                            className="w-24 h-1 bg-muted rounded-full appearance-none cursor-pointer accent-blue-600"
                        />
                        <span className="text-[10px] font-bold text-foreground w-4">{smoothing}</span>
                    </div>
                </div>
            </div>

            <div className="h-[400px] relative">
                {loading ? (
                    <div className="flex h-full items-center justify-center text-muted-foreground text-xs uppercase font-bold tracking-widest animate-pulse">Loading Chart...</div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" vertical={false} />
                            <XAxis
                                dataKey={isAggregate ? "time" : "timeShort"}
                                stroke="currentColor"
                                className="text-muted-foreground"
                                fontSize={10}
                                tickLine={false}
                                axisLine={false}
                                minTickGap={40}
                            />
                            <YAxis
                                stroke="currentColor"
                                className="text-muted-foreground"
                                fontSize={10}
                                tickLine={false}
                                axisLine={false}
                                domain={[minPrice, maxPrice]}
                                tickFormatter={(v) => v.toFixed(2) + (isAggregate ? "%" : "")}
                                orientation="right"
                            />
                            <Tooltip
                                contentStyle={{
                                    backgroundColor: 'var(--card)',
                                    border: '1px solid var(--border)',
                                    borderRadius: '8px',
                                    fontSize: '11px',
                                    color: 'var(--foreground)'
                                }}
                                itemStyle={{ color: 'var(--foreground)' }}
                                formatter={(value: any) => [value.toFixed(2) + (isAggregate ? "%" : ""), ""]}
                            />

                            {/* Session visual markers */}
                            {sessions.pre && (
                                <ReferenceArea x1="04:00" x2="09:30" fill="currentColor" fillOpacity={0.03} className="text-muted-foreground" />
                            )}
                            {sessions.market && (
                                <ReferenceArea x1="09:30" x2="16:00" fill="currentColor" fillOpacity={0.01} className="text-blue-500" />
                            )}
                            {sessions.post && (
                                <ReferenceArea x1="16:00" x2="20:00" fill="currentColor" fillOpacity={0.03} className="text-orange-500" />
                            )}

                            {isAggregate ? (
                                <>
                                    <Line type="monotone" dataKey="avg_change" stroke="#2563eb" strokeWidth={3} dot={false} name="Average" animationDuration={300} />
                                    <Line type="monotone" dataKey="median_change" stroke="#60a5fa" strokeWidth={2} strokeDasharray="4 4" dot={false} name="Median" animationDuration={300} />
                                </>
                            ) : (
                                <>
                                    {pmHigh > 0 && <ReferenceLine y={pmHigh} stroke="#a855f7" strokeDasharray="3 3" label={{ position: 'insideRight', value: 'PMH', fill: '#a855f7', fontSize: 10 }} />}
                                    <ReferenceLine x="09:30" stroke="currentColor" strokeDasharray="3 3" className="text-muted-foreground" />
                                    <Area type="monotone" dataKey="close" stroke="#2563eb" strokeWidth={2} fillOpacity={0.1} fill="#2563eb" dot={false} animationDuration={300} />
                                </>
                            )}
                        </ComposedChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};
