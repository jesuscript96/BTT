// Tags de organización de estrategias (2026-09-23, petición de Álvaro).
//
// Dos familias:
//   · AUTOMÁTICOS: se derivan SIEMPRE de la definición (market_sessions,
//     scalping, pyramiding) y nunca se guardan — al editar la estrategia
//     se recalculan solos, no pueden quedar desactualizados.
//   · MANUALES: los que el usuario escribe (viven en la columna `tags`,
//     se modifican con PATCH /api/strategies/{id}/tags).
//
// Todas las funciones aceptan la DEFINICIÓN suelta (Record<string, unknown>),
// no el objeto Strategy: las estrategias llegan envueltas ({id, name,
// definition}) desde /data/strategies y planas desde /api/strategies, y los
// componentes ya resuelven `s.definition ?? s` para otros campos.

/** Sesiones RTH del mercado US (ET), para clasificar ventanas custom. */
const RTH_OPEN = "09:30";
const RTH_CLOSE = "16:00";

type Definition = Record<string, unknown> | null | undefined;

function sessionsOf(def: Definition): string[] {
  const s = def?.market_sessions;
  return Array.isArray(s) ? s.map(String) : [];
}

function str(def: Definition, key: string): string | undefined {
  const v = def?.[key];
  return typeof v === "string" ? v : undefined;
}

/** ¿La estrategia opera (al menos en parte) antes de la apertura? */
export function usaPremarket(def: Definition): boolean {
  const sessions = sessionsOf(def);
  if (sessions.includes("pre")) return true;
  if (sessions.includes("custom")) {
    const start = str(def, "custom_start_time") || RTH_OPEN;
    return start < RTH_OPEN;
  }
  return false;
}

/** ¿La estrategia opera (al menos en parte) en horario de mercado? */
export function usaRTH(def: Definition): boolean {
  const sessions = sessionsOf(def);
  if (sessions.includes("rth")) return true;
  if (sessions.includes("custom")) {
    const start = str(def, "custom_start_time") || RTH_OPEN;
    const end = str(def, "custom_end_time") || RTH_CLOSE;
    return end > RTH_OPEN && start < RTH_CLOSE;
  }
  return false;
}

export type SessionGroup = "premarket" | "rth" | "conjunta" | "otras";

/** Grupo de sesión para los rótulos del selector del backtester:
 *  PREMARKET / RTH / CONJUNTAS (pre+rth) / OTRAS (afterhours, custom pura). */
export function sessionGroup(def: Definition): SessionGroup {
  const pre = usaPremarket(def);
  const rth = usaRTH(def);
  if (pre && rth) return "conjunta";
  if (pre) return "premarket";
  if (rth) return "rth";
  return "otras";
}

/** Tags automáticos derivados de la definición, en orden fijo.
 *
 * `scalping` y `piramidación` se derivan de la PRESENCIA del bloque — regla
 * nº1 de ambos: la definición solo lleva la clave cuando la feature está
 * encendida (ver ScalpingConfig en types/strategy.ts y el serializador del
 * backend, que solo escribe `pyramiding`/`scalping` si existen). */
export function autoTags(def: Definition): string[] {
  const out: string[] = [];
  if (usaPremarket(def)) out.push("premarket");
  if (usaRTH(def)) out.push("rth");
  if (def?.scalping) out.push("scalping");
  const pyr = def?.pyramiding as { levels?: unknown[] } | undefined;
  if (pyr && Array.isArray(pyr.levels) && pyr.levels.length > 0) {
    out.push("piramidación");
  }
  return out;
}

/** Tags manuales saneados para mostrar (el backend ya los sanea al guardar;
 *  esto es solo defensivo contra payloads viejos). */
export function manualTags(tags: string[] | null | undefined): string[] {
  return (tags || []).filter((t) => typeof t === "string" && t.trim() !== "");
}

/** Todos los tags de una estrategia (automáticos primero, para que el chip
 *  cobre siempre salga en el mismo sitio), para filtros y buscadores. */
export function allTags(def: Definition, tags: string[] | null | undefined): string[] {
  return [...autoTags(def), ...manualTags(tags)];
}
