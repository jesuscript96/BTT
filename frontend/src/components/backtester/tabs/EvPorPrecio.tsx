"use client";

// EV · MFE medio · Fade medio por PRECIO de entrada (17-sep, Jaume): las tres
// medidas de la estrategia que se pueden enfrentar al fade necesario del
// locate, y cómo cambian con el precio de la acción.
//
// Las tres son % del precio de ENTRADA (el fill, no el precio medio con las
// pirámides), brutas (sin comisiones ni locates) e independientes del capital:
//   EV    = lo que se movió el precio a favor desde la entrada hasta el precio
//           medio de TODAS las salidas (parciales incluidos, ponderado por
//           acciones). Media por trade = WR × ganancia media − (1 − WR) ×
//           pérdida media, en unidades de fade.
//   MFE   = lo MÁXIMO que se movió el precio a favor desde la entrada hasta la
//           salida final (el `mfe` que ya mide el simulador).
//   Fade  = lo que se movió el precio a favor desde la entrada hasta la salida
//           FINAL (la última pierna: con tres parciales, el tercero).
// Misma definición que `locates_gate.metrica_trade` del backend, que es la
// que usa la puerta.
//
// Dos vistas: barras finas de 0,5 $ (hasta 20 $ y «> 20») de la medida
// elegida, y la tabla con las tres medidas por los seis tramos de la puerta
// «por rango» y del cuadro de mandos, que son los números que se copian.

import React, { useMemo, useState } from "react";
import type { TradeRecord } from "@/lib/api_backtester";
import { RANGOS_PRECIO_EV, etiquetaRango, indiceRango } from "@/lib/evRangos";
import InfoTooltip from "@/components/backtester/InfoTooltip";

const f2 = (x: number) => x.toFixed(2).replace(".", ",");
const f1 = (x: number) => x.toFixed(1).replace(".", ",");

export type MetricaPuerta = "ev" | "mfe" | "fade";
export const METRICA_LABEL: Record<MetricaPuerta, string> = { ev: "EV", mfe: "MFE", fade: "Fade" };

/** Precio medio de salida ponderado por acciones (piernas exit / reduce /
 *  lot_stop de `executions`); sin ellas, `exit_price`. */
function precioSalidaMedio(t: TradeRecord): number {
  let num = 0, den = 0;
  for (const e of t.executions || []) {
    if (e.kind !== "exit" && e.kind !== "reduce" && e.kind !== "lot_stop") continue;
    const sz = Number(e.size || 0), px = Number(e.price || 0);
    if (sz > 0 && px > 0) { num += sz * px; den += sz; }
  }
  return den > 0 ? num / den : Number(t.exit_price || 0);
}

const precioEntrada = (t: TradeRecord) => Number(t.entry_price || t.avg_entry_price || 0);
const esLargo = (t: TradeRecord) => String(t.direction || "").toLowerCase().startsWith("l");
const aFavor = (t: TradeRecord, ent: number, sal: number) => ((esLargo(t) ? sal - ent : ent - sal) / ent) * 100;

/** EV: del fill de la entrada al precio medio de salida. */
export function movimientoPct(t: TradeRecord): number | null {
  const ent = precioEntrada(t), sal = precioSalidaMedio(t);
  if (!(ent > 0) || !(sal > 0)) return null;
  return aFavor(t, ent, sal);
}

/** Fade: del fill de la entrada a la salida FINAL. */
export function fadeSalidaPct(t: TradeRecord): number | null {
  const ent = precioEntrada(t), sal = Number(t.exit_price || 0);
  if (!(ent > 0) || !(sal > 0)) return null;
  return aFavor(t, ent, sal);
}

/** MFE: lo máximo a favor, que ya mide el simulador. */
export function mfePct(t: TradeRecord): number | null {
  const v = t.mfe;
  return v == null || !Number.isFinite(Number(v)) ? null : Number(v);
}

export function metricaTrade(t: TradeRecord, m: MetricaPuerta): number | null {
  return m === "mfe" ? mfePct(t) : m === "fade" ? fadeSalidaPct(t) : movimientoPct(t);
}

