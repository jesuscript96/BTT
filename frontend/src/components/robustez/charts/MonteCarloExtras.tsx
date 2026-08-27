"use client";

/**
 * Los dos bloques finales de un Monte Carlo Bootstrap:
 *
 *   1. `LossesSection`  — perdidas paso a paso, simulado contra real, con
 *      sliders para preguntar "¿que probabilidad hay de perder X?".
 *   2. `FundingSection` — probabilidad de superar una prueba de fondeo con unas
 *      reglas concretas (limite diario, drawdown, objetivo, minimos, plazo).
 *
 * Sirven a DOS sitios con la misma corrida por debajo: el Monte Carlo de
 * Robustez (una estrategia) y el Monte Carlo del modelo en Portfolio (la
 * cartera combinada). Por eso los props son datos sueltos y no un `RobustezRun`:
 * el portfolio no tiene trades individuales ni MAE, y pasa lo que tiene.
 *
 * ESTILO (peticion expresa del usuario, 2026-08-24): nada de tarjetas. Cifras
 * sobre el fondo, tablas finas y las explicaciones dentro de un `?` — no
 * ocupando media pantalla. Mismo criterio que `StatSheet`/`InlineStats`.
 *
 * MODELO DE PROBABILIDAD: ECDF empirica. Se cuenta que fraccion de los casos
 * observados queda por debajo del umbral. No se ajusta ninguna normal: los
 * retornos de trading tienen colas gordas y una normal las subestima justo en
 * la zona que aqui interesa.
 */

import { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import {
  DataTable,
  ErrorBox,
  Field,
  NumberInput,
  ReadingNote,
  RunButton,
  SectionHead,
  Segmented,
  fmt,
} from "../shared";
import { Help } from "../help";
import { InlineStats } from "@/components/portfolio/StatSheet";
import { probEnRejilla, probMenorOIgual, type RealLossStats } from "@/lib/robustez/loss_stats";
import { runRobustezFunding, type FundingOut, type FundingOutcome, type MonteCarloOut } from "@/lib/api_robustez";

/* ── piezas locales ──────────────────────────────────────────────────── */

/** Rotulo de sub-bloque: versalitas cobre, con `?` opcional. Sin recuadro. */
function Rotulo({ children, help, helpTitle }: { children: string; help?: React.ReactNode; helpTitle?: string }) {
  return (
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
        marginBottom: 7,
      }}
    >
      {children}
      {help && (
        <Help title={helpTitle || children} width={430}>
          {help}
        </Help>
      )}
    </div>
  );
}

/** Caja numerica + barra deslizante. Compacta, sin marco. */
function SliderRow({
  label,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  suffix?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{label}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 5, width: 118 }}>
          <NumberInput value={value} onChange={onChange} min={min} max={max} step={step} />
          {suffix && <span style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted }}>{suffix}</span>}
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={Math.min(Math.max(value, min), max)}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: "100%", accentColor: "var(--color-ec-copper)", height: 14 }}
      />
    </div>
  );
}

/** Cifra de probabilidad sobre el fondo. Destaca el numero, nada mas. */
function Prob({ label, pct, tone }: { label: string; pct: number; tone?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
      <span
        style={{
          fontSize: 9.5,
          letterSpacing: "0.07em",
          textTransform: "uppercase",
          color: color.textMuted,
          fontFamily: font.sans,
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 19, fontFamily: font.mono, color: tone || color.textHigh, lineHeight: 1.15 }}>
        {pct.toFixed(1)}%
      </span>
    </div>
  );
}

/* ── 1. Perdidas y probabilidades ────────────────────────────────────── */

export interface CapitalInfo {
  initCash: number;
  esPct: boolean;
  riskPct: number;
  /** Etiqueta cruda del JSON del backtest ("PERCENT" / "FIXED"), si la hay. */
  riesgoTipo?: string;
  /** Como se llama la fuente en pantalla: "backtest guardado", "modelo"… */
  origen?: string;
}

