/**
 * El catálogo de filtros de UNIVERSO, en un solo sitio.
 *
 * Lo usan tres pantallas con aspectos muy distintos:
 *   - `InlineDatasetBuilder` (Backtester), que crea datasets.
 *   - `InlineStrategyBuilder` («Añadir filtro de mercado» del constructor de
 *     estrategias; hasta 2026-10-01 tenía su propia lista y se quedó sin los
 *     filtros nuevos).
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
  /** «Hora inicio gap»: el usuario escribe HORA ("05:00" o "ayer 18:00") y
   *  construirFiltros la convierte a t antes de mandarla al backend. */
  valorHora?: boolean;
  /** «Hora de cruce de gap»: además de la hora, la condición lleva `pct`
   *  (20-200, de 5 en 5) y `tramo` (PMH / RTH). Ver reglasCruce(). */
  cruce?: boolean;
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
  // Filtro «Hora de cruce de gap» (5.2-bis; rediseñado 2026-10-01 a petición
  // de Álvaro): UNA sola entrada; el % y el tramo se eligen en la propia fila.
  // Propiedad del DÍA del gap (sección gap_day). Columna gap_start_min_<pct>.
  { key: "gap_cross", label: "Hora de cruce de gap", unit: "h", placeholder: "08:00", valorHora: true, cruce: true },
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
  days_since_first_day:
    "Días entre el día del gap y el PRIMER DÍA del ticker en el lago. Es un PROXY de la IPO, no la IPO real: el lago empieza en 2019, así que lo listado antes de 2019 llega con la edad recortada (un ticker de 2015 aparece como «~N años» según 2019). Criterio 6.1 del Bloque 6: los recién listados son los mejores trades de la 1B (monótono: <30 d +10 % → >5 y +2 %) y el 2B lo replica. Úsalo para PRIORIZAR poder de compra, no para excluir (los viejos también ganan).",
};

DESCRIPCIONES_UNIVERSO.gap_cross =
  "Hora del PRIMER minuto en que el MÁXIMO del precio cruza +X % sobre el cierre de ayer. Eliges el % (20-200, de 5 en 5) y el tramo: PMH = el cruce ocurrió en el premarket (o en el after-hours de la víspera, hasta las 09:29); RTH = el cruce ocurrió en sesión regular (09:30-15:59). Ej.: PMH +20 % ≥ 08:00 = «antes de las 8 ni siquiera había subido un 20 %». Es el PRIMER cruce del día: si cruzó en PM, no tiene cruce RTH. Sin cruce = sin dato (no pasa). ⚠️ LOOK-AHEAD: la estrategia debe entrar DESPUÉS del cruce (p. ej. exigiendo «PM High Gap % ≥ X» en la vela de entrada).";

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
  /** number; con «Hora de cruce» puede llegar la cadena "05:00" o
   *  "ayer 18:00" tal cual (construirFiltros la convierte a t). */
  val1: number | string;
  val2?: number | string;
  /** Solo Gap -1: "include" = los ticker-día SIN dato (IPO, recién llegada,
   *  ventana inválida) pasan la regla en vez de excluirse. Sin valor = excluir
   *  (comportamiento de siempre). */
  missing?: "include";
  /** Solo «Hora de cruce de gap». */
  pct?: number;
  tramo?: TramoCruce;
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
      gap_cross: "gap_start_min",  // + _<pct> en reglasCruce
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

/** ¿Este parámetro se escribe en HORA y viaja como t (min desde las 16:00 de
 *  la víspera)? La familia «Hora de cruce» entera. */
export const esValorHora = (paramKey: string) =>
  paramKey === "gap_cross" || paramKey.startsWith("gap_start_");
export const esCruce = (paramKey: string) => paramKey === "gap_cross";

// ── «Hora de cruce de gap» ───────────────────────────────────────────────
// Tabla gap_start.parquet (scripts/construir_gap_start.py): t del PRIMER cruce
// del máximo sobre +pct %, línea continua 16:00 víspera → 16:00 de hoy.
// PMH = t ≤ 1049 (≤ 09:29) · RTH = t ≥ 1050 (≥ 09:30).
export type TramoCruce = "PMH" | "RTH";
export const NIVELES_CRUCE: number[] = Array.from({ length: 37 }, (_, i) => 20 + i * 5);
const T_FIN_PMH = 1049;

