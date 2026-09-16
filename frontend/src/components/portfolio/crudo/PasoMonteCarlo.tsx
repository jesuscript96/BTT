"use client";

// Paso 3 de «En crudo»: limites de perdida. Lo historico (lo que ya paso en
// la serie real) y el Monte Carlo bootstrap de los dias del conjunto (lo que
// podria pasar con la misma suerte en otro orden). Y, con locates aleatorios,
// la banda de semillas: cuanto del resultado depende del precio de los locates.

import React, { useMemo } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { SpaghettiChart, DistributionChart } from "@/components/robustez/charts/MonteCarloCharts";
import type { RawOut } from "@/lib/api_portfolio_lab";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Btn, Nota, Num, Sec, Stat, Toggle, n, pct, tdNum, tdTxt, thL, thR, usd, usdCorto } from "./hoja";
import { LinesChart } from "./CrudoCharts";
import { limitesHistoricos } from "./modelo";

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
}

export function PasoMonteCarlo({ m }: { m: MonteCarloModel }) {
  const { out, mcOut, mcSims, setMcSims, mcMethod, setMcMethod, mcRunning, mcError, simularMc } = m;
  const cap = out.config.capital;
  const hist = useMemo(() => limitesHistoricos(out.daily_pnl, out.equity, cap), [out, cap]);
  const bd = out.locates_band;
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
              <Stat label="DD mediano" value={pct(mcOut.drawdown?.p50)} tone="loss" sub={`real ${pct(mcOut.base_max_drawdown)}`} />
              <Stat big label="DD a tragar (1 de 20)" value={pct(mcOut.dd_tolerance?.p95)} tone="loss" help="Para que solo 1 de cada 20 escenarios lo supere, hay que aguantar este drawdown." />
              <Stat label="DD a tragar (1 de 100)" value={pct(mcOut.dd_tolerance?.p99)} tone="loss" />
              <Stat label="Acabar perdiendo" value={pct(mcOut.prob_losing_pct)} sub="probabilidad" />
              <Stat label="Ruina (−50 %)" value={pct(mcOut.prob_ruin_pct)} sub="probabilidad" />
              <Stat label="Balance mediano" value={usd(mcOut.final_balance?.p50)} sub={`p5 ${usdCorto(mcOut.final_balance?.p5 ?? NaN)} · p95 ${usdCorto(mcOut.final_balance?.p95 ?? NaN)}`} />
            </div>
          )}
        </Sec>
      </div>

      {mcOut && (
        <Sec title="Recorridos y distribuciones" sinRelleno help="Arriba, una muestra de recorridos simulados con la banda y la curva real en cobre. Abajo, la distribución del balance final y la del drawdown máximo, con el valor real marcado.">
          <div style={{ padding: "6px 10px 10px", display: "flex", flexDirection: "column", gap: 12 }}>
            <SpaghettiChart spaghetti={mcOut.spaghetti} bands={mcOut.bands} baseCurve={mcOut.base_curve} initCash={mcOut.init_cash} xLabel="días →" />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
              <DistributionChart hist={mcOut.hist_final} markers={[{ value: mcOut.base_final, label: `real ${usd(mcOut.base_final)}`, color: "var(--color-ec-copper)" }]} caption="Balance final de cada recorrido" />
              <DistributionChart hist={mcOut.hist_drawdown} markers={[{ value: mcOut.base_max_drawdown, label: `real ${pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]} fmtValue={(v: number) => pct(v)} caption="Drawdown máximo de cada recorrido" />
            </div>
          </div>
        </Sec>
      )}

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
