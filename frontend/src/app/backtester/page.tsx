"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import BacktestPanel, { type BacktestPanelParams } from "@/components/backtester/BacktestPanel";
import InlineStrategyBuilder, { type Draft } from "@/components/backtester/InlineStrategyBuilder";
import InlineDatasetBuilder from "@/components/backtester/InlineDatasetBuilder";
import StrategyModeSelector from "@/components/strategy-builder/StrategyModeSelector";
import WizardStrategyBuilder from "@/components/strategy-builder/WizardStrategyBuilder";
import MetricsCard from "@/components/backtester/MetricsCard";
import MaeScatterChart from "@/components/backtester/MaeScatterChart";
import ResultsTabs from "@/components/backtester/ResultsTabs";
import DaySelector from "@/components/backtester/DaySelector";
import EquityCurveTab from "@/components/backtester/tabs/EquityCurveTab";
import { createStrategy, createQuery, getStrategy, saveBacktest, updateStrategy } from "@/lib/api";
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
  const [mode, setMode] = useState<"config" | "builder_choice" | "builder" | "wizard" | "dataset">("config");
  /* POST-MVP AGENTIC - descomentar cuando se active ChatBotAgentic.tsx (ver docs/plan_asistente_edgie.md)
  // ── Edgie assistant integration (AssistantBus) ───────────────
  useAssistantAction({
    name: "backtester.set_mode",
    description:
      "Cambia el panel visible del Backtester: 'config' muestra el formulario del backtest, 'builder' el constructor de estrategias, 'dataset' el constructor de datasets.",
    parameters: SetModeSchema,
    confirm: "auto",
    handler: (args) => {
      const newMode = String(args.mode);
      if (newMode === "config" || newMode === "builder" || newMode === "dataset") {
        setMode(newMode);
        return { ok: true, result: { mode: newMode } };
      }
      return { ok: false, error: `Modo desconocido: ${newMode}` };
    },
  });

  useAssistantContext("backtester.page", () => {
    const metrics: any = result?.aggregate_metrics ?? null;
    return {
      mode,
      isRunning: loading,
      lastError: error,
      results: result
        ? {
            days: result.day_results?.length ?? 0,
            aggregate_metrics: metrics,
          }
        : null,
    };
  });
  */

  const [drawerExpanded, setDrawerExpanded] = useState(false);
  const [strategySessionKey, setStrategySessionKey] = useState<string>("init");

  useEffect(() => {
    if (mode !== 'builder' && mode !== 'wizard' && mode !== 'dataset') {
      setDrawerExpanded(false);
    }
  }, [mode]);

  const [datasetRefresh, setDatasetRefresh] = useState(0);
  const [pendingDatasetSelect, setPendingDatasetSelect] = useState<string | undefined>(undefined);
  const [isSavingDataset, setIsSavingDataset] = useState(false);
  const [draftStrategy, setDraftStrategy] = useState<Draft | null>(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showRewriteModal, setShowRewriteModal] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [builderDraft, setBuilderDraft] = useState<Draft | null>(null);
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
        id: draftStrategy.id,
        name: draftStrategy.name,
        bias: draftStrategy.bias,
        apply_day: draftStrategy.apply_day,
        postgap_preconditions: draftStrategy.postgap_preconditions,
        entry_logic: draftStrategy.entry_logic,
        exit_logic: draftStrategy.exit_logic,
        risk_management: draftStrategy.risk_management,
        dataset_id: draftStrategy.dataset_id,
        universe_filters: (draftStrategy as any).universe_filters,
        is_wizard: draftStrategy.is_wizard,
        description: (draftStrategy as any).description || activeStrategy?.description || "",
      });

      const isExisting = draftStrategy.id && !draftStrategy.id.startsWith("draft") && !draftStrategy.id.startsWith("wizard_draft");
      if (isExisting) {
        setShowRewriteModal(true);
      } else {
        setSaveName(draftStrategy.name);
        setShowSaveModal(true);
      }
    } else {
      alert("No hay ninguna estrategia modificada activa para guardar.");
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
    
    setActiveSessions((prev) => {
      const next = params.market_sessions || ["rth"];
      if (prev.length === next.length && prev.every((v, i) => v === next[i])) {
        return prev;
      }
      return next;
    });
    
    setActiveCustomStartTime((prev) => {
      const next = params.custom_start_time || "09:30";
      return prev === next ? prev : next;
    });
    
    setActiveCustomEndTime((prev) => {
      const next = params.custom_end_time || "16:00";
      return prev === next ? prev : next;
    });
  }, []);

  const handleDraftChange = useCallback((draft: any) => {
    setBuilderDraft(draft);
  }, []);

  const [dayCandles, setDayCandles] = useState<DayCandles | null>(null);
  const [activeStrategy, setActiveStrategy] = useState<any | null>(null);
  const [multiDayCandles, setMultiDayCandles] = useState<MultiDayCandles | null>(null);
  const [candlesLoading, setCandlesLoading] = useState(false);

  const computedActiveStrategy = useMemo(() => {
    if (mode === "builder" || mode === "wizard") {
      return builderDraft;
    }
    return activeStrategy;
  }, [mode, builderDraft, activeStrategy]);


  const handleRunWithDraft = async (draft: Draft) => {
    const p = panelParamsRef.current;
    
    let activeDatasetId = (draft as any).dataset_id;
    
    // Auto-create dataset if custom universe filters are specified but no dataset_id exists
    if (!activeDatasetId && (draft as any).universe_filters) {
      setLoading(true);
      setError(null);
      try {
        const uniqueName = `Universo_${draft.name.replace(/\s+/g, "_")}_${Date.now().toString().slice(-4)}`;
        const newQuery = await createQuery({ name: uniqueName, filters: (draft as any).universe_filters });
        activeDatasetId = newQuery.id;
        (draft as any).dataset_id = newQuery.id; // update draft in place
        
        // Refresh datasets list in backtest panel so it exists in lists
        setDatasetRefresh((prev) => prev + 1);
        setPendingDatasetSelect(newQuery.id);
      } catch (err: any) {
        setError(err.message || "Error al crear el universo para la estrategia.");
        setLoading(false);
        return;
      }
    }

    if (!activeDatasetId) {
      // Fallback to panel params dataset_id if not present in draft
      activeDatasetId = p?.dataset_id;
    }

    if (!activeDatasetId) {
      setError("Configura el universo de la estrategia antes de ejecutar el backtest.");
      return;
    }

    try {
      const { fetchPrecacheStatus } = await import("@/lib/api_backtester");
      const statusData = await fetchPrecacheStatus(activeDatasetId);
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
        const prog = await fetchBacktestProgress(activeDatasetId);
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
    setActiveStrategy({
      id: draft.id,
      name: draft.name,
      description: "",
      definition: {
        apply_day: draft.apply_day,
        bias: draft.bias,
        postgap_preconditions: draft.postgap_preconditions,
        entry_logic: draft.entry_logic,
        exit_logic: draft.exit_logic,
        risk_management: draft.risk_management,
        market_sessions: draft.market_sessions,
        custom_start_time: draft.custom_start_time,
        custom_end_time: draft.custom_end_time,
        dataset_id: activeDatasetId,
        universe_filters: (draft as any).universe_filters,
      }
    });

    initCashRef.current = p?.init_cash ?? 10000;
    riskRRef.current = p?.risk_r ?? 100;
    datasetIdRef.current = activeDatasetId;
    strategyIdRef.current = draft.id;
    backtestParamsRef.current = {
      init_cash: p?.init_cash ?? 10000,
      risk_r: p?.risk_r ?? 100,
      fees: p?.fees ?? 0.01,
      slippage: p?.slippage ?? 0.01,
      start_date: p?.start_date,
      end_date: p?.end_date,
      market_sessions: draft.market_sessions || p?.market_sessions,
      custom_start_time: (draft.market_sessions || p?.market_sessions || []).includes("custom") ? (draft.custom_start_time || p?.custom_start_time) : undefined,
      custom_end_time: (draft.market_sessions || p?.market_sessions || []).includes("custom") ? (draft.custom_end_time || p?.custom_end_time) : undefined,
      monthly_expenses: p?.monthly_expenses,
      locates_cost: p?.locates_cost,
      is_percent: p?.is_percent,
      risk_type: p?.risk_type,
      fixed_ratio_delta: p?.fixed_ratio_delta,
      size_by_sl: draft.risk_management.size_by_sl || p?.size_by_sl || false,
      fee_type: p?.fee_type,
      look_ahead_prevention: p?.look_ahead_prevention ?? true,
    };

    try {
      const data = await runBacktestWithDefinition({
        dataset_id: activeDatasetId,
        strategy_definition: {
          name: draft.name,
          bias: draft.bias,
          apply_day: draft.apply_day,
          postgap_preconditions: draft.postgap_preconditions,
          entry_logic: draft.entry_logic,
          exit_logic: draft.exit_logic,
          risk_management: draft.risk_management,
          market_sessions: draft.market_sessions,
          custom_start_time: draft.custom_start_time,
          custom_end_time: draft.custom_end_time,
          dataset_id: activeDatasetId,
          universe_filters: (draft as any).universe_filters,
        },
        init_cash: p?.init_cash ?? 10000,
        risk_r: p?.risk_r ?? 100,
        risk_type: p?.risk_type ?? "FIXED",
        fixed_ratio_delta: p?.fixed_ratio_delta,
        size_by_sl: draft.risk_management.size_by_sl || false,
        fees: p?.fees ?? 0.01,
        fee_type: p?.fee_type ?? "PERCENT",
        slippage: p?.slippage ?? 0.01,
        start_date: p?.start_date || undefined,
        end_date: p?.end_date || undefined,
        market_sessions: draft.market_sessions || p?.market_sessions,
        custom_start_time: (draft.market_sessions || p?.market_sessions || []).includes("custom") ? (draft.custom_start_time || p?.custom_start_time || undefined) : undefined,
        custom_end_time: (draft.market_sessions || p?.market_sessions || []).includes("custom") ? (draft.custom_end_time || p?.custom_end_time || undefined) : undefined,
        locates_cost: p?.locates_cost,
        monthly_expenses: p?.monthly_expenses,
        look_ahead_prevention: p?.look_ahead_prevention ?? true,
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
    } catch (err: unknown) {
      let msg = "Error desconocido";
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        msg = axiosErr.response?.data?.detail || "Error del servidor";
      } else if (err && typeof err === "object" && "message" in err) {
        const errMsg = (err as { message: string }).message;
        if (errMsg.includes("timeout")) {
          msg = "Timeout: el backtest tardó demasiado. Prueba con un dataset más pequeño.";
        } else if (errMsg.includes("Network")) {
          msg = "Error de red: verifica que el backend esté corriendo.";
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
    is_percent?: number;
  }) => {
    if (params.strategy_id === "draft" && activeStrategy) {
      const draft = {
        name: activeStrategy.name,
        bias: activeStrategy.definition?.bias || activeStrategy.bias,
        apply_day: activeStrategy.definition?.apply_day || activeStrategy.apply_day,
        postgap_preconditions: activeStrategy.definition?.postgap_preconditions || activeStrategy.postgap_preconditions,
        entry_logic: activeStrategy.definition?.entry_logic || activeStrategy.entry_logic,
        exit_logic: activeStrategy.definition?.exit_logic || activeStrategy.exit_logic,
        risk_management: activeStrategy.definition?.risk_management || activeStrategy.risk_management,
      } as any;
      await handleRunWithDraft(draft);
      return;
    }

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
      custom_start_time: params.custom_start_time,
      custom_end_time: params.custom_end_time,
      monthly_expenses: params.monthly_expenses,
      locates_cost: (params as any).locates_cost,
      is_percent: params.is_percent,
      risk_type: (params as any).risk_type,
      fixed_ratio_delta: (params as any).fixed_ratio_delta,
      size_by_sl: (params as any).size_by_sl,
      fee_type: (params as any).fee_type,
      look_ahead_prevention: (params as any).look_ahead_prevention,
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

        const swingActive = activeStrategy?.definition?.risk_management?.swing_option?.active || activeStrategy?.risk_management?.swing_option?.active || false;
        const swingTargetDay = activeStrategy?.definition?.risk_management?.swing_option?.target_day || activeStrategy?.risk_management?.swing_option?.target_day || "gap_1_day";

        const data = await fetchMultiDayCandles(
          datasetIdRef.current,
          day.ticker,
          day.date,
          applyDay,
          swingActive,
          swingTargetDay
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

  // Load results state from sessionStorage on mount
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem("backtester_results_state");
      if (stored) {
        const saved = JSON.parse(stored);
        if (saved.result) setResult(saved.result);
        if (saved.activeStrategy) setActiveStrategy(saved.activeStrategy);
        if (saved.selectedDay !== undefined) setSelectedDay(saved.selectedDay);
        if (saved.mode) setMode(saved.mode);
        if (saved.builderDraft) setBuilderDraft(saved.builderDraft);
      }
    } catch (e) {
      console.error("Error loading backtester_results_state:", e);
    }
  }, []);

  // Save results state to sessionStorage on change
  useEffect(() => {
    const resultsState = {
      result,
      activeStrategy,
      selectedDay,
      mode,
      builderDraft
    };
    try {
      sessionStorage.setItem("backtester_results_state", JSON.stringify(resultsState));
    } catch (e) {
      console.warn("Storage quota exceeded for backtester_results_state. Trying lighter state...");
      try {
        // Fallback 1: Save result metadata and summary stats, but exclude heavy list datasets
        const lightState = {
          result: result ? { ...result, trades: [], day_results: [] } : null,
          activeStrategy,
          selectedDay,
          mode,
          builderDraft
        };
        sessionStorage.setItem("backtester_results_state", JSON.stringify(lightState));
      } catch (innerEx) {
        // Fallback 2: Save only active builder configuration, mode, and builder draft
        try {
          const configOnlyState = {
            result: null,
            activeStrategy,
            selectedDay,
            mode,
            builderDraft
          };
          sessionStorage.setItem("backtester_results_state", JSON.stringify(configOnlyState));
        } catch (configEx) {
          console.warn("Could not save backtester results state to sessionStorage:", configEx);
        }
      }
    }
  }, [result, activeStrategy, selectedDay, mode, builderDraft]);

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
              onNewStrategy={() => setMode((prev) => {
                const isOpening = !(prev === 'builder' || prev === 'builder_choice' || prev === 'wizard');
                if (isOpening) {
                  return 'builder_choice';
                }
                return 'config';
              })}
              onNewDataset={() => setMode((prev) => (prev === 'dataset' ? 'config' : 'dataset'))}
              onParamsChange={handlePanelParamsChange}
              refreshTrigger={strategiesRefresh}
              datasetRefreshTrigger={datasetRefresh}
              pendingDatasetSelect={pendingDatasetSelect}
              onClearPendingDataset={() => setPendingDatasetSelect(undefined)}
              loading={loading}
              isDarkMode={isDarkMode}
              activeStrategy={computedActiveStrategy}
              onConfigureStrategy={async (strategyId) => {
                if (strategyId === "draft") {
                  setMode('builder');
                } else if (strategyId === "wizard_draft") {
                  setMode('wizard');
                } else if (strategyId) {
                  try {
                    const strategyData = await getStrategy(strategyId);
                    setActiveStrategy(strategyData);
                    
                    const def = typeof strategyData.definition === 'string' 
                      ? JSON.parse(strategyData.definition) 
                      : strategyData.definition || strategyData;
                    
                    setBuilderDraft({
                      id: strategyData.id,
                      name: strategyData.name || "",
                      bias: def.bias || "long",
                      apply_day: def.apply_day || "gap_day",
                      postgap_preconditions: def.postgap_preconditions || [],
                      entry_logic: def.entry_logic || {
                        root_condition: { type: "group", operator: "AND", conditions: [] },
                        entry_time_windows: []
                      },
                      exit_logic: def.exit_logic || {
                        root_condition: { type: "group", operator: "AND", conditions: [] }
                      },
                      risk_management: def.risk_management || {
                        size_by_sl: false,
                        use_take_profit: false,
                        take_profit_mode: "Fixed",
                        fixed_take_profit_pct: 1.0,
                        partial_take_profits: [],
                        use_stop_loss: true,
                        stop_loss_mode: "Fixed",
                        fixed_stop_loss_pct: 1.0,
                        trail_stop_loss_pct: 1.0,
                        use_time_exit: false,
                        time_exit_session: "rth",
                        time_exit_value: "15:58",
                        swing_option: { active: false, target_day: "gap_1_day" }
                      },
                      dataset_id: def.dataset_id,
                      universe_filters: def.universe_filters,
                      is_wizard: def.is_wizard || strategyData.is_wizard || false,
                    } as any);
                    
                    setMode('builder_choice');
                  } catch (err) {
                    alert("Error al cargar la estrategia para configurar.");
                  }
                }
              }}
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
                Selecciona una estrategia<br />para ejecutar el backtest
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
                      {backtestProgress.current} / {backtestProgress.total} pares procesados
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
                        disabled={!draftStrategy}
                        onMouseEnter={() => { if (draftStrategy) setHoveredSaveBtn(true); }}
                        onMouseLeave={() => { setHoveredSaveBtn(false); setActiveSaveBtn(false); }}
                        onMouseDown={() => { if (draftStrategy) setActiveSaveBtn(true); }}
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
                          cursor: draftStrategy ? 'pointer' : 'not-allowed',
                          opacity: draftStrategy ? 1 : 0.4,
                          boxShadow: (hoveredSaveBtn && draftStrategy) ? '0 0 14px rgba(216, 122, 61, 0.5)' : 'none',
                          transform: (activeSaveBtn && draftStrategy) ? 'scale(0.98)' : (hoveredSaveBtn && draftStrategy) ? 'scale(1.015)' : 'scale(1)',
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
                  <div style={{ height: 288, width: '100%', marginTop: 'auto', marginBottom: 0, flexShrink: 0 }}>
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
                        is_wizard: strategyToSave.is_wizard ?? strategyToSave.id?.startsWith("wizard_draft") ?? false,
                        apply_day: strategyToSave.apply_day,
                        postgap_preconditions: strategyToSave.postgap_preconditions,
                        universe_filters: strategyToSave.universe_filters,
                        dataset_id: strategyToSave.dataset_id,
                      } as any);
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

          {/* Modal — reescribir estrategia existente */}
          {showRewriteModal && (
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
                width: 360,
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ec-text-high)', fontFamily: 'var(--color-ec-serif)' }}>
                  ¿Desea reescribir la estrategia?
                </div>
                <div style={{ fontSize: 12, color: 'var(--color-ec-text-secondary)', fontFamily: 'var(--color-ec-sans)', lineHeight: 1.5 }}>
                  Se actualizará la configuración de la estrategia <strong>{strategyToSave?.name}</strong> con los cambios actuales.
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => setShowRewriteModal(false)}
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
                    No
                  </button>
                  <button
                    onClick={async () => {
                      if (!strategyToSave || !strategyToSave.id) return;
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
                      
                      try {
                        const updated = await updateStrategy(strategyToSave.id, {
                          name: strategyToSave.name,
                          description,
                          bias: strategyToSave.bias,
                          entry_logic: strategyToSave.entry_logic,
                          exit_logic: strategyToSave.exit_logic,
                          risk_management: strategyToSave.risk_management,
                          is_wizard: strategyToSave.is_wizard ?? strategyToSave.id.startsWith("wizard_draft") ?? false,
                          apply_day: strategyToSave.apply_day,
                          postgap_preconditions: strategyToSave.postgap_preconditions,
                          universe_filters: strategyToSave.universe_filters,
                          dataset_id: strategyToSave.dataset_id,
                        } as any);

                        // Persist backtest results linked to this strategy
                        if (result) {
                          try {
                            await saveBacktest({
                              strategy_ids: [strategyToSave.id],
                              results_json: {
                                ...result,
                                backtest_params: backtestParamsRef.current
                              } as unknown as Record<string, unknown>,
                            });
                          } catch (e) {
                            console.warn("No se pudieron guardar los resultados del backtest:", e);
                          }
                        }

                        // Update the active strategy in the state with the returned/updated strategy
                        setActiveStrategy(updated);
                        
                        setStrategiesRefresh((prev) => prev + 1);
                        setShowRewriteModal(false);
                        setDraftStrategy(null);
                        setStrategyToSave(null);
                      } catch (err: any) {
                        alert(err.message || "Error al actualizar la estrategia.");
                      }
                    }}
                    style={{
                      flex: 2, padding: '7px 0', borderRadius: 5,
                      fontSize: 11, fontWeight: 700, letterSpacing: 1.2,
                      textTransform: 'uppercase', cursor: 'pointer',
                      backgroundColor: 'var(--color-ec-copper)',
                      border: 'none',
                      color: 'var(--color-ec-copper-text)',
                      fontFamily: 'var(--color-ec-sans)',
                    }}
                  >
                    Sí
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>

        {/* Backdrop blur overlay for the main content area */}
        {(mode === 'builder_choice' || mode === 'builder' || mode === 'wizard' || mode === 'dataset') && (
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

        {/* Drawer/Desplegable de la lógica (Strategy Builder / Mode Selector) */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 280,
          bottom: 0,
          width: (mode === 'builder' || mode === 'wizard') && drawerExpanded ? 680 : 550,
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          borderRight: '0.5px solid var(--color-ec-border)',
          zIndex: 40,
          transform: (mode === 'builder_choice' || mode === 'builder' || mode === 'wizard') ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 300ms cubic-bezier(0.4, 0, 0.2, 1), width 300ms cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: '10px 0 30px rgba(0, 0, 0, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <div
            key={strategySessionKey}
            style={{
              display: 'flex',
              width: '200%',
              height: '100%',
              transform: (mode === 'builder' || mode === 'wizard') ? 'translateX(-50%)' : 'translateX(0)',
              transition: 'transform 350ms cubic-bezier(0.16, 1, 0.3, 1)',
            }}
          >
            {/* Panel 1: Mode Selector */}
            <div style={{
              width: '50%',
              height: '100%',
              flexShrink: 0,
              opacity: mode === 'builder_choice' ? 1 : 0,
              transition: 'opacity 280ms ease-out',
            }}>
              <StrategyModeSelector
                onBack={() => setMode('config')}
                onSelectFree={() => setMode('builder')}
                onSelectWizard={() => setMode('wizard')}
              />
            </div>
            {/* Panel 2: Strategy Builder OR Wizard */}
            <div style={{
              width: '50%',
              height: '100%',
              flexShrink: 0,
              opacity: (mode === 'builder' || mode === 'wizard') ? 1 : 0,
              transition: 'opacity 280ms ease-out',
            }}>
              {mode === 'wizard' && (
                <div style={{ height: '100%' }}>
                  <WizardStrategyBuilder
                    onBack={() => setMode('builder_choice')}
                    onTest={async (draft) => {
                      setDraftStrategy(draft as Draft);
                      setMode('config');
                      await handleRunWithDraft(draft as Draft);
                    }}
                    onDraftChange={handleDraftChange}
                    marketSessions={activeSessions}
                    customStartTime={activeCustomStartTime}
                    customEndTime={activeCustomEndTime}
                    initialStrategy={builderDraft || activeStrategy || undefined}
                    onExpandedChange={setDrawerExpanded}
                  />
                </div>
              )}
              {mode === 'builder' && (
                <div style={{ height: '100%' }}>
                  <InlineStrategyBuilder
                    onBack={() => setMode('builder_choice')}
                    onTest={async (draft) => {
                      setDraftStrategy(draft);
                      setMode('config');
                      await handleRunWithDraft(draft);
                    }}
                    marketSessions={activeSessions}
                    customStartTime={activeCustomStartTime}
                    customEndTime={activeCustomEndTime}
                    onDraftChange={handleDraftChange}
                    initialStrategy={builderDraft || activeStrategy || undefined}
                    onExpandedChange={setDrawerExpanded}
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Drawer/Desplegable de la creación de Dataset (InlineDatasetBuilder) */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 280,
          bottom: 0,
          width: mode === 'dataset' && drawerExpanded ? 680 : 550,
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          borderRight: '0.5px solid var(--color-ec-border)',
          zIndex: 40,
          transform: mode === 'dataset' ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 300ms cubic-bezier(0.4, 0, 0.2, 1), width 300ms cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: '10px 0 30px rgba(0, 0, 0, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <InlineDatasetBuilder
            onBack={() => setMode('config')}
            isSaving={isSavingDataset}
            onExpandedChange={setDrawerExpanded}
            onSave={async (name, filters) => {
              if (isSavingDataset) return;
              setIsSavingDataset(true);
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
              } finally {
                setIsSavingDataset(false);
              }
            }}
          />
        </div>

      </div>
    </div>
  );
}
