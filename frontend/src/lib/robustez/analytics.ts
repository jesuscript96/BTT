// Matematica del "Analisis basico": drawdown, rachas y recuperacion.
//
// Se calcula en el navegador a proposito. Son unos pocos miles de trades y un
// par de barridos O(n): hacerlo aqui evita un viaje al servidor por cada
// reajuste y deja el panel instantaneo. Los modulos que SI necesitan al backend
// son los que re-ejecutan backtests.

import type { EquityPointT, RobustezTrade } from "@/lib/api_robustez";

const DAY_S = 86_400;

export interface DrawdownEpisode {
  /** Indice del pico donde arranca el episodio. */
  startIdx: number;
  /** Indice del punto mas bajo. */
  troughIdx: number;
  /** Indice donde se recupera el pico previo; null si nunca se recupero. */
  recoveredIdx: number | null;
  depthPct: number;
  depthUsd: number;
  /** Sesiones (puntos de la curva) desde el pico hasta recuperarlo. */
  sessions: number;
  /** Dias naturales entre el pico y la recuperacion. */
  calendarDays: number;
  startTime: number;
  troughTime: number;
}

export interface StreakInfo {
  maxLosing: number;
  maxLosingUsd: number;
  maxWinning: number;
  maxWinningUsd: number;
  /** Distribucion: cuantas veces se dio cada longitud de racha perdedora. */
  losingHistogram: Array<{ length: number; count: number }>;
}

export interface BasicAnalysis {
  episodes: DrawdownEpisode[];
  worstEpisode: DrawdownEpisode | null;
  /** Episodio con mas sesiones, que no siempre es el mas profundo. */
  longestEpisode: DrawdownEpisode | null;
  /** Episodio abierto al final del histórico, si lo hay. */
  openEpisode: DrawdownEpisode | null;
  pctTimeInDrawdown: number;
  /** El episodio mas largo, como fraccion del histórico completo. */
  longestEpisodePctOfTime: number;
  maxDrawdownPct: number;
  ulcerIndex: number;
  streaks: StreakInfo;
  worstDayUsd: number;
  worstDayDate: string | null;
  worstTradeUsd: number;
  worstTradeLabel: string | null;
  avgDailyPnl: number;
  tradingDays: number;
}

/** Episodios de drawdown a partir de la curva de equity diaria. */
export function drawdownEpisodes(equity: EquityPointT[]): DrawdownEpisode[] {
  if (equity.length < 2) return [];
  const out: DrawdownEpisode[] = [];

  let peakIdx = 0;
  let peakVal = equity[0].value;
  let inDd = false;
  let troughIdx = 0;
  let troughVal = peakVal;

  for (let i = 1; i < equity.length; i++) {
    const v = equity[i].value;
    if (v >= peakVal) {
      // Recuperado: cierra el episodio abierto antes de mover el pico.
      if (inDd) {
        out.push(buildEpisode(equity, peakIdx, troughIdx, i, peakVal, troughVal));
        inDd = false;
      }
      peakVal = v;
      peakIdx = i;
    } else {
      if (!inDd) {
        inDd = true;
        troughVal = v;
        troughIdx = i;
      } else if (v < troughVal) {
        troughVal = v;
        troughIdx = i;
      }
    }
  }
  // Episodio que sigue abierto al final del histórico.
  if (inDd) out.push(buildEpisode(equity, peakIdx, troughIdx, null, peakVal, troughVal));
  return out;
}

function buildEpisode(
  equity: EquityPointT[],
  peakIdx: number,
  troughIdx: number,
  recoveredIdx: number | null,
  peakVal: number,
  troughVal: number,
): DrawdownEpisode {
  const endIdx = recoveredIdx ?? equity.length - 1;
  return {
    startIdx: peakIdx,
    troughIdx,
    recoveredIdx,
    depthPct: peakVal > 0 ? (troughVal / peakVal - 1) * 100 : 0,
    depthUsd: troughVal - peakVal,
    sessions: endIdx - peakIdx,
    calendarDays: Math.round((equity[endIdx].time - equity[peakIdx].time) / DAY_S),
    startTime: equity[peakIdx].time,
    troughTime: equity[troughIdx].time,
  };
}

