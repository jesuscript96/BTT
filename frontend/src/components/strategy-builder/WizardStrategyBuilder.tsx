"use client";

import { useState, useEffect, useMemo, useRef, Fragment } from "react";
import type {
  EntryLogic as EntryLogicType,
  ExitLogic as ExitLogicType,
  RiskManagement as RiskManagementType,
  PostGapPrecondition,
  ConditionGroup,
} from "@/types/strategy";
import {
  initialEntryLogic,
  initialExitLogic,
  initialRiskManagement,
  RiskType,
} from "@/types/strategy";
import { EntryLogicBuilder } from "@/components/strategy-builder/EntryLogic";
import { ExitLogicBuilder } from "@/components/strategy-builder/ExitLogic";
import { RiskManagementComponent } from "@/components/strategy-builder/RiskManagement";
import { validateStrategyLogic } from "@/lib/strategyValidation";
import { INDICATOR_LABELS, COMPARATOR_LABELS } from "@/components/strategy-builder/ConditionBuilder";
import { Clock, Plus, Trash2, Info, HelpCircle, Sparkles } from "lucide-react";

export interface WizardDraft {
  id: string;
  name: string;
  bias: "long" | "short";
  apply_day?: "gap_day" | "gap_1_day" | "gap_2_day";
  postgap_preconditions?: PostGapPrecondition[];
  entry_logic: EntryLogicType;
  exit_logic: ExitLogicType;
  risk_management: RiskManagementType;
  created_at: string;
}

interface Props {
  onBack: () => void;
  onTest: (draft: WizardDraft) => void;
  onDraftChange?: (draft: WizardDraft) => void;
  marketSessions?: string[];
  customStartTime?: string;
  customEndTime?: string;
}

