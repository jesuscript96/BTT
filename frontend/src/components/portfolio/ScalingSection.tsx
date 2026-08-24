"use client";

// F2 — Modelos de escalado y ponderacion, y su comparativa.
//
// Dos "motores" al estilo de los modulos de Robustez: cada uno devuelve
// {config, results} y la pestaña Portfolio los monta en su rejilla. Comparten
// la configuracion de modelo (modelCfg vive en PortfolioTab): lo que se ajusta
// en "Escalado y pesos" es la base que usa la comparativa.

import React, { useMemo, useRef, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import {
  DataTable,
  ErrorBox,
  Field,
  NumberInput,
  Placeholder,
  RunButton,
  SectionHead,
  Segmented,
  Select,
  fmt,
} from "@/components/robustez/shared";
import { Help, StaleNotice, Verdict } from "@/components/robustez/help";
import { StatSheet, InlineStats } from "./StatSheet";
import { WeightsArea } from "./charts/WeightsArea";
import { CompareCurves, CompareDrawdown, type ModelYMode } from "./charts/CompareCurves";
import { SERIES_PALETTE } from "./charts/PortfolioCurves";
import { PnlCalendar } from "./PnlCalendar";
import { CorrelationMatrix } from "./charts/CorrelationMatrix";
import { DrawdownRibbon } from "@/components/robustez/charts/BasicCharts";
import { SpaghettiChart, DistributionChart } from "@/components/robustez/charts/MonteCarloCharts";
import { FundingSection, LossesSection } from "@/components/robustez/charts/MonteCarloExtras";
import { realLossStatsFromDaily } from "@/lib/robustez/loss_stats";
import { runPortfolioMc } from "@/lib/api_portfolio_lab";
import type { MonteCarloOut } from "@/lib/api_robustez";
import { ChevronRight } from "lucide-react";
import {
  runPortfolioScaling,
  runPortfolioScalingCompare,
  type RebalanceFreq,
  type ScalingCfg,
  type ScalingCompareResult,
  type ScalingOut,
  type ScalingReqIn,
  type ScalingVariantIn,
  type WeightingCfg,
} from "@/lib/api_portfolio_lab";

/* ── Configuracion compartida ────────────────────────────────────── */

export interface ExecCfg {
  init_cash: number;
  fees: number;
  fee_type: "FLAT" | "PERCENT";
  slippage_pct: number;
  locates_cost: number;
  monthly_expenses: number;
  start_date: string;
  end_date: string;
}

export interface ModelCfg {
  rebalance: RebalanceFreq;
  lookback_days: number;
  cap_global_pct: number;
  scaling: ScalingCfg;
  weighting: WeightingCfg;
}

export const DEFAULT_MODEL_CFG: ModelCfg = {
  rebalance: "M",
  lookback_days: 90,
  cap_global_pct: 0,
  scaling: { model: "fixed", base_risk: 100, pct: 1, delta: 500, kelly_mult: 0.5, threshold_equity: 20000 },
  weighting: { model: "equal", floor: 0.1, cap_strat_pct: 0 },
};

const SCALING_LABELS: Record<string, string> = {
  fixed: "$ fijo por trade",
  percent: "% lineal del capital",
  fixed_ratio: "Fix ratio (Ryan Jones)",
  kelly: "Kelly",
  combinatoria: "Combinatoria (fix ratio → Kelly)",
};

const WEIGHT_LABELS: Record<string, string> = {
  equal: "Iguales",
  hrp: "HRP (López de Prado)",
  momentum: "Momentum (ventana)",
  ev: "EV normalizado (ventana)",
  dd: "Sensible al drawdown",
};

interface Ctx {
  selectedIds: string[];
  names: string[]; // en el MISMO orden que selectedIds
  execCfg: ExecCfg;
  modelCfg: ModelCfg;
  setModelCfg: React.Dispatch<React.SetStateAction<ModelCfg>>;
}

function reqBody(ctx: Ctx): ScalingReqIn {
  const { execCfg: e, modelCfg: m } = ctx;
  return {
    strategy_ids: ctx.selectedIds,
    init_cash: e.init_cash,
    fees: e.fees,
    fee_type: e.fee_type,
    slippage_pct: e.slippage_pct,
    locates_cost: e.locates_cost,
    monthly_expenses: e.monthly_expenses,
    start_date: e.start_date || null,
    end_date: e.end_date || null,
    rebalance: m.rebalance,
    lookback_days: m.lookback_days,
    cap_global_pct: m.cap_global_pct,
    scaling: m.scaling,
    weighting: m.weighting,
  };
}

/** Formato para retornos que pueden ser astronomicos (kelly sin costes). */
const fmtBig = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 100000) return `${v.toExponential(1).replace("+", "")} %`;
  return fmt.pct(v);
};

/* ── Conclusion "AHORA" ──────────────────────────────────────────── */