/** Error legible o null. `t` ya convertido con parseHoraGapStart. */
export function errorCruce(pct: number, tramo: TramoCruce, ts: (number | null)[]): string | null {
  if (!NIVELES_CRUCE.includes(pct)) return "El % debe ser 20-200, de 5 en 5";
  for (const t of ts) {
    if (t === null || Number.isNaN(t)) return "Hora: HH:MM (o «ayer 18:00»)";
    if (tramo === "PMH" && t > T_FIN_PMH) return "PMH: hora hasta las 09:29";
    if (tramo === "RTH" && t <= T_FIN_PMH) return "RTH: hora desde las 09:30";
  }
  return null;
}

/** Reglas del backend para un cruce. Todas llevan `cruce` (lo ignora el
 *  backend; sirve para pintar y borrar el grupo entero). La regla de tramo
 *  va marcada `cruce_limite` y no se pinta. */
export function reglasCruce(pct: number, tramo: TramoCruce, op: OperadorUniverso,
                            t1: number, t2?: number): any[] {
  const metric = `gap_start_min_${pct}`;
  const cruce = { pct, tramo, id: `${metric}_${tramo}_${Date.now().toString(36)}` };
  const r = (operator: string, value: number, extra = {}) =>
    ({ metric, operator, valueType: "static", value: String(value), cruce, ...extra });
  const opName = { ">=": "GREATER_THAN_OR_EQUAL", "<=": "LESS_THAN_OR_EQUAL",
                   ">": "GREATER_THAN", "<": "LESS_THAN" } as const;
  const out = op === "between"
    ? [r("GREATER_THAN_OR_EQUAL", t1), r("LESS_THAN_OR_EQUAL", t2!)]
    : [r(opName[op], t1)];
  out.push(tramo === "PMH"
    ? r("LESS_THAN_OR_EQUAL", T_FIN_PMH, { cruce_limite: true })
    : r("GREATER_THAN", T_FIN_PMH, { cruce_limite: true }));
  return out;
}

/** HORA del usuario -> t de la línea continua 16:00 víspera -> 16:00 del día.
 *  Acepta "05:00" / "12:30" (hoy, premarket o RTH), "ayer 18:00" / "18:00 ayer"
 *  (after-hours de la víspera, 16:00-19:59) y un número t directo
 *  (retrocompatibilidad: 780 = 05:00). Devuelve null si no lo puede
 *  interpretar. «16:00» a secas sigue siendo la víspera (t=0), como desde el
 *  29-sep; el cierre de HOY se escribe «15:59» o el t crudo 1439. */
export function parseHoraGapStart(v: string): number | null {
  const t = v.trim().toLowerCase();
  if (!t) return null;
  if (/^-?[0-9]+(\.[0-9]+)?$/.test(t)) return Number(t);
  const ayer = t.startsWith("ayer ") || t.endsWith(" ayer");
  const m = t.replace(/^ayer[ ]+/, "").replace(/[ ]+ayer$/, "").match(/^([0-9]{1,2}):([0-9]{2})$/);
  if (!m) return null;
  const h = Number(m[1]);
  const mm = Number(m[2]);
  if (mm > 59) return null;
  if (ayer) {
    if (h < 16 || h > 19) return null;
    return h * 60 + mm - 960;
  }
  // Hoy: premarket 04:00-09:59 y RTH 10:00-15:59 -> t = h*60+mm+480.
  if (h >= 4 && h <= 15) return h * 60 + mm + 480;
  if (h >= 16 && h <= 19) return h * 60 + mm - 960;
  return null;
}

/** Inversa de parseHoraGapStart: t -> "08:00" / "ayer 18:00" / "12:30" (para
 *  pintar reglas ya guardadas). Fuera de rango devuelve el t tal cual. */
