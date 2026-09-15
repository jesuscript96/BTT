"use client";

// Estanteria de estrategias: el cuadro rectangular con filas FINAS de UNA
// linea, estilo hoja de calculo (pedido el 14-sep-2026: el baul crecia y habia
// que bajar y bajar), que se usa para el baul generico, el portfolio y la
// incubadora. Las etiquetas de las metricas van UNA vez, en la cabecera del
// cuadro, y no repetidas en cada fila; el cuadro tiene altura tope y scroll
// interno con la cabecera fija. Cada fila lleva el distintivo de normalizacion
// y las acciones que le pase el contenedor; al desplegarla se ven todas las
// condiciones y el minigrafico (que se carga en ese momento, no antes).

import React, { useMemo, useState } from "react";
import { CircleAlert, ChevronRight } from "lucide-react";
import { color, font, radius } from "@/components/ui/tokens";
import { Help } from "@/components/robustez/help";
import { RenameableName } from "@/components/robustez/shared";
import type { PortfolioStrategy } from "@/lib/api_portfolio_lab";
import { StrategyDetail } from "./StrategyDetail";

const num = (v: number | null | undefined, d = 2, suffix = "") =>
  v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}${suffix}`;

/** Celda numerica de la fila: sin etiqueta (va en la cabecera del cuadro). */
function Cell({ value, tone }: { value: string; tone?: string }) {
  return (
    <span style={{ fontSize: 11.5, fontFamily: font.mono, color: tone || color.textPrimary, textAlign: "right", whiteSpace: "nowrap" }}>
      {value}
    </span>
  );
}

/** Columnas de la fila y de la cabecera: chevron, nombre, corrida, estado,
 *  cinco metricas y las acciones. Compartidas para que cuadren. */
const COLS = "14px minmax(180px, 1fr) 150px 132px 64px 60px 52px 48px 56px auto";

function HeadCell({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <span style={{ fontSize: 8.5, letterSpacing: "0.09em", textTransform: "uppercase", color: color.textMuted, fontFamily: font.sans, textAlign: right ? "right" : "left", whiteSpace: "nowrap" }}>
      {children}
    </span>
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
        se normalizará{n.exact ? "" : " ≈"}
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
  onRename,
  onOpen,
  onMove,
  maxRows = 12,
}: {
  title: string;
  hint?: string;
  strategies: PortfolioStrategy[];
  emptyText: string;
  actions?: (s: PortfolioStrategy) => React.ReactNode;
  /** Curvas de equity que el contenedor (BaulTab) ya tiene en memoria. */
  curves?: Record<string, CurveState>;
  /** Renombrado inline. Si se omite, el nombre se pinta sin lapiz. */
  onRename?: (s: PortfolioStrategy, newName: string) => Promise<void>;
  /** Se llama al DESPLEGAR una fila: el contenedor carga la curva entonces.
   *  Antes se precargaban todas al abrir la pagina, trece llamadas a la vez
   *  que se serializaban en el backend y dejaban el listado en timeout. */
  onOpen?: (s: PortfolioStrategy) => void;
  /** Subir/bajar la fila dentro de este cuadro (se le pasan los ids visibles). */
  onMove?: (s: PortfolioStrategy, dir: -1 | 1, visibles: string[]) => void;
  /** Filas visibles sin scroll; a partir de ahi el cuadro hace scroll interno. */
  maxRows?: number;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const ROW_H = 28;
  const toggleRow = (s: PortfolioStrategy, open: boolean) => {
    setOpenId(open ? null : s.id);
    if (!open) onOpen?.(s);
  };

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
      // Con una fila desplegada el cuadro crece: el detalle (condiciones y
      // minigrafico) no cabe en doce filas y leerlo con scroll interno era
      // incomodo. Al plegarla vuelve a su altura tope.
      <div style={{ maxHeight: openId ? undefined : ROW_H * maxRows + 24, overflowY: "auto" }}>
        {/* Cabecera de columnas, fija al hacer scroll. */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: COLS,
            columnGap: 10,
            alignItems: "center",
            padding: "4px 14px",
            position: "sticky",
            top: 0,
            zIndex: 1,
            background: color.bgSurface,
            borderBottom: `0.5px solid ${color.border}`,
          }}
        >
          <span />
          <HeadCell>Estrategia</HeadCell>
          <HeadCell>Corrida</HeadCell>
          <HeadCell>Estado</HeadCell>
          <HeadCell right>Retorno</HeadCell>
          <HeadCell right>Max DD</HeadCell>
          <HeadCell right>Win</HeadCell>
          <HeadCell right>PF</HeadCell>
          <HeadCell right>Sharpe</HeadCell>
          <span />
        </div>
        {strategies.map((s, idx) => {
          const open = openId === s.id;
          const r = s.run;
          const visibles = strategies.map((x) => x.id);
          return (
            <div key={s.id} style={{ borderTop: `0.5px solid ${color.border}` }}>
              <div
                role="button"
                tabIndex={0}
                aria-expanded={open}
                onClick={() => toggleRow(s, open)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleRow(s, open);
                  }
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-ec-surface-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = open ? color.bgElevated : "transparent")}
                style={{
                  display: "grid",
                  gridTemplateColumns: COLS,
                  columnGap: 10,
                  alignItems: "center",
                  height: ROW_H,
                  padding: "0 14px",
                  cursor: "pointer",
                  transition: "background 120ms",
                  outline: "none",
                  background: open ? color.bgElevated : "transparent",
                }}
              >
                <ChevronRight
                  style={{
                    width: 12,
                    height: 12,
                    strokeWidth: 1.5,
                    color: color.textMuted,
                    transform: open ? "rotate(90deg)" : "none",
                    transition: "transform 150ms",
                  }}
                />
                <div style={{ minWidth: 0, fontSize: 12, fontFamily: font.sans, color: color.textHigh, display: "flex", alignItems: "center" }}>
                  {onRename ? (
                    <RenameableName name={s.name} onRename={(n) => onRename(s, n)} textStyle={{ fontSize: 12 }} />
                  ) : (
                    <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.name}
                    </span>
                  )}
                </div>
                <span style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {r
                    ? `${r.total_trades ?? "?"} tr · ${(r.executed_at || "").slice(0, 10)}`
                    : "sin backtest"}
                </span>
                {r ? (
                  <>
                    <NormBadge s={s} />
                    <Cell value={num(r.total_return_pct, 1, "%")} tone={(r.total_return_pct ?? 0) >= 0 ? color.profit : color.loss} />
                    <Cell value={num(r.max_drawdown_pct, 1, "%")} tone={color.loss} />
                    <Cell value={num(r.win_rate, 1, "%")} />
                    <Cell value={num(r.profit_factor, 2)} />
                    <Cell value={num(r.sharpe_ratio, 2)} />
                  </>
                ) : (
                  <>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, color: color.warning, fontFamily: font.sans, whiteSpace: "nowrap" }}>
                      <CircleAlert style={{ width: 11, height: 11, strokeWidth: 1.5 }} />
                      no analizable
                    </span>
                    <Cell value="—" tone={color.textMuted} />
                    <Cell value="—" tone={color.textMuted} />
                    <Cell value="—" tone={color.textMuted} />
                    <Cell value="—" tone={color.textMuted} />
                    <Cell value="—" tone={color.textMuted} />
                  </>
                )}
                <div style={{ display: "flex", gap: 5, justifyContent: "flex-end", minWidth: 0, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
                  {onMove && (
                    <span style={{ display: "inline-flex", gap: 2, marginRight: 4 }}>
                      <MoveBtn dir={-1} disabled={idx === 0} onClick={() => onMove(s, -1, visibles)} />
                      <MoveBtn dir={1} disabled={idx === strategies.length - 1} onClick={() => onMove(s, 1, visibles)} />
                    </span>
                  )}
                  {actions?.(s)}
                </div>
              </div>

              {open && <StrategyDetail s={s} curve={curves[s.id]} />}
            </div>
          );
        })}
      </div>
      )}
    </section>
  );
}

/** Flecha para subir o bajar la fila un puesto. Discreta: mismo gris que el
 *  texto apagado, y se apaga del todo en los extremos. */
export function MoveBtn({ dir, disabled, onClick }: { dir: -1 | 1; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={dir < 0 ? "Subir" : "Bajar"}
      style={{
        width: 18,
        height: 18,
        padding: 0,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.sm,
        background: "transparent",
        color: color.textSecondary,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.25 : 1,
        fontSize: 9,
        lineHeight: 1,
        fontFamily: font.sans,
      }}
    >
      {dir < 0 ? "▲" : "▼"}
    </button>
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
        padding: "2px 7px",
        fontSize: 9.5,
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
