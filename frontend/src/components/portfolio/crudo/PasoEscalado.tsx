"use client";

// Paso 4 de «En crudo»: escalado y pesos. Cuanto arriesgar por trade en TOTAL
// (Kelly, % fijo, $ fijos, fixed ratio) y como repartirlo entre estrategias
// (HRP de Lopez de Prado y compania), con el tope del usuario sobre la SUMA.
// Dos respuestas: lo que habria que poner HOY, y que habria pasado aplicandolo
// desde el principio (re-estimado en cada rebalanceo solo con datos
// anteriores). Los R de las filas del paso 1 no cuentan aqui.
//
// Unidad de todo esto: RIESGO por trade = lo que se pierde si salta el stop,
// en % del capital con el que empieza el dia. NO es nocional (dinero metido).

import React, { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawOut } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Row, Sec, Stat, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";
import { LinesChart, WeightsChart } from "./CrudoCharts";
import { MODELO_LABEL, curvaPropia, type EscCfg } from "./modelo";

export interface EscaladoModel {
  out: RawOut;
  outEsc: RawOut | null;
  esc: EscCfg;
  setEsc: React.Dispatch<React.SetStateAction<EscCfg>>;
  escRunning: boolean;
  escError: string | null;
  escStale: boolean;
  calcularEsc: () => void;
}

const sel: React.CSSProperties = { ...control, fontFamily: font.sans, cursor: "pointer" };

/** R acumulada por dia del calendario: suma de la R de cada trade de ese dia. */
function rAcumulada(o: RawOut): number[] {
  const porDia = new Map<string, number>();
  for (let k = 0; k < o.trades.date.length; k++) porDia.set(o.trades.date[k], (porDia.get(o.trades.date[k]) || 0) + (o.trades.r[k] || 0));
  let acc = 0;
  return o.calendar.map((d) => { acc += porDia.get(d) || 0; return acc; });
}

function fraccionLabel(m: number) {
  return m === 1 ? "entera (óptima)" : m === 0.5 ? "½" : m === 0.25 ? "¼" : `× ${n(m, 2)}`;
}

