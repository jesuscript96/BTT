"use client";

import React from "react";
import {
    XAxis, YAxis, Tooltip, ResponsiveContainer,
    Area, CartesianGrid, ReferenceLine, ComposedChart, Line
} from "recharts";
import { Info, Clock } from "lucide-react";

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
    [key: string]: number;
}

interface DashboardStats {
    count: number;
    averages: StatsAverages;
    distributions: DistributionStats;
}

interface TimeSeriesItem {
    time: string;
    value: number;
    median?: number;
}

interface DashboardProps {
    stats: DashboardStats;
    data: unknown[];
    aggregateSeries?: TimeSeriesItem[];
}

export const Dashboard: React.FC<DashboardProps> = ({ stats, aggregateSeries, data }) => {
    if (!stats || !stats.averages) return (
        <div className="p-20 text-center text-zinc-500 bg-[#F9F9F8] min-h-screen">
            Apply filters to see performance analysis
        </div>
    );

    const averages = stats.averages;

    return (
        <div className="p-6 bg-[#F9F9F8] space-y-6 min-h-screen font-sans">
            {/* Top Row: Metrics & Main Chart */}
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">

                {/* Left Column: Metric Groups (Stats, Volume, Price, Return) */}
                <div className="xl:col-span-5 bg-white border border-zinc-200 text-zinc-900 p-6 rounded-xl shadow-sm space-y-8">
                    <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
                        <h2 className="text-xl font-black uppercase tracking-tight text-zinc-900">{stats.count} RECORDS</h2>
                        <div className="flex gap-3 text-[10px] font-bold uppercase tracking-wider items-center">
                            <span className="px-2 py-0.5 bg-zinc-100 text-zinc-900 rounded">Average</span>
                            <span className="text-zinc-400 hover:text-zinc-600 cursor-pointer transition-colors">25th</span>
                            <span className="text-zinc-400 hover:text-zinc-600 cursor-pointer transition-colors">Median</span>
                            <span className="text-zinc-400 hover:text-zinc-600 cursor-pointer transition-colors">75th</span>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-10">
                        {/* Progress Bars Section */}
                        <div className="space-y-5">
                            <StatProgress label="PM High Gap %" value={averages.gap_at_open_pct} color="#4ade80" />
                            <StatProgress label="PM Fade To Open %" value={averages.pmh_fade_to_open_pct} color="#f87171" />
                            <StatProgress label="Gap at Open %" value={averages.gap_at_open_pct} color="#22c55e" />
                            <StatProgress label="RTH Fade To Close %" value={averages.rth_fade_to_close_pct} color="#ef4444" />

                            <div className="pt-4 space-y-4">
                                <StatProgress label="Open < VWAP" value={averages.open_lt_vwap} color="#f59e0b" />
                                <StatProgress label="PM High Break" value={averages.pm_high_break} color="#3b82f6" />
                                <StatProgress label="Close Red" value={averages.close_direction_red} color="#ef4444" />
                            </div>
                        </div>

                        {/* List Stats Section */}
                        <div className="space-y-8">
                            <div className="space-y-3">
                                <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-[0.2em]">Volume</p>
                                <MetricRow label="Premarket Volume" value={formatLargeNumber(averages.avg_pm_volume)} />
                                <MetricRow label="Volume" value={formatLargeNumber(averages.avg_volume)} />
                            </div>

                            <div className="space-y-3 pt-2">
                                <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-[0.2em]">Price</p>
                                <MetricRow label="PMH Price" value={averages.avg_pmh_price?.toFixed(2)} />
                                <MetricRow label="Open Price" value={averages.avg_open_price?.toFixed(2)} />
                                <MetricRow label="Close Price" value={averages.avg_close_price?.toFixed(2)} />
                            </div>

                            <div className="space-y-3 pt-2">
                                <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-[0.2em]">Return</p>
                                <MetricRow label="M15 Return %" value={`${averages.m15_return_pct?.toFixed(2)}%`} />
                                <MetricRow label="M30 Return %" value={`${averages.m30_return_pct?.toFixed(2)}%`} />
                                <MetricRow label="M60 Return %" value={`${averages.m60_return_pct?.toFixed(2)}%`} />
                            </div>

                            <div className="pt-4 space-y-4">
                                <StatProgress label="Close < M15 Price" value={averages.close_lt_m15} color="#f97316" />
                                <StatProgress label="Close < M30 Price" value={averages.close_lt_m30} color="#06b6d4" />
                                <StatProgress label="Close < M60 Price" value={averages.close_lt_m60} color="#8b5cf6" />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Column: Main Area Chart (Intraday for Top Ticker) */}
                <IntradayDashboardChart data={data} />
            </div>

            {/* Bottom Row: Distribution Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-6">
                <HorizontalDistributionCard
                    title="HIGH SPIKE AVERAGE"
                    value={`${stats.averages.high_spike_pct?.toFixed(2)}%`}
                    data={rangeDistribution}
                    icon={<Info className="w-3 h-3" />}
                />
                <HorizontalDistributionCard
                    title="LOW SPIKE AVERAGE"
                    value={`${stats.averages.low_spike_pct?.toFixed(2)}%`}
                    data={lowSpikeDistribution}
                    icon={<Info className="w-3 h-3" />}
                />
                <HorizontalDistributionCard
                    title="HOD AVERAGE TIME"
                    value={getDefaultHOD(stats.distributions.hod_time)}
                    data={transformDist(stats.distributions.hod_time)}
                    icon={<Clock className="w-3 h-3" />}
                />
                <HorizontalDistributionCard
                    title="LOD AVERAGE TIME"
                    value={getDefaultHOD(stats.distributions.lod_time)}
                    data={transformDist(stats.distributions.lod_time)}
                    icon={<Clock className="w-3 h-3" />}
                />
                <HorizontalDistributionCard
                    title="RETURN AVERAGE"
                    value={`${stats.averages.rth_run_pct?.toFixed(2)}%`}
                    data={returnDistribution}
                    icon={<Info className="w-3 h-3" />}
                />
            </div>
        </div>
    );
};

const StatProgress = ({ label, value, color }: { label: string; value: number | undefined; color: string }) => {
    const safeValue = value ?? 0;
    return (
        <div className="space-y-1.5">
            <div className="flex justify-between items-center text-[10px] font-bold uppercase tracking-wide">
                <span className="text-zinc-500">{label}</span>
                <span style={{ color: safeValue < 0 ? '#ef4444' : color }} className="font-black">
                    {safeValue >= 0 ? `${safeValue.toFixed(2)}%` : `${safeValue.toFixed(2)}%`}
                </span>
            </div>
            <div className="h-1.5 w-full bg-zinc-100 rounded-full overflow-hidden border border-zinc-200/50">
                <div
                    className="h-full transition-all duration-700 ease-out"
                    style={{
                        width: `${Math.min(Math.max(Math.abs(safeValue), 5), 100)}%`,
                        backgroundColor: safeValue < 0 ? '#ef4444' : color
                    }}
                />
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
        <span className="text-zinc-400 font-medium">{label}</span>
        <span className="text-zinc-900 font-bold">{value}</span>
    </div>
);

const HorizontalDistributionCard = ({ title, value, data, icon }: { title: string; value: string; data: DistributionItem[]; icon: React.ReactNode }) => (
    <div className="bg-white border border-zinc-200 p-5 rounded-xl space-y-5 shadow-sm hover:shadow-md transition-all">
        <div className="flex justify-between items-start">
            <div className="space-y-1">
                <p className="text-[10px] text-zinc-400 uppercase font-bold tracking-[0.1em]">{title}</p>
                <p className="text-2xl font-black text-zinc-900 tracking-tighter">{value}</p>
            </div>
            <div className="text-zinc-300 bg-zinc-50 p-1.5 rounded-full">{icon}</div>
        </div>
        <div className="space-y-1 mt-2">
            <p className="text-[9px] font-black text-zinc-400 uppercase tracking-widest mb-2">Distribution</p>
            <div className="h-40 overflow-y-auto pr-2 custom-scrollbar">
                {data.map((item, idx) => (
                    <div key={idx} className="flex items-center gap-3 mb-1.5">
                        <span className="text-[9px] text-zinc-400 font-bold w-16 truncate">{item.label}</span>
                        <div className="flex-1 h-2 bg-zinc-50 rounded-full overflow-hidden">
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

const IntradayDashboardChart = ({ data }: { data: any[] }) => {
    const [chartData, setChartData] = React.useState<any[]>([]);
    const [loading, setLoading] = React.useState(false);
    const [activeTicker, setActiveTicker] = React.useState<string>("");

    // Effect to update ticker when data changes
    React.useEffect(() => {
        if (data && data.length > 0) {
            setActiveTicker(data[0].ticker);
        }
    }, [data]);

    React.useEffect(() => {
        if (!activeTicker) return;
        setLoading(true);
        // Default to latest date logic handled by backend if trade_date not passed
        // We could pass date from data[0].date if available
        let url = `http://localhost:8000/api/market/ticker/${activeTicker}/intraday`;
        if (data && data[0] && data[0].date) {
            url += `?trade_date=${data[0].date}`;
        }

        fetch(url)
            .then(res => res.json())
            .then(resData => {
                const parsed = resData.map((d: any) => ({
                    ...d,
                    timeShort: d.timestamp.split(' ')[1].substring(0, 5)
                }));
                setChartData(parsed);
            })
            .catch(e => console.error("Chart fetch error", e))
            .finally(() => setLoading(false));
    }, [activeTicker]);

    if (!activeTicker) {
        return (
            <div className="xl:col-span-7 bg-white border border-zinc-200 p-8 rounded-xl shadow-sm flex items-center justify-center text-zinc-400 text-sm">
                No data selected for charting.
            </div>
        );
    }

    // Min/Max for domain
    const prices = chartData.map(d => d.close);
    const minPrice = prices.length ? Math.min(...prices) * 0.99 : 0;
    const maxPrice = prices.length ? Math.max(...prices) * 1.01 : 0;
    const pmHigh = chartData.length > 0 ? chartData[0].pm_high : 0;

    return (
        <div className="xl:col-span-7 bg-white border border-zinc-200 p-8 rounded-xl shadow-sm space-y-6">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <h3 className="text-lg font-black text-zinc-900 tracking-tight">{activeTicker}</h3>
                    <span className="text-[10px] font-bold uppercase text-zinc-400 tracking-wider">INTRADAY ACTION</span>
                </div>
                <div className="flex items-center gap-4 text-[10px] font-bold uppercase text-zinc-400">
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-600" /> Price</div>
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-orange-400" /> VWAP</div>
                    {pmHigh > 0 && <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-purple-500" /> PM High</div>}
                </div>
            </div>

            <div className="h-[400px] relative">
                {loading ? (
                    <div className="flex h-full items-center justify-center text-zinc-400 text-xs uppercase font-bold tracking-widest animate-pulse">Loading Chart...</div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                            <XAxis
                                dataKey="timeShort"
                                stroke="#94a3b8"
                                fontSize={10}
                                tickLine={false}
                                axisLine={false}
                                minTickGap={40}
                            />
                            <YAxis
                                stroke="#94a3b8"
                                fontSize={10}
                                tickLine={false}
                                axisLine={false}
                                domain={[minPrice, maxPrice]}
                                tickFormatter={(v) => v.toFixed(2)}
                                orientation="right"
                            />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '11px', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)' }}
                            />
                            {pmHigh > 0 && <ReferenceLine y={pmHigh} stroke="#a855f7" strokeDasharray="3 3" label={{ position: 'insideRight', value: 'PMH', fill: '#a855f7', fontSize: 10 }} />}
                            <Area type="monotone" dataKey="close" stroke="#2563eb" strokeWidth={2} fillOpacity={0.1} fill="#2563eb" dot={false} />
                            <Line type="monotone" dataKey="vwap" stroke="#fb923c" strokeWidth={2} dot={false} />
                        </ComposedChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
};
