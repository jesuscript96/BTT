"use client";

import React, { useState, useEffect } from "react";
import {
  LayoutDashboard,
  Activity
} from 'lucide-react';
import { AdvancedFilterPanel } from "@/components/AdvancedFilterPanel";
import { Dashboard } from "@/components/Dashboard";
import { DataGrid } from "@/components/DataGrid";
import { FilterBuilder } from "@/components/FilterBuilder";
import { SaveDatasetModal, LoadDatasetModal } from "@/components/DatasetModals";
import TickerAnalysis from "@/components/TickerAnalysis";
import { MarketIntelligenceCharts } from "@/components/MarketIntelligenceCharts";

import { getScreener, getAggregateIntraday, exportData } from "@/lib/api";

// Custom debounce hook
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = React.useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<'screener' | 'ticker'>('screener');
  const [data, setData] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [aggregateSeries, setAggregateSeries] = useState<any[] | null>([]);
  const [isLoading, setIsLoading] = useState(false);
  // Initialize filters with defaults matching the panel UI
  const [currentFilters, setCurrentFilters] = useState<any>({
    min_gap_pct: 20,
    max_gap_pct: 50,
    min_pm_volume: 100000,
    start_date: new Date(new Date().setMonth(new Date().getMonth() - 4)).toISOString().split('T')[0],
    end_date: new Date().toISOString().split('T')[0]
  });
  const [isFilterBuilderOpen, setIsFilterBuilderOpen] = useState(false);
  const [activeRules, setActiveRules] = useState<any[]>([]);
  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
  const [isLoadModalOpen, setIsLoadModalOpen] = useState(false);
  const [filterPanelKey, setFilterPanelKey] = useState(0);
  const [showScanResults, setShowScanResults] = useState(false);

  const handleFilterStateChange = React.useCallback((newFilters: any) => {
    setCurrentFilters(newFilters);
    setData([]);
    setStats(null);
    setAggregateSeries([]);
  }, []);
  const abortControllerRef = React.useRef<AbortController | null>(null);



  const [isAggregateLoading, setIsAggregateLoading] = useState(false);

  const fetchData = async (filters: any = currentFilters, rules: any[] = activeRules) => {
    setIsLoading(true);
    setAggregateSeries([]); // Reset aggregate data on new fetch

    // Build query params from filters
    const queryParams = new URLSearchParams();

    // Basic filters - use full column names to match backend dynamic system
    if (filters.min_gap_pct !== undefined) queryParams.append("min_gap_at_open_pct", filters.min_gap_pct.toString());
    if (filters.max_gap_pct !== undefined) queryParams.append("max_gap_at_open_pct", filters.max_gap_pct.toString());
    if (filters.min_rth_volume !== undefined) queryParams.append("min_rth_volume", filters.min_rth_volume.toString());
    if (filters.min_pm_volume !== undefined) queryParams.append("min_pm_volume", filters.min_pm_volume.toString());

    // Date filters
    if (filters.start_date) queryParams.append("start_date", filters.start_date);
    if (filters.end_date) queryParams.append("end_date", filters.end_date);
    if (filters.ticker) queryParams.append("ticker", filters.ticker);

    // Advanced filters
    if (filters.min_m15_ret_pct !== undefined) queryParams.append("min_m15_return_pct", filters.min_m15_ret_pct.toString());
    if (filters.min_rth_run_pct !== undefined) queryParams.append("min_rth_run_pct", filters.min_rth_run_pct.toString());
    if (filters.min_high_spike_pct !== undefined) queryParams.append("min_high_spike_pct", filters.min_high_spike_pct.toString());
    if (filters.min_low_spike_pct !== undefined) queryParams.append("min_low_spike_pct", filters.min_low_spike_pct.toString());
    if (filters.hod_after) queryParams.append("hod_after", filters.hod_after);
    if (filters.lod_before) queryParams.append("lod_before", filters.lod_before);

    // Convert Advanced Rules to query parameters
    // Map metric names to database columns and parameter names
    // Map metric names to database columns and parameter names
    const metricToParamMap: Record<string, { column: string, paramPrefix: string }> = {
      // Price metrics
      "Open Price": { column: "open", paramPrefix: "open" },
      "Close Price": { column: "close", paramPrefix: "close" },
      "Previous Day Close Price": { column: "prev_close", paramPrefix: "prev_close" },
      "Pre-Market High Price": { column: "pm_high", paramPrefix: "pm_high" },
      "High Spike Price": { column: "rth_high", paramPrefix: "high_spike_price" },
      "Low Spike Price": { column: "rth_low", paramPrefix: "low_spike_price" },
      "M1 Price": { column: "m1_price", paramPrefix: "m1_price" }, // Assuming these exist if not, revert to close
      "M5 Price": { column: "m5_price", paramPrefix: "m5_price" },
      "M15 Price": { column: "m15_price", paramPrefix: "m15_price" },
      "M30 Price": { column: "m30_price", paramPrefix: "m30_price" },
      "M60 Price": { column: "m60_price", paramPrefix: "m60_price" },
      "M90 Price": { column: "m90_price", paramPrefix: "m90_price" },
      "M120 Price": { column: "m120_price", paramPrefix: "m120_price" },
      "M180 Price": { column: "m180_price", paramPrefix: "m180_price" },

      // Volume metrics
      "EOD Volume": { column: "volume", paramPrefix: "volume" },
      "Premarket Volume": { column: "pm_volume", paramPrefix: "pm_volume" },

      // Gap & Run metrics
      "Open Gap %": { column: "gap_pct", paramPrefix: "gap_pct" },
      "RTH Run %": { column: "rth_run_pct", paramPrefix: "rth_run_pct" },
      "PMH Gap %": { column: "pmh_gap_pct", paramPrefix: "pmh_gap_pct" },
      "PMH Fade to Open %": { column: "pmh_fade_pct", paramPrefix: "pmh_fade_pct" },
      "RTH Fade to Close %": { column: "rth_fade_pct", paramPrefix: "rth_fade_pct" },

      // Volatility metrics
      "RTH Range %": { column: "rth_range_pct", paramPrefix: "rth_range_pct" },
      "High Spike %": { column: "rth_run_pct", paramPrefix: "high_spike_pct" }, // Using rth_run_pct as proxy logic
      "Low Spike %": { column: "rth_range_pct", paramPrefix: "low_spike_pct" }, // using rth_range_pct as proxy logic
      "M15 High Spike %": { column: "m15_high_spike_pct", paramPrefix: "m15_high_spike_pct" },
      "M15 Low Spike %": { column: "m15_low_spike_pct", paramPrefix: "m15_low_spike_pct" },

      // Return metrics
      "Day Return %": { column: "day_return_pct", paramPrefix: "day_return_pct" },
      "M15 Return %": { column: "m15_return_pct", paramPrefix: "m15_return_pct" },
      "M30 Return %": { column: "m30_return_pct", paramPrefix: "m30_return_pct" },
      "M60 Return %": { column: "m60_return_pct", paramPrefix: "m60_return_pct" },
      "Return at Close %": { column: "return_close_pct", paramPrefix: "return_close_pct" },
    };

    // Process Advanced Rules
    for (const rule of rules) {
      const mapping = metricToParamMap[rule.metric];
      if (!mapping) continue; // Skip unmapped metrics

      const { column, paramPrefix } = mapping;
      const value = rule.value;

      // Convert operator to parameter name
      // For simplicity, we'll use min_/max_ prefixes based on operator
      if (rule.operator === ">" || rule.operator === ">=") {
        queryParams.append(`min_${column}`, value);
      } else if (rule.operator === "<" || rule.operator === "<=") {
        queryParams.append(`max_${column}`, value);
      } else if (rule.operator === "=") {
        queryParams.append(`exact_${column}`, value);
      }
    }

    // Always add limit (User requested more results, default was 100)
    queryParams.append("limit", "5000");

    // Cancel any previous pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      // 1. FAST FETCH: Get Screener Data (Grid/Sidebar) - Critical Path
      const result = await getScreener(queryParams, controller.signal) as any;

      if (Array.isArray(result)) {
        setData(result);
        setStats(null);
      } else {
        setData(result.records || []);
        setStats(result.stats || null);
      }
      setIsLoading(false);
      setShowScanResults(true); // Auto-expand when results are fetched
      setAggregateSeries(null); // null = loading, prevents individual ticker mode

      // 2. SLOW FETCH: Get Aggregate Intraday (Chart) - Background Path
      setIsAggregateLoading(true);
      getAggregateIntraday(queryParams, controller.signal)
        .then(aggregateResult => {
          setAggregateSeries(Array.isArray(aggregateResult) && aggregateResult.length > 0 ? aggregateResult : []);
        })
        .catch(err => {
          if (err.name !== 'AbortError') console.error("Error fetching aggregate data:", err);
        })
        .finally(() => {
          setIsAggregateLoading(false);
        });

    } catch (error: any) {
      if (error.name === 'AbortError') return;
      console.error("Error fetching data:", error);
      setIsLoading(false);
    }
  };


  const handleExport = async () => {
    try {
      const blob = await exportData({ ...currentFilters, rules: activeRules });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `export_${new Date().toISOString()}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (error) {
      console.error("Export failed:", error);
      alert("Export failed");
    }
  };

  const handleLoadDataset = (filters: any) => {
    const { rules, ...basicFilters } = filters;
    setCurrentFilters(basicFilters);
    setActiveRules(rules || []);
    setFilterPanelKey(prev => prev + 1); // Reset panel with new values
  };

  // Fetch when rules change, skipping initial mount
  const isFirstMount = React.useRef(true);
  useEffect(() => {
    if (isFirstMount.current) {
      isFirstMount.current = false;
      return;
    }
    fetchData(currentFilters, activeRules);
  }, [activeRules]);

  const memoizedData = React.useMemo(() => data, [data]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', 
                  height: '100vh', overflow: 'hidden',
                  backgroundColor: 'var(--color-ec-bg-base)' }}>
      
      {/* Tab Navigation */}
      <div style={{
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        borderBottom: '0.5px solid var(--color-ec-border)',
        padding: '0 20px',
        display: 'flex',
        alignItems: 'flex-end',
        gap: 0,
        minHeight: '38px'
      }}>
        <button
          onClick={() => setActiveTab('screener')}
          style={{
            color: activeTab === 'screener' ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)',
            borderBottom: activeTab === 'screener' ? '2px solid var(--color-ec-copper)' : '2px solid transparent',
            padding: '0 14px',
            height: 38,
            fontFamily: "'General Sans', sans-serif",
            fontSize: 12,
            fontWeight: 600,
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            whiteSpace: 'nowrap',
          }}
        >
          <LayoutDashboard size={14} strokeWidth={1.5} />
          Market & Summary
        </button>
        <button
          onClick={() => setActiveTab('ticker')}
          style={{
            color: activeTab === 'ticker' ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)',
            borderBottom: activeTab === 'ticker' ? '2px solid var(--color-ec-copper)' : '2px solid transparent',
            padding: '0 14px',
            height: 38,
            fontFamily: "'General Sans', sans-serif",
            fontSize: 12,
            fontWeight: 600,
            background: 'transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            whiteSpace: 'nowrap',
          }}
        >
          <Activity size={14} strokeWidth={1.5} />
          Ticker Analysis
        </button>
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        overflowX: 'hidden',
        backgroundColor: 'var(--color-ec-bg-base)'
      }}>

        {activeTab === 'screener' && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            padding: '20px',
            height: 'calc(100vh - 38px)',
            backgroundColor: 'var(--color-ec-bg-base)',
            overflow: 'hidden'
          }}>
            <AdvancedFilterPanel
              key={filterPanelKey}
              filters={currentFilters}
              onFilterStateChange={handleFilterStateChange}
              onFilter={(newFilters) => fetchData(newFilters, activeRules)}
              onExport={handleExport}
              onSaveDataset={() => setIsSaveModalOpen(true)}
              onLoadDataset={() => setIsLoadModalOpen(true)}
              isLoading={isLoading}
              onToggleFilterBuilder={() => setIsFilterBuilderOpen(!isFilterBuilderOpen)}
              activeRules={activeRules}
              onRemoveRule={(id) => setActiveRules(prev => prev.filter(r => r.id !== id))}
              showScanResults={showScanResults}
              onToggleScanResults={() => setShowScanResults(prev => !prev)}
            />

            <FilterBuilder
              isOpen={isFilterBuilderOpen}
              onClose={() => setIsFilterBuilderOpen(false)}
              onSave={(newRules) => {
                setActiveRules(prev => [...prev, ...newRules]);
                setIsFilterBuilderOpen(false);
              }}
            />

            <SaveDatasetModal
              isOpen={isSaveModalOpen}
              onClose={() => setIsSaveModalOpen(false)}
              filters={currentFilters}
              rules={activeRules}
            />

            <LoadDatasetModal
              isOpen={isLoadModalOpen}
              onClose={() => setIsLoadModalOpen(false)}
              onLoad={handleLoadDataset}
            />

            {/* Container for sliding panels */}
            <div style={{
              position: 'relative',
              flex: 1,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}>
              
              {/* Background Panel: Market Intelligence */}
              <div style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                gap: '16px',
                overflowY: 'auto',
                paddingBottom: '20px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '0.5px solid var(--color-ec-border)', paddingBottom: '16px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <h1 style={{
                      fontFamily: "'Fraunces', serif",
                      fontSize: 32,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-high)',
                      letterSpacing: '-0.5px',
                      marginBottom: 4,
                    }}>MARKET INTELLIGENCE</h1>
                    <span style={{
                      fontFamily: "'General Sans', sans-serif",
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: 2,
                      color: 'var(--color-ec-text-muted)',
                    }}>
                      REAL-TIME STATISTICAL DISTRIBUTIONS AND GAP COHORT ANALYSIS
                    </span>
                  </div>
                </div>
                <div style={{ flex: 1 }}>
                  <MarketIntelligenceCharts />
                </div>
              </div>

              {/* Foreground Sliding Panel: Scan Results */}
              <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                backgroundColor: 'var(--color-ec-bg-base)',
                transform: showScanResults ? 'translateY(0)' : 'translateY(-110%)',
                opacity: showScanResults ? 1 : 0,
                transition: 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease-in-out',
                zIndex: 20,
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: '32px',
                padding: '24px',
                boxSizing: 'border-box',
              }}>
                {/* Dashboard & DataGrid Stack */}
                <Dashboard stats={stats} data={data} aggregateSeries={aggregateSeries} isLoadingAggregate={isAggregateLoading} />

                <div style={{
                  flex: 1,
                  minHeight: 500,
                  background: 'var(--color-ec-bg-surface)',
                  borderRadius: 8,
                  border: '1px solid var(--color-ec-border)',
                  overflow: 'hidden',
                  boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)',
                }}>
                  <DataGrid
                    data={memoizedData}
                    isLoading={isLoading}
                  />
                </div>
              </div>

            </div>
          </div>
        )}

        {activeTab === 'ticker' && (
          <TickerAnalysis
            ticker={currentFilters.ticker || (data.length > 0 ? data[0].ticker : undefined)}
            availableTickers={Array.from(new Set(data.map(d => d.ticker)))}
          />
        )}
      </div>
    </div>
  );
}

// Icons for Home
const XIcon = ({ className }: { className?: string }) => <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>;
