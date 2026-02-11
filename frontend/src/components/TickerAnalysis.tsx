"use client";

import React, { useState, useEffect } from 'react';
import {
    Activity, Globe, MapPin, Building2, Users, FileText,
    ArrowUpRight, ArrowDownRight, ExternalLink, ChevronDown, ChevronUp
} from 'lucide-react';
import {
    LineChart, Line, ResponsiveContainer, YAxis
} from 'recharts';
import { API_URL } from '@/config/constants';

interface TickerAnalysisProps {
    ticker?: string;
    availableTickers: string[]; // For the combobox
}

// Sparkline Component
const Sparkline = ({ data, color }: { data: any[], color: string }) => {
    if (!data || data.length === 0) return <div className="h-12 w-full bg-muted/20 animate-pulse rounded"></div>;
    return (
        <div className="h-12 w-full">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                    <Line
                        type="monotone"
                        dataKey="value"
                        stroke={color}
                        strokeWidth={2}
                        dot={false}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};

export default function TickerAnalysis({ ticker: initialTicker, availableTickers }: TickerAnalysisProps) {
    const [selectedTicker, setSelectedTicker] = useState<string>(initialTicker || availableTickers[0] || '');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState<any>(null);
    const [filings, setFilings] = useState<any>(null);
    const [showFullDesc, setShowFullDesc] = useState(false);

    // Update if prop changes
    useEffect(() => {
        if (initialTicker) setSelectedTicker(initialTicker);
    }, [initialTicker]);

    // Fetch Data
    useEffect(() => {
        if (!selectedTicker) return;

        const fetchData = async () => {
            setLoading(true);
            try {
                // Parallel fetching
                const [analysisRes, filingsRes] = await Promise.all([
                    fetch(`${API_URL}/ticker-analysis/${selectedTicker}`),
                    fetch(`${API_URL}/ticker-analysis/${selectedTicker}/sec-filings`)
                ]);

                if (analysisRes.ok) setData(await analysisRes.json());
                if (filingsRes.ok) setFilings(await filingsRes.json());

            } catch (error) {
                console.error("Error fetching ticker analysis:", error);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [selectedTicker]);

    if (!selectedTicker) return <div className="p-8 text-center text-muted-foreground">Select a ticker to view analysis</div>;

    // Helpers
    const formatNumber = (num: number | null) => {
        if (num === null || num === undefined) return '-';
        if (num >= 1e9) return `$ ${(num / 1e9).toFixed(2)} B`;
        if (num >= 1e6) return `$ ${(num / 1e6).toFixed(2)} M`;
        if (num >= 1e3) return `$ ${(num / 1e3).toFixed(2)} K`;
        return num.toFixed(2);
    };

    const formatPercent = (num: number | null) => {
        if (num === null || num === undefined) return '-';
        return `${(num * 100).toFixed(2)}%`; // assuming raw decimal e.g. 0.05
    };

    // YFinance sometimes returns percents as 0.05 (5%) or 5 (5%). 
    // Usually 'heldPercent' is 0.X. 'performance' from our backend is returned as 100-based (e.g. 5.2).
    const formatPerf = (num: number | null) => {
        if (num === null || num === undefined) return '-';
        return `${num.toFixed(2)}%`;
    };


    return (
        <div className="flex flex-col gap-6 p-4 max-w-7xl mx-auto pb-20">

            {/* Header / Selector */}
            <div className="flex items-center justify-between gap-4 bg-card p-4 rounded-xl border border-border shadow-sm">
                <div className="flex items-center gap-4">
                    {data?.profile?.logo_url ? (
                        <img src={data.profile.logo_url} alt={selectedTicker} className="w-12 h-12 rounded-lg bg-white object-contain p-1" />
                    ) : (
                        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center text-primary font-bold text-xl">
                            {selectedTicker[0]}
                        </div>
                    )}
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                            {selectedTicker}
                            <span className="text-sm font-normal text-muted-foreground bg-muted px-2 py-0.5 rounded-full">{data?.profile?.exchange || 'BS'}</span>
                        </h1>
                        <p className="text-sm text-muted-foreground">{data?.profile?.name || 'Loading...'}</p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground hidden sm:inline">Switch Ticker:</span>
                    <select
                        className="bg-background border border-border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary w-32 md:w-48"
                        value={selectedTicker}
                        onChange={(e) => setSelectedTicker(e.target.value)}
                    >
                        {availableTickers.sort().map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                </div>
            </div>

            {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-pulse">
                    {[1, 2, 3, 4, 5, 6].map(i => <div key={i} className="h-32 bg-muted/20 rounded-xl"></div>)}
                </div>
            ) : (
                <>
                    {/* Section 2: Key Metrics Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <MetricCard title="Market Cap" value={formatNumber(data?.market?.market_cap)} icon={<Activity className="w-4 h-4" />} />
                        <MetricCard title="Shares Outstanding" value={formatNumber(data?.market?.shares_outstanding).replace('$', '')} icon={<Users className="w-4 h-4" />} />
                        <MetricCard
                            title="Float"
                            value={formatNumber(data?.market?.float_shares).replace('$', '')}
                            subtext={`${formatPercent(data?.market?.held_percent_insiders)} Insiders / ${formatPercent(data?.market?.held_percent_institutions)} Inst.`}
                            icon={<Users className="w-4 h-4" />}
                        />
                    </div>

                    {/* Section 3: Corp Info & Section 4: Description */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                        {/* Corp Info Grid */}
                        <div className="lg:col-span-1 bg-card rounded-xl border border-border p-5 space-y-4">
                            <h3 className="font-semibold flex items-center gap-2 text-card-foreground">
                                <Building2 className="w-4 h-4 text-blue-500" /> Corporate Info
                            </h3>
                            <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-sm">
                                <InfoItem label="Sector" value={data?.profile?.sector} />
                                <InfoItem label="Industry" value={data?.profile?.industry} />
                                <InfoItem label="Employees" value={data?.profile?.employees?.toLocaleString()} />
                                <InfoItem label="Country" value={data?.profile?.country} />
                                <div className="col-span-2">
                                    <span className="text-xs text-muted-foreground block">Website</span>
                                    {data?.profile?.website ? (
                                        <a href={data.profile.website} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline flex items-center gap-1">
                                            {data.profile.website} <ExternalLink className="w-3 h-3" />
                                        </a>
                                    ) : '-'}
                                </div>
                            </div>
                        </div>

                        {/* Description */}
                        <div className="lg:col-span-2 bg-card rounded-xl border border-border p-5">
                            <h3 className="font-semibold mb-3 text-card-foreground">Description</h3>
                            <div className={`relative text-sm text-muted-foreground leading-relaxed ${!showFullDesc ? 'max-h-[140px] overflow-hidden' : ''}`}>
                                {data?.profile?.description || 'No description available.'}
                                {!showFullDesc && data?.profile?.description && (
                                    <div className="absolute bottom-0 left-0 w-full h-12 bg-gradient-to-t from-card to-transparent"></div>
                                )}
                            </div>
                            {data?.profile?.description && (
                                <button
                                    onClick={() => setShowFullDesc(!showFullDesc)}
                                    className="mt-2 text-xs font-medium text-primary hover:underline flex items-center gap-1"
                                >
                                    {showFullDesc ? 'Show Less' : 'Read More'} {showFullDesc ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Section 5: Financials & Performance */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        {/* Financial Stats */}
                        <div className="bg-card rounded-xl border border-border p-5">
                            <h3 className="font-semibold mb-4 text-card-foreground">Financial Statistics</h3>
                            <div className="space-y-3">
                                <StatRow label="Enterprise Value" value={formatNumber(data?.financials?.enterprise_value)} />
                                <StatRow label="Total Cash" value={formatNumber(data?.financials?.cash)} />
                                <StatRow label="Total Debt" value={formatNumber(data?.financials?.total_debt)} />
                                <StatRow label="EBITDA" value={formatNumber(data?.financials?.ebitda)} />
                                <StatRow label="EPS (TTM)" value={data?.financials?.eps?.toFixed(2) || '-'} />
                            </div>
                        </div>

                        {/* Performance Cards */}
                        <div className="bg-card rounded-xl border border-border p-5">
                            <h3 className="font-semibold mb-4 text-card-foreground">Price Performance</h3>
                            <div className="grid grid-cols-3 gap-3">
                                <PerfCard label="1 Week" value={data?.performance?.['1w']} />
                                <PerfCard label="1 Month" value={data?.performance?.['1m']} />
                                <PerfCard label="3 Month" value={data?.performance?.['3m']} />
                                <PerfCard label="6 Month" value={data?.performance?.['6m']} />
                                <PerfCard label="1 Year" value={data?.performance?.['1y']} />
                                <PerfCard label="YTD" value={data?.performance?.['ytd']} />
                            </div>
                        </div>
                    </div>

                    {/* Section 6: Sparklines */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <SparklineCard title="Cash Trend (Quarterly)" value={formatNumber(data?.financials?.cash)} data={data?.charts?.cash_history} color="#22c55e" />
                        <SparklineCard title="Debt Trend (Quarterly)" value={formatNumber(data?.financials?.total_debt)} data={data?.charts?.debt_history} color="#ef4444" />
                        <SparklineCard title="Working Capital" value={formatNumber(data?.financials?.working_capital)} data={data?.charts?.working_capital_history} color="#3b82f6" />
                    </div>

                    {/* Section 7: SEC Filings */}
                    <div className="bg-card rounded-xl border border-border p-5">
                        <h3 className="font-semibold mb-4 text-card-foreground flex items-center gap-2">
                            <FileText className="w-5 h-5 text-orange-500" /> latest SEC Filings
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            <FilingList title="Financials (10-K/Q)" items={filings?.financials} />
                            <FilingList title="News & Events (8-K)" items={filings?.news} />
                            <FilingList title="Offerings (424B/S-1)" items={filings?.prospectuses} />
                            <FilingList title="Ownership (13G/D, 3/4)" items={filings?.ownership} />
                            <FilingList title="Proxies (14A)" items={filings?.proxies} />
                            <FilingList title="Other Forms" items={filings?.others} />
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

// Sub-components
const MetricCard = ({ title, value, subtext, icon }: any) => (
    <div className="bg-card rounded-xl border border-border p-5 shadow-sm">
        <div className="flex justify-between items-start mb-2">
            <span className="text-sm font-medium text-muted-foreground">{title}</span>
            <span className="text-muted-foreground opacity-50">{icon}</span>
        </div>
        <div className="text-2xl font-bold text-card-foreground">{value}</div>
        {subtext && <div className="text-xs text-muted-foreground mt-1">{subtext}</div>}
    </div>
);

const InfoItem = ({ label, value }: any) => (
    <div className="flex flex-col">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-sm font-medium text-foreground truncate" title={value}>{value || '-'}</span>
    </div>
);

const StatRow = ({ label, value }: any) => (
    <div className="flex justify-between items-center py-2 border-b border-border/50 last:border-0">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-sm font-medium text-foreground font-mono">{value}</span>
    </div>
);

const PerfCard = ({ label, value }: any) => {
    if (value === null || value === undefined) return (
        <div className="bg-secondary/50 rounded-lg p-3 flex flex-col items-center justify-center opacity-50">
            <span className="text-xs text-muted-foreground">{label}</span>
            <span className="font-mono text-sm">-</span>
        </div>
    );

    const isPos = value >= 0;
    return (
        <div className={`rounded-lg p-3 flex flex-col items-center justify-center border ${isPos ? 'bg-green-500/10 border-green-500/20 text-green-500' : 'bg-red-500/10 border-red-500/20 text-red-500'}`}>
            <span className="text-xs font-medium opacity-80 mb-1">{label}</span>
            <div className="flex items-center gap-1 font-bold font-mono">
                {isPos ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                {Math.abs(value).toFixed(2)}%
            </div>
        </div>
    );
}

const SparklineCard = ({ title, value, data, color }: any) => (
    <div className="bg-card rounded-xl border border-border p-5 shadow-sm">
        <div className="flex justify-between items-end mb-4">
            <div>
                <div className="text-sm text-muted-foreground mb-1">{title}</div>
                <div className="text-xl font-bold text-foreground">{value}</div>
            </div>
        </div>
        <Sparkline data={data} color={color} />
    </div>
);

const FilingList = ({ title, items }: any) => {
    if (!items || items.length === 0) return null;
    return (
        <div className="bg-muted/10 rounded-lg p-3 border border-border/50 max-h-[250px] overflow-y-auto">
            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3 sticky top-0 bg-background/95 backdrop-blur p-1 rounded">{title}</h4>
            <ul className="space-y-2">
                {items.map((item: any, i: number) => (
                    <li key={i} className="group">
                        <a href={item.link} target="_blank" rel="noopener noreferrer" className="block p-2 rounded hover:bg-secondary/50 transition-colors">
                            <div className="flex justify-between items-start">
                                <span className="font-medium text-blue-500 group-hover:underline text-sm">{item.type}</span>
                                <span className="text-[10px] text-muted-foreground">{item.date}</span>
                            </div>
                            <div className="text-xs text-foreground mt-0.5 line-clamp-1 opacity-80" title={item.title}>
                                {item.title}
                            </div>
                        </a>
                    </li>
                ))}
            </ul>
        </div>
    );
}
