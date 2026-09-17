"use client";

// Locates por RANGOS con EV fijo (17-sep, Jaume): la misma cuenta del paso 1
// con varios rangos de locates aleatorios, cada uno sin puerta y con la
// puerta por EV fijo, para ver a partir de que precio deja de compensar. Cada
// fila es un calculo del motor crudo (0,3 s): exacto, con el alquiler
// compartido recalculado. Pulsar una fila abre su calendario.

import React, { useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawOut } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Sec, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { CalendarioCrudo } from "./CalendarioCrudo";
import { curvaPropia } from "./modelo";

export interface RangoFila {
  min: number;
  max: number;
  puerta: boolean;
  out: RawOut;
}

/** «1-3, 1-5, 1-10, 2-20» -> [[1,3],[1,5],[1,10],[2,20]]. */
export function parseRangos(txt: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (const parte of txt.split(/[,;]/)) {
    const m = parte.trim().match(/^(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)$/);
    if (!m) continue;
    const a = Number(m[1].replace(",", ".")), b = Number(m[2].replace(",", "."));
    if (Number.isFinite(a) && Number.isFinite(b) && b > a) out.push([a, b]);
  }
  return out;
}

export function RangosLocatesCrudo({ base, evInicial, seedInicial, correr }: {
  /** El resultado del paso 1 al que pertenecen las filas (si cambia, se vacían). */
  base: RawOut;
  evInicial: number;
  seedInicial: number;
  correr: (min: number, max: number, seed: number, evFijo: number | null) => Promise<RawOut>;
}) {
  const [txt, setTxt] = useState("1-3, 1-5, 1-10, 2-20");
  const [ev, setEv] = useState<number | "">(evInicial);
  const [seed, setSeed] = useState<number | "">(seedInicial);
  const [conSinPuerta, setConSinPuerta] = useState(true);
  const [filas, setFilas] = useState<{ de: RawOut; lista: RangoFila[] } | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [corriendo, setCorriendo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rangos = parseRangos(txt);
  const lista = filas && filas.de === base ? filas.lista : [];
  const cap = base.config.capital;

  const lanzar = async () => {
    if (!rangos.length || corriendo) return;
    setError(null);
    setSel(null);
    const acc: RangoFila[] = [];
    setFilas({ de: base, lista: acc });
    try {
      for (const [mn, mx] of rangos) {
        const variantes: Array<boolean> = conSinPuerta ? [false, true] : [true];
        for (const puerta of variantes) {
          setCorriendo(`${n(mn, 1)}–${n(mx, 1)} $ ${puerta ? "con EV fijo" : "sin puerta"}`);
          const o = await correr(mn, mx, Number(seed) || 1, puerta ? (Number(ev) || 0) : null);
          acc.push({ min: mn, max: mx, puerta, out: o });
          setFilas({ de: base, lista: [...acc] });
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo calcular");
    } finally {
      setCorriendo(null);
    }
  };

  const filaSel = sel != null ? lista[sel] : null;

  return (
    <Sec title="Locates por rangos — con EV fijo" help={
      <>
        La misma cuenta del paso 1 (estrategias, R, comisiones, tope, «una a la vez»), con varios <strong>rangos de
        locates aleatorios</strong> (mismo sorteo del Backtester, misma semilla para todos, así lo único que cambia es
        el rango) y, para cada rango, <strong>sin puerta</strong> y <strong>con la puerta por EV fijo</strong> (entra el
        corto si ese EV supera su fade necesario). Es exacto: cada fila es un cálculo del motor con el alquiler
        compartido recalculado. Pulsa una fila para ver su calendario. El EV fijo que pongas aquí es el que midas en IS;
        con el periodo del paso 1 en OOS ves qué tal se sostiene.
      </>
    }>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", padding: "6px 0" }}>
        <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>rangos ($ por paquete)</span>
        <input value={txt} onChange={(e) => setTxt(e.target.value)} style={{ background: color.bgSidebar, border: `1px solid ${color.border}`, color: color.textHigh, fontFamily: font.mono, fontSize: 12, padding: "4px 7px", width: 260, height: 28, outline: "none" }} />
        <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>EV fijo</span>
        <div style={{ width: 60 }}><Num value={ev} onChange={setEv} min={0} step={0.5} /></div>
        <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% · semilla</span>
        <div style={{ width: 56 }}><Num value={seed} onChange={setSeed} min={0} step={1} /></div>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer" }}>
          <input type="checkbox" checked={conSinPuerta} onChange={(e) => setConSinPuerta(e.target.checked)} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
          también sin puerta
        </label>
        <Btn primary onClick={lanzar} disabled={!rangos.length || !!corriendo}>{corriendo ? `Calculando ${corriendo}…` : `Calcular ${rangos.length} ${rangos.length === 1 ? "rango" : "rangos"}`}</Btn>
        {!rangos.length && <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.warning }}>escribe rangos como «1-3, 1-5, 1-10»</span>}
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
      {lista.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4 }}>
          <thead>
            <tr>
              <th style={thL}>Rango</th>
              <th style={thL}>Puerta</th>
              <th style={thR}>Neto</th>
              <th style={thR}>Retorno</th>
              <th style={thR}>Max DD</th>
              <th style={thR}>PF</th>
              <th style={thR}>Trades</th>
              <th style={thR}>Fuera</th>
              <th style={thR}>Locates</th>
              <th style={thR}>$/paq. medio</th>
              <th style={thR}>Equilibrio</th>
            </tr>
          </thead>
          <tbody>
            {lista.map((f, i) => {
              const o = f.out;
              const neto = o.equity[o.equity.length - 1] - o.config.capital;
              const dd = curvaPropia(o.daily_pnl, o.calendar.map(() => 1), o.config.capital).maxDd;
              const an = o.locates_analysis;
              const on = sel === i;
              return (
                <tr key={i} onClick={() => setSel(on ? null : i)} style={{ cursor: "pointer", background: on ? color.bgElevated : undefined }}>
                  <td style={{ ...tdTxt, fontFamily: font.mono, color: on ? color.copperText : color.textHigh }}>{n(f.min, 1)} – {n(f.max, 1)} $</td>
                  <td style={{ ...tdTxt, color: f.puerta ? color.textHigh : color.textMuted }}>{f.puerta ? `EV fijo ${n(Number(ev) || 0, 1)} %` : "sin puerta"}</td>
                  <td style={{ ...tdNum, color: neto >= 0 ? color.profit : color.loss, fontWeight: 600 }}>{usd(neto)}</td>
                  <td style={{ ...tdNum, color: o.metrics.total_return_pct >= 0 ? color.profit : color.loss }}>{pct(o.metrics.total_return_pct)}</td>
                  <td style={{ ...tdNum, color: color.loss }}>{pct(dd)}</td>
                  <td style={tdNum}>{n(o.metrics.profit_factor)}</td>
                  <td style={tdNum}>{n(o.metrics.n_trades, 0)}</td>
                  <td style={{ ...tdNum, color: (o.locates_report?.gate_out || 0) > 0 ? color.warning : color.textMuted }}>{n(o.locates_report?.gate_out || 0, 0)}</td>
                  <td style={{ ...tdNum, color: color.textMuted }}>{usd(o.costs.locates)}</td>
                  <td style={{ ...tdNum, color: color.textMuted }}>{an ? `${n(an.avg_price_paid, 2)} $` : "—"}</td>
                  <td style={{ ...tdNum, color: color.textMuted }}>{an ? `${n(an.breakeven_price, 2)} $` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {lista.length > 0 && !filaSel && <Nota>Pulsa una fila para ver su calendario. «Equilibrio»: el $ por paquete al que los cortos de esa fila se quedan a cero. Capital {usd(cap)}.</Nota>}
      {filaSel && (
        <div style={{ marginTop: 8, borderTop: `1px solid ${color.border}`, paddingTop: 8 }}>
          <Nota>Calendario de <strong>{n(filaSel.min, 1)} – {n(filaSel.max, 1)} $ {filaSel.puerta ? `con EV fijo ${n(Number(ev) || 0, 1)} %` : "sin puerta"}</strong>: Profits, Gastos y Profits − Gastos en $ o R; pulsa un día para ver sus trades.</Nota>
          <CalendarioCrudo out={filaSel.out} names={filaSel.out.per_strategy.map((p) => p.name)} />
        </div>
      )}
    </Sec>
  );
}
