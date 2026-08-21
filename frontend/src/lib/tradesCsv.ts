import type { TradeRecord } from "./api_backtester";

// Exportación CSV de los trades de un backtest: una fila por trade con todos los
// datos disponibles — identificación, punto de entrada/salida, triggers de salida
// (cadena completa + detalle de cada ejecución parcial), resultado y excursiones.
// Función pura (sin React ni DOM) para poder construir y descargar desde cualquier
// componente.

const COLUMNS = [
  "ticker",
  "date",
  "direction",
  "entry_time",
  "entry_price",
  "size",
  "stop_loss",
  "sl_dist_pct",
  "exit_time",
  "exit_price",
  "exit_reason",
  "exit_reasons",
  "legs_detail",
  "n_executions",
  "partials_skipped",
  "pnl",
  "fees",
  "return_pct",
  "r_multiple",
  "mae",
  "mfe",
  "mae_prev_max",
  "mfe_prev_max",
  "prev_max_ref",
  "fade_at_entry_pct",
  "gap_pct",
  "entry_hour",
  "entry_weekday",
  "status",
] as const;

// Escapado RFC 4180: comillar si hay coma, comilla o salto de línea.
function csvEscape(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

// Números siempre con punto decimal (sin locale); null/undefined → vacío.
function num(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "" : String(value);
}

// Detalle de cada ejecución de la posición (parciales + cierre final):
// "hora|precio|size|razón|pnl" por leg, unidas por ";". Internamente usa "|" y
// ";" para no chocar con la coma del CSV.
function legsDetail(t: TradeRecord): string {
  if (!t.legs?.length) return "";
  return t.legs
    .map((l) =>
      [l.exit_time ?? "", num(l.exit_price), num(l.size), l.exit_reason ?? "", num(l.pnl)].join("|")
    )
    .join(";");
}

function partialsSkipped(t: TradeRecord): string {
  return (t.partials_skipped ?? []).map((s) => s.reason).join(";");
}

// Distancia % del stop al entry — misma fórmula que la métrica agregada del
// backend (abs(stop − entry) / entry × 100). Vacío si el trade no tiene stop
// válido o el entry es inválido.
function slDistPct(t: TradeRecord): string {
  const sl = t.stop_loss ?? 0;
  const ep = t.entry_price ?? 0;
  if (sl <= 0 || ep <= 0) return "";
  return ((Math.abs(sl - ep) / ep) * 100).toFixed(1);
}

export function buildTradesCsv(trades: TradeRecord[]): { csv: string; filename: string } {
  // Orden cronológico por entrada, independiente del orden visual del tab.
  const sorted = [...trades].sort((a, b) => (a.entry_time_epoch ?? 0) - (b.entry_time_epoch ?? 0));

  const rows = sorted.map((t) =>
    [
      t.ticker ?? "",
      t.date ?? "",
      t.direction ?? "",
      t.entry_time ?? "",
      num(t.entry_price),
      num(t.size),
      num(t.stop_loss),
      slDistPct(t),
      t.exit_time ?? "",
      num(t.exit_price),
      t.exit_reason ?? "",
      (t.exit_reasons ?? []).join(" → "),
      legsDetail(t),
      num(t.n_executions),
      partialsSkipped(t),
      num(t.pnl),
      num(t.fees),
      num(t.return_pct),
      num(t.r_multiple),
      num(t.mae),
      num(t.mfe),
      num(t.mae_prev_max),
      num(t.mfe_prev_max),
      num(t.prev_max_ref),
      num(t.fade_at_entry_pct),
      num(t.gap_pct),
      num(t.entry_hour),
      num(t.entry_weekday),
      t.status ?? "",
    ].map(csvEscape).join(",")
  );

  // BOM UTF-8 para que Excel interprete bien la codificación (la cadena de
  // triggers lleva "→").
  const csv = "\uFEFF" + [COLUMNS.join(","), ...rows].join("\r\n");

  const first = sorted[0]?.date;
  const last = sorted[sorted.length - 1]?.date;
  const filename =
    first && last ? `trades_${first}_to_${last}.csv` : `trades_${new Date().toISOString().slice(0, 10)}.csv`;

  return { csv, filename };
}
