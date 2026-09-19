"use client";

// Paso 2 de «En crudo»: la vision general del resultado de la suma. Una
// pestaña por vista para no apilar seis graficas: Resumen (cifras + curva y
// drawdown con su tabla), Exposicion, Por estrategia, Correlacion, Calendario.

import React, { useState } from "react";
import { color, font, hairline } from "@/components/ui/tokens";
import { CorrelationMatrix } from "../charts/CorrelationMatrix";
import type { RawOut } from "@/lib/api_portfolio_lab";
import { Nota, Sec, Stat, SubTabs, Toggle, colorSerie, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";
import { ExposureChart, PnlDdChart, type Serie } from "./CrudoCharts";
import { CalendarioCrudo } from "./CalendarioCrudo";

type Vista = "resumen" | "exposicion" | "estrategias" | "correlacion" | "calendario";

export interface VisionModel {
  out: RawOut;
  curvas: { pnl: Serie[]; dd: Serie[]; sumaMaxDd: number };
  propias: Array<{ dd: number[]; maxDd: number; pnlTotal: number }>;
  exposicion: { pct: number[]; max: number };
  yMode: "usd" | "pct";
  setYMode: (m: "usd" | "pct") => void;
}

export function PasoVision({ m }: { m: VisionModel }) {
  const { out, curvas, propias, exposicion, yMode, setYMode } = m;
  const [vista, setVista] = useState<Vista>("resumen");
  const met = out.metrics;
  const totalPnl = out.equity[out.equity.length - 1] - out.config.capital;
  const sep = { borderTop: `1px solid ${color.border}` };
  const costesTot = out.costs.fees + (out.costs.slippage || 0) + out.costs.locates + out.costs.expenses;
  const fmtY = (v: number) => (yMode === "usd" ? usdCorto(v) : `${n(v, 0)} %`);
  const fmtHover = (v: number) => (yMode === "usd" ? `${n(v, 0)} $` : `${n(v, 2)} %`);
  const lr = out.locates_report;

  return (
    <div>
      <SubTabs
        value={vista}
        onChange={setVista}
        options={[
          { value: "resumen", label: "Resumen" },
          { value: "exposicion", label: "Exposición" },
          { value: "estrategias", label: "Por estrategia" },
          { value: "correlacion", label: "Correlación" },
          { value: "calendario", label: "Calendario" },
        ]}
      />

      {vista === "resumen" && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 16px", padding: "4px 0 8px" }}>
            <Stat big label="Retorno neto" value={pct(met.total_return_pct)} sub={usd(totalPnl)} tone={met.total_return_pct >= 0 ? "profit" : "loss"} />
            <Stat label="CAGR" value={pct(met.cagr_pct)} />
            <Stat label="Max DD" value={pct(curvas.sumaMaxDd)} sub={`${met.longest_dd_days} días el más largo`} tone="loss" />
            <Stat label="Sharpe" value={n(met.sharpe)} sub={`Sortino ${n(met.sortino)} · Calmar ${n(met.calmar)}`} />
            <Stat label="Trades" value={n(met.n_trades, 0)} sub={`win ${pct(met.win_rate)} · PF ${n(met.profit_factor)}`} />
            <Stat label="En posiciones a la vez (máx.)" value={`${n(exposicion.max, 0)} %`} sub={`del capital del día · hasta ${usd(out.exposure.max_usd)} · ${Math.max(0, ...out.exposure.max_open_daily)} posiciones`} tone={exposicion.max > 100 ? "warning" : undefined} help="El mayor porcentaje del capital del día que llegó a estar metido en posiciones abiertas simultáneamente, sumando todas (medido al minuto: un trade de premercado y uno de RTH no coinciden si no se solapan)." />
            <Stat label="Costes" value={usd(costesTot)} sub={`comis. ${usd(out.costs.fees)} · slippage ${usd(out.costs.slippage || 0)} · locates ${usd(out.costs.locates)} · fijos ${usd(out.costs.expenses)}`} tone="loss" />
            {out.cap_report.skipped > 0 && <Stat label="Fuera por el tope" value={n(out.cap_report.skipped, 0)} sub={`trades de ${n(out.cap_report.taken + out.cap_report.skipped, 0)}`} tone="warning" />}
            {out.margin_report && <Stat label="Margen y BP" value={`${n(out.margin_report.skipped + out.margin_report.trimmed, 0)} trades`} sub={`fuera/recortados por margen · pico medio ${n(out.margin_report.pico_medio_pct, 0)} %, máx ${n(out.margin_report.pico_max_pct, 0)} % de la capacidad`} help={`Trades que no cupieron en el margen del bróker (${out.margin_report.broker}) en su momento: cada posición abierta consume margen según su precio y lado (cortos por debajo de 2,50 $: 2,50 $ por acción), contra el equity del día. El pico es cuánto de esa capacidad llegó a usarse en el peor momento de cada día.`} tone={(out.margin_report.skipped + out.margin_report.trimmed) > 0 ? "warning" : undefined} />}
            {(out.cap_report.blocked || 0) > 0 && <Stat label="Bloqueadas" value={n(out.cap_report.blocked, 0)} sub="señales con otra estrategia ya dentro" help="Trades de las corridas que no entran porque otra estrategia ya tenía posición abierta en esa acción (opción «una a la vez por acción»)." tone="warning" />}
            {lr && lr.mode !== "none" && lr.mode !== "per_row" && (
              <Stat label="Locates" value={usd(lr.cost)} sub={`${n(lr.packages, 0)} paquetes en ${n(lr.ticker_days, 0)} acción-días${lr.shared ? ` · ${n(lr.gate_free, 0)} entradas gratis` : ""}`} help="Paquetes de 100 alquilados y lo que costaron. «Entradas gratis»: cortos que cabían en lo ya alquilado ese día por otra estrategia (o por una reentrada) y no pagaron nada." />
            )}
            {lr && lr.gate && <Stat label="Fuera por la puerta" value={n(lr.gate_out, 0)} sub="cortos cuyo EV no pagaba el locate" tone="warning" />}
          </div>
          {out.ruined && <Nota tone="loss">La cuenta llegó a cero antes del final: a partir de ahí no se abre ningún trade más.</Nota>}
          {met.total_return_pct > 100000 && (
            <Nota tone="warning">Un R en % del capital compone cada día: con varios trades al día y PF &gt; 1 la cifra se dispara y deja de decir nada. Baja el %, ponlo en $ fijos, o acorta el periodo.</Nota>
          )}
          {out.cap_report.unsized > 0 && <Nota tone="warning">{out.cap_report.unsized} trades sin tamaño o precio válidos se han dejado fuera.</Nota>}

          <Sec
            title="PnL acumulado y drawdown — cada estrategia y la suma"
            help="Arriba, el PnL acumulado: una línea por estrategia y la suma en cobre, sobre el mismo calendario (un día sin operar arrastra el valor anterior). Abajo, el drawdown: el de la suma es el normal (caída desde su máximo); el de cada estrategia es su pérdida desde su máximo relativa al capital que había ese día en la cuenta, que es lo que pesa cuando varias comparten cuenta. Las etiquetas del borde derecho son el valor final."
            right={<div style={{ width: 90 }}><Toggle value={yMode} onChange={setYMode} options={[{ value: "usd", label: "$" }, { value: "pct", label: "%" }]} /></div>}
            sinRelleno
          >
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: 0, alignItems: "start" }}>
              <PnlDdChart labels={out.calendar} pnl={curvas.pnl} dd={curvas.dd} yFormat={fmtY} hoverFormat={fmtHover} height={430} />
              <div style={{ borderLeft: `1px solid ${color.border}`, alignSelf: "stretch" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={thL}>Serie</th>
                      <th style={thR}>PnL</th>
                      <th style={thR}>Retorno</th>
                      <th style={thR}>Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {out.per_strategy.map((p, i) => (
                      <tr key={p.strategy_id}>
                        <td style={{ ...tdTxt, maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis" }} title={p.name}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><span style={{ width: 9, height: 9, background: colorSerie(i), display: "inline-block", flexShrink: 0 }} />{p.name}</span>
                        </td>
                        <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{usdCorto(p.totals.pnl_net)}</td>
                        <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{pct((p.totals.pnl_net / out.config.capital) * 100, 0)}</td>
                        <td style={{ ...tdNum, color: color.loss }}>{pct(propias[i]?.maxDd)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td style={{ ...tdTxt, ...sep, color: color.copper, fontWeight: 600 }}>Suma</td>
                      <td style={{ ...tdNum, ...sep, color: totalPnl >= 0 ? color.profit : color.loss }}>{usdCorto(totalPnl)}</td>
                      <td style={{ ...tdNum, ...sep, color: met.total_return_pct >= 0 ? color.profit : color.loss }}>{pct(met.total_return_pct, 0)}</td>
                      <td style={{ ...tdNum, ...sep, color: color.loss }}>{pct(curvas.sumaMaxDd)}</td>
                    </tr>
                  </tbody>
                </table>
                <p style={{ margin: 0, padding: "8px 10px", fontSize: 10, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                  Todo sobre el capital del portfolio ({usd(out.config.capital)}): el retorno de cada estrategia es lo que aporta.
                </p>
              </div>
            </div>
          </Sec>
        </>
      )}

      {vista === "exposicion" && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 380px", gap: 14, alignItems: "start" }}>
          <Sec title="En posiciones a la vez — % del capital del día" help="La suma de los nocionales (acciones × precio de entrada) de todos los trades abiertos en el mismo instante, de todas las estrategias, partida por el capital con el que empezó ese día la suma. Se mide al minuto: un trade de premercado que cierra a las 09:29 y uno de RTH que abre a las 09:35 no cuentan a la vez. Por encima del 100 % hace falta margen." sinRelleno>
            <ExposureChart labels={out.calendar} pct={exposicion.pct} usd={out.exposure.peak_daily} maxOpen={out.exposure.max_open_daily} height={260} />
          </Sec>
          <Sec title="Lectura">
            <Nota>
              Con un 4 % por trade y 7 trades abiertos a la vez (de la estrategia que sea) el día marca 28 %. Es el dato
              para el tope de exposición y para repartir el capital.
            </Nota>
            <div style={{ display: "flex", flexWrap: "wrap" }}>
              <Stat label="Máximo" value={`${n(exposicion.max, 0)} %`} sub={`${usd(out.exposure.max_usd)} en posiciones`} tone={exposicion.max > 100 ? "warning" : undefined} />
              <Stat label="Días por encima del 100 %" value={n(exposicion.pct.filter((v) => v > 100).length, 0)} sub={`de ${n(out.calendar.length, 0)} operados`} />
              <Stat label="Posiciones a la vez (máx.)" value={n(Math.max(0, ...out.exposure.max_open_daily), 0)} />
            </div>
          </Sec>
        </div>
      )}

      {vista === "estrategias" && (
        <Sec title="Por estrategia" help="Cada una con la ejecución fijada en el paso 1. Retorno y drawdown sobre el capital del portfolio (el retorno es lo que aporta); Sharpe y Sortino sobre sus propios días. «Aporta»: su parte del PnL total (solo cuando el conjunto gana). «Nocional medio»: el valor medio con el que entró cada trade. «Locates»: lo que pagó esta estrategia (con locates compartidos, solo los paquetes de más que provocó). La R de cada trade es neto / (distancia inicial al stop × acciones); «stop ≈» cuenta los trades en que la distancia inicial no se pudo recuperar y se usó el último stop guardado." sinRelleno>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thL}>Estrategia</th>
                <th style={thL}>Ejecución</th>
                <th style={thR}>Trades</th>
                <th style={thR}>Win</th>
                <th style={thR}>PF</th>
                <th style={thR}>PnL neto</th>
                <th style={thR}>Aporta</th>
                <th style={thR}>Retorno</th>
                <th style={thR}>Max DD</th>
                <th style={thR}>Sharpe</th>
                <th style={thR}>Sortino</th>
                <th style={thR}>Nocional medio</th>
                <th style={thR}>Comis.</th>
                <th style={thR}>Slippage</th>
                <th style={thR}>Locates</th>
                {lr?.shared && <th style={thR}>Gratis</th>}
                {lr?.gate && <th style={thR}>Puerta</th>}
                <th style={thR}>stop ≈</th>
                {out.config.one_per_ticker && <th style={thR}>Bloqueadas</th>}
              </tr>
            </thead>
            <tbody>
              {out.per_strategy.map((p, i) => {
                const e = p.exec;
                const ej = !e ? "—" : e.sizing === "as_saved" ? "tal cual" : `R ${n(e.size_value, e.size_unit === "pct" ? 2 : 0)} ${e.size_unit === "pct" ? "%" : "$"} ${e.sizing === "risk" ? "por SL" : "por capital"}`;
                return (
                  <tr key={p.strategy_id}>
                    <td style={tdTxt}><span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><span style={{ width: 10, height: 10, background: colorSerie(i), display: "inline-block" }} />{p.name}</span></td>
                    <td style={{ ...tdTxt, fontFamily: font.mono, color: color.textSecondary }}>{ej}</td>
                    <td style={tdNum}>{n(p.totals.n_trades, 0)}</td>
                    <td style={tdNum}>{pct(p.totals.win_rate)}</td>
                    <td style={tdNum}>{n(p.totals.profit_factor)}</td>
                    <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{usd(p.totals.pnl_net)}</td>
                    <td style={tdNum} title={totalPnl > 0 ? "parte del PnL total que pone esta estrategia" : "el conjunto no gana: no hay reparto que enseñar"}>{totalPnl > 0 ? pct((p.totals.pnl_net / totalPnl) * 100, 0) : "—"}</td>
                    <td style={{ ...tdNum, color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{pct((p.totals.pnl_net / out.config.capital) * 100)}</td>
                    <td style={{ ...tdNum, color: color.loss }}>{pct(propias[i]?.maxDd)}</td>
                    <td style={tdNum}>{n(p.metrics?.sharpe)}</td>
                    <td style={tdNum}>{n(p.metrics?.sortino)}</td>
                    <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.avg_notional)}</td>
                    <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.fees)}</td>
                    <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.slippage || 0)}</td>
                    <td style={{ ...tdNum, color: color.textMuted }}>{usd(p.totals.locates)}</td>
                    {lr?.shared && <td style={{ ...tdNum, color: color.textMuted }}>{n(p.cap_report.gate_free || 0, 0)}</td>}
                    {lr?.gate && <td style={{ ...tdNum, color: (p.cap_report.gate_out || 0) > 0 ? color.warning : color.textMuted }}>{n(p.cap_report.gate_out || 0, 0)}</td>}
                    <td style={{ ...tdNum, color: color.textMuted }} title={`${n(p.totals.sin_stop || 0, 0)} sin stop guardado (R = 0)`}>{n(p.totals.stop_aprox || 0, 0)}</td>
                    {out.config.one_per_ticker && <td style={{ ...tdNum, color: (p.cap_report.blocked || 0) > 0 ? color.warning : color.textMuted }}>{n(p.cap_report.blocked || 0, 0)}</td>}
                  </tr>
                );
              })}
              <tr>
                <td style={{ ...tdTxt, ...sep, color: color.copper, fontWeight: 600 }}>Suma</td>
                <td style={{ ...tdTxt, ...sep, fontFamily: font.mono, color: color.textMuted }}>{out.calendar[0]} → {out.calendar[out.calendar.length - 1]}</td>
                <td style={{ ...tdNum, ...sep }}>{n(met.n_trades, 0)}</td>
                <td style={{ ...tdNum, ...sep }}>{pct(met.win_rate)}</td>
                <td style={{ ...tdNum, ...sep }}>{n(met.profit_factor)}</td>
                <td style={{ ...tdNum, ...sep, color: totalPnl >= 0 ? color.profit : color.loss }}>{usd(totalPnl)}</td>
                <td style={{ ...tdNum, ...sep }}>{totalPnl > 0 ? "100 %" : "—"}</td>
                <td style={{ ...tdNum, ...sep, color: met.total_return_pct >= 0 ? color.profit : color.loss }}>{pct(met.total_return_pct)}</td>
                <td style={{ ...tdNum, ...sep, color: color.loss }}>{pct(curvas.sumaMaxDd)}</td>
                <td style={{ ...tdNum, ...sep }}>{n(met.sharpe)}</td>
                <td style={{ ...tdNum, ...sep }}>{n(met.sortino)}</td>
                <td style={{ ...tdNum, ...sep }} />
                <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{usd(out.costs.fees)}</td>
                <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{usd(out.costs.slippage || 0)}</td>
                <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{usd(out.costs.locates)}</td>
                {lr?.shared && <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{n(lr.gate_free, 0)}</td>}
                {lr?.gate && <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{n(lr.gate_out, 0)}</td>}
                <td style={{ ...tdNum, ...sep }} />
                {out.config.one_per_ticker && <td style={{ ...tdNum, ...sep, color: color.textMuted }}>{n(out.cap_report.blocked || 0, 0)}</td>}
              </tr>
            </tbody>
          </table>
          {out.locates_random && out.locates_random.n > 0 && (
            <p style={{ margin: 0, padding: "6px 10px", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, borderTop: hairline }}>
              Locates sorteados: {n(out.locates_random.n, 0)} acción-días · mediana {n(out.locates_random.p50, 2)} $ por paquete de 100 (p10 {n(out.locates_random.p10, 2)} · p90 {n(out.locates_random.p90, 2)}).
            </p>
          )}
        </Sec>
      )}

      {vista === "correlacion" && (
        <Sec title="Correlación del PnL diario" help="Entre parejas, solo en el tramo en que ambas tienen trades. Por debajo de 0,3 diversifican de verdad; por encima de 0,7 son la misma apuesta dos veces.">
          {out.correlation ? (
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 24, alignItems: "start" }}>
              <CorrelationMatrix corr={out.correlation} names={out.per_strategy.map((p) => p.name)} />
              <div style={{ display: "flex", flexWrap: "wrap", marginTop: 6 }}>
                <Stat label="Media de parejas" value={out.correlation.avg_pairwise == null ? "—" : n(out.correlation.avg_pairwise)} tone={out.correlation.avg_pairwise == null ? undefined : out.correlation.avg_pairwise > 0.7 ? "loss" : out.correlation.avg_pairwise > 0.3 ? "warning" : "profit"} />
                {out.correlation.max_pair && (
                  <Stat label="Pareja más correlacionada" value={n(out.correlation.max_pair.corr)} sub={`${out.per_strategy[out.correlation.max_pair.i]?.name} · ${out.per_strategy[out.correlation.max_pair.j]?.name}`} />
                )}
              </div>
            </div>
          ) : (
            <Nota>Hacen falta al menos dos estrategias.</Nota>
          )}
        </Sec>
      )}

      {vista === "calendario" && (
        <Sec title="Calendario de la suma" help="El mismo calendario del Backtester, sobre el resultado del conjunto: Profits (bruto, antes de costes), Gastos (comisiones + slippage + locates + gastos fijos) y Profits − Gastos, en $ o en R. Pulsa un día para ver sus trades por estrategia.">
          <div style={{ padding: "8px 0 4px" }}>
            <CalendarioCrudo out={out} names={out.per_strategy.map((p) => p.name)} />
          </div>
        </Sec>
      )}
    </div>
  );
}
