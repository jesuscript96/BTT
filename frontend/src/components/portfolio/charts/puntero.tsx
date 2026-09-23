"use client";

// Lectura "técnica" bajo el cursor para los gráficos SVG del portfolio
// (Jaume, 19-sep: «al pasar el ratón quiero la fecha y los datos en el propio
// puntero; los gráficos de esta página más técnicos y menos minimalistas»).
//
// Tres piezas que comparten todos los gráficos de la página:
//   - usePuntero: el índice de la serie bajo el cursor + la posición del ratón
//     en píxeles del contenedor (para colocar el cartel).
//   - CruzTecnica: dentro del SVG, la cruz (vertical + horizontal), la etiqueta
//     de la fecha pegada al eje X, la del valor pegada al eje Y y un punto por
//     serie.
//   - CartelPuntero: el cartel que sigue al ratón, con la fecha y una fila por
//     serie (color, nombre, valor). Se recoloca para no salirse del lienzo.

import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";

export type Puntero = {
  /** Índice del punto bajo el cursor (0..n-1). */
  idx: number;
  /** Posición del ratón en píxeles del CONTENEDOR (el div `position: relative`). */
  px: number;
  py: number;
  /** Ancho y alto del contenedor, para que el cartel no se salga. */
  cw: number;
  ch: number;
};

/** Índice bajo el cursor a partir del eje X del SVG (viewBox de ancho `W` con
 *  márgenes `padL`/`padR`) y posición del ratón en el contenedor del SVG. */
export function usePuntero(nPuntos: number, W: number, padL: number, padR: number) {
  const [puntero, setPuntero] = useState<Puntero | null>(null);
  const onMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const svg = e.currentTarget;
      const rect = svg.getBoundingClientRect();
      const cont = (svg.parentElement as HTMLElement | null)?.getBoundingClientRect() ?? rect;
      const fx = ((e.clientX - rect.left) / rect.width) * W;
      const n = Math.max(nPuntos, 2);
      const i = Math.round(((fx - padL) / (W - padL - padR)) * (n - 1));
      if (i < 0 || i >= nPuntos) {
        setPuntero(null);
        return;
      }
      setPuntero({ idx: i, px: e.clientX - cont.left, py: e.clientY - cont.top, cw: cont.width, ch: cont.height });
    },
    [nPuntos, W, padL, padR],
  );
  const onLeave = useCallback(() => setPuntero(null), []);
  return { puntero, onMove, onLeave };
}

export type FilaPuntero = {
  color: string;
  nombre: string;
  valor: string;
  /** Segundo dato a la derecha (p. ej. el drawdown), en gris. */
  extra?: string;
  /** La fila principal (la combinada) va en negrita. */
  grueso?: boolean;
};

/** El cartel que sigue al ratón. Por defecto arriba a la derecha del puntero;
 *  si no cabe, a la izquierda y/o debajo. */
export function CartelPuntero({
  puntero,
  titulo,
  subtitulo,
  filas,
}: {
  puntero: Puntero;
  titulo: string;
  subtitulo?: string;
  filas: FilaPuntero[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [dim, setDim] = useState({ w: 220, h: 60 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setDim({ w: el.offsetWidth, h: el.offsetHeight });
  }, [titulo, filas.length, puntero.idx]);
  const SEP = 16;
  let left = puntero.px + SEP;
  if (left + dim.w > puntero.cw - 4) left = Math.max(4, puntero.px - SEP - dim.w);
  let top = puntero.py - dim.h - 12;
  if (top < 4) top = Math.min(puntero.py + SEP, Math.max(4, puntero.ch - dim.h - 4));
  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        top,
        left,
        background: color.bgElevated,
        border: `1px solid ${color.border}`,
        borderRadius: radius.sm,
        padding: "8px 11px",
        fontSize: 11.5,
        fontFamily: font.mono,
        color: color.textPrimary,
        pointerEvents: "none",
        minWidth: 190,
        maxWidth: 340,
        boxShadow: "0 6px 18px rgba(0,0,0,0.35)",
        zIndex: 5,
      }}
    >
      <div style={{ fontFamily: font.sans, fontWeight: 700, fontSize: 11.5, color: color.textHigh, marginBottom: subtitulo ? 0 : 5 }}>{titulo}</div>
      {subtitulo && <div style={{ fontFamily: font.sans, fontSize: 10, color: color.textMuted, marginBottom: 5 }}>{subtitulo}</div>}
      {filas.map((f, k) => (
        <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, lineHeight: 1.55, fontWeight: f.grueso ? 700 : 400 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: f.color, flexShrink: 0 }} />
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: font.sans, color: color.textSecondary }}>{f.nombre}</span>
          <span style={{ color: color.textHigh, whiteSpace: "nowrap" }}>{f.valor}</span>
          {f.extra != null && <span style={{ color: color.textMuted, whiteSpace: "nowrap", fontSize: 10.5 }}>{f.extra}</span>}
        </div>
      ))}
    </div>
  );
}

