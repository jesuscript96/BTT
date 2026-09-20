"use client";

// Paso 4 · B «Escalado automático» (20-sep-2026, tarde). Jaume: «lo ÚNICO que
// hace que el portfolio mejore es redistribuir pesos, dentro del tope global,
// a la que mejor va en el último periodo de X días; metemos solo eso en el
// escalado. Y el freno como opción». Y ver cómo habría quedado la curva con
// solo la rotación, con solo el freno (pesos fijos) y con las dos.
//
// Las dos reglas, medidas antes de construirlas (docs/MEMORIA.md, 20-sep):
//  - Rotación por ranking: cada periodo, la que más aportó por unidad de
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

/** Las tres simulaciones del escalado (las que haya según lo encendido). */
export interface EscaladoAutoResultado {
  /** Solo rotación (pesos que cambian, sin freno). */
  rot: RawOut | null;
  /** Solo freno (los % del paso 1 fijos, con freno). */
  frenoSolo: RawOut | null;
  /** Rotación + freno. */
  ambos: RawOut | null;
}

export interface EscaladoAutoModel {
  out: RawOut;
  nombres: string[];
  /** % del paso 1 de cada estrategia marcada (mismo orden que `nombres`). */
  pctBase: number[];
  rot: RawRotationIn;
  setRot: React.Dispatch<React.SetStateAction<RawRotationIn>>;
  brake: RawBrakeIn;
  setBrake: React.Dispatch<React.SetStateAction<RawBrakeIn>>;
  auto: EscaladoAutoResultado | null;
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
  const { out, nombres, pctBase, rot, setRot, brake, setBrake, auto, running, error, stale, calcular } = m;
  const cap0 = out.config.capital;
  const setR = <K extends keyof RawRotationIn>(k: K, v: RawRotationIn[K]) => setRot((r) => ({ ...r, [k]: v }));
  const setB = <K extends keyof RawBrakeIn>(k: K, v: RawBrakeIn[K]) => setBrake((b) => ({ ...b, [k]: v }));
  const patron = patronEfectivo(rot, pctBase);
  const sumaPatron = patron.reduce((a, b) => a + b, 0);
  const setPatron = (k: number, v: number) => {
    const p = [...patron]; p[k] = Math.max(0, v);
    setRot((r) => ({ ...r, pattern: p }));
  };
  // La rotación que manda para «hoy»: la de la simulación con las dos reglas si está, si no la de solo rotación.
  const rotOut = auto?.ambos?.rotation ?? auto?.rot?.rotation ?? null;
  const brakeOut = auto?.ambos?.brake ?? auto?.frenoSolo?.brake ?? null;
  const ejemplo = useMemo(() => {
    // Ejemplo numérico del reparto para la ayuda: el patrón sobre un ranking cualquiera.
    const orden = nombres.map((nm, i) => ({ nm, i })).slice(0, patron.length);
    return orden.map((o, k) => `${o.nm.length > 14 ? `${o.nm.slice(0, 13)}…` : o.nm} → ${n(patron[k] ?? 0, 2)} %`).join(", ");
  }, [nombres, patron]);

  const filas = useMemo(() => {
    if (!auto) return null;
    const lista: Array<{ nombre: string; o: RawOut; col: string; width: number }> = [{ nombre: "Fijo (tus % del paso 1)", o: out, col: color.textSecondary, width: 1.4 }];
    if (auto.rot) lista.push({ nombre: "Solo rotación de pesos", o: auto.rot, col: color.copper, width: 2.0 });
    if (auto.frenoSolo) lista.push({ nombre: "Solo freno (pesos fijos)", o: auto.frenoSolo, col: color.info, width: 1.6 });
    if (auto.ambos) lista.push({ nombre: "Rotación + freno", o: auto.ambos, col: color.profit, width: 2.2 });
    const series: Serie[] = lista.map((f) => ({ name: f.nombre, color: f.col, width: f.width, values: f.o.equity.map((e) => (e / cap0 - 1) * 100) }));
    const porAno = lista.map((f) => ({ nombre: f.nombre, anos: retornoPorAno(f.o.calendar, f.o.equity, cap0) }));
    return { lista, series, porAno, anos: porAno[0].anos.map((a) => a.ano) };
  }, [auto, out, cap0]);

