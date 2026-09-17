"use client";

// EV por PRECIO de entrada (17-sep, Jaume): el EV de la estrategia (media,
// por trade, de lo que se movió el PRECIO a favor desde la entrada, en % del
// precio de entrada, antes de comisiones y de locates) y cómo cambia con el
// precio de la acción.
//
// EL MOVIMIENTO ES EL CAMINO DEL PRECIO TRAS LA SEÑAL: del fill de la ENTRADA
// (no del precio medio con las pirámides: con añadidos en % del equity sobre
// una base fija en $, la media dependía del capital y el EV cambiaba de signo
// entre «fijo» y «%») al precio medio de TODAS las salidas ponderado por
// acciones (no la última pierna: con un parcial a buen precio y el resto a
// EOD peor salía «negativo» en trades ganadores). Así no depende de cuánto
// dinero se mete. Misma definición que `locates_gate.movimiento_pct` del
// backend, que es la que usa la puerta por EV.
//
// Dos vistas: barras finas de 0,5 $ (hasta 20 $ y «> 20») para ver la forma,
// y la tabla con los seis tramos de la puerta «EV fijo por rango» y del
// cuadro de mandos, que son los números que se copian.

import React, { useMemo, useState } from "react";
import type { TradeRecord } from "@/lib/api_backtester";
import { RANGOS_PRECIO_EV, etiquetaRango, indiceRango } from "@/lib/evRangos";
import InfoTooltip from "@/components/backtester/InfoTooltip";

const f2 = (x: number) => x.toFixed(2).replace(".", ",");
const f1 = (x: number) => x.toFixed(1).replace(".", ",");

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

/** Movimiento del precio a favor desde el fill de la entrada hasta el precio
 *  medio de salida, en % del precio de entrada. Bruto e independiente del
 *  capital. */
export function movimientoPct(t: TradeRecord): number | null {
  const ent = Number(t.entry_price || t.avg_entry_price || 0);
  const sal = precioSalidaMedio(t);
  if (!(ent > 0) || !(sal > 0)) return null;
  const largo = String(t.direction || "").toLowerCase().startsWith("l");
  return ((largo ? sal - ent : ent - sal) / ent) * 100;
}

const PASO = 0.5;      // $ por barra
const TECHO = 20;      // la última barra es «> 20 $»
const N_FINAS = TECHO / PASO + 1;

const media = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

