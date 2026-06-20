"use client";

import { useState, useEffect, useMemo, useRef, Fragment } from "react";
import type {
  EntryLogic as EntryLogicType,
  ExitLogic as ExitLogicType,
  RiskManagement as RiskManagementType,
  PostGapPrecondition,
  ConditionGroup,
  PartialTakeProfit,
} from "@/types/strategy";
import {
  initialEntryLogic,
  initialExitLogic,
  initialRiskManagement,
  RiskType,
  IndicatorType,
  Comparator,
  TakeProfitMode,
} from "@/types/strategy";
import { fetchDatasets, fetchAvailableDateRange, type Dataset } from "@/lib/api_backtester";
import { EntryLogicBuilder } from "@/components/strategy-builder/EntryLogic";
import { ExitLogicBuilder } from "@/components/strategy-builder/ExitLogic";
import { RiskManagementComponent } from "@/components/strategy-builder/RiskManagement";
import { validateStrategyLogic } from "@/lib/strategyValidation";
import { getAllowedTargets } from "@/lib/indicatorValidation";
import { INDICATOR_LABELS, COMPARATOR_LABELS, INDICATOR_CATEGORIES, INDICATOR_DESCRIPTIONS, getDefaultParamsForIndicator } from "@/components/strategy-builder/ConditionBuilder";
import { Clock, Plus, Trash2, Info, Sparkles, Database, SlidersHorizontal } from "lucide-react";

export interface WizardDraft {
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

const MARKET_LEVEL_LABELS: Record<string, string> = {
  "HOD": "HOD",
  "LOD": "LOD",
  "PMH": "PMH",
  "PML": "PML",
  "Previous Max": "Prev. Max",
  "Previous Min": "Prev. Min"
};

const MARKET_LEVEL_DESCRIPTIONS: Record<string, string> = {
  "HOD": "Máximo Diario (High of Day). El precio más alto alcanzado durante la sesión regular de hoy.",
  "LOD": "Mínimo Diario (Low of Day). El precio más bajo alcanzado durante la sesión regular de hoy.",
  "PMH": "Máximo Pre-market (PM High). El precio más alto registrado en el pre-market de hoy.",
  "PML": "Mínimo Pre-market (PM Low). El precio más bajo registrado en el pre-market de hoy.",
  "Previous Max": "Máximo Día Anterior (Previous Day High). El precio más alto de la sesión de ayer.",
  "Previous Min": "Mínimo Día Anterior (Previous Day Low). El precio más bajo de la sesión de ayer."
};

const CustomTooltip = ({ title, text }: { title?: string; text: string }) => {
  const [hovered, setHovered] = useState(false);
  const [coords, setCoords] = useState({ x: 0, y: 0 });

  const handleMouseEnter = (e: React.MouseEvent) => {
    setCoords({ x: e.clientX, y: e.clientY });
    setHovered(true);
  };

  return (
    <span 
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 13,
        height: 13,
        borderRadius: '50%',
        backgroundColor: 'var(--color-ec-bg-elevated)',
        border: '0.5px solid var(--color-ec-border)',
        color: 'var(--color-ec-text-muted)',
        fontSize: 9,
        fontWeight: 700,
        cursor: 'help',
        marginLeft: 4,
        flexShrink: 0,
        userSelect: 'none',
      }}
    >
      ?
      {hovered && (
        <span style={{
          position: 'fixed',
          top: coords.y,
          left: coords.x,
          transform: 'translate(0, -100%)',
          backgroundColor: 'var(--color-ec-bg-elevated)',
          border: '0.5px solid var(--color-ec-border)',
          borderRadius: 4,
          padding: '6px 8px',
          color: 'var(--color-ec-text-primary)',
          fontSize: 9.5,
          fontWeight: 400,
          whiteSpace: 'normal',
          width: 185,
          boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
          zIndex: 100005,
          textAlign: 'left',
          pointerEvents: 'none',
          lineHeight: '1.3',
          fontFamily: 'var(--color-ec-sans)',
        }}>
          {title && (
            <strong style={{ display: 'block', color: 'var(--color-ec-copper)', fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 2 }}>
              {title}
            </strong>
          )}
          <span 
            style={{ fontSize: 9.5, color: "var(--color-ec-text-high)", lineHeight: 1.3 }}
            dangerouslySetInnerHTML={{ __html: text }}
          />
        </span>
      )}
    </span>
  );
};

interface WizardIndicatorSelectorProps {
  value: IndicatorType;
  onChange: (val: IndicatorType) => void;
  allowedTargets?: IndicatorType[];
  exclude?: IndicatorType[];
}

