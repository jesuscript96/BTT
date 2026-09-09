// Cálculos de la pestaña Edge. Puro, sin React y sin red: todo sale de los
// trades que el motor ya devuelve.
//
// Dos avisos que gobiernan este fichero:
//
//  1. `return_pct` NO es el movimiento de precio. Es `pnl / capital_en_riesgo`
//     (`portfolio_sim.py`). Para los barridos de TP y SL hace falta el % que se
//     movió el PRECIO, y ese se reconstruye aquí en `movePct`.
//  2. `mae` y `mfe` son MAGNITUDES POSITIVAS en % sobre el precio de entrada, y
//     ya vienen orientadas por dirección (adversa / favorable). No llevan signo.

import type { TradeRecord } from "@/lib/api_backtester";

export type Modo = "anio" | "semestre" | "trimestre";
export type Unidad = "R" | "$";

/** Trade con los derivados que la pestaña necesita, calculados una sola vez. */
export interface TradeEdge {
  t: TradeRecord;
  periodo: string;
  mes: string;
  /** Valor del trade en la unidad elegida (R si la hay, si no $). */
  v: number;
  /** Movimiento del precio a favor, en % y CON signo (negativo = fue en contra). */
  movePct: number;
  /** Excursión favorable máxima, % positivo. */
  mfe: number;
  /** Excursión adversa máxima, % positivo. */
  mae: number;
  /** Distancia al stop en % del precio de entrada. 0 si el trade no llevaba. */
  slDist: number;
}

export function periodKey(fecha: string, modo: Modo): string {
  const [a, m] = fecha.split("-");
  const mes = Number(m);
  if (modo === "anio" || !mes) return a;
  if (modo === "semestre") return `${a} S${mes <= 6 ? 1 : 2}`;
  return `${a} T${Math.ceil(mes / 3)}`;
}

/** ¿Se puede trabajar en R? Solo si casi todos los trades traen `r_multiple`. */
export function unidadDisponible(trades: TradeRecord[]): Unidad {
  if (!trades.length) return "$";
  const conR = trades.reduce((n, t) => n + (t.r_multiple != null ? 1 : 0), 0);
  return conR / trades.length >= 0.9 ? "R" : "$";
}

export function preparar(trades: TradeRecord[], modo: Modo, unidad: Unidad): TradeEdge[] {
  const out: TradeEdge[] = [];
  for (const t of trades) {
    const entrada = t.avg_entry_price || t.entry_price;
    if (!entrada || !t.date) continue;
    const esLargo = (t.direction || "").toLowerCase().startsWith("l");
    const bruto = esLargo
      ? ((t.exit_price - entrada) / entrada) * 100
      : ((entrada - t.exit_price) / entrada) * 100;
    const sl = t.stop_loss && t.stop_loss > 0
      ? (Math.abs(t.stop_loss - entrada) / entrada) * 100
      : 0;
    out.push({
      t,
      periodo: periodKey(t.date, modo),
      mes: t.date.slice(0, 7),
      v: unidad === "R" ? (t.r_multiple ?? 0) : t.pnl,
      movePct: Number.isFinite(bruto) ? bruto : 0,
      mfe: Math.max(0, t.mfe ?? 0),
      mae: Math.max(0, t.mae ?? 0),
      slDist: Number.isFinite(sl) ? sl : 0,
    });
  }
  return out;
}

export function agrupar(filas: TradeEdge[]): Map<string, TradeEdge[]> {
  const m = new Map<string, TradeEdge[]>();
  for (const f of filas) {
    const g = m.get(f.periodo);
    if (g) g.push(f); else m.set(f.periodo, [f]);
  }
  return new Map([...m.entries()].sort((a, b) => a[0].localeCompare(b[0])));
}

/* ---- estadística ---- */

export const media = (xs: number[]) => (xs.length ? xs.reduce((p, c) => p + c, 0) / xs.length : 0);

export function desviacion(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = media(xs);
  return Math.sqrt(xs.reduce((p, c) => p + (c - m) * (c - m), 0) / (xs.length - 1));
}

/** Percentil por interpolación lineal. `p` en 0..1. */
export function percentil(ordenados: number[], p: number): number {
  if (!ordenados.length) return 0;
  const i = (ordenados.length - 1) * p;
  const lo = Math.floor(i), hi = Math.ceil(i);
  return lo === hi ? ordenados[lo] : ordenados[lo] + (i - lo) * (ordenados[hi] - ordenados[lo]);
}

export interface ResumenPeriodo {
  periodo: string;
  n: number;
  wr: number;
  ganMedia: number;
  perdMedia: number;
  expectancy: number;
  /** Error estándar de la expectancy. El intervalo es ±1,96·ee. */
  ee: number;
  lo: number;
  hi: number;
  pf: number;
  /** % del PnL total que aporta el decil superior de operaciones. */
  decilSup: number;
  /** Expectancy quitando el 1 % mejor. */
  sinMejor1: number;
  /** Cuántas operaciones hacen el 50 % del PnL positivo. */
  ops50: number;
  mfeP: number[];
  maeP: number[];
}

