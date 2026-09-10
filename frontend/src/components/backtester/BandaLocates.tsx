"use client";

// Banda de locates: «entre qué dos curvas voy a acabar según me toquen los
// locates». Monte Carlo sobre el precio del locate SIN volver a correr: con la
// corrida abierta se recalcula la factura para N semillas. Bloque aparte a
// propósito — la curva de equity de siempre no se toca.
//
// 10-sep: al lado, el BOOTSTRAP. La banda de la izquierda fija las operaciones
// y mueve el precio; la de la derecha mueve las dos cosas y contesta la
// pregunta de verdad: «¿ganaría igual con otro histórico?».

import React, { useMemo, useState } from "react";
import type { BacktestResult, TradeRecord } from "@/lib/api_backtester";
import { color, font } from "@/components/ui";
import { Help } from "@/components/robustez/help";
import { pedirBandaLocates, type BandaLocates as Banda, type BootstrapLocates } from "@/lib/api_locates";
import { Histograma } from "@/components/backtester/tabs/edge/charts";

const num: React.CSSProperties = { fontFamily: font.mono, fontVariantNumeric: "tabular-nums" };
const f2 = (x: number) => x.toFixed(2).replace(".", ",");
const f1 = (x: number) => x.toFixed(1).replace(".", ",");
const usd = (x: number) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ".") + " $";
// Para los ejes: con cifras de seis dígitos el texto se come el gráfico.
const usdK = (x: number) => {
  const a = Math.abs(x), s = x < 0 ? "−" : "";
  if (a >= 1e6) return s + (a / 1e6).toFixed(1).replace(".", ",") + "M";
  if (a >= 1e3) return s + Math.round(a / 1e3) + "k";
  return s + Math.round(a);
};

function Cifra({ k, v, s, tono, ultima, chico }: { k: string; v: React.ReactNode; s?: string; tono?: string; ultima?: boolean; chico?: boolean }) {
  return (
    <div style={{ flex: 1, padding: "0 14px", minWidth: 0, borderRight: ultima ? undefined : `0.5px solid ${color.border}` }}>
      <div style={{ fontSize: 10, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted }}>{k}</div>
      <div style={{ ...num, fontSize: chico ? 15 : 18, lineHeight: 1.25, color: tono || color.textHigh, marginTop: 3, overflowWrap: "anywhere" }}>{v}</div>
      {s && <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 1 }}>{s}</div>}
    </div>
  );
}

function Titulo({ n, t, s }: { n: string; t: string; s: string }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 10.5, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted }}>
        <span style={{ color: color.copperBright }}>{n} · </span>{t}
      </div>
      <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 1 }}>{s}</div>
    </div>
  );
}

const inp: React.CSSProperties = {
  width: 64, height: 26, boxSizing: "border-box", padding: "0 7px", background: color.bgElevated,
  border: `1px solid ${color.border}`, fontFamily: font.mono, fontSize: 11.5, color: color.textPrimary,
  outline: "none", textAlign: "right",
};

// Los dos gráficos comparten caja para que se puedan comparar de un vistazo.
const W = 560, H = 300, L = 52, R = 14, Tp = 16, B = 36;

/* ---- el abanico de semillas: mismas operaciones, distinto precio ---- */
function Abanico({ b, initCash, conBruta }: { b: Banda; initCash: number; conBruta: boolean }) {
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
          <text x={L - 6} y={Y(v) + 3.5} fill={color.textSecondary} fontSize={9.5} textAnchor="end" style={num}>{usdK(v)}</text>
        </React.Fragment>
      ))}
      <line x1={L} y1={Y(initCash)} x2={W - R} y2={Y(initCash)} stroke={color.textMuted} strokeWidth={1} />
      {[...anios.entries()].map(([a, i]) => (
        <React.Fragment key={a}>
          <line x1={X(i)} y1={Tp} x2={X(i)} y2={H - B} stroke={color.border} strokeWidth={1} />
          <text x={X(i) + 3} y={H - B + 14} fill={color.textMuted} fontSize={9.5} textAnchor="start" style={num}>{a}</text>
        </React.Fragment>
      ))}
      <path d={area} fill={color.copper} opacity={0.16} />
      <path d={path(b.curvas.min)} fill="none" stroke={color.loss} strokeWidth={1} opacity={0.6} />
      <path d={path(b.curvas.max)} fill="none" stroke={color.profit} strokeWidth={1} opacity={0.6} />
      {conBruta && <path d={path(b.curvas.bruta)} fill="none" stroke={color.textMuted} strokeWidth={1.2} strokeDasharray="4 3" />}
      <path d={path(b.curvas.p50)} fill="none" stroke={color.copper} strokeWidth={2.2} strokeLinejoin="round" />
      {b.actual && <path d={path(b.actual.curva)} fill="none" stroke={color.textHigh} strokeWidth={1.4} strokeLinejoin="round" />}
      <text x={L + (W - L - R) / 2} y={H - 5} fill={color.textMuted} fontSize={10} textAnchor="middle">
        tu histórico real · banda p10–p90 sobre {b.n_semillas} semillas
      </text>
    </svg>
  );
}

