"use client";

import { useState } from "react";
import { ChevronRight, CircleAlert, Check } from "lucide-react";
import { color, font, radius } from "@/components/ui/tokens";
import type { RobustezStrategy } from "@/lib/api_robustez";
import { flattenConditions, formatUniverseRule, riskLines } from "@/lib/robustez/formatStrategy";
import { Help } from "./help";
import { RenameableName } from "./shared";

/**
 * Parametros de EJECUCION de la corrida guardada: capital, comisiones,
 * slippage, locates. No estan en la definicion de la estrategia (eso es el
 * "que" se opera); son el "como" se ejecuto, y sin ellos no se pueden
 * interpretar ni el retorno ni el resto de graficos.
 */
export function executionLines(bp: Record<string, any> | undefined): Array<[string, string, React.ReactNode?]> {
  if (!bp || !Object.keys(bp).length) return [];
  const n = (v: unknown, d = 2) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d));
  const out: Array<[string, string, React.ReactNode?]> = [];

  out.push([
    "Capital inicial",
    bp.init_cash != null ? `$${Number(bp.init_cash).toLocaleString("es-ES")}` : "—",
    "El capital con el que arranca la simulacion. Todos los porcentajes de retorno se miden sobre el.",
  ]);

  const isPct = String(bp.risk_type ?? "").toUpperCase() === "PERCENT";
  out.push([
    "Riesgo por trade",
    bp.risk_r != null ? (isPct ? `${n(bp.risk_r)} % del capital` : `$${n(bp.risk_r)} fijos`) : "—",
    isPct ? (
      <>
        Se arriesga ese porcentaje del capital <strong>vivo</strong>, asi que la posicion crece
        conforme crece la cuenta. Eso es lo que hace que la estrategia componga.
      </>
    ) : (
      "Cantidad fija en dolares por operacion, independiente del capital acumulado."
    ),
  ]);

  out.push([
    "Locates",
    bp.locates_cost != null ? `$${n(bp.locates_cost)} / 100 acc` : "—",
    <>
      Coste de alquilar las acciones para vender en corto. Se cobra por{" "}
      <strong>paquetes de 100</strong> y siempre hacia arriba: para 101 acciones se pagan 2 paquetes.
      Ademas se cobra <strong>una vez por ticker y dia</strong>, sobre el mayor tamaño que se llego a
      tener abierto esa sesion — no una vez por operacion.
    </>,
  ]);

  // El motor trata `slippage` como fraccion pese a que la UI del Backtester lo
  // titula "%". Aqui se enseña convertido, que es lo que de verdad se aplico.
  const slipPct = bp.slippage != null ? Number(bp.slippage) * 100 : null;
  out.push([
    "Slippage",
    slipPct != null ? `${slipPct.toFixed(3)} %` : "—",
    <>
      Cuanto se desvia el precio real de ejecucion respecto al de la vela, en entrada y en salida.
      <br />
      <br />
      Ojo: el campo del Backtester se titula &ldquo;Slippage (%)&rdquo; pero el simulador lo trata como
      una <strong>fraccion</strong>. El valor guardado es{" "}
      <code>{String(bp.slippage ?? 0)}</code>, que son {slipPct != null ? slipPct.toFixed(3) : "—"}%
      reales — cien veces mas de lo que sugiere la etiqueta.
    </>,
  ]);

  const feeType = String(bp.fee_type ?? "").toUpperCase();
  out.push([
    "Comisiones",
    bp.fees != null ? (feeType === "PERCENT" ? `${Number(bp.fees) * 100} % (frac. ${bp.fees})` : `$${n(bp.fees, 4)}`) : "—",
    "Comision del broker por operacion, aparte de los locates.",
  ]);

  if (bp.monthly_expenses) out.push(["Gastos fijos", `$${n(bp.monthly_expenses, 0)} / mes`]);
  if (bp.start_date || bp.end_date) out.push(["Periodo ejecutado", `${bp.start_date ?? "?"} → ${bp.end_date ?? "?"}`]);

  return out;
}

