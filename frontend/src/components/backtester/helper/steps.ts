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
  | "builder";
export type HelperFill = "dataset" | "strategy" | "config";

export interface HelperStep {
  id: string;
  /** Estado que la página debe tener ANTES de resaltar este paso. */
  enter: { mode: HelperMode; fill?: HelperFill };
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

  // 3 — Constructor libre · dirección y sesión
  //
  // Del 2026-08-31: estos pasos iban por el Wizard, que se ha borrado. Se
  // rehicieron sobre el constructor libre usando las anclas que este YA tenía
  // (st-bias, st-sessions, st-entry, st-risk). El tour no pierde ningún paso.
  {
    id: "bias",
    enter: { mode: "builder", fill: "strategy" },
    element: '[data-helper="st-bias"]',
    popover: {
      title: "1 · Dirección y día",
      description:
        "Toda estrategia son tres bloques: <strong>qué días miro · cuándo entro · cuánto " +
        "arriesgo</strong>. Empezamos por la dirección: voy <strong>CORTO</strong> y opero " +
        "<strong>solo el día del gap</strong> —vamos a probar qué pasa cuando el precio " +
        "atraviesa el VWAP hacia abajo—. Te lo dejo ya marcado.",
      side: "right",
      align: "start",
    },
  },

  // 4 — Constructor libre · sesión de ejecución
  {
    id: "sessions",
    enter: { mode: "builder" },
    element: '[data-helper="st-sessions"]',
    popover: {
      title: "2 · En qué sesión",
      description:
        "El <strong>horario de mercado (RTH)</strong>, que es donde hay volumen de verdad. " +
        "Aquí también puedes operar el premercado o el after, o inventarte tu propia franja.",
      side: "right",
      align: "start",
    },
  },

  // 5 — Constructor libre · lógica de entrada
  {
    id: "entry",
    enter: { mode: "builder" },
    element: '[data-helper="st-entry"]',
    popover: {
      title: "3 · La entrada (la chicha)",
      description:
        "Quiero entrar cuando el cierre de la vela (<strong>Close</strong>) <strong>cruza por " +
        "debajo del VWAP</strong>. Puedes encadenar condiciones con AND/OR, agruparlas, y medir " +
        "<em>distancia</em> a otra variable para sistemas más finos. Y solo acepto entradas en la " +
        "ventana de <strong>09:30 a 11:00</strong>, cuando hay más volatilidad.",
      side: "right",
      align: "start",
    },
  },

  // 6 — Constructor libre · riesgo
  {
    id: "risk",
    enter: { mode: "builder" },
    element: '[data-helper="st-risk"]',
    popover: {
      title: "4 · El riesgo, simple",
      description:
        "La salida la dejo <strong>sin condición por indicador</strong>: salgo por stop o por la " +
        "hora. Pongo un <strong>stop del 20 %</strong> y permito un <strong>máximo de 2 " +
        "reentradas</strong> si la cosa va en contra. Mi premisa: cuanto más simple, <em>mejor</em>. " +
        "Debajo tienes piramidación, take profit, trailing y el límite de pérdida diaria.",
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
