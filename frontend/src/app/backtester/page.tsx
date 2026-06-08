"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import BacktestPanel, { type BacktestPanelParams } from "@/components/backtester/BacktestPanel";
import InlineStrategyBuilder, { type Draft } from "@/components/backtester/InlineStrategyBuilder";
import InlineDatasetBuilder from "@/components/backtester/InlineDatasetBuilder";
import MetricsCard from "@/components/backtester/MetricsCard";
import MaeScatterChart from "@/components/backtester/MaeScatterChart";
import ResultsTabs from "@/components/backtester/ResultsTabs";
import DaySelector from "@/components/backtester/DaySelector";
import EquityCurveTab from "@/components/backtester/tabs/EquityCurveTab";
import { createStrategy, createQuery, getStrategy, saveBacktest } from "@/lib/api";
import { validateStrategyLogic } from "@/lib/strategyValidation";
import {
  runBacktest,
  runBacktestWithDefinition,
  fetchDayCandles,
  fetchMultiDayCandles,
  type BacktestResult,
  type DayCandles,
  type MultiDayCandles,
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
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const panelParamsRef = useRef<BacktestPanelParams | null>(null);
  const [activeSessions, setActiveSessions] = useState<string[]>(["rth"]);
  const [activeCustomStartTime, setActiveCustomStartTime] = useState("09:30");
  const [activeCustomEndTime, setActiveCustomEndTime] = useState("16:00");

  const handlePanelParamsChange = useCallback((params: BacktestPanelParams) => {
    panelParamsRef.current = params;
    setActiveSessions(params.market_sessions || ["rth"]);
    setActiveCustomStartTime(params.custom_start_time || "09:30");
    setActiveCustomEndTime(params.custom_end_time || "16:00");
  }, []);

  const [dayCandles, setDayCandles] = useState<DayCandles | null>(null);
  const [activeStrategy, setActiveStrategy] = useState<any | null>(null);
  const [multiDayCandles, setMultiDayCandles] = useState<MultiDayCandles | null>(null);
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
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
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
    setMultiDayCandles(null);
    setActiveStrategy(null);

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
      locates_cost: p.locates_cost,
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
      if (data.trades && data.trades.length > 0) {
        const firstTrade = data.trades[0];
        const dayIdx = data.day_results.findIndex(
          (d) => d.ticker === firstTrade.ticker && d.date === firstTrade.date
        );
        if (dayIdx !== -1) {
          setSelectedDay(dayIdx);
        }
      }
      setActiveStrategy({
        id: "draft",
        name: draft.name,
        description: "",
        definition: {
          apply_day: draft.apply_day,
          bias: draft.bias,
          postgap_preconditions: draft.postgap_preconditions,
          entry_logic: draft.entry_logic,
          exit_logic: draft.exit_logic,
          risk_management: draft.risk_management,
        }
      });
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
      if (msg !== "Backtest cancelado") {
        setError(msg);
      }
    } finally {
      setLoading(false);
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
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
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
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
    setMultiDayCandles(null);
    setActiveStrategy(null);
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
      locates_cost: (params as any).locates_cost,
    };

    try {
      const data = await runBacktest(params);
      setResult(data);
      if (data.trades && data.trades.length > 0) {
        const firstTrade = data.trades[0];
        const dayIdx = data.day_results.findIndex(
          (d) => d.ticker === firstTrade.ticker && d.date === firstTrade.date
        );
        if (dayIdx !== -1) {
          setSelectedDay(dayIdx);
        }
      }
      try {
        const strategyData = await getStrategy(params.strategy_id);
        setActiveStrategy(strategyData);
      } catch (strategyErr) {
        console.warn("Could not fetch strategy definition:", strategyErr);
      }
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
      if (msg !== "Backtest cancelado") {
        setError(msg);
      }
    } finally {
      setLoading(false);
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
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
      setMultiDayCandles(null);
      try {
        let applyDay = "gap_day";
        if (activeStrategy?.definition?.apply_day) {
          applyDay = activeStrategy.definition.apply_day as string;
        }

        const data = await fetchMultiDayCandles(
          datasetIdRef.current,
          day.ticker,
          day.date,
          applyDay
        );
        setMultiDayCandles(data);

        // Populate fallback dayCandles for backward compatibility
        let mainCandlesObj = data.gap_day;
        if (applyDay === "gap_1_day" && data.gap_1_day) {
          mainCandlesObj = data.gap_1_day;
        } else if (applyDay === "gap_2_day" && data.gap_2_day) {
          mainCandlesObj = data.gap_2_day;
        }

        if (mainCandlesObj) {
          setDayCandles({
            ticker: day.ticker,
            date: mainCandlesObj.date,
            candles: mainCandlesObj.candles,
          });
        }
      } catch (err) {
        console.error("Error loading candles:", err);
        setDayCandles(null);
        setMultiDayCandles(null);
      } finally {
        setCandlesLoading(false);
      }
    },
    [result, activeStrategy]
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

  // ── IS/OOS filtering ──
  const currentIsPercent = (panelParamsRef.current?.is_percent as number) ?? 100;

  const isFilteredResult = useMemo(() => {
    if (!result || currentIsPercent >= 100) return result;

    const eq = result.global_equity;
    if (!eq || eq.length < 2) return result;

    // Find the IS cutoff index based on percentage of equity points
    const cutoffIdx = Math.max(1, Math.floor(eq.length * currentIsPercent / 100));
    const cutoffTime = eq[cutoffIdx - 1].time;

    // Filter trades to IS period only
    const isTrades = result.trades.filter(t => {
      const tradeEpoch = t.entry_time_epoch;
      return tradeEpoch <= cutoffTime;
    });

    // Filter day_results to IS period only
    const isDayResults = result.day_results.filter(d => {
      const dateEpoch = new Date(d.date).getTime() / 1000;
      return dateEpoch <= cutoffTime;
    });

    // Filter equity and drawdown to IS period
    const isEquity = eq.slice(0, cutoffIdx);
    const isDrawdown = result.global_drawdown.filter(p => p.time <= cutoffTime);

    // Filter equity_curves (per-day) to IS period
    const isEquityCurves = result.equity_curves.filter(e => {
      const dateEpoch = new Date(e.date).getTime() / 1000;
      return dateEpoch <= cutoffTime;
    });

    // Recompute aggregate metrics from IS trades
    const totalTrades = isTrades.length;
    const wins = isTrades.filter(t => t.pnl > 0);
    const losses = isTrades.filter(t => t.pnl < 0);
    const winRate = totalTrades > 0 ? (wins.length / totalTrades) * 100 : 0;
    const grossProfit = wins.reduce((s, t) => s + t.pnl, 0);
    const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
    const totalPnl = isTrades.reduce((s, t) => s + t.pnl, 0);
    const initCash = initCashRef.current;
    const totalReturnPct = initCash > 0 ? (totalPnl / initCash) * 100 : 0;

    // Daily returns for Sharpe/Sortino
    const dailyPnls = new Map<string, number>();
    isTrades.forEach(t => {
      dailyPnls.set(t.date, (dailyPnls.get(t.date) || 0) + t.pnl);
    });
    const dailyReturns = Array.from(dailyPnls.values()).map(p => p / initCash);
    const meanRet = dailyReturns.length > 0 ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length : 0;
    const stdRet = dailyReturns.length > 1
      ? Math.sqrt(dailyReturns.reduce((s, r) => s + (r - meanRet) ** 2, 0) / (dailyReturns.length - 1))
      : 0;
    const downside = dailyReturns.filter(r => r < 0);
    const downsideStd = downside.length > 1
      ? Math.sqrt(downside.reduce((s, r) => s + r ** 2, 0) / (downside.length - 1))
      : 0;
    const sharpe = stdRet > 0 ? (meanRet / stdRet) * Math.sqrt(252) : 0;
    const sortino = downsideStd > 0 ? (meanRet / downsideStd) * Math.sqrt(252) : 0;

    // Max drawdown from IS equity
    let peak = isEquity[0]?.value ?? initCash;
    let maxDd = 0;
    isEquity.forEach(p => {
      if (p.value > peak) peak = p.value;
      const dd = ((p.value - peak) / peak) * 100;
      if (dd < maxDd) maxDd = dd;
    });

    const avgWin = wins.length > 0 ? grossProfit / wins.length : 0;
    const avgLoss = losses.length > 0 ? grossLoss / losses.length : 0;
    const uniqueDays = new Set(isTrades.map(t => t.date)).size;

    const isMetrics = {
      ...result.aggregate_metrics,
      total_days: uniqueDays,
      total_trades: totalTrades,
      win_rate_pct: winRate,
      total_return_pct: totalReturnPct,
      total_pnl: totalPnl,
      avg_sharpe: sharpe,
      sortino_ratio: sortino,
      max_drawdown_pct: maxDd,
      avg_profit_factor: profitFactor,
      avg_win: avgWin,
      avg_loss: avgLoss,
      payoff_ratio: avgLoss > 0 ? avgWin / avgLoss : 0,
      expectancy: totalTrades > 0 ? totalPnl / totalTrades : 0,
      avg_r_per_day: uniqueDays > 0 && riskRRef.current > 0
        ? totalPnl / uniqueDays / riskRRef.current
        : 0,
      calmar_ratio: maxDd !== 0 ? totalReturnPct / Math.abs(maxDd) : 0,
      dd_return_ratio: totalReturnPct !== 0 ? Math.abs(maxDd) / totalReturnPct : 0,
    };

    // Filter global_equity_expenses if present
    const isEquityExpenses = result.global_equity_expenses
      ? result.global_equity_expenses.filter(p => p.time <= cutoffTime)
      : undefined;

    return {
      ...result,
      aggregate_metrics: isMetrics,
      day_results: isDayResults,
      trades: isTrades,
      equity_curves: isEquityCurves,
      global_equity: isEquity,
      global_equity_expenses: isEquityExpenses,
      global_drawdown: isDrawdown,
    } as BacktestResult;
  }, [result, currentIsPercent]);

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
              onClearPendingDataset={() => setPendingDatasetSelect(undefined)}
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
                <button
                  onClick={async () => {
                    const dsId = datasetIdRef.current;
                    if (!dsId) return;
                    setLoading(false);
                    setBacktestProgress(null);
                    setError("Backtest cancelado por el usuario.");
                    if (pollTimerRef.current) {
                      clearInterval(pollTimerRef.current);
                      pollTimerRef.current = null;
                    }
                    try {
                      const { cancelBacktest } = await import("@/lib/api_backtester");
                      await cancelBacktest(dsId);
                    } catch (e) {
                      console.warn("Error requesting backtest cancel:", e);
                    }
                  }}
                  style={{
                    marginTop: 16,
                    padding: '8px 16px',
                    backgroundColor: 'transparent',
                    border: '1px solid var(--color-ec-border)',
                    borderRadius: 5,
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '1px',
                    color: 'var(--color-ec-text-muted)',
                    cursor: 'pointer',
                    transition: 'all 150ms ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
                    e.currentTarget.style.color = 'var(--color-ec-text-primary)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                    e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                  }}
                >
                  Cancelar carga
                </button>
              </div>
            </div>
          )}

          {result && (
            <>
              {/* TOP ROW: Equity Curve (2/3) + Metrics (1/3) */}
              <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
                <div style={{ width: '66.666667%', height: 580 }}>
                  <EquityCurveTab
                    globalEquity={isFilteredResult!.global_equity}
                    globalDrawdown={isFilteredResult!.global_drawdown}
                    trades={isFilteredResult!.trades}
                    metrics={isFilteredResult!.aggregate_metrics}
                    initCash={initCashRef.current}
                    riskR={riskRRef.current}
                    monthlyExpenses={backtestParamsRef.current.monthly_expenses as number | undefined}
                    isPercent={currentIsPercent}
                    fullGlobalEquity={result.global_equity}
                    fullGlobalDrawdown={result.global_drawdown}
                    fullTrades={result.trades}
                    isDarkMode={isDarkMode}
                  />
                </div>
                <div style={{ width: '33.333333%', display: 'flex', flexDirection: 'column', height: 580, paddingBottom: 4, boxSizing: 'border-box' }}>
                  <div style={{ flexShrink: 0 }}>
                    <MetricsCard metrics={isFilteredResult!.aggregate_metrics} vertical />
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
                    <MaeScatterChart trades={isFilteredResult!.trades} isDarkMode={isDarkMode} />
                  </div>
                </div>
              </div>

              <ResultsTabs
                result={isFilteredResult!}
                initCash={initCashRef.current}
                riskR={riskRRef.current}
                dayCandles={dayCandles}
                multiDayCandles={multiDayCandles}
                activeStrategy={activeStrategy}
                strategyDefinition={activeStrategy?.definition}
                candlesLoading={candlesLoading}
                currentTrades={currentTrades || []}
                currentEquity={currentEquity?.equity || []}
                isDarkMode={isDarkMode}
                strategyId={strategyIdRef.current}
                datasetId={datasetIdRef.current}
                backtestParams={backtestParamsRef.current}
                onSelectDay={setSelectedDay}
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
                      const logicErrors = validateStrategyLogic(
                        strategyToSave.entry_logic,
                        strategyToSave.exit_logic,
                      );
                      if (logicErrors.length > 0) {
                        alert("Hay condiciones incompletas:\n" + logicErrors.join("\n"));
                        return;
                      }
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
                            results_json: {
                              ...result,
                              backtest_params: backtestParamsRef.current
                            } as unknown as Record<string, unknown>,
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
            marketSessions={activeSessions}
            customStartTime={activeCustomStartTime}
            customEndTime={activeCustomEndTime}
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
