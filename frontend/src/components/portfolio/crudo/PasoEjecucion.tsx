"use client";

// Paso 1 de «En crudo»: que estrategias entran, con que ejecucion cada una
// (R por trade, comisiones, slippage) y lo que es de la CUENTA (capital,
// gastos fijos, tope, una a la vez, locates, periodo). Termina en Calcular.

import React, { Fragment } from "react";
import { ChevronRight } from "lucide-react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { PortfolioStrategy, RawExec } from "@/lib/api_portfolio_lab";
import { StrategyDetail } from "../StrategyDetail";
import { MoveBtn, type CurveState } from "../StrategyShelf";
import { Btn, Num, Row, Sec, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { GATE_METRIC_LABEL, condiciones, execDeCorrida, type Cfg, type LocCfg } from "./modelo";

export interface EjecucionModel {
  pool: PortfolioStrategy[];
  checked: Record<string, boolean>;
  setChecked: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  selected: PortfolioStrategy[];
  selectedIds: string[];
  defaultExec: RawExec;
  setDefaultExec: React.Dispatch<React.SetStateAction<RawExec>>;
  execRaw: Record<string, RawExec>;
  setExecRaw: React.Dispatch<React.SetStateAction<Record<string, RawExec>>>;
  execDe: (id: string) => RawExec;
  vista: "exec" | "corrida";
  setVista: (v: "exec" | "corrida") => void;
  abierta: string | null;
  curves: Record<string, CurveState>;
  desplegar: (s: PortfolioStrategy) => void;
  onMove?: (s: PortfolioStrategy, dir: -1 | 1, visibles: string[]) => void;
  cfgRaw: Cfg;
  cfg: Cfg;
  set: <K extends keyof Cfg>(k: K, v: Cfg[K]) => void;
  setCfg: React.Dispatch<React.SetStateAction<Cfg>>;
  capitalCorridas: number;
  loc: LocCfg;
  setLoc: React.Dispatch<React.SetStateAction<LocCfg>>;
  problema: string | null;
  stale: boolean;
  running: boolean;
  calcular: () => void;
  error: string | null;
}

const sel: React.CSSProperties = { ...control, height: 24, fontSize: 11, padding: "2px 4px", fontFamily: font.sans, cursor: "pointer" };
const numChico: React.CSSProperties = { height: 24, fontSize: 11, padding: "2px 5px", textAlign: "right" };

/** Controles de la ejecucion de UNA fila (o de la fila «por defecto»): el R
 *  por trade (fijo o %), comisiones y slippage. Si va por SL o por capital lo
 *  decide la ESTRATEGIA (su «Tamaño por SL»), como en el backtester: aqui se
 *  enseña como etiqueta, no se elige. Los locates son de la cuenta (abajo). */
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
    </>
  );
}

