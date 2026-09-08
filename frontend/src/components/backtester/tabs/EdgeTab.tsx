"use client";

// Pestaña «Edge»: ¿el edge de esta estrategia se está erosionando, o lo que
// cambia es el entorno y yo estoy a punto de tocar algo por ruido?
//
// Va después de «Análisis por trade» a propósito. El orden de las pestañas es un
// zoom hacia fuera: Trades = una operación · Análisis por trade = el microscopio
// · Edge = las mismas operaciones agregadas en el TIEMPO · Charts+Optimization =
// qué valor pongo. Y NO vive dentro de Optimization aunque encaje temáticamente:
// Optimization responde «¿cuál es el mejor valor?» y siempre devuelve uno; esta
// pestaña responde «¿debo cambiar algo?» y su respuesta correcta suele ser NO.
//
// Todo lo que hay aquí sale de `result.trades`. No pide nada al backend.

import React, { useMemo, useState } from "react";
import type { TradeRecord } from "@/lib/api_backtester";
import { Table, Th, Td, Tr, color, font, radius } from "@/components/ui";
import { Help } from "@/components/robustez/help";
import {
  agrupar, barridoSL, barridoTP, envolventeDD, f1, f2, mejorPunto,
  miles, percentil, preparar, rangoBarrido, resumir, serieMensual, sgn, tocaBorde,
  unidadDisponible, type Modo, type Unidad,
} from "./edge/calc";
import { Barras, Barrido, Excursiones, Forest, Histograma, Mensual } from "./edge/charts";

/* ---- piezas de presentación ---- */

const num: React.CSSProperties = {
  fontFamily: font.mono, fontVariantNumeric: "tabular-nums", textAlign: "right",
};

function Ayuda({ titulo, ves, ejemplo, sirve, nota }: {
  titulo: string; ves: string; ejemplo: React.ReactNode; sirve: string; nota?: string;
}) {
  return (
    <Help title={titulo} width={370}>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <div>
          <b style={{ color: color.textHigh }}>Qué estás viendo. </b>
          <span style={{ color: color.textSecondary }}>{ves}</span>
        </div>
        <div style={{
          borderLeft: `2px solid ${color.copper}`, paddingLeft: 8,
          color: color.textPrimary, fontSize: "0.96em",
        }}>
          <b style={{ color: color.copperBright }}>Por ejemplo: </b>{ejemplo}
        </div>
        <div>
          <b style={{ color: color.textHigh }}>Para qué sirve. </b>
          <span style={{ color: color.textSecondary }}>{sirve}</span>
        </div>
        {nota && (
          <div style={{ color: color.warning, fontSize: "0.92em" }}>Ojo: {nota}</div>
        )}
      </div>
    </Help>
  );
}

function Bloque({ titulo, ayuda, pie, children, ancho }: {
  titulo: string; ayuda: React.ReactNode; pie?: React.ReactNode;
  children: React.ReactNode; ancho?: string;
}) {
  return (
    <div style={{
      background: color.bgSurface, border: `0.5px solid ${color.border}`,
      borderRadius: radius.md, overflow: "hidden", display: "flex",
      flexDirection: "column", minWidth: 0, gridColumn: ancho,
    }}>
      <div style={{
        background: color.bgElevated, borderBottom: `0.5px solid ${color.border}`,
        padding: "8px 13px", display: "flex", alignItems: "center", gap: 9,
      }}>
        <h3 style={{
          margin: 0, flex: 1, fontFamily: font.sans, fontSize: 12, fontWeight: 600,
          color: color.textHigh, letterSpacing: "0.01em",
        }}>{titulo}</h3>
        {ayuda}
      </div>
      <div style={{ padding: 13, minWidth: 0 }}>{children}</div>
      {pie && (
        <div style={{
          borderTop: `0.5px solid ${color.border}`, padding: "8px 13px",
          fontSize: 11.5, color: color.textSecondary, lineHeight: 1.5,
        }}>{pie}</div>
      )}
    </div>
  );
}

function Fase({ n }: { n: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 11, margin: "22px 0 10px" }}>
      <span style={{
        fontFamily: font.sans, fontSize: 10, fontWeight: 600, letterSpacing: "0.15em",
        textTransform: "uppercase", color: color.textMuted, whiteSpace: "nowrap",
      }}>{n}</span>
      <span style={{ flex: 1, height: 1, background: color.border }} />
    </div>
  );
}

