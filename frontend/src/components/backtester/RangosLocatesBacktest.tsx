"use client";

// Locates por RANGOS con EV fijo, en el Backtester (17-sep, Jaume): la misma
// estrategia y los mismos parametros de la corrida abierta, vuelta a correr
// con varios rangos de locates aleatorios, cada uno sin puerta y con la
// puerta por EV fijo. Aqui cada fila es un BACKTEST ENTERO (la puerta cambia
// los trades, asi que no vale recalcular la factura como hace la banda): los
// lanza uno detras de otro y espera. «No te preocupes por el coste» (Jaume).
//
// «EV fijo» es un modo de la puerta desde el 17-sep (`ev_gate_by: "fijo"`):
// siempre se compara ese EV con el fade. Aqui va el completo; el «por rango»
// se usa desde el panel de costes opcionales.

import React, { useRef, useState } from "react";
import { color, font } from "@/components/ui";
import { fetchBacktestJobStatus, fetchBacktestResult, startBacktestWithDefinition, type BacktestResult } from "@/lib/api_backtester";
import CalendarTab from "@/components/backtester/tabs/CalendarTab";

const num: React.CSSProperties = { fontFamily: font.mono, fontVariantNumeric: "tabular-nums" };
const f1 = (x: number) => x.toFixed(1).replace(".", ",");
const f2 = (x: number) => x.toFixed(2).replace(".", ",");
const usd = (x: number) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ".") + " $";
const th: React.CSSProperties = { textAlign: "right", padding: "5px 8px", fontSize: 9.5, fontWeight: 700, letterSpacing: "0.8px", textTransform: "uppercase", color: color.textMuted, borderBottom: `1px solid ${color.border}`, whiteSpace: "nowrap" };
const thL: React.CSSProperties = { ...th, textAlign: "left" };
const td: React.CSSProperties = { ...num, textAlign: "right", padding: "4px 8px", fontSize: 11.5, borderBottom: `0.5px solid ${color.border}`, color: color.textPrimary, whiteSpace: "nowrap" };
const tdL: React.CSSProperties = { ...td, textAlign: "left", fontFamily: font.sans };
const control: React.CSSProperties = { background: color.bgSidebar, border: `1px solid ${color.border}`, color: color.textHigh, fontFamily: font.mono, fontSize: 12, padding: "4px 7px", height: 28, outline: "none" };

/** «1-3, 1-5, 1-10, 2-20» -> [[1,3],[1,5],[1,10],[2,20]]. */
function parseRangos(txt: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (const parte of txt.split(/[,;]/)) {
    const m = parte.trim().match(/^(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)$/);
    if (!m) continue;
    const a = Number(m[1].replace(",", ".")), b = Number(m[2].replace(",", "."));
    if (Number.isFinite(a) && Number.isFinite(b) && b > a) out.push([a, b]);
  }
  return out;
}

interface Fila { min: number; max: number; puerta: boolean; result: BacktestResult; jobId: string }

function esperar(ms: number) { return new Promise((r) => setTimeout(r, ms)); }

async function correrYEsperar(peticion: Record<string, unknown>, sigo: () => boolean, onProgreso: (p: number) => void): Promise<{ result: BacktestResult; jobId: string }> {
  const { job_id } = await startBacktestWithDefinition(peticion as Parameters<typeof startBacktestWithDefinition>[0]);
  let faltantes = 0;
  for (;;) {
    if (!sigo()) throw new Error("Parado por el usuario");
    await esperar(1000);
    try {
      const s = await fetchBacktestJobStatus(job_id);
      faltantes = 0;
      onProgreso(Number(s.percent) || 0);
      if (s.status === "succeeded") break;
      if (s.status === "failed" || s.status === "cancelled") throw new Error(s.error || `backtest ${s.status}`);
    } catch (e) {
      // El registro de jobs vive en memoria: una racha de 404 = backend reiniciado.
      if (e instanceof Error && /404/.test(e.message) && ++faltantes < 6) continue;
      throw e;
    }
  }
  const result = await fetchBacktestResult(job_id);
  return { result, jobId: job_id };
}

