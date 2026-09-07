/**
 * El catálogo de filtros de UNIVERSO, en un solo sitio.
 *
 * Lo usan dos pantallas con aspectos muy distintos:
 *   - `InlineDatasetBuilder` (Backtester), que crea datasets.
 *   - La página del Genético, que solo quiere los filtros y los pinta con su
 *     propio estilo.
 *
 * Vive aquí para que no haya DOS listas de métricas. Una lista duplicada no da
 * error: se queda corta en un sitio, el usuario no encuentra la métrica y no
 * hay forma de saber que faltaba — el patrón de las capas que ya se ha comido
 * este repo varias veces.
 *
 * `construirFiltros` devuelve EXACTAMENTE el objeto que espera el backend
 * (`_build_where_clause`), incluidos los campos «legacy» de nivel superior.
 */

export interface ParametroUniverso {
  key: string;
  label: string;
  unit: string;
  placeholder: string;
  min?: number;
}

export const PARAMETROS_UNIVERSO: ParametroUniverso[] = [
  { key: "rth_close", label: "Open price", unit: "$", placeholder: "0.00" },
  { key: "pm_open", label: "Open PM price", unit: "$", placeholder: "0.00" },
  { key: "pmh_gap_pct", label: "PM High Gap", unit: "%", placeholder: "0.0" },
  { key: "pm_volume", label: "Premarket total volume", unit: "M", placeholder: "0.0" },
  { key: "gap_pct", label: "Gap", unit: "%", placeholder: "0.0" },
  { key: "rth_volume", label: "RTH Total volume", unit: "M", placeholder: "0.0" },
  { key: "rth_range_pct", label: "Bar RTH Range", unit: "%", placeholder: "0.0" },
];

export const DESCRIPCIONES_UNIVERSO: Record<string, string> = {
  rth_close: "Precio de la acción en la apertura de mercado regular (Open price)",
  pm_open: "Precio de la acción en la apertura del Premarket (Open PM price)",
  pmh_gap_pct:
    "Porcentaje de cambio entre el precio de cierre de ayer (Previous Close) y el máximo alcanzado en el Premarket (Premarket High)",
  pm_volume: "Volumen total acumulado durante la sesión de premarket",
  gap_pct: "El porcentaje de Gap de apertura (Gap)",
  rth_volume:
    "Volumen total durante la sesión de mercado regular (RTH Total volume) - Especificado en millones (M)",
  rth_range_pct:
    "Rango de la vela en la sesión regular (máximo a mínimo o porcentaje de movimiento)",
};

export type SeccionUniverso =
  | "gap_prev_day"
  | "gap_day"
  | "gap_plus_1_day"
  | "gap_plus_2_day";

export const SECCIONES_UNIVERSO: Record<SeccionUniverso, string> = {
  gap_prev_day: "GAP-1 DAY",
  gap_day: "GAP DAY",
  gap_plus_1_day: "GAP+1 DAY",
  gap_plus_2_day: "GAP+2 DAY",
};

export type OperadorUniverso = ">=" | "<=" | ">" | "<" | "between";

export interface CondicionUniverso {
  section: SeccionUniverso;
  paramKey: string;
  op: OperadorUniverso;
  val1: number;
  val2?: number;
}

/** La columna real del lago para (sección, métrica). */
export function campoDeRegla(section: SeccionUniverso, paramKey: string): string {
  if (section === "gap_prev_day") {
    // Día anterior al gap (D-1): columnas lag_*_1
    return {
      rth_close: "lag_rth_close_1", pm_open: "lag_open_1",
      pmh_gap_pct: "lag_pmh_gap_pct_1", pm_volume: "lag_pm_volume_1",
      gap_pct: "lag_gap_pct_1", rth_volume: "lag_rth_volume_1",
      rth_range_pct: "lag_rth_range_pct_1",
    }[paramKey] ?? "";
  }
  if (section === "gap_day") {
    // El día del gap va por ETIQUETA, no por columna: `_build_where_clause`
    // las traduce con su `field_map`.
    return {
      rth_close: "Close Price", pm_open: "Min Open PM price",
      pmh_gap_pct: "PMH Gap %", pm_volume: "Premarket Volume",
      gap_pct: "Open Gap %", rth_volume: "EOD Volume",
      rth_range_pct: "RTH Range %",
    }[paramKey] ?? "";
  }
  const suf = section === "gap_plus_1_day" ? "_1" : "_2";
  return {
    rth_close: `lead_rth_close${suf}`, pm_open: `lead_open${suf}`,
    pmh_gap_pct: `lead_pmh_gap_pct${suf}`, pm_volume: `lead_pm_volume${suf}`,
    gap_pct: `lead_gap_pct${suf}`, rth_volume: `lead_rth_volume${suf}`,
    rth_range_pct: `lead_rth_range_pct${suf}`,
  }[paramKey] ?? "";
}

