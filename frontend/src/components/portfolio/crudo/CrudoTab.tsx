"use client";

// Sub-pestaña «En crudo» de Portfolio: la SUMA de varias corridas guardadas
// NORMALIZADAS (1 $ por trade, sin costes), a las que se les pone aqui lo del
// portfolio: el % por trade de cada una, comisiones, slippage, locates de la
// cuenta, capital, gastos fijos y margen. Nada se vuelve a correr: el motor
// (portfolio_lab_raw) deshace el tamaño de cada trade guardado y reaplica lo
// de aqui.
//
// v3 (20-sep-2026, Jaume: «vamos a simplificarlo»), cinco pasos:
//   1. Ejecucion        -> Calcular (estrategias + % por trade + cuenta)
//   2. Vision general   (la curva del portfolio y sus tablas)
//   3. Monte Carlo      (bootstrap: datos clave y tabla, nada mas)
//   4. Nivel y setups   (A: el nivel de la cuenta por la caida; B: reparto por
//                        Kelly conjunta con IS/OOS; C: tamano por setup, walk-forward)
//   5. Cuenta real      (el CSV de la operativa real: Kelly del total y el reparto)
// Cada paso es una caja plegable con su resumen; el 2-4 no se abren sin el 1.
// Este fichero solo lleva el estado y el hilo; cada paso pinta lo suyo.
//
// La pestaña «Imagen general» (normalizada) sigue siendo la fuente del bot.

import React, { useCallback, useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import {
  getPortfolioStrategyEquity,
  runPortfolioMc,
  runPortfolioNiveles,
  runPortfolioRaw,
  runPortfolioReparto,
  type PortfolioStrategy,
  type RawConfigIn,
  type RawExec,
  type RawNivelesOut,
  type RawOut,
  type RawRepartoOut,
  type RawSetupIn,
} from "@/lib/api_portfolio_lab";
import type { CurveState } from "../StrategyShelf";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Nota, Paso, PasoBar, colorSerie, n, pct, usd } from "./hoja";
import type { Serie } from "./CrudoCharts";
import { CFG0, LOC0, SETUP0, curvaPropia, locatesIn, locatesResumen, pctDe, type Cfg, type LocCfg } from "./modelo";
import { PasoEjecucion, porSlDe } from "./PasoEjecucion";
import { PasoVision } from "./PasoVision";
import { PasoMonteCarlo } from "./PasoMonteCarlo";
import { PasoNivel } from "./PasoNivel";
import { PasoCuentaReal } from "./PasoCuentaReal";

// v3: sin banda de semillas en el paso 1 (el paso 3 es solo el bootstrap).
const BAND_SEEDS = 0;

