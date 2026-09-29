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
  // Filtro 1.6 del Bloque 1 (2026-09-25): solo tiene columna en Gap -1, por eso
  // `paramsDisponibles` no lo ofrece en las demás secciones.
  { key: "day_return_pct", label: "Day Return % (RTH, cierre vs apertura)", unit: "%", placeholder: "0.0" },
  // Filtro 3.2 del Bloque 3 (2026-09-27): igual que el 1.6, solo en Gap -1.
  { key: "ret_5d_pct", label: "Retorno 5 días % (cierre víspera vs 5 sesiones antes)", unit: "%", placeholder: "0.0" },
  // Filtro 6.1 del Bloque 6 (2026-09-27): propiedad del TICKER (día del gap,
  // no víspera). "Primer día en el lago" NO es la IPO real (el lago empieza
  // en 2019: lo listado antes llega con la edad truncada).
  { key: "days_since_first_day", label: "Días desde 1er día en lago (≈IPO, lago 2019+)", unit: "d", placeholder: "90" },
  // Paquete «estrategias nuevas» (2026-09-28, ORDEN §2): evidencia sólida en el
  // UNIVERSO aunque la 1B no la cobre — material para diseñar estrategias
  // distintas de la 1B. Solo en Gap -1 (son de la víspera).
  { key: "volusd_prev", label: "Vol. $ víspera (cierre×vol RTH)", unit: "$", placeholder: "5000000" },
  { key: "gappers_prev", label: "Gappers víspera (nº con PMH≥50 %)", unit: "nº", placeholder: "20" },
  { key: "wick_sup_prev", label: "Mecha superior víspera (% del rango)", unit: "%", placeholder: "40" },
  // Filtro «Hora de inicio del gap» (5.2-bis, ORDEN §3): propiedad del DÍA del
  // gap (sección gap_day). t = minutos desde las 16:00 de la víspera.
  { key: "gap_start_20", label: "Hora inicio gap +20 % (min desde 16:00; 780=05:00)", unit: "min", placeholder: "780" },
  { key: "gap_start_50", label: "Hora inicio gap +50 % (min desde 16:00; 780=05:00)", unit: "min", placeholder: "780" },
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
  day_return_pct:
    "Retorno intra-RTH del día ((cierre RTH − apertura RTH) / apertura RTH). Negativo = vela roja: en Gap -1 es la «víspera roja» del Bloque 1. NO es contra el cierre del día anterior.",
  ret_5d_pct:
    "Retorno del cierre de la víspera frente al cierre de 5 sesiones antes, en % (producto de los retornos diarios de esas 5 sesiones, con el cierre previo ajustado por splits). Criterio 3.2 del Bloque 3: «venía cayendo» (< 0) da más fade premarket. En la 1B se validó como herramienta de SIZING (más peso a «venía cayendo»); en DT y 2B no aportaba.",
  volusd_prev:
    "Volumen en DÓLARES del día anterior (cierre RTH × volumen RTH de la víspera). Criterio 2.4 del B2-bis: la víspera con poco dinero recorrido va con peores trades; el descriptor de liquidez más causal que hay (tramos del estudio: 0,25-10 M$). Para estrategias nuevas y prioridad de poder de compra.",
  gappers_prev:
    "Número de acciones que cerraron la VÍSPERA con PMH Gap ≥ 50 % (el «día caliente» del criterio 7.2a): víspera con >20 gappers → el fade del día sube a 35-40 % (8/8 años). Cuenta el lago entero (no el universo filtrado) y hereda el último día con gappers si la víspera no tuvo ninguno. La 2B ya cobra parte de esta señal.",
  wick_sup_prev:
    "Mecha superior de la vela de la VÍSPERA, en % del rango del día ((high − máx(apertura, cierre)) ÷ (high − low) × 100). Bloque 8: la víspera con rechazo arriba → el gap de hoy se desinfla ~6 pp más (7/8 años). Descriptor que ni la 1B ni la 2B cobran: para estrategias nuevas (fade tarde).",
  gap_start_20:
    "Minuto del PRIMER cruce de +20 % sobre el cierre de la víspera, en la línea continua 16:00 víspera → 09:30 (after-hours incluido): t = minutos desde las 16:00. TABLA: 240 = 20:00 víspera · 720 = 04:00 · 780 = 05:00 · 840 = 06:00 · 900 = 07:00 · 960 = 08:00 · 1049 = 09:29. «Empezó antes de las 05:00» = ≤ 780. Sin cruce ese día = sin dato (con «incluir sin dato» pasa la regla). ⚠️ SIN look-ahead SOLO si la estrategia entra DESPUÉS del cruce: exige p. ej. «PM High Gap % ≥ 20» en la vela de entrada (el máximo acumulado ya ≥ 20 % implica que el cruce ya ocurrió). Estudio 5.2-bis: el gap de madrugada deja ~33 % de fade vs ~24 % el tardío.",
  gap_start_50:
    "Igual que «Hora inicio gap +20 %» pero para el cruce de +50 %. Misma escala t desde las 16:00 (720 = 04:00, 780 = 05:00…). ⚠️ Mismo aviso de look-ahead: sin problemas solo si entras tras el cruce (p. ej. exigiendo PM High Gap % ≥ 50 en la vela, que es el universo clásico de estas estrategias).",
  days_since_first_day:
    "Días entre el día del gap y el PRIMER DÍA del ticker en el lago. Es un PROXY de la IPO, no la IPO real: el lago empieza en 2019, así que lo listado antes de 2019 llega con la edad recortada (un ticker de 2015 aparece como «~N años» según 2019). Criterio 6.1 del Bloque 6: los recién listados son los mejores trades de la 1B (monótono: <30 d +10 % → >5 y +2 %) y el 2B lo replica. Úsalo para PRIORIZAR poder de compra, no para excluir (los viejos también ganan).",
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
  /** Solo Gap -1: "include" = los ticker-día SIN dato (IPO, recién llegada,
   *  ventana inválida) pasan la regla en vez de excluirse. Sin valor = excluir
   *  (comportamiento de siempre). */
  missing?: "include";
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
      day_return_pct: "lag_day_return_pct_1",
      ret_5d_pct: "lag_ret5d_pct_1",
      volusd_prev: "lag_volusd_1",
      gappers_prev: "lag_gappers_prev_1",
      wick_sup_prev: "lag_wick_sup_1",
    }[paramKey] ?? "";
  }
  if (section === "gap_day") {
    // El día del gap va por ETIQUETA, no por columna: `_build_where_clause`
    // las traduce con su `field_map`. days_since_first_day viaja como nombre
    // de columna directo (passthrough, igual que las lag_*).
    return {
      rth_close: "Close Price", pm_open: "Min Open PM price",
      pmh_gap_pct: "PMH Gap %", pm_volume: "Premarket Volume",
      gap_pct: "Open Gap %", rth_volume: "EOD Volume",
      rth_range_pct: "RTH Range %",
      days_since_first_day: "days_since_first_day",
      gap_start_20: "gap_start_min_20",
      gap_start_50: "gap_start_min_50",
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

/** Parámetros que tienen columna real en una sección. Los que no (p. ej.
 *  Day Return % en Gap +1/+2, que no tiene LEAD) ni se ofrecen: una métrica
 *  sin columna se ignoraría en silencio al construir los filtros. */
export function paramsDisponibles(section: SeccionUniverso): ParametroUniverso[] {
  return PARAMETROS_UNIVERSO.filter((p) => campoDeRegla(section, p.key) !== "");
}

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
    // "Si falta el dato: incluir" — viaja como clave `missing` en cada regla
    // Gap -1; el backend la traduce a (condición OR columna IS NULL).
    const missing = c.section === "gap_prev_day" && c.missing === "include"
      ? { missing: "include" as const } : {};

    if (c.op === "between") {
      rules.push({ metric: fieldName, operator: "GREATER_THAN_OR_EQUAL", valueType: "static", value: v1.toString(), ...missing });
      rules.push({ metric: fieldName, operator: "LESS_THAN_OR_EQUAL", valueType: "static", value: v2!.toString(), ...missing });
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
      rules.push({ metric: fieldName, operator: opName, valueType: "static", value: v1.toString(), ...missing });
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
  const sinDato = c.missing === "include" ? " · sin dato: incluye" : "";
  if (c.op === "between") return `${etq} entre ${c.val1}${u} y ${c.val2}${u}${sinDato}`;
  const signo = { ">=": "≥", "<=": "≤", ">": ">", "<": "<" }[c.op];
  return `${etq} ${signo} ${c.val1}${u}${sinDato}`;
}