export default function RangosLocatesBacktest({ peticion, initCash, riskR, riskType, monthlyExpenses }: {
  /** La peticion con la que se lanzo la corrida abierta (definicion + parametros). */
  peticion: Record<string, unknown> | null;
  initCash: number;
  riskR: number;
  riskType?: string;
  monthlyExpenses: number;
}) {
  const [txt, setTxt] = useState("1-3, 1-5, 1-10, 2-20");
  const [ev, setEv] = useState(3);
  const [seed, setSeed] = useState<number>(Number(peticion?.locates_seed) || 1);
  const [conSinPuerta, setConSinPuerta] = useState(true);
  const [filas, setFilas] = useState<Fila[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [estado, setEstado] = useState<{ txt: string; pct: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Ref y no estado: el bucle de `lanzar` es una closure y no veria el cambio.
  const pararRef = useRef(false);
  const [parando, setParando] = useState(false);
  const rangos = parseRangos(txt);

  const lanzar = async () => {
    if (!peticion || !rangos.length || estado) return;
    setError(null);
    setSel(null);
    pararRef.current = false;
    setParando(false);
    const acc: Fila[] = [];
    setFilas([]);
    let seguir = true;
    const sigo = () => true;
    try {
      let k = 0;
      const total = rangos.length * (conSinPuerta ? 2 : 1);
      for (const [mn, mx] of rangos) {
        for (const puerta of conSinPuerta ? [false, true] : [true]) {
          k += 1;
          const etq = `${f1(mn)}–${f1(mx)} $ ${puerta ? `con EV fijo ${f1(ev)} %` : "sin puerta"} (${k} de ${total})`;
          setEstado({ txt: etq, pct: 0 });
          const req: Record<string, unknown> = {
            ...peticion,
            locates_cost: 0,
            locates_random: true,
            locates_random_min: mn,
            locates_random_max: mx,
            locates_seed: seed,
            ev_gate_enabled: puerta,
            ev_gate_by: "fijo",
            ev_gate_fixed_pct: ev,
            ev_gate_ranges: [],
            ev_gate_default_pct: ev,
            ev_gate_min_trades: 10,
            ev_gate_window: 30,
          };
          const { result, jobId } = await correrYEsperar(req, sigo, (p) => setEstado({ txt: etq, pct: p }));
          acc.push({ min: mn, max: mx, puerta, result, jobId });
          setFilas([...acc]);
          if (pararRef.current) { seguir = false; break; }
        }
        if (!seguir) break;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo correr");
    } finally {
      setEstado(null);
      setParando(false);
    }
  };

  const filaSel = sel != null ? filas[sel] : null;
  const locatesPagados = (r: BacktestResult) => r.trades.reduce((a, t) => a + (Number(t.pnl ?? 0) - Number((t as unknown as { pnl_with_locates?: number }).pnl_with_locates ?? t.pnl ?? 0)), 0);

  return (
    <div style={{ marginTop: 18, border: `1px solid ${color.border}`, background: color.bgSurface }}>
      <div style={{ padding: "8px 14px", borderBottom: `1px solid ${color.border}`, background: color.bgElevated }}>
        <div style={{ fontSize: 10.5, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted }}>
          <span style={{ color: color.copperBright }}>3 · </span>Locates por rangos con EV fijo
        </div>
        <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 2, lineHeight: 1.5 }}>
          La misma estrategia y parámetros de esta corrida, vuelta a correr con varios rangos de locates aleatorios (misma semilla para todos: solo cambia el rango), cada uno sin puerta y con la puerta por EV fijo (el corto entra si ese EV supera su fade necesario). Cada fila es un backtest entero y se lanzan uno detrás de otro: tarda. Pon el EV que midas en IS y, con el periodo en OOS, verás qué tal se sostiene. Pulsa una fila para ver su calendario.
        </div>
      </div>
      <div style={{ padding: "10px 14px" }}>
        {!peticion ? (
          <div style={{ fontSize: 11.5, color: color.textMuted }}>Corre primero un backtest desde este panel: los rangos se lanzan con su misma petición.</div>
        ) : (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 10.5, color: color.textMuted }}>rangos ($ por paquete)</span>
            <input value={txt} onChange={(e) => setTxt(e.target.value)} style={{ ...control, width: 260 }} />
            <span style={{ fontSize: 10.5, color: color.textMuted }}>EV fijo</span>
            <input type="number" value={ev} min={0} step={0.5} onChange={(e) => setEv(Number(e.target.value) || 0)} style={{ ...control, width: 64, textAlign: "right" }} />
            <span style={{ fontSize: 10.5, color: color.textMuted }}>% · semilla</span>
            <input type="number" value={seed} min={0} step={1} onChange={(e) => setSeed(Math.round(Number(e.target.value) || 0))} style={{ ...control, width: 60, textAlign: "right" }} />
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: color.textPrimary, cursor: "pointer" }}>
              <input type="checkbox" checked={conSinPuerta} onChange={(e) => setConSinPuerta(e.target.checked)} style={{ margin: 0, accentColor: "var(--color-ec-copper)" }} />
              también sin puerta
            </label>
            {!estado ? (
              <button type="button" onClick={lanzar} disabled={!rangos.length} style={{ background: color.copper, color: "#1A0A00", border: `1px solid ${color.copper}`, padding: "5px 12px", fontSize: 11.5, fontWeight: 600, cursor: rangos.length ? "pointer" : "not-allowed", opacity: rangos.length ? 1 : 0.5, height: 28 }}>
                Correr {rangos.length * (conSinPuerta ? 2 : 1)} backtests
              </button>
            ) : (
              <>
                <span style={{ fontSize: 11, color: color.textHigh }}>{estado.txt} · {f1(estado.pct)} %</span>
                <button type="button" onClick={() => { pararRef.current = true; setParando(true); }} disabled={parando} style={{ background: "transparent", color: color.loss, border: `1px solid ${color.loss}`, padding: "5px 12px", fontSize: 11.5, cursor: "pointer", height: 28, opacity: parando ? 0.5 : 1 }}>{parando ? "parando tras este…" : "parar tras este"}</button>
              </>
            )}
          </div>
        )}
        {error && <div style={{ marginTop: 8, fontSize: 11.5, color: color.loss }}>{error}</div>}
        {filas.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
            <thead>
              <tr>
                <th style={thL}>Rango</th>
                <th style={thL}>Puerta</th>
                <th style={th}>PnL neto</th>
                <th style={th}>Retorno</th>
                <th style={th}>Max DD</th>
                <th style={th}>PF</th>
                <th style={th}>Trades</th>
                <th style={th} title="Veredictos negativos de la puerta: uno por VELA con señal mientras el corto sigue vetado, no uno por trade">Vetos</th>
                <th style={th}>Locates</th>
                <th style={th}>$/paq. mediana</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((f, i) => {
                const m = f.result.aggregate_metrics;
                const on = sel === i;
                const loc = locatesPagados(f.result);
                return (
                  <tr key={f.jobId} onClick={() => setSel(on ? null : i)} style={{ cursor: "pointer", background: on ? color.bgElevated : undefined }}>
                    <td style={{ ...tdL, fontFamily: font.mono, color: on ? color.copperBright : color.textHigh }}>{f1(f.min)} – {f1(f.max)} $</td>
                    <td style={{ ...tdL, color: f.puerta ? color.textHigh : color.textMuted }}>{f.puerta ? `EV fijo ${f1(ev)} %` : "sin puerta"}</td>
                    <td style={{ ...td, color: m.total_pnl >= 0 ? color.profit : color.loss, fontWeight: 600 }}>{usd(m.total_pnl)}</td>
                    <td style={{ ...td, color: m.total_return_pct >= 0 ? color.profit : color.loss }}>{f1(m.total_return_pct)} %</td>
                    <td style={{ ...td, color: color.loss }}>{f1(m.max_drawdown_pct)} %</td>
                    <td style={td}>{f2(m.avg_profit_factor)}</td>
                    <td style={td}>{m.total_trades}</td>
                    <td style={{ ...td, color: (f.result.ev_gate?.rechazadas || 0) > 0 ? color.warning : color.textMuted }}>{f.result.ev_gate?.rechazadas ?? 0}</td>
                    <td style={{ ...td, color: color.textMuted }}>{usd(-Math.abs(loc))}</td>
                    <td style={{ ...td, color: color.textMuted }}>{f.result.locates_random?.p50 != null ? `${f2(f.result.locates_random.p50)} $` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {filas.length > 0 && !filaSel && <div style={{ marginTop: 6, fontSize: 11, color: color.textSecondary }}>Pulsa una fila para ver su calendario. «Vetos»: veredictos negativos de la puerta, uno por vela con señal (una misma señal vetada suma uno cada vela que sigue viva), no uno por trade. «Locates»: lo pagado (PnL − PnL con locates de cada trade).</div>}
        {filaSel && (
          <div style={{ marginTop: 10, borderTop: `1px solid ${color.border}`, paddingTop: 8 }}>
            <div style={{ fontSize: 11, color: color.textSecondary, marginBottom: 6 }}>
              Calendario de <b style={{ color: color.textHigh }}>{f1(filaSel.min)} – {f1(filaSel.max)} $ {filaSel.puerta ? `con EV fijo ${f1(ev)} %` : "sin puerta"}</b>.
            </div>
            <CalendarTab
              dayResults={filaSel.result.day_results || []}
              trades={filaSel.result.trades || []}
              monthlyExpenses={monthlyExpenses}
              riskR={riskR}
              riskType={riskType}
              globalEquity={filaSel.result.global_equity || []}
              initCash={initCash}
            />
          </div>
        )}
      </div>
    </div>
  );
}
