"use client";

import { useState, useEffect, Fragment } from "react";
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

const STORAGE_KEY = "btt_draft_strategies";

export interface Draft {
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

interface Props {
  onTest: (draft: Draft) => void;
  onBack: () => void;
}

export default function InlineStrategyBuilder({ onTest, onBack }: Props) {
  const [name, setName] = useState("Nueva Estrategia");
  const [bias, setBias] = useState<"long" | "short">("long");
  const [applyDay, setApplyDay] = useState<'gap_day' | 'gap_1_day' | 'gap_2_day'>('gap_day');
  const [postgapPreconditions, setPostgapPreconditions] = useState<PostGapPrecondition[]>([]);
  const [entryLogic, setEntryLogic] = useState<EntryLogicType>(initialEntryLogic);
  const [exitLogic, setExitLogic] = useState<ExitLogicType>(initialExitLogic);
  const [riskManagement, setRiskManagement] = useState<RiskManagementType>(initialRiskManagement);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [showDrafts, setShowDrafts] = useState(false);
  const [tempDay, setTempDay] = useState<'gap_day' | 'gap_1_day'>('gap_day');
  const [tempSource, setTempSource] = useState<'cierre' | 'volume' | 'candle_range_pct'>('cierre');
  const [tempOperator, setTempOperator] = useState<'>' | '<'>('>');
  const [tempTarget, setTempTarget] = useState<'apertura' | 'high_low_previo' | 'pm_high' | 'vwap' | 'sma'>('apertura');
  const [tempValue, setTempValue] = useState<number>(1000000);
  const [tempSmaPeriod, setTempSmaPeriod] = useState<number>(20);

  useEffect(() => {
    if (applyDay === 'gap_day') {
      setPostgapPreconditions([]);
    } else if (applyDay === 'gap_1_day') {
      // Ensure all preconditions use 'gap_day' if we are on Gap +1 Day
      setPostgapPreconditions(prev => prev.map(p => ({ ...p, day: 'gap_day' })));
      setTempDay('gap_day');
    }
  }, [applyDay]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setDrafts(JSON.parse(stored));
    } catch {}
  }, []);

  const resetForm = () => {
    setName("Nueva Estrategia");
    setBias("long");
    setApplyDay("gap_day");
    setPostgapPreconditions([]);
    setEntryLogic(initialEntryLogic);
    setExitLogic(initialExitLogic);
    setRiskManagement(initialRiskManagement);
  };

  const buildDraft = (): Draft => ({
    id: `draft_${Date.now()}`,
    name,
    bias,
    apply_day: applyDay,
    postgap_preconditions: postgapPreconditions,
    entry_logic: entryLogic,
    exit_logic: exitLogic,
    risk_management: riskManagement,
    created_at: new Date().toISOString(),
  });

  const handleTest = () => {
    const logicErrors = validateStrategyLogic(entryLogic, exitLogic);
    if (logicErrors.length > 0) {
      alert("Hay condiciones incompletas:\n" + logicErrors.join("\n"));
      return;
    }
    const draft = buildDraft();
    try {
      const updated = [draft, ...drafts].slice(0, 200);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      setDrafts(updated);
    } catch {}
    onTest(draft);
  };

  const handleLoadDraft = (draft: Draft) => {
    setName(draft.name);
    setBias(draft.bias);
    setApplyDay(draft.apply_day || 'gap_day');
    setPostgapPreconditions(draft.postgap_preconditions || []);
    setEntryLogic(draft.entry_logic);
    setExitLogic(draft.exit_logic);
    setRiskManagement(draft.risk_management);
    setShowDrafts(false);
  };

  const handleDeleteDraft = (id: string) => {
    const updated = drafts.filter((d) => d.id !== id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    setDrafts(updated);
  };

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
        {drafts.length > 0 && (
          <button
            onClick={() => setShowDrafts(!showDrafts)}
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: 1,
              textTransform: "uppercase",
              color: "var(--color-ec-text-muted)",
              background: "var(--color-ec-bg-elevated)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 4,
              padding: "3px 8px",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            Drafts ({drafts.length})
          </button>
        )}
      </div>

      {/* Drafts panel */}
      {showDrafts && (
        <div
          style={{
            borderBottom: "0.5px solid var(--color-ec-border)",
            maxHeight: 200,
            overflowY: "auto",
            backgroundColor: "var(--color-ec-bg-surface)",
            flexShrink: 0,
          }}
        >
          {drafts.map((d) => (
            <div
              key={d.id}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "6px 16px",
                borderBottom: "0.5px solid var(--color-ec-border)",
                gap: 8,
              }}
            >
              <button
                onClick={() => handleLoadDraft(d)}
                style={{
                  flex: 1,
                  textAlign: "left",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 12,
                  color: "var(--color-ec-text-primary)",
                  fontFamily: "var(--color-ec-sans)",
                }}
              >
                {d.name}{" "}
                <span style={{ color: "var(--color-ec-text-muted)", fontSize: 10 }}>
                  {new Date(d.created_at).toLocaleDateString()}
                </span>
              </button>
              <button
                onClick={() => handleDeleteDraft(d.id)}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--color-ec-loss)",
                  fontSize: 14,
                  lineHeight: 1,
                  padding: "0 2px",
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Bias toggle */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "0.5px solid var(--color-ec-border)",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 8,
            fontWeight: 700,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--color-ec-text-muted)",
            marginBottom: 8,
            fontFamily: "var(--color-ec-sans)",
          }}
        >
          Direction Bias
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {(["long", "short"] as const).map((b) => (
            <button
              key={b}
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

      {/* Entry / Exit / Risk */}
      <div style={{ 
        flex: 1, 
        overflowY: "auto", 
        padding: "0 20px 80px 20px",
        display: "flex",
        flexDirection: "column",
        gap: "0px"
      }}>
        {/* DIVIDER 1 */}
        <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', width: '100%', margin: '4px 0' }} />

        {/* SECTION: PRE-GAP CONDITIONS */}
        {applyDay !== 'gap_day' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' }}>
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
              {/* Top: Day selector (only for gap_2_day) */}
              {applyDay === 'gap_2_day' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, borderBottom: '0.5px solid var(--color-ec-border)', paddingBottom: 10, marginBottom: 2 }}>
                  <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Evaluar en</label>
                  <select
                    value={tempDay}
                    onChange={(e) => setTempDay(e.target.value as any)}
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
                      const src = e.target.value as 'cierre' | 'volume' | 'candle_range_pct';
                      setTempSource(src);
                      
                      // Set sensible default values/operators
                      if (src === 'volume') {
                        setTempValue(1000000);
                      } else if (src === 'candle_range_pct') {
                        setTempValue(2.0);
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
                      <option value="high_low_previo">High/Low Previo</option>
                      <option value="pm_high">PM High</option>
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
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: tempSource === 'volume' ? 90 : 70 }}>
                    <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Valor</label>
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
                      } else if (tempTarget === 'high_low_previo') {
                        metric = 'close_vs_high_low';
                        operator = tempOperator === '>' ? '> High' : '< Low';
                      } else if (tempTarget === 'pm_high') {
                        metric = 'close_vs_pm_high';
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
                      value = tempValue;
                    } else if (tempSource === 'candle_range_pct') {
                      metric = 'candle_range_pct';
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
                    valLabel = `${cond.operator} ${(cond.value ?? 0).toLocaleString()}`;
                  } else if (cond.metric === 'close_vs_open') {
                    valLabel = `${cond.operator} Apertura`;
                  } else if (cond.metric === 'close_vs_high_low') {
                    valLabel = cond.operator === '> High' ? '> High Previo' : '< Low Previo';
                  } else if (cond.metric === 'close_vs_pm_high') {
                    valLabel = `${cond.operator} PM High`;
                  } else if (cond.metric === 'close_vs_vwap') {
                    valLabel = `${cond.operator} VWAP`;
                  } else if (cond.metric === 'close_vs_sma') {
                    valLabel = `${cond.operator} SMA ${cond.sma_period}`;
                  } else if (cond.metric === 'candle_range_pct') {
                    metricLabel = 'Rango de Vela %';
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

        {/* DIVIDER 2 */}
        <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', width: '100%', margin: '4px 0' }} />

        {/* SECTION: APPLY DAY SELECTOR */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', fontSize: 11, fontFamily: 'var(--color-ec-sans)' }}>
            <span style={{ fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Aplicar en:</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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

        <EntryLogicBuilder logic={entryLogic} onChange={setEntryLogic} />
        <ExitLogicBuilder logic={exitLogic} onChange={setExitLogic} />
        <RiskManagementComponent risk={riskManagement} onChange={setRiskManagement} />
      </div>

      {/* Strategy Summary Panel */}
      {(getGroupSummaryText(entryLogic.root_condition) || getGroupSummaryText(exitLogic.root_condition)) && (
        <div style={{
          padding: "12px 16px",
          backgroundColor: "var(--color-ec-bg-surface)",
          borderTop: "0.5px solid var(--color-ec-border)",
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-secondary)",
          display: "flex",
          flexDirection: "column",
          gap: 6,
          flexShrink: 0,
        }}>
          {getGroupSummaryText(entryLogic.root_condition) && (
            <div style={{ whiteSpace: "normal", wordBreak: "break-word", lineHeight: 1.4 }}>
              <span style={{ fontWeight: 700, color: "var(--color-ec-profit)", marginRight: 4 }}>ENTRY LOGIC:</span>
              <code style={{ color: "var(--color-ec-text-primary)", fontFamily: "var(--color-ec-sans)", fontSize: 10 }}>{getGroupSummaryText(entryLogic.root_condition)}</code>
            </div>
          )}
          {getGroupSummaryText(exitLogic.root_condition) && (
            <div style={{ whiteSpace: "normal", wordBreak: "break-word", lineHeight: 1.4 }}>
              <span style={{ fontWeight: 700, color: "var(--color-ec-loss)", marginRight: 4 }}>EXIT LOGIC:</span>
              <code style={{ color: "var(--color-ec-text-primary)", fontFamily: "var(--color-ec-sans)", fontSize: 10 }}>{getGroupSummaryText(exitLogic.root_condition)}</code>
            </div>
          )}
        </div>
      )}

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
          style={{
            width: "100%",
            padding: "8px 0",
            borderRadius: 5,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.2,
            textTransform: "uppercase",
            cursor: "pointer",
            border: "none",
            backgroundColor: "var(--color-ec-copper)",
            color: "var(--color-ec-copper-text)",
            fontFamily: "var(--color-ec-sans)",
          }}
        >
          ▶ Probar
        </button>
      </div>
    </div>
  );
}