const PASO = 0.5;      // $ por barra
const TECHO = 20;      // la última barra es «> 20 $»
const N_FINAS = TECHO / PASO + 1;
const METRICAS: MetricaPuerta[] = ["ev", "mfe", "fade"];

const media = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

export default function EvPorPrecio({ trades }: { trades: TradeRecord[] }) {
  const [metrica, setMetrica] = useState<MetricaPuerta>("ev");
  const [hover, setHover] = useState<number | null>(null);

  const datos = useMemo(() => {
    const vacio = () => ({ ev: [] as number[], mfe: [] as number[], fade: [] as number[], precio: [] as number[] });
    const finas = Array.from({ length: N_FINAS }, vacio);
    const tramos = RANGOS_PRECIO_EV.map(vacio);
    const todos = vacio();
    for (const t of trades) {
      const ent = precioEntrada(t);
      if (!(ent > 0)) continue;
      // El tramo es el del precio de ENTRADA (el fill), como el que mira la puerta.
      const k = Math.min(N_FINAS - 1, Math.floor(ent / PASO));
      const r = indiceRango(ent);
      for (const m of METRICAS) {
        const v = metricaTrade(t, m);
        if (v == null) continue;
        finas[k][m].push(v);
        tramos[r][m].push(v);
        todos[m].push(v);
      }
      if (movimientoPct(t) != null) { finas[k].precio.push(ent); tramos[r].precio.push(ent); todos.precio.push(ent); }
    }
    // LOCATE MÁXIMO ($ por paquete de 100) que el EV del tramo aguanta: el
    // locate cuesta precio_paquete / 100 por acción y el EV da EV % × precio
    // por acción; se paga si EV % × precio ≥ precio_paquete / 100, o sea
    // precio_paquete ≤ EV (%) × precio de la acción ($). Con el precio medio de
    // entrada de los trades del tramo. Es la puerta hecha regla de bolsillo.
    const resumen = (b: ReturnType<typeof vacio>) => {
      const ev = media(b.ev), precio = media(b.precio);
      return { n: b.ev.length, ev, mfe: media(b.mfe), fade: media(b.fade), precio, locMax: ev != null && precio != null && ev > 0 ? ev * precio : null };
    };
    return {
      total: resumen(todos),
      finas: finas.map((b, k) => ({ lo: k * PASO, ...resumen(b) })),
      tramos: RANGOS_PRECIO_EV.map(([lo, hi], k) => ({ lo, hi, ...resumen(tramos[k]) })),
    };
  }, [trades]);

  const valor = (b: { ev: number | null; mfe: number | null; fade: number | null }) => b[metrica];
  const maxAbs = Math.max(0.5, ...datos.finas.map((b) => Math.abs(valor(b) ?? 0)));
  // La línea del cero reparte el alto según haga falta arriba y abajo.
  const maxPos = Math.max(0, ...datos.finas.map((b) => valor(b) ?? 0));
  const maxNeg = Math.max(0, ...datos.finas.map((b) => -(valor(b) ?? 0)));
  const fracPos = maxPos + maxNeg > 0 ? Math.max(0.25, Math.min(0.85, maxPos / (maxPos + maxNeg))) : 0.6;

  const etiquetaFina = (lo: number) => (lo >= TECHO ? `> ${TECHO}` : String(lo).replace(".", ","));
  const hov = hover != null ? datos.finas[hover] : null;
  const pct = (v: number | null) => (v == null ? "—" : `${f2(v)} %`);
  // CAPTURA = EV / MFE: que parte del recorrido disponible se llevan las
  // salidas (17-sep, Jaume). Bajo = el problema son las salidas, no los locates.
  const captura = (b: { ev: number | null; mfe: number | null }) => (b.ev == null || b.mfe == null || !(b.mfe > 0) ? null : (b.ev / b.mfe) * 100);
  const pct0 = (v: number | null) => (v == null ? "—" : `${v.toFixed(0)} %`);
  const colorDe = (v: number | null) => (v == null ? undefined : v >= 0 ? "var(--color-ec-copper-bright)" : "var(--color-ec-loss)");

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 flex items-center gap-2">
        <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-8 inline-flex items-center gap-1">
          EV · MFE · Fade por precio
          <InfoTooltip
            position="left"
            width={380}
            text="Las tres medidas de la estrategia que se pueden enfrentar al «fade necesario» del locate (Costes opcionales → Puerta por EV/MFE/Fade). Todas en % del precio de ENTRADA (el fill, no el precio medio con las pirámides), brutas y sin que el capital las mueva; por trade, contando el trade entero (parciales incluidos). <b>EV</b>: media de lo que se movió el precio a favor desde la entrada hasta el precio medio de todas las salidas = WR × ganancia media − (1 − WR) × pérdida media, en unidades de fade. <b>MFE medio</b>: media de lo máximo que se movió a favor desde la entrada hasta la salida final. <b>Fade medio</b>: media de lo que se movió a favor desde la entrada hasta la salida FINAL (la última pierna). <b>Captura</b> = EV / MFE: qué parte del recorrido que hubo se llevan tus salidas; si es baja, el problema son las salidas, no los locates. <b>Locate máx.</b> = EV (%) × precio de la acción: el precio por paquete de 100 a partir del cual el locate se come el EV (el locate cuesta precio del paquete / 100 por acción); con el precio medio de entrada del tramo, y sin margen por comisiones ni por el redondeo a paquetes enteros. <b>Barras</b>: la medida elegida por tramos de 0,5 $ del precio de entrada; pasa el ratón para leer cada barra (las claras tienen menos de 20 trades: ruido). <b>Tabla</b>: las tres medidas en los seis tramos de la puerta «por rango» y del cuadro de mandos: son los números que se copian ahí."
          />
        </span>
        <div style={{ display: 'flex', border: '1px solid var(--color-ec-border)', marginLeft: 10 }}>
          {METRICAS.map((m, i) => (
            <button
              key={m}
              type="button"
              onClick={() => setMetrica(m)}
              style={{
                background: metrica === m ? 'var(--color-ec-copper)' : 'var(--color-ec-bg-base)',
                color: metrica === m ? 'var(--color-ec-copper-text)' : 'var(--color-ec-text-secondary)',
                fontWeight: metrica === m ? 600 : 400,
                border: 0, borderLeft: i ? '1px solid var(--color-ec-border)' : undefined,
                fontFamily: 'var(--color-ec-sans)', fontSize: 10, height: 20, padding: '0 8px', cursor: 'pointer',
              }}
            >
              {METRICA_LABEL[m]}
            </button>
          ))}
        </div>
        <span className="ml-auto mr-3 text-[10px] font-mono text-[var(--color-ec-text-secondary)]">
          EV {pct(datos.total.ev)} · MFE {pct(datos.total.mfe)} · Fade {pct(datos.total.fade)} · <span title="Captura = EV / MFE: qué parte del recorrido disponible se llevan tus salidas">captura {pct0(captura(datos.total))}</span> · <span title="Locate máximo que el EV aguanta = EV (%) × precio de la acción, en $ por paquete de 100 (con el precio medio de entrada de la corrida)">locate máx. {datos.total.locMax == null ? "—" : `${f2(datos.total.locMax)} $/paq.`}</span> · {datos.total.n} trades
        </span>
      </div>

      <div className="flex-1 min-h-0 px-3 pb-2" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 440px", gap: 18 }}>
        {/* Barras finas: divs, no SVG estirado (el texto no se deforma). */}
        <div className="flex flex-col min-w-0 h-full">
          <div className="text-[9.5px] font-mono h-[14px]" style={{ color: "var(--color-ec-text-muted)" }}>
            {hov
              ? <>{etiquetaFina(hov.lo)}{hov.lo < TECHO ? ` – ${etiquetaFina(hov.lo + PASO)}` : ""} $ · {METRICA_LABEL[metrica]} {pct(valor(hov))} · n {hov.n}</>
              : <>{METRICA_LABEL[metrica]} por tramos de {f1(PASO)} $ · escala ±{f1(maxAbs)} %</>}
          </div>
          <div className="flex-1 min-h-0 relative" style={{ borderLeft: "1px solid var(--color-ec-border)" }}>
            {/* línea del cero */}
            <div style={{ position: "absolute", left: 0, right: 0, top: `${fracPos * 100}%`, borderTop: "1px solid var(--color-ec-border)" }} />
            <div className="flex h-full items-stretch" style={{ gap: 1 }}>
              {datos.finas.map((b, k) => {
                const vb = valor(b);
                const v = vb ?? 0;
                const hPct = (Math.abs(v) / maxAbs) * (v >= 0 ? fracPos : 1 - fracPos) * 100;
                const color = vb == null ? "transparent" : v >= 0 ? "var(--color-ec-copper)" : "var(--color-ec-loss)";
                return (
                  <div key={k} className="flex-1 min-w-0 relative" onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}
                       title={`${etiquetaFina(b.lo)}${b.lo < TECHO ? ` – ${etiquetaFina(b.lo + PASO)}` : ""} $ · EV ${pct(b.ev)} · MFE ${pct(b.mfe)} · Fade ${pct(b.fade)} · locate máx. ${b.locMax == null ? "—" : f2(b.locMax) + " $/paq."} · n ${b.n}`}>
                    <div style={{
                      position: "absolute", left: 0, right: 0,
                      ...(v >= 0 ? { bottom: `${(1 - fracPos) * 100}%`, height: `${hPct}%` } : { top: `${fracPos * 100}%`, height: `${hPct}%` }),
                      background: color, opacity: hover === k ? 1 : b.n < 20 ? 0.4 : 0.85,
                    }} />
                  </div>
                );
              })}
            </div>
          </div>
          {/* eje X: una etiqueta cada 2 $ (no se solapan ni a 600 px) */}
          <div className="flex h-[14px] text-[9px] font-mono" style={{ color: "var(--color-ec-text-muted)" }}>
            {datos.finas.map((b, k) => (
              <div key={k} className="flex-1 min-w-0 text-left" style={{ overflow: "visible", whiteSpace: "nowrap" }}>
                {k % 4 === 0 ? (b.lo >= TECHO ? `>${TECHO}` : `${b.lo} $`) : ""}
              </div>
            ))}
          </div>
        </div>

        {/* La tabla con las tres medidas en los seis tramos de la puerta: los números que se copian. */}
        <div className="flex flex-col justify-center">
          <table className="w-full text-[10.5px] font-mono" style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "var(--color-ec-text-muted)" }}>
                <th className="text-left font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }}>TRAMO</th>
                {METRICAS.map((m) => (
                  <th key={m} className="text-right font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: metrica === m ? "var(--color-ec-text-primary)" : undefined }}>
                    {m === "ev" ? "EV" : m === "mfe" ? "MFE" : "FADE"}
                  </th>
                ))}
                <th className="text-right font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }} title="Captura = EV / MFE: qué parte del recorrido disponible se llevan tus salidas">CAPT.</th>
                <th className="text-right font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }} title="Locate máximo que el EV del tramo aguanta, en $ por paquete de 100 = EV (%) × precio medio de entrada del tramo">LOC. MÁX.</th>
                <th className="text-right font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }}>N</th>
              </tr>
            </thead>
            <tbody>
              {datos.tramos.map((t, k) => (
                <tr key={k} style={{ borderTop: "1px solid var(--color-ec-border)", color: t.n < 20 ? "var(--color-ec-text-muted)" : "var(--color-ec-text-primary)" }}
                    title={t.n < 20 ? "Menos de 20 trades: ruido" : undefined}>
                  <td className="py-[3px]">{etiquetaRango(t.lo, t.hi)}</td>
                  {METRICAS.map((m) => (
                    <td key={m} className="py-[3px] text-right" style={{ color: colorDe(t[m]), fontWeight: metrica === m ? 600 : 400 }}>{pct(t[m])}</td>
                  ))}
                  <td className="py-[3px] text-right" style={{ color: "var(--color-ec-text-muted)" }}>{pct0(captura(t))}</td>
                  <td className="py-[3px] text-right" style={{ color: t.locMax == null ? undefined : "var(--color-ec-text-primary)" }}>{t.locMax == null ? "—" : `${f2(t.locMax)} $`}</td>
                  <td className="py-[3px] text-right">{t.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-1 text-[9.5px]" style={{ color: "var(--color-ec-text-muted)" }}>los tramos de la puerta «por rango» y del cuadro de mandos</div>
        </div>
      </div>
    </div>
  );
}