/* ---- el abanico bootstrap: otro histórico cada vez ---- */
function AbanicoMC({ mc, initCash }: { mc: BootstrapLocates; initCash: number }) {
  const p = mc.pasos, n = p.length;
  if (n < 2) return null;
  const c = mc.curvas;
  const lo0 = Math.min(...c.p5, initCash), hi0 = Math.max(...c.p95, initCash);
  const pad = (hi0 - lo0) * 0.06 || 1;
  const lo = lo0 - pad, hi = hi0 + pad;
  const X = (i: number) => L + (p[i] / (mc.n_unidades - 1)) * (W - L - R);
  const Y = (v: number) => H - B - ((v - lo) / (hi - lo)) * (H - B - Tp);
  const path = (xs: number[]) => "M" + xs.map((v, i) => `${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" L ");
  const banda = (alto: number[], bajo: number[]) =>
    "M" + alto.map((v, i) => `${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" L ")
    + " L " + bajo.map((v, i) => `${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).reverse().join(" L ") + " Z";
  const ticksY = [0, 0.25, 0.5, 0.75, 1].map((k) => lo + (hi - lo) * k);
  const ticksX = [0, 0.25, 0.5, 0.75, 1].map((k) => Math.round(k * (mc.n_unidades - 1)));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" style={{ display: "block", width: "100%", height: "auto", fontFamily: font.sans }}>
      {ticksY.map((v, i) => (
        <React.Fragment key={i}>
          <line x1={L} y1={Y(v)} x2={W - R} y2={Y(v)} stroke={color.border} strokeWidth={1} strokeDasharray="2 3" />
          <text x={L - 6} y={Y(v) + 3.5} fill={color.textSecondary} fontSize={9.5} textAnchor="end" style={num}>{usdK(v)}</text>
        </React.Fragment>
      ))}
      {ticksX.map((v, i) => (
        <text key={i} x={L + (v / (mc.n_unidades - 1)) * (W - L - R)} y={H - B + 14}
              fill={color.textMuted} fontSize={9.5} textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"} style={num}>{v}</text>
      ))}
      <path d={banda(c.p95, c.p5)} fill={color.copper} opacity={0.13} />
      <path d={banda(c.p75, c.p25)} fill={color.copper} opacity={0.2} />
      {/* La línea del capital inicial es la frontera: por debajo, la réplica pierde. */}
      <line x1={L} y1={Y(initCash)} x2={W - R} y2={Y(initCash)} stroke={color.loss} strokeWidth={1} strokeDasharray="3 3" />
      <path d={path(c.p50)} fill="none" stroke={color.copper} strokeWidth={2.2} strokeLinejoin="round" />
      <text x={L + (W - L - R) / 2} y={H - 5} fill={color.textMuted} fontSize={10} textAnchor="middle">
        ticker-días simulados · {mc.n_replicas.toLocaleString("de-DE")} historias alternativas
      </text>
    </svg>
  );
}

/* ---- distribución del resultado final: cuánta masa cae por debajo de cero ---- */
function HistoResultados({ mc, real }: { mc: BootstrapLocates; real: number | null }) {
  const hW = 460, hh = 244, hL = 40, hR = 14, hT = 24, hB = 42;
  const hist = mc.hist;
  if (!hist.length) return null;
  const min = hist[0].c, max = hist[hist.length - 1].c;
  const span = max - min || 1;
  const paso = hist.length > 1 ? hist[1].c - hist[0].c : 1;
  const maxN = Math.max(...hist.map((h) => h.n)) || 1;
  const X = (v: number) => hL + ((v - min) / span) * (hW - hL - hR);
  const Y = (k: number) => hh - hB - (k / maxN) * (hh - hB - hT);
  const ancho = Math.max(1.5, ((hW - hL - hR) / hist.length) - 1.5);
  const marca = (v: number, col: string, txt: string, arriba: boolean) => (
    <>
      <line x1={X(v)} y1={arriba ? hT - 8 : hh - hB} x2={X(v)} y2={arriba ? hh - hB : hh - hB + 6} stroke={col} strokeWidth={1.2} strokeDasharray="3 2" />
      <text x={X(v)} y={arriba ? hT - 12 : hh - hB + 17} fill={col} fontSize={9.5} textAnchor="middle" style={num}>{txt}</text>
    </>
  );
  return (
    <svg viewBox={`0 0 ${hW} ${hh}`} role="img" style={{ display: "block", width: "100%", height: "auto", fontFamily: font.sans }}>
      {hist.map((h, i) => (
        <rect key={i} x={X(h.c) - ancho / 2} y={Y(h.n)} width={ancho} height={Math.max(0, hh - hB - Y(h.n))}
              fill={h.c + paso / 2 <= 0 ? color.loss : color.copper} opacity={h.c + paso / 2 <= 0 ? 0.55 : 0.45} />
      ))}
      <line x1={hL} y1={hh - hB} x2={hW - hR} y2={hh - hB} stroke={color.border} strokeWidth={1} />
      {min <= 0 && max >= 0 && (
        <>
          <line x1={X(0)} y1={hT - 8} x2={X(0)} y2={hh - hB} stroke={color.textHigh} strokeWidth={1.4} />
          <text x={X(0)} y={hT - 12} fill={color.textHigh} fontSize={10} textAnchor="middle" style={num}>0</text>
        </>
      )}
      {marca(mc.resumen.p5, color.warning, `p5 ${usdK(mc.resumen.p5)}`, false)}
      {real !== null && real >= min && real <= max && marca(real, color.textHigh, `tu corrida ${usdK(real)}`, false)}
      <text x={hL} y={hh - 6} fill={color.textMuted} fontSize={9.5} textAnchor="start" style={num}>{usdK(min)}</text>
      <text x={hW - hR} y={hh - 6} fill={color.textMuted} fontSize={9.5} textAnchor="end" style={num}>{usdK(max)}</text>
      <text x={hL + (hW - hL - hR) / 2} y={hh - 6} fill={color.textMuted} fontSize={10} textAnchor="middle">
        resultado final de cada historia · en rojo, las que pierden
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
  const [nRep, setNRep] = useState(1000);
  const [banda, setBanda] = useState<Banda | null>(null);
  const [conBruta, setConBruta] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cortos = useMemo(() => result.trades.filter((t) => !String(t.direction).toLowerCase().startsWith("l")).length, [result.trades]);

  const calcular = () => {
    setCargando(true); setError(null);
    pedirBandaLocates(result.trades as TradeRecord[], initCash, minimo, maximo, nSem, base, rnd?.seed ?? null, nRep)
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
  const mc = banda?.bootstrap ?? null;
  const tonoPos = !mc ? color.textHigh : mc.positivo_pct >= 90 ? color.profit : mc.positivo_pct >= 65 ? color.warning : color.loss;

  return (
    <div style={{
      marginTop: 14, background: color.bgSurface, border: `1px solid ${color.border}`,
      fontFamily: font.sans, color: color.textPrimary,
    }}>
      <div style={{ background: color.bgElevated, borderBottom: `1px solid ${color.border}`, padding: "8px 13px", display: "flex", alignItems: "center", gap: 9 }}>
        <h3 style={{ margin: 0, flex: 1, fontSize: 12, fontWeight: 600, color: color.textHigh }}>
          Banda de locates: entre qué dos curvas puedes acabar
        </h3>
        <Help title="Banda de locates" width={580}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11.5, lineHeight: 1.45 }}>
            <div><b style={{ color: color.textHigh }}>Qué estás viendo. </b><span style={{ color: color.textSecondary }}>Dos preguntas distintas, una al lado de la otra. <b style={{ color: color.copperBright }}>Izquierda:</b> se toma tu corrida tal cual y se le vuelve a poner precio a los locates N veces, cada vez con una semilla distinta. Las operaciones no cambian, solo lo que cuesta cada día. <b style={{ color: color.copperBright }}>Derecha:</b> además de sortear el precio, cada «historia» saca al azar y con repetición tantos ticker-días como tuviste, de la bolsa de los tuyos. Unos salen dos veces, otros no salen. Es tu estrategia jugando otra vez con otra racha.</span></div>
            <div style={{ borderLeft: `2px solid ${color.copper}`, paddingLeft: 8 }}><b style={{ color: color.copperBright }}>Por ejemplo: </b>si la izquierda te dice que acabas entre +1.100 y +1.400 $, la suerte del alquiler te mueve 300 $. Si la derecha dice que solo 6 de cada 10 historias acaban ganando, entonces que tu histórico saliera en positivo fue en buena parte suerte del muestreo, y 300 $ eran la menor de tus preocupaciones.</div>
            <div><b style={{ color: color.textHigh }}>Para qué sirve. </b><span style={{ color: color.textSecondary }}>La izquierda casi siempre sale estrecha, porque son cientos de sorteos independientes y al sumarlos se compensan. La de la derecha es la que decide: dice si el edge bruto da de verdad para pagar el alquiler, o si el resultado que ves depende de qué operaciones te tocaron.</span></div>
            <div style={{ borderTop: `1px solid ${color.border}`, paddingTop: 6 }}>
              <div style={{ fontSize: "0.82em", letterSpacing: "0.1em", textTransform: "uppercase", color: color.textMuted, marginBottom: 2 }}>Cómo leerlo</div>
              <div><b style={{ color: color.copperBright }}>Más del 90 % de historias en positivo</b><span style={{ color: color.textSecondary }}> · la estrategia aguanta los locates; el histórico no fue suerte.</span></div>
              <div><b style={{ color: color.copperBright }}>Entre el 65 y el 90 %</b><span style={{ color: color.textSecondary }}> · aguanta por poco. Una racha mala normal te deja en pérdidas: o bajas paquetes o aprietas la puerta por EV.</span></div>
              <div><b style={{ color: color.copperBright }}>Por debajo del 65 %</b><span style={{ color: color.textSecondary }}> · no aguanta. Que tu corrida acabara ganando es a poco más que cara o cruz.</span></div>
              <div><b style={{ color: color.copperBright }}>Sin locates el 100 % y con locates la mitad</b><span style={{ color: color.textSecondary }}> · el edge existe pero se lo lleva entero el alquiler. El problema es el coste, no la señal.</span></div>
              <div><b style={{ color: color.copperBright }}>Banda izquierda estrecha y derecha ancha</b><span style={{ color: color.textSecondary }}> · lo normal. Deja de preocuparte por la semilla y mira el porcentaje de la derecha.</span></div>
            </div>
            <div style={{ color: color.warning, fontSize: "0.92em" }}>Ojo (1): el bootstrap supone que todas tus operaciones salen de la misma bolsa. Si el edge se ha degradado con los años — y la pestaña Edge dice que sí — mezcla las buenas de 2021 con las malas de ahora y te da una respuesta OPTIMISTA. Ojo (2): con la puerta por EV activa esto es una aproximación, porque con otra semilla la puerta habría dejado entrar otros trades.</div>
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
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: color.textMuted }}>
            Historias
            <input type="number" step="100" min={0} max={5000} value={nRep} style={inp} onChange={(e) => setNRep(Math.max(0, Math.min(5000, Math.floor(Number(e.target.value) || 0))))} />
          </label>
          <button onClick={calcular} disabled={cargando || maximo <= minimo || cortos === 0}
            style={{
              background: cargando ? color.bgElevated : color.copper,
              color: cargando ? color.textMuted : "var(--color-ec-copper-text)",
              border: `1px solid ${color.border}`, fontFamily: font.sans, fontSize: 12, fontWeight: 600,
              letterSpacing: "0.04em", height: 30, padding: "0 16px", cursor: cargando ? "wait" : "pointer",
            }}>
            {cargando ? "CALCULANDO…" : "CALCULAR"}
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

            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 18, marginTop: 12, alignItems: "start" }}>
              <div>
                <Titulo n="1" t="Mismas operaciones, distinto precio" s="cuánto te mueve la suerte del alquiler" />
                <Abanico b={banda} initCash={initCash} conBruta={conBruta} />
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6, fontSize: 10.5, fontFamily: font.mono, color: color.textSecondary }}>
                  <span><i style={{ display: "inline-block", width: 12, height: 8, background: color.copper, opacity: 0.3, verticalAlign: "middle" }} /> p10–p90</span>
                  <span><i style={{ display: "inline-block", width: 12, height: 2, background: color.copper, verticalAlign: "middle" }} /> mediana</span>
                  <span><i style={{ display: "inline-block", width: 12, height: 2, background: color.textHigh, verticalAlign: "middle" }} /> tu semilla</span>
                  <span><i style={{ display: "inline-block", width: 12, height: 1, background: color.profit, verticalAlign: "middle" }} /> mejor · <i style={{ display: "inline-block", width: 12, height: 1, background: color.loss, verticalAlign: "middle" }} /> peor</span>
                  <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
                    <input type="checkbox" checked={conBruta} onChange={(e) => setConBruta(e.target.checked)} style={{ margin: 0 }} />
                    <i style={{ display: "inline-block", width: 12, height: 0, borderTop: `1.5px dashed ${color.textMuted}`, verticalAlign: "middle" }} /> sin locates
                  </label>
                </div>
              </div>
              <div>
                <Titulo n="2" t="Otro histórico: operaciones y precio sorteados" s="¿ganaría igual con otra racha? — bootstrap" />
                {mc ? (
                  <>
                    <AbanicoMC mc={mc} initCash={initCash} />
                    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6, fontSize: 10.5, fontFamily: font.mono, color: color.textSecondary }}>
                      <span><i style={{ display: "inline-block", width: 12, height: 8, background: color.copper, opacity: 0.22, verticalAlign: "middle" }} /> p5–p95</span>
                      <span><i style={{ display: "inline-block", width: 12, height: 8, background: color.copper, opacity: 0.4, verticalAlign: "middle" }} /> p25–p75</span>
                      <span><i style={{ display: "inline-block", width: 12, height: 2, background: color.copper, verticalAlign: "middle" }} /> mediana</span>
                      <span><i style={{ display: "inline-block", width: 12, height: 0, borderTop: `1.5px dashed ${color.loss}`, verticalAlign: "middle" }} /> capital inicial: por debajo, pierde</span>
                    </div>
                  </>
                ) : (
                  <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", border: `1px dashed ${color.border}`, fontSize: 11.5, color: color.textMuted, textAlign: "center", padding: 20 }}>
                    {nRep === 0 ? "Pon un número de historias (1.000 va bien) y vuelve a calcular."
                      : "Hacen falta al menos 30 ticker-días para remuestrear sin inventarse la distribución."}
                  </div>
                )}
              </div>
            </div>

            <div style={{ display: "flex", borderTop: `0.5px solid ${color.border}`, marginTop: 14, paddingTop: 12 }}>
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

            {mc && (
              <div style={{ display: "flex", borderTop: `0.5px solid ${color.border}`, marginTop: 12, paddingTop: 12 }}>
                <Cifra k="Historias que ganan" v={`${f1(mc.positivo_pct)} %`} tono={tonoPos}
                       s={`sin locates ${f1(mc.positivo_bruto_pct)} %`} />
                <Cifra k="Acabas entre" v={<>{usd(mc.resumen.p5)}<br />y {usd(mc.resumen.p95)}</>} s="9 de cada 10 historias" chico />
                <Cifra k="Mediana" v={usd(mc.resumen.p50)} s={`media ${usd(mc.resumen.media)}`} />
                <Cifra k="Mala de verdad (p5)" v={usd(mc.resumen.p5)} s={`la peor de ${mc.n_replicas.toLocaleString("de-DE")}: ${usd(mc.resumen.peor)}`} tono={color.loss} />
                <Cifra k="Peor caída (p95)" v={`${f1(mc.resumen.dd_p95)} %`} s={`mediana ${f1(mc.resumen.dd_p50)} %`} tono={color.warning} ultima />
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 18, marginTop: 16, alignItems: "start" }}>
              {histDD && (
                <div>
                  <div style={{ fontSize: 10.5, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted, marginBottom: 6 }}>
                    Peor caída por semilla
                  </div>
                  <Histograma hist={histDD} actual={banda.actual?.max_dd_pct ?? r.dd_mediana} p95={r.dd_p95} unidad="%"
                              pie={`peor caída en % de cada una de las ${banda.n_semillas} semillas`} />
                </div>
              )}
              {mc && (
                <div>
                  <div style={{ fontSize: 10.5, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted, marginBottom: 6 }}>
                    En cuánto acaba cada historia
                  </div>
                  <HistoResultados mc={mc} real={banda.actual?.final ?? null} />
                </div>
              )}
            </div>

            <div style={{ fontSize: 12, color: color.textSecondary, lineHeight: 1.55, marginTop: 14, borderTop: `0.5px solid ${color.border}`, paddingTop: 12 }}>
              {(() => {
                const ancho = r.final_p90 - r.final_p10;
                const rel = r.bruta_final !== 0 ? Math.abs(ancho / r.bruta_final) * 100 : 0;
                const anchoMC = mc ? mc.resumen.p95 - mc.resumen.p5 : 0;
                return (
                  <>
                    {mc && (
                      <p style={{ margin: "0 0 8px" }}>
                        De <b style={{ color: color.textHigh }}>{mc.n_replicas.toLocaleString("de-DE")}</b> historias alternativas,
                        acaban ganando <b style={{ color: tonoPos }}>{f1(mc.positivo_pct)} de cada 100</b>
                        {mc.positivo_bruto_pct > mc.positivo_pct + 1 && <> (sin locates serían {f1(mc.positivo_bruto_pct)})</>}.
                        {mc.positivo_pct >= 90 ? " La estrategia aguanta los locates: lo que viste no fue suerte."
                          : mc.positivo_pct >= 65 ? " Aguanta, pero por poco: una racha mala normal te deja en pérdidas."
                            : " No aguanta: que tu corrida acabara ganando es poco más que cara o cruz."}
                      </p>
                    )}
                    <p style={{ margin: "0 0 8px" }}>
                      La suerte con el <b>precio</b> de los locates mueve el resultado en <b style={{ color: color.textHigh }}>{usd(ancho).replace("+", "")}</b>
                      {r.bruta_final !== 0 && <> (un {f1(rel)} % del resultado sin locates)</>}
                      {mc && <>, y la suerte con <b>qué operaciones te tocan</b> lo mueve en <b style={{ color: color.textHigh }}>{usd(anchoMC).replace("+", "")}</b>
                        {anchoMC > ancho * 2 && <>, unas <b style={{ color: color.textHigh }}>{Math.round(anchoMC / Math.max(1, ancho))} veces más</b></>}</>}.
                      {mc && anchoMC > ancho * 2 && " Por eso la de la derecha es la que decide."}
                    </p>
                    <p style={{ margin: 0 }}>
                      Los locates se llevan de media <b style={{ color: color.textHigh }}>{r.bruta_final !== 0 ? f1(Math.abs(r.factura_media / r.bruta_final) * 100) : "—"} %</b> de
                      lo que gana la estrategia sin ellos. La peor caída {mc ? "del 95 % de las historias" : "de todas las semillas"} es{" "}
                      <b style={{ color: color.warning }}>{f1(mc ? mc.resumen.dd_p95 : r.dd_peor)} %</b>: ese es el número con el que dimensionar la cuenta,
                      no el de tu corrida.
                      {mc && " Y recuerda que el bootstrap mezcla todos tus años: si el edge se ha degradado, este número es optimista."}
                    </p>
                  </>
                );
              })()}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
