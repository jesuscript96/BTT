"use client";

// Paso 1 de «En crudo» (v3, 20-sep-2026, Jaume: «vamos a simplificarlo»):
// la lista de estrategias tal cual —entran NORMALIZADAS al motor, y por fila
// solo se toca el slippage— y debajo lo que es del portfolio: el % por trade
// de cada una (el mismo para todas o uno por estrategia), los locates (una
// vez por accion-dia para toda la cuenta, o cada una lo suyo; fijos o
// aleatorios), el capital, los gastos fijos, las comisiones para todas y el
// margen del broker. Termina en Calcular.

import React, { Fragment } from "react";
import { ChevronRight } from "lucide-react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { PortfolioStrategy } from "@/lib/api_portfolio_lab";
import { StrategyDetail } from "../StrategyDetail";
import { MoveBtn, type CurveState } from "../StrategyShelf";
import { Btn, Num, Row, Sec, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { GATE_METRIC_LABEL, condiciones, pctDe, type Cfg, type LocCfg } from "./modelo";

export interface EjecucionModel {
  pool: PortfolioStrategy[];
  checked: Record<string, boolean>;
  setChecked: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  selected: PortfolioStrategy[];
  selectedIds: string[];
  /** Slippage (% del precio, cada lado) por estrategia; sin valor propio, el por defecto. */
  slipDefault: number;
  setSlipDefault: (v: number) => void;
  slipRaw: Record<string, number>;
  setSlipRaw: React.Dispatch<React.SetStateAction<Record<string, number>>>;
  slipDe: (id: string) => number;
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

/** Si la estrategia dimensiona por stop (riesgo) o por capital (posicion): lo
 *  decide su definicion (o los parametros de su corrida). */
export function porSlDe(s: PortfolioStrategy): boolean {
  const params = (s.run?.backtest_params || {}) as Record<string, unknown>;
  const rm = (s.definition as Record<string, unknown> | undefined)?.risk_management as Record<string, unknown> | undefined;
  return !!(rm?.size_by_sl ?? params.size_by_sl);
}

export function PasoEjecucion({ m }: { m: EjecucionModel }) {
  const { pool, checked, setChecked, selected, selectedIds, slipDefault, setSlipDefault, slipRaw, setSlipRaw, slipDe, vista, setVista, abierta, curves, desplegar, onMove, cfgRaw, cfg, set, setCfg, capitalCorridas, loc, setLoc, problema, stale, running, calcular, error } = m;
  const setL = <K extends keyof LocCfg>(k: K, v: LocCfg[K]) => setLoc((l) => ({ ...l, [k]: v }));
  const setPctPor = (id: string, v: number) => setCfg((c) => ({ ...c, pctPor: { ...c.pctPor, [id]: v } }));

  return (
    <>
      <Sec
        title="Estrategias"
        help={
          <>
            Las estrategias entran <strong>normalizadas</strong> (sus corridas guardadas a 1 $ por trade, sin costes):
            así se mide la señal pura de cada una y todo lo demás se pone aquí, en el bloque Portfolio. Por fila solo
            se toca el <strong>slippage</strong> (% del precio en cada lado); «= corrida» pone el de su corrida y «↺»
            vuelve al por defecto. Con «cómo se corrió» ves las condiciones originales, y pulsando el nombre (o la
            flecha) se despliegan debajo los datos de la estrategia.
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
                  <th style={thL}>Dimensiona</th>
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
                  <td style={tdTxt} />
                  <td style={{ ...tdTxt, padding: "2px 6px" }}>
                    <div style={{ width: 64 }}><Num value={slipDefault} onChange={(v) => setSlipDefault(Number(v) || 0)} min={0} step={0.05} style={numChico} /></div>
                  </td>
                  <td style={{ ...tdTxt, padding: "2px 6px" }}>
                    <Btn onClick={() => setSlipRaw({})} title="Quitar los slippages propios: todas con el por defecto">→ todas</Btn>
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
                const nCols = vista === "exec" ? 8 : 16;
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
                  const porSl = porSlDe(s);
                  const propio = s.id in slipRaw;
                  return (
                    <Fragment key={s.id}>
                      <tr style={{ opacity: on ? 1 : 0.5 }}>
                        {cabecera}
                        <td style={{ ...tdTxt, fontSize: 10, color: color.textMuted }} title={porSl ? "Dimensiona por stop: su % es lo que se pierde si salta el stop (riesgo)" : "Dimensiona por capital: su % es el dinero que se mete en el trade (posición)"}>
                          {porSl ? "por SL (riesgo)" : "por capital (posición)"}
                        </td>
                        <td style={{ ...tdTxt, padding: "2px 6px" }}>
                          <div style={{ width: 64 }}><Num value={slipDe(s.id)} onChange={(v) => setSlipRaw((x) => ({ ...x, [s.id]: Number(v) || 0 }))} min={0} step={0.05} style={numChico} /></div>
                        </td>
                        <td style={{ ...tdTxt, padding: "2px 6px" }}>
                          <div style={{ display: "flex", gap: 4 }}>
                            <Btn onClick={() => setSlipRaw((x) => ({ ...x, [s.id]: (Number(params.slippage) || 0) * 100 }))} title="Poner en esta fila el slippage con el que se guardó su corrida">= corrida</Btn>
                            {propio && <Btn onClick={() => setSlipRaw((x) => { const nx = { ...x }; delete nx[s.id]; return nx; })} title="Volver al por defecto">↺</Btn>}
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
            Lo que se aplica a cada estrategia normalizada para montar el portfolio. <strong>% por trade</strong>: lo
            que pone cada estrategia en cada operación, en % del capital con el que empieza el día (compound); el mismo
            para todas, o uno por estrategia. En qué unidad va cada % lo dice su columna «Dimensiona»: <em>riesgo</em>
            (lo que se pierde si salta el stop) si dimensiona por SL, <em>posición</em> (el dinero que se mete) si
            dimensiona por capital, como en su backtest. <strong>Comisiones</strong> para todas: $ por acción (los dos
            lados) o % del valor. <strong>Capital</strong>: la base del compound, del retorno y del drawdown.
            <strong> Gastos fijos</strong>: de la cuenta, el primer día operado de cada mes. <strong>Margen y BP</strong>:
            el margen del bróker sobre todas las posiciones abiertas a la vez; la que no cabe en el equity del día no
            entra (las reglas, en su (?)). <strong>Periodo</strong>: vacío = todo el histórico.
            <br /><br />
            <strong>Locates</strong>: fijos por paquete de 100 o aleatorios (el sorteo del Backtester, banda p10–p90).
            <strong> Una vez por acción y día</strong>: se alquila UNA vez lo que la cuenta necesita (el máximo de
            acciones en corto a la vez sumando estrategias): paga la que provoca el paquete de más, la siguiente que cabe va
            gratis. «Cada estrategia el suyo»: cada una alquila lo suyo aunque coincidan. <strong>Puerta</strong>: un corto
            entra solo si su EV/MFE/Fade paga el «fade necesario» de sus paquetes.
          </>
        }
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 28 }}>
          <div>
            <Row label="% por trade" help="Lo que pone cada estrategia en cada operación, en % del capital del día. «El mismo para todas» o uno por estrategia. La unidad de cada una es la de su backtest (riesgo al stop o posición): la columna «Dimensiona» de arriba.">
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ width: 290 }}>
                    <Toggle value={cfg.pctMismo ? "mismo" : "por"} onChange={(v) => set("pctMismo", v === "mismo")} options={[{ value: "mismo", label: "el mismo para todas" }, { value: "por", label: "por estrategia" }]} />
                  </div>
                  {cfg.pctMismo && (
                    <>
                      <div style={{ width: 70 }}><Num value={cfg.pctComun} onChange={(v) => set("pctComun", Number(v) || 0)} min={0} step={0.25} /></div>
                      <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% del capital del día, cada una en su unidad</span>
                    </>
                  )}
                </div>
                {!cfg.pctMismo && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {selected.length === 0 && <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>marca estrategias arriba</span>}
                    {selected.map((s, i) => (
                      <div key={s.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span style={{ width: 10, height: 10, background: colorSerie(i), display: "inline-block", flexShrink: 0 }} />
                        <span style={{ fontSize: 11, fontFamily: font.sans, color: color.textPrimary, width: 210, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.name}>{s.name}</span>
                        <div style={{ width: 70 }}><Num value={pctDe(cfg, s.id)} onChange={(v) => setPctPor(s.id, Number(v) || 0)} min={0} step={0.25} /></div>
                        <span style={{ fontSize: 10, fontFamily: font.sans, color: color.textMuted }}>% · {porSlDe(s) ? "riesgo" : "posición"}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Row>
            <Row label="Comisiones (todas)">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ width: 80 }}><Num value={cfg.fees} onChange={(v) => set("fees", Number(v) || 0)} min={0} step={cfg.feeType === "PERCENT" ? 0.001 : 0.0005} /></div>
                <select style={{ ...sel, width: 70, height: 28 }} value={cfg.feeType} onChange={(ev) => set("feeType", ev.target.value as Cfg["feeType"])}>
                  <option value="FLAT">$/acc</option>
                  <option value="PERCENT">%</option>
                </select>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{cfg.feeType === "FLAT" ? "por acción, los dos lados" : "del valor, cada lado"}</span>
              </div>
            </Row>
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
            <Row label="Criterios Margen y BP" help={<>
              Simula el margen y el buying power del bróker sobre TODAS las estrategias juntas: cada posición abierta consume margen según su precio y su lado, y la que no cabe en el equity del día no entra. Se recorre el día en orden cronológico entre todas las estrategias; la capacidad es el equity del día.
              <br /><br /><strong>SageTrader (FAQ, sep-2026)</strong>: largos 25 % del valor (4:1 intradía); cortos a partir de 5 $, el mayor de 30 % o 5 $ por acción; entre 2,50 y 5 $, el 100 % del valor; por debajo de 2,50 $, 2,50 $ POR ACCIÓN (a 0,50 $ es el 500 % del nocional).
              <br /><br /><strong>SageTrader estricto</strong>: igual, pero TODOS los cortos a partir de 2,50 $ exigen el 100 % del valor, como cuando el valor está en lista especial (hard to borrow), que es lo habitual en los gappers que se venden en corto. Si en real te deja menos exposición de la que dice la simulación, prueba este.
              <br /><br />La exposición que enseña Visión es el nocional abierto ÷ equity; el margen es otra cosa (mucho menor que el nocional salvo por debajo de 2,50 $): un 80 % de exposición en cortos de 5-15 $ usa un 40-80 % de la capacidad con la FAQ, y el 80 % con el estricto.
            </>}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11.5, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer" }}>
                  <input type="checkbox" checked={!!cfg.margin} onChange={(e) => set("margin", e.target.checked)} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
                  aplicar el margen del bróker
                </label>
                {cfg.margin && (
                  <select value={cfg.marginBroker || "sagetrader"} onChange={(e) => set("marginBroker", e.target.value)} style={{ ...control, fontFamily: font.sans, width: "auto" }}>
                    <option value="sagetrader">SageTrader (FAQ)</option>
                    <option value="sagetrader_estricto">SageTrader estricto (cortos 100 %)</option>
                  </select>
                )}
              </div>
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
                    <Toggle value={loc.shared ? "shared" : "row"} onChange={(v) => setL("shared", v === "shared")} options={[{ value: "shared", label: "una vez por acción y día" }, { value: "row", label: "cada estrategia el suyo" }]} />
                  </div>
                </Row>
                <Row label="Puerta por EV/MFE/Fade" help="Un corto entra solo si la medida elegida (EV, MFE medio o fade medio, en % del precio de entrada; las tres se ven en Charts → «EV por precio» del backtester) paga el «fade necesario»: el % que tiene que moverse la acción a favor solo para pagar los paquetes de más que exige ese corto (con alquiler compartido, lo ya alquilado por cualquiera va gratis). «Rodante»: el valor por defecto hasta que la estrategia tiene historia y luego la media de sus últimos N trades cerrados. «Fijo»: SIEMPRE se enfrenta ese valor al fade; entra si lo supera.">
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
