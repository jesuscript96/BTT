import type React from "react";
import type { RobustezRun, RobustezStrategy } from "@/lib/api_robustez";

/**
 * Cada motor de robustez se implementa como un hook que devuelve sus DOS
 * mitades: la configuracion (panel izquierdo) y el resultado (panel derecho).
 *
 * Se hace asi porque ambas comparten estado —los parametros que eliges a la
 * izquierda son los que produce el grafico de la derecha— y partirlo en dos
 * componentes hermanos obligaria a subir ese estado a la pagina y a repartirlo
 * modulo por modulo. El hook mantiene cada motor autocontenido.
 */
export interface ModuleParts {
  config: React.ReactNode;
  results: React.ReactNode;
}

export interface ModuleCtx {
  run: RobustezRun | null;
  strategy: RobustezStrategy | null;
  loading: boolean;
}