export function PasoEjecucion({ m }: { m: EjecucionModel }) {
  const { pool, checked, setChecked, selected, selectedIds, defaultExec, setDefaultExec, execRaw, setExecRaw, execDe, vista, setVista, abierta, curves, desplegar, onMove, cfgRaw, cfg, set, setCfg, capitalCorridas, loc, setLoc, problema, stale, running, calcular, error } = m;
  const setL = <K extends keyof LocCfg>(k: K, v: LocCfg[K]) => setLoc((l) => ({ ...l, [k]: v }));

  return (
    <>
      <Sec
        title="Estrategias — ejecución de cada una"
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
            del precio en cada lado. Los <strong>locates</strong> ya no van por fila: son de la cuenta, en el bloque
            Portfolio de abajo.
            <br /><br />
            La fila <strong>por defecto</strong> es la ejecución de todas las que no se hayan tocado; «→ todas» la copia
            a todas las marcadas. «= corrida» pone en una fila lo que tenía su corrida. Con «cómo se corrió» ves las
            condiciones originales de cada una, y pulsando el nombre (o la flecha) se despliegan debajo los datos
            de la estrategia.
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
                const nCols = vista === "exec" ? 9 : 16;
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
                            <Btn onClick={() => setExecRaw((x) => ({ ...x, [s.id]: execDeCorrida(params) }))} title="Poner en esta fila la ejecución con la que se guardó su corrida (R, comisiones y slippage)">= corrida</Btn>
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

      <Sec
        title="Portfolio — la cuenta"
        help={
          <>
            <strong>Capital</strong>: el del portfolio; es la base del % por trade (compound: cada día se usa el capital
            con el que empieza), del retorno y del drawdown. <strong>Gastos fijos</strong>: de esta cuenta, el primer día
            operado de cada mes; los de las corridas no cuentan. <strong>Tope de exposición</strong> (opcional): lo máximo
            que puede haber en posiciones abiertas a la vez sumando todas las estrategias, en % del capital <em>del
            día</em> o en $; un trade que no cabe no se entra. 0 = sin tope. <strong>Una a la vez por acción</strong>
            (opcional): en cada acción solo la primera estrategia que da señal; las demás esperan a que salga.
            <br /><br />
            <strong>Locates</strong>: el bróker es uno, así que el modelo de precio (fijo por paquete de 100, o aleatorio
            con el sorteo del Backtester) vale para todas. <strong>Compartidos</strong>: por cada acción y día se alquila
            una sola vez lo que la cuenta necesita —el máximo de acciones en corto <em>a la vez</em> sumando
            estrategias—; la que cubre libera, y la siguiente que cabe en lo alquilado va gratis (la de premercado
            paga, la de RTH no). Paga la que provoca el paquete de más. «Por estrategia» es lo de antes: cada una
            alquila lo suyo aunque coincidan. <strong>Puerta de los cortos</strong>: decide si un corto entra según
            lo que le cuesta el locate («fade necesario»: el % que tiene que moverse la acción solo para pagar los
            paquetes de más que exige). «Fade máximo» es la regla que gana en la auditoría del 17-sep; las de EV
            comparan el fade con el edge medio de la estrategia (todo el histórico, o los últimos N trades). Con
            locates compartidos lo ya alquilado por cualquiera va gratis, así que muchas entradas pasan sin coste.
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
            <Row label="Una a la vez por acción" help="En cada acción entra solo la primera estrategia que da señal; mientras su posición está abierta, las demás no entran en esa acción. Cuando sale (stop, take profit, lo que sea), vuelve a entrar la primera que dé señal, sea la que sea. Se resuelve al minuto con las horas de entrada y salida guardadas; a igual minuto manda el orden de la lista (la de más arriba). Las señales que se quedan fuera salen como «Bloqueadas». Ojo: las señales que una estrategia bloqueada habría tenido después, mientras en su propio backtest estaba dentro, no existen en los datos guardados, así que el resultado es, si acaso, conservador.">
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11.5, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer" }}>
                <input type="checkbox" checked={!!cfg.onePerTicker} onChange={(e) => set("onePerTicker", e.target.checked)} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
                solo una estrategia abierta a la vez en cada acción
              </label>
            </Row>
            <Row label="Periodo" help="Vacío = todo el histórico de cada corrida. Cada estrategia solo cuenta en el tramo en que tiene trades.">
              <div style={{ display: "flex", gap: 6 }}>
                <input type="date" style={{ ...control, fontFamily: font.sans }} value={cfg.start} onChange={(e) => set("start", e.target.value)} />
                <input type="date" style={{ ...control, fontFamily: font.sans }} value={cfg.end} onChange={(e) => set("end", e.target.value)} />
              </div>
            </Row>
          </div>
          <div>
            <Row label="Locates">
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <select style={{ ...sel, width: 110, height: 28 }} value={loc.mode} onChange={(ev) => setL("mode", ev.target.value as LocCfg["mode"])}>
                  <option value="none">sin locates</option>
                  <option value="fixed">fijos</option>
                  <option value="random">aleatorios</option>
                </select>
                {loc.mode === "fixed" && (
                  <>
                    <div style={{ width: 70 }}><Num value={loc.cost} onChange={(v) => setL("cost", Number(v) || 0)} min={0} step={0.5} /></div>
                    <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>$ por paquete de 100</span>
                  </>
                )}
                {loc.mode === "random" && (
                  <>
                    <div style={{ width: 56 }}><Num value={loc.min} onChange={(v) => setL("min", Number(v) || 0)} min={0} step={0.5} /></div>
                    <span style={{ fontSize: 10.5, color: color.textMuted }}>–</span>
                    <div style={{ width: 56 }}><Num value={loc.max} onChange={(v) => setL("max", Number(v) || 0)} min={0} step={0.5} /></div>
                    <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>$/100 · semilla</span>
                    <div style={{ width: 52 }}><Num value={loc.seed} onChange={(v) => setL("seed", Math.round(Number(v) || 0))} min={0} step={1} /></div>
                  </>
                )}
              </div>
            </Row>
            {loc.mode !== "none" && (
              <>
                <Row label="Alquiler">
                  <div style={{ width: 300 }}>
                    <Toggle value={loc.shared ? "shared" : "row"} onChange={(v) => setL("shared", v === "shared")} options={[{ value: "shared", label: "compartido por acción y día" }, { value: "row", label: "cada estrategia el suyo" }]} />
                  </div>
                </Row>
                <Row label="Puerta por EV/MFE/Fade" help="Un corto entra solo si la medida elegida (EV, MFE medio o fade medio, en % del precio de entrada; las tres se ven en Charts → «EV por precio» del backtester) paga el «fade necesario»: el % que tiene que moverse la acción a favor solo para pagar los paquetes de más que exige ese corto (con alquiler compartido, lo ya alquilado por cualquiera va gratis). «EV rodante»: lo de siempre, el EV por defecto hasta que la estrategia tiene historia y luego la media de sus últimos N trades cerrados; ojo, con N = 30 el error de la estimación es mayor que el propio EV y rechaza por racha (auditoría del 17-sep). «EV fijo»: SIEMPRE se enfrenta ese valor al fade — pon el EV que midas en IS y mira qué tal va en OOS; entra si EV fijo > fade.">
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11.5, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer" }}>
                      <input type="checkbox" checked={!!loc.gate} onChange={(e) => setL("gate", e.target.checked)} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
                      activa
                    </label>
                    {loc.gate && (
                      <>
                        <div style={{ width: 250 }}>
                          <Toggle value={loc.gateMetric ?? "ev"} onChange={(v) => setL("gateMetric", v)} options={[{ value: "ev", label: "EV" }, { value: "mfe", label: "MFE" }, { value: "fade", label: "Fade" }]} />
                        </div>
                        <div style={{ width: 200 }}>
                          <Toggle value={loc.gateMode ?? "ev_rodante"} onChange={(v) => setL("gateMode", v)} options={[{ value: "ev_rodante", label: "rodante" }, { value: "ev_fijo", label: "fijo" }]} />
                        </div>
                        {(loc.gateMode ?? "ev_rodante") === "ev_rodante" ? (
                          <>
                            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>últimos</span>
                            <div style={{ width: 56 }}><Num value={loc.gateVentana} onChange={(v) => setL("gateVentana", Math.max(1, Math.round(Number(v) || 0)))} min={1} step={5} /></div>
                            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>trades · valor sin historia</span>
                            <div style={{ width: 56 }}><Num value={loc.gateEv} onChange={(v) => setL("gateEv", Number(v) || 0)} min={0} step={0.5} /></div>
                            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>%</span>
                          </>
                        ) : (
                          <>
                            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{GATE_METRIC_LABEL[loc.gateMetric ?? "ev"]}</span>
                            <div style={{ width: 56 }}><Num value={loc.evFijo ?? 3} onChange={(v) => setL("evFijo", Number(v) || 0)} min={0} step={0.5} /></div>
                            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% del precio · entra si supera el fade necesario</span>
                          </>
                        )}
                      </>
                    )}
                  </div>
                </Row>
              </>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0 4px" }}>
              <Btn primary onClick={calcular} disabled={!!problema || running}>{running ? "Calculando…" : "Calcular"}</Btn>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: problema || stale ? color.warning : color.textMuted }}>
                {problema
                  ? problema
                  : stale
                    ? "ha cambiado algo desde el último cálculo"
                    : `${selectedIds.length} ${selectedIds.length === 1 ? "estrategia" : "estrategias"} sobre ${usd(cfg.capital)} · se reconstruye desde los trades guardados`}
              </span>
            </div>
          </div>
        </div>
        {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
      </Sec>
    </>
  );
}
