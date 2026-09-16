"use client";

// Sub-pestaña «En crudo» de Portfolio: la SUMA de varias corridas guardadas,
// cada una con la EJECUCION QUE SE FIJA AQUI (tamaño por trade, comisiones,
// slippage y locates, como en el panel izquierdo del Backtester), reseteando
// lo que tenia la corrida. Los gastos fijos y el tope de exposicion son del
// portfolio. La pregunta: si operara todas estas estrategias a la vez, con
// esta ejecucion, ¿como quedaria la curva y cuanto ganaria o perderia?
//
// Nada se vuelve a correr: el motor (portfolio_lab_raw) deshace los costes y
// el tamaño de cada trade guardado y reaplica los de aqui. Black Swan y Halts
// no se pueden reconstruir desde los trades: quedan para una fase con
// backtest efimero, si hace falta.
//
// La pestaña «Imagen general» (normalizada) sigue siendo la fuente del bot.
// Estilo hoja de datos (como el Genético): secciones con hairline, controles
// cuadrados, cifras grandes sobre el fondo, «?» en cada bloque.

import React, { Fragment, useCallback, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { color, font, hairline } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { SpaghettiChart, DistributionChart } from "@/components/robustez/charts/MonteCarloCharts";
import { CorrelationMatrix } from "../charts/CorrelationMatrix";
import {
  RAW_EXEC_DEFAULT,
  getPortfolioStrategyEquity,
  runPortfolioMc,
  runPortfolioRaw,
  type PortfolioStrategy,
  type RawExec,
  type RawOut,
} from "@/lib/api_portfolio_lab";
import { StrategyDetail } from "../StrategyDetail";
import { MoveBtn, type CurveState } from "../StrategyShelf";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Btn, Num, Row, Sec, Stat, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";
import { ExposureChart, PnlDdChart, type Serie } from "./CrudoCharts";
import { CalendarioCrudo } from "./CalendarioCrudo";

interface Cfg {
  /** 0 = la suma de los capitales de las corridas marcadas. */
  capital: number;
  expenses: number;
  cap: number;
  capUnit: "usd" | "pct";
  /** Solo una estrategia abierta a la vez por accion. */
  onePerTicker: boolean;
  start: string;
  end: string;
}

const CFG0: Cfg = { capital: 0, expenses: 0, cap: 0, capUnit: "pct", onePerTicker: false, start: "", end: "" };

/** Curva propia de una serie (base + PnL diario) y su drawdown, con el pico
 *  arrancando en la base. Antes del primer dia con trades, NaN.
 *
 *  Con `eqOpen` (el capital con el que empieza cada dia la SUMA) el drawdown
 *  de la serie se mide como la perdida desde su maximo RELATIVA al capital de
 *  ese dia. Es lo que tiene sentido para una estrategia que comparte cuenta:
 *  su tamaño compone sobre el capital de la suma, asi que medir su bache
 *  contra una base fija daba cifras sin sentido (−33.000 % visto el 14-sep). */
function curvaPropia(pnl: number[], trades: number[], base: number, eqOpen?: number[]) {
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
function condiciones(p: Record<string, unknown>) {
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
      ? `aleatorios ${n(num("locates_random_min"), 0)}–${n(num("locates_random_max"), 0)} (semilla ${n(num("locates_seed"), 0)})`
      : num("locates_cost") === 0 ? "0" : `${n(num("locates_cost"), 2)} ${String(p.locate_type ?? "FLAT").toUpperCase() === "PERCENT" ? "%" : "$"}/100`,
    gastos: num("monthly_expenses") === 0 ? "0" : `${n(num("monthly_expenses"), 0)} $/mes`,
    periodo: `${String(p.start_date ?? "?").slice(0, 10)} → ${String(p.end_date ?? "?").slice(0, 10)}`,
  };
}

/** La ejecucion de la propia corrida, en el formato de aqui (boton «= corrida»). */
function execDeCorrida(p: Record<string, unknown>): RawExec {
  const num = (k: string) => Number(p[k] ?? 0) || 0;
  const isPct = String(p.risk_type ?? "").toUpperCase() === "PERCENT";
  const ft = String(p.fee_type ?? "FLAT").toUpperCase() === "PERCENT" ? "PERCENT" : "FLAT";
  const random = !!p.locates_random;
  return {
    sizing: "auto",
    size_value: num("risk_r"),
    size_unit: isPct ? "pct" : "usd",
    fees: ft === "PERCENT" ? num("fees") * 100 : num("fees"),
    fee_type: ft,
    slippage_pct: num("slippage") * 100,
    locates: random ? "random" : num("locates_cost") > 0 ? "fixed" : "none",
    locates_cost: num("locates_cost"),
    locates_min: random ? num("locates_random_min") : 1,
    locates_max: random ? num("locates_random_max") : 10,
    locates_seed: random ? num("locates_seed") : 1,
  };
}

const sel: React.CSSProperties = { ...control, height: 24, fontSize: 11, padding: "2px 4px", fontFamily: font.sans, cursor: "pointer" };
const numChico: React.CSSProperties = { height: 24, fontSize: 11, padding: "2px 5px", textAlign: "right" };

/** Controles de la ejecucion de UNA fila (o de la fila «por defecto»): el R
 *  por trade (fijo o %), comisiones, slippage y locates. Si va por SL o por
 *  capital lo decide la ESTRATEGIA (su «Tamaño por SL»), como en el
 *  backtester: aqui se enseña como etiqueta, no se elige. */
function ExecCells({ e, onChange, porSl }: { e: RawExec; onChange: (next: RawExec) => void; porSl: boolean | null }) {
  const set = <K extends keyof RawExec>(k: K, v: RawExec[K]) => onChange({ ...e, [k]: v });
  const fijo = e.sizing === "as_saved";
  return (
    <>
      <td style={{ ...tdTxt, padding: "2px 6px" }}>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <div style={{ width: 70 }}><Num value={e.size_value} onChange={(v) => set("size_value", Number(v) || 0)} min={0} step={e.size_unit === "pct" ? 0.5 : 100} disabled={fijo} style={numChico} /></div>
          <select style={{ ...sel, width: 52 }} value={e.size_unit} disabled={fijo} onChange={(ev) => set("size_unit", ev.target.value as RawExec["size_unit"])}>
            <option value="pct">%</option>
            <option value="usd">$</option>
          </select>
          {porSl != null && (
            <span
              title={porSl ? "La estrategia dimensiona por stop: 1R es lo que se pierde si salta el stop" : "La estrategia dimensiona por capital: 1R es el dinero que se mete en el trade"}
              style={{ fontSize: 9.5, fontFamily: font.sans, color: color.textMuted, whiteSpace: "nowrap", cursor: "help" }}
            >
              {porSl ? "por SL" : "por capital"}
            </span>
          )}
        </div>
      </td>
      <td style={{ ...tdTxt, padding: "2px 6px" }}>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <div style={{ width: 70 }}><Num value={e.fees} onChange={(v) => set("fees", Number(v) || 0)} min={0} step={e.fee_type === "PERCENT" ? 0.001 : 0.0005} disabled={fijo} style={numChico} /></div>
          <select style={{ ...sel, width: 64 }} value={e.fee_type} disabled={fijo} onChange={(ev) => set("fee_type", ev.target.value as RawExec["fee_type"])}>
            <option value="FLAT">$/acc</option>
            <option value="PERCENT">%</option>
          </select>
        </div>
      </td>
      <td style={{ ...tdTxt, padding: "2px 6px" }}>
        <div style={{ width: 64 }}><Num value={e.slippage_pct} onChange={(v) => set("slippage_pct", Number(v) || 0)} min={0} step={0.05} disabled={fijo} style={numChico} /></div>
      </td>
      <td style={{ ...tdTxt, padding: "2px 6px" }}>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <select style={{ ...sel, width: 88 }} value={e.locates} disabled={fijo} onChange={(ev) => set("locates", ev.target.value as RawExec["locates"])}>
            <option value="none">sin locates</option>
            <option value="fixed">fijos</option>
            <option value="random">aleatorios</option>
          </select>
          {e.locates === "fixed" && (
            <>
              <div style={{ width: 58 }}><Num value={e.locates_cost} onChange={(v) => set("locates_cost", Number(v) || 0)} min={0} step={0.5} disabled={fijo} style={numChico} /></div>
              <span style={{ fontSize: 9.5, color: color.textMuted }}>$/100</span>
            </>
          )}
          {e.locates === "random" && (
            <>
              <div style={{ width: 46 }}><Num value={e.locates_min} onChange={(v) => set("locates_min", Number(v) || 0)} min={0} step={0.5} disabled={fijo} style={numChico} /></div>
              <span style={{ fontSize: 9.5, color: color.textMuted }}>–</span>
              <div style={{ width: 46 }}><Num value={e.locates_max} onChange={(v) => set("locates_max", Number(v) || 0)} min={0} step={0.5} disabled={fijo} style={numChico} /></div>
              <span style={{ fontSize: 9.5, color: color.textMuted }}>$/100 · semilla</span>
              <div style={{ width: 44 }}><Num value={e.locates_seed} onChange={(v) => set("locates_seed", Math.round(Number(v) || 0))} min={0} step={1} disabled={fijo} style={numChico} /></div>
            </>
          )}
        </div>
      </td>
    </>
  );
}

export function CrudoTab({ strategies, onMove }: { strategies: PortfolioStrategy[]; onMove?: (s: PortfolioStrategy, dir: -1 | 1, visibles: string[]) => void }) {
  const pool = useMemo(() => strategies.filter((s) => s.run), [strategies]);

  // Marcadas por defecto: las del cuadro Portfolio. Se guarda solo lo que el
  // usuario ha tocado; el resto se deriva al pintar.
  const [checkedRaw, setChecked] = useState<Record<string, boolean>>({});
  const checked = useMemo(() => {
    const next: Record<string, boolean> = {};
    for (const s of pool) next[s.id] = checkedRaw[s.id] ?? s.buckets.includes("portfolio");
    return next;
  }, [pool, checkedRaw]);

  // Ejecucion por estrategia; la fila «por defecto» rellena las que no se han tocado.
  const [defaultExec, setDefaultExec] = useState<RawExec>({ ...RAW_EXEC_DEFAULT });
  const [execRaw, setExecRaw] = useState<Record<string, RawExec>>({});
  const execDe = (id: string): RawExec => execRaw[id] ?? defaultExec;
  const [vista, setVista] = useState<"exec" | "corrida">("exec");

  const [cfgRaw, setCfg] = useState<Cfg>(CFG0);
  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg((c) => ({ ...c, [k]: v }));

  // Fila desplegada (los datos de la estrategia, como en el Baul) y su curva,
  // que se pide al abrir y se guarda.
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

  const [mcOut, setMcOut] = useState<MonteCarloOut | null>(null);
  const [mcSims, setMcSims] = useState<number | "">(5000);
  const [mcMethod, setMcMethod] = useState<"bootstrap" | "permutacion">("bootstrap");
  const [mcRunning, setMcRunning] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);

  const selected = pool.filter((s) => checked[s.id]);
  const selectedIds = selected.map((s) => s.id);

  const capitalCorridas = selected.reduce((a, s) => a + (Number((s.run?.backtest_params as Record<string, unknown> | undefined)?.init_cash) || 0), 0);
  const cfg: Cfg = { ...cfgRaw, capital: cfgRaw.capital > 0 ? cfgRaw.capital : capitalCorridas };
  const perStrategy: Record<string, RawExec> = {};
  for (const s of selected) perStrategy[s.id] = execDe(s.id);

  const cfgKey = JSON.stringify({ ids: selectedIds, cfg, perStrategy });
  const stale = out != null && ranKey !== cfgKey;
  const problema: string | null =
    !selectedIds.length ? "Marca al menos una estrategia."
    : cfg.capital <= 0 ? "Pon un capital mayor que cero."
    : selected.some((s) => { const e = execDe(s.id); return e.sizing !== "as_saved" && e.size_value <= 0; }) ? "Alguna estrategia marcada tiene el tamaño por trade a cero."
    : null;

  const calcular = async () => {
    if (problema || running) return;
    setRunning(true);
    setError(null);
    try {
      const res = await runPortfolioRaw({
        strategy_ids: selectedIds,
        capital: cfg.capital,
        per_strategy: perStrategy,
        default_exec: defaultExec,
        max_exposure_usd: cfg.capUnit === "usd" ? cfg.cap : 0,
        max_exposure_pct: cfg.capUnit === "pct" ? cfg.cap : 0,
        one_per_ticker: !!cfg.onePerTicker,
        cap_mode: "skip",
        monthly_expenses: cfg.expenses,
        start_date: cfg.start || null,
        end_date: cfg.end || null,
      });
      // El motor viejo del backend ignora `per_strategy` y responderia con
      // otra cosa sin avisar: se reconoce al nuevo por `config.default_exec`.
      if (!res.config?.default_exec) {
        throw new Error("El backend todavía no lleva el motor de ejecución por estrategia (portfolio_lab_raw.py, portfolio_lab_engine.py y el router): hay que aplicar los tres ficheros con el bot parado.");
      }
      setOut(res);
      setRanKey(cfgKey);
      setMcOut(null);
      setMcError(null);
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
      const res = await runPortfolioMc({
        values: out.daily_pnl,
        init_cash: out.config.capital,
        simulations: Number(mcSims) || 5000,
        method: mcMethod,
        mode: "additive",
        // En modo aditivo el riesgo no interviene, pero el modelo exige > 0.
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

  // ── Series de los graficos (todas sobre el capital del portfolio) ─────
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

  // Exposicion como % del capital DEL DIA (no del inicial).
  const exposicion = useMemo(() => {
    if (!out) return null;
    const cap = out.config.capital;
    const pctS = out.exposure.peak_daily.map((v, i) => {
      const open = i === 0 ? cap : out.equity[i - 1];
      return open > 0 ? (v / open) * 100 : 0;
    });
    return { pct: pctS, max: Math.max(0, ...pctS) };
  }, [out]);

  const fmtY = (v: number) => (yMode === "usd" ? usdCorto(v) : `${n(v, 0)} %`);
  const fmtHover = (v: number) => (yMode === "usd" ? `${n(v, 0)} $` : `${n(v, 2)} %`);

  if (!pool.length) {
    return (
      <p style={{ fontSize: 12, fontFamily: font.sans, color: color.textMuted, padding: "30px 0", textAlign: "center" }}>
        No hay estrategias con backtest guardado. Corre una en el Backtester y guárdala en el baúl.
      </p>
    );
  }

  const m = out?.metrics;
  const totalPnl = out ? out.equity[out.equity.length - 1] - out.config.capital : 0;
  const sep = { borderTop: `1px solid ${color.border}` };
  const costesTot = out ? out.costs.fees + (out.costs.slippage || 0) + out.costs.locates + out.costs.expenses : 0;

  return (
    <div>
      {/* ── 1. Estrategias y su ejecucion AQUI ── */}
      <Sec
        title="Estrategias — ejecución de cada una en este portfolio"
        help={
          <>
            Lo del panel izquierdo del Backtester, pero fijado aquí y por estrategia: lo que tenía cada corrida se
            <strong> resetea</strong> para este cálculo (nada se guarda ni se toca en la estrategia).
            <br /><br />
            <strong>R por trade</strong> — lo mismo que «Riesgo por trade» del panel del Backtester: fijo en $ o en %
            del capital del portfolio con el que empieza cada día. Si ese R es lo que se pierde al stop o el dinero
            que se mete lo decide <strong>la estrategia</strong> (su «Tamaño por SL»), como siempre; aquí se enseña
            como etiqueta al lado del R.
            <br /><br />
            <strong>Comisiones</strong> en $ por acción o % del valor (los dos lados). <strong>Slippage</strong> en %
            del precio en cada lado. <strong>Locates</strong>: fijos ($ por paquete de 100, por ticker y día sobre el
            mayor corto) o aleatorios con el mismo sorteo del Backtester (rango y semilla).
            <br /><br />
            La fila <strong>por defecto</strong> es la ejecución de todas las que no se hayan tocado; «→ todas» la copia
            a todas las marcadas. «= corrida» pone en una fila lo que tenía su corrida. Con «cómo se corrió» ves las
            condiciones originales de cada una, y pulsando el nombre (o la flecha) se despliegan debajo los datos
            de la estrategia: universo, entrada, salida, riesgo, con qué se corrió y su curva.
          </>
        }
        sinRelleno
        right={
          <>
            <div style={{ width: 190 }}>
              <Toggle value={vista} onChange={setVista} options={[{ value: "exec", label: "ejecución aquí" }, { value: "corrida", label: "cómo se corrió" }]} />
            </div>
            <Btn onClick={() => setChecked(Object.fromEntries(pool.map((s) => [s.id, true])))}>todas</Btn>
            <Btn onClick={() => setChecked(Object.fromEntries(pool.map((s) => [s.id, s.buckets.includes("portfolio")])))}>las del cuadro Portfolio</Btn>
            <Btn onClick={() => setChecked(Object.fromEntries(pool.map((s) => [s.id, false])))}>ninguna</Btn>
          </>
        }
      >
        <div style={{ maxHeight: abierta ? undefined : 30 * 15 + 60, overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ position: "sticky", top: 0, background: color.bgSurface, zIndex: 1 }}>
              {vista === "exec" ? (
                <tr>
                  <th style={{ ...thL, width: 26 }} />
                  <th style={{ ...thL, width: 14 }} />
                  <th style={{ ...thL, width: 18 }} />
                  <th style={{ ...thL, width: 44 }} />
                  <th style={thL}>Estrategia</th>
                  <th style={thL}>R por trade</th>
                  <th style={thL}>Comisiones</th>
                  <th style={thL}>Slippage %</th>
                  <th style={thL}>Locates</th>
                  <th style={{ ...thL, width: 90 }} />
                </tr>
              ) : (
                <tr>
                  <th style={{ ...thL, width: 26 }} />
                  <th style={{ ...thL, width: 14 }} />
                  <th style={{ ...thL, width: 18 }} />
                  <th style={{ ...thL, width: 44 }} />
                  <th style={thL}>Estrategia</th>
                  <th style={thL}>Corrida</th>
                  <th style={thL}>Periodo</th>
                  <th style={thR}>Capital</th>
                  <th style={thR}>Tamaño</th>
                  <th style={thR}>Comisiones</th>
                  <th style={thR}>Slippage</th>
                  <th style={thR}>Locates</th>
                  <th style={thR}>Gastos</th>
                  <th style={thR}>Trades</th>
                  <th style={thR}>PF</th>
                  <th style={thR}>Retorno</th>
                </tr>
              )}
            </thead>
            <tbody>
              {vista === "exec" && (
                <tr style={{ background: color.bgElevated }}>
                  <td style={tdTxt} />
                  <td style={tdTxt} />
                  <td style={tdTxt} />
                  <td style={tdTxt} />
                  <td style={{ ...tdTxt, color: color.copperText, fontWeight: 600 }}>Por defecto</td>
                  <ExecCells e={defaultExec} onChange={setDefaultExec} porSl={null} />
                  <td style={{ ...tdTxt, padding: "2px 6px" }}>
                    <Btn onClick={() => setExecRaw((x) => { const nx = { ...x }; for (const s of selected) nx[s.id] = { ...defaultExec }; return nx; })} title="Copia la fila por defecto a todas las estrategias marcadas">→ todas</Btn>
                  </td>
                </tr>
              )}
              {pool.map((s, idx) => {
                const on = !!checked[s.id];
                const ci = selectedIds.indexOf(s.id);
                const visibles = pool.map((x) => x.id);
                const params = (s.run?.backtest_params || {}) as Record<string, unknown>;
                const c = condiciones(params);
                const ret = s.run?.total_return_pct ?? null;
                const open = abierta === s.id;
                const nCols = vista === "exec" ? 10 : 16;
                const cabecera = (
                  <>
                    <td style={{ ...tdTxt, padding: "0 4px 0 10px" }}>
                      <input type="checkbox" checked={on} onChange={(e) => setChecked((x) => ({ ...x, [s.id]: e.target.checked }))} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
                    </td>
                    <td style={{ ...tdTxt, padding: "0 4px" }}>
                      <span style={{ display: "block", width: 10, height: 10, background: on && ci >= 0 ? colorSerie(ci) : color.border }} />
                    </td>
                    <td style={{ ...tdTxt, padding: "0 2px", cursor: "pointer" }} onClick={() => desplegar(s)} title={open ? "Plegar" : "Ver los datos de la estrategia"}>
                      <ChevronRight style={{ width: 12, height: 12, strokeWidth: 1.5, color: color.textMuted, transform: open ? "rotate(90deg)" : "none", transition: "transform 150ms", display: "block" }} />
                    </td>
                    <td style={{ ...tdTxt, padding: "0 4px" }}>
                      {onMove && (
                        <span style={{ display: "inline-flex", gap: 2 }}>
                          <MoveBtn dir={-1} disabled={idx === 0} onClick={() => onMove(s, -1, visibles)} />
                          <MoveBtn dir={1} disabled={idx === pool.length - 1} onClick={() => onMove(s, 1, visibles)} />
                        </span>
                      )}
                    </td>
                    <td style={{ ...tdTxt, maxWidth: 230, overflow: "hidden", textOverflow: "ellipsis", cursor: "pointer", color: open ? color.copperText : color.textHigh }} onClick={() => desplegar(s)} title={`corrida del ${(s.run?.executed_at || "").slice(0, 10)} · ${c.periodo} · capital ${usd(c.capital)} · ${c.tamano} · comisiones ${c.comisiones} · slippage ${c.slippage} · locates ${c.locates} · gastos ${c.gastos} — pulsa para ver los datos de la estrategia`}>
                      {s.name}
                    </td>
                  </>
                );
                const detalle = open && (
                  <tr key={`${s.id}-detalle`}>
                    <td colSpan={nCols} style={{ padding: 0, borderBottom: `1px solid ${color.border}` }}>
                      <StrategyDetail s={s} curve={curves[s.id]} paddingLeft={44} />
                    </td>
                  </tr>
                );
                if (vista === "exec") {
                  const e = execDe(s.id);
                  const propio = !!execRaw[s.id];
                  return (
                    <Fragment key={s.id}>
                      <tr style={{ opacity: on ? 1 : 0.5 }}>
                        {cabecera}
                        <ExecCells e={e} onChange={(next) => setExecRaw((x) => ({ ...x, [s.id]: next }))} porSl={!!(((s.definition as Record<string, unknown> | undefined)?.risk_management as Record<string, unknown> | undefined)?.size_by_sl ?? params.size_by_sl)} />
                        <td style={{ ...tdTxt, padding: "2px 6px" }}>
                          <div style={{ display: "flex", gap: 4 }}>
                            <Btn onClick={() => setExecRaw((x) => ({ ...x, [s.id]: execDeCorrida(params) }))} title="Poner en esta fila la ejecución con la que se guardó su corrida">= corrida</Btn>
                            {propio && <Btn onClick={() => setExecRaw((x) => { const nx = { ...x }; delete nx[s.id]; return nx; })} title="Volver a la fila por defecto">↺</Btn>}
                          </div>
                        </td>
                      </tr>
                      {detalle}
                    </Fragment>
                  );
                }
                return (
                  <Fragment key={s.id}>
                  <tr style={{ opacity: on ? 1 : 0.5 }}>
                    {cabecera}
                    <td style={{ ...tdTxt, fontFamily: font.mono, color: color.textMuted }}>{(s.run?.executed_at || "").slice(0, 10)}</td>
                    <td style={{ ...tdTxt, fontFamily: font.mono, color: color.textSecondary }}>{c.periodo}</td>
                    <td style={tdNum}>{usd(c.capital)}</td>
                    <td style={tdNum}>{c.tamano}</td>
                    <td style={tdNum}>{c.comisiones}</td>
                    <td style={tdNum}>{c.slippage}</td>
                    <td style={tdNum}>{c.locates}</td>
                    <td style={{ ...tdNum, color: color.textMuted }}>{c.gastos}</td>
                    <td style={tdNum}>{n(s.run?.total_trades ?? null, 0)}</td>
                    <td style={tdNum}>{n(s.run?.profit_factor ?? null, 2)}</td>
                    <td style={{ ...tdNum, color: ret == null ? color.textMuted : ret >= 0 ? color.profit : color.loss }}>{pct(ret)}</td>
                  </tr>
                  {detalle}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Sec>

      {/* ── 2. Portfolio ── */}
      <Sec
        title="Portfolio"
        help={
          <>
            <strong>Capital</strong>: el del portfolio; es la base del % por trade (compound: cada día se usa el capital
            con el que empieza), del retorno y del drawdown. <strong>Gastos fijos</strong>: de esta cuenta, el primer día
            operado de cada mes; los de las corridas no cuentan. <strong>Tope de exposición</strong> (opcional): lo máximo
            que puede haber en posiciones abiertas a la vez sumando todas las estrategias, en % del capital <em>del
            día</em> o en $; un trade que no cabe no se entra. 0 = sin tope. <strong>Una a la vez por acción</strong>
            (opcional): en cada acción solo la primera estrategia que da señal; las demás esperan a que salga.
          </>
        }
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 28 }}>
          <div>
            <Row label="Capital">
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={{ width: 160, flexShrink: 0 }}>
                  <Num value={cfgRaw.capital || ""} onChange={(v) => set("capital", Number(v) || 0)} min={0} step={5000} placeholder={String(Math.round(capitalCorridas))} />
                </div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, whiteSpace: "nowrap" }}>
                  {cfgRaw.capital > 0 ? (
                    <>suma de las corridas: {usd(capitalCorridas)} · <button type="button" onClick={() => set("capital", 0)} style={{ background: "none", border: "none", padding: 0, color: color.copperText, cursor: "pointer", fontSize: 10.5, fontFamily: font.sans }}>usar la suma</button></>
                  ) : (
                    "= suma de los capitales de las corridas marcadas"
                  )}
                </span>
              </div>
            </Row>
            <Row label="Gastos fijos ($/mes)">
              <div style={{ width: 160 }}><Num value={cfg.expenses} onChange={(v) => set("expenses", Number(v) || 0)} min={0} step={25} /></div>
            </Row>
            <Row label="Tope de exposición">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ width: 100 }}><Num value={cfg.cap} onChange={(v) => set("cap", Number(v) || 0)} min={0} step={cfg.capUnit === "pct" ? 10 : 5000} /></div>
                <div style={{ width: 150 }}>
                  <Toggle value={cfg.capUnit} onChange={(u) => setCfg((c) => ({ ...c, capUnit: u, cap: 0 }))} options={[{ value: "pct", label: "% del día" }, { value: "usd", label: "$" }]} />
                </div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{cfg.cap > 0 ? "" : "sin tope"}</span>
              </div>
            </Row>
            <Row label="Una a la vez por acción" help="En cada acción entra solo la primera estrategia que da señal; mientras su posición está abierta, las demás no entran en esa acción. Cuando sale (stop, take profit, lo que sea), vuelve a entrar la primera que dé señal, sea la que sea. Se resuelve al minuto con las horas de entrada y salida guardadas; a igual minuto manda el orden de la lista (la de más arriba). Las señales que se quedan fuera salen en la columna «Bloqueadas». Ojo: las señales que una estrategia bloqueada habría tenido después, mientras en su propio backtest estaba dentro, no existen en los datos guardados, así que el resultado es, si acaso, conservador.">
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11.5, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer" }}>
                {/* `!!`: tras una recarga en caliente el estado viejo no trae el
                    campo y `undefined` haria el input no controlado. */}
                <input type="checkbox" checked={!!cfg.onePerTicker} onChange={(e) => set("onePerTicker", e.target.checked)} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
                solo una estrategia abierta a la vez en cada acción
              </label>
            </Row>
          </div>
          <div>
            <Row label="Periodo" help="Vacío = todo el histórico de cada corrida. Cada estrategia solo cuenta en el tramo en que tiene trades.">
              <div style={{ display: "flex", gap: 6 }}>
                <input type="date" style={{ ...control, fontFamily: font.sans }} value={cfg.start} onChange={(e) => set("start", e.target.value)} />
                <input type="date" style={{ ...control, fontFamily: font.sans }} value={cfg.end} onChange={(e) => set("end", e.target.value)} />
              </div>
            </Row>
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0 4px" }}>
              <Btn primary onClick={calcular} disabled={!!problema || running}>{running ? "Calculando…" : "Calcular"}</Btn>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: problema || stale ? color.warning : color.textMuted }}>
                {problema
                  ? problema
                  : stale
                    ? "ha cambiado algo desde el último cálculo"
                    : `${selectedIds.length} ${selectedIds.length === 1 ? "estrategia" : "estrategias"} sobre ${usd(cfg.capital)} · se reconstruye desde los trades guardados, tarda menos de un segundo`}
              </span>
            </div>
          </div>
        </div>
        {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
      </Sec>

      {!out || !m || !curvas || !exposicion ? (
        <p style={{ fontSize: 12, fontFamily: font.sans, color: color.textMuted, padding: "20px 0", textAlign: "center" }}>
          Marca las estrategias, fija la ejecución de cada una y pulsa <strong>Calcular</strong>.
        </p>
      ) : (
        <>
          {/* ── 3. Cifras del conjunto ── */}
          <Sec title="Resultado de la suma" help="Lo que habría hecho una cuenta operando todas las estrategias marcadas a la vez con la ejecución fijada arriba. «En posiciones a la vez»: el mayor porcentaje del capital del día que llegó a estar metido en posiciones abiertas simultáneamente, sumando todas (medido al minuto: un trade de premercado y uno de RTH no coinciden si no se solapan).">
            <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 16px", padding: "4px 0" }}>
              <Stat big label="Retorno neto" value={pct(m.total_return_pct)} sub={usd(totalPnl)} tone={m.total_return_pct >= 0 ? "profit" : "loss"} />
              <Stat label="CAGR" value={pct(m.cagr_pct)} />
              <Stat label="Max DD" value={pct(curvas.sumaMaxDd)} sub={`${m.longest_dd_days} días el más largo`} tone="loss" />
              <Stat label="Sharpe" value={n(m.sharpe)} sub={`Sortino ${n(m.sortino)} · Calmar ${n(m.calmar)}`} />
              <Stat label="Trades" value={n(m.n_trades, 0)} sub={`win ${pct(m.win_rate)} · PF ${n(m.profit_factor)}`} />
              <Stat label="En posiciones a la vez (máx.)" value={`${n(exposicion.max, 0)} %`} sub={`del capital del día · hasta ${usd(out.exposure.max_usd)} · ${Math.max(0, ...out.exposure.max_open_daily)} posiciones`} tone={exposicion.max > 100 ? "warning" : undefined} />
              <Stat label="Costes" value={usd(costesTot)} sub={`comis. ${usd(out.costs.fees)} · slippage ${usd(out.costs.slippage || 0)} · locates ${usd(out.costs.locates)} · fijos ${usd(out.costs.expenses)}`} tone="loss" />
              {out.cap_report.skipped > 0 && <Stat label="Fuera por el tope" value={n(out.cap_report.skipped, 0)} sub={`trades de ${n(out.cap_report.taken + out.cap_report.skipped, 0)}`} tone="warning" />}
              {(out.cap_report.blocked || 0) > 0 && <Stat label="Bloqueadas" value={n(out.cap_report.blocked, 0)} sub="señales con otra estrategia ya dentro" help="Trades de las corridas que no entran porque otra estrategia ya tenía posición abierta en esa acción (opción «una a la vez por acción»)." tone="warning" />}
            </div>
            {out.ruined && <p style={{ margin: "4px 0 0", fontSize: 11, fontFamily: font.sans, color: color.loss }}>La cuenta llegó a cero antes del final: a partir de ahí no se abre ningún trade más.</p>}
            {m.total_return_pct > 100000 && (
              <p style={{ margin: "4px 0 0", fontSize: 11, fontFamily: font.sans, color: color.warning, lineHeight: 1.5 }}>
                Un R en % del capital compone cada día: con varios trades al día y PF &gt; 1 la cifra se dispara y deja de decir nada. Baja el %, ponlo en $ fijos, o acorta el periodo.
              </p>
            )}
            {out.cap_report.unsized > 0 && (
              <p style={{ margin: "4px 0 0", fontSize: 10.5, fontFamily: font.sans, color: color.warning }}>
                {out.cap_report.unsized} trades sin tamaño o precio válidos se han dejado fuera.
              </p>
            )}
          </Sec>

          {/* ── 4. Curvas con su drawdown, y la tabla al lado ── */}
          <Sec
            title="PnL acumulado y drawdown — cada estrategia y la suma"
            help="Arriba, el PnL acumulado: una línea por estrategia y la suma en cobre, sobre el mismo calendario (un día sin operar arrastra el valor anterior). Abajo, el drawdown: el de la suma es el normal (caída desde su máximo); el de cada estrategia es su pérdida desde su máximo relativa al capital que había ese día en la cuenta, que es lo que pesa cuando varias comparten cuenta. Las etiquetas del borde derecho son el valor final."
            right={<div style={{ width: 90 }}><Toggle value={yMode} onChange={setYMode} options={[{ value: "usd", label: "$" }, { value: "pct", label: "%" }]} /></div>}
            sinRelleno
          >
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: 0, alignItems: "start" }}>
              <PnlDdChart labels={out.calendar} pnl={curvas.pnl} dd={curvas.dd} yFormat={fmtY} hoverFormat={fmtHover} height={430} />
              <div style={{ borderLeft: `1px solid ${color.border}`, alignSelf: "stretch" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={thL}>Serie</th>
                      <th style={thR}>PnL</th>
                      <th style={thR}>Retorno</th>
                      <th style={thR}>Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {out.per_strategy.map((p, i) => (
                      <tr key={p.strategy_id}>
                        <td style={{ ...tdTxt, maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis" }} title={p.name}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><span style={{ width: 9, height: 9, background: colorSerie(i), display: "inline-block", flexShrink: 0 }} />{p.name}</span>
                        </td>
                        <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{usdCorto(p.totals.pnl_net)}</td>
                        <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{pct((p.totals.pnl_net / out.config.capital) * 100, 0)}</td>
                        <td style={{ ...tdNum, color: color.loss }}>{pct(propias[i]?.maxDd)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td style={{ ...tdTxt, ...sep, color: color.copper, fontWeight: 600 }}>Suma</td>
                      <td style={{ ...tdNum, ...sep, color: totalPnl >= 0 ? color.profit : color.loss }}>{usdCorto(totalPnl)}</td>
                      <td style={{ ...tdNum, ...sep, color: m.total_return_pct >= 0 ? color.profit : color.loss }}>{pct(m.total_return_pct, 0)}</td>
                      <td style={{ ...tdNum, ...sep, color: color.loss }}>{pct(curvas.sumaMaxDd)}</td>
                    </tr>
                  </tbody>
                </table>
                <p style={{ margin: 0, padding: "8px 10px", fontSize: 10, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                  Todo sobre el capital del portfolio ({usd(out.config.capital)}): el retorno de cada estrategia es lo que aporta.
                </p>
              </div>
            </div>
          </Sec>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 380px", gap: 14, alignItems: "start" }}>
            <Sec title="En posiciones a la vez — % del capital del día" help="La suma de los nocionales (acciones × precio de entrada) de todos los trades abiertos en el mismo instante, de todas las estrategias, partida por el capital con el que empezó ese día la suma. Se mide al minuto: un trade de premercado que cierra a las 09:29 y uno de RTH que abre a las 09:35 no cuentan a la vez. Por encima del 100 % hace falta margen." sinRelleno>
              <ExposureChart labels={out.calendar} pct={exposicion.pct} usd={out.exposure.peak_daily} maxOpen={out.exposure.max_open_daily} height={220} />
            </Sec>
            <Sec title="Lectura">
              <p style={{ margin: "4px 0 6px", fontSize: 11, fontFamily: font.sans, color: color.textSecondary, lineHeight: 1.55 }}>
                Con un 4 % por trade y 7 trades abiertos a la vez (de la estrategia que sea) el día marca 28 %. Es
                el dato para el tope de exposición y para repartir el capital.
              </p>
              <div style={{ display: "flex", flexWrap: "wrap" }}>
                <Stat label="Máximo" value={`${n(exposicion.max, 0)} %`} sub={`${usd(out.exposure.max_usd)} en posiciones`} tone={exposicion.max > 100 ? "warning" : undefined} />
                <Stat label="Días por encima del 100 %" value={n(exposicion.pct.filter((v) => v > 100).length, 0)} sub={`de ${n(out.calendar.length, 0)} operados`} />
                <Stat label="Posiciones a la vez (máx.)" value={n(Math.max(0, ...out.exposure.max_open_daily), 0)} />
              </div>
            </Sec>
          </div>

          {/* ── 5. Tabla por estrategia ── */}
          <Sec title="Por estrategia" help="Cada una con la ejecución fijada arriba. Retorno y drawdown sobre el capital del portfolio (el retorno es lo que aporta); Sharpe y Sortino sobre sus propios días. «Aporta»: su parte del PnL total (solo cuando el conjunto gana). «Nocional medio»: el valor medio con el que entró cada trade. La R de cada trade es neto / (distancia inicial al stop × acciones); «stop ≈» cuenta los trades en que la distancia inicial no se pudo recuperar y se usó el último stop guardado." sinRelleno>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thL}>Estrategia</th>
                  <th style={thL}>Ejecución</th>
                  <th style={thR}>Trades</th>
                  <th style={thR}>Win</th>
                  <th style={thR}>PF</th>
                  <th style={thR}>PnL neto</th>
                  <th style={thR}>Aporta</th>
                  <th style={thR}>Retorno</th>
                  <th style={thR}>Max DD</th>
                  <th style={thR}>Sharpe</th>
                  <th style={thR}>Sortino</th>
                  <th style={thR}>Nocional medio</th>
                  <th style={thR}>Comis.</th>
                  <th style={thR}>Slippage</th>
                  <th style={thR}>Locates</th>
                  <th style={thR}>stop ≈</th>
                  {out.config.one_per_ticker && <th style={thR}>Bloqueadas</th>}
                </tr>
              </thead>
              <tbody>
                {out.per_strategy.map((p, i) => {
                  const e = p.exec;
                  const ej = !e ? "—" : e.sizing === "as_saved" ? "tal cual" : `R ${n(e.size_value, e.size_unit === "pct" ? 2 : 0)} ${e.size_unit === "pct" ? "%" : "$"} ${e.sizing === "risk" ? "por SL" : "por capital"}`;
                  return (
                    <tr key={p.strategy_id}>
                      <td style={tdTxt}><span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><span style={{ width: 10, height: 10, background: colorSerie(i), display: "inline-block" }} />{p.name}</span></td>
                      <td style={{ ...tdTxt, fontFamily: font.mono, color: color.textSecondary }}>{ej}</td>
                      <td style={tdNum}>{n(p.totals.n_trades, 0)}</td>
                      <td style={tdNum}>{pct(p.totals.win_rate)}</td>
                      <td style={tdNum}>{n(p.totals.profit_factor)}</td>
                      <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{usd(p.totals.pnl_net)}</td>
                      <td style={tdNum} title={totalPnl > 0 ? "parte del PnL total que pone esta estrategia" : "el conjunto no gana: no hay reparto que enseñar"}>{totalPnl > 0 ? pct((p.totals.pnl_net / totalPnl) * 100, 0) : "—"}</td>
                      <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{pct((p.totals.pnl_net / out.config.capital) * 100)}</td>
                      <td style={{ ...tdNum, color: color.loss }}>{pct(propias[i]?.maxDd)}</td>
                      <td style={tdNum}>{n(p.metrics?.sharpe)}</td>
                      <td style={tdNum}>{n(p.metrics?.sortino)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.avg_notional)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.fees)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.slippage || 0)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.locates)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }} title={`${n(p.totals.sin_stop || 0, 0)} sin stop guardado (R = 0)`}>{n(p.totals.stop_aprox || 0, 0)}</td>
                      {out.config.one_per_ticker && <td style={{ ...tdNum, color: (p.cap_report.blocked || 0) > 0 ? color.warning : color.textMuted }}>{n(p.cap_report.blocked || 0, 0)}</td>}
                    </tr>
                  );
                })}
                <tr>
                  <td style={{ ...tdTxt, ...sep, color: color.copper, fontWeight: 600 }}>Suma</td>
                  <td style={{ ...tdTxt, ...sep, fontFamily: font.mono, color: color.textMuted }}>{out.calendar[0]} → {out.calendar[out.calendar.length - 1]}</td>
                  <td style={{ ...tdNum, ...sep }}>{n(m.n_trades, 0)}</td>
                  <td style={{ ...tdNum, ...sep }}>{pct(m.win_rate)}</td>
                  <td style={{ ...tdNum, ...sep }}>{n(m.profit_factor)}</td>
                  <td style={{ ...tdNum, ...sep, color: totalPnl >= 0 ? color.profit : color.loss }}>{usd(totalPnl)}</td>
                  <td style={{ ...tdNum, ...sep }}>{totalPnl > 0 ? "100 %" : "—"}</td>
                  <td style={{ ...tdNum, ...sep, color: m.total_return_pct >= 0 ? color.profit : color.loss }}>{pct(m.total_return_pct)}</td>
                  <td style={{ ...tdNum, ...sep, color: color.loss }}>{pct(curvas.sumaMaxDd)}</td>
                  <td style={{ ...tdNum, ...sep }}>{n(m.sharpe)}</td>
                  <td style={{ ...tdNum, ...sep }}>{n(m.sortino)}</td>
                  <td style={{ ...tdNum, ...sep }} />
                  <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{usd(out.costs.fees)}</td>
                  <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{usd(out.costs.slippage || 0)}</td>
                  <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{usd(out.costs.locates)}</td>
                  <td style={{ ...tdNum, ...sep }} />
                  {out.config.one_per_ticker && <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{n(out.cap_report.blocked || 0, 0)}</td>}
                </tr>
              </tbody>
            </table>
            {out.locates_random && out.locates_random.n > 0 && (
              <p style={{ margin: 0, padding: "6px 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, borderTop: hairline }}>
                Locates sorteados: {n(out.locates_random.n, 0)} ticker-días · mediana {n(out.locates_random.p50, 2)} $ por paquete de 100 (p10 {n(out.locates_random.p10, 2)} · p90 {n(out.locates_random.p90, 2)}).
              </p>
            )}
          </Sec>

          {/* ── 6. Correlacion ── */}
          <Sec title="Correlación del PnL diario" help="Entre parejas, solo en el tramo en que ambas tienen trades. Por debajo de 0,3 diversifican de verdad; por encima de 0,7 son la misma apuesta dos veces.">
            {out.correlation ? (
              <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 24, alignItems: "start" }}>
                <CorrelationMatrix corr={out.correlation} names={out.per_strategy.map((p) => p.name)} />
                <div style={{ display: "flex", flexWrap: "wrap", marginTop: 6 }}>
                  <Stat label="Media de parejas" value={out.correlation.avg_pairwise == null ? "—" : n(out.correlation.avg_pairwise)} tone={out.correlation.avg_pairwise == null ? undefined : out.correlation.avg_pairwise > 0.7 ? "loss" : out.correlation.avg_pairwise > 0.3 ? "warning" : "profit"} />
                  {out.correlation.max_pair && (
                    <Stat label="Pareja más correlacionada" value={n(out.correlation.max_pair.corr)} sub={`${out.per_strategy[out.correlation.max_pair.i]?.name} · ${out.per_strategy[out.correlation.max_pair.j]?.name}`} />
                  )}
                </div>
              </div>
            ) : (
              <p style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textMuted, margin: "8px 0" }}>Hacen falta al menos dos estrategias.</p>
            )}
          </Sec>

          {/* ── 7. Calendario ── */}
          <Sec title="Calendario de la suma" help="El mismo calendario del Backtester, sobre el resultado del conjunto: Profits (bruto, antes de costes), Gastos (comisiones + slippage + locates + gastos fijos) y Profits − Gastos, en $ o en R. Pulsa un día para ver sus trades por estrategia.">
            <div style={{ padding: "8px 0 4px" }}>
              <CalendarioCrudo out={out} names={out.per_strategy.map((p) => p.name)} />
            </div>
          </Sec>

          {/* ── 8. Monte Carlo ── */}
          <Sec
            title="Monte Carlo de la suma"
            help="Remuestrea los DÍAS del conjunto (bootstrap con reemplazo o permutación del orden), no los trades: los de una misma sesión van correlacionados. Dice cuánto del resultado depende del orden en que llegaron los días y qué drawdown hay que estar dispuesto a tragar."
            right={
              <>
                <div style={{ width: 80 }}><Num value={mcSims} onChange={setMcSims} min={500} max={20000} step={500} style={{ height: 24, fontSize: 11 }} /></div>
                <div style={{ width: 200 }}><Toggle value={mcMethod} onChange={setMcMethod} options={[{ value: "bootstrap", label: "Bootstrap" }, { value: "permutacion", label: "Permutación" }]} /></div>
                <Btn primary onClick={simularMc} disabled={mcRunning}>{mcRunning ? "Simulando…" : "Simular"}</Btn>
              </>
            }
          >
            {mcError && <ErrorBox>{mcError}</ErrorBox>}
            {!mcOut ? (
              <p style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textMuted, margin: "10px 0" }}>Pulsa <strong>Simular</strong>.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "6px 0" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 16px" }}>
                  <Stat label="DD mediano simulado" value={pct(mcOut.drawdown?.p50)} tone="loss" />
                  <Stat label="DD a tragar (1 de 20)" value={pct(mcOut.dd_tolerance?.p95)} tone="loss" help="Para que solo 1 de cada 20 escenarios lo supere, hay que aguantar este drawdown." />
                  <Stat label="DD a tragar (1 de 100)" value={pct(mcOut.dd_tolerance?.p99)} tone="loss" />
                  <Stat label="Prob. de acabar perdiendo" value={pct(mcOut.prob_losing_pct)} />
                  <Stat label="Prob. de ruina (−50 %)" value={pct(mcOut.prob_ruin_pct)} />
                  <Stat label="Balance mediano" value={usd(mcOut.final_balance?.p50)} />
                </div>
                <SpaghettiChart spaghetti={mcOut.spaghetti} bands={mcOut.bands} baseCurve={mcOut.base_curve} initCash={mcOut.init_cash} xLabel="días →" />
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
                  <DistributionChart hist={mcOut.hist_final} markers={[{ value: mcOut.base_final, label: `real ${usd(mcOut.base_final)}`, color: "var(--color-ec-copper)" }]} caption="Balance final de cada escenario simulado." />
                  <DistributionChart hist={mcOut.hist_drawdown} markers={[{ value: mcOut.base_max_drawdown, label: `real ${pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]} fmtValue={(v) => `${v.toFixed(0)}%`} barColor="var(--color-ec-loss)" caption="Max drawdown de cada escenario simulado (%)." />
                </div>
              </div>
            )}
          </Sec>

          <p style={{ margin: "0 0 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
            Todo se reconstruye desde los trades guardados de cada corrida; no se vuelve a correr ningún backtest ni se
            modifica ninguna estrategia. Black Swan y Halts no se pueden reconstruir así: quedan para una fase con backtest
            efímero, si hace falta. La pestaña <strong>Imagen general</strong> sigue siendo la del portfolio normalizado que lee el bot.
          </p>
        </>
      )}
    </div>
  );
}
