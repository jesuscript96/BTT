// Tramos de PRECIO del «EV por rango» (17-sep-2026). Son los mismos que
// `locates_gate.RANGOS_PRECIO_EV` del backend: el backtest, el portfolio en
// crudo, la pestaña Charts y el cuadro de mandos del bot tienen que mirar el
// MISMO tramo para el mismo precio, o el veredicto de la app y el del /evf se
// separan sin que nada avise. `hi` null = sin techo.

export interface EvRango {
  lo: number;
  hi: number | null;
  ev_pct: number | null;
}

export const RANGOS_PRECIO_EV: Array<[number, number | null]> = [
  [0, 0.5], [0.5, 1], [1, 3], [3, 5], [5, 10], [10, null],
];

const f = (x: number) => String(x).replace(".", ",");

/** «0 – 0,5 $», «> 10 $». */
export function etiquetaRango(lo: number, hi: number | null): string {
  return hi == null ? `> ${f(lo)} $` : `${f(lo)} – ${f(hi)} $`;
}

/** Las 6 casillas (texto) -> la lista que entiende el backend. Vacío = sin EV
 *  en ese tramo: el backend cae al EV «completo» que reciba con la lista. En
 *  el cuadro de mandos ese completo es el EV de la estrategia; en el backtest
 *  «por rango» no viaja ninguno (0), asi que en un tramo vacio NO se entra. */
export function rangosDesdeCasillas(casillas: string[]): EvRango[] {
  return RANGOS_PRECIO_EV.map(([lo, hi], k) => {
    const v = Number(String(casillas[k] ?? "").replace(",", "."));
    return { lo, hi, ev_pct: Number.isFinite(v) && v > 0 ? v : null };
  });
}

/** La lista del backend -> las 6 casillas (texto), en el orden de los tramos. */
export function casillasDesdeRangos(rangos: EvRango[] | null | undefined): string[] {
  return RANGOS_PRECIO_EV.map(([lo]) => {
    const r = (rangos || []).find((x) => Math.abs(x.lo - lo) < 1e-9);
    return r && r.ev_pct != null && r.ev_pct > 0 ? String(r.ev_pct) : "";
  });
}

/** El tramo que contiene un precio. */
export function indiceRango(precio: number): number {
  const k = RANGOS_PRECIO_EV.findIndex(([lo, hi]) => precio >= lo && (hi == null || precio < hi));
  return k < 0 ? RANGOS_PRECIO_EV.length - 1 : k;
}