export function CrudoTab({ strategies, onMove }: { strategies: PortfolioStrategy[]; onMove?: (s: PortfolioStrategy, dir: -1 | 1, visibles: string[]) => void }) {
  const pool = useMemo(() => strategies.filter((s) => s.run), [strategies]);

  // ── Paso 1: seleccion, ejecucion por estrategia y la cuenta ───────────
  const [checkedRaw, setChecked] = useState<Record<string, boolean>>({});
  const checked = useMemo(() => {
    const next: Record<string, boolean> = {};
    for (const s of pool) next[s.id] = checkedRaw[s.id] ?? s.buckets.includes("portfolio");
    return next;
  }, [pool, checkedRaw]);
  // v3: por fila solo el slippage; el % por trade y las comisiones van en cfg.
  const [slipDefault, setSlipDefault] = useState<number>(0);
  const [slipRaw, setSlipRaw] = useState<Record<string, number>>({});
  const slipDe = (id: string): number => (id in slipRaw ? slipRaw[id] : slipDefault);
  const execDe = (id: string): RawExec => ({
    sizing: "auto", size_value: pctDe(cfg, id), size_unit: "pct",
    fees: cfg.fees, fee_type: cfg.feeType, slippage_pct: slipDe(id),
    locates: "none", locates_cost: 0, locates_min: 1, locates_max: 10, locates_seed: 1,
  });
  const [vista, setVista] = useState<"exec" | "corrida">("exec");
  const [cfgRaw, setCfg] = useState<Cfg>(CFG0);
  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg((c) => ({ ...c, [k]: v }));
  // Necesario antes de execDe (usa cfg): el capital resuelto va abajo, aqui solo la config.
  const cfg: Cfg = cfgRaw;
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
  const [mcRunning, setMcRunning] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);

  // ── Paso 4: nivel por la caida, reparto y tamano por setup ─────────────
  const [niveles, setNiveles] = useState<RawNivelesOut | null>(null);
  const [nivelesRunning, setNivelesRunning] = useState(false);
  const [nivelesError, setNivelesError] = useState<string | null>(null);
  const [reparto, setReparto] = useState<RawRepartoOut | null>(null);
  const [repartoRunning, setRepartoRunning] = useState(false);
  const [repartoError, setRepartoError] = useState<string | null>(null);
  const [setup, setSetup] = useState<RawSetupIn>(SETUP0);
  const [outSetup, setOutSetup] = useState<RawOut | null>(null);
  const [outConst, setOutConst] = useState<RawOut | null>(null);
  const [setupKey, setSetupKey] = useState("");
  const [setupRunning, setSetupRunning] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);

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
  const capitalEfectivo = cfgRaw.capital > 0 ? cfgRaw.capital : capitalCorridas;
  const perStrategy: Record<string, RawExec> = {};
  for (const s of selected) perStrategy[s.id] = execDe(s.id);
  const defaultExec: RawExec = { sizing: "auto", size_value: cfg.pctComun, size_unit: "pct", fees: cfg.fees, fee_type: cfg.feeType, slippage_pct: slipDefault, locates: "none", locates_cost: 0, locates_min: 1, locates_max: 10, locates_seed: 1 };

  const cfgKey = JSON.stringify({ ids: selectedIds, cfg, capitalEfectivo, perStrategy, loc });
  const stale = out != null && ranKey !== cfgKey;
  const problema: string | null =
    !selectedIds.length ? "Marca al menos una estrategia."
    : capitalEfectivo <= 0 ? "Pon un capital mayor que cero."
    : selected.some((s) => pctDe(cfg, s.id) <= 0) ? "Alguna estrategia marcada tiene el % por trade a cero."
    : loc.mode === "fixed" && loc.cost <= 0 ? "Los locates fijos necesitan un precio por paquete."
    : loc.mode === "random" && loc.max <= loc.min ? "En los locates aleatorios el máximo tiene que ser mayor que el mínimo."
    : null;

  // v3: sin tope de exposicion, ni «una a la vez», ni tope por accion (el
  // motor los sigue admitiendo por API; aqui van apagados).
  const cuerpo = (): RawConfigIn => ({
    strategy_ids: selectedIds,
    capital: capitalEfectivo,
    per_strategy: perStrategy,
    default_exec: defaultExec,
    max_exposure_usd: 0,
    max_exposure_pct: 0,
    one_per_ticker: false,
    max_ticker_pct: 0,
    ticker_cap_basis: "risk",
    margin: cfg.margin ? { enabled: true, broker: cfg.marginBroker || "sagetrader", capacity_pct: 100 } : null,
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
      setNiveles(null);
      setReparto(null);
      setOutSetup(null);
      setOutConst(null);
      setSetupKey("");
      setAbiertos((a) => ({ ...a, 1: false, 2: true }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo calcular el portfolio");
    } finally {
      setRunning(false);
    }
  };

  // Se remuestrean los RETORNOS diarios (% del capital con el que empezo
  // cada dia) y se componen, no los $ de cada dia sumados: con una curva que
  // compone, un dia de −50 M $ puesto donde la cuenta tenia 100 k $ daba
  // drawdowns de −40.000 % (visto el 16-sep). Con `risk_pct: 1` el motor hace
  // equity *= 1 + ret/100, es decir, compone tal cual.
  const mcDe = (o: RawOut) => {
    const cap = o.config.capital;
    const rets = o.daily_pnl.map((v, i) => {
      const open = i === 0 ? cap : o.equity[i - 1];
      return open > 0 ? (v / open) * 100 : 0;
    });
    return runPortfolioMc({
      values: rets,
      init_cash: cap,
      simulations: Number(mcSims) || 5000,
      method: "bootstrap",
      mode: "compound",
      risk_pct: 1,
      ruin_pct: 50,
    });
  };
  const simularMc = async () => {
    if (!out || mcRunning) return;
    setMcRunning(true);
    setMcError(null);
    try {
      setMcOut(await mcDe(out));
    } catch (e) {
      setMcError(e instanceof Error ? e.message : "No se pudo simular");
    } finally {
      setMcRunning(false);
    }
  };
  // ── Paso 4 ────────────────────────────────────────────────────────────
  const calcularNiveles = async () => {
    if (!out || nivelesRunning) return;
    setNivelesRunning(true);
    setNivelesError(null);
    try {
      setNiveles(await runPortfolioNiveles({ ...cuerpo(), factors: [0.5, 0.75, 1, 1.25, 1.5, 2], mc_sims: Math.min(5000, Number(mcSims) || 2000) }));
    } catch (e) {
      setNivelesError(e instanceof Error ? e.message : "No se pudieron calcular los niveles");
    } finally {
      setNivelesRunning(false);
    }
  };
  const calcularReparto = async () => {
    if (!out || repartoRunning) return;
    setRepartoRunning(true);
    setRepartoError(null);
    try {
      setReparto(await runPortfolioReparto({ ...cuerpo(), split: 0.5 }));
    } catch (e) {
      setRepartoError(e instanceof Error ? e.message : "No se pudo calcular el reparto");
    } finally {
      setRepartoRunning(false);
    }
  };
  const setupKeyNow = JSON.stringify({ ranKey, setup });
  const setupStale = outSetup != null && setupKey !== setupKeyNow;
  const calcularSetup = async () => {
    if (!out || setupRunning) return;
    setSetupRunning(true);
    setSetupError(null);
    try {
      const conSetup = await runPortfolioRaw({ ...cuerpo(), setup: { ...setup, enabled: true } });
      if (!conSetup.setup) throw new Error("El backend que responde no lleva el tamaño por setup: hay que reiniciarlo (con el bot parado).");
      setOutSetup(conSetup);
      // La comparacion honesta: el % constante con el MISMO tamano medio que
      // acabo aplicando la tabla a cada estrategia.
      const base = cuerpo();
      const per: Record<string, RawExec> = { ...base.per_strategy };
      for (const p of conSetup.setup.por_estrategia) {
        const st = selected.find((x) => x.name === p.name);
        if (!st) continue;
        const ex = per[st.id] ?? base.default_exec;
        per[st.id] = { ...ex, size_value: ex.size_value * p.mult_medio };
      }
      setOutConst(await runPortfolioRaw({ ...base, per_strategy: per }));
      setSetupKey(setupKeyNow);
    } catch (e) {
      setSetupError(e instanceof Error ? e.message : "No se pudo calcular el tamaño por setup");
    } finally {
      setSetupRunning(false);
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
  const resumen1 = `${selectedIds.length} ${selectedIds.length === 1 ? "estrategia" : "estrategias"} · ${usd(capitalEfectivo)} · ${cfg.pctMismo ? `${n(cfg.pctComun, 2)} % por trade` : "% por estrategia"}${cfg.fees > 0 ? ` · comisiones ${n(cfg.fees, cfg.feeType === "FLAT" ? 4 : 3)} ${cfg.feeType === "FLAT" ? "$/acc" : "%"}` : ""}${cfg.margin ? " · margen" : ""} · ${locatesResumen(loc)}${cfg.expenses > 0 ? ` · ${usd(cfg.expenses)}/mes` : ""}`;
  const resumen2 = out ? `retorno ${pct(out.metrics.total_return_pct)} · max DD ${pct(curvas?.sumaMaxDd)} · ${n(out.metrics.n_trades, 0)} trades · Sharpe ${n(out.metrics.sharpe)}${stale ? " · (desactualizado)" : ""}` : "";
  const resumen3 = mcOut ? `DD a tragar (1 de 20) ${pct(mcOut.dd_tolerance?.p95)} · prob. de acabar perdiendo ${pct(mcOut.prob_losing_pct)}` : "Monte Carlo sin simular";
  const nivelActual = niveles?.niveles.find((f) => Math.abs(f.factor - 1) < 1e-9);
  const resumen4 = [
    nivelActual?.mc ? `al nivel del paso 1, DD a tragar ${pct(nivelActual.mc.dd_p95)}` : "nivel por la caída",
    reparto ? `reparto OOS ×${n(reparto.candidatos[0]?.oos.mult, 1)} vs ×${n(reparto.candidatos[1]?.oos.mult, 1)} tus %` : "reparto",
    outSetup ? `setup ${usd(outSetup.equity[outSetup.equity.length - 1])}${outConst ? ` vs constante ${usd(outConst.equity[outConst.equity.length - 1])}` : ""}${setupStale ? " (desactualizado)" : ""}` : "tamaño por setup",
  ].join(" · ");

  const listo = !!out && !!curvas && !!exposicion;
  const pasos = [
    { num: 1, label: "Ejecución", hecho: listo && !stale, disponible: true },
    { num: 2, label: "Visión general", hecho: listo, disponible: listo },
    { num: 3, label: "Monte Carlo", hecho: !!mcOut, disponible: listo },
    { num: 4, label: "Nivel y setups", hecho: !!(niveles || reparto || outSetup), disponible: listo && !backendViejo },
    { num: 5, label: "Cuenta real", hecho: false, disponible: true },
  ];
  const activo = !listo ? 1 : abiertos[4] && (niveles || reparto || outSetup) ? 4 : abiertos[3] ? 3 : abiertos[2] ? 2 : 1;

  return (
    <div>
      <PasoBar pasos={pasos} activo={activo} onGo={ir} />

      <Paso num={1} title="Ejecución" open={!!abiertos[1]} onToggle={() => toggle(1)} summary={resumen1} sinRelleno
        help="Las estrategias marcadas entran normalizadas; aquí se les pone lo del portfolio: el % por trade de cada una (el mismo para todas o uno por estrategia), comisiones, slippage, locates, capital, gastos fijos, margen y periodo. Calcular reconstruye la suma desde los trades guardados; nada se vuelve a correr ni se modifica.">
        <div style={{ padding: "10px 10px 0" }}>
          <PasoEjecucion m={{ pool, checked, setChecked, selected, selectedIds, slipDefault, setSlipDefault, slipRaw, setSlipRaw, slipDe, vista, setVista, abierta, curves, desplegar, onMove, cfgRaw, cfg: { ...cfg, capital: capitalEfectivo }, set, setCfg, capitalCorridas, loc, setLoc, problema, stale, running, calcular, error }} />
        </div>
      </Paso>

      {backendViejo && (
        <Nota tone="warning">
          El backend que responde no lleva todavía los locates de la cuenta ni el paso 4 (motor del 16-sep): los locates del paso 1 se han ignorado y el paso 4 está apagado. Se aplica con el bot parado.
        </Nota>
      )}

      <Paso num={2} title="Visión general" open={!!abiertos[2]} onToggle={() => toggle(2)} summary={resumen2} disabled={!listo} disabledNote="primero calcula el paso 1"
        help="Lo que habría hecho una cuenta operando todas las estrategias marcadas a la vez con la ejecución del paso 1. Pestañas: el resumen con la curva y el drawdown, la exposición al minuto, la tabla por estrategia, la correlación y el calendario.">
        {listo && out && curvas && exposicion && <PasoVision m={{ out, curvas, propias, exposicion, yMode, setYMode }} />}
      </Paso>

      <Paso num={3} title="Monte Carlo" open={!!abiertos[3]} onToggle={() => toggle(3)} summary={resumen3} disabled={!listo} disabledNote="primero calcula el paso 1"
        help="Lo que podría pasar remuestreando los días del portfolio con reemplazo (bootstrap): el drawdown que hay que estar dispuesto a tragar, la probabilidad de acabar perdiendo y la tabla de percentiles.">
        {listo && out && <PasoMonteCarlo m={{ out, mcOut, mcSims, setMcSims, mcRunning, mcError, simularMc }} />}
      </Paso>

      <Paso num={4} title="Nivel y setups" open={!!abiertos[4]} onToggle={() => toggle(4)} summary={resumen4} disabled={!listo || backendViejo} disabledNote={backendViejo ? "el backend todavía no lleva el paso 4" : "primero calcula el paso 1"}
        help="Tres preguntas sobre el portfolio del paso 1. A: ¿a qué nivel de la cuenta? (tus % × un factor, con la caída real y la del Monte Carlo: se elige por la caída que tragas). B: ¿cómo repartir entre estrategias? (Kelly conjunta con correlaciones, estimada en la primera mitad y comprobada en la segunda contra tus %). C: ¿más tamaño en los mejores setups? (la Kelly relativa de cada tramo de precio, walk-forward por años, comparada contra un % constante con el mismo tamaño medio: si no gana a eso, no añade nada)."
        sinRelleno>
        {listo && out && <PasoNivel m={{ out, nombres: selected.map((s) => s.name), niveles, nivelesRunning, nivelesError, calcularNiveles, reparto, repartoRunning, repartoError, calcularReparto, setup, setSetup, outSetup, outConst, setupRunning, setupError, setupStale, calcularSetup }} />}
      </Paso>

      <Paso num={5} title="Cuenta real" open={!!abiertos[5]} onToggle={() => toggle(5)} summary="Kelly sobre tu operativa real y el reparto entre estrategias"
        help="El fichero de tu cuenta real (el export de DAS en .csv o .xlsx, o fecha y PnL) y la unidad de la R: sale la Kelly de TU cuenta (fills, slippage y locates reales incluidos) → cuánto arriesgar en total el siguiente periodo, y ese total repartido entre las estrategias con los pesos del paso 1 (o los del reparto B si lo has calculado). No hace falta saber de qué estrategia viene cada trade.">
        <div style={{ padding: "10px 10px 6px" }}>
          <PasoCuentaReal m={{ out, capital: capitalEfectivo, pesos: selected.map((s, i) => ({ name: s.name, kelly_pct: reparto && reparto.recomendado.pct[i] != null && reparto.strategy_ids[i] === s.id ? reparto.recomendado.pct[i] : pctDe(cfg, s.id), basis: porSlDe(s) ? "risk" as const : "capital" as const })), origenPesos: reparto ? "el reparto B (Kelly conjunta, todo el histórico)" : "los % del paso 1" }} />
        </div>
      </Paso>

      <p style={{ margin: "0 0 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
        Todo se reconstruye desde los trades guardados de cada corrida; no se vuelve a correr ningún backtest ni se
        modifica ninguna estrategia. Black Swan y Halts no se pueden reconstruir así: quedan para una fase con backtest
        efímero, si hace falta. La pestaña <strong>Imagen general</strong> sigue siendo la del portfolio normalizado que lee el bot.
      </p>
    </div>
  );
}
