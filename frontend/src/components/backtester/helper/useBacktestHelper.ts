// Hook que orquesta el tour guiado del backtester con driver.js.
// Ver docs/helper-backtester/PRD_HELPER_BACKTESTER.md §5.3.
//
// La página le pasa un "controller" con los setters que necesita (cambiar de
// modo, precargar la estrategia de ejemplo, disparar los rellenos de
// config/dataset y marcar el tour como activo). El hook se encarga de:
//   · construir la instancia de driver.js con el tema, el contador y el botón Saltar;
//   · la coreografía: antes de resaltar un paso que vive en un drawer, abre ese
//     drawer y lo rellena, esperando a que termine la animación (300 ms);
//   · la gate de "primera visita" (localStorage) y el re-lanzamiento.

"use client";

import { useCallback, useEffect, useRef } from "react";
import { driver, type Driver, type Config } from "driver.js";
import "driver.js/dist/driver.css";
import "./helper.css";
import { HELPER_STEPS, type HelperMode, type HelperStep } from "./steps";

const SEEN_KEY = "edgecute:bt-helper:v1:seen";
/** ms de margen para que termine la transición del drawer (CSS 300ms). */
const TRANSITION_MS = 380;
/** ms para montar el Wizard y que cargue la estrategia de ejemplo. */
const WIZARD_MOUNT_MS = 520;
/** ms para que el contenido de un sub-paso del Wizard se pinte. */
const STEP_SWAP_MS = 260;

/** Avatar de Edgie — mismo robot que el botón flotante del ChatBot
 *  (RobotAvatar en ChatBot.tsx), en su variante "encendida" (cobre). */
const EDGIE_AVATAR_SVG =
  '<svg width="22" height="22" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">' +
  '<rect x="6" y="9" width="20" height="15" rx="3.5" fill="#1C1E21" stroke="var(--color-ec-copper-bright)" stroke-width="1.5"/>' +
  '<rect x="3" y="14" width="3" height="5" rx="1.5" fill="#2C2F33" stroke="var(--color-ec-copper)" stroke-width="1"/>' +
  '<rect x="26" y="14" width="3" height="5" rx="1.5" fill="#2C2F33" stroke="var(--color-ec-copper)" stroke-width="1"/>' +
  '<path d="M16 9V5M16 5C17.1046 5 18 4.10457 18 3C18 1.89543 17.1046 1 16 1C14.8954 1 14 1.89543 14 3C14 4.10457 14.8954 5 16 5Z" fill="var(--color-ec-copper)"/>' +
  '<circle cx="11" cy="15" r="2.5" fill="var(--color-ec-copper-bright)"/>' +
  '<circle cx="21" cy="15" r="2.5" fill="var(--color-ec-copper-bright)"/>' +
  '<rect x="11" y="19" width="10" height="2" rx="1" fill="#2C2F33" stroke="var(--color-ec-copper)" stroke-width="0.5"/>' +
  '</svg>';

export function hasSeenHelper(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function markSeen(): void {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* localStorage no disponible: ignorar */
  }
}

export interface HelperController {
  setMode: (mode: HelperMode) => void;
  loadExampleStrategy: () => void;
  fillDataset: () => void;
  fillConfig: () => void;
  /** Posiciona el Wizard en uno de sus sub-pasos (universo, bias, entry…). */
  setWizardStep: (step: string) => void;
  /** Telemetría (PostHog): quién consume el tour y hasta dónde llega. */
  track?: (event: string, props?: Record<string, unknown>) => void;
  setHelperActive: (active: boolean) => void;
  /** Cierra el tour. Si `completed` es true (el usuario llegó al final), DEJA el
   *  ejemplo reflejado en los formularios. Si es false (Saltar), restaura el
   *  borrador previo y resetea lo que el tour tocó. */
  cleanup: (completed: boolean) => void;
}

