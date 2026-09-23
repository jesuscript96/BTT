// Gastos fijos: punto de equilibrio y umbral de «ruido» (13-sep-2026).
//
// LA IDEA. El edge de una estrategia es un PORCENTAJE (escala con el capital);
// los gastos fijos (datos, plataforma, locates de suscripcion...) son una
// CIFRA al mes que no escala. Con riesgo fijo en dolares por operacion,
//
//     neto/mes = (riesgo % x capital) x (R por operacion x operaciones/mes) - gastos
//
// asi que hay un capital (o un riesgo %) por debajo del cual los gastos se
// comen el beneficio, y otro por encima del cual son ruido. Y un tercer efecto
// que no sale de la media: con poco capital el bruto de un mes es del orden de
// los gastos, y un mes flojo es un mes en perdidas aunque la estrategia sea
// buena. Eso se mide contando meses sobre los meses REALES de la corrida.
//
// COMO SE ESCALA. El motor corre con un riesgo fijo `riskR` en $ por
// operacion, asi que el PnL de cada operacion es proporcional al riesgo que se
// ponga: con riesgo r, cada PnL vale `pnl x (r / riskR)`. No hace falta lanzar
// nada: se toman los meses de la corrida y se multiplican. Vale tanto con
// «shares por distancia» (riskR es el riesgo real) como sin el (riskR es el
// nocional): en los dos casos la posicion es proporcional a riskR.
//
// CON RIESGO EN % DEL EQUITY (`risk_type` PERCENT) el PnL en $ de cada trade
// COMPONE: los ultimos meses pesan mucho mas que los primeros y la media
// mensual no es una escala de nada (medido en una corrida real: 7.358 $/mes
// «a 500 $ por operacion», que era un 16 % por operacion, imposible). Se
// DESCOMPONE con `r_multiple`: el motor lo define como pnl / (riesgo de ESE
// dia = capital del dia x %), asi que `r_multiple x R0` es el PnL que habria
// tenido ese mismo trade con un riesgo fijo R0 en $ (el del primer dia:
// capital x %). Los locates se escalan con el mismo factor. A partir de ahi,
// todo igual que con riesgo fijo.
//
// (Hasta el 19-sep-2026 se descomponia con `return_pct`, que es pnl / nocional
// DEL LEG: con piramides y salidas parciales cada leg tiene su propio nocional
// y la suma no es la del trade a riesgo fijo. En PM (A), con piramide y tres
// parciales, salia 4 veces corto: 0,34 R/mes en vez de 7,6, y de ahi que
// «para que los gastos sean ruido» pidiera 290.000 $ de capital. Jaume lo vio.)
//
// Y en small caps la escala lineal miente a partir de cierto tamano: una
// posicion de 40.000 $ en un chicharro no se llena al precio del backtest.
// Por eso se ensena la posicion mediana en $ en cada fila, para que se vea
// donde deja de ser creible.
//
// (Separadores ASCII a proposito: los `──` en comentarios tumbaron el dev
// server de Next. Ver la cabecera de EdgeTab.tsx.)
import type { TradeRecord } from "@/lib/api_backtester";

export interface MesBruto {
  /** "2025-03" */
  mes: string;
  /** PnL del mes en $ AL RIESGO DE LA CORRIDA (riskR), locates descontados. */
  bruto: number;
  ops: number;
}

/** PnL del trade y factor de escala respecto al PnL real.
 *  Con riesgo fijo: el pnl tal cual (factor 1). Con riesgo en % del equity
 *  (`r0` dado): el pnl descompuesto a un riesgo fijo r0 via `r_multiple`
 *  (exacto tambien con piramides y parciales: el motor mide la R del trade
 *  contra el riesgo del dia). Sin `r_multiple`, respaldo con `return_pct`. */
export function pnlBase(t: TradeRecord, r0?: number): { pnl: number; factor: number } {
  const pnl = Number(t.pnl) || 0;
  if (!r0 || r0 <= 0) return { pnl, factor: 1 };
  const rm = Number(t.r_multiple);
  if (Number.isFinite(rm)) {
    const fijo = rm * r0;
    return { pnl: fijo, factor: pnl !== 0 ? fijo / pnl : 1 };
  }
  const ret = Number(t.return_pct);
  if (!Number.isFinite(ret)) return { pnl, factor: 1 };
  const fijo = (ret / 100) * r0;
  return { pnl: fijo, factor: pnl !== 0 ? fijo / pnl : 1 };
}

/** Los meses de la corrida, del primero al ultimo con operaciones, SIN huecos:
 *  un mes sin operaciones tambien paga los gastos fijos. */
export function mesesBrutos(trades: TradeRecord[], r0?: number): MesBruto[] {
  const porMes = new Map<string, MesBruto>();
  const locatesVistos = new Set<string>();
  for (const t of trades) {
    const mes = String(t.date || "").slice(0, 7);
    if (mes.length !== 7) continue;
    const m = porMes.get(mes) ?? { mes, bruto: 0, ops: 0 };
    const { pnl, factor } = pnlBase(t, r0);
    m.bruto += pnl;
    m.ops += 1;
    // Los locates se cobran UNA vez por ticker-dia y los comparten todos los
    // trades de ese dia: se descuentan una sola vez.
    const clave = `${t.ticker}|${t.date}`;
    if (t.locates_fee_day && !locatesVistos.has(clave)) {
      locatesVistos.add(clave);
      m.bruto -= (Number(t.locates_fee_day) || 0) * factor;
    }
    porMes.set(mes, m);
  }
  if (porMes.size === 0) return [];
  const claves = Array.from(porMes.keys()).sort();
  const salida: MesBruto[] = [];
  let [y, mo] = claves[0].split("-").map(Number);
  const [yF, moF] = claves[claves.length - 1].split("-").map(Number);
  while (y < yF || (y === yF && mo <= moF)) {
    const k = `${y}-${String(mo).padStart(2, "0")}`;
    salida.push(porMes.get(k) ?? { mes: k, bruto: 0, ops: 0 });
    mo += 1;
    if (mo > 12) { mo = 1; y += 1; }
  }
  return salida;
}