const WizardIndicatorSelector: React.FC<WizardIndicatorSelectorProps> = ({
  value,
  onChange,
  allowedTargets,
  exclude = []
}) => {
  const wizardExclusions = [
    IndicatorType.HIGH_X_DAYS,
    IndicatorType.LOW_X_DAYS,
    IndicatorType.TRIANGLE_ASCENDING,
    IndicatorType.TRIANGLE_DESCENDING,
    IndicatorType.TRIANGLE_SYMMETRIC
  ];
  const combinedExclude = [...exclude, ...wizardExclusions];

  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const selectedLabel = INDICATOR_LABELS[value] || value;

  return (
    <div ref={containerRef} style={{ position: "relative", width: "100%" }}>
      {/* Trigger Button */}
      <div
        onClick={() => {
          setIsOpen(!isOpen);
        }}
        style={{
          width: "100%",
          backgroundColor: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          color: "var(--color-ec-text-primary)",
          fontSize: 11,
          padding: "6px 10px",
          borderRadius: 5,
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          userSelect: "none",
          boxSizing: "border-box"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, overflow: "hidden", flex: 1 }}>
          <span style={{ textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>{selectedLabel}</span>
          <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex", alignItems: "center" }}>
            <CustomTooltip
              title={INDICATOR_LABELS[value] || value}
              text={INDICATOR_DESCRIPTIONS[value] || ""}
            />
          </span>
        </div>
        <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)" }}>
          {isOpen ? "▲" : "▼"}
        </span>
      </div>

      {isOpen && (
        <div style={{ display: "flex", position: "absolute", top: "105%", left: 0, zIndex: 1000, width: "100%" }}>
          {/* Dropdown Menu */}
          <div 
            style={{
              width: "100%",
              maxHeight: 200,
              overflowY: "auto",
              backgroundColor: "var(--color-ec-bg-elevated)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 5,
              boxShadow: "0 6px 16px rgba(0,0,0,0.15)",
              scrollbarWidth: "none",
            }}
          >
            {Object.entries(INDICATOR_CATEGORIES).map(([category, indicators]) => {
              const filtered = (allowedTargets 
                ? indicators.filter(ind => allowedTargets.includes(ind))
                : indicators).filter(ind => !combinedExclude.includes(ind));
              if (filtered.length === 0) return null;

              return (
                <div key={category}>
                  {/* Category Header */}
                  <div style={{
                    padding: "4px 8px",
                    fontSize: 8,
                    fontWeight: 700,
                    color: "var(--color-ec-text-muted)",
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    borderBottom: "0.5px solid var(--color-ec-border)",
                    backgroundColor: "rgba(255, 255, 255, 0.02)",
                  }}>
                    {category}
                  </div>
                  {/* Category Options */}
                  {filtered.map((ind) => {
                    const isSelected = value === ind;
                    return (
                      <div
                        key={ind}
                        onClick={() => {
                          onChange(ind);
                          setIsOpen(false);
                        }}
                        style={{
                          padding: "6px 8px",
                          fontSize: 10,
                          color: isSelected ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                          fontWeight: isSelected ? 700 : 500,
                          cursor: "pointer",
                          display: "flex",
                          justifyContent: "flex-start",
                          alignItems: "center",
                          gap: 6,
                          backgroundColor: isSelected ? "rgba(216, 122, 61, 0.06)" : "transparent",
                          borderLeft: isSelected ? "2px solid var(--color-ec-copper)" : "2px solid transparent",
                          transition: "all 100ms ease",
                        }}
                        onMouseEnter={(e) => {
                          if (!isSelected) {
                            e.currentTarget.style.backgroundColor = "var(--color-ec-bg-surface)";
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (!isSelected) {
                            e.currentTarget.style.backgroundColor = "transparent";
                          }
                        }}
                      >
                        <span style={{ textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>{INDICATOR_LABELS[ind] || ind}</span>
                        <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex", alignItems: "center" }}>
                          <CustomTooltip
                            title={INDICATOR_LABELS[ind] || ind}
                            text={INDICATOR_DESCRIPTIONS[ind] || ""}
                          />
                        </span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

interface Props {
  onBack: () => void;
  onTest: (draft: WizardDraft) => void;
  onDraftChange?: (draft: WizardDraft) => void;
  marketSessions?: string[];
  customStartTime?: string;
  customEndTime?: string;
  initialStrategy?: any;
  onExpandedChange?: (expanded: boolean) => void;
}

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

function formatFilterValue(key: string, value: any): string | null {
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

function formatRule(rule: any): string {
  if (!rule || !rule.metric) return '';
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
  return `${friendlyMetric} ${op} ${friendlyVal}`;
}

/* ── All wizard steps, matching InlineStrategyBuilder sections ── */
const STEPS = [
  { key: "universo",        label: "Universo",           shortLabel: "Universo" },
  { key: "bias",            label: "Dirección",          shortLabel: "Bias" },
  { key: "apply_day",       label: "Día de aplicación",  shortLabel: "Día" },
  { key: "market_sessions", label: "Sesión de aplicación", shortLabel: "Sesión" },
  { key: "entry",           label: "Lógica de entrada",  shortLabel: "Entry" },
  { key: "exit",            label: "Lógica de salida",   shortLabel: "Exit" },
  { key: "risk",            label: "Gestión de riesgo",  shortLabel: "Riesgo" },
  { key: "summary",         label: "Resumen de estrategia", shortLabel: "Resumen" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

// Recursive helper to format logic builder conditions in full text, matching free config formulas
function getConditionStrings(group: ConditionGroup, timeframe: string): string[] {
  if (!group.conditions || group.conditions.length === 0) return [];
  
  const list: string[] = [];
  
  group.conditions.forEach(c => {
    if (c.type === 'group') {
      list.push(...getConditionStrings(c, timeframe));
    } else {
      const tfStr = c.timeframe ? `[${c.timeframe}] ` : `[${timeframe}] `;
      if (c.type === 'indicator_comparison') {
        if (c.source.name === IndicatorType.ELAPSED_TIME) {
          list.push(`${tfStr}Elapsed Time = ${c.target} mins`);
        } else if (c.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
          list.push(`${tfStr}Elapsed Time Last High ≥ ${c.target} mins`);
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
          list.push(`${tfStr}${sourceStr} ${compStr} ${targetStr}`);
        }
      } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        const posStr = c.position && c.position !== 'any' ? ` (${c.position})` : '';
        list.push(`${tfStr}Dist(${sourceStr}, ${levelStr}) ${compStr} ${c.value_pct}%${posStr}`);
      }
    }
  });
  
  return list;
}

// Recursive helper to build tag objects with deletion callbacks for condition builder groups
function getConditionTags(
  group: ConditionGroup,
  timeframe: string,
  onChange: (newGroup: ConditionGroup) => void
): { label: string; onRemove: () => void }[] {
  if (!group.conditions || group.conditions.length === 0) return [];
  
  const tags: { label: string; onRemove: () => void }[] = [];
  
  group.conditions.forEach((c, idx) => {
    if (c.type === 'group') {
      const subTags = getConditionTags(c, timeframe, (newSub) => {
        const newConds = [...group.conditions];
        newConds[idx] = newSub;
        onChange({ ...group, conditions: newConds });
      });
      tags.push(...subTags);
    } else {
      const tfStr = c.timeframe ? `[${c.timeframe}] ` : `[${timeframe}] `;
      let label = '';
      if (c.type === 'indicator_comparison') {
        if (c.source.name === IndicatorType.ELAPSED_TIME) {
          label = `${tfStr}Elapsed Time = ${c.target} mins`;
        } else if (c.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
          label = `${tfStr}Elapsed Time Last High ≥ ${c.target} mins`;
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
          label = `${tfStr}${sourceStr} ${compStr} ${targetStr}`;
        }
      } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        const posStr = c.position && c.position !== 'any' ? ` (${c.position})` : '';
        label = `${tfStr}Dist(${sourceStr}, ${levelStr}) ${compStr} ${c.value_pct}%${posStr}`;
      }
      
      if (label) {
        tags.push({
          label,
          onRemove: () => {
            const newConds = group.conditions.filter((_, i) => i !== idx);
            onChange({ ...group, conditions: newConds });
          }
        });
      }
    }
  });
  
  return tags;
}

// Format preconditions in full text
function formatPrecondition(cond: PostGapPrecondition): string {
  const dayLabel = cond.day === 'gap_day' ? 'Día del Gap' : 'Día Gap +1';
  let metricLabel = 'Cierre';
  let valLabel = '';

  if (cond.metric === 'volume') {
    metricLabel = 'Volumen';
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
    metricLabel = 'Rango Vela';
    valLabel = `${cond.operator} ${cond.value}%`;
  } else if (cond.metric === 'candle_range_ratio_gap_1_vs_gap') {
    metricLabel = 'Rango Gap+1 vs Gap';
    valLabel = `${cond.operator} ${cond.value}%`;
  }

  return `[${dayLabel}] ${metricLabel} ${valLabel}`;
}

const isTriangle = (name: string) =>
  name === IndicatorType.TRIANGLE_ASCENDING ||
  name === IndicatorType.TRIANGLE_DESCENDING ||
  name === IndicatorType.TRIANGLE_SYMMETRIC;

const isVolumeIndicator = (name?: string): boolean => {
  if (!name) return false;
  return (
    name === IndicatorType.VOLUME ||
    name === IndicatorType.ACCUMULATED_VOLUME ||
    name === IndicatorType.YESTERDAY_VOLUME
  );
};

export default function WizardStrategyBuilder({
  onBack,
  onTest,
  onDraftChange,
  marketSessions = ["rth"],
  customStartTime = "09:30",
  customEndTime = "16:00",
  initialStrategy,
  onExpandedChange,
}: Props) {
  const [currentStep, setCurrentStep] = useState(0);
  const createdAtRef = useRef(new Date().toISOString());
  const lastLoadedStrategyRef = useRef<string>("");

  // Load strategy from prop when initialStrategy is provided
  useEffect(() => {
    if (!initialStrategy) return;
    if ((initialStrategy.id === "draft" || initialStrategy.id === "wizard_draft") && lastLoadedStrategyRef.current !== "") return;

    const stratObj = initialStrategy.definition ? initialStrategy.definition : initialStrategy;
    const str = JSON.stringify({
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
      setWizardMarketSessions(stratObj.market_sessions);
    } else {
      setWizardMarketSessions(marketSessions || ["rth"]);
    }
    if (stratObj.custom_start_time) setWizardCustomStartTime(stratObj.custom_start_time);
    if (stratObj.custom_end_time) setWizardCustomEndTime(stratObj.custom_end_time);
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
  const [isUnivFiltroOpen, setIsUnivFiltroOpen] = useState(false);
  const univFiltroDropdownRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (univFiltroDropdownRef.current && !univFiltroDropdownRef.current.contains(e.target as Node)) {
        setIsUnivFiltroOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Custom Universe Rules Form States
  const [tempUnivDay, setTempUnivDay] = useState<'gap_day' | 'gap_plus_1_day' | 'gap_plus_2_day'>('gap_day');
  const [tempUnivParam, setTempUnivParam] = useState<string>('gap_pct');
  const [tempUnivOp, setTempUnivOp] = useState<string>('>=');
  const [tempUnivVal1, setTempUnivVal1] = useState<string>('2.0');
  const [tempUnivVal2, setTempUnivVal2] = useState<string>('');

  useEffect(() => {
    if (onExpandedChange) {
      const isUnivStep = STEPS[currentStep]?.key === 'universo';
      const isBetween = tempUnivOp === 'between';
      onExpandedChange(isUnivStep && isBetween);
    }
    return () => {
      onExpandedChange?.(false);
    };
  }, [currentStep, tempUnivOp, onExpandedChange]);

  // Fetch datasets list and available date range
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
        console.error("Error loading datasets/dates in Wizard:", err);
      } finally {
        setLoadingDatasets(false);
      }
    };
    loadDatasetsList();
  }, []);

  // Strategy Builder States
  const [bias, setBias] = useState<"long" | "short" | null>(null);
  const [hoveredBias, setHoveredBias] = useState<"long" | "short" | null>(null);
  const [applyDay, setApplyDay] = useState<'gap_day' | 'gap_1_day' | 'gap_2_day'>('gap_day');
  const [wizardMarketSessions, setWizardMarketSessions] = useState<string[]>(initialStrategy?.definition?.market_sessions || initialStrategy?.market_sessions || marketSessions || ["rth"]);
  const [wizardCustomStartTime, setWizardCustomStartTime] = useState<string>(initialStrategy?.definition?.custom_start_time || initialStrategy?.custom_start_time || customStartTime || "09:30");
  const [wizardCustomEndTime, setWizardCustomEndTime] = useState<string>(initialStrategy?.definition?.custom_end_time || initialStrategy?.custom_end_time || customEndTime || "16:00");
  const [postgapPreconditions, setPostgapPreconditions] = useState<PostGapPrecondition[]>([]);
  const [entryLogic, setEntryLogic] = useState<EntryLogicType>(initialEntryLogic);
  const [exitLogic, setExitLogic] = useState<ExitLogicType>(initialExitLogic);
  const [riskManagement, setRiskManagement] = useState<RiskManagementType>(initialRiskManagement);

  // Preconditions Form States
  const [tempDay, setTempDay] = useState<'gap_day' | 'gap_1_day'>('gap_day');
  const [tempSource, setTempSource] = useState<'cierre' | 'volume' | 'candle_range_pct' | 'candle_range_ratio_gap_1_vs_gap'>('cierre');
  const [tempOperator, setTempOperator] = useState<'>' | '<'>('>');
  const [tempTarget, setTempTarget] = useState<'apertura' | 'high_gap_day' | 'low_gap_day' | 'pm_high' | 'pm_low' | 'vwap' | 'sma'>('apertura');
  const [tempValue, setTempValue] = useState<number>(1000000);
  const [tempVolumeText, setTempVolumeText] = useState<string>("1.0");
  const [tempSmaPeriod, setTempSmaPeriod] = useState<number>(20);

  // Time Window Form States
  const [tempFromTime, setTempFromTime] = useState("09:30");
  const [tempToTime, setTempToTime] = useState("16:00");

  /* ── Track completed steps ── */
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set());

  // Step-by-step condition builder states in Wizard mode
  const [wizardCondStep, setWizardCondStep] = useState<number>(-1);
  const [wizardTf, setWizardTf] = useState<string>("1m");
  const [wizardSource, setWizardSource] = useState<IndicatorType>(IndicatorType.BAR_CLOSE);
  const [wizardSourcePeriod, setWizardSourcePeriod] = useState<number>(14);
  const [wizardSourceDev, setWizardSourceDev] = useState<number>(2);
  const [wizardSourceBand, setWizardSourceBand] = useState<string>("Upper");
  const [wizardSourceDays, setWizardSourceDays] = useState<number>(5);
  const [wizardSourceOrb, setWizardSourceOrb] = useState<number>(30);
  const [wizardMode, setWizardMode] = useState<"comparison" | "distance">("comparison");
  const [wizardComparator, setWizardComparator] = useState<any>(Comparator.GT);
  const [wizardTargetType, setWizardTargetType] = useState<"fixed" | "indicator">("fixed");
  const [wizardTargetValue, setWizardTargetValue] = useState<number>(0);
  const [wizardTargetValueText, setWizardTargetValueText] = useState<string>("");
  const [wizardTargetIndicator, setWizardTargetIndicator] = useState<IndicatorType>(IndicatorType.VWAP);
  const [wizardTargetPeriod, setWizardTargetPeriod] = useState<number>(14);
  const [wizardTargetDev, setWizardTargetDev] = useState<number>(2);
  const [wizardTargetBand, setWizardTargetBand] = useState<string>("Upper");
  const [wizardTargetDays, setWizardTargetDays] = useState<number>(5);
  const [wizardTargetOrb, setWizardTargetOrb] = useState<number>(30);
  const [wizardDistanceLevel, setWizardDistanceLevel] = useState<IndicatorType>(IndicatorType.VWAP);
  const [wizardDistanceLevelPeriod, setWizardDistanceLevelPeriod] = useState<number>(14);
  const [wizardDistanceValue, setWizardDistanceValue] = useState<number>(0.5);
  const [wizardTargetOffset, setWizardTargetOffset] = useState<number>(0);
  const [wizardDistanceLevelOffset, setWizardDistanceLevelOffset] = useState<number>(0);
  const [isLevelDropdownOpen, setIsLevelDropdownOpen] = useState(false);
  const slLevelDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (slLevelDropdownRef.current && !slLevelDropdownRef.current.contains(e.target as Node)) {
        setIsLevelDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const [wizardSourceSession, setWizardSourceSession] = useState<"ap.PM" | "ap.RTH" | "ap.AM">("ap.RTH");
  const [wizardTargetSession, setWizardTargetSession] = useState<"ap.PM" | "ap.RTH" | "ap.AM">("ap.RTH");
  const [wizardDistanceLevelSession, setWizardDistanceLevelSession] = useState<"ap.PM" | "ap.RTH" | "ap.AM">("ap.RTH");
  const [wizardRiskStep, setWizardRiskStep] = useState<number>(0);

  // Triangle Pattern States
  const [wizardSourcePivotWindow, setWizardSourcePivotWindow] = useState<number>(5);
  const [wizardSourceMinPivots, setWizardSourceMinPivots] = useState<number>(2);
  const [wizardSourceTriLookback, setWizardSourceTriLookback] = useState<number>(35);
  const [wizardSourceSlopeTolerance, setWizardSourceSlopeTolerance] = useState<number>(1.5);
  const [wizardSourceMinRSquared, setWizardSourceMinRSquared] = useState<number>(0.65);

  // Price Level Distance Position
  const [wizardDistancePosition, setWizardDistancePosition] = useState<'above' | 'below' | 'any'>('any');


  // Check market session overlaps for time windows
  const getSessionOverlapWarning = (fromTime: string, toTime: string) => {
    if (!marketSessions || marketSessions.length === 0 || marketSessions.includes("all")) {
      return null;
    }

    const parseTimeToMins = (t: string) => {
      const [h, m] = t.split(":").map(Number);
      return h * 60 + m;
    };

    const windowStart = parseTimeToMins(fromTime);
    const windowEnd = parseTimeToMins(toTime);

    const intervals: { label: string; start: number; end: number }[] = [];
    marketSessions.forEach(s => {
      if (s === "pre") {
        intervals.push({ label: "Pre-Market", start: 240, end: 570 });
      } else if (s === "rth") {
        intervals.push({ label: "Regular Hours", start: 570, end: 960 });
      } else if (s === "post") {
        intervals.push({ label: "After-Market", start: 960, end: 1200 });
      } else if (s === "custom" && customStartTime && customEndTime) {
        intervals.push({
          label: `Custom (${customStartTime}-${customEndTime})`,
          start: parseTimeToMins(customStartTime),
          end: parseTimeToMins(customEndTime)
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

  // Preconditions synchronization when applyDay changes
  useEffect(() => {
    if (applyDay === 'gap_day') {
      setPostgapPreconditions([]);
    } else if (applyDay === 'gap_1_day') {
      setPostgapPreconditions(prev => prev.map(p => ({ ...p, day: 'gap_day' })));
      setTempDay('gap_day');
      if (tempSource === 'candle_range_ratio_gap_1_vs_gap') {
        setTempSource('cierre');
      }
    }
  }, [applyDay]);

  // Synchronize wizardDistanceLevel when wizardSource changes
  useEffect(() => {
    const allowed = getAllowedTargets(wizardSource, "price_level_distance");
    if (allowed.length > 0 && !allowed.includes(wizardDistanceLevel)) {
      setWizardDistanceLevel(allowed[0]);
    }
  }, [wizardSource, wizardDistanceLevel]);

  // Synchronize wizardTargetType and wizardTargetIndicator when wizardSource changes
  useEffect(() => {
    const allowed = getAllowedTargets(wizardSource, "indicator_comparison");
    if (allowed.length === 0) {
      setWizardTargetType("fixed");
    } else if (wizardTargetType === "indicator" && !allowed.includes(wizardTargetIndicator)) {
      setWizardTargetIndicator(allowed[0]);
    }
  }, [wizardSource, wizardTargetType, wizardTargetIndicator]);

  // Synchronize wizardMode and wizardComparator when wizardSource changes
  useEffect(() => {
    const supportsDist = getAllowedTargets(wizardSource, "price_level_distance").length > 0;
    if (!supportsDist) {
      setWizardMode("comparison");
      if (wizardComparator === "DISTANCE_GT" || wizardComparator === "DISTANCE_LT") {
        setWizardComparator(Comparator.GT);
      }
    }
    const isCrossAllowed = [
      IndicatorType.BAR_CLOSE,
      IndicatorType.BAR_OPEN,
      IndicatorType.HIGH_BAR,
      IndicatorType.LOW_BAR,
      IndicatorType.SMA,
      IndicatorType.EMA,
      IndicatorType.VWAP
    ].includes(wizardSource);

    if (!isCrossAllowed && (wizardComparator === Comparator.CROSSES_ABOVE || wizardComparator === Comparator.CROSSES_BELOW)) {
      setWizardComparator(Comparator.GT);
    }
  }, [wizardSource, wizardComparator]);

  // Synchronize wizardTargetValueText when wizardTargetValue or wizardSource changes
  useEffect(() => {
    if (isVolumeIndicator(wizardSource)) {
      const clean = wizardTargetValueText.trim().toLowerCase();
      const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
      const parsedVal = parseFloat(numericStr) * 1000000;
      if (isNaN(parsedVal) || parsedVal !== wizardTargetValue || wizardTargetValueText === "") {
        setWizardTargetValueText((wizardTargetValue / 1000000).toString());
      }
    } else {
      setWizardTargetValueText(wizardTargetValue.toString());
    }
  }, [wizardTargetValue, wizardSource]);

  // Reset condition wizard when changing main step
  useEffect(() => {
    setWizardCondStep(-1);
    setWizardSource(IndicatorType.BAR_CLOSE);
    setWizardMode("comparison");
    setWizardComparator(Comparator.GT);
    setWizardTargetType("fixed");
    setWizardTargetValue(0);
    setWizardTargetValueText("");
    setWizardTargetOffset(0);
    setWizardDistanceLevelOffset(0);
    setWizardSourceSession("ap.RTH");
    setWizardTargetSession("ap.RTH");
    setWizardDistanceLevelSession("ap.RTH");
    setWizardRiskStep(0);
    setWizardSourcePivotWindow(5);
    setWizardSourceMinPivots(2);
    setWizardSourceTriLookback(35);
    setWizardSourceSlopeTolerance(1.5);
    setWizardSourceMinRSquared(0.65);
    setWizardDistancePosition('any');
  }, [currentStep]);

  // Update parent with latest draft strategy
  useEffect(() => {
    const draft: any = {
      id: "wizard_draft",
      name: "Nueva Estrategia (Wizard)",
      bias: bias || "long",
      apply_day: applyDay,
      postgap_preconditions: postgapPreconditions,
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      risk_management: riskManagement,
      created_at: createdAtRef.current,
      market_sessions: wizardMarketSessions,
      custom_start_time: wizardMarketSessions.includes("custom") ? wizardCustomStartTime : undefined,
      custom_end_time: wizardMarketSessions.includes("custom") ? wizardCustomEndTime : undefined,
      dataset_id: customUniverse ? undefined : selectedDataset,
      universe_filters: customUniverse ? universeFilters : undefined,
    };
    
    // Sync lastLoadedStrategyRef to prevent initialStrategy reload loops
    lastLoadedStrategyRef.current = JSON.stringify({
      bias: bias,
      apply_day: applyDay,
      postgap_preconditions: postgapPreconditions,
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      risk_management: riskManagement,
      market_sessions: wizardMarketSessions,
      custom_start_time: wizardCustomStartTime,
      custom_end_time: wizardCustomEndTime,
      dataset_id: customUniverse ? undefined : selectedDataset,
      universe_filters: customUniverse ? universeFilters : undefined,
    });

    onDraftChange?.(draft);
  }, [bias, applyDay, postgapPreconditions, entryLogic, exitLogic, riskManagement, wizardMarketSessions, wizardCustomStartTime, wizardCustomEndTime, selectedDataset, customUniverse, universeFilters, onDraftChange]);

  // Actions handlers
  const handleBiasSelect = (b: "long" | "short") => {
    setBias(b);
    setCompletedSteps((prev) => new Set(prev).add(0));
  };

  const handleApplyDaySelect = (day: 'gap_day' | 'gap_1_day' | 'gap_2_day') => {
    setApplyDay(day);
    setCompletedSteps((prev) => new Set(prev).add(1));
  };

  const addPrecondition = () => {
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
    setCompletedSteps((prev) => new Set(prev).add(1));
  };

  const handleRunBacktest = () => {
    if (!bias) {
      alert("Por favor, selecciona una dirección para la estrategia.");
      return;
    }

    const isPartialTPMode = riskManagement.use_take_profit === true && riskManagement.take_profit_mode === "Partial";
    const totalPartialCapital = (riskManagement.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0);
    const isRiskInvalid = isPartialTPMode && Math.abs(totalPartialCapital - 100) > 0.01;

    if (isRiskInvalid) {
      alert("La suma del capital de los parciales de Take Profit debe ser exactamente 100%.");
      return;
    }

    const logicErrors = validateStrategyLogic(entryLogic, exitLogic);
    if (logicErrors.length > 0) {
      alert("Hay condiciones incompletas:\n" + logicErrors.join("\n"));
      return;
    }

    if (entryLogic.entry_time_windows && entryLogic.entry_time_windows.length > 0) {
      const hasInvalidWindow = entryLogic.entry_time_windows.some(window => {
        return getSessionOverlapWarning(window.from_time, window.to_time) !== null;
      });
      if (hasInvalidWindow) {
        alert("Las ventanas horarias de entrada están fuera del rango de la sesión de mercado fijada.");
        return;
      }
    }

    setCompletedSteps((prev) => new Set(prev).add(STEPS.findIndex(s => s.key === "risk")));

    const draft: WizardDraft & { dataset_id?: string; universe_filters?: any; is_wizard?: boolean } = {
      id: `wizard_draft_${Date.now()}`,
      name: "Nueva Estrategia (Wizard)",
      is_wizard: true,
      bias: bias || "long",
      apply_day: applyDay,
      postgap_preconditions: postgapPreconditions,
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      risk_management: riskManagement,
      created_at: new Date().toISOString(),
      market_sessions: wizardMarketSessions,
      custom_start_time: wizardMarketSessions.includes("custom") ? wizardCustomStartTime : undefined,
      custom_end_time: wizardMarketSessions.includes("custom") ? wizardCustomEndTime : undefined,
      dataset_id: customUniverse ? undefined : selectedDataset,
      universe_filters: customUniverse ? universeFilters : undefined,
    };

    onTest(draft);
  };

  /* ── Steps rendering ── */
  const renderStep = () => {
    switch (STEPS[currentStep]?.key) {
      case "universo":
        return renderUniversoStep();
      case "bias":
        return renderBiasStep();
      case "apply_day":
        return renderApplyDayStep();
      case "market_sessions":
        return renderMarketSessionsStep();
      case "entry":
        return renderLogicStep('entry');
      case "exit":
        return renderLogicStep('exit');
      case "risk":
        return renderRiskStep();
      case "summary":
        return renderSummaryStep();
      default:
        return null;
    }
  };

  // Step 0: Universo Step
  const renderUniversoStep = () => {
    const getDayWidth = (val: string) => {
      return val === 'gap_day' ? 110 : 105;
    };

    const getParamWidth = (val: string) => {
      const widths: Record<string, number> = {
        gap_pct: 95,
        pm_volume: 135,
        rth_volume: 140,
        rth_close: 140,
        pm_open: 140,
        pmh_gap_pct: 145,
        rth_range_pct: 130,
      };
      return widths[val] || 130;
    };
    
    const getOpWidth = (val: string) => {
      return val === 'between' ? 70 : 45;
    };

    const FILTRO_DESCRIPTIONS: Record<string, string> = {
      gap_pct: "Porcentaje de diferencia entre el precio de apertura y el cierre del día anterior.",
      pm_volume: "Volumen total negociado durante la sesión de premercado (en millones).",
      rth_volume: "Volumen total negociado durante el horario regular de trading (en millones).",
      rth_close: "Precio de cierre de la vela (o precio actual).",
      pm_open: "Precio al que se realiza la primera transacción de premercado.",
      pmh_gap_pct: "Porcentaje de diferencia entre el máximo de premercado y el cierre del día anterior.",
      rth_range_pct: "Rango de precio (Máximo - Mínimo) expresado como porcentaje del precio durante la sesión RTH.",
    };



    const cardStyle = (active: boolean): React.CSSProperties => ({
      flex: 1,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 6,
      padding: "12px 14px",
      borderRadius: 7,
      border: active ? "1.5px solid var(--color-ec-copper)" : "1px solid var(--color-ec-border)",
      backgroundColor: active ? "rgba(216, 122, 61, 0.07)" : "var(--color-ec-bg-surface)",
      cursor: "pointer",
      textAlign: "center",
      transition: "all 200ms ease",
    });

    const currentDs = datasets.find(d => d.id === selectedDataset);

    // Helpers to format filters in Universo step
    const formatUnivRule = (r: any) => {
      const friendlyName = r.metric.replace(/_/g, " ").toLowerCase();
      const friendlyOp = r.operator === "GREATER_THAN_OR_EQUAL" ? ">=" : r.operator === "LESS_THAN_OR_EQUAL" ? "<=" : r.operator === "GREATER_THAN" ? ">" : "<";
      let friendlyVal = r.value;
      const numVal = parseFloat(r.value);
      if (!isNaN(numVal)) {
        if (r.metric.toLowerCase().includes('volume')) {
          friendlyVal = `${(numVal / 1000000).toFixed(1).replace(/\.0$/, '')}M`;
        }
      }
      return `${friendlyName} ${friendlyOp} ${friendlyVal}`;
    };

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            Configura el Universo del Dataset
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: 0,
            lineHeight: 1.5,
          }}>
            Carga un dataset previamente guardado o define filtros personalizados de mercado para tu estrategia
          </p>
        </div>

        {/* Choice Buttons/Areas */}
        <div style={{ 
          display: "flex", 
          alignItems: "center", 
          justifyContent: "center", 
          gap: 0, 
          borderBottom: "1px solid var(--color-ec-border)", 
          marginBottom: 16,
          paddingBottom: 12
        }}>
          <button
            type="button"
            onClick={() => setCustomUniverse(false)}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              padding: "8px 12px",
              border: "none",
              background: !customUniverse ? "rgba(216, 122, 61, 0.04)" : "transparent",
              borderRadius: 6,
              color: !customUniverse ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)",
              cursor: "pointer",
              transition: "all 150ms ease",
            }}
          >
            <Database style={{ 
              width: 15, 
              height: 15, 
              strokeWidth: 1.5, 
              color: !customUniverse ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)" 
            }} />
            <span style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 10.5,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}>
              Dataset Guardado
            </span>
          </button>
          
          <div style={{ width: 1, height: 18, backgroundColor: "var(--color-ec-border)", margin: "0 12px" }} />
          
          <button
            type="button"
            onClick={() => setCustomUniverse(true)}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              padding: "8px 12px",
              border: "none",
              background: customUniverse ? "rgba(216, 122, 61, 0.04)" : "transparent",
              borderRadius: 6,
              color: customUniverse ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)",
              cursor: "pointer",
              transition: "all 150ms ease",
            }}
          >
            <SlidersHorizontal style={{ 
              width: 15, 
              height: 15, 
              strokeWidth: 1.5, 
              color: customUniverse ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)" 
            }} />
            <span style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 10.5,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}>
              Personalizar
            </span>
          </button>
        </div>

        {/* Conditionally render content */}
        {!customUniverse ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", color: "var(--color-ec-text-muted)" }}>
              Seleccionar Dataset
            </label>
            {loadingDatasets ? (
              <div style={{ height: 36, backgroundColor: "var(--color-ec-bg-elevated)", borderRadius: 5, animation: "pulse 1.5s infinite" }} />
            ) : (
              <select
                value={selectedDataset}
                onChange={(e) => setSelectedDataset(e.target.value)}
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  border: '0.5px solid var(--color-ec-border)',
                  borderRadius: 5,
                  padding: '8px 10px',
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
                    {d.name} {d.pair_count > 0 ? `(${d.pair_count} pares)` : " (Pendiente)"}
                  </option>
                ))}
              </select>
            )}

            {currentDs && (
              <div style={{
                marginTop: 4,
                backgroundColor: 'rgba(255, 255, 255, 0.02)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6
              }}>
                <div style={{ display: 'flex', gap: 16, fontSize: 10.5, fontFamily: 'var(--color-ec-sans)' }}>
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>PARES: </span>
                    <span style={{ color: 'var(--color-ec-copper)', fontWeight: 700 }}>
                      {currentDs.pair_count > 0 ? `${currentDs.pair_count} pares` : "Pendiente"}
                    </span>
                  </div>
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>RANGO: </span>
                    <span style={{ color: 'var(--color-ec-text-primary)' }}>
                      {currentDs.min_date ? formatDate(currentDs.min_date) : '?'} - {currentDs.max_date ? formatDate(currentDs.max_date) : '?'}
                    </span>
                  </div>
                </div>

                {/* Render filters inside the dataset */}
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
                            padding: '4px 10px', 
                            borderRadius: 6, 
                            backgroundColor: 'rgba(216, 122, 61, 0.12)', 
                            color: 'var(--color-ec-text-high)', 
                            border: '0.5px solid rgba(216, 122, 61, 0.35)' 
                          }}>
                            {lbl}
                          </span>
                        ) : null;
                      })}
                    {(currentDs.filters.rules || []).map((r: any, idx: number) => (
                      <span key={idx} style={{ 
                        fontSize: 10, 
                        fontWeight: 600,
                        padding: '4px 10px', 
                        borderRadius: 6, 
                        backgroundColor: 'rgba(216, 122, 61, 0.12)', 
                        color: 'var(--color-ec-text-high)', 
                        border: '0.5px solid rgba(216, 122, 61, 0.35)' 
                      }}>
                        {formatUnivRule(r)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          // Custom universe form
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                <label style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Fecha Desde</label>
                <input
                  type="date"
                  value={universeFilters.date_from || ''}
                  min={dbDateRange.min_date}
                  max={dbDateRange.max_date}
                  onChange={(e) => setUniverseFilters((prev: any) => ({ ...prev, date_from: e.target.value }))}
                  style={{
                    backgroundColor: "var(--color-ec-bg-elevated)",
                    border: "0.5px solid var(--color-ec-border)",
                    borderRadius: 5,
                    padding: "6px 8px",
                    color: "var(--color-ec-text-primary)",
                    fontSize: 11,
                    outline: "none",
                  }}
                />
              </div>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                <label style={{ fontSize: 8.5, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Fecha Hasta</label>
                <input
                  type="date"
                  value={universeFilters.date_to || ''}
                  min={universeFilters.date_from && universeFilters.date_from > dbDateRange.min_date ? universeFilters.date_from : dbDateRange.min_date}
                  max={dbDateRange.max_date}
                  onChange={(e) => setUniverseFilters((prev: any) => ({ ...prev, date_to: e.target.value }))}
                  style={{
                    backgroundColor: "var(--color-ec-bg-elevated)",
                    border: "0.5px solid var(--color-ec-border)",
                    borderRadius: 5,
                    padding: "6px 8px",
                    color: "var(--color-ec-text-primary)",
                    fontSize: 11,
                    outline: "none",
                  }}
                />
              </div>
            </div>

            {/* Rule builder form */}
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              padding: 10,
              backgroundColor: 'rgba(255, 255, 255, 0.01)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 6,
            }}>
              <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", color: "var(--color-ec-copper)", borderBottom: "0.5px solid rgba(255, 255, 255, 0.05)", paddingBottom: 2 }}>
                Añadir filtro de mercado
              </div>

              {/* Row 1: Día */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Día</label>
                <select
                  value={tempUnivDay}
                  onChange={(e) => setTempUnivDay(e.target.value as any)}
                  style={{
                    background: 'var(--color-ec-bg-surface)',
                    border: '0.5px solid var(--color-ec-border)',
                    color: 'var(--color-ec-text-primary)',
                    fontSize: 10,
                    padding: '4px 6px',
                    borderRadius: 4,
                    outline: 'none',
                    cursor: 'pointer',
                    width: getDayWidth(tempUnivDay),
                  }}
                >
                  <option value="gap_day">Día del Gap</option>
                  <option value="gap_plus_1_day">Día Gap +1</option>
                  <option value="gap_plus_2_day">Día Gap +2</option>
                </select>
              </div>

              {/* Row 2: Filtro, Operador, Valor (Mín / Máx), + Añadir */}
              <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end', width: '100%' }}>
                {/* Custom dropdown for Filtro */}
                <div 
                  ref={univFiltroDropdownRef} 
                  style={{ 
                    position: 'relative', 
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 3,
                    width: getParamWidth(tempUnivParam),
                    flexShrink: 0,
                  }}
                >
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Filtro</label>
                  
                  {/* Trigger */}
                  <div
                    onClick={() => setIsUnivFiltroOpen(!isUnivFiltroOpen)}
                    style={{
                      backgroundColor: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 4,
                      padding: '4px 6px',
                      fontSize: 10,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      fontFamily: 'var(--color-ec-sans)',
                      width: '100%',
                      cursor: 'pointer',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      userSelect: 'none',
                      boxSizing: 'border-box',
                      height: 23,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, overflow: 'hidden', flex: 1 }}>
                      <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                        {{
                          gap_pct: "Gap (%)",
                          pm_volume: "Volumen PM (M)",
                          rth_volume: "Volumen RTH (M)",
                          rth_close: "Apertura RTH ($)",
                          pm_open: "Apertura PM ($)",
                          pmh_gap_pct: "PM High Gap (%)",
                          rth_range_pct: "Rango RTH (%)",
                        }[tempUnivParam] || tempUnivParam}
                      </span>
                      <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center' }}>
                        <CustomTooltip 
                          title={{
                            gap_pct: "Gap (%)",
                            pm_volume: "Volumen Premarket (M)",
                            rth_volume: "Volumen RTH (M)",
                            rth_close: "Precio Apertura RTH ($)",
                            pm_open: "Precio Apertura PM ($)",
                            pmh_gap_pct: "PM High Gap (%)",
                            rth_range_pct: "Rango Vela RTH (%)",
                          }[tempUnivParam] || tempUnivParam} 
                          text={FILTRO_DESCRIPTIONS[tempUnivParam] || ""} 
                        />
                      </span>
                    </div>
                    <span style={{ fontSize: 7, color: 'var(--color-ec-text-muted)', marginLeft: 4 }}>
                      {isUnivFiltroOpen ? '▲' : '▼'}
                    </span>
                  </div>

                  {/* List */}
                  {isUnivFiltroOpen && (
                    <div style={{
                      position: 'absolute',
                      top: '100%',
                      left: 0,
                      width: 215,
                      maxHeight: 180,
                      overflowY: 'auto',
                      backgroundColor: 'var(--color-ec-bg-elevated)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                      zIndex: 99999,
                      fontFamily: 'var(--color-ec-sans)',
                      marginTop: 4,
                    }}>
                      {[
                        { value: "gap_pct", label: "Gap (%)" },
                        { value: "pm_volume", label: "Volumen Premarket (M)" },
                        { value: "rth_volume", label: "Volumen RTH (M)" },
                        { value: "rth_close", label: "Precio Apertura RTH ($)" },
                        { value: "pm_open", label: "Precio Apertura PM ($)" },
                        { value: "pmh_gap_pct", label: "PM High Gap (%)" },
                        { value: "rth_range_pct", label: "Rango Vela RTH (%)" },
                      ].map((opt) => {
                        const isSelected = tempUnivParam === opt.value;
                        return (
                          <div 
                            key={opt.value}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'flex-start',
                              gap: 6,
                              backgroundColor: isSelected ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                              borderLeft: isSelected ? '3px solid var(--color-ec-copper)' : '3px solid transparent',
                              padding: '5px 8px',
                              cursor: 'pointer',
                            }}
                            onClick={() => {
                              setTempUnivParam(opt.value);
                              setIsUnivFiltroOpen(false);
                              if (opt.value === 'pm_volume' || opt.value === 'rth_volume') {
                                setTempUnivVal1('1.0');
                              } else if (opt.value === 'gap_pct' || opt.value === 'rth_range_pct') {
                                setTempUnivVal1('2.0');
                              } else {
                                setTempUnivVal1('5.0');
                              }
                            }}
                            onMouseEnter={(e) => {
                              if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-surface)';
                            }}
                            onMouseLeave={(e) => {
                              if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                            }}
                          >
                            <span style={{
                              color: isSelected ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-primary)',
                              fontWeight: isSelected ? 600 : 400,
                              fontSize: 10,
                              textOverflow: 'ellipsis',
                              overflow: 'hidden',
                              whiteSpace: 'nowrap',
                            }}>
                              {opt.label}
                            </span>
                            <CustomTooltip title={opt.label} text={FILTRO_DESCRIPTIONS[opt.value] || ""} />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Operator */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: getOpWidth(tempUnivOp), flexShrink: 0 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Op.</label>
                  <select
                    value={tempUnivOp}
                    onChange={(e) => setTempUnivOp(e.target.value)}
                    style={{
                      background: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-primary)',
                      fontSize: 10,
                      padding: '4px 6px',
                      borderRadius: 4,
                      outline: 'none',
                      cursor: 'pointer',
                      width: '100%',
                      height: 23,
                    }}
                  >
                    <option value=">=">&gt;=</option>
                    <option value="<=">&lt;=</option>
                    <option value=">">&gt;</option>
                    <option value="<">&lt;</option>
                    <option value="between">Entre</option>
                  </select>
                </div>

                {/* Value 1 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 65, flexShrink: 0 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>
                    {tempUnivOp === 'between' ? 'Mín' : 'Valor'}
                  </label>
                  <input
                    type="text"
                    value={tempUnivVal1}
                    onChange={(e) => setTempUnivVal1(e.target.value)}
                    style={{
                      background: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-primary)',
                      fontSize: 10,
                      padding: '4px 6px',
                      borderRadius: 4,
                      outline: 'none',
                      width: '100%',
                      height: 23,
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                {/* Value 2 (between) */}
                {tempUnivOp === 'between' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 65, flexShrink: 0 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Máx</label>
                    <input
                      type="text"
                      value={tempUnivVal2}
                      onChange={(e) => setTempUnivVal2(e.target.value)}
                      style={{
                        background: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        color: 'var(--color-ec-text-primary)',
                        fontSize: 10,
                        padding: '4px 6px',
                        borderRadius: 4,
                        outline: 'none',
                        width: '100%',
                        height: 23,
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>
                )}

                {/* + Añadir button placed right next to Value */}
                <button
                  type="button"
                  onClick={() => {
                    const val1 = parseFloat(tempUnivVal1);
                    const val2 = tempUnivOp === 'between' ? parseFloat(tempUnivVal2) : null;
                    if (isNaN(val1) || (tempUnivOp === 'between' && isNaN(val2!))) {
                      alert("Por favor introduce valores numéricos válidos.");
                      return;
                    }

                    // Add condition to universeFilters.rules
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

                    setUniverseFilters((prev: any) => ({
                      ...prev,
                      rules: newRules
                    }));
                  }}
                  style={{
                    backgroundColor: 'var(--color-ec-copper)',
                    color: 'var(--color-ec-copper-text)',
                    border: 'none',
                    borderRadius: 4,
                    padding: '0 12px',
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: 'pointer',
                    height: 23,
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  + Añadir
                </button>
              </div>
            </div>

            {/* List of custom universe filters as tags */}
            {universeFilters.rules && universeFilters.rules.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                {universeFilters.rules.map((r: any, idx: number) => (
                  <span
                    key={idx}
                    onClick={() => {
                      setUniverseFilters((prev: any) => ({
                        ...prev,
                        rules: prev.rules.filter((_: any, i: number) => i !== idx)
                      }));
                    }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      padding: '4px 10px',
                      backgroundColor: 'rgba(216, 122, 61, 0.12)',
                      border: '0.5px solid rgba(216, 122, 61, 0.35)',
                      borderRadius: 6,
                      fontFamily: 'var(--color-ec-sans)',
                      fontSize: 10,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-high)',
                      cursor: 'pointer',
                    }}
                  >
                    <span>{formatUnivRule(r)}</span>
                    <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', marginLeft: 4 }}>×</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Step 1: Direction Bias
  const renderBiasStep = () => {
    const biasCard = (
      id: "long" | "short",
      isSelected: boolean,
      isHovered: boolean
    ): React.CSSProperties => {
      const accentColor = id === "long" ? "var(--color-ec-profit)" : "var(--color-ec-loss)";
      const rawRgb = id === "long" ? "34, 197, 94" : "239, 68, 68";
      return {
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 7,
        border: isSelected
          ? `1px solid ${accentColor}`
          : isHovered
            ? `1px solid rgba(${rawRgb}, 0.35)`
            : "1px solid var(--color-ec-border)",
        backgroundColor: isSelected
          ? `rgba(${rawRgb}, 0.07)`
          : isHovered
            ? `rgba(${rawRgb}, 0.025)`
            : "var(--color-ec-bg-surface)",
        cursor: "pointer",
        transition: "all 200ms cubic-bezier(0.22, 1, 0.36, 1)",
        transform: isSelected
          ? "scale(1.01)"
          : isHovered
            ? "translateY(-1px)"
            : "translateY(0)",
        boxShadow: isSelected
          ? `0 2px 12px rgba(${rawRgb}, 0.15)`
          : isHovered
            ? "0 3px 12px rgba(0, 0, 0, 0.15)"
            : "0 1px 3px rgba(0, 0, 0, 0.05)",
        outline: "none",
        overflow: "hidden",
        flex: 1,
        minWidth: 0,
      };
    };

    return (
      <div>
        <h3 style={{
          fontFamily: "var(--color-ec-serif)",
          fontSize: 14,
          fontWeight: 600,
          color: "var(--color-ec-text-high)",
          margin: "0 0 4px 0",
          letterSpacing: "-0.2px",
        }}>
          ¿Qué dirección tomará tu estrategia?
        </h3>
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-muted)",
          margin: "0 0 14px 0",
          lineHeight: 1.5,
        }}>
          Selecciona si operarás a favor de la tendencia alcista o bajista
        </p>

        <div style={{ display: "flex", gap: 8 }}>
          {/* Long */}
          <button
            onClick={() => handleBiasSelect("long")}
            onMouseEnter={() => setHoveredBias("long")}
            onMouseLeave={() => setHoveredBias(null)}
            style={biasCard("long", bias === "long", hoveredBias === "long")}
          >
            <div style={{
              position: "absolute", top: 0, left: 0, right: 0,
              height: bias === "long" ? 2 : 0,
              background: "var(--color-ec-profit)",
              transition: "height 250ms ease",
              borderRadius: "7px 7px 0 0",
            }} />
            <div style={{
              width: 30, height: 30, borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              backgroundColor: bias === "long" ? "rgba(34, 197, 94, 0.12)" : "var(--color-ec-bg-elevated)",
              border: bias === "long" ? "1px solid rgba(34, 197, 94, 0.25)" : "1px solid var(--color-ec-border)",
              transition: "all 200ms ease", flexShrink: 0,
            }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke={bias === "long" || hoveredBias === "long" ? "var(--color-ec-profit)" : "var(--color-ec-text-muted)"}
                strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                style={{ transition: "stroke 200ms ease" }}>
                <path d="M12 19V5" /><path d="M5 12l7-7 7 7" />
              </svg>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span style={{
                fontFamily: "var(--color-ec-sans)", fontSize: 12, fontWeight: 700,
                color: bias === "long" ? "var(--color-ec-profit)" : "var(--color-ec-text-high)",
                transition: "color 200ms ease",
              }}>Long</span>
              <span style={{
                fontFamily: "var(--color-ec-sans)", fontSize: 9,
                color: "var(--color-ec-text-muted)", lineHeight: 1.3,
              }}>Posiciones alcistas</span>
            </div>
            {bias === "long" && (
              <div style={{
                marginLeft: "auto",
                width: 16, height: 16, borderRadius: "50%",
                backgroundColor: "var(--color-ec-profit)",
                display: "flex", alignItems: "center", justifyContent: "center",
                animation: "wizCheckPop 250ms cubic-bezier(0.34, 1.56, 0.64, 1)",
                flexShrink: 0,
              }}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none"
                  stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            )}
          </button>

          {/* Short */}
          <button
            onClick={() => handleBiasSelect("short")}
            onMouseEnter={() => setHoveredBias("short")}
            onMouseLeave={() => setHoveredBias(null)}
            style={biasCard("short", bias === "short", hoveredBias === "short")}
          >
            <div style={{
              position: "absolute", top: 0, left: 0, right: 0,
              height: bias === "short" ? 2 : 0,
              background: "var(--color-ec-loss)",
              transition: "height 250ms ease",
              borderRadius: "7px 7px 0 0",
            }} />
            <div style={{
              width: 30, height: 30, borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              backgroundColor: bias === "short" ? "rgba(239, 68, 68, 0.12)" : "var(--color-ec-bg-elevated)",
              border: bias === "short" ? "1px solid rgba(239, 68, 68, 0.25)" : "1px solid var(--color-ec-border)",
              transition: "all 200ms ease", flexShrink: 0,
            }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke={bias === "short" || hoveredBias === "short" ? "var(--color-ec-loss)" : "var(--color-ec-text-muted)"}
                strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                style={{ transition: "stroke 200ms ease" }}>
                <path d="M12 5v14" /><path d="M19 12l-7 7-7-7" />
              </svg>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span style={{
                fontFamily: "var(--color-ec-sans)", fontSize: 12, fontWeight: 700,
                color: bias === "short" ? "var(--color-ec-loss)" : "var(--color-ec-text-high)",
                transition: "color 200ms ease",
              }}>Short</span>
              <span style={{
                fontFamily: "var(--color-ec-sans)", fontSize: 9,
                color: "var(--color-ec-text-muted)", lineHeight: 1.3,
              }}>Posiciones bajistas</span>
            </div>
            {bias === "short" && (
              <div style={{
                marginLeft: "auto",
                width: 16, height: 16, borderRadius: "50%",
                backgroundColor: "var(--color-ec-loss)",
                display: "flex", alignItems: "center", justifyContent: "center",
                animation: "wizCheckPop 250ms cubic-bezier(0.34, 1.56, 0.64, 1)",
                flexShrink: 0,
              }}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none"
                  stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            )}
          </button>
        </div>
      </div>
    );
  };

  // Step 2: Día de aplicación (Apply Day)
  const renderApplyDayStep = () => {
    const dayCard = (id: 'gap_day' | 'gap_1_day' | 'gap_2_day'): React.CSSProperties => {
      const isSelected = applyDay === id;
      return {
        width: "100%",
        maxWidth: 300,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 4,
        padding: "6px 16px",
        borderRadius: 8,
        border: isSelected ? "1.5px solid var(--color-ec-copper)" : "1px solid var(--color-ec-border)",
        backgroundColor: isSelected ? "rgba(216, 122, 61, 0.07)" : "var(--color-ec-bg-surface)",
        cursor: "pointer",
        textAlign: "center",
        transition: "all 200ms cubic-bezier(0.22, 1, 0.36, 1)",
        boxShadow: isSelected ? "0 3px 12px rgba(216, 122, 61, 0.15)" : "0 1px 3px rgba(0, 0, 0, 0.05)",
      };
    };

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            ¿En qué día deseas aplicar la estrategia?
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 0 0",
            lineHeight: 1.5,
          }}>
            Decide si ejecutar tu lógica de entrada el mismo día del gap de apertura o en las sesiones posteriores
          </p>
        </div>

        {/* Days selector column */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, width: "100%" }}>
          {/* Gap Day */}
          <button onClick={() => handleApplyDaySelect("gap_day")} style={dayCard("gap_day")}>
            <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: applyDay === "gap_day" ? "var(--color-ec-copper)" : "var(--color-ec-text-high)" }}>Gap Day</span>
            <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 9, color: "var(--color-ec-text-muted)", lineHeight: 1.2 }}>Mismo día del Gap</span>
          </button>
          {/* Gap +1 Day */}
          <button onClick={() => handleApplyDaySelect("gap_1_day")} style={dayCard("gap_1_day")}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: applyDay === "gap_1_day" ? "var(--color-ec-copper)" : "var(--color-ec-text-high)" }}>Gap +1 Day</span>
              <span style={{ fontSize: 7, fontWeight: 700, padding: "1px 4px", borderRadius: 3, backgroundColor: "rgba(216, 122, 61, 0.15)", color: "var(--color-ec-copper-bright)" }}>BETA</span>
            </div>
            <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 9, color: "var(--color-ec-text-muted)", lineHeight: 1.2 }}>Día siguiente al Gap</span>
          </button>
          {/* Gap +2 Day */}
          <button onClick={() => handleApplyDaySelect("gap_2_day")} style={dayCard("gap_2_day")}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: applyDay === "gap_2_day" ? "var(--color-ec-copper)" : "var(--color-ec-text-high)" }}>Gap +2 Day</span>
              <span style={{ fontSize: 7, fontWeight: 700, padding: "1px 4px", borderRadius: 3, backgroundColor: "rgba(216, 122, 61, 0.15)", color: "var(--color-ec-copper-bright)" }}>BETA</span>
            </div>
            <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 9, color: "var(--color-ec-text-muted)", lineHeight: 1.2 }}>Segundo día tras el Gap</span>
          </button>

          {/* Gap +X Days Placeholder */}
          <div style={{
            width: "100%",
            maxWidth: 300,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            padding: "6px 12px",
            borderRadius: 8,
            border: "0.8px dashed rgba(255, 255, 255, 0.25)",
            backgroundColor: "rgba(255, 255, 255, 0.02)",
            color: "var(--color-ec-text-muted)",
            opacity: 0.85,
            userSelect: "none",
            boxSizing: "border-box",
          }}>
            <span style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 10,
              fontWeight: 500,
              letterSpacing: "0.2px",
            }}>
              Gap +X Days <span style={{ fontSize: 8.5, opacity: 0.7, fontStyle: "italic" }}>(Próximamente)</span>
            </span>
          </div>
        </div>

        {/* Preconditions conditional display */}
        {applyDay !== "gap_day" && (
          <div style={{
            marginTop: 8,
            animation: "wizCheckPop 250ms ease-out",
          }}>
            <h4 style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 11,
              fontWeight: 700,
              color: "var(--color-ec-text-high)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              margin: "0 0 6px 0",
            }}>
              Condiciones previas (Post-Gap)
            </h4>
            <p style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 9,
              color: "var(--color-ec-text-muted)",
              margin: "0 0 12px 0",
              lineHeight: 1.4,
            }}>
              Agrega reglas basadas en el comportamiento de las sesiones anteriores (ej: si el cierre fue superior al RTH high).
            </p>

            {/* Form */}
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              padding: 12,
              backgroundColor: 'rgba(28, 30, 33, 0.2)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 6,
            }}>
              {applyDay === 'gap_2_day' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, borderBottom: '0.5px solid var(--color-ec-border)', paddingBottom: 8, marginBottom: 2 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Evaluar en</label>
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
                      fontSize: 10,
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

              <div style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'flex-end',
                flexWrap: 'nowrap',
                gap: 6,
                width: '100%',
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: '1 1 80px', minWidth: 0 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>Variable</label>
                  <select
                    value={tempSource}
                    onChange={(e) => {
                      const src = e.target.value as 'cierre' | 'volume' | 'candle_range_pct' | 'candle_range_ratio_gap_1_vs_gap';
                      setTempSource(src);
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
                      fontSize: 10,
                      padding: '4px 4px',
                      borderRadius: 4,
                      outline: 'none',
                      fontFamily: 'var(--color-ec-sans)',
                      cursor: 'pointer',
                      width: '100%',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    <option value="cierre">Cierre</option>
                    <option value="volume">Volumen</option>
                    <option value="candle_range_pct">Rango %</option>
                    {applyDay === 'gap_2_day' && tempDay === 'gap_1_day' && (
                      <option value="candle_range_ratio_gap_1_vs_gap">Rango G+1/G %</option>
                    )}
                  </select>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 38, flexShrink: 0 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>Op</label>
                  <select
                    value={tempOperator}
                    onChange={(e) => setTempOperator(e.target.value as any)}
                    style={{
                      background: 'var(--color-ec-bg-surface)',
                      border: '0.5px solid var(--color-ec-border)',
                      color: 'var(--color-ec-text-primary)',
                      fontSize: 10,
                      padding: '4px 4px',
                      borderRadius: 4,
                      outline: 'none',
                      fontFamily: 'var(--color-ec-sans)',
                      cursor: 'pointer',
                      width: '100%',
                    }}
                  >
                    <option value=">">&gt;</option>
                    <option value="<">&lt;</option>
                  </select>
                </div>

                {tempSource === 'cierre' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: '1 1 80px', minWidth: 0 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>Ref</label>
                    <select
                      value={tempTarget}
                      onChange={(e) => setTempTarget(e.target.value as any)}
                      style={{
                        background: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        color: 'var(--color-ec-text-primary)',
                        fontSize: 10,
                        padding: '4px 4px',
                        borderRadius: 4,
                        outline: 'none',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                        width: '100%',
                        textOverflow: 'ellipsis',
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

                {tempSource === 'cierre' && tempTarget === 'sma' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 42, flexShrink: 0 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>Per</label>
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
                        fontSize: 10,
                        padding: '4px 4px',
                        borderRadius: 4,
                        outline: 'none',
                        fontFamily: 'var(--color-ec-sans)',
                        width: '100%',
                        textAlign: 'center',
                      }}
                    />
                  </div>
                )}

                {tempSource !== 'cierre' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: '1 1 70px', minWidth: 0 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>Valor</label>
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
                            fontSize: 10,
                            padding: '4px 14px 4px 4px',
                            borderRadius: 4,
                            outline: 'none',
                            fontFamily: 'var(--color-ec-sans)',
                            width: '100%',
                          }}
                        />
                        <span style={{
                          position: 'absolute',
                          right: 4,
                          fontSize: 9,
                          fontWeight: 600,
                          color: 'rgba(255, 255, 255, 0.3)',
                          pointerEvents: 'none',
                        }}>M</span>
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
                          fontSize: 10,
                          padding: '4px 4px',
                          borderRadius: 4,
                          outline: 'none',
                          fontFamily: 'var(--color-ec-sans)',
                          width: '100%',
                        }}
                      />
                    )}
                  </div>
                )}

                <button
                  type="button"
                  onClick={addPrecondition}
                  style={{
                    backgroundColor: 'var(--color-ec-copper)',
                    color: 'var(--color-ec-copper-text)',
                    border: 'none',
                    padding: '0 8px',
                    borderRadius: 4,
                    fontSize: 9,
                    fontWeight: 700,
                    cursor: 'pointer',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px',
                    height: 23,
                    flexShrink: 0,
                    alignSelf: 'flex-end',
                    marginBottom: 1,
                  }}
                >
                  + Añadir
                </button>
              </div>
            </div>

            {/* List */}
            {postgapPreconditions.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                {postgapPreconditions.map((cond) => {
                  const dayLabel = cond.day === 'gap_day' ? 'Día del Gap' : 'Día Gap +1';
                  let metricLabel = 'Cierre';
                  let valLabel = '';

                  if (cond.metric === 'volume') {
                    metricLabel = 'Volumen';
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
                    metricLabel = 'Rango Vela';
                    valLabel = `${cond.operator} ${cond.value}%`;
                  } else if (cond.metric === 'candle_range_ratio_gap_1_vs_gap') {
                    metricLabel = 'Rango Gap+1 vs Gap';
                    valLabel = `${cond.operator} ${cond.value}%`;
                  }

                  return (
                    <div
                      key={cond.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        backgroundColor: 'rgba(216, 122, 61, 0.12)',
                        border: '0.5px solid rgba(216, 122, 61, 0.35)',
                        borderRadius: 6,
                        padding: '4px 10px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 600,
                        color: 'var(--color-ec-text-high)',
                      }}
                    >
                      <span>{dayLabel} • {metricLabel}: {valLabel}</span>
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
                          fontSize: 10,
                          lineHeight: 1,
                          padding: 0,
                          marginLeft: 4,
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
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
      </div>
    );
  };

  // Step 3: Sesión de aplicación (Market Sessions)
  const renderMarketSessionsStep = () => {
    const sessionCard = (isSelected: boolean): React.CSSProperties => {
      return {
        width: "100%",
        maxWidth: 320,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 14px",
        borderRadius: 8,
        border: isSelected ? "1.5px solid var(--color-ec-copper)" : "1px solid var(--color-ec-border)",
        backgroundColor: isSelected ? "rgba(216, 122, 61, 0.07)" : "var(--color-ec-bg-surface)",
        cursor: "pointer",
        textAlign: "left",
        transition: "all 200ms cubic-bezier(0.22, 1, 0.36, 1)",
        boxShadow: isSelected ? "0 3px 12px rgba(216, 122, 61, 0.15)" : "0 1px 3px rgba(0, 0, 0, 0.05)",
      };
    };

    const toggleSession = (id: string) => {
      let next: string[];
      if (wizardMarketSessions.includes(id)) {
        next = wizardMarketSessions.filter(x => x !== id);
      } else {
        next = [...wizardMarketSessions, id];
      }
      setWizardMarketSessions(next);
      setCompletedSteps((prev) => {
        const nextSet = new Set(prev);
        const idx = STEPS.findIndex(s => s.key === "market_sessions");
        if (next.length > 0) {
          nextSet.add(idx);
        } else {
          nextSet.delete(idx);
        }
        return nextSet;
      });
    };

    const sessions = [
      {
        id: "pre",
        label: "Pre-Market",
        time: "04:00 - 09:30 ET",
        desc: "Operativa antes de la apertura oficial. Útil para reaccionar a catalizadores temprano, pero con spreads anchos."
      },
      {
        id: "rth",
        label: "Regular Hours (RTH)",
        time: "09:30 - 16:00 ET",
        desc: "Horario estándar del mercado de EE. UU. Máxima liquidez y volumen. Ideal para la mayoría de estrategias."
      },
      {
        id: "post",
        label: "After-Market",
        time: "16:00 - 20:00 ET",
        desc: "Operativa después del cierre oficial. Frecuentemente activa durante reportes de ganancias y noticias del cierre."
      },
      {
        id: "custom",
        label: "Horas personalizadas",
        time: "",
        desc: "Define un rango horario específico a tu medida para la ejecución de la lógica."
      }
    ];

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            ¿En qué sesión deseas ejecutar la estrategia?
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 10px 0",
            lineHeight: 1.5,
          }}>
            Selecciona una o varias sesiones de mercado. Tu estrategia solo ejecutará entradas y gestionará posiciones durante el horario seleccionado.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, width: "100%" }}>
          {sessions.map(s => {
            const isSelected = wizardMarketSessions.includes(s.id);
            return (
              <div key={s.id} onClick={() => toggleSession(s.id)} style={sessionCard(isSelected)}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      readOnly
                      style={{
                        accentColor: "var(--color-ec-copper)",
                        cursor: "pointer",
                      }}
                    />
                    <span style={{ fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-high)" }}>{s.label}</span>
                  </div>
                  {s.time && (
                    <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)", fontWeight: 500 }}>{s.time}</span>
                  )}
                </div>
                <p style={{ margin: "4px 0 0 0", fontSize: 9, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>{s.desc}</p>
                {s.id === "custom" && isSelected && (
                  <div 
                    onClick={(e) => e.stopPropagation()} 
                    style={{ 
                      display: "flex", 
                      gap: 12, 
                      marginTop: 8, 
                      paddingTop: 8, 
                      borderTop: "0.5px solid var(--color-ec-border)",
                      width: "100%"
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
                      <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", fontWeight: 700, textTransform: "uppercase" }}>Desde (ET)</span>
                      <input
                        type="time"
                        value={wizardCustomStartTime}
                        onChange={(e) => {
                          setWizardCustomStartTime(e.target.value);
                          setCompletedSteps((prev) => new Set(prev).add(STEPS.findIndex(s => s.key === "market_sessions")));
                        }}
                        style={{
                          backgroundColor: 'var(--color-ec-bg-elevated)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 4,
                          padding: '4px 8px',
                          fontSize: 10,
                          color: 'var(--color-ec-text-primary)',
                          outline: 'none',
                        }}
                      />
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
                      <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", fontWeight: 700, textTransform: "uppercase" }}>Hasta (ET)</span>
                      <input
                        type="time"
                        value={wizardCustomEndTime}
                        onChange={(e) => {
                          setWizardCustomEndTime(e.target.value);
                          setCompletedSteps((prev) => new Set(prev).add(STEPS.findIndex(s => s.key === "market_sessions")));
                        }}
                        style={{
                          backgroundColor: 'var(--color-ec-bg-elevated)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 4,
                          padding: '4px 8px',
                          fontSize: 10,
                          color: 'var(--color-ec-text-primary)',
                          outline: 'none',
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // Step 3 & 4: Lógica de entrada/salida (Entry/Exit Logic)
  const renderLogicStep = (mode: 'entry' | 'exit') => {
    const logic = mode === 'entry' ? entryLogic : exitLogic;
    const setLogic = (newLogic: any) => {
      if (mode === 'entry') {
        setEntryLogic(newLogic);
      } else {
        setExitLogic(newLogic);
      }
    };
    const stepIdx = mode === 'entry' ? STEPS.findIndex(s => s.key === "entry") : STEPS.findIndex(s => s.key === "exit");

    const supportsDistance = (name: IndicatorType): boolean => {
      return getAllowedTargets(name, "price_level_distance").length > 0;
    };

    const getCondStepsList = (): number[] => {
      if (isTriangle(wizardSource)) {
        return [0, 1];
      }
      if (wizardSource === IndicatorType.ELAPSED_TIME_LAST_HIGH || wizardSource === IndicatorType.ELAPSED_TIME) {
        return [0, 1, 4];
      }
      if (wizardSource.toLowerCase() === 'range of time') {
        return [0, 1, 3, 4];
      }
      if (supportsDistance(wizardSource)) {
        return [0, 1, 2, 3, 4];
      }
      return [0, 1, 3, 4];
    };



    const getIndicatorParams = (name: IndicatorType, role: "source" | "target" | "distance_level") => {
      const getVal = (paramName: string, defaultVal: any) => {
        if (role === "source") {
          if (paramName === "period") return wizardSourcePeriod;
          if (paramName === "stdDev") return wizardSourceDev;
          if (paramName === "band_line") return wizardSourceBand;
          if (paramName === "days_lookback") return wizardSourceDays;
          if (paramName === "orb_minutes") return wizardSourceOrb;
          if (paramName === "ap_session") return wizardSourceSession;
          if (paramName === "pivot_window") return wizardSourcePivotWindow;
          if (paramName === "min_pivots") return wizardSourceMinPivots;
          if (paramName === "tri_lookback") return wizardSourceTriLookback;
          if (paramName === "slope_tolerance") return wizardSourceSlopeTolerance;
          if (paramName === "min_r_squared") return wizardSourceMinRSquared;
        } else if (role === "target") {
          if (paramName === "period") return wizardTargetPeriod;
          if (paramName === "stdDev") return wizardTargetDev;
          if (paramName === "band_line") return wizardTargetBand;
          if (paramName === "days_lookback") return wizardTargetDays;
          if (paramName === "orb_minutes") return wizardTargetOrb;
          if (paramName === "ap_session") return wizardTargetSession;
        } else {
          if (paramName === "period") return wizardDistanceLevelPeriod;
          if (paramName === "ap_session") return wizardDistanceLevelSession;
        }
        return defaultVal;
      };

      switch (name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.ATR:
          return { period: getVal("period", 14) };
        case IndicatorType.RVOL:
          return { period: getVal("period", 20) };
        case IndicatorType.BOLLINGER_BANDS:
          return { period: getVal("period", 20), stdDev: getVal("stdDev", 2), band_line: getVal("band_line", "Upper") };
        case IndicatorType.DONCHIAN:
          return { period: getVal("period", 20), band_line: getVal("band_line", "Upper") };
        case IndicatorType.HIGH_X_DAYS:
        case IndicatorType.LOW_X_DAYS:
          return { days_lookback: getVal("days_lookback", 5) };
        case IndicatorType.PREVIOUS_MAX:
        case IndicatorType.PREVIOUS_MIN:
          return { ap_session: getVal("ap_session", "ap.RTH") };
        case IndicatorType.OPENING_RANGE_PLUS:
        case IndicatorType.OPENING_RANGE_MINUS:
        case IndicatorType.OPENING_RANGE_AM_PLUS:
        case IndicatorType.OPENING_RANGE_AM_MINUS:
          return { orb_minutes: getVal("orb_minutes", 30) };
        case IndicatorType.TRIANGLE_ASCENDING:
        case IndicatorType.TRIANGLE_DESCENDING:
        case IndicatorType.TRIANGLE_SYMMETRIC:
          return {
            pivot_window: getVal("pivot_window", 5),
            min_pivots: getVal("min_pivots", 2),
            tri_lookback: getVal("tri_lookback", 35),
            slope_tolerance: getVal("slope_tolerance", 1.5),
            min_r_squared: getVal("min_r_squared", 0.65)
          };
        default:
          return {};
      }
    };
    
    const timeframes = ["1m", "5m", "15m", "30m", "1h", "1d"];
    
    const comparatorOptions = [
      { value: Comparator.GT, label: "Mayor que (>)" },
      { value: Comparator.LT, label: "Menor que (<)" },
      { value: Comparator.GTE, label: "Mayor o igual que (>=)" },
      { value: Comparator.LTE, label: "Menor o igual que (<=)" },
      { value: Comparator.EQ, label: "Igual que (=)" },
      { value: Comparator.CROSSES_ABOVE, label: "Cruza por encima (↗)" },
      { value: Comparator.CROSSES_BELOW, label: "Cruza por debajo (↘)" },
    ];
    
    const distanceComparatorOptions = [
      { value: "DISTANCE_GT", label: "Mayor que la distancia (>)" },
      { value: "DISTANCE_LT", label: "Menor que la distancia (<)" },
    ];

    const handleNext = () => {
      const condStepsList = getCondStepsList();
      const currIdx = condStepsList.indexOf(wizardCondStep);
      if (currIdx !== -1 && currIdx < condStepsList.length - 1) {
        const nextStep = condStepsList[currIdx + 1];
        setWizardCondStep(nextStep);
        if (nextStep === 3 && !supportsDistance(wizardSource)) {
          setWizardMode("comparison");
        }
      }
    };

    const handleBack = () => {
      const condStepsList = getCondStepsList();
      const currIdx = condStepsList.indexOf(wizardCondStep);
      if (currIdx > 0) {
        setWizardCondStep(condStepsList[currIdx - 1]);
      } else {
        setWizardCondStep(-1);
      }
    };

    const handleAddCondition = () => {
      let newCond: any;
      if (isTriangle(wizardSource)) {
        const defaultParams = getDefaultParamsForIndicator(wizardSource);
        newCond = {
          type: "indicator_comparison",
          source: {
            name: wizardSource,
            offset: 0,
            ...defaultParams
          },
          comparator: Comparator.GT,
          target: 0,
          timeframe: wizardTf
        };
      } else if (wizardSource === IndicatorType.ELAPSED_TIME_LAST_HIGH || wizardSource === IndicatorType.ELAPSED_TIME) {
        newCond = {
          type: "indicator_comparison",
          source: {
            name: wizardSource,
            offset: 0
          },
          comparator: Comparator.GTE,
          target: wizardTargetValue,
          timeframe: wizardTf
        };
      } else if (wizardSource.toLowerCase() === 'range of time') {
        newCond = {
          type: "indicator_comparison",
          source: {
            name: wizardSource,
            offset: 0
          },
          comparator: wizardComparator as Comparator,
          target: wizardTargetValue,
          timeframe: wizardTf
        };
      } else if (wizardMode === "comparison") {
        newCond = {
          type: "indicator_comparison",
          source: {
            name: wizardSource,
            ...getIndicatorParams(wizardSource, "source")
          },
          comparator: wizardComparator as Comparator,
          target: wizardTargetType === "fixed" ? wizardTargetValue : {
            name: wizardTargetIndicator,
            offset: wizardTargetOffset,
            ...getIndicatorParams(wizardTargetIndicator, "target")
          },
          timeframe: wizardTf
        };
      } else {
        newCond = {
          type: "price_level_distance",
          source: {
            name: wizardSource,
            ...getIndicatorParams(wizardSource, "source")
          },
          level: {
            name: wizardDistanceLevel,
            offset: wizardDistanceLevelOffset,
            ...getIndicatorParams(wizardDistanceLevel, "distance_level")
          },
          comparator: wizardComparator as "DISTANCE_GT" | "DISTANCE_LT",
          value_pct: wizardDistanceValue,
          position: wizardDistancePosition,
          timeframe: wizardTf
        };
      }

      const currentConds = logic.root_condition.conditions || [];
      setLogic({
        ...logic,
        root_condition: {
          ...logic.root_condition,
          conditions: [...currentConds, newCond]
        }
      });
      setCompletedSteps((prev) => new Set(prev).add(stepIdx));
      
      // Reset condition wizard
      setWizardCondStep(-1);
      setWizardSource(IndicatorType.BAR_CLOSE);
      setWizardMode("comparison");
      setWizardComparator(Comparator.GT);
      setWizardTargetType("fixed");
      setWizardTargetValue(0);
      setWizardTargetValueText("");
      setWizardTargetOffset(0);
      setWizardDistanceLevelOffset(0);
      setWizardSourceSession("ap.RTH");
      setWizardTargetSession("ap.RTH");
      setWizardDistanceLevelSession("ap.RTH");
      setWizardSourcePivotWindow(5);
      setWizardSourceMinPivots(2);
      setWizardSourceTriLookback(35);
      setWizardSourceSlopeTolerance(1.5);
      setWizardSourceMinRSquared(0.65);
      setWizardDistancePosition('any');
    };

    const renderLivePreviewTags = () => {
      const tags = [];
      
      // Step 0: Timeframe
      tags.push({ label: `Tf: ${wizardTf}` });
      
      // Step 1: Source
      if (wizardCondStep >= 1) {
        const label = INDICATOR_LABELS[wizardSource] || wizardSource;
        tags.push({ label: `Var: ${label}` });
      }
      
      // Step 2: Mode (if applicable)
      if (wizardCondStep >= 2 && supportsDistance(wizardSource)) {
        tags.push({ label: wizardMode === "comparison" ? "Comparación" : "Distancia" });
      }
      
      // Step 3: Comparator
      if (wizardCondStep >= 3) {
        const label = COMPARATOR_LABELS[wizardComparator] || wizardComparator;
        tags.push({ label: `Rel: ${label}` });
      }
      
      // Step 4: Target
      if (wizardCondStep >= 4) {
        if (wizardMode === "comparison") {
          if (wizardTargetType === "fixed") {
            tags.push({ label: `Val: ${wizardTargetValue}` });
          } else {
            const label = INDICATOR_LABELS[wizardTargetIndicator] || wizardTargetIndicator;
            const offsetSuffix = wizardTargetOffset > 0 ? `[t-${wizardTargetOffset}]` : '';
            tags.push({ label: `Obj: ${label}${offsetSuffix}` });
          }
        } else {
          const label = INDICATOR_LABELS[wizardDistanceLevel] || wizardDistanceLevel;
          const offsetSuffix = wizardDistanceLevelOffset > 0 ? `[t-${wizardDistanceLevelOffset}]` : '';
          tags.push({ label: `Nivel: ${label}${offsetSuffix}` });
          tags.push({ label: `Dist: ${wizardDistanceValue}%` });
        }
      }
      
      return (
        <div style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 6,
          marginTop: 14,
          padding: "8px 10px",
          backgroundColor: "var(--color-ec-bg-elevated)",
          borderRadius: 6,
          border: "0.5px solid var(--color-ec-border)"
        }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase", marginRight: 4 }}>Progreso Condición:</span>
          {tags.map((t, idx) => (
            <span key={idx} style={{
              fontSize: 9,
              fontWeight: 600,
              padding: "2px 6px",
              borderRadius: 4,
              backgroundColor: "rgba(255, 255, 255, 0.05)",
              color: "var(--color-ec-text-secondary)",
              border: "0.5px solid rgba(255, 255, 255, 0.1)",
            }}>
              {t.label}
            </span>
          ))}
        </div>
      );
    };

    const renderParameterInputs = (name: IndicatorType, role: "source" | "target" | "distance_level") => {
      const getVal = (paramName: string) => {
        if (role === "source") {
          if (paramName === "period") return wizardSourcePeriod;
          if (paramName === "stdDev") return wizardSourceDev;
          if (paramName === "band_line") return wizardSourceBand;
          if (paramName === "days_lookback") return wizardSourceDays;
          if (paramName === "orb_minutes") return wizardSourceOrb;
          if (paramName === "ap_session") return wizardSourceSession;
          if (paramName === "pivot_window") return wizardSourcePivotWindow;
          if (paramName === "min_pivots") return wizardSourceMinPivots;
          if (paramName === "tri_lookback") return wizardSourceTriLookback;
          if (paramName === "slope_tolerance") return wizardSourceSlopeTolerance;
          if (paramName === "min_r_squared") return wizardSourceMinRSquared;
        } else if (role === "target") {
          if (paramName === "period") return wizardTargetPeriod;
          if (paramName === "stdDev") return wizardTargetDev;
          if (paramName === "band_line") return wizardTargetBand;
          if (paramName === "days_lookback") return wizardTargetDays;
          if (paramName === "orb_minutes") return wizardTargetOrb;
          if (paramName === "ap_session") return wizardTargetSession;
        } else {
          if (paramName === "period") return wizardDistanceLevelPeriod;
          if (paramName === "ap_session") return wizardDistanceLevelSession;
        }
      };

      const setVal = (paramName: string, val: any) => {
        if (role === "source") {
          if (paramName === "period") setWizardSourcePeriod(val);
          if (paramName === "stdDev") setWizardSourceDev(val);
          if (paramName === "band_line") setWizardSourceBand(val);
          if (paramName === "days_lookback") setWizardSourceDays(val);
          if (paramName === "orb_minutes") setWizardSourceOrb(val);
          if (paramName === "ap_session") setWizardSourceSession(val);
          if (paramName === "pivot_window") setWizardSourcePivotWindow(val);
          if (paramName === "min_pivots") setWizardSourceMinPivots(val);
          if (paramName === "tri_lookback") setWizardSourceTriLookback(val);
          if (paramName === "slope_tolerance") setWizardSourceSlopeTolerance(val);
          if (paramName === "min_r_squared") setWizardSourceMinRSquared(val);
        } else if (role === "target") {
          if (paramName === "period") setWizardTargetPeriod(val);
          if (paramName === "stdDev") setWizardTargetDev(val);
          if (paramName === "band_line") setWizardTargetBand(val);
          if (paramName === "days_lookback") setWizardTargetDays(val);
          if (paramName === "orb_minutes") setWizardTargetOrb(val);
          if (paramName === "ap_session") setWizardTargetSession(val);
        } else {
          if (paramName === "period") setWizardDistanceLevelPeriod(val);
          if (paramName === "ap_session") setWizardDistanceLevelSession(val);
        }
      };

      switch (name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.ATR:
        case IndicatorType.RVOL:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Período (Velas):</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.3 }}>Define el número de velas que se promedian. Ej: 20 velas para corto plazo, 200 para largo plazo.</span>
              <input
                type="number"
                value={getVal("period")}
                onChange={(e) => setVal("period", parseInt(e.target.value) || 14)}
                style={{ width: 60, background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "3px 6px", borderRadius: 4 }}
              />
            </div>
          );
        case IndicatorType.BOLLINGER_BANDS:
        case IndicatorType.DONCHIAN:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Período (Velas):</span>
                <input
                  type="number"
                  value={getVal("period")}
                  onChange={(e) => setVal("period", parseInt(e.target.value) || 20)}
                  style={{ width: 60, background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "3px 6px", borderRadius: 4 }}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Línea de Banda:</span>
                <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.3 }}>Selecciona si evalúas la banda Superior (Upper), la Inferior (Lower) o la Base (Basis).</span>
                <select
                  value={getVal("band_line")}
                  onChange={(e) => setVal("band_line", e.target.value)}
                  style={{ background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "3px 6px", borderRadius: 4 }}
                >
                  <option value="Upper">Upper (Superior)</option>
                  <option value="Basis">Basis (Base/Media)</option>
                  <option value="Lower">Lower (Inferior)</option>
                </select>
              </div>
              {name === IndicatorType.BOLLINGER_BANDS && (
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Desviación Estándar:</span>
                  <input
                    type="number"
                    step="0.1"
                    value={getVal("stdDev")}
                    onChange={(e) => setVal("stdDev", parseFloat(e.target.value) || 2)}
                    style={{ width: 60, background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "3px 6px", borderRadius: 4 }}
                  />
                </div>
              )}
            </div>
          );
        case IndicatorType.HIGH_X_DAYS:
        case IndicatorType.LOW_X_DAYS:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Días de Lookback:</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.3 }}>Número de días anteriores a evaluar.</span>
              <input
                type="number"
                value={getVal("days_lookback")}
                onChange={(e) => setVal("days_lookback", parseInt(e.target.value) || 5)}
                style={{ width: 60, background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "3px 6px", borderRadius: 4 }}
              />
            </div>
          );
        case IndicatorType.PREVIOUS_MAX:
        case IndicatorType.PREVIOUS_MIN:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Sesión de Referencia:</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.3 }}>Elige la sesión horaria desde la cual se medirá el máximo/mínimo anterior.</span>
              <select
                value={getVal("ap_session") || "ap.RTH"}
                onChange={(e) => setVal("ap_session", e.target.value as "ap.PM" | "ap.RTH" | "ap.AM")}
                style={{ background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "5px 8px", borderRadius: 5, cursor: "pointer", outline: "none" }}
              >
                <option value="ap.PM">ap.PM (Premarket)</option>
                <option value="ap.RTH">ap.RTH (Horario Regular)</option>
                <option value="ap.AM">ap.AM (After Market)</option>
              </select>
            </div>
          );
        case IndicatorType.OPENING_RANGE_PLUS:
        case IndicatorType.OPENING_RANGE_MINUS:
        case IndicatorType.OPENING_RANGE_AM_PLUS:
        case IndicatorType.OPENING_RANGE_AM_MINUS:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Minutos del Rango Inicial:</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.3 }}>La duración del rango inicial (ej: 30 minutos desde la apertura).</span>
              <input
                type="number"
                value={getVal("orb_minutes")}
                onChange={(e) => setVal("orb_minutes", parseInt(e.target.value) || 30)}
                style={{ width: 60, background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 10, padding: "3px 6px", borderRadius: 4 }}
              />
            </div>
          );
        case IndicatorType.TRIANGLE_ASCENDING:
        case IndicatorType.TRIANGLE_DESCENDING:
        case IndicatorType.TRIANGLE_SYMMETRIC:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
              <div style={{ display: "flex", gap: 6, width: "100%", flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 60px", minWidth: "60px" }}>
                  <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-ec-text-muted)", display: "block", marginBottom: 2 }}>Pivot Win.</span>
                  <input
                    type="number"
                    min={2}
                    max={20}
                    value={getVal("pivot_window")}
                    onChange={(e) => setVal("pivot_window", Math.max(2, parseInt(e.target.value) || 5))}
                    style={{
                      width: "100%",
                      backgroundColor: "var(--color-ec-bg-sidebar)",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 5,
                      padding: "5px 8px",
                      fontSize: 10,
                      fontWeight: 500,
                      color: "var(--color-ec-text-primary)",
                      fontFamily: "var(--color-ec-sans)",
                      outline: "none",
                    }}
                    title="Pivot Window: candles to left and right required to confirm a Swing High/Low"
                  />
                </div>
                <div style={{ flex: "1 1 60px", minWidth: "60px" }}>
                  <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-ec-text-muted)", display: "block", marginBottom: 2 }}>Min Pivots</span>
                  <input
                    type="number"
                    min={2}
                    max={50}
                    value={getVal("min_pivots")}
                    onChange={(e) => setVal("min_pivots", Math.max(2, parseInt(e.target.value) || 2))}
                    style={{
                      width: "100%",
                      backgroundColor: "var(--color-ec-bg-sidebar)",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 5,
                      padding: "5px 8px",
                      fontSize: 10,
                      fontWeight: 500,
                      color: "var(--color-ec-text-primary)",
                      fontFamily: "var(--color-ec-sans)",
                      outline: "none",
                    }}
                    title="Min Pivots: minimum swing highs and lows required to fit trend lines (min 2)"
                  />
                </div>
                <div style={{ flex: "1 1 60px", minWidth: "60px" }}>
                  <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-ec-text-muted)", display: "block", marginBottom: 2 }}>Lookback</span>
                  <input
                    type="number"
                    min={10}
                    max={200}
                    value={getVal("tri_lookback")}
                    onChange={(e) => setVal("tri_lookback", Math.max(10, parseInt(e.target.value) || 35))}
                    style={{
                      width: "100%",
                      backgroundColor: "var(--color-ec-bg-sidebar)",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 5,
                      padding: "5px 8px",
                      fontSize: 10,
                      fontWeight: 500,
                      color: "var(--color-ec-text-primary)",
                      fontFamily: "var(--color-ec-sans)",
                      outline: "none",
                    }}
                    title="Lookback: how many bars back to search for pivots"
                  />
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, width: "100%", flexWrap: "wrap", alignItems: "flex-end" }}>
                <div style={{ flex: "1 1 90px", minWidth: "90px" }}>
                  <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-ec-text-muted)", display: "block", marginBottom: 2 }}>Slope Tol. (%)</span>
                  <input
                    type="number"
                    min={0.01}
                    max={10.0}
                    step={0.1}
                    value={getVal("slope_tolerance")}
                    onChange={(e) => setVal("slope_tolerance", Math.max(0.01, parseFloat(e.target.value) || 1.5))}
                    style={{
                      width: "100%",
                      backgroundColor: "var(--color-ec-bg-sidebar)",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 5,
                      padding: "5px 8px",
                      fontSize: 10,
                      fontWeight: 500,
                      color: "var(--color-ec-text-primary)",
                      fontFamily: "var(--color-ec-sans)",
                      outline: "none",
                    }}
                    title="Slope Tolerance (%): max total price change over the lookback window to consider a trend line 'flat'"
                  />
                </div>
                <div style={{ flex: "1 2 110px", minWidth: "110px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-ec-text-muted)" }}>Min R²</span>
                    <span style={{ fontSize: 10, fontWeight: 600, color: "var(--color-ec-text-primary)", fontFamily: "var(--color-ec-sans)" }}>{Number(getVal("min_r_squared") ?? 0.65).toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={getVal("min_r_squared")}
                    onChange={(e) => setVal("min_r_squared", parseFloat(e.target.value) || 0.65)}
                    style={{
                      width: "100%",
                      accentColor: "var(--color-ec-copper)",
                      cursor: "pointer",
                    }}
                    title="Minimum R-squared quality for trend lines (0 = no requirement, 1 = perfect fit)"
                  />
                </div>
              </div>
            </div>
          );
        default:
          return null;
      }
    };

    const renderStepContent = () => {
      switch (wizardCondStep) {
        case 0:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Paso 1: Temporalidad de la condición</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
                Determina la temporalidad de las velas. Indica cada cuánto tiempo se actualizarán los datos de tu gráfico para calcular esta condición. Temporalidades cortas (como 1m o 5m) reaccionan rápido al precio, mientras que temporalidades más largas (como 15m, 1h o 1d) filtran el ruido del mercado.
              </span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                {timeframes.map((tf) => {
                  const isSelected = wizardTf === tf;
                  return (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setWizardTf(tf)}
                      style={{
                        padding: "6px 12px",
                        borderRadius: 5,
                        fontFamily: "var(--color-ec-sans)",
                        fontSize: 10,
                        fontWeight: 700,
                        cursor: "pointer",
                        transition: "all 150ms ease",
                        backgroundColor: isSelected ? "rgba(216, 122, 61, 0.08)" : "var(--color-ec-bg-surface)",
                        border: isSelected ? "1px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)",
                        color: isSelected ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                      }}
                    >
                      {tf}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        case 1:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Paso 2: Variable de Entrada</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
                Elige el elemento principal que quieres analizar. Puede ser el precio del activo ("Cierre de vela" / Bar Close) o un indicador técnico matemático (como medias móviles SMA/EMA o VWAP) calculado sobre los datos históricos.
              </span>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Indica la variable de entrada:</span>
                <WizardIndicatorSelector
                  value={wizardSource}
                  onChange={(val) => {
                    setWizardSource(val);
                    if (val === IndicatorType.ELAPSED_TIME) {
                      setWizardTargetValue(60);
                    } else if (val === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
                      setWizardTargetValue(20);
                    }
                  }}
                  exclude={mode !== 'exit' ? [IndicatorType.ELAPSED_TIME] : []}
                />
              </div>
              {renderParameterInputs(wizardSource, "source")}
            </div>
          );
        case 2:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Paso 3: Modo de Evaluación</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
                Define cómo se evaluará la variable principal. Puedes compararla directamente con un objetivo (ej: Cierre mayor que SMA) o medir el porcentaje de separación (distancia) que hay entre ambos (ej. precio a menos de 1% de distancia de la SMA).
              </span>
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <button
                  type="button"
                  onClick={() => {
                    setWizardMode("comparison");
                    setWizardComparator(Comparator.GT);
                  }}
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 5,
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    backgroundColor: wizardMode === "comparison" ? "rgba(216, 122, 61, 0.08)" : "var(--color-ec-bg-surface)",
                    border: wizardMode === "comparison" ? "1px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)",
                    color: wizardMode === "comparison" ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                  }}
                >
                  Comparación
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setWizardMode("distance");
                    setWizardComparator("DISTANCE_GT");
                  }}
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 5,
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    backgroundColor: wizardMode === "distance" ? "rgba(216, 122, 61, 0.08)" : "var(--color-ec-bg-surface)",
                    border: wizardMode === "distance" ? "1px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)",
                    color: wizardMode === "distance" ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                  }}
                >
                  Distancia %
                </button>
              </div>
            </div>
          );
        case 3:
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Paso 4: Relación de activación</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
                Selecciona la relación lógica que debe cumplirse. Un cruce (ej: cruza por encima) ocurre únicamente en el momento exacto en que una línea atraviesa a la otra. Una comparación simple (ej: mayor que) se mantiene activa mientras la variable esté por encima de la referencia.
              </span>
              <select
                value={wizardComparator}
                onChange={(e) => setWizardComparator(e.target.value)}
                style={{
                  width: "100%",
                  background: "var(--color-ec-bg-surface)",
                  border: "0.5px solid var(--color-ec-border)",
                  color: "var(--color-ec-text-primary)",
                  fontSize: 11,
                  padding: "6px 8px",
                  borderRadius: 5,
                  outline: "none",
                  cursor: "pointer",
                  marginTop: 4
                }}
              >
                {(wizardMode === "comparison"
                  ? (wizardSource === IndicatorType.PM_HIGH_GAP
                     ? comparatorOptions.filter(opt => [Comparator.GT, Comparator.LT, Comparator.GTE, Comparator.LTE].includes(opt.value as Comparator))
                     : [
                         IndicatorType.BAR_CLOSE,
                         IndicatorType.BAR_OPEN,
                         IndicatorType.HIGH_BAR,
                         IndicatorType.LOW_BAR,
                         IndicatorType.SMA,
                         IndicatorType.EMA,
                         IndicatorType.VWAP
                       ].includes(wizardSource)
                       ? comparatorOptions
                       : comparatorOptions.filter(opt => opt.value !== Comparator.CROSSES_ABOVE && opt.value !== Comparator.CROSSES_BELOW))
                  : distanceComparatorOptions).map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          );
        case 4: {
          const allowedCompTargets = getAllowedTargets(wizardSource, "indicator_comparison");
          const showToggle = allowedCompTargets.length > 0;
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Paso 5: Objetivo / Cruce</span>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.4 }}>
                {wizardMode === "comparison" 
                  ? "Define contra qué valor o indicador comparamos nuestra variable de entrada. Puedes elegir un valor fijo (un precio exacto en dólares) o un indicador técnico dinámico (como el VWAP o una media móvil)." 
                  : "Define con respecto a qué indicador de referencia medirás la distancia, y especifica el porcentaje máximo de separación permitido para activar la entrada."}
              </span>
              {wizardMode === "comparison" ? (
                <>
                  {showToggle && (
                    <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                      <button
                        type="button"
                        onClick={() => setWizardTargetType("fixed")}
                        style={{
                          flex: 1,
                          padding: "6px 12px",
                          borderRadius: 4,
                          fontFamily: "var(--color-ec-sans)",
                          fontSize: 9,
                          fontWeight: 700,
                          cursor: "pointer",
                          transition: "all 150ms ease",
                          backgroundColor: wizardTargetType === "fixed" ? "rgba(216, 122, 61, 0.08)" : "var(--color-ec-bg-surface)",
                          border: wizardTargetType === "fixed" ? "1px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)",
                          color: wizardTargetType === "fixed" ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                        }}
                      >
                        Valor Fijo
                      </button>
                      <button
                        type="button"
                        onClick={() => setWizardTargetType("indicator")}
                        style={{
                          flex: 1,
                          padding: "6px 12px",
                          borderRadius: 4,
                          fontFamily: "var(--color-ec-sans)",
                          fontSize: 9,
                          fontWeight: 700,
                          cursor: "pointer",
                          transition: "all 150ms ease",
                          backgroundColor: wizardTargetType === "indicator" ? "rgba(216, 122, 61, 0.08)" : "var(--color-ec-bg-surface)",
                          border: wizardTargetType === "indicator" ? "1px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)",
                          color: wizardTargetType === "indicator" ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                        }}
                      >
                        Otro Indicador
                      </button>
                    </div>
                  )}
                  {wizardTargetType === "fixed" ? (
                    isVolumeIndicator(wizardSource) ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
                        <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Volumen (en millones de acciones, ej. 1.5 para 1.5M):</span>
                        <div style={{ position: "relative", width: "100%" }}>
                          <input
                            type="text"
                            value={wizardTargetValueText}
                            onChange={(e) => {
                              const txt = e.target.value;
                              setWizardTargetValueText(txt);
                              const clean = txt.trim().toLowerCase();
                              const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
                              const num = parseFloat(numericStr);
                              if (!isNaN(num)) {
                                setWizardTargetValue(num * 1000000);
                              }
                            }}
                            placeholder="e.g. 1.5"
                            style={{ width: "100%", background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 11, padding: "5px 24px 5px 8px", borderRadius: 4, boxSizing: "border-box" }}
                          />
                          <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            fontFamily: 'var(--color-ec-sans)',
                            pointerEvents: 'none'
                          }}>M</span>
                        </div>
                      </div>
                    ) : wizardSource === IndicatorType.PM_HIGH_GAP ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
                        <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Valor (en %):</span>
                        <div style={{ position: "relative", width: "100%" }}>
                          <input
                            type="number"
                            step="0.01"
                            value={wizardTargetValue}
                            onChange={(e) => setWizardTargetValue(parseFloat(e.target.value) || 0)}
                            placeholder="e.g. 2.5"
                            style={{ width: "100%", background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 11, padding: "5px 24px 5px 8px", borderRadius: 4, boxSizing: "border-box" }}
                          />
                          <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            fontFamily: 'var(--color-ec-sans)',
                            pointerEvents: 'none'
                          }}>%</span>
                        </div>
                      </div>
                    ) : wizardSource === IndicatorType.ELAPSED_TIME_LAST_HIGH || wizardSource === IndicatorType.ELAPSED_TIME ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
                        <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Tiempo Transcurrido (en minutos):</span>
                        <div style={{ position: "relative", width: "100%" }}>
                          <input
                            type="number"
                            min="1"
                            value={wizardTargetValue || (wizardSource === IndicatorType.ELAPSED_TIME ? 60 : 20)}
                            onChange={(e) => setWizardTargetValue(Math.max(1, parseInt(e.target.value) || 0))}
                            style={{ width: "100%", background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 11, padding: "5px 40px 5px 8px", borderRadius: 4, boxSizing: "border-box" }}
                          />
                          <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            fontFamily: 'var(--color-ec-sans)',
                            pointerEvents: 'none'
                          }}>mins</span>
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
                        <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Valor Numérico (en USD):</span>
                        <input
                          type="number"
                          step="0.01"
                          value={wizardTargetValue}
                          onChange={(e) => setWizardTargetValue(parseFloat(e.target.value) || 0)}
                          style={{ width: "100%", background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 11, padding: "5px 8px", borderRadius: 4 }}
                        />
                      </div>
                    )
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
                      <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Selecciona Indicador Objetivo:</span>
                      <WizardIndicatorSelector
                        value={wizardTargetIndicator}
                        onChange={(val) => setWizardTargetIndicator(val)}
                        allowedTargets={allowedCompTargets}
                      />
                      {renderParameterInputs(wizardTargetIndicator, "target")}

                      {/* Offset Checkbox and Input for Comparison Target */}
                      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <input
                            type="checkbox"
                            id="wizard-target-offset-checkbox"
                            checked={wizardTargetOffset > 0}
                            onChange={(e) => {
                              setWizardTargetOffset(e.target.checked ? 1 : 0);
                            }}
                            style={{
                              width: 14,
                              height: 14,
                              accentColor: 'var(--color-ec-copper)',
                              cursor: 'pointer'
                            }}
                          />
                          <label
                            htmlFor="wizard-target-offset-checkbox"
                            style={{
                              fontSize: 10,
                              fontWeight: 600,
                              color: 'var(--color-ec-text-primary)',
                              cursor: 'pointer',
                              userSelect: 'none'
                            }}
                          >
                            ¿Offset a Variable de cruce?
                          </label>
                          <CustomTooltip
                            title="¿Offset a Variable de cruce?"
                            text="Compara la variable de entrada con el valor de la variable de cruce de X velas hacia atrás. Ejemplo: Si Bar Close &gt; SMA_30 y le indicamos un offset de 3 velas, el Bar Close Actual comparará si es mayor que el valor del SMA_30 de hace 3 velas y no del actual."
                          />
                        </div>

                        {wizardTargetOffset > 0 && (
                          <div style={{ 
                            display: 'flex', 
                            alignItems: 'center', 
                            gap: 8, 
                            paddingLeft: 20,
                            marginTop: 2
                          }}>
                            <span style={{
                              fontSize: 10,
                              fontWeight: 600,
                              color: 'var(--color-ec-text-secondary)',
                              fontFamily: 'var(--color-ec-sans)',
                            }}>Velas atrás:</span>
                            <select
                              value={wizardTargetOffset}
                              onChange={(e) => setWizardTargetOffset(Number(e.target.value))}
                              style={{
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 4,
                                padding: '2px 8px 2px 6px',
                                fontSize: 11,
                                fontWeight: 700,
                                color: 'var(--color-ec-copper)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                                cursor: 'pointer',
                                width: 55,
                                textAlign: 'center'
                              }}
                            >
                              {Array.from({ length: 20 }, (_, i) => i + 1).map((val) => (
                                <option key={val} value={val} style={{ backgroundColor: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-primary)' }}>
                                  {val}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Medir distancia respecto a:</span>
                    <WizardIndicatorSelector
                      value={wizardDistanceLevel}
                      onChange={(val) => setWizardDistanceLevel(val)}
                      allowedTargets={getAllowedTargets(wizardSource, 'price_level_distance')}
                    />
                    {renderParameterInputs(wizardDistanceLevel, "distance_level")}

                    {/* Offset Checkbox and Input for Distance Level */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <input
                          type="checkbox"
                          id="wizard-distance-offset-checkbox"
                          checked={wizardDistanceLevelOffset > 0}
                          onChange={(e) => {
                            setWizardDistanceLevelOffset(e.target.checked ? 1 : 0);
                          }}
                          style={{
                            width: 14,
                            height: 14,
                            accentColor: 'var(--color-ec-copper)',
                            cursor: 'pointer'
                          }}
                        />
                        <label
                          htmlFor="wizard-distance-offset-checkbox"
                          style={{
                            fontSize: 10,
                            fontWeight: 600,
                            color: 'var(--color-ec-text-primary)',
                            cursor: 'pointer',
                            userSelect: 'none'
                          }}
                        >
                          ¿Offset a Variable de cruce?
                        </label>
                        <CustomTooltip
                          title="¿Offset a Variable de cruce?"
                          text="Compara la variable de entrada con el valor de la variable de cruce de X velas hacia atrás. Ejemplo: Si Bar Close &gt; SMA_30 y le indicamos un offset de 3 velas, el Bar Close Actual comparará si es mayor que el valor del SMA_30 de hace 3 velas y no del actual."
                        />
                      </div>

                      {wizardDistanceLevelOffset > 0 && (
                        <div style={{ 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: 8, 
                          paddingLeft: 20,
                          marginTop: 2
                        }}>
                          <span style={{
                            fontSize: 10,
                            fontWeight: 600,
                            color: 'var(--color-ec-text-secondary)',
                            fontFamily: 'var(--color-ec-sans)',
                          }}>Velas atrás:</span>
                          <select
                            value={wizardDistanceLevelOffset}
                            onChange={(e) => setWizardDistanceLevelOffset(Number(e.target.value))}
                            style={{
                              backgroundColor: 'var(--color-ec-bg-sidebar)',
                              border: '0.5px solid var(--color-ec-border)',
                              borderRadius: 4,
                              padding: '2px 8px 2px 6px',
                              fontSize: 11,
                              fontWeight: 700,
                              color: 'var(--color-ec-copper)',
                              fontFamily: 'var(--color-ec-sans)',
                              outline: 'none',
                              cursor: 'pointer',
                              width: 55,
                              textAlign: 'center'
                            }}
                          >
                            {Array.from({ length: 20 }, (_, i) => i + 1).map((val) => (
                              <option key={val} value={val} style={{ backgroundColor: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-primary)' }}>
                                {val}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Distancia requerida (%):</span>
                    <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.3 }}>Especifica el porcentaje de margen máximo (ej: 0.5 para 0.5% de separación).</span>
                    <input
                      type="number"
                      step="0.01"
                      value={wizardDistanceValue}
                      onChange={(e) => setWizardDistanceValue(parseFloat(e.target.value) || 0.5)}
                      style={{ width: "100%", background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)", fontSize: 11, padding: "5px 8px", borderRadius: 4 }}
                    />
                  </div>
                  {/* Distance Position Selector */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Posición:</span>
                    <select
                      value={wizardDistancePosition}
                      onChange={(e) => setWizardDistancePosition(e.target.value as 'above' | 'below' | 'any')}
                      style={{
                        width: "100%",
                        background: "var(--color-ec-bg-surface)",
                        border: "0.5px solid var(--color-ec-border)",
                        color: "var(--color-ec-text-primary)",
                        fontSize: 11,
                        padding: "6px 8px",
                        borderRadius: 5,
                        outline: "none",
                        cursor: "pointer",
                        marginTop: 2
                      }}
                    >
                      <option value="any">Cualquiera (Any)</option>
                      <option value="above">Por encima del nivel</option>
                      <option value="below">Por debajo del nivel</option>
                    </select>
                  </div>
                </div>
              )}
            </div>
          );
        }
        default:
          return null;
      }
    };

    const condStepsList = getCondStepsList();

    const currentIndicatorStepNum = condStepsList.indexOf(wizardCondStep);

    return (
      <div>
        <h3 style={{
          fontFamily: "var(--color-ec-serif)",
          fontSize: 14,
          fontWeight: 600,
          color: "var(--color-ec-text-high)",
          margin: "0 0 4px 0",
          letterSpacing: "-0.2px",
        }}>
          {mode === 'entry' 
            ? "¿Cuáles son las condiciones para entrar al mercado?"
            : "¿Cuáles son las condiciones para salir del mercado?"}
        </h3>
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-muted)",
          margin: "0 0 16px 0",
          lineHeight: 1.5,
        }}>
          {mode === 'entry'
            ? "define las variables de entrada"
            : "Opcional. Define las condiciones basadas en indicadores técnicos que cerrarán tu posición de forma anticipada"}
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {wizardCondStep === -1 ? (
            <div
              onClick={() => setWizardCondStep(0)}
              style={{
                backgroundColor: "var(--color-ec-bg-elevated)",
                border: "1.5px dashed var(--color-ec-border)",
                borderRadius: 8,
                padding: "24px 16px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                cursor: "pointer",
                transition: "all 200ms ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "var(--color-ec-copper)";
                e.currentTarget.style.backgroundColor = "rgba(216, 122, 61, 0.04)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--color-ec-border)";
                e.currentTarget.style.backgroundColor = "var(--color-ec-bg-elevated)";
              }}
            >
              <span style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "var(--color-ec-copper)"
              }}>
                + Nueva Condición
              </span>
              <span style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 9,
                color: "var(--color-ec-text-muted)",
                textAlign: "center"
              }}>
                {mode === 'entry'
                  ? "Haz clic aquí para definir una nueva regla de entrada basada en precio o indicadores."
                  : "Haz clic aquí para definir una nueva regla de salida basada en precio o indicadores."}
              </span>
            </div>
          ) : (
            /* Step-by-Step UI Card */
            <div style={{
              backgroundColor: "var(--color-ec-bg-elevated)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 8,
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
              boxShadow: "0 4px 20px rgba(0, 0, 0, 0.15)"
            }}>
              {/* Header */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: "var(--color-ec-copper)"
                }}>
                  Condición
                </span>
                {/* Step indicators dots */}
                <div style={{ display: "flex", gap: 4 }}>
                  {condStepsList.map((stepNum, idx) => {
                    const isActiveStep = stepNum === wizardCondStep;
                    const isPassedStep = condStepsList.indexOf(stepNum) < currentIndicatorStepNum;
                    return (
                      <div
                        key={stepNum}
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          backgroundColor: isActiveStep
                            ? "var(--color-ec-copper)"
                            : isPassedStep
                            ? "rgba(216, 122, 61, 0.45)"
                            : "var(--color-ec-border)",
                          transition: "all 200ms ease"
                        }}
                      />
                    );
                  })}
                </div>
              </div>

              <div style={{ height: "0.5px", backgroundColor: "var(--color-ec-border)" }} />

              {/* Body */}
              <div style={{ minHeight: 120 }}>
                {renderStepContent()}
              </div>

              {/* Live Preview Tags */}
              {renderLivePreviewTags()}

              {/* Sub-wizard Navigation Footer */}
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                {wizardCondStep > 0 ? (
                  <button
                    type="button"
                    onClick={handleBack}
                    style={{
                      backgroundColor: "transparent",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 5,
                      padding: "5px 10px",
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      color: "var(--color-ec-text-muted)",
                      cursor: "pointer"
                    }}
                  >
                    Atrás
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleBack}
                    style={{
                      backgroundColor: "transparent",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 5,
                      padding: "5px 10px",
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      color: "var(--color-ec-text-muted)",
                      cursor: "pointer"
                    }}
                  >
                    Cancelar
                  </button>
                )}

                {currentIndicatorStepNum < condStepsList.length - 1 ? (
                  <button
                    type="button"
                    onClick={handleNext}
                    style={{
                      backgroundColor: "var(--color-ec-copper)",
                      color: "var(--color-ec-copper-text)",
                      border: "none",
                      borderRadius: 5,
                      padding: "5px 12px",
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      cursor: "pointer"
                    }}
                  >
                    Siguiente
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleAddCondition}
                    style={{
                      backgroundColor: "var(--color-ec-profit)",
                      color: "#fff",
                      border: "none",
                      borderRadius: 5,
                      padding: "5px 14px",
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      cursor: "pointer",
                      boxShadow: "0 2px 8px rgba(34, 197, 94, 0.2)"
                    }}
                  >
                    + Añadir Condición
                  </button>
                )}
              </div>
            </div>
          )}

          {/* List of Added Conditions inside the wizard panel */}
          {logic.root_condition.conditions.length > 0 && (
            <div style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              marginTop: 4,
              padding: 12,
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 6,
              backgroundColor: "var(--color-ec-bg-surface)"
            }}>
              <span style={{
                fontSize: 8,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "var(--color-ec-text-secondary)",
              }}>
                {mode === 'entry' ? "Condiciones Añadidas" : "Condiciones de Salida Añadidas"}
              </span>
              <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                {logic.root_condition.conditions.map((cond: any, idx: number) => {
                  const label = getConditionTags({ type: "group", operator: "AND", conditions: [cond] }, logic.timeframe, () => {})[0]?.label || "Condición";
                  return (
                    <div
                      key={idx}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "4px 10px",
                        backgroundColor: "rgba(216, 122, 61, 0.12)",
                        border: "0.5px solid rgba(216, 122, 61, 0.35)",
                        borderRadius: 6,
                        fontFamily: "var(--color-ec-sans)",
                        fontSize: 10,
                        fontWeight: 600,
                        color: "var(--color-ec-text-high)",
                        animation: "wizTagSlideIn 200ms ease"
                      }}
                    >
                      <span>{label}</span>
                      <button
                        type="button"
                        onClick={() => {
                          const newConds = logic.root_condition.conditions.filter((_, i) => i !== idx);
                          setLogic({
                            ...logic,
                            root_condition: {
                              ...logic.root_condition,
                              conditions: newConds
                            }
                          });
                        }}
                        style={{
                          background: "none",
                          border: "none",
                          color: "var(--color-ec-text-muted)",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          padding: 1,
                          fontSize: 12,
                          lineHeight: 1,
                          marginLeft: 2,
                          transition: "color 150ms ease"
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.color = "var(--color-ec-loss)"}
                        onMouseLeave={(e) => e.currentTarget.style.color = "var(--color-ec-text-muted)"}
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Entry Time Windows Sub-panel */}
          {mode === 'entry' && (
            <div style={{
              marginTop: 6,
              paddingTop: 14,
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
                    Ventanas Horarias de Entrada
                  </span>
                </div>
                <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>
                  Nueva York (ET)
                </span>
              </div>

              {/* Inputs Row */}
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
                        setCompletedSteps((prev) => new Set(prev).add(STEPS.findIndex(s => s.key === "entry")));
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

              {/* Validation warning */}
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

              {/* Active windows list */}
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
                          padding: '3px 6px',
                          fontFamily: 'var(--color-ec-sans)',
                          fontSize: 9,
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
          )}
        </div>
      </div>
    );
  };

  // Step 5: Gestión de riesgo (Risk Management) - Sub-step helpers
  const renderRiskSubStepStopLoss = () => {
    const isStopOn = riskManagement.use_hard_stop === true;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }} className="animate-in fade-in duration-200">
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            Límite de Pérdida (Hard Stop Loss)
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 12px 0",
            lineHeight: 1.5,
          }}>
            El **Stop Loss** es tu red de seguridad. Cierra automáticamente la operación si el mercado va en tu contra para evitar pérdidas descontroladas.
          </p>
        </div>

        {/* Toggle Option */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          backgroundColor: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 6,
        }}>
          <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-primary)" }}>
            ¿Activar Stop Loss?
          </span>
          <div className="flex items-center gap-2">
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              fontWeight: 700,
              color: 'var(--color-ec-text-muted)',
            }}>{isStopOn ? 'SÍ' : 'NO'}</span>
            <div
              className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${isStopOn ? 'bg-ec-loss/70' : 'bg-muted'}`}
              onClick={() => setRiskManagement({
                ...riskManagement,
                use_hard_stop: !isStopOn,
                size_by_sl: false // Hidden in Wizard, always false
              })}
            >
              <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${isStopOn ? 'left-4.5' : 'left-0.5'}`}></div>
            </div>
          </div>
        </div>

        {/* Form Inputs if Stop Loss is Active */}
        {isStopOn && (
          <div 
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              padding: 14,
              backgroundColor: "rgba(255, 255, 255, 0.01)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 6,
            }}
            className="animate-in fade-in duration-200"
          >
            {/* Type selection: Percentage vs Market Structure */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Tipo de Stop Loss:</span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => setRiskManagement({
                    ...riskManagement,
                    hard_stop: { type: RiskType.PERCENTAGE, value: 2.0 },
                    size_by_sl: false
                  })}
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 5,
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    backgroundColor: riskManagement.hard_stop.type === RiskType.PERCENTAGE ? "rgba(239, 68, 68, 0.07)" : "var(--color-ec-bg-surface)",
                    border: riskManagement.hard_stop.type === RiskType.PERCENTAGE ? "1px solid var(--color-ec-loss)" : "0.5px solid var(--color-ec-border)",
                    color: riskManagement.hard_stop.type === RiskType.PERCENTAGE ? "var(--color-ec-text-high)" : "var(--color-ec-text-primary)",
                  }}
                >
                  Porcentaje (%)
                </button>
                <button
                  type="button"
                  onClick={() => setRiskManagement({
                    ...riskManagement,
                    hard_stop: { type: RiskType.MARKET_STRUCTURE, value: 'LOD', operator: '>=', offset_pct: 0.0 },
                    size_by_sl: false
                  })}
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 5,
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    backgroundColor: riskManagement.hard_stop.type === RiskType.MARKET_STRUCTURE ? "rgba(239, 68, 68, 0.07)" : "var(--color-ec-bg-surface)",
                    border: riskManagement.hard_stop.type === RiskType.MARKET_STRUCTURE ? "1px solid var(--color-ec-loss)" : "0.5px solid var(--color-ec-border)",
                    color: riskManagement.hard_stop.type === RiskType.MARKET_STRUCTURE ? "var(--color-ec-text-high)" : "var(--color-ec-text-primary)",
                  }}
                >
                  Estructura de Mercado
                </button>
              </div>
            </div>

            {/* Inputs based on type */}
            {riskManagement.hard_stop.type === RiskType.PERCENTAGE ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "center", textAlign: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Valor del porcentaje</span>
                  <CustomTooltip
                    title="Stop Loss fijo en %"
                    text="Define la distancia porcentual máxima que permites que el precio se mueva en contra antes de cerrar la posición con pérdidas."
                  />
                </div>
                <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.35 }}>Ejemplo: 2.0% de distancia máxima de Stop Loss con respecto a tu precio de entrada.</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "center" }}>
                  <div
                    style={{
                      backgroundColor: 'var(--color-ec-bg-sidebar)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '7px 14px',
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-primary)',
                      fontFamily: 'var(--color-ec-sans)',
                      height: '36px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      userSelect: 'none',
                    }}
                  >
                    %
                  </div>
                  <div className="relative" style={{ width: '120px' }}>
                    <input
                      type="number"
                      step="0.1"
                      value={typeof riskManagement.hard_stop.value === 'number' ? riskManagement.hard_stop.value : 2.0}
                      onChange={(e) => setRiskManagement({
                        ...riskManagement,
                        hard_stop: { ...riskManagement.hard_stop, value: Number(e.target.value) }
                      })}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '7px 24px 7px 10px',
                        fontSize: 13,
                        fontWeight: 600,
                        color: 'var(--color-ec-text-primary)',
                        fontFamily: 'var(--color-ec-sans)',
                        outline: 'none',
                        width: '100%',
                        height: '36px',
                        textAlign: 'center',
                      }}
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center", textAlign: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Parámetros de estructura</span>
                  <CustomTooltip
                    title="Referencia de Estructura"
                    text="Sitúa tu Stop Loss en base a precios clave (LOD, HOD, etc.) más un % de margen (offset).<br/><br/><strong>Ejemplo de Dirección:</strong><br/>• Si compras (Largo) y usas el <strong>LOD</strong> (mínimo), pon el Stop <strong>Por debajo</strong> (resta el % al LOD, ej: LOD - 1%).<br/>• Si vendes corto y usas el <strong>HOD</strong> (máximo), pon el Stop <strong>Por encima</strong> (suma el % al HOD, ej: HOD + 1%)."
                  />
                </div>
                <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.35 }}>
                  Establece el Stop Loss en base a referencias clave del mercado (como el mínimo/máximo diario LOD/HOD) más un margen de holgura (offset).
                </span>
                
                <div style={{ display: "flex", gap: 5, alignItems: "center", justifyContent: "center", flexWrap: "nowrap" }}>
                  {/* Custom Dropdown for Level selection with explanations and ? symbols */}
                  <div ref={slLevelDropdownRef} style={{ position: "relative", width: "90px" }}>
                    <div
                      onClick={() => {
                        setIsLevelDropdownOpen(!isLevelDropdownOpen);
                      }}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '6px 8px',
                        fontSize: 11,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-primary)',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                        height: '32px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        boxSizing: 'border-box',
                        userSelect: 'none',
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 5, overflow: "hidden", flex: 1 }}>
                        <span style={{ textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                          {(() => {
                            const val = riskManagement.hard_stop.value || 'LOD';
                            if (val === 'Previous Max') return 'Prev. Max';
                            if (val === 'Previous Min') return 'Prev. Min';
                            return val;
                          })()}
                        </span>
                        <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex", alignItems: "center" }}>
                          <CustomTooltip
                            title={(() => {
                              const val = riskManagement.hard_stop.value || 'LOD';
                              if (val === 'Previous Max') return 'Prev. Max';
                              if (val === 'Previous Min') return 'Prev. Min';
                              return String(val);
                            })()}
                            text={MARKET_LEVEL_DESCRIPTIONS[String(riskManagement.hard_stop.value || 'LOD')] || ""}
                          />
                        </span>
                      </div>
                      <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", marginLeft: 4 }}>
                        {isLevelDropdownOpen ? "▲" : "▼"}
                      </span>
                    </div>

                    {isLevelDropdownOpen && (
                      <div style={{
                        position: "absolute",
                        bottom: "110%", // open upwards
                        left: 0,
                        width: "120px",
                        backgroundColor: "var(--color-ec-bg-elevated)",
                        border: "0.5px solid var(--color-ec-border)",
                        borderRadius: 6,
                        boxShadow: "0 -4px 16px rgba(0,0,0,0.4)",
                        zIndex: 110,
                        padding: "4px 0",
                      }}>
                        {[
                          { val: "HOD", label: "HOD" },
                          { val: "LOD", label: "LOD" },
                          { val: "PMH", label: "PMH" },
                          { val: "PML", label: "PML" },
                          { val: "Previous Max", label: "Prev. Max" },
                          { val: "Previous Min", label: "Prev. Min" },
                        ].map((opt) => {
                          const isSelected = (riskManagement.hard_stop.value || 'LOD') === opt.val;
                          return (
                            <div
                              key={opt.val}
                              onClick={() => {
                                setRiskManagement({
                                  ...riskManagement,
                                  hard_stop: { ...riskManagement.hard_stop, value: opt.val }
                                });
                                setIsLevelDropdownOpen(false);
                              }}
                              style={{
                                padding: "6px 8px",
                                fontSize: 10,
                                color: isSelected ? "var(--color-ec-copper)" : "var(--color-ec-text-primary)",
                                fontWeight: isSelected ? 700 : 500,
                                cursor: "pointer",
                                display: "flex",
                                justifyContent: "flex-start",
                                alignItems: "center",
                                gap: 5,
                                backgroundColor: isSelected ? "rgba(216, 122, 61, 0.06)" : "transparent",
                                borderLeft: isSelected ? "2px solid var(--color-ec-copper)" : "2px solid transparent",
                                transition: "all 100ms ease",
                              }}
                              onMouseEnter={(e) => {
                                if (!isSelected) {
                                  e.currentTarget.style.backgroundColor = "var(--color-ec-bg-surface)";
                                }
                              }}
                              onMouseLeave={(e) => {
                                if (!isSelected) {
                                  e.currentTarget.style.backgroundColor = "transparent";
                                }
                              }}
                            >
                              <span>{opt.label}</span>
                              <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex", alignItems: "center" }}>
                                <CustomTooltip
                                  title={opt.label}
                                  text={MARKET_LEVEL_DESCRIPTIONS[opt.val] || ""}
                                />
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  
                  <select
                    value={riskManagement.hard_stop.operator || '>='}
                    onChange={(e) => setRiskManagement({
                      ...riskManagement,
                      hard_stop: { ...riskManagement.hard_stop, operator: e.target.value }
                    })}
                    style={{
                      backgroundColor: 'var(--color-ec-bg-sidebar)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '6px 4px',
                      fontSize: 11,
                      fontWeight: 500,
                      color: 'var(--color-ec-text-primary)',
                      fontFamily: 'var(--color-ec-sans)',
                      outline: 'none',
                      cursor: 'pointer',
                      width: '95px',
                      height: '32px',
                      textAlign: 'center',
                    }}
                  >
                    <option value=">=">Por encima</option>
                    <option value="<=">Por debajo</option>
                  </select>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <div style={{ position: 'relative', width: '60px' }}>
                      <input
                        type="number"
                        step="0.1"
                        value={riskManagement.hard_stop.offset_pct ?? 0.0}
                        onChange={(e) => setRiskManagement({
                          ...riskManagement,
                          hard_stop: { ...riskManagement.hard_stop, offset_pct: parseFloat(e.target.value) || 0.0 }
                        })}
                        style={{
                          backgroundColor: 'var(--color-ec-bg-sidebar)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 5,
                          padding: '6px 14px 6px 6px',
                          fontSize: 11,
                          fontWeight: 600,
                          color: 'var(--color-ec-text-primary)',
                          fontFamily: 'var(--color-ec-sans)',
                          outline: 'none',
                          width: '100%',
                          height: '32px',
                          boxSizing: 'border-box',
                          textAlign: 'right'
                        }}
                      />
                      <span style={{
                        position: 'absolute',
                        right: 4,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        fontSize: 9,
                        fontWeight: 700,
                        color: 'var(--color-ec-text-muted)',
                        pointerEvents: 'none',
                      }}>
                        %
                      </span>
                    </div>
                    <CustomTooltip
                      title="Holgura (Offset)"
                      text="Porcentaje de margen extra que se suma o resta a la referencia para evitar que barridos de precio temporales toquen tu stop."
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Local Preview Tag underneath inputs */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 8,
          padding: "8px 10px",
          backgroundColor: "var(--color-ec-bg-elevated)",
          borderRadius: 6,
          border: "0.5px solid var(--color-ec-border)"
        }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Configuración actual SL:</span>
          <span style={{
            fontSize: 9,
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 4,
            backgroundColor: isStopOn ? "rgba(239, 68, 68, 0.08)" : "rgba(255, 255, 255, 0.03)",
            color: isStopOn ? "var(--color-ec-loss)" : "var(--color-ec-text-muted)",
            border: isStopOn ? "0.5px solid rgba(239, 68, 68, 0.2)" : "0.5px solid rgba(255, 255, 255, 0.1)"
          }}>
            {!isStopOn 
              ? "Desactivado" 
              : riskManagement.hard_stop.type === RiskType.PERCENTAGE 
              ? `Stop Loss: ${riskManagement.hard_stop.value}%` 
              : `Stop Loss: ${riskManagement.hard_stop.value} ${(riskManagement.hard_stop.operator === '<' || riskManagement.hard_stop.operator === '<=') ? '-' : '+'} ${riskManagement.hard_stop.offset_pct ?? 0}%`}
          </span>
        </div>
      </div>
    );
  };

  const renderRiskSubStepTakeProfit = () => {
    const isTpOn = riskManagement.use_take_profit === true;
    
    const addPartial = () => {
      const currentPartials = riskManagement.partial_take_profits || [];
      const lastPartial = currentPartials.length > 0 ? currentPartials[currentPartials.length - 1] : null;
      let lastDist = 3.0;
      if (lastPartial && typeof lastPartial.distance_pct === 'number') {
        lastDist = lastPartial.distance_pct;
      }
      const currentTotal = currentPartials.reduce((sum, p) => sum + p.capital_pct, 0);
      const remaining = Math.max(0, 100 - currentTotal);
      
      setRiskManagement({
        ...riskManagement,
        partial_take_profits: [
          ...currentPartials,
          { distance_pct: Number((lastDist + 2).toFixed(1)), capital_pct: remaining > 0 ? remaining : 25 }
        ]
      });
    };

    const removePartial = (index: number) => {
      setRiskManagement({
        ...riskManagement,
        partial_take_profits: riskManagement.partial_take_profits.filter((_, i) => i !== index)
      });
    };

    const updatePartial = (index: number, field: keyof PartialTakeProfit, value: number | 'EOD') => {
      setRiskManagement({
        ...riskManagement,
        partial_take_profits: riskManagement.partial_take_profits.map((p, i) =>
          i === index ? { ...p, [field]: value } : p
        )
      });
    };

    const totalPartialCapital = (riskManagement.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0);

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }} className="animate-in fade-in duration-200">
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            Toma de Ganancias (Take Profit)
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 12px 0",
            lineHeight: 1.5,
          }}>
            El **Take Profit** define el nivel de precio en el que decides vender automáticamente para asegurar tus beneficios.
          </p>
        </div>

        {/* Toggle Option */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          backgroundColor: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 6,
        }}>
          <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-primary)" }}>
            ¿Activar Take Profit?
          </span>
          <div className="flex items-center gap-2">
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              fontWeight: 700,
              color: 'var(--color-ec-text-muted)',
            }}>{isTpOn ? 'SÍ' : 'NO'}</span>
            <div
              className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${isTpOn ? 'bg-ec-profit/70' : 'bg-muted'}`}
              onClick={() => setRiskManagement({ ...riskManagement, use_take_profit: !isTpOn })}
            >
              <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${isTpOn ? 'left-4.5' : 'left-0.5'}`}></div>
            </div>
          </div>
        </div>

        {/* Form Inputs if Take Profit is Active */}
        {isTpOn && (
          <div 
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              padding: 14,
              backgroundColor: "rgba(255, 255, 255, 0.01)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 6,
            }}
            className="animate-in fade-in duration-200"
          >
            {/* Mode selection: Full vs Partial */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Tipo de salida:</span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => setRiskManagement({
                    ...riskManagement,
                    take_profit_mode: TakeProfitMode.FULL
                  })}
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 5,
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    backgroundColor: riskManagement.take_profit_mode === TakeProfitMode.FULL ? "rgba(34, 197, 94, 0.07)" : "var(--color-ec-bg-surface)",
                    border: riskManagement.take_profit_mode === TakeProfitMode.FULL ? "1px solid var(--color-ec-profit)" : "0.5px solid var(--color-ec-border)",
                    color: riskManagement.take_profit_mode === TakeProfitMode.FULL ? "var(--color-ec-text-high)" : "var(--color-ec-text-primary)",
                  }}
                >
                  Completo (Full)
                </button>
                <button
                  type="button"
                  onClick={() => setRiskManagement({
                    ...riskManagement,
                    take_profit_mode: TakeProfitMode.PARTIAL
                  })}
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 5,
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    backgroundColor: riskManagement.take_profit_mode === TakeProfitMode.PARTIAL ? "rgba(34, 197, 94, 0.07)" : "var(--color-ec-bg-surface)",
                    border: riskManagement.take_profit_mode === TakeProfitMode.PARTIAL ? "1px solid var(--color-ec-profit)" : "0.5px solid var(--color-ec-border)",
                    color: riskManagement.take_profit_mode === TakeProfitMode.PARTIAL ? "var(--color-ec-text-high)" : "var(--color-ec-text-primary)",
                  }}
                >
                  Parciales (Partial)
                </button>
              </div>
            </div>

            {/* Inputs based on mode */}
            {riskManagement.take_profit_mode === TakeProfitMode.FULL ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "center", textAlign: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Valor del porcentaje</span>
                  <CustomTooltip
                    title="Take Profit fijo en %"
                    text="Define el porcentaje de beneficio objetivo. Cuando el precio alcance esta distancia de subida (o bajada si es Short) desde tu entrada, se cerrará la operación asegurando las ganancias."
                  />
                </div>
                <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.35 }}>Ejemplo: 6.0% de distancia de toma de ganancias con respecto al precio de entrada.</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "center" }}>
                  <div
                    style={{
                      backgroundColor: 'var(--color-ec-bg-sidebar)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '7px 14px',
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-primary)',
                      fontFamily: 'var(--color-ec-sans)',
                      height: '36px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      userSelect: 'none',
                    }}
                  >
                    %
                  </div>
                  <div className="relative" style={{ width: '120px' }}>
                    <input
                      type="number"
                      step="0.1"
                      value={riskManagement.take_profit.value}
                      onChange={(e) => setRiskManagement({
                        ...riskManagement,
                        take_profit: { ...riskManagement.take_profit, value: Number(e.target.value) }
                      })}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '7px 24px 7px 10px',
                        fontSize: 13,
                        fontWeight: 600,
                        color: 'var(--color-ec-text-primary)',
                        fontFamily: 'var(--color-ec-sans)',
                        outline: 'none',
                        width: '100%',
                        height: '36px',
                        textAlign: 'center',
                      }}
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Parciales de salida</span>
                  <CustomTooltip
                    title="Salidas Parciales"
                    text="Te permite cerrar una fracción de tu posición (ej: 50%) a un precio objetivo determinado, y el resto en otros niveles o al final del día (EOD)."
                  />
                </div>
                <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.35 }}>
                  Define múltiples niveles para salir de la operación por tramos. La suma del capital asignado debe ser exactamente 100%.
                </span>
                
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {riskManagement.partial_take_profits.map((partial, idx) => (
                    <div
                      key={idx}
                      style={{
                        backgroundColor: "var(--color-ec-bg-elevated)",
                        border: "0.5px solid var(--color-ec-border)",
                        borderRadius: 6,
                        padding: "8px 10px",
                        display: "flex",
                        flexDirection: "column",
                        gap: 8,
                        boxShadow: "0 1px 3px rgba(0, 0, 0, 0.15)",
                      }}
                    >
                      {/* Header */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontSize: 9.5, fontWeight: 800, color: "var(--color-ec-profit)" }}>
                          Parcial #{idx + 1}
                        </span>
                        {riskManagement.partial_take_profits.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removePartial(idx)}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              cursor: 'pointer',
                              padding: 2,
                              color: 'var(--color-ec-text-muted)',
                              transition: 'color 150ms ease',
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-ec-loss)'}
                            onMouseLeave={(e) => e.currentTarget.style.color = 'var(--color-ec-text-muted)'}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      {/* Body Controls */}
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {/* Target Distance */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                          <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-muted)" }}>Nivel Objetivo:</span>
                          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <select
                              value={partial.distance_pct === 'EOD' ? 'EOD' : 'PCT'}
                              onChange={(e) => {
                                if (e.target.value === 'EOD') {
                                  updatePartial(idx, 'distance_pct', 'EOD');
                                } else {
                                  updatePartial(idx, 'distance_pct', 3.0);
                                }
                              }}
                              style={{
                                backgroundColor: 'var(--color-ec-bg-surface)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 4,
                                padding: '4px 6px',
                                fontSize: 10,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                                cursor: 'pointer',
                              }}
                            >
                              <option value="PCT">% Distancia</option>
                              <option value="EOD">Fin del Día (EOD)</option>
                            </select>

                            {partial.distance_pct !== 'EOD' && (
                              <div style={{ position: "relative", width: 55 }}>
                                <input
                                  type="number"
                                  step="0.1"
                                  value={partial.distance_pct}
                                  onChange={(e) => updatePartial(idx, 'distance_pct', Number(e.target.value))}
                                  style={{
                                    width: '100%',
                                    backgroundColor: 'var(--color-ec-bg-surface)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 4,
                                    padding: '4px 14px 4px 4px',
                                    fontSize: 10,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-text-primary)',
                                    outline: 'none',
                                    textAlign: 'right',
                                    boxSizing: 'border-box',
                                  }}
                                />
                                <span style={{
                                  position: "absolute",
                                  right: 4,
                                  top: "50%",
                                  transform: "translateY(-50%)",
                                  fontSize: 8,
                                  fontWeight: "bold",
                                  color: "var(--color-ec-text-muted)",
                                  pointerEvents: "none",
                                }}>%</span>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Capital Slider */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>Capital a Retirar:</span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, justifyContent: 'flex-end', maxWidth: '65%' }}>
                            <input
                              type="range"
                              min="1"
                              max="100"
                              value={partial.capital_pct}
                              onChange={(e) => updatePartial(idx, 'capital_pct', Number(e.target.value))}
                              style={{
                                backgroundColor: 'rgba(255, 255, 255, 0.12)',
                                accentColor: 'var(--color-ec-profit)',
                                outline: 'none',
                                height: '4px',
                                flex: 1,
                                minWidth: '40px',
                                cursor: 'pointer',
                                borderRadius: '2px',
                                appearance: 'none',
                              }}
                            />
                            <span style={{
                              fontSize: 9.5,
                              fontWeight: 800,
                              color: 'var(--color-ec-text-primary)',
                              width: 32,
                              textAlign: 'right',
                              flexShrink: 0
                            }}>
                              {partial.capital_pct}%
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                <button
                  type="button"
                  onClick={addPartial}
                  style={{
                    width: '100%',
                    padding: '6px 0',
                    border: '0.5px dashed var(--color-ec-border)',
                    borderRadius: 5,
                    fontSize: 9,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: 'var(--color-ec-text-muted)',
                    backgroundColor: 'transparent',
                    cursor: 'pointer',
                    fontFamily: 'var(--color-ec-sans)',
                    transition: 'all 150ms ease',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 6,
                    marginTop: 4
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-profit)'; e.currentTarget.style.color = 'var(--color-ec-profit)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                >
                  <Plus className="w-3 h-3" />
                  <span>Añadir Salida Parcial</span>
                </button>

                {/* Capital total validation */}
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: 8,
                  borderRadius: 5,
                  border: `0.5px solid ${Math.abs(totalPartialCapital - 100) < 0.01 ? 'rgba(34, 197, 94, 0.2)' : 'rgba(216, 122, 61, 0.2)'}`,
                  backgroundColor: Math.abs(totalPartialCapital - 100) < 0.01 ? 'rgba(34, 197, 94, 0.04)' : 'rgba(216, 122, 61, 0.04)',
                  color: Math.abs(totalPartialCapital - 100) < 0.01 ? 'var(--color-ec-profit)' : 'var(--color-ec-copper-bright)',
                  fontSize: 9,
                  fontWeight: 600
                }}>
                  <Info className="w-3.5 h-3.5 shrink-0" />
                  <div>
                    Suma total asignada: <span style={{ textDecoration: "underline", fontWeight: 700 }}>{totalPartialCapital}%</span>
                    {Math.abs(totalPartialCapital - 100) > 0.01 && (
                      <span style={{ display: "block", fontSize: 8, opacity: 0.8, marginTop: 2 }}>Debe ser exactamente 100% para continuar.</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Local Preview Tag underneath inputs */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 8,
          padding: "8px 10px",
          backgroundColor: "var(--color-ec-bg-elevated)",
          borderRadius: 6,
          border: "0.5px solid var(--color-ec-border)"
        }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Configuración actual TP:</span>
          <span style={{
            fontSize: 9,
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 4,
            backgroundColor: isTpOn ? "rgba(34, 197, 94, 0.08)" : "rgba(255, 255, 255, 0.03)",
            color: isTpOn ? "var(--color-ec-profit)" : "var(--color-ec-text-muted)",
            border: isTpOn ? "0.5px solid rgba(34, 197, 94, 0.2)" : "0.5px solid rgba(255, 255, 255, 0.1)"
          }}>
            {!isTpOn
              ? "Desactivado"
              : riskManagement.take_profit_mode === TakeProfitMode.FULL
              ? `Take Profit: ${riskManagement.take_profit.value}%`
              : `Take Profit: ${riskManagement.partial_take_profits.length} parciales (Total ${totalPartialCapital}%)`}
          </span>
        </div>
      </div>
    );
  };

  const renderRiskSubStepTrailingStop = () => {
    const isTrailingActive = riskManagement.trailing_stop?.active === true;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }} className="animate-in fade-in duration-200">
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            Límite Dinámico (Trailing Stop)
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 12px 0",
            lineHeight: 1.5,
          }}>
            El **Trailing Stop** es un Stop Loss móvil que acompaña de manera automática el precio cuando este avanza a tu favor, protegiendo ganancias si se revierte.
          </p>
        </div>

        {/* Toggle Option */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          backgroundColor: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 6,
        }}>
          <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-primary)" }}>
            ¿Activar Trailing Stop?
          </span>
          <div className="flex items-center gap-2">
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              fontWeight: 700,
              color: 'var(--color-ec-text-muted)',
            }}>{isTrailingActive ? 'SÍ' : 'NO'}</span>
            <div
              className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${isTrailingActive ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
              onClick={() => setRiskManagement({
                ...riskManagement,
                trailing_stop: { ...riskManagement.trailing_stop, active: !isTrailingActive }
              })}
            >
              <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${isTrailingActive ? 'left-4.5' : 'left-0.5'}`}></div>
            </div>
          </div>
        </div>

        {/* Form Inputs if Trailing Stop is Active */}
        {isTrailingActive && (
          <div 
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              padding: 14,
              backgroundColor: "rgba(255, 255, 255, 0.01)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 6,
            }}
            className="animate-in fade-in duration-200"
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "center", textAlign: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-ec-text-secondary)" }}>Distancia de activación (Trailing buffer %)</span>
                <CustomTooltip
                  title="Distancia del Trailing Stop"
                  text="El Stop Loss dinámico seguirá al precio a esta distancia porcentual fija. Si el precio retrocede esta cantidad desde su punto más alto, se ejecutará el cierre."
                />
              </div>
              <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)", lineHeight: 1.35 }}>
                Especifica la distancia máxima permitida en % que el precio puede retroceder antes de activar el Stop Loss.
              </span>
              <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "center", marginTop: 4 }}>
                <div className="relative" style={{ width: '120px' }}>
                  <input
                    type="number"
                    step="0.1"
                    value={riskManagement.trailing_stop.buffer_pct}
                    onChange={(e) => setRiskManagement({
                      ...riskManagement,
                      trailing_stop: { ...riskManagement.trailing_stop, buffer_pct: Number(e.target.value) }
                    })}
                    style={{
                      backgroundColor: 'var(--color-ec-bg-sidebar)',
                      border: '0.5px solid var(--color-ec-border)',
                      borderRadius: 5,
                      padding: '7px 24px 7px 10px',
                      fontSize: 13,
                      fontWeight: 600,
                      color: 'var(--color-ec-text-primary)',
                      fontFamily: 'var(--color-ec-sans)',
                      outline: 'none',
                      width: '100%',
                      height: '36px',
                      textAlign: 'center',
                    }}
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Local Preview Tag underneath inputs */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 8,
          padding: "8px 10px",
          backgroundColor: "var(--color-ec-bg-elevated)",
          borderRadius: 6,
          border: "0.5px solid var(--color-ec-border)"
        }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Configuración actual Trailing:</span>
          <span style={{
            fontSize: 9,
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 4,
            backgroundColor: isTrailingActive ? "rgba(216, 122, 61, 0.08)" : "rgba(255, 255, 255, 0.03)",
            color: isTrailingActive ? "var(--color-ec-copper-bright)" : "var(--color-ec-text-muted)",
            border: isTrailingActive ? "0.5px solid rgba(216, 122, 61, 0.2)" : "0.5px solid rgba(255, 255, 255, 0.1)"
          }}>
            {!isTrailingActive ? "Desactivado" : `Trailing Stop: ${riskManagement.trailing_stop.buffer_pct}%`}
          </span>
        </div>
      </div>
    );
  };

  const renderRiskSubStepReentries = () => {
    const isReentriesAllowed = riskManagement.accept_reentries === true;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }} className="animate-in fade-in duration-200">
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            Permitir Reentradas (Re-entries)
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 12px 0",
            lineHeight: 1.5,
          }}>
            Determina si el algoritmo de backtesting puede abrir una nueva posición en el mismo día si las condiciones de entrada vuelven a cumplirse tras haberse cerrado una posición previa.
          </p>
        </div>

        {/* Toggle Option */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          backgroundColor: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 6,
        }}>
          <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-primary)" }}>
            ¿Permitir reentradas en la misma sesión?
          </span>
          <div className="flex items-center gap-2">
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              fontWeight: 700,
              color: 'var(--color-ec-text-muted)',
            }}>{isReentriesAllowed ? 'SÍ' : 'NO'}</span>
            <div
              className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${isReentriesAllowed ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
              onClick={() => setRiskManagement({
                ...riskManagement,
                accept_reentries: !isReentriesAllowed,
                max_reentries: !isReentriesAllowed ? -1 : 0
              })}
            >
              <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${isReentriesAllowed ? 'left-4.5' : 'left-0.5'}`}></div>
            </div>
          </div>
        </div>

        {/* Sutil selector de cantidad de reentradas si están activas */}
        {isReentriesAllowed && (
          <div 
            className="flex items-center justify-between animate-in fade-in slide-in-from-top-1 duration-200"
            style={{
              borderTop: "0.5px dotted var(--color-ec-border)",
              marginTop: "14px",
              paddingTop: "14px",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-primary)" }}>
                Tipo de Reentradas
              </span>
              <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 9, color: "var(--color-ec-text-muted)" }}>
                Límite de reentradas adicionales permitidas
              </span>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={riskManagement.max_reentries === undefined || riskManagement.max_reentries === -1 ? 'infinite' : 'limited'}
                onChange={(e) => {
                  if (e.target.value === 'infinite') {
                    setRiskManagement({ ...riskManagement, max_reentries: -1 });
                  } else {
                    setRiskManagement({ ...riskManagement, max_reentries: 2 });
                  }
                }}
                style={{
                  backgroundColor: 'var(--color-ec-bg-sidebar)',
                  border: '0.5px solid var(--color-ec-border)',
                  borderRadius: 5,
                  padding: '5px 8px',
                  fontSize: 11,
                  fontWeight: 500,
                  color: 'var(--color-ec-text-primary)',
                  fontFamily: 'var(--color-ec-sans)',
                  outline: 'none',
                  cursor: 'pointer',
                  height: '30px',
                }}
              >
                <option value="infinite">Infinitas</option>
                <option value="limited">Limitadas</option>
              </select>
              {riskManagement.max_reentries !== undefined && riskManagement.max_reentries >= 0 && (
                <input
                  type="number"
                  min="0"
                  value={riskManagement.max_reentries}
                  onChange={(e) => {
                    const val = Math.max(0, parseInt(e.target.value) || 0);
                    setRiskManagement({ ...riskManagement, max_reentries: val });
                  }}
                  style={{
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                    padding: '5px 8px',
                    fontSize: 11,
                    fontWeight: 600,
                    color: 'var(--color-ec-text-primary)',
                    fontFamily: 'var(--color-ec-sans)',
                    outline: 'none',
                    width: '50px',
                    height: '30px',
                    textAlign: 'center',
                  }}
                />
              )}
            </div>
          </div>
        )}

        {/* Informative text box */}
        <div style={{
          padding: "10px 12px",
          backgroundColor: "rgba(255, 255, 255, 0.02)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 6,
          fontFamily: "var(--color-ec-sans)",
          fontSize: 9,
          color: "var(--color-ec-text-secondary)",
          lineHeight: 1.4,
        }}>
          <strong>SÍ:</strong> Permite múltiples operaciones por día si el mercado vuelve a dar una señal clara.<br />
          <strong>NO:</strong> Solo realiza una única operación al día, bloqueando cualquier otra entrada hasta la siguiente jornada.
        </div>

        {/* Local Preview Tag underneath inputs */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 8,
          padding: "8px 10px",
          backgroundColor: "var(--color-ec-bg-elevated)",
          borderRadius: 6,
          border: "0.5px solid var(--color-ec-border)"
        }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Configuración actual Reentradas:</span>
          <span style={{
            fontSize: 9,
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 4,
            backgroundColor: isReentriesAllowed ? "rgba(216, 122, 61, 0.08)" : "rgba(255, 255, 255, 0.03)",
            color: isReentriesAllowed ? "var(--color-ec-copper-bright)" : "var(--color-ec-text-muted)",
            border: isReentriesAllowed ? "0.5px solid rgba(216, 122, 61, 0.2)" : "0.5px solid rgba(255, 255, 255, 0.1)"
          }}>
            {isReentriesAllowed 
              ? (riskManagement.max_reentries === undefined || riskManagement.max_reentries === -1 ? "Reentradas: Infinitas" : `Reentradas: Máx ${riskManagement.max_reentries}`)
              : "Reentradas: Desactivado"
            }
          </span>
        </div>
      </div>
    );
  };

  /* ── Unified full-text tag list for Strategy Summary ── */
  const allTagsUnified = useMemo(() => {
    const list: { label: string; stepName: string }[] = [];
    
    // 0. Universo
    if (customUniverse) {
      list.push({
        label: `Personalizado: Desde ${universeFilters.date_from || '?'} hasta ${universeFilters.date_to || '?'}`,
        stepName: "Universo"
      });
      (universeFilters.rules || []).forEach((r: any) => {
        const friendlyName = r.metric.replace(/_/g, " ").toLowerCase();
        const friendlyOp = r.operator === "GREATER_THAN_OR_EQUAL" ? ">=" : r.operator === "LESS_THAN_OR_EQUAL" ? "<=" : r.operator === "GREATER_THAN" ? ">" : "<";
        let friendlyVal = r.value;
        const numVal = parseFloat(r.value);
        if (!isNaN(numVal)) {
          if (r.metric.toLowerCase().includes('volume')) {
            friendlyVal = `${(numVal / 1000000).toFixed(1).replace(/\.0$/, '')}M`;
          }
        }
        list.push({
          label: `${friendlyName} ${friendlyOp} ${friendlyVal}`,
          stepName: "Universo"
        });
      });
    } else if (selectedDataset) {
      const currentDs = datasets.find(d => d.id === selectedDataset);
      list.push({
        label: `Dataset: ${currentDs ? currentDs.name : (loadingDatasets ? "Cargando..." : selectedDataset)}`,
        stepName: "Universo"
      });
    }

    // 1. Bias
    if (bias) {
      list.push({
        label: bias === "long" ? "▲ Long (Compra)" : "▼ Short (Venta)",
        stepName: "Dirección"
      });
    }
    
    // 2. Día de Aplicación & Preconditions
    const dayLabel = applyDay === "gap_day" ? "Gap Day" : applyDay === "gap_1_day" ? "Gap +1 Day" : "Gap +2 Day";
    list.push({
      label: `Aplicar en: ${dayLabel}`,
      stepName: "Día de Aplicación"
    });
    postgapPreconditions.forEach((cond) => {
      list.push({
        label: formatPrecondition(cond),
        stepName: "Día de Aplicación"
      });
    });

    // Sesión de Aplicación
    const sessionNames: Record<string, string> = {
      pre: "Pre-Market (04:00 - 09:30)",
      rth: "Regular Hours (09:30 - 16:00)",
      post: "After-Market (16:00 - 20:00)",
      custom: `Custom (${wizardCustomStartTime} - ${wizardCustomEndTime})`
    };
    if (wizardMarketSessions && wizardMarketSessions.length > 0) {
      const activeLabels = wizardMarketSessions.map(id => sessionNames[id] || id);
      list.push({
        label: `Sesión: ${activeLabels.join(", ")}`,
        stepName: "Sesión de Aplicación"
      });
    } else {
      list.push({
        label: "Sesión: Ninguna",
        stepName: "Sesión de Aplicación"
      });
    }
    
    // 3. Lógica de Entrada
    const entryConds = getConditionStrings(entryLogic.root_condition, entryLogic.timeframe);
    entryConds.forEach((c) => {
      list.push({
        label: c,
        stepName: "Lógica de Entrada"
      });
    });
    (entryLogic.entry_time_windows || []).forEach((w) => {
      list.push({
        label: `Hora: ${w.from_time} - ${w.to_time}`,
        stepName: "Lógica de Entrada"
      });
    });
    
    // 4. Lógica de Salida
    const exitConds = getConditionStrings(exitLogic.root_condition, exitLogic.timeframe);
    exitConds.forEach((c) => {
      list.push({
        label: c,
        stepName: "Lógica de Salida"
      });
    });
    
    // 5. Gestión de Riesgo
    // Stop Loss
    if (riskManagement.use_hard_stop === true) {
      const label = riskManagement.hard_stop.type === RiskType.PERCENTAGE
        ? `Stop Loss: ${riskManagement.hard_stop.value}%`
        : `Stop Loss: ${riskManagement.hard_stop.value} ${(riskManagement.hard_stop.operator === '<' || riskManagement.hard_stop.operator === '<=') ? '-' : '+'} ${riskManagement.hard_stop.offset_pct ?? 0}%`;
      list.push({
        label,
        stepName: "Gestión de Riesgo"
      });
    } else {
      list.push({
        label: "Stop Loss: Desactivado",
        stepName: "Gestión de Riesgo"
      });
    }
    
    // Take Profit
    if (riskManagement.use_take_profit === true) {
      if (riskManagement.take_profit_mode === "Full") {
        list.push({
          label: `Take Profit: ${riskManagement.take_profit.value}%`,
          stepName: "Gestión de Riesgo"
        });
      } else {
        const partials = riskManagement.partial_take_profits || [];
        partials.forEach((p, idx) => {
          const distStr = p.distance_pct === 'EOD' ? 'EOD' : `${p.distance_pct}%`;
          list.push({
            label: `TP Parcial ${idx + 1}: ${p.capital_pct}% a ${distStr}`,
            stepName: "Gestión de Riesgo"
          });
        });
      }
    } else {
      list.push({
        label: "Take Profit: Desactivado",
        stepName: "Gestión de Riesgo"
      });
    }
    
    // Trailing Stop
    if (riskManagement.trailing_stop?.active) {
      list.push({
        label: `Trailing: ${riskManagement.trailing_stop.buffer_pct}%`,
        stepName: "Gestión de Riesgo"
      });
    } else {
      list.push({
        label: "Trailing Stop: Desactivado",
        stepName: "Gestión de Riesgo"
      });
    }
    
    // Reentries
    list.push({
      label: riskManagement.accept_reentries === true 
        ? (riskManagement.max_reentries === undefined || riskManagement.max_reentries === -1 ? "Reentradas: Infinitas" : `Reentradas: Máx ${riskManagement.max_reentries}`)
        : "Reentradas: Bloqueadas",
      stepName: "Gestión de Riesgo"
    });
    
    return list;
  }, [
    bias,
    applyDay,
    postgapPreconditions,
    entryLogic,
    exitLogic,
    riskManagement,
    customUniverse,
    universeFilters,
    selectedDataset,
    datasets,
    wizardMarketSessions,
    wizardCustomStartTime,
    wizardCustomEndTime,
    loadingDatasets
  ]);

  // Step 6: Resumen de estrategia
  const renderSummaryStep = () => {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }} className="animate-in fade-in duration-300">
        <div>
          <h3 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 4px 0",
            letterSpacing: "-0.2px",
          }}>
            Resumen de tu Estrategia
          </h3>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 10,
            color: "var(--color-ec-text-muted)",
            margin: "0 0 12px 0",
            lineHeight: 1.5,
          }}>
            Revisa la configuración completa de tu estrategia antes de ejecutar la simulación de backtesting.
          </p>
        </div>

        {/* Grouped tags by category in a 2-column layout */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          paddingRight: 6,
        }}>
          {(() => {
            const categories: Record<string, string[]> = {
              "Universo": [],
              "Dirección": [],
              "Día de Aplicación": [],
              "Sesión de Aplicación": [],
              "Lógica de Entrada": [],
              "Lógica de Salida": [],
              "Gestión de Riesgo": [],
            };

            allTagsUnified.forEach((tag) => {
              if (categories[tag.stepName]) {
                categories[tag.stepName].push(tag.label);
              }
            });

            const activeCategories = Object.entries(categories).filter(([_, tags]) => tags.length > 0);

            return activeCategories.map(([categoryName, tags], idx) => (
              <div
                key={categoryName}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  padding: "10px 12px",
                  borderRadius: 6,
                  backgroundColor: "rgba(216, 122, 61, 0.03)",
                  border: "0.5px solid rgba(216, 122, 61, 0.15)",
                  fontFamily: "var(--color-ec-sans)",
                  animation: "wizTagSlideIn 200ms ease-out",
                  animationDelay: `${idx * 40}ms`,
                  animationFillMode: "both",
                  gridColumn: (categoryName === "Gestión de Riesgo" || categoryName === "Lógica de Entrada") ? "span 2" : "auto",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{
                    fontSize: 7.5,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    color: "var(--color-ec-copper)",
                    letterSpacing: "0.03em"
                  }}>
                    {categoryName}
                  </span>
                  <div style={{
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    backgroundColor: "var(--color-ec-copper)",
                  }} />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {tags.map((tagText, tIdx) => (
                    <div key={tIdx} style={{ display: "flex", alignItems: "flex-start", gap: 5 }}>
                      <span style={{ color: "var(--color-ec-copper)", fontSize: 9.5, lineHeight: 1.2 }}>•</span>
                      <span style={{
                        fontSize: 9.5,
                        fontWeight: 600,
                        color: "var(--color-ec-text-primary)",
                        lineHeight: 1.2
                      }}>
                        {tagText}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ));
          })()}
        </div>
      </div>
    );
  };

  // Step 5: Gestión de riesgo (Risk Management) - Router
  const renderRiskStep = () => {
    switch (wizardRiskStep) {
      case 0:
        return renderRiskSubStepStopLoss();
      case 1:
        return renderRiskSubStepTakeProfit();
      case 2:
        return renderRiskSubStepTrailingStop();
      case 3:
        return renderRiskSubStepReentries();
      default:
        return null;
    }
  };

  // StepRailItem component declaration removed (now inlined directly in step rail mapping to prevent React recreation/remounting click bugs)


  /* ── Dynamic full-text tag generators grouped by category ── */
  /* ── Dynamic full-text tag generators grouped by category ── */
  const directionTags = useMemo(() => {
    const summaryStepIdx = STEPS.findIndex(s => s.key === "summary");
    if (!bias || currentStep === summaryStepIdx) return [];
    return [{
      label: bias === "long" ? "▲ Long" : "▼ Short",
      color: "var(--color-ec-copper)",
      onRemove: () => {
        setBias(null);
        setCompletedSteps(prev => {
          const next = new Set(prev);
          next.delete(0);
          return next;
        });
      }
    }];
  }, [bias, currentStep]);

  const applyDayTags = useMemo(() => {
    const summaryStepIdx = STEPS.findIndex(s => s.key === "summary");
    if (currentStep === summaryStepIdx) return [];
    const list = [];
    const dayLabel = applyDay === "gap_day" ? "Gap Day" : applyDay === "gap_1_day" ? "Gap +1 Day" : "Gap +2 Day";
    list.push({
      label: `Aplicar en: ${dayLabel}`,
      color: "var(--color-ec-copper)",
      onRemove: () => {
        setApplyDay("gap_day");
        setPostgapPreconditions([]);
      }
    });
    
    postgapPreconditions.forEach((cond, idx) => {
      list.push({
        label: formatPrecondition(cond),
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setPostgapPreconditions(postgapPreconditions.filter((_, i) => i !== idx));
        }
      });
    });
    return list;
  }, [applyDay, postgapPreconditions, currentStep]);

  const marketSessionsTags = useMemo(() => {
    const summaryStepIdx = STEPS.findIndex(s => s.key === "summary");
    const marketSessionsStepIdx = STEPS.findIndex(s => s.key === "market_sessions");
    if (currentStep === summaryStepIdx || currentStep < marketSessionsStepIdx) return [];
    
    const list: { label: string; color: string; onRemove: () => void }[] = [];
    const sessionNames: Record<string, string> = {
      pre: "Pre-Market",
      rth: "Regular Hours",
      post: "After-Market",
      custom: `Custom (${wizardCustomStartTime}-${wizardCustomEndTime})`
    };
    
    wizardMarketSessions.forEach((s) => {
      list.push({
        label: sessionNames[s] || s,
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setWizardMarketSessions(prev => {
            const next = prev.filter(x => x !== s);
            setCompletedSteps((completed) => {
              const nextSet = new Set(completed);
              const idx = STEPS.findIndex(st => st.key === "market_sessions");
              if (next.length > 0) {
                nextSet.add(idx);
              } else {
                nextSet.delete(idx);
              }
              return nextSet;
            });
            return next;
          });
        }
      });
    });
    return list;
  }, [wizardMarketSessions, wizardCustomStartTime, wizardCustomEndTime, currentStep]);

  const entryTags = useMemo(() => {
    const summaryStepIdx = STEPS.findIndex(s => s.key === "summary");
    const entryStepIdx = STEPS.findIndex(s => s.key === "entry");
    if (currentStep === summaryStepIdx || currentStep < entryStepIdx) {
      return [];
    }
    const list: { label: string; color: string; onRemove: () => void }[] = [];
    
    // Condition tags with callback
    const condTags = getConditionTags(
      entryLogic.root_condition,
      entryLogic.timeframe,
      (newRoot) => setEntryLogic({ ...entryLogic, root_condition: newRoot })
    );
    condTags.forEach(tag => {
      list.push({ ...tag, color: "var(--color-ec-copper)" });
    });

    // Time window tags
    const windows = entryLogic.entry_time_windows || [];
    windows.forEach((w, wIdx) => {
      list.push({
        label: `Hora: ${w.from_time} - ${w.to_time}`,
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setEntryLogic({
            ...entryLogic,
            entry_time_windows: windows.filter((_, i) => i !== wIdx)
          });
        }
      });
    });
    return list;
  }, [entryLogic, currentStep]);

  const exitTags = useMemo(() => {
    const summaryStepIdx = STEPS.findIndex(s => s.key === "summary");
    if (currentStep === summaryStepIdx) return [];
    return getConditionTags(
      exitLogic.root_condition,
      exitLogic.timeframe,
      (newRoot) => setExitLogic({ ...exitLogic, root_condition: newRoot })
    ).map(tag => ({ ...tag, color: "var(--color-ec-copper)" }));
  }, [exitLogic, currentStep]);

  const riskTags = useMemo(() => {
    const summaryStepIdx = STEPS.findIndex(s => s.key === "summary");
    const riskStepIdx = STEPS.findIndex(s => s.key === "risk");
    if (currentStep === summaryStepIdx || currentStep < riskStepIdx || (wizardRiskStep < 3 && !completedSteps.has(riskStepIdx))) {
      return [];
    }
    const list = [];
    
    // Stop Loss
    if (riskManagement.use_hard_stop === true) {
      const label = riskManagement.hard_stop.type === RiskType.PERCENTAGE
        ? `Stop Loss: ${riskManagement.hard_stop.value}%`
        : `Stop Loss: ${riskManagement.hard_stop.value} ${(riskManagement.hard_stop.operator === '<' || riskManagement.hard_stop.operator === '<=') ? '-' : '+'} ${riskManagement.hard_stop.offset_pct ?? 0}%`;
      list.push({
        label,
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setRiskManagement({
            ...riskManagement,
            use_hard_stop: false
          });
        }
      });
      if (riskManagement.size_by_sl) {
        list.push({
          label: `Calcular Shares por SL: Sí`,
          color: "var(--color-ec-copper)",
          onRemove: () => {
            setRiskManagement({
              ...riskManagement,
              size_by_sl: false
            });
          }
        });
      }
    } else {
      list.push({
        label: `Stop Loss: Desactivado`,
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setRiskManagement({
            ...riskManagement,
            use_hard_stop: true
          });
        }
      });
    }

    // Take Profit
    if (riskManagement.use_take_profit === true) {
      if (riskManagement.take_profit_mode === "Full") {
        list.push({
          label: `Take Profit: ${riskManagement.take_profit.value}%`,
          color: "var(--color-ec-copper)",
          onRemove: () => {
            setRiskManagement({
              ...riskManagement,
              use_take_profit: false
            });
          }
        });
      } else {
        const partials = riskManagement.partial_take_profits || [];
        partials.forEach((p, idx) => {
          const distStr = p.distance_pct === 'EOD' ? 'EOD' : `${p.distance_pct}%`;
          list.push({
            label: `TP Parcial ${idx + 1}: ${p.capital_pct}% a ${distStr}`,
            color: "var(--color-ec-copper)",
            onRemove: () => {
              const newPartials = partials.filter((_, i) => i !== idx);
              setRiskManagement({
                ...riskManagement,
                partial_take_profits: newPartials,
                use_take_profit: newPartials.length > 0 ? riskManagement.use_take_profit : false
              });
            }
          });
        });
      }
    } else {
      list.push({
        label: `Take Profit: Desactivado`,
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setRiskManagement({
            ...riskManagement,
            use_take_profit: true
          });
        }
      });
    }

    // Trailing Stop
    if (riskManagement.trailing_stop?.active) {
      list.push({
        label: `Trailing: ${riskManagement.trailing_stop.buffer_pct}% (${riskManagement.trailing_stop.type})`,
        color: "var(--color-ec-copper)",
        onRemove: () => {
          setRiskManagement({
            ...riskManagement,
            trailing_stop: {
              ...riskManagement.trailing_stop,
              active: false
            }
          });
        }
      });
    }

    // Re-entries
    list.push({
      label: riskManagement.accept_reentries === true 
        ? (riskManagement.max_reentries === undefined || riskManagement.max_reentries === -1 ? "Reentradas: Infinitas" : `Reentradas: Máx ${riskManagement.max_reentries}`)
        : "Reentradas: Bloqueadas",
      color: "var(--color-ec-copper)",
      onRemove: () => {
        setRiskManagement({
          ...riskManagement,
          accept_reentries: !riskManagement.accept_reentries,
          max_reentries: !riskManagement.accept_reentries ? -1 : 0
        });
      }
    });

    return list;
  }, [riskManagement, currentStep, wizardRiskStep, completedSteps]);

  // Sidebar sections headers and tags layout styles
  const sectionHeaderStyle: React.CSSProperties = {
    fontFamily: "var(--color-ec-sans)",
    fontSize: 8,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "var(--color-ec-text-muted)",
    marginBottom: 4,
    display: "block",
  };

  // Render a tag with a custom separator and an X delete button with colored background
  const renderSummaryTag = (
    label: string,
    color: string,
    onRemove?: () => void
  ) => {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 6,
          padding: "4px 6px 4px 8px",
          borderRadius: 4,
          backgroundColor: `color-mix(in srgb, ${color} 8%, transparent)`,
          border: `0.5px solid ${color}`,
          fontFamily: "var(--color-ec-sans)",
          fontSize: 9,
          fontWeight: 600,
          color: color,
          lineHeight: 1.3,
          whiteSpace: "normal",
          wordBreak: "break-word",
          animation: "wizTagSlideIn 200ms ease-out",
        }}
      >
        <span style={{ flex: 1 }}>{label}</span>
        {onRemove && (
          <>
            <div
              style={{
                width: 1,
                alignSelf: "stretch",
                backgroundColor: `color-mix(in srgb, ${color} 25%, transparent)`,
              }}
            />
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 14,
                height: 14,
                borderRadius: 2,
                border: "none",
                backgroundColor: `color-mix(in srgb, ${color} 18%, transparent)`,
                color: color,
                cursor: "pointer",
                padding: 0,
                fontSize: 10,
                fontWeight: 700,
                lineHeight: 1,
                transition: "all 150ms ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = `color-mix(in srgb, ${color} 35%, transparent)`;
                e.currentTarget.style.color = "var(--color-ec-text-high)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = `color-mix(in srgb, ${color} 18%, transparent)`;
                e.currentTarget.style.color = color;
              }}
            >
              ×
            </button>
          </>
        )}
      </div>
    );
  };

  const isContinueDisabled = (() => {
    const stepKey = STEPS[currentStep]?.key;
    if (stepKey === "universo") {
      return !customUniverse && !selectedDataset;
    }
    if (stepKey === "bias") {
      return bias === null;
    }
    return false;
  })();

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      overflow: "hidden",
    }}>
      <style>{`
        @keyframes wizCheckPop {
          0% { transform: scale(0.95); opacity: 0; }
          100% { transform: scale(1); opacity: 1; }
        }
        @keyframes wizTagSlideIn {
          0% { opacity: 0; transform: scale(0.92); }
          100% { opacity: 1; transform: scale(1); }
        }
      `}</style>

      {/* Header */}
      <div style={{
        padding: "12px 16px",
        borderBottom: "0.5px solid var(--color-ec-border)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        backgroundColor: "var(--color-ec-bg-base)",
        flexShrink: 0,
      }}>
        <button
          onClick={onBack}
          style={{
            background: "none", border: "none",
            color: "var(--color-ec-text-muted)",
            cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px",
          }}
        >←</button>
        <span style={{
          fontFamily: "var(--color-ec-serif)",
          fontSize: 14, fontWeight: 600,
          color: "var(--color-ec-text-high)",
          letterSpacing: "-0.2px",
        }}>Config. guiada</span>
      </div>

      {/* Progress bar */}
      <div style={{
        height: 2,
        backgroundColor: "var(--color-ec-bg-elevated)",
        flexShrink: 0, overflow: "hidden",
      }}>
        <div style={{
          height: "100%",
           width: `${((currentStep) / (STEPS.length - 1)) * 100}%`,
          background: "linear-gradient(90deg, var(--color-ec-copper), rgba(216, 122, 61, 0.6))",
          transition: "width 400ms cubic-bezier(0.22, 1, 0.36, 1)",
          borderRadius: "0 2px 2px 0",
        }} />
      </div>

      {/* Body: Rail + Content */}
      <div style={{
        flex: 1,
        display: "flex",
        overflow: "hidden",
        minHeight: 0,
      }}>
        {/* Left: Step Rail (width 190px for full formulas) */}
        <div style={{
          width: 190,
          flexShrink: 0,
          borderRight: "0.5px solid var(--color-ec-border)",
          display: "flex",
          flexDirection: "column",
          backgroundColor: "var(--color-ec-bg-base)",
          height: "100%",
          overflow: "hidden",
        }}>
          {/* Top Container: Steps Indicators */}
          <div style={{
            flexShrink: 0,
            padding: "14px 8px 8px 8px",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}>
            {STEPS.map((step, idx) => {
              const isActive = idx === currentStep;
              const isCompleted = completedSteps.has(idx) && idx < currentStep;
              const isFuture = idx > currentStep;

              return (
                <div key={step.key} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => {
                      setCurrentStep(idx);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "6px 8px",
                      borderRadius: 6,
                      background: isActive ? "rgba(216, 122, 61, 0.06)" : "transparent",
                      border: "none",
                      cursor: "pointer",
                      opacity: isFuture ? 0.45 : 1,
                      transition: "all 200ms ease",
                      width: "100%",
                      textAlign: "left",
                      position: "relative",
                      zIndex: 2,
                    }}
                  >
                    <div style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                      backgroundColor: isCompleted
                        ? "var(--color-ec-copper)"
                        : isActive
                          ? "rgba(216, 122, 61, 0.15)"
                          : "transparent",
                      border: isCompleted
                        ? "none"
                        : isActive
                          ? "1.5px solid var(--color-ec-copper)"
                          : "1px solid var(--color-ec-border)",
                      transition: "all 250ms ease",
                    }}>
                      {isCompleted ? (
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                          stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <span style={{
                          fontFamily: "var(--color-ec-sans)",
                          fontSize: 8,
                          fontWeight: 700,
                          color: isActive ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)",
                        }}>
                          {idx + 1}
                        </span>
                      )}
                    </div>
                    <span style={{
                      fontFamily: "var(--color-ec-sans)",
                      fontSize: 10,
                      fontWeight: isActive ? 700 : 500,
                      color: isActive
                        ? "var(--color-ec-copper)"
                        : isCompleted
                          ? "var(--color-ec-text-high)"
                          : "var(--color-ec-text-muted)",
                      transition: "color 200ms ease",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}>
                      {step.label}
                    </span>
                  </button>

                  {idx < STEPS.length - 1 && (
                    <div style={{
                      position: "absolute",
                      left: 18,
                      top: 28,
                      width: 1,
                      height: 10,
                      backgroundColor: isCompleted
                        ? "var(--color-ec-copper)"
                        : "var(--color-ec-border)",
                      transition: "background-color 300ms ease",
                      zIndex: 1,
                    }} />
                  )}
                </div>
              );
            })}
          </div>

          {/* Divider */}
          <div style={{
            height: "0.5px",
            backgroundColor: "var(--color-ec-border)",
            width: "100%",
          }} />

          {/* Bottom 2/3 Container: Summary Tags grouped by category */}
          <div style={{
            flex: 1,
            padding: "12px 10px",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 12,
            scrollbarWidth: "none",
          }}>
            {/* Dirección */}
            {directionTags.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={sectionHeaderStyle}>Dirección</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {directionTags.map((tag, idx) => (
                    <Fragment key={idx}>
                      {renderSummaryTag(tag.label, tag.color, tag.onRemove)}
                    </Fragment>
                  ))}
                </div>
              </div>
            )}

            {/* Día de Aplicación */}
            {applyDayTags.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={sectionHeaderStyle}>Día de Aplicación</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {applyDayTags.map((tag, idx) => (
                    <Fragment key={idx}>
                      {renderSummaryTag(tag.label, tag.color, tag.onRemove)}
                    </Fragment>
                  ))}
                </div>
              </div>
            )}

            {/* Sesión de Aplicación */}
            {marketSessionsTags.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={sectionHeaderStyle}>Sesión de Aplicación</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {marketSessionsTags.map((tag, idx) => (
                    <Fragment key={idx}>
                      {renderSummaryTag(tag.label, tag.color, tag.onRemove)}
                    </Fragment>
                  ))}
                </div>
              </div>
            )}

            {/* Lógica de Entrada */}
            {entryTags.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={sectionHeaderStyle}>Lógica de Entrada</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {entryTags.map((tag, idx) => (
                    <Fragment key={idx}>
                      {renderSummaryTag(tag.label, tag.color, tag.onRemove)}
                    </Fragment>
                  ))}
                </div>
              </div>
            )}

            {/* Lógica de Salida */}
            {exitTags.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={sectionHeaderStyle}>Lógica de Salida</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {exitTags.map((tag, idx) => (
                    <Fragment key={idx}>
                      {renderSummaryTag(tag.label, tag.color, tag.onRemove)}
                    </Fragment>
                  ))}
                </div>
              </div>
            )}

            {/* Gestión de Riesgo */}
            {riskTags.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={sectionHeaderStyle}>Gestión de Riesgo</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {riskTags.map((tag, idx) => (
                    <Fragment key={idx}>
                      {renderSummaryTag(tag.label, tag.color, tag.onRemove)}
                    </Fragment>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div style={{
          flex: 1,
          overflow: "hidden",
          padding: "20px 22px 20px",
          display: "flex",
          flexDirection: "column",
          justifyContent: STEPS[currentStep]?.key === "summary" ? "flex-start" : "space-between",
        }}>
          <div style={{
            flex: STEPS[currentStep]?.key === "summary" ? "0 1 auto" : 1,
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
            scrollbarWidth: "none",
            minHeight: 0
          }}>
            <div style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 8,
              fontWeight: 700,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "var(--color-ec-copper)",
              marginBottom: 10,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              width: "100%"
            }}>
              <span>
                Paso {currentStep + 1} de {STEPS.length}
                {STEPS[currentStep]?.key === "risk" && ` (Riesgo: ${wizardRiskStep + 1} de 4)`}
              </span>
              {STEPS[currentStep]?.key === "risk" && (
                <div style={{ display: "flex", gap: 4 }}>
                  {Array.from({ length: 4 }).map((_, idx) => (
                    <div
                      key={idx}
                      style={{
                        width: 5,
                        height: 5,
                        borderRadius: "50%",
                        backgroundColor: idx === wizardRiskStep 
                          ? "var(--color-ec-copper)" 
                          : idx < wizardRiskStep 
                          ? "rgba(216, 122, 61, 0.45)" 
                          : "var(--color-ec-border)",
                        transition: "all 150ms ease"
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
 
            {renderStep()}
          </div>
 
          {/* Navigation Footer */}
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: STEPS[currentStep]?.key === "summary" ? 8 : 32,
            paddingTop: 16,
            borderTop: "0.5px solid var(--color-ec-border)",
            flexShrink: 0,
          }}>
            {currentStep > 0 ? (
              <button
                onClick={() => {
                  if (STEPS[currentStep]?.key === "risk" && wizardRiskStep > 0) {
                    setWizardRiskStep((prev) => prev - 1);
                  } else {
                    setCurrentStep((prev) => prev - 1);
                  }
                }}
                style={{
                  backgroundColor: "transparent",
                  border: "0.5px solid var(--color-ec-border)",
                  borderRadius: 5,
                  padding: "6px 12px",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: "var(--color-ec-text-muted)",
                  cursor: "pointer",
                  transition: "all 150ms ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = "var(--color-ec-text-primary)";
                  e.currentTarget.style.borderColor = "var(--color-ec-text-primary)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = "var(--color-ec-text-muted)";
                  e.currentTarget.style.borderColor = "var(--color-ec-border)";
                }}
              >
                Atrás
              </button>
            ) : (
              <div />
            )}
 
            {currentStep < STEPS.length - 1 ? (
              (STEPS[currentStep]?.key === "risk" && wizardRiskStep === 3) ? (
                <button
                  onClick={() => {
                    setCompletedSteps((prev) => new Set(prev).add(STEPS.findIndex(s => s.key === "risk")));
                    setCurrentStep(STEPS.findIndex(s => s.key === "summary"));
                  }}
                  style={{
                    backgroundColor: "var(--color-ec-copper)",
                    color: "var(--color-ec-copper-text)",
                    border: "none",
                    borderRadius: 5,
                    padding: "6px 16px",
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    cursor: "pointer",
                    transition: "all 150ms ease",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <span>Resumen</span>
                  <span>→</span>
                </button>
              ) : STEPS[currentStep]?.key === "risk" ? (
                <button
                  onClick={() => {
                    if (wizardRiskStep === 1 && riskManagement.use_take_profit === true && riskManagement.take_profit_mode === TakeProfitMode.PARTIAL) {
                      const totalPartialCapital = (riskManagement.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0);
                      if (Math.abs(totalPartialCapital - 100) > 0.01) {
                        alert("La suma del capital de los parciales de Take Profit debe ser exactamente 100% para continuar.");
                        return;
                      }
                    }
                    setWizardRiskStep((prev) => prev + 1);
                  }}
                  style={{
                    backgroundColor: "var(--color-ec-copper)",
                    color: "var(--color-ec-copper-text)",
                    border: "none",
                    borderRadius: 5,
                    padding: "6px 16px",
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    cursor: "pointer",
                    transition: "all 150ms ease",
                  }}
                >
                  Continuar
                </button>
              ) : (
                <button
                  onClick={() => {
                    setCompletedSteps((prev) => new Set(prev).add(currentStep));
                    setCurrentStep((prev) => prev + 1);
                  }}
                  disabled={isContinueDisabled}
                  style={{
                    backgroundColor: isContinueDisabled ? "var(--color-ec-bg-elevated)" : "var(--color-ec-copper)",
                    color: isContinueDisabled ? "var(--color-ec-text-muted)" : "var(--color-ec-copper-text)",
                    border: "none",
                    borderRadius: 5,
                    padding: "6px 16px",
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    cursor: isContinueDisabled ? "not-allowed" : "pointer",
                    transition: "all 150ms ease",
                    opacity: isContinueDisabled ? 0.5 : 1,
                  }}
                >
                  Continuar
                </button>
              )
            ) : (
              <button
                onClick={handleRunBacktest}
                style={{
                  backgroundColor: "var(--color-ec-copper)",
                  color: "var(--color-ec-copper-text)",
                  border: "none",
                  borderRadius: 5,
                  padding: "6px 16px",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <Sparkles size={12} />
                Ejecutar Backtest
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
