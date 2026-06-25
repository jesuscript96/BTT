"use client";

import { useState, useEffect, useRef, Fragment } from "react";
import { createPortal } from "react-dom";
import { EntryLogicBuilder } from "@/components/strategy-builder/EntryLogic";
import { ExitLogicBuilder } from "@/components/strategy-builder/ExitLogic";
import { RiskManagementComponent } from "@/components/strategy-builder/RiskManagement";
import { validateStrategyLogic } from "@/lib/strategyValidation";
import {
  initialEntryLogic,
  initialExitLogic,
  initialRiskManagement,
  IndicatorType,
  Comparator,
  Timeframe,
} from "@/types/strategy";
import type {
  EntryLogic as EntryLogicType,
  ExitLogic as ExitLogicType,
  RiskManagement as RiskManagementType,
  ConditionGroup,
  PostGapPrecondition,
} from "@/types/strategy";
import { INDICATOR_LABELS, COMPARATOR_LABELS, ConditionRow } from "@/components/strategy-builder/ConditionBuilder";
import { Clock, Save } from "lucide-react";
import { fetchDatasets, fetchAvailableDateRange, type Dataset } from "@/lib/api_backtester";

/* ── Date range constants for dataset filter ── */
const MIN_DATE = "2006-01-01";
const MAX_DATE = new Date().toISOString().split("T")[0];
const TWO_YEARS_AGO = new Date(
  new Date().setFullYear(new Date().getFullYear() - 2)
).toISOString().split("T")[0];

function formatDate(dStr: string): string {
  if (!dStr) return '';
  const parts = dStr.split('-');
  if (parts.length === 3) {
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  }
  return dStr;
}

function formatFilterValue(key: string, value: any): { label: string; value: string } | null {
  if (key === 'rules') return null;
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

  if (typeof value === 'boolean') return value ? { label, value: '' } : null;
  if (typeof value === 'number') {
    if (key.includes('market_cap')) {
      if (value >= 1_000_000_000) return { label: `${label}:`, value: `$${(value / 1_000_000_000).toFixed(1).replace(/\.0$/, '')}B` };
      if (value >= 1_000_000) return { label: `${label}:`, value: `$${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M` };
    }
    if (value >= 1_000_000) return { label: `${label}:`, value: `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M` };
    if (value >= 1_000) return { label: `${label}:`, value: `${(value / 1_000).toFixed(1).replace(/\.0$/, '')}K` };
    return { label: `${label}:`, value: `${value}` };
  }
  return { label: `${label}:`, value: `${value}` };
}