export function resumir(grupos: Map<string, TradeEdge[]>): ResumenPeriodo[] {
  const out: ResumenPeriodo[] = [];
  for (const [periodo, filas] of grupos) {
    const vs = filas.map((f) => f.v);
    const gan = vs.filter((v) => v > 0);
    const per = vs.filter((v) => v <= 0);
    const ee = desviacion(vs) / Math.sqrt(Math.max(1, vs.length));
    const e = media(vs);
    const sumaGan = gan.reduce((p, c) => p + c, 0);
    const sumaPer = Math.abs(per.reduce((p, c) => p + c, 0));

    // Concentración: siempre sobre el PnL en dinero, que es lo que se cobra.
    const pnls = filas.map((f) => f.t.pnl).sort((a, b) => b - a);
    const total = pnls.reduce((p, c) => p + c, 0);
    const nDecil = Math.max(1, Math.round(pnls.length * 0.1));
    const decilSup = total > 0
      ? (pnls.slice(0, nDecil).reduce((p, c) => p + c, 0) / total) * 100
      : 0;
    const n1 = Math.max(1, Math.round(pnls.length * 0.01));
    const ordenV = [...vs].sort((a, b) => b - a);
    const sinMejor1 = media(ordenV.slice(n1));
    let acum = 0, ops50 = 0;
    for (const p of pnls) {
      if (acum >= total / 2 || total <= 0) break;
      acum += p; ops50 += 1;
    }

    const mfes = filas.map((f) => f.mfe).sort((a, b) => a - b);
    const maes = filas.map((f) => f.mae).sort((a, b) => a - b);

    out.push({
      periodo,
      n: filas.length,
      wr: filas.length ? (gan.length / filas.length) * 100 : 0,
      ganMedia: media(gan),
      perdMedia: Math.abs(media(per)),
      expectancy: e,
      ee,
      lo: e - 1.96 * ee,
      hi: e + 1.96 * ee,
      pf: sumaPer > 0 ? sumaGan / sumaPer : Infinity,
      decilSup,
      sinMejor1,
      ops50,
      mfeP: [0.25, 0.5, 0.75, 0.9].map((p) => percentil(mfes, p)),
      maeP: [0.25, 0.5, 0.75, 0.9].map((p) => percentil(maes, p)),
    });
  }
  return out;
}

/* ---- oportunidad vs edge: serie mensual ---- */

export interface PuntoMes { mes: string; ops: number; media: number; ee: number }

/** Serie por mes con media móvil de `ventana` meses y su error estándar. */
export function serieMensual(filas: TradeEdge[], ventana = 6): PuntoMes[] {
  const porMes = new Map<string, number[]>();
  for (const f of filas) {
    const g = porMes.get(f.mes);
    if (g) g.push(f.v); else porMes.set(f.mes, [f.v]);
  }
  const meses = [...porMes.keys()].sort();
  return meses.map((mes, i) => {
    const trozo = meses.slice(Math.max(0, i - (ventana - 1)), i + 1)
      .flatMap((m) => porMes.get(m)!);
    return {
      mes,
      ops: porMes.get(mes)!.length,
      media: media(trozo),
      ee: desviacion(trozo) / Math.sqrt(Math.max(1, trozo.length)),
    };
  });
}

/* ---- barridos de TP y SL ---- */

export interface PuntoBarrido { x: number; v: number }

/**
 * Barrido de Take Profit. Si la excursión favorable llegó al x %, la operación
 * habría cerrado ahí; si no, acaba como acabó.
 *
 * En R hace falta la distancia REAL al stop de cada operación (el riesgo no
 * cambia al mover el TP). Sin `stop_loss` no hay R posible y se devuelve el
 * movimiento de precio en %.
 */
export function barridoTP(filas: TradeEdge[], enR: boolean, r: Rango): PuntoBarrido[] {
  const usables = enR ? filas.filter((f) => f.slDist > 0) : filas;
  const out: PuntoBarrido[] = [];
  const paso = Math.max(0.05, (r.hasta - r.desde) / 80);
  for (let x = r.desde; x <= r.hasta + 1e-9; x += paso) {
    let s = 0;
    for (const f of usables) {
      const move = f.mfe >= x ? x : f.movePct;
      s += enR ? move / f.slDist : move;
    }
    out.push({ x, v: usables.length ? s / usables.length : 0 });
  }
  return out;
}

/**
 * Barrido de Stop Loss. Si la excursión adversa llegó al x %, la operación
 * habría saltado ahí.
 *
 * OBLIGATORIAMENTE en R: con «Shares por distancia al SL», mover el stop mueve
 * el tamaño, así que el resultado en dinero no es comparable entre stops. En R
 * sí lo es, porque el riesgo por operación es 1 por definición.
 */
