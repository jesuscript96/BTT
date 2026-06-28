// Fuente de verdad del backtest de EJEMPLO que muestra el tour guiado del
// backtester (ver docs/helper-backtester/PRD_HELPER_BACKTESTER.md, §3).
//
// "Fade de gap parabólico (+70%)" — un short clásico de small-caps:
//   · Universo: solo días con PMH Gap ≥ 70% (va en universe_filters de la
//     estrategia, para que el Wizard lo pinte en su paso "Universo").
//   · Estrategia: corto el día del gap, en sesión RTH; entras cuando el Close
//     M1 CRUZA POR DEBAJO del VWAP, solo en la ventana 09:30–11:00; stop al 20%
//     del precio de entrada; hasta 2 reentradas.
//   · Ajustes: 10.000$ de capital, riesgo fijo de 100$ (1R), OOS 20%.
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
        // Entrada corta: el Close de la vela M1 CRUZA POR DEBAJO del VWAP.
        {
          type: "indicator_comparison",
          source: { name: IndicatorType.BAR_CLOSE },
          comparator: Comparator.CROSSES_BELOW,
          target: { name: IndicatorType.VWAP },
          timeframe: Timeframe.M1,
        },
      ],
    },
    // Solo se aceptan entradas en la ventana volátil de apertura (09:30–11:00).
    entry_time_windows: [{ from_time: "09:30", to_time: "11:00" }],
  },
  exit_logic: {
    // Sin condición de salida por indicador: sale por el stop (50%) o por el
    // fin de la sesión personalizada (11:00).
    timeframe: Timeframe.M1,
    root_condition: { type: "group", operator: "AND", conditions: [] },
  },
  risk_management: {
    use_hard_stop: true,
    hard_stop: { type: RiskType.PERCENTAGE, value: 20 }, // SL = 20% del precio de entrada
    use_take_profit: false, // sin TP por precio: salida por stop o fin de sesión
    take_profit_mode: TakeProfitMode.FULL,
    take_profit: { type: RiskType.PERCENTAGE, value: 6 }, // ignorado (use_take_profit=false)
    partial_take_profits: [],
    trailing_stop: { active: false, type: "Percentage", buffer_pct: 0.5 },
    accept_reentries: true, // permite reentrar si la operación va en contra
    max_reentries: 2, // máximo 2 reentradas
    size_by_sl: false,
    swing_option: { active: false, target_day: "gap_1_day" },
  },
  market_sessions: ["rth"], // opera en horario de mercado (Regular Hours)
  custom_start_time: "09:30",
  custom_end_time: "16:00",
  dataset_id: undefined,
  // Universo dentro de la propia estrategia (el Wizard lo pinta en su paso 1):
  // solo días con PM High Gap ≥ 70%.
  universe_filters: {
    date_from: TWO_YEARS_AGO,
    date_to: MAX_DATE,
    rules: [
      { metric: "PMH Gap %", operator: "GREATER_THAN_OR_EQUAL", valueType: "static", value: "70" },
    ],
  },
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
  marketSessions: ["rth"],
  customStartTime: "09:30",
  customEndTime: "16:00",
  isPercent: 80, // reparto 80% In-Sample / 20% Out-of-Sample
};

// Nombres de los eventos del contrato "rellenar formulario" (revividos por el helper).
export const FILL_DATASET_EVENT = "fill-dataset-builder";
export const FILL_CONFIG_EVENT = "fill-backtest-form";
/** Posiciona el Wizard en un sub-paso concreto (lo escucha WizardStrategyBuilder). */
export const WIZARD_SET_STEP_EVENT = "wizard-set-step";

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
