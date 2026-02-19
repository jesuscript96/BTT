"use client";

import React, { useState, useEffect } from "react";
import {
  LayoutDashboard,
  LineChart,
  ScatterChart,
  Activity
} from 'lucide-react';
import { AdvancedFilterPanel } from "@/components/AdvancedFilterPanel";
import { Dashboard } from "@/components/Dashboard";
import { DataGrid } from "@/components/DataGrid";
import { FilterBuilder } from "@/components/FilterBuilder";
import { SaveDatasetModal, LoadDatasetModal } from "@/components/DatasetModals";
import RollingAnalysisDashboard from "@/components/RollingAnalysisDashboard";
import RegressionAnalysis from "@/components/RegressionAnalysis";
import TickerAnalysis from "@/components/TickerAnalysis";

import { API_URL } from "@/config/constants";

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
  const [activeTab, setActiveTab] = useState<'screener' | 'rolling' | 'regression' | 'ticker'>('screener');
  const [data, setData] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [aggregateSeries, setAggregateSeries] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // Initialize filters with defaults matching the panel UI
  const [currentFilters, setCurrentFilters] = useState<any>({
    min_gap_pct: 30,
    max_gap_pct: 50,
    min_pm_volume: 5000000,
    start_date: new Date(new Date().setMonth(new Date().getMonth() - 4)).toISOString().split('T')[0],
    end_date: new Date().toISOString().split('T')[0]
  });
  const [isFilterBuilderOpen, setIsFilterBuilderOpen] = useState(false);
  const [activeRules, setActiveRules] = useState<any[]>([]);
  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
  const [isLoadModalOpen, setIsLoadModalOpen] = useState(false);
  const [filterPanelKey, setFilterPanelKey] = useState(0);

  // Debounce filter updates to prevent excessive re-renders/fetches
  const debouncedFilters = useDebounce(currentFilters, 400);
  const abortControllerRef = React.useRef<AbortController | null>(null);



  const fetchData = async (filters: any = currentFilters, rules: any[] = activeRules) => {
    setIsLoading(true);

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
      const [result, aggregateResult] = await Promise.all([
        fetch(`${API_URL}/market/screener?${queryParams.toString()}`, { signal: controller.signal }).then(r => r.json()),
        fetch(`${API_URL}/market/aggregate/intraday?${queryParams.toString()}`, { signal: controller.signal }).then(r => r.json())
      ]);

      if (Array.isArray(result)) {
        setData(result);
        setStats(null);
      } else {
        setData(result.records || []);
        setStats(result.stats || null);
      }

      setAggregateSeries(Array.isArray(aggregateResult) ? aggregateResult : []);
    } catch (error: any) {
      if (error.name === 'AbortError') return;
      console.error("Error fetching data:", error);
    } finally {
      setIsLoading(false);
    }
  };


  const handleExport = async () => {
    try {
      const res = await fetch(`${API_URL}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...currentFilters, rules: activeRules }),
      });

      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `export_${new Date().toISOString()}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
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

  // Fetch when rules change
  useEffect(() => {
    if (activeRules.length > 0) {
      fetchData(currentFilters, activeRules);
    }
  }, [activeRules]);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <AdvancedFilterPanel
        key={filterPanelKey}
        filters={currentFilters}
        onFilterStateChange={setCurrentFilters}
        onFilter={(newFilters) => fetchData(newFilters, activeRules)}
        onExport={handleExport}
        onSaveDataset={() => setIsSaveModalOpen(true)}
        onLoadDataset={() => setIsLoadModalOpen(true)}
        isLoading={isLoading}
      />

      {/* Active Filters Bar */}
      <div className="bg-muted/50 px-6 py-2 border-b border-border flex items-center gap-4 shadow-sm z-10 transition-colors">
        <button
          onClick={() => setIsFilterBuilderOpen(!isFilterBuilderOpen)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-black uppercase tracking-tighter transition-all shadow-md active:scale-95 shrink-0"
        >
          <div className="w-1.5 h-1.5 rounded-full bg-white" />
          FILTROS
        </button>

        <div className="flex-1 flex items-center gap-2 overflow-x-auto no-scrollbar border-l border-border pl-4">
          <span className="text-[10px] font-black text-muted-foreground uppercase tracking-widest mr-2 whitespace-nowrap">Advanced Rules:</span>
          {activeRules.map(rule => (
            <div key={rule.id} className="bg-card border border-border px-3 py-1 rounded-full flex items-center gap-2 group hover:border-blue-400 transition-all cursor-default shadow-sm shrink-0">
              <span className="text-[10px] font-bold text-foreground/80">{rule.metric} {rule.operator} {rule.value}</span>
              <button
                onClick={() => setActiveRules(prev => prev.filter(r => r.id !== rule.id))}
                className="opacity-40 group-hover:opacity-100 hover:text-red-500 transition-opacity"
              >
                <XIcon className="h-3 w-3" />
              </button>
            </div>
          ))}
          {activeRules.length === 0 && <span className="text-[10px] italic text-muted-foreground/60">No active advanced rules</span>}
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="px-6 pt-4 border-b border-border flex gap-6 overflow-x-auto">
        <button
          onClick={() => setActiveTab('screener')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 whitespace-nowrap ${activeTab === 'screener'
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
        >
          <LayoutDashboard className="w-4 h-4" />
          Screener & Summary
        </button>
        <button
          onClick={() => setActiveTab('rolling')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 whitespace-nowrap ${activeTab === 'rolling'
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
        >
          <LineChart className="w-4 h-4" />
          Rolling Analysis
        </button>
        <button
          onClick={() => setActiveTab('regression')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 whitespace-nowrap ${activeTab === 'regression'
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
        >
          <ScatterChart className="w-4 h-4" />
          Regression Analysis
        </button>
        <button
          onClick={() => setActiveTab('ticker')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 whitespace-nowrap ${activeTab === 'ticker'
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
        >
          <Activity className="w-4 h-4" />
          Ticker Analysis
        </button>
      </div>

      <div className="flex-1 overflow-auto bg-background scrollbar-thin scrollbar-track-muted/50 scrollbar-thumb-muted relative transition-colors duration-300">

        {activeTab === 'screener' && (
          <div className="flex flex-col gap-6 p-6 min-h-screen">
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

            {/* Dashboard & DataGrid Stack */}
            <Dashboard stats={stats} data={data} aggregateSeries={aggregateSeries} />

            <div className="flex-1 min-h-[500px] bg-card rounded-xl border border-border shadow-sm overflow-hidden">
              <DataGrid
                data={data}
                isLoading={isLoading}
              />
            </div>
          </div>
        )}

        {activeTab === 'rolling' && (
          <div className="p-6 h-full">
            {currentFilters.ticker ? (
              <RollingAnalysisDashboard
                ticker={currentFilters.ticker}
                startDate={currentFilters.start_date}
                endDate={currentFilters.end_date}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-muted-foreground border border-dashed border-border rounded-xl">
                <p>Please select a Ticker in the Filter Panel to view Rolling Analysis.</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'regression' && (
          <div className="p-6 h-full">
            <RegressionAnalysis data={data} />
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