/** Los volúmenes se piden en MILLONES y viajan en unidades. */
export const esVolumen = (paramKey: string) =>
  paramKey === "pm_volume" || paramKey === "rth_volume";

/** El objeto de filtros que entiende el backend. */
export function construirFiltros(
  condiciones: CondicionUniverso[],
  dateFrom: string,
  dateTo: string,
): Record<string, unknown> {
  const rules: any[] = [];
  let min_gap_pct: number | undefined;
  let max_gap_pct: number | undefined;
  let min_pm_volume: number | undefined;
  let min_rth_volume: number | undefined;

  for (const c of condiciones) {
    const fieldName = campoDeRegla(c.section, c.paramKey);
    if (!fieldName) continue;
    const isVol = esVolumen(c.paramKey);
    const v1 = isVol ? c.val1 * 1_000_000 : c.val1;
    const v2 = c.val2 !== undefined && isVol ? c.val2 * 1_000_000 : c.val2;

    if (c.op === "between") {
      rules.push({ metric: fieldName, operator: "GREATER_THAN_OR_EQUAL", valueType: "static", value: v1.toString() });
      rules.push({ metric: fieldName, operator: "LESS_THAN_OR_EQUAL", valueType: "static", value: v2!.toString() });
      if (c.section === "gap_day") {
        if (c.paramKey === "gap_pct") { min_gap_pct = v1; max_gap_pct = v2; }
        else if (c.paramKey === "pm_volume") min_pm_volume = v1;
        else if (c.paramKey === "rth_volume") min_rth_volume = v1;
      }
    } else {
      const opName = {
        ">=": "GREATER_THAN_OR_EQUAL", "<=": "LESS_THAN_OR_EQUAL",
        ">": "GREATER_THAN", "<": "LESS_THAN",
      }[c.op];
      rules.push({ metric: fieldName, operator: opName, valueType: "static", value: v1.toString() });
      if (c.section === "gap_day") {
        if (c.paramKey === "gap_pct") {
          if (c.op === ">=" || c.op === ">") min_gap_pct = v1;
          if (c.op === "<=" || c.op === "<") max_gap_pct = v1;
        } else if (c.paramKey === "pm_volume" && (c.op === ">=" || c.op === ">")) {
          min_pm_volume = v1;
        } else if (c.paramKey === "rth_volume" && (c.op === ">=" || c.op === ">")) {
          min_rth_volume = v1;
        }
      }
    }
  }

  return {
    date_from: dateFrom, date_to: dateTo,
    start_date: dateFrom, end_date: dateTo,
    min_gap_pct, max_gap_pct, min_pm_volume, min_rth_volume,
    rules,
  };
}

/** Lectura humana de una condición, para las listas de resumen. */
export function leeCondicion(c: CondicionUniverso): string {
  const p = PARAMETROS_UNIVERSO.find((x) => x.key === c.paramKey);
  const etq = `${SECCIONES_UNIVERSO[c.section]} · ${p?.label ?? c.paramKey}`;
  const u = p?.unit ?? "";
  if (c.op === "between") return `${etq} entre ${c.val1}${u} y ${c.val2}${u}`;
  const signo = { ">=": "≥", "<=": "≤", ">": ">", "<": "<" }[c.op];
  return `${etq} ${signo} ${c.val1}${u}`;
}
