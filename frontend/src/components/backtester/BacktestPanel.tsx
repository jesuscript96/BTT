"use client";

import { useEffect, useState } from "react";
import type { Dataset, Strategy, PrecacheStatus } from "@/lib/api_backtester";
import { fetchDatasets, fetchStrategies, fetchPrecacheStatus } from "@/lib/api_backtester";
import { INDICATOR_LABELS, COMPARATOR_LABELS } from "@/components/strategy-builder/ConditionBuilder";

export interface BacktestPanelParams {
  dataset_id: string;
  init_cash: number;
  risk_r: number;
  risk_type: string;
  fixed_ratio_delta: number;
  size_by_sl: boolean;
  fees: number;
  fee_type: string;
  slippage: number;
  start_date: string;
  end_date: string;
  market_sessions: string[];
  custom_start_time: string;
  custom_end_time: string;
  locates_cost: number;
  monthly_expenses: number;
  look_ahead_prevention: boolean;
  is_percent: number;
}

interface BacktestPanelProps {
  refreshTrigger?: number;
  onNewStrategy: () => void;
  onRun: (params: {
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
    locates_cost?: number;
    look_ahead_prevention?: boolean;
    risk_type?: string;
    size_by_sl?: boolean;
    fee_type?: string;
    monthly_expenses?: number;
    fixed_ratio_delta?: number;
  }) => void;
  onParamsChange?: (params: BacktestPanelParams) => void;
  loading: boolean;
  isDarkMode?: boolean;
  onNewDataset: () => void;
  datasetRefreshTrigger?: number;
  pendingDatasetSelect?: string;
  onClearPendingDataset?: () => void;
}

