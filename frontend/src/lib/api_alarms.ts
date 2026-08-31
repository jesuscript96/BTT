/**
 * Cliente de la API de alarmas del Screener.
 *
 * Es una feature interna: no pasa por el gateway comercial. Todo va autenticado
 * con el token de Clerk y el backend filtra por dueño; el frontend nunca manda
 * un user_id.
 */
import { apiRequest, API_BASE } from "./api";
import { getClerkToken } from "./clerk_token";

export type AlarmFieldKind = "instant" | "bar";

export interface AlarmFieldDef {
  key: string;
  label: string;
  kind: AlarmFieldKind;
  unit: string;
  help: string;
}

export interface AlarmOperatorDef {
  key: string;
  label: string;
  bar_only?: boolean;
}

export interface AlarmCatalog {
  fields: AlarmFieldDef[];
  operators: AlarmOperatorDef[];
}

/** Una condición: `left` siempre es un campo; `right` es un número o el nombre de otro campo. */
export interface AlarmCondition {
  left: string;
  op: string;
  right: number | string;
}

export interface AlarmDefinition {
  conditions: AlarmCondition[];
  universe?: AlarmCondition[];
  watchlist?: string[];
  window?: { from?: string; to?: string } | null;
  cooldown?: { max_per_ticker_per_day?: number; min_minutes_between?: number } | null;
  sizing?: {
    stop_ref?: string;
    stop_offset_pct?: number;
    stop_pct?: number;
    risk_usd?: number;
    notional_usd?: number;
    locate_package_cost?: number;
  } | null;
  channels?: { browser?: boolean; telegram?: boolean; sound?: boolean } | null;
  /** Lo calcula el backend a partir de los campos usados; el usuario no lo elige. */
  mode?: AlarmFieldKind;
}

export interface Alarm {
  id: string;
  name: string;
  enabled: boolean;
  side: "long" | "short";
  definition: AlarmDefinition;
  created_at?: string;
  updated_at?: string;
}

export interface AlarmEvent {
  id: string;
  alarm_id: string;
  ticker: string;
  session_date: string;
  fired_at: string;
  price: number | null;
  payload: Record<string, unknown>;
}

export interface TelegramStatus {
  configured: boolean;
  link: { chat_id: string; username: string | null; linked_at: string; broken: boolean } | null;
}

export const getAlarmCatalog = () => apiRequest<AlarmCatalog>("/alarms/catalog");

export const listAlarms = () =>
  apiRequest<{ alarms: Alarm[] }>("/alarms").then((r) => r.alarms);

export const createAlarm = (body: {
  name: string; side: string; enabled: boolean; definition: AlarmDefinition;
}) => apiRequest<Alarm>("/alarms", { method: "POST", body: JSON.stringify(body) });

export const updateAlarm = (id: string, body: Partial<{
  name: string; side: string; enabled: boolean; definition: AlarmDefinition;
}>) => apiRequest<Alarm>(`/alarms/${id}`, { method: "PUT", body: JSON.stringify(body) });

export const deleteAlarm = (id: string) =>
  apiRequest<{ deleted: boolean }>(`/alarms/${id}`, { method: "DELETE" });

export const listAlarmEvents = (sessionDate?: string) =>
  apiRequest<{ events: AlarmEvent[] }>(
    `/alarms/events/list${sessionDate ? `?session_date=${sessionDate}` : ""}`,
  ).then((r) => r.events);

export interface ReplaySignal {
  ticker: string;
  price: number | null;
  fired_minute: string;
  reasons: string[];
  sizing: Record<string, number | undefined>;
  message: string;
}

export interface ReplayResult {
  ticker: string;
  date: string;
  mode: string;
  bars: number;
  prev_close: number | null;
  entered_universe: boolean;
  signals: ReplaySignal[];
  delivered?: boolean;
  note: string;
}

/**
 * Pasa un día real por el motor y devuelve lo que HABRÍA avisado.
 * No es un backtest: no simula ejecuciones ni calcula rendimiento.
 */
export const replayAlarm = (id: string, ticker: string, date: string, deliver = false) =>
  apiRequest<ReplayResult>(`/alarms/${id}/replay`, {
    method: "POST",
    body: JSON.stringify({ ticker, date, deliver }),
    timeoutMs: 60_000,
  });

export const getTelegramStatus = () => apiRequest<TelegramStatus>("/alarms/telegram/status");

export const createTelegramLink = () =>
  apiRequest<{ url: string; expires_at: string; ttl_minutes: number }>(
    "/alarms/telegram/link", { method: "POST" },
  );

export const unlinkTelegram = () =>
  apiRequest<{ unlinked: boolean }>("/alarms/telegram/link", { method: "DELETE" });

export const sendTelegramTest = () =>
  apiRequest<{ sent: boolean }>("/alarms/telegram/test", { method: "POST" });

/** Evento que el backend empuja por WS cuando salta una alarma. */
export interface LiveAlarmEvent {
  type: "alarm" | "hello";
  alarm_name?: string;
  ticker?: string;
  side?: string;
  price?: number | null;
  reasons?: string[];
  sizing?: Record<string, unknown>;
  mode?: string;
  fired_minute?: string;
  sound?: boolean;
}

/**
 * Abre el canal de alarmas en vivo. El token va por query porque un WebSocket
 * del navegador no admite cabeceras propias; el backend lo verifica igual que
 * una petición normal y de ahí saca a quién pertenecen los avisos.
 */
export async function openAlarmsSocket(
  onEvent: (e: LiveAlarmEvent) => void,
): Promise<WebSocket | null> {
  const token = await getClerkToken();
  const base = API_BASE.replace(/^http/, "ws");
  const url = `${base}/alarms/live${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  try {
    const ws = new WebSocket(url);
    ws.onmessage = (ev) => {
      try {
        onEvent(JSON.parse(ev.data));
      } catch {
        /* mensaje ilegible: se ignora */
      }
    };
    return ws;
  } catch {
    return null;
  }
}
