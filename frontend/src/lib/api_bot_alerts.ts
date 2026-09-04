/**
 * Cliente del cuadro de mandos del bot de alertas.
 *
 * Router backend: /api/bot-alerts (gated por BOT_ALERTS_ENABLED, apagado por
 * defecto; en produccion responde 503 y la pagina ni siquiera se lista).
 *
 * Las rutas van SIN /api: apiRequest ya lo anyade a la base.
 */
import { apiRequest } from "./api";

/* ── Estrategias vigiladas ────────────────────────────────────────────── */

export interface Ventana {
  inicio: string | null;
  fin: string | null;
}

export interface EstrategiaCandidata {
  strategy_id: string;
  name: string;
  /** De qué cubo viene. Decide en qué tabla de avisos se pinta. */
  origen: "portfolio" | "incubadora";
  activa: boolean;
  riesgo_usd: number | null;
  bias: string | null;
  /** Decide que SIGNIFICA el riesgo: perdida maxima (true) o capital (false). */
  size_by_sl: boolean;
  /** Stop hibrido: por SL pero con techo de exposicion ante un evento de cola. */
  hybrid_stop?: boolean;
  hybrid_black_swan_pct?: number | null;
  hybrid_max_loss_pct?: number | null;
  /** Riesgo del ANYADIDO. null = usa lo que diga la estrategia. */
  riesgo_piramide_usd?: number | null;
  /** La cuenta real. Solo hace falta con stop hibrido, que sin ella no puede
   *  calcular su techo — y sin ella el backend no deja activar. */
  capital_usd?: number | null;
  /** Si la estrategia piramida: decide si se pide el riesgo del anyadido. */
  piramida?: boolean;
  hard_stop: Record<string, unknown> | null;
  ventana: Ventana;
  /** La ventana de ENTRADAS (`entry_time_windows`), que NO es la de sesion.
   *  Son capas distintas: la sesion dice que velas existen, esta cuando se
   *  puede ABRIR (entradas y piramides). */
  ventana_entradas?: { inicio: string | null; fin: string | null }[];
}

export function listarEstrategias(): Promise<EstrategiaCandidata[]> {
  return apiRequest<EstrategiaCandidata[]>("/bot-alerts/strategies");
}

export function guardarVigilancia(
  strategy_id: string,
  activa: boolean,
  riesgo_usd: number,
  extra?: { riesgo_piramide_usd?: number | null; capital_usd?: number | null },
): Promise<{ strategy_id: string; activa: boolean; riesgo_usd: number }> {
  return apiRequest("/bot-alerts/watch", {
    method: "POST",
    // Los opcionales solo se mandan si tienen valor: `null` y "no dicho" son
    // cosas distintas en el backend, y mandar 0 pareceria una decision.
    body: JSON.stringify({
      strategy_id, activa, riesgo_usd,
      ...(extra?.riesgo_piramide_usd ? { riesgo_piramide_usd: extra.riesgo_piramide_usd } : {}),
      ...(extra?.capital_usd ? { capital_usd: extra.capital_usd } : {}),
    }),
  });
}

/** Lo que el motor hace DE VERDAD con una estrategia, frente a lo que dice su
 *  JSON. `inactivo` es la parte que importa: configuracion guardada que NO se
 *  aplica, y por que. */
export interface ExplicacionEstrategia {
  name: string;
  sesion: { sesiones: string[]; desde?: string | null; hasta?: string | null };
  entradas: { condiciones: string[]; timeframe: string | null; ventanas: string[] };
  dimensionado: { modo: string; size_by_sl: boolean };
  salidas: string[];
  reentradas: string;
  piramidacion: { accion: string; cantidad: string; veces: number; condiciones: string[] }[];
  universo: string[];
  no_vigilable_en_vivo: string[];
  inactivo: { que: string; valor: string; por_que: string }[];
}

export function explicarEstrategia(id: string): Promise<ExplicacionEstrategia> {
  return apiRequest<ExplicacionEstrategia>(`/bot-alerts/strategies/${id}/explicacion`);
}

/** Borra la configuracion que el motor NO aplica. NO cambia el comportamiento:
 *  se quita lo que ya se ignoraba. Lo que desaparece es la posibilidad de
 *  resucitarla sin querer cambiando otro campo. */
export function limpiarInactivo(id: string): Promise<{ quitado: string[]; detalle?: string }> {
  return apiRequest(`/bot-alerts/strategies/${id}/limpiar-inactivo`, { method: "POST" });
}

/* ── Avisos ───────────────────────────────────────────────────────────── */