function formatConditionGroup(group: any): string {
  if (!group || !group.conditions || group.conditions.length === 0) return "";
  
  const parts = group.conditions.map((c: any) => {
    if (!c) return "";
    if (c.type === 'group') {
      const subText = formatConditionGroup(c);
      return subText ? `(${subText})` : "";
    } else {
      const tfStr = c.timeframe ? `[${c.timeframe}] ` : '';
      if (c.type === 'indicator_comparison') {
        const sourceName = c.source?.name || "";
        const sourceStr = `${INDICATOR_LABELS[sourceName] || sourceName}${c.source?.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator || "";
        let targetStr = '';
        if (typeof c.target === 'number') {
          targetStr = String(c.target);
        } else if (c.target && typeof c.target === 'object') {
          const targetName = c.target.name || "";
          targetStr = `${INDICATOR_LABELS[targetName] || targetName}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        return `${tfStr}${sourceStr} ${compStr} ${targetStr}`.trim();
      } else if (c.type === 'price_level_distance') {
        const sourceName = c.source?.name || "";
        const sourceStr = `${INDICATOR_LABELS[sourceName] || sourceName}${c.source?.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelName = c.level?.name || "";
        const levelStr = `${INDICATOR_LABELS[levelName] || levelName}${c.level?.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        return `${tfStr}Dist(${sourceStr}, ${levelStr}) ${compStr} ${c.value_pct || 0}%`.trim();
      }
      return "";
    }
  }).filter(Boolean);

  if (parts.length === 0) return "";
  return parts.join(` ${group.operator || 'AND'} `);
}

function formatPreconditions(preconditions: any[]): string {
  if (!preconditions || preconditions.length === 0) return "";
  return preconditions.map((cond: any) => {
    const dayLabel = cond.day === 'gap_day' ? 'Gap Day' : cond.day === 'gap_1_day' ? 'Gap+1 Day' : 'Gap+2 Day';
    let metricLabel = 'Close';
    let valLabel = '';
    
    if (cond.metric === 'volume') {
      metricLabel = 'Volume';
      valLabel = `${cond.operator} ${(cond.value ?? 0).toLocaleString()}`;
    } else if (cond.metric === 'close_vs_open') {
      valLabel = `${cond.operator} Open`;
    } else if (cond.metric === 'close_vs_high_low') {
      valLabel = cond.operator === '> High' ? '> Prev High' : '< Prev Low';
    } else if (cond.metric === 'close_vs_pm_high') {
      valLabel = `${cond.operator} PM High`;
    } else if (cond.metric === 'close_vs_vwap') {
      valLabel = `${cond.operator} VWAP`;
    } else if (cond.metric === 'close_vs_sma') {
      valLabel = `${cond.operator} SMA ${cond.sma_period}`;
    } else if (cond.metric === 'candle_range_pct') {
      metricLabel = 'Candle Range %';
      valLabel = `${cond.operator} ${cond.value}%`;
    } else {
      valLabel = `${cond.operator || ""} ${cond.value !== undefined ? cond.value : ""}`.trim();
    }
    
    return `${dayLabel} (${metricLabel} ${valLabel})`;
  }).join(", ");
}

export default function BacktestPanel({
  refreshTrigger,
  onNewStrategy,
  onNewDataset,
  datasetRefreshTrigger,
  pendingDatasetSelect,
  onClearPendingDataset,
  onRun,
  onParamsChange,
  loading,
  isDarkMode = false
}: BacktestPanelProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const [initCash, setInitCash] = useState(10000);
  const [riskR, setRiskR] = useState(100);
  const [fees, setFees] = useState(0.01);
  const [slippage, setSlippage] = useState(0.01);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [marketSessions, setMarketSessions] = useState<string[]>(["rth"]);
  const [customStartTime, setCustomStartTime] = useState("09:30");
  const [customEndTime, setCustomEndTime] = useState("16:00");
  const [locatesCost, setLocatesCost] = useState(0);
  const [useLocates, setUseLocates] = useState(false);
  const [useMonthlyExpenses, setUseMonthlyExpenses] = useState(false);
  const [monthlyExpenses, setMonthlyExpenses] = useState(0);
  const lookAheadPrevention = true;
  const [riskType, setRiskType] = useState<"FIXED" | "PERCENT" | "FIXED_RATIO">("FIXED");
  const [fixedRatioDelta, setFixedRatioDelta] = useState(500);
  const [sizeBySl, setSizeBySl] = useState(false);
  const [feeType, setFeeType] = useState<"PERCENT" | "FLAT">("PERCENT");
  const [isPercent, setIsPercent] = useState(100);
  const [loadingData, setLoadingData] = useState(true);
  const [hoveredBtn, setHoveredBtn] = useState<string | null>(null);
  const [activeBtn, setActiveBtn] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [precacheStatus, setPrecacheStatus] = useState<PrecacheStatus | null>(null);
  const [visualPercent, setVisualPercent] = useState<number>(0);

  const loadData = async () => {
    setLoadingData(true);
    setLoadError(false);
    let failed = false;

    // Check if there is prefill in sessionStorage
    let prefill: { strategy_id?: string; dataset_id?: string } | null = null;
    try {
      const stored = sessionStorage.getItem('backtester_prefill');
      if (stored) {
        prefill = JSON.parse(stored);
        sessionStorage.removeItem('backtester_prefill'); // Clear it so it doesn't stick around
      }
    } catch (e) {
      console.error("Error reading backtester_prefill:", e);
    }

    try {
      const d = await fetchDatasets();
      setDatasets(d);
      if (d.length > 0) {
        const hasPrefillDataset = prefill?.dataset_id && d.some(ds => ds.id === prefill.dataset_id);
        const selectedId = hasPrefillDataset ? prefill!.dataset_id! : d[0].id;
        setSelectedDataset(selectedId);
        const selectedDs = d.find(ds => ds.id === selectedId);
        if (selectedDs?.min_date) setStartDate(selectedDs.min_date);
        if (selectedDs?.max_date) setEndDate(selectedDs.max_date);
      }
    } catch (e) {
      console.error("Error loading datasets:", e);
      failed = true;
    }
    try {
      const s = await fetchStrategies();
      setStrategies(s);
      if (s.length > 0) {
        const hasPrefillStrategy = prefill?.strategy_id && s.some(st => st.id === prefill.strategy_id);
        setSelectedStrategy(hasPrefillStrategy ? prefill!.strategy_id! : s[0].id);
      }
    } catch (e) {
      console.error("Error loading strategies:", e);
      failed = true;
    }
    setLoadError(failed);
    setLoadingData(false);
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const ds = datasets.find(d => d.id === selectedDataset);
    if (ds) {
      if (ds.min_date) setStartDate(ds.min_date);
      if (ds.max_date) setEndDate(ds.max_date);
    }
  }, [selectedDataset, datasets]);

  useEffect(() => {
    if (!refreshTrigger) return;
    fetchStrategies()
      .then((s) => setStrategies(s))
      .catch((e) => console.error("Error refreshing strategies:", e));
  }, [refreshTrigger]);

  useEffect(() => {
    if (!datasetRefreshTrigger) return;
    fetchDatasets()
      .then((d) => {
        setDatasets(d);
      })
      .catch((e) => console.error("Error refreshing datasets:", e));
  }, [datasetRefreshTrigger]);

  useEffect(() => {
    if (pendingDatasetSelect && datasets.some((d) => d.id === pendingDatasetSelect)) {
      setSelectedDataset(pendingDatasetSelect);
      onClearPendingDataset?.();
    }
  }, [datasets, pendingDatasetSelect, onClearPendingDataset]);

  useEffect(() => {
    if (!selectedDataset) {
      setPrecacheStatus(null);
      setVisualPercent(0);
      return;
    }

    let isMounted = true;
    let timer: NodeJS.Timeout | null = null;
    let progressTimer: NodeJS.Timeout | null = null;

    setVisualPercent(0);

    const checkStatus = async () => {
      try {
        const statusData = await fetchPrecacheStatus(selectedDataset);
        if (!isMounted) return;

        setPrecacheStatus(statusData);

        if (statusData.status === "running") {
          timer = setTimeout(checkStatus, 1500);
          if (statusData.percent > 0) {
            setVisualPercent((prev) => Math.max(prev, statusData.percent));
          }
        } else if (statusData.status === "completed") {
          setVisualPercent(100);
        }
      } catch (err) {
        console.error("Error fetching precache status:", err);
        if (isMounted) {
          timer = setTimeout(checkStatus, 3000);
        }
      }
    };

    const updateProgress = () => {
      setVisualPercent((prev) => {
        if (prev >= 95) return prev;
        let increment = 1.5;
        if (prev >= 80) increment = 0.2;
        else if (prev >= 50) increment = 0.5;
        return Math.min(95, prev + increment);
      });
      if (isMounted) {
        progressTimer = setTimeout(updateProgress, 1000);
      }
    };

    checkStatus();
    updateProgress();

    return () => {
      isMounted = false;
      if (timer) clearTimeout(timer);
      if (progressTimer) clearTimeout(progressTimer);
    };
  }, [selectedDataset]);

  useEffect(() => {
    onParamsChange?.({
      dataset_id: selectedDataset,
      init_cash: initCash,
      risk_r: riskR,
      risk_type: riskType,
      fixed_ratio_delta: fixedRatioDelta,
      size_by_sl: sizeBySl,
      fees: feeType === "PERCENT" ? fees / 100 : fees,
      fee_type: feeType,
      slippage: slippage / 100,
      start_date: startDate,
      end_date: endDate,
      market_sessions: marketSessions,
      custom_start_time: customStartTime,
      custom_end_time: customEndTime,
      locates_cost: useLocates ? locatesCost : 0,
      monthly_expenses: useMonthlyExpenses ? monthlyExpenses : 0,
      look_ahead_prevention: lookAheadPrevention,
      is_percent: isPercent,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedDataset, initCash, riskR, riskType, fixedRatioDelta, sizeBySl,
    fees, feeType, slippage, startDate, endDate, marketSessions,
    customStartTime, customEndTime, useLocates, locatesCost,
    useMonthlyExpenses, monthlyExpenses, lookAheadPrevention, isPercent,
  ]);

  const handleRun = () => {
    if (!selectedDataset || !selectedStrategy) return;
    if (isSelectedStratRiskInvalid) {
      alert("La suma del capital de los parciales de Take Profit debe ser exactamente 100%.");
      return;
    }
    if (precacheStatus?.status === "running") {
      alert(`Espera a que se cargue el dataset (progreso: ${precacheStatus.percent}%)`);
      return;
    }
    onRun({
      dataset_id: selectedDataset,
      strategy_id: selectedStrategy,
      init_cash: initCash,
      risk_r: riskR,
      fees: feeType === "PERCENT" ? fees / 100 : fees,
      fee_type: feeType,
      slippage: slippage / 100,
      start_date: startDate,
      end_date: endDate,
      market_sessions: marketSessions,
      custom_start_time: marketSessions.includes("custom") ? customStartTime : undefined,
      custom_end_time: marketSessions.includes("custom") ? customEndTime : undefined,
      locates_cost: useLocates ? locatesCost : 0,
      monthly_expenses: useMonthlyExpenses ? monthlyExpenses : 0,
      look_ahead_prevention: lookAheadPrevention,
      risk_type: riskType,
      fixed_ratio_delta: riskType === "FIXED_RATIO" ? fixedRatioDelta : 500,
      size_by_sl: sizeBySl,
    });
  };

  const toggleSession = (session: string) => {
    setMarketSessions(prev =>
      prev.includes(session)
        ? prev.filter(s => s !== session)
        : [...prev, session]
    );
  };

  const selectedStrat = strategies.find((s) => s.id === selectedStrategy);
  const selectedDs = datasets.find((d) => d.id === selectedDataset);

  const stratDef = selectedStrat?.definition as any;
  const riskMgmt = stratDef?.risk_management;
  const isSelectedStratPartialTP = riskMgmt?.use_take_profit !== false && riskMgmt?.take_profit_mode === "Partial";
  const selectedStratPartialCapital = (riskMgmt?.partial_take_profits || []).reduce((sum: number, p: any) => sum + (p.capital_pct || 0), 0);
  const isSelectedStratRiskInvalid = isSelectedStratPartialTP && Math.abs(selectedStratPartialCapital - 100) > 0.01;

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
    }}>
      {/* CONFIGURACIÓN */}
      <h2 style={{
        fontFamily: 'var(--color-ec-sans)',
        fontSize: 14,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.12em',
        color: 'var(--color-ec-text-high)',
        marginBottom: 4,
      }}>
        CONFIGURACIÓN
      </h2>

      {loadError && (
        <div className="flex items-center gap-2" style={{
          backgroundColor: 'color-mix(in srgb, var(--color-ec-loss) 10%, transparent)',
          border: '0.5px solid color-mix(in srgb, var(--color-ec-loss) 30%, transparent)',
          borderRadius: 5,
          padding: '8px 12px',
          marginBottom: 4,
        }}>
          <span style={{
            fontFamily: 'var(--color-ec-sans)',
            fontSize: 11,
            color: 'var(--color-ec-loss)',
            flex: 1,
          }}>Error al conectar con el servidor</span>
          <button
            onClick={loadData}
            className="text-xs font-medium underline hover:no-underline cursor-pointer"
            style={{ color: 'var(--color-ec-loss)' }}
          >
            Reintentar
          </button>
        </div>
      )}

      <div className="space-y-3">
        <div>
          <label style={{
            display: 'block',
            fontFamily: 'var(--color-ec-sans)',
            fontSize: 9,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--color-ec-text-muted)',
            marginBottom: 5,
          }}>
            Cargar Dataset Guardado
          </label>
          {loadingData ? (
            <div className="h-9 bg-gray-100 rounded animate-pulse" />
          ) : (
            <select
              value={selectedDataset}
              onChange={(e) => setSelectedDataset(e.target.value)}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
                cursor: 'pointer',
              }}
            >
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} {d.pair_count > 0 ? `(${d.pair_count} pares)` : ""}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={onNewDataset}
            onMouseEnter={() => setHoveredBtn("dataset")}
            onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
            onMouseDown={() => setActiveBtn("dataset")}
            onMouseUp={() => setActiveBtn(null)}
            style={{
              width: '100%',
              padding: '8px 0',
              borderRadius: 5,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '1px',
              textTransform: 'uppercase',
              cursor: 'pointer',
              border: hoveredBtn === "dataset" ? '0.5px solid transparent' : '0.5px solid var(--color-ec-copper)',
              backgroundColor: hoveredBtn === "dataset" ? 'var(--color-ec-copper)' : 'transparent',
              color: hoveredBtn === "dataset" ? 'var(--color-ec-copper-text)' : 'var(--color-ec-copper)',
              fontFamily: 'var(--color-ec-sans)',
              marginTop: 6,
              marginBottom: 2,
              boxShadow: hoveredBtn === "dataset" ? '0 0 12px rgba(216, 122, 61, 0.35)' : 'none',
              transform: activeBtn === "dataset" ? 'scale(0.98)' : hoveredBtn === "dataset" ? 'scale(1.015)' : 'scale(1)',
              transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          >
            + NUEVO DATASET
          </button>
          {precacheStatus && precacheStatus.status === "running" && (
            <div style={{
              marginTop: 8,
              padding: '8px 10px',
              backgroundColor: 'var(--color-ec-bg-elevated)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 5,
              display: 'flex',
              flexDirection: 'column',
              gap: 5,
            }}>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-copper)',
              }}>
                <span>Descargando Data...</span>
                <span>{Math.round(visualPercent)}%</span>
              </div>
              <div style={{
                height: 4,
                backgroundColor: 'rgba(216, 122, 61, 0.15)',
                borderRadius: 2,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${visualPercent}%`,
                  backgroundColor: 'var(--color-ec-copper)',
                  borderRadius: 2,
                  transition: 'width 1000ms linear',
                }} />
              </div>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 8,
                color: 'var(--color-ec-text-muted)',
                marginTop: 2,
                gap: 8,
              }}>
                <span style={{ textAlign: 'left', flex: 1, lineHeight: '1.2' }}>
                  La carga puede tardar unos minutos.
                </span>
                <span style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                  {Math.min(precacheStatus.total, Math.round(precacheStatus.total * (visualPercent / 100)))} / {precacheStatus.total} pares
                </span>
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
          <label style={{
            display: 'block',
            fontFamily: 'var(--color-ec-sans)',
            fontSize: 9,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--color-ec-text-muted)',
          }}>
            cargar estrategia guardada
          </label>
          {loadingData ? (
            <div className="h-9 bg-gray-100 rounded animate-pulse" />
          ) : (
            <select
              value={selectedStrategy}
              onChange={(e) => setSelectedStrategy(e.target.value)}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
                cursor: 'pointer',
              }}
            >
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
          {selectedStrat && (() => {
            const cleanDesc = (selectedStrat.description || "")
              .replace(/\[What-if:[\s\S]*\]/g, "")
              .trim();
            const stratDef = selectedStrat.definition as any;
            const entryLogic = stratDef?.entry_logic;
            const exitLogic = stratDef?.exit_logic;
            const bias = stratDef?.bias;
            const applyDay = stratDef?.apply_day;
            const preconds = stratDef?.postgap_preconditions;

            const entryText = entryLogic ? formatConditionGroup(entryLogic.root_condition) : "";
            const exitText = exitLogic ? formatConditionGroup(exitLogic.root_condition) : "";
            const precondsText = formatPreconditions(preconds);

            const displayBias = bias ? bias.toUpperCase() : "";
            const displayDay = applyDay ? (applyDay === 'gap_day' ? 'Gap Day' : applyDay === 'gap_1_day' ? 'Gap+1 Day' : 'Gap+2 Day') : "";

            if (!cleanDesc && !entryText && !exitText && !precondsText && !displayBias) return null;

            return (
              <div style={{
                marginTop: 8,
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}>
                {cleanDesc && (
                  <span style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 11,
                    color: 'var(--color-ec-text-primary)',
                    lineHeight: '1.4',
                    display: 'block',
                  }}>{cleanDesc}</span>
                )}

                {(displayBias || displayDay || precondsText) && (
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10,
                    color: 'var(--color-ec-text-secondary)',
                  }}>
                    {displayBias && (
                      <div>
                        <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>BIAS: </span>
                        <span style={{ 
                          color: displayBias === 'LONG' ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)',
                          fontWeight: 700 
                        }}>{displayBias}</span>
                        {displayDay && ` | Aplicar en ${displayDay}`}
                      </div>
                    )}
                    {entryLogic?.entry_time_windows && entryLogic.entry_time_windows.length > 0 && (
                      <div>
                        <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>HORAS ENTRADA (ET): </span>
                        <span style={{ color: 'var(--color-ec-copper)', fontWeight: 700 }}>
                          {entryLogic.entry_time_windows.map((w: any) => `${w.from_time}-${w.to_time}`).join(", ")}
                        </span>
                      </div>
                    )}
                    {precondsText && (
                      <div>
                        <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>PRECONDICIONES: </span>
                        <span>{precondsText}</span>
                      </div>
                    )}
                  </div>
                )}

                {(entryText || exitText) && (
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10.5,
                  }}>
                    {entryText && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span style={{ fontWeight: 700, color: 'var(--color-ec-profit)', fontSize: 9.5 }}>CONDICIONES ENTRADA:</span>
                        <span style={{ 
                          color: 'var(--color-ec-text-primary)', 
                          fontSize: 11,
                          wordBreak: 'break-word',
                          lineHeight: '1.3',
                        }}>{entryText}</span>
                      </div>
                    )}
                    {exitText && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span style={{ fontWeight: 700, color: 'var(--color-ec-loss)', fontSize: 9.5 }}>CONDICIONES SALIDA:</span>
                        <span style={{ 
                          color: 'var(--color-ec-text-primary)', 
                          fontSize: 11,
                          wordBreak: 'break-word',
                          lineHeight: '1.3',
                        }}>{exitText}</span>
                      </div>
                    )}
                  </div>
                )}

                {isSelectedStratRiskInvalid && (
                  <div style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.08)',
                    border: '0.5px solid var(--color-ec-loss)',
                    borderRadius: 4,
                    padding: '6px 10px',
                    color: 'var(--color-ec-loss)',
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10,
                    fontWeight: 700,
                    lineHeight: '1.4',
                    marginTop: 6,
                  }}>
                    ⚠️ Los parciales de Take Profit suman {selectedStratPartialCapital}%. Debe ser exactamente 100%. Edita la estrategia para corregirlo.
                  </div>
                )}
              </div>
            );
          })()}
          
          <button
            type="button"
            onClick={onNewStrategy}
            onMouseEnter={() => setHoveredBtn("strategy")}
            onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
            onMouseDown={() => setActiveBtn("strategy")}
            onMouseUp={() => setActiveBtn(null)}
            style={{
              width: '100%',
              padding: '8px 0',
              borderRadius: 5,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '1px',
              textTransform: 'uppercase',
              cursor: 'pointer',
              border: hoveredBtn === "strategy" ? '0.5px solid transparent' : '0.5px solid var(--color-ec-copper)',
              backgroundColor: hoveredBtn === "strategy" ? 'var(--color-ec-copper)' : 'transparent',
              color: hoveredBtn === "strategy" ? 'var(--color-ec-copper-text)' : 'var(--color-ec-copper)',
              fontFamily: 'var(--color-ec-sans)',
              marginTop: 4,
              marginBottom: 8,
              boxShadow: hoveredBtn === "strategy" ? '0 0 12px rgba(216, 122, 61, 0.35)' : 'none',
              transform: activeBtn === "strategy" ? 'scale(0.98)' : hoveredBtn === "strategy" ? 'scale(1.015)' : 'scale(1)',
              transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          >
            + Nueva Estrategia
          </button>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
          marginBottom: 8,
        }}>
          <div>
            <label style={{
              display: 'block',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--color-ec-text-muted)',
              marginBottom: 5,
            }}>
              Capital ($)
            </label>
            <input
              type="number"
              value={initCash}
              onChange={(e) => setInitCash(Number(e.target.value))}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 5,
            }}>
              <label style={{
                display: 'block',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                color: 'var(--color-ec-text-muted)',
              }}>
                1R
              </label>
              <select
                value={riskType}
                onChange={(e) => setRiskType(e.target.value as "FIXED" | "PERCENT")}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  outline: 'none',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 600,
                  color: 'var(--color-ec-copper)',
                  cursor: 'pointer',
                }}
              >
                <option value="FIXED" style={{ backgroundColor: 'var(--color-ec-bg-elevated)', color: 'var(--color-ec-text-primary)' }}>Fijo ($)</option>
                <option value="PERCENT" style={{ backgroundColor: 'var(--color-ec-bg-elevated)', color: 'var(--color-ec-text-primary)' }}>% Eq</option>
              </select>
            </div>
            <div className="flex gap-2">
              <input
                type="number"
                step={riskType === "PERCENT" ? "0.1" : "1"}
                value={riskR}
                onChange={(e) => setRiskR(Number(e.target.value))}
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  border: '0.5px solid var(--color-ec-border)',
                  borderRadius: 5,
                  padding: '7px 10px',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 12,
                  fontWeight: 500,
                  color: 'var(--color-ec-text-primary)',
                  outline: 'none',
                  width: '100%',
                }}
              />
            </div>
          </div>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
        }}>
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 5,
            }}>
              <label style={{
                display: 'block',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                color: 'var(--color-ec-text-muted)',
              }}>
                Fees {feeType === "PERCENT" ? "(%)" : "($)"}
              </label>
              <select
                value={feeType}
                onChange={(e) => setFeeType(e.target.value as "PERCENT" | "FLAT")}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  outline: 'none',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 600,
                  color: 'var(--color-ec-copper)',
                  cursor: 'pointer',
                }}
              >
                <option value="PERCENT" style={{ backgroundColor: 'var(--color-ec-bg-elevated)', color: 'var(--color-ec-text-primary)' }}>%</option>
                <option value="FLAT" style={{ backgroundColor: 'var(--color-ec-bg-elevated)', color: 'var(--color-ec-text-primary)' }}>$</option>
              </select>
            </div>
            <input
              type="number"
              step="0.01"
              value={fees}
              onChange={(e) => setFees(Number(e.target.value))}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--color-ec-text-muted)',
              marginBottom: 5,
            }}>
              Slippage (%)
            </label>
            <input
              type="number"
              step="0.01"
              value={slippage}
              onChange={(e) => setSlippage(Number(e.target.value))}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
        </div>

        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          paddingTop: 16,
          marginTop: 12,
          borderTop: '0.5px solid var(--color-ec-border)',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useLocates}
                onChange={() => setUseLocates(!useLocates)}
                className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
              />
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--color-ec-text-secondary)',
              }}>Locates estimados $/100</span>
            </label>
            {useLocates && (
              <input
                type="number"
                step="0.01"
                value={locatesCost}
                onChange={(e) => setLocatesCost(Number(e.target.value))}
                className="w-20 border border-[var(--color-ec-border)]"
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  borderRadius: 5,
                  padding: '6px 8px',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  color: 'var(--color-ec-text-primary)',
                  outline: 'none',
                }}
              />
            )}
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useMonthlyExpenses}
                onChange={() => setUseMonthlyExpenses(!useMonthlyExpenses)}
                className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
              />
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--color-ec-text-secondary)',
              }}>Gastos fijos mensuales ($)</span>
            </label>
            {useMonthlyExpenses && (
              <input
                type="number"
                step="1"
                value={monthlyExpenses}
                onChange={(e) => setMonthlyExpenses(Number(e.target.value))}
                className="w-20 border border-[var(--color-ec-border)]"
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  borderRadius: 5,
                  padding: '6px 8px',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  color: 'var(--color-ec-text-primary)',
                  outline: 'none',
                }}
              />
            )}
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            paddingTop: 4,
          }}>
            <div className="flex flex-col">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sizeBySl}
                  onChange={() => setSizeBySl(!sizeBySl)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  fontWeight: 500,
                  color: 'var(--color-ec-text-secondary)',
                }}>Size por Distancia al SL</span>
              </label>
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 10,
                color: 'var(--color-ec-text-secondary)',
                fontStyle: 'italic',
                marginLeft: 24,
                marginTop: 4,
                lineHeight: '1.3',
              }}>
                Calcula nº Shares usando el Riesgo dividido por la distancia real al Stop Loss
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* RANGO DE FECHAS IS-OOS */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        paddingTop: 16,
        borderTop: '0.5px solid var(--color-ec-border)',
      }}>
        <h2 style={{
          fontFamily: 'var(--color-ec-sans)',
          fontSize: 9,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          color: 'var(--color-ec-text-muted)',
          marginBottom: 4,
        }}>
          Rango de fechas IS-OOS
        </h2>

        {/* IS % SLIDER */}
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              fontWeight: 600,
              color: 'var(--color-ec-text-secondary)',
            }}>
              IS: <span style={{ color: 'var(--color-ec-copper)', fontWeight: 700 }}>{isPercent}%</span>
            </span>
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              fontWeight: 600,
              color: isPercent >= 90 ? 'var(--color-ec-text-muted)' : 'var(--color-ec-profit)',
            }}>
              OOS: {100 - isPercent}%
            </span>
          </div>

          {/* Visual bar */}
          <div style={{
            display: 'flex',
            height: 12,
            borderRadius: 6,
            overflow: 'hidden',
            backgroundColor: 'var(--color-ec-bg-elevated)',
            border: '0.5px solid var(--color-ec-border)',
            boxShadow: 'inset 0 1px 3px rgba(0,0,0,0.4)',
          }}>
            <div style={{
              width: `${isPercent}%`,
              backgroundColor: 'var(--color-ec-copper)',
              borderRadius: '6px 0 0 6px',
              transition: 'width 150ms ease',
            }} />
            {isPercent < 100 && (
              <div style={{
                width: `${100 - isPercent}%`,
                backgroundColor: 'color-mix(in srgb, var(--color-ec-profit) 70%, transparent)',
                borderRadius: '0 6px 6px 0',
                transition: 'width 150ms ease',
              }} />
            )}
          </div>

          {/* Range slider */}
          <input
            type="range"
            min={50}
            max={100}
            step={5}
            value={isPercent}
            onChange={(e) => setIsPercent(Number(e.target.value))}
            style={{
              width: '100%',
              accentColor: 'var(--color-ec-copper)',
              cursor: 'pointer',
              height: 10,
              marginTop: 4,
            }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 8,
              color: 'var(--color-ec-text-muted)',
            }}>50%</span>
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 8,
              color: 'var(--color-ec-text-muted)',
            }}>100%</span>
          </div>

          {/* Warnings */}
          {isPercent > 80 && isPercent < 100 && (
            <div style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              color: 'var(--color-ec-copper)',
              fontStyle: 'italic',
              marginTop: 2,
            }}>
              ⚠ OOS &lt; 20% — validación limitada
            </div>
          )}
          {isPercent > 90 && isPercent < 100 && (
            <div style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              color: 'var(--color-ec-loss)',
              fontStyle: 'italic',
            }}>
              ⛔ OOS &lt; 10% — pestaña de degradación deshabilitada
            </div>
          )}
        </div>
      </div>

      {/* SESIÓN DE MERCADO */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        paddingTop: 16,
        borderTop: '0.5px solid var(--color-ec-border)',
      }}>
        <h2 style={{
          fontFamily: 'var(--color-ec-sans)',
          fontSize: 9,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          color: 'var(--color-ec-text-muted)',
          marginBottom: 4,
        }}>
          Sesión de mercado
        </h2>
        <div className="space-y-2">
          {[
            { id: "pre", label: "Pre-Market", time: "04:00 - 09:30 ET" },
            { id: "rth", label: "Regular Hours", time: "09:30 - 16:00 ET" },
            { id: "post", label: "After-Market", time: "16:00 - 20:00 ET" },
            { id: "custom", label: "Horas personalizadas (ET)", time: "" },
          ].map((session) => (
            <div key={session.id} className="space-y-2">
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={marketSessions.includes(session.id)}
                    onChange={() => toggleSession(session.id)}
                    className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                  />
                  <span style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 11,
                    fontWeight: 500,
                    color: 'var(--color-ec-text-secondary)',
                  }}>{session.label}</span>
                </label>
                {session.time && (
                  <span style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10,
                    fontWeight: 400,
                    color: 'var(--color-ec-text-muted)',
                  }}>{session.time}</span>
                )}
              </div>

              {session.id === "custom" && marketSessions.includes("custom") && (
                <div className="grid grid-cols-2 gap-2 mt-3 pl-6">
                  <div>
                    <label style={{
                      display: "block",
                      fontFamily: "var(--color-ec-sans)",
                      fontSize: 11,
                      fontWeight: 500,
                      color: "var(--color-ec-text-secondary)",
                      fontStyle: "italic",
                      marginBottom: 4,
                    }}>Desde</label>
                    <input
                      type="time"
                      value={customStartTime}
                      onChange={(e) => setCustomStartTime(e.target.value)}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '6px 10px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-primary)',
                        outline: 'none',
                        width: '100%',
                      }}
                    />
                  </div>
                  <div>
                    <label style={{
                      display: "block",
                      fontFamily: "var(--color-ec-sans)",
                      fontSize: 11,
                      fontWeight: 500,
                      color: "var(--color-ec-text-secondary)",
                      fontStyle: "italic",
                      marginBottom: 4,
                    }}>Hasta</label>
                    <input
                      type="time"
                      value={customEndTime}
                      onChange={(e) => setCustomEndTime(e.target.value)}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '6px 10px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-primary)',
                        outline: 'none',
                        width: '100%',
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={handleRun}
        disabled={loading || !selectedDataset || !selectedStrategy || isSelectedStratRiskInvalid}
        onMouseEnter={() => setHoveredBtn("run")}
        onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
        onMouseDown={() => setActiveBtn("run")}
        onMouseUp={() => setActiveBtn(null)}
        style={{
            backgroundColor: 'var(--color-ec-copper)',
            color: 'var(--color-ec-copper-text)',
            border: 'none',
            borderRadius: 5,
            padding: '9px 16px',
            fontFamily: "'General Sans', sans-serif",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '1.2px',
            textTransform: 'uppercase',
            cursor: loading || !selectedDataset || !selectedStrategy || isSelectedStratRiskInvalid ? 'not-allowed' : 'pointer',
            width: '100%',
            marginTop: 8,
            opacity: loading || !selectedDataset || !selectedStrategy || isSelectedStratRiskInvalid ? 0.35 : 1,
            boxShadow: hoveredBtn === "run" && !loading && selectedDataset && selectedStrategy && !isSelectedStratRiskInvalid ? '0 0 14px rgba(216, 122, 61, 0.5)' : 'none',
            transform: activeBtn === "run" && !loading && selectedDataset && selectedStrategy && !isSelectedStratRiskInvalid ? 'scale(0.98)' : hoveredBtn === "run" && !loading && selectedDataset && selectedStrategy && !isSelectedStratRiskInvalid ? 'scale(1.015)' : 'scale(1)',
            transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
          }}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Ejecutando...
          </span>
        ) : (
          "Ejecutar Backtest"
        )}
      </button>
    </div>
  );
}
