"use client";

import { useState } from "react";

interface Props {
  onSave: (name: string, filters: any) => Promise<void>;
  onBack: () => void;
}

interface ParameterConfig {
  key: string;
  label: string;
  unit: string;
  placeholder: string;
  min?: number;
}

const SECTION_PARAMS: ParameterConfig[] = [
  { key: "rth_close", label: "Min Close price", unit: "$", placeholder: "0.00" },
  { key: "pmh_gap_pct_min", label: "PM High Gap min", unit: "%", placeholder: "10.0", min: 10 },
  { key: "pmh_gap_pct_max", label: "PM High Gap max", unit: "%", placeholder: "0.0" },
  { key: "pm_volume", label: "Premarket total volume", unit: "M", placeholder: "0.0" },
  { key: "gap_pct_min", label: "Gap mín", unit: "%", placeholder: "10.0", min: 10 },
  { key: "gap_pct_max", label: "Gap max", unit: "%", placeholder: "0.0" },
  { key: "rth_volume", label: "RTH Total Volume", unit: "%", placeholder: "0.0" },
  { key: "rth_range_pct", label: "Bar Range", unit: "%", placeholder: "0.0" },
];

type SectionId = "gap_day" | "gap_1_day" | "gap_2_day";

const SECTION_LABELS: Record<SectionId, string> = {
  gap_day: "GAP DAY",
  gap_1_day: "GAP-1 DAY",
  gap_2_day: "GAP-2 DAY",
};

interface IncludedCondition {
  section: SectionId;
  paramKey: string;
  label: string;
  value: number;
  unit: string;
}

