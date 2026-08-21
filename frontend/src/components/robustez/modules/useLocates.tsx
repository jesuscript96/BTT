"use client";

import { useEffect, useRef, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import {
  DataTable,
  TextInput,
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
import {
  LocatesCurvesChart,
  LocatesSlippageHeatmap,
  LocatesSlippageSurface,
} from "../charts/LocatesCharts";
import { PlainStats, StaleNotice } from "../help";
import {
  cancelRobustezJob,
  pollRobustezJob,
  startLocatesCurves,
  startLocatesMatrix,
  type LocatesCurvesOut,
  type LocatesMatrixOut,
} from "@/lib/api_robustez";
import type { ModuleCtx, ModuleParts } from "./types";

type View = "curvas" | "matriz";
type ZMetric = "return_net_pct" | "sharpe" | "expectancy";

// Se usa `return_net_pct` y no `total_return_pct` porque el motor calcula este
// ultimo sin descontar los gastos fijos mensuales. Con gastos a 0 son iguales.
const Z_LABELS: Record<ZMetric, string> = {
  return_net_pct: "Retorno neto %",
  sharpe: "Sharpe",
  expectancy: "EV por trade ($)",
};

export function useLocates({ run, strategy, loading }: ModuleCtx): ModuleParts {
  const [view, setView] = useState<View>("curvas");

  // Curvas 1D
  const [lMin, setLMin] = useState(0.5);
  const [lMax, setLMax] = useState(5);
  const [lSteps, setLSteps] = useState(6);
  const [fixedSlip, setFixedSlip] = useState(0.1);
  const [xAxis, setXAxis] = useState<"time" | "trade">("time");

  // Matriz 2D
  const [mlMin, setMlMin] = useState(1);
  const [mlMax, setMlMax] = useState(10);
  const [mlSteps, setMlSteps] = useState(6);
  const [msMin, setMsMin] = useState(0.1);
  const [msMax, setMsMax] = useState(1);
  const [msSteps, setMsSteps] = useState(6);
  const [zMetric, setZMetric] = useState<ZMetric>("return_net_pct");
  const [plot3d, setPlot3d] = useState<"3d" | "heatmap">("3d");

  const [expenses, setExpenses] = useState(0);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [curves, setCurves] = useState<LocatesCurvesOut | null>(null);
  const [matrix, setMatrix] = useState<LocatesMatrixOut | null>(null);
  const [ranCfg, setRanCfg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const initCash = Number(run?.compounding.init_cash ?? 10000);
  // El backtest guarda el slippage en unidades del motor (fraccion); aqui se
  // trabaja en % real. Ver la nota de unidades en robustness_grid.py.
  const savedSlipPct = Number(run?.backtest_params?.slippage ?? 0) * 100;
  const savedLocates = Number(run?.backtest_params?.locates_cost ?? 0);
  // Donde corriste tu de verdad: se marca sobre la superficie y el mapa.
  const operating = run ? { locates: savedLocates, slippagePct: savedSlipPct } : undefined;

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };
  useEffect(() => stopPolling, []);

  const poll = <T,>(id: string, onDone: (r: T) => void) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await pollRobustezJob<T>(id);
        setProgress(s.progress ?? 0);
        if (s.status === "done" && s.result) {
          stopPolling();
          setBusy(false);
          setTaskId(null);
          onDone(s.result);
        } else if (s.status === "error") {
          stopPolling();
          setBusy(false);
          setTaskId(null);
          setErr(s.error || "Fallo la ejecucion");
        } else if (s.status === "cancelled") {
          stopPolling();
          setBusy(false);
          setTaskId(null);
          setErr("Cancelado");
        }
      } catch (e: any) {
        stopPolling();
        setBusy(false);
        setTaskId(null);
        setErr(e?.message || "Se perdio el contacto con la tarea");
      }
    }, 1500);
  };

  const launchCurves = async () => {
    if (!strategy) return;
    setBusy(true);
    setErr(null);
    setProgress(0);
    setCurves(null);
    try {
      const { task_id } = await startLocatesCurves({
        strategy_id: strategy.id,
        locates_min: lMin,
        locates_max: lMax,
        locates_steps: lSteps,
        slippage: fixedSlip,
        monthly_expenses: expenses,
        start_date: from || null,
        end_date: to || null,
      });
      setTaskId(task_id);
      poll<LocatesCurvesOut>(task_id, (r) => {
        setCurves(r);
        setRanCfg(cfgKey);
      });
    } catch (e: any) {
      setBusy(false);
      setErr(e?.message || "No se pudo lanzar");
    }
  };

  const launchMatrix = async () => {
    if (!strategy) return;
    setBusy(true);
    setErr(null);
    setProgress(0);
    setMatrix(null);
    try {
      const { task_id } = await startLocatesMatrix({
        strategy_id: strategy.id,
        locates_min: mlMin,
        locates_max: mlMax,
        locates_steps: mlSteps,
        slippage_min: msMin,
        slippage_max: msMax,
        slippage_steps: msSteps,
        monthly_expenses: expenses,
        start_date: from || null,
        end_date: to || null,
      });
      setTaskId(task_id);
      poll<LocatesMatrixOut>(task_id, (r) => {
        setMatrix(r);
        setRanCfg(cfgKey);
      });
    } catch (e: any) {
      setBusy(false);
      setErr(e?.message || "No se pudo lanzar");
    }
  };

  const cancel = async () => {
    if (!taskId) return;
    try {
      await cancelRobustezJob(taskId);
    } catch {
      /* si falla el aviso, el polling acabara reportandolo */
    }
  };

  // Huella de la configuracion: si cambia sin re-ejecutar, lo que se ve en
  // pantalla es del barrido anterior y hay que decirlo.
  const cfgKey = JSON.stringify(
    view === "curvas"
      ? { view, lMin, lMax, lSteps, fixedSlip, expenses, from, to }
      : { view, mlMin, mlMax, mlSteps, msMin, msMax, msSteps, expenses, from, to },
  );
  const stale = ranCfg !== null && ranCfg !== cfgKey && !busy;

  const nPoints = view === "curvas" ? lSteps : mlSteps * msSteps;

  /**
   * Estimacion de tiempo. Medido en esta maquina sobre la estrategia de prueba:
   *   - rango completo (2 años, 4.891 dias·ticker): ~72 s de carga, ~18 s/punto
   *   - medio año (1.452 dias·ticker):              ~31 s de carga, ~5 s/punto
   * Escala con el numero de dias·ticker, asi que acotar las fechas es la forma
   * de abaratar una prueba antes de lanzar la rejilla entera.
   */
  const rangeFrac = (() => {
    if (!from && !to) return 1;
    const all = run?.trades.map((t) => t.date).sort() ?? [];
    if (!all.length) return 1;
    const a = from || all[0];
    const b = to || all[all.length - 1];
    const inRange = all.filter((d) => d >= a && d <= b).length;
    return inRange / all.length || 1;
  })();
  const estSec = 72 * rangeFrac + nPoints * 18 * rangeFrac;
  const estLabel = estSec < 90 ? `${Math.round(estSec)} s` : `${(estSec / 60).toFixed(1)} min`;

  /* ─────────────────── CONFIG ─────────────────── */
  const config = (
    <>
      <Field label="Vista">
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { value: "curvas", label: "Modelizacion" },
            { value: "matriz", label: "Matriz 3D" },
          ]}
        />
      </Field>

      {view === "curvas" ? (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            <Field label="Locates min">
              <NumberInput value={lMin} onChange={setLMin} min={0} step={0.5} />
            </Field>
            <Field label="max">
              <NumberInput value={lMax} onChange={setLMax} min={0} step={0.5} />
            </Field>
            <Field label="pasos">
              <NumberInput value={lSteps} onChange={setLSteps} min={2} max={16} step={1} />
            </Field>
          </div>
          <Field label="Slippage fijo (%)" hint={`El backtest guardado uso ${savedSlipPct.toFixed(3)}%.`}>
            <NumberInput value={fixedSlip} onChange={setFixedSlip} min={0} step={0.05} />
          </Field>
          <Field label="Eje X">
            <Segmented
              value={xAxis}
              onChange={setXAxis}
              options={[
                { value: "time", label: "Tiempo" },
                { value: "trade", label: "Trades" },
              ]}
            />
          </Field>
        </>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            <Field label="Locates min">
              <NumberInput value={mlMin} onChange={setMlMin} min={0} step={0.5} />
            </Field>
            <Field label="max">
              <NumberInput value={mlMax} onChange={setMlMax} min={0} step={0.5} />
            </Field>
            <Field label="pasos">
              <NumberInput value={mlSteps} onChange={setMlSteps} min={2} max={12} step={1} />
            </Field>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            <Field label="Slippage min %">
              <NumberInput value={msMin} onChange={setMsMin} min={0} step={0.05} />
            </Field>
            <Field label="max">
              <NumberInput value={msMax} onChange={setMsMax} min={0} step={0.05} />
            </Field>
            <Field label="pasos">
              <NumberInput value={msSteps} onChange={setMsSteps} min={2} max={12} step={1} />
            </Field>
          </div>
          <Field label="Eje Z">
            <Segmented
              value={zMetric}
              onChange={setZMetric}
              options={[
                { value: "return_net_pct", label: "Retorno" },
                { value: "sharpe", label: "Sharpe" },
                { value: "expectancy", label: "EV" },
              ]}
            />
          </Field>
          <Field label="Representacion">
            <Segmented
              value={plot3d}
              onChange={setPlot3d}
              options={[
                { value: "3d", label: "Superficie 3D" },
                { value: "heatmap", label: "Mapa plano" },
              ]}
            />
          </Field>
        </>
      )}

      <Field label="Gastos fijos mensuales ($)" hint="Plataforma, datos, etc. Se restan mes a mes.">
        <NumberInput value={expenses} onChange={setExpenses} min={0} step={50} />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Desde">
          <TextInput type="date" value={from} onChange={setFrom} />
        </Field>
        <Field label="Hasta">
          <TextInput type="date" value={to} onChange={setTo} />
        </Field>
      </div>
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, marginTop: -6, lineHeight: 1.45 }}>
        Vacio = todo el histórico. Acotar las fechas es lo que abarata la prueba: el coste va con los
        dias·ticker cargados.
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
        {nPoints} backtests · unos {estLabel} estimados. Bloquea la maquina mientras corre.
      </div>

      {busy ? (
        <>
          <ProgressBar pct={progress} label="Ejecutando" />
          <button
            type="button"
            onClick={cancel}
            style={{
              width: "100%",
              padding: "8px 12px",
              fontSize: 12,
              fontFamily: font.sans,
              border: `0.5px solid ${color.border}`,
              borderRadius: 5,
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
          onClick={view === "curvas" ? launchCurves : launchMatrix}
          disabled={!strategy || loading}
          label={view === "curvas" ? "Generar curvas" : "Generar matriz"}
        />
      )}
    </>
  );

  /* ─────────────────── RESULTADOS ─────────────────── */
  let results: React.ReactNode;

  const unitNote = (
    <ReadingNote>
      <strong>Sobre el slippage.</strong> El simulador lo aplica como una fraccion
      (<code>precio × slippage</code>), pero el campo de la pagina de Backtester se titula
      &ldquo;Slippage (%)&rdquo;: lo que escribes ahi acaba valiendo cien veces mas. Tu corrida
      guardada tiene <code>{String(run?.backtest_params?.slippage ?? 0)}</code>, que son{" "}
      <strong>{savedSlipPct.toFixed(3)}%</strong> reales. Aqui los ejes van en porcentaje de
      verdad.
    </ReadingNote>
  );

  if (loading) {
    results = <Placeholder>Cargando los trades de la estrategia…</Placeholder>;
  } else if (!run || !strategy) {
    results = <Placeholder>Elige arriba una estrategia que tenga un backtest guardado.</Placeholder>;
  } else if (busy) {
    results = (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <SectionHead
          title="Re-ejecutando backtests"
          hint="Las velas se cargan una sola vez; a partir de ahi cada punto es solo simulacion."
        />
        <ProgressBar pct={progress} label={`${nPoints} puntos`} />
        <Placeholder>
          El primer tramo (hasta el 10%) es la carga de velas de minuto. El resto avanza punto a
          punto.
        </Placeholder>
      </div>
    );
  } else if (view === "curvas") {
    results = curves ? (
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        {stale && <StaleNotice onRun={launchCurves} />}
        <section>
          <SectionHead
            title="Modelizacion de locates"
            hint={`Una curva por coste de locates, con ${curves.slippage}% de slippage fijo. Donde la curva cruza por debajo del capital inicial, ese coste ya no es asumible.`}
          />
          <LocatesCurvesChart curves={curves.curves} axis={xAxis} initCash={initCash} />
        </section>

        <section>
          <TileGrid>
            <MetricTile
              label="Locates maximo asumible"
              value={curves.break_even != null ? `$${curves.break_even.toFixed(2)}` : "fuera de rango"}
              sub="por cada 100 acciones"
              hint="Coste al que el retorno NETO de gastos cruza cero."
              tone={color.copper}
            />
            <MetricTile
              label="Locates del backtest"
              value={`$${savedLocates.toFixed(2)}`}
              sub={
                curves.break_even != null
                  ? `margen de ${(((curves.break_even - savedLocates) / Math.max(savedLocates, 0.01)) * 100).toFixed(0)}%`
                  : "lo que usaste"
              }
              hint="El coste con el que se ejecuto la corrida guardada."
            />
          </TileGrid>

          <div style={{ marginTop: 18 }}>
            <PlainStats
              items={[
                {
                  label: "Carga de velas",
                  value: `${curves.load_seconds} s`,
                  sub: `${fmt.int(curves.n_groups)} dias-ticker`,
                  help: "Se paga una sola vez por ejecucion: leer las velas de minuto y traducir la estrategia a señales de entrada y salida.",
                },
                { label: "Barrido", value: `${curves.sweep_seconds} s`, sub: `${curves.curves.length} backtests` },
                {
                  label: "Slippage aplicado",
                  value: `${curves.slippage} %`,
                  help: "Fijo en todas las curvas: aqui solo se mueve el coste de locates.",
                },
                {
                  label: "Gastos fijos",
                  value: curves.monthly_expenses ? `$${curves.monthly_expenses} / mes` : "ninguno",
                  help: "Se restan mes a mes del capital y cuentan para el punto de equilibrio.",
                },
              ]}
            />
          </div>
        </section>

        <section>
          <SectionHead title="Resultado por coste de locates" />
          <DataTable
            columns={["Locates $/100", "Retorno neto %", "Max DD %", "Sharpe", "PF", "EV/trade", "Trades", "seg"]}
            rows={curves.curves.map((c) => [
              `$${c.locates_cost}`,
              <span key="r" style={{ color: (c.metrics.return_net_pct ?? 0) >= 0 ? color.profit : color.loss }}>
                {fmt.num(c.metrics.return_net_pct, 1)}
              </span>,
              fmt.num(c.metrics.max_drawdown_pct, 1),
              fmt.num(c.metrics.sharpe, 2),
              fmt.num(c.metrics.profit_factor, 2),
              fmt.num(c.metrics.expectancy, 2),
              fmt.int(c.metrics.total_trades),
              c.seconds,
            ])}
          />
        </section>

        {unitNote}
      </div>
    ) : (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        <Placeholder>
          Barre varios costes de locates y dibuja una curva de rentabilidad por cada uno, para ver a
          partir de que precio la estrategia deja de compensar.
        </Placeholder>
        {unitNote}
      </div>
    );
  } else {
    results = matrix ? (
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        {stale && <StaleNotice onRun={launchMatrix} />}
        <section>
          <SectionHead
            title="Matriz locates × slippage"
            hint={`${matrix.n_points} backtests reales, uno por celda. X = coste de locates, Y = slippage, Z = ${Z_LABELS[zMetric]}.`}
          />
          {plot3d === "3d" ? (
            <LocatesSlippageSurface
              data={matrix}
              metricKey={zMetric}
              metricLabel={Z_LABELS[zMetric]}
              showZeroPlane
              operating={operating}
            />
          ) : (
            <LocatesSlippageHeatmap
              data={matrix}
              metricKey={zMetric}
              metricLabel={Z_LABELS[zMetric]}
              operating={operating}
            />
          )}
        </section>

        <section>
          <PlainStats
            items={[
              { label: "Backtests", value: fmt.int(matrix.n_points), sub: `${matrix.sweep_seconds} s de barrido` },
              {
                label: "Carga de velas",
                value: `${matrix.load_seconds} s`,
                sub: `${fmt.int(matrix.n_groups)} dias-ticker`,
                help: "Se paga una sola vez: leer las velas y traducir la estrategia a señales.",
              },
              {
                label: "Primer punto",
                value: `${matrix.first_point_seconds} s`,
                help: "Mas caro que el resto porque incluye traducir la estrategia a señales de entrada y salida.",
              },
              {
                label: "Puntos siguientes",
                value: `${matrix.seconds_per_point} s`,
                help: "Media. Reutilizan las señales cacheadas: ni los locates ni el slippage cambian CUANDO entra o sale la estrategia, solo cuanto cuesta cada operacion.",
              },
            ]}
          />
        </section>

        <section>
          <SectionHead
            title="Frontera de rentabilidad"
            hint="Para cada nivel de slippage, el coste de locates al que el retorno cruza cero. Es la lectura practica de la matriz."
          />
          <DataTable
            columns={["Slippage %", "Locates maximo asumible"]}
            rows={matrix.frontier.map((f) => [
              `${f.slippage}%`,
              f.break_even_locates != null ? (
                <span key="b" style={{ color: color.copper }}>${f.break_even_locates.toFixed(2)}</span>
              ) : (
                <span key="b" style={{ color: color.textMuted }}>
                  {(matrix.grids.return_net_pct?.[matrix.slippage_values.indexOf(f.slippage)]?.[0] ?? 0) > 0
                    ? "aguanta todo el rango"
                    : "pierde en todo el rango"}
                </span>
              ),
            ])}
          />
        </section>

        {unitNote}
      </div>
    ) : (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {err && <ErrorBox>{err}</ErrorBox>}
        <Placeholder>
          Ejecuta un backtest real por cada combinacion de coste de locates y slippage, y dibuja la
          superficie resultante. El punto donde atraviesa el plano cero es donde la estrategia deja de
          ganar.
        </Placeholder>
        {unitNote}
      </div>
    );
  }

  return { config, results };
}
