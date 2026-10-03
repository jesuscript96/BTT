/**
 * Cliente de la pestaña «Ejecución»: el bot de ejecución en DAS.
 *
 * Router backend: /api/bot-das (mismo interruptor que el bot de alertas,
 * BOT_ALERTS_ENABLED). El bot no habla con el backend: lee un fichero firmado
 * (el «cuadro») cada segundo. Estos endpoints leen su estado (latidos, foto,
 * diario) y reescriben el cuadro validándolo antes.
 *
 * Las rutas van SIN /api: apiRequest ya lo añade a la base.
 */
import { ApiError, apiRequest } from "./api";

export interface LatidoProceso {
  vivo: boolean;
  edad_s: number | null;
  ultimo: string | null;
}

export interface PosicionDas {
  ticker: string;
  neta_das: number | null;
  neta_fills: number | null;
  avg_das: string | null;
  estado: string | null;
  motivo: string | null;
  lotes: number;
  cisne_negro: boolean;
}

export interface OrdenDas {
  token: string; ticker: string; lado: string; tipo: string; qty: number; llenas: number;
  precio: string | null; stop: string | null; estado: string; proposito: string;
}

export interface FotoDas {
  fase: string | null;
  hora_et: string | null;
  vigilando: boolean | null;
  pausa_global: boolean | null;
  control_humano: boolean | null;
  version_config: number | null;
  posiciones: PosicionDas[];
  ordenes: OrdenDas[];
  locates: Array<Record<string, unknown>>;
  gasto_locates_dia: number | null;
  locates_tope_dia: boolean | null;
  equity: number | null;
  bp: number | null;
  das_conectado: boolean | null;
  feed_edad_s: number | null;
  modos_degradados: string[];
  parado: boolean | null;
  sombra: boolean | null;
  todo_vivo: boolean | null;
}

export interface EstrategiaCuadro {
  strategy_id: string;
  name: string;
  origen: string | null;
  ejecutar: boolean;
  riesgo_usd: number | null;
  riesgo_piramide_usd: number | null;
  ev_pct: number | null;
  motivo_no_ejecuta?: string | null;
}

export interface CuadroDas {
  config_version: number;
  sha256: string;
  generado_at: string | null;
  generado_por: string | null;
  fase: "sombra" | "canario" | "real" | string;
  vigilando: boolean;
  pausar_entradas: boolean;
  estrategias: EstrategiaCuadro[];
  locates: { tope_gasto_dia_usd: number | null };
  halts: { silencio: boolean | null };
  stops: Record<string, unknown>;
  rutas: Record<string, unknown> | null;
}

export interface AvisoDas {
  t: string | null;
  proceso: string | null;
  tipo: string;
  nivel: number | null;
  ticker: string | null;
  texto: string;
}

export interface EstadoDas {
  dir_bot: string;
  ruta_cuadro: string;
  latidos: Record<string, LatidoProceso>;
  /** Algún proceso del bot (ejecutor o vigilante) late. */
  encendido: boolean;
  /** Encendido y vigilando o con posiciones: el bot ignoraría las hojas que no son «en caliente». */
  bloquea_no_calientes: boolean;
  ultimo_latido: string | null;
  foto: FotoDas | null;
  foto_edad_s: number | null;
  avisos: AvisoDas[];
  cuadro: CuadroDas | null;
  cuadro_error: string | null;
}

export interface CambioCuadro {
  config_version?: number;
  vigilando?: boolean;
  estrategias?: Array<{ strategy_id: string; ejecutar?: boolean; riesgo_usd?: number | null; ev_pct?: number | null }>;
  locates?: { tope_gasto_dia_usd: number };
  halts?: { silencio: boolean };
}

export interface RespuestaCambio {
  ok: boolean;
  escrito: boolean;
  config_version: number;
  cambios: Array<{ ruta: string; antes: unknown; despues: unknown }>;
}

export interface ResumenExportar {
  ok: boolean;
  config_version: number;
  estrategias: number;
  ejecutan: number;
  nuevas: string[];
  quitadas: string[];
  cambios: string[];
  avisos: string[];
}

export function leerEstadoDas(): Promise<EstadoDas> {
  return apiRequest<EstadoDas>("/bot-das/estado");
}

export function cambiarCuadro(cambio: CambioCuadro): Promise<RespuestaCambio> {
  return apiRequest<RespuestaCambio>("/bot-das/cuadro", { method: "PUT", body: JSON.stringify(cambio) });
}

export function exportarCuadro(): Promise<ResumenExportar> {
  return apiRequest<ResumenExportar>("/bot-das/exportar", { method: "POST", timeoutMs: 60_000 });
}

/** El 422 del backend trae {mensaje, errores}; apiRequest solo sabe formatear textos y listas de pydantic. */
export function mensajeError(err: unknown, porDefecto: string): string {
  if (err instanceof ApiError) {
    const d = err.detail as { mensaje?: string; errores?: string[] } | string | undefined;
    if (d && typeof d === "object" && !Array.isArray(d) && d.mensaje) {
      const errores = Array.isArray(d.errores) ? d.errores.slice(0, 6).join(" · ") : "";
      return errores ? `${d.mensaje} ${errores}` : d.mensaje;
    }
    return err.message || porDefecto;
  }
  return (err as Error)?.message || porDefecto;
}
