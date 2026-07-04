// Guion (storyboard) del tour guiado del backtester — 9 pasos narrados en
// primera persona por Edgie (el asistente de Edgecute). El tour recorre el
// WIZARD con un ejemplo ya pre-rellenado (no hace falta que el usuario
// construya nada) y termina en el panel de config, dejando el backtest de
// ejemplo REFLEJADO y listo para que el usuario lo guarde y lo corra.
// Ver docs/helper-backtester/PLAN_HELPER_WIZARD_v2.md. La `description` admite
// HTML simple (driver.js la inyecta como innerHTML).

import type { Side, Alignment } from "driver.js";

export type HelperMode =
  | "config"
  | "dataset"
  | "builder"
  | "builder_choice"
  | "wizard";
export type HelperFill = "dataset" | "strategy" | "config";
/** Claves de los sub-pasos internos del Wizard (deben coincidir con STEPS en
 *  WizardStrategyBuilder.tsx). */
export type WizardStepKey =
  | "universo"
  | "bias"
  | "apply_day"
  | "market_sessions"
  | "entry"
  | "exit"
  | "risk"
  | "summary";

export interface HelperStep {
  id: string;
  /** Estado que la página debe tener ANTES de resaltar este paso. */
  enter: { mode: HelperMode; fill?: HelperFill; wizardStep?: WizardStepKey };
  /** Elemento a resaltar: selector CSS (o función que lo devuelve). */
  element?: string | (() => Element);
  popover: {
    title: string;
    description: string;
    side?: Side;
    align?: Alignment;
  };
}

export const HELPER_STEPS: HelperStep[] = [
  // 1 — Intro (popover centrado)
  {
    id: "intro",
    enter: { mode: "config" },
    popover: {
      title: "¡Hola! Soy Edgie 👋",
      description:
        "Te voy a montar tu primer backtest conmigo, paso a paso. " +
        "<strong>Lo que vale, cuesta</strong>: un buen backtest tiene su miga, así que te dejo " +
        "un ejemplo ya armado —<em>qué pasa si el precio cae por debajo del VWAP en horario de " +
        "mercado</em>— y te lo voy contando. Dale a <strong>Entendido</strong> cuando lo pilles " +
        "(o <em>Saltar</em> si ya vas sobrado).",
    },
  },

  // 2 — Panel principal
  {
    id: "panel",
    enter: { mode: "config" },
    element: '[data-helper="panel-root"]',
    popover: {
      title: "Tu panel de mando",
      description:
        "Desde aquí cargas estrategias que ya tengas guardadas, las configuras o creas una " +
        "nueva. Antes de simular, acuérdate de fijar <strong>capital, comisiones y riesgo</strong>. " +
        "Vamos a crear una <strong>nueva estrategia</strong>.",
      side: "right",
      align: "start",
    },
  },

  // 3 — Selector de modo (Wizard vs libre)
  {
    id: "mode",
    enter: { mode: "builder_choice" },
    element: '[data-helper="mode-selector"]',
    popover: {
      title: "¿Wizard o modo libre?",
      description:
        "Puedes montarla pieza a pieza con el <strong>Wizard</strong>, con componentes básicos, " +
        "o a pelo en <strong>modo libre</strong> con todas las opciones avanzadas. Como esta es " +
        "simple, vamos por la línea fácil: el <strong>Wizard</strong>. Tranquilo, " +
        "<em>no vas a necesitar programar</em>.",
      side: "right",
      align: "start",
    },
  },

  // 4 — Wizard · Universo (carga el ejemplo y entra al wizard)
  {
    id: "universo",
    enter: { mode: "wizard", fill: "strategy", wizardStep: "universo" },
    element: '[data-helper="wiz-universo"]',
    popover: {
      title: "1 · El Universo",
      description:
        "Toda estrategia son tres bloques: <strong>universo · parámetros · riesgo</strong>. " +
        "Empezamos por el universo: qué días miro. Para el ejemplo pido solo gaps bestiales " +
        "(<strong>PM High Gap ≥ 70 %</strong>). Cuantos más filtros, más fino (y más pequeño) " +
        "el universo.",
      side: "right",
      align: "start",
    },
  },

  // 5 — Wizard · Parámetros (dirección + día + sesión, ya marcados)
  {
    id: "params",
    enter: { mode: "wizard", wizardStep: "bias" },
    element: '[data-helper="wiz-bias"]',
    popover: {
      title: "2 · Parámetros del sistema",
      description:
        "Ahora la dirección y el cuándo. Voy <strong>CORTO</strong>, opero <strong>solo el día " +
        "del gap</strong> y en <strong>horario de mercado (RTH)</strong> —porque vamos a probar " +
        "qué pasa cuando el precio atraviesa el VWAP—. Te lo dejo ya marcado.",
      side: "right",
      align: "start",
    },
  },

  // 6 — Wizard · Entrada (condición + ventana horaria, en chip)
  {
    id: "entry",
    enter: { mode: "wizard", wizardStep: "entry" },
    element: '[data-helper="wiz-entry"]',
    popover: {
      title: "2 · La entrada (la chicha)",
      description:
        "Quiero entrar cuando el cierre de la vela (<strong>Close</strong>) <strong>cruza por " +
        "debajo del VWAP</strong>. El Wizard también permite medir <em>distancia</em> a otra " +
        "variable para sistemas más finos, pero aquí basta con comparar. Y solo acepto entradas " +
        "en la ventana de <strong>09:30 a 11:00</strong>, cuando hay más volatilidad.",
      side: "right",
      align: "start",
    },
  },

  // 7 — Wizard · Riesgo (salida simple + stop + reentradas)
  {
    id: "risk",
    enter: { mode: "wizard", wizardStep: "risk" },
    element: '[data-helper="wiz-risk"]',
    popover: {
      title: "3 · El riesgo, simple",
      description:
        "La salida la dejo <strong>sin condición por indicador</strong>: salgo por stop o por la " +
        "hora. Pongo un <strong>stop del 20 %</strong> y permito un <strong>máximo de 2 " +
        "reentradas</strong> si la cosa va en contra. Mi premisa: cuanto más simple, <em>mejor</em>.",
      side: "right",
      align: "start",
    },
  },

  // 8 — Wizard · Resumen (la estrategia montada)
  {
    id: "summary",
    enter: { mode: "wizard", wizardStep: "summary" },
    element: '[data-helper="wiz-summary"]',
    popover: {
      title: "¡Y aquí lo tienes!",
      description:
        "El resumen de toda tu estrategia, montada de una pieza. Repásala… y vamos a cerrar el " +
        "círculo con los ajustes del backtest.",
      side: "right",
      align: "start",
    },
  },

  // 9 — Cierre en config: capital + IS/OOS, ejemplo reflejado y listo para correr
  {
    id: "close",
    enter: { mode: "config", fill: "config" },
    element: '[data-helper="cfg-capital"]',
    popover: {
      title: "El último ajuste: IS / OOS",
      description:
        "Aquí pones <strong>capital, comisiones</strong> y el <strong>reparto IS/OOS</strong> " +
        "—te recomiendo un <strong>OOS del 20 %</strong> para cazar el sobreajuste—. Te dejo el " +
        "ejemplo entero reflejado: cuando guardes y selecciones tu estrategia arriba, el botón de " +
        "correr se enciende y lo pulsas tú. ¿Repetir el tour? Me tienes en <em>¿Cómo funciona?</em>. — Edgie",
      side: "right",
      align: "start",
    },
  },
];