export function LossesSection({
  out,
  real,
  capital,
}: {
  out: MonteCarloOut;
  real: RealLossStats;
  capital: CapitalInfo;
}) {
  const L = out.losses;
  // Umbral por defecto: el 2% de la cuenta, el limite diario tipico de un
  // challenge. Asi la caja arranca en una cifra que ya significa algo.
  const [umbralUsd, setUmbralUsd] = useState(() => Math.round(out.init_cash * 0.02));
  const [umbralDd, setUmbralDd] = useState(10);

  // "sesion" es femenino y "trade" masculino.
  const esDia = L?.unit !== "trade";
  const paso = esDia ? "sesion" : "trade";
  const pasoPlural = esDia ? "sesiones" : "trades";
  const unPaso = esDia ? "una sesion" : "un trade";
  const cualquiera = esDia ? "Una sesion cualquiera" : "Un trade cualquiera";

  const probs = useMemo(() => {
    if (!L) return null;
    const objetivo = -Math.abs(umbralUsd);
    return {
      simUno: probEnRejilla(L.grids.step_usd, objetivo),
      simAlguno: probEnRejilla(L.grids.worst_step_usd, objetivo),
      realUno: probMenorOIgual(real.porDia.valores, objetivo),
      // Los drawdowns son NEGATIVOS y la rejilla va de peor a mejor, asi que la
      // posicion del umbral en la rejilla YA es P(DD <= -X). Invertirla daba el
      // complemento: mediana -4,8% y "97,6% llega a -10%" a la vez.
      simDd: probEnRejilla(L.grids.max_dd_pct, -Math.abs(umbralDd)),
    };
  }, [L, umbralUsd, umbralDd, real.porDia.valores]);

  if (!L || !probs) return null;

  const hayTrades = real.porTrade.todo.n > 0;
  const ddRealAlcanzado = Math.abs(out.base_max_drawdown) >= Math.abs(umbralDd);
  const money2 = (v: number) => fmt.money(v, 2);

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <SectionHead
        title="Perdidas: cuanto se pierde, cada cuanto y con que probabilidad"
        hint={`Sobre las mismas ${fmt.int(out.simulations)} simulaciones, mirando ${paso} a ${paso} en vez de solo el resultado final.`}
      />

      {/* ── Capital asumido: datos sueltos, sin cuadros ── */}
      <div>
        <Rotulo>Capital que se esta asumiendo</Rotulo>
        <InlineStats
          items={[
            { label: "Capital inicial", value: fmt.money(out.init_cash), help: `El del ${capital.origen || "backtest guardado"}.` },
            {
              label: "Tipo de riesgo",
              value: capital.esPct ? "% del capital" : "Tamaño fijo",
              help: capital.esPct
                ? `Cada operacion arriesga un % del capital VIVO${capital.riesgoTipo ? ` (${capital.riesgoTipo})` : ""}: gana mas dolares cuanto mayor es la cuenta.`
                : `El tamaño de posicion no depende del balance${capital.riesgoTipo ? ` (${capital.riesgoTipo})` : ""}.`,
            },
            {
              label: "Riesgo / operacion",
              value: capital.esPct ? `${out.risk_pct}%` : "—",
              help: capital.esPct ? `${fmt.money((out.init_cash * out.risk_pct) / 100)} al empezar.` : undefined,
            },
            {
              label: "Composicion",
              value: out.mode === "compound" ? "Compuesta" : "Aditiva",
              help:
                out.mode === "compound"
                  ? "Se remuestrean R-multiplos y se recompone el capital, igual que hizo el backtest."
                  : "Se suman dolares. Correcto solo con tamaño de posicion fijo.",
            },
            { label: "Unidad", value: esDia ? "Sesion" : "Trade", help: "La que se remuestrea en el bootstrap." },
            { label: "Pasos", value: fmt.int(out.n_trades) },
          ]}
        />
      </div>

      {/* ── Extremos y rachas, en tabla ── */}
      <div>
        <Rotulo
          helpTitle="Lo peor que aparece"
          help={
            <>
              La columna <strong>real</strong> es lo que ocurrio de verdad. Las simuladas describen
              el <strong>peor paso de cada corrida</strong> a lo largo de las {fmt.int(out.simulations)}{" "}
              simulaciones: la mediana es la corrida tipica, «1 de cada 20» es la mala.
              <br />
              <br />
              <strong>Ojo con una trampa:</strong> el bootstrap solo baraja {pasoPlural} que{" "}
              <em>ya ocurrieron</em>, asi que por construccion no puede inventarse una peor que la
              que ya viviste. Con tamaño de posicion fijo las cuatro columnas salen practicamente
              iguales — no es un fallo, es que en casi todas las corridas ese peor dia acaba
              apareciendo. Para dimensionar un limite diario,{" "}
              <strong>estas cifras son un suelo, no un techo</strong>.
              <br />
              <br />
              Con riesgo en % del capital si difieren: el mismo movimiento duele mas dolares cuando
              la cuenta ha crecido.
            </>
          }
        >
          Lo peor que aparece
        </Rotulo>
        <DataTable
          columns={["", "Real", "Sim. mediana", "Sim. 1 de cada 20", "Sim. peor"]}
          rows={[
            [
              `Peor ${paso} ($)`,
              <span key="a" style={{ color: color.copper }}>{fmt.money(real.peorDiaUsd)}</span>,
              <span key="b" style={{ color: color.loss }}>{fmt.money(L.worst_step_usd.median)}</span>,
              <span key="c" style={{ color: color.loss }}>{fmt.money(L.worst_step_usd.p5)}</span>,
              <span key="d" style={{ color: color.loss }}>{fmt.money(L.worst_step_usd.worst)}</span>,
            ],
            [
              `Peor ${paso} (% del capital)`,
              <span key="a" style={{ color: color.copper }}>{fmt.pct(real.peorDiaPct, 2)}</span>,
              <span key="b" style={{ color: color.loss }}>{fmt.pct(L.worst_step_pct.median, 2)}</span>,
              <span key="c" style={{ color: color.loss }}>{fmt.pct(L.worst_step_pct.p5, 2)}</span>,
              <span key="d" style={{ color: color.loss }}>{fmt.pct(L.worst_step_pct.worst, 2)}</span>,
            ],
            [
              `Racha perdedora (${pasoPlural})`,
              <span key="a" style={{ color: color.copper }}>{fmt.int(real.porDia.rachaMax)}</span>,
              <span key="b" style={{ color: color.loss }}>{fmt.int(L.streak.median)}</span>,
              <span key="c" style={{ color: color.loss }}>{fmt.int(L.streak.p95)}</span>,
              <span key="d" style={{ color: color.loss }}>{fmt.int(L.streak.worst)}</span>,
            ],
          ]}
        />
        {real.peorDiaFecha && (
          <div style={{ marginTop: 5, fontSize: 10, fontFamily: font.mono, color: color.textMuted }}>
            peor {paso} real: {real.peorDiaFecha}
          </div>
        )}
      </div>

      {/* ── Medias y medianas ── */}
      <div>
        <Rotulo
          helpTitle="Ganancia y perdida media y mediana"
          help={
            <>
              La <strong>media</strong> reparte el total entre todos los dias; un solo dia
              extraordinario la dispara. La <strong>mediana</strong> es el dia de en medio: la
              mitad fue mejor y la mitad peor. Cuando la media es mucho mayor que la mediana, el
              resultado depende de unos pocos dias irrepetibles — eso es fragilidad, no habilidad.
              <br />
              <br />
              <strong>Por que no hay fila simulada:</strong> el bootstrap remuestrea los mismos{" "}
              {pasoPlural} con reemplazo, asi que la distribucion de un paso cualquiera es la real.
              La media y la mediana simuladas coinciden con las reales salvo ruido de muestreo. Lo
              que si aporta el Monte Carlo son los <em>extremos</em> y las <em>probabilidades</em>,
              que estan en los otros bloques.
            </>
          }
        >
          Ganancia y perdida media y mediana
        </Rotulo>
        <DataTable
          columns={["", "Media", "Mediana", "Media si gana", "Mediana si gana", "Media si pierde", "Mediana si pierde", "% aciertos"]}
          rows={[
            [
              "Por sesion",
              money2(real.porDia.todo.mean),
              money2(real.porDia.todo.median),
              <span key="b" style={{ color: color.profit }}>{money2(real.porDia.ganancias.mean)}</span>,
              <span key="c" style={{ color: color.profit }}>{money2(real.porDia.ganancias.median)}</span>,
              <span key="d" style={{ color: color.loss }}>{money2(real.porDia.perdidas.mean)}</span>,
              <span key="e" style={{ color: color.loss }}>{money2(real.porDia.perdidas.median)}</span>,
              fmt.pct(real.porDia.winRatePct, 1),
            ],
            ...(hayTrades
              ? [
                  [
                    "Por trade",
                    money2(real.porTrade.todo.mean),
                    money2(real.porTrade.todo.median),
                    <span key="b" style={{ color: color.profit }}>{money2(real.porTrade.ganancias.mean)}</span>,
                    <span key="c" style={{ color: color.profit }}>{money2(real.porTrade.ganancias.median)}</span>,
                    <span key="d" style={{ color: color.loss }}>{money2(real.porTrade.perdidas.mean)}</span>,
                    <span key="e" style={{ color: color.loss }}>{money2(real.porTrade.perdidas.median)}</span>,
                    fmt.pct(real.porTrade.winRatePct, 1),
                  ],
                ]
              : []),
          ]}
        />
      </div>

      {/* ── Probabilidad de perder X ── */}
      <div>
        <Rotulo
          helpTitle="Como se calcula esta probabilidad"
          help={
            <>
              <strong>ECDF empirica.</strong> Se ordenan todos los casos observados y se cuenta que
              fraccion queda por debajo del umbral. Sin ajustar ninguna campana de Gauss: los
              resultados de trading tienen <strong>colas gordas</strong> —los dias horribles pasan
              mas de lo que una normal predice— y una normal te daria falsa tranquilidad justo en la
              zona que importa.
              <br />
              <br />
              El backend manda esa curva comprimida en 501 cuantiles, y aqui se interpola. Por eso
              el slider responde al instante sin volver a simular.
              <br />
              <br />
              <strong>Las tres cifras no preguntan lo mismo.</strong> «{cualquiera}» es la
              probabilidad de que pase <em>mañana</em>, y se mide sobre los pasos sueltos. «Alguna
              vez en la corrida» es la probabilidad de que pase <em>al menos una vez</em> en las{" "}
              {fmt.int(out.n_trades)} {pasoPlural} de una corrida entera, y se mide sobre el peor
              paso de cada simulacion. Un suceso raro repetido cientos de veces deja de ser raro:
              por eso la tercera es mucho mayor.
              <br />
              <br />
              Para un limite de perdida diaria de un fondeo manda <strong>la tercera</strong>: basta
              con romperlo una vez para estar fuera.
              <br />
              <br />
              La columna real cuenta sobre las {fmt.int(real.porDia.valores.length)} sesiones que
              ocurrieron de verdad.
            </>
          }
        >
          Probabilidad de perder una cantidad concreta
        </Rotulo>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 270px) 1fr", gap: 22, alignItems: "center" }}>
          <SliderRow
            label={`Perder en ${unPaso} al menos…`}
            value={umbralUsd}
            onChange={setUmbralUsd}
            min={0}
            max={Math.max(1000, Math.round(out.init_cash * 0.25))}
            step={Math.max(10, Math.round(out.init_cash * 0.001))}
            suffix="$"
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: "10px 30px" }}>
            <Prob label={`${cualquiera} · simulado`} pct={probs.simUno} tone={color.loss} />
            <Prob label={`${cualquiera} · real`} pct={probs.realUno} tone={color.copper} />
            <Prob
              label="Alguna vez en la corrida · simulado"
              pct={probs.simAlguno}
              tone={probs.simAlguno > 50 ? color.loss : color.warning}
            />
          </div>
        </div>
      </div>

      {/* ── Probabilidad de un drawdown de X% ── */}
      <div>
        <Rotulo
          helpTitle="Como se calcula esta probabilidad"
          help={
            <>
              Misma <strong>ECDF empirica</strong>: de las {fmt.int(out.simulations)} corridas
              simuladas se cuenta que fraccion tuvo un drawdown maximo igual o peor que el umbral.
              <br />
              <br />
              <strong>El drawdown real no es una probabilidad.</strong> El histórico recorrio{" "}
              <em>un</em> camino y su maximo fue {fmt.pct(out.base_max_drawdown, 1)}: es un hecho.
              La cifra simulada si lo es, porque ahi hay {fmt.int(out.simulations)} caminos
              distintos que contar.
              <br />
              <br />
              Compara los dos: si tu drawdown real es mucho mas suave que la mediana simulada,
              tuviste suerte y no deberias dimensionar el riesgo con esa cifra.
            </>
          }
        >
          Probabilidad de un drawdown concreto
        </Rotulo>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 270px) 1fr", gap: 22, alignItems: "center" }}>
          <SliderRow
            label="Drawdown maximo de al menos…"
            value={umbralDd}
            onChange={setUmbralDd}
            min={1}
            max={90}
            step={0.5}
            suffix="%"
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: "10px 30px" }}>
            <Prob
              label="Corridas que lo alcanzan · simulado"
              pct={probs.simDd}
              tone={probs.simDd > 50 ? color.loss : color.warning}
            />
            <InlineStats
              items={[
                { label: "DD mediano sim.", value: fmt.pct(out.drawdown.p50, 1), tone: color.loss },
                {
                  label: "DD real",
                  value: fmt.pct(out.base_max_drawdown, 1),
                  tone: color.copper,
                  help: ddRealAlcanzado
                    ? `Ya te ha pasado: el histórico llego a superar el -${umbralDd}%.`
                    : `En el histórico nunca se llego a -${umbralDd}%.`,
                },
              ]}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── 2. Prueba de fondeo ─────────────────────────────────────────────── */

