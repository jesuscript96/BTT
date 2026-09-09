import type { TradeRecord, DayResult } from "./api_backtester";

/** Un día operado con su PnL neto y su número de trades. */
export interface StreakDay {
  date: string;
  /** Σ trade.pnl del día − locates_fee del día (convención de rachas). */
  pnl: number;
  trades: number;
}

/** Una racha corrida de días del mismo signo, en índices de `days`. */
export interface StreakRun {
  type: "W" | "L";
  length: number;
  startIdx: number;
}

export interface DayStreakStats {
  /** Días operados en orden cronológico. */
  days: StreakDay[];
  totalDays: number;
  winDays: number;
  loseDays: number;
  winDaysPct: number;
  maxWinStreak: number;
  maxLoseStreak: number;
  /** Racha que contiene al último día operado (null sin días). */
  currentStreak: StreakRun | null;
  winStreaks: StreakRun[];
  loseStreaks: StreakRun[];
}

/** Rachas de días ganadores/perdedores de una corrida.
 *
 * MISMA receta que las métricas «Max W/L Day Streak» (backend,
 * backtest_service._aggregate_metrics) y que el recorte IS del cliente
 * (backtester/page.tsx): el día es Σ pnl de sus trades menos la factura de
 * locates (que viaja en day_results y NO dentro de ningún pnl de trade);
 * solo cuentan los días con operaciones — un día sin operar no rompe la
 * racha — y un día plano (pnl 0) cuenta como perdedor. Los gastos fijos
 * mensuales no se descuentan aquí.
 */
export function computeDayStreaks(
  trades: TradeRecord[],
  dayResults: DayResult[],
): DayStreakStats {
  const pnlByDate = new Map<string, number>();
  const tradesByDate = new Map<string, number>();
  for (const t of trades) {
    if (!t.date) continue;
    pnlByDate.set(t.date, (pnlByDate.get(t.date) ?? 0) + t.pnl);
    tradesByDate.set(t.date, (tradesByDate.get(t.date) ?? 0) + 1);
  }
  // Los locates solo se restan de días que ya tienen trades: un ticker-día
  // con factura pero sin operaciones no es un «día operado».
  for (const d of dayResults) {
    if (!d.date || !d.locates_fee) continue;
    if (pnlByDate.has(d.date)) {
      pnlByDate.set(d.date, (pnlByDate.get(d.date) ?? 0) - d.locates_fee);
    }
  }

  const dates = Array.from(pnlByDate.keys()).sort();
  const days: StreakDay[] = dates.map((date) => ({
    date,
    pnl: pnlByDate.get(date) ?? 0,
    trades: tradesByDate.get(date) ?? 0,
  }));

  const winStreaks: StreakRun[] = [];
  const loseStreaks: StreakRun[] = [];
  let winDays = 0;
  days.forEach((d, idx) => {
    const type: "W" | "L" = d.pnl > 0 ? "W" : "L";
    if (type === "W") winDays += 1;
    const list = type === "W" ? winStreaks : loseStreaks;
    const prev = list[list.length - 1];
    if (prev && prev.startIdx + prev.length === idx) prev.length += 1;
    else list.push({ type, length: 1, startIdx: idx });
  });

  const totalDays = days.length;
  const currentStreak = (() => {
    const w = winStreaks[winStreaks.length - 1];
    if (w && w.startIdx + w.length === totalDays) return w;
    const l = loseStreaks[loseStreaks.length - 1];
    if (l && l.startIdx + l.length === totalDays) return l;
    return null;
  })();

  return {
    days,
    totalDays,
    winDays,
    loseDays: totalDays - winDays,
    winDaysPct: totalDays > 0 ? (winDays / totalDays) * 100 : 0,
    maxWinStreak: winStreaks.reduce((m, s) => Math.max(m, s.length), 0),
    maxLoseStreak: loseStreaks.reduce((m, s) => Math.max(m, s.length), 0),
    currentStreak,
    winStreaks,
    loseStreaks,
  };
}
