// Estado y calculos puros de la vista En crudo (16-sep): lo que no pinta
// nada vive aqui para que cada paso sea solo su pantalla.

import type { RawExec, RawLocatesIn, RawSetupIn } from "@/lib/api_portfolio_lab";
import { n } from "./hoja";

/** Bloque Portfolio del paso 1 (v3, 20-sep): las estrategias entran
 *  normalizadas y aqui se pone lo de la cuenta: el % por trade de cada una (el
 *  mismo para todas o uno por estrategia), comisiones para todas, capital,
 *  gastos fijos, margen y periodo. Los locates van en `LocCfg`. */
export interface Cfg {
  /** 0 = la suma de los capitales de las corridas marcadas. */
  capital: number;
  expenses: number;
  /** % del capital del dia por trade: el mismo para todas o uno por estrategia (por id). */
  pctMismo: boolean;
  pctComun: number;
  pctPor: Record<string, number>;
  /** Comisiones para todas: $ por accion (los dos lados) o % del valor. */
  fees: number;
  feeType: "FLAT" | "PERCENT";
  /** Criterios de margen y buying power del broker (19-sep). */
  margin: boolean;
  marginBroker: string;
  start: string;
  end: string;
}

export const CFG0: Cfg = { capital: 0, expenses: 0, pctMismo: true, pctComun: 1, pctPor: {}, fees: 0, feeType: "FLAT", margin: false, marginBroker: "sagetrader", start: "", end: "" };

/** El % por trade que le toca a una estrategia con la config del paso 1. */
export function pctDe(cfg: Cfg, id: string): number {
  if (cfg.pctMismo) return cfg.pctComun;
  const v = cfg.pctPor[id];
  return Number.isFinite(v) ? v : cfg.pctComun;
}

/** Locates de la CUENTA (paso 1): un broker para todas las estrategias. */
export interface LocCfg {
  mode: "none" | "fixed" | "random";
  cost: number;
  min: number;
  max: number;
  seed: number;
  /** Un alquiler por ticker-dia para toda la cuenta (true) o cada estrategia el suyo. */
  shared: boolean;
  gate: boolean;
  /** ev_rodante: lo de siempre (EV por defecto hasta que hay historia, luego
   *  el rolling de N trades); ev_fijo: SIEMPRE ese EV contra el fade. */
  gateMode: "ev_rodante" | "ev_fijo";
  /** Que medida se enfrenta al fade (17-sep): EV, MFE medio o fade medio. */
  gateMetric?: "ev" | "mfe" | "fade";
  gateVentana: number;
  gateEv: number;
  /** El EV fijo (% del precio) que se enfrenta al fade en modo ev_fijo. */
  evFijo: number;
}

export const LOC0: LocCfg = { mode: "none", cost: 3, min: 1, max: 10, seed: 1, shared: true, gate: false, gateMode: "ev_rodante", gateMetric: "ev", gateVentana: 30, gateEv: 2, evFijo: 3 };

export const GATE_METRIC_LABEL: Record<"ev" | "mfe" | "fade", string> = { ev: "EV", mfe: "MFE", fade: "Fade" };

export function locatesIn(l: LocCfg, bandSeeds: number): RawLocatesIn {
  return {
    mode: l.mode,
    cost: l.cost,
    min: l.min,
    max: l.max,
    seed: l.seed,
    shared: l.shared,
    gate: l.gate && l.mode !== "none"
      ? (l.gateMode === "ev_fijo"
        ? { mode: "ev_fixed", metric: l.gateMetric ?? "ev", ev_fixed_pct: l.evFijo, ventana: 0, por: "trades", ev_defecto_pct: l.evFijo, min_trades: 10 }
        : { mode: "ev", metric: l.gateMetric ?? "ev", ventana: l.gateVentana, por: "trades", ev_defecto_pct: l.gateEv, min_trades: 10 })
      : null,
    band_seeds: l.mode === "random" ? bandSeeds : 0,
  };
}

export function locatesResumen(l: LocCfg): string {
  if (l.mode === "none") return "sin locates";
  const precio = l.mode === "fixed" ? `${n(l.cost, 2)} $/100` : `aleatorios ${n(l.min, 0)}–${n(l.max, 0)} $/100`;
  const med = GATE_METRIC_LABEL[l.gateMetric ?? "ev"];
  const puerta = !l.gate ? "" : l.gateMode === "ev_fijo" ? ` · puerta por ${med} fijo ${n(l.evFijo, 1)} %` : ` · puerta por ${med} rodante (${l.gateVentana} trades)`;
  return `locates ${precio} ${l.shared ? "compartidos" : "por estrategia"}${puerta}`;
}

/** Tamano por setup (paso 4 C). */
export const SETUP0: RawSetupIn = {
  enabled: true,
  feature: "price",
  min_trades: 30,
  shrink: 50,
  clip_lo: 0.5,
  clip_hi: 2.0,
  estimate: "walk_forward",
  pooled: false,
};

/** Curva propia de una serie (base + PnL diario) y su drawdown, con el pico
 *  arrancando en la base. Antes del primer dia con trades, NaN.
 *
 *  Con `eqOpen` (el capital con el que empieza cada dia la SUMA) el drawdown
 *  de la serie se mide como la perdida desde su maximo RELATIVA al capital de
 *  ese dia. Es lo que tiene sentido para una estrategia que comparte cuenta:
 *  su tamaño compone sobre el capital de la suma, asi que medir su bache
 *  contra una base fija daba cifras sin sentido (−33.000 % visto el 14-sep). */
