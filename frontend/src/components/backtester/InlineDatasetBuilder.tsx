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
  { key: "rth_close", label: "Open price", unit: "$", placeholder: "0.00" },
  { key: "pm_open", label: "Open PM price", unit: "$", placeholder: "0.00" },
  { key: "pmh_gap_pct", label: "PM High Gap", unit: "%", placeholder: "0.0" },
  { key: "pm_volume", label: "Premarket total volume", unit: "M", placeholder: "0.0" },
  { key: "gap_pct", label: "Gap", unit: "%", placeholder: "0.0" },
  { key: "rth_volume", label: "RTH Total volume", unit: "M", placeholder: "0.0" },
  { key: "rth_range_pct", label: "Bar RTH Range", unit: "%", placeholder: "0.0" },
];

const PARAM_DESCRIPTIONS: Record<string, string> = {
  rth_close: "Precio de la acción en la apertura de mercado regular (Open price)",
  pm_open: "Precio de la acción en la apertura del Premarket (Open PM price)",
  pmh_gap_pct: "Porcentaje de cambio entre el precio de cierre de ayer (Previous Close) y el máximo alcanzado en el Premarket (Premarket High)",
  pm_volume: "Volumen total acumulado durante la sesión de premarket",
  gap_pct: "El porcentaje de Gap de apertura (Gap)",
  rth_volume: "Volumen total durante la sesión de mercado regular (RTH Total volume) - Especificado en millones (M)",
  rth_range_pct: "Rango de la vela en la sesión regular (máximo a mínimo o porcentaje de movimiento)",
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
  op: string; // '>=', '<=', '>', '<', 'between'
  val1: number;
  val2?: number;
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
  const [values, setValues] = useState<Record<SectionId, Record<string, { op: string; val1: string; val2: string }>>>({
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

  const getParamValueObj = (section: SectionId, paramKey: string) => {
    return values[section][paramKey] || { op: ">=", val1: "", val2: "" };
  };

  const handleVal1Change = (section: SectionId, paramKey: string, val1: string) => {
    setValues((prev) => {
      const current = prev[section][paramKey] || { op: ">=", val1: "", val2: "" };
      return {
        ...prev,
        [section]: {
          ...prev[section],
          [paramKey]: { ...current, val1 },
        },
      };
    });
  };

  const handleVal2Change = (section: SectionId, paramKey: string, val2: string) => {
    setValues((prev) => {
      const current = prev[section][paramKey] || { op: ">=", val1: "", val2: "" };
      return {
        ...prev,
        [section]: {
          ...prev[section],
          [paramKey]: { ...current, val2 },
        },
      };
    });
  };

  const handleOpChange = (section: SectionId, paramKey: string, op: string) => {
    setValues((prev) => {
      const current = prev[section][paramKey] || { op: ">=", val1: "", val2: "" };
      return {
        ...prev,
        [section]: {
          ...prev[section],
          [paramKey]: { ...current, op },
        },
      };
    });
  };

  const toggleSection = (section: SectionId) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const getValidationError = (param: ParameterConfig, op: string, val1Str: string, val2Str: string): string | null => {
    if (!val1Str && !val2Str) return null;
    if (val1Str) {
      const val1 = parseFloat(val1Str);
      if (isNaN(val1)) return "Valor 1 inválido";
      if (param.min !== undefined && val1 < param.min) {
        return `Mínimo ${param.min}%`;
      }
    }
    if (op === "between") {
      if (!val1Str || !val2Str) return "Faltan valores";
      const val1 = parseFloat(val1Str);
      const val2 = parseFloat(val2Str);
      if (isNaN(val2)) return "Valor 2 inválido";
      if (val1 > val2) return "Mín > Máx";
    }
    return null;
  };

  const isConditionIncluded = (section: SectionId, paramKey: string) => {
    return includedConditions.some((c) => c.section === section && c.paramKey === paramKey);
  };

  const handleIncludeToggle = (section: SectionId, param: ParameterConfig) => {
    const obj = getParamValueObj(section, param.key);
    const { op, val1: val1Str, val2: val2Str } = obj;

    if (!val1Str && op !== "between") return;
    if (op === "between" && (!val1Str || !val2Str)) return;

    const error = getValidationError(param, op, val1Str, val2Str);
    if (error) return;

    const val1 = parseFloat(val1Str);
    const val2 = op === "between" ? parseFloat(val2Str) : undefined;
    const exists = isConditionIncluded(section, param.key);

    if (exists) {
      // Remove it
      setIncludedConditions((prev) =>
        prev.filter((c) => !(c.section === section && c.paramKey === param.key))
      );
    } else {
      // Add it
      setIncludedConditions((prev) => [
        ...prev,
        {
          section,
          paramKey: param.key,
          label: param.label,
          op,
          val1,
          val2,
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

      // Map to exact DuckDB/Parquet columns
      if (c.section === "gap_day") {
        if (c.paramKey === "rth_close") fieldName = "Close Price";
        else if (c.paramKey === "pm_open") fieldName = "Min Open PM price";
        else if (c.paramKey === "pmh_gap_pct") fieldName = "PMH Gap %";
        else if (c.paramKey === "pm_volume") fieldName = "Premarket Volume";
        else if (c.paramKey === "gap_pct") fieldName = "Open Gap %";
        else if (c.paramKey === "rth_volume") fieldName = "EOD Volume";
        else if (c.paramKey === "rth_range_pct") fieldName = "RTH Range %";
      } else {
        // GAP+1 or GAP+2
        const lagSuffix = c.section === "gap_plus_1_day" ? "_1" : "_2";
        if (c.paramKey === "rth_close") fieldName = `lead_rth_close${lagSuffix}`;
        else if (c.paramKey === "pm_open") fieldName = `lead_open${lagSuffix}`;
        else if (c.paramKey === "pmh_gap_pct") fieldName = `lead_pmh_gap_pct${lagSuffix}`;
        else if (c.paramKey === "pm_volume") fieldName = `lead_pm_volume${lagSuffix}`;
        else if (c.paramKey === "gap_pct") fieldName = `lead_gap_pct${lagSuffix}`;
        else if (c.paramKey === "rth_volume") fieldName = `lead_rth_volume${lagSuffix}`;
        else if (c.paramKey === "rth_range_pct") fieldName = `lead_rth_range_pct${lagSuffix}`;
      }

      if (fieldName) {
        const isVol = c.paramKey === "pm_volume" || c.paramKey === "rth_volume";
        const val1_mapped = isVol ? c.val1 * 1000000 : c.val1;
        const val2_mapped = (c.val2 !== undefined && isVol) ? c.val2 * 1000000 : c.val2;

        if (c.op === "between") {
          rules.push({
            metric: fieldName,
            operator: "GREATER_THAN_OR_EQUAL",
            valueType: "static",
            value: val1_mapped.toString(),
          });
          rules.push({
            metric: fieldName,
            operator: "LESS_THAN_OR_EQUAL",
            valueType: "static",
            value: val2_mapped!.toString(),
          });

          // Legacy filters (top-level properties)
          if (c.section === "gap_day") {
            if (c.paramKey === "gap_pct") {
              min_gap_pct = val1_mapped;
              max_gap_pct = val2_mapped;
            } else if (c.paramKey === "pm_volume") {
              min_pm_volume = val1_mapped;
            } else if (c.paramKey === "rth_volume") {
              min_rth_volume = val1_mapped;
            }
          }
        } else {
          let opName = "";
          if (c.op === ">=") opName = "GREATER_THAN_OR_EQUAL";
          else if (c.op === "<=") opName = "LESS_THAN_OR_EQUAL";
          else if (c.op === ">") opName = "GREATER_THAN";
          else if (c.op === "<") opName = "LESS_THAN";

          rules.push({
            metric: fieldName,
            operator: opName,
            valueType: "static",
            value: val1_mapped.toString(),
          });

          // Legacy filters (top-level properties)
          if (c.section === "gap_day") {
            if (c.paramKey === "gap_pct") {
              if (c.op === ">=" || c.op === ">") min_gap_pct = val1_mapped;
              if (c.op === "<=" || c.op === "<") max_gap_pct = val1_mapped;
            } else if (c.paramKey === "pm_volume" && (c.op === ">=" || c.op === ">")) {
              min_pm_volume = val1_mapped;
            } else if (c.paramKey === "rth_volume" && (c.op === ">=" || c.op === ">")) {
              min_rth_volume = val1_mapped;
            }
          }
        }
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
                    const obj = getParamValueObj(sectionId, param.key);
                    const validationErr = getValidationError(param, obj.op, obj.val1, obj.val2);
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
                          position: "relative",
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
                                  text = "Precio en el que comienza el Premarket del día del gap";
                                } else if (sectionId === "gap_plus_1_day") {
                                  text = "Precio en el que comienza el Premarket del día del Gap +1";
                                } else if (sectionId === "gap_plus_2_day") {
                                  text = "Precio en el que comienza el Premarket del día del Gap +2";
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
                          {/* Operator Selector */}
                          <select
                            value={obj.op}
                            onChange={(e) => handleOpChange(sectionId, param.key, e.target.value)}
                            disabled={included}
                            style={{
                              backgroundColor: "var(--color-ec-bg-elevated)",
                              border: "0.5px solid var(--color-ec-border)",
                              borderRadius: 5,
                              padding: "6px 20px 6px 8px",
                              fontFamily: "var(--color-ec-sans)",
                              fontSize: 11,
                              fontWeight: 500,
                              color: "var(--color-ec-text-primary)",
                              outline: "none",
                              cursor: "pointer",
                              opacity: included ? 0.6 : 1,
                              width: obj.op === "between" ? "135px" : "52px",
                              textAlign: "left",
                            }}
                          >
                            <option value=">=">&gt;=</option>
                            <option value="<=">&lt;=</option>
                            <option value=">">&gt;</option>
                            <option value="<">&lt;</option>
                            <option value="between">Entre dos valores</option>
                          </select>

                          {/* Inputs with unit suffix/prefix */}
                          {obj.op === "between" ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                              <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                                {param.unit === "$" && (
                                  <span style={{ position: "absolute", left: 8, fontSize: 11, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>$</span>
                                )}
                                <input
                                  type="number"
                                  step="any"
                                  value={obj.val1}
                                  placeholder="min"
                                  onChange={(e) => handleVal1Change(sectionId, param.key, e.target.value)}
                                  disabled={included}
                                  style={{
                                    backgroundColor: "var(--color-ec-bg-elevated)",
                                    border: `0.5px solid ${validationErr ? "var(--color-ec-loss)" : "var(--color-ec-border)"}`,
                                    borderRadius: 5,
                                    padding: `6px ${param.unit !== "$" ? "18px" : "8px"} 6px ${param.unit === "$" ? "18px" : "8px"}`,
                                    fontFamily: "var(--color-ec-sans)",
                                    fontSize: 11,
                                    fontWeight: 500,
                                    color: "var(--color-ec-text-primary)",
                                    outline: "none",
                                    width: 60,
                                    textAlign: "right",
                                    opacity: included ? 0.6 : 1,
                                  }}
                                />
                                {param.unit !== "$" && (!param.placeholder.includes("%") || obj.val1) && (
                                  <span style={{ position: "absolute", right: 6, fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>{param.unit}</span>
                                )}
                              </div>
                              <span style={{ fontFamily: "var(--color-ec-sans)", fontSize: 11, color: "var(--color-ec-text-secondary)" }}>y</span>
                              <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                                {param.unit === "$" && (
                                  <span style={{ position: "absolute", left: 8, fontSize: 11, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>$</span>
                                )}
                                <input
                                  type="number"
                                  step="any"
                                  value={obj.val2}
                                  placeholder="max"
                                  onChange={(e) => handleVal2Change(sectionId, param.key, e.target.value)}
                                  disabled={included}
                                  style={{
                                    backgroundColor: "var(--color-ec-bg-elevated)",
                                    border: `0.5px solid ${validationErr ? "var(--color-ec-loss)" : "var(--color-ec-border)"}`,
                                    borderRadius: 5,
                                    padding: `6px ${param.unit !== "$" ? "18px" : "8px"} 6px ${param.unit === "$" ? "18px" : "8px"}`,
                                    fontFamily: "var(--color-ec-sans)",
                                    fontSize: 11,
                                    fontWeight: 500,
                                    color: "var(--color-ec-text-primary)",
                                    outline: "none",
                                    width: 60,
                                    textAlign: "right",
                                    opacity: included ? 0.6 : 1,
                                  }}
                                />
                                {param.unit !== "$" && (!param.placeholder.includes("%") || obj.val2) && (
                                  <span style={{ position: "absolute", right: 6, fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>{param.unit}</span>
                                )}
                              </div>
                            </div>
                          ) : (
                            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                              {param.unit === "$" && (
                                <span style={{ position: "absolute", left: 8, fontSize: 11, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>$</span>
                              )}
                              <input
                                type="number"
                                step="any"
                                value={obj.val1}
                                placeholder={param.placeholder}
                                onChange={(e) => handleVal1Change(sectionId, param.key, e.target.value)}
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
                              {param.unit !== "$" && (!param.placeholder.includes("%") || obj.val1) && (
                                <span style={{ position: "absolute", right: 8, fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>{param.unit}</span>
                              )}
                            </div>
                          )}

                          {/* Include Button */}
                          <button
                            type="button"
                            onClick={() => handleIncludeToggle(sectionId, param)}
                            disabled={(!obj.val1 && obj.op !== "between") || (obj.op === "between" && (!obj.val1 || !obj.val2)) || !!validationErr}
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
                              opacity: ((!obj.val1 && obj.op !== "between") || (obj.op === "between" && (!obj.val1 || !obj.val2)) || !!validationErr) ? 0.3 : 1,
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
                    {c.label}{" "}
                    {c.op === "between" ? (
                      <>
                        entre{" "}
                        <strong style={{ color: "var(--color-ec-text-primary)" }}>
                          {c.unit === "$" ? `$${c.val1}` : `${c.val1}${c.unit}`}
                        </strong>{" "}
                        y{" "}
                        <strong style={{ color: "var(--color-ec-text-primary)" }}>
                          {c.unit === "$" ? `$${c.val2}` : `${c.val2}${c.unit}`}
                        </strong>
                      </>
                    ) : (
                      <>
                        {c.op}{" "}
                        <strong style={{ color: "var(--color-ec-text-primary)" }}>
                          {c.unit === "$" ? `$${c.val1}` : `${c.val1}${c.unit}`}
                        </strong>
                      </>
                    )}
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
