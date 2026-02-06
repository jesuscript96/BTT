"use client";

import React, { useState, useEffect } from "react";
import { AdvancedFilterPanel } from "@/components/AdvancedFilterPanel";
import { Dashboard } from "@/components/Dashboard";
import { DataGrid } from "@/components/DataGrid";
import { FilterBuilder } from "@/components/FilterBuilder";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export default function Home() {
  const [data, setData] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [aggregateSeries, setAggregateSeries] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [currentFilters, setCurrentFilters] = useState<any>({});
  const [isFilterBuilderOpen, setIsFilterBuilderOpen] = useState(false);
  const [activeRules, setActiveRules] = useState<any[]>([]);

  const fetchData = async (filters: any = currentFilters, rules: any[] = activeRules) => {
    setIsLoading(true);
    setCurrentFilters(filters);
    try {
      const res = await fetch(`${API_URL}/filter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...filters, rules }),
      });
      if (res.ok) {
        const result = await res.json();
        setData(result.records || []);
        setStats(result.stats || null);
        setAggregateSeries(result.aggregate_series || []);
      }
    } catch (error) {
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

  // Initial load
  useEffect(() => {
    fetchData();
  }, [activeRules]);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <AdvancedFilterPanel
        onFilter={(newFilters) => fetchData(newFilters, activeRules)}
        onExport={handleExport}
        isLoading={isLoading}
      />

      {/* Active Filters Bar */}
      <div className="bg-[#F2F0ED] px-6 py-2 border-b border-zinc-200 flex items-center gap-4 shadow-sm z-10 transition-colors">
        <button
          onClick={() => setIsFilterBuilderOpen(!isFilterBuilderOpen)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-black uppercase tracking-tighter transition-all shadow-md active:scale-95"
        >
          <div className="w-1.5 h-1.5 rounded-full bg-white" />
          FILTROS
        </button>

        <div className="flex-1 flex items-center gap-2 overflow-x-auto no-scrollbar border-l border-zinc-300 pl-4">
          <span className="text-[10px] font-black text-zinc-400 uppercase tracking-widest mr-2 whitespace-nowrap">Advanced Rules:</span>
          {activeRules.map(rule => (
            <div key={rule.id} className="bg-white border border-zinc-200 px-3 py-1 rounded-full flex items-center gap-2 group hover:border-blue-400 transition-all cursor-default shadow-sm shrink-0">
              <span className="text-[10px] font-bold text-zinc-700">{rule.metric} {rule.operator} {rule.value}</span>
              <button
                onClick={() => setActiveRules(prev => prev.filter(r => r.id !== rule.id))}
                className="opacity-40 group-hover:opacity-100 hover:text-red-500 transition-opacity"
              >
                <XIcon className="h-3 w-3" />
              </button>
            </div>
          ))}
          {activeRules.length === 0 && <span className="text-[10px] italic text-zinc-400">No active advanced rules</span>}
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-[#F9F9F8] scrollbar-thin scrollbar-track-zinc-100 scrollbar-thumb-zinc-300 relative">
        <FilterBuilder
          isOpen={isFilterBuilderOpen}
          onClose={() => setIsFilterBuilderOpen(false)}
          onSave={(newRules) => {
            setActiveRules(prev => [...prev, ...newRules]);
            setIsFilterBuilderOpen(false);
          }}
        />
        <Dashboard stats={stats} data={data} aggregateSeries={aggregateSeries} />
        <div className="px-6 pb-20">
          <div className="border border-zinc-200 rounded-xl overflow-hidden shadow-sm bg-white">
            <DataGrid data={data} isLoading={isLoading} />
          </div>
        </div>
      </div>
    </div>
  );
}

// Icons for Home
const XIcon = ({ className }: { className?: string }) => <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>;