export default function InlineDatasetBuilder({ onSave, onBack }: Props) {
  const [name, setName] = useState("Nuevo Dataset");
  const [values, setValues] = useState<Record<SectionId, Record<string, string>>>({
    gap_day: {},
    gap_1_day: {},
    gap_2_day: {},
  });

  const [includedConditions, setIncludedConditions] = useState<IncludedCondition[]>([]);
  const [expandedSections, setExpandedSections] = useState<Record<SectionId, boolean>>({
    gap_day: true,
    gap_1_day: true,
    gap_2_day: true,
  });

  const handleInputChange = (section: SectionId, paramKey: string, val: string) => {
    setValues((prev) => ({
      ...prev,
      [section]: {
        ...prev[section],
        [paramKey]: val,
      },
    }));
  };

  const toggleSection = (section: SectionId) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const getValidationError = (param: ParameterConfig, valStr: string): string | null => {
    if (!valStr) return null;
    const val = parseFloat(valStr);
    if (isNaN(val)) return "Valor inválido";
    if (param.min !== undefined && val < param.min) {
      return `Mínimo ${param.min}%`;
    }
    return null;
  };

  const isConditionIncluded = (section: SectionId, paramKey: string) => {
    return includedConditions.some((c) => c.section === section && c.paramKey === paramKey);
  };

  const handleIncludeToggle = (section: SectionId, param: ParameterConfig) => {
    const valStr = values[section][param.key];
    if (!valStr) return;

    const error = getValidationError(param, valStr);
    if (error) return; // Don't include if there's a validation error

    const val = parseFloat(valStr);
    const exists = isConditionIncluded(section, param.key);

    if (exists) {
      // Remove it
      setIncludedConditions((prev) =>
        prev.filter((c) => !(c.section === section && c.paramKey === param.key))
      );
    } else {
      // Add it
      const labelText = param.label === "Bar Range" && section !== "gap_day" ? "Bar RTH Range" : param.label;
      setIncludedConditions((prev) => [
        ...prev,
        {
          section,
          paramKey: param.key,
          label: labelText,
          value: val,
          unit: param.unit,
        },
      ]);
    }
  };

  const removeCondition = (section: SectionId, paramKey: string) => {
    setIncludedConditions((prev) =>
      prev.filter((c) => !(c.section === section && c.paramKey === paramKey))
    );
  };

  const handleSave = async () => {
    // Construct the filters object from the included conditions
    const rules: any[] = [];
    let min_gap_pct: number | undefined = undefined;
    let max_gap_pct: number | undefined = undefined;
    let min_pm_volume: number | undefined = undefined;
    let min_rth_volume: number | undefined = undefined;

    includedConditions.forEach((c) => {
      let fieldName = "";
      let operator = "GREATER_THAN_OR_EQUAL";
      let finalVal = c.value;

      // Map to exact DuckDB/Parquet columns
      if (c.section === "gap_day") {
        if (c.paramKey === "rth_close") fieldName = "Close Price";
        else if (c.paramKey === "pmh_gap_pct_min") fieldName = "PMH Gap %";
        else if (c.paramKey === "pmh_gap_pct_max") {
          fieldName = "PMH Gap %";
          operator = "LESS_THAN_OR_EQUAL";
        } else if (c.paramKey === "pm_volume") {
          fieldName = "Premarket Volume";
          finalVal = c.value * 1000000; // in Millions
          min_pm_volume = finalVal;
        } else if (c.paramKey === "gap_pct_min") {
          fieldName = "Open Gap %";
          min_gap_pct = c.value;
        } else if (c.paramKey === "gap_pct_max") {
          fieldName = "Open Gap %";
          operator = "LESS_THAN_OR_EQUAL";
          max_gap_pct = c.value;
        } else if (c.paramKey === "rth_volume") {
          fieldName = "EOD Volume";
          min_rth_volume = c.value;
        } else if (c.paramKey === "rth_range_pct") fieldName = "RTH Range %";
      } else {
        // GAP-1 or GAP-2
        const lagSuffix = c.section === "gap_1_day" ? "_1" : "_2";
        if (c.paramKey === "rth_close") fieldName = `lag_rth_close${lagSuffix}`;
        else if (c.paramKey === "pmh_gap_pct_min") fieldName = `lag_pmh_gap_pct${lagSuffix}`;
        else if (c.paramKey === "pmh_gap_pct_max") {
          fieldName = `lag_pmh_gap_pct${lagSuffix}`;
          operator = "LESS_THAN_OR_EQUAL";
        } else if (c.paramKey === "pm_volume") {
          fieldName = `lag_pm_volume${lagSuffix}`;
          finalVal = c.value * 1000000; // in Millions
        } else if (c.paramKey === "gap_pct_min") fieldName = `lag_gap_pct${lagSuffix}`;
        else if (c.paramKey === "gap_pct_max") {
          fieldName = `lag_gap_pct${lagSuffix}`;
          operator = "LESS_THAN_OR_EQUAL";
        } else if (c.paramKey === "rth_volume") fieldName = `lag_rth_volume${lagSuffix}`;
        else if (c.paramKey === "rth_range_pct") fieldName = `lag_rth_range_pct${lagSuffix}`;
      }

      if (fieldName) {
        rules.push({
          metric: fieldName,
          operator,
          valueType: "static",
          value: finalVal.toString(),
        });
      }
    });

    const filters = {
      date_from: "2024-01-01",
      date_to: "2024-12-31",
      start_date: "2024-01-01",
      end_date: "2024-12-31",
      min_gap_pct,
      max_gap_pct,
      min_pm_volume,
      min_rth_volume,
      rules,
    };

    await onSave(name, filters);
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
      </div>

      {/* Main Content Area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: 16 }}>
        {(["gap_day", "gap_1_day", "gap_2_day"] as SectionId[]).map((sectionId) => {
          const isExpanded = expandedSections[sectionId];
          return (
            <div
              key={sectionId}
              style={{
                border: "0.5px solid var(--color-ec-border)",
                borderRadius: 6,
                backgroundColor: "var(--color-ec-bg-sidebar)",
                overflow: "hidden",
              }}
            >
              {/* Section Header */}
              <div
                onClick={() => toggleSection(sectionId)}
                style={{
                  padding: "10px 14px",
                  backgroundColor: "var(--color-ec-bg-elevated)",
                  cursor: "pointer",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  borderBottom: isExpanded ? "0.5px solid var(--color-ec-border)" : "none",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--color-ec-sans)",
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                    color: "var(--color-ec-text-high)",
                  }}
                >
                  {SECTION_LABELS[sectionId]}
                </span>
                <span style={{ fontSize: 10, color: "var(--color-ec-text-muted)" }}>
                  {isExpanded ? "▲" : "▼"}
                </span>
              </div>

              {/* Section Body */}
              {isExpanded && (
                <div style={{ padding: "12px", display: "flex", flexDirection: "column", gap: 10 }}>
                  {SECTION_PARAMS.map((param) => {
                    const val = values[sectionId][param.key] || "";
                    const validationErr = getValidationError(param, val);
                    const included = isConditionIncluded(sectionId, param.key);
                    const labelText = param.label === "Bar Range" && sectionId !== "gap_day" ? "Bar RTH Range" : param.label;

                    return (
                      <div
                        key={param.key}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: 12,
                        }}
                      >
                        {/* Parameter Label */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <span
                            style={{
                              fontFamily: "var(--color-ec-sans)",
                              fontSize: 11,
                              fontWeight: 500,
                              color: "var(--color-ec-text-secondary)",
                              display: "block",
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {labelText}
                          </span>
                        </div>

                        {/* Input & Include Button */}
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          {/* Input box with units */}
                          <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                            {param.unit === "$" && (
                              <span
                                style={{
                                  position: "absolute",
                                  left: 8,
                                  fontSize: 11,
                                  color: "var(--color-ec-text-muted)",
                                  fontFamily: "var(--color-ec-sans)",
                                }}
                              >
                                $
                              </span>
                            )}
                            <input
                              type="number"
                              step="any"
                              value={val}
                              placeholder={param.placeholder}
                              onChange={(e) => handleInputChange(sectionId, param.key, e.target.value)}
                              disabled={included}
                              style={{
                                backgroundColor: "var(--color-ec-bg-elevated)",
                                border: `0.5px solid ${validationErr ? "var(--color-ec-loss)" : "var(--color-ec-border)"}`,
                                borderRadius: 5,
                                padding: `6px 24px 6px ${param.unit === "$" ? "18px" : "8px"}`,
                                fontFamily: "var(--color-ec-sans)",
                                fontSize: 11,
                                fontWeight: 500,
                                color: "var(--color-ec-text-primary)",
                                outline: "none",
                                width: 85,
                                textAlign: "right",
                                opacity: included ? 0.6 : 1,
                              }}
                            />
                            {param.unit !== "$" && (
                              <span
                                style={{
                                  position: "absolute",
                                  right: 8,
                                  fontSize: 11,
                                  fontWeight: 600,
                                  color: "var(--color-ec-text-muted)",
                                  fontFamily: "var(--color-ec-sans)",
                                }}
                              >
                                {param.unit}
                              </span>
                            )}
                          </div>

                          {/* Include Button */}
                          <button
                            type="button"
                            onClick={() => handleIncludeToggle(sectionId, param)}
                            disabled={!val || !!validationErr}
                            style={{
                              padding: "6px 12px",
                              borderRadius: 4,
                              fontSize: 10,
                              fontWeight: 700,
                              textTransform: "uppercase",
                              letterSpacing: "0.5px",
                              cursor: "pointer",
                              transition: "all 150ms ease",
                              border: included
                                ? "none"
                                : "0.5px solid var(--color-ec-copper)",
                              backgroundColor: included
                                ? "var(--color-ec-copper)"
                                : "transparent",
                              color: included
                                ? "var(--color-ec-copper-text)"
                                : "var(--color-ec-copper)",
                              opacity: !val || !!validationErr ? 0.3 : 1,
                            }}
                          >
                            {included ? "✓ Incluido" : "Incluir"}
                          </button>
                        </div>

                        {/* Validation warning */}
                        {validationErr && (
                          <div
                            style={{
                              position: "absolute",
                              marginTop: 32,
                              right: 120,
                              fontSize: 9,
                              color: "var(--color-ec-loss)",
                              fontFamily: "var(--color-ec-sans)",
                              fontWeight: 600,
                            }}
                          >
                            {validationErr}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {/* Included Conditions Tag Summary */}
        <div style={{ marginTop: 8 }}>
          <span
            style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 9,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.15em",
              color: "var(--color-ec-text-muted)",
              display: "block",
              marginBottom: 8,
            }}
          >
            Resumen de Condiciones ({includedConditions.length})
          </span>
          {includedConditions.length === 0 ? (
            <span
              style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 11,
                fontStyle: "italic",
                color: "var(--color-ec-text-muted)",
              }}
            >
              Ninguna condición incluida. Escribe un valor e inclúyelo arriba.
            </span>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {includedConditions.map((c) => {
                const sectLabel = SECTION_LABELS[c.section];
                return (
                  <div
                    key={`${c.section}_${c.paramKey}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      backgroundColor: "var(--color-ec-bg-elevated)",
                      border: "0.5px solid var(--color-ec-border)",
                      borderRadius: 4,
                      padding: "4px 8px",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--color-ec-sans)",
                        fontSize: 10,
                        fontWeight: 600,
                        color: "var(--color-ec-text-secondary)",
                      }}
                    >
                      <strong style={{ color: "var(--color-ec-copper)" }}>{sectLabel}</strong>:{" "}
                      {c.label} {c.paramKey.includes("max") ? "≤" : "≥"}{" "}
                      {c.unit === "$" ? `$${c.value}` : `${c.value}${c.unit}`}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeCondition(c.section, c.paramKey)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--color-ec-text-muted)",
                        cursor: "pointer",
                        fontSize: 12,
                        lineHeight: 1,
                        padding: "0 2px",
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
          onClick={handleSave}
          disabled={includedConditions.length === 0}
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
            opacity: includedConditions.length === 0 ? 0.5 : 1,
          }}
        >
          Guardar y Probar
        </button>
      </div>
    </div>
  );
}