interface Props {
  strategies: RobustezStrategy[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loadingRunFor: string | null;
  /** Renombrado inline. Si se omite, el nombre se pinta sin lapiz. */
  onRename?: (s: RobustezStrategy, newName: string) => Promise<void>;
  /** Subir/bajar la fila (mismo orden manual que las listas del Portfolio). */
  onMove?: (s: RobustezStrategy, dir: -1 | 1, visibles: string[]) => void;
}

const num = (v: number | null | undefined, digits = 2, suffix = "") =>
  v == null || Number.isNaN(v) ? "—" : `${v.toFixed(digits)}${suffix}`;

/** Celda numerica de la fila: sin etiqueta (va UNA vez en la cabecera). */
function Cell({ value, tone }: { value: string; tone?: string }) {
  return (
    <span style={{ fontSize: 11.5, fontFamily: font.mono, color: tone || color.textHigh, textAlign: "right", whiteSpace: "nowrap" }}>
      {value}
    </span>
  );
}

/** Columnas de la fila y de la cabecera (14-sep-2026: filas de UNA linea de
 *  28 px, como el Baul y «En crudo» del Portfolio; antes eran de dos lineas
 *  con la etiqueta de cada metrica repetida en cada fila). */
const COLS = "14px minmax(180px, 1fr) 150px 64px 60px 52px 48px 56px 44px";

function HeadCell({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <span style={{ fontSize: 8.5, letterSpacing: "0.09em", textTransform: "uppercase", color: color.textMuted, fontFamily: font.sans, textAlign: right ? "right" : "left", whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

/** Flecha para subir o bajar la fila un puesto. */
function MoveBtn({ dir, disabled, onClick }: { dir: -1 | 1; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      disabled={disabled}
      title={dir < 0 ? "Subir" : "Bajar"}
      style={{
        width: 18, height: 18, padding: 0, border: `0.5px solid ${color.border}`, borderRadius: radius.sm,
        background: "transparent", color: color.textSecondary, cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.25 : 1, fontSize: 9, lineHeight: 1, fontFamily: font.sans,
      }}
    >
      {dir < 0 ? "▲" : "▼"}
    </button>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        color: color.copper,
        fontFamily: font.sans,
        marginBottom: 8,
      }}
    >
      {children}
    </div>
  );
}

export function ConditionList({ items }: { items: ReturnType<typeof flattenConditions> }) {
  if (!items.length) {
    return <div style={{ fontSize: 12, color: color.textMuted, fontFamily: font.sans }}>Sin condiciones</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {items.map((c, i) => (
        <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 8, paddingLeft: c.depth * 14 }}>
          <span
            style={{
              fontSize: 9,
              fontFamily: font.mono,
              color: color.textMuted,
              border: `0.5px solid ${color.border}`,
              borderRadius: radius.xs,
              padding: "1px 4px",
              minWidth: 30,
              textAlign: "center",
              flexShrink: 0,
            }}
          >
            {i === 0 ? "SI" : c.operator}
          </span>
          <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textPrimary }}>{c.text}</span>
        </div>
      ))}
    </div>
  );
}

