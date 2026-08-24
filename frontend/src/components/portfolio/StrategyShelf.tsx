"use client";

// Estanteria de estrategias: el cuadro rectangular con filas FINAS (mas
// delgadas que las de Robustez, a peticion) que se usa para el baul generico,
// el portfolio y la incubadora. Cada fila lleva sus metricas tipicas, el
// distintivo de normalizacion y las acciones que le pase el contenedor.

import React, { useMemo, useState } from "react";
import { CircleAlert, ChevronRight } from "lucide-react";
import { color, font, radius } from "@/components/ui/tokens";
import { Help } from "@/components/robustez/help";
import {
  ConditionList,
  KeyVals,
  SectionTitle,
  executionLines,
} from "@/components/robustez/StrategyPicker";
import { flattenConditions, formatUniverseRule, riskLines } from "@/lib/robustez/formatStrategy";
import type { PortfolioStrategy } from "@/lib/api_portfolio_lab";

const num = (v: number | null | undefined, d = 2, suffix = "") =>
  v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}${suffix}`;

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1, minWidth: 52 }}>
      <span style={{ fontSize: 8.5, letterSpacing: "0.08em", textTransform: "uppercase", color: color.textMuted, fontFamily: font.sans }}>
        {label}
      </span>
      <span style={{ fontSize: 12, fontFamily: font.mono, color: tone || color.textPrimary }}>{value}</span>
    </div>
  );
}

/** Chip del estado de normalizacion (el requisito para entrar al portfolio). */
function NormBadge({ s }: { s: PortfolioStrategy }) {
  if (!s.run) return null;
  const n = s.normalization;
  if (!n) return null;
  if (n.normalized) {
    return (
      <span
        style={{
          fontSize: 9,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontFamily: font.sans,
          color: color.profit,
          border: `0.5px solid ${color.profit}`,
          borderRadius: radius.pill,
          padding: "2px 8px",
          whiteSpace: "nowrap",
        }}
      >
        normalizada
      </span>
    );
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap" }}>
      <span
        style={{
          fontSize: 9,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontFamily: font.sans,
          color: color.warning,
          border: `0.5px solid ${color.warning}`,
          borderRadius: radius.pill,
          padding: "2px 8px",
        }}
      >
        se normalizará{n.exact ? "" : " (aprox.)"}
      </span>
      <Help title="Corrida sin normalizar">
        Esta corrida se guardó con {n.issues.join(", ")}. El motor del portfolio la lleva al dominio común
        (R por trade, sin costes) antes de calcular: las comisiones y el compound se deshacen de forma exacta;
        el slippage solo se puede reconstruir de forma aproximada. Para el distintivo verde, re-córrela y
        guárdala con costes a cero y riesgo FIJO.
      </Help>
    </span>
  );
}

export type EqPoint = { time: number; value: number };
export type CurveState = EqPoint[] | "loading" | "error";

/** Minigrafico de los ultimos 6 meses de una curva simulada. Lo usan el
 *  desplegable del baul y las tarjetas de la Monitorizacion. */
export function Sparkline({ points }: { points: EqPoint[] }) {
  const W = 260;
  const H = 78;
  const PAD = 5;
  const data = useMemo(() => {
    if (!points || points.length < 2) return null;
    const last = points[points.length - 1].time;
    const win = points.filter((p) => p.time >= last - 182 * 86400);
    if (win.length < 2) return null;
    const vals = win.map((p) => p.value);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const span = hi - lo || 1;
    const x = (i: number) => PAD + (i / (win.length - 1)) * (W - 2 * PAD);
    const y = (v: number) => PAD + (1 - (v - lo) / span) * (H - 2 * PAD);
    const path = win.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
    const area = `${path}L${x(win.length - 1).toFixed(1)},${H - PAD}L${x(0).toFixed(1)},${H - PAD}Z`;
    const chg = win[0].value > 0 ? (win[win.length - 1].value / win[0].value - 1) * 100 : 0;
    const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);
    return { path, area, chg, d0: day(win[0].time), d1: day(last) };
  }, [points]);

  if (!data) {
    return <span style={{ fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>curva no disponible</span>;
  }
  const tone = data.chg >= 0 ? color.profit : color.loss;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, maxWidth: W }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{
          width: "100%",
          height: "auto",
          display: "block",
          background: color.bgSurface,
          border: `0.5px solid ${color.border}`,
          borderRadius: radius.sm,
        }}
      >
        <path d={data.area} fill={tone} opacity="0.08" />
        <path d={data.path} fill="none" stroke={tone} strokeWidth="1.2" />
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 9.5, fontFamily: font.mono, color: color.textMuted }}>
          {data.d0} → {data.d1}
        </span>
        <span style={{ fontSize: 11.5, fontFamily: font.mono, color: tone }}>
          {data.chg >= 0 ? "+" : ""}
          {data.chg.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

export function StrategyShelf({
  title,
  hint,
  strategies,
  emptyText,
  actions,
  curves = {},
}: {
  title: string;
  hint?: string;
  strategies: PortfolioStrategy[];
  emptyText: string;
  actions?: (s: PortfolioStrategy) => React.ReactNode;
  /** Curvas de equity PRECARGADAS por el contenedor (BaulTab): al desplegar
   *  una fila el minigrafico ya esta en memoria y sale al instante. */
  curves?: Record<string, CurveState>;
}) {
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section
      style={{
        background: color.bgSurface,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "9px 16px",
          borderBottom: `0.5px solid ${color.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <span style={{ fontSize: 10, letterSpacing: "0.11em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans }}>
          {title}
        </span>
        {hint && <span style={{ fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>{hint}</span>}
      </div>

      {strategies.length === 0 ? (
        <div style={{ padding: "18px 20px", fontSize: 12, color: color.textMuted, fontFamily: font.sans }}>{emptyText}</div>
      ) : (
        strategies.map((s, i) => {
          const open = openId === s.id;
          const r = s.run;
          return (
            <div key={s.id} style={{ borderTop: i === 0 ? "none" : `0.5px solid ${color.border}` }}>
              <div
                role="button"
                tabIndex={0}
                aria-expanded={open}
                onClick={() => setOpenId(open ? null : s.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setOpenId(open ? null : s.id);
                  }
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-ec-surface-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "6px 14px",
                  cursor: "pointer",
                  transition: "background 120ms",
                  outline: "none",
                }}
              >
                <ChevronRight
                  style={{
                    width: 13,
                    height: 13,
                    strokeWidth: 1.5,
                    color: color.textMuted,
                    flexShrink: 0,
                    transform: open ? "rotate(90deg)" : "none",
                    transition: "transform 150ms",
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontFamily: font.sans, color: color.textHigh, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.name}
                  </div>
                  <div style={{ fontSize: 10, fontFamily: font.sans, color: color.textMuted }}>
                    {r
                      ? `${r.total_trades ?? "?"} trades · corrida del ${(r.executed_at || "").slice(0, 16).replace("T", " ")}`
                      : "sin backtest guardado"}
                  </div>
                </div>

                {r ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
                    <NormBadge s={s} />
                    <Stat label="Retorno" value={num(r.total_return_pct, 1, "%")} tone={(r.total_return_pct ?? 0) >= 0 ? color.profit : color.loss} />
                    <Stat label="Max DD" value={num(r.max_drawdown_pct, 1, "%")} tone={color.loss} />
                    <Stat label="Win" value={num(r.win_rate, 1, "%")} />
                    <Stat label="PF" value={num(r.profit_factor, 2)} />
                    <Stat label="Sharpe" value={num(r.sharpe_ratio, 2)} />
                  </div>
                ) : (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, color: color.warning, fontFamily: font.sans, flexShrink: 0 }}>
                    <CircleAlert style={{ width: 12, height: 12, strokeWidth: 1.5 }} />
                    no analizable
                  </span>
                )}

                {actions && (
                  <div style={{ display: "flex", gap: 6, flexShrink: 0, marginLeft: 4 }} onClick={(e) => e.stopPropagation()}>
                    {actions(s)}
                  </div>
                )}
              </div>

              {open &&
                (() => {
                  // Mismo desplegable que el StrategyPicker de Robustez: TODAS
                  // las condiciones de la estrategia, mas el minigrafico de la
                  // curva simulada.
                  const def = (s.definition || {}) as Record<string, any>;
                  const entry = flattenConditions(def.entry_logic?.root_condition);
                  const exit = flattenConditions(def.exit_logic?.root_condition);
                  const uni = (def.universe_filters?.rules || []) as Record<string, any>[];
                  const risk = riskLines(def.risk_management);
                  const windows = (def.entry_logic?.entry_time_windows || []) as Record<string, any>[];
                  const exec = executionLines(r?.backtest_params as Record<string, any> | undefined);
                  const curve = curves[s.id];
                  return (
                    <div style={{ background: color.bgBase, padding: "14px 18px 16px 37px" }}>
                      {s.description && (
                        <p style={{ margin: "0 0 12px", fontSize: 11.5, fontFamily: font.sans, color: color.textSecondary, lineHeight: 1.55, maxWidth: 720 }}>
                          {s.description}
                        </p>
                      )}
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 22 }}>
                        <div>
                          <SectionTitle>Universo</SectionTitle>
                          <KeyVals
                            rows={[
                              ["Sesgo", String(def.bias ?? "—")],
                              ["Dia", String(def.apply_day ?? "—")],
                              ["Rango", `${def.universe_filters?.date_from ?? "?"} → ${def.universe_filters?.date_to ?? "?"}`],
                              ["Sesiones", ((def.market_sessions as string[]) || []).join(", ") || "—"],
                              ...uni.map((rule) => ["Filtro", formatUniverseRule(rule)] as [string, string]),
                            ]}
                          />
                        </div>

                        <div>
                          <SectionTitle>Entrada</SectionTitle>
                          <ConditionList items={entry} />
                          {windows.length > 0 && (
                            <div style={{ marginTop: 10 }}>
                              <KeyVals rows={windows.map((w) => ["Ventana", `${w.from_time} — ${w.to_time}`] as [string, string])} />
                            </div>
                          )}
                        </div>

                        <div>
                          <SectionTitle>Salida</SectionTitle>
                          <ConditionList items={exit} />
                        </div>

                        <div>
                          <SectionTitle>Riesgo</SectionTitle>
                          <KeyVals rows={risk} />
                        </div>

                        {exec.length > 0 && (
                          <div>
                            <SectionTitle>Ejecucion — con que se corrio</SectionTitle>
                            <KeyVals rows={exec} />
                          </div>
                        )}

                        {r && (
                          <div>
                            <SectionTitle>Ultimos 6 meses (simulado)</SectionTitle>
                            {curve === "loading" || curve === undefined ? (
                              <span style={{ fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>cargando curva…</span>
                            ) : curve === "error" ? (
                              <span style={{ fontSize: 11, color: color.warning, fontFamily: font.sans }}>no se pudo cargar la curva</span>
                            ) : (
                              <Sparkline points={curve} />
                            )}
                            <p style={{ margin: "7px 0 0", fontSize: 9.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.45, maxWidth: 260 }}>
                              Tramo final de la curva de la corrida guardada. El seguimiento en vivo llega
                              con la Monitorización.
                            </p>
                          </div>
                        )}
                      </div>
                      {!r && (
                        <span style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textMuted, display: "block", marginTop: 10 }}>
                          Ejecuta y guarda un backtest de esta estrategia desde el Backtester para poder estudiarla aqui.
                        </span>
                      )}
                    </div>
                  );
                })()}
            </div>
          );
        })
      )}
    </section>
  );
}

/** Boton pequeño de accion de fila (añadir/quitar de un cuadro, borrar).
 *
 *  `danger` lo tiñe de rojo sin rellenarlo: la accion destructiva tiene que
 *  distinguirse de un vistazo, pero sin gritar mas que los datos de la fila. */
export function ShelfAction({
  label,
  active,
  onClick,
  disabled,
  title,
  danger,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
}) {
  const borde = danger ? color.loss : active ? color.copper : color.border;
  const texto = disabled
    ? color.textMuted
    : danger
      ? color.loss
      : active
        ? color.copperText
        : color.textSecondary;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        padding: "3px 9px",
        fontSize: 10,
        fontFamily: font.sans,
        letterSpacing: "0.03em",
        border: `0.5px solid ${borde}`,
        borderRadius: radius.sm,
        background: active && !danger ? color.copper : "transparent",
        color: texto,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: "background 120ms, border-color 120ms",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </button>
  );
}
