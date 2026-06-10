"use client";

import { useState, useRef } from "react";

interface Props {
  onSave: (name: string, filters: any) => Promise<void>;
  onBack: () => void;
  isSaving?: boolean;
}

interface ParameterConfig {
  key: string;
  label: string;
  unit: string;
  placeholder: string;
  min?: number;
}

const SECTION_PARAMS: ParameterConfig[] = [
  { key: "rth_close", label: "Min Open price", unit: "$", placeholder: "0.00" },
  { key: "pm_open", label: "Min Open PM price", unit: "$", placeholder: "0.00" },
  { key: "pmh_gap_pct_min", label: "PM High Gap min", unit: "%", placeholder: "10.0", min: 10 },
  { key: "pmh_gap_pct_max", label: "PM High Gap max", unit: "%", placeholder: "0.0" },
  { key: "pm_volume", label: "Min Premarket total volume", unit: "M", placeholder: "0.0" },
  { key: "gap_pct_min", label: "Gap min", unit: "%", placeholder: "10.0", min: 10 },
  { key: "gap_pct_max", label: "Gap max", unit: "%", placeholder: "0.0" },
  { key: "rth_volume", label: "Min RTH Total Volume", unit: "M", placeholder: "0.0" },
  { key: "rth_range_pct", label: "Bar RTH Range", unit: "%", placeholder: "0.0" },
];

const PARAM_DESCRIPTIONS: Record<string, string> = {
  rth_close: "Precio mínimo de la acción en la apertura de mercado",
  pm_open: "Precio de apertura del Premarket",
  pmh_gap_pct_min: "Precio mínimo de la sesión de premarket",
  pmh_gap_pct_max: "Precio máximo de la sesión de premarket",
  pm_volume: "Volumen mínimo acumulado durante el premarket",
  gap_pct_min: "% de Gap mínimo",
  gap_pct_max: "% de Gap máximo",
  rth_volume: "Volumen mínimo durante la sesión de mercado REGULAR",
  rth_range_pct: "Rango de la vela en temporalidad diaria, es decir, el % de subida o bajada que ha hecho la vela este día (se permite buscar tanto para +% como para -%)",
};

type SectionId = "gap_day" | "gap_plus_1_day" | "gap_plus_2_day";

const SECTION_LABELS: Record<SectionId, string> = {
  gap_day: "GAP DAY",
  gap_plus_1_day: "GAP+1 DAY",
  gap_plus_2_day: "GAP+2 DAY",
};

interface IncludedCondition {
  section: SectionId;
  paramKey: string;
  label: string;
  value: number;
  unit: string;
}

const MIN_DATE = "2006-01-01";
const MAX_DATE = new Date().toISOString().split("T")[0];
const TWO_YEARS_AGO = new Date(
  new Date().setFullYear(new Date().getFullYear() - 2)
).toISOString().split("T")[0];

