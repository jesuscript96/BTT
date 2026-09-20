"use client";

// Paso 3 · «Caminos de la simulación según los locates» (20-sep-2026, tarde).
// Jaume: «como no sabemos cómo van a evolucionar los locates y los costes,
// un Monte Carlo de la simulación con semillas distintas, para ver los
// distintos caminos del equity según distintos rangos de locates, y saber si
// lo que voy ganando está entre esas bandas».
//
// Cada camino es la simulación ENTERA con otra semilla del sorteo (cambia el
// precio de cada acción-día y, con la puerta, qué cortos entran), para uno o
// varios rangos de precios. La curva real (CSV del paso 5) se pinta encima en
// el paso 5.

import React, { useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawCaminosOut, RawOut } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Sec, Stat, colorSerie, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";

export interface CaminosModel {
  out: RawOut;
  caminos: RawCaminosOut | null;
  running: boolean;
  error: string | null;
  seeds: number;
  setSeeds: (v: number) => void;
  /** Rangos extra a probar además del del paso 1: [[lo, hi], ...]. */
  rangosExtra: Array<[number, number]>;
  setRangosExtra: (v: Array<[number, number]>) => void;
  calcular: () => void;
  /** El rango cuya banda se pinta (lo lleva el padre, que coloca el grafico). */
  sel: number;
  setSel: (k: number) => void;
}

const numChico: React.CSSProperties = { height: 24, fontSize: 11, padding: "2px 5px", textAlign: "right" };
const lbl: React.CSSProperties = { fontSize: 10.5, fontFamily: font.sans, color: color.textMuted };

