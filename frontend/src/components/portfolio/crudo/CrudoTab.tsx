"use client";

// Sub-pestaña «En crudo» de Portfolio: la SUMA de varias corridas guardadas,
// cada una con la EJECUCION QUE SE FIJA AQUI (R por trade, comisiones,
// slippage), reseteando lo que tenia la corrida; capital, gastos fijos, tope,
// «una a la vez» y LOCATES son de la cuenta. Nada se vuelve a correr: el motor
// (portfolio_lab_raw) deshace los costes y el tamaño de cada trade guardado y
// reaplica los de aqui.
//
// Desde el 16-sep es un flujo de cuatro pasos numerados (Jaume: «quiero orden
// y un flujo que se intuya, nada de mil cosas donde mirar»):
//   1. Ejecucion        -> Calcular
//   2. Vision general   (resumen, exposicion, por estrategia, correlacion, calendario)
//   3. Limites de perdida (historico, Monte Carlo bootstrap, banda de locates)
//   4. Escalado y pesos (Kelly x HRP con tope: hoy y desde el inicio)
// Cada paso es una caja plegable con su resumen; el 2-4 no se abren sin el 1.
// Este fichero solo lleva el estado y el hilo; cada paso pinta lo suyo.
//
// La pestaña «Imagen general» (normalizada) sigue siendo la fuente del bot.

import React, { useCallback, useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import {
  RAW_EXEC_DEFAULT,
  getPortfolioStrategyEquity,
  runPortfolioMc,
  runPortfolioRaw,
  type PortfolioStrategy,
  type RawConfigIn,
  type RawExec,
  type RawOut,
} from "@/lib/api_portfolio_lab";
import type { CurveState } from "../StrategyShelf";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Nota, Paso, PasoBar, colorSerie, n, pct, usd } from "./hoja";
import type { Serie } from "./CrudoCharts";
import { CFG0, ESC0, KELLY_SCOPE_LABEL, LOC0, curvaPropia, locatesIn, locatesResumen, type Cfg, type EscCfg, type LocCfg, MODELO_LABEL } from "./modelo";
import { PasoEjecucion } from "./PasoEjecucion";
import { PasoVision } from "./PasoVision";
import { PasoMonteCarlo } from "./PasoMonteCarlo";
import { PasoEscalado } from "./PasoEscalado";

const BAND_SEEDS = 100;