export default function InlineDatasetBuilder({ onSave, onBack, isSaving = false }: Props) {
  const [name, setName] = useState("Nuevo Dataset");
  const [dateFrom, setDateFrom] = useState(TWO_YEARS_AGO);
  const [dateTo, setDateTo] = useState(MAX_DATE);
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [tempName, setTempName] = useState("");
  const [values, setValues] = useState<Record<SectionId, Record<string, string>>>({
    gap_day: {},
    gap_plus_1_day: {},
    gap_plus_2_day: {},
  });

  const [includedConditions, setIncludedConditions] = useState<IncludedCondition[]>([]);
  const [expandedSections, setExpandedSections] = useState<Record<SectionId, boolean>>({
    gap_day: true,
    gap_plus_1_day: true,
    gap_plus_2_day: true,
  });

  const [activeTooltip, setActiveTooltip] = useState<{
    text: string;
    x: number;
    y: number;
    width: number;
  } | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

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
      const labelText = param.label;
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

  const handleSave = async (datasetName: string) => {
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
        else if (c.paramKey === "pm_open") fieldName = "Min Open PM price";
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
          finalVal = c.value * 1000000; // in Millions
          min_rth_volume = finalVal;
        } else if (c.paramKey === "rth_range_pct") fieldName = "RTH Range %";
      } else {
        // GAP+1 or GAP+2
        const lagSuffix = c.section === "gap_plus_1_day" ? "_1" : "_2";
        if (c.paramKey === "rth_close") fieldName = `lead_rth_close${lagSuffix}`;
        else if (c.paramKey === "pm_open") fieldName = `lead_open${lagSuffix}`;
        else if (c.paramKey === "pmh_gap_pct_min") fieldName = `lead_pmh_gap_pct${lagSuffix}`;
        else if (c.paramKey === "pmh_gap_pct_max") {
          fieldName = `lead_pmh_gap_pct${lagSuffix}`;
          operator = "LESS_THAN_OR_EQUAL";
        } else if (c.paramKey === "pm_volume") {
          fieldName = `lead_pm_volume${lagSuffix}`;
          finalVal = c.value * 1000000; // in Millions
        } else if (c.paramKey === "gap_pct_min") fieldName = `lead_gap_pct${lagSuffix}`;
        else if (c.paramKey === "gap_pct_max") {
          fieldName = `lead_gap_pct${lagSuffix}`;
          operator = "LESS_THAN_OR_EQUAL";
        } else if (c.paramKey === "rth_volume") {
          fieldName = `lead_rth_volume${lagSuffix}`;
          finalVal = c.value * 1000000; // in Millions
        } else if (c.paramKey === "rth_range_pct") fieldName = `lead_rth_range_pct${lagSuffix}`;
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
      date_from: dateFrom,
      date_to: dateTo,
      start_date: dateFrom,
      end_date: dateTo,
      min_gap_pct,
      max_gap_pct,
      min_pm_volume,
      min_rth_volume,
      rules,
    };

    await onSave(datasetName, filters);
  };

  return (
    <div ref={containerRef} style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", position: "relative" }}>
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
        {/* Date Range Selector Card */}
        <div
          style={{
            border: "0.5px solid var(--color-ec-border)",
            borderRadius: 6,
            backgroundColor: "var(--color-ec-bg-sidebar)",
            padding: "12px 14px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: "var(--color-ec-text-high)",
              textTransform: "uppercase",
            }}
          >
            RANGO DE FECHAS GLOBAL
          </span>
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 9, fontFamily: "var(--color-ec-sans)", fontWeight: 600, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Desde</span>
              <input
                type="date"
                value={dateFrom}
                min={MIN_DATE}
                max={dateTo || MAX_DATE}
                onChange={(e) => setDateFrom(e.target.value)}
                style={{
                  backgroundColor: "var(--color-ec-bg-elevated)",
                  border: "0.5px solid var(--color-ec-border)",
                  borderRadius: 5,
                  padding: "6px 8px",
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 11,
                  color: "var(--color-ec-text-primary)",
                  outline: "none",
                }}
              />
            </div>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 9, fontFamily: "var(--color-ec-sans)", fontWeight: 600, color: "var(--color-ec-text-muted)", textTransform: "uppercase" }}>Hasta</span>
              <input
                type="date"
                value={dateTo}
                min={dateFrom || MIN_DATE}
                max={MAX_DATE}
                onChange={(e) => setDateTo(e.target.value)}
                style={{
                  backgroundColor: "var(--color-ec-bg-elevated)",
                  border: "0.5px solid var(--color-ec-border)",
                  borderRadius: 5,
                  padding: "6px 8px",
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 11,
                  color: "var(--color-ec-text-primary)",
                  outline: "none",
                }}
              />
            </div>
          </div>
        </div>

        {(["gap_day", "gap_plus_1_day", "gap_plus_2_day"] as SectionId[]).map((sectionId) => {
          const isExpanded = expandedSections[sectionId];
          return (
            <div
              key={sectionId}
              style={{
                border: "0.5px solid var(--color-ec-border)",
                borderRadius: 6,
                backgroundColor: "var(--color-ec-bg-sidebar)",
                overflow: "hidden",
                flexShrink: 0,
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
                <div style={{ padding: "12px 12px 20px 12px", display: "flex", flexDirection: "column", gap: 10, maxHeight: "200px", overflowY: "auto", overscrollBehaviorY: "contain" }}>
                  {SECTION_PARAMS.map((param) => {
                    const val = values[sectionId][param.key] || "";
                    const validationErr = getValidationError(param, val);
                    const included = isConditionIncluded(sectionId, param.key);
                    const labelText = param.label;

                    const isHovered = hoveredRow === `${sectionId}_${param.key}`;
                    return (
                      <div
                        key={param.key}
                        onMouseEnter={() => setHoveredRow(`${sectionId}_${param.key}`)}
                        onMouseLeave={() => setHoveredRow(null)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: 12,
                          flexShrink: 0,
                          padding: "6px 8px",
                          margin: "0 -8px",
                          borderRadius: 4,
                          transition: "background-color 150ms ease",
                          backgroundColor: isHovered ? "var(--color-ec-bg-elevated)" : "transparent",
                        }}
                      >
                        {/* Parameter Label */}
                        <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 6 }}>
                          <span
                            style={{
                              fontFamily: "var(--color-ec-sans)",
                              fontSize: 11,
                              fontWeight: 500,
                              color: "var(--color-ec-text-secondary)",
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {labelText}
                          </span>
                          <span
                            onMouseEnter={(e) => {
                              if (!containerRef.current) return;
                              const containerRect = containerRef.current.getBoundingClientRect();
                              const rect = e.currentTarget.getBoundingClientRect();
                              let text = PARAM_DESCRIPTIONS[param.key];
                              if (param.key === "pm_open") {
                                if (sectionId === "gap_day") {
                                  text = "mínimo precio en el que comienza el Premarket del día del gap";
                                } else if (sectionId === "gap_plus_1_day") {
                                  text = "mínimo precio en el que comienza el Premarket del día del Gap +1";
                                } else if (sectionId === "gap_plus_2_day") {
                                  text = "mínimo precio en el que comienza el Premarket del día del Gap +2";
                                }
                              }
                              // Estimar el ancho del tooltip basado en el largo del texto (entre 100px y 220px)
                              const estimatedWidth = Math.min(Math.max(text.length * 6.5 + 24, 100), 220);
                              const halfWidth = estimatedWidth / 2;
                              
                              let tooltipX = rect.left - containerRect.left + rect.width / 2;
                              const tooltipY = rect.top - containerRect.top - 6;
                              
                              const minMargin = 16;
                              if (tooltipX - halfWidth < minMargin) {
                                tooltipX = minMargin + halfWidth;
                              }
                              
                              const maxRight = containerRect.width - minMargin;
                              if (tooltipX + halfWidth > maxRight) {
                                tooltipX = maxRight - halfWidth;
                              }
                              
                              setActiveTooltip({
                                text,
                                x: tooltipX,
                                y: tooltipY,
                                width: estimatedWidth,
                              });
                              e.currentTarget.style.color = "var(--color-ec-text-primary)";
                              e.currentTarget.style.borderColor = "var(--color-ec-text-muted)";
                              e.currentTarget.style.backgroundColor = "var(--color-ec-bg-surface)";
                            }}
                            onMouseLeave={(e) => {
                              setActiveTooltip(null);
                              e.currentTarget.style.color = "var(--color-ec-text-muted)";
                              e.currentTarget.style.borderColor = "var(--color-ec-border)";
                              e.currentTarget.style.backgroundColor = "var(--color-ec-bg-elevated)";
                            }}
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
                              flexShrink: 0,
                              userSelect: "none",
                              transition: "all 150ms ease",
                            }}
                          >
                            ?
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
                                padding: `6px ${param.unit !== "$" ? "22px" : "8px"} 6px ${param.unit === "$" ? "18px" : "8px"}`,
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
        <div style={{ marginTop: 8, flexShrink: 0 }}>
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
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {/* Date Range Tag */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                backgroundColor: "rgba(216, 122, 61, 0.08)",
                border: "0.5px solid var(--color-ec-copper)",
                borderRadius: 4,
                padding: "4px 8px",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--color-ec-copper)",
                }}
              >
                Rango de dataset: <strong style={{ color: "var(--color-ec-text-primary)" }}>{dateFrom}</strong> a <strong style={{ color: "var(--color-ec-text-primary)" }}>{dateTo}</strong>
              </span>
            </div>

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
          onClick={() => {
            setTempName(name);
            setShowSaveModal(true);
          }}
          disabled={includedConditions.length === 0 || isSaving}
          style={{
            width: "100%",
            padding: "8px 0",
            borderRadius: 5,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.2,
            textTransform: "uppercase",
            cursor: isSaving ? "wait" : "pointer",
            border: "none",
            backgroundColor: "var(--color-ec-copper)",
            color: "var(--color-ec-copper-text)",
            fontFamily: "var(--color-ec-sans)",
            opacity: includedConditions.length === 0 || isSaving ? 0.5 : 1,
          }}
        >
          {isSaving ? "Guardando..." : "Guardar y Probar"}
        </button>
      </div>
      {showSaveModal && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            backgroundColor: "rgba(0,0,0,0.5)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 10000,
          }}
        >
          <div
            style={{
              backgroundColor: "var(--color-ec-bg-sidebar)",
              border: "0.5px solid var(--color-ec-border)",
              borderRadius: 8,
              padding: "20px",
              width: "280px",
              display: "flex",
              flexDirection: "column",
              gap: 16,
              boxShadow: "0 10px 25px rgba(0,0,0,0.5)",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span
                style={{
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--color-ec-text-high)",
                }}
              >
                Guardar Dataset
              </span>
              <span
                style={{
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 10,
                  color: "var(--color-ec-text-muted)",
                }}
              >
                Introduce el nombre del dataset para guardarlo:
              </span>
            </div>
            
            <input
              type="text"
              value={tempName}
              onChange={(e) => setTempName(e.target.value)}
              placeholder="Nombre del dataset..."
              autoFocus
              onFocus={(e) => e.target.select()}
              onKeyDown={(e) => {
                if (e.key === "Enter" && tempName.trim() && !isSaving) {
                  const finalName = tempName.trim();
                  setName(finalName);
                  setShowSaveModal(false);
                  handleSave(finalName);
                } else if (e.key === "Escape") {
                  setShowSaveModal(false);
                }
              }}
              style={{
                backgroundColor: "var(--color-ec-bg-elevated)",
                border: "0.5px solid var(--color-ec-border)",
                borderRadius: 5,
                padding: "8px 10px",
                fontFamily: "var(--color-ec-sans)",
                fontSize: 12,
                color: "var(--color-ec-text-primary)",
                outline: "none",
                width: "100%",
                boxSizing: "border-box",
              }}
            />

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={() => setShowSaveModal(false)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--color-ec-text-muted)",
                  cursor: "pointer",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  padding: "6px 12px",
                }}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => {
                  if (tempName.trim() && !isSaving) {
                    const finalName = tempName.trim();
                    setName(finalName);
                    setShowSaveModal(false);
                    handleSave(finalName);
                  }
                }}
                disabled={!tempName.trim() || isSaving}
                style={{
                  padding: "6px 12px",
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  cursor: "pointer",
                  border: "none",
                  backgroundColor: "var(--color-ec-copper)",
                  color: "var(--color-ec-copper-text)",
                  opacity: !tempName.trim() ? 0.5 : 1,
                }}
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}
      {activeTooltip && (
        <div
          style={{
            position: "absolute",
            top: activeTooltip.y,
            left: activeTooltip.x,
            transform: "translate(-50%, -100%)",
            backgroundColor: "var(--color-ec-bg-sidebar)",
            color: "var(--color-ec-text-primary)",
            border: "0.5px solid var(--color-ec-border)",
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: 10,
            fontStyle: "italic",
            lineHeight: 1.4,
            width: activeTooltip.width,
            zIndex: 9999,
            pointerEvents: "none",
            boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
            fontFamily: "var(--color-ec-sans)",
            transition: "opacity 150ms ease",
          }}
        >
          {activeTooltip.text}
        </div>
      )}
    </div>
  );
}
