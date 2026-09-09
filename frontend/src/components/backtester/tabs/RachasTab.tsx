"use client";

import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { TradeRecord, DayResult } from "@/lib/api_backtester";
import { computeDayStreaks, type StreakDay, type StreakRun } from "@/lib/day_streaks";

const MESES_ES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"];

function fmtPnl(n: number): string {
  const abs = Math.abs(n).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n >= 0 ? "+" : "-"}$${abs}`;
}

function formatFecha(date: string): string {
  // T12:00 fija mediodía local para que el día no se mueva por la zona horaria.
  const d = new Date(`${date}T12:00:00`);
  return d.toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

const statBase: CSSProperties = {
  fontFamily: "var(--color-ec-sans)",
  fontSize: 11,
  color: "var(--color-ec-text-muted)",
  whiteSpace: "nowrap",
};

function StatNum({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <strong style={{ fontFamily: "var(--color-ec-mono)", fontSize: 13.5, color: color ?? "var(--color-ec-text-high)" }}>
      {children}
    </strong>
  );
}

function StreakHistogram({ runs, color, title }: { runs: StreakRun[]; color: string; title: string }) {
  if (!runs.length) return null;
  const maxLen = Math.max(...runs.map((r) => r.length));
  const counts = new Array<number>(maxLen + 1).fill(0);
  for (const r of runs) counts[r.length] += 1;
  const maxCount = Math.max(...counts);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{
        fontFamily: "var(--color-ec-sans)",
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        color: "var(--color-ec-text-muted)",
      }}>
        {title}
      </span>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 5 }}>
        {counts.slice(1).map((c, i) => (
          <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, width: 24 }}>
            <span style={{ fontFamily: "var(--color-ec-mono)", fontSize: 11, color: c > 0 ? color : "transparent" }}>
              {c}
            </span>
            <div
              title={c > 0 ? `${c} racha${c === 1 ? "" : "s"} de ${i + 1} día${i + 1 === 1 ? "" : "s"}` : undefined}
              style={{
                width: 16,
                height: Math.max(2, Math.round((c / maxCount) * 64)),
                borderRadius: 2,
                backgroundColor: color,
                opacity: c > 0 ? 0.85 : 0.12,
              }}
            />
            <span style={{ fontFamily: "var(--color-ec-mono)", fontSize: 10, color: "var(--color-ec-text-muted)" }}>
              {i + 1}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

interface RachasTabProps {
  trades: TradeRecord[];
  dayResults: DayResult[];
}

export default function RachasTab({ trades, dayResults }: RachasTabProps) {
  const stats = useMemo(() => computeDayStreaks(trades, dayResults), [trades, dayResults]);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Los días se agrupan por mes natural: cada bloque lleva su etiqueta arriba
  // y los bloques fluyen con wrap, así las rachas se leen de corrido sin
  // huecos de calendario.
  const months = useMemo(() => {
    const groups: { key: string; label: string; days: { day: StreakDay; idx: number }[] }[] = [];
    stats.days.forEach((day, idx) => {
      const key = day.date.slice(0, 7);
      let g = groups[groups.length - 1];
      if (!g || g.key !== key) {
        g = {
          key,
          label: `${MESES_ES[Number(day.date.slice(5, 7)) - 1] ?? "?"} ${day.date.slice(2, 4)}`,
          days: [],
        };
        groups.push(g);
      }
      g.days.push({ day, idx });
    });
    return groups;
  }, [stats.days]);

  if (!stats.totalDays) {
    return <p className="text-[11px] text-[var(--color-ec-text-muted)] font-mono">Sin días operados</p>;
  }

  const cur = stats.currentStreak;

  return (
    <div style={{ padding: "10px 2px 8px" }}>
      {/* ── Cabecera de estadísticas ── */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 18px", alignItems: "baseline" }}>
        <span style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 9.5,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--color-ec-copper)",
        }}>
          Rachas de días
        </span>
        <span style={statBase}>
          Días operados <StatNum>{stats.totalDays}</StatNum>
        </span>
        <span style={statBase}>
          Ganadores <StatNum color="var(--color-ec-profit)">{stats.winDays}</StatNum>
        </span>
        <span style={statBase}>
          Perdedores <StatNum color="var(--color-ec-loss)">{stats.loseDays}</StatNum>
        </span>
        <span style={statBase}>
          <StatNum>{stats.winDaysPct.toFixed(1)}%</StatNum> días ganadores
        </span>
        <span style={statBase}>
          Racha máx <StatNum color="var(--color-ec-profit)">W {stats.maxWinStreak}</StatNum>
          {" / "}
          <StatNum color="var(--color-ec-loss)">L {stats.maxLoseStreak}</StatNum>
        </span>
        {cur && (
          <span style={statBase}>
            Actual <StatNum color={cur.type === "W" ? "var(--color-ec-profit)" : "var(--color-ec-loss)"}>
              {cur.type}{cur.length}
            </StatNum>
          </span>
        )}
      </div>

      {/* ── Tira cronológica: un cuadradito por día operado.
          Los meses van en una rejilla de celdas del MISMO ancho (patrón del
          grid de meses de CalendarTab): bloques alineados entre sí y
          cuadraditos que llenan la celda, compacto y sin bordes desiguales.
          Se lee en orden cronológico: izquierda→derecha, arriba→abajo. */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: "10px 16px",
        padding: "12px 0 0",
      }}>
        {months.map((m) => (
          <div key={m.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{
              fontFamily: "var(--color-ec-sans)",
              fontSize: 9,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.12em",
              color: "var(--color-ec-text-muted)",
            }}>
              {m.label}
            </span>
            <div style={{ display: "flex", gap: 2 }}>
              {m.days.map(({ day, idx }) => {
                const win = day.pnl > 0;
                const hovered = hoverIdx === idx;
                return (
                  <div
                    key={day.date}
                    style={{ position: "relative", flex: "1 1 0", minWidth: 5 }}
                    onMouseEnter={() => setHoverIdx(idx)}
                    onMouseLeave={() => setHoverIdx((h) => (h === idx ? null : h))}
                  >
                    <div style={{
                      width: "100%",
                      height: 18,
                      borderRadius: 2,
                      cursor: "default",
                      backgroundColor: win
                        ? `rgba(74, 157, 127, ${hovered ? 0.38 : 0.18})`
                        : `rgba(201, 77, 63, ${hovered ? 0.38 : 0.18})`,
                      border: `0.5px solid ${win ? "var(--color-ec-profit)" : "var(--color-ec-loss)"}`,
                      transition: "background-color 100ms ease",
                    }} />
                    {hovered && (
                      <div style={{
                        position: "absolute",
                        bottom: "100%",
                        left: "50%",
                        transform: "translateX(-50%)",
                        marginBottom: 6,
                        padding: "5px 8px",
                        backgroundColor: "var(--color-ec-bg-elevated)",
                        border: "0.5px solid var(--color-ec-border)",
                        borderRadius: 4,
                        fontFamily: "var(--color-ec-mono)",
                        fontSize: 10,
                        lineHeight: 1.5,
                        whiteSpace: "nowrap",
                        zIndex: 30,
                        pointerEvents: "none",
                      }}>
                        <div style={{ color: "var(--color-ec-text-high)" }}>{formatFecha(day.date)}</div>
                        <div style={{ color: win ? "var(--color-ec-profit)" : "var(--color-ec-loss)" }}>
                          {fmtPnl(day.pnl)} · {day.trades} {day.trades === 1 ? "trade" : "trades"}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* ── Histograma de longitudes ── */}
      <div style={{ marginTop: 14, paddingTop: 10, borderTop: "0.5px solid var(--color-ec-border)" }}>
        <span style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 9,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          color: "var(--color-ec-text-muted)",
        }}>
          Nº de rachas por longitud
        </span>
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 10,
          color: "var(--color-ec-text-muted)",
          margin: "3px 0 0",
        }}>
          Cuántas veces hubo una racha de exactamente N días seguidos del mismo signo.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 36, marginTop: 10 }}>
          <StreakHistogram runs={stats.winStreaks} color="var(--color-ec-profit)" title="Rachas ganadoras" />
          <StreakHistogram runs={stats.loseStreaks} color="var(--color-ec-loss)" title="Rachas perdedoras" />
        </div>
      </div>

      <p style={{
        marginTop: 14,
        fontSize: 10,
        color: "var(--color-ec-text-muted)",
        fontFamily: "var(--color-ec-sans)",
        lineHeight: 1.6,
      }}>
        Verde = día cerrado en positivo (neto de locates) · rojo = negativo o plano. Solo cuentan los
        días con operaciones: un día sin operar no rompe la racha. Los gastos fijos mensuales no están
        descontados aquí (la curva «con gastos» del equity sí los lleva).
      </p>
    </div>
  );
}
