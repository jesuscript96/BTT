"use client";

// Paso 3 de «En crudo» (v3/v4, 20-sep-2026): el Monte Carlo bootstrap del
// portfolio del paso 1 (datos clave y tabla de percentiles) y los caminos de la
// simulación según los locates (N simulaciones enteras con otra semilla). Los
// tres gráficos van en una fila, el de los caminos el más grande, a tamaño
// real (Jaume: «no quiero un gráfico tan masivamente grande; tres, uno al lado
// del otro, siendo el de los caminos el más grande»).

import React, { useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { SpaghettiChart, DistributionChart } from "@/components/robustez/charts/MonteCarloCharts";
import { useAncho } from "@/components/backtester/tabs/edge/charts";
import type { RawCaminosOut, RawOut } from "@/lib/api_portfolio_lab";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { Btn, Nota, Num, Sec, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { McTarjetas } from "./McResultado";
import { CaminosLocates, seriesCaminos } from "./CaminosLocates";
import { LinesChart } from "./CrudoCharts";

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

/** Una celda de la fila de gráficos que mide su ancho para dibujar a tamaño real. */
function Celda({ children, titulo }: { children: (ancho: number) => React.ReactNode; titulo: string }) {
  const [ref, ancho] = useAncho(420);
  return (
    <div ref={ref} style={{ minWidth: 0 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.textMuted, fontFamily: font.sans, marginBottom: 4 }}>{titulo}</div>
      {children(ancho)}
    </div>
  );
}

export function PasoMonteCarlo({ m }: { m: MonteCarloModel }) {
  const { out, mcOut, mcSims, setMcSims, mcRunning, mcError, simularMc, caminos, caminosRunning, caminosError, seeds, setSeeds, rangosExtra, setRangosExtra, simularCaminos } = m;
  const [sel, setSel] = useState(0);
  const gc = caminos ? seriesCaminos(caminos, sel, out) : null;
  const vacio = (txt: string) => <div style={{ border: `1px dashed ${color.border}`, padding: 14, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, textAlign: "center" }}>{txt}</div>;

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
          <>
            <Nota>{n(mcOut.simulations, 0)} recorridos de {n(out.calendar.length, 0)} días sobre la suma del paso 2.</Nota>
            <McTarjetas mcOut={mcOut} />
          </>
        )}
      </Sec>

      <CaminosLocates m={{ out, caminos, running: caminosRunning, error: caminosError, seeds, setSeeds, rangosExtra, setRangosExtra, calcular: simularCaminos, sel, setSel }} />

      {/* La fila de tres graficos: caminos (el grande), recorridos, distribuciones. */}
      <Sec title="Gráficos" sinRelleno help="A la izquierda, los caminos según los locates (banda p05–p95, mediana, y tu semilla en cobre; pulsa una fila de la tabla de arriba para cambiar de rango). En medio, una muestra de recorridos del bootstrap con sus bandas y la curva real. A la derecha, la distribución del balance final y la del drawdown máximo de los recorridos, con el valor real marcado.">
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr)", gap: 12, alignItems: "start", padding: "8px 10px 10px" }}>
          <Celda titulo={gc ? `Caminos según los locates · rango ${n(gc.rango.lo, 2)}–${n(gc.rango.hi, 2)} $` : "Caminos según los locates"}>
            {() => gc && caminos ? (
              <LinesChart labels={caminos.calendar} series={gc.series} band={gc.band} yFormat={(v) => `${n(v, 0)} %`} hoverFormat={(v) => `${n(v, 1)} %`} height={300} titulo="RETORNO SOBRE EL CAPITAL" />
            ) : vacio("Simula los caminos (arriba) para ver la banda.")}
          </Celda>
          <Celda titulo="Recorridos del bootstrap">
            {(ancho) => mcOut ? (
              <SpaghettiChart spaghetti={mcOut.spaghetti} bands={mcOut.bands} baseCurve={mcOut.base_curve} initCash={mcOut.init_cash} xLabel="días →" width={Math.max(260, ancho - 26)} height={300} caption="Líneas tenues: recorridos; bandas: p5–p95 y p25–p75; cobre: lo real." />
            ) : vacio("Simula el bootstrap para ver los recorridos.")}
          </Celda>
          <Celda titulo="Distribuciones">
            {(ancho) => mcOut ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <DistributionChart hist={mcOut.hist_final} markers={[{ value: mcOut.base_final, label: `real ${usd(mcOut.base_final)}`, color: "var(--color-ec-copper)" }]} caption="Balance final de cada recorrido" width={Math.max(260, ancho - 26)} height={130} />
                <DistributionChart hist={mcOut.hist_drawdown} markers={[{ value: mcOut.base_max_drawdown, label: `real ${pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]} fmtValue={(v: number) => pct(v)} caption="Drawdown máximo de cada recorrido" width={Math.max(260, ancho - 26)} height={130} />
              </div>
            ) : vacio("Simula el bootstrap para ver las distribuciones.")}
          </Celda>
        </div>
      </Sec>

      {mcOut && <TablaPercentiles mcOut={mcOut} />}
    </div>
  );
}
