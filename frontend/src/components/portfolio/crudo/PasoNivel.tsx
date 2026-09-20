"use client";

// Paso 4 de «En crudo» (v4, 20-sep-2026, tras la conversacion con Jaume sobre
// que mejora de verdad un % constante): tres bloques, los tres sobre el
// portfolio del paso 1.
//   A. Nivel de la cuenta por la caida: los % del paso 1 x un factor, y para
//      cada factor lo real y el Monte Carlo. El nivel se elige por la DD que
//      se traga, no por el retorno (estamos muy por debajo de Kelly).
//   B. Reparto entre estrategias: la Kelly conjunta (con correlaciones),
//      estimada en la primera parte y comprobada en la segunda contra los %
//      del paso 1 y a partes iguales.
//   C. Tamano por setup: la Kelly relativa (EV/sigma^2) de cada tramo de
//      precio de entrada, estimada walk-forward por anos, como multiplicador
//      del % del paso 1; y la comparacion HONESTA: contra la base y contra un
//      % constante con el MISMO tamano medio.

import React, { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawNivelesOut, RawOut, RawRepartoOut, RawSetupIn } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Row, Sec, Stat, Toggle, colorSerie, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { LinesChart, type Serie } from "./CrudoCharts";

export interface NivelModel {
  out: RawOut;
  nombres: string[];
  // A
  niveles: RawNivelesOut | null;
  nivelesRunning: boolean;
  nivelesError: string | null;
  calcularNiveles: () => void;
  // B
  reparto: RawRepartoOut | null;
  repartoRunning: boolean;
  repartoError: string | null;
  calcularReparto: () => void;
  // C
  setup: RawSetupIn;
  setSetup: React.Dispatch<React.SetStateAction<RawSetupIn>>;
  outSetup: RawOut | null;
  outConst: RawOut | null;
  setupRunning: boolean;
  setupError: string | null;
  setupStale: boolean;
  calcularSetup: () => void;
}

const numChico: React.CSSProperties = { height: 24, fontSize: 11, padding: "2px 5px", textAlign: "right" };

/** Retorno por ano natural de una curva (equity al cierre de cada dia). */
export function retornoPorAno(cal: string[], equity: number[], capital: number): Array<{ ano: string; pct: number; dd: number }> {
  const out: Array<{ ano: string; pct: number; dd: number }> = [];
  let ini = capital; let anoAct = ""; let fin = capital; let prev = capital; let peak = capital; let dd = 0;
  for (let i = 0; i < cal.length; i++) {
    const a = cal[i].slice(0, 4);
    if (a !== anoAct) {
      if (anoAct) out.push({ ano: anoAct, pct: ini > 0 ? (fin / ini - 1) * 100 : 0, dd });
      anoAct = a; ini = prev; peak = prev; dd = 0;
    }
    fin = equity[i]; prev = fin;
    peak = Math.max(peak, fin);
    dd = Math.min(dd, peak > 0 ? (fin / peak - 1) * 100 : 0);
  }
  if (anoAct) out.push({ ano: anoAct, pct: ini > 0 ? (fin / ini - 1) * 100 : 0, dd });
  return out;
}

function maxDd(equity: number[], capital: number): number {
  let peak = capital; let dd = 0;
  for (const e of equity) { peak = Math.max(peak, e); dd = Math.min(dd, peak > 0 ? (e / peak - 1) * 100 : 0); }
  return dd;
}