interface FundingCfg {
  account: number;
  riskPct: number;
  targetPct: number;
  dailyLossPct: number;
  maxDdPct: number;
  ddBasis: "percent" | "fixed";
  minTradingDays: number;
  minTrades: number;
  plazo: "infinito" | "fijo";
  horizonDays: number;
  sims: number;
}

const DEFAULT_FUNDING: FundingCfg = {
  account: 25000,
  riskPct: 1,
  targetPct: 8,
  dailyLossPct: 2,
  maxDdPct: 6,
  ddBasis: "percent",
  minTradingDays: 5,
  minTrades: 20,
  plazo: "infinito",
  horizonDays: 30,
  sims: 5000,
};

/** Barra apilada con el reparto de desenlaces. */
function OutcomeBar({ o }: { o: FundingOutcome }) {
  const partes = [
    { pct: o.pass_pct, c: color.profit, label: "aprueban" },
    { pct: o.fail_daily_pct, c: color.loss, label: "mueren por el límite diario" },
    { pct: o.fail_dd_pct, c: color.warning, label: "mueren por drawdown" },
    { pct: o.unresolved_pct, c: color.textMuted, label: "se quedan sin resolver" },
  ].filter((p) => p.pct > 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {/* Sin esta linea, un "rompe limite diario 88%" se lee como "el 88% de
          mis DIAS pierden mas del limite", que es falso y desconcierta: son
          los INTENTOS que acaban rotos, y basta UN dia malo en todo el intento
          para romperlo. Le paso al usuario el 2026-08-27. */}
      <div style={{ fontSize: 10, fontFamily: font.sans, color: color.textMuted }}>
        De cada 100 <strong>intentos</strong> de fondeo (no de días):
      </div>
      <div style={{ display: "flex", height: 9, borderRadius: 2, overflow: "hidden" }}>
        {partes.map((p) => (
          <div key={p.label} style={{ width: `${p.pct}%`, background: p.c }} title={`${p.label}: ${p.pct}% de los intentos`} />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "3px 14px" }}>
        {partes.map((p) => (
          <span
            key={p.label}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, fontFamily: font.sans, color: color.textMuted }}
          >
            <span style={{ width: 7, height: 7, borderRadius: 1.5, background: p.c }} />
            {p.label} {p.pct.toFixed(1)}%
          </span>
        ))}
      </div>
    </div>
  );
}

