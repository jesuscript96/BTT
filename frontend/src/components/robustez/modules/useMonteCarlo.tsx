"use client";

import { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import {
  DataTable,
  ErrorBox,
  Field,
  NumberInput,
  Placeholder,
  ReadingNote,
  RunButton,
  SectionHead,
  Segmented,
  TextInput,
  fmt,
} from "../shared";
import { InlineStats } from "@/components/portfolio/StatSheet";
import { DistributionChart, SpaghettiChart } from "../charts/MonteCarloCharts";
import { DrawdownCompare } from "../charts/DrawdownCompare";
import { FundingSection, LossesSection } from "../charts/MonteCarloExtras";
import { HorizonStudy } from "../charts/HorizonStudy";
import { realLossStats } from "@/lib/robustez/loss_stats";
import { Help, StaleNotice } from "../help";
import { runRobustezMonteCarlo, type McMethod, type MonteCarloOut } from "@/lib/api_robustez";
import type { ModuleCtx, ModuleParts } from "./types";

export function useMonteCarlo({ run, loading }: ModuleCtx): ModuleParts {
  const [sims, setSims] = useState(5000);
  const [method, setMethod] = useState<McMethod>("bootstrap");
  const [unit, setUnit] = useState<"day" | "trade">("day");
  const [ruinPct, setRuinPct] = useState(50);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [out, setOut] = useState<MonteCarloOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [ranCfg, setRanCfg] = useState<string | null>(null);

  const compounding = run?.compounding;
  const useCompound = !!compounding?.is_percent_risk;

  const bounds = useMemo(() => {
    if (!run?.trades.length) return null;
    const ds = run.trades.map((t) => t.date).sort();
    return { first: ds[0], last: ds[ds.length - 1] };
  }, [run]);

  const selected = useMemo(() => {
    if (!run) return [];
    const a = from || "0000";
    const b = to || "9999";
    return run.trades.filter((t) => t.date >= a && t.date <= b);
  }, [run, from, to]);

  /**
   * Valores que se remuestrean.
   *
   * Por DIA es el modo por defecto y no es un capricho: el motor de backtest
   * dimensiona todas las posiciones de una sesion sobre el balance de apertura
   * y acumula el PnL al cerrar el dia, asi que la unidad natural de composicion
   * es el dia, no el trade. Ademas los trades de una misma sesion estan
   * correlacionados (mismo regimen de mercado); remuestrearlos por separado
   * rompe esa correlacion y SUBESTIMA el riesgo.
   *
   * Por TRADE queda disponible porque es el bootstrap de manual, pero su curva
   * base no reproduce exactamente la corrida real (compone trade a trade).
   */
  const values = useMemo(() => {
    if (!selected.length) return [];
    const pick = (t: (typeof selected)[number]) => (useCompound ? t.r_precise : t.pnl);
    if (unit === "trade") return selected.map(pick);
    const byDay = new Map<string, number>();
    for (const t of selected) byDay.set(t.date, (byDay.get(t.date) || 0) + pick(t));
    return Array.from(byDay.entries())
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([, v]) => v);
  }, [selected, unit, useCompound]);

  // El lado REAL de los bloques de abajo. Depende solo de la corrida cargada,
  // no de la simulacion, asi que se calcula una vez y sobrevive a cada
  // re-ejecucion del Monte Carlo.
  const real = useMemo(
    () =>
      run
        ? realLossStats(run.trades, run.global_equity, compounding?.init_cash ?? 10000)
        : null,
    [run, compounding?.init_cash],
  );

  // Serie por SESION para la prueba de fondeo. No usa `values` a proposito: si
  // el usuario elige remuestreo "por trade" arriba, el bootstrap principal
  // cambia de unidad, pero un challenge se juega SIEMPRE con limites diarios.
  const fundingValues = useMemo(() => {
    if (!run || !real) return [];
    if (!useCompound) return real.porDia.valores;
    const byDay = new Map<string, number>();
    for (const t of run.trades) byDay.set(t.date, (byDay.get(t.date) || 0) + (t.r_precise ?? 0));
    return real.fechas.map((d) => byDay.get(d) || 0);
  }, [run, real, useCompound]);

  // Huella de la configuracion: si se cambia un mando y no se vuelve a
  // ejecutar, lo que se ve es del barrido anterior.
  const cfgKey = JSON.stringify({ sims, method, unit, ruinPct, from, to });
  const stale = !!out && ranCfg !== null && ranCfg !== cfgKey && !busy;

  const launch = async () => {
    if (!run || !values.length) return;
    setBusy(true);
    setErr(null);
    const t0 = performance.now();
    try {
      const res = await runRobustezMonteCarlo({
        values,
        init_cash: compounding?.init_cash ?? 10000,
        simulations: sims,
        method,
        mode: useCompound ? "compound" : "additive",
        risk_pct: compounding?.risk_pct || 3,
        ruin_pct: ruinPct,
        unit,
        seed: null,
      });
      setOut(res);
      setRanCfg(cfgKey);
      setElapsed(performance.now() - t0);
    } catch (e: any) {
      setErr(e?.message || "Fallo la simulacion");
      setOut(null);
    } finally {
      setBusy(false);
    }
  };

  /* ─────────────────── CONFIG ─────────────────── */
  const config = (
    <>
      <Field
        label="Metodo"
        hint={
          method === "bootstrap"
            ? "Con reemplazo: cada simulacion es un histórico alternativo. Responde a '¿y si me hubieran tocado otros trades?'."
            : "Baraja los mismos trades: el balance final es siempre el mismo, solo cambia el camino. Aisla el efecto del ORDEN."
        }
      >
        <Segmented
          value={method}
          onChange={setMethod}
          options={[
            { value: "bootstrap", label: "Bootstrap" },
            { value: "permutacion", label: "Permutacion" },
          ]}
        />
      </Field>

      <Field
        label="Unidad de remuestreo"
        hint={
          unit === "day"
            ? "Sesiones completas. Reproduce exactamente la curva real y respeta que los trades de un mismo dia van correlacionados."
            : "Trades sueltos. Bootstrap clasico, pero rompe la correlacion intradia y su curva base no cuadra al milimetro con la real."
        }
      >
        <Segmented
          value={unit}
          onChange={setUnit}
          options={[
            { value: "day", label: "Por dia" },
            { value: "trade", label: "Por trade" },
          ]}
        />
      </Field>

      <Field label="Simulaciones" hint="5.000 tarda menos de un segundo.">
        <NumberInput value={sims} onChange={setSims} min={100} max={50000} step={1000} />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Desde">
          <TextInput type="date" value={from} onChange={setFrom} />
        </Field>
        <Field label="Hasta">
          <TextInput type="date" value={to} onChange={setTo} />
        </Field>
      </div>
      {bounds && (
        <div style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, marginTop: -6 }}>
          disponible {bounds.first} → {bounds.last} · {fmt.int(selected.length)} trades ·{" "}
          {fmt.int(values.length)} muestras
        </div>
      )}

      <Field label="Umbral de ruina (%)" hint="Perder este % del capital cuenta como ruina.">
        <NumberInput value={ruinPct} onChange={setRuinPct} min={5} max={95} step={5} />
      </Field>

      <RunButton
        onClick={launch}
        loading={busy}
        disabled={!run || loading || !values.length}
        label="Generar simulaciones"
        loadingLabel="Simulando…"
      />
      {elapsed != null && !busy && out && (
        <div style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, textAlign: "center" }}>
          {(elapsed / 1000).toFixed(2)} s · {fmt.int(out.simulations)} simulaciones
        </div>
      )}
    </>
  );

  /* ─────────────────── RESULTADOS ─────────────────── */
  let results: React.ReactNode;

  if (loading) {
    results = <Placeholder>Cargando los trades de la estrategia…</Placeholder>;
  } else if (!run) {
    results = <Placeholder>Elige arriba una estrategia que tenga un backtest guardado.</Placeholder>;
  } else if (!out) {
    results = (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        <Placeholder>
          Configura a la izquierda y pulsa <strong>Generar simulaciones</strong>. Se reordena el
          histórico miles de veces para separar qué parte del resultado es la estrategia y qué parte
          fue el orden en que llegaron los trades.
        </Placeholder>
      </div>
    );
  } else {
    const isPerm = out.method === "permutacion";
    const realWasMilder = out.base_max_drawdown > out.dd_tolerance.p95;

    results = (
      <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        {stale && <StaleNotice onRun={launch} />}

        {/* ── Espagueti ── */}
        <section>
          <SectionHead
            title={`${fmt.int(out.simulations)} historias alternativas`}
            hint={
              isPerm
                ? "Permutacion: los mismos trades en distinto orden. Todas acaban en el mismo sitio — lo que cambia, y mucho, es el camino."
                : "Bootstrap: trades remuestreados con reemplazo. El abanico es el rango de resultados compatibles con esta estrategia."
            }
          />
          <SpaghettiChart
            spaghetti={out.spaghetti}
            bands={out.bands}
            baseCurve={out.base_curve}
            initCash={out.init_cash}
          />
        </section>

        {/* ── Riesgo de drawdown ── */}
        <section>
          <SectionHead
            title="Cuanto drawdown hay que estar dispuesto a tragar"
            hint="El drawdown que viviste no es el que te espera. Estas cifras dicen cuanto tendrias que aguantar para no verte forzado a abandonar."
            right={
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 11,
                  color: color.textMuted,
                  fontFamily: font.sans,
                }}
              >
                <Help title="Como se lee esto" width={400}>
                  Tu backtest recorrio <strong>un</strong> camino posible. El Monte Carlo genera miles
                  de caminos alternativos con los mismos ingredientes y mira que drawdown sale en cada
                  uno.
                  <br />
                  <br />
                  <strong>Aguantar el 95%</strong> es la cifra practica: solo 1 de cada 20 escenarios
                  llega a ser peor que esa. Si dimensionas tu riesgo con el drawdown del backtest y no
                  con este, tienes una posibilidad entre veinte de encontrarte algo que no habias
                  previsto — y abandonar justo en el peor momento.
                  <br />
                  <br />
                  Los porcentajes son negativos porque son caidas desde un maximo.
                </Help>
                metodo
              </span>
            }
          />
          <InlineStats
            items={[
              { label: "DD real", value: fmt.pct(out.base_max_drawdown, 1), tone: color.copper, help: "Lo que ocurrio de verdad." },
              { label: "DD mediano", value: fmt.pct(out.drawdown.p50, 1), tone: color.loss, help: "La mitad de los escenarios pasa de aqui." },
              { label: "Aguantar el 95%", value: fmt.pct(out.dd_tolerance.p95, 1), tone: color.loss, help: "Solo 1 de cada 20 escenarios lo supera." },
              { label: "Aguantar el 99%", value: fmt.pct(out.dd_tolerance.p99, 1), tone: color.loss, help: "Solo 1 de cada 100 lo supera." },
              { label: "Peor simulado", value: fmt.pct(out.drawdown.worst, 1), tone: color.loss },
            ]}
          />

          <div style={{ marginTop: 14 }}>
            <DistributionChart
              hist={out.hist_drawdown}
              barColor="var(--color-ec-loss)"
              fmtValue={(v) => `${v.toFixed(0)}%`}
              markers={[
                {
                  value: out.base_max_drawdown,
                  label: `real ${out.base_max_drawdown.toFixed(1)}%`,
                  color: "var(--color-ec-copper)",
                },
                {
                  value: out.dd_tolerance.p95,
                  label: `95% ${out.dd_tolerance.p95.toFixed(1)}%`,
                  color: "var(--color-ec-warning)",
                },
              ]}
              caption="Distribucion del drawdown maximo de cada simulacion. La marca cobre es el que realmente ocurrio."
            />
          </div>

          {out.dd_paths && out.dd_paths.real?.length > 1 && (
            <div style={{ marginTop: 18 }}>
              <SectionHead
                title="El drawdown real contra los escenarios simulados"
                hint="Los percentiles dicen cuanto se cae; estas curvas dicen como. Una caida del 30% de golpe y otra que se arrastra medio año son la misma cifra y dos experiencias distintas."
              />
              <DrawdownCompare paths={out.dd_paths} />
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <ReadingNote>
              {realWasMilder ? (
                <>
                  El drawdown real ({fmt.pct(out.base_max_drawdown, 1)}) fue <strong>mas benigno</strong>{" "}
                  que el que deberias esperar: 1 de cada 20 escenarios llega a{" "}
                  {fmt.pct(out.dd_tolerance.p95, 1)}. Dimensiona el riesgo con esa cifra, no con la del
                  backtest.
                </>
              ) : (
                <>
                  El drawdown real ({fmt.pct(out.base_max_drawdown, 1)}) ya cae en la cola mala de la
                  distribucion: viviste un escenario peor que el 95% de los simulados.
                </>
              )}
            </ReadingNote>
          </div>
        </section>

        {/* ── Rango de escenarios ── */}
        <section>
          <SectionHead
            title="Rango de escenarios posibles"
            right={
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 11,
                  color: color.textMuted,
                  fontFamily: font.sans,
                }}
              >
                <Help title="Percentiles, en cristiano" width={400}>
                  Ordena los miles de resultados finales de peor a mejor.
                  <br />
                  <br />
                  <strong>p5</strong> es el que deja por debajo al 5% de los escenarios: el mal
                  escenario, pero no el peor imaginable.
                  <br />
                  <strong>p50</strong> es la mediana: la mitad sale mejor, la mitad peor.
                  <br />
                  <strong>p95</strong> es el buen escenario, superado solo por 1 de cada 20.
                  <br />
                  <br />
                  Si tu resultado real esta pegado al p95, tuviste suerte y no deberias esperar que se
                  repita. Si esta cerca del p50, el backtest fue representativo.
                </Help>
                percentiles
              </span>
            }
            hint={
              isPerm
                ? "En permutacion todos los caminos acaban igual, asi que el rango de finales es un punto. Cambia a Bootstrap para ver la dispersion de resultados."
                : "Intervalos de confianza sobre el resultado final."
            }
          />
          <InlineStats
            items={[
              {
                label: "Prob. de perder",
                value: fmt.pct(out.prob_losing_pct, 1),
                tone: out.prob_losing_pct > 20 ? color.loss : color.profit,
                help: "Escenarios que acaban por debajo del capital inicial.",
              },
              {
                label: `Prob. ruina (-${out.ruin_pct_threshold}%)`,
                value: fmt.pct(out.prob_ruin_pct, 1),
                tone: out.prob_ruin_pct > 5 ? color.loss : color.profit,
              },
              { label: "Final p5", value: `${fmt.money(out.final_balance.p5)} · ${fmt.pct(out.return_pct.p5, 0)}`, tone: color.loss },
              { label: "Final mediano", value: `${fmt.money(out.final_balance.p50)} · ${fmt.pct(out.return_pct.p50, 0)}` },
              { label: "Final p95", value: `${fmt.money(out.final_balance.p95)} · ${fmt.pct(out.return_pct.p95, 0)}`, tone: color.profit },
            ]}
          />

          {!isPerm && (
            <div style={{ marginTop: 14 }}>
              <DistributionChart
                hist={out.hist_final}
                markers={[
                  {
                    value: out.base_final,
                    label: `real $${Math.round(out.base_final).toLocaleString("es-ES")} (${
                      out.base_return_pct >= 0 ? "+" : ""
                    }${out.base_return_pct.toFixed(0)}%)`,
                    color: "var(--color-ec-copper)",
                  },
                  { value: out.init_cash, label: "capital inicial", color: "var(--color-ec-text-muted)" },
                ]}
                caption="Distribucion del capital final. A la izquierda de 'capital inicial' la estrategia perdio dinero."
              />
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <DataTable
              columns={["Percentil", "Capital final", "Retorno", "Drawdown max"]}
              rows={[
                ["p5 (malo)", fmt.money(out.final_balance.p5), fmt.pct(out.return_pct.p5, 1), fmt.pct(out.drawdown.p5, 1)],
                ["p25", fmt.money(out.final_balance.p25), "—", fmt.pct(out.drawdown.p25, 1)],
                ["p50 (mediana)", fmt.money(out.final_balance.p50), fmt.pct(out.return_pct.p50, 1), fmt.pct(out.drawdown.p50, 1)],
                ["p75", fmt.money(out.final_balance.p75), "—", fmt.pct(out.drawdown.p75, 1)],
                ["p95 (bueno)", fmt.money(out.final_balance.p95), fmt.pct(out.return_pct.p95, 1), fmt.pct(out.drawdown.p95, 1)],
              ]}
            />
          </div>

          {/* El horizonte, como VARIABLE: la ruina de arriba se mide sobre el
              largo del backtest, que no elige el usuario. Va por SESION aunque
              el bootstrap principal remuestree por trade — un fondeo se juega
              con limites diarios. */}
          <HorizonStudy
            valoresDia={fundingValues}
            initCash={out.init_cash}
            riskPct={out.risk_pct}
            esPct={useCompound}
          />
        </section>

        {/* ── Perdidas dia a dia y probabilidades ── */}
        {real && out.losses && (
          <LossesSection
            out={out}
            real={real}
            capital={{
              initCash: out.init_cash,
              esPct: useCompound,
              riskPct: out.risk_pct,
              riesgoTipo: String((run.backtest_params as Record<string, unknown>)?.risk_type ?? "").toUpperCase() || undefined,
              origen: "backtest guardado",
            }}
          />
        )}

        {/* ── Prueba de fondeo ── */}
        {real && (
          <FundingSection
            valoresDia={fundingValues}
            maeFracs={real.maeFracs}
            tradesPorDia={real.tradesPorDia}
            esPct={useCompound}
            riskPctDefault={compounding?.risk_pct || 1}
            nSesiones={real.fechas.length}
            baseCash={out.init_cash}
          />
        )}

        <ReadingNote>
          Modelo <strong>{out.mode === "compound" ? "compuesto" : "aditivo"}</strong>
          {out.mode === "compound" ? (
            <>
              {" "}— se remuestrean R-multiplos y se recompone el capital al {out.risk_pct}% de riesgo por
              trade, que es como dimensiono el backtest de verdad. Bandas calculadas sobre{" "}
              {fmt.int(out.bands_from)} trayectorias.
            </>
          ) : (
            <> — se suman PnL en dolares. Correcto solo con tamaño de posicion fijo.</>
          )}
        </ReadingNote>
      </div>
    );
  }

  return { config, results };
}