export function CrudoTab({ strategies, onMove }: { strategies: PortfolioStrategy[]; onMove?: (s: PortfolioStrategy, dir: -1 | 1, visibles: string[]) => void }) {
  const pool = useMemo(() => strategies.filter((s) => s.run), [strategies]);

  // ── Paso 1: seleccion, ejecucion por estrategia y la cuenta ───────────
  const [checkedRaw, setChecked] = useState<Record<string, boolean>>({});
  const checked = useMemo(() => {
    const next: Record<string, boolean> = {};
    for (const s of pool) next[s.id] = checkedRaw[s.id] ?? s.buckets.includes("portfolio");
    return next;
  }, [pool, checkedRaw]);
  const [defaultExec, setDefaultExec] = useState<RawExec>({ ...RAW_EXEC_DEFAULT });
  const [execRaw, setExecRaw] = useState<Record<string, RawExec>>({});
  const execDe = (id: string): RawExec => execRaw[id] ?? defaultExec;
  const [vista, setVista] = useState<"exec" | "corrida">("exec");
  const [cfgRaw, setCfg] = useState<Cfg>(CFG0);
  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg((c) => ({ ...c, [k]: v }));
  const [loc, setLoc] = useState<LocCfg>(LOC0);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [curves, setCurves] = useState<Record<string, CurveState>>({});
  const desplegar = useCallback((s: PortfolioStrategy) => {
    setAbierta((cur) => (cur === s.id ? null : s.id));
    setCurves((c) => {
      if (c[s.id] && c[s.id] !== "error") return c;
      getPortfolioStrategyEquity(s.id)
        .then((r) => setCurves((prev) => ({ ...prev, [s.id]: r.equity })))
        .catch(() => setCurves((prev) => ({ ...prev, [s.id]: "error" })));
      return { ...c, [s.id]: "loading" };
    });
  }, []);

  const [out, setOut] = useState<RawOut | null>(null);
  const [ranKey, setRanKey] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [yMode, setYMode] = useState<"usd" | "pct">("usd");

  // ── Paso 3: Monte Carlo ────────────────────────────────────────────────
  const [mcOut, setMcOut] = useState<MonteCarloOut | null>(null);
  const [mcSims, setMcSims] = useState<number | "">(5000);
  const [mcMethod, setMcMethod] = useState<"bootstrap" | "permutacion">("bootstrap");
  const [mcRunning, setMcRunning] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);

  // ── Paso 4: escalado ───────────────────────────────────────────────────
  const [esc, setEsc] = useState<EscCfg>(ESC0);
  const [outEsc, setOutEsc] = useState<RawOut | null>(null);
  const [escKey, setEscKey] = useState("");
  const [escRunning, setEscRunning] = useState(false);
  const [escError, setEscError] = useState<string | null>(null);

  // ── Que paso esta abierto ─────────────────────────────────────────────
  const [abiertos, setAbiertos] = useState<Record<number, boolean>>({ 1: true, 2: true, 3: false, 4: false });
  const toggle = (k: number) => setAbiertos((a) => ({ ...a, [k]: !a[k] }));
  const ir = (k: number) => {
    setAbiertos((a) => ({ ...a, [k]: true }));
    if (typeof document !== "undefined") document.getElementById(`paso-${k}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const selected = pool.filter((s) => checked[s.id]);
  const selectedIds = selected.map((s) => s.id);
  const capitalCorridas = selected.reduce((a, s) => a + (Number((s.run?.backtest_params as Record<string, unknown> | undefined)?.init_cash) || 0), 0);
  const cfg: Cfg = { ...cfgRaw, capital: cfgRaw.capital > 0 ? cfgRaw.capital : capitalCorridas };
  const perStrategy: Record<string, RawExec> = {};
  for (const s of selected) perStrategy[s.id] = execDe(s.id);

  const cfgKey = JSON.stringify({ ids: selectedIds, cfg, perStrategy, loc });
  const stale = out != null && ranKey !== cfgKey;
  const problema: string | null =
    !selectedIds.length ? "Marca al menos una estrategia."
    : cfg.capital <= 0 ? "Pon un capital mayor que cero."
    : selected.some((s) => { const e = execDe(s.id); return e.sizing !== "as_saved" && e.size_value <= 0; }) ? "Alguna estrategia marcada tiene el tamaño por trade a cero."
    : loc.mode === "fixed" && loc.cost <= 0 ? "Los locates fijos necesitan un precio por paquete."
    : loc.mode === "random" && loc.max <= loc.min ? "En los locates aleatorios el máximo tiene que ser mayor que el mínimo."
    : null;

  const cuerpo = (): RawConfigIn => ({
    strategy_ids: selectedIds,
    capital: cfg.capital,
    per_strategy: perStrategy,
    default_exec: defaultExec,
    max_exposure_usd: cfg.capUnit === "usd" ? cfg.cap : 0,
    max_exposure_pct: cfg.capUnit === "pct" ? cfg.cap : 0,
    one_per_ticker: !!cfg.onePerTicker,
    cap_mode: "skip",
    monthly_expenses: cfg.expenses,
    locates: locatesIn(loc, BAND_SEEDS),
    start_date: cfg.start || null,
    end_date: cfg.end || null,
  });

  // El backend viejo ignora los bloques nuevos sin avisar: se reconoce al
  // nuevo por `locates_report`.
  const backendViejo = out != null && out.locates_report === undefined;

  const calcular = async () => {
    if (problema || running) return;
    setRunning(true);
    setError(null);
    try {
      const res = await runPortfolioRaw(cuerpo());
      if (!res.config?.default_exec) {
        throw new Error("El backend todavía no lleva el motor de ejecución por estrategia: hay que aplicarlo con el bot parado.");
      }
      setOut(res);
      setRanKey(cfgKey);
      setMcOut(null);
      setMcError(null);
      setOutEsc(null);
      setEscKey("");
      setAbiertos((a) => ({ ...a, 1: false, 2: true }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo calcular el portfolio");
    } finally {
      setRunning(false);
    }
  };

  const simularMc = async () => {
    if (!out || mcRunning) return;
    setMcRunning(true);
    setMcError(null);
    try {
      // Se remuestrean los RETORNOS diarios (% del capital con el que empezo
      // cada dia) y se componen, no los $ de cada dia sumados: con una curva
      // que compone, un dia de −50 M $ puesto donde la cuenta tenia 100 k $
      // daba drawdowns de −40.000 % (visto el 16-sep). Con `risk_pct: 1` el
      // motor hace equity *= 1 + ret/100, es decir, compone tal cual.
      const cap = out.config.capital;
      const rets = out.daily_pnl.map((v, i) => {
        const open = i === 0 ? cap : out.equity[i - 1];
        return open > 0 ? (v / open) * 100 : 0;
      });
      const res = await runPortfolioMc({
        values: rets,
        init_cash: cap,
        simulations: Number(mcSims) || 5000,
        method: mcMethod,
        mode: "compound",
        risk_pct: 1,
        ruin_pct: 50,
      });
      setMcOut(res);
    } catch (e) {
      setMcError(e instanceof Error ? e.message : "No se pudo simular");
    } finally {
      setMcRunning(false);
    }
  };

  const escKeyNow = JSON.stringify({ ranKey, esc });
  const escStale = outEsc != null && escKey !== escKeyNow;
  const calcularEsc = async () => {
    if (!out || escRunning) return;
    setEscRunning(true);
    setEscError(null);
    try {
      const res = await runPortfolioRaw({ ...cuerpo(), scaling: esc });
      if (!res.scaling) throw new Error("El backend todavía no lleva el escalado del portfolio en crudo: hay que aplicarlo con el bot parado.");
      setOutEsc(res);
      setEscKey(escKeyNow);
    } catch (e) {
      setEscError(e instanceof Error ? e.message : "No se pudo calcular el escalado");
    } finally {
      setEscRunning(false);
    }
  };

  // ── Series del paso 2 (todas sobre el capital del portfolio) ──────────
  const propias = useMemo(() => {
    if (!out) return [];
    const cap = out.config.capital;
    const eqOpen = out.calendar.map((_, i) => (i === 0 ? cap : out.equity[i - 1]));
    return out.per_strategy.map((p) => curvaPropia(p.pnl_daily, p.trades_daily, cap, eqOpen));
  }, [out]);
  const curvas = useMemo(() => {
    if (!out) return null;
    const cap = out.config.capital;
    const toY = (v: number) => (yMode === "usd" ? v : (v / cap) * 100);
    const pnl: Serie[] = out.per_strategy.map((p, i) => {
      let acc = 0;
      return { name: p.name, color: colorSerie(i), values: p.pnl_daily.map((v) => { acc += v; return toY(acc); }) };
    });
    pnl.push({ name: "Suma", color: color.copper, width: 2.2, values: out.equity.map((e) => toY(e - cap)) });
    const dd: Serie[] = out.per_strategy.map((p, i) => ({ name: p.name, color: colorSerie(i), values: propias[i]?.dd || [] }));
    const suma = curvaPropia(out.daily_pnl, out.calendar.map(() => 1), cap);
    dd.push({ name: "Suma", color: color.copper, width: 2.2, values: suma.dd });
    return { pnl, dd, sumaMaxDd: suma.maxDd };
  }, [out, yMode, propias]);
  const exposicion = useMemo(() => {
    if (!out) return null;
    const cap = out.config.capital;
    const pctS = out.exposure.peak_daily.map((v, i) => {
      const open = i === 0 ? cap : out.equity[i - 1];
      return open > 0 ? (v / open) * 100 : 0;
    });
    return { pct: pctS, max: Math.max(0, ...pctS) };
  }, [out]);

  if (!pool.length) {
    return (
      <p style={{ fontSize: 12, fontFamily: font.sans, color: color.textMuted, padding: "30px 0", textAlign: "center" }}>
        No hay estrategias con backtest guardado. Corre una en el Backtester y guárdala en el baúl.
      </p>
    );
  }

  // ── Resumenes de cabecera de cada paso ───────────────────────────────
  const resumen1 = `${selectedIds.length} ${selectedIds.length === 1 ? "estrategia" : "estrategias"} · ${usd(cfg.capital)} · ${cfg.cap > 0 ? `tope ${n(cfg.cap, 0)} ${cfg.capUnit === "pct" ? "% del día" : "$"}` : "sin tope"}${cfg.onePerTicker ? " · una a la vez" : ""} · ${locatesResumen(loc)}${cfg.expenses > 0 ? ` · ${usd(cfg.expenses)}/mes` : ""}`;
  const resumen2 = out ? `retorno ${pct(out.metrics.total_return_pct)} · max DD ${pct(curvas?.sumaMaxDd)} · ${n(out.metrics.n_trades, 0)} trades · Sharpe ${n(out.metrics.sharpe)}${stale ? " · (desactualizado)" : ""}` : "";
  const resumen3 = mcOut ? `DD a tragar (1 de 20) ${pct(mcOut.dd_tolerance?.p95)} · prob. de acabar perdiendo ${pct(mcOut.prob_losing_pct)}` : out?.locates_band ? `banda de ${n(out.locates_band.seeds, 0)} semillas lista · Monte Carlo sin simular` : "límites históricos listos · Monte Carlo sin simular";
  const hoy = outEsc?.scaling?.today;
  const modeloTxt = esc.model === "kelly" ? `${KELLY_SCOPE_LABEL[esc.kelly_scope ?? "per_strategy"]} × ${n(esc.kelly_mult, 2)}` : MODELO_LABEL[esc.model];
  const resumen4 = hoy ? `hoy: ${pct(hoy.applied_pct, 2)} por trade sumando todas (${usd(hoy.applied_usd)}) · ${modeloTxt}${escStale ? " · (desactualizado)" : ""}` : `${modeloTxt} · tope ${n(esc.cap_pct, 1)} %`;

  const listo = !!out && !!curvas && !!exposicion;
  const pasos = [
    { num: 1, label: "Ejecución", hecho: listo && !stale, disponible: true },
    { num: 2, label: "Visión general", hecho: listo, disponible: listo },
    { num: 3, label: "Límites de pérdida", hecho: !!mcOut, disponible: listo },
    { num: 4, label: "Escalado y pesos", hecho: !!outEsc, disponible: listo && !backendViejo },
  ];
  const activo = !listo ? 1 : abiertos[4] && outEsc ? 4 : abiertos[3] ? 3 : abiertos[2] ? 2 : 1;

  return (
    <div>
      <PasoBar pasos={pasos} activo={activo} onGo={ir} />

      <Paso num={1} title="Ejecución" open={!!abiertos[1]} onToggle={() => toggle(1)} summary={resumen1} sinRelleno
        help="Qué estrategias entran y con qué ejecución cada una (R por trade, comisiones, slippage), y lo que es de la cuenta: capital, gastos fijos, tope de exposición, «una a la vez», locates y periodo. Calcular reconstruye la suma desde los trades guardados; nada se vuelve a correr ni se modifica.">
        <div style={{ padding: "10px 10px 0" }}>
          <PasoEjecucion m={{ pool, checked, setChecked, selected, selectedIds, defaultExec, setDefaultExec, execRaw, setExecRaw, execDe, vista, setVista, abierta, curves, desplegar, onMove, cfgRaw, cfg, set, setCfg, capitalCorridas, loc, setLoc, problema, stale, running, calcular, error }} />
        </div>
      </Paso>

      {backendViejo && (
        <Nota tone="warning">
          El backend que responde no lleva todavía los locates de la cuenta ni el escalado (motor del 16-sep): los locates del paso 1 se han ignorado y el paso 4 está apagado. Se aplica con el bot parado.
        </Nota>
      )}

      <Paso num={2} title="Visión general" open={!!abiertos[2]} onToggle={() => toggle(2)} summary={resumen2} disabled={!listo} disabledNote="primero calcula el paso 1"
        help="Lo que habría hecho una cuenta operando todas las estrategias marcadas a la vez con la ejecución del paso 1. Pestañas: el resumen con la curva y el drawdown, la exposición al minuto, la tabla por estrategia, la correlación y el calendario.">
        {listo && out && curvas && exposicion && <PasoVision m={{ out, curvas, propias, exposicion, yMode, setYMode }} />}
      </Paso>

      <Paso num={3} title="Límites de pérdida" open={!!abiertos[3]} onToggle={() => toggle(3)} summary={resumen3} disabled={!listo} disabledNote="primero calcula el paso 1"
        help="Cuánto se puede llegar a perder con esto: lo que ya pasó en la serie real (peor día, VaR, rachas), lo que podría pasar remuestreando los días (Monte Carlo bootstrap: el drawdown que hay que estar dispuesto a tragar) y, con locates aleatorios, cuánto depende el resultado del precio de los locates (banda de semillas).">
        {listo && out && <PasoMonteCarlo m={{ out, mcOut, mcSims, setMcSims, mcMethod, setMcMethod, mcRunning, mcError, simularMc }} />}
      </Paso>

      <Paso num={4} title="Escalado y pesos" open={!!abiertos[4]} onToggle={() => toggle(4)} summary={resumen4} disabled={!listo || backendViejo} disabledNote={backendViejo ? "el backend todavía no lleva el escalado" : "primero calcula el paso 1"}
        help="Cuánto arriesgar por trade en cada estrategia según Kelly (de cada una, o global sobre el capital total), con la fracción que quieras y un tope sobre la suma que manda sobre todo. Responde a dos preguntas: qué habría que poner HOY en cada estrategia, y qué habría pasado aplicándolo desde el principio con datos solo anteriores a cada rebalanceo. Aquí los R del paso 1 no cuentan: el tamaño lo pone Kelly.">
        {listo && out && <PasoEscalado m={{ out, outEsc, esc, setEsc, escRunning, escError, escStale, calcularEsc }} />}
      </Paso>

      <p style={{ margin: "0 0 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
        Todo se reconstruye desde los trades guardados de cada corrida; no se vuelve a correr ningún backtest ni se
        modifica ninguna estrategia. Black Swan y Halts no se pueden reconstruir así: quedan para una fase con backtest
        efímero, si hace falta. La pestaña <strong>Imagen general</strong> sigue siendo la del portfolio normalizado que lee el bot.
      </p>
    </div>
  );
}
