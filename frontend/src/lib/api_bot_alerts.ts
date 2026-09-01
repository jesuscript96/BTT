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
  hard_stop: Record<string, unknown> | null;
  ventana: Ventana;
}

export function listarEstrategias(): Promise<EstrategiaCandidata[]> {
  return apiRequest<EstrategiaCandidata[]>("/bot-alerts/strategies");
}

export function guardarVigilancia(
  strategy_id: string,
  activa: boolean,
  riesgo_usd: number,
): Promise<{ strategy_id: string; activa: boolean; riesgo_usd: number }> {
  return apiRequest("/bot-alerts/watch", {
    method: "POST",
    body: JSON.stringify({ strategy_id, activa, riesgo_usd }),
  });
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
   * 'prealerta' mientras la vela se esta formando, 'alerta' cuando cierra.
   * La misma fila pasa de una a otra: comparten id, asi que la confirmacion
   * actualiza la fila en vez de anyadir una nueva.
   */
  estado: "prealerta" | "alerta";
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
