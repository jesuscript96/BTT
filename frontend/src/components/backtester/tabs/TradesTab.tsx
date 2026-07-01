"use client";

import { useState, useMemo, useEffect } from "react";
import type { TradeRecord } from "@/lib/api_backtester";

interface TradesTabProps {
  trades: TradeRecord[];
  onSelectTrade?: (ticker: string, date: string) => void;
}

type SortKey = keyof TradeRecord;
type SortDir = "asc" | "desc";

const EXIT_COLORS: Record<string, { bg: string; text: string }> = {
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

export default function TradesTab({ trades, onSelectTrade }: TradesTabProps) {
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
    return {
      total: trades.length,
      avgR: rValues.length ? rValues.reduce((a, b) => a + b, 0) / rValues.length : null,
      totalPnl: trades.reduce((a, t) => a + t.pnl, 0),
    };
  }, [trades]);

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
          <span>
            pnl:{" "}
            <strong className={summary.totalPnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"}>
              {summary.totalPnl >= 0 ? "+" : ""}${summary.totalPnl.toFixed(2)}
            </strong>
          </span>
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
              <SortHeader label="Exit" field="exit_reason" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
            </tr>
          </thead>
          <tbody>
            {shown.map((t, i) => (
              <tr
                key={i}
                className="hover:bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)] transition-colors"
                style={{ borderBottom: '1px solid color-mix(in srgb, var(--border) 30%, transparent)' }}
              >
                <td className="px-4 py-1.5 font-semibold">
                  <span
                    onClick={() => onSelectTrade?.(t.ticker, t.date)}
                    className="hover:text-[var(--color-ec-copper-bright)] hover:underline transition-colors cursor-pointer"
                    style={{ color: 'var(--color-ec-text-high)' }}
                  >
                    {t.ticker}
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
            ))}
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
