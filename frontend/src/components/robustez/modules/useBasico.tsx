"use client";

import { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import {
  DataTable,
  ErrorBox,
  Field,
  MetricTile,
  NumberInput,
  Placeholder,
  ReadingNote,
  RunButton,
  SectionHead,
  TileGrid,
  fmt,
} from "../shared";
import { Help, PlainStats, StaleNotice, SubTabs } from "../help";
import { DrawdownRibbon, LosingStreakBars } from "../charts/BasicCharts";
import { StressCurves } from "../charts/StressCurves";
import { analyzeBasic, epochToDate } from "@/lib/robustez/analytics";
import { runRobustezStress, type StressOut } from "@/lib/api_robustez";
import type { ModuleCtx, ModuleParts } from "./types";

interface StressCfg {
  skipTopPct: number;
  extraSlippage: number;
  blackSwanCount: number;
  blackSwanPct: number;
  dailyMaxTrades: number;
  maxConcurrentTrades: number;
  randomMonthlyDays: number;
  monthlyExpenses: number;
}

const DEFAULT_STRESS: StressCfg = {
  skipTopPct: 10,
  extraSlippage: 0,
  blackSwanCount: 0,
  blackSwanPct: 500,
  dailyMaxTrades: 0,
  maxConcurrentTrades: 0,
  randomMonthlyDays: 0,
  monthlyExpenses: 0,
};

type Tab = "analisis" | "estres";

export function useBasico({ run, loading }: ModuleCtx): ModuleParts {
  const [tab, setTab] = useState<Tab>("analisis");
  const [cfg, setCfg] = useState<StressCfg>(DEFAULT_STRESS);
  const [ranCfg, setRanCfg] = useState<StressCfg | null>(null);
  const [stress, setStress] = useState<StressOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  const set = <K extends keyof StressCfg>(k: K, v: StressCfg[K]) => setCfg((c) => ({ ...c, [k]: v }));

  const analysis = useMemo(
    () => (run ? analyzeBasic(run.trades, run.global_equity) : null),
    [run],
  );

  const initCash = Number(run?.backtest_params?.init_cash ?? 10000);
  // El resultado en pantalla es viejo si se han tocado los mandos desde que se
  // ejecuto: sin este aviso parece que cambiar un campo no hace nada.
  const stale = !!stress && !!ranCfg && JSON.stringify(ranCfg) !== JSON.stringify(cfg);

  const runStress = async () => {
    if (!run) return;
    setBusy(true);
    setErr(null);
    setTab("estres");
    const t0 = performance.now();
    try {
      const res = await runRobustezStress({
        trades: run.trades,
        init_cash: initCash,
        // Compuesto cuando el backtest arriesgaba un % del capital vivo, que es
        // como se dimensiono de verdad. Ver robustness_stress.py.
        mode: run.compounding.is_percent_risk ? "compound" : "additive",
        risk_pct: run.compounding.risk_pct || 3,
        seed: 7,
        params: {
          random_monthly_days: cfg.randomMonthlyDays,
          daily_max_trades: cfg.dailyMaxTrades,
          max_concurrent_trades: cfg.maxConcurrentTrades,
          skip_top_pct: cfg.skipTopPct,
          extra_slippage: cfg.extraSlippage,
          black_swan_count: cfg.blackSwanCount,
          black_swan_pct: cfg.blackSwanPct,
          monthly_expenses: cfg.monthlyExpenses,
        },
      });
      setStress(res);
      setRanCfg(cfg);
      setElapsed(performance.now() - t0);
    } catch (e: any) {
      setErr(e?.message || "Fallo el test de estres");
      setStress(null);
    } finally {
      setBusy(false);
    }
  };

  /* ─────────────────── CONFIG (panel izquierdo) ─────────────────── */
  const config = (
    <>
      <div style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.55 }}>
        El bloque de drawdown y rachas se calcula solo, sobre los trades reales. Lo de abajo aplica
        castigos al histórico para ver qué aguanta.
      </div>

      <div style={{ height: 1, background: color.border, margin: "2px 0" }} />

      <Field
        label="Quitar el mejor % de trades"
        hint="Simula no haber pillado los mejores dias."
      >
        <NumberInput value={cfg.skipTopPct} onChange={(v) => set("skipTopPct", v)} min={0} max={90} step={1} />
      </Field>

      <Field label="Slippage extra (%)" hint="Se resta al retorno de cada trade.">
        <NumberInput value={cfg.extraSlippage} onChange={(v) => set("extraSlippage", v)} min={0} step={0.1} />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Black swans">
          <NumberInput value={cfg.blackSwanCount} onChange={(v) => set("blackSwanCount", v)} min={0} step={1} />
        </Field>
        <Field label="Tamaño (%)">
          <NumberInput value={cfg.blackSwanPct} onChange={(v) => set("blackSwanPct", v)} min={0} step={50} />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Max trades/dia" hint="0 = sin limite">
          <NumberInput value={cfg.dailyMaxTrades} onChange={(v) => set("dailyMaxTrades", v)} min={0} step={1} />
        </Field>
        <Field label="Max simultaneos" hint="0 = sin limite">
          <NumberInput value={cfg.maxConcurrentTrades} onChange={(v) => set("maxConcurrentTrades", v)} min={0} step={1} />
        </Field>
      </div>

      <Field label="Dias perdidos al mes" hint="Vacaciones, cortes, despistes. 0 = ninguno.">
        <NumberInput value={cfg.randomMonthlyDays} onChange={(v) => set("randomMonthlyDays", v)} min={0} step={1} />
      </Field>

      <Field label="Gastos fijos mensuales ($)" hint="Plataforma, datos, etc.">
        <NumberInput value={cfg.monthlyExpenses} onChange={(v) => set("monthlyExpenses", v)} min={0} step={50} />
      </Field>

      <RunButton
        onClick={runStress}
        loading={busy}
        disabled={!run || loading}
        label="Ejecutar test de estres"
        loadingLabel="Aplicando castigos…"
      />
      {elapsed != null && !busy && (
        <div style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, textAlign: "center" }}>
          {(elapsed / 1000).toFixed(2)} s
        </div>
      )}
    </>
  );

  /* ─────────────────── RESULTADOS (panel derecho) ─────────────────── */
  let results: React.ReactNode;

  if (loading) {
    results = <Placeholder>Cargando los trades de la estrategia…</Placeholder>;
  } else if (!run || !analysis) {
    results = <Placeholder>Elige arriba una estrategia que tenga un backtest guardado.</Placeholder>;
  } else {
    const a = analysis;
    const s = a.streaks;
    const sBase = stress?.base;
    const sOut = stress?.stressed;

    const panelAnalisis = (
      <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        {/* ── Drawdown ── */}
        <section>
          <SectionHead
            title="Drawdown: cuanto y durante cuanto"
            hint="La profundidad asusta, pero lo que hace abandonar una estrategia es la duracion. Mira las sesiones tanto como el porcentaje."
          />
          <TileGrid>
            <MetricTile
              label="Max drawdown"
              value={fmt.pct(a.maxDrawdownPct, 2)}
              sub={a.worstEpisode ? fmt.money(a.worstEpisode.depthUsd) : undefined}
              tone={color.loss}
              hint="La mayor caida desde un maximo hasta el fondo."
            />
            <MetricTile
              label="DD mas largo"
              value={a.longestEpisode ? `${a.longestEpisode.sessions} ses.` : "—"}
              sub={a.longestEpisode ? `${a.longestEpisode.calendarDays} dias naturales` : undefined}
              hint="El tramo mas largo sin superar el maximo anterior."
            />
            <MetricTile
              label="Ese DD, en % del total"
              value={fmt.pct(a.longestEpisodePctOfTime, 1)}
              sub={
                a.longestEpisode
                  ? `${a.longestEpisode.sessions} de ${fmt.int(run.global_equity.length)} sesiones`
                  : undefined
              }
              tone={a.longestEpisodePctOfTime > 40 ? color.loss : color.warning}
              hint="Cuanto del histórico se lo comio ESE unico hundimiento."
            />
            <MetricTile
              label="Tiempo total en DD"
              value={fmt.pct(a.pctTimeInDrawdown, 1)}
              sub={`${fmt.int(a.episodes.length)} episodios · ${
                a.openEpisode ? "1 sin recuperar" : "todos recuperados"
              }`}
              hint="Sumando todos los hundimientos, no solo el mayor."
            />
            <MetricTile
              label="Ulcer index"
              value={fmt.num(a.ulcerIndex, 2)}
              hint="Castiga los hundimientos largos, no solo el peor punto."
            />
          </TileGrid>

          <div style={{ marginTop: 8, display: "flex", gap: 18, flexWrap: "wrap" }}>
            <HelpLine label="¿Que es el drawdown?">
              Es la distancia entre el capital que llegaste a tener y el que tienes ahora. Si subiste
              a 10.000 $ y bajaste a 7.300 $, tu drawdown es del −27%: has devuelto ese 27% de lo que
              ya habias ganado. Se mide desde el <strong>maximo previo</strong>, no desde el capital
              inicial.
            </HelpLine>
            <HelpLine label="¿Por que dos cifras de tiempo?">
              <strong>Tiempo total en DD</strong> suma todas las temporadas bajo el maximo, aunque
              sean cortas y repartidas. <strong>Ese DD en % del total</strong> mira solo el
              hundimiento mas largo: responde a &ldquo;¿cuanto tiempo seguido puedo estar sin ver un
              maximo nuevo?&rdquo;, que es lo que de verdad agota a un operador.
            </HelpLine>
            <HelpLine label="¿Que es el Ulcer index?">
              La raiz del drawdown cuadratico medio. El max drawdown solo mira el peor instante; el
              Ulcer mira todo el recorrido, asi que penaliza a una estrategia que pasa media vida un
              10% por debajo mas que a otra que se hunde un 25% un solo dia y se recupera. Cuanto mas
              bajo, mas comodo se lleva.
            </HelpLine>
          </div>

          <div style={{ marginTop: 14 }}>
            <DrawdownRibbon equity={run.global_equity} />
          </div>
        </section>

        {/* ── Peores episodios ── */}
        {a.episodes.length > 0 && (
          <section>
            <SectionHead
              title="Los cinco peores hundimientos"
              hint="Ordenados por profundidad. 'Abierto' significa que el histórico termino sin haber recuperado el maximo previo."
            />
            <DataTable
              columns={["Desde", "Fondo", "Profundidad", "$", "Sesiones", "Dias nat.", "Estado"]}
              rows={[...a.episodes]
                .sort((x, y) => x.depthPct - y.depthPct)
                .slice(0, 5)
                .map((e) => [
                  epochToDate(e.startTime),
                  epochToDate(e.troughTime),
                  <span key="d" style={{ color: color.loss }}>{fmt.pct(e.depthPct, 2)}</span>,
                  fmt.money(e.depthUsd),
                  fmt.int(e.sessions),
                  fmt.int(e.calendarDays),
                  e.recoveredIdx === null ? (
                    <span key="s" style={{ color: color.warning }}>abierto</span>
                  ) : (
                    <span key="s" style={{ color: color.textMuted }}>recuperado</span>
                  ),
                ])}
            />
          </section>
        )}

        {/* ── Rachas ── */}
        <section>
          <SectionHead
            title="Rachas: la perdida continua que hay que aguantar"
            hint="La racha perdedora maxima del pasado es el minimo que debes estar dispuesto a soportar — casi siempre hay una peor por venir."
          />
          <TileGrid>
            <MetricTile
              label="Racha perdedora max"
              value={`${s.maxLosing} trades`}
              sub={fmt.money(s.maxLosingUsd)}
              tone={color.loss}
              hint="Operaciones perdedoras seguidas, sin ninguna ganadora en medio."
            />
            <MetricTile label="Racha ganadora max" value={`${s.maxWinning} trades`} sub={fmt.money(s.maxWinningUsd)} tone={color.profit} />
            <MetricTile label="Peor dia" value={fmt.money(a.worstDayUsd)} sub={a.worstDayDate ?? undefined} tone={color.loss} />
            <MetricTile label="Peor trade" value={fmt.money(a.worstTradeUsd)} sub={a.worstTradeLabel ?? undefined} tone={color.loss} />
            <MetricTile label="PnL medio/dia" value={fmt.money(a.avgDailyPnl, 2)} sub={`${fmt.int(a.tradingDays)} sesiones`} />
          </TileGrid>

          <div style={{ marginTop: 8 }}>
            <HelpLine label="¿Como leo el histograma?">
              Cada barra cuenta cuantas veces se encadenaron N perdidas seguidas. Lo importante no es
              la barra mas alta (siempre seran las rachas cortas), sino <strong>hasta donde llega la
              cola de la derecha</strong>: esa es la peor racha que ya te ha ocurrido, y el minimo que
              tienes que poder aguantar sin cerrar el grifo. Estadisticamente, en el futuro habra una
              peor.
            </HelpLine>
          </div>

          <div style={{ marginTop: 14 }}>
            <LosingStreakBars histogram={s.losingHistogram} />
          </div>
        </section>
      </div>
    );

    const panelEstres = (
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        <SectionHead
          title="Test de estres"
          hint="Castigos aplicados sobre este histórico, recomponiendo el capital igual que hizo el backtest. Configura a la izquierda y ejecuta."
        />
        {err && <ErrorBox>{err}</ErrorBox>}
        {stale && <StaleNotice onRun={runStress} />}

        {!stress && !err && (
          <ReadingNote>
            Sin ejecutar. El castigo mas revelador es <strong>quitar el mejor % de trades</strong>: si
            la estrategia se hunde al retirarle un 10% de sus mejores operaciones, su resultado depende
            de un puñado de dias irrepetibles.
          </ReadingNote>
        )}

        {stress && sBase && sOut && (
          <>
            <TileGrid>
              <MetricTile
                label="Retorno estresado"
                value={fmt.pct(sOut.total_return_pct, 1)}
                sub={`base ${fmt.pct(sBase.total_return_pct, 1)}`}
                tone={sOut.total_return_pct >= 0 ? color.profit : color.loss}
                hint="Lo que habria rendido con los castigos aplicados."
              />
              <MetricTile
                label="Capital final"
                value={fmt.money(sOut.final_balance)}
                sub={`base ${fmt.money(sBase.final_balance)}`}
                tone={sOut.final_balance >= stress.init_cash ? color.profit : color.loss}
              />
              <MetricTile
                label="Max DD estresado"
                value={fmt.pct(sOut.max_drawdown_pct, 1)}
                sub={`base ${fmt.pct(sBase.max_drawdown_pct, 1)}`}
                tone={color.loss}
              />
              <MetricTile label="Profit factor" value={fmt.num(sOut.profit_factor, 2)} sub={`base ${fmt.num(sBase.profit_factor, 2)}`} />
              <MetricTile label="Win rate" value={fmt.pct(sOut.win_rate_pct, 1)} sub={`base ${fmt.pct(sBase.win_rate_pct, 1)}`} />
            </TileGrid>

            <StressCurves base={stress.base_curve} stressed={stress.stressed_curve} initCash={stress.init_cash} />

            <PlainStats
              items={[
                { label: "Trades retirados", value: fmt.int(stress.trades_removed), sub: `de ${fmt.int(stress.trades_removed + stress.trades_kept)}` },
                {
                  label: "Sesiones operadas",
                  value: fmt.int(sOut.active_days),
                  sub: `de ${fmt.int(sBase.active_days)} del histórico`,
                  help: (
                    <>
                      Los castigos que vacian dias enteros —dias perdidos al mes, limite de trades por
                      dia— no acortan el histórico: el eje sigue cubriendo todo el periodo y esas
                      sesiones simplemente pasan sin operar, con el capital plano.
                    </>
                  ),
                },
                {
                  label: "Modelo",
                  value: stress.mode === "compound" ? "compuesto" : "aditivo",
                  sub: stress.mode === "compound" ? `${stress.risk_pct}% de riesgo por trade` : "tamaño fijo",
                  help: (
                    <>
                      Tu backtest arriesga un <strong>{stress.risk_pct}% del capital vivo</strong> en
                      cada operacion, asi que los dolares que gana un trade dependen del balance que
                      hubiera ese dia. Por eso el castigo se aplica en R-multiplos y se recompone el
                      capital, en vez de sumar dolares sueltos: sumarlos daria cifras imposibles, como
                      perder mas del 100%.
                    </>
                  ),
                },
              ]}
            />

            <ReadingNote>
              {sOut.total_return_pct <= 0 ? (
                <>
                  Con estos castigos la estrategia pasa a <strong>perder dinero</strong>: de{" "}
                  {fmt.pct(sBase.total_return_pct, 1)} a {fmt.pct(sOut.total_return_pct, 1)}. Su margen
                  es estrecho — revisa si el resultado base se apoya en pocas operaciones excepcionales.
                </>
              ) : (
                <>
                  Sigue en positivo tras el castigo, con {fmt.pct(sOut.total_return_pct, 1)} frente a{" "}
                  {fmt.pct(sBase.total_return_pct, 1)} del histórico intacto.
                </>
              )}
            </ReadingNote>
          </>
        )}
      </div>
    );

    results = (
      <>
        <SubTabs
          value={tab}
          onChange={setTab}
          options={[
            { value: "analisis", label: "Analisis" },
            { value: "estres", label: "Test de estres" },
          ]}
        />
        {tab === "analisis" ? panelAnalisis : panelEstres}
      </>
    );
  }

  return { config, results };
}

/** Enlace de ayuda en linea, para explicaciones largas bajo un bloque. */
function HelpLine({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 11,
        fontFamily: font.sans,
        color: color.textMuted,
      }}
    >
      <Help title={label} width={360}>
        {children}
      </Help>
      {label}
    </span>
  );
}
