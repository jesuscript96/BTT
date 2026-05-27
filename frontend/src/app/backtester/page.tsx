"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import BacktestPanel, { type BacktestPanelParams } from "@/components/backtester/BacktestPanel";
import InlineStrategyBuilder, { type Draft } from "@/components/backtester/InlineStrategyBuilder";
import MetricsCard from "@/components/backtester/MetricsCard";
import MaeScatterChart from "@/components/backtester/MaeScatterChart";
import ResultsTabs from "@/components/backtester/ResultsTabs";
import DaySelector from "@/components/backtester/DaySelector";
import EquityCurveTab from "@/components/backtester/tabs/EquityCurveTab";
import { createStrategy } from "@/lib/api";
import {
  runBacktest,
  runBacktestWithDefinition,
  fetchDayCandles,
  type BacktestResult,
  type DayCandles,
} from "@/lib/api_backtester";

export default function Home() {
  const [mode, setMode] = useState<"config" | "builder">("config");
  const [draftStrategy, setDraftStrategy] = useState<Draft | null>(null);
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
  const panelParamsRef = useRef<BacktestPanelParams | null>(null);
  const handlePanelParamsChange = useCallback((params: BacktestPanelParams) => {
    panelParamsRef.current = params;
  }, []);

  const [dayCandles, setDayCandles] = useState<DayCandles | null>(null);
  const [candlesLoading, setCandlesLoading] = useState(false);

  const handleRunWithDraft = async (draft: Draft) => {
    const p = panelParamsRef.current;
    if (!p?.dataset_id) {
      setError("Selecciona un dataset en el panel de configuración antes de probar el draft.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedDay(0);
    setDayCandles(null);
    initCashRef.current = p.init_cash;
    riskRRef.current = p.risk_r;
    datasetIdRef.current = p.dataset_id;
    strategyIdRef.current = "draft";
    backtestParamsRef.current = {
      init_cash: p.init_cash,
      risk_r: p.risk_r,
      fees: p.fees,
      slippage: p.slippage,
      start_date: p.start_date,
      end_date: p.end_date,
      market_sessions: p.market_sessions,
      monthly_expenses: p.monthly_expenses,
    };

    try {
      const data = await runBacktestWithDefinition({
        dataset_id: p.dataset_id,
        strategy_definition: {
          name: draft.name,
          bias: draft.bias,
          entry_logic: draft.entry_logic,
          exit_logic: draft.exit_logic,
          risk_management: draft.risk_management,
        },
        init_cash: p.init_cash,
        risk_r: p.risk_r,
        risk_type: p.risk_type,
        fixed_ratio_delta: p.fixed_ratio_delta,
        size_by_sl: p.size_by_sl,
        fees: p.fees,
        fee_type: p.fee_type,
        slippage: p.slippage,
        start_date: p.start_date || undefined,
        end_date: p.end_date || undefined,
        market_sessions: p.market_sessions,
        custom_start_time: p.custom_start_time || undefined,
        custom_end_time: p.custom_end_time || undefined,
        locates_cost: p.locates_cost,
        monthly_expenses: p.monthly_expenses,
        look_ahead_prevention: p.look_ahead_prevention,
      });
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

  const handleSaveDraft = async (draft: Draft) => {
    try {
      await createStrategy({
        name: draft.name,
        description: "",
        bias: draft.bias,
        entry_logic: draft.entry_logic,
        exit_logic: draft.exit_logic,
        risk_management: draft.risk_management,
      });
      setMode("config");
    } catch (err) {
      console.error("Error guardando estrategia:", err);
    }
  };

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
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100dvh',
      backgroundColor: 'var(--color-ec-bg-base)',
      overflow: 'hidden',
    }}>
      <header style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px',
        height: 52,
        borderBottom: '0.5px solid var(--color-ec-border)',
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        flexShrink: 0,
      }}>
        <div className="flex items-center gap-3">
          <h1 style={{
            fontFamily: 'var(--color-ec-serif)',
            fontSize: 20,
            fontWeight: 600,
            color: 'var(--color-ec-text-high)',
            letterSpacing: '-0.3px',
          }}>Backtester</h1>
          <span style={{
            fontSize: 9,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            padding: '2px 7px',
            borderRadius: 3,
            backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 15%, transparent)',
            color: 'var(--color-ec-copper)',
            fontFamily: 'var(--color-ec-sans)',
          }}>
            VectorBT
          </span>
        </div>
      </header>

      <div style={{
        display: 'flex',
        flex: 1,
        overflow: 'hidden',
        minHeight: 0,
      }}>
        <aside style={{
          width: mode === 'builder' ? 360 : 280,
          flexShrink: 0,
          borderRight: '0.5px solid var(--color-ec-border)',
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          overflowY: mode === 'builder' ? 'hidden' : 'auto',
          overflowX: 'hidden',
          padding: mode === 'builder' ? 0 : '16px 12px',
          paddingBottom: mode === 'builder' ? 0 : 24,
          display: 'flex',
          flexDirection: 'column',
          gap: mode === 'builder' ? 0 : 16,
          scrollbarWidth: 'none',
        }}>
          {mode === 'builder' ? (
            <InlineStrategyBuilder
              onBack={() => setMode('config')}
              onTest={async (draft) => {
                setDraftStrategy(draft);
                setMode('config');
                await handleRunWithDraft(draft);
              }}
              onSave={handleSaveDraft}
            />
          ) : (
            <>
              <button
                onClick={() => setMode('builder')}
                style={{
                  width: '100%',
                  padding: '8px 0',
                  borderRadius: 5,
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: 1.2,
                  textTransform: 'uppercase',
                  cursor: 'pointer',
                  border: '0.5px solid var(--color-ec-copper)',
                  backgroundColor: 'transparent',
                  color: 'var(--color-ec-copper)',
                  fontFamily: 'var(--color-ec-sans)',
                }}
              >
                + Nueva Estrategia
              </button>

              <BacktestPanel onRun={handleRun} onParamsChange={handlePanelParamsChange} loading={loading} isDarkMode={isDarkMode} />

              {result && (
                <DaySelector
                  days={result.day_results}
                  selectedIdx={selectedDay}
                  onSelect={setSelectedDay}
                />
              )}
            </>
          )}
        </aside>

        <main style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          backgroundColor: 'var(--color-ec-bg-base)',
          minWidth: 0,
        }}>
          {error && (
            <div className="bg-ec-loss/10 border border-ec-loss/30 rounded-lg p-4">
              <p className="text-sm text-ec-loss">{error}</p>
            </div>
          )}

          {!result && !loading && !error && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 1,
              gap: 12,
              color: 'var(--color-ec-text-muted)',
            }}>
              <p style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-muted)',
                textAlign: 'center',
              }}>
                Selecciona un dataset y una estrategia para ejecutar el backtest
              </p>
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
                      style={{
                        width: '100%',
                        padding: '7px 0',
                        backgroundColor: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11,
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        letterSpacing: '1.2px',
                        color: 'var(--color-ec-text-secondary)',
                        cursor: 'pointer',
                        transition: 'color 150ms ease',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-ec-text-primary)')}
                      onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-ec-text-secondary)')}
                    >
                      Guardar estrategia
                    </button>
                    <label className="flex items-center gap-1.5 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        className="w-3 h-3 rounded-sm border border-[var(--color-ec-border)]"
                      />
                      <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-muted)',
                        letterSpacing: '0.05em',
                      }}>
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
