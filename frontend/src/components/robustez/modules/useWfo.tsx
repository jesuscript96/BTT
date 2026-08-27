"use client";

import { useEffect, useRef, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import {
  DataTable,
  ErrorBox,
  Field,
  MetricTile,
  NumberInput,
  Placeholder,
  ProgressBar,
  ReadingNote,
  RunButton,
  SectionHead,
  Segmented,
  TileGrid,
  fmt,
} from "../shared";
import { Help, PlainStats, StaleNotice, Verdict } from "../help";
import { WfoParamMatrix, WfoWindowBars } from "../charts/WfoCharts";

import {
  cancelRobustezJob,
  getStrategyParameters,
  pollRobustezJob,
  runWfoFast,
  startWfoFull,
  type OptimizableParam,
  type WfoOut,
} from "@/lib/api_robustez";
import type { ModuleCtx, ModuleParts } from "./types";

/* ── Horas de cierre ──────────────────────────────────────────────────
   Los parametros de hora se barren en MINUTOS DESDE MEDIANOCHE (08:30 = 510).
   Estos dos ayudantes estan duplicados a proposito de
   `OptimizationSurfaceTab`: importarlos de alli arrastraria Plotly (va con
   `next/dynamic`) a un modulo de Robustez que no lo necesita. Son seis lineas;
   si aparece un tercer sitio, toca moverlos a un util comun. */
const minutosAHHMM = (mins: number) => {
  const m = Math.max(0, Math.round(mins));
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};
const hhmmAMinutos = (txt: string): number | null => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(txt.trim());
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
};

function HoraInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <input
      type="time"
      value={minutosAHHMM(value)}
      onChange={(e) => {
        const v = hhmmAMinutos(e.target.value);
        if (v !== null) onChange(v);
      }}
      style={{
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.sm,
        color: color.textHigh,
        fontFamily: font.mono,
        fontSize: 12.5,
        padding: "7px 9px",
        width: "100%",
        outline: "none",
      }}
      onFocus={(e) => (e.currentTarget.style.borderColor = color.copper)}
      onBlur={(e) => (e.currentTarget.style.borderColor = color.border)}
    />
  );
}

type Mode = "rapido" | "completo";

const METRICS = [
  { value: "sharpe", label: "Sharpe" },
  { value: "total_return", label: "Retorno" },
  { value: "profit_factor", label: "Profit factor" },
] as const;

/**
 * Lectura de la eficiencia — el numero que resume todo el walk-forward.
 *
 * Ojo con el tramo alto: una eficiencia MUY por encima de 1 no significa que la
 * estrategia sea el doble de buena fuera de muestra. Significa que el tramo de
 * optimizacion rindio poco comparado con el de validacion, casi siempre porque
 * las ventanas son pocas o cortas y el reparto salio desigual. Es ruido, no una
 * virtud, y darlo por bueno seria justo el error que este modulo existe para
 * evitar.
 */
function readEfficiency(e: number | null): { tone: string; text: string } {
  if (e == null) return { tone: color.textMuted, text: "No calculable: el tramo de optimizacion no fue rentable." };
  if (e >= 1.5)
    return {
      tone: color.warning,
      text:
        "Que hay por encima de 1,5: el resultado fuera de muestra supera con mucho al de dentro. Eso no es " +
        "robustez, suele significar que los tramos de optimizacion salieron flojos o demasiado cortos y la " +
        "comparacion no es justa.",
    };
  if (e >= 0.7)
    return {
      tone: color.profit,
      text: "Que significa entre 0,7 y 1,5: se conserva la mayor parte del rendimiento al salir de muestra. Es el rango sano.",
    };
  if (e >= 0.5)
    return {
      tone: color.warning,
      text: "Que significa entre 0,5 y 0,7: se conserva entre la mitad y dos tercios del rendimiento. Pierde filo, pero aguanta.",
    };
  return {
    tone: color.loss,
    text:
      "Que significa por debajo de 0,5: fuera de muestra se conserva menos de la mitad del rendimiento. " +
      "Puede seguir ganando dinero, pero mucho menos de lo que prometia el backtest.",
  };
}

