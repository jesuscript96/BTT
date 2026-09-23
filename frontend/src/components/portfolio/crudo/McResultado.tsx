"use client";

// Tarjetas del Monte Carlo bootstrap sobre una curva diaria (la suma del paso
// 2). Los graficos (recorridos y distribuciones) los coloca PasoMonteCarlo en
// la fila de tres, al lado de los caminos por locates (Jaume, 20-sep: «no
// quiero un grafico tan masivamente grande»).

import React from "react";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Stat, pct, usd, usdCorto } from "./hoja";

export function McTarjetas({ mcOut }: { mcOut: MonteCarloOut }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
      <Stat label="DD mediano" value={pct(mcOut.drawdown?.p50)} tone="loss" sub={`real ${pct(mcOut.base_max_drawdown)}`} />
      <Stat big label="DD a tragar (1 de 20)" value={pct(mcOut.dd_tolerance?.p95)} tone="loss" help="Para que solo 1 de cada 20 escenarios lo supere, hay que aguantar este drawdown." />
      <Stat label="DD a tragar (1 de 100)" value={pct(mcOut.dd_tolerance?.p99)} tone="loss" />
      <Stat label="Acabar perdiendo" value={pct(mcOut.prob_losing_pct)} sub="probabilidad" />
      <Stat label="Ruina (−50 %)" value={pct(mcOut.prob_ruin_pct)} sub="probabilidad" />
      <Stat label="Balance mediano" value={usd(mcOut.final_balance?.p50)} sub={`p5 ${usdCorto(mcOut.final_balance?.p5 ?? NaN)} · p95 ${usdCorto(mcOut.final_balance?.p95 ?? NaN)}`} />
    </div>
  );
}
