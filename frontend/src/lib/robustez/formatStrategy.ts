// Traduce una definicion de estrategia a texto legible para el desplegable de
// condiciones de la pagina de Robustez.
//
// El vocabulario (INDICATOR_LABELS / COMPARATOR_LABELS) se reutiliza del
// builder para que un indicador se llame igual en toda la app. La logica de
// formateo se reescribe aqui en vez de importarse porque en el Baul vive dentro
// del componente de pagina, no exportada; duplicar 30 lineas es preferible a
// refactorizar un fichero de 2.000 que ya funciona.

import { COMPARATOR_LABELS, INDICATOR_LABELS } from "@/components/strategy-builder/ConditionBuilder";

type AnyRec = Record<string, any>;

export function formatIndicator(ind: AnyRec | number | null | undefined): string {
  if (ind == null) return "";
  if (typeof ind === "number") return String(ind);
  const params: string[] = [];
  const push = (label: string, v: unknown, suffix = "") => {
    if (v != null && v !== "") params.push(`${label}:${v}${suffix}`);
  };
  push("P", ind.period);
  push("P2", ind.period2);
  push("P3", ind.period3);
  push("SD", ind.stdDev);
  push("Lookback", ind.days_lookback, "d");
  push("ORB", ind.orb_minutes, "m");
  push("Elapsed", ind.elapsed_minutes, "m");
  if (typeof ind.ap_session === "string" && ind.ap_session) params.push(ind.ap_session.replace("ap.", ""));
  if (ind.band_line) params.push(String(ind.band_line));
  if (ind.macd_line) params.push(String(ind.macd_line));

  const offsetStr = ind.offset != null && ind.offset > 0 ? `[t-${ind.offset}]` : "";
  const paramsStr = params.length ? `(${params.join(", ")})` : "";
  const nameStr = ind.name ? INDICATOR_LABELS[ind.name] || ind.name : "Variable";
  return `${nameStr}${paramsStr}${offsetStr}`;
}

export function formatCondition(cond: AnyRec | null | undefined): string {
  if (!cond) return "";
  if (cond.type === "indicator_comparison") {
    const src = formatIndicator(cond.source);
    const cmp = COMPARATOR_LABELS[cond.comparator] || cond.comparator || "=";
    const tgt = typeof cond.target === "number" ? String(cond.target) : formatIndicator(cond.target);
    return `${src} ${cmp} ${tgt}`;
  }
  if (cond.type === "price_level_distance") {
    const src = formatIndicator(cond.source);
    const cmp = cond.comparator === "DISTANCE_GT" ? ">" : "<";
    const lvl = formatIndicator(cond.level);
    const pos = cond.position && cond.position !== "any" ? ` (${cond.position})` : "";
    return `${src} dist ${cmp} ${cond.value_pct}% a ${lvl}${pos}`;
  }
  return "";
}

export interface FlatCondition {
  depth: number;
  operator: string;
  text: string;
}

/** Aplana el arbol de condiciones conservando el nivel y el operador del grupo. */
export function flattenConditions(group: AnyRec | null | undefined, depth = 0): FlatCondition[] {
  if (!group || !Array.isArray(group.conditions)) return [];
  const op = group.operator || "AND";
  const out: FlatCondition[] = [];
  for (const c of group.conditions) {
    if (c?.type === "group") {
      out.push(...flattenConditions(c, depth + 1));
    } else {
      const text = formatCondition(c);
      if (text) out.push({ depth, operator: op, text });
    }
  }
  return out;
}

/** Reglas del universo (filtros de candidatos), ya vienen casi legibles. */
export function formatUniverseRule(rule: AnyRec): string {
  const cmp = COMPARATOR_LABELS[rule?.operator] || rule?.operator || "=";
  const val = rule?.value ?? "";
  return `${rule?.metric ?? "?"} ${cmp} ${val}`;
}

const RISK_UNITS: Record<string, string> = {
  Percentage: "%",
  Fixed: "$",
  ATR: "ATR",
};

/** Resumen de la gestion de riesgo en lineas etiqueta/valor. */
export function riskLines(rm: AnyRec | null | undefined): Array<[string, string]> {
  if (!rm) return [];
  const lines: Array<[string, string]> = [];
  const unit = (t?: string) => RISK_UNITS[t || ""] || t || "";

  if (rm.use_hard_stop && rm.hard_stop) {
    lines.push(["Hard stop", `${rm.hard_stop.value} ${unit(rm.hard_stop.type)}`]);
  } else {
    lines.push(["Hard stop", "desactivado"]);
  }

  if (rm.use_take_profit && rm.take_profit) {
    lines.push(["Take profit", `${rm.take_profit.value} ${unit(rm.take_profit.type)} (${rm.take_profit_mode || "Full"})`]);
  }

  if (Array.isArray(rm.partial_take_profits) && rm.partial_take_profits.length) {
    lines.push([
      "TP parciales",
      rm.partial_take_profits.map((p: AnyRec) => `${p.capital_pct}% a +${p.distance_pct}%`).join(" · "),
    ]);
  }

  if (rm.trailing_stop?.active) {
    lines.push(["Trailing stop", `${rm.trailing_stop.buffer_pct} ${unit(rm.trailing_stop.type)}`]);
  }

  lines.push([
    "Reentradas",
    rm.accept_reentries ? `si (max ${rm.max_reentries < 0 ? "sin limite" : rm.max_reentries})` : "no",
  ]);

  if (rm.swing_option?.active) lines.push(["Swing", String(rm.swing_option.target_day)]);
  if (rm.max_drawdown_daily) lines.push(["DD diario max", String(rm.max_drawdown_daily)]);

  return lines;
}
