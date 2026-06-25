// Guion (storyboard) del tour guiado del backtester — 9 pasos agrupados,
// narrados en primera persona por Edgie (el asistente de Edgecute).
// Ver docs/helper-backtester/PRD_HELPER_BACKTESTER.md §4. La `description` admite
// HTML simple (driver.js la inyecta como innerHTML).

import type { Side, Alignment } from "driver.js";

export type HelperMode = "config" | "dataset" | "builder";
export type HelperFill = "dataset" | "strategy" | "config";

export interface HelperStep {
  id: string;
  /** Estado que la página debe tener ANTES de resaltar este paso. */
  enter: { mode: HelperMode; fill?: HelperFill };
  /** Elemento a resaltar: selector CSS o función que lo devuelve (para anclas
   *  cuyo wrapper es `display:contents` y hay que apuntar al hijo real). */
  element?: string | (() => Element);
  popover: {
    title: string;
    description: string;
    side?: Side;
    align?: Alignment;
  };
}

/** Devuelve el primer hijo real de un wrapper `display:contents` (que no tiene
 *  caja propia y por tanto no se puede resaltar directamente). */
const childOf = (selector: string) => (): Element => {
  const wrapper = document.querySelector(selector);
  return (wrapper?.firstElementChild ?? wrapper ?? document.body) as Element;
};

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
        "un ejemplo ya armado —un <em>fade de gap parabólico</em>— y te lo voy contando. " +
        "Dale a <strong>Entendido</strong> cuando lo pilles (o <em>Saltar</em> si ya vas sobrado).",
    },
  },

  // 2 — El mapa: las 3 piezas
  {
    id: "map",
    enter: { mode: "config" },
    element: '[data-helper="panel-root"]',
    popover: {
      title: "Lo monto en 3 piezas",
      description:
        "Yo siempre pienso un backtest en tres bloques: el <strong>Universo</strong> (qué días miro), " +
        "la <strong>Estrategia</strong> (cuándo entro y salgo) y los <strong>Ajustes</strong> " +
        "(capital, riesgo y comisiones). Te los enseño uno a uno desde este panel.",
      side: "right",
      align: "start",
    },
  },

  // 3 — Universo (Dataset)
  {
    id: "universe",
    enter: { mode: "dataset", fill: "dataset" },
    element: '[data-helper="ds-gapday"]',
    popover: {
      title: "1 · El Universo",
      description:
        "Aquí te filtro los días que me interesan. Para este ejemplo solo quiero gaps bestiales: " +
        "<strong>PM High Gap ≥ 70%</strong>. Cuantos más filtros le metas, más fino te queda el " +
        "universo (y más pequeño).",
      side: "right",
      align: "start",
    },
  },

  // 4 — Estrategia: dirección y día
  {
    id: "strategy-bias",
    enter: { mode: "builder", fill: "strategy" },
    element: '[data-helper="st-bias"]',
    popover: {
      title: "2 · La Estrategia",
      description:
        "Te pongo la dirección: voy <strong>CORTO</strong> el <strong>día del gap</strong>. " +
        "La idea es hacer un <em>fade</em>: apostar a que ese pico parabólico se desinfla.",
      side: "right",
      align: "start",
    },
  },

  // 5 — Estrategia: entrada
  {
    id: "strategy-entry",
    enter: { mode: "builder" },
    element: childOf('[data-helper="st-entry"]'),
    popover: {
      title: "2 · Mi entrada",
      description:
        "Entro cuando veo una <strong>vela de 1 minuto roja por encima del VWAP</strong> " +
        "(cierre &lt; apertura y el precio aún sobre el VWAP). Para mí es la señal de que la " +
        "subida se está quedando sin gasolina.",
      side: "right",
      align: "start",
    },
  },

  // 6 — Estrategia: sesión / salida a las 11:00
  {
    id: "strategy-sessions",
    enter: { mode: "builder" },
    element: '[data-helper="st-sessions"]',
    popover: {
      title: "2 · Cuándo cierro",
      description:
        "Este es tu “take profit por tiempo”: te lo dejo con <strong>Horas personalizadas " +
        "09:30 → 11:00 ET</strong>. Solo opero en esa ventana, así que <strong>cierro a las " +
        "11:00 de Nueva York</strong> sí o sí.",
      side: "right",
      align: "start",
    },
  },

  // 7 — Estrategia: riesgo
  {
    id: "strategy-risk",
    enter: { mode: "builder" },
    element: childOf('[data-helper="st-risk"]'),
    popover: {
      title: "2 · Mi riesgo",
      description:
        "Te pongo el stop al <strong>50% del precio de entrada</strong> (estos squeezes pegan fuerte) " +
        "y <strong>sin reentradas</strong>. No uso take-profit por precio: salgo por stop o por la hora.",
      side: "right",
      align: "start",
    },
  },

  // 8 — Ajustes (capital + riesgo)
  {
    id: "config-capital",
    enter: { mode: "config", fill: "config" },
    element: '[data-helper="cfg-capital"]',
    popover: {
      title: "3 · Los Ajustes",
      description:
        "Cierro con la pasta: <strong>10.000$</strong> de capital y riesgo <strong>fijo de 100$</strong> " +
        "por operación (tu 1R). Justo debajo tienes comisiones, slippage y el reparto IS/OOS para " +
        "cazar el sobreajuste.",
      side: "right",
      align: "start",
    },
  },

  // 9 — Ejecutar
  {
    id: "run",
    enter: { mode: "config" },
    element: '[data-helper="cfg-run"]',
    popover: {
      title: "¡Listo para correr!",
      description:
        "Y ya está. Cuando tengas tu <strong>dataset y tu estrategia guardados y seleccionados</strong> " +
        "arriba, este botón se enciende y lo pulsas tú. ¿Quieres repetirlo? Me tienes en " +
        "<em>¿Cómo funciona?</em> siempre que quieras. — Edgie",
      side: "right",
      align: "start",
    },
  },
];
