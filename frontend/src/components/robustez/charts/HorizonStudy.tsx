"use client";

/**
 * Probabilidad de ruina y de alcanzar un objetivo DENTRO de X sesiones.
 *
 * NO es una prueba de fondeo y no debe presentarse como tal (se llamo asi al
 * nacer y confundio): aqui el suelo es FIJO — un % por debajo del capital
 * inicial — y no hay limite de perdida diaria ni drawdown trailing. Con la
 * misma corrida, este bloque daba 70% de exito donde `FundingSection` daba 17%,
 * y las dos cifras eran correctas: no contestan la misma pregunta. Si algun dia
 * se quiere comparabilidad real, hay que traerse esas dos reglas.
 *
 * Lo que aporta frente al bloque de escenarios: alli el `prob_ruin_pct` se mide
 * sobre el horizonte COMPLETO del backtest, que no elige el usuario. Aqui el
 * horizonte es la variable.
 *
 * Se calcula UNA vez hasta el tope y el deslizador lee la curva ya en memoria,
 * sin volver a llamar al backend en cada movimiento.
 *
 * Se remuestrea por SESION, igual que la prueba de fondeo: un challenge se
 * juega con limites diarios, asi que remuestrear trades sueltos no responde a
 * la pregunta.
 *
 * ESTILO: mismo criterio que `MonteCarloExtras` — nada de tarjetas, cifras
 * sobre el fondo y las explicaciones dentro de un `?`.
 */

import { useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox, Field, NumberInput, ReadingNote, RunButton, fmt } from "../shared";
import { Help } from "../help";
import { InlineStats } from "@/components/portfolio/StatSheet";
import { runRobustezHorizon, type HorizonOut } from "@/lib/api_robustez";

interface HorizonCfg {
  horizonte: number; // hasta cuantas sesiones se simula
  objetivoPct: number;
  ruinaPct: number;
  sims: number;
}

const DEFAULT_HORIZON: HorizonCfg = {
  horizonte: 250, // ~1 año de sesiones
  objetivoPct: 8,
  ruinaPct: 20,
  sims: 5000,
};

/** Las dos curvas acumuladas, con marcador vertical en el dia elegido. */
function HorizonChart({ out, dia }: { out: HorizonOut; dia: number }) {
  const W = 660;
  const H = 156;
  const L = 32;
  const B = 18;
  const T = 8;
  const R = 8;
  const n = out.days.length;
  const px = (i: number) => L + (i / Math.max(1, n - 1)) * (W - L - R);
  const py = (v: number) => T + (1 - v / 100) * (H - T - B);
  const traza = (serie: number[]) =>
    serie.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join("");

  const i = Math.min(n - 1, Math.max(0, dia - 1));
  const series = [
    { d: out.prob_target_alive_pct, c: color.profit, label: "objetivo" },
    { d: out.prob_ruin_pct, c: color.loss, label: "ruina" },
  ];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {[0, 25, 50, 75, 100].map((g) => (
        <g key={g}>
          <line x1={L} x2={W - R} y1={py(g)} y2={py(g)} stroke={color.border} strokeWidth="0.5" />
          <text
            x={L - 5}
            y={py(g) + 3}
            textAnchor="end"
            fontSize="8"
            fill={color.textMuted}
            fontFamily="var(--color-ec-mono)"
          >
            {g}%
          </text>
        </g>
      ))}
      {/* Marcador del dia consultado: ata la curva a las cifras de arriba. */}
      <line
        x1={px(i)}
        x2={px(i)}
        y1={T}
        y2={H - B}
        stroke={color.copper}
        strokeWidth="1"
        strokeDasharray="3 2"
      />
      {series.map((s) => (
        <path key={s.label} d={traza(s.d)} fill="none" stroke={s.c} strokeWidth="1.4" />
      ))}
      {series.map((s) => (
        <circle key={s.label} cx={px(i)} cy={py(s.d[i] ?? 0)} r="2.6" fill={s.c} />
      ))}
      <text x={L} y={H - 5} fontSize="8" fill={color.textMuted} fontFamily="var(--color-ec-mono)">
        1
      </text>
      <text
        x={W - R}
        y={H - 5}
        textAnchor="end"
        fontSize="8"
        fill={color.textMuted}
        fontFamily="var(--color-ec-mono)"
      >
        {out.max_days} sesiones
      </text>
    </svg>
  );
}