  return (
    <Sec
      title="B · Escalado automático: rotación de pesos y freno por caída"
      help={
        <>
          <strong>Qué es.</strong> La única palanca que mejora el portfolio sin adivinar el futuro es <em>a quién</em> le das el capital:
          dentro del tope global (la suma del patrón), más a la estrategia que mejor lo está haciendo y menos a la que peor.
          Aquí eso se hace solo, cada cierto tiempo, y se corre desde el principio con el motor entero para ver cómo habría
          quedado frente a dejar tus % fijos. El freno es una opción aparte, y se corren las combinaciones: solo rotación,
          solo freno con pesos fijos, y las dos.
          <br /><br />
          <strong>Cómo se reparte (la partición).</strong> Cada periodo se mira la ventana anterior (X sesiones) y se ordenan las
          estrategias por lo que cada una aportó al portfolio por cada 1 % de tamaño (así se comparan aunque una vaya por stop
          y otra por capital). La primera del ranking se lleva el primer número del patrón, la segunda el segundo, y así.
          Con tu patrón de ahora: <em>{ejemplo}</em> (según el puesto de cada una ese periodo). Si alguna queda por debajo del suelo,
          sube al suelo y la diferencia se quita de las de arriba en proporción: la suma no cambia. El primer periodo, sin
          historia, va con tus % del paso 1.
          <br /><br />
          <strong>Freno por caída.</strong> Si al abrir el día la cuenta está más de X % por debajo de su máximo, todos los tamaños
          se multiplican por m hasta que la caída vuelve por encima de Y %. Ejemplo con 10 / ×0,5 / 5: la cuenta hace máximo en
          100.000 $, cae a 89.000 (−11 %) → desde el día siguiente todo a la mitad (4/2/1 pasa a 2/1/0,5) → sigue así hasta que
          la cuenta vuelve a 95.000 (−5 %) → tamaño completo otra vez. No predice nada: <em>limita la profundidad</em> de una caída
          que ya ha empezado (una que iba a llegar al −16 % se queda en unos −13 %), a cambio de recuperar más despacio. No evita un
          precipicio de un solo día.
          <br /><br />
          <strong>Al final:</strong> «Siguiente periodo — lo que toca poner»: el % de cada estrategia según el ranking con toda la
          historia, y si el freno está puesto. En el paso 5, con tu CSV, el total lo pone tu cuenta y este reparto se aplica sobre él.
        </>
      }
      right={<Btn primary onClick={calcular} disabled={running || (!rot.enabled && !brake.enabled)}>{running ? "Calculando…" : auto ? "Volver a calcular" : "Calcular escalado"}</Btn>}
    >
      {/* ── Rotación ─────────────────────────────────────────────────── */}
      <Row label="Rotación de pesos" help="Encendida: los % por trade de cada estrategia cambian cada periodo según el ranking. Apagada: se quedan los % del paso 1 (así puedes ver el freno solo).">
        <div style={{ width: 190 }}><Toggle value={rot.enabled ? "si" : "no"} onChange={(v) => setR("enabled", v === "si")} options={[{ value: "si", label: "encendida" }, { value: "no", label: "apagada" }]} /></div>
      </Row>
      {rot.enabled && (
        <>
          <Row label="Cada cuánto" help="Cuándo se vuelve a mirar el ranking y se cambian los pesos: cada semana (el primer día operado de la semana), cada mes (el primer día operado del mes) o cada N sesiones. Entre revisiones, los pesos no se tocan. Más a menudo no es necesariamente mejor: el ranking cambia poco (en tus PM, 4-8 veces en 33 meses) y cada cambio es un salto de tamaño; en tus PM la semanal salió algo mejor que la mensual.">
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
          <Row label="Ventana (X días)" help="Cuántas sesiones hacia atrás se miran para hacer el ranking: «la que mejor lo ha hecho en los últimos X días». Corta (20-60) reacciona rápido pero es ruidosa: un mes bueno de una estrategia mala la sube al primer puesto. Larga (126-252 sesiones = 6-12 meses) mide la calidad de verdad y cambia poco. Medido en tus PM: 126 fue lo mejor. Hasta que no hay tantas sesiones de historia, se usan los % del paso 1.">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ width: 70 }}><Num value={rot.lookback_days} onChange={(v) => setR("lookback_days", Math.max(5, Math.round(Number(v) || 5)))} min={5} step={21} style={numChico} /></div>
              <span style={lbl}>sesiones (126 ≈ 6 meses, 252 ≈ 1 año)</span>
            </div>
          </Row>
          <Row label="Por qué se ordena" help={<>
            Lo que se mira de cada estrategia en la ventana para ordenarlas. Siempre en RELATIVO al tamaño (por cada 1 % que se le da), nunca en dinero: así una con el 1 % y otra con el 4 % se comparan de igual a igual.
            <br /><br />
            <strong>Lo ganado por 1 %</strong>: lo que aportó al portfolio por cada 1 % de tamaño, sumado en la ventana: quien más ha aportado por unidad, primera (es lo que se midió: +17-35 % en tus PM).
            <br /><strong>EV por trade</strong>: lo mismo dividido por sus trades: la calidad media de cada operación, sin premiar a la que opera más.
            <br /><strong>Por hora en mercado</strong>: lo ganado por 1 % dividido por las horas que tuvo posición abierta: premia a la que entra y sale rápido frente a la que ocupa la sesión entera ganando más. Ojo: en esta simulación tener la posición abierta mucho rato no cuesta nada (cada estrategia tiene su % y no se roban capital, salvo que el margen del bróker esté activado), así que esta forma de ordenar no hace ganar más aquí; sirve si tú prefieres estrategias rápidas por razones de fuera (buying power real, atención, riesgo de estar dentro).
            <br /><strong>Sharpe</strong>: lo ganado dividido por lo que oscila día a día: premia a la regular frente a la que gana a golpes (con tus PM fue peor).
            <br /><br />No es «la que ha mejorado más»: es «la que mejor lo ha hecho en la ventana».
          </>}>
            <div style={{ width: 480 }}><Toggle value={rot.metric} onChange={(v) => setR("metric", v)} options={[{ value: "return", label: "lo ganado por 1 %" }, { value: "ev_trade", label: "EV por trade" }, { value: "per_hour", label: "por hora en mercado" }, { value: "sharpe", label: "Sharpe" }]} /></div>
          </Row>
          <Row label="Patrón de pesos" help="El % por trade que se lleva cada PUESTO del ranking: el primer número va a la mejor estrategia del periodo, el segundo a la siguiente… La suma del patrón es el tope global (elígelo con el bloque A). Por defecto son tus % del paso 1 ordenados de mayor a menor (con 4/2/1 en el paso 1: la mejor 4, la del medio 2, la peor 1), así la suma es la misma que sin rotación y la comparación es justa. Un patrón más desigual (5/2/0) gana más y cae más; uno más plano (3/2/2) al revés.">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {patron.map((v, k) => (
                <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <span style={lbl}>{k + 1}.º</span>
                  <div style={{ width: 62 }}><Num value={v} onChange={(x) => setPatron(k, Number(x) || 0)} min={0} step={0.5} style={numChico} /></div>
                </span>
              ))}
              <span style={lbl}>= {n(sumaPatron, 2)} % por trade en total (el tope global)</span>
              <Btn onClick={() => setRot((r) => ({ ...r, pattern: null }))}>los del paso 1</Btn>
            </div>
          </Row>
          <Row label="Suelo por estrategia" help="Ninguna estrategia baja de este % por trade, aunque el patrón le dé menos (o 0). Lo que le falte para llegar al suelo se quita de las que están por encima, en proporción, para que la suma no cambie. Sirve para no apagar del todo a la que va peor: sigue operando en pequeño y, si vuelve a rendir, el ranking la sube (el ranking se calcula con lo que rinde por unidad, no con lo que llevaba). Con 0, una estrategia con 0 en el patrón queda apagada hasta que el ranking la suba.">
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
        <Row label="Freno por caída" help={<>
            <strong>Sin freno</strong>: cada trade va con su % del capital de ese día. Si la cuenta baja, apuestas menos dólares (porque el capital es menor) pero el MISMO %: eso ya lo hace el compound solo.
            <br /><br />
            <strong>Con freno</strong>: se mira cada mañana cuánto ha caído la cuenta desde su máximo (con el cierre de ayer). Si la caída pasa de X %, ADEMÁS del compound, todos los tamaños se multiplican por m (0,5 = la mitad) y se quedan así hasta que la caída vuelve a ser menor que Y %. Entonces se quita el freno y se vuelve al tamaño completo.
            <br /><br />
            <strong>Para qué</strong>: que una mala racha que ya ha empezado no se haga tan profunda: a partir del −X % solo pierdes la mitad (o lo que pongas en m) de lo que perderías sin freno. <strong>Lo que cuesta</strong>: los días buenos que llegan mientras estás frenado también cuentan a la mitad, así que recuperas más despacio. <strong>Lo que no evita</strong>: un precipicio de un solo día, porque se decide con el cierre de ayer.
            <br /><br />Se corre con freno y sin freno (y con y sin rotación) para que veas las cuatro curvas y elijas.
          </>}>
          <div style={{ width: 190 }}><Toggle value={brake.enabled ? "si" : "no"} onChange={(v) => setB("enabled", v === "si")} options={[{ value: "si", label: "con freno" }, { value: "no", label: "sin freno" }]} /></div>
        </Row>
        {brake.enabled && (
          <Row label="Regla" help={<>
            Ejemplo con 10 / ×0,5 / 5: la cuenta hace máximo en 100.000 $ y va cayendo. Mientras esté por encima de 90.000 (menos de un 10 % de caída) no pasa nada. El día que cierra en 89.000 (−11 %), desde la mañana siguiente todo va a la mitad: 4/2/1 pasa a 2/1/0,5. Sigue a la mitad aunque la cuenta suba a 92.000 o baje a 85.000. El día que cierra en 95.000 o más (menos de un 5 % de caída), a la mañana siguiente se vuelve al tamaño completo.
            <br /><br />
            <strong>Frena a partir de −X %</strong>: cuanto más pequeño, antes frena y más a menudo (10 % en tus PM: 4 veces, 42 días en total de 668). <strong>Multiplicador</strong>: 0,5 = la mitad; 0,25 = un cuarto; 0 = no operar hasta soltar. <strong>Suelta al volver a −Y %</strong>: tiene que ser menor que X; con Y = 0 hay que volver al máximo, y eso a mitad de tamaño puede tardar meses.
            <br /><br />Regla de bolsillo: la caída máxima se queda en X + (lo que hubiera sobrepasado) × m. Una caída que sin freno iba a llegar al −16 % se queda en unos −13 %.
          </>}>
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
      {stale && auto && <Nota tone="warning">Los ajustes han cambiado desde el último cálculo.</Nota>}
      {!auto && !error && <Nota>Pulsa <strong>Calcular escalado</strong>: el portfolio desde el principio con {rot.enabled && brake.enabled ? "solo rotación, solo freno y las dos" : rot.enabled ? "la rotación" : brake.enabled ? "el freno" : "(enciende la rotación o el freno)"}, frente a tus % fijos, y lo que toca el siguiente periodo.</Nota>}

      {auto && filas && (
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
                  <Stat label="Total por trade" value={pct(rotOut.hoy.total_pct, 2)} sub="sumando todas (el tope global)" />
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
            {filas.lista.map((f, k) => (
              <Stat key={f.nombre} label={f.nombre} value={usd(f.o.equity[f.o.equity.length - 1])} sub={`DD ${pct(maxDd(f.o.equity, cap0))} · ${n(f.o.cap_report.taken, 0)} trades`} tone={k === 0 ? undefined : f.o.equity[f.o.equity.length - 1] >= out.equity[out.equity.length - 1] ? "profit" : "loss"} />
            ))}
            {rotOut && <Stat label="Rotación" value={`${n(rotOut.rebalanceos, 0)} revisiones`} sub={`${n(rotOut.cambios_de_ranking, 0)} cambios de ranking · tamaño medio ${rotOut.size_medio.map((x) => n(x, 2)).join(" / ")} %`} />}
            {brakeOut && <Stat label="Freno" value={`${n(brakeOut.dias_frenado, 0)} días frenado`} sub={`${n(brakeOut.episodios, 0)} episodios`} />}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 420px", gap: 12, alignItems: "start", marginTop: 8 }}>
            <LinesChart labels={out.calendar} series={filas.series} yFormat={(v) => `${n(v, 0)} %`} hoverFormat={(v) => `${n(v, 1)} %`} height={280} titulo="RETORNO SOBRE EL CAPITAL" />
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thL}>Año</th>
                  {filas.porAno.map((p) => <th key={p.nombre} style={thR}>{p.nombre.replace("Fijo (tus % del paso 1)", "Fijo").replace("Solo rotación de pesos", "Rotación").replace("Solo freno (pesos fijos)", "Freno").replace("Rotación + freno", "Las dos")}</th>)}
                </tr>
              </thead>
              <tbody>
                {filas.anos.map((ano, k) => (
                  <tr key={ano}>
                    <td style={{ ...tdTxt, fontFamily: font.mono }}>{ano}</td>
                    {filas.porAno.map((p) => {
                      const a = p.anos[k];
                      return <td key={p.nombre} style={{ ...tdNum, color: a && a.pct >= 0 ? color.profit : color.loss }}>{a ? `${pct(a.pct, 0)} · DD ${pct(a.dd, 0)}` : "—"}</td>;
                    })}
                  </tr>
                ))}
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
