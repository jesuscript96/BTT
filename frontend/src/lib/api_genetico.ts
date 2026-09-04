// Cliente de la pagina Genetico (/genetico).
//
// El backend solo prepara y lanza corridas (proceso aparte) y devuelve los
// JSON que ese proceso deja en disco. Sondear el progreso NO toca DuckDB.
import { apiRequest } from "./api";

export interface IndicadorCatalogo {
  nombre: string;
  /** Grupo al que va en la pantalla: una de las claves de `familias`. */
  familia: string;
  /** Una línea de qué hace y para qué sirve. Se enseña al pasar por encima. */
  ayuda: string;
  /** Si viene marcado al abrir la página. Solo los siete de la v1: marcar
   *  los 26 dispararía el espacio de búsqueda. */
  por_defecto: boolean;
  params: Record<string, Array<string | number | null>>;
  valores: number[];
  objetivos: string[];
  comparadores: string[];
}

/** Guarda fija: va delante de TODAS las condiciones y no la busca el genético.
 *  Las define el catálogo del backend y no la página, para que añadir una sea
 *  tocar un solo sitio. */
export interface GuardaCatalogo {
  clave: string;
  indicador: string;
  etiqueta: string;
  comparador: string;
  ayuda: string;
}

export interface CatalogoGenetico {
  indicadores: IndicadorCatalogo[];
  familias: Array<{ clave: string; etiqueta: string }>;
  guardas: GuardaCatalogo[];
  stops: { pct: number[]; offset_pct: number[]; niveles: Record<string, string[]> };
  tps: {
    pct: number[]; hora: string[]; tiempo: number[];
    parcial_cierre: number[]; parcial_max: number;
  };
  fitness: Array<{ id: string; label: string }>;
  python: string;
  python_ok: boolean;
  dir_trabajo: string;
}

export interface CondicionMotor {
  type: "indicator_comparison";
  source: { name: string; offset: number };
  comparator: string;
  target: number;
  timeframe: "1m";
}

export interface RiesgoConfig {
  init_cash: number;
  risk_r: number;
  risk_type: "FIXED";
  fees: number;
  fee_type: "PERCENT";
  slippage: number;
  locates_cost: number;
  max_locates: number;
  size_by_sl: boolean;
  accept_reentries: boolean;
  max_reentries: number;
  /** STOP HÍBRIDO: por distancia al stop, pero con techo de exposición.
   *  Implica `size_by_sl` — sin él no iría por distancia y el techo quedaría
   *  puesto sin recortar nada. */
  hybrid_stop?: boolean;
  /** El peor movimiento en contra que quieres contemplar, en %. */
  hybrid_black_swan_pct?: number | null;
  /** Cuánto de la cuenta entera aceptas perder si eso pasa, en %. */
  hybrid_max_loss_pct?: number | null;
  /** Suelo del stop en %. Solo afecta al modo porcentaje: en el de estructura
   *  la distancia la pone el mercado. 0 = sin suelo. */
  stop_min_pct?: number;
  /** Objetivo mínimo en %. Solo afecta al modo porcentaje. 0 = sin mínimo. */
  tp_min_pct?: number;
  /** Deja que el genético pruebe take profits parciales. */
  tp_parciales?: boolean;
}

export interface ConfigCorrida {
  dataset_id: string;
  fecha_ini: string | null;
  fecha_fin: string | null;
  sesgo: "short" | "long";
  sesiones: string[];
  hora_ini: string | null;
  hora_fin: string | null;
  ventana_entrada: Array<{ from_time: string; to_time: string }> | null;
  guardas: CondicionMotor[];
  catalogo: string[];
  n_condiciones: number;
  stops: string[];
  tps: string[];
  riesgo: RiesgoConfig;
  fitness: string;
  min_trades: number;
  semilla: number;
  poblacion: number;
  generaciones: number;
  workers: number;
  paciencia: number;
}

export interface MetricasIndividuo {
  trades: number | null;
  avg_r: number | null;
  expectancy: number | null;
  pf: number | null;
  wr: number | null;
  max_dd: number | null;
  retorno: number | null;
  dd_return: number | null;
  sharpe: number | null;
  fitness: number;
  segundos: number;
  error?: string;
}

export interface Mejor {
  huella: string;
  fitness: number;
  receta: string;
  metricas: MetricasIndividuo;
  individuo: unknown;
  definicion: Record<string, unknown>;
}

export interface EstadoCorrida {
  estado: string;
  mensaje: string;
  generacion: number;
  generaciones: number;
  poblacion: number;
  evaluadas: number;
  unicas: number;
  segundos_por_eval: number;
  eta_segundos: number;
  inicio: number;
  actualizado: number;
  semilla: number;
  mejor: { huella: string; fitness: number; receta: string; metricas: MetricasIndividuo } | null;
  historial: Array<{ generacion: number; mejor: number; media: number; unicas: number; distintas_top: number }>;
}

export interface CorridaResumen {
  id: string;
  nombre: string;
  dataset_id: string | null;
  semilla: number | null;
  poblacion: number | null;
  generaciones: number | null;
  n_condiciones: number | null;
  estado: string;
  generacion: number;
  evaluadas: number;
  inicio: number | null;
  actualizado: number | null;
  mejor: EstadoCorrida["mejor"];
  vivo: boolean;
}

export interface CorridaDetalle {
  id: string;
  config: ConfigCorrida & { nombre?: string; dir_datos?: string };
  estado: Partial<EstadoCorrida>;
  mejores: Mejor[];
  datos: { pares: number; velas: number; primer_dia: string; ultimo_dia: string } | null;
  vivo: boolean;
  parada_pedida: boolean;
  log: string[];
  salida: string[];
}

export interface DatasetResumen {
  id: string;
  name: string;
  pair_count?: number;
  min_date?: string | null;
  max_date?: string | null;
}

export const getCatalogo = () => apiRequest<CatalogoGenetico>("/genetico/catalogo");
export const listarDatasets = () => apiRequest<DatasetResumen[]>("/data/datasets");
export const listarCorridas = () => apiRequest<CorridaResumen[]>("/genetico/corridas", { timeoutMs: 10_000 });
export const verCorrida = (id: string) =>
  apiRequest<CorridaDetalle>(`/genetico/corridas/${encodeURIComponent(id)}`, { timeoutMs: 10_000 });
export const crearCorrida = (config: ConfigCorrida, nombre?: string) =>
  apiRequest<{ id: string; pid: number; pares_dataset: number }>("/genetico/corridas", {
    method: "POST",
    body: JSON.stringify({ config, nombre }),
    timeoutMs: 60_000,
  });
export const pararCorrida = (id: string) =>
  apiRequest<{ ok: boolean }>(`/genetico/corridas/${encodeURIComponent(id)}/parar`, { method: "POST" });
export const reanudarCorrida = (id: string) =>
  apiRequest<{ ok: boolean }>(`/genetico/corridas/${encodeURIComponent(id)}/reanudar`, { method: "POST" });
export const borrarCorrida = (id: string) =>
  apiRequest<{ ok: boolean }>(`/genetico/corridas/${encodeURIComponent(id)}`, { method: "DELETE" });

/** Guarda un finalista como estrategia normal (mismo endpoint que el boton
 *  «guardar» del panel) para abrirlo en el Backtester y comprobarlo. */
export const guardarComoEstrategia = (nombre: string, descripcion: string, definicion: Record<string, unknown>, datasetId: string) =>
  apiRequest<{ id: string }>("/strategies/", {
    method: "POST",
    body: JSON.stringify({ ...definicion, name: nombre, description: descripcion, dataset_id: datasetId }),
  });
