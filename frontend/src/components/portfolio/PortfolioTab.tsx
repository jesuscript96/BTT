"use client";

// Pestaña Portfolio: la "imagen general" lineal (F1).
//
// Izquierda: seleccion de estrategias (ticks) + configuracion de ejecucion.
// Derecha: curvas superpuestas + combinada, metricas agregadas, aportacion
// por estrategia, correlacion, VaR/CVaR y Monte Carlo bootstrap por dia.
//
// Los modelos de escalado (fix ratio, Kelly, HRP, momentum, EV, drawdown) y
// la frecuencia de rebalanceo llegan en la fase 2 como sub-modulos de esta
// misma pestaña.

import React, { useEffect, useMemo, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import {
  ErrorBox,
  Field,
  NumberInput,
  Placeholder,
  ReadingNote,
  RunButton,
  SectionHead,
  Segmented,
  Select,
  TextInput,
  DataTable,
  fmt,
} from "@/components/robustez/shared";
import { StatSheet, InlineStats } from "./StatSheet";
import { Help, PlainStats, StaleNotice, SubTabs, Verdict } from "@/components/robustez/help";
import { DEFAULT_MODEL_CFG, useCompareSection, useScalingSection, type ModelCfg } from "./ScalingSection";
import { SpaghettiChart, DistributionChart } from "@/components/robustez/charts/MonteCarloCharts";
import { DrawdownRibbon } from "@/components/robustez/charts/BasicCharts";
import { PortfolioCurves, SERIES_PALETTE, type XMode, type YMode } from "./charts/PortfolioCurves";
import { CorrelationMatrix } from "./charts/CorrelationMatrix";
import { PnlCalendar } from "./PnlCalendar";
import { ChevronRight } from "lucide-react";
import {
  runPortfolioCombine,
  runPortfolioMc,
  type CombineOut,
  type PortfolioStrategy,
} from "@/lib/api_portfolio_lab";
import type { MonteCarloOut } from "@/lib/api_robustez";

interface Cfg {
  init_cash: number;
  risk_type: "FIXED" | "PERCENT";
  risk_r: number;
  fees: number;
  fee_type: "FLAT" | "PERCENT";
  slippage_pct: number;
  locates_cost: number;
  monthly_expenses: number;
  start_date: string;
  end_date: string;
}

const DEFAULT_CFG: Cfg = {
  init_cash: 10000,
  risk_type: "FIXED",
  risk_r: 100,
  fees: 0,
  fee_type: "FLAT",
  slippage_pct: 0,
  locates_cost: 0,
  monthly_expenses: 0,
  start_date: "",
  end_date: "",
};

export function PortfolioTab({ strategies }: { strategies: PortfolioStrategy[] }) {
  // Solo se estudian las del cuadro "Portfolio" del Baul.
  const pool = useMemo(() => strategies.filter((s) => s.buckets.includes("portfolio") && s.run), [strategies]);

  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [cfg, setCfg] = useState<Cfg>(DEFAULT_CFG);
  const [out, setOut] = useState<CombineOut | null>(null);
  const [ranKey, setRanKey] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [yMode, setYMode] = useState<YMode>("pct");
  const [xMode, setXMode] = useState<XMode>("fecha");
  const [showCalendar, setShowCalendar] = useState(false);

  // F2: sub-pestañas y configuracion compartida de los modelos.
  const [sub, setSub] = useState<"general" | "modelos" | "comparar">("general");
  const [modelCfg, setModelCfg] = useState<ModelCfg>(DEFAULT_MODEL_CFG);

  const [mcOut, setMcOut] = useState<MonteCarloOut | null>(null);
  const [mcSims, setMcSims] = useState(5000);
  const [mcMethod, setMcMethod] = useState<"bootstrap" | "permutacion">("bootstrap");
  const [mcRunning, setMcRunning] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);

  // Las nuevas del cuadro entran marcadas; las elecciones previas se respetan.
  useEffect(() => {
    setChecked((prev) => {
      const next: Record<string, boolean> = {};
      for (const s of pool) next[s.id] = prev[s.id] ?? true;
      return next;
    });
  }, [pool]);

  const selectedIds = pool.filter((s) => checked[s.id]).map((s) => s.id);
  const cfgKey = JSON.stringify({ ids: selectedIds, cfg });
  const stale = out != null && ranKey !== cfgKey;

  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg((c) => ({ ...c, [k]: v }));

  const run = async () => {
    if (!selectedIds.length || running) return;
    setRunning(true);
    setError(null);
    try {
      const res = await runPortfolioCombine({
        strategy_ids: selectedIds,
        init_cash: cfg.init_cash,
        risk_type: cfg.risk_type,
        risk_r: cfg.risk_r,
        fees: cfg.fees,
        fee_type: cfg.fee_type,
        slippage_pct: cfg.slippage_pct,
        locates_cost: cfg.locates_cost,
        monthly_expenses: cfg.monthly_expenses,
        start_date: cfg.start_date || null,
        end_date: cfg.end_date || null,
      });
      setOut(res);
      setRanKey(cfgKey);
      setMcOut(null); // el MC anterior era de otra configuracion
      setMcError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo calcular el portfolio");
    } finally {
      setRunning(false);
    }
  };

  const runMc = async () => {
    // Con la cuenta quebrada, el motor anota 0 en todos los días posteriores:
    // remuestrear esa cola de ceros fantasma diluiría la distribución de
    // drawdowns y la probabilidad de ruina. Mejor no simular.
    if (!out || out.ruined || mcRunning) return;
    setMcRunning(true);
    setMcError(null);
    try {
      const compound = String(out.config.risk_type).toUpperCase() === "PERCENT";
      const res = await runPortfolioMc({
        values: compound ? out.daily_r_net : out.daily_pnl,
        init_cash: Number(out.config.init_cash) || cfg.init_cash,
        simulations: mcSims,
        method: mcMethod,
        mode: compound ? "compound" : "additive",
        risk_pct: Number(out.config.risk_r) || cfg.risk_r,
        ruin_pct: 50,
      });
      setMcOut(res);
    } catch (e) {
      setMcError(e instanceof Error ? e.message : "No se pudo simular");
    } finally {
      setMcRunning(false);
    }
  };

  // Serie de equity en el formato {time, value} que consume el DrawdownRibbon
  // de Robustez, y el recuento de trades por dia para el calendario.
  const eqPoints = useMemo(
    () =>
      out
        ? out.calendar.map((d, i) => ({
            time: Math.floor(Date.parse(`${d}T00:00:00Z`) / 1000),
            value: out.equity[i],
          }))
        : [],
    [out],
  );
  const dayCounts = useMemo(() => {
    if (!out) return [] as number[];
    const c = new Map<string, number>();
    for (const d of out.trades_seq.dates) c.set(d, (c.get(d) || 0) + 1);
    return out.calendar.map((d) => c.get(d) || 0);
  }, [out]);

  // Motores de F2 (hooks: se instancian siempre, pinta solo el activo).
  const sectionCtx = {
    selectedIds,
    names: pool.filter((s) => checked[s.id]).map((s) => s.name),
    execCfg: cfg,
    modelCfg,
    setModelCfg,
  };
  const scalingEngine = useScalingSection(sectionCtx);
  const compareEngine = useCompareSection(sectionCtx);

  if (!pool.length) {
    return (
      <Placeholder>
        El cuadro <strong>Portfolio</strong> está vacío. Ve a la pestaña Baúl y añade estrategias con
        «+ Portfolio» — hacen falta corridas guardadas, idealmente normalizadas.
      </Placeholder>
    );
  }

  const m = out?.metrics;
  const approx = out?.strategies.filter((s) => !s.normalization.normalized) || [];

  const card: React.CSSProperties = {
    background: color.bgSurface,
    border: `0.5px solid ${color.border}`,
    borderRadius: radius.md,
    padding: 16,
  };

  return (
    <div>
      <SubTabs
        value={sub}
        onChange={setSub}
        options={[
          { value: "general", label: "Imagen general" },
          { value: "modelos", label: "Modelos (Escalado y Pesos)" },
          { value: "comparar", label: "Comparativa" },
        ]}
      />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 340px) minmax(0, 1fr)", gap: 18, alignItems: "start" }}>
      {/* ── Rail de configuracion (la ejecucion es comun a las tres vistas).
          maxHeight + scroll interno: con dos tarjetas el rail supera la
          pantalla y, siendo sticky, lo de abajo quedaria inalcanzable. ── */}
      <div style={{ position: "sticky", top: 16, display: "flex", flexDirection: "column", gap: 14, maxHeight: "calc(100vh - 32px)", overflowY: "auto", paddingRight: 2 }}>
      <div style={{ ...card, display: "flex", flexDirection: "column", gap: 13 }}>
        <span style={{ fontSize: 10, letterSpacing: "0.11em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans }}>
          Configuración de ejecución
        </span>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textSecondary, display: "inline-flex", alignItems: "center", gap: 6 }}>
            Estrategias del portfolio
            <Help title="Selección">
              Marca cuáles entran en esta imagen general. Todas se ejecutan con la MISMA configuración y
              el mismo peso — el reparto de pesos desigual y los modelos de escalado llegan en la fase 2.
            </Help>
          </span>
          {pool.map((s) => {
            // El color debe salir del indice dentro de las MARCADAS: los
            // graficos colorean por posicion en el subconjunto enviado al
            // backend, y usar el indice del pool completo desalineaba
            // leyenda y curvas en cuanto se desmarcaba una estrategia.
            const ci = selectedIds.indexOf(s.id);
            const on = ci >= 0;
            return (
              <label key={s.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer", padding: "2px 0" }}>
                <input
                  type="checkbox"
                  checked={!!checked[s.id]}
                  onChange={(e) => setChecked((c) => ({ ...c, [s.id]: e.target.checked }))}
                  style={{ accentColor: "var(--color-ec-copper)" }}
                />
                <span
                  style={{
                    width: 10,
                    height: 0,
                    borderTop: `2px solid ${on ? SERIES_PALETTE[ci % SERIES_PALETTE.length] : color.textMuted}`,
                    opacity: on ? 1 : 0.4,
                    flexShrink: 0,
                  }}
                />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                {s.normalization && !s.normalization.normalized && (
                  <span style={{ fontSize: 9, color: color.warning, flexShrink: 0 }}>ámbar</span>
                )}
              </label>
            );
          })}
        </div>

        <Field label="Capital inicial ($)">
          <NumberInput value={cfg.init_cash} onChange={(v) => set("init_cash", v)} min={100} step={1000} />
        </Field>

        {sub === "general" && (
        <Field label="Riesgo por trade" hint={cfg.risk_type === "PERCENT" ? "cada trade arriesga este % del capital vivo (compound)" : "cada trade arriesga esta cantidad fija en $"}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Segmented
              value={cfg.risk_type}
              onChange={(v) => {
                // Al cambiar de modo, el numero cambia de UNIDAD ($ vs %): se
                // resetea a un valor sensato del modo nuevo. Dejar el 100 de
                // "$ fijo" al pasar a "% compound" seria arriesgar el 100% del
                // capital por trade — paso en la primera prueba real.
                setCfg((c) => ({ ...c, risk_type: v, risk_r: v === "PERCENT" ? 3 : 100 }));
              }}
              options={[
                { value: "FIXED", label: "$ fijo" },
                { value: "PERCENT", label: "% compound" },
              ]}
            />
            <NumberInput value={cfg.risk_r} onChange={(v) => set("risk_r", v)} min={0} step={cfg.risk_type === "PERCENT" ? 0.5 : 25} />
            {cfg.risk_type === "PERCENT" && cfg.risk_r > 10 && (
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.warning, lineHeight: 1.45 }}>
                {cfg.risk_r}% del capital POR TRADE es una barbaridad — con varios trades al día la
                cuenta puede quebrar en una sesión. Lo habitual es 1–5%.
              </span>
            )}
          </div>
        </Field>
        )}

        <Field label="Comisiones">
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <NumberInput value={cfg.fees} onChange={(v) => set("fees", v)} min={0} step={0.5} />
            </div>
            <div style={{ width: 110 }}>
              <Select
                value={cfg.fee_type}
                onChange={(v) => set("fee_type", v)}
                options={[
                  // "$ por lado" describia el modelo viejo, que ignoraba el
                  // numero de acciones. Desde 2026-08-22 el importe es $ POR
                  // ACCION — y, como el %, se cobra en la compra Y en la venta.
                  { value: "FLAT", label: "$ por acción" },
                  { value: "PERCENT", label: "% del valor" },
                ]}
              />
            </div>
          </div>
        </Field>

        <Field label="Slippage (% real)" hint="aquí el % es de verdad: 0,1 significa 0,1% del precio en cada lado">
          <NumberInput value={cfg.slippage_pct} onChange={(v) => set("slippage_pct", v)} min={0} step={0.01} />
        </Field>

        <Field label="Locates ($ por 100 acc.)" hint="una vez por ticker y día, sobre el mayor corto abierto — por estrategia">
          <NumberInput value={cfg.locates_cost} onChange={(v) => set("locates_cost", v)} min={0} step={0.5} />
        </Field>

        <Field label="Gastos fijos ($/mes)">
          <NumberInput value={cfg.monthly_expenses} onChange={(v) => set("monthly_expenses", v)} min={0} step={25} />
        </Field>

        <Field label="Periodo" hint="vacío = todo el histórico disponible de cada estrategia">
          <div style={{ display: "flex", gap: 6 }}>
            <TextInput value={cfg.start_date} onChange={(v) => set("start_date", v)} type="date" />
            <TextInput value={cfg.end_date} onChange={(v) => set("end_date", v)} type="date" />
          </div>
        </Field>

        {sub === "general" && (
          <>
            <RunButton onClick={run} loading={running} disabled={!selectedIds.length} label="Calcular imagen general" loadingLabel="Calculando…" />
            <p style={{ margin: 0, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
              Esta imagen es la base lineal con pesos iguales; el riesgo de arriba se usa aquí. El
              escalado dinámico y el reparto de pesos viven en las otras dos vistas.
            </p>
          </>
        )}
        {sub !== "general" && (
          <p style={{ margin: 0, fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
            Capital, costes y periodo son comunes a las tres vistas. El riesgo por trade no se pide
            aquí: lo decide el modelo de escalado.
          </p>
        )}
      </div>

      {sub === "modelos" && <div style={card}>{scalingEngine.config}</div>}
      {sub === "comparar" && <div style={card}>{compareEngine.config}</div>}
      </div>

      {/* ── Resultados ── */}
      <div
        style={{
          background: color.bgSurface,
          border: `0.5px solid ${color.border}`,
          borderRadius: radius.md,
          padding: "18px 20px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 22,
          minWidth: 0,
        }}
      >
        {sub === "modelos" ? (
          scalingEngine.results
        ) : sub === "comparar" ? (
          compareEngine.results
        ) : (
          <>
        {error && <ErrorBox>{error}</ErrorBox>}
        {stale && out && <StaleNotice onRun={run} label={running ? "Calculando…" : "Re-calcular"} />}

        {!out ? (
          <Placeholder>
            Marca las estrategias, ajusta la ejecución y pulsa <strong>Calcular imagen general</strong>.
            Todo se reconstruye desde los trades guardados: tarda segundos.
          </Placeholder>
        ) : (
          <>
            {approx.length > 0 && (
              <ReadingNote>
                {approx.map((s) => s.name).join(", ")}{" "}
                {approx.length === 1 ? "no estaba normalizada y se ha normalizado" : "no estaban normalizadas y se han normalizado"}{" "}
                al calcular ({approx.map((s) => s.normalization.issues.join(", ")).join(" · ")}).
                {approx.some((s) => !s.normalization.exact) &&
                  " Al llevar slippage, parte de la reconstrucción es aproximada."}
              </ReadingNote>
            )}

            {out.ruined && (
              <Verdict level="fail" title="La cuenta quiebra con esta configuración">
                El capital llegó a cero antes del final del periodo: a partir de ahí no se abre ningún
                trade más. Baja el riesgo por trade o los costes.
              </Verdict>
            )}

            <div>
              <SectionHead
                title="Imagen general del portfolio"
                hint="PnL acumulado desde cero: una línea fina por estrategia y la suma en cobre. Un día sin operar arrastra el valor anterior — el peso no se redistribuye."
                right={
                  <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                    <Segmented
                      value={yMode}
                      onChange={setYMode}
                      options={[
                        { value: "usd", label: "$" },
                        { value: "pct", label: "%" },
                        { value: "r", label: "R" },
                      ]}
                    />
                    <Segmented
                      value={xMode}
                      onChange={setXMode}
                      options={[
                        { value: "fecha", label: "Fecha" },
                        { value: "trades", label: "Trades" },
                      ]}
                    />
                  </div>
                }
              />
              <PortfolioCurves out={out} yMode={yMode} xMode={xMode} />
              {yMode === "r" && (
                <p style={{ margin: "8px 4px 0", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                  El eje R muestra la señal pura de cada estrategia (sin costes): es la vara de medir
                  común. Las métricas de abajo sí incluyen todos los costes configurados.
                </p>
              )}
            </div>

            {/* Drawdown del combinado — estatico, siempre visible bajo las curvas. */}
            <div>
              <SectionHead title="Drawdown del portfolio" />
              <DrawdownRibbon equity={eqPoints} />
            </div>

            {/* Calendario de PnL — discreto, plegado por defecto. */}
            <div>
              <button
                type="button"
                onClick={() => setShowCalendar((v) => !v)}
                aria-expanded={showCalendar}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 7,
                  padding: "7px 12px",
                  fontSize: 12,
                  fontFamily: font.sans,
                  background: "transparent",
                  border: `0.5px solid ${color.border}`,
                  borderRadius: radius.sm,
                  color: showCalendar ? color.textHigh : color.textSecondary,
                  cursor: "pointer",
                  transition: "color 120ms, border-color 120ms",
                }}
              >
                <ChevronRight
                  style={{
                    width: 13,
                    height: 13,
                    strokeWidth: 1.5,
                    transform: showCalendar ? "rotate(90deg)" : "none",
                    transition: "transform 150ms",
                  }}
                />
                Calendario de PnL diario
                <span style={{ fontSize: 10, color: color.textMuted }}>
                  {showCalendar ? "ocultar" : "ver el PnL de cada día y semana, mes a mes"}
                </span>
              </button>
              {showCalendar && (
                <div style={{ marginTop: 12 }}>
                  <PnlCalendar dates={out.calendar} pnl={out.daily_pnl} counts={dayCounts} />
                </div>
              )}
            </div>

            {m && (
              <div>
                <SectionHead title="Métricas del portfolio combinado" hint="Con todos los costes configurados, gastos fijos incluidos." />
                <StatSheet
                  groups={[
                    {
                      title: "Rendimiento",
                      rows: [
                        { label: "Retorno neto", value: fmt.pct(m.total_return_pct), sub: fmt.money(m.final_equity), tone: m.total_return_pct >= 0 ? color.profit : color.loss },
                        { label: "CAGR", value: fmt.pct(m.cagr_pct) },
                        { label: "Win rate", value: fmt.pct(m.win_rate, 1), sub: `${fmt.int(m.n_trades)} trades` },
                        { label: "Profit factor", value: fmt.num(m.profit_factor) },
                        {
                          label: "Expectancy",
                          value: `${fmt.num(m.expectancy_r)} R`,
                          sub: `payoff ${fmt.num(m.payoff)}`,
                          help: (
                            <>
                              Lo que deja <strong>de media cada trade</strong>, en unidades de R. Es
                              exactamente la fórmula clásica{" "}
                              <em>(% aciertos × ganancia media) − (% fallos × pérdida media)</em>:
                              ambas dan el mismo número, porque la media del PnL de todos los trades
                              es esa suma ponderada.
                              <br />
                              <br />
                              Aquí va en <strong>R</strong> (múltiplos del riesgo), mientras que
                              «Media gan./perd.» va en <strong>$</strong>: si comparas a mano, hazlo
                              en la misma unidad. Y ojo al detalle: los trades que salen a cero
                              exacto no son ni ganadores ni perdedores, así que{" "}
                              <em>% fallos</em> no es exactamente 100 − <em>% aciertos</em>.
                            </>
                          ),
                        },
                        { label: "Media gan. / perd.", value: `${fmt.money(m.avg_win, 0)} / ${fmt.money(m.avg_loss, 0)}` },
                      ],
                    },
                    {
                      title: "Riesgo",
                      rows: [
                        { label: "Max drawdown", value: fmt.pct(m.max_drawdown_pct), tone: color.loss },
                        {
                          label: "DD más largo",
                          value: `${m.longest_dd_days} días`,
                          sub: `${fmt.pct(m.longest_dd_pct_of_span, 1)} del hist.`,
                          help: "Cuánto tiempo SEGUIDO se estuvo sin ver un máximo nuevo, en días civiles.",
                        },
                        { label: "Tiempo en DD", value: fmt.pct(m.time_in_dd_pct, 1), sub: "de las sesiones" },
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
                        {
                          label: "Total",
                          value: fmt.money(out.costs.fees + out.costs.slippage + out.costs.locates + out.costs.expenses, 0),
                          tone: color.loss,
                        },
                      ],
                    },
                  ]}
                />
              </div>
            )}

            <div>
              <SectionHead title="Aportación por estrategia" hint="PnL neto con los costes atribuidos a sus trades; la R acumulada va sin costes (señal pura)." />
              <DataTable
                columns={["Estrategia", "Periodo", "Trades", "Win", "PnL neto", "R acum.", "Comisiones", "Slippage", "Locates"]}
                rows={out.per_strategy.map((p, i) => [
                  <span key="n" style={{ color: SERIES_PALETTE[i % SERIES_PALETTE.length] }}>{p.name}</span>,
                  `${p.alive_from || "?"} → ${p.alive_to || "?"}`,
                  fmt.int(p.totals.n_trades),
                  fmt.pct(p.totals.win_rate, 1),
                  <span key="p" style={{ color: p.totals.pnl_net >= 0 ? color.profit : color.loss }}>{fmt.money(p.totals.pnl_net, 0)}</span>,
                  fmt.num(p.totals.cum_r, 1),
                  fmt.money(p.totals.fees, 0),
                  fmt.money(p.totals.slippage, 0),
                  fmt.money(p.totals.locates, 0),
                ])}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 20, alignItems: "start" }}>
              <div>
                <SectionHead
                  title="Correlación entre estrategias"
                  hint="Sobre la R diaria normalizada, solo en el tramo donde ambas coexisten."
                />
                {out.correlation ? (
                  <>
                    <CorrelationMatrix corr={out.correlation} names={out.per_strategy.map((p) => p.name)} />
                    <div style={{ marginTop: 10 }}>
                      <PlainStats
                        min={150}
                        items={[
                          {
                            label: "Correlación media",
                            value: out.correlation.avg_pairwise == null ? "—" : fmt.num(out.correlation.avg_pairwise),
                            help: "Media de todas las parejas. Por debajo de 0,3 la cartera diversifica de verdad; por encima de 0,7 estás comprando la misma apuesta varias veces.",
                            tone:
                              out.correlation.avg_pairwise == null
                                ? undefined
                                : out.correlation.avg_pairwise > 0.7
                                  ? color.loss
                                  : out.correlation.avg_pairwise > 0.3
                                    ? color.warning
                                    : color.profit,
                          },
                          {
                            label: "Pareja más correlacionada",
                            value:
                              out.correlation.max_pair == null
                                ? "—"
                                : fmt.num(out.correlation.max_pair.corr),
                            sub:
                              out.correlation.max_pair == null
                                ? undefined
                                : `${out.per_strategy[out.correlation.max_pair.i]?.name} · ${out.per_strategy[out.correlation.max_pair.j]?.name}`,
                          },
                        ]}
                      />
                    </div>
                  </>
                ) : (
                  <Placeholder>Hacen falta al menos dos estrategias para medir correlación.</Placeholder>
                )}
              </div>

              <div>
                <SectionHead
                  title="VaR / CVaR del día"
                  hint="Distribución del retorno diario del portfolio. VaR 95: el día malo típico (1 de cada 20 lo supera). CVaR: lo que pierdes de media cuando lo supera."
                />
                {out.var ? (
                  <>
                    <InlineStats
                      items={[
                        { label: "VaR 95", value: fmt.pct(out.var.var95), tone: color.loss },
                        { label: "CVaR 95", value: fmt.pct(out.var.cvar95), tone: color.loss },
                        { label: "VaR 99", value: fmt.pct(out.var.var99), tone: color.loss },
                        { label: "CVaR 99", value: fmt.pct(out.var.cvar99), tone: color.loss },
                      ]}
                    />
                    <div style={{ marginTop: 10 }}>
                      <DistributionChart
                        hist={{ counts: out.var.hist_counts, edges: out.var.hist_edges }}
                        markers={[
                          { value: out.var.var95, label: `VaR95 ${out.var.var95.toFixed(2)}%`, color: "var(--color-ec-warning)" },
                          { value: out.var.var99, label: `VaR99 ${out.var.var99.toFixed(2)}%`, color: "var(--color-ec-loss)" },
                        ]}
                        fmtValue={(v) => `${v.toFixed(1)}%`}
                        caption="Retorno diario del portfolio (%). Las marcas señalan el percentil 5 y el 1."
                      />
                    </div>
                  </>
                ) : (
                  <Placeholder>Hacen falta al menos 20 sesiones para estimar VaR con algo de sentido.</Placeholder>
                )}
              </div>
            </div>

            <div>
              <SectionHead
                title="Monte Carlo del portfolio"
                hint="Remuestrea los DÍAS del portfolio combinado (bootstrap con reemplazo o permutación del orden). Por día y no por trade: los trades de una misma sesión van correlacionados."
                right={
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
                    <div style={{ width: 90 }}>
                      <NumberInput value={mcSims} onChange={setMcSims} min={500} max={20000} step={500} />
                    </div>
                    <Segmented
                      value={mcMethod}
                      onChange={setMcMethod}
                      options={[
                        { value: "bootstrap", label: "Bootstrap" },
                        { value: "permutacion", label: "Permutación" },
                      ]}
                    />
                    <div style={{ width: 130 }}>
                      <RunButton onClick={runMc} loading={mcRunning} disabled={out.ruined} label="Simular" loadingLabel="Simulando…" />
                    </div>
                  </div>
                }
              />
              {mcError && <ErrorBox>{mcError}</ErrorBox>}
              {!mcOut ? (
                <Placeholder>
                  Pulsa <strong>Simular</strong> para ver cuánto del resultado depende del orden en que
                  llegaron los días y qué drawdown deberías estar dispuesto a tragar.
                </Placeholder>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <PlainStats
                    min={150}
                    items={[
                      { label: "DD mediano simulado", value: fmt.pct(mcOut.drawdown?.p50), tone: color.loss },
                      {
                        label: "DD a tragar (1 de 20)",
                        value: fmt.pct(mcOut.dd_tolerance?.p95),
                        tone: color.loss,
                        help: "Para que solo 1 de cada 20 escenarios lo supere, tienes que estar dispuesto a aguantar este drawdown.",
                      },
                      { label: "DD a tragar (1 de 100)", value: fmt.pct(mcOut.dd_tolerance?.p99), tone: color.loss },
                      { label: "Prob. de acabar perdiendo", value: fmt.pct(mcOut.prob_losing_pct, 1) },
                      { label: "Prob. de ruina (−50%)", value: fmt.pct(mcOut.prob_ruin_pct, 1) },
                      { label: "Balance mediano", value: fmt.money(mcOut.final_balance?.p50, 0) },
                    ]}
                  />
                  <SpaghettiChart
                    spaghetti={mcOut.spaghetti}
                    bands={mcOut.bands}
                    baseCurve={mcOut.base_curve}
                    initCash={mcOut.init_cash}
                    xLabel="días →"
                  />
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14 }}>
                    <DistributionChart
                      hist={mcOut.hist_final}
                      markers={[{ value: mcOut.base_final, label: `real ${fmt.money(mcOut.base_final, 0)}`, color: "var(--color-ec-copper)" }]}
                      caption="Balance final de cada escenario simulado."
                    />
                    <DistributionChart
                      hist={mcOut.hist_drawdown}
                      markers={[{ value: mcOut.base_max_drawdown, label: `real ${fmt.pct(mcOut.base_max_drawdown)}`, color: "var(--color-ec-copper)" }]}
                      fmtValue={(v) => `${v.toFixed(0)}%`}
                      barColor="var(--color-ec-loss)"
                      caption="Max drawdown de cada escenario simulado (%)."
                    />
                  </div>
                </div>
              )}
            </div>
          </>
        )}
          </>
        )}
      </div>
      </div>
    </div>
  );
}