/** La cruz dentro del SVG: vertical en `x` (con la fecha en una cajita sobre
 *  el eje X), horizontal en `y` (con el valor en una cajita sobre el eje Y) y
 *  un punto por serie. `y`/`etiquetaY` son opcionales (gráficos sin valor
 *  principal). */
export function CruzTecnica({
  x,
  y,
  W,
  top,
  bottom,
  padL,
  etiquetaX,
  etiquetaY,
  puntos,
}: {
  x: number;
  y?: number;
  W: number;
  /** y del borde superior e inferior del área de dibujo. */
  top: number;
  bottom: number;
  padL: number;
  etiquetaX: string;
  etiquetaY?: string;
  puntos: { cx: number; cy: number; color: string; r?: number }[];
}) {
  const anchoX = Math.max(46, etiquetaX.length * 6.2 + 10);
  const xCaja = Math.min(Math.max(x - anchoX / 2, padL), W - anchoX - 2);
  const anchoY = etiquetaY ? Math.max(30, etiquetaY.length * 6.2 + 10) : 0;
  return (
    <g pointerEvents="none">
      <line x1={x} x2={x} y1={top} y2={bottom} stroke={color.textSecondary} strokeWidth={0.8} strokeDasharray="3 3" />
      {y != null && etiquetaY && (
        <>
          <line x1={padL} x2={W} y1={y} y2={y} stroke={color.textSecondary} strokeWidth={0.6} strokeDasharray="3 3" />
          <rect x={padL - anchoY - 3} y={y - 8} width={anchoY} height={16} rx={2} fill={color.bgElevated} stroke={color.border} strokeWidth={0.6} />
          <text x={padL - anchoY / 2 - 3} y={y + 3.5} textAnchor="middle" fontSize="9.5" fontFamily="var(--color-ec-mono)" fill={color.textHigh}>
            {etiquetaY}
          </text>
        </>
      )}
      <rect x={xCaja} y={bottom + 3} width={anchoX} height={15} rx={2} fill={color.bgElevated} stroke={color.border} strokeWidth={0.6} />
      <text x={xCaja + anchoX / 2} y={bottom + 14} textAnchor="middle" fontSize="9.5" fontFamily="var(--color-ec-mono)" fill={color.textHigh}>
        {etiquetaX}
      </text>
      {puntos.map((p, k) => (
        <circle key={k} cx={p.cx} cy={p.cy} r={p.r ?? 3} fill={p.color} stroke={color.bgBase} strokeWidth={1.2} />
      ))}
    </g>
  );
}

/** Rejilla vertical fina en las marcas del eje X (los gráficos solo tenían la
 *  horizontal). */
export function RejillaX({ xs, top, bottom }: { xs: number[]; top: number; bottom: number }) {
  return (
    <g>
      {xs.map((x, k) => (
        <line key={k} x1={x} x2={x} y1={top} y2={bottom} stroke="var(--color-ec-border)" strokeWidth={0.5} strokeDasharray="2 3" />
      ))}
    </g>
  );
}