export function curvaPropia(pnl: number[], trades: number[], base: number, eqOpen?: number[]) {
  const dd: number[] = [];
  let acc = base;
  let peak = base;
  let viva = false;
  let maxDd = 0;
  for (let i = 0; i < pnl.length; i++) {
    if (!viva && (trades[i] > 0 || pnl[i] !== 0)) viva = true;
    acc += pnl[i];
    if (!viva) {
      dd.push(NaN);
      continue;
    }
    if (acc > peak) peak = acc;
    const denom = eqOpen ? eqOpen[i] : peak;
    const d = denom > 0 ? ((acc - peak) / denom) * 100 : 0;
    if (d < maxDd) maxDd = d;
    dd.push(d);
  }
  return { dd, maxDd, pnlTotal: acc - base };
}

/** Con que se corrio la corrida, leido de backtest_params del listado. */
export function condiciones(p: Record<string, unknown>) {
  const num = (k: string) => Number(p[k] ?? 0) || 0;
  const rt = String(p.risk_type ?? "FIXED").toUpperCase();
  const ft = String(p.fee_type ?? "FLAT").toUpperCase();
  const fees = num("fees");
  const random = !!p.locates_random;
  return {
    capital: num("init_cash"),
    tamano: `${p.size_by_sl ? "riesgo" : "capital"} ${rt === "PERCENT" ? `${n(num("risk_r"), 2)} %` : rt.startsWith("FIXED_RATIO") ? `ratio Δ${n(num("fixed_ratio_delta"), 0)}` : `${n(num("risk_r"), 0)} $`}`,
    // `fees` PERCENT y `slippage` se guardan como fraccion (UI % / 100).
    comisiones: fees === 0 ? "0" : ft === "PERCENT" ? `${n(fees * 100, 4)} %` : `${n(fees, 4)} $/acc`,
    slippage: num("slippage") === 0 ? "0" : `${n(num("slippage") * 100, 3)} %`,
    locates: random
      ? `aleatorios ${n(num("locates_random_min"), 2)}–${n(num("locates_random_max"), 1)} (semilla ${n(num("locates_seed"), 0)})`
      : num("locates_cost") === 0 ? "0" : `${n(num("locates_cost"), 2)} ${String(p.locate_type ?? "FLAT").toUpperCase() === "PERCENT" ? "%" : "$"}/100`,
    gastos: num("monthly_expenses") === 0 ? "0" : `${n(num("monthly_expenses"), 0)} $/mes`,
    periodo: `${String(p.start_date ?? "?").slice(0, 10)} → ${String(p.end_date ?? "?").slice(0, 10)}`,
  };
}

/** La ejecucion de la propia corrida, en el formato de aqui (boton «= corrida»).
 *  Los locates ya no van por fila: son de la cuenta (paso 1, bloque Portfolio). */
export function execDeCorrida(p: Record<string, unknown>): RawExec {
  const num = (k: string) => Number(p[k] ?? 0) || 0;
  const isPct = String(p.risk_type ?? "").toUpperCase() === "PERCENT";
  const ft = String(p.fee_type ?? "FLAT").toUpperCase() === "PERCENT" ? "PERCENT" : "FLAT";
  return {
    sizing: "auto",
    size_value: num("risk_r"),
    size_unit: isPct ? "pct" : "usd",
    fees: ft === "PERCENT" ? num("fees") * 100 : num("fees"),
    fee_type: ft,
    slippage_pct: num("slippage") * 100,
    locates: "none",
    locates_cost: 0,
    locates_min: 1,
    locates_max: 10,
    locates_seed: 1,
  };
}

/** Limites de perdida historicos sobre la serie diaria real ($ y % del capital
 *  del dia): peor dia, VaR/CVaR al 95 y 99 %, y la peor racha de 5 y 20 dias. */
export function limitesHistoricos(dailyPnl: number[], equity: number[], capital: number) {
  const nD = dailyPnl.length;
  if (!nD) return null;
  const ret = dailyPnl.map((v, i) => { const open = i === 0 ? capital : equity[i - 1]; return open > 0 ? (v / open) * 100 : 0; });
  const q = (xs: number[], p: number) => {
    const s = [...xs].sort((a, b) => a - b);
    const k = Math.max(0, Math.min(s.length - 1, Math.floor((p / 100) * (s.length - 1))));
    return s[k];
  };
  const cvar = (xs: number[], p: number) => {
    const s = [...xs].sort((a, b) => a - b);
    const k = Math.max(1, Math.floor((p / 100) * s.length));
    return s.slice(0, k).reduce((a, b) => a + b, 0) / k;
  };
  const racha = (win: number) => {
    let worstUsd = 0;
    let worstPct = 0;
    for (let i = 0; i + win <= nD; i++) {
      let su = 0;
      let sp = 0;
      for (let k = i; k < i + win; k++) { su += dailyPnl[k]; sp += ret[k]; }
      if (su < worstUsd) worstUsd = su;
      if (sp < worstPct) worstPct = sp;
    }
    return { usd: worstUsd, pct: worstPct };
  };
  const iMin = dailyPnl.reduce((b, v, i) => (v < dailyPnl[b] ? i : b), 0);
  return {
    dias: nD,
    peorDia: { usd: dailyPnl[iMin], pct: ret[iMin], idx: iMin },
    var95: { usd: q(dailyPnl, 5), pct: q(ret, 5) },
    var99: { usd: q(dailyPnl, 1), pct: q(ret, 1) },
    cvar95: { usd: cvar(dailyPnl, 5), pct: cvar(ret, 5) },
    racha5: racha(5),
    racha20: racha(20),
    diasNegativos: dailyPnl.filter((v) => v < 0).length,
  };
}
