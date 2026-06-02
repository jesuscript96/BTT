"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import BacktestPanel, { type BacktestPanelParams } from "@/components/backtester/BacktestPanel";
import InlineStrategyBuilder, { type Draft } from "@/components/backtester/InlineStrategyBuilder";
import InlineDatasetBuilder from "@/components/backtester/InlineDatasetBuilder";
import MetricsCard from "@/components/backtester/MetricsCard";
import MaeScatterChart from "@/components/backtester/MaeScatterChart";
import ResultsTabs from "@/components/backtester/ResultsTabs";
import DaySelector from "@/components/backtester/DaySelector";
import EquityCurveTab from "@/components/backtester/tabs/EquityCurveTab";
import { createStrategy, createQuery, getStrategy, saveBacktest } from "@/lib/api";
import {
  runBacktest,
  runBacktestWithDefinition,
  fetchDayCandles,
  type BacktestResult,
  type DayCandles,
} from "@/lib/api_backtester";

export default function Home() {
  const [mode, setMode] = useState<"config" | "builder" | "dataset">("config");
  const [datasetRefresh, setDatasetRefresh] = useState(0);
  const [pendingDatasetSelect, setPendingDatasetSelect] = useState<string | undefined>(undefined);
  const [draftStrategy, setDraftStrategy] = useState<Draft | null>(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [strategiesRefresh, setStrategiesRefresh] = useState(0);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [backtestProgress, setBacktestProgress] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState(0);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [strategyToSave, setStrategyToSave] = useState<any | null>(null);
  const [includeWhatIfInSave, setIncludeWhatIfInSave] = useState(false);
  const [hoveredSaveBtn, setHoveredSaveBtn] = useState(false);
  const [activeSaveBtn, setActiveSaveBtn] = useState(false);

  const handleSaveToBaulClick = async () => {
    if (draftStrategy) {
      setStrategyToSave({
        name: draftStrategy.name,
        bias: draftStrategy.bias,
        apply_day: draftStrategy.apply_day,
        postgap_preconditions: draftStrategy.postgap_preconditions,
        entry_logic: draftStrategy.entry_logic,
        exit_logic: draftStrategy.exit_logic,
        risk_management: draftStrategy.risk_management,
      });
      setSaveName(draftStrategy.name);
      setShowSaveModal(true);
    } else if (strategyIdRef.current && strategyIdRef.current !== "draft") {
      try {
        const existing = await getStrategy(strategyIdRef.current);
        setStrategyToSave(existing);
        setSaveName(`${existing.name} (Copia)`);
        setShowSaveModal(true);
      } catch (err) {
        alert("Error al cargar la estrategia para guardar.");
      }
    } else {
      alert("No hay ninguna estrategia activa para guardar.");
    }
  };
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

    try {
      const { fetchPrecacheStatus } = await import("@/lib/api_backtester");
      const statusData = await fetchPrecacheStatus(p.dataset_id);
      if (statusData && statusData.status === "running") {
        setError(`Espera a que se cargue el dataset (progreso: ${statusData.percent}%)`);
        return;
      }
    } catch (e) {
      console.warn("Could not check dataset precache status before run:", e);
    }

    setLoading(true);
    setBacktestProgress({ status: "running", percent: 0.0, current: 0, total: 0 });
    const pollTimer = setInterval(async () => {
      try {
        const { fetchBacktestProgress } = await import("@/lib/api_backtester");
        const prog = await fetchBacktestProgress(p.dataset_id);
        setBacktestProgress(prog);
      } catch (err) {
        console.warn("Could not fetch backtest progress:", err);
      }
    }, 500);

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
          apply_day: draft.apply_day,
          postgap_preconditions: draft.postgap_preconditions,
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
      clearInterval(pollTimer);
      setBacktestProgress(null);
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
    setBacktestProgress({ status: "running", percent: 0.0, current: 0, total: 0 });
    const pollTimer = setInterval(async () => {
      try {
        const { fetchBacktestProgress } = await import("@/lib/api_backtester");
        const prog = await fetchBacktestProgress(params.dataset_id);
        setBacktestProgress(prog);
      } catch (err) {
        console.warn("Could not fetch backtest progress:", err);
      }
    }, 500);

    setError(null);
    setResult(null);
    setSelectedDay(0);
    setDayCandles(null);
    setDraftStrategy(null);
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
      clearInterval(pollTimer);
      setBacktestProgress(null);
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh', overflow: 'hidden', backgroundColor: 'var(--color-ec-bg-base)' }}>

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
        </div>
      </header>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0, position: 'relative' }}>
        {/* Panel izquierdo */}
        <aside style={{
          width: 280,
          flexShrink: 0,
          borderRight: '0.5px solid var(--color-ec-border)',
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          overflowY: 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          scrollbarWidth: 'none',
          position: 'relative',
          zIndex: 45,
        }}>
          <div style={{ padding: '16px 12px 24px 12px', display: 'flex', flexDirection: 'column', gap: 16 }}>
            <BacktestPanel
              onRun={handleRun}
              onNewStrategy={() => setMode((prev) => (prev === 'builder' ? 'config' : 'builder'))}
              onNewDataset={() => setMode((prev) => (prev === 'dataset' ? 'config' : 'dataset'))}
              onParamsChange={handlePanelParamsChange}
              refreshTrigger={strategiesRefresh}
              datasetRefreshTrigger={datasetRefresh}
              pendingDatasetSelect={pendingDatasetSelect}
              loading={loading}
              isDarkMode={isDarkMode}
            />
            {result && (
              <DaySelector
                days={result.day_results}
                selectedIdx={selectedDay}
                onSelect={setSelectedDay}
              />
            )}
          </div>
        </aside>

        {/* Panel derecho */}
        <main style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: 0,
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
              height: '100%',
              gap: 12,
              color: 'var(--color-ec-text-muted)',
            }}>
              <div style={{ fontSize: 32 }}>◎</div>
              <div style={{
                fontSize: 13,
                fontWeight: 500,
                textAlign: 'center',
                maxWidth: 300,
                lineHeight: 1.6,
                fontFamily: 'var(--color-ec-sans)',
                color: 'var(--color-ec-text-muted)',
              }}>
                Selecciona un dataset y una estrategia<br />para ejecutar el backtest
              </div>
            </div>
          )}

          {loading && (
            <div className="flex items-center justify-center h-64">
              <div className="text-center space-y-4 w-full max-w-sm px-6">
                <svg className="animate-spin h-7 w-7 text-[var(--color-ec-copper)] mx-auto" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <div className="space-y-2">
                  <div className="flex justify-between items-end">
                    <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-ec-text-primary)]">
                      Ejecutando backtest
                    </p>
                    {backtestProgress && backtestProgress.percent !== undefined && (
                      <span className="text-xs font-mono font-bold text-[var(--color-ec-copper)]">
                        {backtestProgress.percent}%
                      </span>
                    )}
                  </div>
                  <div className="h-1.5 w-full bg-[var(--color-ec-bg-elevated)] border border-[var(--color-ec-border)] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[var(--color-ec-copper)] rounded-full transition-all duration-300 ease-out"
                      style={{ width: `${backtestProgress?.percent ?? 0}%` }}
                    />
                  </div>
                  {backtestProgress && backtestProgress.total > 0 && (
                    <p className="text-[10px] text-[var(--color-ec-text-muted)] font-mono text-right">
                      {backtestProgress.current} / {backtestProgress.total} días procesados
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {result && (
            <>
              {/* TOP ROW: Equity Curve (2/3) + Metrics (1/3) */}
              <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
                <div style={{ width: '66.666667%', height: 580 }}>
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
                <div style={{ width: '33.333333%', display: 'flex', flexDirection: 'column', height: 580, paddingBottom: 4, boxSizing: 'border-box' }}>
                  <div style={{ flexShrink: 0 }}>
                    <MetricsCard metrics={result.aggregate_metrics} vertical />
                    <div style={{ padding: '12px 4px 4px 4px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <button
                        onClick={handleSaveToBaulClick}
                        onMouseEnter={() => setHoveredSaveBtn(true)}
                        onMouseLeave={() => { setHoveredSaveBtn(false); setActiveSaveBtn(false); }}
                        onMouseDown={() => setActiveSaveBtn(true)}
                        onMouseUp={() => setActiveSaveBtn(false)}
                        style={{
                          width: '100%',
                          padding: '8px 0',
                          backgroundColor: 'var(--color-ec-copper)',
                          border: 'none',
                          borderRadius: 5,
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 11,
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          letterSpacing: '1.2px',
                          color: 'var(--color-ec-copper-text)',
                          cursor: 'pointer',
                          boxShadow: hoveredSaveBtn ? '0 0 14px rgba(216, 122, 61, 0.5)' : 'none',
                          transform: activeSaveBtn ? 'scale(0.98)' : hoveredSaveBtn ? 'scale(1.015)' : 'scale(1)',
                          transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
                        }}
                      >
                        Guardar estrategia en el baúl
                      </button>
                      <label style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 8,
                        cursor: 'pointer',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        color: 'var(--color-ec-text-secondary)',
                        userSelect: 'none',
                      }}>
                        <input
                          type="checkbox"
                          checked={includeWhatIfInSave}
                          onChange={(e) => setIncludeWhatIfInSave(e.target.checked)}
                          style={{
                            accentColor: 'var(--color-ec-copper)',
                            cursor: 'pointer',
                            width: 13,
                            height: 13,
                          }}
                        />
                        <span>incluir configuración del what-if</span>
                      </label>
                    </div>
                  </div>
                  <div style={{ height: 250, width: '100%', marginTop: 'auto', marginBottom: 38, flexShrink: 0 }}>
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
          {/* Modal — guardar draft como estrategia */}
          {showSaveModal && (
            <div style={{
              position: 'fixed', inset: 0, zIndex: 100,
              backgroundColor: 'rgba(0,0,0,0.6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <div style={{
                backgroundColor: 'var(--color-ec-bg-surface)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 7,
                padding: 24,
                width: 340,
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ec-text-high)', fontFamily: 'var(--color-ec-serif)' }}>
                  Guardar estrategia
                </div>
                <input
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="Nombre de la estrategia"
                  autoFocus
                  style={{
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                    padding: '8px 11px',
                    fontSize: 12,
                    color: 'var(--color-ec-text-primary)',
                    outline: 'none',
                    width: '100%',
                    fontFamily: 'var(--color-ec-sans)',
                  }}
                  onKeyDown={(e) => { if (e.key === 'Escape') setShowSaveModal(false); }}
                />
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => setShowSaveModal(false)}
                    style={{
                      flex: 1, padding: '7px 0', borderRadius: 5,
                      fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
                      textTransform: 'uppercase', cursor: 'pointer',
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-muted)',
                      fontFamily: 'var(--color-ec-sans)',
                    }}
                  >
                    Cancelar
                  </button>
                  <button
                    disabled={!saveName.trim()}
                    onClick={async () => {
                      if (!saveName.trim() || !strategyToSave) return;
                      let description = strategyToSave.description || "";
                      if (includeWhatIfInSave) {
                        const stored = localStorage.getItem("current_whatif_params");
                        if (stored) {
                          try {
                            const parsed = JSON.parse(stored);
                            const whatifDesc = `[What-if: ${Object.entries(parsed).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")}]`;
                            description = description ? `${description}\n${whatifDesc}` : whatifDesc;
                          } catch {
                            description = description ? `${description}\n[What-if: ${stored}]` : `[What-if: ${stored}]`;
                          }
                        }
                      }
                      const savedStrategy = await createStrategy({
                        name: saveName.trim(),
                        description,
                        bias: strategyToSave.bias,
                        entry_logic: strategyToSave.entry_logic,
                        exit_logic: strategyToSave.exit_logic,
                        risk_management: strategyToSave.risk_management,
                      });
                      const newStrategyId = savedStrategy.id;

                      // Persist the backtest run linked to the newly created strategy so
                      // the Baul can display real metrics (equity, win rate, sharpe, etc.)
                      if (result && newStrategyId) {
                        try {
                          await saveBacktest({
                            strategy_ids: [newStrategyId],
                            results_json: result as unknown as Record<string, unknown>,
                          });
                        } catch (e) {
                          console.warn("No se pudieron guardar los resultados del backtest:", e);
                        }
                      }

                      setStrategiesRefresh((prev) => prev + 1);
                      setShowSaveModal(false);
                      setDraftStrategy(null);
                      setStrategyToSave(null);
                    }}
                    style={{
                      flex: 2, padding: '7px 0', borderRadius: 5,
                      fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
                      textTransform: 'uppercase', cursor: 'pointer',
                      backgroundColor: 'var(--color-ec-copper)',
                      border: 'none',
                      color: 'var(--color-ec-copper-text)',
                      fontFamily: 'var(--color-ec-sans)',
                      opacity: saveName.trim() ? 1 : 0.4,
                    }}
                  >
                    Guardar
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>

        {/* Backdrop blur overlay for the main content area */}
        {(mode === 'builder' || mode === 'dataset') && (
          <div 
            onClick={() => setMode('config')}
            style={{
              position: 'absolute',
              inset: 0,
              left: 280, // Starts after the sidebar (width 280px)
              backgroundColor: 'rgba(0, 0, 0, 0.4)',
              backdropFilter: 'blur(2px)',
              zIndex: 35,
              transition: 'opacity 300ms ease',
              cursor: 'pointer',
            }}
          />
        )}

        {/* Drawer/Desplegable de la lógica (InlineStrategyBuilder) */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 280,
          bottom: 0,
          width: 550,
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          borderRight: '0.5px solid var(--color-ec-border)',
          zIndex: 40,
          transform: mode === 'builder' ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 300ms cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: '10px 0 30px rgba(0, 0, 0, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <InlineStrategyBuilder
            onBack={() => setMode('config')}
            onTest={async (draft) => {
              setDraftStrategy(draft);
              setMode('config');
              await handleRunWithDraft(draft);
            }}
          />
        </div>

        {/* Drawer/Desplegable de la creación de Dataset (InlineDatasetBuilder) */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 280,
          bottom: 0,
          width: 550,
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          borderRight: '0.5px solid var(--color-ec-border)',
          zIndex: 40,
          transform: mode === 'dataset' ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 300ms cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: '10px 0 30px rgba(0, 0, 0, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <InlineDatasetBuilder
            onBack={() => setMode('config')}
            onSave={async (name, filters) => {
              try {
                setError(null);
                const newQuery = await createQuery({ name, filters });
                // Trigger refresh of datasets in BacktestPanel
                setDatasetRefresh((prev) => prev + 1);
                // We will select the new dataset after it refreshes
                setPendingDatasetSelect(newQuery.id);
                setMode("config");
              } catch (err: any) {
                setError(err.message || "Error al guardar el dataset");
              }
            }}
          />
        </div>

      </div>
    </div>
  );
}
