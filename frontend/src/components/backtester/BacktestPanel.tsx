"use client";

import React, { useEffect, useState, useRef } from "react";
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
  max_locates: number;
  locates_random?: boolean;
  locates_random_min?: number;
  locates_random_max?: number;
  locates_seed?: number;
  ev_gate_enabled?: boolean;
  ev_gate_window?: number;
  ev_gate_by?: "trades" | "dias";
  ev_gate_default_pct?: number;
  ev_gate_min_trades?: number;
  // Coste de Black Swan (Jaume 2026-09-11). Ver backend/app/services/bswan.py.
  bswan_enabled?: boolean;
  bswan_mode?: "mercado" | "manual";
  bswan_threshold_pct?: number;
  bswan_slippage_pct?: number;
  bswan_partition_pct?: number;
  bswan_minutes?: number;
  // Coste de halts (Jaume 2026-09-12). Ver backend/app/services/halts.py.
  halts_enabled?: boolean;
  halts_mode?: "primero" | "n";
  halts_n?: number;
  halts_slippage_pct?: number;
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
    locate_type?: "PERCENT" | "FLAT";
    max_locates?: number;
    locates_random?: boolean;
    locates_random_min?: number;
    locates_random_max?: number;
    locates_seed?: number;
    ev_gate_enabled?: boolean;
    ev_gate_window?: number;
    ev_gate_by?: "trades" | "dias";
    ev_gate_default_pct?: number;
    ev_gate_min_trades?: number;
    bswan_enabled?: boolean;
    bswan_mode?: "mercado" | "manual";
    bswan_threshold_pct?: number;
    bswan_slippage_pct?: number;
    bswan_partition_pct?: number;
    bswan_minutes?: number;
    halts_enabled?: boolean;
    halts_mode?: "primero" | "n";
    halts_n?: number;
    halts_slippage_pct?: number;
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
  // Tope de locates: cuantos paquetes de 100 acciones como maximo se esta
  // dispuesto a alquilar por ticker-dia. 0 = sin tope (comportamiento previo).
  const [maxLocates, setMaxLocates] = useState(0);
  // Locates aleatorios (Jaume 2026-09-08). "fijo" = el precio unico de siempre;
  // "aleatorio" = sorteo por ticker-dia dentro de [min, max], sesgado por el
  // precio de la accion y determinista por semilla.
  const [locatesMode, setLocatesMode] = useState<"fijo" | "aleatorio">("fijo");
  const [locatesMin, setLocatesMin] = useState(1);
  const [locatesMax, setLocatesMax] = useState(10);
  const [locatesSeed, setLocatesSeed] = useState(1);
  const useLocatesRandom = useLocates && locatesMode === "aleatorio";
  // Puerta por EV (fase 2). Solo tiene sentido con locates aleatorios.
  const [evGate, setEvGate] = useState(false);
  const [evGateWindow, setEvGateWindow] = useState(30);
  const [evGateBy, setEvGateBy] = useState<"trades" | "dias">("trades");
  const [evGateDefault, setEvGateDefault] = useState(2);
  const [evGateMinTrades, setEvGateMinTrades] = useState(10);
  const useEvGate = useLocatesRandom && evGate;
  // COSTE DE BLACK SWAN (Jaume 2026-09-11). Ver backend/app/services/bswan.py.
  // "mercado" = el motor cierra en la vela del mechazo a un precio penalizado
  // (por tramos si la posicion supera la particion); "manual" = cierra N
  // minutos despues, con el stop suspendido entre medias.
  const [useBswan, setUseBswan] = useState(false);
  const [bswanMode, setBswanMode] = useState<"mercado" | "manual">("mercado");
  const [bswanThreshold, setBswanThreshold] = useState(200);
  const [bswanSlippage, setBswanSlippage] = useState(100);
  const [bswanPartition, setBswanPartition] = useState(0);
  const [bswanMinutes, setBswanMinutes] = useState(15);
  // COSTE DE HALTS (Jaume 2026-09-12). Ver backend/app/services/halts.py.
  // "primero" = sale al primer halt que pille la posicion; "n" = al halt
  // numero N del dia (contando desde la apertura). Sale en la reapertura,
  // penalizado; no vuelve a operar ese ticker-dia.
  const [useHalts, setUseHalts] = useState(false);
  const [haltsMode, setHaltsMode] = useState<"primero" | "n">("primero");
  const [haltsN, setHaltsN] = useState(2);
  const [haltsSlippage, setHaltsSlippage] = useState(5);
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
      if (savedState.maxLocates !== undefined) setMaxLocates(savedState.maxLocates);
      if (savedState.locatesMode !== undefined) setLocatesMode(savedState.locatesMode);
      if (savedState.locatesMin !== undefined) setLocatesMin(savedState.locatesMin);
      if (savedState.locatesMax !== undefined) setLocatesMax(savedState.locatesMax);
      if (savedState.locatesSeed !== undefined) setLocatesSeed(savedState.locatesSeed);
      if (savedState.evGate !== undefined) setEvGate(savedState.evGate);
      if (savedState.evGateWindow !== undefined) setEvGateWindow(savedState.evGateWindow);
      if (savedState.evGateBy !== undefined) setEvGateBy(savedState.evGateBy);
      if (savedState.evGateDefault !== undefined) setEvGateDefault(savedState.evGateDefault);
      if (savedState.evGateMinTrades !== undefined) setEvGateMinTrades(savedState.evGateMinTrades);
      if (savedState.useBswan !== undefined) setUseBswan(savedState.useBswan);
      if (savedState.bswanMode !== undefined) setBswanMode(savedState.bswanMode);
      if (savedState.bswanThreshold !== undefined) setBswanThreshold(savedState.bswanThreshold);
      if (savedState.bswanSlippage !== undefined) setBswanSlippage(savedState.bswanSlippage);
      if (savedState.bswanPartition !== undefined) setBswanPartition(savedState.bswanPartition);
      if (savedState.bswanMinutes !== undefined) setBswanMinutes(savedState.bswanMinutes);
      if (savedState.useHalts !== undefined) setUseHalts(savedState.useHalts);
      if (savedState.haltsMode !== undefined) setHaltsMode(savedState.haltsMode);
      if (savedState.haltsN !== undefined) setHaltsN(savedState.haltsN);
      if (savedState.haltsSlippage !== undefined) setHaltsSlippage(savedState.haltsSlippage);
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

  // Tour guiado / asistente Edgie: rellena el formulario desde un evento externo
  // (mismo contrato que dispararía backtest.fill_form). Solo aplica las claves enviadas.
  useEffect(() => {
    const onFill = (e: Event) => {
      const d = (e as CustomEvent).detail || {};
      if (d.initCash !== undefined) setInitCash(Number(d.initCash));
      if (d.riskType !== undefined) setRiskType(d.riskType);
      if (d.riskR !== undefined) setRiskR(Number(d.riskR));
      if (d.feeType !== undefined) setFeeType(d.feeType);
      if (d.fees !== undefined) setFees(Number(d.fees));
      if (d.slippage !== undefined) setSlippage(Number(d.slippage));
      if (Array.isArray(d.marketSessions)) setMarketSessions(d.marketSessions);
      if (d.customStartTime !== undefined) setCustomStartTime(d.customStartTime);
      if (d.customEndTime !== undefined) setCustomEndTime(d.customEndTime);
      if (d.isPercent !== undefined) setIsPercent(Number(d.isPercent));
    };
    window.addEventListener("fill-backtest-form", onFill);
    return () => window.removeEventListener("fill-backtest-form", onFill);
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
      locates_cost: useLocates && !useLocatesRandom ? locatesCost : 0,
      max_locates: useLocates ? maxLocates : 0,
      locates_random: useLocatesRandom,
      locates_random_min: useLocatesRandom ? locatesMin : 0,
      locates_random_max: useLocatesRandom ? locatesMax : 0,
      locates_seed: useLocatesRandom ? locatesSeed : 0,
      ev_gate_enabled: useEvGate,
      ev_gate_window: useEvGate ? evGateWindow : 0,
      ev_gate_by: evGateBy,
      ev_gate_default_pct: useEvGate ? evGateDefault : 0,
      ev_gate_min_trades: useEvGate ? evGateMinTrades : 0,
      bswan_enabled: useBswan,
      bswan_mode: bswanMode,
      bswan_threshold_pct: useBswan ? bswanThreshold : 0,
      bswan_slippage_pct: useBswan ? bswanSlippage : 0,
      bswan_partition_pct: useBswan ? bswanPartition : 0,
      bswan_minutes: useBswan ? bswanMinutes : 0,
      halts_enabled: useHalts,
      halts_mode: haltsMode,
      halts_n: useHalts ? haltsN : 0,
      halts_slippage_pct: useHalts ? haltsSlippage : 0,
      monthly_expenses: useMonthlyExpenses ? monthlyExpenses : 0,
      look_ahead_prevention: lookAheadPrevention,
      is_percent: isPercent,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedDataset, initCash, riskR, riskType, fixedRatioDelta,
    fees, feeType, slippage, startDate, endDate, marketSessions,
    customStartTime, customEndTime, useLocates, locatesCost, maxLocates,
    useLocatesRandom, locatesMin, locatesMax, locatesSeed,
    useEvGate, evGateWindow, evGateBy, evGateDefault, evGateMinTrades,
    useBswan, bswanMode, bswanThreshold, bswanSlippage, bswanPartition, bswanMinutes,
    useHalts, haltsMode, haltsN, haltsSlippage,
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
        maxLocates,
        locatesMode,
        locatesMin,
        locatesMax,
        locatesSeed,
        evGate,
        evGateWindow,
        evGateBy,
        evGateDefault,
        evGateMinTrades,
        useBswan,
        bswanMode,
        bswanThreshold,
        bswanSlippage,
        bswanPartition,
        bswanMinutes,
        useHalts,
        haltsMode,
        haltsN,
        haltsSlippage,
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
    useLocates, locatesCost, maxLocates, locatesMode, locatesMin, locatesMax, locatesSeed,
    evGate, evGateWindow, evGateBy, evGateDefault, evGateMinTrades,
    useBswan, bswanMode, bswanThreshold, bswanSlippage, bswanPartition, bswanMinutes,
    useHalts, haltsMode, haltsN, haltsSlippage,
    useMonthlyExpenses, monthlyExpenses
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
      locates_cost: useLocates && !useLocatesRandom ? locatesCost : 0,
      // FLAT = coste en $ por cada 100 acciones (lo que cuesta un locate),
      // no % del riesgo (decisión de producto, Jaume 2026-07-07).
      locate_type: "FLAT",
      // Tope de locates: 0 = sin tope. Solo aplica en corto.
      max_locates: useLocates ? maxLocates : 0,
      // Locates aleatorios: sustituyen al precio fijo cuando estan activos.
      locates_random: useLocatesRandom,
      locates_random_min: useLocatesRandom ? locatesMin : 0,
      locates_random_max: useLocatesRandom ? locatesMax : 0,
      locates_seed: useLocatesRandom ? locatesSeed : 0,
      ev_gate_enabled: useEvGate,
      ev_gate_window: useEvGate ? evGateWindow : 0,
      ev_gate_by: evGateBy,
      ev_gate_default_pct: useEvGate ? evGateDefault : 0,
      ev_gate_min_trades: useEvGate ? evGateMinTrades : 0,
      // Coste de Black Swan. Apagado = el backend ni lo mira.
      bswan_enabled: useBswan,
      bswan_mode: bswanMode,
      bswan_threshold_pct: useBswan ? bswanThreshold : 0,
      bswan_slippage_pct: useBswan ? bswanSlippage : 0,
      bswan_partition_pct: useBswan ? bswanPartition : 0,
      bswan_minutes: useBswan ? bswanMinutes : 0,
      // Coste de halts. Apagado = el backend ni lo mira.
      halts_enabled: useHalts,
      halts_mode: haltsMode,
      halts_n: useHalts ? haltsN : 0,
      halts_slippage_pct: useHalts ? haltsSlippage : 0,
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
    <div data-helper="panel-root" style={{
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
                {/* El nombre de la estrategia que se va a ejecutar. Sin él, dos
                    estrategias distintas daban resúmenes indistinguibles y era
                    fácil creer que se estaba corriendo otra cosa. */}
                {(currentStrat?.name || (stratDef as any)?.name) && (
                  <div style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 11.5,
                    fontWeight: 700,
                    color: 'var(--color-ec-copper)',
                    lineHeight: '1.3',
                    wordBreak: 'break-word',
                  }}>{currentStrat?.name || (stratDef as any)?.name}</div>
                )}

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
                      // El motor hace la UNIÓN de todas las sesiones marcadas.
                      // Con «custom» + una preajustada eso da un horario que no
                      // es el que se lee arriba: RTH + 04:00-12:00 corre hasta
                      // las 16:00. Desde el 6-sep-2026 la interfaz no deja
                      // marcar las dos, pero las estrategias guardadas antes
                      // siguen ahí y hay que decirles la verdad.
                      const PRESETS: Record<string, [string, string]> = {
                        pre: ['04:00', '09:30'], rth: ['09:30', '16:00'], post: ['16:00', '20:00'],
                      };
                      const mezcla = sessions.includes('custom') && sessions.some((s: string) => s in PRESETS);
                      let efectiva = '';
                      if (mezcla) {
                        const rangos: [string, string][] = sessions.map((s: string) =>
                          s === 'custom'
                            ? [stratDef?.custom_start_time || '09:30', stratDef?.custom_end_time || '16:00'] as [string, string]
                            : PRESETS[s]
                        ).filter(Boolean);
                        const desde = rangos.map(r => r[0]).sort()[0];
                        const hasta = rangos.map(r => r[1]).sort().slice(-1)[0];
                        efectiva = `${desde} - ${hasta}`;
                      }
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
                          {mezcla && (
                            <div style={{ color: 'var(--color-ec-loss)', fontWeight: 700, marginTop: 2 }}>
                              ⚠️ Se SUMAN: la sesión real del backtest es {efectiva} ET.
                              Desmarca una de las dos en la estrategia.
                            </div>
                          )}
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
                      
                      // Stop Loss. Un stop de ESTRUCTURA no lleva un número:
                      // lleva el nivel (Previous Max, HOD/LOD...), su operador y
                      // un margen. Antes se imprimía como si fuese un % y salía
                      // "Stop Loss: Previous Max%".
                      if (rm.use_hard_stop && rm.hard_stop) {
                        const hs = rm.hard_stop;
                        if (hs.type === 'Market Structure (HOD/LOD)') {
                          const op = hs.operator ? ` ${hs.operator}` : '';
                          const off = (hs.offset_pct != null && hs.offset_pct !== 0) ? ` ${hs.offset_pct > 0 ? '+' : ''}${hs.offset_pct}%` : '';
                          stopList.push(`Stop Loss (estructura): ${hs.value}${op}${off}`);
                        } else if (hs.value > 0) {
                          stopList.push(`Stop Loss: ${hs.value}${hs.type === 'Percentage' ? '%' : 'R'}`);
                        }
                      }
                      if (rm.trailing_stop?.active) {
                        const ts = rm.trailing_stop;
                        const bufferVal = ts.type === 'Percentage' ? `${ts.buffer_pct}%` : `${ts.buffer_r}R`;
                        stopList.push(`Trailing (${ts.type === 'Percentage' ? '%' : 'R'}): ${bufferVal}`);
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
                      
                      // Tamaño por stop loss
                      if (rm.size_by_sl) {
                        stopList.push("Tamaño por SL");
                      }

                      // Salida por tiempo
                      if (rm.use_time_exit) {
                        stopList.push(`Salida por tiempo: ${rm.time_exit_value ?? ''}${rm.time_exit_session ? ` (${rm.time_exit_session})` : ''}`);
                      }

                      if (stopList.length === 0) return null;

                      return (
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>RIESGO / STOPS: </span>
                          <span style={{ color: 'var(--color-ec-text-primary)' }}>{stopList.join(" | ")}</span>
                        </div>
                      );
                    })()}

                    {/* Timeframes de los bloques de lógica. */}
                    {(() => {
                      const te = stratDef?.entry_logic?.timeframe;
                      const tx = stratDef?.exit_logic?.timeframe;
                      const cd = stratDef?.entry_logic?.candle_delay;
                      const partes: string[] = [];
                      if (te) partes.push(`Entrada ${te}`);
                      if (tx) partes.push(`Salida ${tx}`);
                      if (cd) partes.push(`Retardo ${cd} velas`);
                      if (!partes.length) return null;
                      return (
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>TEMPORALIDAD: </span>
                          <span style={{ color: 'var(--color-ec-text-primary)' }}>{partes.join(" | ")}</span>
                        </div>
                      );
                    })()}

                    {/* Piramidación. No aparecía en el resumen, así que una
                        estrategia con pirámide se veía idéntica a una sin
                        ella — justo lo que hace falta distinguir. */}
                    {(() => {
                      const pyr = stratDef?.pyramiding;
                      const niveles = pyr?.levels || [];
                      if (!niveles.length) return null;
                      const txt = niveles.map((l: any, i: number) => {
                        const unidad = (l.unit ?? 'pct') === 'usd' ? '$' : '%';
                        const accion = l.action === 'reduce' ? 'Quita' : 'Añade';
                        const base = (l.unit ?? 'pct') === 'usd'
                          ? ''
                          : (l.action === 'reduce' ? ' de la posición' : ' del equity');
                        const veces = (l.times ?? 1) > 1 ? ` ×${l.times}` : '';
                        return `${i + 1}) ${accion} ${l.capital_pct}${unidad}${base}${veces}`;
                      }).join(" | ");
                      return (
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--color-ec-copper)' }}>PIRAMIDACIÓN: </span>
                          <span style={{ color: 'var(--color-ec-text-primary)' }}>
                            {txt}{pyr?.mode === 'sequential' ? ' · secuencial' : ''}
                            {pyr?.timeframe ? ` · ${pyr.timeframe}` : ''}
                          </span>
                        </div>
                      );
                    })()}

                    {/* Scalping. Mismo motivo que la piramidación: con el
                        bloque, la entrada y la salida lógicas significan otra
                        cosa (abren y cierran la ventana), y eso hay que verlo. */}
                    {(() => {
                      const sc = stratDef?.scalping;
                      if (!sc?.root_condition?.conditions?.length) return null;
                      const partes = [
                        `gatillo con ${sc.root_condition.conditions.length} condición${sc.root_condition.conditions.length === 1 ? '' : 'es'}`,
                        sc.max_minutes > 0 ? `salida a los ${sc.max_minutes} min` : 'sin salida por tiempo propia',
                        sc.cooldown_bars > 0 ? `pausa de ${sc.cooldown_bars} vela${sc.cooldown_bars === 1 ? '' : 's'}` : 'sin pausa',
                        `${sc.capital_pct ?? 100}% de la cifra del panel por entrada`,
                      ];
                      return (
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--color-ec-copper)' }}>SCALPING: </span>
                          <span style={{ color: 'var(--color-ec-text-primary)' }}>
                            {partes.join(' · ')}{sc.timeframe ? ` · ${sc.timeframe}` : ''}
                            {' (la entrada lógica abre la ventana y la salida lógica la cierra)'}
                          </span>
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

        <div data-helper="cfg-capital" style={{
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
              }}
                // El importe se cobra DOS veces, una por operacion (compra y
                // venta). En FLAT `fees` es ademas $ por accion, asi que el
                // total de un trade es fees x acciones x 2.
                title={feeType === "PERCENT"
                  ? "Porcentaje del valor operado. Se cobra en la compra y en la venta."
                  : "$ por acción. Se cobra en la compra y en la venta: 0,003 con 100 acciones = 0,30 € + 0,30 €."}
              >
                Fees {feeType === "PERCENT" ? "(%)" : "($/acc)"}
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
                {/* El desplegable elige la UNIDAD del importe ($ o %); las dos
                    se cobran igual en la compra y en la venta. El "$" a secas
                    era ambiguo y ademas describia el modelo viejo, que ignoraba
                    el numero de acciones. La explicacion completa esta en el
                    title de la etiqueta de arriba. */}
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

        {/* COSTES OPCIONALES. Un solo bloque ordenado: cada coste es una fila
            «etiqueta | control» y lo que se despliega queda DENTRO del bloque.
            Antes eran cuadros sueltos y el selector Fijo/Aleatorio se salía por
            debajo del panel. Mismo criterio que el genético: borde de 1 px sin
            radio, filas separadas por hairline, controles cuadrados. */}
        {(() => {
          const et: React.CSSProperties = {
            fontFamily: 'var(--color-ec-sans)', fontSize: 11, fontWeight: 500,
            color: 'var(--color-ec-text-secondary)', display: 'inline-flex',
            alignItems: 'center', gap: 2, whiteSpace: 'nowrap',
          };
          const sub: React.CSSProperties = { ...et, color: 'var(--color-ec-text-muted)', paddingLeft: 22 };
          const inp: React.CSSProperties = {
            width: 62, height: 26, boxSizing: 'border-box', padding: '0 7px',
            backgroundColor: 'var(--color-ec-bg-elevated)',
            border: '1px solid var(--color-ec-border)', borderRadius: 0,
            fontFamily: 'var(--color-ec-mono)', fontSize: 11,
            color: 'var(--color-ec-text-primary)', outline: 'none', textAlign: 'right',
          };
          const nota: React.CSSProperties = {
            fontFamily: 'var(--color-ec-sans)', fontSize: 10,
            color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap',
          };
          const filas: React.ReactNode[] = [];

          filas.push(
            <React.Fragment key="locates">
              <label className="flex items-center gap-2 cursor-pointer" style={{ whiteSpace: 'nowrap' }}>
                <input
                  type="checkbox"
                  checked={useLocates}
                  onChange={() => setUseLocates(!useLocates)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span style={et}>
                  Loc. ($ / 100 acc.)
                  <InfoTooltip
                    position="left"
                    width={280}
                    text="Coste en dólares de cada locate: lo que cuestan 100 acciones reutilizables en corto. Se cobra UNA sola vez por ticker y día (no al comprar y otra al vender), por cada bloque de 100 acciones del tamaño máximo en corto de ese día. Ejemplo: si el locate cuesta 3$ y controlas 1000 acciones (10 locates), pagas 30$ ese día. «Fijo» usa el mismo precio toda la corrida; «Aleatorio» sortea uno distinto por ticker y día dentro de un rango."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
              </label>
              {useLocates ? (
                <div style={{ display: 'flex', border: '1px solid var(--color-ec-border)' }}>
                  {(["fijo", "aleatorio"] as const).map((m, i) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setLocatesMode(m)}
                      style={{
                        background: locatesMode === m ? 'var(--color-ec-copper)' : 'var(--color-ec-bg-base)',
                        color: locatesMode === m ? 'var(--color-ec-copper-text)' : 'var(--color-ec-text-secondary)',
                        fontWeight: locatesMode === m ? 600 : 400,
                        border: 0, borderLeft: i ? '1px solid var(--color-ec-border)' : undefined,
                        fontFamily: 'var(--color-ec-sans)', fontSize: 10, height: 24,
                        padding: '0 9px', cursor: 'pointer',
                      }}
                    >
                      {m === "fijo" ? "Fijo" : "Aleatorio"}
                    </button>
                  ))}
                </div>
              ) : <span />}
            </React.Fragment>
          );

          if (useLocates && locatesMode === "fijo") {
            filas.push(
              <React.Fragment key="precio">
                <span style={sub}>Precio del paquete</span>
                <input type="number" step="0.01" value={locatesCost} style={inp}
                       onChange={(e) => setLocatesCost(Number(e.target.value))} />
              </React.Fragment>
            );
          }

          if (useLocatesRandom) {
            filas.push(
              <React.Fragment key="rango">
                <span style={sub}>
                  Rango
                  <InfoTooltip
                    position="left"
                    width={320}
                    text="En vez de un precio fijo, cada ticker y día recibe un precio de locate distinto, sorteado dentro de este rango (en dólares por paquete de 100 acciones). El sorteo NO es a ciegas: las acciones baratas caen hacia la parte baja del rango y las caras hacia la alta, porque así funcionan los brokers. Ejemplo con rango 1-10: una acción a 0,30 $ suele salir entre 2 y 4; una a 3 $ entre 4,5 y 9; una a 15 $ entre 6,5 y 10. El precio de referencia es la primera vela del día (04:00), así que no mira el futuro. Se cobra como siempre: paquetes enteros, una vez por ticker y día, sobre el máximo en corto de ese día."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <input type="number" step="0.1" min={0} value={locatesMin} style={{ ...inp, width: 46 }}
                         onChange={(e) => setLocatesMin(Math.max(0, Number(e.target.value) || 0))} />
                  <span style={nota}>a</span>
                  <input type="number" step="0.1" min={0} value={locatesMax} style={{ ...inp, width: 46 }}
                         onChange={(e) => setLocatesMax(Math.max(0, Number(e.target.value) || 0))} />
                </span>
              </React.Fragment>
            );
            filas.push(
              <React.Fragment key="semilla">
                <span style={sub}>
                  Semilla
                  <InfoTooltip
                    position="left"
                    width={320}
                    text="Un sorteo necesita un número de arranque: eso es la semilla. Con la MISMA semilla, la corrida saca exactamente los mismos precios de locate cada vez, así que si cambias otro parámetro y el resultado se mueve, sabes que es por el parámetro y no por la suerte del sorteo. Con OTRA semilla tienes otro «mundo» de precios de locate: los mismos días, pero a otros precios. Correr varias semillas y comparar es la forma de ver entre cuánto y cuánto puedes acabar según te toquen los locates, que es la pregunta de verdad. Cualquier número entero vale; 1, 2, 3… es lo normal."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  {locatesMax <= locatesMin && (
                    <span style={{ ...nota, color: 'var(--color-ec-warning)' }}>máx. debe superar al mín.</span>
                  )}
                  <input type="number" step="1" min={0} value={locatesSeed} style={inp}
                         onChange={(e) => setLocatesSeed(Math.max(0, Math.floor(Number(e.target.value) || 0)))} />
                </span>
              </React.Fragment>
            );
            filas.push(
              <React.Fragment key="puerta">
                <label className="flex items-center gap-2 cursor-pointer" style={{ whiteSpace: 'nowrap', paddingLeft: 22 }}>
                  <input
                    type="checkbox"
                    checked={evGate}
                    onChange={() => setEvGate(!evGate)}
                    className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                  />
                  <span style={et}>
                    Puerta por EV
                    <InfoTooltip
                      position="left"
                      width={340}
                      text="Es la cuenta del /evf del bot, hecha dentro del backtest y trade a trade: con el locate sorteado de ese día, ¿cuánto tiene que moverse el precio a favor solo para pagarlo (el «fade necesario»)? Si el EV de la estrategia en ese momento no lo cubre, NO se entra. QUÉ EV MIRA: el «EV en sombra». El backtest corre DOS veces: la primera sin puerta, y de ahí sale lo que rinden TODAS las señales de la estrategia en % del precio (cortos, bruto de locates); la segunda corre con la puerta y, en cada entrada, mira el EV medio de las señales de la primera que ya habían CERRADO antes de ese instante — nunca el futuro. Es el EV de la estrategia, no el de lo que se ejecutó: es el que hoy le das a mano al /evf. En vivo tendrás el de tus resultados, que arrastra un sesgo (si rechazas, no entra información nueva); esa variante queda para más adelante. Solo mira cortos; las reentradas que caben en lo ya alquilado pasan gratis."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                </label>
                {evGate ? (
                  <div style={{ display: 'flex', border: '1px solid var(--color-ec-border)' }}>
                    {(["trades", "dias"] as const).map((m, i) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setEvGateBy(m)}
                        title="Sobre qué se calcula el EV rodante: los últimos N trades cerrados, o los trades cerrados en los últimos N días"
                        style={{
                          background: evGateBy === m ? 'var(--color-ec-copper)' : 'var(--color-ec-bg-base)',
                          color: evGateBy === m ? 'var(--color-ec-copper-text)' : 'var(--color-ec-text-secondary)',
                          fontWeight: evGateBy === m ? 600 : 400,
                          border: 0, borderLeft: i ? '1px solid var(--color-ec-border)' : undefined,
                          fontFamily: 'var(--color-ec-sans)', fontSize: 10, height: 24,
                          padding: '0 9px', cursor: 'pointer',
                        }}
                      >
                        {m === "trades" ? "Trades" : "Días"}
                      </button>
                    ))}
                  </div>
                ) : <span />}
              </React.Fragment>
            );
            if (evGate) {
              filas.push(
                <React.Fragment key="ventana">
                  <span style={{ ...sub, paddingLeft: 44 }}>
                    Ventana ({evGateBy === "trades" ? "trades" : "días"})
                    <InfoTooltip
                      position="left"
                      width={300}
                      text="Cuántos trades hacia atrás (o cuántos días hacia atrás) se miran para sacar el EV en cada entrada. Corta (10-20 trades) reacciona rápido pero se mueve mucho con la suerte; larga (50-100) es estable pero tarda en enterarse de que el edge ha cambiado. 30 trades es un punto medio razonable para empezar."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <input type="number" step="1" min={1} value={evGateWindow} style={inp}
                         onChange={(e) => setEvGateWindow(Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
                </React.Fragment>
              );
              filas.push(
                <React.Fragment key="evdef">
                  <span style={{ ...sub, paddingLeft: 44 }}>
                    EV por defecto (%)
                    <InfoTooltip
                      position="left"
                      width={300}
                      text="El EV que se asume mientras aún no hay historia suficiente (al principio de la corrida, o cuando en la ventana hay menos trades que el mínimo de abajo). En % del precio, como el fade: 2 significa que se da por hecho que la acción se mueve un 2 % a favor de media. Ponlo parecido al EV real que le das al /evf; si lo pones muy alto, al principio entra en todo; muy bajo, no entra en nada hasta que hay datos."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <input type="number" step="0.1" min={0} value={evGateDefault} style={inp}
                         onChange={(e) => setEvGateDefault(Math.max(0, Number(e.target.value) || 0))} />
                </React.Fragment>
              );
              filas.push(
                <React.Fragment key="mintr">
                  <span style={{ ...sub, paddingLeft: 44 }}>
                    Mín. trades
                    <InfoTooltip
                      position="left"
                      width={300}
                      text="Por debajo de este número de trades cerrados en la ventana, el EV rodante no se fía de sí mismo y usa el EV por defecto. Evita que dos trades sueltos decidan por toda una semana."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <input type="number" step="1" min={1} value={evGateMinTrades} style={inp}
                         onChange={(e) => setEvGateMinTrades(Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
                </React.Fragment>
              );
            }
          }

          if (useLocates) {
            filas.push(
              <React.Fragment key="tope">
                <span style={sub}>
                  Máx. locates
                  <InfoTooltip
                    position="left"
                    width={300}
                    text="Tope de paquetes de 100 acciones que se está dispuesto a alquilar por ticker y día. Limita dinámicamente el tamaño de la posición en CORTO a (máx. locates × 100) acciones: si con el riesgo configurado tocaría comprar más locates de los permitidos, se entra con menos acciones en vez de pagarlos. Ejemplo con tope 5: a 5$ y 1.000$ de exposición harían falta 2 locates y entra entero; a 0,50$ harían falta 20, así que entra con 500 acciones (250$) y paga 5 locates. 0 = sin tope. No afecta a las posiciones en largo."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <span style={nota}>{maxLocates > 0 ? `máx. ${maxLocates * 100} acc.` : 'sin tope'}</span>
                  <input type="number" min={0} step="1" value={maxLocates} style={inp}
                         onChange={(e) => setMaxLocates(Math.max(0, Math.floor(Number(e.target.value) || 0)))} />
                </span>
              </React.Fragment>
            );
          }

          // COSTE DE BLACK SWAN (Jaume 2026-09-11). Fila madre con el selector
          // A mercado | Manual, y debajo lo que pide cada modo.
          filas.push(
            <React.Fragment key="bswan">
              <label className="flex items-center gap-2 cursor-pointer" style={{ whiteSpace: 'nowrap' }}>
                <input
                  type="checkbox"
                  checked={useBswan}
                  onChange={() => setUseBswan(!useBswan)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span style={et}>
                  Coste BSwan
                  <InfoTooltip
                    position="left"
                    width={360}
                    text="Simula qué habría pasado si, en cada trade que estuvo dentro durante una «mecha Black Swan», el mechazo te hubiera sacado. Una mecha cuenta como Black Swan cuando la vela de 1 minuto se dispara sobre su apertura más del umbral de abajo (en largo, hacia abajo) Y ADEMÁS cruza tu stop: un fogonazo que ni llega al stop no barre ninguna orden y el trade sigue abierto. Sin stop configurado no hay Black Swan. Es un coste opcional: NO cambia qué se opera, solo cómo salen esos trades, y vale para saber cuántos te habrías comido de verdad. A MERCADO: el motor cierra en esa misma vela a un precio peor que el stop, penalizado con el slippage BS y, si pones una partición, por tramos de ese % de la posición cada vez peores. MANUAL: no cierra en la vela (modela un stop mental, sin orden puesta que la barrida pueda ejecutar): suspende stop, TP y parciales y cierra toda la posición N minutos después. Solo mira mientras se está dentro. Fuerza el motor Python (más lento que el kernel). La mecha se mide sobre las velas del lago, que a veces esconden el pico real: el resultado es un suelo, no un techo. En Trades las salidas afectadas llevan la etiqueta BS."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
              </label>
              {useBswan ? (
                // Mas estrecho que el selector de locates y con margen a la
                // izquierda: el «?» de la etiqueta quedaba pegado a los botones.
                <div style={{ display: 'flex', border: '1px solid var(--color-ec-border)', marginLeft: 10 }}>
                  {(["mercado", "manual"] as const).map((m, i) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setBswanMode(m)}
                      title={m === "mercado"
                        ? "A mercado: cierra en la vela del mechazo (si además cruza tu stop), a un precio penalizado con el slippage BS (por tramos si hay partición)"
                        : "Manual: no cierra en la vela; cierra toda la posición N minutos después, con el stop suspendido entre medias"}
                      style={{
                        background: bswanMode === m ? 'var(--color-ec-copper)' : 'var(--color-ec-bg-base)',
                        color: bswanMode === m ? 'var(--color-ec-copper-text)' : 'var(--color-ec-text-secondary)',
                        fontWeight: bswanMode === m ? 600 : 400,
                        border: 0, borderLeft: i ? '1px solid var(--color-ec-border)' : undefined,
                        fontFamily: 'var(--color-ec-sans)', fontSize: 10, height: 24,
                        padding: '0 6px', cursor: 'pointer',
                      }}
                    >
                      {m === "mercado" ? "Mercado" : "Manual"}
                    </button>
                  ))}
                </div>
              ) : <span />}
            </React.Fragment>
          );

          if (useBswan) {
            filas.push(
              <React.Fragment key="bs-umbral">
                <span style={sub}>
                  Umbral BS (%)
                  <InfoTooltip
                    position="left"
                    width={320}
                    text="Tamaño mínimo de la mecha para contarla como Black Swan: distancia de la apertura al máximo de la vela de 1 minuto (al mínimo, en largo), en % de la apertura. 100 = el precio se duplicó dentro del minuto; 200 = se triplicó. Solo se miran las velas en las que la posición estaba abierta, y solo cuenta si esa vela además cruza tu stop (fijo, estructural, ATR o trailing): si la mecha se queda por debajo del stop, no es Black Swan y el trade sigue. Cuanto más bajo el umbral, más trades se cierran por BS."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
                <input type="number" step="10" min={1} value={bswanThreshold} style={inp}
                       onChange={(e) => setBswanThreshold(Math.max(1, Number(e.target.value) || 1))} />
              </React.Fragment>
            );
            if (bswanMode === "mercado") {
              filas.push(
                <React.Fragment key="bs-slip">
                  <span style={sub}>
                    Slippage BS (%)
                    <InfoTooltip
                      position="left"
                      width={320}
                      text="Cuánto peor que el stop se ejecuta el cierre, en % del nivel del stop que la vela cruzó (o del trailing, si era el que mandaba). Ejemplo: corto en 1 $ con stop al 20 % (debías salir en 1,20 $); con 100 % sales a 2,40 $. No se recorta al máximo de la vela: es una penalización, no un fill, y las velas de minuto esconden los picos. Sustituye al slippage normal en esa salida."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <input type="number" step="10" min={0} value={bswanSlippage} style={inp}
                         onChange={(e) => setBswanSlippage(Math.max(0, Number(e.target.value) || 0))} />
                </React.Fragment>
              );
              filas.push(
                <React.Fragment key="bs-particion">
                  <span style={sub}>
                    Partición (% posición)
                    <InfoTooltip
                      position="left"
                      width={330}
                      text="Qué parte de la posición sale en cada tramo, en % de la posición que haya en ese momento, para que valga igual con 300 acciones que con 30.000. Cada tramo paga un escalón más de slippage BS: con 50 % y slippage del 100 %, la mitad sale al +100 % y la otra mitad al +200 %; con 30 %, sale un 30 % al +100 %, otro 30 % al +200 %, otro 30 % al +300 % y el 10 % restante al +400 %. 0 (o 100) = toda la posición en un solo tramo. En Trades cada tramo aparece como una ejecución («BS 1/2 +100%»)."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    {bswanPartition > 0 && bswanPartition < 100 && (
                      <span style={nota}>{Math.ceil(100 / bswanPartition)} tramos</span>
                    )}
                    <input type="number" step="10" min={0} max={100} value={bswanPartition} style={inp}
                           title="0 (o 100) = toda la posición sale en un solo tramo"
                           onChange={(e) => setBswanPartition(Math.min(100, Math.max(0, Number(e.target.value) || 0)))} />
                  </span>
                </React.Fragment>
              );
            } else {
              filas.push(
                <React.Fragment key="bs-minutos">
                  <span style={sub}>
                    Minutos hasta cerrar
                    <InfoTooltip
                      position="left"
                      width={320}
                      text="En modo manual, cuántos minutos después de la vela del mechazo se cierra TODA la posición: al cierre de la primera vela que esté a esa distancia, con el slippage normal. Entre medias no actúan el stop, el TP, los parciales ni la salida por señal (es lo que modela: no había orden en el mercado). Si antes llega el fin de sesión, el límite de tiempo o el cortacircuitos diario, mandan ellos."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <input type="number" step="1" min={1} value={bswanMinutes} style={inp}
                         onChange={(e) => setBswanMinutes(Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
                </React.Fragment>
              );
            }
          }

          // COSTE DE HALTS (Jaume 2026-09-12). Fila madre con el selector
          // Primero | N halts, y debajo el N (si toca) y el slippage.
          filas.push(
            <React.Fragment key="halts">
              <label className="flex items-center gap-2 cursor-pointer" style={{ whiteSpace: 'nowrap' }}>
                <input
                  type="checkbox"
                  checked={useHalts}
                  onChange={() => setUseHalts(!useHalts)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span style={et}>
                  Coste Halts
                  <InfoTooltip
                    position="left"
                    width={360}
                    text="Simula qué habría pasado si un halt de cotización (LULD, noticia, regulatorio) te hubiera pillado dentro. Los halts salen de la tabla exacta de Nasdaq que baja «Actualizar datos» (hora de parada, reanudación y motivo), no de las velas. PRIMERO: al primer halt que pille la posición abierta, el motor cierra TODA la posición al precio de apertura de la primera vela tras la reanudación, un % peor (el slippage de abajo). N HALTS: igual, pero solo cuando el halt es el N-ésimo del día para ese ticker, contando desde la apertura (si entras después del 3.º y N=3, el siguiente que te pille dispara). En los dos casos no se vuelve a operar ese ticker ese día. Durante el halt no se ejecuta nada: un stop cruzado en la vela de la parada no se llena. Si el halt no reabre ese día (T12, suspensión), cierra al último precio antes de parar con el mismo slippage y el trade queda marcado «atrapado». En Trades las salidas afectadas llevan la etiqueta Halt. Fuerza el motor Python."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
              </label>
              {useHalts ? (
                <div style={{ display: 'flex', border: '1px solid var(--color-ec-border)', marginLeft: 10 }}>
                  {(["primero", "n"] as const).map((m, i) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setHaltsMode(m)}
                      title={m === "primero"
                        ? "Primero: sale en la reapertura del primer halt que pille la posición"
                        : "N halts: sale en la reapertura del halt número N del día (contando desde la apertura)"}
                      style={{
                        background: haltsMode === m ? 'var(--color-ec-copper)' : 'var(--color-ec-bg-base)',
                        color: haltsMode === m ? 'var(--color-ec-copper-text)' : 'var(--color-ec-text-secondary)',
                        fontWeight: haltsMode === m ? 600 : 400,
                        border: 0, borderLeft: i ? '1px solid var(--color-ec-border)' : undefined,
                        fontFamily: 'var(--color-ec-sans)', fontSize: 10, height: 24,
                        padding: '0 6px', cursor: 'pointer',
                      }}
                    >
                      {m === "primero" ? "Primero" : "N halts"}
                    </button>
                  ))}
                </div>
              ) : <span />}
            </React.Fragment>
          );

          if (useHalts) {
            if (haltsMode === "n") {
              filas.push(
                <React.Fragment key="halts-n">
                  <span style={sub}>
                    N.º de halt que saca
                    <InfoTooltip
                      position="left"
                      width={320}
                      text="A partir de qué halt del día se sale. Se cuentan TODOS los halts del ticker ese día desde la apertura, no solo los que ocurren estando dentro: con 3, el primer halt que te pille dentro siendo el 3.º o posterior del día es el que te saca. 1 equivale al modo «Primero»."
                      style={{ display: 'inline-flex' }}
                    />
                  </span>
                  <input type="number" step="1" min={1} value={haltsN} style={inp}
                         onChange={(e) => setHaltsN(Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
                </React.Fragment>
              );
            }
            filas.push(
              <React.Fragment key="halts-slip">
                <span style={sub}>
                  Slippage halt (%)
                  <InfoTooltip
                    position="left"
                    width={320}
                    text="Cuánto peor que el precio de reapertura se ejecuta el cierre, en % de ese precio (para un corto, más arriba; para un largo, más abajo). Ejemplo: la acción reabre a 1,50 $ tras el halt y con 5 % un corto sale a 1,575 $. Sustituye al slippage normal en esa salida. Ojo: el estudio de halts midió reaperturas de mediana +2 % pero con cola larga; el precio de reapertura real ya lleva el salto, esto es solo el coste de ejecutar."
                    style={{ display: 'inline-flex' }}
                  />
                </span>
                <input type="number" step="1" min={0} value={haltsSlippage} style={inp}
                       onChange={(e) => setHaltsSlippage(Math.max(0, Number(e.target.value) || 0))} />
              </React.Fragment>
            );
          }

          filas.push(
            <React.Fragment key="gastos">
              <label className="flex items-center gap-2 cursor-pointer" style={{ whiteSpace: 'nowrap' }}>
                <input
                  type="checkbox"
                  checked={useMonthlyExpenses}
                  onChange={() => setUseMonthlyExpenses(!useMonthlyExpenses)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span style={et}>Gastos fijos / mes ($)</span>
              </label>
              {useMonthlyExpenses ? (
                <input type="number" step="1" value={monthlyExpenses} style={inp}
                       onChange={(e) => setMonthlyExpenses(Number(e.target.value))} />
              ) : <span />}
            </React.Fragment>
          );

          return (
            <div style={{ paddingTop: 16, marginTop: 12, borderTop: '0.5px solid var(--color-ec-border)' }}>
              <label style={{
                display: 'block', fontFamily: 'var(--color-ec-sans)', fontSize: 9, fontWeight: 700,
                textTransform: 'uppercase', letterSpacing: '0.12em',
                color: 'var(--color-ec-text-muted)', marginBottom: 6,
              }}>
                Costes opcionales
              </label>
              <div style={{ border: '1px solid var(--color-ec-border)', background: 'var(--color-ec-bg-surface)' }}>
                {filas.map((f, i) => (
                  <div key={i} style={{
                    display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto',
                    alignItems: 'center', gap: 8, padding: '5px 9px', minHeight: 34,
                    borderTop: i ? '0.5px solid var(--color-ec-border)' : undefined,
                  }}>
                    {f}
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
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
        data-helper="cfg-run"
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
