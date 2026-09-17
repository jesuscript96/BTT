"use client";

// Resultado de un Monte Carlo bootstrap sobre una curva diaria (la suma del
// paso 2 o la escalada del paso 4): tarjetas, recorridos y distribuciones.
// Un solo componente para no tener dos copias que se separen.

import React from "react";
import { SpaghettiChart, DistributionChart } from "@/components/robustez/charts/MonteCarloCharts";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Sec, Stat, pct, usd, usdCorto } from "./hoja";

export function McResultado({ mcOut, titulo }: { mcOut: MonteCarloOut; titulo?: string }) {
  return (
    <>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
        <Stat label="DD mediano" value={pct(mcOut.drawdown?.p50)} tone="loss" sub={`real ${pct(mcOut.base_max_drawdown)}`} />
        <Stat big label="DD a tragar (1 de 20)" value={pct(mcOut.dd_tolerance?.p95)} tone="loss" help="Para que solo 1 de cada 20 escenarios lo supere, hay que aguantar este drawdown." />
        <Stat label="DD a tragar (1 de 100)" value={pct(mcOut.dd_tolerance?.p99)} tone="loss" />
        <Stat label="Acabar perdiendo" value={pct(mcOut.prob_losing_pct)} sub="probabilidad" />
        <Stat label="Ruina (−50 %)" value={pct(mcOut.prob_ruin_pct)} sub="probabilidad" />
        <Stat label="Balance mediano" value={usd(mcOut.final_balance?.p50)} sub={`p5 ${usdCorto(mcOut.final_balance?.p5 ?? NaN)} · p95 ${usdCorto(mcOut.final_balance?.p95 ?? NaN)}`} />
      </div>
      <Sec title={titulo ?? "Recorridos y distribuciones"} sinRelleno help="Arriba, una muestra de recorridos simulados con la banda y la curva real en cobre. Abajo, la distribución del balance final y la del drawdown máximo, con el valor real marcado.">
        <div style={{ padding: "6px 10px 10px", display: "flex", flexDirection: "column", gap: 12 }}>
          <SpaghettiChart spaghetti={mcOut.spaghetti} bands={mcOut.bands} baseCurve={mcOut.base_curve} initCash={mcOut.init_cash} xLabel="días →" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
            <DistributionChart hist={mcOut.hist_final} markers={[{ value: mcOut.base_final, label: `real ${usd(mcOut.base_final)}`, color: "var(--color-ec-copper)" }]} caption="Balance final de cada recorrido" />
            <DistributionChart hist={mcOut.hist_drawdown} markers={[{ value: mcOut.base_max_drawdown, label: `real ${pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]} fmtValue={(v: number) => pct(v)} caption="Drawdown máximo de cada recorrido" />
          </div>
        </div>
      </Sec>
    </>
  );
}
