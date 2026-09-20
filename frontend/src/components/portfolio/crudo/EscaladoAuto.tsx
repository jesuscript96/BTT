"use client";

// Paso 4 · B «Escalado automático» (20-sep-2026, tarde). Jaume: «ponerlo en la
// zona de escalado, que vaya ajustando por semana, por mes o por X días, ver
// cómo habría quedado el portfolio y que me dé la distribución de pesos para
// el próximo periodo; el freno como opción; límites mínimos por estrategia; y
// todo con ? explicativos».
//
// Dos reglas, medidas antes de construirlas (MEMORIA 20-sep):
//  - Rotación por ranking: cada periodo, la que mejor rindió por unidad de
//    tamaño en la ventana se lleva el primer % del patrón, la siguiente el
//    segundo... con un suelo por estrategia. Solo mira el pasado.
//  - Freno por caída: si la cuenta cae más de X % desde su máximo, todos los
//    tamaños × m hasta recuperar. Limita la profundidad, no predice.

import React, { useMemo } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawBrakeIn, RawOut, RawRotationIn } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Row, Sec, Stat, Toggle, colorSerie, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { LinesChart, type Serie } from "./CrudoCharts";
import { retornoPorAno } from "./PasoNivel";

export interface EscaladoAutoModel {
  out: RawOut;
  nombres: string[];
  /** % del paso 1 de cada estrategia marcada (mismo orden que `nombres`). */
  pctBase: number[];
  rot: RawRotationIn;
  setRot: React.Dispatch<React.SetStateAction<RawRotationIn>>;
  brake: RawBrakeIn;
  setBrake: React.Dispatch<React.SetStateAction<RawBrakeIn>>;
  outAuto: RawOut | null;
  running: boolean;
  error: string | null;
  stale: boolean;
  calcular: () => void;
}

const numChico: React.CSSProperties = { height: 24, fontSize: 11, padding: "2px 5px", textAlign: "right" };
const lbl: React.CSSProperties = { fontSize: 10.5, fontFamily: font.sans, color: color.textMuted };

function maxDd(equity: number[], capital: number): number {
  let peak = capital; let dd = 0;
  for (const e of equity) { peak = Math.max(peak, e); dd = Math.min(dd, peak > 0 ? (e / peak - 1) * 100 : 0); }
  return dd;
}

/** El patrón que se manda: el guardado si tiene la longitud de las marcadas; si no, los % del paso 1 ordenados de mayor a menor. */
export function patronEfectivo(rot: RawRotationIn, pctBase: number[]): number[] {
  if (rot.pattern && rot.pattern.length === pctBase.length) return rot.pattern;
  return [...pctBase].sort((a, b) => b - a);
}

