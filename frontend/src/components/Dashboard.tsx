"use client";

import React from "react";
import {
    XAxis, YAxis, Tooltip, ResponsiveContainer,
    Area, CartesianGrid, ReferenceLine, ComposedChart, Line, ReferenceArea
} from "recharts";
import { API_URL } from "@/config/constants";
import { NewsFeed } from "./NewsFeed";

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
    isLoadingAggregate?: boolean;
}

type StatMode = 'avg' | 'p25' | 'p50' | 'p75';

// ─── Sidebar Metric Row ───────────────────────────────────────────────
const SidebarMetricRow = ({ label, value, suffix = "%" }: { label: string; value: number | undefined; suffix?: string }) => {
    const safeValue = value ?? 0;
    const isNegative = safeValue < 0;
    const formatted = suffix === "%" ? `${safeValue.toFixed(2)}%` : `${safeValue.toFixed(2)}`;
    const badgeColor = isNegative ? "bg-red-500/15 text-red-500" : "bg-emerald-500/15 text-emerald-500";
    const badgeText = isNegative ? `${safeValue.toFixed(1)}%` : `+${safeValue.toFixed(1)}%`;

    return (
        <div className="flex items-center justify-between py-2.5 border-b border-border/40">
            <div className="flex flex-col gap-0.5">
                <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">{label}</span>
                <span className={`text-base font-black tracking-tight ${isNegative ? 'text-red-500' : 'text-foreground'}`}>
                    {formatted}
                </span>
            </div>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${badgeColor}`}>
                {badgeText}
            </span>
        </div>
    );
};

// ─── Format large numbers ─────────────────────────────────────────────
const formatLargeNumber = (num: number) => {
    if (!num) return "0";
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return num.toFixed(0);
};

// ─── Main Dashboard ───────────────────────────────────────────────────
export const Dashboard: React.FC<DashboardProps> = ({ stats, aggregateSeries, data, isLoadingAggregate }) => {
    const [mode, setMode] = React.useState<StatMode>('avg');

    const averages = stats?.[mode] ?? stats?.avg;

    // Empty State: Show News Feed
    if (!stats || !stats.avg) return (
        <div className="p-6 bg-background min-h-screen font-sans transition-colors duration-300">
            <div className="flex flex-col h-full gap-6">
                <div className="flex items-center justify-between border-b border-border/40 pb-4">
                    <div className="flex flex-col gap-1">
                        <h1 className="text-xl font-black tracking-tight text-foreground">MARKET INTELLIGENCE</h1>
                        <span className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">
                            WAITING FOR DATA... WHILE YOU WAIT, READ THE LATEST
                        </span>
                    </div>
                </div>
                <div className="flex-1 overflow-hidden">
                    <NewsFeed />
                </div>
            </div>
        </div>
    );

    return (
        <div className="p-6 bg-background min-h-screen font-sans transition-colors duration-300">
            {/* Top Row: Sidebar Metrics & Main Chart */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-0">

                {/* ═══ LEFT COLUMN: Stacked Metric Rows ═══ */}
                <div className="md:col-span-3 border-r border-border/40 pr-6 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 48px)' }}>
                    {/* Header: Sample + Mode Selector */}
                    <div className="flex items-center justify-between py-2.5 border-b border-border/40">
                        <div className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                                <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Total Sample</span>
                            </div>
                            <span className="text-lg font-black text-foreground tracking-tight">{stats.count} RECORDS</span>
                        </div>
                        <div className="flex gap-2 text-[9px] font-black uppercase tracking-widest items-center">
                            {(['avg', 'p25', 'p50', 'p75'] as const).map((m) => (
                                <span
                                    key={m}
                                    onClick={() => setMode(m)}
                                    className={`cursor-pointer transition-all ${mode === m ? 'text-blue-500 bg-blue-500/10 px-1.5 py-0.5 rounded' : 'text-muted-foreground/50 hover:text-foreground'}`}
                                >
                                    {m === 'avg' ? 'AVG' : m === 'p25' ? '25th' : m === 'p50' ? 'MED' : '75th'}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Metric Rows */}
                    <SidebarMetricRow label="Gap at Open" value={averages.gap_at_open_pct} />
                    <SidebarMetricRow label="PM High Gap" value={averages.pm_high_gap_pct} />
                    <SidebarMetricRow label="PM Fade to Open" value={averages.pmh_fade_to_open_pct} />
                    <SidebarMetricRow label="RTH High Run" value={averages.rth_high_run_pct} />
                    <SidebarMetricRow label="RTH High Fade to Close" value={averages.rth_fade_to_close_pct} />
                    <SidebarMetricRow label="PM High Break" value={averages.pm_high_break} />
                    <SidebarMetricRow label="Close Red" value={averages.close_red} />
                    <SidebarMetricRow label="Range" value={averages.rth_range_pct} />
                    <SidebarMetricRow label="Low Spike" value={averages.low_spike_pct} />
                    <SidebarMetricRow label="Low Spike vs Prev Close" value={averages.low_spike_prev_close_pct} />

                    {/* Volume rows */}
                    <div className="flex items-center justify-between py-2.5 border-b border-border/40">
                        <div className="flex flex-col gap-0.5">
                            <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Premarket Volume</span>
                            <span className="text-base font-black text-foreground tracking-tight">{formatLargeNumber(averages.avg_pm_volume)}</span>
                        </div>
                    </div>
                    <div className="flex items-center justify-between py-2.5 border-b border-border/40">
                        <div className="flex flex-col gap-0.5">
                            <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">Volume</span>
                            <span className="text-base font-black text-foreground tracking-tight">{formatLargeNumber(averages.avg_volume)}</span>
                        </div>
                    </div>

                    {/* Volatility rows */}
                    <div className="flex items-center justify-between py-2.5 border-b border-border/40">
                        <div className="flex flex-col gap-0.5">
                            <span className="text-[9px] font-black text-muted-foreground uppercase tracking-widest">High Spike</span>
                            <span className="text-base font-black text-foreground tracking-tight">{averages.high_spike_pct?.toFixed(2) || "0.00"}%</span>
                        </div>
                    </div>
                </div>

                {/* ═══ RIGHT COLUMN: Chart + Cards Below ═══ */}
                <div className="md:col-span-9 flex flex-col pl-6">
                    {/* Chart */}
                    <div className="h-[500px]">
                        <IntradayDashboardChart data={data} aggregateSeries={aggregateSeries} isLoadingAggregate={isLoadingAggregate} />
                    </div>

                    {/* Transparent cards below chart */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
                        {/* Volume Card */}
                        <div className="bg-transparent p-4">
                            <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest mb-3">Volume Stats</p>
                            <div className="space-y-2">
                                <div className="flex justify-between items-center text-[11px]">
                                    <span className="text-muted-foreground font-medium">Premarket Volume</span>
                                    <span className="text-foreground font-bold">{formatLargeNumber(averages.avg_pm_volume)}</span>
                                </div>
                                <div className="flex justify-between items-center text-[11px]">
                                    <span className="text-muted-foreground font-medium">Volume</span>
                                    <span className="text-foreground font-bold">{formatLargeNumber(averages.avg_volume)}</span>
                                </div>
                            </div>
                        </div>

                        {/* Volatility Card */}
                        <div className="bg-transparent p-4">
                            <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest mb-3">Volatility Context</p>
                            <div className="space-y-2">
                                <div className="flex justify-between items-center text-[11px]">
                                    <span className="text-muted-foreground font-medium">High Spike %</span>
                                    <span className="text-foreground font-bold">{averages.high_spike_pct?.toFixed(2) || "0.00"}%</span>
                                </div>
                                <div className="flex justify-between items-center text-[11px]">
                                    <span className="text-muted-foreground font-medium">Low Spike %</span>
                                    <span className="text-foreground font-bold">{averages.low_spike_pct?.toFixed(2) || "0.00"}%</span>
                                </div>
                                <div className="flex justify-between items-center text-[11px]">
                                    <span className="text-muted-foreground font-medium">Range %</span>
                                    <span className="text-foreground font-bold">{averages.rth_range_pct?.toFixed(2) || "0.00"}%</span>
                                </div>
                            </div>
                        </div>

                        {/* Bullish / PMH Breaker Card */}
                        <div className="bg-transparent p-4">
                            <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest mb-3">Signal Summary</p>
                            <div className="space-y-3">
                                <div className="flex items-center gap-3">
                                    <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                                    <div className="flex flex-col">
                                        <span className="text-[10px] font-bold text-muted-foreground uppercase">Bullish</span>
                                        <span className="text-xl font-black text-foreground tracking-tight">85.3%</span>
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                                    <div className="flex flex-col">
                                        <span className="text-[10px] font-bold text-muted-foreground uppercase">PMH Breaker</span>
                                        <span className="text-xl font-black text-foreground tracking-tight">75th</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

// ─── Intraday Chart (unchanged logic) ─────────────────────────────────
const IntradayDashboardChart = ({ data, aggregateSeries, isLoadingAggregate }: { data: any[], aggregateSeries?: TimeSeriesItem[], isLoadingAggregate?: boolean }) => {
    const [chartData, setChartData] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [activeTicker, setActiveTicker] = React.useState<string>("");

    const [smoothing, setSmoothing] = React.useState<number>(1);
    const [sessions, setSessions] = React.useState({
        pre: false,
        market: true,
        post: false
    });

    const isAggregate = aggregateSeries && aggregateSeries.length > 0;

    React.useEffect(() => {
        if (!isAggregate && data && data.length > 0) {
            setActiveTicker(data[0].ticker);
        }
    }, [data, isAggregate]);

    React.useEffect(() => {
        if (isAggregate) {
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

    const processData = (raw: any[]) => {
        if (!raw || raw.length === 0) return [];

        const filtered = raw.filter(d => {
            const time = d.time || d.timeShort;
            if (!time) return true;

            if (time >= "04:00" && time < "09:30") return sessions.pre;
            if (time >= "09:30" && time < "16:00") return sessions.market;
            if (time >= "16:00" && time < "20:00") return sessions.post;
            return false;
        });

        if (smoothing <= 1) return filtered;

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
            <div className="bg-transparent p-8 flex items-center justify-center text-muted-foreground text-[10px] font-black uppercase tracking-widest h-full">
                No intraday data available for selection.
            </div>
        );
    }

    let minPrice: number, maxPrice: number;
    if (isAggregate) {
        const vals = chartData.flatMap(d => [d.avg_change, d.median_change].filter(v => v !== undefined));
        minPrice = vals.length ? Math.min(...vals) : -1;
        maxPrice = vals.length ? Math.max(...vals) : 1;
        const range = maxPrice - minPrice;
        minPrice -= range * 0.1 || 0.1;
        maxPrice += range * 0.1 || 0.1;
    } else {
        const prices = chartData.map(d => d.close);
        minPrice = prices.length ? Math.min(...prices) * 0.99 : 0;
        maxPrice = prices.length ? Math.max(...prices) * 1.01 : 0;
    }

    const pmHigh = !isAggregate && chartData.length > 0 ? chartData[0].pm_high : 0;

    // Combined loading state
    const isChartLoading = loading || (isAggregate && isLoadingAggregate);

    return (
        <div className="bg-transparent p-8 space-y-6 h-full flex flex-col relative">
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

            <div className="flex-1 min-h-0 relative">
                {isChartLoading ? (
                    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-background/50 backdrop-blur-sm">
                        <div className="w-8 h-8 border-4 border-blue-500 border-solid rounded-full border-t-transparent animate-spin mb-4"></div>
                        <div className="text-muted-foreground text-[10px] uppercase font-bold tracking-widest">
                            {isLoadingAggregate ? "Aggregating Intraday Data..." : "Loading Chart..."}
                        </div>
                    </div>
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
