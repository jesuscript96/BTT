// Fuente de verdad del backtest de EJEMPLO que muestra el tour guiado del
// backtester (ver docs/helper-backtester/PRD_HELPER_BACKTESTER.md, §3).
//
// "Fade de gap parabólico (+70%)" — un short clásico de small-caps:
//   · Universo: solo días con PMH Gap ≥ 70%.
//   · Estrategia: corto el día del gap; entras con una vela M1 roja por encima
//     del VWAP; stop al 50% del precio de entrada; sin reentradas; la "salida a
//     las 11:00 NY" se codifica como sesión personalizada 09:30 → 11:00 ET
//     (el builder no tiene salida por hora de reloj).
//   · Ajustes: 10.000$ de capital, riesgo fijo de 100$ (1R).
//
// Todos los valores usan los enums reales de @/types/strategy para que
// TypeScript valide el ejemplo (cero strings inventados).

import {
  IndicatorType,
  Comparator,
  Timeframe,
  RiskType,
  TakeProfitMode,
} from "@/types/strategy";
import type { Draft } from "@/components/backtester/InlineStrategyBuilder";

// Mismas constantes de rango que InlineDatasetBuilder.tsx:60-64
const MAX_DATE = new Date().toISOString().split("T")[0];
const TWO_YEARS_AGO = new Date(
  new Date().setFullYear(new Date().getFullYear() - 2)
).toISOString().split("T")[0];

/** Payload del evento `fill-dataset-builder` (forma interna del InlineDatasetBuilder). */
export interface ExampleDataset {
  name: string;
  dateFrom: string;
  dateTo: string;
  values: Record<string, Record<string, { op: string; val1: string; val2: string }>>;
  includedConditions: Array<{
    section: "gap_day" | "gap_plus_1_day" | "gap_plus_2_day";
    paramKey: string;
    label: string;
    op: string;
    val1: number;
    val2?: number;
    unit: string;
  }>;
}

export const EXAMPLE_DATASET: ExampleDataset = {
  name: "Ejemplo · Gap PMH ≥ 70%",
  dateFrom: TWO_YEARS_AGO,
  dateTo: MAX_DATE,
  values: {
    gap_day: { pmh_gap_pct: { op: ">=", val1: "70", val2: "" } },
    gap_plus_1_day: {},
    gap_plus_2_day: {},
  },
  includedConditions: [
    { section: "gap_day", paramKey: "pmh_gap_pct", label: "PM High Gap", op: ">=", val1: 70, unit: "%" },
  ],
};

/** Borrador de estrategia, precargado vía `setBuilderDraft` → `initialStrategy`. */
export const EXAMPLE_STRATEGY: Draft = {
  id: "draft",
  name: "Ejemplo · Fade gap +70%",
  bias: "short",
  apply_day: "gap_day",
  postgap_preconditions: [],
  entry_logic: {
    timeframe: Timeframe.M1,
    root_condition: {
      type: "group",
      operator: "AND",
      conditions: [
        // Vela M1 roja: el cierre queda por debajo de su apertura.
        {
          type: "indicator_comparison",
          source: { name: IndicatorType.BAR_CLOSE },
          comparator: Comparator.LT,
          target: { name: IndicatorType.BAR_OPEN },
          timeframe: Timeframe.M1,
        },
        // ...y por encima del VWAP (rechazo en extensión).
        {
          type: "indicator_comparison",
          source: { name: IndicatorType.BAR_CLOSE },
          comparator: Comparator.GT,
          target: { name: IndicatorType.VWAP },
          timeframe: Timeframe.M1,
        },
      ],
    },
    entry_time_windows: [],
  },
  exit_logic: {
    // Sin condición de salida por indicador: sale por el stop (50%) o por el
    // fin de la sesión personalizada (11:00).
    timeframe: Timeframe.M1,
    root_condition: { type: "group", operator: "AND", conditions: [] },
  },
  risk_management: {
    use_hard_stop: true,
    hard_stop: { type: RiskType.PERCENTAGE, value: 50 }, // SL = 50% del precio de entrada
    use_take_profit: false, // el "TP" es la salida por hora (sesión 09:30–11:00)
    take_profit_mode: TakeProfitMode.FULL,
    take_profit: { type: RiskType.PERCENTAGE, value: 6 }, // ignorado (use_take_profit=false)
    partial_take_profits: [],
    trailing_stop: { active: false, type: "Percentage", buffer_pct: 0.5 },
    accept_reentries: false, // sin reentradas
    max_reentries: -1,
    size_by_sl: false,
    swing_option: { active: false, target_day: "gap_1_day" },
  },
  market_sessions: ["custom"],
  custom_start_time: "09:30",
  custom_end_time: "11:00", // ← fuerza la salida a las 11:00 NY
  dataset_id: undefined,
  universe_filters: undefined,
  created_at: new Date().toISOString(),
};

/** Payload del evento `fill-backtest-form` (forma interna del BacktestPanel). */
export interface ExampleConfig {
  initCash: number;
  riskType: "FIXED" | "PERCENT" | "FIXED_RATIO";
  riskR: number;
  feeType: "PERCENT" | "FLAT";
  fees: number;
  slippage: number;
  marketSessions: string[];
  customStartTime: string;
  customEndTime: string;
  isPercent: number;
}

export const EXAMPLE_CONFIG: ExampleConfig = {
  initCash: 10000,
  riskType: "FIXED",
  riskR: 100, // riesgo fijo de 100$ (1R)
  feeType: "PERCENT",
  fees: 0.01,
  slippage: 0.01,
  marketSessions: ["custom"],
  customStartTime: "09:30",
  customEndTime: "11:00",
  isPercent: 100,
};

// Nombres de los eventos del contrato "rellenar formulario" (revividos por el helper).
export const FILL_DATASET_EVENT = "fill-dataset-builder";
export const FILL_CONFIG_EVENT = "fill-backtest-form";

// ── Limpieza al salir del tour ───────────────────────────────────
// El tour es una demostración: al cerrarse NO debe dejar el ejemplo metido en
// los formularios del usuario. Estos payloads devuelven los componentes
// "siempre montados" (dataset builder y panel de config) a sus valores por
// defecto. La estrategia no necesita reset aquí: se restaura el `builderDraft`
// previo desde la página (el builder se desmonta al volver a 'config').

/** Vacía el Dataset Builder (vuelve a su estado inicial visible). */
export const RESET_DATASET = {
  name: "Nuevo Dataset",
  values: { gap_day: {}, gap_plus_1_day: {}, gap_plus_2_day: {} },
  includedConditions: [],
};

/** Restablece en el panel de config lo único que el ejemplo cambia respecto al
 *  default y que además se filtra a sessionStorage / a nuevas estrategias: la
 *  sesión de mercado (vuelve a RTH). */
export const RESET_CONFIG = {
  marketSessions: ["rth"],
  customStartTime: "09:30",
  customEndTime: "16:00",
};
