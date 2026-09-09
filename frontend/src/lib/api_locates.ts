// Banda de locates: Monte Carlo sobre el precio del locate, sin volver a correr.
import { apiRequest } from "./api";
import type { TradeRecord } from "./api_backtester";

export interface BandaLocates {
  fechas: string[];
  n_semillas: number;
  semilla_base: number;
  rango: { min: number; max: number };
  ticker_dias_con_locate: number;
  curvas: { p10: number[]; p50: number[]; p90: number[]; min: number[]; max: number[]; bruta: number[] };
  finales: number[];
  max_dd_pct: number[];
  facturas: number[];
  resumen: {
    final_p10: number; final_p50: number; final_p90: number; final_min: number; final_max: number;
    dd_mediana: number; dd_peor: number; dd_p95: number; factura_media: number; bruta_final: number;
  };
  actual: {
    semilla: number; curva: number[]; final: number; max_dd_pct: number; factura: number; percentil_final: number;
  } | null;
}

export function pedirBandaLocates(
  trades: TradeRecord[],
  initCash: number,
  minimo: number,
  maximo: number,
  nSemillas: number,
  semillaBase: number,
  semillaActual: number | null,
): Promise<BandaLocates> {
  const payload = trades.map((t) => ({
    ticker: t.ticker,
    fecha: t.date,
    size: t.size,
    dir: t.direction,
    // La referencia del sorteo es la primera vela del día; si la corrida no fue
    // aleatoria no la tenemos y se usa el precio de entrada, que anda cerca.
    precio_ref: t.locate_ref_price ?? t.avg_entry_price ?? t.entry_price,
    pnl: t.pnl,
  }));
  return apiRequest<BandaLocates>("/locates/banda", {
    method: "POST",
    body: JSON.stringify({
      trades: payload, init_cash: initCash, minimo, maximo,
      n_semillas: nSemillas, semilla_base: semillaBase, semilla_actual: semillaActual,
    }),
    timeoutMs: 300_000,
  });
}
