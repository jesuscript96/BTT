"use client";

import { useMemo, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";

interface Pt {
  date: string;
  value: number;
}

const W = 900;
const H = 260;
const PAD = { t: 16, r: 16, b: 46, l: 74 };

const money = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1000) return `$${(v / 1000).toFixed(a >= 10_000 ? 0 : 1)}k`;
  return `$${v.toFixed(0)}`;
};

/** Rendimiento acumulado respecto al capital inicial. */
const retPct = (v: number, init: number) => (v / init - 1) * 100;
const fmtRet = (r: number) => `${r >= 0 ? "+" : ""}${Math.abs(r) >= 100 ? r.toFixed(0) : r.toFixed(1)}%`;

/**
 * Curva original contra curva castigada.
 *
 * El eje vertical va en RENDIMIENTO acumulado (%), no en dolares: es la cifra
 * que se compara entre las dos curvas y la que se lee en el resto del panel.
 * La escala es logaritmica sobre el capital porque una estrategia que compone
 * recorre dos ordenes de magnitud y en lineal los primeros meses se aplastan
 * contra el eje — que es justo donde empieza a separarse la version estresada.
 */
export function StressCurves({
  base,
  stressed,
  initCash,
}: {
  base: Pt[];
  stressed: Pt[];
  initCash: number;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const geom = useMemo(() => {
    if (!base.length) return null;
    const all = [...base.map((p) => p.value), ...stressed.map((p) => p.value), initCash];
    // El suelo se recorta: en log, un capital casi cero mandaria el eje a -inf.
    const floor = Math.max(1, initCash * 0.01);
    const lo = Math.log10(Math.max(floor, Math.min(...all)));
    const hi = Math.log10(Math.max(...all, initCash * 1.1));
    const span = hi - lo || 1;

    const n = Math.max(base.length, stressed.length, 2);
    const xOf = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const yOf = (v: number) =>
      PAD.t + (1 - (Math.log10(Math.max(v, floor)) - lo) / span) * (H - PAD.t - PAD.b);

    const line = (pts: Pt[]) =>
      pts.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(p.value).toFixed(1)}`).join("");

    // Marcas del eje: potencias de 10 dentro del rango, etiquetadas en
    // rendimiento. Si salen menos de tres se rellena con medias potencias para
    // que el eje no quede desnudo en rangos estrechos.
    const ticks: number[] = [];
    for (let e = Math.floor(lo); e <= Math.ceil(hi); e++) {
      for (const m of [1, 3]) {
        const v = m * Math.pow(10, e);
        if (Math.log10(v) >= lo - 1e-9 && Math.log10(v) <= hi + 1e-9) ticks.push(v);
      }
    }
    return { xOf, yOf, basePath: line(base), stressPath: line(stressed), ticks, n, floor };
  }, [base, stressed, initCash]);

  if (!geom) return null;

  // Seis marcas de fecha repartidas: con dos o tres el eje no dice nada.
  const xTickIdx = Array.from({ length: 6 }, (_, k) =>
    Math.round((k / 5) * (base.length - 1)),
  ).filter((v, i, a) => a.indexOf(v) === i);

  const hoveredBase = hover != null ? base[hover] : null;
  const hoveredStress = hover != null ? stressed[Math.min(hover, stressed.length - 1)] : null;

  return (
    <div
      style={{
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        padding: "10px 12px 6px",
      }}
    >
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {geom.ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={geom.yOf(t)}
              y2={geom.yOf(t)}
              stroke="var(--color-ec-border)"
              strokeWidth="0.5"
            />
            <text
              x={PAD.l - 8}
              y={geom.yOf(t) + 3}
              textAnchor="end"
              fontSize="9.5"
              fill="var(--color-ec-text-secondary)"
              fontFamily="var(--color-ec-mono)"
            >
              {fmtRet(retPct(t, initCash))}
            </text>
            <text
              x={PAD.l - 8}
              y={geom.yOf(t) + 12}
              textAnchor="end"
              fontSize="8"
              fill="var(--color-ec-text-muted)"
              fontFamily="var(--color-ec-mono)"
            >
              {money(t)}
            </text>
          </g>
        ))}

        {/* Capital inicial: la frontera entre ganar y perder */}
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={geom.yOf(initCash)}
          y2={geom.yOf(initCash)}
          stroke="var(--color-ec-text-muted)"
          strokeWidth="0.9"
          strokeDasharray="3 3"
        />

        <path d={geom.basePath} fill="none" stroke="var(--color-ec-profit)" strokeWidth="1.4" />
        <path d={geom.stressPath} fill="none" stroke="var(--color-ec-loss)" strokeWidth="1.4" />

        {[
          { c: "var(--color-ec-profit)", label: "original" },
          { c: "var(--color-ec-loss)", label: "estresada" },
        ].map((s, i) => (
          <g key={s.label} transform={`translate(${PAD.l + 8}, ${PAD.t + 11 + i * 15})`}>
            <line x1="0" x2="15" y1="0" y2="0" stroke={s.c} strokeWidth="1.6" />
            <text x="20" y="3.5" fontSize="9.5" fill="var(--color-ec-text-secondary)" fontFamily="var(--color-ec-sans)">
              {s.label}
            </text>
          </g>
        ))}

        {/* Eje X: fechas */}
        {xTickIdx.map((i, k) => (
          <g key={k}>
            <line
              x1={geom.xOf(i)}
              x2={geom.xOf(i)}
              y1={H - PAD.b}
              y2={H - PAD.b + 4}
              stroke="var(--color-ec-border)"
              strokeWidth="0.5"
            />
            <text
              x={geom.xOf(i)}
              y={H - PAD.b + 16}
              textAnchor={k === 0 ? "start" : k === xTickIdx.length - 1 ? "end" : "middle"}
              fontSize="9.5"
              fill="var(--color-ec-text-secondary)"
              fontFamily="var(--color-ec-mono)"
            >
              {base[i]?.date}
            </text>
          </g>
        ))}

        <text
          x={PAD.l + (W - PAD.l - PAD.r) / 2}
          y={H - 6}
          textAnchor="middle"
          fontSize="9.5"
          fill="var(--color-ec-text-muted)"
          fontFamily="var(--color-ec-sans)"
        >
          sesiones de negociacion
        </text>
        <text
          transform={`translate(13, ${PAD.t + (H - PAD.t - PAD.b) / 2}) rotate(-90)`}
          textAnchor="middle"
          fontSize="9.5"
          fill="var(--color-ec-text-muted)"
          fontFamily="var(--color-ec-sans)"
        >
          rendimiento acumulado
        </text>

        {/* Hover */}
        <rect
          x={PAD.l}
          y={PAD.t}
          width={W - PAD.l - PAD.r}
          height={H - PAD.t - PAD.b}
          fill="transparent"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const svg = e.currentTarget.ownerSVGElement;
            if (!svg) return;
            const r = svg.getBoundingClientRect();
            const rel = ((e.clientX - r.left) / r.width) * W;
            const i = Math.round(((rel - PAD.l) / (W - PAD.l - PAD.r)) * (base.length - 1));
            setHover(i >= 0 && i < base.length ? i : null);
          }}
        />
        {hover != null && hoveredBase && (
          <g pointerEvents="none">
            <line
              x1={geom.xOf(hover)}
              x2={geom.xOf(hover)}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="var(--color-ec-copper)"
              strokeWidth="0.75"
            />
            <circle cx={geom.xOf(hover)} cy={geom.yOf(hoveredBase.value)} r="2.5" fill="var(--color-ec-profit)" />
            {hoveredStress && (
              <circle cx={geom.xOf(hover)} cy={geom.yOf(hoveredStress.value)} r="2.5" fill="var(--color-ec-loss)" />
            )}
            <text
              x={Math.min(geom.xOf(hover) + 9, W - 210)}
              y={PAD.t + 12}
              fontSize="10"
              fill="var(--color-ec-text-high)"
              fontFamily="var(--color-ec-mono)"
            >
              {hoveredBase.date} · orig {fmtRet(retPct(hoveredBase.value, initCash))}
              {hoveredStress ? ` · estr ${fmtRet(retPct(hoveredStress.value, initCash))}` : ""}
            </text>
          </g>
        )}
      </svg>
      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "2px 2px 4px" }}>
        Escala logaritmica. La linea de puntos es el 0% (capital inicial): por debajo, la estrategia
        pierde dinero. Pasa el puntero para leer ambas curvas en cualquier fecha.
      </div>
    </div>
  );
}
