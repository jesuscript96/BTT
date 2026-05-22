"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import BacktestPanel from "@/components/backtester/BacktestPanel";
import MetricsCard from "@/components/backtester/MetricsCard";
import MaeScatterChart from "@/components/backtester/MaeScatterChart";
import ResultsTabs from "@/components/backtester/ResultsTabs";
import DaySelector from "@/components/backtester/DaySelector";
import EquityCurveTab from "@/components/backtester/tabs/EquityCurveTab";
import {
  runBacktest,
  fetchDayCandles,
  type BacktestResult,
  type DayCandles,
} from "@/lib/api_backtester";

export default function Home() {
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState(0);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const initCashRef = useRef(10000);
  const riskRRef = useRef(100);
  const datasetIdRef = useRef("");
  const strategyIdRef = useRef("");
  const backtestParamsRef = useRef<Record<string, unknown>>({});

  const [dayCandles, setDayCandles] = useState<DayCandles | null>(null);
  const [candlesLoading, setCandlesLoading] = useState(false);

  const handleRun = async (params: {
    dataset_id: string;
    strategy_id: string;
    init_cash: number;
    risk_r: number;
    fees: number;
    slippage: number;
    start_date?: string;
    end_date?: string;
    market_sessions?: string[];
    custom_start_time?: string;
    custom_end_time?: string;
    monthly_expenses?: number;
  }) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedDay(0);
    setDayCandles(null);
    initCashRef.current = params.init_cash;
    riskRRef.current = params.risk_r;
    datasetIdRef.current = params.dataset_id;
    strategyIdRef.current = params.strategy_id;
    backtestParamsRef.current = {
      init_cash: params.init_cash,
      risk_r: params.risk_r,
      fees: params.fees,
      slippage: params.slippage,
      start_date: params.start_date,
      end_date: params.end_date,
      market_sessions: params.market_sessions,
      monthly_expenses: params.monthly_expenses,
    };

    try {
      const data = await runBacktest(params);
      setResult(data);
    } catch (err: unknown) {
      let msg = "Error desconocido";
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        msg = axiosErr.response?.data?.detail || "Error del servidor";
      } else if (err && typeof err === "object" && "message" in err) {
        const errMsg = (err as { message: string }).message;
        if (errMsg.includes("timeout")) {
          msg = "Timeout: el backtest tardo demasiado. Prueba con un dataset mas pequeno.";
        } else if (errMsg.includes("Network")) {
          msg = "Error de red: verifica que el backend este corriendo.";
        } else {
          msg = errMsg;
        }
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const loadCandles = useCallback(
    async (dayIdx: number) => {
      if (!result || !datasetIdRef.current) return;
      const day = result.day_results[dayIdx];
      if (!day) return;

      setCandlesLoading(true);
      setDayCandles(null);
      try {
        const data = await fetchDayCandles(
          datasetIdRef.current,
          day.ticker,
          day.date
        );
        setDayCandles(data);
      } catch {
        setDayCandles(null);
      } finally {
        setCandlesLoading(false);
      }
    },
    [result]
  );

  useEffect(() => {
    if (result && result.day_results.length > 0) {
      loadCandles(selectedDay);
    }
  }, [result, selectedDay, loadCandles]);

  // Dark Mode side-effect
  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") {
      setIsDarkMode(true);
      document.documentElement.classList.add("dark");
    }
  }, []);

  const toggleDarkMode = () => {
    const newVal = !isDarkMode;
    setIsDarkMode(newVal);
    if (newVal) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  };

  const selectedDayResult = result?.day_results?.[selectedDay];
  const currentEquity = result?.equity_curves?.find(
    (e) =>
      selectedDayResult &&
      e.ticker === selectedDayResult.ticker &&
      e.date === selectedDayResult.date
  );
  const currentTrades = result?.trades?.filter(
    (t) =>
      selectedDayResult &&
      t.ticker === selectedDayResult.ticker &&
      t.date === selectedDayResult.date
  );

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)] transition-colors duration-200">
      <header className="border-b border-[var(--border)] bg-[var(--card-bg)] px-6 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold text-[var(--foreground)]">BacktesterJaume</h1>
          <span className="text-xs px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-100 font-medium">
            VectorBT
          </span>
        </div>

        <button
          onClick={toggleDarkMode}
          className="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 border border-[var(--border)] transition-colors"
          title={isDarkMode ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
        >
          {isDarkMode ? "☀️" : "🌙"}
        </button>
      </header>

      <div className="flex h-[calc(100vh-53px)]">
        <aside className="w-80 min-w-80 border-r border-[var(--border)] p-4 overflow-y-auto space-y-4 bg-[var(--sidebar-bg)]">
          <BacktestPanel onRun={handleRun} loading={loading} isDarkMode={isDarkMode} />

          {result && (
            <DaySelector
              days={result.day_results}
              selectedIdx={selectedDay}
              onSelect={setSelectedDay}
            />
          )}
        </aside>

        <main className="flex-1 overflow-y-auto p-4 space-y-4">
          {error && (
            <div className="bg-ec-loss/10 border border-ec-loss/30 rounded-lg p-4">
              <p className="text-sm text-ec-loss">{error}</p>
            </div>
          )}

          {!result && !loading && !error && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center space-y-2">
                <div className="text-5xl opacity-20">📊</div>
                <p className="text-[var(--muted)] text-sm">
                  Selecciona un dataset y una estrategia para ejecutar el backtest
                </p>
              </div>
            </div>
          )}

          {loading && (
            <div className="flex items-center justify-center h-64">
              <div className="text-center space-y-3">
                <svg className="animate-spin h-8 w-8 text-[var(--accent)] mx-auto" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <p className="text-sm text-[var(--muted)]">
                  Ejecutando backtest con VectorBT...
                </p>
              </div>
            </div>
          )}

          {result && (
            <>
              {/* TOP ROW: Equity Curve (2/3) + Metrics (1/3) */}
              <div className="flex gap-4 items-stretch">
                <div className="w-2/3">
                  <EquityCurveTab
                      globalEquity={result.global_equity}
                      globalDrawdown={result.global_drawdown}
                      trades={result.trades}
                      metrics={result.aggregate_metrics}
                      initCash={initCashRef.current}
                      riskR={riskRRef.current}
                      monthlyExpenses={backtestParamsRef.current.monthly_expenses as number | undefined}
                      isDarkMode={isDarkMode}
                    />
                </div>
                <div className="w-1/3 flex flex-col px-1 h-[675px]">
                  <div>
                    <MetricsCard metrics={result.aggregate_metrics} vertical />
                    
                    <div className="flex flex-col items-center justify-center gap-2 py-3 px-1">
                    <button
                      className="w-full px-4 py-2 text-[11px] font-bold uppercase tracking-[0.08em] rounded
                        bg-[var(--foreground)] text-[var(--background)]
                        hover:opacity-80 transition-opacity cursor-pointer shadow-sm"
                    >
                      Guardar estrategia
                    </button>
                    <label className="flex items-center gap-1.5 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        className="w-3 h-3 rounded-sm border border-[var(--border)] accent-[var(--foreground)]"
                      />
                      <span className="text-[9px] text-[var(--muted)] font-mono">
                        Enviar con configuración del What if
                      </span>
                    </label>
                  </div>
                  </div>
                  
                  <div className="h-[290px] w-full mt-auto mb-[-14px]">
                    <MaeScatterChart trades={result.trades} isDarkMode={isDarkMode} />
                  </div>
                </div>
              </div>

              <ResultsTabs
                result={result}
                initCash={initCashRef.current}
                riskR={riskRRef.current}
                dayCandles={dayCandles}
                candlesLoading={candlesLoading}
                currentTrades={currentTrades || []}
                currentEquity={currentEquity?.equity || []}
                isDarkMode={isDarkMode}
                strategyId={strategyIdRef.current}
                datasetId={datasetIdRef.current}
                backtestParams={backtestParamsRef.current}
              />
            </>
          )}

        </main>
      </div>
    </div>
  );
}