export default function EvPorPrecio({ trades }: { trades: TradeRecord[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const datos = useMemo(() => {
    const finas = Array.from({ length: N_FINAS }, () => [] as number[]);
    const tramos = RANGOS_PRECIO_EV.map(() => [] as number[]);
    const todos: number[] = [];
    for (const t of trades) {
      const m = movimientoPct(t);
      if (m == null) continue;
      // El tramo es el del precio de ENTRADA (el fill), como el que mira la puerta.
      const ent = Number(t.entry_price || t.avg_entry_price || 0);
      const k = Math.min(N_FINAS - 1, Math.floor(ent / PASO));
      finas[k].push(m);
      tramos[indiceRango(ent)].push(m);
      todos.push(m);
    }
    return {
      total: { n: todos.length, ev: media(todos) },
      finas: finas.map((xs, k) => ({ lo: k * PASO, n: xs.length, ev: media(xs) })),
      tramos: RANGOS_PRECIO_EV.map(([lo, hi], k) => ({ lo, hi, n: tramos[k].length, ev: media(tramos[k]) })),
    };
  }, [trades]);

  const maxAbs = Math.max(0.5, ...datos.finas.map((b) => Math.abs(b.ev ?? 0)));
  // La línea del cero reparte el alto según haga falta arriba y abajo.
  const maxPos = Math.max(0, ...datos.finas.map((b) => b.ev ?? 0));
  const maxNeg = Math.max(0, ...datos.finas.map((b) => -(b.ev ?? 0)));
  const fracPos = maxPos + maxNeg > 0 ? Math.max(0.25, Math.min(0.85, maxPos / (maxPos + maxNeg))) : 0.6;

  const etiquetaFina = (lo: number) => (lo >= TECHO ? `> ${TECHO}` : String(lo).replace(".", ","));
  const hov = hover != null ? datos.finas[hover] : null;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 flex items-center gap-2">
        <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-8 inline-flex items-center gap-1">
          EV por precio
          <InfoTooltip
            position="left"
            width={360}
            text="<b>EV de la estrategia</b> = media, por trade, de lo que se movió el PRECIO a favor desde la entrada, en % del precio de entrada: del fill de la entrada al precio medio de todas las salidas (parciales incluidas, ponderado por acciones). Es el camino del precio tras la señal: bruto (sin comisiones ni locates) e independiente de cuánto dinero se mete o de las pirámides. Es lo que se enfrenta al «fade necesario» del locate. <b>Barras</b>: el mismo EV por tramos de 0,5 $ del precio de entrada, para ver la forma; pasa el ratón para leer cada barra (las claras tienen menos de 20 trades: ruido). <b>Tabla</b>: los seis tramos de la puerta «EV fijo por rango» (Costes opcionales → Puerta por EV → Fijo → Por rango) y del cuadro de mandos: son los números que se copian ahí."
          />
        </span>
        <span className="ml-auto mr-3 text-[10px] font-mono text-[var(--color-ec-text-secondary)]">
          EV {datos.total.ev == null ? "—" : `${f2(datos.total.ev)} %`}
          {" · "}{datos.total.n} trades
        </span>
      </div>

      <div className="flex-1 min-h-0 px-3 pb-2" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 250px", gap: 18 }}>
        {/* Barras finas: divs, no SVG estirado (el texto no se deforma). */}
        <div className="flex flex-col min-w-0 h-full">
          <div className="text-[9.5px] font-mono h-[14px]" style={{ color: "var(--color-ec-text-muted)" }}>
            {hov
              ? <>{etiquetaFina(hov.lo)}{hov.lo < TECHO ? ` – ${etiquetaFina(hov.lo + PASO)}` : ""} $ · EV {hov.ev == null ? "—" : `${f2(hov.ev)} %`} · n {hov.n}</>
              : <>por tramos de {f1(PASO)} $ · escala ±{f1(maxAbs)} %</>}
          </div>
          <div className="flex-1 min-h-0 relative" style={{ borderLeft: "1px solid var(--color-ec-border)" }}>
            {/* línea del cero */}
            <div style={{ position: "absolute", left: 0, right: 0, top: `${fracPos * 100}%`, borderTop: "1px solid var(--color-ec-border)" }} />
            <div className="flex h-full items-stretch" style={{ gap: 1 }}>
              {datos.finas.map((b, k) => {
                const v = b.ev ?? 0;
                const hPct = (Math.abs(v) / maxAbs) * (v >= 0 ? fracPos : 1 - fracPos) * 100;
                const color = b.ev == null ? "transparent" : v >= 0 ? "var(--color-ec-copper)" : "var(--color-ec-loss)";
                return (
                  <div key={k} className="flex-1 min-w-0 relative" onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}
                       title={`${etiquetaFina(b.lo)}${b.lo < TECHO ? ` – ${etiquetaFina(b.lo + PASO)}` : ""} $ · EV ${b.ev == null ? "—" : f2(b.ev) + " %"} · n ${b.n}`}>
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

        {/* La tabla con los seis tramos de la puerta: los números que se copian. */}
        <div className="flex flex-col justify-center">
          <table className="w-full text-[10.5px] font-mono" style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "var(--color-ec-text-muted)" }}>
                <th className="text-left font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }}>TRAMO</th>
                <th className="text-right font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }}>EV</th>
                <th className="text-right font-semibold pb-1" style={{ fontSize: 9.5, letterSpacing: "0.08em" }}>N</th>
              </tr>
            </thead>
            <tbody>
              {datos.tramos.map((t, k) => (
                <tr key={k} style={{ borderTop: "1px solid var(--color-ec-border)", color: t.n < 20 ? "var(--color-ec-text-muted)" : "var(--color-ec-text-primary)" }}
                    title={t.n < 20 ? "Menos de 20 trades: ruido" : undefined}>
                  <td className="py-[3px]">{etiquetaRango(t.lo, t.hi)}</td>
                  <td className="py-[3px] text-right" style={{ color: t.ev == null ? undefined : t.ev >= 0 ? "var(--color-ec-copper-bright)" : "var(--color-ec-loss)" }}>
                    {t.ev == null ? "—" : `${f2(t.ev)} %`}
                  </td>
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
