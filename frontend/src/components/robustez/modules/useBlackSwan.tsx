"use client";

import { Placeholder } from "../shared";
import type { ModuleCtx, ModuleParts } from "./types";

/**
 * Margen de EV para eventos de Black Swan.
 *
 * Reservado a proposito: el hueco existe en el rail para que el modulo tenga su
 * sitio, pero todavia no hay logica detras. No calcula nada ni llama a ningun
 * endpoint.
 */
export function useBlackSwan(_ctx: ModuleCtx): ModuleParts {
  return {
    config: (
      <div style={{ fontSize: 11.5, lineHeight: 1.6, opacity: 0.7 }}>
        Sin parametros todavia.
      </div>
    ),
    results: (
      <Placeholder>
        Pendiente de definir. Este modulo medira cuanto margen de valor esperado aguanta la
        estrategia antes de que un evento extremo se lo coma — pero aun no hay nada implementado
        detras.
      </Placeholder>
    ),
  };
}
