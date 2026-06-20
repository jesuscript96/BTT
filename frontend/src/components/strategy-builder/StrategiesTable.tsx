"use client";

import React, { useEffect, useState } from 'react';
import { Strategy, IndicatorConfig, AnyCondition, ConditionGroup, PostGapPrecondition, UniverseFilters, RiskManagement, IndicatorType } from '@/types/strategy';
import { Loader2, Trash2, ChevronDown, ChevronUp, Play, Filter, Tag, Shield } from 'lucide-react';
import { getStrategies, deleteStrategy } from '@/lib/api';
import { COMPARATOR_LABELS, INDICATOR_LABELS } from './ConditionBuilder';

interface Props {
    refreshTrigger?: number;
}

export const StrategiesTable = ({ refreshTrigger }: Props) => {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expandedId, setExpandedId] = useState<string | null>(null);

    const fetchStrategies = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await getStrategies();
            setStrategies(data);
        } catch (err) {
            const message = err instanceof Error ? err.message : "Unknown error";
            setError(message);
            setStrategies([]);
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (id: string, e: React.MouseEvent) => {
        e.stopPropagation(); // Avoid triggering row expansion/collapse
        if (!confirm('Are you sure you want to delete this strategy?')) return;

        try {
            await deleteStrategy(id);
            if (expandedId === id) setExpandedId(null);
            fetchStrategies(); // Refresh list
        } catch (err) {
            alert('Error deleting strategy');
        }
    };

    const toggleExpand = (id: string) => {
        setExpandedId(prev => prev === id ? null : id);
    };

    useEffect(() => {
        fetchStrategies();
    }, [refreshTrigger]);

    // Formatter helpers
    const formatIndicator = (ind: IndicatorConfig): string => {
        if (!ind) return "";
        const params: string[] = [];
        if (ind.period != null && ind.period as any !== "") params.push(`P:${ind.period}`);
        if (ind.period2 != null && ind.period2 as any !== "") params.push(`P2:${ind.period2}`);
        if (ind.stdDev != null && ind.stdDev as any !== "") params.push(`SD:${ind.stdDev}`);
        if (ind.days_lookback != null && ind.days_lookback as any !== "") params.push(`Lookback:${ind.days_lookback}d`);
        if (ind.orb_minutes != null && ind.orb_minutes as any !== "") params.push(`ORB:${ind.orb_minutes}m`);
        if (ind.ap_session != null && typeof ind.ap_session === 'string') {
            params.push(`${ind.ap_session.replace("ap.", "")}`);
        }
        if (ind.elapsed_minutes != null && ind.elapsed_minutes as any !== "") params.push(`Elapsed:${ind.elapsed_minutes}m`);
        if (ind.band_line != null && ind.band_line as any !== "") params.push(`${ind.band_line}`);
        
        let offsetStr = "";
        if (ind.offset != null && ind.offset > 0) {
            offsetStr = `[t-${ind.offset}]`;
        }
        
        const paramsStr = params.length > 0 ? `(${params.join(",")})` : "";
        const nameStr = ind.name ? (INDICATOR_LABELS[ind.name] || ind.name) : "Variable";
        return `${nameStr}${paramsStr}${offsetStr}`;
    };

    const formatCondition = (cond: AnyCondition): string => {
        if (!cond) return "";
        if (cond.type === 'indicator_comparison') {
            const sourceStr = formatIndicator(cond.source);
            const compStr = COMPARATOR_LABELS[cond.comparator] || cond.comparator || "=";
            const targetStr = typeof cond.target === 'number' 
                ? (cond.source.name === IndicatorType.PM_HIGH_GAP ? `${cond.target}%` : cond.target.toString()) 
                : formatIndicator(cond.target);
            const tfStr = cond.timeframe ? `[${cond.timeframe}] ` : "";
            return `${tfStr}${sourceStr} ${compStr} ${targetStr}`;
        } else if (cond.type === 'price_level_distance') {
            const sourceStr = formatIndicator(cond.source);
            const compStr = cond.comparator === 'DISTANCE_GT' ? ">" : "<";
            const levelStr = formatIndicator(cond.level);
            const posStr = cond.position && cond.position !== 'any' ? ` (${cond.position})` : "";
            const tfStr = cond.timeframe ? `[${cond.timeframe}] ` : "";
            return `${tfStr}${sourceStr} dist ${compStr} ${cond.value_pct}% to ${levelStr}${posStr}`;
        }
        return "";
    };

    const formatPrecondition = (pre: PostGapPrecondition): string => {
        if (!pre) return "";
        const dayStr = pre.day === 'gap_day' ? 'Gap Day' : 'Gap+1 Day';
        const metricLabels: Record<string, string> = {
            volume: 'Volume',
            close_vs_open: 'Close vs Open',
            close_vs_high_low: 'Close vs High/Low',
            close_vs_high: 'Close vs High',
            close_vs_low: 'Close vs Low',
            close_vs_pm_high: 'Close vs PM High',
            close_vs_pm_low: 'Close vs PM Low',
            close_vs_vwap: 'Close vs VWAP',
            close_vs_sma: `Close vs SMA(${pre.sma_period || 20})`,
            candle_range_pct: 'Candle Range %',
            candle_range_ratio_gap_1_vs_gap: pre.day === 'gap_1_day' ? 'Candle Range Gap+1 vs Gap' : 'Candle Range vs Prev'
        };
        const metricStr = metricLabels[pre.metric] || pre.metric;
        let valueStr = '';
        if (pre.value != null && (pre.value as any) !== "") {
            if (pre.metric === 'volume') {
                valueStr = pre.value >= 1000000 ? ` ${pre.value / 1000000}M` : ` ${pre.value.toLocaleString()}`;
            } else if (pre.metric === 'candle_range_pct' || pre.metric === 'candle_range_ratio_gap_1_vs_gap') {
                valueStr = ` ${pre.value}%`;
            } else {
                valueStr = ` ${pre.value}`;
            }
        }
        return `${dayStr}: ${metricStr} ${pre.operator}${valueStr}`;
    };

    const getUniverseTags = (filters?: UniverseFilters): string[] => {
        if (!filters) return [];
        const tags: string[] = [];
        if (filters.min_market_cap != null && (filters.min_market_cap as any) !== "") tags.push(`Min Cap: $${(filters.min_market_cap / 1e6).toFixed(1)}M`);
        if (filters.max_market_cap != null && (filters.max_market_cap as any) !== "") tags.push(`Max Cap: $${(filters.max_market_cap / 1e6).toFixed(1)}M`);
        if (filters.min_price != null && (filters.min_price as any) !== "") tags.push(`Min Price: $${filters.min_price}`);
        if (filters.max_price != null && (filters.max_price as any) !== "") tags.push(`Max Price: $${filters.max_price}`);
        if (filters.min_volume != null && (filters.min_volume as any) !== "") tags.push(`Min Vol: ${(filters.min_volume / 1e3).toFixed(0)}k`);
        if (filters.max_shares_float != null && (filters.max_shares_float as any) !== "") tags.push(`Max Float: ${(filters.max_shares_float / 1e6).toFixed(1)}M`);
        if (filters.require_shortable === true) tags.push("Require Shortable");
        if (filters.exclude_dilution === true) tags.push("Exclude Dilution");
        if (filters.whitelist_sectors && filters.whitelist_sectors.length > 0) {
            tags.push(`Sectors: ${filters.whitelist_sectors.join(', ')}`);
        }
        return tags;
    };

    const getRiskTags = (risk?: RiskManagement): string[] => {
        if (!risk) return [];
        const tags: string[] = [];
        if (risk.use_hard_stop && risk.hard_stop && risk.hard_stop.value != null && (risk.hard_stop.value as any) !== "") {
            tags.push(`Stop Loss: ${risk.hard_stop.value}%`);
        }
        if (risk.use_take_profit && risk.take_profit && risk.take_profit.value != null && (risk.take_profit.value as any) !== "") {
            tags.push(`Take Profit: ${risk.take_profit.value}%`);
        }
        if (risk.take_profit_mode && (risk.use_take_profit || (risk.partial_take_profits && risk.partial_take_profits.length > 0))) {
            tags.push(`TP Mode: ${risk.take_profit_mode}`);
        }
        if (risk.partial_take_profits && risk.partial_take_profits.length > 0) {
            risk.partial_take_profits.forEach((pt, i) => {
                if (pt && pt.capital_pct != null && pt.distance_pct != null) {
                    tags.push(`Partial TP ${i+1}: ${pt.capital_pct}% cap @ ${pt.distance_pct === 'EOD' ? 'EOD' : pt.distance_pct + '% dist'}`);
                }
            });
        }
        if (risk.trailing_stop?.active && risk.trailing_stop.buffer_pct != null && (risk.trailing_stop.buffer_pct as any) !== "") {
            tags.push(`Trailing: ${risk.trailing_stop.buffer_pct}%`);
        }
        if (risk.accept_reentries === true) {
            if (risk.max_reentries === undefined || risk.max_reentries === -1) {
                tags.push("Reentradas: Infinitas");
            } else {
                tags.push(`Reentradas: Máx ${risk.max_reentries}`);
            }
        }
        if (risk.max_drawdown_daily != null && (risk.max_drawdown_daily as any) !== "") {
            tags.push(`Max Daily DD: ${risk.max_drawdown_daily}%`);
        }
        return tags;
    };

    const getConditionTags = (group?: ConditionGroup): string[] => {
        if (!group) return [];
        
        const parseGroup = (g: ConditionGroup, pathOperator: string = ""): string[] => {
            let results: string[] = [];
            const op = g.operator || "AND";
            
            if (g.conditions) {
                g.conditions.forEach(c => {
                    if (c.type === 'group') {
                        results = results.concat(parseGroup(c, op));
                    } else {
                        const formatted = formatCondition(c);
                        if (formatted) {
                            results.push(`${op}: ${formatted}`);
                        }
                    }
                });
            }
            return results;
        };
        
        return parseGroup(group);
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-ec-text-secondary" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="bg-ec-loss/10 border-ec-loss/20 rounded-xl p-4 text-ec-loss text-sm font-bold">
                Error loading strategies: {error}
            </div>
        );
    }

    if (strategies.length === 0) {
        return (
            <div className="bg-muted/30 border border-border rounded-xl p-8 text-center transition-all">
                <p className="text-muted-foreground/60 text-[10px] font-black uppercase tracking-widest">No strategies created yet. Create your first one above!</p>
            </div>
        );
    }

    return (
        <div className="bg-transparent border-t border-border/40 overflow-hidden transition-all">
            <div className="px-6 py-5 border-b border-border/50">
                <h3 className="text-[10px] font-black text-foreground uppercase tracking-widest">Saved Strategies</h3>
                <p className="text-[10px] text-muted-foreground/50 font-black uppercase tracking-widest mt-1.5">{strategies.length} strateg{strategies.length === 1 ? 'y' : 'ies'} found</p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead className="bg-muted/30 border-b border-border/50">
                        <tr>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Name</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Description</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Timeframe</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Created</th>
                            <th className="px-6 py-3 text-right text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                        {strategies.map((strategy) => {
                            const isExpanded = expandedId === strategy.id;
                            return (
                                <React.Fragment key={strategy.id}>
                                    <tr 
                                        onClick={() => strategy.id && toggleExpand(strategy.id)}
                                        className="hover:bg-muted/20 transition-colors group cursor-pointer"
                                    >
                                        <td className="px-6 py-4">
                                            <div className="flex items-center gap-2">
                                                {isExpanded ? (
                                                    <ChevronUp className="w-4 h-4 text-ec-text-secondary" />
                                                ) : (
                                                    <ChevronDown className="w-4 h-4 text-ec-text-secondary" />
                                                )}
                                                <div className="text-sm font-bold text-foreground">{strategy.name}</div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="text-sm text-muted-foreground font-medium max-w-md truncate opacity-80">
                                                {strategy.description || <span className="text-muted-foreground/30 italic">No description</span>}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">
                                                {strategy.entry_logic?.timeframe || 'N/A'}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">
                                                {strategy.created_at ? new Date(strategy.created_at).toLocaleDateString() : 'N/A'}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 text-right">
                                            <button
                                                onClick={(e) => strategy.id && handleDelete(strategy.id, e)}
                                                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black text-ec-loss/60 hover:text-ec-loss hover:bg-ec-loss/10 rounded-lg transition-all opacity-0 group-hover:opacity-100"
                                            >
                                                <Trash2 className="w-3 h-3" />
                                                Delete
                                            </button>
                                        </td>
                                    </tr>
                                    {isExpanded && strategy.id && (
                                        <tr className="bg-muted/10 border-b border-border/20">
                                            <td colSpan={5} className="px-6 py-4">
                                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
                                                    {/* 1. Timing & Preconditions */}
                                                    <div className="bg-muted/5 border border-border/10 rounded-xl p-3">
                                                        <div className="flex items-center gap-1.5 mb-2 font-black uppercase tracking-wider text-[10px] text-muted-foreground">
                                                            <Play className="w-3.5 h-3.5 text-ec-text-secondary" />
                                                            <span>Bias & Preconditions</span>
                                                        </div>
                                                        <div className="flex flex-wrap gap-1.5">
                                                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                                                                strategy.bias === 'long' 
                                                                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
                                                                    : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                                            }`}>
                                                                Bias: {strategy.bias}
                                                            </span>
                                                            {strategy.apply_day && (
                                                                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase tracking-wider">
                                                                    Apply: {strategy.apply_day}
                                                                </span>
                                                            )}
                                                            {strategy.postgap_preconditions?.map((pre, idx) => (
                                                                <span key={idx} className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                                                    {formatPrecondition(pre)}
                                                                </span>
                                                            ))}
                                                            {(!strategy.postgap_preconditions || strategy.postgap_preconditions.length === 0) && !strategy.apply_day && (
                                                                <span className="text-[10px] text-muted-foreground/40 italic">No preconditions</span>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* 2. Universe Filters */}
                                                    <div className="bg-muted/5 border border-border/10 rounded-xl p-3">
                                                        <div className="flex items-center gap-1.5 mb-2 font-black uppercase tracking-wider text-[10px] text-muted-foreground">
                                                            <Filter className="w-3.5 h-3.5 text-ec-text-secondary" />
                                                            <span>Universe Filters</span>
                                                        </div>
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {getUniverseTags(strategy.universe_filters).map((tag, idx) => (
                                                                    <span key={idx} className="px-2 py-0.5 rounded text-[10px] font-bold bg-violet-500/10 text-violet-400 border border-violet-500/20">
                                                                        {tag}
                                                                    </span>
                                                            ))}
                                                            {getUniverseTags(strategy.universe_filters).length === 0 && (
                                                                <span className="text-[10px] text-muted-foreground/40 italic">No universe filters</span>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* 3. Entry Logic */}
                                                    <div className="bg-muted/5 border border-border/10 rounded-xl p-3">
                                                        <div className="flex items-center gap-1.5 mb-2 font-black uppercase tracking-wider text-[10px] text-muted-foreground">
                                                            <Tag className="w-3.5 h-3.5 text-emerald-400" />
                                                            <span>Entry Conditions</span>
                                                        </div>
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {getConditionTags(strategy.entry_logic?.root_condition).map((tag, idx) => (
                                                                <span key={idx} className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                                                    {tag}
                                                                </span>
                                                            ))}
                                                            {getConditionTags(strategy.entry_logic?.root_condition).length === 0 && (
                                                                <span className="text-[10px] text-muted-foreground/40 italic">No entry conditions</span>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* 4. Exit Logic & Risk */}
                                                    <div className="bg-muted/5 border border-border/10 rounded-xl p-3">
                                                        <div className="flex items-center gap-1.5 mb-2 font-black uppercase tracking-wider text-[10px] text-muted-foreground">
                                                            <Shield className="w-3.5 h-3.5 text-rose-400" />
                                                            <span>Exit & Risk</span>
                                                        </div>
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {/* Exit Conditions */}
                                                            {getConditionTags(strategy.exit_logic?.root_condition).map((tag, idx) => (
                                                                <span key={idx} className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                                                    Exit {tag}
                                                                </span>
                                                            ))}
                                                            {/* Risk Tags */}
                                                            {getRiskTags(strategy.risk_management).map((tag, idx) => (
                                                                <span key={idx} className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                                                                    {tag}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </td>
                                        </tr>
                                    )}
                                </React.Fragment>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
