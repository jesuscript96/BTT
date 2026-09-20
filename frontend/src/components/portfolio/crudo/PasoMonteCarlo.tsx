"use client";

// Paso 3 de «En crudo» (v3, 20-sep-2026): SOLO el Monte Carlo bootstrap del
// portfolio del paso 1, con sus datos clave, los recorridos, las
// distribuciones y una tabla de percentiles. Jaume: «el montecarlo bootstrap
// con sus datos clave y tabla. Nada más».

import React from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawCaminosOut, RawOut } from "@/lib/api_portfolio_lab";
import { CaminosLocates } from "./CaminosLocates";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Btn, Nota, Num, Sec, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { McResultado } from "./McResultado";

export interface MonteCarloModel {
  out: RawOut;
  mcOut: MonteCarloOut | null;
  mcSims: number | "";
  setMcSims: (v: number | "") => void;
  mcRunning: boolean;
  mcError: string | null;
  simularMc: () => void;
  // Caminos segun los locates (N simulaciones enteras con otra semilla)
  caminos: RawCaminosOut | null;
  caminosRunning: boolean;
  caminosError: string | null;
  seeds: number;
  setSeeds: (v: number) => void;
  rangosExtra: Array<[number, number]>;
  setRangosExtra: (v: Array<[number, number]>) => void;
  simularCaminos: () => void;
}

const PERCENTILES = ["p1", "p5", "p10", "p25", "p50", "p75", "p90", "p95", "p99"] as const;

function TablaPercentiles({ mcOut }: { mcOut: MonteCarloOut }) {
  const cols = PERCENTILES.filter((p) => mcOut.final_balance?.[p] != null || mcOut.drawdown?.[p] != null || mcOut.return_pct?.[p] != null);
  if (!cols.length) return null;
  const filas: Array<[string, (p: string) => string, string]> = [
    ["Balance final", (p) => usd(mcOut.final_balance?.[p]), `real ${usd(mcOut.base_final)}`],
    ["Retorno", (p) => pct(mcOut.return_pct?.[p]), `real ${pct(mcOut.base_return_pct)}`],
    ["Drawdown máximo", (p) => pct(mcOut.drawdown?.[p]), `real ${pct(mcOut.base_max_drawdown)}`],
  ];
  return (
    <Sec title="Percentiles" sinRelleno help="Cada columna es un percentil de los recorridos simulados: p5 = solo 1 de cada 20 recorridos queda por debajo (o, en drawdown, por encima); p50 = la mediana; p95 = solo 1 de cada 20 queda por encima. La última columna es lo que pasó de verdad.">
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thL} />
            {cols.map((p) => <th key={p} style={thR}>{p}</th>)}
            <th style={{ ...thR, color: color.copper }}>real</th>
          </tr>
        </thead>
        <tbody>
          {filas.map(([nombre, f, real]) => (
            <tr key={nombre}>
              <td style={tdTxt}>{nombre}</td>
              {cols.map((p) => <td key={p} style={tdNum}>{f(p)}</td>)}
              <td style={{ ...tdNum, color: color.copper }}>{real}</td>
            </tr>
          ))}
          <tr>
            <td style={tdTxt}>Probabilidades</td>
            <td colSpan={cols.length + 1} style={{ ...tdTxt, fontFamily: font.mono, color: color.textSecondary }}>
              acabar perdiendo {pct(mcOut.prob_losing_pct)} · ruina (−{n(mcOut.ruin_pct_threshold, 0)} %) {pct(mcOut.prob_ruin_pct)} · DD a tragar 1 de 20: {pct(mcOut.dd_tolerance?.p95)} · 1 de 100: {pct(mcOut.dd_tolerance?.p99)}
            </td>
          </tr>
        </tbody>
      </table>
    </Sec>
  );
}

export function PasoMonteCarlo({ m }: { m: MonteCarloModel }) {
  const { out, mcOut, mcSims, setMcSims, mcRunning, mcError, simularMc, caminos, caminosRunning, caminosError, seeds, setSeeds, rangosExtra, setRangosExtra, simularCaminos } = m;
  return (
    <div style={{ padding: "10px 10px 6px" }}>
      <Sec
        title="Monte Carlo bootstrap"
        help="Remuestrea los DÍAS del portfolio con reemplazo (un día puede salir dos veces y otro ninguna), no los trades: los de una misma sesión van correlacionados y no se separan. Cada día entra como su RETORNO (% del capital con el que empezó) y los recorridos se componen día a día. Con miles de recorridos sale la distribución del drawdown y del balance final. «DD a tragar (1 de 20)»: para que solo 1 de cada 20 recorridos lo supere, hay que aguantar ese drawdown."
        right={
          <>
            <div style={{ width: 80 }}><Num value={mcSims} onChange={setMcSims} min={500} max={20000} step={500} style={{ height: 24, fontSize: 11 }} /></div>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>recorridos</span>
            <Btn primary onClick={simularMc} disabled={mcRunning}>{mcRunning ? "Simulando…" : "Simular"}</Btn>
          </>
        }
      >
        {mcError && <ErrorBox>{mcError}</ErrorBox>}
        {!mcOut ? (
          <Nota>Pulsa <strong>Simular</strong>: {n(Number(mcSims) || 5000, 0)} recorridos de {n(out.calendar.length, 0)} días sobre la suma del paso 2.</Nota>
        ) : (
          <Nota>{n(mcOut.simulations, 0)} recorridos de {n(out.calendar.length, 0)} días sobre la suma del paso 2.</Nota>
        )}
      </Sec>
      {mcOut && <McResultado mcOut={mcOut} />}
      {mcOut && <TablaPercentiles mcOut={mcOut} />}
      <CaminosLocates m={{ out, caminos, running: caminosRunning, error: caminosError, seeds, setSeeds, rangosExtra, setRangosExtra, calcular: simularCaminos }} />
    </div>
  );
}
