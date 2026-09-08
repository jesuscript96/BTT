"use client";

/**
 * Panel — la sección densa, de instrumento, que estrenó la página del Genético
 * y que a Jaume le gustó lo bastante como para querer llevarla a Portfolio y a
 * Robustez.
 *
 * QUÉ LA DIFERENCIA DE `Card`, y por qué existen las dos:
 *
 *   `Card`    superficie con aire, radio y sombra. Para contenido que se lee:
 *             una estrategia, un resultado, una explicación.
 *   `Panel`   superficie SIN radio, con cabecera propia y mucha menos altura.
 *             Para paneles de control: parámetros, filtros, mandos. Lo que se
 *             mira de reojo mientras trabajas con otra cosa.
 *
 * No es un capricho estético: en una pantalla con veinte parámetros el radio y
 * el aire de `Card` obligan a desplazarse, y desplazarse para ver un parámetro
 * que estás ajustando rompe el trabajo. El panel cabe entero.
 *
 * TODO SALE DE LOS TOKENS, ni un hex ni un px de color suelto — es la regla del
 * sistema (`docs/DESIGN_SYSTEM.md`). El único valor crudo es el `borderRadius:
 * 0`, que ES la decisión de diseño: no hay token para «sin radio» porque hasta
 * ahora nada lo necesitaba.
 */
import type { CSSProperties, ReactNode } from "react";

import { color, font, hairline } from "./tokens";

/** Etiqueta de campo: pequeña, en versales, con mucho tracking. Se lee como una
 *  marca de instrumento, no como texto. */
export const etiquetaPanel: CSSProperties = {
  fontFamily: font.sans,
  fontSize: 9,
  fontWeight: 700,
  letterSpacing: "1px",
  textTransform: "uppercase",
  color: color.textMuted,
};

/** Control de formulario dentro de un Panel: monoespaciado (son datos), 28 px
 *  de alto y sin radio, para que una columna de ellos forme una rejilla y no
 *  una lista de cápsulas. */
export const controlPanel: CSSProperties = {
  background: color.bgSidebar,
  border: hairline,
  borderRadius: 0,
  color: color.textHigh,
  fontFamily: font.mono,
  fontSize: 12,
  padding: "5px 7px",
  width: "100%",
  outline: "none",
  height: 28,
};

export function Panel({ titulo, extra, children, sinRelleno, style }: {
  titulo: string;
  /** A la derecha de la cabecera: un contador, una ayuda, un interruptor. */
  extra?: ReactNode;
  children: ReactNode;
  /** Para meter una tabla que ya trae sus propios márgenes. */
  sinRelleno?: boolean;
  style?: CSSProperties;
}) {
  return (
    <section style={{
      marginBottom: 14,
      border: `1px solid ${color.border}`,
      background: color.bgSurface,
      ...style,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 6, padding: "6px 10px",
        borderBottom: `1px solid ${color.border}`,
        background: color.bgElevated,
      }}>
        <span style={{ ...etiquetaPanel, color: color.textSecondary, fontSize: 10 }}>
          {titulo}
        </span>
        {extra}
      </div>
      <div style={{ padding: sinRelleno ? 0 : "2px 10px 6px" }}>{children}</div>
    </section>
  );
}

/** Una fila etiqueta-valor dentro de un Panel. La columna de etiquetas es fija
 *  para que los controles queden alineados entre filas: si cada uno empezara
 *  donde acaba su texto, la columna sería un zigzag. */
export function FilaPanel({ etiqueta, children, ancha }: {
  etiqueta: string;
  children: ReactNode;
  /** La etiqueta va encima en vez de al lado. Para controles anchos. */
  ancha?: boolean;
}) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: ancha ? "1fr" : "150px 1fr",
      gap: ancha ? 4 : 10,
      alignItems: "center",
      padding: "5px 0",
      borderBottom: hairline,
    }}>
      <span style={etiquetaPanel}>{etiqueta}</span>
      <div>{children}</div>
    </div>
  );
}

/** Grupo de botones excluyentes, pegados, sin radio. Ocupa menos que una fila
 *  de radios y se lee de un vistazo cuál está activo. */
export function ConmutadorPanel<T extends string>({ valor, onChange, opciones }: {
  valor: T;
  onChange: (v: T) => void;
  opciones: Array<{ value: T; label: string }>;
}) {
  return (
    <div style={{ display: "flex", border: hairline }}>
      {opciones.map((o) => {
        const activo = o.value === valor;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            style={{
              flex: 1,
              padding: "4px 8px",
              border: "none",
              borderRadius: 0,
              cursor: "pointer",
              fontFamily: font.sans,
              fontSize: 11,
              fontWeight: activo ? 600 : 400,
              background: activo ? color.copper : "transparent",
              color: activo ? "#fff" : color.textSecondary,
              transition: "background 120ms ease",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
