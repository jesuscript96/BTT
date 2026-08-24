// El lado REAL del bloque de perdidas: lo que de verdad ocurrio, con las mismas
// definiciones que usa el bootstrap para que las dos columnas sean comparables.
//
// Se calcula en el navegador por lo mismo que `analytics.ts`: son unos miles de
// trades y un par de barridos O(n), y asi el panel responde al instante cuando
// se mueve un slider.

import type { EquityPointT, RobustezTrade } from "@/lib/api_robustez";

export interface Muestra {
  n: number;
  mean: number;
  median: number;
  worst: number;
  best: number;
}

export interface LadoReal {
  /** PnL de cada unidad (sesion o trade), en dolares. */
  valores: number[];
  todo: Muestra;
  ganancias: Muestra;
  perdidas: Muestra;
  winRatePct: number;
  /** Racha maxima de unidades perdedoras seguidas. */
  rachaMax: number;
}

export interface RealLossStats {
  porDia: LadoReal;
  porTrade: LadoReal;
  /** Peor sesion en % del capital con el que abrio ese dia. */
  peorDiaPct: number;
  peorDiaUsd: number;
  peorDiaFecha: string | null;
  /**
   * Fraccion de la equity de apertura que cada sesion llego a perder en su peor
   * momento, segun el MAE de sus trades. Alineado con `porDia.valores`.
   */
  maeFracs: number[];
  /** PnL por sesion en R o en $, segun el modelo, listo para el bootstrap. */
  tradesPorDia: number[];
  fechas: string[];
}

function resume(xs: number[]): Muestra {
  if (!xs.length) return { n: 0, mean: 0, median: 0, worst: 0, best: 0 };
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return {
    n: s.length,
    mean: xs.reduce((a, b) => a + b, 0) / s.length,
    median: s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2,
    worst: s[0],
    best: s[s.length - 1],
  };
}

function rachaPerdedora(xs: number[]): number {
  let acc = 0;
  let best = 0;
  for (const v of xs) {
    if (v < 0) {
      acc += 1;
      if (acc > best) best = acc;
    } else if (v > 0) {
      acc = 0;
    }
    // Un cero no rompe la racha ni suma: mismo criterio que analytics.streaks.
  }
  return best;
}

function lado(valores: number[]): LadoReal {
  const ganancias = valores.filter((v) => v > 0);
  const perdidas = valores.filter((v) => v < 0);
  return {
    valores,
    todo: resume(valores),
    ganancias: resume(ganancias),
    perdidas: resume(perdidas),
    winRatePct: valores.length ? (ganancias.length / valores.length) * 100 : 0,
    rachaMax: rachaPerdedora(valores),
  };
}

/**
 * Equity con la que ABRIO cada sesion.
 *
 * Misma logica que `attach_precise_r` en el backend: el motor dimensiona las
 * posiciones de una sesion sobre el balance con el que empieza el dia, asi que
 * el denominador correcto para pasar dolares a % es ese, no el cierre.
 */
function aperturaPorDia(equity: EquityPointT[], initCash: number): Map<string, number> {
  const out = new Map<string, number>();
  let prev = initCash;
  for (const p of equity) {
    const dia = new Date(p.time * 1000).toISOString().slice(0, 10);
    if (!out.has(dia)) out.set(dia, prev);
    prev = p.value;
  }
  return out;
}