export function HorizonStudy({
  valoresDia,
  initCash,
  riskPct,
  esPct,
}: {
  /** Serie por SESION. Vacia = no hay corrida utilizable. */
  valoresDia: number[];
  initCash: number;
  riskPct: number;
  /** true = R-multiplos (compuesto); false = PnL en $ (aditivo). */
  esPct: boolean;
}) {
  const [abierto, setAbierto] = useState(false);
  const [cfg, setCfg] = useState<HorizonCfg>(DEFAULT_HORIZON);
  const [dia, setDia] = useState(30);
  const [out, setOut] = useState<HorizonOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ranCfg, setRanCfg] = useState<string | null>(null);

  const set = <K extends keyof HorizonCfg>(k: K, v: HorizonCfg[K]) =>
    setCfg((c) => ({ ...c, [k]: v }));

  const cfgKey = JSON.stringify(cfg);
  const stale = !!out && ranCfg !== null && ranCfg !== cfgKey && !busy;

  const lanzar = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await runRobustezHorizon({
        values: valoresDia,
        init_cash: initCash,
        simulations: cfg.sims,
        mode: esPct ? "compound" : "additive",
        risk_pct: riskPct,
        ruin_pct: cfg.ruinaPct,
        target_pct: cfg.objetivoPct,
        max_days: cfg.horizonte,
        seed: null,
      });
      setOut(res);
      setRanCfg(cfgKey);
      setDia((d) => Math.min(d, res.max_days));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Fallo el estudio de horizonte");
      setOut(null);
    } finally {
      setBusy(false);
    }
  };

  const i = out ? Math.min(out.days.length - 1, Math.max(0, dia - 1)) : 0;
  const pRuina = out ? out.prob_ruin_pct[i] ?? 0 : 0;
  const pObjetivo = out ? out.prob_target_alive_pct[i] ?? 0 : 0;
  const pObjetivoBruto = out ? out.prob_target_pct[i] ?? 0 : 0;

  return (
    <div style={{ marginTop: 18, borderTop: `0.5px solid ${color.border}`, paddingTop: 12 }}>
      <button
        type="button"
        onClick={() => setAbierto((a) => !a)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 7,
          background: "transparent",
          border: "none",
          padding: 0,
          cursor: "pointer",
          fontSize: 9.5,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: color.copper,
          fontFamily: font.sans,
        }}
      >
        <span
          style={{
            display: "inline-block",
            transform: abierto ? "rotate(90deg)" : "none",
            transition: "transform 150ms",
          }}
        >
          ›
        </span>
        Probabilidad de ruina y objetivo por horizonte
      </button>

      {abierto && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 14 }}>
          <ReadingNote>
            La <strong>probabilidad de ruina</strong> de aquí arriba se mide sobre el horizonte
            completo del backtest, que no eliges tú. En este bloque el horizonte es la variable:
            «¿qué probabilidad hay de arruinarme —o de llegar al objetivo— en las próximas X
            sesiones?». Se calcula una vez y luego el deslizador lee la curva sin volver a simular.
            <br />
            <br />
            <strong>No es una prueba de fondeo.</strong> Aquí el suelo es fijo —un % por debajo de tu
            capital inicial— y no hay límite de pérdida diaria ni drawdown que suba con cada máximo.
            Por eso estos números salen bastante mejores que los de «¿Pasarías el fondeo?»: aquella
            te elimina por cosas que este bloque ni mira.
          </ReadingNote>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
              gap: 12,
            }}
          >
            <Field label="Objetivo (%)" hint="Beneficio sobre el capital inicial.">
              <NumberInput
                value={cfg.objetivoPct}
                onChange={(v) => set("objetivoPct", v)}
                min={0.1}
                step={0.5}
              />
            </Field>
            <Field label="Ruina (%)" hint="Caída desde el capital inicial que te deja fuera.">
              <NumberInput
                value={cfg.ruinaPct}
                onChange={(v) => set("ruinaPct", v)}
                min={0.1}
                max={99}
                step={1}
              />
            </Field>
            <Field
              label="Horizonte (sesiones)"
              hint="Hasta dónde se simula. El deslizador se mueve dentro de este tope."
            >
              <NumberInput
                value={cfg.horizonte}
                onChange={(v) => set("horizonte", Math.round(v))}
                min={1}
                max={2000}
                step={10}
              />
            </Field>
            <Field label="Simulaciones">
              <NumberInput
                value={cfg.sims}
                onChange={(v) => set("sims", Math.round(v))}
                min={100}
                max={50000}
                step={1000}
              />
            </Field>
          </div>

          <RunButton
            onClick={lanzar}
            loading={busy}
            disabled={!valoresDia.length}
            label={out ? "Recalcular" : "Calcular probabilidades por horizonte"}
            loadingLabel="Simulando…"
          />

          {err && <ErrorBox>{err}</ErrorBox>}
          {stale && (
            <span style={{ fontSize: 11, fontFamily: font.sans, color: color.warning }}>
              Has cambiado un mando: lo que se ve es del cálculo anterior. Pulsa «Recalcular».
            </span>
          )}

          {out && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span
                  style={{
                    fontSize: 11.5,
                    fontFamily: font.sans,
                    color: color.textSecondary,
                    whiteSpace: "nowrap",
                  }}
                >
                  Tras
                </span>
                <input
                  type="range"
                  min={1}
                  max={out.max_days}
                  step={1}
                  value={dia}
                  onChange={(e) => setDia(Number(e.target.value))}
                  style={{ flex: 1, accentColor: color.copper }}
                />
                <input
                  type="number"
                  min={1}
                  max={out.max_days}
                  value={dia}
                  onChange={(e) =>
                    setDia(
                      Math.min(out.max_days, Math.max(1, Math.round(Number(e.target.value) || 1))),
                    )
                  }
                  style={{
                    width: 62,
                    background: color.bgBase,
                    border: `0.5px solid ${color.border}`,
                    borderRadius: 4,
                    color: color.textHigh,
                    fontFamily: font.mono,
                    fontSize: 12.5,
                    padding: "5px 7px",
                    outline: "none",
                  }}
                />
                <span
                  style={{
                    fontSize: 11.5,
                    fontFamily: font.sans,
                    color: color.textSecondary,
                    whiteSpace: "nowrap",
                  }}
                >
                  sesiones
                </span>
              </div>

              <InlineStats
                items={[
                  {
                    label: `Prob. ruina (-${out.ruin_pct}%)`,
                    value: fmt.pct(pRuina, 1),
                    tone: pRuina > 5 ? color.loss : color.profit,
                    help: `Trayectorias que tocan ${fmt.money(out.ruin_level)} en algún momento dentro de esas ${dia} sesiones.`,
                  },
                  {
                    label: `Prob. objetivo (+${out.target_pct}%)`,
                    value: fmt.pct(pObjetivo, 1),
                    tone: pObjetivo > 50 ? color.profit : color.textHigh,
                    help: `Llegan a ${fmt.money(out.target_level)} SIN haberse arruinado antes. Ignorando la ruina serían ${fmt.pct(pObjetivoBruto, 1)}.`,
                  },
                  {
                    label: "Ni lo uno ni lo otro",
                    value: fmt.pct(Math.max(0, 100 - pRuina - pObjetivo), 1),
                    help: "Siguen vivas pero sin alcanzar el objetivo al acabar el plazo.",
                  },
                ]}
              />

              <div>
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 9.5,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: color.copper,
                    fontFamily: font.sans,
                  }}
                >
                  Probabilidad acumulada por horizonte
                  <Help title="Cómo leer las curvas" width={430}>
                    Cada curva es <strong>acumulada</strong>: en el día X marca el porcentaje de
                    trayectorias que ya habían tocado ese nivel en algún momento hasta ahí. Por eso
                    solo pueden subir.
                    <br />
                    <br />
                    La curva verde cuenta el objetivo <strong>alcanzado con la cuenta viva</strong>:
                    si una trayectoria revienta el día 12 y «llega» al objetivo el 40, no cuenta —
                    en un fondeo ya estarías fuera.
                    <br />
                    <br />
                    Ojo con leer la roja como un riesgo diario: al ser acumulada crece con el plazo
                    aunque la estrategia sea la misma. Cuanto más tiempo juegues, más oportunidades
                    hay de tocar el suelo.
                  </Help>
                </div>
                <div style={{ marginTop: 8 }}>
                  <HorizonChart out={out} dia={dia} />
                </div>
                <div style={{ display: "flex", gap: 16, marginTop: 4 }}>
                  {[
                    { c: color.loss, t: "ruina" },
                    { c: color.profit, t: "objetivo (vivo)" },
                  ].map((l) => (
                    <span
                      key={l.t}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 10,
                        fontFamily: font.sans,
                        color: color.textMuted,
                      }}
                    >
                      <span style={{ width: 10, height: 2, background: l.c }} />
                      {l.t}
                    </span>
                  ))}
                </div>
              </div>

              <span
                style={{
                  fontSize: 10.5,
                  fontFamily: font.sans,
                  color: color.textMuted,
                  lineHeight: 1.5,
                }}
              >
                {out.simulations.toLocaleString("es-ES")} trayectorias remuestreadas de{" "}
                {out.sample_size.toLocaleString("es-ES")} sesiones reales, con {riskPct}% de riesgo
                por operación sobre {fmt.money(out.init_cash)}.
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
