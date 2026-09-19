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
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Btn, Nota, Num, Row, Sec, Stat, SubTabs, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";
import { LinesChart, WeightsChart } from "./CrudoCharts";
import { MODELO_LABEL, curvaPropia, type EscCfg } from "./modelo";
import { CalendarioCrudo } from "./CalendarioCrudo";
import { McResultado } from "./McResultado";

export interface EscaladoModel {
  out: RawOut;
  outEsc: RawOut | null;
  esc: EscCfg;
  setEsc: React.Dispatch<React.SetStateAction<EscCfg>>;
  escRunning: boolean;
  escError: string | null;
  escStale: boolean;
  calcularEsc: () => void;
  /** Monte Carlo sobre la curva escalada (17-sep). */
  mcEsc: MonteCarloOut | null;
  mcEscRunning: boolean;
  mcEscError: string | null;
  simularMcEsc: () => void;
  mcSims: number | "";
}

const sel: React.CSSProperties = { ...control, fontFamily: font.sans, cursor: "pointer" };

/** R acumulada por dia del calendario: suma de la R de cada trade de ese dia. */
function rAcumulada(o: RawOut): number[] {
  const porDia = new Map<string, number>();
  for (let k = 0; k < o.trades.date.length; k++) porDia.set(o.trades.date[k], (porDia.get(o.trades.date[k]) || 0) + (o.trades.r[k] || 0));
  let acc = 0;
  return o.calendar.map((d) => { acc += porDia.get(d) || 0; return acc; });
}

