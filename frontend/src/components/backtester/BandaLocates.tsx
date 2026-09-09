"use client";

// Banda de locates: «entre qué dos curvas voy a acabar según me toquen los
// locates». Monte Carlo sobre el precio del locate SIN volver a correr: con la
// corrida abierta se recalcula la factura para N semillas. Bloque aparte a
// propósito — la curva de equity de siempre no se toca.

import React, { useMemo, useState } from "react";
import type { BacktestResult, TradeRecord } from "@/lib/api_backtester";
import { color, font } from "@/components/ui";
import { Help } from "@/components/robustez/help";
import { pedirBandaLocates, type BandaLocates as Banda } from "@/lib/api_locates";
import { Histograma } from "@/components/backtester/tabs/edge/charts";

const num: React.CSSProperties = { fontFamily: font.mono, fontVariantNumeric: "tabular-nums" };
const f2 = (x: number) => x.toFixed(2).replace(".", ",");
const f1 = (x: number) => x.toFixed(1).replace(".", ",");
const usd = (x: number) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ".") + " $";

function Cifra({ k, v, s, tono, ultima, chico }: { k: string; v: React.ReactNode; s?: string; tono?: string; ultima?: boolean; chico?: boolean }) {
  return (
    <div style={{ flex: 1, padding: "0 14px", minWidth: 0, borderRight: ultima ? undefined : `0.5px solid ${color.border}` }}>
      <div style={{ fontSize: 10, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted }}>{k}</div>
      <div style={{ ...num, fontSize: chico ? 15 : 18, lineHeight: 1.25, color: tono || color.textHigh, marginTop: 3, overflowWrap: "anywhere" }}>{v}</div>
      {s && <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 1 }}>{s}</div>}
    </div>
  );
}

const inp: React.CSSProperties = {
  width: 64, height: 26, boxSizing: "border-box", padding: "0 7px", background: color.bgElevated,
  border: `1px solid ${color.border}`, fontFamily: font.mono, fontSize: 11.5, color: color.textPrimary,
  outline: "none", textAlign: "right",
};