export function KeyVals({ rows }: { rows: Array<[string, string, React.ReactNode?]> }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map(([k, v, help], i) => (
        <div key={`${k}-${i}`} style={{ display: "flex", gap: 8, fontSize: 12, alignItems: "baseline" }}>
          <span
            style={{
              color: color.textMuted,
              fontFamily: font.sans,
              minWidth: 104,
              flexShrink: 0,
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {k}
            {help && <Help title={k} width={340}>{help}</Help>}
          </span>
          <span style={{ color: color.textPrimary, fontFamily: font.mono }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function StrategyPicker({ strategies, selectedId, onSelect, loadingRunFor, onRename, onMove }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const ROW_H = 28;
  const visibles = strategies.map((x) => x.id);

  if (!strategies.length) {
    return (
      <div
        style={{
          padding: "28px 20px",
          textAlign: "center",
          fontFamily: font.sans,
          fontSize: 13,
          color: color.textMuted,
        }}
      >
        No hay estrategias guardadas. Guarda una desde el Backtester para analizarla aqui.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: COLS,
          columnGap: 10,
          alignItems: "center",
          padding: "4px 14px 4px 16px",
          borderBottom: `0.5px solid ${color.border}`,
        }}
      >
        <span />
        <HeadCell>Estrategia</HeadCell>
        <HeadCell>Corrida</HeadCell>
        <HeadCell right>Retorno</HeadCell>
        <HeadCell right>Max DD</HeadCell>
        <HeadCell right>Win</HeadCell>
        <HeadCell right>PF</HeadCell>
        <HeadCell right>Sharpe</HeadCell>
        <span />
      </div>
      {strategies.map((s, idx) => {
        const isExpanded = expandedId === s.id;
        const isSelected = selectedId === s.id;
        const hasRun = !!s.run;
        const def = (s.definition || {}) as Record<string, any>;
        const entry = flattenConditions(def.entry_logic?.root_condition);
        const exit = flattenConditions(def.exit_logic?.root_condition);
        const uni = (def.universe_filters?.rules || []) as Record<string, any>[];
        const risk = riskLines(def.risk_management);
        const windows = (def.entry_logic?.entry_time_windows || []) as Record<string, any>[];
        const exec = executionLines(s.run?.backtest_params as Record<string, any> | undefined);

        return (
          <div key={s.id} style={{ borderTop: idx === 0 ? "none" : `0.5px solid ${color.border}` }}>
            {/* Cabecera clicable */}
            <div
              role="button"
              tabIndex={0}
              aria-expanded={isExpanded}
              onClick={() => {
                setExpandedId(isExpanded ? null : s.id);
                if (hasRun) onSelect(s.id);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpandedId(isExpanded ? null : s.id);
                  if (hasRun) onSelect(s.id);
                }
              }}
              style={{
                display: "grid",
                gridTemplateColumns: COLS,
                columnGap: 10,
                alignItems: "center",
                height: ROW_H,
                padding: "0 14px",
                cursor: "pointer",
                background: isSelected ? color.bgElevated : "transparent",
                borderLeft: `2px solid ${isSelected ? color.copper : "transparent"}`,
                transition: "background 150ms",
              }}
              onMouseEnter={(e) => {
                if (!isSelected) e.currentTarget.style.background = color.surfaceHover;
              }}
              onMouseLeave={(e) => {
                if (!isSelected) e.currentTarget.style.background = "transparent";
              }}
            >
              <ChevronRight
                style={{
                  width: 12,
                  height: 12,
                  strokeWidth: 1.5,
                  color: color.textMuted,
                  transform: isExpanded ? "rotate(90deg)" : "none",
                  transition: "transform 150ms",
                }}
              />

              <div style={{ minWidth: 0, display: "flex", alignItems: "center", gap: 7 }}>
                {isSelected && <Check style={{ width: 12, height: 12, color: color.copper, flexShrink: 0 }} />}
                {onRename ? (
                  <RenameableName
                    name={s.name || "Sin nombre"}
                    onRename={(n) => onRename(s, n)}
                    textStyle={{ fontSize: 12, color: color.textHigh, minWidth: 0 }}
                  />
                ) : (
                  <span style={{ fontSize: 12, fontFamily: font.sans, color: color.textHigh, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.name || "Sin nombre"}
                  </span>
                )}
                {loadingRunFor === s.id && (
                  <span style={{ fontSize: 10, color: color.copper, fontFamily: font.sans, flexShrink: 0 }}>cargando…</span>
                )}
              </div>

              <span style={{ fontSize: 10.5, fontFamily: font.mono, color: color.textMuted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {hasRun ? `${s.run!.total_trades ?? 0} tr · ${(s.run!.executed_at || "").slice(0, 10)}` : "sin backtest"}
              </span>

              {hasRun ? (
                <>
                  <Cell value={num(s.run!.total_return_pct, 1, "%")} tone={(s.run!.total_return_pct ?? 0) >= 0 ? color.profit : color.loss} />
                  <Cell value={num(s.run!.max_drawdown_pct, 1, "%")} tone={color.loss} />
                  <Cell value={num(s.run!.win_rate, 1, "%")} />
                  <Cell value={num(s.run!.profit_factor, 2)} />
                  <Cell value={num(s.run!.sharpe_ratio, 2)} />
                </>
              ) : (
                <>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: color.warning, fontSize: 10, fontFamily: font.sans, whiteSpace: "nowrap", gridColumn: "span 5" }}>
                    <CircleAlert style={{ width: 11, height: 11, strokeWidth: 1.5 }} />
                    no analizable
                  </span>
                </>
              )}

              <span style={{ display: "inline-flex", gap: 2, justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
                {onMove && (
                  <>
                    <MoveBtn dir={-1} disabled={idx === 0} onClick={() => onMove(s, -1, visibles)} />
                    <MoveBtn dir={1} disabled={idx === strategies.length - 1} onClick={() => onMove(s, 1, visibles)} />
                  </>
                )}
              </span>
            </div>

            {/* Desplegable: TODAS las condiciones */}
            {isExpanded && (
              <div
                style={{
                  padding: "16px 20px 20px 44px",
                  background: color.bgBase,
                  borderTop: `0.5px solid ${color.border}`,
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                  gap: 24,
                }}
              >
                <div>
                  <SectionTitle>Universo</SectionTitle>
                  <KeyVals
                    rows={[
                      ["Sesgo", String(def.bias ?? "—")],
                      ["Dia", String(def.apply_day ?? "—")],
                      ["Rango", `${def.universe_filters?.date_from ?? "?"} → ${def.universe_filters?.date_to ?? "?"}`],
                      ["Sesiones", (def.market_sessions || []).join(", ") || "—"],
                      ...uni.map((r) => ["Filtro", formatUniverseRule(r)] as [string, string]),
                    ]}
                  />
                </div>

                <div>
                  <SectionTitle>Entrada</SectionTitle>
                  <ConditionList items={entry} />
                  {windows.length > 0 && (
                    <div style={{ marginTop: 10 }}>
                      <KeyVals
                        rows={windows.map((w) => ["Ventana", `${w.from_time} — ${w.to_time}`] as [string, string])}
                      />
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
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
