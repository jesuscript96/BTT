"use client";

import { useState, useEffect } from "react";
import { EntryLogicBuilder } from "@/components/strategy-builder/EntryLogic";
import { ExitLogicBuilder } from "@/components/strategy-builder/ExitLogic";
import { RiskManagementComponent } from "@/components/strategy-builder/RiskManagement";
import {
  initialEntryLogic,
  initialExitLogic,
  initialRiskManagement,
} from "@/types/strategy";
import type {
  EntryLogic as EntryLogicType,
  ExitLogic as ExitLogicType,
  RiskManagement as RiskManagementType,
  ConditionGroup,
} from "@/types/strategy";
import { INDICATOR_LABELS, COMPARATOR_LABELS } from "@/components/strategy-builder/ConditionBuilder";

const STORAGE_KEY = "btt_draft_strategies";

export interface Draft {
  id: string;
  name: string;
  bias: "long" | "short";
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
  const [entryLogic, setEntryLogic] = useState<EntryLogicType>(initialEntryLogic);
  const [exitLogic, setExitLogic] = useState<ExitLogicType>(initialExitLogic);
  const [riskManagement, setRiskManagement] = useState<RiskManagementType>(initialRiskManagement);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [showDrafts, setShowDrafts] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setDrafts(JSON.parse(stored));
    } catch {}
  }, []);

  const resetForm = () => {
    setName("Nueva Estrategia");
    setBias("long");
    setEntryLogic(initialEntryLogic);
    setExitLogic(initialExitLogic);
    setRiskManagement(initialRiskManagement);
  };

  const buildDraft = (): Draft => ({
    id: `draft_${Date.now()}`,
    name,
    bias,
    entry_logic: entryLogic,
    exit_logic: exitLogic,
    risk_management: riskManagement,
    created_at: new Date().toISOString(),
  });

  const handleTest = () => {
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
