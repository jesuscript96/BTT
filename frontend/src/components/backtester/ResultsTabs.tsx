"use client";

import { useState } from "react";
import type { BacktestResult, DayCandles, TradeRecord, EquityPoint } from "@/lib/api_backtester";
import PerformanceTab from "@/components/backtester/tabs/PerformanceTab";
import CalendarTab from "@/components/backtester/tabs/CalendarTab";
import TradesTab from "@/components/backtester/tabs/TradesTab";
import ChartsTab from "@/components/backtester/tabs/ChartsTab";
import OptimizationSurfaceTab from "@/components/backtester/tabs/OptimizationSurfaceTab";
import Chart from "@/components/backtester/Chart";

const TABS = [
  { id: "performance", label: "Performance" },
  { id: "calendar", label: "Calendar" },
  { id: "trades", label: "Trades" },
  { id: "analysis", label: "Análisis por trade" },
  { id: "charts", label: "Charts" },
  { id: "optimization", label: "Op. Surface" },
] as const;

type TabId = (typeof TABS)[number]["id"];

interface ResultsTabsProps {
  result: BacktestResult;
  initCash: number;
  riskR: number;
  dayCandles: DayCandles | null;
  candlesLoading: boolean;
  currentTrades: TradeRecord[];
  currentEquity: EquityPoint[];
  isDarkMode?: boolean;
  strategyId?: string;
  datasetId?: string;
  backtestParams?: Record<string, unknown>;
}

export default function ResultsTabs({
  result,
  initCash,
  riskR,
  dayCandles,
  candlesLoading,
  currentTrades,
  currentEquity,
  isDarkMode = false,
  strategyId = "",
  datasetId = "",
  backtestParams = {},
}: ResultsTabsProps) {
  const [activeTab, setActiveTab] = useState<TabId>("performance");

  return (
    <div className="transition-colors">
      <div style={{
        borderBottom: '0.5px solid var(--color-ec-border)',
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}>
        <nav className="flex min-w-max">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={activeTab === tab.id ? {
                padding: '0 14px',
                height: 36,
                display: 'flex',
                alignItems: 'center',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-text-high)',
                background: 'transparent',
                borderTop: '0.5px solid var(--color-ec-border)',
                borderLeft: '0.5px solid var(--color-ec-border)',
                borderRight: '0.5px solid var(--color-ec-border)',
                borderBottom: '2px solid var(--color-ec-copper)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              } : {
                padding: '0 14px',
                height: 36,
                display: 'flex',
                alignItems: 'center',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-text-muted)',
                borderTop: '0.5px solid var(--color-ec-border)',
                borderLeft: '0.5px solid var(--color-ec-border)',
                borderRight: '0.5px solid var(--color-ec-border)',
                borderBottom: '0.5px solid var(--color-ec-border)',
                background: 'transparent',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
              onMouseEnter={(e) => { if (activeTab !== tab.id) e.currentTarget.style.color = 'var(--color-ec-text-secondary)'; }}
              onMouseLeave={(e) => { if (activeTab !== tab.id) e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="pb-2">
        <div style={{ display: activeTab === "performance" ? "block" : "none" }}>
          <PerformanceTab
            dayResults={result.day_results}
            trades={result.trades}
            initCash={initCash}
            riskR={riskR}
            isDarkMode={isDarkMode}
          />
        </div>
        <div style={{ display: activeTab === "calendar" ? "block" : "none" }}>
          <CalendarTab dayResults={result.day_results} trades={result.trades} isDarkMode={isDarkMode} />
        </div>
        <div style={{ display: activeTab === "trades" ? "block" : "none" }}>
          <TradesTab trades={result.trades} />
        </div>
        <div style={{ display: activeTab === "analysis" ? "block" : "none" }}>
          <div>
            {candlesLoading && (
              <div className="flex items-center justify-center p-8">
                <div className="text-center space-y-2">
                  <svg className="animate-spin h-5 w-5 text-[var(--muted)] mx-auto" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <p className="text-[10px] text-[var(--muted)] font-mono">loading chart...</p>
                </div>
              </div>
            )}
            {!candlesLoading && dayCandles && dayCandles.candles.length > 0 && (
              <Chart
                candles={dayCandles.candles}
                trades={currentTrades}
                equity={currentEquity}
                ticker={dayCandles.ticker}
                date={dayCandles.date}
              />
            )}
            {!candlesLoading && (!dayCandles || dayCandles.candles.length === 0) && (
              <p className="text-[10px] text-[var(--muted)] text-center py-8 font-mono">
                Selecciona un dia en el panel lateral para ver el analisis del trade.
              </p>
            )}
          </div>
        </div>
        <div style={{ display: activeTab === "charts" ? "block" : "none" }}>
          <ChartsTab trades={result.trades} dayResults={result.day_results} riskR={riskR} isDarkMode={isDarkMode} />
        </div>
        <div style={{ display: activeTab === "optimization" ? "block" : "none" }}>
          <OptimizationSurfaceTab
            strategyId={strategyId}
            datasetId={datasetId}
            isDarkMode={isDarkMode}
            backtestParams={backtestParams}
          />
        </div>
      </div>
    </div>
  );
}