export function CaminosLocates({ m }: { m: CaminosModel }) {
  const { out, caminos, running, error, seeds, setSeeds, rangosExtra, setRangosExtra, calcular, sel, setSel } = m;
  const loc = out.config.locates;
  const aleatorios = !!loc && loc.mode === "random";
  const [nuevoLo, setNuevoLo] = useState(0.3);
  const [nuevoHi, setNuevoHi] = useState(15);
  const rango = caminos?.rangos[Math.min(sel, (caminos?.rangos.length ?? 1) - 1)] ?? null;

  return (
    <Sec
      title="Caminos de la simulación según los locates"
      help={
        <>
          El precio de los locates es lo que menos sabes del futuro. Aquí se corre la simulación del paso 1 <strong>entera N
          veces</strong>, cada vez con otra semilla del sorteo de locates (otro precio para cada acción-día; con la puerta por EV, eso
          cambia también qué cortos entran). Salen N caminos de equity y sus percentiles: la banda p05–p95 es «entre esto y esto
          habría acabado el portfolio según la suerte con los locates». Con varios rangos de precios (p. ej. el 1–10 $ del paso 1 y el
          0,3–15 $ del bróker real) ves cuánto depende el resultado del rango que te toque.
          <br /><br />
          <strong>Para qué:</strong> en el paso 5, tu curva real se pinta encima de estas bandas (en el tramo que coincide): si va por
          dentro, lo que ganas es lo que dice la simulación con tus locates; si va por debajo de la p05, o los locates te salen más
          caros que el rango, o hay algo más (slippage, fills). Cada camino es una simulación completa, así que N = 30 tarda unos 20 s
          por rango con tres estrategias.
        </>
      }
      right={
        <>
          <span style={lbl}>N =</span>
          <div style={{ width: 64 }}><Num value={seeds} onChange={(v) => setSeeds(Math.max(2, Math.min(200, Math.round(Number(v) || 2))))} min={2} max={200} step={10} style={numChico} /></div>
          <span style={lbl}>semillas</span>
          <Btn primary onClick={calcular} disabled={running || !aleatorios}>{running ? "Simulando…" : caminos ? "Volver a simular" : "Simular caminos"}</Btn>
        </>
      }
    >
      {!aleatorios && <Nota tone="warning">Necesita los locates <strong>aleatorios</strong> del paso 1: es el precio sorteado lo que cambia de un camino a otro.</Nota>}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
        <span style={lbl}>Rangos: <strong style={{ color: color.textHigh }}>{loc ? `${n(loc.min ?? 1, 2)}–${n(loc.max ?? 10, 2)} $ (paso 1)` : "—"}</strong></span>
        {rangosExtra.map(([lo, hi], k) => (
          <span key={k} style={{ ...lbl, display: "inline-flex", alignItems: "center", gap: 4, border: `1px solid ${color.border}`, padding: "1px 6px" }}>
            {n(lo, 2)}–{n(hi, 2)} $ <button type="button" onClick={() => setRangosExtra(rangosExtra.filter((_, j) => j !== k))} style={{ background: "transparent", border: "none", color: color.textMuted, cursor: "pointer", padding: 0 }}>✕</button>
          </span>
        ))}
        <span style={lbl}>añadir</span>
        <div style={{ width: 60 }}><Num value={nuevoLo} onChange={(v) => setNuevoLo(Math.max(0, Number(v) || 0))} min={0} step={0.1} style={numChico} /></div>
        <span style={lbl}>–</span>
        <div style={{ width: 60 }}><Num value={nuevoHi} onChange={(v) => setNuevoHi(Math.max(0, Number(v) || 0))} min={0} step={1} style={numChico} /></div>
        <Btn onClick={() => { if (nuevoHi > nuevoLo && rangosExtra.length < 5) setRangosExtra([...rangosExtra, [nuevoLo, nuevoHi]]); }}>+ rango</Btn>
        <span style={lbl}>(0,3–15 $ es lo medido en un mes de locates reales del socio)</span>
      </div>
      {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
      {!caminos && !error && aleatorios && <Nota>Pulsa <strong>Simular caminos</strong>: {n(seeds, 0)} simulaciones completas por rango.</Nota>}
      {caminos && rango && (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
            <thead>
              <tr>
                <th style={thL}>Rango de locates</th>
                <th style={thR}>Final p05</th>
                <th style={thR}>Final p50</th>
                <th style={thR}>Final p95</th>
                <th style={thR}>DD p05 (peor)</th>
                <th style={thR}>DD p50</th>
                <th style={thR}>Locates p50</th>
                <th style={thR}>Trades p50</th>
              </tr>
            </thead>
            <tbody>
              {caminos.rangos.map((r, k) => (
                <tr key={`${r.lo}-${r.hi}`} onClick={() => setSel(k)} style={{ cursor: "pointer", background: k === sel ? "rgba(184, 115, 51, 0.08)" : undefined }}>
                  <td style={{ ...tdTxt, fontWeight: k === sel ? 700 : 500 }}>{n(r.lo, 2)}–{n(r.hi, 2)} $ · {n(r.seeds, 0)} caminos</td>
                  <td style={tdNum}>{usd(r.final.p05)}</td>
                  <td style={{ ...tdNum, fontWeight: 700 }}>{usd(r.final.p50)}</td>
                  <td style={tdNum}>{usd(r.final.p95)}</td>
                  <td style={{ ...tdNum, color: color.loss }}>{pct(r.max_dd_pct.p05)}</td>
                  <td style={{ ...tdNum, color: color.loss }}>{pct(r.max_dd_pct.p50)}</td>
                  <td style={tdNum}>{usdCorto(r.cost.p50)}</td>
                  <td style={tdNum}>{n(r.trades.p50, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", flexWrap: "wrap", marginTop: 6 }}>
            <Stat label={`Final · rango ${n(rango.lo, 2)}–${n(rango.hi, 2)} $`} value={usd(rango.final.p50)} sub={`p05 ${usdCorto(rango.final.p05)} · p95 ${usdCorto(rango.final.p95)} · tu semilla ${usdCorto(out.equity[out.equity.length - 1])}`} />
            <Stat label="Caída máxima" value={pct(rango.max_dd_pct.p50)} sub={`peor camino ${pct(rango.max_dd_pct.p05)} · mejor ${pct(rango.max_dd_pct.p95)}`} tone="loss" />
            <Stat label="Locates" value={usd(rango.cost.p50)} sub={`p05 ${usdCorto(rango.cost.p05)} · p95 ${usdCorto(rango.cost.p95)}`} tone="loss" />
          </div>
          <p style={{ ...lbl, margin: "4px 0 0", lineHeight: 1.5 }}>
            Banda estrecha: el precio de los locates no decide el resultado. Ancha: la estrategia vive del precio que le toque. Pulsa otra fila para ver su banda en el gráfico de abajo.
          </p>
        </>
      )}
    </Sec>
  );
}

/** Las series del gráfico de caminos: banda p05–p95, mediana y la semilla del paso 1, en % del capital. */
export function seriesCaminos(caminos: RawCaminosOut, rangoIdx: number, out: RawOut) {
  const rango = caminos.rangos[Math.min(rangoIdx, caminos.rangos.length - 1)];
  if (!rango) return null;
  const cap = out.config.capital;
  const toPct = (v: number) => ((v - cap) / cap) * 100;
  return {
    rango,
    series: [
      { name: "mediana", color: color.textSecondary, width: 1.4, values: rango.bands.p50.map(toPct) },
      { name: "tu semilla", color: color.copper, width: 2.2, values: out.equity.map(toPct) },
    ],
    band: { lo: rango.bands.p05.map(toPct), hi: rango.bands.p95.map(toPct), color: color.info, name: "p05 … p95" },
  };
}

/** La curva real (fecha → equity) sobre las bandas de la simulación, en el
 *  tramo que coincide, las dos re-basadas a 0 % el primer día real. */
export function realSobreCaminos(caminos: RawCaminosOut, rangoIdx: number, real: Array<{ date: string; equity: number }>) {
  const r = caminos.rangos[rangoIdx];
  if (!r || !real.length) return null;
  const idx = new Map(caminos.calendar.map((d, i) => [d, i] as [string, number]));
  const comunes = real.filter((p) => idx.has(p.date));
  if (comunes.length < 2) return null;
  const d0 = comunes[0].date;
  const i0 = idx.get(d0)!;
  const base = { p05: r.bands.p05[i0], p50: r.bands.p50[i0], p95: r.bands.p95[i0] };
  const realBase = comunes[0].equity;
  const labels = comunes.map((p) => p.date);
  const toPct = (v: number, b: number) => (b > 0 ? (v / b - 1) * 100 : 0);
  return {
    labels,
    series: [
      { name: "mediana de la simulación", color: color.textSecondary, width: 1.4, values: comunes.map((p) => toPct(r.bands.p50[idx.get(p.date)!], base.p50)) },
      { name: "tu cuenta real", color: color.copper, width: 2.4, values: comunes.map((p) => toPct(p.equity, realBase)) },
    ],
    band: { lo: comunes.map((p) => toPct(r.bands.p05[idx.get(p.date)!], base.p05)), hi: comunes.map((p) => toPct(r.bands.p95[idx.get(p.date)!], base.p95)), color: color.info, name: "p05 … p95 de la simulación" },
    dias: comunes.length,
    desde: d0,
    hasta: comunes[comunes.length - 1].date,
    colorReal: colorSerie(0),
  };
}
