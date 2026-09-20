"use client";

// Paso 4 de «En crudo», «Escalado» (20-sep-2026, tarde; Jaume: «metemos solo
// eso en la parte de escalado y ya está»). Dos bloques sobre el portfolio del
// paso 1:
//   A. Nivel de la cuenta por la caída: los % del paso 1 × un factor, y para
//      cada factor lo real y el Monte Carlo. Sirve para elegir el TOPE global.
//   B. Escalado automático: la rotación de pesos por ranking (con suelo) y el
//      freno por caída, con las cuatro curvas (fijo, solo rotación, solo
//      freno, las dos) y lo que toca poner el siguiente periodo.
// Lo que se probó y se quitó (Kelly por ventana, Kelly conjunta, Markowitz,
// tamaño por setup) está en docs/MEMORIA.md del 20-sep.

import React, { useMemo } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import type { RawBrakeIn, RawNivelesOut, RawOut, RawRotationIn } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Sec, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import { EscaladoAuto, type EscaladoAutoResultado } from "./EscaladoAuto";

export interface NivelModel {
  out: RawOut;
  nombres: string[];
  // A
  niveles: RawNivelesOut | null;
  nivelesRunning: boolean;
  nivelesError: string | null;
  calcularNiveles: () => void;
  // B
  pctBase: number[];
  rot: RawRotationIn;
  setRot: React.Dispatch<React.SetStateAction<RawRotationIn>>;
  brake: RawBrakeIn;
  setBrake: React.Dispatch<React.SetStateAction<RawBrakeIn>>;
  auto: EscaladoAutoResultado | null;
  autoRunning: boolean;
  autoError: string | null;
  autoStale: boolean;
  calcularAuto: () => void;
}

/** Retorno por año natural de una curva (equity al cierre de cada día). */
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

export function PasoNivel({ m }: { m: NivelModel }) {
  const { out, nombres, niveles, nivelesRunning, nivelesError, calcularNiveles, pctBase, rot, setRot, brake, setBrake, auto, autoRunning, autoError, autoStale, calcularAuto } = m;

  const totalBase = useMemo(() => out.per_strategy.map((p) => p.exec?.size_value ?? 0).reduce((a, b) => a + b, 0), [out]);

  return (
    <div style={{ padding: "10px 10px 6px" }}>
      {/* ── A. Nivel ─────────────────────────────────────────────────── */}
      <Sec
        title="A · Nivel de la cuenta por la caída (para elegir el tope)"
        help={
          <>
            Tus % del paso 1 (que suman <strong>{n(totalBase, 2)} %</strong> por trade) multiplicados por cada factor, con todo lo
            demás igual, y para cada uno: el final, la caída máxima real, el peor día y el Monte Carlo (bootstrap por días):
            la caída que hay que tragar para que solo 1 de 20 (p95) o 1 de 100 (p99) recorridos la superen.
            <br /><br />
            <strong>Cómo se lee:</strong> subir el nivel da más retorno y más caída casi en proporción; no hay un nivel «óptimo» por
            retorno. Se elige el mayor factor cuya DD p95 aguantas: ese es el tope global de la cuenta, y la suma que reparte
            el bloque B.
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

      {/* ── B. Escalado automatico ─────────────────────────────────── */}
      <EscaladoAuto m={{ out, nombres, pctBase, rot, setRot, brake, setBrake, auto, running: autoRunning, error: autoError, stale: autoStale, calcular: calcularAuto }} />
    </div>
  );
}
