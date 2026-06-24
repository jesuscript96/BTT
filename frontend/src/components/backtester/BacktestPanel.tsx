"use client";

import { useEffect, useState, useRef } from "react";
import type { Dataset, Strategy } from "@/lib/api_backtester";
import { fetchDatasets, fetchStrategies } from "@/lib/api_backtester";
import { INDICATOR_LABELS, COMPARATOR_LABELS } from "@/components/strategy-builder/ConditionBuilder";
import InfoTooltip from "@/components/backtester/InfoTooltip";
import { Plus, Settings } from "lucide-react";

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
    is_percent?: number;
  }) => void;
  onParamsChange?: (params: BacktestPanelParams) => void;
  loading: boolean;
  isDarkMode?: boolean;
  onNewDataset: () => void;
  datasetRefreshTrigger?: number;
  pendingDatasetSelect?: string;
  onClearPendingDataset?: () => void;
  activeStrategy?: any;
  onConfigureStrategy?: (strategyId: string) => void;
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
      const volVal = cond.value ?? 0;
      valLabel = `${cond.operator} ${volVal >= 1000000 ? `${volVal / 1000000}M` : volVal.toLocaleString()}`;
    } else if (cond.metric === 'close_vs_open') {
      valLabel = `${cond.operator} Open`;
    } else if (cond.metric === 'close_vs_high_low') {
      valLabel = cond.operator === '> High' ? '> Prev High' : '< Prev Low';
    } else if (cond.metric === 'close_vs_high') {
      valLabel = `${cond.operator} High`;
    } else if (cond.metric === 'close_vs_low') {
      valLabel = `${cond.operator} Low`;
    } else if (cond.metric === 'close_vs_pm_high') {
      valLabel = `${cond.operator} PM High`;
    } else if (cond.metric === 'close_vs_pm_low') {
      valLabel = `${cond.operator} PM Low`;
    } else if (cond.metric === 'close_vs_vwap') {
      valLabel = `${cond.operator} VWAP`;
    } else if (cond.metric === 'close_vs_sma') {
      valLabel = `${cond.operator} SMA ${cond.sma_period}`;
    } else if (cond.metric === 'candle_range_pct') {
      metricLabel = 'Candle Range %';
      valLabel = `${cond.operator} ${cond.value}%`;
    } else if (cond.metric === 'candle_range_ratio_gap_1_vs_gap') {
      metricLabel = cond.day === 'gap_1_day' ? 'Candle Range Gap+1 vs Gap' : 'Candle Range vs Prev';
      valLabel = `${cond.operator} ${cond.value}%`;
    } else {
      valLabel = `${cond.operator || ""} ${cond.value !== undefined ? cond.value : ""}`.trim();
    }
    
    return `${dayLabel} (${metricLabel} ${valLabel})`;
  }).join(", ");
}

function formatDate(dStr: string): string {
  if (!dStr) return '';
  const parts = dStr.split('-');
  if (parts.length === 3) {
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  }
  return dStr;
}