export function horaDeGapStart(t: number): string {
  const hhmm = (min: number) =>
    `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
  if (t >= 0 && t < 240) return `ayer ${hhmm(t + 960)}`;
  // 720 = 04:00 … 1439 = 15:59 (la ventana del día llega hasta las 16:00)
  if (t >= 720 && t < 1440) return hhmm(t - 480);
  return String(t);
}

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
    if (esCruce(c.paramKey)) {
      const t1 = typeof c.val1 === "string" ? parseHoraGapStart(c.val1) : c.val1;
      const t2 = c.val2 === undefined ? undefined
        : typeof c.val2 === "string" ? parseHoraGapStart(c.val2) : c.val2;
      const tramo = c.tramo ?? "PMH";
      const err = errorCruce(c.pct ?? NaN, tramo, c.op === "between" ? [t1, t2 ?? null] : [t1]);
      // Nunca filtrar en silencio: una condición mal formada revienta aquí.
      if (err) throw new Error(`Hora de cruce de gap: ${err}`);
      rules.push(...reglasCruce(c.pct!, tramo, c.op, t1!, t2 ?? undefined));
      continue;
    }
    const fieldName = campoDeRegla(c.section, c.paramKey);
    if (!fieldName) continue;
    const isVol = esVolumen(c.paramKey);
    // «Hora inicio gap»: la hora del usuario ("05:00" / "ayer 18:00") viaja
    // al backend ya convertida a t. Si no se puede interpretar, se manda TAL
    // CUAL: el backend reventara ruidosamente antes que filtrar en silencio.
    const v1raw = esValorHora(c.paramKey) && typeof c.val1 === "string"
      ? (parseHoraGapStart(c.val1) ?? c.val1)
      : c.val1;
    // Igual para el segundo valor del «entre»: "05:00" -> t (parseFloat se
    // comería los ':' y mandaría 5).
    const v2raw = esValorHora(c.paramKey) && typeof c.val2 === "string"
      ? (parseHoraGapStart(c.val2) ?? c.val2)
      : c.val2;
    const v1 = isVol ? Number(v1raw) * 1_000_000 : v1raw;
    const v2 = c.val2 !== undefined && isVol ? Number(v2raw) * 1_000_000 : v2raw;
    // "Si falta el dato: incluir" — viaja como clave `missing` en cada regla
    // Gap -1; el backend la traduce a (condición OR columna IS NULL).
    const missing = c.section === "gap_prev_day" && c.missing === "include"
      ? { missing: "include" as const } : {};

    if (c.op === "between") {
      rules.push({ metric: fieldName, operator: "GREATER_THAN_OR_EQUAL", valueType: "static", value: v1.toString(), ...missing });
      rules.push({ metric: fieldName, operator: "LESS_THAN_OR_EQUAL", valueType: "static", value: v2!.toString(), ...missing });
      if (c.section === "gap_day") {
        if (c.paramKey === "gap_pct") { min_gap_pct = Number(v1); max_gap_pct = Number(v2); }
        else if (c.paramKey === "pm_volume") min_pm_volume = Number(v1);
        else if (c.paramKey === "rth_volume") min_rth_volume = Number(v1);
      }
    } else {
      const opName = {
        ">=": "GREATER_THAN_OR_EQUAL", "<=": "LESS_THAN_OR_EQUAL",
        ">": "GREATER_THAN", "<": "LESS_THAN",
      }[c.op];
      rules.push({ metric: fieldName, operator: opName, valueType: "static", value: v1.toString(), ...missing });
      if (c.section === "gap_day") {
        if (c.paramKey === "gap_pct") {
          if (c.op === ">=" || c.op === ">") min_gap_pct = Number(v1);
          if (c.op === "<=" || c.op === "<") max_gap_pct = Number(v1);
        } else if (c.paramKey === "pm_volume" && (c.op === ">=" || c.op === ">")) {
          min_pm_volume = Number(v1);
        } else if (c.paramKey === "rth_volume" && (c.op === ">=" || c.op === ">")) {
          min_rth_volume = Number(v1);
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
  if (esCruce(c.paramKey)) {
    const base = `${SECCIONES_UNIVERSO[c.section]} · cruce ${c.tramo ?? "PMH"} +${c.pct} %`;
    if (c.op === "between") return `${base} entre ${c.val1} y ${c.val2}`;
    return `${base} ${{ ">=": "≥", "<=": "≤", ">": ">", "<": "<" }[c.op]} ${c.val1}`;
  }
  if (c.op === "between") return `${etq} entre ${c.val1}${u} y ${c.val2}${u}${sinDato}`;
  const signo = { ">=": "≥", "<=": "≤", ">": ">", "<": "<" }[c.op];
  return `${etq} ${signo} ${c.val1}${u}${sinDato}`;
}