function Cifra({ k, v, s, tono }: { k: string; v: string; s?: string; tono?: string }) {
  return (
    <div style={{ flex: 1, padding: "0 14px", borderRight: `0.5px solid ${color.border}`, minWidth: 0 }}>
      <div style={{ fontSize: 10, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted }}>{k}</div>
      <div style={{ ...num, textAlign: "left", fontSize: 20, color: tono || color.textHigh, marginTop: 2 }}>{v}</div>
      {s && <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 1 }}>{s}</div>}
    </div>
  );
}

const Seg = <T extends string>({ valor, opciones, onChange }: {
  valor: T; opciones: { id: T; label: string }[]; onChange: (v: T) => void;
}) => (
  <div style={{ display: "flex", border: `0.5px solid ${color.border}`, borderRadius: radius.sm, overflow: "hidden" }}>
    {opciones.map((o, i) => (
      <button key={o.id} onClick={() => onChange(o.id)}
        style={{
          background: valor === o.id ? color.copper : color.bgBase,
          color: valor === o.id ? "var(--color-ec-copper-text)" : color.textSecondary,
          fontWeight: valor === o.id ? 600 : 400,
          border: 0, borderLeft: i ? `0.5px solid ${color.border}` : undefined,
          fontFamily: font.sans, fontSize: 11.5, padding: "5px 11px", cursor: "pointer",
        }}>{o.label}</button>
    ))}
  </div>
);

/* ---- la pestaña ---- */

const MIN_OPS = 100;