function ConclusionNow({ out, names }: { out: ScalingOut; names: string[] }) {
  const now = out.now;
  if (!now) return null;
  // Con escalados en $ (fijo, fix ratio) el titular util es el importe: el %
  // sale sobre la equity FINAL y parece ridiculo siendo correcto ($100 sobre
  // una cuenta que crecio a $38k = "0,26%"). Con % y kelly, al reves.
  const dollarModel = ["fixed", "fixed_ratio"].includes(String((out.config.scaling as ScalingCfg)?.model));
  return (
    <div
      style={{
        background: color.bgSurface,
        border: `0.5px solid ${color.border}`,
        borderLeft: `2px solid ${color.copper}`,
        borderRadius: `0 ${radius.md} ${radius.md} 0`,
        padding: "14px 18px",
      }}
    >
      <div style={{ fontSize: 10, letterSpacing: "0.11em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans, marginBottom: 10 }}>
        Qué usar AHORA — último rebalanceo ({now.date})
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(180px, 240px) minmax(0, 1fr)", gap: "10px 28px", alignItems: "start" }}>
        <div>
          <div style={{ fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: color.textMuted, fontFamily: font.sans }}>
            Riesgo por trade
          </div>
          <div style={{ fontSize: 22, fontFamily: font.mono, color: color.textHigh, lineHeight: 1.2 }}>
            {dollarModel ? fmt.money(now.x, 0) : fmt.pct(now.x_pct)}
          </div>
          <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textSecondary }}>
            {dollarModel
              ? `= ${fmt.pct(now.x_pct)} del capital actual (${fmt.money(now.equity, 0)})`
              : `${fmt.money(now.x, 0)} sobre ${fmt.money(now.equity, 0)}`}
          </div>
          {now.note && (
            <div style={{ marginTop: 6, fontSize: 10.5, fontFamily: font.sans, color: color.warning, lineHeight: 1.45 }}>
              {now.note}
            </div>
          )}
          {now.w_fallback && (
            <div style={{ marginTop: 6, fontSize: 10.5, fontFamily: font.sans, color: color.warning, lineHeight: 1.45 }}>
              Los pesos de este rebalanceo son IGUALES a la fuerza: el modelo de reparto no tenía
              muestra suficiente en la ventana (hacen falta ~20 sesiones). Amplía la ventana de
              estimación o el periodo.
            </div>
          )}
          {out.cap_hits > 0 && (
            <div style={{ marginTop: 6, fontSize: 10.5, fontFamily: font.sans, color: out.cap_hits / Math.max(1, out.n_rebalances) > 0.5 ? color.warning : color.textMuted, lineHeight: 1.45 }}>
              Tu tope recortó el size en {out.cap_hits} de {out.n_rebalances} rebalanceos.
              {out.cap_hits / Math.max(1, out.n_rebalances) > 0.5 &&
                " El modelo vive por encima de tu tolerancia: baja la fracción de Kelly hasta que el tope solo salte de vez en cuando — el tope debe ser red de seguridad, no la regla de sizing."}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {names.map((nm, i) => {
            const w = (now.weights[i] || 0) * 100;
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <span style={{ fontSize: 11, fontFamily: font.sans, color: color.textPrimary, width: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>
                  {nm}
                </span>
                <div style={{ flex: 1, minWidth: 40, height: 8, background: color.bgElevated, borderRadius: radius.pill, overflow: "hidden" }}>
                  <div style={{ width: `${Math.min(100, w)}%`, height: "100%", background: SERIES_PALETTE[i % SERIES_PALETTE.length], opacity: 0.8 }} />
                </div>
                <span style={{ fontSize: 11.5, fontFamily: font.mono, color: color.textHigh, width: 52, textAlign: "right", flexShrink: 0 }}>
                  {w.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── Controles del modelo ────────────────────────────────────────── */

/** Titulo de grupo DENTRO de la tarjeta de configuracion: destaca y separa
 *  (peticion expresa: los grupos no se distinguian de los campos). */
function GroupTitle({ children, help }: { children: React.ReactNode; help?: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        borderTop: `0.5px solid ${color.border}`,
        paddingTop: 12,
        marginTop: 2,
      }}
    >
      <span style={{ fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: color.textHigh, fontFamily: font.sans, fontWeight: 600 }}>
        {children}
      </span>
      {help && <Help title={String(children)} width={360}>{help}</Help>}
    </div>
  );
}

function ModelFields({ cfg, setCfg }: { cfg: ModelCfg; setCfg: Ctx["setModelCfg"] }) {
  const s = cfg.scaling;
  const w = cfg.weighting;
  const setS = (patch: Partial<ScalingCfg>) => setCfg((c) => ({ ...c, scaling: { ...c.scaling, ...patch } }));
  const setW = (patch: Partial<WeightingCfg>) => setCfg((c) => ({ ...c, weighting: { ...c.weighting, ...patch } }));
  const model = s.model;
  return (
    <>
      <GroupTitle
        help={
          <>
            Decide <strong>cuánto dinero se arriesga en cada trade</strong> según cómo va la cuenta.
            <br />
            <br />
            <strong>$ fijo</strong>: siempre la misma cantidad, gane o pierda la cuenta. La base más
            conservadora.
            <br />
            <strong>% lineal</strong>: siempre el mismo % del capital vivo — la posición crece si la
            cuenta crece (compound).
            <br />
            <strong>Fix ratio</strong>: como $ fijo, pero sube un escalón cada vez que acumulas
            suficiente beneficio. Agresivo al principio, se calma solo.
            <br />
            <strong>Kelly</strong>: calcula matemáticamente el % que maximiza el crecimiento a largo
            plazo, a partir del historial reciente.
            <br />
            <strong>Combinatoria</strong>: fix ratio para crecer rápido con cuenta pequeña, y Kelly
            cuando la cuenta supera el umbral que fijes.
          </>
        }
      >
        Escalado global
      </GroupTitle>
      <Field label="Modelo">
        <Select
          value={model}
          onChange={(v) => setS({ model: v })}
          options={Object.entries(SCALING_LABELS).map(([value, label]) => ({ value: value as ScalingCfg["model"], label }))}
        />
      </Field>
      {(model === "fixed" || model === "fixed_ratio" || model === "combinatoria") && (
        <Field label="Riesgo base ($ por trade)" hint="lo que arriesga cada trade en el primer escalón">
          <NumberInput value={s.base_risk} onChange={(v) => setS({ base_risk: v })} min={1} step={25} />
        </Field>
      )}
      {model === "percent" && (
        <Field label="% del capital por trade">
          <NumberInput value={s.pct} onChange={(v) => setS({ pct: v })} min={0.1} step={0.5} />
        </Field>
      )}
      {(model === "fixed_ratio" || model === "combinatoria") && (
        <Field label="Delta del fix ratio ($)">
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <NumberInput value={s.delta} onChange={(v) => setS({ delta: v })} min={50} step={100} />
            </div>
            <Help title="Delta del fix ratio" width={380}>
              Es <strong>cuánto beneficio te exige el método para subir de escalón</strong>. Con base
              $100 y delta $500: arriesgas $100/trade hasta ganar $500; entonces pasas a $200/trade,
              y el siguiente escalón te exige $1.000 más (2×500), el siguiente $1.500 más… Cada
              escalón cuesta más que el anterior, así que el riesgo crece rápido al principio y se
              frena solo.
              <br />
              <br />
              <strong>Referencias (delta como % del capital inicial):</strong>
              <br />• <strong>Agresivo</strong>: menos del ~10% de la cuenta. Con $10.000, delta $500
              = doblas el riesgo tras ganar solo un +5%. Crece muy rápido — y también baja rápido en
              rachas malas.
              <br />• <strong>Equilibrado</strong>: entre el 10% y el 25% (delta $1.000–2.500 con
              $10.000).
              <br />• <strong>Prudente</strong>: más del 25% de la cuenta (delta $2.500+): doblar el
              riesgo te exige haber ganado ya un cuarto de la cuenta.
              <br />
              <br />
              Otra vara útil: delta ≈ 5–10× el riesgo base es agresivo; ≈ 25× o más, prudente.
            </Help>
          </div>
        </Field>
      )}
      {(model === "kelly" || model === "combinatoria") && (
        <Field label="Fracción de Kelly">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Segmented
              value={String(s.kelly_mult) as "0.25" | "0.5" | "1"}
              onChange={(v) => setS({ kelly_mult: parseFloat(v) })}
              options={[
                { value: "0.25", label: "¼ Kelly" },
                { value: "0.5", label: "½ Kelly" },
                { value: "1", label: "Óptima" },
              ]}
            />
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, flexShrink: 0 }}>
                o a mano:
              </span>
              <div style={{ width: 90 }}>
                <NumberInput value={s.kelly_mult} onChange={(v) => setS({ kelly_mult: v })} min={0.05} max={1} step={0.05} />
              </div>
              <Help title="Fracción a mano" width={330}>
                Si tu tope global salta en la mayoría de rebalanceos, baja aquí la fracción (0,15;
                0,10…) hasta que el modelo viva por debajo del tope y sus subidas y bajadas vuelvan a
                mover tu size de verdad. El panel «Qué usar ahora» te dice en cuántos rebalanceos
                recortó el tope.
              </Help>
            </div>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
              de dónde sale el número
              <Help title="Cómo calcula Kelly" width={380}>
                Kelly mira la <strong>ventana de estimación</strong> (los últimos X días del propio
                portfolio) y calcula f* = media ÷ varianza de su R diaria: el % del capital que habría
                maximizado el crecimiento EN ESA ventana. Problema: asume que esa muestra es toda la
                verdad, así que <strong>siempre sobreapuesta</strong> — un solo día malo fuera de
                muestra a esos tamaños funde la cuenta. Por eso: (1) usa fracciones (½ o ¼), que
                moderan el modelo entero; (2) hay un techo interno del 25%; y (3) tu tope global corta
                por encima de todo. La nota del panel «Qué usar ahora» te dice siempre cuánto pedía el
                modelo en crudo y qué lo recortó.
              </Help>
            </span>
          </div>
        </Field>
      )}
      {model === "combinatoria" && (
        <Field label="Umbral de cambio ($)" hint="con la cuenta por debajo manda fix ratio; por encima, Kelly">
          <NumberInput value={s.threshold_equity} onChange={(v) => setS({ threshold_equity: v })} min={0} step={1000} />
        </Field>
      )}

      <GroupTitle
        help={
          <>
            Decide <strong>qué parte del riesgo total se lleva cada estrategia</strong>. Se recalcula
            en cada rebalanceo, mirando SOLO datos anteriores a esa fecha.
            <br />
            <br />
            <strong>Iguales</strong>: todas pesan lo mismo.
            <br />
            <strong>HRP</strong> (López de Prado): agrupa las estrategias que se parecen y reparte
            para que ningún «clúster» domine el riesgo — castiga a las que van correlacionadas y a
            las más volátiles.
            <br />
            <strong>Momentum</strong>: más peso a la que mejor ha rendido en la ventana.
            <br />
            <strong>EV</strong>: más peso a la que más gana POR TRADE (expectancy) en la ventana.
            <br />
            <strong>Drawdown</strong>: baja el peso de una estrategia cuanto más hundida esté respecto
            a su peor caída histórica; en máximos pesa entero.
          </>
        }
      >
        Reparto de pesos
      </GroupTitle>
      <Field label="Modelo">
        <Select
          value={w.model}
          onChange={(v) => setW({ model: v })}
          options={Object.entries(WEIGHT_LABELS).map(([value, label]) => ({ value: value as WeightingCfg["model"], label }))}
        />
      </Field>
      {w.model !== "equal" && (
        <Field label={w.model === "dd" ? "Suelo del multiplicador" : "Suelo relativo del peso"}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <NumberInput value={w.floor} onChange={(v) => setW({ floor: v })} min={0} max={1} step={0.05} />
            </div>
            <Help title="Suelo" width={340}>
              {w.model === "dd" ? (
                <>
                  Cuando una estrategia está en su peor caída histórica, su exposición no baja de esta
                  fracción (0,25 = como mínimo un cuarto de lo normal). Sin suelo, una mala racha la
                  apagaría del todo y nunca podría recuperarse dentro del portfolio.
                </>
              ) : (
                <>
                  Ninguna estrategia viva baja de <strong>suelo × peso igualitario</strong>. Con 2
                  estrategias y suelo 0,1, ninguna pesa menos del 5%. Evita que el modelo apague por
                  completo una estrategia por una ventana mala — mañana puede ser la buena.
                </>
              )}
            </Help>
          </div>
        </Field>
      )}

      <GroupTitle
        help={
          <>
            <strong>Rebalanceo</strong>: cada cuánto se revisan el escalado y los pesos. Entre
            rebalanceos, los tamaños quedan congelados.
            <br />
            <br />
            <strong>Ventana de estimación</strong>: cuántos días hacia atrás miran Kelly, HRP,
            momentum, EV y drawdown para decidir. Corta = reacciona rápido pero con más ruido; larga =
            estable pero lenta en adaptarse.
            <br />
            <br />
            <strong>Topes de size</strong>: tu límite duro, en % del capital. El global corta el
            riesgo por trade del modelo; el de estrategia corta lo que puede llevarse una sola. Si el
            modelo pide más, se aplica TU tope y el exceso se queda sin desplegar (no se pasa a otra
            estrategia).
          </>
        }
      >
        Rebalanceo y topes
      </GroupTitle>
      <Field label="Frecuencia de revisión">
        <Segmented
          value={cfg.rebalance}
          onChange={(v) => setCfg((c) => ({ ...c, rebalance: v }))}
          options={[
            { value: "D", label: "Diario" },
            { value: "W", label: "Semanal" },
            { value: "M", label: "Mensual" },
          ]}
        />
      </Field>
      <Field
        label="Ventana de estimación (días)"
        hint="mínimo útil: ~20 SESIONES de mercado dentro de la ventana (≈30 días civiles). Con menos, Kelly cae al % base y los repartos a iguales — y lo verás avisado"
      >
        <NumberInput value={cfg.lookback_days} onChange={(v) => setCfg((c) => ({ ...c, lookback_days: v }))} min={30} step={30} />
      </Field>
      <Field
        label="Tope MÁXIMO por trade (% del capital · 0 = sin tope)"
        hint="techo duro global: ningún trade arriesga más de esto, pida lo que pida el modelo"
      >
        <NumberInput value={cfg.cap_global_pct} onChange={(v) => setCfg((c) => ({ ...c, cap_global_pct: v }))} min={0} step={0.5} />
      </Field>
      <Field
        label="Tope MÁXIMO por estrategia (% del capital · 0 = sin tope)"
        hint="techo de lo que puede llevarse UNA sola estrategia por trade, aunque los pesos le den más"
      >
        <NumberInput value={w.cap_strat_pct} onChange={(v) => setW({ cap_strat_pct: v })} min={0} step={0.5} />
      </Field>
      <p style={{ margin: 0, fontSize: 10, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
        Los dos son techos — mínimo no hay: cuando el modelo baja el size, te está protegiendo.
      </p>
    </>
  );
}

/* ── Motor: Escalado y pesos ─────────────────────────────────────── */

export function useScalingSection(ctx: Ctx): { config: React.ReactNode; results: React.ReactNode } {
  const [out, setOut] = useState<ScalingOut | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ranKey, setRanKey] = useState("");
  const [yMode, setYMode] = useState<ModelYMode>("usd");
  const [mcSims, setMcSims] = useState(5000);
  const [mcOut, setMcOut] = useState<MonteCarloOut | null>(null);
  const [mcRunning, setMcRunning] = useState(false);
  const [mcErr, setMcErr] = useState<string | null>(null);
  const [showCal, setShowCal] = useState(false);

  const key = JSON.stringify(reqBody(ctx));
  const stale = out != null && ranKey !== key;

  const run = async () => {
    if (!ctx.selectedIds.length || running) return;
    setRunning(true);
    setError(null);
    try {
      const res = await runPortfolioScaling(reqBody(ctx));
      setOut(res);
      setRanKey(key);
      setMcOut(null); // el MC anterior era de otro modelo/configuracion
      setMcErr(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo calcular el modelo");
    } finally {
      setRunning(false);
    }
  };

  const runMc = async () => {
    if (!out || out.ruined || mcRunning) return;
    setMcRunning(true);
    setMcErr(null);
    try {
      // Bootstrap sobre los RETORNOS diarios del modelo (compound, risk 1 ->
      // eq *= 1 + v/100 replica exactamente ese retorno).
      const init = Number(out.config.init_cash) || ctx.execCfg.init_cash;
      const rets: number[] = [];
      let prev = init;
      for (const v of out.equity) {
        rets.push(prev > 0 ? (v / prev - 1) * 100 : 0);
        prev = v;
      }
      setMcOut(
        await runPortfolioMc({
          values: rets,
          init_cash: init,
          simulations: mcSims,
          method: "bootstrap",
          mode: "compound",
          risk_pct: 1,
          ruin_pct: 50,
        }),
      );
    } catch (e) {
      setMcErr(e instanceof Error ? e.message : "No se pudo simular");
    } finally {
      setMcRunning(false);
    }
  };

  const names = out ? out.per_strategy.map((p) => p.name) : ctx.names;

  // Lado REAL de los bloques de perdidas y fondeo. En el portfolio no hay
  // trades individuales ni MAE, solo el PnL de cada sesion del modelo
  // combinado: se construye la misma estructura con los huecos vacios y la
  // interfaz oculta sola lo que no aplica.
  const realModelo = useMemo(
    () =>
      out
        ? realLossStatsFromDaily(
            out.calendar,
            out.daily_pnl,
            out.equity,
            Number(out.config.init_cash) || ctx.execCfg.init_cash,
          )
        : null,
    [out, ctx.execCfg.init_cash],
  );

  // El fondeo se juega SIEMPRE por sesiones. El MC del modelo compone con
  // risk_pct=1 sobre el retorno diario en %, asi que esa misma serie es la
  // unidad correcta aqui (mode compound, riesgo 1 -> eq *= 1 + v/100).
  const fundingValuesModelo = useMemo(() => {
    if (!out) return [];
    const init = Number(out.config.init_cash) || ctx.execCfg.init_cash;
    const rets: number[] = [];
    let prev = init;
    for (const v of out.equity) {
      rets.push(prev > 0 ? (v / prev - 1) * 100 : 0);
      prev = v;
    }
    return rets;
  }, [out, ctx.execCfg.init_cash]);

  const config = (
    <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
      <span style={{ fontSize: 10, letterSpacing: "0.11em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans }}>
        Modelos (Escalado y Pesos)
      </span>
      <ModelFields cfg={ctx.modelCfg} setCfg={ctx.setModelCfg} />
      <RunButton onClick={run} loading={running} disabled={!ctx.selectedIds.length} label="Calcular modelo" loadingLabel="Calculando…" />
    </div>
  );

  const m = out?.metrics;
  const results = (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {error && <ErrorBox>{error}</ErrorBox>}
      {stale && out && <StaleNotice onRun={run} label={running ? "Calculando…" : "Re-calcular"} />}
      {!out ? (
        <Placeholder>
          Elige el modelo de escalado, el reparto de pesos y la frecuencia de rebalanceo, y pulsa{" "}
          <strong>Calcular modelo</strong>: la foto completa del portfolio bajo ese modelo — curva,
          drawdown, pesos, métricas, correlación, Monte Carlo y calendario.
        </Placeholder>
      ) : (
        <>
          {out.ruined && (
            <Verdict level="fail" title="Este modelo quiebra la cuenta">
              El capital llegó a cero durante la simulación. Baja la agresividad del escalado o pon topes.
            </Verdict>
          )}
          {/* Recordatorio de que la ejecucion compartida SI aplica aqui. */}
          <p style={{ margin: "-6px 0 0", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
            Ejecución aplicada (de la tarjeta común): capital {fmt.money(Number(out.config.init_cash), 0)} · comisiones{" "}
            {Number(out.config.fees) > 0
              ? String(out.config.fee_type) === "PERCENT"
                // El backend ecoa `fees` ya en FRACCION cuando es PERCENT: se
                // reconvierte para enseñar el % que tecleo el usuario.
                ? `${(Number(out.config.fees) * 100).toFixed(3)}% del valor`
                : `$${out.config.fees} por lado`
              : "sin"}{" "}
            · slippage{" "}
            {Number(out.config.slippage) > 0 ? `${(Number(out.config.slippage) * 100).toFixed(3)}%` : "sin"} · locates{" "}
            {Number(out.config.locates_cost) > 0 ? `$${out.config.locates_cost}/100` : "sin"} · gastos{" "}
            {Number(out.config.monthly_expenses) > 0 ? `$${out.config.monthly_expenses}/mes` : "sin"} · periodo{" "}
            {String(out.config.start_date || "todo")} → {String(out.config.end_date || "hoy")}
          </p>
          <div>
            <SectionHead
              title="Curva del modelo"
              hint={yMode === "usd" ? "Capital en escala logarítmica — los modelos que componen recorren órdenes de magnitud." : yMode === "pct" ? "Retorno acumulado sobre el capital inicial." : "R acumulada: el PnL de cada día medido en unidades del riesgo vigente."}
              right={
                <Segmented
                  value={yMode}
                  onChange={setYMode}
                  options={[
                    { value: "usd", label: "$" },
                    { value: "pct", label: "%" },
                    { value: "r", label: "R" },
                  ]}
                />
              }
            />
            <CompareCurves
              results={[{ label: SCALING_LABELS[String((out.config.scaling as ScalingCfg)?.model)] || "modelo", equity: out.equity, calendar: out.calendar, daily_r_net: out.daily_r_net }]}
              initCash={Number(out.config.init_cash) || ctx.execCfg.init_cash}
              yMode={yMode}
            />
          </div>
          <div>
            <SectionHead title="Drawdown del modelo" />
            <DrawdownRibbon
              equity={out.calendar.map((d, i) => ({ time: Math.floor(Date.parse(`${d}T00:00:00Z`) / 1000), value: out.equity[i] }))}
            />
          </div>
          <div>
            <SectionHead
              title="Evolución de los pesos"
              hint={`${out.n_rebalances} rebalanceos (${String(out.config.rebalance)}). ${out.weight_fallbacks > 0 ? `En ${out.weight_fallbacks} no hubo muestra suficiente y se cayó a pesos iguales.` : "Sin fallbacks."}`}
            />
            <WeightsArea timeline={out.timeline} names={names} />
          </div>
          {m && (
            <div>
              <SectionHead title="Métricas del modelo" hint="Con todos los costes configurados." />
              <StatSheet
                groups={[
                  {
                    title: "Rendimiento",
                    rows: [
                      { label: "Retorno neto", value: fmtBig(m.total_return_pct), sub: fmt.money(m.final_equity, 0), tone: m.total_return_pct >= 0 ? color.profit : color.loss },
                      { label: "CAGR", value: fmtBig(m.cagr_pct) },
                      { label: "Win rate", value: fmt.pct(m.win_rate, 1), sub: `${fmt.int(m.n_trades)} trades` },
                      { label: "Profit factor", value: fmt.num(m.profit_factor) },
                      {
                        label: "Expectancy",
                        value: `${fmt.num(m.expectancy_r)} R`,
                        help: (
                          <>
                            Lo que deja de media cada trade, en R. Equivale exactamente a la fórmula
                            clásica <em>(% aciertos × ganancia media) − (% fallos × pérdida media)</em>:
                            la media del PnL de todos los trades ES esa suma ponderada.
                          </>
                        ),
                      },
                    ],
                  },
                  {
                    title: "Riesgo",
                    rows: [
                      { label: "Max drawdown", value: fmt.pct(m.max_drawdown_pct), tone: color.loss },
                      { label: "DD más largo", value: `${m.longest_dd_days} días`, sub: `${fmt.pct(m.longest_dd_pct_of_span, 1)} del hist.` },
                      { label: "Tiempo en DD", value: fmt.pct(m.time_in_dd_pct, 1) },
                      { label: "Sharpe", value: fmt.num(m.sharpe) },
                      { label: "Ulcer index", value: fmt.num(m.ulcer_index) },
                    ],
                  },
                  {
                    title: "Costes pagados",
                    rows: [
                      { label: "Comisiones", value: fmt.money(out.costs.fees, 0) },
                      { label: "Slippage", value: fmt.money(out.costs.slippage, 0) },
                      { label: "Locates", value: fmt.money(out.costs.locates, 0) },
                      { label: "Gastos fijos", value: fmt.money(out.costs.expenses, 0) },
                    ],
                  },
                ]}
              />
              {out.var && (
                <div style={{ marginTop: 12 }}>
                  <InlineStats
                    center
                    items={[
                      { label: "VaR 95", value: fmt.pct(out.var.var95), tone: color.loss, help: "El día malo típico de este modelo: 1 de cada 20 sesiones pierde más que esto." },
                      { label: "CVaR 95", value: fmt.pct(out.var.cvar95), tone: color.loss, help: "Cuando ese 1-de-20 ocurre, esto es lo que se pierde de media." },
                      { label: "VaR 99", value: fmt.pct(out.var.var99), tone: color.loss },
                      { label: "CVaR 99", value: fmt.pct(out.var.cvar99), tone: color.loss },
                    ]}
                  />
                </div>
              )}
            </div>
          )}

          {/* ── Correlacion (igual que en la imagen general) ── */}
          {out.correlation && (
            <div>
              <SectionHead
                title="Correlación entre estrategias"
                hint="Sobre la R diaria normalizada (la señal pura), solo en el tramo donde ambas coexisten."
              />
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 20, alignItems: "start" }}>
                <CorrelationMatrix corr={out.correlation} names={names} />
                <InlineStats
                  items={[
                    {
                      label: "Correlación media",
                      value: out.correlation.avg_pairwise == null ? "—" : fmt.num(out.correlation.avg_pairwise),
                      tone:
                        out.correlation.avg_pairwise == null
                          ? undefined
                          : out.correlation.avg_pairwise > 0.7
                            ? color.loss
                            : out.correlation.avg_pairwise > 0.3
                              ? color.warning
                              : color.profit,
                      help: "Por debajo de 0,3 la cartera diversifica de verdad; por encima de 0,7 estás comprando la misma apuesta varias veces.",
                    },
                    {
                      label: "Pareja más correlacionada",
                      value: out.correlation.max_pair == null ? "—" : fmt.num(out.correlation.max_pair.corr),
                    },
                  ]}
                />
              </div>
            </div>
          )}

          {/* ── Aportacion por estrategia ── */}
          <div>
            <SectionHead
              title="Aportación por estrategia"
              hint="PnL neto de cada una bajo este modelo, su señal pura en R, y el peso y riesgo que le tocaban en el último rebalanceo."
            />
            <DataTable
              columns={["Estrategia", "Trades", "Win", "PnL neto", "R acum.", "Peso ahora", "Riesgo ahora"]}
              rows={out.per_strategy.map((p, i) => [
                <span key="n" style={{ color: SERIES_PALETTE[i % SERIES_PALETTE.length] }}>{p.name}</span>,
                fmt.int(p.n_trades),
                fmt.pct(p.win_rate, 1),
                <span key="p" style={{ color: p.pnl_net >= 0 ? color.profit : color.loss }}>{fmt.money(p.pnl_net, 0)}</span>,
                fmt.num(p.cum_r, 1),
                p.weight_now != null ? fmt.pct(p.weight_now * 100, 1) : "—",
                p.risk_now != null ? fmt.money(p.risk_now, 0) : "—",
              ])}
            />
          </div>

          {/* ── Monte Carlo del modelo ── */}
          <div>
            <SectionHead
              title="Monte Carlo del modelo"
              hint="Remuestrea los días de ESTE modelo (bootstrap): la clave es el drawdown a tragar — el histórico solo te enseñó un camino."
              right={
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
                  <div style={{ width: 90 }}>
                    <NumberInput value={mcSims} onChange={setMcSims} min={500} max={20000} step={500} />
                  </div>
                  <div style={{ width: 120 }}>
                    <RunButton onClick={runMc} loading={mcRunning} disabled={out.ruined} label="Simular" loadingLabel="Simulando…" />
                  </div>
                </div>
              }
            />
            {mcErr && <ErrorBox>{mcErr}</ErrorBox>}
            {out.ruined ? (
              <p style={{ margin: 0, fontSize: 11.5, fontFamily: font.sans, color: color.warning }}>
                Modelo quebrado: su distribución no es analizable.
              </p>
            ) : !mcOut ? (
              <p style={{ margin: 0, fontSize: 11.5, fontFamily: font.sans, color: color.textMuted }}>
                Pulsa <strong>Simular</strong> para ver la distribución de drawdowns de este modelo.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <InlineStats
                  items={[
                    { label: "DD mediano sim.", value: fmt.pct(mcOut.drawdown?.p50), tone: color.loss },
                    { label: "DD a tragar (1 de 20)", value: fmt.pct(mcOut.dd_tolerance?.p95), tone: color.loss, help: "Para que solo 1 de cada 20 escenarios lo supere, hay que aguantar este drawdown." },
                    { label: "DD a tragar (1 de 100)", value: fmt.pct(mcOut.dd_tolerance?.p99), tone: color.loss },
                    { label: "Prob. acabar perdiendo", value: fmt.pct(mcOut.prob_losing_pct, 1) },
                    { label: "Prob. de ruina (−50%)", value: fmt.pct(mcOut.prob_ruin_pct, 1) },
                    { label: "Balance mediano", value: fmt.money(mcOut.final_balance?.p50, 0) },
                  ]}
                />
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
                  <SpaghettiChart spaghetti={mcOut.spaghetti} bands={mcOut.bands} baseCurve={mcOut.base_curve} initCash={mcOut.init_cash} xLabel="días →" />
                  <DistributionChart
                    hist={mcOut.hist_drawdown}
                    markers={[{ value: mcOut.base_max_drawdown, label: `real ${fmt.pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]}
                    fmtValue={(v) => `${v.toFixed(0)}%`}
                    barColor="var(--color-ec-loss)"
                    caption="Max drawdown de cada escenario simulado (%)."
                  />
                </div>

                {/* Mismos bloques que en Robustez, sobre la serie del modelo. */}
                {realModelo && mcOut.losses && (
                  <LossesSection
                    out={mcOut}
                    real={realModelo}
                    capital={{
                      initCash: mcOut.init_cash,
                      // El MC del modelo compone SIEMPRE sobre el retorno diario
                      // en %, sea cual sea el escalado: el riesgo por operacion
                      // ya esta dentro de esa serie.
                      esPct: true,
                      riskPct: mcOut.risk_pct,
                      riesgoTipo: SCALING_LABELS[String((out.config.scaling as ScalingCfg)?.model)] || undefined,
                      origen: "modelo calculado",
                    }}
                  />
                )}

                {realModelo && (
                  <FundingSection
                    valoresDia={fundingValuesModelo}
                    maeFracs={null}
                    tradesPorDia={null}
                    esPct
                    riskPctDefault={1}
                    nSesiones={out.calendar.length}
                    riskLabel="Multiplicador de exposicion (x1 = 1%)"
                    riskHint="El riesgo por trade ya esta dentro del modelo. Este mando escala la serie entera: 2 = el doble de exposicion."
                  />
                )}
              </div>
            )}
          </div>

          {/* ── Calendario de PnL del modelo ── */}
          <div>
            <button
              type="button"
              onClick={() => setShowCal((v) => !v)}
              aria-expanded={showCal}
              style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "6px 11px", fontSize: 11.5, fontFamily: font.sans, background: "transparent", border: `0.5px solid ${color.border}`, borderRadius: radius.sm, color: showCal ? color.textHigh : color.textSecondary, cursor: "pointer" }}
            >
              <ChevronRight style={{ width: 12, height: 12, strokeWidth: 1.5, transform: showCal ? "rotate(90deg)" : "none", transition: "transform 150ms" }} />
              Calendario de PnL del modelo
            </button>
            {showCal && (
              <div style={{ marginTop: 12 }}>
                <PnlCalendar dates={out.calendar} pnl={out.daily_pnl} counts={out.calendar.map(() => 0)} />
              </div>
            )}
          </div>

          {/* ── La conclusion, al final y sin robar protagonismo ── */}
          <ConclusionNow out={out} names={names} />
        </>
      )}
    </div>
  );

  return { config, results };
}

/* ── Motor: Comparativa ──────────────────────────────────────────── */

export function useCompareSection(ctx: Ctx): { config: React.ReactNode; results: React.ReactNode } {
  const [mode, setMode] = useState<"escalados" | "ponderaciones">("escalados");
  const [res, setRes] = useState<ScalingCompareResult[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ranKey, setRanKey] = useState("");
  const [yMode, setYMode] = useState<ModelYMode>("usd");
  const [visible, setVisible] = useState<boolean[]>([]);
  const toggleVisible = (i: number) => setVisible((v) => v.map((x, k) => (k === i ? !x : x)));

  // Analisis fino del modelo elegido (riesgo a fondo).
  const [anLabel, setAnLabel] = useState<string>("");
  const anRef = useRef<HTMLDivElement>(null);
  const chooseModel = (label: string) => {
    setAnLabel(label);
    setMcOut(null);
    setTimeout(() => anRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };
  const [mcSims, setMcSims] = useState(5000);
  const [mcOut, setMcOut] = useState<MonteCarloOut | null>(null);
  const [mcRunning, setMcRunning] = useState(false);
  const [mcErr, setMcErr] = useState<string | null>(null);
  const [showCal, setShowCal] = useState(false);

  const chosen = res?.find((x) => x.label === anLabel && !x.error && x.equity && x.equity.length > 2) || null;
  const anStats = useMemo(() => {
    if (!chosen?.equity || !chosen.calendar) return null;
    const eq = chosen.equity;
    const rets: number[] = [];
    for (let i = 1; i < eq.length; i++) rets.push(eq[i - 1] > 0 ? eq[i] / eq[i - 1] - 1 : 0);
    const retPct = rets.map((r) => r * 100).sort((a, b) => a - b);
    const q = (p: number) => retPct[Math.max(0, Math.min(retPct.length - 1, Math.floor(p * retPct.length)))];
    const v95 = q(0.05);
    const v99 = q(0.01);
    const tail = (v: number) => {
      const t = retPct.filter((x) => x <= v);
      return t.length ? t.reduce((a, b) => a + b, 0) / t.length : v;
    };
    let peak = eq[0];
    let inDd = 0;
    let sumSq = 0;
    let maxDd = 0;
    for (const v of eq) {
      if (v > peak) peak = v;
      const dd = peak > 0 ? (v / peak - 1) * 100 : 0;
      if (dd < -1e-9) inDd++;
      sumSq += dd * dd;
      if (dd < maxDd) maxDd = dd;
    }
    return {
      dailyPnl: eq.map((v, i) => (i === 0 ? 0 : v - eq[i - 1])),
      returns: rets,
      var95: v95,
      cvar95: tail(v95),
      var99: v99,
      cvar99: tail(v99),
      maxDd,
      ulcer: Math.sqrt(sumSq / eq.length),
      timeInDd: (100 * inDd) / eq.length,
      worstDay: Math.min(...retPct),
    };
  }, [chosen]);

  const runMcDetail = async () => {
    if (!chosen || !anStats || mcRunning) return;
    setMcRunning(true);
    setMcErr(null);
    try {
      // Bootstrap sobre los RETORNOS diarios del modelo: en modo compound con
      // risk_pct=1, eq *= (1 + v/100) reproduce exactamente ese retorno.
      setMcOut(
        await runPortfolioMc({
          values: anStats.returns.map((r) => r * 100),
          init_cash: ctx.execCfg.init_cash,
          simulations: mcSims,
          method: "bootstrap",
          mode: "compound",
          risk_pct: 1,
          ruin_pct: 50,
        }),
      );
    } catch (e) {
      setMcErr(e instanceof Error ? e.message : "No se pudo simular");
    } finally {
      setMcRunning(false);
    }
  };

  const variants: ScalingVariantIn[] = useMemo(() => {
    const s = ctx.modelCfg.scaling;
    const w = ctx.modelCfg.weighting;
    if (mode === "escalados") {
      return [
        { label: "$ fijo", scaling: { ...s, model: "fixed" } },
        { label: "% lineal", scaling: { ...s, model: "percent" } },
        { label: "Fix ratio", scaling: { ...s, model: "fixed_ratio" } },
        { label: "Kelly", scaling: { ...s, model: "kelly" } },
        { label: "Combinatoria", scaling: { ...s, model: "combinatoria" } },
      ];
    }
    return [
      { label: "Iguales", weighting: { ...w, model: "equal" } },
      { label: "HRP", weighting: { ...w, model: "hrp" } },
      { label: "Momentum", weighting: { ...w, model: "momentum" } },
      { label: "EV", weighting: { ...w, model: "ev" } },
      { label: "Drawdown", weighting: { ...w, model: "dd" } },
    ];
  }, [mode, ctx.modelCfg]);

  const key = JSON.stringify({ body: reqBody(ctx), variants });
  const stale = res != null && ranKey !== key;

  const run = async () => {
    if (!ctx.selectedIds.length || running) return;
    setRunning(true);
    setError(null);
    try {
      const r = await runPortfolioScalingCompare({ ...reqBody(ctx), variants });
      setRes(r.results);
      setVisible(r.results.map(() => true));
      setRanKey(key);
      setMcOut(null);
      const firstOk = r.results.find((x) => !x.error && !x.ruined);
      setAnLabel(firstOk?.label || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo comparar");
    } finally {
      setRunning(false);
    }
  };

  const config = (
    <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
      <span style={{ fontSize: 10, letterSpacing: "0.11em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans }}>
        Comparativa de modelos
      </span>
      <Field label="Qué comparar">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <Segmented
            value={mode}
            onChange={setMode}
            options={[
              { value: "escalados", label: "Escalado (size)" },
              { value: "ponderaciones", label: "Reparto (pesos)" },
            ]}
          />
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
            ¿cuál es la diferencia?
            <Help title="Escalado vs Reparto" width={370}>
              El modelo del portfolio tiene DOS mandos independientes, y aquí comparas uno fijando el
              otro:
              <br />
              <br />
              <strong>Escalado (size)</strong> = cuánto dinero se arriesga en total por trade según
              va la cuenta ($ fijo, % lineal, fix ratio, Kelly, combinatoria). Es el acelerador.
              <br />
              <br />
              <strong>Reparto (pesos)</strong> = cómo se divide ese riesgo entre tus estrategias en
              cada rebalanceo (iguales, HRP, momentum, EV, drawdown). Es el volante.
              <br />
              <br />
              Por eso los resultados son tan distintos: comparar escalados enfrenta cinco
              aceleradores con el mismo volante; comparar repartos enfrenta cinco volantes con el
              mismo acelerador. Lo que no se compara se toma de tu configuración de «Modelos
              (Escalado y Pesos)».
            </Help>
          </span>
        </div>
      </Field>
      <p style={{ margin: 0, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
        {mode === "escalados"
          ? `Se enfrentan los 5 escalados, todos con el reparto «${WEIGHT_LABELS[ctx.modelCfg.weighting.model]}» que tienes elegido.`
          : `Se enfrentan los 5 repartos de pesos, todos con el escalado «${SCALING_LABELS[ctx.modelCfg.scaling.model]}» que tienes elegido.`}
      </p>
      <RunButton onClick={run} loading={running} disabled={!ctx.selectedIds.length} label="Comparar" loadingLabel="Comparando…" />
    </div>
  );

  const results = (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {error && <ErrorBox>{error}</ErrorBox>}
      {stale && res && <StaleNotice onRun={run} label={running ? "Comparando…" : "Re-comparar"} />}
      {!res ? (
        <Placeholder>
          Pulsa <strong>Comparar</strong> para correr los cinco modelos sobre los mismos datos y ver
          cuál aguanta mejor con estas estrategias.
        </Placeholder>
      ) : (
        <>
          <div>
            <SectionHead
              title="Modelos frente a frente"
              hint="Mismos datos, mismos costes; solo cambia el modelo. El check «Ver» enseña u oculta cada modelo en las curvas y drawdowns de abajo. «Riesgo ahora» es el % por trade del último rebalanceo; «¿Quiebra?» marca los que llevaron la cuenta a cero."
            />
            <DataTable
              columns={["Ver", "Modelo", "Retorno", "CAGR", "Max DD", "Sharpe", "Ulcer", "PF", "Riesgo ahora", "¿Quiebra?"]}
              align={["left", "left", "right", "right", "right", "right", "right", "right", "right", "right"]}
              rows={res.map((r, i) => {
                if (r.error) return ["", r.label, <span key="e" style={{ color: color.warning }}>{r.error}</span>, "—", "—", "—", "—", "—", "—", "—"];
                const mm = r.metrics!;
                const isChosen = r.label === anLabel;
                return [
                  // Check de visibilidad: enseña u oculta este modelo en las
                  // curvas superpuestas y en los drawdowns comparados de abajo.
                  <input
                    key="v"
                    type="checkbox"
                    checked={visible[i] ?? true}
                    onChange={() => toggleVisible(i)}
                    title="Mostrar u ocultar en las curvas y drawdowns de abajo"
                    style={{ accentColor: "var(--color-ec-copper)", cursor: "pointer" }}
                  />,
                  <span key="l" style={{ color: SERIES_PALETTE[i % SERIES_PALETTE.length], opacity: (visible[i] ?? true) ? 1 : 0.4 }}>
                    {isChosen ? "▸ " : ""}
                    {r.label}
                  </span>,
                  <span key="r" style={{ color: mm.total_return_pct >= 0 ? color.profit : color.loss }}>{fmtBig(mm.total_return_pct)}</span>,
                  fmtBig(mm.cagr_pct),
                  <span key="d" style={{ color: color.loss }}>{fmt.pct(mm.max_drawdown_pct)}</span>,
                  fmt.num(mm.sharpe),
                  fmt.num(mm.ulcer_index),
                  fmt.num(mm.profit_factor),
                  r.now ? fmt.pct(r.now.x_pct) : "—",
                  r.ruined ? <span key="q" style={{ color: color.loss }}>SÍ</span> : "no",
                ];
              })}
            />
          </div>
          <div>
            <SectionHead
              title="Curvas superpuestas"
              hint="Pulsa un modelo en la leyenda para ocultarlo o volver a enseñarlo."
              right={
                <Segmented
                  value={yMode}
                  onChange={setYMode}
                  options={[
                    { value: "usd", label: "$" },
                    { value: "pct", label: "%" },
                    { value: "r", label: "R" },
                  ]}
                />
              }
            />
            <CompareCurves results={res} initCash={ctx.execCfg.init_cash} yMode={yMode} visible={visible} onToggle={toggleVisible} />
          </div>
          <div>
            <SectionHead
              title="Drawdowns comparados"
              hint="La caída desde máximos de cada modelo, en %: cuánto duele cada camino, no solo cuánto rinde."
            />
            <CompareDrawdown results={res} visible={visible} onToggle={toggleVisible} />
          </div>

          {/* ── Analisis fino del modelo que te guste ── */}
          <div ref={anRef}>
            <SectionHead
              title="Análisis fino del modelo elegido"
              hint="Elige UNO de los modelos recién comparados — con el botón «analizar →» de su fila en la tabla de arriba, o aquí — y estúdialo a fondo: VaR/CVaR, Monte Carlo bootstrap y su calendario de PnL."
            />
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <span style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textSecondary }}>Modelo elegido:</span>
              <div style={{ width: 220 }}>
                <Select
                  value={anLabel}
                  onChange={chooseModel}
                  options={res
                    .filter((x) => !x.error)
                    .map((x) => ({ value: x.label, label: x.ruined ? `${x.label} (quiebra)` : x.label }))}
                />
              </div>
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
                (los de la comparativa de arriba, con su misma configuración)
              </span>
            </div>
            {!chosen || !anStats ? (
              <p style={{ margin: 0, fontSize: 11.5, fontFamily: font.sans, color: color.textMuted }}>
                Elige un modelo del desplegable (los quebrados no se pueden analizar a fondo).
              </p>
            ) : chosen.ruined ? (
              <p style={{ margin: 0, fontSize: 11.5, fontFamily: font.sans, color: color.warning }}>
                Este modelo quiebra la cuenta: su distribución de retornos no es analizable. Ponle
                topes o baja la agresividad y re-compara.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <InlineStats
                  items={[
                    { label: "VaR 95", value: fmt.pct(anStats.var95), tone: color.loss, help: "El día malo típico: 1 de cada 20 sesiones pierde MÁS que esto (en % del capital)." },
                    { label: "CVaR 95", value: fmt.pct(anStats.cvar95), tone: color.loss, help: "Cuando ese 1-de-20 ocurre, esto es lo que se pierde DE MEDIA. Siempre peor que el VaR: mide la cola, no el umbral." },
                    { label: "VaR 99", value: fmt.pct(anStats.var99), tone: color.loss, help: "Lo mismo, pero 1 de cada 100 sesiones." },
                    { label: "CVaR 99", value: fmt.pct(anStats.cvar99), tone: color.loss },
                    { label: "DD máx", value: fmt.pct(anStats.maxDd), tone: color.loss, help: "La peor caída desde máximos que tuvo este modelo en el histórico." },
                    { label: "Peor día", value: fmt.pct(anStats.worstDay), tone: color.loss },
                    { label: "Tiempo en DD", value: fmt.pct(anStats.timeInDd, 1), help: "Porcentaje de sesiones que el modelo pasó por debajo de su último máximo — cuánto se sufre, no solo cuánto se cae." },
                    { label: "Ulcer", value: fmt.num(anStats.ulcer), help: "El «dolor medio» del drawdown: castiga las caídas profundas Y largas. Comparativo: menos es mejor; no tiene unidades intuitivas." },
                  ]}
                />

                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontFamily: font.sans, color: color.textSecondary }}>
                    Monte Carlo (bootstrap por día):
                    <Help title="Monte Carlo bootstrap" width={350}>
                      Remuestrea los DÍAS del modelo con reemplazo y recompone miles de historias
                      alternativas: qué habría pasado si la suerte y el orden hubieran sido otros.
                      Lo que importa de aquí son los percentiles de drawdown («a tragar»): el
                      histórico solo te enseñó UN camino; esto te enseña la distribución.
                    </Help>
                  </span>
                  <div style={{ width: 90 }}>
                    <NumberInput value={mcSims} onChange={setMcSims} min={500} max={20000} step={500} />
                  </div>
                  <div style={{ width: 120 }}>
                    <RunButton onClick={runMcDetail} loading={mcRunning} label="Simular" loadingLabel="Simulando…" />
                  </div>
                  {mcErr && <span style={{ fontSize: 11, color: color.loss, fontFamily: font.sans }}>{mcErr}</span>}
                </div>

                {mcOut && (
                  <>
                    <InlineStats
                      items={[
                        { label: "DD mediano sim.", value: fmt.pct(mcOut.drawdown?.p50), tone: color.loss },
                        {
                          label: "DD a tragar (1 de 20)",
                          value: fmt.pct(mcOut.dd_tolerance?.p95),
                          tone: color.loss,
                          help: "Para que solo 1 de cada 20 escenarios lo supere, hay que aguantar este drawdown.",
                        },
                        { label: "DD a tragar (1 de 100)", value: fmt.pct(mcOut.dd_tolerance?.p99), tone: color.loss },
                        { label: "Prob. acabar perdiendo", value: fmt.pct(mcOut.prob_losing_pct, 1), help: "Escenarios que terminan por debajo del capital inicial." },
                        { label: "Prob. de ruina (−50%)", value: fmt.pct(mcOut.prob_ruin_pct, 1), help: "Escenarios que en algún momento pierden la mitad de la cuenta." },
                        { label: "Balance mediano", value: fmt.money(mcOut.final_balance?.p50, 0), help: "La mitad de los escenarios acaba por encima de esto y la otra mitad por debajo." },
                      ]}
                    />
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
                      <SpaghettiChart spaghetti={mcOut.spaghetti} bands={mcOut.bands} baseCurve={mcOut.base_curve} initCash={mcOut.init_cash} xLabel="días →" />
                      <DistributionChart
                        hist={mcOut.hist_drawdown}
                        markers={[{ value: mcOut.base_max_drawdown, label: `real ${fmt.pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]}
                        fmtValue={(v) => `${v.toFixed(0)}%`}
                        barColor="var(--color-ec-loss)"
                        caption="Max drawdown de cada escenario simulado (%)."
                      />
                    </div>
                  </>
                )}

                <div>
                  <button
                    type="button"
                    onClick={() => setShowCal((v) => !v)}
                    aria-expanded={showCal}
                    style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "6px 11px", fontSize: 11.5, fontFamily: font.sans, background: "transparent", border: `0.5px solid ${color.border}`, borderRadius: radius.sm, color: showCal ? color.textHigh : color.textSecondary, cursor: "pointer" }}
                  >
                    <ChevronRight style={{ width: 12, height: 12, strokeWidth: 1.5, transform: showCal ? "rotate(90deg)" : "none", transition: "transform 150ms" }} />
                    Calendario de PnL de este modelo
                  </button>
                  {showCal && chosen.calendar && (
                    <div style={{ marginTop: 12 }}>
                      <PnlCalendar dates={chosen.calendar} pnl={anStats.dailyPnl} counts={chosen.calendar.map(() => 0)} />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );

  return { config, results };
}
