"use client";

import { useMemo, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";

const W = 900;
const H = 230;
const PAD = { t: 12, r: 16, b: 30, l: 52 };

export interface DdPaths {
  real: number[];
  p50: number[];
  p95: number[];
  p99: number[];
  levels: { real: number; p50: number; p95: number; p99: number };
}

/**
 * El drawdown real contra dos escenarios simulados, superpuestos.
 *
 * El real va como area rellena, igual que en el analisis basico, para que se
 * reconozca de un vistazo como "lo que paso". Encima, dos lineas finas: la
 * mediana de las simulaciones y el escenario que solo 1 de cada 20 supera.
 *
 * Se dibujan solo esos dos. El backend tambien devuelve el escenario del 1%,
 * pero con cuatro curvas encima el grafico se convertia en una maraña y dejaba
 * de leerse; esa cifra ya esta en los recuadros de arriba.
 *
 * Por que curvas y no solo los numeros: los percentiles dicen CUANTO se cae,
 * pero no COMO. Una caida del 30% que llega de golpe y se recupera en dos
 * semanas, y otra que se arrastra medio año, son la misma cifra y dos
 * experiencias distintas.
 *
 * El eje horizontal son operaciones, no fechas: en una simulacion los trades no
 * tienen fecha propia, son una historia alternativa.
 */
export function DrawdownCompare({ paths }: { paths: DdPaths }) {
  const [hover, setHover] = useState<number | null>(null);

  const lines = useMemo(
    () =>
      [
        { key: "p50", label: "mediana simulada", data: paths.p50, stroke: "var(--color-ec-info)" },
        { key: "p95", label: "1 de cada 20 (95%)", data: paths.p95, stroke: "var(--color-ec-warning)" },
      ].filter((s) => Array.isArray(s.data) && s.data.length > 1),
    [paths],
  );

  const geom = useMemo(() => {
    const pool = [...(paths.real || []), ...lines.flatMap((s) => s.data)];
    if (pool.length < 2) return null;
    const minDd = Math.min(-1, ...pool);
    const n = Math.max(paths.real?.length ?? 0, ...lines.map((s) => s.data.length), 2);
    const xOf = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
    const yOf = (v: number) => PAD.t + (v / minDd) * (H - PAD.t - PAD.b);

    // Submuestreo: con 3.500 puntos por serie el SVG se arrastra al mover el
    // raton. Con ~700 la forma es indistinguible.
    const step = Math.max(1, Math.floor(n / 700));
    const line = (d: number[]) => {
      let out = "";
      for (let i = 0; i < d.length; i += step) {
        out += `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(d[i]).toFixed(1)}`;
      }
      const last = d.length - 1;
      if (last % step !== 0) out += `L${xOf(last).toFixed(1)},${yOf(d[last]).toFixed(1)}`;
      return out;
    };

    const realPath = paths.real?.length ? line(paths.real) : "";
    const realArea = realPath
      ? `${realPath}L${xOf((paths.real.length ?? 1) - 1).toFixed(1)},${yOf(0).toFixed(1)}L${xOf(0).toFixed(1)},${yOf(0).toFixed(1)}Z`
      : "";

    const ticks: number[] = [];
    const stepY = Math.max(5, Math.ceil(Math.abs(minDd) / 4 / 5) * 5);
    for (let v = 0; v >= minDd - 1e-9; v -= stepY) ticks.push(v);

    return { xOf, yOf, line, realPath, realArea, minDd, n, ticks };
  }, [paths, lines]);

  if (!geom) return null;

  const legend = [
    { label: "real", value: paths.levels?.real, stroke: "var(--color-ec-loss)", area: true },
    ...lines.map((s) => ({
      label: s.label,
      value: paths.levels?.[s.key as "p50" | "p95"],
      stroke: s.stroke,
      area: false,
    })),
  ];

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
        <defs>
          {/* Rojo mas oscuro que el del trazo: la mancha tiene que leerse como
              fondo solido, no como una sombra tenue. */}
          <linearGradient id="ddcmp" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7B2A22" stopOpacity="0.30" />
            <stop offset="100%" stopColor="#5A1E18" stopOpacity="0.78" />
          </linearGradient>
        </defs>

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
              x={PAD.l - 7}
              y={geom.yOf(t) + 3}
              textAnchor="end"
              fontSize="9.5"
              fill="var(--color-ec-text-muted)"
              fontFamily="var(--color-ec-mono)"
            >
              {t.toFixed(0)}%
            </text>
          </g>
        ))}

        {/* El real, relleno — igual que en el analisis basico */}
        <path d={geom.realArea} fill="url(#ddcmp)" />
        <path d={geom.realPath} fill="none" stroke="var(--color-ec-loss)" strokeWidth="2.2" />

        {/* Los simulados, linea normal encima */}
        {lines.map((s) => (
          <path key={s.key} d={geom.line(s.data)} fill="none" stroke={s.stroke} strokeWidth="1.1" opacity="0.9" />
        ))}

        <text
          x={PAD.l + (W - PAD.l - PAD.r) / 2}
          y={H - 6}
          textAnchor="middle"
          fontSize="9.5"
          fill="var(--color-ec-text-muted)"
          fontFamily="var(--color-ec-sans)"
        >
          operaciones →
        </text>

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
            const i = Math.round(((rel - PAD.l) / (W - PAD.l - PAD.r)) * (geom.n - 1));
            setHover(i >= 0 && i < geom.n ? i : null);
          }}
        />
        {hover != null && (
          <g pointerEvents="none">
            <line
              x1={geom.xOf(hover)}
              x2={geom.xOf(hover)}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="var(--color-ec-text-muted)"
              strokeWidth="0.6"
            />
            {paths.real?.[hover] != null && (
              <circle cx={geom.xOf(hover)} cy={geom.yOf(paths.real[hover])} r="2.4" fill="var(--color-ec-loss)" />
            )}
            {lines.map(
              (s) =>
                s.data[hover] != null && (
                  <circle key={s.key} cx={geom.xOf(hover)} cy={geom.yOf(s.data[hover])} r="2.4" fill={s.stroke} />
                ),
            )}
            <text
              x={Math.min(geom.xOf(hover) + 8, W - 300)}
              y={H - PAD.b - 8}
              fontSize="10"
              fill="var(--color-ec-text-high)"
              fontFamily="var(--color-ec-mono)"
            >
              op. {hover} · real {paths.real?.[hover]?.toFixed(1)}%
              {lines.map((s) => (s.data[hover] != null ? ` · ${s.key} ${s.data[hover].toFixed(1)}%` : "")).join("")}
            </text>
          </g>
        )}
      </svg>

      {/* Leyenda debajo del lienzo: dentro la tapaban las propias curvas. */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "10px 26px",
          padding: "8px 4px 4px",
          borderTop: `0.5px solid ${color.border}`,
          marginTop: 4,
        }}
      >
        {legend.map((l) => (
          <span key={l.label} style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
            {l.area ? (
              <span
                style={{
                  width: 16,
                  height: 9,
                  background: "#5A1E18",
                  border: `1px solid ${l.stroke}`,
                  borderRadius: 1,
                  flexShrink: 0,
                }}
              />
            ) : (
              <span style={{ width: 16, height: 2, background: l.stroke, flexShrink: 0 }} />
            )}
            <span style={{ fontSize: 11, fontFamily: font.sans, color: color.textSecondary }}>{l.label}</span>
            {l.value != null && (
              <span style={{ fontSize: 11, fontFamily: font.mono, color: l.stroke }}>
                max {l.value.toFixed(1)}%
              </span>
            )}
          </span>
        ))}
      </div>

      <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "2px 4px 4px", lineHeight: 1.5 }}>
        La mancha roja es el drawdown que ocurrio de verdad. Las dos lineas encima son simulaciones
        reales del bootstrap, elegidas por tener el drawdown maximo mas cercano a la mediana y al
        escenario que solo 1 de cada 20 supera.
      </div>
    </div>
  );
}