export function useBacktestHelper(ctrl: HelperController): { startHelper: () => void } {
  // Mantener el controller fresco sin reconstruir callbacks en cada render.
  const ctrlRef = useRef(ctrl);
  ctrlRef.current = ctrl;

  const modeRef = useRef<HelperMode>("config");
  const wizardStepRef = useRef<string | null>(null);
  const completedRef = useRef(false);
  /** Índice del paso más lejano alcanzado (para "hasta dónde llega"). */
  const lastStepRef = useRef(0);
  const driverRef = useRef<Driver | null>(null);

  /** Aplica el estado que un paso necesita ANTES de resaltarse.
   *  Devuelve los ms que conviene esperar a que el DOM se estabilice (montaje
   *  del drawer / cambio de sub-paso del Wizard) antes de resaltar. */
  const applyEnter = useCallback((enter: HelperStep["enter"]): number => {
    const c = ctrlRef.current;
    // La estrategia debe precargarse antes de montar el wizard/builder.
    if (enter.fill === "strategy") c.loadExampleStrategy();

    let wait = 0;
    if (enter.mode !== modeRef.current) {
      c.setMode(enter.mode);
      // Montar el Wizard (componente pesado + carga de initialStrategy) tarda
      // algo más que abrir un drawer ya montado.
      wait = enter.mode === "wizard" ? WIZARD_MOUNT_MS : TRANSITION_MS;
    }
    modeRef.current = enter.mode;

    // Estos componentes están siempre montados: el evento se aplica al vuelo.
    if (enter.fill === "dataset") c.fillDataset();
    if (enter.fill === "config") c.fillConfig();

    // Posicionar el Wizard en el sub-paso del guion.
    if (enter.mode === "wizard" && enter.wizardStep) {
      if (enter.wizardStep !== wizardStepRef.current) {
        c.setWizardStep(enter.wizardStep);
        wait = Math.max(wait, STEP_SWAP_MS);
      }
      wizardStepRef.current = enter.wizardStep;
    } else {
      wizardStepRef.current = null;
    }
    return wait;
  }, []);

  const buildDriver = useCallback((): Driver => {
    const config: Config = {
      animate: true,
      smoothScroll: true,
      allowClose: false,            // ni overlay ni Esc cierran: solo los botones
      allowKeyboardControl: false,  // evita que las flechas salten la coreografía
      disableActiveInteraction: true, // el campo resaltado es demo, no se toca
      overlayOpacity: 0.7,
      stagePadding: 6,
      stageRadius: 6,
      showProgress: true,
      progressText: "Paso {{current}} de {{total}}",
      showButtons: ["next"],
      nextBtnText: "Entendido →",
      doneBtnText: "¡Hecho!",
      popoverClass: "ec-helper-popover",
      steps: HELPER_STEPS.map((s) => ({
        element: s.element,
        popover: {
          title: s.popover.title,
          description: s.popover.description,
          side: s.popover.side,
          align: s.popover.align,
        },
      })),
      // Avance: preparamos el SIGUIENTE paso y, si abre un drawer, esperamos.
      onNextClick: (_el, _step, { driver: d }) => {
        const i = d.getActiveIndex() ?? 0;
        const next = HELPER_STEPS[i + 1];
        if (!next) {
          // Último paso → el tour se completó: dejamos el ejemplo reflejado.
          completedRef.current = true;
          d.destroy();
          return;
        }
        const wait = applyEnter(next.enter);
        if (wait > 0) {
          window.setTimeout(() => d.moveNext(), wait);
        } else {
          d.moveNext();
        }
      },
      // Identidad de Edgie en la cabecera del popover + botón "Saltar" en el pie.
      onPopoverRender: (popover, { driver: d }) => {
        if (!popover.wrapper.querySelector("[data-helper-edgie]")) {
          const chip = document.createElement("div");
          chip.className = "ec-helper-edgie";
          chip.setAttribute("data-helper-edgie", "");
          chip.innerHTML =
            '<span class="ec-helper-edgie-avatar" aria-hidden="true">' + EDGIE_AVATAR_SVG + '</span>' +
            '<span class="ec-helper-edgie-name">Edgie</span>' +
            '<span class="ec-helper-edgie-tag">tu copiloto</span>';
          popover.wrapper.insertBefore(chip, popover.wrapper.firstChild);
        }
        if (!popover.footerButtons.querySelector("[data-helper-skip]")) {
          const skip = document.createElement("button");
          skip.type = "button";
          skip.textContent = "Saltar";
          skip.className = "ec-helper-skip";
          skip.setAttribute("data-helper-skip", "");
          skip.addEventListener("click", () => d.destroy());
          popover.footerButtons.insertBefore(skip, popover.footerButtons.firstChild);
        }
      },
      // Cada vez que se resalta un paso: registramos hasta dónde ha llegado.
      onHighlightStarted: (_el, _step, { driver: d }) => {
        const i = d.getActiveIndex() ?? 0;
        lastStepRef.current = i;
        const s = HELPER_STEPS[i];
        ctrlRef.current.track?.("bt_helper_step_viewed", {
          step_index: i + 1,
          step_id: s?.id,
          step_total: HELPER_STEPS.length,
        });
      },
      onDestroyed: () => {
        const c = ctrlRef.current;
        const completed = completedRef.current;
        const i = lastStepRef.current;
        c.track?.(completed ? "bt_helper_completed" : "bt_helper_skipped", {
          last_step_index: i + 1,
          last_step_id: HELPER_STEPS[i]?.id,
          step_total: HELPER_STEPS.length,
        });
        // Si se completó, el último paso ya nos dejó en 'config' con el ejemplo
        // reflejado: NO tocamos el modo. Si se saltó, volvemos al panel.
        if (!completed) c.setMode("config");
        c.cleanup(completed);
        c.setHelperActive(false);
        markSeen();
      },
    };
    return driver(config);
  }, [applyEnter]);

  const startHelper = useCallback(() => {
    const c = ctrlRef.current;
    // Limpia cualquier instancia previa para arrancar siempre desde el paso 1.
    driverRef.current?.destroy();
    c.setHelperActive(true);
    c.setMode("config");
    modeRef.current = "config";
    wizardStepRef.current = null;
    completedRef.current = false;
    lastStepRef.current = 0;
    c.track?.("bt_helper_started", { step_total: HELPER_STEPS.length });
    const d = buildDriver();
    driverRef.current = d;
    d.drive(0);
  }, [buildDriver]);

  // Limpieza al desmontar la página.
  useEffect(() => {
    return () => {
      driverRef.current?.destroy();
      driverRef.current = null;
    };
  }, []);

  return { startHelper };
}
