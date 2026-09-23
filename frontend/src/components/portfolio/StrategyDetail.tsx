"use client";

// Desplegable de una estrategia: TODAS sus condiciones (universo, entrada,
// salida, riesgo), con que se corrio su backtest y el minigrafico de los
// ultimos 6 meses. Es el mismo bloque que abre cada fila del Baul; vive
// aparte para que la vista «En crudo» del Portfolio lo despliegue tambien
// bajo cada fila (pedido el 14-sep-2026).

import React from "react";
import { color, font } from "@/components/ui/tokens";
import {
  ConditionList,
  KeyVals,
  SectionTitle,
  executionLines,
} from "@/components/robustez/StrategyPicker";
import { flattenConditions, formatUniverseRule, riskLines } from "@/lib/robustez/formatStrategy";
import { autoTags } from "@/lib/strategyTags";
import { TagEditor } from "@/components/ui/TagEditor";
import type { PortfolioStrategy } from "@/lib/api_portfolio_lab";
import { Sparkline, type CurveState } from "./StrategyShelf";

export function StrategyDetail({
  s,
  curve,
  paddingLeft = 37,
  onTags,
  tagSuggestions = [],
}: {
  s: PortfolioStrategy;
  /** Curva de equity de la ultima corrida; `undefined` = aun no pedida. */
  curve?: CurveState;
  paddingLeft?: number;
  /** Guardar las etiquetas manuales (metadato). Opcional: donde no se pasa,
   *  el desplegable solo enseña los tags sin editarlos. */
  onTags?: (s: PortfolioStrategy, tags: string[]) => Promise<void>;
  /** Tags que ya existen en otras estrategias, para sugerirlos. */
  tagSuggestions?: string[];
}) {
  const r = s.run;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const def = (s.definition || {}) as Record<string, any>;
  const entry = flattenConditions(def.entry_logic?.root_condition);
  const exit = flattenConditions(def.exit_logic?.root_condition);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const uni = (def.universe_filters?.rules || []) as Record<string, any>[];
  const risk = riskLines(def.risk_management);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const windows = (def.entry_logic?.entry_time_windows || []) as Record<string, any>[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const exec = executionLines(r?.backtest_params as Record<string, any> | undefined);

  return (
    <div style={{ background: color.bgBase, padding: `14px 18px 16px ${paddingLeft}px` }}>
      {s.description && (
        <p style={{ margin: "0 0 12px", fontSize: 11.5, fontFamily: font.sans, color: color.textSecondary, lineHeight: 1.55, maxWidth: 720 }}>
          {s.description}
        </p>
      )}
      {onTags && (
        <div style={{ margin: "0 0 14px" }}>
          <SectionTitle>Etiquetas</SectionTitle>
          <TagEditor
            tags={s.tags || []}
            autoTags={autoTags(s.definition)}
            suggestions={tagSuggestions}
            onSave={(next) => onTags(s, next)}
          />
        </div>
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
}
