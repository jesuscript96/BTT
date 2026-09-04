"use client";

import React from "react";

import { Panel, color, font } from "@/components/ui";
import { MODULES, type ModuleId } from "./ModuleRail";

interface Props {
  module: ModuleId;
  children: React.ReactNode;
}

/**
 * El cuadro grande donde se pintan los resultados del módulo activo.
 *
 * Usa el primitivo `Panel` (el estilo denso que estrenó el Genético) en vez de
 * una sección escrita a mano: antes tenía aquí sus propios px, su radio y su
 * cabecera, que es justo como se llega a tener tres estilos de cuadro distintos
 * dentro de la misma app.
 */
export default function ResultsPanel({ module, children }: Props) {
  const def = MODULES.find((m) => m.id === module);
  return (
    <Panel
      titulo={def?.label ?? "Resultados"}
      style={{ minHeight: 380, marginBottom: 0 }}
      sinRelleno
      extra={
        <span style={{ fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>
          {def?.blurb}
        </span>
      }
    >
      <div style={{ padding: "18px 18px 22px" }}>{children}</div>
    </Panel>
  );
}