/* ---- el abanico ---- */
function Abanico({ b, initCash, conBruta }: { b: Banda; initCash: number; conBruta: boolean }) {
  const W = 1100, H = 320, L = 64, R = 20, Tp = 22, B = 40;
  const n = b.fechas.length;
  if (n < 2) return null;
  const todos = [...b.curvas.min, ...b.curvas.max, ...(conBruta ? b.curvas.bruta : []), ...(b.actual?.curva ?? []), initCash];
  const lo0 = Math.min(...todos), hi0 = Math.max(...todos);
  const pad = (hi0 - lo0) * 0.06 || 1;
  const lo = lo0 - pad, hi = hi0 + pad;
  const X = (i: number) => L + (i / (n - 1)) * (W - L - R);
  const Y = (v: number) => H - B - ((v - lo) / (hi - lo)) * (H - B - Tp);
  const path = (xs: number[]) => "M" + xs.map((v, i) => `${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" L ");
  const area = "M" + b.curvas.p90.map((v, i) => `${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" L ")
    + " L " + b.curvas.p10.map((v, i) => `${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).reverse().join(" L ") + " Z";
  const ticksY = [0, 0.25, 0.5, 0.75, 1].map((k) => lo + (hi - lo) * k);
  const anios = new Map<string, number>();
  b.fechas.forEach((f, i) => { const a = f.slice(0, 4); if (!anios.has(a)) anios.set(a, i); });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" style={{ display: "block", width: "100%", height: "auto", fontFamily: font.sans }}>
      {ticksY.map((v, i) => (
        <React.Fragment key={i}>
          <line x1={L} y1={Y(v)} x2={W - R} y2={Y(v)} stroke={color.border} strokeWidth={1} strokeDasharray="2 3" />
          <text x={L - 8} y={Y(v) + 3.5} fill={color.textSecondary} fontSize={10} textAnchor="end" style={num}>
            {Math.round(v).toLocaleString("de-DE")}
          </text>
        </React.Fragment>
      ))}
      <line x1={L} y1={Y(initCash)} x2={W - R} y2={Y(initCash)} stroke={color.textMuted} strokeWidth={1} />
      {[...anios.entries()].map(([a, i]) => (
        <React.Fragment key={a}>
          <line x1={X(i)} y1={Tp} x2={X(i)} y2={H - B} stroke={color.border} strokeWidth={1} />
          <text x={X(i) + 3} y={H - B + 15} fill={color.textMuted} fontSize={10} textAnchor="start" style={num}>{a}</text>
        </React.Fragment>
      ))}
      <path d={area} fill={color.copper} opacity={0.16} />
      <path d={path(b.curvas.min)} fill="none" stroke={color.loss} strokeWidth={1} opacity={0.6} />
      <path d={path(b.curvas.max)} fill="none" stroke={color.profit} strokeWidth={1} opacity={0.6} />
      {conBruta && <path d={path(b.curvas.bruta)} fill="none" stroke={color.textMuted} strokeWidth={1.2} strokeDasharray="4 3" />}
      <path d={path(b.curvas.p50)} fill="none" stroke={color.copper} strokeWidth={2.2} strokeLinejoin="round" />
      {b.actual && <path d={path(b.actual.curva)} fill="none" stroke={color.textHigh} strokeWidth={1.4} strokeLinejoin="round" />}
      <text x={L + (W - L - R) / 2} y={H - 6} fill={color.textMuted} fontSize={10.5} textAnchor="middle">
        equity neta de locates (bruta de gastos fijos) · banda p10–p90 sobre {b.n_semillas} semillas
      </text>
    </svg>
  );
}

/* ---- el bloque ---- */
export default function BandaLocates({ result, initCash, backtestParams }: {
  result: BacktestResult; initCash: number; backtestParams?: Record<string, unknown>;
}) {
  const rnd = result.locates_random;
  const conPuerta = !!result.ev_gate;
  // El rango CONFIGURADO sale de los parametros de la corrida; `locates_random`
  // solo trae el resumen de lo sorteado (su min es el minimo observado, no el
  // del rango) y con el la factura no cuadra con la del motor.
  const num0 = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
  const [minimo, setMinimo] = useState<number>(num0(backtestParams?.locates_random_min) ?? rnd?.min ?? 1);
  const [maximo, setMaximo] = useState<number>(num0(backtestParams?.locates_random_max) ?? rnd?.max ?? 10);
  const [nSem, setNSem] = useState(50);
  const [base, setBase] = useState(1);
  const [banda, setBanda] = useState<Banda | null>(null);
  const [conBruta, setConBruta] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cortos = useMemo(() => result.trades.filter((t) => !String(t.direction).toLowerCase().startsWith("l")).length, [result.trades]);

  const calcular = () => {
    setCargando(true); setError(null);
    pedirBandaLocates(result.trades as TradeRecord[], initCash, minimo, maximo, nSem, base, rnd?.seed ?? null)
      .then(setBanda)
      .catch((e) => setError(e?.message || "No se pudo calcular la banda"))
      .finally(() => setCargando(false));
  };

  // Histograma de la peor caída por semilla, con la de la semilla actual marcada.
  const histDD = useMemo(() => {
    if (!banda) return null;
    const xs = [...banda.max_dd_pct].sort((a, b) => a - b);
    const min = xs[0], max = xs[xs.length - 1], nb = 24, ancho = (max - min) / nb || 1;
    const hist = Array.from({ length: nb }, (_, i) => ({ c: min + ancho * (i + 0.5), n: 0 }));
    for (const x of xs) hist[Math.min(nb - 1, Math.max(0, Math.floor((x - min) / ancho)))].n += 1;
    return hist;
  }, [banda]);

  const r = banda?.resumen;
  return (
    <div style={{
      marginTop: 14, background: color.bgSurface, border: `1px solid ${color.border}`,
      fontFamily: font.sans, color: color.textPrimary,
    }}>
      <div style={{ background: color.bgElevated, borderBottom: `1px solid ${color.border}`, padding: "8px 13px", display: "flex", alignItems: "center", gap: 9 }}>
        <h3 style={{ margin: 0, flex: 1, fontSize: 12, fontWeight: 600, color: color.textHigh }}>
          Banda de locates: entre qué dos curvas puedes acabar
        </h3>
        <Help title="Banda de locates" width={520}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11.5, lineHeight: 1.45 }}>
            <div><b style={{ color: color.textHigh }}>Qué estás viendo. </b><span style={{ color: color.textSecondary }}>Un Monte Carlo sobre el precio de los locates. Se toma la corrida que tienes abierta y se le vuelven a poner precio a los locates {"N"} veces, cada vez con una semilla distinta (otro «mundo» de precios, dentro del rango que pongas). Sale una curva de equity por semilla; el abanico es lo que queda entre la mejor y la peor. Sin volver a correr nada: cambiar de semilla no cambia ningún trade, solo lo que cuesta cada día.</span></div>
            <div style={{ borderLeft: `2px solid ${color.copper}`, paddingLeft: 8 }}><b style={{ color: color.copperBright }}>Por ejemplo: </b>si la mediana acaba en +1.900 $ y la banda va de +1.200 a +2.600, tu resultado depende de la suerte con los locates en unos ±700 $. Si la línea blanca (tu semilla) está pegada al borde de arriba, te ha tocado un mundo bueno y no cuentes con repetirlo.</div>
            <div><b style={{ color: color.textHigh }}>Para qué sirve. </b><span style={{ color: color.textSecondary }}>Para no decidir con UNA corrida: la media puede ser idéntica y el peor caso no parecerse en nada. Mira el peor drawdown de todas las semillas, no el de la tuya.</span></div>
            <div style={{ borderTop: `1px solid ${color.border}`, paddingTop: 6 }}>
              <div style={{ fontSize: "0.82em", letterSpacing: "0.1em", textTransform: "uppercase", color: color.textMuted, marginBottom: 2 }}>Cómo leerlo</div>
              <div><b style={{ color: color.copperBright }}>Banda estrecha</b><span style={{ color: color.textSecondary }}> · los locates no te cambian la vida; el riesgo está en otra parte.</span></div>
              <div><b style={{ color: color.copperBright }}>Banda ancha y la mediana cerca de la bruta</b><span style={{ color: color.textSecondary }}> · pagas poco de media pero algunos días te destrozan: mira el histograma de caídas.</span></div>
              <div><b style={{ color: color.copperBright }}>La mediana muy por debajo de la bruta</b><span style={{ color: color.textSecondary }}> · los locates se comen el edge de forma sistemática. O reduces paquetes (tope de locates) o filtras con la puerta por EV.</span></div>
              <div><b style={{ color: color.copperBright }}>Tu semilla en el borde</b><span style={{ color: color.textSecondary }}> · lo que has visto en la corrida no es lo típico; fíate de la mediana.</span></div>
            </div>
            <div style={{ color: color.warning, fontSize: "0.92em" }}>Ojo: con la puerta por EV activa esto es una aproximación, porque con otra semilla la puerta habría dejado entrar otros trades. Aquí se mantienen los trades de tu corrida y solo se mueve el precio.</div>
          </div>
        </Help>
      </div>

      <div style={{ padding: 13 }}>
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: color.textMuted }}>
            Rango $/paquete
            <input type="number" step="0.1" min={0} value={minimo} style={inp} onChange={(e) => setMinimo(Math.max(0, Number(e.target.value) || 0))} />
            <span>a</span>
            <input type="number" step="0.1" min={0} value={maximo} style={inp} onChange={(e) => setMaximo(Math.max(0, Number(e.target.value) || 0))} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: color.textMuted }}>
            Semillas
            <input type="number" step="1" min={1} max={200} value={nSem} style={inp} onChange={(e) => setNSem(Math.max(1, Math.min(200, Math.floor(Number(e.target.value) || 1))))} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: color.textMuted }}>
            desde la
            <input type="number" step="1" min={0} value={base} style={inp} onChange={(e) => setBase(Math.max(0, Math.floor(Number(e.target.value) || 0)))} />
          </label>
          <button onClick={calcular} disabled={cargando || maximo <= minimo || cortos === 0}
            style={{
              background: cargando ? color.bgElevated : color.copper,
              color: cargando ? color.textMuted : "var(--color-ec-copper-text)",
              border: `1px solid ${color.border}`, fontFamily: font.sans, fontSize: 12, fontWeight: 600,
              letterSpacing: "0.04em", height: 30, padding: "0 16px", cursor: cargando ? "wait" : "pointer",
            }}>
            {cargando ? "CALCULANDO…" : "CALCULAR LA BANDA"}
          </button>
          <span style={{ fontSize: 11, color: color.textMuted }}>
            {cortos === 0 ? "no hay cortos: los locates no aplican"
              : rnd ? `esta corrida se hizo con la semilla ${rnd.seed}; sorteos entre ${f2(rnd.min)} y ${f2(rnd.max)} $ (media ${f2(rnd.media ?? 0)})`
                : "esta corrida no llevaba locates aleatorios: la referencia de precio es la entrada"}
          </span>
          {error && <span style={{ fontSize: 11.5, color: color.loss }}>{error}</span>}
        </div>

        {banda && r && (
          <>
            {conPuerta && (
              <div style={{ marginTop: 10, fontSize: 11.5, color: color.warning }}>
                Aproximación: la corrida lleva la puerta por EV y con otra semilla habría dejado entrar otros trades. Aquí se mantienen los tuyos y solo cambia el precio.
              </div>
            )}
            <div style={{ marginTop: 12 }}>
              <Abanico b={banda} initCash={initCash} conBruta={conBruta} />
            </div>
            <div style={{ display: "flex", gap: 15, flexWrap: "wrap", marginTop: 8, fontSize: 11, fontFamily: font.mono, color: color.textSecondary }}>
              <span><i style={{ display: "inline-block", width: 14, height: 8, background: color.copper, opacity: 0.3, verticalAlign: "middle" }} /> p10–p90</span>
              <span><i style={{ display: "inline-block", width: 14, height: 2, background: color.copper, verticalAlign: "middle" }} /> mediana</span>
              <span><i style={{ display: "inline-block", width: 14, height: 2, background: color.textHigh, verticalAlign: "middle" }} /> tu semilla</span>
              <span><i style={{ display: "inline-block", width: 14, height: 1, background: color.profit, verticalAlign: "middle" }} /> mejor · <i style={{ display: "inline-block", width: 14, height: 1, background: color.loss, verticalAlign: "middle" }} /> peor</span>
              <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
                <input type="checkbox" checked={conBruta} onChange={(e) => setConBruta(e.target.checked)} style={{ margin: 0 }} />
                <i style={{ display: "inline-block", width: 14, height: 0, borderTop: `1.5px dashed ${color.textMuted}`, verticalAlign: "middle" }} /> ver la curva sin locates (aplasta la banda si el edge bruto es grande)
              </label>
            </div>

            <div style={{ display: "flex", borderTop: `0.5px solid ${color.border}`, marginTop: 12, paddingTop: 12 }}>
              <Cifra k="Acabas entre" v={<>{usd(r.final_p10)}<br />y {usd(r.final_p90)}</>} s="8 de cada 10 semillas" chico />
              <Cifra k="Mediana" v={usd(r.final_p50)} s={`sin locates ${usd(r.bruta_final)}`} />
              <Cifra k="Peor semilla" v={usd(r.final_min)} s={`mejor ${usd(r.final_max)}`} tono={color.loss} />
              <Cifra k="Peor caída" v={`${f1(r.dd_peor)} %`} s={`mediana ${f1(r.dd_mediana)} %`} tono={color.warning} />
              <Cifra k="Factura media" v={`−${Math.round(r.factura_media).toLocaleString("de-DE")} $`}
                     s={`${banda.ticker_dias_con_locate} ticker-días con locate`} ultima={!banda.actual} />
              {banda.actual && (
                <Cifra k={`Tu semilla (${banda.actual.semilla})`} v={usd(banda.actual.final)}
                       s={`percentil ${f1(banda.actual.percentil_final)} · caída ${f1(banda.actual.max_dd_pct)} %`} ultima />
              )}
            </div>

            {histDD && (
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 14, alignItems: "start" }}>
                <div>
                  <div style={{ fontSize: 10.5, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted, marginBottom: 6 }}>
                    Peor caída por semilla
                  </div>
                  <Histograma hist={histDD} actual={banda.actual?.max_dd_pct ?? r.dd_mediana} p95={r.dd_p95} unidad="%"
                              pie={`peor caída en % de cada una de las ${banda.n_semillas} semillas`} />
                </div>
                <div style={{ fontSize: 12, color: color.textSecondary, lineHeight: 1.55, paddingTop: 22 }}>
                  {(() => {
                    const ancho = r.final_p90 - r.final_p10;
                    const rel = r.bruta_final !== 0 ? Math.abs(ancho / r.bruta_final) * 100 : 0;
                    return (
                      <>
                        <p style={{ margin: "0 0 8px" }}>
                          La suerte con los locates mueve el resultado en <b style={{ color: color.textHigh }}>{usd(ancho).replace("+", "")}</b>
                          {r.bruta_final !== 0 && <> (un {f1(rel)} % del resultado sin locates)</>}.
                          {rel < 10 ? " Es poco: qué semilla te toque apenas cambia el resultado; lo que pesa es cuánto cuestan de media, no la suerte." : rel < 40 ? " Es relevante: no juzgues esta estrategia por una sola corrida." : " Es enorme: el resultado depende más de la suerte con los locates que de la estrategia."}
                        </p>
                        <p style={{ margin: 0 }}>
                          Los locates se llevan de media <b style={{ color: color.textHigh }}>{r.bruta_final !== 0 ? f1(Math.abs(r.factura_media / r.bruta_final) * 100) : "—"} %</b> de
                          lo que gana la estrategia sin ellos. La peor caída de todas las semillas es <b style={{ color: color.warning }}>{f1(r.dd_peor)} %</b>:
                          ese es el número con el que dimensionar la cuenta, no el de tu corrida.
                        </p>
                      </>
                    );
                  })()}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
