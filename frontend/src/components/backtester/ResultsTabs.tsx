"use client";

import { useState, useEffect } from "react";
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
  onSelectDay?: (idx: number) => void;
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
  onSelectDay,
}: ResultsTabsProps) {
  const [activeTab, setActiveTab] = useState<TabId>("performance");

  const handleSelectTrade = (ticker: string, date: string) => {
    const dayIdx = result.day_results.findIndex(
      (d) => d.ticker === ticker && d.date === date
    );
    if (dayIdx !== -1) {
      if (onSelectDay) {
        onSelectDay(dayIdx);
      }
      setActiveTab("analysis");
    }
  };

  const [loadProgress, setLoadProgress] = useState(0);

  useEffect(() => {
    if (candlesLoading) {
      setLoadProgress(0);
      const interval = setInterval(() => {
        setLoadProgress((prev) => {
          if (prev < 30) return prev + Math.random() * 15 + 5;
          if (prev < 70) return prev + Math.random() * 10 + 2;
          if (prev < 90) return prev + Math.random() * 3 + 0.5;
          return prev;
        });
      }, 80);
      return () => clearInterval(interval);
    } else {
      setLoadProgress(100);
    }
  }, [candlesLoading]);

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
          <TradesTab trades={result.trades} onSelectTrade={handleSelectTrade} />
        </div>
        <div style={{ display: activeTab === "analysis" ? "block" : "none" }}>
          <div style={{ minHeight: 520, display: 'flex', flexDirection: 'column', position: 'relative' }}>
            {candlesLoading && (
              <div 
                style={{ 
                  display: 'flex', 
                  flexDirection: 'column', 
                  alignItems: 'center', 
                  justifyContent: 'center', 
                  flex: 1,
                  minHeight: 520,
                  gap: 16 
                }}
              >
                <div style={{ width: 240 }}>
                  <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center', 
                    marginBottom: 6,
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    color: 'var(--color-ec-text-secondary)'
                  }}>
                    <span>Cargando trade</span>
                    <span style={{ fontFamily: 'var(--color-ec-mono)', color: 'var(--color-ec-copper)', fontWeight: 700 }}>
                      {Math.round(loadProgress)}%
                    </span>
                  </div>
                  <div style={{ 
                    height: 4, 
                    width: '100%', 
                    backgroundColor: 'var(--color-ec-bg-elevated)', 
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 2,
                    overflow: 'hidden'
                  }}>
                    <div 
                      style={{ 
                        height: '100%', 
                        width: `${loadProgress}%`, 
                        backgroundColor: 'var(--color-ec-copper)',
                        borderRadius: 2,
                        transition: 'width 80ms ease-out'
                      }} 
                    />
                  </div>
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
              <div 
                style={{ 
                  display: 'flex', 
                  flexDirection: 'column', 
                  alignItems: 'center', 
                  justifyContent: 'center', 
                  flex: 1, 
                  minHeight: 520 
                }}
              >
                <p className="text-[10px] text-[var(--muted)] text-center font-mono">
                  Selecciona un dia en el panel lateral para ver el analisis del trade.
                </p>
              </div>
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
