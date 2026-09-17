"use client";

// Paso 3 de «En crudo»: limites de perdida. Lo historico (lo que ya paso en
// la serie real) y el Monte Carlo bootstrap de los dias del conjunto (lo que
// podria pasar con la misma suerte en otro orden). Con locates aleatorios, la
// banda de semillas: cuanto del resultado depende del precio de los locates.
// Y desde el 17-sep: hasta que precio compensan los locates (precio de
// equilibrio, neto por tramo de fade y la regla «fade maximo»).

import React, { useMemo } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawOut } from "@/lib/api_portfolio_lab";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Btn, Nota, Num, Sec, Stat, Toggle, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";
import { LinesChart } from "./CrudoCharts";
import { limitesHistoricos } from "./modelo";
import { McResultado } from "./McResultado";
import { RangosLocatesCrudo } from "./RangosLocatesCrudo";

export interface MonteCarloModel {
  out: RawOut;
  mcOut: MonteCarloOut | null;
  mcSims: number | "";
  setMcSims: (v: number | "") => void;
  mcMethod: "bootstrap" | "permutacion";
  setMcMethod: (v: "bootstrap" | "permutacion") => void;
  mcRunning: boolean;
  mcError: string | null;
  simularMc: () => void;
  /** Poner en el paso 1 la puerta «EV fijo = F» (hay que volver a calcular). */
  onUsarFade: (f: number) => void;
  /** Un calculo del motor con otro rango de locates aleatorios (y puerta por EV fijo o sin puerta). */
  correrRango: (min: number, max: number, seed: number, evFijo: number | null) => Promise<RawOut>;
  evFijoActual: number;
  seedActual: number;
}