export function PasoNivel({ m }: { m: NivelModel }) {
  const { out, nombres, niveles, nivelesRunning, nivelesError, calcularNiveles, reparto, repartoRunning, repartoError, calcularReparto,
    setup, setSetup, outSetup, outConst, setupRunning, setupError, setupStale, calcularSetup } = m;
  const cap0 = out.config.capital;
  const set = <K extends keyof RawSetupIn>(k: K, v: RawSetupIn[K]) => setSetup((s) => ({ ...s, [k]: v }));

  const totalBase = useMemo(() => {
    const ps = out.per_strategy.map((p) => p.exec?.size_value ?? 0);
    return ps.reduce((a, b) => a + b, 0);
  }, [out]);

  // ── C: comparacion base / setup / constante de igual tamano ────────────
  const comparacion = useMemo(() => {
    if (!outSetup) return null;
    const filas = [
      { nombre: "Los % del paso 1 (base)", o: out, col: color.textSecondary },
      { nombre: "Tamaño por setup", o: outSetup, col: color.copper },
      ...(outConst ? [{ nombre: "% constante con el mismo tamaño medio", o: outConst, col: color.profit }] : []),
    ];
    const series: Serie[] = filas.map((f) => ({ name: f.nombre, color: f.col, width: f.o === outSetup ? 2.2 : 1.4, values: f.o.equity.map((e) => (e / cap0 - 1) * 100) }));
    const porAno = filas.map((f) => ({ nombre: f.nombre, anos: retornoPorAno(f.o.calendar, f.o.equity, cap0) }));
    const anos = porAno[0].anos.map((a) => a.ano);
    return { filas, series, porAno, anos };
  }, [out, outSetup, outConst, cap0]);
  const veredicto = useMemo(() => {
    if (!outSetup || !outConst) return null;
    const fS = outSetup.equity[outSetup.equity.length - 1]; const fC = outConst.equity[outConst.equity.length - 1];
    const dS = maxDd(outSetup.equity, cap0); const dC = maxDd(outConst.equity, cap0);
    const mejora = fS > fC && dS >= dC - 1e-9;
    const peor = fS <= fC && dS <= dC + 1e-9;
    return { fS, fC, dS, dC, mejora, peor };
  }, [outSetup, outConst, cap0]);

  return (
    <div style={{ padding: "10px 10px 6px" }}>
      {/* ── A. Nivel ─────────────────────────────────────────────────── */}
      <Sec
        title="A · Nivel de la cuenta por la caída"
        help={
          <>
            Tus % del paso 1 (que suman <strong>{n(totalBase, 2)} %</strong> por trade) multiplicados por cada factor, con todo lo
            demás igual, y para cada uno: el final, la caída máxima real, el peor día y el Monte Carlo (bootstrap por días):
            la caída que hay que tragar para que solo 1 de 20 (p95) o 1 de 100 (p99) recorridos la superen.
            <br /><br />
            <strong>Cómo se lee:</strong> estás muy por debajo de la Kelly de la cuenta, así que subir el nivel da más retorno y más caída casi en
            proporción. No hay un nivel «óptimo» por retorno: se elige el mayor factor cuya DD p95 aguantas. Ese es el tope de la cuenta.
          </>
        }
        right={<Btn primary onClick={calcularNiveles} disabled={nivelesRunning}>{nivelesRunning ? "Calculando…" : niveles ? "Volver a calcular" : "Calcular niveles"}</Btn>}
        sinRelleno
      >
        {nivelesError && <div style={{ padding: 8 }}><ErrorBox>{nivelesError}</ErrorBox></div>}
        {!niveles ? (
          <div style={{ padding: "8px 10px" }}><Nota>Pulsa <strong>Calcular niveles</strong>: 6 simulaciones del portfolio (×0,5 … ×2 los % del paso 1) con su Monte Carlo.</Nota></div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thL}>Factor</th>
                <th style={thR}>Total por trade</th>
                <th style={thR}>Final</th>
                <th style={thR}>Retorno</th>
                <th style={thR}>DD real</th>
                <th style={thR}>Peor día</th>
                <th style={thR}>DD a tragar (1 de 20)</th>
                <th style={thR}>(1 de 100)</th>
                <th style={thR}>Final mediana MC</th>
                <th style={thR}>Ruina (−{n(niveles.ruin_pct, 0)} %)</th>
              </tr>
            </thead>
            <tbody>
              {niveles.niveles.map((f) => {
                const actual = Math.abs(f.factor - 1) < 1e-9;
                return (
                  <tr key={f.factor} style={actual ? { background: "rgba(184, 115, 51, 0.08)" } : undefined}>
                    <td style={{ ...tdTxt, fontFamily: font.mono, fontWeight: actual ? 700 : 500 }}>×{n(f.factor, 2)}{actual ? " (paso 1)" : ""}</td>
                    <td style={tdNum}>{pct(f.total_pct, 2)}</td>
                    <td style={tdNum}>{f.ruined ? <span style={{ color: color.loss }}>ruina</span> : usd(f.final_equity)}</td>
                    <td style={{ ...tdNum, color: f.return_pct >= 0 ? color.profit : color.loss }}>{pct(f.return_pct, 0)}</td>
                    <td style={{ ...tdNum, color: color.loss }}>{pct(f.max_dd_pct)}</td>
                    <td style={{ ...tdNum, color: color.loss }}>{pct(f.worst_day_pct)}</td>
                    <td style={{ ...tdNum, color: color.loss, fontWeight: 700 }}>{f.mc ? pct(f.mc.dd_p95) : "—"}</td>
                    <td style={{ ...tdNum, color: color.loss }}>{f.mc ? pct(f.mc.dd_p99) : "—"}</td>
                    <td style={tdNum}>{f.mc ? usd(f.mc.final_p50) : "—"}</td>
                    <td style={{ ...tdNum, color: f.mc && f.mc.prob_ruin_pct > 0 ? color.loss : color.textMuted }}>{f.mc ? pct(f.mc.prob_ruin_pct) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Sec>

      {/* ── B. Reparto ───────────────────────────────────────────────── */}
      <Sec
        title="B · Reparto entre estrategias, con la misma suma"
        help={
          <>
            Qué pasa si cambias el capital de cada estrategia <strong>sin cambiar la suma</strong>: cada reparto candidato se corre con
            el motor entero (locates, margen, costes) y se mira el final, la caída y lo de antes y después del corte (la
            segunda mitad es fuera de muestra). Candidatos: tus % del paso 1, a partes iguales, la <strong>Kelly conjunta</strong>
            (la f que maximiza el crecimiento de la suma con las correlaciones; estimada en la primera mitad y con todo),
            «sin X» (su parte repartida a las demás) y «todo a X».
            <br /><br />
            <strong>Cómo se lee:</strong> a un nivel tan bajo respecto a Kelly el crecimiento es casi la suma de lo que rinde cada una por
            unidad de tamaño, así que mover capital hacia la que más rinde por unidad sube el retorno… y la caída, porque
            pierdes diversificación. La tabla te da la frontera: eliges por la caída que tragas (bloque A).
          </>
        }
        right={<Btn primary onClick={calcularReparto} disabled={repartoRunning}>{repartoRunning ? "Calculando…" : reparto ? "Volver a calcular" : "Calcular reparto"}</Btn>}
        sinRelleno
      >
        {repartoError && <div style={{ padding: 8 }}><ErrorBox>{repartoError}</ErrorBox></div>}
        {!reparto ? (
          <div style={{ padding: "8px 10px" }}><Nota>Pulsa <strong>Calcular reparto</strong>. Necesita los % del paso 1 en % del capital.</Nota></div>
        ) : (
          <>
            <div style={{ padding: "6px 10px 0", display: "flex", flexWrap: "wrap" }}>
              <Stat label="Suma por trade" value={pct(reparto.total_pct, 2)} sub="la de tus % del paso 1, igual en todos" />
              <Stat label="Corte" value={reparto.split_date ?? "—"} sub={`${n(reparto.dias_is, 0)} días antes · ${n(reparto.dias_oos, 0)} después (fuera de muestra)`} />
              {reparto.ret_por_unidad_pct && (
                <Stat label="Retorno por 1 % por trade" value={reparto.ret_por_unidad_pct.map((x) => `${n(x, 3)} %`).join(" · ")} sub={`al día · ${reparto.names.map((nm) => nm.slice(0, 10)).join(" · ")}`} help="El retorno diario medio del portfolio que aporta cada estrategia por cada 1 % por trade que se le da. A un nivel bajo, el crecimiento es casi la suma de esto × su %: la que más rinde por unidad es la que «pide» el capital." />
              )}
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 6 }}>
              <thead>
                <tr>
                  <th style={thL}>Reparto</th>
                  {reparto.names.map((nm, i) => <th key={nm} style={{ ...thR, color: colorSerie(i) }}>{nm.length > 18 ? `${nm.slice(0, 17)}…` : nm}</th>)}
                  <th style={thR}>Final</th>
                  <th style={thR}>DD</th>
                  <th style={thR}>Antes ×</th>
                  <th style={thR}>DD</th>
                  <th style={thR}>Después ×</th>
                  <th style={thR}>DD</th>
                </tr>
              </thead>
              <tbody>
                {[...reparto.candidatos].sort((a, b) => b.final_equity - a.final_equity).map((c) => {
                  const actual = c.clave === "actual";
                  return (
                    <tr key={c.name} style={actual ? { background: "rgba(184, 115, 51, 0.08)" } : undefined}>
                      <td style={{ ...tdTxt, fontWeight: actual ? 700 : 500, whiteSpace: "normal" }}>{c.name}</td>
                      {c.pct.map((x, i) => <td key={i} style={tdNum}>{pct(x, 2)}</td>)}
                      <td style={{ ...tdNum, fontWeight: 700 }}>{c.ruined ? <span style={{ color: color.loss }}>ruina</span> : usd(c.final_equity)}</td>
                      <td style={{ ...tdNum, color: color.loss, fontWeight: 700 }}>{pct(c.max_dd_pct)}</td>
                      <td style={tdNum}>×{n(c.is.mult, 1)}</td>
                      <td style={{ ...tdNum, color: color.loss }}>{pct(c.is.dd_pct)}</td>
                      <td style={tdNum}>×{n(c.oos.mult, 1)}</td>
                      <td style={{ ...tdNum, color: color.loss }}>{pct(c.oos.dd_pct)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p style={{ margin: 0, padding: "8px 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
              Ordenado por el final. Correlación diaria: {reparto.names.map((nm, i) => reparto.names.slice(i + 1).map((nm2, j) => `${nm.slice(0, 12)} – ${nm2.slice(0, 12)}: ${n(reparto.correlation[i][i + 1 + j], 2)}`).join(" · ")).filter(Boolean).join(" · ")}.
              Kelly propia de cada una (sin tope): {reparto.kelly_propia_pct.map((k, i) => `${reparto.names[i].slice(0, 12)} ${k == null ? "—" : n(k, 0)} %`).join(" · ")}.
              Un reparto que gana en «después» y no en «antes» (o al revés) es ruido; el que gana en los dos con una caída que tragas es el bueno. Compáralo siempre con subir el nivel de tus % (bloque A) a la misma caída.
            </p>
          </>
        )}
      </Sec>

      {/* ── C. Tamano por setup ───────────────────────────────────────── */}
      <Sec
        title="C · Tamaño por setup (tramo de precio de entrada)"
        help={
          <>
            Cada trade se dimensiona con el % del paso 1 <strong>× la Kelly relativa de su setup</strong>: para cada estrategia y
            tramo de precio de entrada se mide en los trades pasados el EV (retorno medio en su unidad, neto de costes y locate
            esperado) y su dispersión, y el tamaño relativo es EV/σ² normalizado al setup medio (mismo nocional medio),
            encogido hacia ×1 según la muestra y acotado.
            <br /><br />
            <strong>Walk-forward:</strong> los trades de cada año van con la tabla estimada con todo lo anterior al 1 de enero de ese año
            (el primer año, sin historia, va a ×1). Así, del segundo año en adelante el resultado es fuera de muestra.
            <br /><br />
            <strong>La comparación que vale:</strong> como la tabla puede acabar apostando más de media que el paso 1 (si los setups buenos
            aparecen más), se corre también un <strong>% constante con el mismo tamaño medio por estrategia</strong>. Si el setup no gana a
            ese constante con caída igual o menor, la tabla no está añadiendo nada: solo está apostando más.
          </>
        }
        right={<Btn primary onClick={calcularSetup} disabled={setupRunning}>{setupRunning ? "Calculando…" : outSetup ? "Volver a calcular" : "Calcular setups"}</Btn>}
      >
        <Row label="Acotación" help="Multiplicador mínimo y máximo sobre el % del paso 1. Con 0 abajo, un tramo con EV ≤ 0 se deja de operar.">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>×</span>
            <div style={{ width: 64 }}><Num value={setup.clip_lo ?? 0.5} onChange={(v) => set("clip_lo", Math.max(0, Number(v) || 0))} min={0} step={0.1} style={numChico} /></div>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>a ×</span>
            <div style={{ width: 64 }}><Num value={setup.clip_hi ?? 2} onChange={(v) => set("clip_hi", Math.max(0.1, Number(v) || 0))} min={0.1} step={0.1} style={numChico} /></div>
          </div>
        </Row>
        <Row label="Muestra" help="Mínimo de trades para que un tramo tenga multiplicador propio (si no, ×1), y el encogimiento hacia ×1: m = 1 + (m − 1) · n / (n + encogimiento). Con 0 no se encoge.">
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>mínimo</span>
            <div style={{ width: 64 }}><Num value={setup.min_trades ?? 30} onChange={(v) => set("min_trades", Math.max(5, Math.round(Number(v) || 0)))} min={5} step={5} style={numChico} /></div>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>trades · encogimiento</span>
            <div style={{ width: 64 }}><Num value={setup.shrink ?? 50} onChange={(v) => set("shrink", Math.max(0, Number(v) || 0))} min={0} step={10} style={numChico} /></div>
          </div>
        </Row>
        <Row label="Estimación" help="Walk-forward: cada año con lo anterior (lo honesto). Toda la historia: la misma tabla para todo, dentro de muestra — sirve para ver la tabla, no para creerse el resultado. «Una tabla común» junta los trades de todas las estrategias (más muestra por tramo).">
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ width: 260 }}><Toggle value={setup.estimate ?? "walk_forward"} onChange={(v) => set("estimate", v)} options={[{ value: "walk_forward", label: "walk-forward por años" }, { value: "all", label: "toda la historia" }]} /></div>
            <div style={{ width: 230 }}><Toggle value={setup.pooled ? "si" : "no"} onChange={(v) => set("pooled", v === "si")} options={[{ value: "no", label: "tabla por estrategia" }, { value: "si", label: "una tabla común" }]} /></div>
          </div>
        </Row>
        {setupError && <div style={{ marginTop: 8 }}><ErrorBox>{setupError}</ErrorBox></div>}
        {setupStale && outSetup && <Nota tone="warning">Los ajustes han cambiado desde el último cálculo.</Nota>}

        {comparacion && outSetup && (
          <>
            <div style={{ display: "flex", flexWrap: "wrap", marginTop: 8 }}>
              {comparacion.filas.map((f) => (
                <Stat key={f.nombre} label={f.nombre} value={usd(f.o.equity[f.o.equity.length - 1])} sub={`DD ${pct(maxDd(f.o.equity, cap0))} · ${n(f.o.cap_report.taken, 0)} trades`} tone={f.o === outSetup ? undefined : undefined} />
              ))}
              {outSetup.setup && (
                <Stat label="Tamaño medio aplicado" value={outSetup.setup.por_estrategia.map((p) => `×${n(p.mult_medio, 2)}`).join(" · ")} sub={outSetup.setup.por_estrategia.map((p) => p.name.slice(0, 8)).join(" · ")} />
              )}
            </div>
            {veredicto && (
              <Nota tone={veredicto.mejora ? undefined : "warning"}>
                {veredicto.mejora
                  ? <>Con el mismo tamaño medio, el setup acaba en {usd(veredicto.fS)} con DD {pct(veredicto.dS)} frente a {usd(veredicto.fC)} y {pct(veredicto.dC)} del constante: <strong>la tabla añade algo</strong>.</>
                  : <>Con el mismo tamaño medio, el % constante acaba en {usd(veredicto.fC)} con DD {pct(veredicto.dC)} y el setup en {usd(veredicto.fS)} con DD {pct(veredicto.dS)}: <strong>hoy la tabla no mejora al % constante</strong>; lo que sube es porque apuesta más, no porque acierte dónde.</>}
              </Nota>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 380px", gap: 12, alignItems: "start", marginTop: 8 }}>
              <LinesChart labels={out.calendar} series={comparacion.series} yFormat={(v) => `${n(v, 0)} %`} hoverFormat={(v) => `${n(v, 1)} %`} height={260} titulo="RETORNO SOBRE EL CAPITAL" />
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={thL}>Año</th>
                    {comparacion.porAno.map((p) => <th key={p.nombre} style={thR}>{p.nombre.length > 16 ? `${p.nombre.slice(0, 15)}…` : p.nombre}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {comparacion.anos.map((ano, k) => (
                    <tr key={ano}>
                      <td style={{ ...tdTxt, fontFamily: font.mono }}>{ano}{k === 0 && (setup.estimate ?? "walk_forward") === "walk_forward" ? " (sin historia: ×1)" : ""}</td>
                      {comparacion.porAno.map((p) => {
                        const a = p.anos[k];
                        return <td key={p.nombre} style={{ ...tdNum, color: a && a.pct >= 0 ? color.profit : color.loss }}>{a ? `${pct(a.pct, 0)} · DD ${pct(a.dd, 0)}` : "—"}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {outSetup.setup && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.textMuted, fontFamily: font.sans, marginBottom: 4 }}>
                  La tabla vigente (estimada con toda la historia: lo que valdría para mañana)
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={thL}>Estrategia</th>
                      {outSetup.setup.vigente[0]?.ranges.map((r) => <th key={`${r.lo}-${r.hi}`} style={thR}>{r.hi == null ? `≥ ${n(r.lo, 1)} $` : `${n(r.lo, 1)}–${n(r.hi, 1)} $`}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {outSetup.setup.vigente.map((t, i) => (
                      <React.Fragment key={t.name}>
                        <tr>
                          <td style={{ ...tdTxt, color: colorSerie(i), fontWeight: 600 }}>{t.name}<span style={{ color: color.textMuted, fontWeight: 400 }}> · {t.basis === "capital" ? "sobre la posición" : "en R"}</span></td>
                          {t.ranges.map((r) => (
                            <td key={`${r.lo}-${r.hi}`} style={{ ...tdNum, color: !r.con_muestra ? color.textMuted : r.m > 1.001 ? color.profit : r.m < 0.999 ? color.loss : color.textPrimary, fontWeight: r.con_muestra && Math.abs(r.m - 1) > 0.001 ? 700 : 500 }}>
                              {r.n === 0 ? "—" : !r.con_muestra ? `×1 (n ${n(r.n, 0)})` : `×${n(r.m, 2)}`}
                            </td>
                          ))}
                        </tr>
                        <tr>
                          <td style={{ ...tdTxt, color: color.textMuted, fontSize: 10 }}>EV · trades</td>
                          {t.ranges.map((r) => (
                            <td key={`${r.lo}-${r.hi}-ev`} style={{ ...tdNum, color: color.textMuted, fontSize: 10 }}>{r.n === 0 ? "" : `${r.ev_pct >= 0 ? "+" : ""}${t.basis === "risk" ? `${n(r.ev_pct / 100, 2)} R` : `${n(r.ev_pct, 1)} %`} · ${n(r.n, 0)}`}</td>
                          ))}
                        </tr>
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        {!outSetup && !setupError && (
          <Nota>Pulsa <strong>Calcular setups</strong>: el portfolio con la tabla, y al lado un % constante con el mismo tamaño medio para saber si la tabla añade algo.</Nota>
        )}
      </Sec>
    </div>
  );
}
