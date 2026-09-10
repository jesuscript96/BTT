"use client";
import type { EvGateSummary } from "@/lib/api_backtester";

import { Fragment, useState, useMemo, useEffect } from "react";
import type { ReactNode } from "react";
import { Download } from "lucide-react";
import type { TradeRecord } from "@/lib/api_backtester";

interface TradesTabProps {
  trades: TradeRecord[];
  /**
   * `modo` decide si el trade se abre en la pestaña «Analisis por trade» o
   * desplegado bajo su propia fila. El padre carga las mismas velas en los dos
   * casos; lo unico que cambia es donde se pinta.
   */
  onSelectTrade?: (ticker: string, date: string, modo?: "pestana" | "desplegable") => void;
  /** `ticker|fecha` del trade desplegado ahora mismo, o null. Lo lleva el padre
   *  para que Trades y Calendario no puedan tener dos abiertos a la vez. */
  tradeDesplegado?: string | null;
  /** El grafico de analisis, ya montado por el padre con sus datos. */
  panelAnalisis?: ReactNode;
  /** Nombre de la estrategia, solo para bautizar el CSV descargado. */
  strategyName?: string;
  /** Puerta por EV (locates aleatorios, fase 2): resumen de la segunda pasada. */
  evGate?: EvGateSummary;
  /** La primera pasada, sin puerta, para poder comparar. */
  sinPuerta?: { total_trades: number };
}

// ── Export CSV ──────────────────────────────────────────────────────────────
// Separador ';' + decimales con punto + BOM UTF-8: Excel-ES lo abre con doble
// clic sin romper columnas y pandas solo necesita `sep=';'`. Una única fila de
// cabecera (sin bloques de resumen) para que el fichero sea directamente
// analyzable. Se exportan TODOS los trades en orden cronológico, no la ventana
// filtrada/ordenada de la tabla. (Feature de Álvaro, re-portada sobre la
// versión de staging en el merge del 08-sep.)

const WEEKDAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

const CSV_COLUMNS = [
  "#",
  "Ticker",
  "Fecha",
  "Día",
  "Dirección",
  "Hora entrada",
  "Hora salida",
  "Duración (min)",
  "Tamaño (acciones)",
  "Precio entrada ($)",
  "Precio medio entrada ($)",
  "Precio salida ($)",
  "Stop loss ($)",
  "PnL ($)",
  "Comisiones ($)",
  "Retorno (%)",
  "R múltiplo",
  "MAE (%)",
  "MFE (%)",
  "Gap (%)",
  "Motivo de salida",
  "Ejecuciones",
];

// Precios/tamaños: hasta 4 decimales sin ceros de relleno (hay tickers
// subdólar donde 2 decimales pierden información); porcentajes: 2 decimales.
const fmtNum = (n: number | null | undefined, dec: number): string =>
  n == null || Number.isNaN(n) ? "" : String(+(n.toFixed(dec)));
const fmtPct = (n: number | null | undefined): string =>
  n == null || Number.isNaN(n) ? "" : n.toFixed(2);