/**
 * Veredicto: ¿pasa el test o no?
 *
 * No basta con la eficiencia. Una estrategia puede tener eficiencia 0,9 y haber
 * perdido dinero fuera de muestra en 5 de 6 ventanas (bastaria con que tambien
 * lo perdiera dentro). Por eso el veredicto cruza TRES cosas:
 *   1. eficiencia: cuanto del rendimiento sobrevive fuera de muestra
 *   2. consistencia: en cuantas ventanas se gano dinero de verdad en OOS
 *   3. que el conjunto de las ventanas OOS sea positivo
 */
function verdict(out: WfoOut): { level: "pass" | "warn" | "fail"; title: string; body: React.ReactNode } {
  const e = out.wfo_efficiency;
  const cons = out.consistency_pct;
  const oosPositive = out.windows.filter((w) => (w.oos.return_pct ?? 0) > 0).length;

  if (e == null) {
    return {
      level: "warn",
      title: "No concluyente",
      body: (
        <>
          No se puede calcular la eficiencia porque los tramos de optimizacion no fueron rentables:
          dividir por un numero negativo no significa nada. Prueba con menos ventanas (asi cada tramo
          es mas largo) o con otra metrica.
        </>
      ),
    };
  }

  if (e >= 1.5) {
    return {
      level: "warn",
      title: "No concluyente — resultado sospechoso",
      body: (
        <>
          La eficiencia sale <strong>{e.toFixed(2)}</strong>, o sea que fuera de muestra rindio mucho
          MAS que dentro. Eso no es robustez: casi siempre significa que los tramos de optimizacion
          salieron flojos o demasiado cortos y la comparacion no es justa. Sube el numero de ventanas
          y vuelve a mirarlo antes de dar nada por bueno.
        </>
      ),
    };
  }

  // Lo primero es si gano dinero en datos que no habia visto. Si no, da igual
  // lo bonita que sea la eficiencia.
  if (cons < 50) {
    return {
      level: "fail",
      title: "No pasa el test",
      body: (
        <>
          Solo <strong>{oosPositive} de {out.windows_total}</strong> ventanas ganaron dinero fuera de
          muestra. Con eficiencia {e.toFixed(2)}, el resultado del backtest se apoya en haber elegido
          los parametros mirando esos mismos datos. Tal cual esta, no deberia operarse.
        </>
      ),
    };
  }

  if (e >= 0.7) {
    return {
      level: "pass",
      title: "Pasa el test",
      body: (
        <>
          Se conserva el <strong>{Math.round(e * 100)}%</strong> del rendimiento al salir de muestra
          (eficiencia {e.toFixed(2)}) y {oosPositive} de {out.windows_total} ventanas ganaron dinero en
          datos que no habian visto. Los parametros que funcionaban en el pasado siguieron funcionando.
        </>
      ),
    };
  }

  if (e >= 0.5) {
    return {
      level: "warn",
      title: "Pasa con reservas",
      body: (
        <>
          Gano dinero en {oosPositive} de {out.windows_total} ventanas fuera de muestra, pero solo
          conservo el <strong>{Math.round(e * 100)}%</strong> del rendimiento (eficiencia{" "}
          {e.toFixed(2)}). Parte de lo que prometia el backtest venia de estar ajustada a ese periodo.
          Opera con tamaño reducido y vuelve a medirlo con mas datos.
        </>
      ),
    };
  }

  return {
    level: "warn",
    title: "Gana, pero muy degradada",
    body: (
      <>
        Hay tension entre las dos cifras: gano dinero en{" "}
        <strong>{oosPositive} de {out.windows_total}</strong> ventanas fuera de muestra —eso es
        bueno—, pero la eficiencia es de solo <strong>{e.toFixed(2)}</strong>: conservo menos de la
        mitad del rendimiento que tenia dentro de muestra.
        <br />
        <br />
        Traducido: la estrategia <em>funciona</em>, pero muy por debajo de lo que sugiere el backtest.
        Si dimensionas el riesgo con las cifras del backtest, te vas a llevar una decepcion. Cuenta con
        aproximadamente un {Math.round(e * 100)}% de aquello.
      </>
    ),
  };
}

