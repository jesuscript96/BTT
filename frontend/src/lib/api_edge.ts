// Cliente del recorrido minuto a minuto (pestaña Edge).
//
// Es la única parte de la pestaña que pide algo al backend: el resto sale de los
// trades que ya están en pantalla. Se pide con un botón porque relee las velas
// de cada ticker-día y tarda.
import { apiRequest } from "./api";
import type { TradeRecord } from "./api_backtester";

export interface PuntoCurva { m: number; n: number; media: number; ee: number }
export interface ResumenDelta { n: number; media: number; ee: number }

export interface Recorrido {
  unidad: "R" | "%";
  periodos: string[];
  /** Minutos del día (0-1439) que se ofrecen como hora de salida. */
  horas: number[];
  curva: Record<string, PuntoCurva[]>;
  /** delta[periodo][horaA][horaB] = diferencia pareada de aguantar de A a B. */
  delta: Record<string, Record<string, Record<string, ResumenDelta>>>;
  /** Minutos desde la entrada hasta el máximo a favor: p25, p50, p75. */
  tiempo_mfe: Record<string, { n: number; p: number[] }>;
  trades_usados: number;
  sin_velas: number;
  horizonte: number;
}

/** Motivos de salida que la HORA de salida gobierna: solo esos se prolongan. */
const POR_TIEMPO = new Set(["EOD", "Time Limit"]);

/** Convierte un epoch en segundos al `YYYY-MM-DDTHH:MM:SS` naive que espera el
 *  backend. Las marcas del lago ya son hora de Nueva York sin zona, así que se
 *  leen en UTC para recuperar el reloj tal cual, sin desplazarlo. */
function tsNaive(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(0, 19);
}

export function pedirRecorrido(
  datasetId: string,
  trades: TradeRecord[],
  periodoDe: (t: TradeRecord) => string,
  unidad: "R" | "pct",
  signal?: AbortSignal,
): Promise<Recorrido> {
  const payload = trades
    .filter((t) => t.entry_time_epoch && t.exit_time_epoch && t.ticker && t.date)
    .map((t) => {
      const entrada = t.avg_entry_price || t.entry_price;
      const sl = t.stop_loss && t.stop_loss > 0 ? t.stop_loss : 0;
      return {
        ticker: t.ticker,
        fecha: t.date,
        entrada_ts: tsNaive(t.entry_time_epoch),
        salida_ts: tsNaive(t.exit_time_epoch),
        entrada,
        dir: t.direction,
        motivo: POR_TIEMPO.has(t.exit_reason) ? t.exit_reason : "",
        sl,
        sl_dist: sl && entrada ? (Math.abs(sl - entrada) / entrada) * 100 : 0,
        periodo: periodoDe(t),
      };
    });

  // `API_BASE` ya termina en /api (ver api.ts), así que la ruta va SIN él.
  return apiRequest<Recorrido>("/edge/recorrido", {
    method: "POST",
    body: JSON.stringify({ dataset_id: datasetId, trades: payload, unidad }),
    signal,
    timeoutMs: 600_000,
  });
}