const csvCell = (v: string | number): string => {
  const s = String(v);
  return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

const buildTradesCsv = (trades: TradeRecord[]): string => {
  const rows = [...trades].sort((a, b) => a.entry_time_epoch - b.entry_time_epoch);
  const lines = [CSV_COLUMNS.join(";")];
  rows.forEach((t, i) => {
    lines.push(
      [
        i + 1,
        t.ticker,
        t.date,
        WEEKDAYS_ES[t.entry_weekday] ?? "",
        t.direction,
        t.entry_time.split(" ").pop()?.slice(0, 8) ?? "",
        t.exit_time.split(" ").pop()?.slice(0, 8) ?? "",
        ((t.exit_time_epoch - t.entry_time_epoch) / 60).toFixed(1),
        fmtNum(t.size, 4),
        fmtNum(t.entry_price, 4),
        // Con piramidación, entry_price es el fill REAL de la primera entrada
        // y avg_entry_price el que gobierna el PnL — van ambas columnas.
        fmtNum(t.avg_entry_price ?? t.entry_price, 4),
        fmtNum(t.exit_price, 4),
        t.stop_loss ? fmtNum(t.stop_loss, 4) : "",
        fmtNum(t.pnl, 4),
        t.fees != null ? fmtNum(t.fees, 4) : "",
        fmtPct(t.return_pct),
        t.r_multiple != null ? fmtNum(t.r_multiple, 3) : "",
        t.mae != null ? fmtPct(t.mae) : "",
        t.mfe != null ? fmtPct(t.mfe) : "",
        t.gap_pct != null ? fmtPct(t.gap_pct) : "",
        t.exit_reason,
        t.n_executions ?? "",
      ]
        .map(csvCell)
        .join(";")
    );
  });
  // \r\n para que Excel también respete los saltos de fila.
  return "\uFEFF" + lines.join("\r\n");
};

const downloadTradesCsv = (trades: TradeRecord[], strategyName?: string) => {
  const blob = new Blob([buildTradesCsv(trades)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const slug = (strategyName ?? "").trim().replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  a.download = `${slug ? slug.toLowerCase() + "_" : ""}trades_${trades.length}_${ts}.csv`;
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

type SortKey = keyof TradeRecord;
type SortDir = "asc" | "desc";

export const EXIT_COLORS: Record<string, { bg: string; text: string }> = {
  SL:           { bg: "rgba(239,68,68,0.1)",  text: "#ef4444" },
  TP:           { bg: "rgba(16,185,129,0.1)", text: "#10b981" },
  "Partial TP": { bg: "rgba(20,184,166,0.1)", text: "#14b8a6" },
  Trailing:     { bg: "rgba(217,119,6,0.1)",  text: "#d97706" },
  Signal:       { bg: "rgba(59,130,246,0.1)", text: "#3b82f6" },
  EOD:          { bg: "rgba(148,163,184,0.12)", text: "var(--color-ec-text-primary)" },
};

interface SortHeaderProps {
  label: string;
  field: SortKey;
  align?: "left" | "right";
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}

const SortHeader = ({ label, field, align = "left", sortKey, sortDir, onSort, className = "" }: SortHeaderProps) => (
  <th
    className={`px-4 py-2 text-[10px] font-semibold text-[var(--color-ec-text-primary)] uppercase tracking-wider cursor-pointer hover:text-[var(--color-ec-text-high)] select-none transition-colors font-mono ${className}`}
    style={{ textAlign: align, borderBottom: '0.5px solid var(--color-ec-border)' }}
    onClick={() => onSort(field)}
  >
    {label}
    {sortKey === field && (
      <span className="ml-0.5 text-[8px]">{sortDir === "asc" ? "▲" : "▼"}</span>
    )}
  </th>
);

export default function TradesTab({ trades, onSelectTrade, tradeDesplegado,
                                   panelAnalisis, strategyName, evGate, sinPuerta }: TradesTabProps) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  // Render en ventana: cap inicial de filas para no meter 60k <tr> en el DOM de
  // golpe (con search/sort operando sobre TODAS). "Mostrar más" agranda la ventana.
  const [visibleCount, setVisibleCount] = useState(500);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const filtered = useMemo(() => {
    let result = trades;
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (t) =>
          t.ticker.toLowerCase().includes(q) ||
          t.date.includes(q) ||
          t.exit_reason.toLowerCase().includes(q)
      );
    }
    return [...result].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDir === "asc" ? aVal - bVal : bVal - aVal;
      }
      const aStr = String(aVal);
      const bStr = String(bVal);
      return sortDir === "asc"
        ? aStr.localeCompare(bStr)
        : bStr.localeCompare(aStr);
    });
  }, [trades, search, sortKey, sortDir]);

  const summary = useMemo(() => {
    const rValues = trades
      .map((t) => t.r_multiple)
      .filter((r): r is number => r !== null);
    // Locates sorteados: el precio es por TICKER-DÍA, no por trade, así que se
    // deduplica por ticker|fecha antes de resumirlo o saldría sesgado hacia los
    // días con más operaciones.
    const porDia = new Map<string, { precio: number; factura: number }>();
    for (const t of trades) {
      if (t.locate_pkg_price != null) {
        porDia.set(`${t.ticker}|${t.date}`, { precio: t.locate_pkg_price, factura: t.locates_fee_day || 0 });
      }
    }
    const dias = [...porDia.values()];
    const sorteos = dias.map((d) => d.precio).sort((a, b) => a - b);
    const locates = sorteos.length
      ? {
          n: sorteos.length,
          media: sorteos.reduce((a, b) => a + b, 0) / sorteos.length,
          min: sorteos[0],
          max: sorteos[sorteos.length - 1],
          // La factura también es por ticker-día: sumarla por trade la contaría
          // tantas veces como trades tuviera ese día.
          factura: dias.reduce((a, d) => a + d.factura, 0),
        }
      : null;
    return {
      total: trades.length,
      avgR: rValues.length ? rValues.reduce((a, b) => a + b, 0) / rValues.length : null,
      totalPnl: trades.reduce((a, t) => a + t.pnl, 0),
      locates,
    };
  }, [trades]);
  const hayLocateSorteado = summary.locates !== null;
  const hayPuerta = trades.some((t) => t.ev_gate_ev != null);

  const shown = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount]);

  // Reinicia la ventana al filtrar/reordenar (no arrastrar un count enorme).
  useEffect(() => {
    setVisibleCount(500);
  }, [search, sortKey, sortDir]);

  if (!trades.length) {
    return <p className="text-[11px] text-[var(--muted)] font-mono">Sin trades</p>;
  }

  return (
    <div className="space-y-4" style={{ paddingTop: 24 }}>
      <div className="flex items-center justify-between mb-3">
        <input
          type="text"
          placeholder="search ticker, date, exit reason..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-2.5 py-1.5 text-[11px] font-mono border-none bg-transparent text-[var(--foreground)] focus:outline-none w-56"
          style={{ borderBottom: '1px solid var(--color-ec-border)' }}
        />
        <div className="flex gap-5 text-[10px] text-[var(--color-ec-text-secondary)] font-mono">
          <span>
            total: <strong style={{ color: 'var(--color-ec-text-high)' }}>{summary.total}</strong>
          </span>
          {summary.avgR !== null && (
            <span>
              avg R:{" "}
              <strong className={summary.avgR >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}>
                {summary.avgR.toFixed(2)}R
              </strong>
            </span>
          )}
          {evGate && (
            <span title="Puerta por EV: señales evaluadas en la segunda pasada, cuántas no compensaban el locate, y cuántos trades tenía la primera pasada (sin puerta)">
              puerta:{" "}
              <strong className="text-[var(--danger)]">{evGate.rechazadas} rechazadas</strong>
              {" "}de {evGate.evaluadas}
              {evGate.con_ev_por_defecto > 0 && ` (${evGate.con_ev_por_defecto} con EV por defecto)`}
              {sinPuerta && <> · sin puerta: <strong style={{ color: 'var(--color-ec-text-high)' }}>{sinPuerta.total_trades}</strong> trades</>}
            </span>
          )}
          {summary.locates && (
            <span title="Locates sorteados por ticker-día: precio medio del paquete de 100, rango que salió, y factura total">
              locates:{" "}
              <strong style={{ color: 'var(--color-ec-text-high)' }}>
                ${summary.locates.media.toFixed(2)}
              </strong>
              {" "}({summary.locates.min.toFixed(2)}–{summary.locates.max.toFixed(2)}, {summary.locates.n} días)
              {" "}· factura{" "}
              <strong className="text-[var(--danger)]">−${summary.locates.factura.toFixed(2)}</strong>
            </span>
          )}
          <span>
            pnl:{" "}
            <strong className={summary.totalPnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}>
              {summary.totalPnl >= 0 ? "+" : ""}${summary.totalPnl.toFixed(2)}
            </strong>
          </span>
          <button
            onClick={() => downloadTradesCsv(trades, strategyName)}
            title="Descargar todos los trades en CSV (orden cronológico, separador ';', decimales con punto)"
            className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider cursor-pointer transition-colors hover:text-[var(--color-ec-text-high)]"
            style={{ border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-secondary)', background: 'transparent' }}
          >
            <Download size={12} strokeWidth={1.5} />
            CSV
          </button>
        </div>
      </div>

      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full text-[11px] font-mono" style={{ borderCollapse: 'collapse' }}>
          <thead className="sticky top-0 bg-[var(--background)]" style={{ zIndex: 10 }}>
            <tr>
              <SortHeader label="Ticker" field="ticker" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="Fecha" field="date" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="Entrada" field="entry_time" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="Salida" field="exit_time" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="Entry $" field="entry_price" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="Exit $" field="exit_price" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="Size" field="size" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="PnL" field="pnl" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="R" field="r_multiple" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="MAE%" field="mae" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <SortHeader label="MFE%" field="mfe" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              {hayLocateSorteado && (
                <SortHeader label="Locate/100" field="locate_pkg_price" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              )}
              {hayPuerta && (
                <>
                  <SortHeader label="EV%" field="ev_gate_ev" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Fade%" field="ev_gate_fade" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                </>
              )}
              <SortHeader label="Exit" field="exit_reason" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
            </tr>
          </thead>
          <tbody>
            {shown.map((t, i) => {
              const abierto = tradeDesplegado === `${t.ticker}|${t.date}`;
              // Fragment CON key: el fragmento corto `<>` no la admite, y sin
              // ella React llena la consola de warnings en cada render.
              return (
              <Fragment key={i}>
              <tr
                className="hover:bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)] transition-colors"
                style={{ borderBottom: '1px solid color-mix(in srgb, var(--border) 30%, transparent)' }}
              >
                <td className="px-4 py-1.5 font-semibold">
                  <span
                    onClick={() => onSelectTrade?.(t.ticker, t.date, "desplegable")}
                    className="hover:text-[var(--color-ec-copper-bright)] hover:underline transition-colors cursor-pointer"
                    style={{ color: abierto ? 'var(--color-ec-copper)' : 'var(--color-ec-text-high)' }}
                    title={abierto ? "Cerrar el grafico" : "Ver el grafico aqui mismo"}
                  >
                    {abierto ? "▾ " : "▸ "}{t.ticker}
                  </span>
                </td>
                <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>{t.date}</td>
                <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>
                  {t.entry_time.split(" ").pop()?.slice(0, 8)}
                </td>
                <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>
                  {t.exit_time.split(" ").pop()?.slice(0, 8)}
                </td>
                <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>
                  ${t.entry_price.toFixed(2)}
                </td>
                <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>
                  ${t.exit_price.toFixed(2)}
                </td>
                <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}>
                  {t.size.toFixed(2)}
                </td>
                <td className={`px-4 py-1.5 font-semibold ${t.pnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}`}>
                  {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                </td>
                <td className={`px-4 py-1.5 ${(t.r_multiple || 0) >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}`}>
                  {t.r_multiple !== null ? `${t.r_multiple.toFixed(2)}R` : "—"}
                </td>
                <td className="px-4 py-1.5 text-[var(--danger)]">
                  {t.mae != null ? `${t.mae.toFixed(2)}%` : "—"}
                </td>
                <td className="px-4 py-1.5 text-[var(--success)]">
                  {t.mfe != null ? `${t.mfe.toFixed(2)}%` : "—"}
                </td>
                {hayLocateSorteado && (
                  <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}
                      title={t.locates_fee_day != null ? `factura del día: $${t.locates_fee_day.toFixed(2)}` : undefined}>
                    {t.locate_pkg_price != null ? `$${t.locate_pkg_price.toFixed(2)}` : "—"}
                  </td>
                )}
                {hayPuerta && (
                  <>
                    <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-primary)' }}
                        title="EV en sombra con el que se decidió entrar (% del precio)">
                      {t.ev_gate_ev != null ? `${t.ev_gate_ev.toFixed(2)}%` : "—"}
                    </td>
                    <td className="px-4 py-1.5" style={{ color: 'var(--color-ec-text-secondary)' }}
                        title={t.ev_gate_paquetes != null ? `${t.ev_gate_paquetes} paquete(s) de más` : undefined}>
                      {t.ev_gate_fade != null ? `${t.ev_gate_fade.toFixed(2)}%` : "—"}
                    </td>
                  </>
                )}
                <td className="px-4 py-1.5">
                  {(() => {
                    const style = EXIT_COLORS[t.exit_reason] || { bg: "rgba(148,163,184,0.12)", text: "var(--color-ec-text-primary)" };
                    return (
                      <span
                        className="inline-block px-1.5 py-0.5 rounded-sm text-[10px] font-medium"
                        style={{ backgroundColor: style.bg, color: style.text }}
                      >
                        {t.exit_reason}
                      </span>
                    );
                  })()}
                </td>
              </tr>
              {abierto && (
                <tr>
                  <td colSpan={15} style={{ padding: '10px 16px 18px', background: 'var(--color-ec-bg-sidebar)' }}>
                    {panelAnalisis}
                  </td>
                </tr>
              )}
              </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {filtered.length > shown.length && (
        <div className="flex items-center justify-center gap-3 py-2">
          <span className="text-[10px] text-[var(--color-ec-text-muted)] font-mono">
            mostrando {shown.length.toLocaleString()} de {filtered.length.toLocaleString()}
          </span>
          <button
            onClick={() => setVisibleCount((c) => c + 1000)}
            className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider cursor-pointer transition-colors hover:text-[var(--color-ec-text-high)]"
            style={{ border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-secondary)', background: 'transparent' }}
          >
            Mostrar más (+1000)
          </button>
        </div>
      )}
    </div>
  );
}