export function EscaladoAuto({ m }: { m: EscaladoAutoModel }) {
  const { out, nombres, pctBase, rot, setRot, brake, setBrake, outAuto, running, error, stale, calcular } = m;
  const cap0 = out.config.capital;
  const setR = <K extends keyof RawRotationIn>(k: K, v: RawRotationIn[K]) => setRot((r) => ({ ...r, [k]: v }));
  const setB = <K extends keyof RawBrakeIn>(k: K, v: RawBrakeIn[K]) => setBrake((b) => ({ ...b, [k]: v }));
  const patron = patronEfectivo(rot, pctBase);
  const sumaPatron = patron.reduce((a, b) => a + b, 0);
  const setPatron = (k: number, v: number) => {
    const p = [...patron]; p[k] = Math.max(0, v);
    setRot((r) => ({ ...r, pattern: p }));
  };
  const rotOut = outAuto?.rotation ?? null;
  const brakeOut = outAuto?.brake ?? null;

  const comparacion = useMemo(() => {
    if (!outAuto) return null;
    const series: Serie[] = [
      { name: "Los % del paso 1 (fijo)", color: color.textSecondary, width: 1.4, values: out.equity.map((e) => (e / cap0 - 1) * 100) },
      { name: "Escalado automático", color: color.copper, width: 2.2, values: outAuto.equity.map((e) => (e / cap0 - 1) * 100) },
    ];
    const anosBase = retornoPorAno(out.calendar, out.equity, cap0);
    const anosAuto = retornoPorAno(outAuto.calendar, outAuto.equity, cap0);
    return { series, anosBase, anosAuto };
  }, [out, outAuto, cap0]);

  return (
    <Sec
      title="B · Escalado automático: rotación por ranking y freno por caída"
      help={
        <>
          Lo que haría una cuenta que <strong>revisa los pesos sola</strong> cada cierto tiempo, mirando solo lo que ya ha pasado.
          Se corre desde el principio con el motor entero (locates, margen, costes) y se compara con dejar tus % fijos.
          Al final te dice <strong>qué % poner a cada estrategia el siguiente periodo</strong> y si el freno está puesto.
          <br /><br />
          <strong>Rotación por ranking.</strong> Cada periodo (semana, mes o cada N sesiones) se ordenan las estrategias por lo
          que han rendido <em>por cada 1 % de tamaño</em> en la ventana anterior (así se comparan aunque una vaya por stop y otra por
          capital), y se les da el % por trade del <em>patrón</em> según su puesto: el primero del patrón a la mejor, el segundo a la
          siguiente… Con un <em>suelo</em>: ninguna baja de X % (lo que falte se quita de las de arriba en proporción, así la suma
          no cambia). Funciona porque la <strong>calidad de una estrategia persiste</strong> (en tus PM, 2A fue «la peor» el 75 % de
          los días): la rotación va llegando sola al reparto bueno sin que tengas que saberlo de antemano. El primer periodo, sin
          historia, va con tus % del paso 1.
          <br /><br />
          <strong>Freno por caída.</strong> Si al abrir el día la cuenta está más de X % por debajo de su máximo, todos los tamaños
          se multiplican por m (0,5 = la mitad) hasta que la caída vuelve por encima de Y %. No predice nada: <em>limita la
          profundidad</em> de una caída que ya ha empezado, a cambio de recuperar más despacio. No evita un precipicio de un solo
          día (se decide con el cierre anterior). Medido en tus PM: la misma caída que bajar el nivel para siempre, con el doble de
          crecimiento.
        </>
      }
      right={<Btn primary onClick={calcular} disabled={running}>{running ? "Calculando…" : outAuto ? "Volver a calcular" : "Calcular escalado"}</Btn>}
    >
      {/* ── Rotación ─────────────────────────────────────────────────── */}
      <Row label="Rotación" help="Encendida: los % por trade de cada estrategia cambian cada periodo según el ranking. Apagada: se quedan los % del paso 1 (útil para probar solo el freno).">
        <div style={{ width: 190 }}><Toggle value={rot.enabled ? "si" : "no"} onChange={(v) => setR("enabled", v === "si")} options={[{ value: "si", label: "encendida" }, { value: "no", label: "apagada" }]} /></div>
      </Row>
      {rot.enabled && (
        <>
          <Row label="Cada cuánto" help="Cuándo se vuelve a mirar el ranking y se cambian los pesos: cada semana (el primer día operado de la semana), cada mes (el primer día operado del mes) o cada N sesiones. Entre revisiones, los pesos no se tocan. Más a menudo no es mejor: el ranking cambia poco (en tus PM, 7 veces en 33 meses) y cada cambio es un salto de tamaño.">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ width: 300 }}><Toggle value={rot.rebalance} onChange={(v) => setR("rebalance", v)} options={[{ value: "W", label: "cada semana" }, { value: "M", label: "cada mes" }, { value: "N", label: "cada N sesiones" }]} /></div>
              {rot.rebalance === "N" && (
                <>
                  <span style={lbl}>N =</span>
                  <div style={{ width: 64 }}><Num value={rot.every_days} onChange={(v) => setR("every_days", Math.max(1, Math.round(Number(v) || 1)))} min={1} step={5} style={numChico} /></div>
                </>
              )}
            </div>
          </Row>
          <Row label="Ventana" help="Cuántas sesiones hacia atrás se miran para hacer el ranking. Corta (20-60) reacciona rápido pero es ruidosa: un mes bueno de una estrategia mala la sube al primer puesto. Larga (126-252 sesiones = 6-12 meses) mide la calidad de verdad y cambia poco. Medido en tus PM: 126 dio +29 % sobre fijo con la misma caída; 63 y 252, algo menos. Hasta que no hay tantas sesiones de historia, se usan los % del paso 1.">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ width: 70 }}><Num value={rot.lookback_days} onChange={(v) => setR("lookback_days", Math.max(5, Math.round(Number(v) || 5)))} min={5} step={21} style={numChico} /></div>
              <span style={lbl}>sesiones (126 ≈ 6 meses, 252 ≈ 1 año)</span>
            </div>
          </Row>
          <Row label="Por qué se ordena" help="«Retorno»: lo que aportó cada estrategia al portfolio por cada 1 % de tamaño, sumado en la ventana (la que más ganó por unidad, primera). «Sharpe»: ese mismo retorno dividido por lo que oscila día a día (premia a la regular frente a la que gana a golpes). Con tus PM el retorno fue mejor; el Sharpe hace lo mismo que Markowitz: sube a la de poca volatilidad aunque gane menos.">
            <div style={{ width: 230 }}><Toggle value={rot.metric} onChange={(v) => setR("metric", v)} options={[{ value: "return", label: "retorno por unidad" }, { value: "sharpe", label: "Sharpe" }]} /></div>
          </Row>
          <Row label="Patrón de pesos" help="El % por trade que se lleva cada PUESTO del ranking: el primer número va a la mejor estrategia del periodo, el segundo a la siguiente… Por defecto son tus % del paso 1 ordenados de mayor a menor (con 4/2/1 en el paso 1: la mejor 4, la del medio 2, la peor 1), así la suma es la misma que sin rotación y la comparación es justa. Un patrón más desigual (5/2/0) gana más y cae más; uno más plano (3/2/2) al revés.">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {patron.map((v, k) => (
                <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <span style={lbl}>{k + 1}.º</span>
                  <div style={{ width: 62 }}><Num value={v} onChange={(x) => setPatron(k, Number(x) || 0)} min={0} step={0.5} style={numChico} /></div>
                </span>
              ))}
              <span style={lbl}>= {n(sumaPatron, 2)} % por trade en total</span>
              <Btn onClick={() => setRot((r) => ({ ...r, pattern: null }))}>los del paso 1</Btn>
            </div>
          </Row>
          <Row label="Suelo por estrategia" help="Ninguna estrategia baja de este % por trade, aunque el patrón le dé menos (o 0). Lo que le falte para llegar al suelo se quita de las que están por encima, en proporción, para que la suma del patrón no cambie. Sirve para no apagar del todo a la que va peor: sigue operando en pequeño y, si vuelve a rendir, el ranking la sube (el ranking se calcula con lo que rinde por unidad, no con lo que llevaba). Con 0, una estrategia con 0 en el patrón queda apagada hasta que el ranking la suba.">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={lbl}>nunca menos de</span>
              <div style={{ width: 64 }}><Num value={rot.min_pct} onChange={(v) => setR("min_pct", Math.max(0, Number(v) || 0))} min={0} step={0.25} style={numChico} /></div>
              <span style={lbl}>% por trade</span>
            </div>
          </Row>
        </>
      )}

      {/* ── Freno ────────────────────────────────────────────────────── */}
      <div style={{ borderTop: `1px solid ${color.border}`, marginTop: 6, paddingTop: 6 }}>
        <Row label="Freno por caída" help="Sin freno: los tamaños solo cambian con el capital (compound). Con freno: cuando la cuenta cae más de X % desde su máximo, todos los tamaños × m hasta que la caída vuelve por encima de Y %. Se decide cada mañana con el cierre del día anterior.">
          <div style={{ width: 190 }}><Toggle value={brake.enabled ? "si" : "no"} onChange={(v) => setB("enabled", v === "si")} options={[{ value: "si", label: "con freno" }, { value: "no", label: "sin freno" }]} /></div>
        </Row>
        {brake.enabled && (
          <Row label="Regla" help="«Frena a partir de −X %»: la caída desde el máximo de la cuenta que dispara el freno (10 % en tus PM: 40 días frenado en 668). «Multiplicador»: por cuánto se multiplican todos los tamaños mientras dura (0,5 = la mitad; 0 = no operar). «Suelta al volver a −Y %»: la caída (menor que X) a la que se quita el freno; si Y es 0 hay que volver al máximo, y eso puede tardar meses a mitad de tamaño. Regla de bolsillo: la caída máxima queda en X + (lo que sobrepase) × m.">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span style={lbl}>frena a partir de −</span>
              <div style={{ width: 60 }}><Num value={brake.dd_pct} onChange={(v) => setB("dd_pct", Math.max(0.1, Number(v) || 0.1))} min={0.1} step={1} style={numChico} /></div>
              <span style={lbl}>% · multiplicador ×</span>
              <div style={{ width: 60 }}><Num value={brake.mult} onChange={(v) => setB("mult", Math.min(1, Math.max(0, Number(v) || 0)))} min={0} max={1} step={0.1} style={numChico} /></div>
              <span style={lbl}>· suelta al volver a −</span>
              <div style={{ width: 60 }}><Num value={brake.exit_dd_pct} onChange={(v) => setB("exit_dd_pct", Math.max(0, Number(v) || 0))} min={0} step={1} style={numChico} /></div>
              <span style={lbl}>%</span>
            </div>
          </Row>
        )}
      </div>

      {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
      {stale && outAuto && <Nota tone="warning">Los ajustes han cambiado desde el último cálculo.</Nota>}
      {!outAuto && !error && <Nota>Pulsa <strong>Calcular escalado</strong>: el portfolio desde el principio con estas reglas, frente a tus % fijos, y lo que toca el siguiente periodo.</Nota>}

      {outAuto && comparacion && (
        <>
          {/* ── Siguiente periodo ───────────────────────────────────── */}
          <div style={{ marginTop: 10, border: `1px solid ${color.copper}`, background: "rgba(184, 115, 51, 0.06)", padding: "8px 12px" }}>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.copper, fontFamily: font.sans, marginBottom: 4 }}>
              Siguiente periodo — lo que toca poner{rotOut?.hoy.desde ? ` (con todo hasta ${rotOut.hoy.desde})` : ""}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {rotOut ? (
                <>
                  {nombres.map((nm, i) => (
                    <Stat key={nm} label={nm.length > 22 ? `${nm.slice(0, 21)}…` : nm} value={pct(rotOut.hoy.sizes[i], 2)} sub={rotOut.hoy.ranks ? `${rotOut.hoy.ranks[i]}.º del ranking · ${pct((rotOut.hoy.weights[i] ?? 0) * 100, 0)} del total` : "sin historia: % del paso 1"} big />
                  ))}
                  <Stat label="Total por trade" value={pct(rotOut.hoy.total_pct, 2)} sub="sumando todas" />
                </>
              ) : (
                nombres.map((nm, i) => <Stat key={nm} label={nm.length > 22 ? `${nm.slice(0, 21)}…` : nm} value={pct(pctBase[i], 2)} sub="rotación apagada: % del paso 1" big />)
              )}
              {brakeOut && (
                <Stat label="Freno" value={brakeOut.hoy.frenado ? `puesto ×${n(brakeOut.hoy.mult, 2)}` : "quitado"} sub={`la cuenta simulada está a ${pct(brakeOut.hoy.dd_pct)} de su máximo`} tone={brakeOut.hoy.frenado ? "warning" : undefined} />
              )}
            </div>
            {rotOut?.hoy.nota && <div style={{ ...lbl, marginTop: 4 }}>{rotOut.hoy.nota}</div>}
            <div style={{ ...lbl, marginTop: 4 }}>
              Esto es lo que dice la simulación con tus corridas. En el paso 5, con tu CSV real, el total lo pone tu cuenta y este reparto se aplica sobre ese total.
            </div>
          </div>

          {/* ── Cómo habría quedado ─────────────────────────────────── */}
          <div style={{ display: "flex", flexWrap: "wrap", marginTop: 10 }}>
            <Stat label="Fijo (tus % del paso 1)" value={usd(out.equity[out.equity.length - 1])} sub={`DD ${pct(maxDd(out.equity, cap0))} · ${n(out.cap_report.taken, 0)} trades`} />
            <Stat label="Escalado automático" value={usd(outAuto.equity[outAuto.equity.length - 1])} sub={`DD ${pct(maxDd(outAuto.equity, cap0))} · ${n(outAuto.cap_report.taken, 0)} trades`} tone={outAuto.equity[outAuto.equity.length - 1] >= out.equity[out.equity.length - 1] ? "profit" : "loss"} />
            {rotOut && <Stat label="Rotación" value={`${n(rotOut.rebalanceos, 0)} revisiones`} sub={`${n(rotOut.cambios_de_ranking, 0)} cambios de ranking · tamaño medio ${rotOut.size_medio.map((x) => n(x, 2)).join(" / ")} %`} />}
            {brakeOut && <Stat label="Freno" value={`${n(brakeOut.dias_frenado, 0)} días frenado`} sub={`${n(brakeOut.episodios, 0)} episodios`} />}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 320px", gap: 12, alignItems: "start", marginTop: 8 }}>
            <LinesChart labels={out.calendar} series={comparacion.series} yFormat={(v) => `${n(v, 0)} %`} hoverFormat={(v) => `${n(v, 1)} %`} height={260} titulo="RETORNO SOBRE EL CAPITAL" />
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thL}>Año</th>
                  <th style={thR}>Fijo</th>
                  <th style={thR}>Automático</th>
                </tr>
              </thead>
              <tbody>
                {comparacion.anosBase.map((a, k) => {
                  const b = comparacion.anosAuto[k];
                  return (
                    <tr key={a.ano}>
                      <td style={{ ...tdTxt, fontFamily: font.mono }}>{a.ano}</td>
                      <td style={{ ...tdNum, color: a.pct >= 0 ? color.profit : color.loss }}>{pct(a.pct, 0)} · DD {pct(a.dd, 0)}</td>
                      <td style={{ ...tdNum, color: b && b.pct >= 0 ? color.profit : color.loss }}>{b ? `${pct(b.pct, 0)} · DD ${pct(b.dd, 0)}` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── Los periodos ────────────────────────────────────────── */}
          {rotOut && rotOut.periods.length > 0 && (
            <div style={{ marginTop: 10, maxHeight: 260, overflow: "auto", border: `1px solid ${color.border}` }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead style={{ position: "sticky", top: 0, background: color.bgSurface }}>
                  <tr>
                    <th style={thL}>Desde</th>
                    {nombres.map((nm, i) => <th key={nm} style={{ ...thR, color: colorSerie(i) }}>{nm.length > 16 ? `${nm.slice(0, 15)}…` : nm}</th>)}
                    <th style={thL}>Nota</th>
                  </tr>
                </thead>
                <tbody>
                  {rotOut.periods.map((p) => (
                    <tr key={p.from}>
                      <td style={{ ...tdTxt, fontFamily: font.mono }}>{p.from}</td>
                      {p.sizes.map((s, i) => (
                        <td key={i} style={{ ...tdNum, fontWeight: p.ranks && p.ranks[i] === 1 ? 700 : 500 }}>{pct(s, 2)}{p.ranks ? <span style={{ color: color.textMuted }}> ({p.ranks[i]}.º)</span> : null}</td>
                      ))}
                      <td style={{ ...tdTxt, color: color.textMuted }}>{p.nota}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {brakeOut && brakeOut.eventos.length > 0 && (
            <p style={{ ...lbl, margin: "6px 0 0", lineHeight: 1.5 }}>
              Freno: {brakeOut.eventos.map((e) => `${e.date} ${e.que === "freno" ? "frena" : "suelta"} (${pct(e.dd_pct)})`).join(" · ")}
            </p>
          )}
        </>
      )}
    </Sec>
  );
}