/** Un desenlace, sin tarjeta: filete cobre a la izquierda y datos sueltos. */
function Outcome({ titulo, help, o }: { titulo: string; help: React.ReactNode; o: FundingOutcome }) {
  return (
    <div style={{ borderLeft: `2px solid ${color.border}`, paddingLeft: 12, display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 11, fontFamily: font.sans, color: color.textSecondary }}>{titulo}</span>
        <Help title={titulo} width={430}>
          {help}
        </Help>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
        <span style={{ fontSize: 26, fontFamily: font.mono, color: color.profit, lineHeight: 1 }}>
          {o.pass_pct.toFixed(1)}%
        </span>
        <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>se fondean</span>
      </div>
      <OutcomeBar o={o} />
      <InlineStats
        items={[
          { label: "Sesiones hasta pasar", value: o.sessions_to_pass.p50 != null ? fmt.int(o.sessions_to_pass.p50) : "—" },
          { label: "Sesion de rotura", value: o.session_of_breach.p50 != null ? fmt.int(o.session_of_breach.p50) : "—" },
          { label: "Retorno final mediano", value: fmt.pct(o.final_return_pct.p50, 1) },
        ]}
      />
    </div>
  );
}

export function FundingSection({
  valoresDia,
  maeFracs,
  tradesPorDia,
  esPct,
  riskPctDefault,
  nSesiones,
  riskLabel,
  riskHint,
  baseCash,
}: {
  /** R-multiplos por sesion (compound) o PnL en $ por sesion (additive). */
  valoresDia: number[];
  /** Capital del que salen esos dolares. Imprescindible en ADITIVO: sin el,
   *  cambiar la cuenta base encogia las reglas pero no las apuestas. */
  baseCash?: number | null;
  /** Excursion adversa de cada sesion como fraccion de su apertura. Opcional. */
  maeFracs?: number[] | null;
  tradesPorDia?: number[] | null;
  esPct: boolean;
  riskPctDefault: number;
  nSesiones: number;
  /** El portfolio no tiene "riesgo por trade": ahi el mando escala la serie. */
  riskLabel?: string;
  riskHint?: string;
}) {
  const [cfg, setCfg] = useState<FundingCfg>(() => ({
    ...DEFAULT_FUNDING,
    riskPct: riskPctDefault || DEFAULT_FUNDING.riskPct,
  }));
  const [out, setOut] = useState<FundingOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ranCfg, setRanCfg] = useState<string | null>(null);

  const set = <K extends keyof FundingCfg>(k: K, v: FundingCfg[K]) => setCfg((c) => ({ ...c, [k]: v }));

  const cfgKey = JSON.stringify(cfg);
  const stale = !!out && ranCfg !== null && ranCfg !== cfgKey && !busy;
  const hayMae = !!maeFracs && maeFracs.length === valoresDia.length && valoresDia.length > 0;

  const lanzar = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await runRobustezFunding({
        values: valoresDia,
        mae_fracs: hayMae ? maeFracs : null,
        trades_per_day: tradesPorDia && tradesPorDia.length === valoresDia.length ? tradesPorDia : null,
        account: cfg.account,
        risk_pct: cfg.riskPct,
        mode: esPct ? "compound" : "additive",
        target_pct: cfg.targetPct,
        daily_loss_pct: cfg.dailyLossPct,
        max_dd_pct: cfg.maxDdPct,
        dd_basis: cfg.ddBasis,
        min_trading_days: cfg.minTradingDays,
        min_trades: cfg.minTrades,
        horizon_days: cfg.plazo === "fijo" ? cfg.horizonDays : null,
        simulations: cfg.sims,
        seed: null,
        values_base_cash: baseCash ?? null,
      });
      setOut(res);
      setRanCfg(cfgKey);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Fallo la simulacion de fondeo");
      setOut(null);
    } finally {
      setBusy(false);
    }
  };

  const limiteUsd = (cfg.account * cfg.dailyLossPct) / 100;
  const ddUsd = (cfg.account * cfg.maxDdPct) / 100;
  const objetivoUsd = (cfg.account * cfg.targetPct) / 100;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SectionHead
        title="¿Pasarias el fondeo?"
        hint="Cada historia alternativa se recorre sesion a sesion y para en el primer evento: o alcanza el objetivo, o rompe una regla."
        right={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>
            <Help title="Como se evalua cada simulacion" width={440}>
              Se empieza con la cuenta base y se encadenan sesiones sorteadas del histórico. En cada
              una se comprueban tres cosas, por este orden:
              <br />
              <br />
              <strong>1)</strong> si la sesion pierde mas que el limite diario{" "}
              <em>contado desde el balance con el que abrio esa mañana</em> → fuera.
              <br />
              <strong>2)</strong> si la cuenta cae por debajo del suelo de drawdown{" "}
              <em>que va subiendo con cada nuevo maximo</em> → fuera.
              <br />
              <strong>3)</strong> si ha alcanzado el objetivo y cumple los minimos de sesiones y de
              operaciones → aprobado.
              <br />
              <br />
              No basta con mirar el drawdown maximo y el beneficio final por separado: si revientas
              el limite diario en la sesion 8, da igual que esa corrida acabase el año un 40%
              arriba.
              <br />
              <br />
              Si un mismo dia rompe una regla y alcanza el objetivo,{" "}
              <strong>gana la rotura</strong>: en vivo el limite salta en el momento, no al cierre.
              <br />
              <br />
              <strong>«Sin resolver»</strong> son las corridas que ni aprobaron ni rompieron nada:
              se acabo el plazo con la cuenta viva pero sin llegar al objetivo.
            </Help>
            reglas
          </span>
        }
      />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12 }}>
        <Field label="Cuenta base ($)" hint="El capital que te prestan.">
          <NumberInput value={cfg.account} onChange={(v) => set("account", v)} min={1000} step={1000} />
        </Field>
        <Field
          label={riskLabel || "Riesgo por operacion (%)"}
          hint={riskHint || (esPct ? "Sobre el capital vivo, como en el backtest." : "La fuente usaba tamaño fijo; no se aplica.")}
        >
          <NumberInput value={cfg.riskPct} onChange={(v) => set("riskPct", v)} min={0.1} max={20} step={0.1} disabled={!esPct} />
        </Field>
        <Field label="Objetivo de beneficio (%)" hint={`${fmt.money(objetivoUsd)} sobre la cuenta base.`}>
          <NumberInput value={cfg.targetPct} onChange={(v) => set("targetPct", v)} min={1} max={100} step={0.5} />
        </Field>
        <Field label="Perdida diaria maxima (%)" hint={`${fmt.money(limiteUsd)} por sesion, desde la apertura del dia.`}>
          <NumberInput value={cfg.dailyLossPct} onChange={(v) => set("dailyLossPct", v)} min={0.1} max={50} step={0.1} />
        </Field>
        <Field
          label="Drawdown maximo (%)"
          hint={cfg.ddBasis === "percent" ? "Porcentaje del maximo alcanzado." : `Cantidad fija bajo el maximo: ${fmt.money(ddUsd)}.`}
        >
          <NumberInput value={cfg.maxDdPct} onChange={(v) => set("maxDdPct", v)} min={0.5} max={90} step={0.5} />
        </Field>
        <Field
          label="Como arrastra el drawdown"
          hint={cfg.ddBasis === "percent" ? "% del pico: el margen absoluto crece contigo." : "$ fijos bajo el pico. Lo habitual en prop firms de acciones."}
        >
          <Segmented
            value={cfg.ddBasis}
            onChange={(v) => set("ddBasis", v)}
            options={[
              { value: "percent", label: "% del pico" },
              { value: "fixed", label: "$ fijos" },
            ]}
          />
        </Field>
        <Field label="Minimo de sesiones" hint="Sesiones operadas antes de poder aprobar.">
          <NumberInput value={cfg.minTradingDays} onChange={(v) => set("minTradingDays", v)} min={0} max={200} step={1} />
        </Field>
        <Field
          label="Minimo de operaciones"
          hint={tradesPorDia && tradesPorDia.length ? "Trades acumulados antes de poder aprobar." : "Sin recuento de trades en esta fuente: se cuenta 1 por sesion."}
        >
          <NumberInput value={cfg.minTrades} onChange={(v) => set("minTrades", v)} min={0} max={2000} step={5} />
        </Field>
        <Field
          label="Plazo"
          hint={cfg.plazo === "infinito" ? `Sin limite: se simulan ${fmt.int(nSesiones)} sesiones.` : "Agotarlo cuenta como «sin resolver»."}
        >
          <Segmented
            value={cfg.plazo}
            onChange={(v) => set("plazo", v)}
            options={[
              { value: "infinito", label: "Sin plazo" },
              { value: "fijo", label: "Fijo" },
            ]}
          />
        </Field>
        {cfg.plazo === "fijo" && (
          <Field label="Sesiones de plazo">
            <NumberInput value={cfg.horizonDays} onChange={(v) => set("horizonDays", v)} min={1} max={2000} step={1} />
          </Field>
        )}
        <Field label="Simulaciones">
          <NumberInput value={cfg.sims} onChange={(v) => set("sims", v)} min={500} max={50000} step={500} />
        </Field>
      </div>

      <div style={{ maxWidth: 300 }}>
        <RunButton
          onClick={lanzar}
          loading={busy}
          disabled={!valoresDia.length}
          label="Calcular probabilidad de fondeo"
          loadingLabel="Evaluando challenges…"
        />
      </div>

      {err && <ErrorBox>{err}</ErrorBox>}
      {stale && (
        <ReadingNote>Has cambiado alguna regla desde el ultimo calculo. Vuelve a pulsar el boton.</ReadingNote>
      )}

      {out && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 20 }}>
            <Outcome
              titulo="Lectura por CIERRE diario"
              o={out.closed}
              help={
                <>
                  Pregunta: «al terminar el dia, ¿habia perdido mas del limite?». Es la lectura
                  exacta y la que soportan los datos sin suposiciones.
                  <br />
                  <br />
                  Pero es <strong>optimista</strong>: ignora que a media mañana pudiste estar mucho
                  peor y en una cuenta real ya te habrian cerrado.
                </>
              }
            />
            {out.mae && (
              <Outcome
                titulo="Lectura por MAE (intradia)"
                o={out.mae}
                help={
                  <>
                    Pregunta: «en el peor momento del dia, ¿habia perdido mas del limite?». El MAE
                    es la maxima excursion en contra de cada operacion.
                    <br />
                    <br />
                    Aqui se <strong>suman los MAE de todas las operaciones del dia</strong>, o sea
                    que se supone que todas tocaron su peor punto a la vez. Eso casi nunca pasa: es
                    una <strong>cota pesimista</strong>, no una medida.
                    <br />
                    <br />
                    La realidad esta entre las dos lecturas. Si se parecen, el resultado es solido.
                    Si la de MAE se hunde, pasas el fondeo solo porque los dias malos se recuperan
                    antes del cierre — y eso es una apuesta, no un plan.
                  </>
                }
              />
            )}
          </div>

          <div style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, lineHeight: 1.6 }}>
            {fmt.int(out.simulations)} intentos · cuenta {fmt.money(out.account)} · {fmt.int(out.n_steps)} sesiones por
            intento {out.rules.horizon_days ? "(plazo fijo)" : "(sin plazo)"} · limite diario{" "}
            {fmt.money(out.rules.daily_loss_usd)} · drawdown{" "}
            {out.rules.dd_basis === "fixed" ? `${fmt.money(out.rules.dd_usd_at_start)} fijos` : `${out.rules.max_dd_pct}% del maximo`} ·
            objetivo {fmt.money(out.rules.target_usd)}
            {!hayMae && " · sin MAE en esta fuente: solo lectura por cierre"}
          </div>
        </>
      )}

      {!out && !busy && !err && (
        <ReadingNote>
          Pon las reglas de tu challenge y pulsa el boton. El mando que mas mueve el resultado es{" "}
          <strong>{(riskLabel || "el riesgo por operacion").toLowerCase().replace(" (%)", "")}</strong>:
          subirlo acelera el objetivo y multiplica las roturas por limite diario.
        </ReadingNote>
      )}
    </section>
  );
}
