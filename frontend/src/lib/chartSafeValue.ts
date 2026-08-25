// Blindaje de los valores que se pasan a lightweight-charts.
//
// POR QUE EXISTE: la libreria lanza una excepcion —no un aviso— si un punto se
// sale de ±90.071.992.547.409,91 (2^53/100, su limite de precision). Una
// estrategia que compone puede superarlo con total legitimidad: 1,0066x por
// operacion sobre 3.500 operaciones son 9,7e9 veces el capital inicial, y con
// 10.000$ de partida la curva llega a 96 billones. El backtest es correcto; lo
// que no puede ser es que al pintarlo se caiga la pagina ENTERA y el usuario se
// quede sin ver ni los trades ni las metricas.
//
// Se recorta y se AVISA. Nunca en silencio: un grafico que miente sobre el
// tamaño de la cuenta es peor que un grafico que no se pinta.

/** Limite duro de lightweight-charts (2^53/100). */
export const CHART_MAX_VALUE = 90_071_992_547_409.91;

/** Margen de seguridad: se recorta un poco por debajo del limite exacto. */
const TOPE = CHART_MAX_VALUE * 0.999;

/**
 * Deja el valor dentro del rango que la libreria acepta.
 *
 * Devuelve 0 para NaN/Infinity: un punto no finito tambien revienta la serie, y
 * es preferible un cero visible a una excepcion.
 */
export function safeChartValue(v: number): number {
  if (!Number.isFinite(v)) return 0;
  if (v > TOPE) return TOPE;
  if (v < -TOPE) return -TOPE;
  return v;
}

/** true si el valor tuvo que recortarse (para poder avisar en pantalla). */
export function excedeRangoGrafico(v: number): boolean {
  return !Number.isFinite(v) || Math.abs(v) > TOPE;
}

/**
 * Recorta una serie entera y dice si hubo que tocar algo.
 *
 * `puntos` se recorre una sola vez: estas series tienen miles de puntos y se
 * repintan en cada cambio de modo de vista.
 */
export function saneaSerie<T extends { value: number }>(
  puntos: T[],
): { datos: T[]; recortado: boolean } {
  let recortado = false;
  const datos = puntos.map((p) => {
    if (!excedeRangoGrafico(p.value)) return p;
    recortado = true;
    return { ...p, value: safeChartValue(p.value) };
  });
  return { datos, recortado };
}