function getFriendlyMetricLabel(metric: string): string {
  if (!metric) return "";
  const m = metric.replace(/['"]+/g, '');
  const labelMap: Record<string, string> = {
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
    "lead_rth_close_1": "cierre gap+1",
    "lead_open_1": "apertura pm gap+1",
    "lead_pmh_gap_pct_1": "gap pm high gap+1 %",
    "lead_pm_volume_1": "volumen premarket gap+1",
    "lead_gap_pct_1": "gap de apertura gap+1 %",
    "lead_rth_volume_1": "volumen rth gap+1",
    "lead_rth_range_pct_1": "rango rth gap+1 %",
  };
  if (labelMap[m]) return labelMap[m];
  return m.replace(/_/g, " ").toLowerCase();
}

function formatRule(rule: any): { label: string; value: string } {
  if (!rule || !rule.metric) return { label: '', value: '' };
  const opMap: Record<string, string> = {
    'GT': '>', 'LT': '<', 'GTE': '>=', 'LTE': '<=', 'EQUAL': '=', 'NEQ': '!=',
    'GREATER_THAN_OR_EQUAL': '>=', 'LESS_THAN_OR_EQUAL': '<=', 'GREATER_THAN': '>', 'LESS_THAN': '<',
  };
  const op = opMap[rule.operator] || rule.operator;
  const friendlyMetric = getFriendlyMetricLabel(rule.metric);
  let friendlyVal = rule.value;
  const numVal = parseFloat(rule.value);
  if (!isNaN(numVal)) {
    if (rule.metric.toLowerCase().includes('volume')) {
      if (numVal >= 1_000_000) friendlyVal = `${(numVal / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
      else if (numVal >= 1_000) friendlyVal = `${(numVal / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
    }
    else if (rule.metric.includes('%') || rule.metric.toLowerCase().includes('pct')) friendlyVal = `${numVal}%`;
    else if (rule.metric.toLowerCase().includes('price') || rule.metric.toLowerCase().includes('close') || rule.metric.toLowerCase().includes('open')) friendlyVal = `$${numVal.toFixed(2).replace(/\.00$/, '')}`;
  }
  return { label: `${friendlyMetric}:`, value: `${op} ${friendlyVal}` };
}

export interface Draft {
  id: string;
  name: string;
  bias: "long" | "short";
  is_wizard?: boolean;
  apply_day?: "gap_day" | "gap_1_day" | "gap_2_day";
  postgap_preconditions?: PostGapPrecondition[];
  entry_logic: EntryLogicType;
  exit_logic: ExitLogicType;
  risk_management: RiskManagementType;
  created_at: string;
  market_sessions?: string[];
  custom_start_time?: string;
  custom_end_time?: string;
  dataset_id?: string;
  universe_filters?: any;
}

function getGroupSummaryText(group: ConditionGroup): string {
  if (!group.conditions || group.conditions.length === 0) return "";
  
  const parts = group.conditions.map(c => {
    if (c.type === 'group') {
      const subText = getGroupSummaryText(c);
      return subText ? `(${subText})` : "";
    } else {
      const tfStr = c.timeframe ? `[${c.timeframe}] ` : '';
      if (c.type === 'indicator_comparison') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
        let targetStr = '';
        if (typeof c.target === 'number') {
          targetStr = String(c.target);
        } else {
          targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        return `${tfStr}${sourceStr} ${compStr} ${targetStr}`;
      } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        return `${tfStr}Dist(${sourceStr}, ${levelStr}) ${compStr} ${c.value_pct}%`;
      }
      return "";
    }
  }).filter(Boolean);

  if (parts.length === 0) return "";
  return parts.join(` ${group.operator} `);
}

function getLeafConditions(
  group: ConditionGroup,
  timeframe: string
): { label: string; value: string }[] {
  if (!group || !group.conditions || group.conditions.length === 0) return [];
  const list: { label: string; value: string }[] = [];

  group.conditions.forEach(c => {
    if (c.type === 'group') {
      list.push(...getLeafConditions(c, timeframe));
    } else {
      const tfStr = c.timeframe ? `[${c.timeframe}] ` : `[${timeframe}] `;
      let label = '';
      let value = '';
      if (c.type === 'indicator_comparison') {
        if (c.source.name === IndicatorType.ELAPSED_TIME) {
          label = `${tfStr}Elapsed Time:`;
          const opSymbol = c.comparator === Comparator.EQ ? '=' : c.comparator === Comparator.GT ? '>' : c.comparator === Comparator.LT ? '<' : c.comparator === Comparator.LTE ? '≤' : '≥';
          value = `${opSymbol} ${c.target} mins`;
        } else if (c.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
          label = `${tfStr}Elapsed Time Last High:`;
          const opSymbol = c.comparator === Comparator.EQ ? '=' : c.comparator === Comparator.GT ? '>' : c.comparator === Comparator.LT ? '<' : c.comparator === Comparator.LTE ? '≤' : '≥';
          value = `${opSymbol} ${c.target} mins`;
        } else {
          const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
          const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
          let targetStr = '';
          if (typeof c.target === 'number') {
            if (c.source.name === IndicatorType.PM_HIGH_GAP) {
              targetStr = `${c.target}%`;
            } else {
              targetStr = String(c.target);
            }
          } else {
            targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
          }
          label = `${tfStr}${sourceStr}:`;
          value = `${compStr} ${targetStr}`;
        }
      } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        const posStr = c.position && c.position !== 'any' ? ` (${c.position})` : '';
        label = `${tfStr}Dist(${sourceStr}, ${levelStr}):`;
        value = `${compStr} ${c.value_pct}%${posStr}`;
      }
      if (label) {
        list.push({ label, value });
      }
    }
  });

  return list;
}

function formatPreconditionText(cond: PostGapPrecondition): { label: string; value: string } {
  const dayLabel = cond.day === 'gap_day' ? 'Día del Gap' : 'Día Gap +1';
  let metricLabel = 'Cierre';
  let valLabel = '';
  
  if (cond.metric === 'volume') {
    metricLabel = 'Volumen Total';
    const volVal = cond.value ?? 0;
    valLabel = `${cond.operator} ${volVal >= 1000000 ? `${volVal / 1000000}M` : volVal.toLocaleString()}`;
  } else if (cond.metric === 'close_vs_open') {
    valLabel = `${cond.operator} Apertura`;
  } else if (cond.metric === 'close_vs_high') {
    valLabel = `${cond.operator} High`;
  } else if (cond.metric === 'close_vs_low') {
    valLabel = `${cond.operator} Low`;
  } else if (cond.metric === 'close_vs_pm_high') {
    valLabel = `${cond.operator} PM High`;
  } else if (cond.metric === 'close_vs_pm_low') {
    valLabel = `${cond.operator} PM Low`;
  } else if (cond.metric === 'close_vs_high_low') {
    valLabel = cond.operator === '> High' ? '> High Previo' : '< Low Previo';
  } else if (cond.metric === 'close_vs_vwap') {
    valLabel = `${cond.operator} VWAP`;
  } else if (cond.metric === 'close_vs_sma') {
    valLabel = `${cond.operator} SMA ${cond.sma_period}`;
  } else if (cond.metric === 'candle_range_pct') {
    metricLabel = 'Rango de Vela %';
    valLabel = `${cond.operator} ${cond.value}%`;
  } else if (cond.metric === 'candle_range_ratio_gap_1_vs_gap') {
    metricLabel = cond.day === 'gap_1_day' ? 'Rango vela Gap+1 vs Gap' : 'Rango vela vs Previo';
    valLabel = `${cond.operator} ${cond.value}%`;
  }
  
  return { label: `[${dayLabel}] ${metricLabel}:`, value: valLabel };
}

function getSessionsText(sessions: string[], startTime?: string, endTime?: string): string {
  const sessionNames: Record<string, string> = {
    pre: "Pre-Market",
    rth: "Regular Hours (RTH)",
    post: "After-Market",
    custom: startTime && endTime ? `Personalizada (${startTime} - ${endTime})` : "Personalizada"
  };
  return sessions.map(s => sessionNames[s] || s).join(", ");
}

interface Props {
  onTest: (draft: Draft) => void;
  onBack: () => void;
  marketSessions?: string[];
  customStartTime?: string;
  customEndTime?: string;
  onDraftChange?: (draft: Draft) => void;
  initialStrategy?: any;
  onExpandedChange?: (expanded: boolean) => void;
}

export default function InlineStrategyBuilder({
  onTest,
  onBack,
  marketSessions = ["rth"],
  customStartTime = "09:30",
  customEndTime = "16:00",
  onDraftChange,
  initialStrategy,
  onExpandedChange,
}: Props) {
  const [name, setName] = useState("Nueva Estrategia");
  /* POST-MVP AGENTIC - descomentar cuando se active ChatBotAgentic.tsx (ver docs/plan_asistente_edgie.md)
  // ── Edgie assistant integration (AssistantBus) ───────────────
  useAssistantAction({
    name: "strategy.fill",
    description:
      "Construye una estrategia NUEVA en el Strategy Builder (parcial o completo): nombre, bias, día de aplicación, precondiciones, lógica de entrada/salida y gestión de riesgo. " +
      "El usuario ve el builder actualizarse en pantalla. Para EJECUTAR esta estrategia recién construida usa strategy_test (la corre directamente, NO hace falta guardarla y NO uses backtest_run con ella).",
    parameters: StrategyDraftSchema,
    confirm: "auto",
    handler: (args) => {
      // Deep-validate the condition tree before it reaches component state:
      // a malformed condition would crash the builder render.
      const guardError = guardStrategyDraft(args as Record<string, any>);
      if (guardError) return { ok: false, error: guardError };
      window.dispatchEvent(new CustomEvent('fill-strategy-builder', { detail: args }));
      return { ok: true, result: { applied: args } };
    },
  });

  useAssistantAction({
    name: "strategy.test",
    description:
      "Ejecuta directamente un backtest con el borrador ACTUAL del Strategy Builder (la estrategia recién construida con strategy_fill), sin necesidad de guardarla. " +
      "Usa el dataset y los parámetros seleccionados en el formulario. Este es el camino correcto para 'crear y probar' una estrategia nueva. " +
      "Falla si hay condiciones incompletas o si los parciales de take profit no suman 100%.",
    parameters: EmptySchema,
    confirm: "auto",
    handler: async () => {
      const logicErrors = validateStrategyLogic(entryLogic, exitLogic);
      if (logicErrors.length > 0) {
        return { ok: false, error: `Condiciones incompletas: ${logicErrors.join('; ')}` };
      }

      // Race the run against a fast backend failure so we report the truth.
      const failure = new Promise<string | null>((resolve) => {
        const onFinished = (e: Event) => {
          const detail = (e as CustomEvent).detail;
          if (detail && detail.ok === false) { cleanup(); resolve(detail.error || "Error al ejecutar el backtest"); }
        };
        const timer = setTimeout(() => { cleanup(); resolve(null); }, 4000);
        const cleanup = () => { clearTimeout(timer); window.removeEventListener("backtest-run-finished", onFinished); };
        window.addEventListener("backtest-run-finished", onFinished);
      });

      handleTest();
      const err = await failure;
      if (err) return { ok: false, error: `El backtest de prueba falló: ${err}` };
      return { ok: true, result: "Backtest de prueba en ejecución con el borrador actual; los resultados aparecerán al terminar." };
    },
  });

  useAssistantContext("strategy.draft", () => ({
    name,
    bias,
    applyDay,
    preconditionsCount: postgapPreconditions.length,
    entrySummary: getGroupSummaryText(entryLogic.root_condition) || "(sin condiciones)",
    entryTimeframe: entryLogic.timeframe,
    entryTimeWindows: entryLogic.entry_time_windows ?? [],
    exitSummary: getGroupSummaryText(exitLogic.root_condition) || "(sin condiciones)",
    exitTimeframe: exitLogic.timeframe,
    riskManagement,
  }));
  */

  const createdAtRef = useRef(new Date().toISOString());
  const lastLoadedStrategyRef = useRef<string>("");
  const [activeTooltip, setActiveTooltip] = useState<{
    text: string;
    x: number;
    y: number;
    title?: string;
  } | null>(null);

  // Load strategy from prop when initialStrategy is provided
  useEffect(() => {
    if (!initialStrategy) return;
    if ((initialStrategy.id === "draft" || initialStrategy.id === "wizard_draft") && lastLoadedStrategyRef.current !== "") return;

    const stratObj = initialStrategy.definition ? initialStrategy.definition : initialStrategy;
    const str = JSON.stringify({
      name: stratObj.name || initialStrategy.name,
      bias: stratObj.bias,
      apply_day: stratObj.apply_day,
      postgap_preconditions: stratObj.postgap_preconditions,
      entry_logic: stratObj.entry_logic,
      exit_logic: stratObj.exit_logic,
      risk_management: stratObj.risk_management,
      market_sessions: stratObj.market_sessions,
      custom_start_time: stratObj.custom_start_time,
      custom_end_time: stratObj.custom_end_time,
      dataset_id: stratObj.dataset_id,
      universe_filters: stratObj.universe_filters,
    });
    if (str === lastLoadedStrategyRef.current) return;
    lastLoadedStrategyRef.current = str;

    const finalName = stratObj.name || initialStrategy.name;
    if (finalName) setName(finalName);
    if (stratObj.bias) setBias(stratObj.bias);
    if (stratObj.apply_day) setApplyDay(stratObj.apply_day);
    if (stratObj.postgap_preconditions) {
      setPostgapPreconditions(stratObj.postgap_preconditions);
    } else {
      setPostgapPreconditions([]);
    }
    if (stratObj.entry_logic) setEntryLogic(stratObj.entry_logic);
    if (stratObj.exit_logic) setExitLogic(stratObj.exit_logic);
    if (stratObj.risk_management) setRiskManagement(stratObj.risk_management);
    if (stratObj.market_sessions) {
      setLocalMarketSessions(stratObj.market_sessions);
    } else {
      setLocalMarketSessions(marketSessions || ["rth"]);
    }
    if (stratObj.custom_start_time) setLocalCustomStartTime(stratObj.custom_start_time);
    if (stratObj.custom_end_time) setLocalCustomEndTime(stratObj.custom_end_time);
    if (stratObj.dataset_id) {
      setSelectedDataset(stratObj.dataset_id);
      setCustomUniverse(false);
    } else if (stratObj.universe_filters) {
      setUniverseFilters(stratObj.universe_filters);
      setCustomUniverse(true);
    }
  }, [initialStrategy, marketSessions, customStartTime, customEndTime]);

  // Universe (Dataset) States
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loadingDatasets, setLoadingDatasets] = useState(true);
  const [selectedDataset, setSelectedDataset] = useState<string>("");
  const [customUniverse, setCustomUniverse] = useState<boolean>(false);
  const [savingUnivNameMode, setSavingUnivNameMode] = useState(false);
  const [newUnivName, setNewUnivName] = useState('');
  const [savingUniv, setSavingUniv] = useState(false);

  const handleSaveCustomUniverse = async () => {
    if (!newUnivName.trim()) return;
    setSavingUniv(true);
    try {
      const { createQuery } = await import("@/lib/api");
      const saved = await createQuery({
        name: newUnivName.trim(),
        filters: universeFilters
      });
      const d = await fetchDatasets();
      setDatasets(d);
      setSelectedDataset(saved.id);
      setCustomUniverse(false);
      setSavingUnivNameMode(false);
      setNewUnivName('');
      alert("Universo guardado correctamente.");
    } catch (err) {
      console.error("Error saving universe:", err);
      alert("Error al guardar el universo.");
    } finally {
      setSavingUniv(false);
    }
  };
  const [universeFilters, setUniverseFilters] = useState<any>({
    date_from: TWO_YEARS_AGO,
    date_to: MAX_DATE,
    rules: []
  });
  const [dbDateRange, setDbDateRange] = useState<any>({
    min_date: "2022-01-01",
    max_date: new Date().toISOString().split("T")[0]
  });

  // Custom Universe Rules Form States
  const [tempUnivDay, setTempUnivDay] = useState<'gap_day' | 'gap_plus_1_day' | 'gap_plus_2_day'>('gap_day');
  const [tempUnivParam, setTempUnivParam] = useState<string>('gap_pct');
  const [tempUnivOp, setTempUnivOp] = useState<string>('>=');
  const [tempUnivVal1, setTempUnivVal1] = useState<string>('2.0');
  const [tempUnivVal2, setTempUnivVal2] = useState<string>('');

  useEffect(() => {
    if (onExpandedChange) {
      onExpandedChange(tempUnivOp === 'between');
    }
    return () => {
      onExpandedChange?.(false);
    };
  }, [tempUnivOp, onExpandedChange]);

  // Fetch datasets list on mount
  useEffect(() => {
    const loadDatasetsList = async () => {
      try {
        const [d, range] = await Promise.all([
          fetchDatasets(),
          fetchAvailableDateRange()
        ]);
        setDatasets(d);
        if (d.length > 0) {
          setSelectedDataset(prev => prev || d[0].id);
        }
        if (range) {
          setDbDateRange(range);
        }
      } catch (err) {
        console.error("Error loading datasets in Free Mode:", err);
      } finally {
        setLoadingDatasets(false);
      }
    };
    loadDatasetsList();
  }, []);

  const [bias, setBias] = useState<"long" | "short">("long");
  const [applyDay, setApplyDay] = useState<'gap_day' | 'gap_1_day' | 'gap_2_day'>('gap_day');
  const [localMarketSessions, setLocalMarketSessions] = useState<string[]>(initialStrategy?.definition?.market_sessions || initialStrategy?.market_sessions || marketSessions || ["rth"]);
  const [localCustomStartTime, setLocalCustomStartTime] = useState<string>(initialStrategy?.definition?.custom_start_time || initialStrategy?.custom_start_time || customStartTime || "09:30");
  const [localCustomEndTime, setLocalCustomEndTime] = useState<string>(initialStrategy?.definition?.custom_end_time || initialStrategy?.custom_end_time || customEndTime || "16:00");
  const [postgapPreconditions, setPostgapPreconditions] = useState<PostGapPrecondition[]>([]);
  const [entryLogic, setEntryLogic] = useState<EntryLogicType>(initialEntryLogic);
  const [exitLogic, setExitLogic] = useState<ExitLogicType>(initialExitLogic);
  const [riskManagement, setRiskManagement] = useState<RiskManagementType>(initialRiskManagement);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [tempDay, setTempDay] = useState<'gap_day' | 'gap_1_day'>('gap_day');
  const [tempSource, setTempSource] = useState<'cierre' | 'volume' | 'candle_range_pct' | 'candle_range_ratio_gap_1_vs_gap'>('cierre');
  const [tempOperator, setTempOperator] = useState<'>' | '<'>('>');
  const [tempTarget, setTempTarget] = useState<'apertura' | 'high_gap_day' | 'low_gap_day' | 'pm_high' | 'pm_low' | 'vwap' | 'sma'>('apertura');
  const [tempValue, setTempValue] = useState<number>(1000000);
  const [tempVolumeText, setTempVolumeText] = useState<string>("1.0");
  const [tempSmaPeriod, setTempSmaPeriod] = useState<number>(20);
  const [tempFromTime, setTempFromTime] = useState("09:30");
  const [tempToTime, setTempToTime] = useState("16:00");

  const getSessionOverlapWarning = (fromTime: string, toTime: string) => {
    if (!localMarketSessions || localMarketSessions.length === 0 || localMarketSessions.includes("all")) {
      return null;
    }

    const parseTimeToMins = (t: string) => {
      const [h, m] = t.split(":").map(Number);
      return h * 60 + m;
    };

    const windowStart = parseTimeToMins(fromTime);
    const windowEnd = parseTimeToMins(toTime);

    const intervals: { label: string; start: number; end: number }[] = [];
    localMarketSessions.forEach(s => {
      if (s === "pre") {
        intervals.push({ label: "Pre-Market", start: 240, end: 570 });
      } else if (s === "rth") {
        intervals.push({ label: "Regular Hours", start: 570, end: 960 });
      } else if (s === "post") {
        intervals.push({ label: "After-Market", start: 960, end: 1200 });
      } else if (s === "custom" && localCustomStartTime && localCustomEndTime) {
        intervals.push({
          label: `Custom (${localCustomStartTime}-${localCustomEndTime})`,
          start: parseTimeToMins(localCustomStartTime),
          end: parseTimeToMins(localCustomEndTime)
        });
      }
    });

    if (intervals.length === 0) return null;

    const isFullyCovered = (() => {
      const endCheck = windowStart === windowEnd ? windowStart : windowEnd - 1;
      for (let m = windowStart; m <= endCheck; m++) {
        const isMinuteCovered = intervals.some(interval => m >= interval.start && m <= interval.end);
        if (!isMinuteCovered) return false;
      }
      return true;
    })();

    if (!isFullyCovered) {
      const sessionsStr = intervals.map(i => i.label).join(", ");
      return `Fuera de sesión activa (${sessionsStr})`;
    }

    return null;
  };

  useEffect(() => {
    if (applyDay === 'gap_day') {
      setPostgapPreconditions([]);
    } else if (applyDay === 'gap_1_day') {
      // Ensure all preconditions use 'gap_day' if we are on Gap +1 Day
      setPostgapPreconditions(prev => prev.map(p => ({ ...p, day: 'gap_day' })));
      setTempDay('gap_day');
      if (tempSource === 'candle_range_ratio_gap_1_vs_gap') {
        setTempSource('cierre');
      }
      setRiskManagement(prev => {
        if (prev.swing_option?.active && prev.swing_option?.target_day === 'gap_1_day') {
          return {
            ...prev,
            swing_option: { ...prev.swing_option!, target_day: 'gap_2_day' }
          };
        }
        return prev;
      });
    } else if (applyDay === 'gap_2_day') {
      setRiskManagement(prev => {
        if (prev.swing_option?.active) {
          return {
            ...prev,
            swing_option: { ...prev.swing_option!, active: false }
          };
        }
        return prev;
      });
    }
  }, [applyDay]);

  useEffect(() => {
    onDraftChange?.({
      id: "draft",
      name,
      bias,
      is_wizard: false,
      apply_day: applyDay,
      postgap_preconditions: postgapPreconditions,
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      risk_management: riskManagement,
      created_at: createdAtRef.current,
      market_sessions: localMarketSessions,
      custom_start_time: localMarketSessions.includes("custom") ? localCustomStartTime : undefined,
      custom_end_time: localMarketSessions.includes("custom") ? localCustomEndTime : undefined,
      dataset_id: customUniverse ? undefined : selectedDataset,
      universe_filters: customUniverse ? universeFilters : undefined,
    });
  }, [name, bias, applyDay, postgapPreconditions, entryLogic, exitLogic, riskManagement, localMarketSessions, localCustomStartTime, localCustomEndTime, selectedDataset, customUniverse, universeFilters, onDraftChange]);

  const resetForm = () => {
    setName("Nueva Estrategia");
    setBias("long");
    setApplyDay("gap_day");
    setLocalMarketSessions(["rth"]);
    setLocalCustomStartTime("09:30");
    setLocalCustomEndTime("16:00");
    setPostgapPreconditions([]);
    setEntryLogic(initialEntryLogic);
    setExitLogic(initialExitLogic);
    setRiskManagement(initialRiskManagement);
    setTempFromTime("09:30");
    setTempToTime("16:00");
  };

  const buildDraft = (): Draft => ({
    id: `draft_${Date.now()}`,
    name,
    bias,
    is_wizard: false,
    apply_day: applyDay,
    postgap_preconditions: postgapPreconditions,
    entry_logic: entryLogic,
    exit_logic: exitLogic,
    risk_management: riskManagement,
    created_at: new Date().toISOString(),
    market_sessions: localMarketSessions,
    custom_start_time: localMarketSessions.includes("custom") ? localCustomStartTime : undefined,
    custom_end_time: localMarketSessions.includes("custom") ? localCustomEndTime : undefined,
    dataset_id: customUniverse ? undefined : selectedDataset,
    universe_filters: customUniverse ? universeFilters : undefined,
  } as any);

  const handleTest = () => {
    if (isRiskInvalid) {
      alert("La suma del capital de los parciales de Take Profit debe ser exactamente 100%.");
      return;
    }
    const logicErrors = validateStrategyLogic(entryLogic, exitLogic);
    if (logicErrors.length > 0) {
      alert("Hay condiciones incompletas:\n" + logicErrors.join("\n"));
      return;
    }

    // Validate if any configured entry time window is completely outside the active sessions
    if (entryLogic.entry_time_windows && entryLogic.entry_time_windows.length > 0) {
      const hasInvalidWindow = entryLogic.entry_time_windows.some(window => {
        return getSessionOverlapWarning(window.from_time, window.to_time) !== null;
      });
      if (hasInvalidWindow) {
        alert("Las ventanas horarias de entrada están fuera del rango de la sesión de mercado fijada, por favor, cambie las ventanas o la sesión de mercado de la estrategia");
        return;
      }
    }

    const draft = buildDraft();
    onTest(draft);
  };

  const isPartialTPMode = riskManagement.use_take_profit === true && riskManagement.take_profit_mode === "Partial";
  const totalPartialCapital = (riskManagement.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0);
  const isRiskInvalid = isPartialTPMode && Math.abs(totalPartialCapital - 100) > 0.01;

  // Count configured items for summary
  const entryCount = getLeafConditions(entryLogic.root_condition, entryLogic.timeframe).length;
  const exitCount = getLeafConditions(exitLogic.root_condition, exitLogic.timeframe).length;
  const preconditionCount = postgapPreconditions.length;
  const sessionCount = localMarketSessions.length;
  const riskCount = 1 // Stop Loss is always configured
    + (riskManagement.use_take_profit ? 1 : 0)
    + (riskManagement.trailing_stop?.active ? 1 : 0)
    + (riskManagement.accept_reentries ? 1 : 0);

  const totalConfigCount = 1 // Bias is always configured
    + 1 // Apply day is always configured
    + preconditionCount
    + (sessionCount > 0 ? 1 : 0)
    + riskCount
    + entryCount
    + exitCount;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "0.5px solid var(--color-ec-border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
          backgroundColor: "var(--color-ec-bg-base)",
          flexShrink: 0,
        }}
      >
        <button
          onClick={onBack}
          style={{
            background: "none",
            border: "none",
            color: "var(--color-ec-text-muted)",
            cursor: "pointer",
            fontSize: 18,
            lineHeight: 1,
            padding: "0 4px",
          }}
        >
          ←
        </button>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            fontSize: 13,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            fontFamily: "var(--color-ec-sans)",
          }}
        />
      </div>



      {/* Entry / Exit / Risk */}
      <div style={{ 
        flex: 1, 
        overflowY: "auto", 
        padding: "0 20px 80px 20px",
        display: "flex",
        flexDirection: "column",
        gap: "0px"
      }}>
        {/* SECTION: UNIVERSO */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          padding: '20px 0',
          borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 3,
              height: 14,
              borderRadius: 1,
              backgroundColor: 'var(--color-ec-copper)',
            }} />
            <h2 style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 13,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--color-ec-text-high)',
              margin: 0,
            }}>Universo (Dataset)</h2>
          </div>

          {/* Two-column layout: Left stacked buttons, Right content */}
          <div style={{ display: 'flex', flexDirection: 'row', gap: 16, alignItems: 'flex-start' }}>
            {/* Left Column: Stacked toggle buttons */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: 130, flexShrink: 0 }}>
              <button
                type="button"
                onClick={() => setCustomUniverse(false)}
                style={{
                  width: '100%',
                  padding: '6px 0',
                  borderRadius: 5,
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  cursor: 'pointer',
                  border: `0.5px solid ${!customUniverse ? 'var(--color-ec-copper)' : 'var(--color-ec-border)'}`,
                  backgroundColor: !customUniverse ? 'rgba(216, 122, 61, 0.07)' : 'transparent',
                  color: !customUniverse ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)',
                  fontFamily: 'var(--color-ec-sans)',
                }}
              >
                Cargar Dataset
              </button>
              <button
                type="button"
                onClick={() => setCustomUniverse(true)}
                style={{
                  width: '100%',
                  padding: '6px 0',
                  borderRadius: 5,
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  cursor: 'pointer',
                  border: `0.5px solid ${customUniverse ? 'var(--color-ec-copper)' : 'var(--color-ec-border)'}`,
                  backgroundColor: customUniverse ? 'rgba(216, 122, 61, 0.07)' : 'transparent',
                  color: customUniverse ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)',
                  fontFamily: 'var(--color-ec-sans)',
                }}
              >
                Personalizar
              </button>
            </div>

            {/* Right Column: Active selector and filters */}
            <div style={{ flex: 1, minWidth: 0 }}>
              {!customUniverse ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {loadingDatasets ? (
                    <div
                      style={{
                        height: 32,
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 8,
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11,
                        color: 'var(--color-ec-text-muted)',
                      }}
                    >
                      <svg
                        className="animate-spin"
                        style={{ width: 14, height: 14, color: 'var(--color-ec-copper)' }}
                        viewBox="0 0 24 24"
                      >
                        <circle
                          style={{ opacity: 0.25 }}
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                          fill="none"
                        />
                        <path
                          style={{ opacity: 0.75 }}
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                        />
                      </svg>
                      <span>Cargando datasets guardados...</span>
                    </div>
                  ) : (
                    <select
                      value={selectedDataset}
                      onChange={(e) => setSelectedDataset(e.target.value)}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '6px 10px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11.5,
                        color: 'var(--color-ec-text-primary)',
                        outline: 'none',
                        width: '100%',
                        cursor: 'pointer',
                      }}
                    >
                      {datasets.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name} {d.pair_count > 0 ? `(${d.pair_count} pares)` : " (Pendiente)"}
                        </option>
                      ))}
                    </select>
                  )}

                  {(() => {
                    const currentDs = datasets.find(d => d.id === selectedDataset);
                    if (!currentDs) return null;
                    return (
                      <div style={{
                        backgroundColor: 'rgba(255, 255, 255, 0.01)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '8px 10px',
                        fontSize: 10,
                        fontFamily: 'var(--color-ec-sans)',
                        color: 'var(--color-ec-text-secondary)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 4
                      }}>
                        <div style={{ display: 'flex', gap: 12 }}>
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>PARES: </span>
                            <span style={{ color: 'var(--color-ec-copper)', fontWeight: 700 }}>{currentDs.pair_count > 0 ? currentDs.pair_count : "Pendiente"}</span>
                          </div>
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>RANGO: </span>
                            <span>{currentDs.min_date ? formatDate(currentDs.min_date) : '?'} - {currentDs.max_date ? formatDate(currentDs.max_date) : '?'}</span>
                          </div>
                        </div>
                        {currentDs.filters && Object.keys(currentDs.filters).length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                            {Object.entries(currentDs.filters)
                              .filter(([k]) => k !== 'rules' && k !== 'date_from' && k !== 'date_to')
                              .map(([key, val]) => {
                                const lbl = formatFilterValue(key, val);
                                return lbl ? (
                                  <span key={key} style={{
                                    fontSize: 10,
                                    fontWeight: 600,
                                    padding: '4px 8px',
                                    borderRadius: 4,
                                    backgroundColor: 'rgba(216, 122, 61, 0.08)',
                                    color: 'var(--color-ec-text-secondary)',
                                    border: '0.5px solid var(--color-ec-copper)',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                  }}>
                                    <span>{lbl.label}</span>
                                    {lbl.value && <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{lbl.value}</strong>}
                                  </span>
                                ) : null;
                              })}
                            {(currentDs.filters.rules || []).map((r: any, idx: number) => {
                              const lbl = formatRule(r);
                              return (
                                <span key={idx} style={{
                                  fontSize: 10,
                                  fontWeight: 600,
                                  padding: '4px 8px',
                                  borderRadius: 4,
                                  backgroundColor: 'rgba(216, 122, 61, 0.08)',
                                  color: 'var(--color-ec-text-secondary)',
                                  border: '0.5px solid var(--color-ec-copper)',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                }}>
                                  <span>{lbl.label}</span>
                                  {lbl.value && <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{lbl.value}</strong>}
                                </span>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              ) : (
                // Custom Universe filters
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Desde</label>
                      <input
                        type="date"
                        value={universeFilters.date_from || ''}
                        min={dbDateRange.min_date}
                        max={dbDateRange.max_date}
                        onChange={(e) => setUniverseFilters((prev: any) => ({ ...prev, date_from: e.target.value }))}
                        style={{
                          backgroundColor: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 4,
                          padding: '4px 6px',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 10.5,
                          outline: 'none',
                        }}
                      />
                    </div>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Hasta</label>
                      <input
                        type="date"
                        value={universeFilters.date_to || ''}
                        min={universeFilters.date_from && universeFilters.date_from > dbDateRange.min_date ? universeFilters.date_from : dbDateRange.min_date}
                        max={dbDateRange.max_date}
                        onChange={(e) => setUniverseFilters((prev: any) => ({ ...prev, date_to: e.target.value }))}
                        style={{
                          backgroundColor: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 4,
                          padding: '4px 6px',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 10.5,
                          outline: 'none',
                        }}
                      />
                    </div>
                  </div>

                  {/* Add Custom rules */}
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    padding: 8,
                    backgroundColor: 'rgba(255, 255, 255, 0.01)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                  }}>
                    <div style={{ fontSize: 8.5, fontWeight: 700, color: 'var(--color-ec-copper)', borderBottom: '0.5px solid rgba(255,255,255,0.05)', paddingBottom: 2 }}>
                      Añadir filtro de mercado
                    </div>

                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                      <select
                        value={tempUnivDay}
                        onChange={(e) => setTempUnivDay(e.target.value as any)}
                        style={{
                          background: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 10,
                          padding: '3px 4px',
                          borderRadius: 4,
                          outline: 'none',
                        }}
                      >
                        <option value="gap_day">Gap Day</option>
                        <option value="gap_plus_1_day">Gap +1</option>
                        <option value="gap_plus_2_day">Gap +2</option>
                      </select>

                      <select
                        value={tempUnivParam}
                        onChange={(e) => {
                          const param = e.target.value;
                          setTempUnivParam(param);
                          if (param === 'pm_volume' || param === 'rth_volume') {
                            setTempUnivVal1('1.0');
                          } else if (param === 'gap_pct' || param === 'rth_range_pct') {
                            setTempUnivVal1('2.0');
                          } else {
                            setTempUnivVal1('5.0');
                          }
                        }}
                        style={{
                          background: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 10,
                          padding: '3px 4px',
                          borderRadius: 4,
                          outline: 'none',
                        }}
                      >
                        <option value="gap_pct">Gap (%)</option>
                        <option value="pm_volume">Vol. PM (M)</option>
                        <option value="rth_volume">Vol. RTH (M)</option>
                        <option value="rth_close">Precio RTH ($)</option>
                        <option value="pm_open">Precio PM ($)</option>
                        <option value="pmh_gap_pct">PM High Gap (%)</option>
                        <option value="rth_range_pct">Rango RTH (%)</option>
                      </select>

                      <select
                        value={tempUnivOp}
                        onChange={(e) => setTempUnivOp(e.target.value)}
                        style={{
                          background: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 10,
                          padding: '3px 4px',
                          borderRadius: 4,
                          outline: 'none',
                        }}
                      >
                        <option value=">=">&gt;=</option>
                        <option value="<=">&lt;=</option>
                        <option value=">">&gt;</option>
                        <option value="<">&lt;</option>
                        <option value="between">Entre</option>
                      </select>

                       <input
                        type="text"
                        value={tempUnivVal1}
                        onChange={(e) => setTempUnivVal1(e.target.value)}
                        style={{
                          background: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 10,
                          padding: '3px 4px',
                          borderRadius: 4,
                          outline: 'none',
                          width: 65,
                        }}
                      />

                      {tempUnivOp === 'between' && (
                        <input
                          type="text"
                          value={tempUnivVal2}
                          onChange={(e) => setTempUnivVal2(e.target.value)}
                          style={{
                            background: 'var(--color-ec-bg-surface)',
                            border: '0.5px solid var(--color-ec-border)',
                            color: 'var(--color-ec-text-primary)',
                            fontSize: 10,
                            padding: '3px 4px',
                            borderRadius: 4,
                            outline: 'none',
                            width: 65,
                          }}
                        />
                      )}

                      <button
                        type="button"
                        onClick={() => {
                          const val1 = parseFloat(tempUnivVal1);
                          const val2 = tempUnivOp === 'between' ? parseFloat(tempUnivVal2) : undefined;
                          if (isNaN(val1) || (tempUnivOp === 'between' && isNaN(val2 || 0))) return;

                          let fieldName = "";
                          const lagSuffix = tempUnivDay === "gap_day" ? "" : tempUnivDay === "gap_plus_1_day" ? "_1" : "_2";
                          
                          if (tempUnivDay === "gap_day") {
                            if (tempUnivParam === "rth_close") fieldName = "Close Price";
                            else if (tempUnivParam === "pm_open") fieldName = "Min Open PM price";
                            else if (tempUnivParam === "pmh_gap_pct") fieldName = "PMH Gap %";
                            else if (tempUnivParam === "pm_volume") fieldName = "Premarket Volume";
                            else if (tempUnivParam === "gap_pct") fieldName = "Open Gap %";
                            else if (tempUnivParam === "rth_volume") fieldName = "EOD Volume";
                            else if (tempUnivParam === "rth_range_pct") fieldName = "RTH Range %";
                          } else {
                            if (tempUnivParam === "rth_close") fieldName = `lead_rth_close${lagSuffix}`;
                            else if (tempUnivParam === "pm_open") fieldName = `lead_open${lagSuffix}`;
                            else if (tempUnivParam === "pmh_gap_pct") fieldName = `lead_pmh_gap_pct${lagSuffix}`;
                            else if (tempUnivParam === "pm_volume") fieldName = `lead_pm_volume${lagSuffix}`;
                            else if (tempUnivParam === "gap_pct") fieldName = `lead_gap_pct${lagSuffix}`;
                            else if (tempUnivParam === "rth_volume") fieldName = `lead_rth_volume${lagSuffix}`;
                            else if (tempUnivParam === "rth_range_pct") fieldName = `lead_rth_range_pct${lagSuffix}`;
                          }

                          if (!fieldName) return;
                          
                          const isVol = tempUnivParam === "pm_volume" || tempUnivParam === "rth_volume";
                          const multiplier = isVol ? 1000000 : 1;

                          const newRules = [...(universeFilters.rules || [])];

                          if (tempUnivOp === 'between') {
                            newRules.push({
                              metric: fieldName,
                              operator: "GREATER_THAN_OR_EQUAL",
                              valueType: "static",
                              value: (val1 * multiplier).toString()
                            });
                            newRules.push({
                              metric: fieldName,
                              operator: "LESS_THAN_OR_EQUAL",
                              valueType: "static",
                              value: (val2! * multiplier).toString()
                            });
                          } else {
                            let opName = "";
                            if (tempUnivOp === ">=") opName = "GREATER_THAN_OR_EQUAL";
                            else if (tempUnivOp === "<=") opName = "LESS_THAN_OR_EQUAL";
                            else if (tempUnivOp === ">") opName = "GREATER_THAN";
                            else if (tempUnivOp === "<") opName = "LESS_THAN";

                            newRules.push({
                              metric: fieldName,
                              operator: opName,
                              valueType: "static",
                              value: (val1 * multiplier).toString()
                            });
                          }

                          setUniverseFilters((prev: any) => ({ ...prev, rules: newRules }));
                        }}
                        style={{
                          backgroundColor: 'var(--color-ec-copper)',
                          color: 'var(--color-ec-copper-text)',
                          border: 'none',
                          borderRadius: 4,
                          padding: '3px 8px',
                          fontSize: 10,
                          fontWeight: 700,
                          cursor: 'pointer',
                        }}
                      >
                        + Add
                      </button>
                    </div>
                  </div>

                  {/* Rules list */}
                  {universeFilters.rules && universeFilters.rules.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                      {universeFilters.rules.map((r: any, idx: number) => {
                        const friendlyName = r.metric.replace(/_/g, " ").toLowerCase();
                        const friendlyOp = r.operator === "GREATER_THAN_OR_EQUAL" ? ">=" : r.operator === "LESS_THAN_OR_EQUAL" ? "<=" : r.operator === "GREATER_THAN" ? ">" : "<";
                        let friendlyVal = r.value;
                        const numVal = parseFloat(r.value);
                        if (!isNaN(numVal) && r.metric.toLowerCase().includes('volume')) {
                          friendlyVal = `${(numVal / 1000000).toFixed(1).replace(/\.0$/, '')}M`;
                        }
                        return (
                          <span
                            key={idx}
                            onClick={() => {
                              setUniverseFilters((prev: any) => ({
                                ...prev,
                                rules: prev.rules.filter((_: any, i: number) => i !== idx)
                              }));
                            }}
                            style={{
                              fontSize: 10,
                              fontWeight: 600,
                              padding: '4px 8px',
                              borderRadius: 4,
                              backgroundColor: 'rgba(216, 122, 61, 0.08)',
                              color: 'var(--color-ec-text-secondary)',
                              border: '0.5px solid var(--color-ec-copper)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              cursor: 'pointer',
                            }}
                          >
                            <span>{friendlyName}:</span>
                            <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{friendlyOp} {friendlyVal}</strong>
                            <span style={{ fontWeight: 700, marginLeft: 3 }}>×</span>
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {/* Save Universe Button / Form */}
                  <div style={{ marginTop: 12, borderTop: '0.5px dotted var(--color-ec-border)', paddingTop: 10 }}>
                    {!savingUnivNameMode ? (
                      <button
                        type="button"
                        onClick={() => setSavingUnivNameMode(true)}
                        style={{
                          backgroundColor: 'transparent',
                          color: 'var(--color-ec-text-muted)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 4,
                          padding: '4px 10px',
                          fontSize: 10,
                          fontWeight: 600,
                          cursor: 'pointer',
                          textTransform: 'uppercase',
                          transition: 'all 150ms ease',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 4
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.color = 'var(--color-ec-copper)';
                          e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                          e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                        }}
                      >
                        <Save style={{ width: 11, height: 11 }} />
                        Guardar nuevo universo
                      </button>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <label style={{ fontSize: 8.5, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Nombre del nuevo universo</label>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <input
                            type="text"
                            value={newUnivName}
                            onChange={(e) => setNewUnivName(e.target.value)}
                            placeholder="Ej. Gap > 20% y Vol > 1M"
                            style={{
                              backgroundColor: 'var(--color-ec-bg-surface)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 4,
                              padding: '4px 6px',
                              color: 'var(--color-ec-text-primary)',
                              fontSize: 10.5,
                              outline: 'none',
                              flex: 1,
                            }}
                          />
                          <button
                            type="button"
                            onClick={handleSaveCustomUniverse}
                            disabled={!newUnivName.trim() || savingUniv}
                            style={{
                              backgroundColor: 'var(--color-ec-copper)',
                              color: 'var(--color-ec-copper-text)',
                              border: 'none',
                              borderRadius: 4,
                              padding: '4px 10px',
                              fontSize: 10,
                              fontWeight: 700,
                              cursor: 'pointer',
                              opacity: (!newUnivName.trim() || savingUniv) ? 0.5 : 1,
                            }}
                          >
                            {savingUniv ? 'Guardando...' : 'Guardar'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setSavingUnivNameMode(false);
                              setNewUnivName('');
                            }}
                            style={{
                              backgroundColor: 'transparent',
                              color: 'var(--color-ec-text-muted)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 4,
                              padding: '4px 10px',
                              fontSize: 10,
                              fontWeight: 700,
                              cursor: 'pointer',
                            }}
                          >
                            Cancelar
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* SECTION: DIRECTION BIAS */}
        <div data-helper="st-bias" style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          padding: '20px 0',
          borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 3,
              height: 14,
              borderRadius: 1,
              backgroundColor: 'var(--color-ec-copper)',
            }} />
            <h2 style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 13,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--color-ec-text-high)',
              margin: 0,
            }}>Direction Bias</h2>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {(["long", "short"] as const).map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBias(b)}
                style={{
                  flex: 1,
                  padding: "6px 0",
                  borderRadius: 5,
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: 1,
                  cursor: "pointer",
                  border: `0.5px solid ${
                    bias === b
                      ? b === "long"
                        ? "var(--color-ec-profit)"
                        : "var(--color-ec-loss)"
                      : "var(--color-ec-border)"
                  }`,
                  backgroundColor:
                    bias === b
                      ? b === "long"
                        ? "color-mix(in srgb, var(--color-ec-profit) 15%, transparent)"
                        : "color-mix(in srgb, var(--color-ec-loss) 15%, transparent)"
                      : "transparent",
                  color:
                    bias === b
                      ? b === "long"
                        ? "var(--color-ec-profit)"
                        : "var(--color-ec-loss)"
                      : "var(--color-ec-text-muted)",
                  fontFamily: "var(--color-ec-sans)",
                }}
              >
                {b === "long" ? "▲ Long" : "▼ Short"}
              </button>
            ))}
          </div>
        </div>

        {/* SECTION: PRE-GAP CONDITIONS */}
        {applyDay !== 'gap_day' && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            padding: '20px 0',
            borderBottom: '0.5px solid var(--color-ec-border)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 3,
                height: 14,
                borderRadius: 1,
                backgroundColor: 'var(--color-ec-copper)',
              }} />
              <h2 style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 13,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-text-high)',
                margin: 0,
              }}>Condiciones previas post-gap</h2>
            </div>

            {/* Form to add preconditions */}
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              padding: 12,
              backgroundColor: 'rgba(28, 30, 33, 0.2)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 6,
            }}>
              {/* "Presets gap day" indicator */}
              <div style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-copper)',
                borderBottom: '0.5px solid rgba(255, 255, 255, 0.05)',
                paddingBottom: 4,
                marginBottom: 2
              }}>
                {applyDay === 'gap_2_day' ? 'Presets gap day y gap +1 day' : 'Presets gap day'}
              </div>
              {/* Top: Day selector (only for gap_2_day) */}
              {applyDay === 'gap_2_day' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, borderBottom: '0.5px solid var(--color-ec-border)', paddingBottom: 10, marginBottom: 2 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Evaluar en</label>
                  <select
                    value={tempDay}
                    onChange={(e) => {
                      const val = e.target.value as 'gap_day' | 'gap_1_day';
                      setTempDay(val);
                      if (val !== 'gap_1_day' && tempSource === 'candle_range_ratio_gap_1_vs_gap') {
                        setTempSource('cierre');
                      }
                    }}
                    style={{
                      background: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-primary)',
                      fontSize: 11,
                      padding: '4px 8px',
                      borderRadius: 4,
                      outline: 'none',
                      fontFamily: 'var(--color-ec-sans)',
                      width: 'fit-content',
                      cursor: 'pointer',
                    }}
                  >
                    <option value="gap_day">Día del Gap</option>
                    <option value="gap_1_day">Día Gap +1</option>
                  </select>
                </div>
              )}

              {/* Bottom: Inputs Row */}
              <div style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'flex-end',
                flexWrap: 'wrap',
                gap: 8,
              }}>
                {/* Source variable selector */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Variable</label>
                  <select
                    value={tempSource}
                    onChange={(e) => {
                      const src = e.target.value as 'cierre' | 'volume' | 'candle_range_pct' | 'candle_range_ratio_gap_1_vs_gap';
                      setTempSource(src);
                      
                      // Set sensible default values/operators
                      if (src === 'volume') {
                        setTempValue(1000000);
                      } else if (src === 'candle_range_pct') {
                        setTempValue(2.0);
                      } else if (src === 'candle_range_ratio_gap_1_vs_gap') {
                        setTempValue(150.0);
                      }
                    }}
                    style={{
                      background: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-primary)',
                      fontSize: 11,
                      padding: '4px 8px',
                      borderRadius: 4,
                      outline: 'none',
                      fontFamily: 'var(--color-ec-sans)',
                      width: 'fit-content',
                      cursor: 'pointer',
                    }}
                  >
                    <option value="cierre">Cierre</option>
                    <option value="volume">Volumen Total</option>
                    <option value="candle_range_pct">Rango de Vela %</option>
                    {applyDay === 'gap_2_day' && tempDay === 'gap_1_day' && (
                      <option value="candle_range_ratio_gap_1_vs_gap">Rango vela Gap+1 vs Gap (%)</option>
                    )}
                  </select>
                </div>

                {/* Operator selector */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Operador</label>
                  <select
                    value={tempOperator}
                    onChange={(e) => setTempOperator(e.target.value as any)}
                    style={{
                      background: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-primary)',
                      fontSize: 11,
                      padding: '4px 8px',
                      borderRadius: 4,
                      outline: 'none',
                      fontFamily: 'var(--color-ec-sans)',
                      width: 'fit-content',
                      cursor: 'pointer',
                    }}
                  >
                    <option value=">">mayor que (&gt;)</option>
                    <option value="<">menor que (&lt;)</option>
                  </select>
                </div>

                {/* Target variable selector (only if source is cierre) */}
                {tempSource === 'cierre' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Comparado con</label>
                    <select
                      value={tempTarget}
                      onChange={(e) => setTempTarget(e.target.value as any)}
                      style={{
                        background: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        color: 'var(--color-ec-text-primary)',
                        fontSize: 11,
                        padding: '4px 8px',
                        borderRadius: 4,
                        outline: 'none',
                        fontFamily: 'var(--color-ec-sans)',
                        width: 'fit-content',
                        cursor: 'pointer',
                      }}
                    >
                      <option value="apertura">Apertura</option>
                      <option value="high_gap_day">RTH high</option>
                      <option value="low_gap_day">RTH low</option>
                      <option value="pm_high">PM high</option>
                      <option value="pm_low">PM low</option>
                      <option value="vwap">VWAP</option>
                      <option value="sma">SMA</option>
                    </select>
                  </div>
                )}

                {/* SMA Period input */}
                {tempSource === 'cierre' && tempTarget === 'sma' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 60 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Periodo</label>
                    <input
                      type="number"
                      value={tempSmaPeriod}
                      min={2}
                      max={500}
                      onChange={(e) => setTempSmaPeriod(parseInt(e.target.value) || 20)}
                      style={{
                        background: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        color: 'var(--color-ec-text-primary)',
                        fontSize: 11,
                        padding: '4px 8px',
                        borderRadius: 4,
                        outline: 'none',
                        fontFamily: 'var(--color-ec-sans)',
                        width: '100%',
                      }}
                    />
                  </div>
                )}

                {/* Value input (only for volume and candle_range_pct) */}
                {tempSource !== 'cierre' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: tempSource === 'volume' ? 100 : 70 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Valor</label>
                    {tempSource === 'volume' ? (
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <input
                          type="text"
                          value={tempVolumeText}
                          onChange={(e) => {
                            const val = e.target.value;
                            if (/^\d*\.?\d*$/.test(val)) {
                              setTempVolumeText(val);
                            }
                          }}
                          placeholder="0"
                          style={{
                            background: 'var(--color-ec-bg-surface)',
                            border: '0.5px solid var(--color-ec-border)',
                            color: 'var(--color-ec-text-primary)',
                            fontSize: 11,
                            padding: '4px 20px 4px 8px',
                            borderRadius: 4,
                            outline: 'none',
                            fontFamily: 'var(--color-ec-sans)',
                            width: '100%',
                          }}
                        />
                        <span style={{
                          position: 'absolute',
                          right: 8,
                          fontSize: 10,
                          fontWeight: 600,
                          color: 'rgba(255, 255, 255, 0.35)',
                          pointerEvents: 'none',
                          fontFamily: 'var(--color-ec-sans)',
                        }}>
                          M
                        </span>
                      </div>
                    ) : (
                      <input
                        type="number"
                        value={tempValue}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          setTempValue(isNaN(val) ? 0 : val);
                        }}
                        style={{
                          background: 'var(--color-ec-bg-surface)',
                          border: '0.5px solid var(--color-ec-border)',
                          color: 'var(--color-ec-text-primary)',
                          fontSize: 11,
                          padding: '4px 8px',
                          borderRadius: 4,
                          outline: 'none',
                          fontFamily: 'var(--color-ec-sans)',
                          width: '100%',
                        }}
                      />
                    )}
                  </div>
                )}

                {/* Add button */}
                <button
                  type="button"
                  onClick={() => {
                    let metric: PostGapPrecondition['metric'] = 'volume';
                    let operator: PostGapPrecondition['operator'] = '>';
                    let value: number | undefined = undefined;
                    let sma_period: number | undefined = undefined;

                    if (tempSource === 'cierre') {
                      if (tempTarget === 'apertura') {
                        metric = 'close_vs_open';
                        operator = tempOperator;
                      } else if (tempTarget === 'high_gap_day') {
                        metric = 'close_vs_high';
                        operator = tempOperator;
                      } else if (tempTarget === 'low_gap_day') {
                        metric = 'close_vs_low';
                        operator = tempOperator;
                      } else if (tempTarget === 'pm_high') {
                        metric = 'close_vs_pm_high';
                        operator = tempOperator;
                      } else if (tempTarget === 'pm_low') {
                        metric = 'close_vs_pm_low';
                        operator = tempOperator;
                      } else if (tempTarget === 'vwap') {
                        metric = 'close_vs_vwap';
                        operator = tempOperator;
                      } else if (tempTarget === 'sma') {
                        metric = 'close_vs_sma';
                        operator = tempOperator;
                        sma_period = tempSmaPeriod;
                      }
                    } else if (tempSource === 'volume') {
                      metric = 'volume';
                      operator = tempOperator;
                      const parsedVol = parseFloat(tempVolumeText);
                      value = (isNaN(parsedVol) ? 0 : parsedVol) * 1000000;
                    } else if (tempSource === 'candle_range_pct') {
                      metric = 'candle_range_pct';
                      operator = tempOperator;
                      value = tempValue;
                    } else if (tempSource === 'candle_range_ratio_gap_1_vs_gap') {
                      metric = 'candle_range_ratio_gap_1_vs_gap';
                      operator = tempOperator;
                      value = tempValue;
                    }

                    const newCond: PostGapPrecondition = {
                      id: `precond_${Date.now()}`,
                      day: applyDay === 'gap_1_day' ? 'gap_day' : tempDay,
                      metric,
                      operator,
                      value,
                      sma_period,
                    };
                    setPostgapPreconditions([...postgapPreconditions, newCond]);
                  }}
                  style={{
                    backgroundColor: 'var(--color-ec-copper)',
                    color: 'var(--color-ec-copper-text)',
                    border: 'none',
                    padding: '6px 12px',
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: 'pointer',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px',
                    height: 25,
                  }}
                >
                  + Añadir
                </button>
              </div>
            </div>

            {/* Summary Tag List */}
            {postgapPreconditions.length === 0 ? (
              <p style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                color: 'var(--color-ec-text-muted)',
                margin: '4px 0 0 0',
                opacity: 0.5,
                fontStyle: 'italic',
              }}>
                Sin condiciones previas configuradas. La estrategia se ejecutará en todas las configuraciones.
              </p>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                {postgapPreconditions.map((cond) => {
                  const dayLabel = cond.day === 'gap_day' ? 'Día del Gap' : 'Día Gap +1';
                  let metricLabel = 'Cierre';
                  let valLabel = '';
                  
                  if (cond.metric === 'volume') {
                    metricLabel = 'Volumen Total';
                    const volVal = cond.value ?? 0;
                    valLabel = `${cond.operator} ${volVal >= 1000000 ? `${volVal / 1000000}M` : volVal.toLocaleString()}`;
                  } else if (cond.metric === 'close_vs_open') {
                    valLabel = `${cond.operator} Apertura`;
                  } else if (cond.metric === 'close_vs_high') {
                    valLabel = `${cond.operator} High`;
                  } else if (cond.metric === 'close_vs_low') {
                    valLabel = `${cond.operator} Low`;
                  } else if (cond.metric === 'close_vs_pm_high') {
                    valLabel = `${cond.operator} PM High`;
                  } else if (cond.metric === 'close_vs_pm_low') {
                    valLabel = `${cond.operator} PM Low`;
                  } else if (cond.metric === 'close_vs_high_low') {
                    valLabel = cond.operator === '> High' ? '> High Previo' : '< Low Previo';
                  } else if (cond.metric === 'close_vs_vwap') {
                    valLabel = `${cond.operator} VWAP`;
                  } else if (cond.metric === 'close_vs_sma') {
                    valLabel = `${cond.operator} SMA ${cond.sma_period}`;
                  } else if (cond.metric === 'candle_range_pct') {
                    metricLabel = 'Rango de Vela %';
                    valLabel = `${cond.operator} ${cond.value}%`;
                  } else if (cond.metric === 'candle_range_ratio_gap_1_vs_gap') {
                    metricLabel = cond.day === 'gap_1_day' ? 'Rango vela Gap+1 vs Gap' : 'Rango vela vs Previo';
                    valLabel = `${cond.operator} ${cond.value}%`;
                  }
                  
                  return (
                    <div
                      key={cond.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        backgroundColor: 'rgba(216, 122, 61, 0.08)',
                        border: '0.5px solid var(--color-ec-copper)',
                        borderRadius: 4,
                        padding: '4px 8px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 600,
                        color: 'var(--color-ec-text-secondary)',
                      }}
                    >
                      <span style={{ color: 'var(--color-ec-copper)' }}>{dayLabel}</span>
                      <span>•</span>
                      <span>{metricLabel}:</span>
                      <strong style={{ color: 'var(--color-ec-text-high)' }}>{valLabel}</strong>
                      
                      <button
                        type="button"
                        onClick={() => {
                          setPostgapPreconditions(postgapPreconditions.filter(p => p.id !== cond.id));
                        }}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--color-ec-text-muted)',
                          cursor: 'pointer',
                          fontSize: 12,
                          lineHeight: 1,
                          padding: '0 2px',
                          marginLeft: 4,
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* SECTION: APPLY DAY SELECTOR */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          padding: '20px 0',
          borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 3,
              height: 14,
              borderRadius: 1,
              backgroundColor: 'var(--color-ec-copper)',
            }} />
            <h2 style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 13,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--color-ec-text-high)',
              margin: 0,
            }}>Día de aplicación de la estrategia</h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, fontFamily: 'var(--color-ec-sans)' }}>
                {(['gap_day', 'gap_1_day', 'gap_2_day'] as const).map((day, idx) => {
                    const isActive = applyDay === day;
                    const labels: Record<string, string> = {
                        gap_day: 'Gap Day',
                        gap_1_day: 'Gap +1 Day',
                        gap_2_day: 'Gap +2 Day',
                    };
                    return (
                        <Fragment key={day}>
                            {idx > 0 && <span style={{ color: 'var(--color-ec-border)', fontSize: 9 }}>/</span>}
                            <span
                                onClick={() => setApplyDay(day)}
                                style={{
                                    color: isActive ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)',
                                    fontWeight: isActive ? 700 : 400,
                                    cursor: 'pointer',
                                    transition: 'color 150ms ease',
                                    fontSize: 11,
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-primary)';
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                                }}
                            >
                                {labels[day]}
                                {day !== 'gap_day' && (
                                    <span style={{
                                        marginLeft: 4,
                                        fontSize: 7,
                                        fontWeight: 700,
                                        padding: '1px 4px',
                                        borderRadius: 3,
                                        backgroundColor: 'rgba(216, 122, 61, 0.18)',
                                        color: 'var(--color-ec-copper-bright)',
                                        letterSpacing: '0.5px',
                                        verticalAlign: 'middle',
                                    }}>BETA</span>
                                )}
                            </span>
                        </Fragment>
                    );
                })}
            </div>
        </div>

        {/* SECTION: SESIÓN DE EJECUCIÓN DE LA ESTRATEGIA */}
        <div data-helper="st-sessions" style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          padding: '20px 0',
          borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 3,
              height: 14,
              borderRadius: 1,
              backgroundColor: 'var(--color-ec-copper)',
            }} />
            <h2 style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 13,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--color-ec-text-high)',
              margin: 0,
            }}>Sesión de ejecución de la estrategia</h2>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            overflow: 'hidden',
            marginTop: 4,
            backgroundColor: 'transparent'
          }}>
            {[
              { id: "pre", label: "Pre-Market", time: "04:00 - 09:30 ET" },
              { id: "rth", label: "Regular Hours", time: "09:30 - 16:00 ET" },
              { id: "post", label: "After-Market", time: "16:00 - 20:00 ET" },
              { id: "custom", label: "Horas personalizadas", time: "Personalizado ET" },
            ].map((session, idx) => {
              const isSelected = localMarketSessions.includes(session.id);
              
              // Cross lines borders
              const borderRight = (idx === 0 || idx === 2) ? '2px dotted var(--color-ec-border)' : 'none';
              const borderBottom = (idx === 0 || idx === 1) ? '2px dotted var(--color-ec-border)' : 'none';

              return (
                <div
                  key={session.id}
                  onClick={() => {
                    setLocalMarketSessions(prev =>
                      prev.includes(session.id)
                        ? prev.filter(s => s !== session.id)
                        : [...prev, session.id]
                    );
                  }}
                  style={{
                    backgroundColor: isSelected ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                    borderRight,
                    borderBottom,
                    padding: '12px 14px',
                    cursor: 'pointer',
                    transition: 'all 150ms ease',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    minHeight: 58,
                    boxSizing: 'border-box',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.backgroundColor = 'rgba(216, 122, 61, 0.03)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.backgroundColor = 'transparent';
                    }
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'space-between' }}>
                    <span style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 11,
                      fontWeight: 600,
                      color: isSelected ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-secondary)',
                    }}>{session.label}</span>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      readOnly
                      style={{
                        cursor: 'pointer',
                        accentColor: 'var(--color-ec-copper)',
                        width: '12px',
                        height: '12px'
                      }}
                    />
                  </div>
                  {session.time && (
                    <span style={{
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9,
                      fontWeight: 400,
                      color: isSelected ? 'var(--color-ec-text-secondary)' : 'var(--color-ec-text-muted)',
                      marginTop: 4,
                    }}>{session.time}</span>
                  )}
                </div>
              );
            })}
          </div>

          {localMarketSessions.includes("custom") && (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: 10,
              marginTop: 8,
              padding: 12,
              backgroundColor: 'rgba(255, 255, 255, 0.02)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 6,
            }}>
              <div>
                <label style={{
                  display: "block",
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--color-ec-text-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.03em",
                  marginBottom: 4,
                }}>Desde</label>
                <input
                  type="time"
                  value={localCustomStartTime}
                  onChange={(e) => setLocalCustomStartTime(e.target.value)}
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
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div>
                <label style={{
                  display: "block",
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--color-ec-text-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.03em",
                  marginBottom: 4,
                }}>Hasta</label>
                <input
                  type="time"
                  value={localCustomEndTime}
                  onChange={(e) => setLocalCustomEndTime(e.target.value)}
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
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>
          )}
        </div>



        <div data-helper="st-entry" style={{ display: 'contents' }}>
        <EntryLogicBuilder logic={entryLogic} onChange={setEntryLogic}>
          {/* Sub-panel de Ventanas de Horario de Entrada */}
          <div style={{
            marginTop: -11, // Offsets the 16px flex gap of the parent to achieve exactly a 5px margin
            paddingTop: 12,
            borderTop: '0.5px dotted var(--color-ec-border)',
            display: 'flex',
            flexDirection: 'column',
            gap: 10
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Clock size={12} style={{ color: 'var(--color-ec-copper)' }} />
                <span style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: 'var(--color-ec-text-secondary)'
                }}>
                  Límites horarios de ejecución de variables de entrada
                </span>
                <span
                  onMouseEnter={(e) => {
                    setActiveTooltip({
                      text: "Define ventanas de tiempo específicas dentro de la sesión de mercado en las cuales se pueden evaluar y ejecutar las condiciones de <strong>entrada</strong>. Las condiciones de <strong>salida</strong> (como Stop Loss, Take Profit y temporales) seguirán activas y se ejecutarán en cualquier momento durante toda la sesión activa de la estrategia, independientemente de estos límites.",
                      x: e.clientX,
                      y: e.clientY,
                      title: "Límites horarios de ejecución"
                    });
                  }}
                  onMouseLeave={() => setActiveTooltip(null)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    backgroundColor: "var(--color-ec-bg-elevated)",
                    border: "0.5px solid var(--color-ec-border)",
                    color: "var(--color-ec-text-muted)",
                    fontSize: 9,
                    fontWeight: 700,
                    cursor: "help",
                    marginLeft: 4,
                    flexShrink: 0,
                    userSelect: "none",
                    transition: "all 150ms ease",
                  }}
                >
                  ?
                </span>
              </div>
              <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>
                Nueva York (ET)
              </span>
            </div>

            {/* Inputs de rango */}
            <div style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'flex-end',
              flexWrap: 'wrap',
              gap: 8,
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: 8, fontWeight: 600, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Desde</span>
                <input
                  type="time"
                  value={tempFromTime}
                  onChange={(e) => setTempFromTime(e.target.value)}
                  style={{
                    background: 'var(--color-ec-bg-surface)',
                    border: '0.5px solid var(--color-ec-border)',
                    color: 'var(--color-ec-text-primary)',
                    fontSize: 10,
                    padding: '0 6px',
                    height: 24,
                    boxSizing: 'border-box',
                    borderRadius: 4,
                    outline: 'none',
                    fontFamily: 'var(--color-ec-sans)',
                    cursor: 'pointer',
                  }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: 8, fontWeight: 600, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Hasta</span>
                <input
                  type="time"
                  value={tempToTime}
                  onChange={(e) => setTempToTime(e.target.value)}
                  style={{
                    background: 'var(--color-ec-bg-surface)',
                    border: '0.5px solid var(--color-ec-border)',
                    color: 'var(--color-ec-text-primary)',
                    fontSize: 10,
                    padding: '0 6px',
                    height: 24,
                    boxSizing: 'border-box',
                    borderRadius: 4,
                    outline: 'none',
                    fontFamily: 'var(--color-ec-sans)',
                    cursor: 'pointer',
                  }}
                />
              </div>

              <button
                type="button"
                onClick={() => {
                  if (tempFromTime && tempToTime) {
                    const windows = entryLogic.entry_time_windows || [];
                    if (!windows.some(w => w.from_time === tempFromTime && w.to_time === tempToTime)) {
                      setEntryLogic({
                        ...entryLogic,
                        entry_time_windows: [...windows, { from_time: tempFromTime, to_time: tempToTime }]
                      });
                    }
                  }
                }}
                style={{
                  backgroundColor: 'var(--color-ec-copper)',
                  color: 'var(--color-ec-copper-text)',
                  border: 'none',
                  padding: '0 10px',
                  borderRadius: 4,
                  fontSize: 9,
                  fontWeight: 700,
                  cursor: 'pointer',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  height: 24,
                  boxSizing: 'border-box',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                + Añadir
              </button>
            </div>

            {/* Warning de validación de overlap para las horas ingresadas en el formulario */}
            {getSessionOverlapWarning(tempFromTime, tempToTime) && (
              <div style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                color: 'var(--color-ec-loss)',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                backgroundColor: 'rgba(235, 94, 85, 0.08)',
                padding: '4px 8px',
                borderRadius: 4,
                border: '0.5px solid rgba(235, 94, 85, 0.2)'
              }}>
                <span>⚠️</span>
                <span>El rango {tempFromTime} - {tempToTime} queda fuera de las sesiones del backtest.</span>
              </div>
            )}

            {/* Listado de ventanas */}
            {entryLogic.entry_time_windows && entryLogic.entry_time_windows.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                {entryLogic.entry_time_windows.map((window, idx) => {
                  const overlapWarning = getSessionOverlapWarning(window.from_time, window.to_time);
                  return (
                    <div
                      key={idx}
                      title={overlapWarning || undefined}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        backgroundColor: overlapWarning ? 'rgba(235, 94, 85, 0.08)' : 'rgba(216, 122, 61, 0.08)',
                        border: `0.5px solid ${overlapWarning ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)'}`,
                        borderRadius: 4,
                        padding: '4px 8px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 600,
                        color: overlapWarning ? 'var(--color-ec-loss)' : 'var(--color-ec-text-secondary)',
                      }}
                    >
                      <span>{window.from_time} - {window.to_time}</span>
                      {overlapWarning && <span style={{ cursor: 'help' }}>⚠️</span>}
                      <button
                        type="button"
                        onClick={() => {
                          const windows = entryLogic.entry_time_windows || [];
                          setEntryLogic({
                            ...entryLogic,
                            entry_time_windows: windows.filter((_, i) => i !== idx)
                          });
                        }}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--color-ec-text-muted)',
                          cursor: 'pointer',
                          fontSize: 10,
                          lineHeight: 1,
                          padding: '0 1px',
                          marginLeft: 2,
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </EntryLogicBuilder>
        </div>

        <ExitLogicBuilder logic={exitLogic} onChange={setExitLogic} />
        <div data-helper="st-risk" style={{ display: 'contents' }}>
        <RiskManagementComponent risk={riskManagement} onChange={setRiskManagement} applyDay={applyDay} />
        </div>
      </div>

      {/* Strategy Summary Panel */}
      <div style={{
        borderTop: "0.5px solid var(--color-ec-border)",
        backgroundColor: "var(--color-ec-bg-surface)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
      }}>
        {/* Toggle Header */}
        <div
          onClick={() => setSummaryExpanded(!summaryExpanded)}
          style={{
            padding: "10px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            cursor: "pointer",
            userSelect: "none",
            backgroundColor: "rgba(255, 255, 255, 0.01)",
            transition: "background-color 150ms ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.01)";
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 10,
              fontWeight: 700,
              color: "var(--color-ec-text-high)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}>
              Resumen de Configuración
            </span>
            <span style={{
              fontSize: 9,
              fontWeight: 700,
              backgroundColor: 'rgba(216, 122, 61, 0.1)',
              color: 'var(--color-ec-copper-bright)',
              padding: '1px 6px',
              borderRadius: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.05em'
            }}>
              {totalConfigCount} {totalConfigCount === 1 ? 'regla' : 'reglas'}
            </span>
          </div>
          <span style={{
            fontSize: 9,
            fontWeight: 700,
            color: "var(--color-ec-copper)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}>
            {summaryExpanded ? "Ocultar ▲" : "Ver Detalles ▼"}
          </span>
        </div>

        {/* Collapsible Content */}
        {summaryExpanded && (
          <div style={{
            padding: "0 16px 16px 16px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
            borderTop: "0.5px solid rgba(255, 255, 255, 0.03)",
            maxHeight: 250,
            overflowY: "auto",
            scrollbarWidth: "none",
          }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 12 }}>
              {/* Left Column: General & Risk */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {/* General Config */}
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <span style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Configuración General</span>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {/* Bias */}
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      backgroundColor: 'rgba(255, 255, 255, 0.03)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 4,
                      padding: '3px 6px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9.5,
                      fontWeight: 500,
                    }}>
                      <span style={{ color: 'var(--color-ec-text-secondary)' }}>Dirección:</span>
                      <strong style={{
                        color: bias === "long" ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
                        marginLeft: 3
                      }}>
                        {bias === "long" ? "LONG" : "SHORT"}
                      </strong>
                    </span>

                    {/* Apply Day */}
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      backgroundColor: 'rgba(255, 255, 255, 0.03)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 4,
                      padding: '3px 6px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9.5,
                      fontWeight: 500,
                    }}>
                      <span style={{ color: 'var(--color-ec-text-secondary)' }}>Aplicar en:</span>
                      <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>
                        {applyDay === "gap_day" ? "Gap Day" : applyDay === "gap_1_day" ? "Gap +1 Day" : "Gap +2 Day"}
                      </strong>
                    </span>

                    {/* Sessions */}
                    {localMarketSessions.length > 0 && (
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        backgroundColor: 'rgba(255, 255, 255, 0.03)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 4,
                        padding: '3px 6px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 9.5,
                        fontWeight: 500,
                      }}>
                        <span style={{ color: 'var(--color-ec-text-secondary)' }}>Sesión:</span>
                        <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>
                          {getSessionsText(localMarketSessions, localCustomStartTime, localCustomEndTime)}
                        </strong>
                      </span>
                    )}
                  </div>
                </div>

                {/* Preconditions */}
                {postgapPreconditions.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                    <span style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Condiciones Previas ({postgapPreconditions.length})</span>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {postgapPreconditions.map((cond, idx) => {
                        const fmt = formatPreconditionText(cond);
                        return (
                          <span key={idx} style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            backgroundColor: 'rgba(216, 122, 61, 0.05)',
                            border: '0.5px solid rgba(216, 122, 61, 0.3)',
                            borderRadius: 4,
                            padding: '3px 6px',
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 9.5,
                            fontWeight: 500,
                          }}>
                            <span style={{ color: 'var(--color-ec-text-secondary)' }}>{fmt.label}</span>
                            <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{fmt.value}</strong>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Risk Management */}
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <span style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Gestión de Riesgo</span>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {/* Stop Loss */}
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      backgroundColor: 'rgba(255, 255, 255, 0.03)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 4,
                      padding: '3px 6px',
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 9.5,
                      fontWeight: 500,
                    }}>
                      <span style={{ color: 'var(--color-ec-text-secondary)' }}>Stop Loss:</span>
                      <strong style={{ color: 'var(--color-ec-loss)', marginLeft: 3 }}>{riskManagement.hard_stop.value}%</strong>
                    </span>

                    {/* Take Profit */}
                    {riskManagement.use_take_profit && (
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        backgroundColor: 'rgba(255, 255, 255, 0.03)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 4,
                        padding: '3px 6px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 9.5,
                        fontWeight: 500,
                      }}>
                        {riskManagement.take_profit_mode === 'Partial' ? (
                          <>
                            <span style={{ color: 'var(--color-ec-text-secondary)' }}>TP Parcial:</span>
                            <strong style={{ color: 'var(--color-ec-profit)', marginLeft: 3 }}>
                              {(riskManagement.partial_take_profits || []).map(tp => `${tp.distance_pct}% (${tp.capital_pct}%)`).join(" / ")}
                            </strong>
                          </>
                        ) : (
                          <>
                            <span style={{ color: 'var(--color-ec-text-secondary)' }}>Take Profit:</span>
                            <strong style={{ color: 'var(--color-ec-profit)', marginLeft: 3 }}>{riskManagement.take_profit.value}%</strong>
                          </>
                        )}
                      </span>
                    )}

                    {/* Trailing Stop */}
                    {riskManagement.trailing_stop?.active && (
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        backgroundColor: 'rgba(255, 255, 255, 0.03)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 4,
                        padding: '3px 6px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 9.5,
                        fontWeight: 500,
                      }}>
                        <span style={{ color: 'var(--color-ec-text-secondary)' }}>Trailing Stop:</span>
                        <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{riskManagement.trailing_stop?.buffer_pct}%</strong>
                      </span>
                    )}

                    {/* Reentries */}
                    {riskManagement.accept_reentries && (
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        backgroundColor: 'rgba(255, 255, 255, 0.03)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 4,
                        padding: '3px 6px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 9.5,
                        fontWeight: 500,
                      }}>
                        <span style={{ color: 'var(--color-ec-text-secondary)' }}>Reentradas:</span>
                        <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>Máx. {riskManagement.max_reentries}</strong>
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Right Column: Entry & Exit Logics */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {/* Entry Logic */}
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <span style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Lógica de Entrada ({entryCount})</span>
                  {entryCount === 0 ? (
                    <span style={{ fontSize: 9.5, fontStyle: "italic", color: "var(--color-ec-text-muted)" }}>Sin condiciones de entrada.</span>
                  ) : (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {getLeafConditions(entryLogic.root_condition, entryLogic.timeframe).map((cond, idx) => (
                        <span key={idx} style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          backgroundColor: 'rgba(34, 197, 94, 0.04)',
                          border: '0.5px solid rgba(34, 197, 94, 0.25)',
                          borderRadius: 4,
                          padding: '3px 6px',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 9.5,
                          fontWeight: 500,
                        }}>
                          <span style={{ color: 'var(--color-ec-text-secondary)' }}>{cond.label}</span>
                          <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{cond.value}</strong>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Exit Logic */}
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <span style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Lógica de Salida ({exitCount})</span>
                  {exitCount === 0 ? (
                    <span style={{ fontSize: 9.5, fontStyle: "italic", color: "var(--color-ec-text-muted)" }}>Sin condiciones de salida.</span>
                  ) : (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {getLeafConditions(exitLogic.root_condition, exitLogic.timeframe).map((cond, idx) => (
                        <span key={idx} style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          backgroundColor: 'rgba(239, 68, 68, 0.04)',
                          border: '0.5px solid rgba(239, 68, 68, 0.25)',
                          borderRadius: 4,
                          padding: '3px 6px',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 9.5,
                          fontWeight: 500,
                        }}>
                          <span style={{ color: 'var(--color-ec-text-secondary)' }}>{cond.label}</span>
                          <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{cond.value}</strong>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          flexShrink: 0,
          padding: "12px 16px",
          borderTop: "0.5px solid var(--color-ec-border)",
          backgroundColor: "var(--color-ec-bg-base)",
        }}
      >
        <button
          onClick={handleTest}
          disabled={isRiskInvalid}
          style={{
            width: "100%",
            padding: "8px 0",
            borderRadius: 5,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.2,
            textTransform: "uppercase",
            cursor: isRiskInvalid ? "not-allowed" : "pointer",
            border: "none",
            backgroundColor: "var(--color-ec-copper)",
            color: "var(--color-ec-copper-text)",
            fontFamily: "var(--color-ec-sans)",
            opacity: isRiskInvalid ? 0.35 : 1,
            transition: "all 150ms ease",
          }}
        >
          ▶ Probar
        </button>
      </div>

      {activeTooltip && typeof document !== "undefined" && createPortal(
        <div
          style={{
            position: "fixed",
            top: activeTooltip.y,
            left: activeTooltip.x,
            transform: "translate(10px, -100%)",
            backgroundColor: "var(--color-ec-bg-elevated)",
            color: "var(--color-ec-text-primary)",
            border: "0.5px solid var(--color-ec-border)",
            borderRadius: 4,
            padding: "6px 8px",
            lineHeight: 1.3,
            width: 220,
            zIndex: 100005,
            pointerEvents: "none",
            boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
            fontFamily: "var(--color-ec-sans)",
            whiteSpace: "normal",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            textAlign: 'left',
          }}
        >
          {activeTooltip.title && (
            <strong style={{ display: 'block', color: 'var(--color-ec-copper)', fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 2 }}>
              {activeTooltip.title}
            </strong>
          )}
          <span 
            style={{ fontSize: 9.5, color: "var(--color-ec-text-high)", lineHeight: 1.3 }}
            dangerouslySetInnerHTML={{ __html: activeTooltip.text }}
          />
        </div>,
        document.body
      )}
    </div>
  );
}