/** Rachas consecutivas de trades ganadores y perdedores. */
export function streaks(trades: RobustezTrade[]): StreakInfo {
  let maxLosing = 0;
  let maxLosingUsd = 0;
  let maxWinning = 0;
  let maxWinningUsd = 0;

  let curLose = 0;
  let curLoseUsd = 0;
  let curWin = 0;
  let curWinUsd = 0;
  const hist = new Map<number, number>();

  const closeLosing = () => {
    if (curLose > 0) hist.set(curLose, (hist.get(curLose) || 0) + 1);
    curLose = 0;
    curLoseUsd = 0;
  };

  for (const t of trades) {
    const pnl = t.pnl ?? 0;
    if (pnl < 0) {
      curWin = 0;
      curWinUsd = 0;
      curLose += 1;
      curLoseUsd += pnl;
      if (curLose > maxLosing) maxLosing = curLose;
      if (curLoseUsd < maxLosingUsd) maxLosingUsd = curLoseUsd;
    } else if (pnl > 0) {
      closeLosing();
      curWin += 1;
      curWinUsd += pnl;
      if (curWin > maxWinning) maxWinning = curWin;
      if (curWinUsd > maxWinningUsd) maxWinningUsd = curWinUsd;
    }
    // pnl === 0 no rompe ninguna racha ni cuenta para ninguna.
  }
  closeLosing();

  const losingHistogram = Array.from(hist.entries())
    .map(([length, count]) => ({ length, count }))
    .sort((a, b) => a.length - b.length);

  return { maxLosing, maxLosingUsd, maxWinning, maxWinningUsd, losingHistogram };
}

export function analyzeBasic(trades: RobustezTrade[], equity: EquityPointT[]): BasicAnalysis {
  const eps = drawdownEpisodes(equity);

  const closed = eps.filter((e) => e.recoveredIdx !== null);
  const open = eps.find((e) => e.recoveredIdx === null) || null;

  const worst = eps.reduce<DrawdownEpisode | null>(
    (acc, e) => (acc === null || e.depthPct < acc.depthPct ? e : acc),
    null,
  );
  const longest = eps.reduce<DrawdownEpisode | null>(
    (acc, e) => (acc === null || e.sessions > acc.sessions ? e : acc),
    null,
  );

  // Fraccion de sesiones por debajo del maximo previo, e indice de Ulcer
  // (raiz del drawdown cuadratico medio: penaliza los hundimientos largos y
  // profundos mas que el max DD, que solo mira el peor punto).
  let below = 0;
  let sumSq = 0;
  let peak = equity.length ? equity[0].value : 0;
  for (const p of equity) {
    if (p.value > peak) peak = p.value;
    const dd = peak > 0 ? (p.value / peak - 1) * 100 : 0;
    if (dd < 0) below += 1;
    sumSq += dd * dd;
  }
  const n = equity.length || 1;

  // PnL agregado por dia, para el peor dia.
  const byDay = new Map<string, number>();
  for (const t of trades) byDay.set(t.date, (byDay.get(t.date) || 0) + (t.pnl ?? 0));
  let worstDayUsd = 0;
  let worstDayDate: string | null = null;
  for (const [d, v] of byDay) {
    if (v < worstDayUsd) {
      worstDayUsd = v;
      worstDayDate = d;
    }
  }

  let worstTradeUsd = 0;
  let worstTradeLabel: string | null = null;
  for (const t of trades) {
    if ((t.pnl ?? 0) < worstTradeUsd) {
      worstTradeUsd = t.pnl;
      worstTradeLabel = `${t.ticker} · ${t.date}`;
    }
  }

  const totalPnl = trades.reduce((s, t) => s + (t.pnl ?? 0), 0);

  return {
    episodes: eps,
    worstEpisode: worst,
    longestEpisode: longest,
    openEpisode: open,
    pctTimeInDrawdown: (below / n) * 100,
    // Cuanto del histórico se lo comio EL PEOR tramo, no la suma de todos: es
    // la respuesta a "¿cuanto tiempo seguido puedo pasar sin ver un maximo?".
    longestEpisodePctOfTime: longest ? (longest.sessions / n) * 100 : 0,
    maxDrawdownPct: worst?.depthPct ?? 0,
    ulcerIndex: Math.sqrt(sumSq / n),
    streaks: streaks(trades),
    worstDayUsd,
    worstDayDate,
    worstTradeUsd,
    worstTradeLabel,
    avgDailyPnl: byDay.size ? totalPnl / byDay.size : 0,
    tradingDays: byDay.size,
    // `closed` se usa solo para distinguir episodios recuperados de los abiertos
    // en la tabla; se recalcula ahi para no arrastrar otro campo.
    ...(closed.length ? {} : {}),
  };
}

/** Formatea una fecha epoch (segundos, UTC) como YYYY-MM-DD. */
export function epochToDate(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}