export interface EventoAlerta {
  id: string;
  fecha: string;
  momento: string;
  tipo: "entrada" | "piramide" | "salida";
  ticker: string;
  strategy_id: string;
  estrategia: string | null;
  direccion: string | null;
  precio: number | null;
  acciones: number | null;
  stop: number | null;
  riesgo_usd: number | null;
  motivo: string | null;
  nivel: number | null;
  accion_piramide: string | null;
  posicion_total: number | null;
  /** Cubo de la estrategia que lo genero, para separar las dos tablas. */
  origen: "portfolio" | "incubadora";
  /**
   * 'vivo' o 'reproduccion'. Un aviso de reproduccion es indistinguible de uno
   * real sin esta marca, y dentro de un mes no habria forma de saber si el bot
   * aviso de verdad ese dia o fue una prueba.
   */
  modo: "vivo" | "reproduccion";
  /**
   * 'prealerta' mientras la vela se está formando, 'alerta' cuando cierra y
   * se confirma, 'descartada' cuando cerró y la señal se cayó. Los tres
   * comparten id: la fila se transforma en el sitio en vez de duplicarse.
   *
   * Un descarte NO se avisa por Telegram (sería ruido): se ve aquí y basta.
   */
  estado: "prealerta" | "alerta" | "descartada";
}

export function listarEventos(fecha?: string, limite = 500): Promise<{ eventos: EventoAlerta[] }> {
  const q = new URLSearchParams();
  if (fecha) q.set("fecha", fecha);
  q.set("limite", String(limite));
  return apiRequest(`/bot-alerts/eventos?${q.toString()}`);
}

export function listarFechas(): Promise<{ fechas: string[] }> {
  return apiRequest("/bot-alerts/fechas");
}

export function limpiarEventos(antes_de: string): Promise<{ borrados: number }> {
  return apiRequest(`/bot-alerts/eventos?antes_de=${encodeURIComponent(antes_de)}`, {
    method: "DELETE",
  });
}

/* ── Estado del bot ───────────────────────────────────────────────────── */

export interface EstadoTelegram {
  ok: boolean;
  detalle: string;
  enviando?: boolean;
  bot?: string;
  chat_id?: string;
}

export interface EstadoBot {
  vigilando: boolean;
  /** Ultima senal de vida. Sin esto no se distingue apagado de colgado. */
  latido_at: string | null;
  tickers_seguidos: number;
  fuente: string | null;
  detalle: string | null;
  telegram: EstadoTelegram;
}

export function leerEstado(): Promise<EstadoBot> {
  return apiRequest<EstadoBot>("/bot-alerts/estado");
}

/* ── Radar ────────────────────────────────────────────────────────────── */

export interface CandidatoRadar {
  ticker: string;
  /** De qué estrategia viene la vigilancia: un ticker puede entrar por varias. */
  estrategia: string;
  /** Qué regla lo trajo, p. ej. "PM High Gap %", y cuánto vale ahora. */
  metrica: string;
  valor: number;
  precio: number;
  volumen: number;
  prev_close: number;
  /** Si el bot lo está evaluando, o solo lo ve pasar porque el cupo está lleno. */
  seguido: boolean;
}

export interface Radar {
  candidatos: CandidatoRadar[];
  actualizado: string | null;
}

export function leerRadar(): Promise<Radar> {
  return apiRequest<Radar>("/bot-alerts/radar");
}

export function cambiarEstado(vigilando: boolean): Promise<EstadoBot> {
  return apiRequest("/bot-alerts/estado", {
    method: "POST",
    body: JSON.stringify({ vigilando }),
  });
}

/* ── Calculo de acciones en vivo ──────────────────────────────────────── */

/**
 * Acciones al precio ACTUAL, no al del aviso.
 *
 * El aviso se emite al cierre de la vela de la senal; para cuando se pone la
 * orden el precio se ha movido (medido: 0,5% de media, hasta 6% en los dias
 * malos). Con el numero congelado del aviso, el riesgo real deja de ser el
 * pedido. Esta es la misma cuenta del motor, rehecha con el precio de ahora.
 */
export function accionesAlPrecio(
  riesgo: number | null,
  precio: number | null,
  stop: number | null,
  sizeBySl: boolean,
): number | null {
  if (!riesgo || !precio || precio <= 0) return null;
  if (sizeBySl && stop != null) {
    const distancia = Math.abs(precio - stop);
    if (distancia > 0) return riesgo / distancia;
  }
  return riesgo / precio;
}