function formatFilterValue(key: string, value: any): string | null {
  if (key === 'rules') return null; // handle separately
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) return null;
  const labels: Record<string, string> = {
    min_market_cap: 'mcap mín',
    max_market_cap: 'mcap máx',
    min_price: 'precio mín',
    max_price: 'precio máx',
    min_volume: 'volumen mín',
    max_shares_float: 'float máx',
    require_shortable: 'shortable',
    exclude_dilution: 'sin dilución',
    date_from: 'desde',
    date_to: 'hasta',
    min_change_pct: 'variación mín %',
    max_change_pct: 'variación máx %',
    start_date: 'desde',
    end_date: 'hasta',
  };
  const label = labels[key] || key.replace(/_/g, " ").toLowerCase();

  if (typeof value === 'boolean') return value ? label : null;
  if (typeof value === 'number') {
    if (key.includes('market_cap')) {
      if (value >= 1_000_000_000) return `${label}: $${(value / 1_000_000_000).toFixed(1).replace(/\.0$/, '')}B`;
      if (value >= 1_000_000) return `${label}: $${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
    }
    if (value >= 1_000_000) return `${label}: ${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
    if (value >= 1_000) return `${label}: ${(value / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
    return `${label}: ${value}`;
  }
  return `${label}: ${value}`;
}

function getFriendlyMetricLabel(metric: string): string {
  if (!metric) return "";
  const m = metric.replace(/['"]+/g, '');
  const labelMap: Record<string, string> = {
    // Gap Day
    "Close Price": "cierre",
    "Min Open PM price": "apertura pm",
    "PMH Gap %": "gap pm high %",
    "Premarket Volume": "volumen premarket",
    "Open Gap %": "gap de apertura %",
    "EOD Volume": "volumen rth",
    "RTH Range %": "rango rth %",
    "Open Price": "apertura rth",
    "High Price": "máximo rth",
    "Low Price": "mínimo rth",
    "RTH Run %": "run rth %",
    "High Spike %": "spike máximo %",
    "Low Spike %": "spike mínimo %",
    "M15 Return %": "retorno m15 %",
    "M30 Return %": "retorno m30 %",
    "M60 Return %": "retorno m60 %",
    "Day Return %": "retorno del día %",
    "Previous Close": "cierre anterior",

    // Gap+1 Day
    "lead_rth_close_1": "cierre gap+1",
    "lead_open_1": "apertura pm gap+1",
    "lead_pmh_gap_pct_1": "gap pm high gap+1 %",
    "lead_pm_volume_1": "volumen premarket gap+1",
    "lead_gap_pct_1": "gap de apertura gap+1 %",
    "lead_rth_volume_1": "volumen rth gap+1",
    "lead_rth_range_pct_1": "rango rth gap+1 %",
    "lead_rth_open_1": "apertura rth gap+1",
    "lead_rth_high_1": "máximo rth gap+1",
    "lead_rth_low_1": "mínimo rth gap+1",

    // Gap+2 Day
    "lead_rth_close_2": "cierre gap+2",
    "lead_open_2": "apertura pm gap+2",
    "lead_pmh_gap_pct_2": "gap pm high gap+2 %",
    "lead_pm_volume_2": "volumen premarket gap+2",
    "lead_gap_pct_2": "gap de apertura gap+2 %",
    "lead_rth_volume_2": "volumen rth gap+2",
    "lead_rth_range_pct_2": "rango rth gap+2 %",
    "lead_rth_open_2": "apertura rth gap+2",
    "lead_rth_high_2": "máximo rth gap+2",
    "lead_rth_low_2": "mínimo rth gap+2",
  };

  if (labelMap[m]) {
    return labelMap[m];
  }
  return m.replace(/_/g, " ").toLowerCase();
}

function formatRule(rule: any): string {
  if (!rule || !rule.metric) return '';
  const opMap: Record<string, string> = {
    'GT': '>',
    'LT': '<',
    'GTE': '>=',
    'LTE': '<=',
    'EQUAL': '=',
    'NEQ': '!=',
    'GREATER_THAN_OR_EQUAL': '>=',
    'LESS_THAN_OR_EQUAL': '<=',
    'GREATER_THAN': '>',
    'LESS_THAN': '<',
  };
  const op = opMap[rule.operator] || rule.operator;
  const friendlyMetric = getFriendlyMetricLabel(rule.metric);

  let friendlyVal = rule.value;
  const numVal = parseFloat(rule.value);
  if (!isNaN(numVal)) {
    // Format volume metrics
    if (rule.metric.toLowerCase().includes('volume')) {
      if (numVal >= 1_000_000) {
        friendlyVal = `${(numVal / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
      } else if (numVal >= 1_000) {
        friendlyVal = `${(numVal / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
      }
    }
    // Format percentage metrics
    else if (rule.metric.includes('%') || rule.metric.toLowerCase().includes('pct')) {
      friendlyVal = `${numVal}%`;
    }
    // Format dollar price metrics
    else if (rule.metric.toLowerCase().includes('price') || rule.metric.toLowerCase().includes('close') || rule.metric.toLowerCase().includes('open') || rule.metric.toLowerCase().includes('high') || rule.metric.toLowerCase().includes('low')) {
      friendlyVal = `$${numVal.toFixed(2).replace(/\.00$/, '')}`;
    }
  }

  return `${friendlyMetric} ${op} ${friendlyVal}`;
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
  isDarkMode = false,
  activeStrategy,
  onConfigureStrategy
}: BacktestPanelProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  /* POST-MVP AGENTIC - descomentar cuando se active ChatBotAgentic.tsx (ver docs/plan_asistente_edgie.md)
  // ── Edgie assistant integration (AssistantBus) ───────────────
  useAssistantAction({
    name: "backtest.fill_form",
    description:
      "Rellena el formulario de configuración del backtest (parcial o completo); el usuario ve los campos cambiar en pantalla. " +
      "También selecciona dataset/estrategia por id o nombre. No ejecuta nada: usa backtest_run después.",
    parameters: BacktestParamsSchema,
    confirm: "auto",
    handler: (args) => {
      const data: any = { ...args };
      const matchedInfo: string[] = [];

      if (data.datasetId || data.datasetName) {
        const query = String(data.datasetId || data.datasetName).toLowerCase();
        const matched = datasetsRef.current.find(
          (d) => d.id.toLowerCase() === query || d.name.toLowerCase().includes(query)
        );
        if (!matched) {
          const available = datasetsRef.current.map((d) => `"${d.name}" (id=${d.id})`).join(", ") || "(ninguno)";
          return { ok: false, error: `Ningún dataset coincide con "${query}". Disponibles: ${available}` };
        }
        matchedInfo.push(`dataset → "${matched.name}" (id=${matched.id})`);
      }
      if (data.strategyId || data.strategyName) {
        const query = String(data.strategyId || data.strategyName).toLowerCase();
        const matched = strategiesRef.current.find(
          (s) => s.id.toLowerCase() === query || s.name.toLowerCase().includes(query)
        );
        if (!matched) {
          const available = strategiesRef.current.map((s) => `"${s.name}" (id=${s.id})`).join(", ") || "(ninguna)";
          return { ok: false, error: `Ninguna estrategia coincide con "${query}". Disponibles: ${available}` };
        }
        matchedInfo.push(`estrategia → "${matched.name}" (id=${matched.id})`);
      }

      window.dispatchEvent(new CustomEvent("fill-backtest-form", { detail: data }));
      return { ok: true, result: { applied: data, matched: matchedInfo } };
    },
  });

  useAssistantAction({
    name: "backtest.run",
    description:
      "Ejecuta el backtest usando el dataset Y la estrategia GUARDADA que están seleccionados en el formulario. " +
      "IMPORTANTE: NO usa el borrador del Strategy Builder. Si el usuario acaba de construir una estrategia nueva con strategy_fill, ejecútala con strategy_test (no con esta). " +
      "Usa backtest_run solo cuando hay una estrategia ya guardada seleccionada. Revisa backtest.form y backtest.catalog antes.",
    parameters: EmptySchema,
    confirm: "auto",
    handler: async () => {
      // Pre-flight: a valid saved dataset and strategy must be selected, or the
      // backend fails with opaque errors like "Strategy not found".
      if (!selectedDataset || !datasetsRef.current.some((d) => d.id === selectedDataset)) {
        return { ok: false, error: "No hay un dataset válido seleccionado. Usa backtest_fill_form con datasetName/datasetId primero." };
      }
      const strat = strategiesRef.current.find((s) => s.id === selectedStrategy);
      if (!strat) {
        const available = strategiesRef.current.map((s) => `"${s.name}" (id=${s.id})`).join(", ") || "(ninguna guardada)";
        return {
          ok: false,
          error:
            "No hay una estrategia GUARDADA válida seleccionada. " +
            "Si quieres ejecutar una estrategia recién construida en el builder, usa strategy_test en su lugar. " +
            `Estrategias guardadas disponibles: ${available}.`,
        };
      }

      // Race the run against a fast backend failure (e.g. "Strategy not found")
      // so we report the truth instead of a false "launched".
      const failure = new Promise<string | null>((resolve) => {
        const onFinished = (e: Event) => {
          const detail = (e as CustomEvent).detail;
          if (detail && detail.ok === false) { cleanup(); resolve(detail.error || "Error al ejecutar el backtest"); }
        };
        const timer = setTimeout(() => { cleanup(); resolve(null); }, 4000);
        const cleanup = () => { clearTimeout(timer); window.removeEventListener("backtest-run-finished", onFinished); };
        window.addEventListener("backtest-run-finished", onFinished);
      });

      window.dispatchEvent(new CustomEvent("run-backtest-action"));
      const err = await failure;
      if (err) return { ok: false, error: `El backtest falló: ${err}` };
      return { ok: true, result: `Backtest en ejecución con la estrategia guardada "${strat.name}"; los resultados aparecerán en pantalla al terminar.` };
    },
  });

  useAssistantContext("backtest.form", () => ({
    selectedDatasetId: selectedDataset,
    selectedStrategyId: selectedStrategy,
    initCash,
    riskR,
    riskType,
    fixedRatioDelta,
    fees,
    feeType,
    slippage,
    startDate,
    endDate,
    marketSessions,
    customStartTime,
    customEndTime,
    locatesCost: useLocates ? locatesCost : 0,
    monthlyExpenses: useMonthlyExpenses ? monthlyExpenses : 0,
  }));

  useAssistantContext("backtest.catalog", () => ({
    datasets: datasets.map((d) => ({ id: d.id, name: d.name, min_date: d.min_date, max_date: d.max_date })),
    strategies: strategies.map((s) => ({ id: s.id, name: s.name })),
  }));
  */

  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const isInitialMountRef = useRef(true);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const lastActiveStrategyRef = useRef<any>(null);
  const [showDatasetFilters, setShowDatasetFilters] = useState(false);
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
  const [feeType, setFeeType] = useState<"PERCENT" | "FLAT">("PERCENT");
  const [isPercent, setIsPercent] = useState(100);
  const [loadingData, setLoadingData] = useState(true);
  const [hoveredBtn, setHoveredBtn] = useState<string | null>(null);
  const [activeBtn, setActiveBtn] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const selectedStrat = strategies.find((s) => s.id === selectedStrategy);
  const selectedDs = datasets.find((d) => d.id === selectedDataset);

  const isDraft = !!selectedStrategy && (
    selectedStrategy === "draft" ||
    selectedStrategy === "wizard_draft" ||
    selectedStrategy.startsWith("draft_") ||
    selectedStrategy.startsWith("wizard_draft_")
  );

  const getStratDef = () => {
    let rawDef: any = null;
    if (isDraft && activeStrategy) {
      rawDef = activeStrategy.definition || activeStrategy;
    } else {
      const strat = strategies.find((s) => s.id === selectedStrategy);
      rawDef = strat?.definition || strat;
    }
    
    if (typeof rawDef === "string") {
      try {
        return JSON.parse(rawDef);
      } catch (e) {
        console.error("Error parsing strategy definition:", e);
      }
    }
    return rawDef;
  };

  const stratDef = getStratDef() as any;
  const riskMgmt = stratDef?.risk_management;
  const sizeBySl = riskMgmt?.size_by_sl || false;
  const isSelectedStratPartialTP = riskMgmt?.use_take_profit === true && riskMgmt?.take_profit_mode === "Partial";
  const selectedStratPartialCapital = (riskMgmt?.partial_take_profits || []).reduce((sum: number, p: any) => sum + (p.capital_pct || 0), 0);
  const isSelectedStratRiskInvalid = isSelectedStratPartialTP && Math.abs(selectedStratPartialCapital - 100) > 0.01;

  const loadData = async () => {
    setLoadingData(true);
    setLoadError(false);
    let failed = false;

    let savedState: any = null;
    try {
      const stored = sessionStorage.getItem("backtester_panel_state");
      if (stored) {
        savedState = JSON.parse(stored);
      }
    } catch (e) {
      console.error("Error reading backtester_panel_state:", e);
    }

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
        const hasSavedDataset = savedState?.selectedDataset && d.some(ds => ds.id === savedState.selectedDataset);
        const selectedId = hasPrefillDataset 
          ? prefill!.dataset_id! 
          : hasSavedDataset 
          ? savedState.selectedDataset 
          : d[0].id;
        setSelectedDataset(selectedId);
        
        if (savedState && savedState.selectedDataset === selectedId) {
          if (savedState.startDate) setStartDate(savedState.startDate);
          if (savedState.endDate) setEndDate(savedState.endDate);
        } else {
          const selectedDs = d.find(ds => ds.id === selectedId);
          if (selectedDs?.min_date) setStartDate(selectedDs.min_date);
          if (selectedDs?.max_date) setEndDate(selectedDs.max_date);
        }
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
        const hasSavedStrategy = savedState?.selectedStrategy && s.some(st => st.id === savedState.selectedStrategy);
        const selectedId = hasPrefillStrategy 
          ? prefill!.strategy_id! 
          : hasSavedStrategy 
          ? savedState.selectedStrategy 
          : s[0].id;
        setSelectedStrategy(selectedId);
      }
    } catch (e) {
      console.error("Error loading strategies:", e);
      failed = true;
    }

    if (savedState) {
      if (savedState.initCash !== undefined) setInitCash(savedState.initCash);
      if (savedState.riskR !== undefined) setRiskR(savedState.riskR);
      if (savedState.fees !== undefined) setFees(savedState.fees);
      if (savedState.slippage !== undefined) setSlippage(savedState.slippage);
      if (savedState.marketSessions !== undefined) setMarketSessions(savedState.marketSessions);
      if (savedState.customStartTime !== undefined) setCustomStartTime(savedState.customStartTime);
      if (savedState.customEndTime !== undefined) setCustomEndTime(savedState.customEndTime);
      if (savedState.riskType !== undefined) setRiskType(savedState.riskType);
      if (savedState.feeType !== undefined) setFeeType(savedState.feeType);
      if (savedState.isPercent !== undefined) setIsPercent(savedState.isPercent);
      if (savedState.useLocates !== undefined) setUseLocates(savedState.useLocates);
      if (savedState.locatesCost !== undefined) setLocatesCost(savedState.locatesCost);
      if (savedState.useMonthlyExpenses !== undefined) setUseMonthlyExpenses(savedState.useMonthlyExpenses);
      if (savedState.monthlyExpenses !== undefined) setMonthlyExpenses(savedState.monthlyExpenses);
    }

    setLoadError(failed);
    setLoadingData(false);
    
    // Allow selectedDataset change effect to run after mount
    setTimeout(() => {
      isInitialMountRef.current = false;
    }, 100);
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (isInitialMountRef.current) return;
    const ds = datasets.find(d => d.id === selectedDataset);
    if (ds) {
      if (ds.min_date) setStartDate(ds.min_date);
      if (ds.max_date) setEndDate(ds.max_date);
    }
    setShowDatasetFilters(false);
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
    if (activeStrategy?.id && activeStrategy.id !== lastActiveStrategyRef.current) {
      setSelectedStrategy(activeStrategy.id);
      lastActiveStrategyRef.current = activeStrategy.id;
    }
  }, [activeStrategy]);

  useEffect(() => {
    if (!selectedStrategy) return;
    const currentStrat = isDraft
      ? activeStrategy
      : strategies.find((s) => s.id === selectedStrategy);
    if (currentStrat) {
      let stratDef = currentStrat.definition || currentStrat;
      if (typeof stratDef === 'string') {
        try {
          stratDef = JSON.parse(stratDef);
        } catch (e) {
          console.error("Error parsing strategy definition in useEffect:", e);
        }
      }
      if (stratDef && typeof stratDef === 'object') {
        if (stratDef.market_sessions) {
          const nextSessions = stratDef.market_sessions;
          setMarketSessions((prev) => {
            if (prev.length === nextSessions.length && prev.every((v, i) => v === nextSessions[i])) {
              return prev;
            }
            return nextSessions;
          });
        } else {
          setMarketSessions((prev) => {
            if (prev.length === 1 && prev[0] === "rth") {
              return prev;
            }
            return ["rth"];
          });
        }
        if (stratDef.custom_start_time) {
          setCustomStartTime((prev) => prev === stratDef.custom_start_time ? prev : stratDef.custom_start_time);
        }
        if (stratDef.custom_end_time) {
          setCustomEndTime((prev) => prev === stratDef.custom_end_time ? prev : stratDef.custom_end_time);
        }
      }
    }
  }, [selectedStrategy, activeStrategy, strategies]);



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
    selectedDataset, initCash, riskR, riskType, fixedRatioDelta,
    fees, feeType, slippage, startDate, endDate, marketSessions,
    customStartTime, customEndTime, useLocates, locatesCost,
    useMonthlyExpenses, monthlyExpenses, lookAheadPrevention, isPercent,
    sizeBySl,
  ]);

  // Save state to sessionStorage on change
  useEffect(() => {
    if (loadingData) return;
    try {
      const panelState = {
        selectedDataset,
        selectedStrategy,
        initCash,
        riskR,
        fees,
        slippage,
        startDate,
        endDate,
        marketSessions,
        customStartTime,
        customEndTime,
        riskType,
        feeType,
        isPercent,
        useLocates,
        locatesCost,
        useMonthlyExpenses,
        monthlyExpenses,
      };
      sessionStorage.setItem("backtester_panel_state", JSON.stringify(panelState));
    } catch (e) {
      console.error("Error writing backtester_panel_state:", e);
    }
  }, [
    selectedDataset, selectedStrategy, initCash, riskR, fees, slippage,
    startDate, endDate, marketSessions, customStartTime, customEndTime,
    riskType, feeType, isPercent, loadingData,
    useLocates, locatesCost, useMonthlyExpenses, monthlyExpenses
  ]);

  // Synchronize dataset selection with the selected strategy's associated dataset
  useEffect(() => {
    if (!selectedStrategy) return;
    let rawDef: any = null;
    if (isDraft && activeStrategy) {
      rawDef = activeStrategy.definition || activeStrategy;
    } else {
      const strat = strategies.find((s) => s.id === selectedStrategy);
      rawDef = strat?.definition || strat;
    }

    if (typeof rawDef === "string") {
      try {
        rawDef = JSON.parse(rawDef);
      } catch (e) {}
    }

    if (rawDef) {
      setSelectedDataset(rawDef.dataset_id || "");
    }
  }, [selectedStrategy, strategies, activeStrategy]);

  const handleRun = () => {
    if (isSelectedStratRiskInvalid) {
      alert("La suma del capital de los parciales de Take Profit debe ser exactamente 100%.");
      return;
    }
    if (!selectedStrategy) return;
    const stratDef = getStratDef();
    const hasUniverse = !!(selectedDataset || stratDef?.universe_filters);
    if (!hasUniverse) return;

    onRun({
      dataset_id: selectedDataset || "",
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
      size_by_sl: getStratDef()?.risk_management?.size_by_sl || false,
      is_percent: isPercent,
    });
  };

  const toggleSession = (session: string) => {
    setMarketSessions(prev =>
      prev.includes(session)
        ? prev.filter(s => s !== session)
        : [...prev, session]
    );
  };

  // getStratDef was moved to the top of the component to avoid rendering loop issues.
  const isConfigurable = !!selectedStrategy;



  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
    }}>
      {/* CONFIGURACIÓN */}
      <h2 style={{
        fontFamily: 'var(--color-ec-sans)',
        fontSize: 9,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.15em',
        color: 'var(--color-ec-text-muted)',
        marginBottom: 4,
      }}>
        Estrategia
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 0 }}>
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
              {isDraft && activeStrategy && (
                <option value={selectedStrategy}>
                  [Borrador] {activeStrategy.name}
                </option>
              )}
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
          {selectedStrategy && (() => {
            const currentStrat = isDraft ? activeStrategy : strategies.find((s) => s.id === selectedStrategy);
            if (!currentStrat) return null;
            const cleanDesc = (currentStrat.description || "")
              .replace(/\[What-if:[\s\S]*\]/g, "")
              .trim();
            let stratDef = currentStrat.definition || currentStrat as any;
            if (typeof stratDef === 'string') {
              try {
                stratDef = JSON.parse(stratDef);
              } catch (e) {
                console.error("Error parsing strategy definition in info box:", e);
              }
            }
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

                {(displayBias || displayDay || precondsText || stratDef?.universe_filters || stratDef?.dataset_id || stratDef?.risk_management) && (
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

                    {(() => {
                      const sessions = stratDef?.market_sessions || ["rth"];
                      return (
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>SESIÓN: </span>
                          <span style={{ color: 'var(--color-ec-text-primary)', fontWeight: 600 }}>
                            {sessions.map((s: string) => {
                              if (s === 'pre') return 'Pre-market';
                              if (s === 'rth') return 'RTH (Mercado)';
                              if (s === 'post') return 'Afterhours';
                              if (s === 'custom') return `Personalizado (${stratDef?.custom_start_time || '09:30'}-${stratDef?.custom_end_time || '16:00'})`;
                              return s;
                            }).join(' + ')}
                          </span>
                        </div>
                      );
                    })()}

                    {/* Universo / Dataset */}
                    {(() => {
                      const universeFilters = stratDef?.universe_filters;
                      const hasUniverseFilters = universeFilters && (
                        universeFilters.date_from ||
                        universeFilters.date_to ||
                        (universeFilters.min_market_cap != null && universeFilters.min_market_cap !== "") ||
                        (universeFilters.max_market_cap != null && universeFilters.max_market_cap !== "") ||
                        (universeFilters.min_price != null && universeFilters.min_price !== "") ||
                        (universeFilters.max_price != null && universeFilters.max_price !== "") ||
                        (universeFilters.min_volume != null && universeFilters.min_volume !== "") ||
                        (universeFilters.max_shares_float != null && universeFilters.max_shares_float !== "") ||
                        universeFilters.require_shortable === true ||
                        (universeFilters.whitelist_sectors && universeFilters.whitelist_sectors.length > 0) ||
                        (universeFilters.rules && universeFilters.rules.length > 0)
                      );

                      if (hasUniverseFilters) {
                        const parts: string[] = [];
                        if (universeFilters.date_from || universeFilters.date_to) {
                          parts.push(`Fechas: ${formatDate(universeFilters.date_from) || '?'} a ${formatDate(universeFilters.date_to) || '?'}`);
                        }
                        if (universeFilters.min_market_cap != null && universeFilters.min_market_cap !== "") {
                          parts.push(`Cap Mín: $${(universeFilters.min_market_cap / 1e6).toFixed(1)}M`);
                        }
                        if (universeFilters.max_market_cap != null && universeFilters.max_market_cap !== "") {
                          parts.push(`Cap Máx: $${(universeFilters.max_market_cap / 1e6).toFixed(1)}M`);
                        }
                        if (universeFilters.min_price != null && universeFilters.min_price !== "") {
                          parts.push(`Precio Mín: $${universeFilters.min_price}`);
                        }
                        if (universeFilters.max_price != null && universeFilters.max_price !== "") {
                          parts.push(`Precio Máx: $${universeFilters.max_price}`);
                        }
                        if (universeFilters.min_volume != null && universeFilters.min_volume !== "") {
                          parts.push(`Vol Mín: ${(universeFilters.min_volume / 1e3).toFixed(0)}K`);
                        }
                        if (universeFilters.max_shares_float != null && universeFilters.max_shares_float !== "") {
                          parts.push(`Float Máx: ${(universeFilters.max_shares_float / 1e6).toFixed(1)}M`);
                        }
                        if (universeFilters.require_shortable === true) {
                          parts.push("Shortable");
                        }
                        if (universeFilters.whitelist_sectors && universeFilters.whitelist_sectors.length > 0) {
                          parts.push(`Sectores: ${universeFilters.whitelist_sectors.join(', ')}`);
                        }
                        if (universeFilters.rules && universeFilters.rules.length > 0) {
                          const rulesText = universeFilters.rules.map((r: any) => formatRule(r)).filter(Boolean).join(", ");
                          if (rulesText) {
                            parts.push(`Criterios: [${rulesText}]`);
                          }
                        }
                        return (
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>UNIVERSO: </span>
                            <span style={{ color: 'var(--color-ec-text-primary)' }}>{parts.join(" | ")}</span>
                          </div>
                        );
                      } else {
                        const dsId = stratDef?.dataset_id || currentStrat.dataset_id;
                        if (dsId) {
                          const currentDs = datasets.find(d => d.id === dsId);
                          const datasetName = currentDs ? currentDs.name : dsId;
                          return (
                            <div>
                              <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>DATASET: </span>
                              <span style={{ color: 'var(--color-ec-text-primary)' }}>{datasetName}</span>
                            </div>
                          );
                        }
                      }
                      return null;
                    })()}

                    {/* Gestión de Riesgo (Stops) */}
                    {(() => {
                      const rm = stratDef?.risk_management;
                      if (!rm) return null;
                      
                      const stopList: string[] = [];
                      
                      // Stop Loss
                      if (rm.use_hard_stop && rm.hard_stop?.value > 0) {
                        stopList.push(`Stop Loss: ${rm.hard_stop.value}${rm.hard_stop.type === 'Percentage' ? '%' : 'R'}`);
                      }
                      if (rm.trailing_stop?.active) {
                        const bufferVal = rm.trailing_stop.type === 'Percentage' ? `${rm.trailing_stop.buffer_pct}%` : `${rm.trailing_stop.buffer_r}R`;
                        stopList.push(`Trailing: ${bufferVal}`);
                      }
                      if (!rm.use_hard_stop && !rm.trailing_stop?.active) {
                        stopList.push("Sin Stop Loss");
                      }
                      
                      // Take Profit
                      if (rm.use_take_profit) {
                        if (rm.take_profit_mode === "Partial") {
                          const partials = (rm.partial_take_profits || []).map((p: any) => {
                            const d = String(p.distance_pct ?? p.multiplier ?? '');
                            if (d === 'EOD') return `EOD: ${p.capital_pct}%`;
                            if (d.startsWith('TIME:')) return `${d.split(':')[1]}m: ${p.capital_pct}%`;
                            if (d.startsWith('HOUR:')) return `${d.substring(5).split(':').slice(0, 2).join(':')}: ${p.capital_pct}%`;
                            const suffix = p.type === 'Percentage' ? '%' : 'R';
                            return `${d}${suffix}: ${p.capital_pct}%`;
                          }).join(', ');
                          stopList.push(`TP Parciales (${partials})`);
                        } else {
                          const tpType = rm.take_profit?.type;
                          const suffix = tpType === 'Percentage' ? '%' : tpType === 'Time' ? 'm' : tpType === 'Hour' ? '' : 'R';
                          const prefix = tpType === 'Hour' ? 'Hora: ' : '';
                          const tpVal = rm.take_profit?.value ? `${prefix}${tpType === 'Hour' ? String(rm.take_profit.value).split(':').slice(0, 2).join(':') : rm.take_profit.value}${suffix}` : '';
                          stopList.push(`Take Profit: ${tpVal}`);
                        }
                      } else {
                        stopList.push("Sin Take Profit");
                      }
                      
                      // Reentries
                      if (rm.accept_reentries) {
                        stopList.push(`Reentradas: ${rm.max_reentries === -1 || rm.max_reentries === undefined ? 'Ilimitadas' : rm.max_reentries}`);
                      }
                      
                      // Swing
                      if (rm.swing_option?.active) {
                        stopList.push(`Swing hasta ${rm.swing_option.target_day === 'gap_1_day' ? 'Gap+1' : 'Gap+2'}`);
                      }

                      // Max daily drawdown
                      if (rm.max_drawdown_daily != null && rm.max_drawdown_daily !== "") {
                        stopList.push(`Max DD Diario: ${rm.max_drawdown_daily}%`);
                      }
                      
                      if (stopList.length === 0) return null;
                      
                      return (
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>RIESGO / STOPS: </span>
                          <span style={{ color: 'var(--color-ec-text-primary)' }}>{stopList.join(" | ")}</span>
                        </div>
                      );
                    })()}

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

              </div>
            );
          })()}


          
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            marginTop: 4,
            marginBottom: 8,
          }}>
            <button
              type="button"
              onClick={onNewStrategy}
              onMouseEnter={() => setHoveredBtn("strategy")}
              onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
              onMouseDown={() => setActiveBtn("strategy")}
              onMouseUp={() => setActiveBtn(null)}
              style={{
                padding: '8px 12px',
                borderRadius: 5,
                fontSize: 11,
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                border: hoveredBtn === "strategy" ? '0.5px solid transparent' : '0.5px solid var(--color-ec-copper)',
                backgroundColor: hoveredBtn === "strategy" ? 'var(--color-ec-copper)' : 'transparent',
                color: hoveredBtn === "strategy" ? 'var(--color-ec-copper-text)' : 'var(--color-ec-copper)',
                fontFamily: 'var(--color-ec-sans)',
                boxShadow: hoveredBtn === "strategy" ? '0 0 12px rgba(216, 122, 61, 0.35)' : 'none',
                transform: activeBtn === "strategy" ? 'scale(0.98)' : hoveredBtn === "strategy" ? 'scale(1.015)' : 'scale(1)',
                transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
              }}
            >
              <Plus size={13} strokeWidth={2.5} />
              Nueva Estrategia
            </button>
            <button
              type="button"
              disabled={!isConfigurable}
              onClick={() => onConfigureStrategy?.(selectedStrategy)}
              onMouseEnter={() => isConfigurable && setHoveredBtn("config_strat")}
              onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
              onMouseDown={() => isConfigurable && setActiveBtn("config_strat")}
              onMouseUp={() => setActiveBtn(null)}
              style={{
                padding: '8px 12px',
                borderRadius: 5,
                fontSize: 11,
                fontWeight: 600,
                cursor: isConfigurable ? 'pointer' : 'not-allowed',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                border: !isConfigurable
                  ? '0.5px solid var(--color-ec-border)'
                  : hoveredBtn === "config_strat"
                    ? '0.5px solid transparent'
                    : '0.5px solid var(--color-ec-copper)',
                backgroundColor: !isConfigurable
                  ? 'transparent'
                  : hoveredBtn === "config_strat"
                    ? 'var(--color-ec-copper)'
                    : 'transparent',
                color: !isConfigurable
                  ? 'var(--color-ec-text-muted)'
                  : hoveredBtn === "config_strat"
                    ? 'var(--color-ec-copper-text)'
                    : 'var(--color-ec-copper)',
                fontFamily: 'var(--color-ec-sans)',
                opacity: isConfigurable ? 1 : 0.5,
                boxShadow: hoveredBtn === "config_strat" && isConfigurable ? '0 0 12px rgba(216, 122, 61, 0.35)' : 'none',
                transform: activeBtn === "config_strat" && isConfigurable ? 'scale(0.98)' : hoveredBtn === "config_strat" && isConfigurable ? 'scale(1.015)' : 'scale(1)',
                transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
              }}
            >
              <Settings size={13} strokeWidth={2} />
              Config. Estrategia guardada
            </button>
          </div>
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
            <label className="flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={useLocates}
                onChange={() => setUseLocates(!useLocates)}
                className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)] mr-2"
              />
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--color-ec-text-secondary)',
              }}>Locates estimados $/100</span>
              <InfoTooltip
                position="left"
                width={260}
                text="Estimación de precio medio por locate, al aplicar este dato se restará por ticker en concepto de comisiones, esta cantidad de precio por locate. Trata de calcular, aproximadamente, la media de precios por locates que estimas que te cobrarán por ticker"
                style={{ marginLeft: '1px', display: 'inline-flex' }}
              />
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
              }}>Gastos fijos/mes ($)</span>
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
          display: 'flex',
          alignItems: 'center',
        }}>
          Rango de fechas IS-OOS
          <InfoTooltip
            position="top-left"
            width={200}
            text="In-Sample / Out-of-Sample. Divide el dataset en dos partes: IS (datos sobre los que diseñas/optimizas la estrategia) y OOS (datos limpios nunca vistos para simular la realidad). Ayuda a comprobar si la estrategia tiene sobreajuste (overfitting). Si en IS ganas y en OOS se desploma, está sobreoptimizada."
            style={{ marginLeft: '6px' }}
          />
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


      <button
        onClick={handleRun}
        disabled={loading || !selectedStrategy || isSelectedStratRiskInvalid || !(selectedDataset || stratDef?.universe_filters)}
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
            cursor: (loading || !selectedStrategy || isSelectedStratRiskInvalid || !(selectedDataset || stratDef?.universe_filters)) ? 'not-allowed' : 'pointer',
            width: '100%',
            marginTop: 8,
            opacity: (loading || !selectedStrategy || isSelectedStratRiskInvalid || !(selectedDataset || stratDef?.universe_filters)) ? 0.35 : 1,
            boxShadow: hoveredBtn === "run" && !(loading || !selectedStrategy || isSelectedStratRiskInvalid || !(selectedDataset || stratDef?.universe_filters)) ? '0 0 14px rgba(216, 122, 61, 0.5)' : 'none',
            transform: activeBtn === "run" && !(loading || !selectedStrategy || isSelectedStratRiskInvalid || !(selectedDataset || stratDef?.universe_filters)) ? 'scale(0.98)' : hoveredBtn === "run" && !(loading || !selectedStrategy || isSelectedStratRiskInvalid || !(selectedDataset || stratDef?.universe_filters)) ? 'scale(1.015)' : 'scale(1)',
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