export function PasoEscalado({ m }: { m: EscaladoModel }) {
  const { out, outEsc, esc, setEsc, escRunning, escError, escStale, calcularEsc } = m;
  const set = <K extends keyof EscCfg>(k: K, v: EscCfg[K]) => setEsc((c) => ({ ...c, [k]: v }));
  const sc = outEsc?.scaling ?? null;
  const hoy = sc?.today ?? null;
  const cap = out.config.capital;
  const [unidad, setUnidad] = useState<"pct" | "usd" | "r">("pct");

  const comparacion = useMemo(() => {
    if (!outEsc) return null;
    const capE = outEsc.config.capital;
    const serieDe = (o: RawOut, base: number) => {
      if (unidad === "usd") return o.equity.map((v) => v - base);
      if (unidad === "r") return rAcumulada(o);
      return o.equity.map((v) => ((v - base) / base) * 100);
    };
    const series = [
      { name: "R de las filas (paso 1, sin escalar)", color: color.textSecondary, values: serieDe(out, cap) },
      { name: "con escalado y pesos", color: color.copper, width: 2.2, values: serieDe(outEsc, capE) },
    ];
    const ddA = curvaPropia(out.daily_pnl, out.calendar.map(() => 1), cap).maxDd;
    const ddB = curvaPropia(outEsc.daily_pnl, outEsc.calendar.map(() => 1), capE).maxDd;
    const rA = rAcumulada(out); const rB = rAcumulada(outEsc);
    return { series, ddA, ddB, rA: rA[rA.length - 1] || 0, rB: rB[rB.length - 1] || 0 };
  }, [out, outEsc, cap, unidad]);

  const fmtY = (v: number) => (unidad === "usd" ? usdCorto(v) : unidad === "r" ? `${n(v, 0)} R` : `${n(v, 0)} %`);
  const fmtHover = (v: number) => (unidad === "usd" ? `${n(v, 0)} $` : unidad === "r" ? `${n(v, 1)} R` : `${n(v, 1)} %`);

  const names = out.per_strategy.map((p) => p.name);
  const colores = names.map((_, i) => colorSerie(i));
  const kellyMax = hoy ? Math.max(hoy.kelly_raw_pct ?? 0, ...hoy.per_strategy.map((p) => p.kelly_pct ?? 0)) : 0;
  const kellyLoco = hoy?.model === "kelly" && kellyMax > 15;
  const periodosUnaViva = sc ? sc.periods.filter((p) => p.alive === 1).length : 0;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(380px, 1fr) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
        <Sec title="Ajustes" help={
          <>
            Todo es <strong>riesgo por trade</strong>: lo que se pierde si salta el stop, en % del capital con el que
            empieza el día (no el dinero metido en la posición). <strong>Kelly</strong> sale de la historia: la fracción
            que habría hecho crecer más la cuenta sobre los días de la ventana (la exacta, con la distribución real de
            los días; la aproximación clásica μ/σ² se enseña al lado). Solo Kelly manda: no hay HRP ni reparto.
            <br /><br />
            <strong>Kelly de cada estrategia</strong>: cada una con su propia Kelly × la fracción; la que mejor va lleva
            más, la que no tiene edge en la ventana se queda a 0. Si la <em>suma</em> de todas pasa del tope, se
            recortan todas en la misma proporción hasta que la suma sea el tope (la mejor sigue llevando más).
            <strong>Kelly global</strong>: la Kelly del conjunto (los días de todas juntas) × la fracción, topada, y
            repartida entre las estrategias en proporción a la Kelly propia de cada una.
            <br /><br />
            <strong>Fracción</strong>: lo que se aplica de la Kelly (1 = entera; ½ y ¼ las de la práctica; cualquier
            número). <strong>Tope</strong>: lo máximo que se arriesga por trade sumando todas las estrategias; con estas
            curvas (liquidez infinita) es lo único que hace realista el resultado. <strong>Rebalanceo</strong>: cada
            cuánto se re-estima todo, siempre con datos anteriores a ese día. <strong>Ventana</strong>: cuántos días
            naturales de historia se miran; una estrategia sin trades en ella no entra ese periodo.
            <br /><br />
            Los R del paso 1 no cuentan; comisiones, slippage, locates, tope de exposición y «una a la vez» sí. Los
            trades sin stop guardado no se pueden dimensionar por riesgo y quedan fuera (se cuentan). Los modelos sin
            Kelly (% fijo, $ fijos, fixed ratio) reparten el total a partes iguales.
          </>
        }>
          <Row label="Riesgo total">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <select style={{ ...sel, width: 210 }} value={esc.model} onChange={(e) => set("model", e.target.value as EscCfg["model"])}>
                {(Object.keys(MODELO_LABEL) as EscCfg["model"][]).map((k) => <option key={k} value={k}>{MODELO_LABEL[k]}</option>)}
              </select>
              {esc.model === "percent" && (
                <>
                  <div style={{ width: 70 }}><Num value={esc.pct} onChange={(v) => set("pct", Number(v) || 0)} min={0} step={0.25} /></div>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% del capital del día</span>
                </>
              )}
              {(esc.model === "fixed" || esc.model === "fixed_ratio") && (
                <>
                  <div style={{ width: 90 }}><Num value={esc.base_risk} onChange={(v) => set("base_risk", Number(v) || 0)} min={0} step={50} /></div>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>$ por trade{esc.model === "fixed_ratio" ? " de base" : ""}</span>
                </>
              )}
              {esc.model === "fixed_ratio" && (
                <>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>Δ</span>
                  <div style={{ width: 90 }}><Num value={esc.delta} onChange={(v) => set("delta", Number(v) || 0)} min={0} step={100} /></div>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>$ de beneficio por escalón</span>
                </>
              )}
            </div>
          </Row>
          {esc.model === "kelly" && (
            <>
              <Row label="Cómo se calcula" help="De cada estrategia: su propia Kelly, y la suma se recorta al tope en proporción. Global: la Kelly del conjunto, topada y repartida por las Kellys propias.">
                <div style={{ width: 340 }}>
                  <Toggle value={esc.kelly_scope ?? "per_strategy"} onChange={(v) => set("kelly_scope", v)} options={[{ value: "per_strategy", label: "de cada estrategia" }, { value: "global", label: "global (capital total)" }]} />
                </div>
              </Row>
              <Row label="Fracción de Kelly" help="Cuánto de la Kelly óptima se aplica: 1 = la entera (óptima), 0,5 = media, 0,25 = un cuarto. Cualquier número vale; por encima de 1 es sobre-Kelly (más drawdown por menos crecimiento).">
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <div style={{ width: 80 }}><Num value={esc.kelly_mult} onChange={(v) => set("kelly_mult", Math.max(0.01, Number(v) || 0))} min={0.01} max={3} step={0.05} /></div>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>× Kelly ·</span>
                  <Btn onClick={() => set("kelly_mult", 0.25)}>¼</Btn>
                  <Btn onClick={() => set("kelly_mult", 0.5)}>½</Btn>
                  <Btn onClick={() => set("kelly_mult", 1)}>óptima</Btn>
                </div>
              </Row>
              <Row label="Sin muestra" help="Mientras la ventana no tiene 20 sesiones (al principio de la historia), Kelly no se puede estimar y se usa este % fijo.">
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <div style={{ width: 70 }}><Num value={esc.pct} onChange={(v) => set("pct", Number(v) || 0)} min={0} step={0.25} /></div>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% del capital del día</span>
                </div>
              </Row>
            </>
          )}
          <Row label="Tope de la suma" help="Lo máximo que se arriesga por trade sumando todas las estrategias, en % del capital del día. Si el modelo pide más, se queda aquí. 0 = sin tope (con estas curvas, que suponen liquidez infinita, Kelly pide cifras de locos: el tope es lo que hace realista el resultado).">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ width: 70 }}><Num value={esc.cap_pct} onChange={(v) => set("cap_pct", Number(v) || 0)} min={0} step={0.5} /></div>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% del capital del día {esc.cap_pct <= 0 ? "· sin tope" : ""}</span>
            </div>
          </Row>
          <Row label="Rebalanceo">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ width: 210 }}>
                <Toggle value={esc.rebalance} onChange={(v) => set("rebalance", v)} options={[{ value: "D", label: "diario" }, { value: "W", label: "semanal" }, { value: "M", label: "mensual" }]} />
              </div>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>ventana</span>
              <div style={{ width: 64 }}><Num value={esc.lookback_days} onChange={(v) => set("lookback_days", Math.max(1, Math.round(Number(v) || 0)))} min={1} step={30} /></div>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>días</span>
            </div>
          </Row>
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0 4px" }}>
            <Btn primary onClick={calcularEsc} disabled={escRunning}>{escRunning ? "Calculando…" : outEsc ? "Recalcular" : "Calcular escalado"}</Btn>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: escStale ? color.warning : color.textMuted }}>
              {escStale ? "ha cambiado algo desde el último cálculo" : "sobre las mismas estrategias, costes y periodo del paso 1"}
            </span>
          </div>
          {escError && <div style={{ marginTop: 8 }}><ErrorBox>{escError}</ErrorBox></div>}
        </Sec>

        <Sec title="Hoy — lo que habría que poner" help="Con toda la historia hasta la última fecha de las corridas: la Kelly de cada estrategia, lo que pide tras la fracción, y lo aplicado tras el tope. Todo es RIESGO por trade (lo que se pierde si salta el stop), no dinero metido. La cifra en $ es sobre el capital final de la simulación. Una estrategia sin trades en los últimos N días de la ventana no entra (no hay con qué estimarla): si su corrida termina antes que las demás, vuelve a correrla hasta hoy.">
          {!hoy ? (
            <Nota>Pulsa <strong>Calcular escalado</strong>.</Nota>
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
                {hoy.model === "kelly" && hoy.kelly_scope === "global" && <Stat label="Kelly global" value={hoy.kelly_raw_pct == null ? "—" : pct(hoy.kelly_raw_pct, 2)} sub={hoy.kelly_raw_pct == null ? (hoy.note || "sin muestra") : `× ${fraccionLabel(hoy.kelly_mult)} = ${pct(hoy.x_pct, 2)}${hoy.kelly_quad_pct != null ? ` · aprox. μ/σ² ${pct(hoy.kelly_quad_pct, 1)}` : ""}`} help="La fracción que maximiza el crecimiento (media de log(1 + f·R diaria)) sobre los días de la ventana con todas las estrategias juntas: la Kelly exacta del conjunto. La aproximación clásica μ/σ² se enseña al lado. Ojo: es la óptima DEL PASADO de la ventana; aplicada entera y sin tope al futuro, arruina (probado el 16-sep con estas corridas)." />}
                {hoy.model === "kelly" && hoy.kelly_scope !== "global" && <Stat label="Suma de las Kellys" value={pct(hoy.x_pct, 2)} sub={`cada una × ${fraccionLabel(hoy.kelly_mult)}, sumadas`} help="La suma de lo que pide cada estrategia (su Kelly exacta × la fracción). Si pasa del tope, se recortan todas en proporción." />}
                {hoy.model !== "kelly" && <Stat label="Modelo" value={pct(hoy.x_pct, 2)} sub={MODELO_LABEL[hoy.model]} />}
                <Stat label="Tope de la suma" value={hoy.cap_pct > 0 ? pct(hoy.cap_pct, 2) : "sin tope"} sub={hoy.capped ? `manda el tope: ${pct(hoy.x_pct, 2)} → ${pct(hoy.cap_pct, 2)}` : "no actúa"} tone={hoy.capped ? "warning" : undefined} />
                <Stat big label="Riesgo total por trade" value={pct(hoy.applied_pct, 2)} sub={`${usd(hoy.applied_usd)} sobre ${usdCorto(hoy.equity)} $ · si entran todas a la vez`} tone="profit" />
              </div>
              <Nota>
                {hoy.model === "kelly"
                  ? <>{hoy.kelly_scope === "global" ? `Kelly global ${pct(hoy.kelly_raw_pct, 2)} × ${fraccionLabel(hoy.kelly_mult)} = ${pct(hoy.x_pct, 2)}` : `Las Kellys de cada estrategia × ${fraccionLabel(hoy.kelly_mult)} suman ${pct(hoy.x_pct, 2)}`}; tope {hoy.cap_pct > 0 ? pct(hoy.cap_pct, 2) : "ninguno"} {hoy.capped ? "→ manda el tope, recorte proporcional" : "→ no actúa"}. <strong>Lo que pones en cada estrategia está en la columna «Aplicado»</strong>; la suma ({pct(hoy.applied_pct, 2)}) es lo que hay en juego si entran todas a la vez.</>
                  : <>{MODELO_LABEL[hoy.model]}: {pct(hoy.x_pct, 2)} en total; tope {hoy.cap_pct > 0 ? pct(hoy.cap_pct, 2) : "ninguno"} {hoy.capped ? "→ manda el tope" : "→ no actúa"}; repartido a partes iguales.</>}
              </Nota>
              {hoy.note && <Nota tone="warning">{hoy.note}</Nota>}
              {kellyLoco && (
                <Nota tone="warning">
                  Kellys de {pct(kellyMax, 0)} por trade no son una recomendación: salen de curvas que suponen liquidez infinita (miles de trades con PF &gt; 1 y tamaños que crecen sin límite). Aquí el tope no afina, es lo que hace realista el resultado.
                </Nota>
              )}
              <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 6 }}>
                <thead>
                  <tr>
                    <th style={thL}>Estrategia</th>
                    {hoy.model === "kelly" && <th style={thR}>Kelly propia</th>}
                    {hoy.model === "kelly" && <th style={thR}>× fracción</th>}
                    <th style={{ ...thR, color: color.copper }}>Aplicado</th>
                    <th style={thR}>$ por trade</th>
                    <th style={thR}>Peso</th>
                  </tr>
                </thead>
                <tbody>
                  {hoy.per_strategy.map((p) => (
                    <tr key={p.idx} style={{ opacity: p.alive ? 1 : 0.5 }}>
                      <td style={tdTxt}><span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><span style={{ width: 10, height: 10, background: colorSerie(p.idx), display: "inline-block" }} />{p.name}{!p.alive && <span style={{ fontSize: 9.5, color: color.textMuted }}>sin trades en la ventana</span>}{p.alive && p.kelly_pct === 0 && <span style={{ fontSize: 9.5, color: color.warning }}>sin edge en la ventana</span>}{p.alive && p.kelly_pct == null && hoy.model === "kelly" && <span style={{ fontSize: 9.5, color: color.textMuted }}>sin muestra: respaldo</span>}</span></td>
                      {hoy.model === "kelly" && <td style={tdNum} title={p.kelly_quad_pct != null ? `aprox. μ/σ² ${pct(p.kelly_quad_pct, 1)}` : ""}>{p.kelly_pct == null ? "—" : pct(p.kelly_pct, 2)}</td>}
                      {hoy.model === "kelly" && <td style={{ ...tdNum, color: color.textSecondary }}>{pct(p.asked_pct, 2)}</td>}
                      <td style={{ ...tdNum, color: color.textHigh, fontWeight: 600 }}>{pct(p.risk_pct, 2)}</td>
                      <td style={{ ...tdNum, color: color.textHigh }}>{usd(p.risk_usd)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }}>{pct(p.weight * 100, 0)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td style={{ ...tdTxt, borderTop: `1px solid ${color.border}`, color: color.copper, fontWeight: 600 }}>Suma</td>
                    {hoy.model === "kelly" && <td style={{ ...tdNum, borderTop: `1px solid ${color.border}` }} />}
                    {hoy.model === "kelly" && <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.textSecondary }}>{pct(hoy.x_pct, 2)}</td>}
                    <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.copper, fontWeight: 600 }}>{pct(hoy.applied_pct, 2)}</td>
                    <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.copper }}>{usd(hoy.applied_usd)}</td>
                    <td style={{ ...tdNum, borderTop: `1px solid ${color.border}` }}>100 %</td>
                  </tr>
                </tbody>
              </table>
              <p style={{ margin: "8px 0 0", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                Ventana {hoy.window.from} → {hoy.window.to}. «Peso» = parte de cada una en la suma aplicada. Si todas entran a la vez en la misma acción, el riesgo en esa acción es la suma: {pct(hoy.applied_pct, 2)}.
              </p>
            </>
          )}
        </Sec>
      </div>

      {outEsc && sc && comparacion && (
        <>
          <Sec
            title="Desde el inicio — si lo hubieras aplicado"
            help="La misma cuenta, los mismos trades, pero con el riesgo por trade que cada periodo dictaban el modelo y el reparto, estimados solo con lo anterior a ese periodo (el primero va con el respaldo y pesos iguales: no hay historia). Frente a la suma del paso 1 con los R de las filas, sin escalar. En % del capital, en $ de PnL acumulado, o en R acumulada (suma de la R de cada trade: neto / lo arriesgado)."
            right={<div style={{ width: 130 }}><Toggle value={unidad} onChange={setUnidad} options={[{ value: "pct", label: "%" }, { value: "usd", label: "$" }, { value: "r", label: "R" }]} /></div>}
            sinRelleno
          >
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", alignItems: "start" }}>
              <LinesChart labels={out.calendar} series={comparacion.series} yFormat={fmtY} hoverFormat={fmtHover} height={300} titulo={unidad === "usd" ? "PNL ACUMULADO" : unidad === "r" ? "R ACUMULADA" : "RETORNO SOBRE EL CAPITAL"} />
              <div style={{ borderLeft: `1px solid ${color.border}`, alignSelf: "stretch" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={thL}>Medida</th>
                      <th style={thR}>R de las filas</th>
                      <th style={{ ...thR, color: color.copper }}>Escalado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {([
                      ["Retorno neto", pct(out.metrics.total_return_pct), pct(outEsc.metrics.total_return_pct)],
                      ["CAGR", pct(out.metrics.cagr_pct), pct(outEsc.metrics.cagr_pct)],
                      ["Max DD", pct(comparacion.ddA), pct(comparacion.ddB)],
                      ["Sharpe", n(out.metrics.sharpe), n(outEsc.metrics.sharpe)],
                      ["Calmar", n(out.metrics.calmar), n(outEsc.metrics.calmar)],
                      ["Trades", n(out.metrics.n_trades, 0), n(outEsc.metrics.n_trades, 0)],
                      ["PF", n(out.metrics.profit_factor), n(outEsc.metrics.profit_factor)],
                      ["R acumulada", `${n(comparacion.rA, 0)} R`, `${n(comparacion.rB, 0)} R`],
                      ["Comis. + slippage", usd(out.costs.fees + (out.costs.slippage || 0)), usd(outEsc.costs.fees + (outEsc.costs.slippage || 0))],
                      ["Locates", usd(out.costs.locates), usd(outEsc.costs.locates)],
                      ["Balance final", usd(out.equity[out.equity.length - 1]), usd(outEsc.equity[outEsc.equity.length - 1])],
                    ] as Array<[string, string, string]>).map(([k, a, b]) => (
                      <tr key={k}>
                        <td style={tdTxt}>{k}</td>
                        <td style={{ ...tdNum, color: color.textSecondary }}>{a}</td>
                        <td style={{ ...tdNum, color: color.textHigh }}>{b}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p style={{ margin: 0, padding: "8px 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                  «R de las filas»: cada estrategia con el R que tiene en su fila del paso 1, sin escalar ni repartir. La R acumulada no depende del tamaño: si es distinta es porque cambian los trades que entran (tope, puerta, sin stop, peso 0).
                </p>
                {(sc.no_stop > 0 || sc.no_weight > 0 || outEsc.ruined || periodosUnaViva > 0) && (
                  <p style={{ margin: 0, padding: "0 10px 8px", fontSize: 10.5, fontFamily: font.sans, color: color.warning, lineHeight: 1.5 }}>
                    {sc.no_stop > 0 && <>{n(sc.no_stop, 0)} trades sin stop guardado se han quedado fuera (no se pueden dimensionar por riesgo). </>}
                    {sc.no_weight > 0 && <>{n(sc.no_weight, 0)} trades con peso 0 en su periodo (estrategia sin trades en la ventana, o Kelly a 0 por falta de edge). </>}
                    {periodosUnaViva > 0 && <>En {n(periodosUnaViva, 0)} de {n(sc.periods.length, 0)} periodos solo una estrategia tenía trades en la ventana. </>}
                    {outEsc.ruined && <>La cuenta llegó a cero. </>}
                  </p>
                )}
              </div>
            </div>
          </Sec>

          <Sec title={`Reparto periodo a periodo — ${sc.periods.length} ${esc.rebalance === "D" ? "días" : esc.rebalance === "W" ? "semanas" : "meses"}`} help="Cada barra es un periodo de rebalanceo: cómo se repartió el riesgo entre las estrategias (apilado al 100 %: la parte de cada una en la suma aplicada, es decir, quién llevaba más ese periodo). La línea de cobre es la suma del riesgo por trade que se APLICÓ, en % del capital del día, ya con el tope; un punto ámbar es un periodo en que las Kellys pedían más y el tope las recortó (al pasar el ratón se ve lo que pedían y el riesgo de cada una)." sinRelleno>
            <WeightsChart periods={sc.periods} names={names} colors={colores} height={200} />
          </Sec>
        </>
      )}
    </div>
  );
}