export function barridoSL(filas: TradeEdge[], r: Rango): PuntoBarrido[] {
  const out: PuntoBarrido[] = [];
  const paso = Math.max(0.05, (r.hasta - r.desde) / 80);
  for (let x = r.desde; x <= r.hasta + 1e-9; x += paso) {
    let s = 0;
    for (const f of filas) s += (f.mae >= x ? -x : f.movePct) / x;
    out.push({ x, v: filas.length ? s / filas.length : 0 });
  }
  return out;
}

export interface Rango { desde: number; hasta: number }

/**
 * Hasta dónde barrer, sacado de los datos.
 *
 * El TECHO: uno fijo deja fuera medio gráfico en unas estrategias y sobra en
 * otras; y si el valor que YA se usa cae fuera, la raya de «ahora» no se pinta.
 *
 * El SUELO es 1 % y NO es cosmético. Por debajo, la reconstrucción miente: un
 * trade cuya excursión adversa fue del 0,3 % y acabó +10 % daría 25 R con un
 * stop del 0,4 %, y en la vida real ese stop lo barre el spread dentro de la
 * misma vela. La vela de un minuto no tiene resolución para afirmar eso.
 */
export function rangoBarrido(valores: number[], actual?: number | null): Rango {
  const ord = [...valores].sort((a, b) => a - b);
  const base = Math.max(percentil(ord, 0.95), (actual ?? 0) * 1.25, 3);
  return { desde: 1, hasta: Math.min(80, Math.ceil(base)) };
}

/** ¿El mejor punto se ha quedado pegado al borde? Entonces el óptimo está fuera. */
export function tocaBorde(p: PuntoBarrido[], mejor: PuntoBarrido | null): boolean {
  if (p.length < 2 || !mejor) return false;
  const paso = p[1].x - p[0].x;
  return mejor.x >= p[p.length - 1].x - paso * 2;
}

export function mejorPunto(p: PuntoBarrido[]): PuntoBarrido | null {
  if (!p.length) return null;
  return p.reduce((a, b) => (b.v > a.v ? b : a));
}

/* ---- envolvente de drawdown por Monte Carlo ---- */

export interface Envolvente {
  actual: number;
  mediana: number;
  p95: number;
  percentilActual: number;
  hist: { c: number; n: number }[];
}

/** Peor caída de una serie acumulada. Devuelve un número ≤ 0. */
function peorCaida(vs: number[]): number {
  let acum = 0, techo = 0, peor = 0;
  for (const v of vs) {
    acum += v;
    if (acum > techo) techo = acum;
    const dd = acum - techo;
    if (dd < peor) peor = dd;
  }
  return peor;
}

/**
 * Remuestrea el ORDEN de las operaciones (sin reemplazo: es una permutación) y
 * devuelve la distribución del peor drawdown. Responde a «¿esta racha la produce
 * mi propia estrategia por puro orden, o se ha salido de lo normal?».
 */
export function envolventeDD(filas: TradeEdge[], iteraciones = 2000): Envolvente | null {
  const vs = filas.map((f) => f.v);
  if (vs.length < 30) return null;
  const actual = peorCaida(vs);

  // Generador determinista: la misma corrida da siempre el mismo gráfico.
  let s = 0x2f6e2b1 >>> 0;
  const rnd = () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5; s >>>= 0;
    return s / 0x100000000;
  };

  const peores: number[] = [];
  const copia = vs.slice();
  for (let it = 0; it < iteraciones; it++) {
    for (let i = copia.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      const tmp = copia[i]; copia[i] = copia[j]; copia[j] = tmp;
    }
    peores.push(peorCaida(copia));
  }
  peores.sort((a, b) => a - b);           // de la peor (más negativa) a la mejor
  const p95 = percentil(peores, 0.05);    // el 5 % peor
  const mediana = percentil(peores, 0.5);
  const peoresQueActual = peores.filter((p) => p < actual).length;

  const min = peores[0], max = peores[peores.length - 1];
  const nb = 32, ancho = (max - min) / nb || 1;
  const hist = Array.from({ length: nb }, (_, i) => ({ c: min + ancho * (i + 0.5), n: 0 }));
  for (const p of peores) {
    const i = Math.min(nb - 1, Math.max(0, Math.floor((p - min) / ancho)));
    hist[i].n += 1;
  }

  return {
    actual,
    mediana,
    p95,
    percentilActual: (1 - peoresQueActual / peores.length) * 100,
    hist,
  };
}

/* ---- formato ---- */

export const f1 = (x: number) => x.toFixed(1).replace(".", ",");
export const f2 = (x: number) => x.toFixed(2).replace(".", ",");
export const f3 = (x: number) => x.toFixed(3).replace(".", ",");
export const sgn = (x: number, d = 3) =>
  (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d).replace(".", ",");
/** Miles con punto, sin `toLocaleString` (Node y Chrome no traen el mismo ICU
 *  y el número saldría distinto en servidor y cliente → *Hydration failed*). */
export const miles = (x: number) => {
  const [e, d] = Math.abs(x).toFixed(0).split(".");
  return (x < 0 ? "−" : "") + e.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (d ? "," + d : "");
};