export function PasoMonteCarlo({ m }: { m: MonteCarloModel }) {
  const { out, mcOut, mcSims, setMcSims, mcMethod, setMcMethod, mcRunning, mcError, simularMc, onUsarFade, correrRango, evFijoActual, seedActual } = m;
  const cap = out.config.capital;
  const hist = useMemo(() => limitesHistoricos(out.daily_pnl, out.equity, cap), [out, cap]);
  const bd = out.locates_band;
  const an = out.locates_analysis;
  const bandSeries = useMemo(() => {
    if (!bd) return null;
    return {
      series: [
        { name: "mediana de las semillas", color: color.textSecondary, values: bd.bands.p50.map((v) => ((v - cap) / cap) * 100) },
        { name: "real (semilla del paso 1)", color: color.copper, width: 2.2, values: out.equity.map((v) => ((v - cap) / cap) * 100) },
      ],
      band: { lo: bd.bands.p05.map((v) => ((v - cap) / cap) * 100), hi: bd.bands.p95.map((v) => ((v - cap) / cap) * 100), color: color.info, name: "p05 … p95" },
    };
  }, [bd, out.equity, cap]);
  const curvaPrecio = useMemo(() => {
    if (!an) return null;
    return {
      labels: an.curve.map((c) => `${n(c.price, 1)} $`),
      series: [
        { name: "neto de los cortos", color: color.copper, width: 2.2, values: an.curve.map((c) => c.net_shorts) },
        { name: "neto del portfolio", color: color.textSecondary, values: an.curve.map((c) => c.net_total) },
      ],
    };
  }, [an]);

  const fila = (etq: string, ayuda: string, u: number, p: number) => (
    <tr>
      <td style={tdTxt} title={ayuda}>{etq}</td>
      {u === 0 && p === 0 ? (
        <td colSpan={2} style={{ ...tdNum, color: color.textMuted }}>ninguna negativa</td>
      ) : (
        <>
          <td style={{ ...tdNum, color: u < 0 ? color.loss : color.textPrimary }}>{usd(u)}</td>
          <td style={{ ...tdNum, color: p < 0 ? color.loss : color.textPrimary }}>{pct(p, 2)}</td>
        </>
      )}
    </tr>
  );
  const gateActual = out.config.locates?.gate;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
        <Sec title="Lo que ya pasó — límites históricos" help="Sobre la serie diaria real del paso 2, en $ y en % del capital con el que empezó cada día. VaR 95 %: el día malo que solo se supera 1 de cada 20 días (el percentil 5 de los días). VaR 99 %: 1 de cada 100. CVaR 95 %: la media de ese 5 % de días peores (lo que pierdes cuando toca perder de verdad). Peor racha de N días: la peor suma de N días seguidos que hubo." sinRelleno>
          {hist ? (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thL}>Medida</th>
                  <th style={thR}>$</th>
                  <th style={thR}>% del capital del día</th>
                </tr>
              </thead>
              <tbody>
                {fila(`Peor día (${out.calendar[hist.peorDia.idx]})`, "El día de mayor pérdida de toda la serie.", hist.peorDia.usd, hist.peorDia.pct)}
                {fila("VaR 95 % diario", "Pérdida que solo se supera 1 de cada 20 días.", hist.var95.usd, hist.var95.pct)}
                {fila("VaR 99 % diario", "Pérdida que solo se supera 1 de cada 100 días.", hist.var99.usd, hist.var99.pct)}
                {fila("CVaR 95 % diario", "Media del 5 % de días peores.", hist.cvar95.usd, hist.cvar95.pct)}
                {fila("Peor racha de 5 días", "La peor suma de 5 días seguidos.", hist.racha5.usd, hist.racha5.pct)}
                {fila("Peor racha de 20 días", "La peor suma de 20 días seguidos (un mes).", hist.racha20.usd, hist.racha20.pct)}
                <tr>
                  <td style={{ ...tdTxt, color: color.textMuted }}>Días negativos</td>
                  <td style={{ ...tdNum, color: color.textMuted }}>{n(hist.diasNegativos, 0)} de {n(hist.dias, 0)}</td>
                  <td style={{ ...tdNum, color: color.textMuted }}>{pct((hist.diasNegativos / hist.dias) * 100, 0)}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <Nota>Sin días.</Nota>
          )}
        </Sec>

        <Sec
          title="Lo que podría pasar — Monte Carlo bootstrap"
          help="Remuestrea los DÍAS del conjunto (bootstrap: con reemplazo, un día puede salir dos veces; permutación: los mismos días en otro orden), no los trades: los de una misma sesión van correlacionados y no se separan. Cada día entra como su RETORNO (% del capital con el que empezó ese día) y los recorridos se componen día a día, así un día malo pesa lo mismo caiga donde caiga; sumar los $ de cada día daba drawdowns de miles de % en una curva que compone. Con miles de recorridos sale la distribución del drawdown y del balance final. «DD a tragar (1 de 20)»: para que solo 1 de cada 20 recorridos lo supere, hay que aguantar ese drawdown; es el número que hay que poder tragar antes de operar esto."
          right={
            <>
              <div style={{ width: 80 }}><Num value={mcSims} onChange={setMcSims} min={500} max={20000} step={500} style={{ height: 24, fontSize: 11 }} /></div>
              <div style={{ width: 200 }}><Toggle value={mcMethod} onChange={setMcMethod} options={[{ value: "bootstrap", label: "Bootstrap" }, { value: "permutacion", label: "Permutación" }]} /></div>
              <Btn primary onClick={simularMc} disabled={mcRunning}>{mcRunning ? "Simulando…" : "Simular"}</Btn>
            </>
          }
        >
          {mcError && <ErrorBox>{mcError}</ErrorBox>}
          {!mcOut ? (
            <Nota>Pulsa <strong>Simular</strong>: {n(Number(mcSims) || 5000, 0)} recorridos de {n(out.calendar.length, 0)} días.</Nota>
          ) : (
            <Nota>Simulado sobre la suma del paso 2: {n(mcOut.simulations, 0)} recorridos. Abajo, los recorridos y las distribuciones.</Nota>
          )}
        </Sec>
      </div>

      {mcOut && <McResultado mcOut={mcOut} />}

      {an && (
        <Sec title="Locates — hasta qué precio compensan" help={
          <>
            <strong>Precio de equilibrio</strong>: el PnL de los cortos antes de locates (ya con comisiones y slippage)
            partido por los paquetes de 100 que la cuenta alquila. A ese precio por paquete los cortos se quedan a cero;
            el neto baja en línea recta con el precio (la curva). Por estrategia, lo mismo con sus cortos y sus paquetes.
            <br /><br />
            <strong>Fade necesario</strong> de un corto: el % que tiene que moverse la acción a favor solo para pagar los
            paquetes de más que exige (con alquiler compartido, lo ya alquilado va gratis). La tabla por tramos enseña el
            neto tras el locate según ese fade: donde el neto medio se vuelve negativo, ese corto no compensaba.
            <br /><br />
            <strong>Puerta por EV fijo</strong>: entra el corto si el EV que fijes supera su fade necesario. La tabla
            estima el neto para varios EV fijos sobre los cortos de este cálculo (aproximado: quitar un corto cambia lo
            alquilado a los demás; al ponerlo en el paso 1 se recalcula exacto). Auditoría del 17-sep: el EV rodante de
            30 trades rechazaba por racha (el error de estimar el EV con 30 trades es mayor que el propio EV) y perdía
            dinero; el EV fijo compara el coste de CADA corto con el edge de la estrategia, que es lo que se buscaba.
          </>
        }>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
            <Stat big label="Precio de equilibrio" value={`${n(an.breakeven_price, 2)} $`} sub="por paquete de 100 · a ese precio los cortos se quedan a cero" tone="warning" />
            <Stat label="Paquetes alquilados" value={n(an.packages, 0)} sub={`${n(an.shorts, 0)} cortos`} />
            <Stat label="PnL de los cortos antes de locates" value={usd(an.pnl_shorts_pre_locates)} tone={an.pnl_shorts_pre_locates >= 0 ? "profit" : "loss"} />
            {an.paid > 0 && <Stat label="Pagado" value={usd(an.paid)} sub={`${n(an.avg_price_paid, 2)} $ por paquete de media · ${pct((an.paid / Math.max(1, an.pnl_shorts_pre_locates)) * 100, 0)} del bruto`} tone="loss" />}
            <Stat label="Movimiento medio del corto" value={pct(an.mean_move_pct, 2)} sub="del precio, antes de locates" help="La media de lo que se mueve a favor cada corto (PnL / nocional). Es el edge medio contra el que se compara el fade." />
            {an.best_fade_max_pct != null && an.fade_rule && (
              <Stat label="EV fijo que más neto deja" value={`${n(an.best_fade_max_pct, 1)} %`} sub={`≈ ${usd(an.fade_rule.find((r) => r.fade_max_pct === an.best_fade_max_pct)?.net_est ?? 0)} frente a ${usd(an.net_now ?? 0)} sin puerta`} tone="profit" />
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14, alignItems: "start", marginTop: 6 }}>
            <div>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={thL}>Estrategia</th>
                    <th style={thR}>Cortos</th>
                    <th style={thR}>Paquetes</th>
                    <th style={thR}>PnL antes de locates</th>
                    <th style={thR}>Equilibrio $/paq.</th>
                    {an.paid > 0 && <th style={thR}>Pagado</th>}
                  </tr>
                </thead>
                <tbody>
                  {an.per_strategy.map((p) => (
                    <tr key={p.idx}>
                      <td style={tdTxt}>{p.name}</td>
                      <td style={tdNum}>{n(p.shorts, 0)}</td>
                      <td style={tdNum}>{n(p.packages, 0)}</td>
                      <td style={{ ...tdNum, color: p.pnl_pre_locates >= 0 ? color.profit : color.loss }}>{usd(p.pnl_pre_locates)}</td>
                      <td style={{ ...tdNum, color: color.textHigh }}>{p.breakeven_price == null ? "—" : `${n(p.breakeven_price, 2)} $`}</td>
                      {an.paid > 0 && <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.paid)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
              {curvaPrecio && (
                <div style={{ marginTop: 10 }}>
                  <LinesChart labels={curvaPrecio.labels} series={curvaPrecio.series} yFormat={(v) => usdCorto(v)} hoverFormat={(v) => `${n(v, 0)} $`} height={220} titulo="NETO SEGÚN EL PRECIO DEL PAQUETE (FIJO PARA TODOS)" />
                </div>
              )}
            </div>
            <div>
              {an.fade_buckets ? (
                <>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        <th style={thL}>Fade necesario</th>
                        <th style={thR}>Cortos</th>
                        <th style={thR}>Mov. medio</th>
                        <th style={thR}>Neto medio</th>
                        <th style={thR}>Neto total</th>
                        <th style={thR}>Win</th>
                      </tr>
                    </thead>
                    <tbody>
                      {an.fade_buckets.map((b, i) => (
                        <tr key={i}>
                          <td style={{ ...tdTxt, fontFamily: font.mono }}>{b.hi == null ? `> ${n(b.lo, 1)} %` : b.hi <= 0.001 ? "gratis (0 %)" : `${n(b.lo, 1)} – ${n(b.hi, 1)} %`}</td>
                          <td style={tdNum}>{n(b.n, 0)}</td>
                          <td style={tdNum}>{pct(b.move_pct, 2)}</td>
                          <td style={{ ...tdNum, color: b.net_mean >= 0 ? color.profit : color.loss, fontWeight: 600 }}>{usd(b.net_mean, 2)}</td>
                          <td style={{ ...tdNum, color: b.net_total >= 0 ? color.profit : color.loss }}>{usd(b.net_total)}</td>
                          <td style={{ ...tdNum, color: color.textMuted }}>{pct(b.win_pct, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {an.fade_rule && (
                    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
                      <thead>
                        <tr>
                          <th style={thL}>Puerta por EV fijo de</th>
                          <th style={thR}>Entran</th>
                          <th style={thR}>Neto estimado</th>
                          <th style={thL} />
                        </tr>
                      </thead>
                      <tbody>
                        {an.fade_rule.map((r) => {
                          const mejor = r.fade_max_pct === an.best_fade_max_pct;
                          const activa = gateActual?.mode === "ev_fixed" && gateActual.ev_fixed_pct === r.fade_max_pct;
                          return (
                            <tr key={r.fade_max_pct} style={{ background: mejor ? color.bgElevated : undefined }}>
                              <td style={{ ...tdTxt, fontFamily: font.mono, color: mejor ? color.copperText : color.textHigh }}>{n(r.fade_max_pct, 1)} %{activa ? " · en uso" : ""}</td>
                              <td style={tdNum}>{n(r.taken, 0)} de {n(an.shorts, 0)}</td>
                              <td style={{ ...tdNum, color: (r.net_est - (an.net_now ?? 0)) >= 0 ? color.profit : color.loss }}>{usd(r.net_est)}</td>
                              <td style={{ ...tdTxt, padding: "2px 6px" }}><Btn onClick={() => onUsarFade(r.fade_max_pct)} title="Poner este EV fijo como puerta en el paso 1 y volver a calcular (exacto)">usar</Btn></td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </>
              ) : (
                <Nota>Sin precio de locate (paso 1 en «sin locates») no hay fade que mirar: el precio de equilibrio y la curva valen igual; para los tramos y la regla, pon locates fijos o aleatorios y vuelve a calcular.</Nota>
              )}
            </div>
          </div>
        </Sec>
      )}

      <RangosLocatesCrudo base={out} evInicial={an?.best_fade_max_pct ?? evFijoActual} seedInicial={seedActual} correr={correrRango} />

      {bd && bandSeries && (
        <Sec title={`Banda de locates — ${n(bd.seeds, 0)} semillas`} help="Los mismos trades y los mismos paquetes alquilados, pero con el precio de cada acción-día sorteado con otra semilla, N veces (como la banda del Backtester: sin volver a simular). Dice cuánto del resultado depende de la suerte con el precio de los locates. La curva real es la de la semilla del paso 1; la banda va del percentil 5 al 95 de las semillas." sinRelleno>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", alignItems: "start" }}>
            <LinesChart labels={out.calendar} series={bandSeries.series} band={bandSeries.band} yFormat={(v) => `${n(v, 0)} %`} hoverFormat={(v) => `${n(v, 1)} %`} height={260} titulo="RETORNO SOBRE EL CAPITAL" />
            <div style={{ borderLeft: `1px solid ${color.border}`, alignSelf: "stretch", padding: "4px 10px" }}>
              <div style={{ display: "flex", flexWrap: "wrap" }}>
                <Stat label="Coste de locates" value={usd(bd.cost.p50)} sub={`p5 ${usdCorto(bd.cost.p05)} · p95 ${usdCorto(bd.cost.p95)} · real ${usdCorto(out.costs.locates)}`} tone="loss" />
                <Stat label="Balance final" value={usd(bd.final.p50)} sub={`p5 ${usdCorto(bd.final.p05)} · p95 ${usdCorto(bd.final.p95)}`} />
                <Stat label="Max DD" value={pct(bd.max_dd_pct.p50)} sub={`p5 ${pct(bd.max_dd_pct.p05)} · p95 ${pct(bd.max_dd_pct.p95)}`} tone="loss" />
              </div>
              <p style={{ margin: "6px 0 0", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                Si la banda es estrecha, el precio de los locates no decide el resultado; si es ancha, la estrategia vive del precio que le toque.
              </p>
            </div>
          </div>
        </Sec>
      )}
    </div>
  );
}