export default function EdgeTab({ trades }: { trades: TradeRecord[] }) {
  const [modo, setModo] = useState<Modo>("anio");
  const unidadMax = useMemo(() => unidadDisponible(trades), [trades]);
  const [unidad, setUnidad] = useState<Unidad>(unidadMax);
  const u: Unidad = unidadMax === "$" ? "$" : unidad;

  const datos = useMemo(() => {
    const filas = preparar(trades, modo, u);
    const grupos = agrupar(filas);
    const res = resumir(grupos);
    const serie = serieMensual(filas, 6);
    const env = envolventeDD(filas);
    const conSL = filas.filter((f) => f.slDist > 0).map((f) => f.slDist).sort((a, b) => a - b);
    const slActual = conSL.length ? percentil(conSL, 0.5) : null;
    const hayR = filas.some((f) => f.slDist > 0);

    // El rango de los barridos se saca de los datos, y el del stop tiene además
    // que dejar dentro el que ya se usa: si no, la raya de «ahora» no aparece.
    const rangoTP = rangoBarrido(filas.map((f) => f.mfe));
    const rangoSL = rangoBarrido(filas.map((f) => f.mae), slActual);

    // Los barridos van por periodo, pero solo los 6 últimos con muestra
    // suficiente: más líneas y ninguna se lee.
    const utiles = res.filter((r) => r.n >= MIN_OPS).slice(-6);
    const series = utiles.map((r) => {
      const g = grupos.get(r.periodo)!;
      const tp = barridoTP(g, hayR, rangoTP);
      const sl = barridoSL(g, rangoSL);
      return {
        etiqueta: r.periodo,
        tp: { etiqueta: r.periodo, puntos: tp, mejor: mejorPunto(tp) },
        sl: { etiqueta: r.periodo, puntos: sl, mejor: mejorPunto(sl) },
      };
    });
    return { filas, grupos, res, serie, env, slActual, hayR, series, utiles };
  }, [trades, modo, u]);

  const { res, serie, env, slActual, hayR, series } = datos;
  const uL = u === "R" ? "R" : "$";
  const ultimo = res[res.length - 1];
  const primero = res[0];
  const flojos = res.filter((r) => r.n < MIN_OPS);

  if (!trades.length) {
    return <div style={{ padding: 24, color: color.textMuted, fontFamily: font.sans }}>
      Este resultado no tiene operaciones que analizar.
    </div>;
  }

  const ultSerie = series.length ? series[series.length - 1] : null;
  const mejorTP = ultSerie ? ultSerie.tp.mejor : null;
  const mejorTPviejo = series.length > 1 ? series[0].tp.mejor : null;
  const mejorSL = ultSerie ? ultSerie.sl.mejor : null;
  const tpBorde = ultSerie ? tocaBorde(ultSerie.tp.puntos, mejorTP) : false;
  const slBorde = ultSerie ? tocaBorde(ultSerie.sl.puntos, mejorSL) : false;

  return (
    <div style={{ padding: "14px 4px 40px", fontFamily: font.sans, color: color.textPrimary }}>

      {/* === FASE 1 === */}
      <Fase n="1 · ¿Se puede leer esto?" />
      <Bloque
        titulo="Comparabilidad y muestra"
        ayuda={<Ayuda
          titulo="Comparabilidad y muestra"
          ves="Cuántas operaciones tiene cada periodo y en qué unidad se está midiendo todo lo demás."
          ejemplo={<>Si 2024 tiene {miles(primero?.n ?? 0)} operaciones y otro periodo tiene 12,
            el de 12 no dice nada: con esa muestra, un solo día bueno cambia el resultado entero.
            Por eso se marcan los periodos con menos de {MIN_OPS} operaciones.</>}
          sirve="Es el filtro de entrada. Dos periodos solo se pueden comparar si salen del mismo motor y del mismo universo; si el rango cruza un cambio del programa, lo que verías abajo serían tus propios cambios de código, no el mercado."
          nota="Las corridas guardadas antes del 27-ago-2026 (SL de estructura) y del 6-sep-2026 (universo y ventana de entrada) NO son comparables con las nuevas. Vuelve a lanzar el rango entero de una vez."
        />}
        pie={<>Todos los periodos vienen de <b style={{ color: color.textPrimary }}>esta misma corrida</b>, así
          que son comparables entre sí. Lo que no puedes es comparar esta pantalla contra una corrida guardada
          hace semanas.</>}
      >
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11.5, color: color.textMuted }}>Agrupar por</span>
            <Seg valor={modo} onChange={setModo} opciones={[
              { id: "anio" as Modo, label: "Año" },
              { id: "semestre" as Modo, label: "Semestre" },
              { id: "trimestre" as Modo, label: "Trimestre" },
            ]} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11.5, color: color.textMuted }}>Unidad</span>
            {unidadMax === "R"
              ? <Seg valor={unidad} onChange={setUnidad} opciones={[
                  { id: "R" as Unidad, label: "R" }, { id: "$" as Unidad, label: "$" }]} />
              : <span style={{ ...num, fontSize: 12, color: color.warning }}>
                  $ · esta corrida no trae R por operación
                </span>}
          </div>
        </div>
        <div style={{ display: "flex", borderTop: `0.5px solid ${color.border}`, marginTop: 12, paddingTop: 12 }}>
          <Cifra k="Operaciones" v={miles(trades.length)} s={`${res.length} periodos`} />
          <Cifra k="Periodos con muestra" v={`${res.length - flojos.length}`}
                 s={`de ${res.length} · mínimo ${MIN_OPS} ops`}
                 tono={flojos.length ? color.warning : color.profit} />
          <Cifra k="Unidad" v={uL} s={u === "R" ? "múltiplos de riesgo" : "dinero"} />
          <Cifra k="Stop conocido" v={hayR ? "Sí" : "No"}
                 s={slActual != null ? `mediana ${f1(slActual)} %` : "sin distancia al SL"}
                 tono={hayR ? undefined : color.warning} />
        </div>
      </Bloque>

      {/* === FASE 2 === */}
      <Fase n="2 · ¿Ha cambiado el edge?" />
      <Bloque
        titulo="Expectancy descompuesta por periodo"
        ayuda={<Ayuda
          titulo="Expectancy descompuesta por periodo"
          ves={`Lo que gana de media cada operación en cada periodo, partido en sus piezas: cuántas ganas, cuánto ganas cuando ganas y cuánto pierdes cuando pierdes. La barra del gráfico es el margen de error.`}
          ejemplo={ultimo && primero && res.length > 1 ? (
            <>En {primero.periodo} cada operación dejaba {sgn(primero.expectancy)} {uL} y en {ultimo.periodo} deja {sgn(ultimo.expectancy)} {uL}.
              Parece una caída — pero mira las barras: la de {ultimo.periodo} va de {sgn(ultimo.lo, 2)} a {sgn(ultimo.hi, 2)}.
              {ultimo.hi >= primero.lo
                ? " Se solapan, así que no puedes afirmar que sean distintas: es la misma estrategia con suerte distinta."
                : " NO se solapan, así que la diferencia es real y no casualidad."}</>
          ) : "Cada punto es la media y la barra es hasta dónde podría estar de verdad."}
          sirve="Es la pregunta madre de la pestaña. Si las barras de dos periodos se solapan, no ha pasado nada y tocar la estrategia sería perseguir ruido. Solo cuando dejan de solaparse tienes derecho a decir que el edge ha cambiado."
          nota="Una media sin su barra de error es una trampa: con pocas operaciones siempre parece que hay tendencia."
        />}
        pie={ultimo && primero && res.length > 1 ? (
          ultimo.hi >= primero.lo
            ? <>Los intervalos del primer y último periodo <b style={{ color: color.warning }}>se solapan</b>: no hay
                prueba de que el edge haya cambiado. Ojo con reoptimizar por una racha.</>
            : <>Los intervalos del primer y último periodo <b style={{ color: color.loss }}>no se solapan</b>: la
                diferencia es real. Mira abajo si el motivo es el objetivo, el stop o el entorno.</>
        ) : undefined}
      >
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, alignItems: "start" }}>
          <div style={{ overflowX: "auto" }}>
            <Table>
              <thead><Tr>
                <Th>Periodo</Th><Th style={{ textAlign: "right" }}>Ops</Th>
                <Th style={{ textAlign: "right" }}>Aciertos</Th>
                <Th style={{ textAlign: "right" }}>Gana</Th>
                <Th style={{ textAlign: "right" }}>Pierde</Th>
                <Th style={{ textAlign: "right" }}>Expectancy</Th>
                <Th style={{ textAlign: "right" }}>PF</Th>
              </Tr></thead>
              <tbody>
                {res.map((r) => (
                  <Tr key={r.periodo}>
                    <Td style={{ fontFamily: font.mono, color: color.textHigh }}>
                      {r.periodo}{r.n < MIN_OPS && <span style={{ color: color.warning }}> ·poca</span>}
                    </Td>
                    <Td style={num}>{miles(r.n)}</Td>
                    <Td style={num}>{f1(r.wr)} %</Td>
                    <Td style={{ ...num, color: color.profit }}>+{f2(r.ganMedia)}</Td>
                    <Td style={{ ...num, color: color.loss }}>−{f2(r.perdMedia)}</Td>
                    <Td style={{ ...num, color: color.textHigh, fontWeight: 600 }}>{sgn(r.expectancy)}</Td>
                    <Td style={num}>{Number.isFinite(r.pf) ? f2(r.pf) : "—"}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
          <Forest unidad={uL} filas={res.map((r) => ({ etiqueta: r.periodo, v: r.expectancy, lo: r.lo, hi: r.hi }))} />
        </div>
      </Bloque>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 12, marginTop: 12 }}>
        <Bloque
          titulo="Concentración de la cola"
          ayuda={<Ayuda
            titulo="Concentración de la cola"
            ves="De cuántas operaciones depende tu resultado. La barra es el porcentaje del beneficio NETO (lo que te llevas al bolsillo) que aporta el 10 % mejor de operaciones."
            ejemplo={ultimo ? (
              <>En {ultimo.periodo}, el 10 % mejor de tus operaciones aporta el {f1(ultimo.decilSup)} % de lo que
                ganaste, y hacen falta solo {ultimo.ops50} operaciones para juntar la mitad del dinero.
                Si esa barra sube año a año, cada vez dependes más de que aparezcan cuatro monstruos.</>
            ) : ""}
            sirve="Detecta fragilidad, que es distinto de perder. Una estrategia puede ganar lo mismo cada año y ser mucho más frágil, porque el beneficio se apoya en menos operaciones. Cuando esa barra sube, la probabilidad de un año malo sube aunque el edge medio no se mueva."
            nota="Puede pasar del 100 %, y no es un fallo: significa que el otro 90 % de las operaciones, juntas, PIERDEN dinero, y que todo lo que ganas sale del 10 % mejor. Es el caso más frágil que hay."
          />}
          pie={ultimo && primero && res.length > 1
            ? <>El decil superior pasa del <b>{f1(primero.decilSup)} %</b> al <b>{f1(ultimo.decilSup)} %</b> del beneficio.</>
            : undefined}
        >
          <Barras titulo="% del beneficio NETO que aporta el 10 % mejor · por encima de 100 % el resto pierde"
                  sufijo=" %" filas={res.map((r) => ({ etiqueta: r.periodo, v: r.decilSup }))} />
          <div style={{ overflowX: "auto", marginTop: 10 }}>
            <Table>
              <thead><Tr>
                <Th>Periodo</Th><Th style={{ textAlign: "right" }}>Decil sup.</Th>
                <Th style={{ textAlign: "right" }}>Sin el 1 % mejor</Th>
                <Th style={{ textAlign: "right" }}>Ops = 50 %</Th>
              </Tr></thead>
              <tbody>
                {res.map((r) => (
                  <Tr key={r.periodo}>
                    <Td style={{ fontFamily: font.mono, color: color.textHigh }}>{r.periodo}</Td>
                    <Td style={num}>{f1(r.decilSup)} %</Td>
                    <Td style={{ ...num, color: r.sinMejor1 <= 0 ? color.loss : color.textPrimary }}>
                      {sgn(r.sinMejor1)} {uL}</Td>
                    <Td style={num}>{r.ops50}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
        </Bloque>

        <Bloque
          titulo="Oportunidad contra edge"
          ayuda={<Ayuda
            titulo="Oportunidad contra edge"
            ves="Las barras grises son cuántas operaciones hubo cada mes. La línea de cobre es lo que valía de media cada operación, suavizada a seis meses, con su margen de error."
            ejemplo={<>Imagina que este año ganas la mitad que el pasado. Si las barras han bajado a la mitad y la
              línea sigue plana, el problema es que hay menos días buenos: tu estrategia está intacta y no hay
              nada que tocar. Si las barras siguen igual y la línea baja, entonces sí: cada operación vale menos.</>}
            sirve="Separa «gano menos porque hay menos oportunidades» de «gano menos por operación». Son problemas distintos y solo el segundo se arregla cambiando parámetros; el primero se arregla esperando o buscando más universo."
            nota="La banda es ancha a propósito. Un mes suelto no significa nada, y así se ve."
          />}
        >
          <Mensual serie={serie} unidad={uL} />
        </Bloque>
      </div>

      {/* === FASE 3 === */}
      <Fase n="3 · ¿Dónde y por qué?" />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 12 }}>
        <Bloque
          titulo="Recorrido a favor y en contra (MFE / MAE)"
          ayuda={<Ayuda
            titulo="Recorrido a favor y en contra"
            ves="Cuánto se movió el precio a tu favor (verde) y en tu contra (rojo) dentro de cada operación, en % sobre el precio de entrada. La caja es el grueso de las operaciones y la raya blanca es la mediana."
            ejemplo={ultimo ? (
              <>En {ultimo.periodo}, la operación típica llegó a ir {f1(ultimo.mfeP[1])} % a favor y {f1(ultimo.maeP[1])} % en contra.
                Si el verde se encoge año a año y el rojo no, es que hay menos recorrido que capturar por el mismo
                riesgo — la señal más temprana de que algo se está agotando.</>
            ) : ""}
            sirve="Es el aviso que llega ANTES que la caída del beneficio, y no depende de los parámetros que tengas puestos: es una propiedad del mercado. Además es de aquí de donde se decide dónde poner el objetivo y el stop, que es lo que ves en los dos gráficos de abajo."
          />}
          pie={ultimo && primero && res.length > 1 ? (
            <>Recorrido a favor típico: <b>{f1(primero.mfeP[1])} % → {f1(ultimo.mfeP[1])} %</b>.
              En contra: <b>{f1(primero.maeP[1])} % → {f1(ultimo.maeP[1])} %</b>.</>
          ) : undefined}
        >
          <Excursiones filas={res.map((r) => ({ etiqueta: r.periodo, mfeP: r.mfeP, maeP: r.maeP }))} />
          <div style={{ display: "flex", gap: 15, marginTop: 9, fontSize: 11, fontFamily: font.mono, color: color.textSecondary, flexWrap: "wrap" }}>
            <span style={{ color: color.profit }}>■ a favor (MFE)</span>
            <span style={{ color: color.loss }}>■ en contra (MAE)</span>
            <span>caja p25–p75 · bigote p90 · raya mediana</span>
          </div>
        </Bloque>

        <Bloque
          titulo="¿Está rota? Envolvente de caída"
          ayuda={<Ayuda
            titulo="Envolvente de caída"
            ves="Se baraja 2.000 veces el ORDEN de tus propias operaciones y se anota la peor caída de cada baraje. El histograma son esas 2.000 caídas; la raya de cobre es la que has tenido de verdad."
            ejemplo={env ? (
              <>Tu peor caída ha sido {f1(env.actual)} {uL}. Barajando tus mismas operaciones, la caída típica sale
                {" "}{f1(env.mediana)} {uL} y solo una de cada veinte llega a {f1(env.p95)} {uL}.
                {env.actual > env.p95
                  ? " O sea que lo que has pasado entra dentro de lo normal para esta estrategia."
                  : " La tuya se ha salido de esa raya: ahí sí hay algo que mirar."}</>
            ) : "Hacen falta al menos 30 operaciones."}
            sirve="Es el freno contra apagar una estrategia sana por una mala racha. Toda estrategia con edge produce caídas grandes solo por el orden en que salen las operaciones; esto te dice si la tuya es una de esas o si de verdad se ha salido del guion."
            nota="Baraja el orden, no inventa operaciones. Si el mercado ha cambiado, esto no lo detecta — para eso está el bloque de arriba."
          />}
          pie={env ? (
            env.actual > env.p95
              ? <><b style={{ color: color.profit }}>Dentro de lo normal.</b> Tu caída está en el percentil {f1(env.percentilActual)}.
                  Una racha así no es motivo para apagar ni para reoptimizar.</>
              : <><b style={{ color: color.loss }}>Fuera de la envolvente.</b> Tu caída supera el 95 % de las
                  reordenaciones de tus propias operaciones.</>
          ) : undefined}
        >
          {env
            ? <>
                <Histograma hist={env.hist} actual={env.actual} p95={env.p95} unidad={uL} />
                <div style={{ display: "flex", borderTop: `0.5px solid ${color.border}`, marginTop: 10, paddingTop: 10 }}>
                  <Cifra k="Caída real" v={`${f1(env.actual)} ${uL}`} s={`percentil ${f1(env.percentilActual)}`} />
                  <Cifra k="Típica" v={`${f1(env.mediana)} ${uL}`} s="lo esperable" />
                  <Cifra k="Percentil 95" v={`${f1(env.p95)} ${uL}`} s="línea de alarma" tono={color.warning} />
                </div>
              </>
            : <div style={{ color: color.textMuted, fontSize: 12 }}>Hacen falta al menos 30 operaciones.</div>}
        </Bloque>
      </div>

      {/* === FASE 4 === */}
      <Fase n="4 · ¿Cambio algo?" />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 12 }}>
        <Bloque
          titulo="Barrido de Take Profit"
          ayuda={<Ayuda
            titulo="Barrido de Take Profit"
            ves={`Qué habría pasado con cada objetivo posible. Si el precio llegó a ir un X % a favor, la operación habría cerrado ahí; si no llegó, acaba como acabó. Una línea por periodo, y el punto marca el mejor objetivo de ese periodo.`}
            ejemplo={mejorTP && mejorTPviejo && series.length > 1 ? (
              <>En {series[0].etiqueta} el mejor objetivo estaba en {f1(mejorTPviejo.x)} % y en {series[series.length - 1].etiqueta} está
                en {f1(mejorTP.x)} %. Si se ha estrechado, el mercado te da menos recorrido y aguantar a por más te
                está costando dinero. Y si las líneas son casi planas, da igual dónde lo pongas: eso también es
                una respuesta.</>
            ) : mejorTP ? <>El mejor objetivo de este periodo está en {f1(mejorTP.x)} %.</> : ""}
            sirve="Es un barrido de objetivo GRATIS: no hay que lanzar ni un backtest más, sale del recorrido que ya midió el motor. Y como hay una línea por periodo, ves si el punto bueno se está moviendo con el tiempo o siempre estuvo donde está."
            nota="Es por operación aislada: no simula reentradas, ni piramidación, ni el capital. Sirve para orientar dónde mirar, no como promesa de beneficio."
          />}
          pie={mejorTP ? (tpBorde
            ? <>El resultado <b style={{ color: color.warning }}>sigue subiendo en el borde</b> del barrido: el
                objetivo bueno está más allá del recorrido que llegan a hacer tus operaciones. Traducido: a esta
                estrategia le sienta mal ponerle objetivo, mejor dejar correr.</>
            : <>Mejor objetivo del último periodo: <b style={{ color: color.copperBright }}>{f1(mejorTP.x)} %</b>.
                Elige el centro de la meseta, no el pico exacto.</>) : undefined}
        >
          {series.length
            ? <Barrido series={series.map((s) => s.tp)} unidad={hayR ? "R" : "%"}
                       ejeX={`take profit · resultado medio por operación en ${hayR ? "R" : "% de precio"}`} />
            : <div style={{ color: color.textMuted, fontSize: 12 }}>
                Ningún periodo llega a {MIN_OPS} operaciones.
              </div>}
        </Bloque>

        <Bloque
          titulo="Barrido de Stop Loss"
          ayuda={<Ayuda
            titulo="Barrido de Stop Loss"
            ves="Lo mismo con el stop: si el precio llegó a ir un X % en tu contra, la operación habría saltado ahí. Siempre en R, nunca en dinero."
            ejemplo={mejorSL ? (
              <>El mejor stop del último periodo sale en {f1(mejorSL.x)} %, dando {sgn(mejorSL.v)} R por operación.
                Un stop más corto salta demasiado; uno más largo te hace pagar caras las malas.
                {slActual != null && <> Ahora mismo llevas la mediana en {f1(slActual)} % — es la raya amarilla.</>}</>
            ) : ""}
            sirve="Te dice si el stop que llevas está en la zona buena o te has quedado descolgado. Y comparando las líneas de los distintos periodos ves si el stop bueno lleva años en el mismo sitio (lo normal) o se está moviendo."
            nota="En R obligatoriamente. Con «Shares por distancia al SL» encendido, acortar el stop agranda la posición, así que el resultado en dinero no se puede comparar entre stops distintos. En múltiplos de riesgo sí. Y el barrido empieza en el 1 % a propósito: por debajo, la vela de un minuto no tiene resolución para decir si el stop habría saltado o no, y saldrían R's imposibles."
          />}
          pie={mejorSL ? (slBorde
            ? <>El mejor stop cae en el <b style={{ color: color.warning }}>borde del barrido</b>: cuanto más ancho,
                mejor sale. Con esta estrategia el stop no es lo que hay que apretar.</>
            : <>Mejor stop del último periodo: <b style={{ color: color.copperBright }}>{f1(mejorSL.x)} %</b>
                {slActual != null && <> · el que llevas: <b>{f1(slActual)} %</b></>}.</>) : undefined}
        >
          {series.length
            ? <Barrido series={series.map((s) => s.sl)} unidad="R" marcaActual={slActual}
                       ejeX="stop loss · resultado medio por operación en R" />
            : <div style={{ color: color.textMuted, fontSize: 12 }}>
                Ningún periodo llega a {MIN_OPS} operaciones.
              </div>}
        </Bloque>
      </div>

      <div style={{
        marginTop: 16, padding: "10px 13px", border: `0.5px solid ${color.border}`,
        borderLeft: `2px solid ${color.copper}`, borderRadius: radius.sm,
        background: color.bgSurface, fontSize: 11.5, color: color.textSecondary, lineHeight: 1.55,
      }}>
        <b style={{ color: color.textHigh }}>Antes de tocar un parámetro, las tres llaves.</b>{" "}
        Una: el intervalo del periodo reciente no se solapa con el de antes. Dos: el signo del cambio se repite en
        los dos últimos periodos, no solo en el agregado. Tres: el punto bueno se desplaza de forma ordenada, no a
        saltos. Si falta una, no se toca — y cuando se toca, al centro de la meseta y a medio camino del óptimo
        nuevo, nunca de golpe.
      </div>
    </div>
  );
}