/** Caida maxima de la curva acumulada de PnL en $ al riesgo de la corrida
 *  (sin componer). En % del capital solo depende del riesgo %:
 *  DD% = riesgo% x (DD$ / riskR). */
export function caidaMaximaDolares(trades: TradeRecord[], r0?: number): number {
  const orden = trades.slice().sort((a, b) =>
    (a.exit_time_epoch || 0) - (b.exit_time_epoch || 0));
  let acum = 0, pico = 0, dd = 0;
  for (const t of orden) {
    acum += pnlBase(t, r0).pnl;
    if (acum > pico) pico = acum;
    if (pico - acum > dd) dd = pico - acum;
  }
  return dd;
}

/** Posicion mediana en $ (acciones x precio de entrada) al riesgo de la corrida. */
export function posicionMediana(trades: TradeRecord[], r0?: number): number {
  const xs = trades
    .map((t) => (Number(t.size) || 0) * (Number(t.avg_entry_price ?? t.entry_price) || 0) * pnlBase(t, r0).factor)
    .filter((x) => x > 0)
    .sort((a, b) => a - b);
  if (!xs.length) return 0;
  const i = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[i] : (xs[i - 1] + xs[i]) / 2;
}

export interface Escenario {
  /** Riesgo por operacion en $ */
  riesgo: number;
  /** Riesgo en % del capital */
  riesgoPct: number;
  capital: number;
  brutoMes: number;
  netoMes: number;
  /** Que parte del bruto se llevan los gastos (0-1; >1 = pierdes). */
  parteGastos: number;
  /** Meses en perdidas sobre el total de meses, 0-1. */
  mesesPerdida: number;
  /** Caida maxima en % del capital. */
  ddPct: number;
  /** Posicion mediana en $. */
  posicion: number;
}

export interface BaseGastos {
  meses: MesBruto[];
  brutoMedio: number;
  dd: number;
  posicion: number;
  riskR: number;
}

/** `riskR`: riesgo por operacion en $ de la corrida (con riesgo en % del
 *  equity, el del primer dia: capital x %, y `descomponer` = true). */
export function base(trades: TradeRecord[], riskR: number, descomponer = false): BaseGastos {
  const r0 = descomponer ? riskR : undefined;
  const meses = mesesBrutos(trades, r0);
  const brutoMedio = meses.length ? meses.reduce((p, m) => p + m.bruto, 0) / meses.length : 0;
  return { meses, brutoMedio, dd: caidaMaximaDolares(trades, r0), posicion: posicionMediana(trades, r0), riskR };
}

export function escenario(b: BaseGastos, riesgo: number, capital: number, gastos: number): Escenario {
  const k = b.riskR > 0 ? riesgo / b.riskR : 0;
  const brutoMes = b.brutoMedio * k;
  const netoMes = brutoMes - gastos;
  const perdidas = b.meses.length
    ? b.meses.filter((m) => m.bruto * k - gastos < 0).length / b.meses.length : 0;
  return {
    riesgo, riesgoPct: capital > 0 ? (riesgo / capital) * 100 : 0, capital,
    brutoMes, netoMes,
    parteGastos: brutoMes > 0 ? gastos / brutoMes : Infinity,
    mesesPerdida: perdidas,
    ddPct: capital > 0 ? (b.dd * k / capital) * 100 : 0,
    posicion: b.posicion * k,
  };
}

export interface Umbrales {
  /** Riesgo % (sobre `capital`) con el que neto/mes = 0. */
  riesgoEquilibrioPct: number;
  /** Riesgo % con el que los gastos son <= `theta` del bruto. */
  riesgoRuidoPct: number;
  /** Capital (a `riesgoPct`) con el que neto/mes = 0. */
  capitalEquilibrio: number;
  /** Capital (a `riesgoPct`) con el que los gastos son <= `theta` del bruto. */
  capitalRuido: number;
  /** DD maxima en % del capital al riesgo de ruido (es lo que cuesta). */
  ddEnRuidoPct: number;
}

/** `theta` = fraccion del bruto que se acepta que se lleven los gastos
 *  (0,10 = «ruido» cuando son el 10 % o menos). */
export function umbrales(b: BaseGastos, capital: number, riesgoPct: number,
                         gastos: number, theta: number): Umbrales | null {
  if (b.brutoMedio <= 0 || b.riskR <= 0) return null;   // sin bruto positivo no hay equilibrio
  // riesgo $ con el que bruto x k = gastos  ->  k = gastos / brutoMedio
  const rEq = (gastos / b.brutoMedio) * b.riskR;
  const rRuido = (gastos / (theta * b.brutoMedio)) * b.riskR;
  return {
    riesgoEquilibrioPct: capital > 0 ? rEq / capital * 100 : 0,
    riesgoRuidoPct: capital > 0 ? rRuido / capital * 100 : 0,
    capitalEquilibrio: riesgoPct > 0 ? rEq / (riesgoPct / 100) : 0,
    capitalRuido: riesgoPct > 0 ? rRuido / (riesgoPct / 100) : 0,
    // La DD en % del capital solo depende del riesgo %: DD% = riesgo% x DD$/riskR.
    ddEnRuidoPct: capital > 0 ? (b.dd * (rRuido / b.riskR) / capital) * 100 : 0,
  };
}

export const RIESGOS_PCT = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5];
export const CAPITALES = [5_000, 10_000, 25_000, 50_000, 100_000, 250_000];