export function useWfo({ run, strategy, loading }: ModuleCtx): ModuleParts {
  const [mode, setMode] = useState<Mode>("rapido");
  const [nWindows, setNWindows] = useState(6);
  const [oosPct, setOosPct] = useState(30);
  const [anchored, setAnchored] = useState(false);
  const [metric, setMetric] = useState<string>("sharpe");
  const [matrixView, setMatrixView] = useState<"3d" | "heatmap">("heatmap");

  const [params, setParams] = useState<OptimizableParam[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [pMin, setPMin] = useState(0);
  const [pMax, setPMax] = useState(0);
  const [pSteps, setPSteps] = useState(6);

  const [out, setOut] = useState<WfoOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [ranCfg, setRanCfg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Huella de la configuracion. Si cambia y no se ha vuelto a ejecutar, lo que
  // se ve en pantalla es del barrido anterior — y sin avisarlo parece que
  // cambiar la metrica no hace nada (que es justo lo que se reporto).
  const cfgKey = JSON.stringify({ mode, nWindows, oosPct, anchored, metric, chosen, pMin, pMax, pSteps });

  /* Parametros optimizables de la estrategia (solo para el modo completo). */
  useEffect(() => {
    if (!strategy || mode !== "completo") return;
    let alive = true;
    getStrategyParameters(strategy.id)
      .then((r) => {
        if (!alive) return;
        setParams(r.parameters);
        // Preselecciona el primero "barato": los de risk_management no invalidan
        // la cache de señales, asi que el barrido va mucho mas rapido.
        const cheap = r.parameters.find((p) => p.cheap) || r.parameters[0];
        if (cheap) {
          setChosen(cheap.path);
          setPMin(cheap.min);
          setPMax(cheap.max);
        }
      })
      .catch((e) => alive && setErr(e?.message || "No se pudieron leer los parametros"));
    return () => {
      alive = false;
    };
  }, [strategy, mode]);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };
  useEffect(() => stopPolling, []);

  const sel = params.find((p) => p.path === chosen) || null;
  // Solo `time_of_day` es una hora de reloj. `minutes` (un TP a los N minutos
  // de abrir) es un numero normal y se sigue pintando como tal.
  const esHora = sel?.unit === "time_of_day";

  const launchFast = async () => {
    if (!strategy) return;
    setBusy(true);
    setErr(null);
    setOut(null);
    const t0 = performance.now();
    try {
      const r = await runWfoFast({
        strategy_id: strategy.id,
        n_windows: nWindows,
        oos_pct: oosPct,
        anchored,
        metric,
      });
      setOut(r);
      setRanCfg(cfgKey);
      setElapsed(performance.now() - t0);
    } catch (e: any) {
      setErr(e?.message || "Fallo el walk-forward");
    } finally {
      setBusy(false);
    }
  };

  const launchFull = async () => {
    if (!strategy || !sel) return;
    setBusy(true);
    setErr(null);
    setOut(null);
    setProgress(0);
    const t0 = performance.now();
    try {
      const { task_id } = await startWfoFull({
        strategy_id: strategy.id,
        params: [{ path: sel.path, label: sel.label, min: pMin, max: pMax, steps: pSteps }],
        n_windows: nWindows,
        oos_pct: oosPct,
        anchored,
        metric,
      });
      setTaskId(task_id);
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const s = await pollRobustezJob<WfoOut>(task_id);
          setProgress(s.progress ?? 0);
          if (s.status === "done" && s.result) {
            stopPolling();
            setBusy(false);
            setTaskId(null);
            setOut(s.result);
            setRanCfg(cfgKey);
            setElapsed(performance.now() - t0);
          } else if (s.status === "error" || s.status === "cancelled") {
            stopPolling();
            setBusy(false);
            setTaskId(null);
            setErr(s.status === "cancelled" ? "Cancelado" : s.error || "Fallo la ejecucion");
          }
        } catch (e: any) {
          stopPolling();
          setBusy(false);
          setTaskId(null);
          setErr(e?.message || "Se perdio el contacto con la tarea");
        }
      }, 2000);
    } catch (e: any) {
      setBusy(false);
      setErr(e?.message || "No se pudo lanzar");
    }
  };

  const cancel = async () => {
    if (taskId) await cancelRobustezJob(taskId).catch(() => {});
  };

  const nBacktests = nWindows * (pSteps + 1);
  /**
   * Estimacion medida en esta maquina: 3 ventanas x 4 pasos (15 backtests) sobre
   * el parametro barato tardaron 146,7 s en total — 88 s de carga de velas y
   * 58 s de barrido, o sea ~3,9 s por backtest.
   *
   * La clave es que cada backtest solo cubre SU ventana, no el histórico entero:
   * el coste por punto baja al subir el numero de ventanas. Por eso se divide.
   */
  const perBt = ((sel?.cheap ? 18 : 26) * 6) / Math.max(1, nWindows);
  const estSec = 88 + nBacktests * perBt;
  const estLabel = estSec < 90 ? `${Math.round(estSec)} s` : `${(estSec / 60).toFixed(1)} min`;

  /* ─────────────────── CONFIG ─────────────────── */
  const config = (
    <>
      <Field
        label="Modo"
        hint={
          mode === "rapido"
            ? "Parte los trades ya guardados en ventanas y compara la primera mitad con la segunda. Instantaneo, pero NO re-optimiza: la eficiencia es orientativa."
            : "El walk-forward de verdad: optimiza en cada tramo pasado y valida en el futuro que no ha visto. Re-ejecuta backtests."
        }
      >
        <Segmented
          value={mode}
          onChange={setMode}
          options={[
            { value: "rapido", label: "Rapido" },
            { value: "completo", label: "Completo" },
          ]}
        />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Ventanas">
          <NumberInput value={nWindows} onChange={setNWindows} min={2} max={20} step={1} />
        </Field>
        <Field label="% fuera de muestra">
          <NumberInput value={oosPct} onChange={setOosPct} min={10} max={60} step={5} />
        </Field>
      </div>

      <Field
        label="Tipo de ventana"
        hint={
          anchored
            ? "Anclada: el tramo de optimizacion empieza siempre en el primer dia y va creciendo."
            : "Desplazable: cada ventana arranca donde acabo la anterior."
        }
      >
        <Segmented
          value={anchored ? "anchored" : "rolling"}
          onChange={(v) => setAnchored(v === "anchored")}
          options={[
            { value: "rolling", label: "Desplazable" },
            { value: "anchored", label: "Anclada" },
          ]}
        />
      </Field>

      <Field label="Metrica a optimizar">
        <Segmented value={metric} onChange={setMetric} options={METRICS as any} />
      </Field>

      {mode === "completo" && (
        <>
          <div style={{ height: 1, background: color.border, margin: "2px 0" }} />
          <Field
            label="Parametro a optimizar"
            hint={
              sel
                ? sel.cheap
                  ? "De gestion de riesgo: las señales se reutilizan entre combinaciones, asi que el barrido va rapido."
                  : "Toca un indicador: hay que recalcular las señales en cada combinacion, asi que va mas lento."
                : undefined
            }
          >
            <select
              value={chosen ?? ""}
              onChange={(e) => {
                const p = params.find((x) => x.path === e.target.value);
                setChosen(e.target.value);
                if (p) {
                  setPMin(p.min);
                  setPMax(p.max);
                }
              }}
              style={{
                background: color.bgBase,
                border: `0.5px solid ${color.border}`,
                borderRadius: radius.sm,
                color: color.textHigh,
                fontFamily: font.sans,
                fontSize: 12,
                padding: "7px 9px",
                width: "100%",
                outline: "none",
              }}
            >
              {params.length === 0 && <option value="">(cargando…)</option>}
              {params.map((p) => (
                <option key={p.path} value={p.path} style={{ background: color.bgSurface }}>
                  {p.cheap ? "· " : ""}
                  {p.label} (ahora {p.current_value})
                </option>
              ))}
            </select>
          </Field>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            {/* Un parametro de HORA de cierre viaja en MINUTOS DESDE MEDIANOCHE
                (08:30 = 510). Con NumberInput se veia el 510 crudo y habia que
                hacer la cuenta a mano. Los de unidad `minutes` (un TP a los N
                minutos de abrir) SI son un numero normal: esos no se tocan. */}
            {esHora ? (
              <>
                <Field label="min (hora)">
                  <HoraInput value={pMin} onChange={setPMin} />
                </Field>
                <Field label="max (hora)">
                  <HoraInput value={pMax} onChange={setPMax} />
                </Field>
              </>
            ) : (
              <>
                <Field label="min">
                  <NumberInput value={pMin} onChange={setPMin} step={1} />
                </Field>
                <Field label="max">
                  <NumberInput value={pMax} onChange={setPMax} step={1} />
                </Field>
              </>
            )}
            <Field label="pasos">
              <NumberInput value={pSteps} onChange={setPSteps} min={2} max={20} step={1} />
            </Field>
          </div>

          <div
            style={{
              fontSize: 10.5,
              fontFamily: font.sans,
              color: color.warning,
              lineHeight: 1.5,
              borderLeft: `2px solid ${color.warning}`,
              paddingLeft: 8,
            }}
          >
            {nBacktests} backtests · unos {estLabel} estimados. Bloquea la maquina mientras corre.
          </div>
        </>
      )}

      {busy && mode === "completo" ? (
        <>
          <ProgressBar pct={progress} label="Optimizando ventanas" />
          <button
            type="button"
            onClick={cancel}
            style={{
              width: "100%",
              padding: "8px 12px",
              fontSize: 12,
              fontFamily: font.sans,
              border: `0.5px solid ${color.border}`,
              borderRadius: radius.sm,
              background: "transparent",
              color: color.textSecondary,
              cursor: "pointer",
            }}
          >
            Cancelar
          </button>
        </>
      ) : (
        <RunButton
          onClick={mode === "rapido" ? launchFast : launchFull}
          loading={busy}
          disabled={!strategy || loading || (mode === "completo" && !sel)}
          label={mode === "rapido" ? "Analizar ventanas" : "Ejecutar walk-forward"}
        />
      )}
      {elapsed != null && !busy && (
        <div style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, textAlign: "center" }}>
          {(elapsed / 1000).toFixed(2)} s
        </div>
      )}
    </>
  );

  /* ─────────────────── RESULTADOS ─────────────────── */
  let results: React.ReactNode;

  if (loading) {
    results = <Placeholder>Cargando los trades de la estrategia…</Placeholder>;
  } else if (!run || !strategy) {
    results = <Placeholder>Elige arriba una estrategia que tenga un backtest guardado.</Placeholder>;
  } else if (busy && mode === "completo") {
    results = (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <SectionHead title="Optimizando ventana a ventana" hint="Cada ventana barre la rejilla en su tramo pasado y valida en el futuro." />
        <ProgressBar pct={progress} label={`${nBacktests} backtests`} />
        <Placeholder>El primer 10% es la carga de velas. Puedes cancelar en cualquier momento.</Placeholder>
      </div>
    );
  } else if (!out) {
    results = (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        <Placeholder>
          El walk-forward parte el histórico en tramos, ajusta en el pasado y comprueba en el futuro que
          no ha visto. Si el rendimiento se desploma al cruzar esa frontera, la estrategia estaba
          ajustada al ruido.
        </Placeholder>
      </div>
    );
  } else {
    const eff = readEfficiency(out.wfo_efficiency);
    const isFull = out.kind === "wfo_full";
    const pc = out.param_configs?.[0];
    const pa = out.param_analysis;
    const v = verdict(out);
    const stale = ranCfg !== null && ranCfg !== cfgKey;

    results = (
      <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        {stale && <StaleNotice onRun={mode === "rapido" ? launchFast : launchFull} />}

        <Verdict level={v.level} title={v.title}>
          {v.body}
        </Verdict>

        <section>
          <SectionHead
            title="Las dos cifras que hay que mirar"
            hint="La eficiencia dice cuanto del rendimiento sobrevive fuera de muestra. La consistencia, en cuantas ventanas se gano dinero de verdad."
            right={
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>
                <Help title="Como se lee la eficiencia" width={400}>
                  Se divide el resultado <strong>fuera de muestra</strong> entre el de{" "}
                  <strong>dentro de muestra</strong>, ventana a ventana, y se toma la mediana.
                  <br />
                  <br />
                  <strong>1,00</strong> = fuera de muestra rindio igual que dentro: los parametros no
                  estaban ajustados al pasado.
                  <br />
                  <strong>0,70 – 1,50</strong> = rango sano. Se pierde algo de filo, que es normal.
                  <br />
                  <strong>0,50 – 0,70</strong> = pierde bastante. Vigilar.
                  <br />
                  <strong>&lt; 0,50</strong> = mas de la mitad del rendimiento era ajuste al pasado.
                  Sobreajuste.
                  <br />
                  <strong>&gt; 1,50</strong> = sospechoso, no bueno: significa que el tramo de
                  optimizacion salio flojo y la comparacion no es justa.
                  <br />
                  <br />
                  Se mide sobre la <em>metrica a optimizar</em> que elijas a la izquierda, asi que
                  cambiarla cambia la cifra — pero hay que <strong>volver a ejecutar</strong>.
                </Help>
                metodo
              </span>
            }
          />
          <TileGrid min={165}>
            <MetricTile
              label="WFO efficiency"
              value={out.wfo_efficiency != null ? fmt.num(out.wfo_efficiency, 2) : "—"}
              sub={out.wfo_efficiency_mean != null ? `media ${fmt.num(out.wfo_efficiency_mean, 2)}` : undefined}
              tone={eff.tone}
              hint="Cuanto del rendimiento sobrevive al salir de muestra."
            />
            <MetricTile
              label="Consistencia"
              value={fmt.pct(out.consistency_pct, 0)}
              sub={`${out.windows_oos_positive} de ${out.windows_total} ventanas`}
              tone={out.consistency_pct >= 60 ? color.profit : color.loss}
              hint="Ventanas con retorno OOS positivo."
            />
            <MetricTile label="Ventanas" value={fmt.int(out.windows_total)} sub={out.mode === "anchored" ? "ancladas" : "desplazables"} />
            {isFull && (
              <MetricTile
                label="Backtests"
                value={fmt.int(out.n_backtests)}
                sub={out.sweep_seconds ? `${out.sweep_seconds}s` : undefined}
                hint={out.signal_cache_used ? "Señales cacheadas entre combinaciones." : "Sin cache: hay parametros de indicador."}
              />
            )}
          </TileGrid>

          <div style={{ marginTop: 14 }}>
            <ReadingNote>{eff.text}</ReadingNote>
          </div>

          {!isFull && (
            <div style={{ marginTop: 10 }}>
              <ReadingNote>
                <strong>Modo rapido.</strong> Aqui no se re-optimiza nada: se compara la primera mitad de
                cada ventana con la segunda sobre los trades ya guardados. Sirve para ver degradacion,
                pero la eficiencia canonica exige ajustar parametros en IS y validarlos en OOS — eso es
                el modo <strong>Completo</strong>.
              </ReadingNote>
            </div>
          )}
        </section>

        <section>
          <SectionHead title="Dentro contra fuera de muestra, ventana a ventana" />
          <WfoWindowBars windows={out.windows} metricKey="return_pct" metricLabel="Retorno %" />
        </section>

        {isFull && pc && pc.values.length > 1 && (
          <section>
            <SectionHead
              title="Matriz del walk-forward"
              hint="Cada ventana contra cada valor del parametro, coloreado por la metrica optimizada."
              right={
                <div style={{ width: 210 }}>
                  <Segmented
                    value={matrixView}
                    onChange={setMatrixView}
                    options={[
                      { value: "heatmap", label: "Mapa" },
                      { value: "3d", label: "3D" },
                    ]}
                  />
                </div>
              }
            />
            <WfoParamMatrix
              windows={out.windows}
              paramValues={pc.values}
              paramLabel={pc.label}
              formatValue={esHora ? minutosAHHMM : undefined}
              metricLabel={METRICS.find((m) => m.value === out.metric)?.label ?? out.metric}
              view={matrixView}
            />
          </section>
        )}

        {isFull && pa && pa.per_value.length > 1 && (
          <section>
            <SectionHead
              title="Que valor conviene usar de verdad"
              hint="El ganador de una ventana suelta es el que mejor se ajusto a ESE tramo. Lo que sirve es la meseta: la zona de valores que va bien en todas."
            />
            <TileGrid min={165}>
              <MetricTile
                label="Valor recomendado"
                value={
                  pa.recommended == null
                    ? "—"
                    : esHora
                      ? minutosAHHMM(pa.recommended)
                      : fmt.num(pa.recommended, 2)
                }
                sub={pa.at_edge ? "en el borde del rango" : pa.label}
                tone={pa.at_edge ? color.warning : color.copper}
                hint="El de mejor meseta, no el que mas veces gano."
              />
              <MetricTile
                label="Estabilidad del optimo"
                value={pa.stability}
                sub={`dispersion ${fmt.pct(pa.winner_dispersion * 100, 0)} del rango`}
                tone={pa.stability === "estable" ? color.profit : pa.stability === "dudosa" ? color.warning : color.loss}
                hint="Cuanto se mueve el ganador de una ventana a otra."
              />
              <MetricTile
                label="Valor actual"
                value={sel ? fmt.num(sel.current_value, 2) : "—"}
                sub="el que tiene la estrategia"
              />
            </TileGrid>

            <div style={{ marginTop: 14 }}>
              <DataTable
                columns={["Valor", "Puntuacion media", "Meseta", "Peor ventana", "Veces ganador", "Dispersion"]}
                rows={pa.per_value.map((pv) => {
                  const isBest = pa.recommended != null && Math.abs(pv.value - pa.recommended) < 1e-6;
                  const mark = (n: React.ReactNode) =>
                    isBest ? <span style={{ color: color.copper }}>{n}</span> : n;
                  return [
                    mark(esHora ? minutosAHHMM(pv.value) : fmt.num(pv.value, 2)),
                    mark(fmt.num(pv.mean, 3)),
                    mark(fmt.num(pv.plateau, 3)),
                    mark(fmt.num(pv.min, 3)),
                    mark(`${pv.wins} / ${pa.n_windows}`),
                    mark(fmt.num(pv.std, 3)),
                  ];
                })}
              />
            </div>

            {pa.at_edge && (
              <div style={{ marginTop: 12 }}>
                <ReadingNote>
                  <strong>Ojo: el valor recomendado esta en el extremo del rango que barriste</strong>{" "}
                  ({fmt.num(pa.range[0], 2)} a {fmt.num(pa.range[1], 2)}). Cuando eso pasa, casi siempre
                  significa que el optimo de verdad queda FUERA y la rejilla se quedo corta: lo que ves
                  no es un maximo, es donde dejaste de mirar. Amplia el rango y vuelve a ejecutar antes
                  de tomarlo como conclusion.
                </ReadingNote>
              </div>
            )}

            <div style={{ marginTop: 12 }}>
              <ReadingNote>
                {pa.stability === "estable" ? (
                  <>
                    El optimo apenas se mueve entre ventanas: el parametro es <strong>robusto</strong>.
                    Usar {pa.recommended != null ? fmt.num(pa.recommended, 2) : "el recomendado"} es una
                    decision defendible.
                  </>
                ) : pa.stability === "dudosa" ? (
                  <>
                    El optimo se mueve algo entre ventanas. Quedate con la zona central de la meseta en
                    vez de con un valor exacto, y no lo reajustes cada poco.
                  </>
                ) : (
                  <>
                    El optimo <strong>salta de un extremo a otro</strong> segun la ventana. Eso
                    significa que este parametro no tiene un valor bueno estable: lo que se estaria
                    optimizando es ruido. Mejor fijarlo por criterio propio y no tocarlo.
                  </>
                )}
              </ReadingNote>
            </div>
          </section>
        )}

        <section>
          <SectionHead title="Detalle por ventana" />
          <DataTable
            columns={
              isFull
                ? ["#", "IS", "OOS", "Param", "IS ret%", "OOS ret%", "IS Sharpe", "OOS Sharpe", "Efic."]
                : ["#", "IS", "OOS", "IS ret%", "OOS ret%", "IS Sharpe", "OOS Sharpe", "OOS trades", "Efic."]
            }
            align={isFull ? ["left", "left", "left", "right", "right", "right", "right", "right", "right"] : undefined}
            rows={out.windows.map((w) => {
              const cells: React.ReactNode[] = [
                `V${w.index}`,
                `${w.is_from} → ${w.is_to}`,
                `${w.oos_from} → ${w.oos_to}`,
              ];
              // Un parametro de hora viaja en minutos: sin esto la columna
              // "mejor valor" de cada ventana enseñaba 510 en vez de 08:30.
              if (isFull)
                cells.push(
                  w.best_params?.map((v) => (esHora ? minutosAHHMM(v) : fmt.num(v, 2))).join(" / ") ?? "—",
                );
              cells.push(
                <span key="i" style={{ color: w.is.return_pct >= 0 ? color.profit : color.loss }}>
                  {fmt.num(w.is.return_pct, 1)}
                </span>,
                <span key="o" style={{ color: w.oos.return_pct >= 0 ? color.profit : color.loss }}>
                  {fmt.num(w.oos.return_pct, 1)}
                </span>,
                fmt.num(w.is.sharpe, 2),
                fmt.num(w.oos.sharpe, 2),
              );
              if (!isFull) cells.push(fmt.int(w.oos.trades));
              cells.push(
                w.efficiency == null ? (
                  <span key="e" style={{ color: color.textMuted }}>—</span>
                ) : (
                  <span key="e" style={{ color: readEfficiency(w.efficiency).tone }}>{fmt.num(w.efficiency, 2)}</span>
                ),
              );
              return cells;
            })}
          />
          <div style={{ marginTop: 10 }}>
            <ReadingNote>
              Una eficiencia vacia significa que el tramo de optimizacion perdio dinero: dividir por un
              numero negativo no dice nada, asi que se deja en blanco en vez de inventar una cifra.
            </ReadingNote>
          </div>
        </section>
      </div>
    );
  }

  return { config, results };
}