export function realLossStats(
  trades: RobustezTrade[],
  equity: EquityPointT[],
  initCash: number,
): RealLossStats {
  const aperturas = aperturaPorDia(equity, initCash);

  const pnlDia = new Map<string, number>();
  const maeDia = new Map<string, number>();
  const nDia = new Map<string, number>();

  for (const t of trades) {
    const d = t.date;
    pnlDia.set(d, (pnlDia.get(d) || 0) + (t.pnl ?? 0));
    nDia.set(d, (nDia.get(d) || 0) + 1);
    // MAE viene en % POSITIVO sobre el precio de entrada (ver portfolio_sim.py).
    // A dolares: % x precio de entrada x acciones. Se suman los del dia, que es
    // la cota pesimista: supone que todos tocaron su peor punto a la vez.
    const maeUsd = ((t.mae ?? 0) / 100) * (t.entry_price ?? 0) * (t.size ?? 0);
    maeDia.set(d, (maeDia.get(d) || 0) + (Number.isFinite(maeUsd) ? maeUsd : 0));
  }

  const fechas = Array.from(pnlDia.keys()).sort();
  const valoresDia = fechas.map((d) => pnlDia.get(d) || 0);
  const tradesPorDia = fechas.map((d) => nDia.get(d) || 0);

  const maeFracs = fechas.map((d) => {
    const apertura = aperturas.get(d) ?? initCash;
    if (!(apertura > 0)) return 0;
    return Math.max(0, (maeDia.get(d) || 0) / apertura);
  });

  let peorDiaUsd = 0;
  let peorDiaPct = 0;
  let peorDiaFecha: string | null = null;
  fechas.forEach((d, i) => {
    const v = valoresDia[i];
    if (v < peorDiaUsd) {
      peorDiaUsd = v;
      peorDiaFecha = d;
      const apertura = aperturas.get(d) ?? initCash;
      peorDiaPct = apertura > 0 ? (v / apertura) * 100 : 0;
    }
  });

  return {
    porDia: lado(valoresDia),
    porTrade: lado(trades.map((t) => t.pnl ?? 0)),
    peorDiaUsd,
    peorDiaPct,
    peorDiaFecha,
    maeFracs,
    tradesPorDia,
    fechas,
  };
}

/**
 * Probabilidad, en %, de que un valor de la muestra sea <= umbral.
 *
 * Modelo: ECDF empirica, sin ninguna hipotesis de distribucion. No se asume
 * normalidad —los retornos de trading tienen colas gordas y una normal las
 * subestima justo donde importa—, solo se cuenta que fraccion de los casos
 * observados quedo por debajo.
 */
export function probMenorOIgual(muestra: number[], umbral: number): number {
  if (!muestra.length) return 0;
  let k = 0;
  for (const v of muestra) if (v <= umbral) k += 1;
  return (k / muestra.length) * 100;
}

/**
 * Lo mismo, pero sobre una rejilla de cuantiles ya ordenada (la que manda el
 * backend). La rejilla son 501 puntos equiespaciados en probabilidad: buscar
 * donde encaja el umbral e interpolar da la probabilidad directamente, sin
 * necesidad de recibir las 50.000 simulaciones.
 */
export function probEnRejilla(rejilla: number[], umbral: number): number {
  const n = rejilla.length;
  if (!n) return 0;
  if (umbral <= rejilla[0]) return 0;
  if (umbral >= rejilla[n - 1]) return 100;

  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (rejilla[mid] <= umbral) lo = mid;
    else hi = mid;
  }
  const span = rejilla[hi] - rejilla[lo];
  const frac = span > 0 ? (umbral - rejilla[lo]) / span : 0;
  return ((lo + frac) / (n - 1)) * 100;
}

/**
 * Misma forma que `realLossStats` pero a partir de una serie DIARIA ya
 * agregada, sin lista de trades.
 *
 * Lo usa el Monte Carlo del portfolio: alli no hay trades individuales ni MAE,
 * solo el PnL de cada sesion del modelo combinado. Devolver la misma estructura
 * permite reutilizar tal cual el bloque de perdidas de robustez; los huecos
 * (por trade, MAE) quedan vacios y la interfaz los oculta sola.
 */
export function realLossStatsFromDaily(
  fechas: string[],
  pnlDiario: number[],
  equity: number[],
  initCash: number,
): RealLossStats {
  const valores = pnlDiario.map((v) => v ?? 0);

  let peorDiaUsd = 0;
  let peorDiaPct = 0;
  let peorDiaFecha: string | null = null;
  valores.forEach((v, i) => {
    if (v < peorDiaUsd) {
      peorDiaUsd = v;
      peorDiaFecha = fechas[i] ?? null;
      // Capital con el que abrio ese dia: el cierre del anterior.
      const apertura = i > 0 ? equity[i - 1] : initCash;
      peorDiaPct = apertura > 0 ? (v / apertura) * 100 : 0;
    }
  });

  return {
    porDia: lado(valores),
    porTrade: lado([]),
    peorDiaUsd,
    peorDiaPct,
    peorDiaFecha,
    maeFracs: [],
    tradesPorDia: [],
    fechas,
  };
}