/** Primer dia del periodo de rebalanceo que viene despues de `ultimo`. */
function siguientePeriodo(ultimo: string, rebalance: "D" | "W" | "M"): string {
  const d = new Date(`${ultimo}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "el siguiente";
  if (rebalance === "M") { d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + 1); }
  else if (rebalance === "W") { const dow = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() + (7 - dow)); }
  else d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function fraccionLabel(m: number) {
  return m === 1 ? "entera (óptima)" : m === 0.5 ? "½" : m === 0.25 ? "¼" : `× ${n(m, 2)}`;
}

export function PasoEscalado({ m }: { m: EscaladoModel }) {
  const { out, outEsc, esc, setEsc, escRunning, escError, escStale, calcularEsc, mcEsc, mcEscRunning, mcEscError, simularMcEsc, mcSims } = m;
  const set = <K extends keyof EscCfg>(k: K, v: EscCfg[K]) => setEsc((c) => ({ ...c, [k]: v }));
  const sc = outEsc?.scaling ?? null;
  const hoy = sc?.today ?? null;
  const cap = out.config.capital;
  const [unidad, setUnidad] = useState<"pct" | "usd" | "r">("pct");
  // Capital con el que se leen los $ del siguiente periodo: el del portfolio
  // por defecto, no el final de la simulacion (que con estas curvas es una
  // cifra de fantasia).
  const [capitalSig, setCapitalSig] = useState<number>(cap);
  const [vistaEsc, setVistaEsc] = useState<"curva" | "calendario" | "montecarlo">("curva");

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

  // En R el escalado no puede ganar MAS que las filas: la R de un trade no
  // depende del tamano; solo puede perder los trades que no pudo dimensionar.
  const perdidosEsc = sc ? (sc.no_weight || 0) + (sc.no_stop || 0) : 0;
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
            <strong>Unidad</strong>: cada estrategia va en la suya, la misma que en su backtest: por RIESGO (lo que se
            pierde al stop) si dimensionó por stop; por POSICIÓN (% del capital metido) si dimensionó por capital. Así
            «1 %» en Kelly es lo mismo que «1 %» en su fila del paso 1, y no seis veces más.
            <strong>Fracción</strong>: lo que se aplica de la Kelly (1 = entera; ½ y ¼ las de la práctica; cualquier
            número). <strong>Tope por estrategia</strong>: lo máximo por trade de cada una (primero). <strong>Tope de la
            suma</strong>: lo máximo por trade sumando todas (después, recorte proporcional); con estas curvas (liquidez
            infinita) los topes son lo único que hace realista el resultado: Kelly pone el orden, los topes el nivel. <strong>Rebalanceo</strong>: cada
            cuánto se re-estima todo, siempre con datos anteriores a ese día. <strong>Ventana</strong>: cuántos días
            naturales de historia se miran; una estrategia sin trades en ella no entra ese periodo.
            <br /><br />
            <strong>Por trade o por acción</strong>: la fracción de Kelly es POR TRADE. Si dos estrategias entran en
            la misma acción a la vez, esa acción lleva la suma de las dos. Para que el límite sea POR ACCIÓN, en el
            paso 1 está «Tope por acción»: X % en riesgo, o «un trade» (en una acción nunca más de lo que arriesga un
            trade de Kelly); y «Lo que no cabe» decide si la segunda se salta o entra recortada. Se aplica también
            aquí, al simular el escalado.
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
          <Row label="Tope por estrategia" help="Lo máximo que puede arriesgar POR TRADE una estrategia, en % del capital del día. Se aplica ANTES que el tope de la suma y no reparte lo recortado. Sin él, en cuanto una estrategia tiene muestra y las demás van con el respaldo, el recorte proporcional de la suma le daba a esa casi todo el tope (con tus tres, feb-2024: 9,0 / 0,5 / 0,5 % con tope 10) y la curva se disparaba desde el segundo mes. Con él, Kelly decide el orden y las proporciones y los topes deciden el nivel: es lo que convierte esto en una guía. 0 = sin tope.">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ width: 70 }}><Num value={esc.cap_strategy_pct ?? 0} onChange={(v) => set("cap_strategy_pct", Number(v) || 0)} min={0} step={0.25} /></div>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% del capital del día por trade y estrategia {(esc.cap_strategy_pct ?? 0) <= 0 ? "· sin tope" : ""}</span>
            </div>
          </Row>
          <Row label="Tope de la suma" help="Lo máximo que se arriesga POR TRADE sumando todas las estrategias, en % del capital del día. Si el modelo pide más, se queda aquí (recorte proporcional, después del tope por estrategia). 0 = sin tope (con estas curvas, que suponen liquidez infinita, Kelly pide cifras de locos: los topes son lo que hace realista el resultado). Es por trade: dos estrategias en la misma acción a la vez suman; para eso está «Tope por acción» en el paso 1.">
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

        <Sec title={`Siguiente periodo — lo que hay que poner${hoy ? ` (desde ${siguientePeriodo(hoy.date, esc.rebalance)})` : ""}`} help="La recomendación para el periodo que viene: con la ventana que acaba en la última fecha de las corridas (los últimos N días), la Kelly de cada estrategia, lo que pide tras la fracción, y lo aplicado tras el tope. Todo es RIESGO por trade (lo que se pierde si salta el stop), no dinero metido. La cifra en $ es sobre el capital que pongas en la casilla (por defecto, el del portfolio), no sobre el final de la simulación. Da lo mismo cuánta historia haya antes de la ventana: la estimación solo mira la ventana. Una estrategia sin trades en la ventana no entra (no hay con qué estimarla): si su corrida termina antes que las demás, vuelve a correrla hasta hoy.">
          {!hoy ? (
            <Nota>Pulsa <strong>Calcular escalado</strong>.</Nota>
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
                {hoy.model === "kelly" && hoy.kelly_scope === "global" && <Stat label="Kelly global" value={hoy.kelly_raw_pct == null ? "—" : pct(hoy.kelly_raw_pct, 2)} sub={hoy.kelly_raw_pct == null ? (hoy.note || "sin muestra") : `× ${fraccionLabel(hoy.kelly_mult)} = ${pct(hoy.x_pct, 2)}${hoy.kelly_quad_pct != null ? ` · aprox. μ/σ² ${pct(hoy.kelly_quad_pct, 1)}` : ""}`} help="La fracción que maximiza el crecimiento (media de log(1 + f·R diaria)) sobre los días de la ventana con todas las estrategias juntas: la Kelly exacta del conjunto. La aproximación clásica μ/σ² se enseña al lado. Ojo: es la óptima DEL PASADO de la ventana; aplicada entera y sin tope al futuro, arruina (probado el 16-sep con estas corridas)." />}
                {hoy.model === "kelly" && hoy.kelly_scope !== "global" && <Stat label="Suma de las Kellys" value={pct(hoy.x_pct, 2)} sub={`cada una × ${fraccionLabel(hoy.kelly_mult)}, sumadas`} help="La suma de lo que pide cada estrategia (su Kelly exacta × la fracción). Si pasa del tope, se recortan todas en proporción." />}
                {hoy.model !== "kelly" && <Stat label="Modelo" value={pct(hoy.x_pct, 2)} sub={MODELO_LABEL[hoy.model]} />}
                <Stat label="Tope por estrategia" value={(hoy.cap_strategy_pct ?? 0) > 0 ? pct(hoy.cap_strategy_pct ?? 0, 2) : "sin tope"} sub={hoy.capped_strategy ? "recorta a alguna" : "no actúa"} tone={hoy.capped_strategy ? "warning" : undefined} />
                <Stat label="Tope de la suma" value={hoy.cap_pct > 0 ? pct(hoy.cap_pct, 2) : "sin tope"} sub={hoy.capped ? `manda el tope: ${pct(hoy.x_pct, 2)} → ${pct(hoy.cap_pct, 2)}` : "no actúa"} tone={hoy.capped ? "warning" : undefined} />
                <Stat big label="Riesgo total por trade" value={pct(hoy.applied_pct, 2)} sub={`${usd(capitalSig * hoy.applied_pct / 100)} sobre ${usdCorto(capitalSig)} $ · si entran todas a la vez`} tone="profit" />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0 6px" }}>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>Capital de la cuenta para el siguiente periodo</span>
                <div style={{ width: 110 }}><Num value={capitalSig} onChange={(v) => setCapitalSig(Number(v) || 0)} min={0} step={1000} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>$ · los $ por trade de la tabla salen de aquí</span>
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
                      <td style={{ ...tdNum, color: color.textHigh, fontWeight: 600 }} title={p.basis === "capital" ? "en POSICIÓN: % del capital del día metido en la operación (la corrida dimensiona por capital, sin stop)" : "en RIESGO: % del capital del día que se pierde si salta el stop"}>{pct(p.risk_pct, 2)}<span style={{ fontSize: 9.5, color: color.textMuted, fontWeight: 400, marginLeft: 4 }}>{p.basis === "capital" ? "posición" : "riesgo"}</span></td>
                      <td style={{ ...tdNum, color: color.textHigh }}>{usd(capitalSig * p.risk_pct / 100)}</td>
                      <td style={{ ...tdNum, color: color.textMuted }}>{pct(p.weight * 100, 0)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td style={{ ...tdTxt, borderTop: `1px solid ${color.border}`, color: color.copper, fontWeight: 600 }}>Suma</td>
                    {hoy.model === "kelly" && <td style={{ ...tdNum, borderTop: `1px solid ${color.border}` }} />}
                    {hoy.model === "kelly" && <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.textSecondary }}>{pct(hoy.x_pct, 2)}</td>}
                    <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.copper, fontWeight: 600 }}>{pct(hoy.applied_pct, 2)}</td>
                    <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.copper }}>{usd(capitalSig * hoy.applied_pct / 100)}</td>
                    <td style={{ ...tdNum, borderTop: `1px solid ${color.border}` }}>100 %</td>
                  </tr>
                </tbody>
              </table>
              <p style={{ margin: "8px 0 0", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                Ventana {hoy.window.from} → {hoy.window.to} ({esc.lookback_days} días: solo cuenta esto, la historia anterior no cambia la recomendación). <strong>Unidad</strong>: «riesgo» = % del capital que se pierde si salta el stop (corridas dimensionadas por stop); «posición» = % del capital metido en la operación (corridas dimensionadas por capital, como en su backtest): con stops al 15 %, un 1 % de riesgo son posiciones 6 veces mayores que un 1 % en posición. «Peso» = parte de cada una en la suma aplicada. Si todas entran a la vez en la misma acción, el riesgo en esa acción es la suma: {pct(hoy.applied_pct, 2)} (o lo que diga el «Tope por acción» del paso 1).
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
            right={vistaEsc === "curva" ? <div style={{ width: 130 }}><Toggle value={unidad} onChange={setUnidad} options={[{ value: "pct", label: "%" }, { value: "usd", label: "$" }, { value: "r", label: "R" }]} /></div> : undefined}
            sinRelleno
          >
            <div style={{ padding: "6px 10px 0" }}>
              <SubTabs value={vistaEsc} onChange={setVistaEsc} options={[{ value: "curva", label: "Curva" }, { value: "calendario", label: "Calendario" }, { value: "montecarlo", label: "Monte Carlo" }]} />
            </div>
            {vistaEsc === "calendario" && (
              <div style={{ padding: "4px 10px 10px" }}>
                <Nota>El mismo calendario del paso 2, sobre la simulación escalada: Profits (bruto), Gastos (comisiones + slippage + locates + fijos) y Profits − Gastos, en $ o en R. Pulsa un día para ver sus trades por estrategia.</Nota>
                <CalendarioCrudo out={outEsc} names={names} />
              </div>
            )}
            {vistaEsc === "montecarlo" && (
              <div style={{ padding: "4px 10px 10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "4px 0 8px" }}>
                  <Btn primary onClick={simularMcEsc} disabled={mcEscRunning}>{mcEscRunning ? "Simulando…" : mcEsc ? "Volver a simular" : "Simular"}</Btn>
                  <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{n(Number(mcSims) || 5000, 0)} recorridos (los del paso 3) sobre los retornos diarios de la curva escalada, compuestos. A qué drawdown te expones con este escalado.</span>
                </div>
                {mcEscError && <ErrorBox>{mcEscError}</ErrorBox>}
                {mcEsc && <McResultado mcOut={mcEsc} titulo="Recorridos y distribuciones del escalado" />}
              </div>
            )}
            {vistaEsc === "curva" && (
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
                  «R de las filas»: cada estrategia con el R que tiene en su fila del paso 1, sin escalar ni repartir. <strong>En R el escalado nunca puede ganar más que las filas</strong>: la R de un trade (neto ÷ lo arriesgado) no depende del tamaño, así que escalar multiplica los $ pero deja la R igual; solo puede PERDER R por los trades que no pudo dimensionar ({n(perdidosEsc, 0)} aquí: peso 0 en su periodo o sin stop) y por los que dejan fuera los topes. Si ves menos R con más $, es eso, no un error.
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
            )}
          </Sec>

          <Sec title={`Riesgo por trade, periodo a periodo — ${sc.periods.length} ${esc.rebalance === "D" ? "días" : esc.rebalance === "W" ? "semanas" : "meses"}`} help="Cada barra es un periodo de rebalanceo. La altura de cada tramo es el riesgo por trade que se APLICÓ a esa estrategia ese periodo, en % REAL del capital del día (ya con la fracción de Kelly y el tope); la barra entera es la suma, lo que hay en juego si entran todas a la vez. La raya de cobre es el tope de la suma; un triángulo ámbar marca un periodo en que el modelo pedía más y mandó el tope. Al pasar el ratón: el % por trade de cada estrategia, su Kelly propia de ese periodo y lo que pedía la suma." sinRelleno>
            <WeightsChart periods={sc.periods} names={names} colors={colores} capPct={esc.cap_pct} height={240} />
          </Sec>
        </>
      )}
    </div>
  );
}
