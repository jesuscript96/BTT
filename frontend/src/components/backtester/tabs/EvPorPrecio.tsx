"use client";

// EV por rango de PRECIO de entrada (17-sep, Jaume): el EV de la estrategia
// (media del movimiento a favor en % del precio, antes de locates) y un
// grafico de barras con el mismo EV por tramo de precio — los tramos del
// «EV por rango» de la puerta (lib/evRangos = locates_gate.RANGOS_PRECIO_EV).
// Jaume anota estos valores y los pone en «Costes opcionales → Puerta por
// EV → Fijo → Por rango» y en el cuadro de mandos del bot.

import React, { useMemo } from "react";
import type { TradeRecord } from "@/lib/api_backtester";
import { RANGOS_PRECIO_EV, etiquetaRango, indiceRango } from "@/lib/evRangos";
import InfoTooltip from "@/components/backtester/InfoTooltip";

const f2 = (x: number) => x.toFixed(2).replace(".", ",");

/** Movimiento a favor en % del precio: para un corto (entrada − salida)/entrada,
 *  para un largo (salida − entrada)/entrada. Con piramide manda el precio
 *  medio, como en `locates_gate.sombra_desde_trades`. */
function movimientoPct(t: TradeRecord): number | null {
  const ent = Number(t.avg_entry_price || t.entry_price || 0);
  const sal = Number(t.exit_price || 0);
  if (!(ent > 0) || !(sal > 0)) return null;
  const largo = String(t.direction || "").toLowerCase().startsWith("l");
  return ((largo ? sal - ent : ent - sal) / ent) * 100;
}

export default function EvPorPrecio({ trades }: { trades: TradeRecord[] }) {
  const datos = useMemo(() => {
    const porTramo = RANGOS_PRECIO_EV.map(() => [] as number[]);
    const todos: number[] = [];
    for (const t of trades) {
      const m = movimientoPct(t);
      if (m == null) continue;
      const ent = Number(t.avg_entry_price || t.entry_price || 0);
      porTramo[indiceRango(ent)].push(m);
      todos.push(m);
    }
    const media = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
    return {
      total: { n: todos.length, ev: media(todos) },
      tramos: RANGOS_PRECIO_EV.map(([lo, hi], k) => ({ lo, hi, n: porTramo[k].length, ev: media(porTramo[k]) })),
    };
  }, [trades]);

  const evs = datos.tramos.map((t) => t.ev ?? 0);
  const maxAbs = Math.max(1, ...evs.map((v) => Math.abs(v)));
  const W = 600, H = 190, padL = 46, padR = 10, padT = 18, padB = 30;
  const n = datos.tramos.length;
  const bw = (W - padL - padR) / n;
  const y0 = padT + (H - padT - padB) / 2;                // linea del 0 en medio
  const escala = (H - padT - padB) / 2 / maxAbs;
  const yDe = (v: number) => y0 - v * escala;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 flex items-center gap-2">
        <span className="text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-[0.12em] ml-8 inline-flex items-center gap-1">
          EV por precio
          <InfoTooltip
            position="left"
            width={340}
            text="<b>EV de la estrategia</b> = media de lo que se mueve la acción a favor en cada trade, en % del precio de entrada (para un corto, entrada − salida sobre la entrada), antes de locates. Es el número que se enfrenta al «fade necesario» del locate. <b>Por precio</b>: el mismo EV pero solo con los trades cuya entrada cae en cada tramo de precio; una acción de 0,40 $ no se mueve como una de 8 $. Son los tramos del «EV por rango» de la puerta (Costes opcionales → Puerta por EV → Fijo → Por rango) y del cuadro de mandos: anota estos valores ahí. Con pocos trades en un tramo, el EV de ese tramo es ruido: mira la n."
          />
        </span>
        <span className="ml-auto mr-3 text-[10px] font-mono text-[var(--color-ec-text-secondary)]">
          EV {datos.total.ev == null ? "—" : `${f2(datos.total.ev)} %`} · {datos.total.n} trades
        </span>
      </div>
      <div className="flex-1 min-h-0 px-2">
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "100%" }} preserveAspectRatio="none">
          <line x1={padL} x2={W - padR} y1={y0} y2={y0} stroke="var(--color-ec-border)" strokeWidth={1} />
          {[maxAbs, -maxAbs].map((v) => (
            <text key={v} x={padL - 6} y={yDe(v) + 3.5} textAnchor="end" fontSize={9} fontFamily="var(--color-ec-mono)" fill="var(--color-ec-text-muted)">{f2(v)} %</text>
          ))}
          <text x={padL - 6} y={y0 + 3.5} textAnchor="end" fontSize={9} fontFamily="var(--color-ec-mono)" fill="var(--color-ec-text-muted)">0</text>
          {datos.tramos.map((t, k) => {
            const x = padL + k * bw + bw * 0.18;
            const w = bw * 0.64;
            const v = t.ev ?? 0;
            const yTop = Math.min(yDe(v), y0);
            const h = Math.max(1, Math.abs(yDe(v) - y0));
            const color = t.ev == null ? "var(--color-ec-border)" : v >= 0 ? "var(--color-ec-copper)" : "var(--color-ec-loss)";
            return (
              <g key={k}>
                <rect x={x} y={yTop} width={w} height={t.ev == null ? 1 : h} fill={color} opacity={t.n < 20 ? 0.45 : 0.9} />
                <text x={x + w / 2} y={v >= 0 ? yTop - 4 : yTop + h + 11} textAnchor="middle" fontSize={9.5} fontFamily="var(--color-ec-mono)" fill="var(--color-ec-text-primary)">
                  {t.ev == null ? "—" : `${f2(t.ev)} %`}
                </text>
                <text x={x + w / 2} y={H - padB + 12} textAnchor="middle" fontSize={9} fontFamily="var(--color-ec-mono)" fill="var(--color-ec-text-muted)">{etiquetaRango(t.lo, t.hi)}</text>
                <text x={x + w / 2} y={H - padB + 23} textAnchor="middle" fontSize={8.5} fontFamily="var(--color-ec-sans)" fill="var(--color-ec-text-muted)">n {t.n}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