/* ── All wizard steps, matching InlineStrategyBuilder sections ── */
const STEPS = [
  { key: "bias",       label: "Dirección",          shortLabel: "Bias" },
  { key: "apply_day",  label: "Día de aplicación",  shortLabel: "Día" },
  { key: "entry",      label: "Lógica de entrada",  shortLabel: "Entry" },
  { key: "exit",       label: "Lógica de salida",   shortLabel: "Exit" },
  { key: "risk",       label: "Gestión de riesgo",  shortLabel: "Riesgo" },
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
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
        let targetStr = '';
        if (typeof c.target === 'number') {
          targetStr = String(c.target);
        } else {
          targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        list.push(`${tfStr}${sourceStr} ${compStr} ${targetStr}`);
      } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        list.push(`${tfStr}Dist(${sourceStr}, ${levelStr}) ${compStr} ${c.value_pct}%`);
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
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
        let targetStr = '';
        if (typeof c.target === 'number') {
          targetStr = String(c.target);
        } else {
          targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        label = `${tfStr}${sourceStr} ${compStr} ${targetStr}`;
      } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        label = `${tfStr}Dist(${sourceStr}, ${levelStr}) ${compStr} ${c.value_pct}%`;
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

export default function WizardStrategyBuilder({
  onBack,
  onTest,
  onDraftChange,
  marketSessions = ["rth"],
  customStartTime = "09:30",
  customEndTime = "16:00",
}: Props) {
  const [currentStep, setCurrentStep] = useState(0);
  const createdAtRef = useRef(new Date().toISOString());

  // Strategy Builder States
  const [bias, setBias] = useState<"long" | "short" | null>(null);
  const [hoveredBias, setHoveredBias] = useState<"long" | "short" | null>(null);
  const [applyDay, setApplyDay] = useState<'gap_day' | 'gap_1_day' | 'gap_2_day'>('gap_day');
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

    const hasOverlap = intervals.some(interval => {
      return windowStart < interval.end && windowEnd > interval.start;
    });

    if (!hasOverlap) {
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

  // Update parent with latest draft strategy
  useEffect(() => {
    if (!bias) return;
    const draft: WizardDraft = {
      id: "wizard_draft",
      name: "Nueva Estrategia (Wizard)",
      bias,
      apply_day: applyDay,
      postgap_preconditions: postgapPreconditions,
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      risk_management: riskManagement,
      created_at: createdAtRef.current,
    };
    onDraftChange?.(draft);
  }, [bias, applyDay, postgapPreconditions, entryLogic, exitLogic, riskManagement, onDraftChange]);

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

    const isPartialTPMode = riskManagement.use_take_profit !== false && riskManagement.take_profit_mode === "Partial";
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

    setCompletedSteps((prev) => new Set(prev).add(4));

    const draft: WizardDraft = {
      id: `wizard_draft_${Date.now()}`,
      name: "Nueva Estrategia (Wizard)",
      bias,
      apply_day: applyDay,
      postgap_preconditions: postgapPreconditions,
      entry_logic: entryLogic,
      exit_logic: exitLogic,
      risk_management: riskManagement,
      created_at: new Date().toISOString(),
    };

    onTest(draft);
  };

  /* ── Steps rendering ── */
  const renderStep = () => {
    switch (STEPS[currentStep]?.key) {
      case "bias":
        return renderBiasStep();
      case "apply_day":
        return renderApplyDayStep();
      case "entry":
        return renderEntryStep();
      case "exit":
        return renderExitStep();
      case "risk":
        return renderRiskStep();
      default:
        return null;
    }
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
                        backgroundColor: 'rgba(216, 122, 61, 0.08)',
                        border: '0.5px solid var(--color-ec-copper)',
                        borderRadius: 4,
                        padding: '3px 6px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 9,
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
                          fontSize: 10,
                          lineHeight: 1,
                          padding: 0,
                          marginLeft: 4,
                          display: 'inline-flex',
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
    );
  };

  // Step 3: Lógica de entrada (Entry Logic)
  const renderEntryStep = () => {
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
          ¿Cuáles son las condiciones para entrar al mercado?
        </h3>
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-muted)",
          margin: "0 0 16px 0",
          lineHeight: 1.5,
        }}>
          Define los indicadores técnicos y filtros temporales que deben coincidir para abrir una posición
        </p>

        <EntryLogicBuilder
          logic={entryLogic}
          onChange={(newLogic) => {
            setEntryLogic(newLogic);
            setCompletedSteps((prev) => new Set(prev).add(2));
          }}
        >
          {/* Entry Time Windows Sub-panel */}
          <div style={{
            marginTop: -11,
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
                      setCompletedSteps((prev) => new Set(prev).add(2));
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
        </EntryLogicBuilder>
      </div>
    );
  };

  // Step 4: Lógica de salida (Exit Logic)
  const renderExitStep = () => {
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
          ¿Cuáles son las condiciones para salir del mercado?
        </h3>
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-muted)",
          margin: "0 0 16px 0",
          lineHeight: 1.5,
        }}>
          Opcional. Define las condiciones basadas en indicadores técnicos que cerrarán tu posición de forma anticipada
        </p>

        <ExitLogicBuilder
          logic={exitLogic}
          onChange={(newLogic) => {
            setExitLogic(newLogic);
            setCompletedSteps((prev) => new Set(prev).add(3));
          }}
        />
      </div>
    );
  };

  // Step 5: Gestión de riesgo (Risk Management)
  const renderRiskStep = () => {
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
          ¿Cómo gestionarás el riesgo de tu estrategia?
        </h3>
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-muted)",
          margin: "0 0 16px 0",
          lineHeight: 1.5,
        }}>
          Configura tus parámetros de salida: Stop Loss, Take Profit y Trailing Stop para proteger el capital
        </p>

        <RiskManagementComponent
          risk={riskManagement}
          onChange={(newRisk) => {
            setRiskManagement(newRisk);
            setCompletedSteps((prev) => new Set(prev).add(4));
          }}
        />
      </div>
    );
  };

  // StepRailItem component declaration removed (now inlined directly in step rail mapping to prevent React recreation/remounting click bugs)


  /* ── Dynamic full-text tag generators grouped by category ── */
  const directionTags = useMemo(() => {
    if (!bias) return [];
    return [{
      label: bias === "long" ? "▲ Long" : "▼ Short",
      color: bias === "long" ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
      onRemove: () => {
        setBias(null);
        setCompletedSteps(prev => {
          const next = new Set(prev);
          next.delete(0);
          return next;
        });
      }
    }];
  }, [bias]);

  const applyDayTags = useMemo(() => {
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
  }, [applyDay, postgapPreconditions]);

  const entryTags = useMemo(() => {
    const list: { label: string; color: string; onRemove: () => void }[] = [];
    
    // Condition tags with callback
    const condTags = getConditionTags(
      entryLogic.root_condition,
      entryLogic.timeframe,
      (newRoot) => setEntryLogic({ ...entryLogic, root_condition: newRoot })
    );
    condTags.forEach(tag => {
      list.push({ ...tag, color: "#60a5fa" });
    });

    // Time window tags
    const windows = entryLogic.entry_time_windows || [];
    windows.forEach((w, wIdx) => {
      list.push({
        label: `Hora: ${w.from_time} - ${w.to_time}`,
        color: "#3b82f6",
        onRemove: () => {
          setEntryLogic({
            ...entryLogic,
            entry_time_windows: windows.filter((_, i) => i !== wIdx)
          });
        }
      });
    });
    return list;
  }, [entryLogic]);

  const exitTags = useMemo(() => {
    return getConditionTags(
      exitLogic.root_condition,
      exitLogic.timeframe,
      (newRoot) => setExitLogic({ ...exitLogic, root_condition: newRoot })
    ).map(tag => ({ ...tag, color: "#f43f5e" }));
  }, [exitLogic]);

  const riskTags = useMemo(() => {
    const list = [];
    
    // Stop Loss
    if (riskManagement.use_hard_stop !== false) {
      const label = riskManagement.hard_stop.type === RiskType.PERCENTAGE
        ? `Stop Loss: ${riskManagement.hard_stop.value}%`
        : `Stop Loss: ${riskManagement.hard_stop.value} (Offset ${riskManagement.hard_stop.offset_pct ?? 0}%)`;
      list.push({
        label,
        color: "#f87171",
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
          color: "#f87171",
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
        color: "var(--color-ec-text-muted)",
        onRemove: () => {
          setRiskManagement({
            ...riskManagement,
            use_hard_stop: true
          });
        }
      });
    }

    // Take Profit
    if (riskManagement.use_take_profit !== false) {
      if (riskManagement.take_profit_mode === "Full") {
        list.push({
          label: `Take Profit: ${riskManagement.take_profit.value}%`,
          color: "var(--color-ec-profit)",
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
            color: "var(--color-ec-profit)",
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
        color: "var(--color-ec-text-muted)",
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
        color: "#fbbf24",
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

    return list;
  }, [riskManagement]);

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
          width: `${((completedSteps.size) / STEPS.length) * 100}%`,
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
          {/* Top 1/3 Container: Steps Indicators */}
          <div style={{
            height: "33%",
            flexShrink: 0,
            padding: "14px 8px 8px 8px",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            overflowY: "auto",
            scrollbarWidth: "none",
          }}>
            {STEPS.map((step, idx) => {
              const isActive = idx === currentStep;
              const isCompleted = completedSteps.has(idx);
              const isFuture = idx > currentStep && !isCompleted;

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
                      backgroundColor: completedSteps.has(idx)
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

        {/* Right: Step Content */}
        <div style={{
          flex: 1,
          overflowY: "auto",
          padding: "20px 22px 80px",
          scrollbarWidth: "none",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}>
          <div>
            <div style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 8,
              fontWeight: 700,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "var(--color-ec-copper)",
              marginBottom: 10,
            }}>
              Paso {currentStep + 1} de {STEPS.length}
            </div>

            {renderStep()}
          </div>

          {/* Navigation Footer */}
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 32,
            paddingTop: 16,
            borderTop: "0.5px solid var(--color-ec-border)",
          }}>
            {currentStep > 0 ? (
              <button
                onClick={() => setCurrentStep((prev) => prev - 1)}
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
              <button
                onClick={() => {
                  setCompletedSteps((prev) => new Set(prev).add(currentStep));
                  setCurrentStep((prev) => prev + 1);
                }}
                disabled={currentStep === 0 && bias === null}
                style={{
                  backgroundColor: (currentStep === 0 && bias === null) ? "var(--color-ec-bg-elevated)" : "var(--color-ec-copper)",
                  color: (currentStep === 0 && bias === null) ? "var(--color-ec-text-muted)" : "var(--color-ec-copper-text)",
                  border: "none",
                  borderRadius: 5,
                  padding: "6px 16px",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  cursor: (currentStep === 0 && bias === null) ? "not-allowed" : "pointer",
                  transition: "all 150ms ease",
                  opacity: (currentStep === 0 && bias === null) ? 0.5 : 1,
                }}
              >
                Continuar
              </button>
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
