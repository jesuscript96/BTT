"use client";

import { useMemo, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import type { EquityPointT } from "@/lib/api_robustez";
import { epochToDate } from "@/lib/robustez/analytics";

/* SVG a pelo en vez de una libreria de charts: estas dos figuras son un area y
   unas barras, y dibujarlas a mano nos deja controlar el grosor de linea y la
   densidad de rejilla al detalle del design system. */

const money = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1000) return `$${(v / 1000).toFixed(a >= 10_000 ? 0 : 1)}k`;
  return `$${v.toFixed(0)}`;
};

const W = 900;
const H = 190;
const PAD = { t: 12, r: 12, b: 22, l: 46 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const span = max - min;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw))));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

function ChartFrame({
  children,
  height = H,
  caption,
}: {
  children: React.ReactNode;
  height?: number;
  caption?: string;
}) {
  return (
    <div
      style={{
        background: color.bgBase,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        padding: "10px 12px 6px",
      }}
    >
      <svg viewBox={`0 0 ${W} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {children}
      </svg>
      {caption && (
        <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, padding: "2px 2px 4px" }}>
          {caption}
        </div>
      )}
    </div>
  );
}

/** Curva "bajo el agua": el drawdown en cada momento, medido desde el maximo previo. */
export function DrawdownRibbon({ equity }: { equity: EquityPointT[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const { path, area, dd, minDd, xOf, yOf, eqPath, eqLo, eqHi } = useMemo(() => {
    const dd: number[] = [];
    let peak = equity.length ? equity[0].value : 0;
    for (const p of equity) {
      if (p.value > peak) peak = p.value;
      dd.push(peak > 0 ? (p.value / peak - 1) * 100 : 0);
    }
    const minDd = Math.min(-1, ...dd);
    const n = Math.max(1, dd.length - 1);
    const xOf = (i: number) => PAD.l + (i / n) * (W - PAD.l - PAD.r);
    const yOf = (v: number) => PAD.t + (v / minDd) * (H - PAD.t - PAD.b);

    let path = "";
    dd.forEach((v, i) => {
      path += `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`;
    });
    const area = `${path}L${xOf(dd.length - 1).toFixed(1)},${yOf(0).toFixed(1)}L${xOf(0).toFixed(1)},${yOf(0).toFixed(1)}Z`;

    // Equity de fondo, en su PROPIA escala (logaritmica) y muy atenuada. No
    // comparte eje con el drawdown a proposito: aqui solo sirve de referencia
    // visual — para ver si un hundimiento cayo en plena subida o en un tramo
    // plano —, no para leerle un valor.
    const vals = equity.map((p) => p.value).filter((v) => Number.isFinite(v) && v > 0);
    const eqLo = vals.length ? Math.min(...vals) : 0;
    const eqHi = vals.length ? Math.max(...vals) : 1;
    const lg = (v: number) => Math.log10(Math.max(v, 1));
    const span = lg(eqHi) - lg(eqLo) || 1;
    // Ocupa la mitad inferior del lienzo para no taparle la cara al drawdown.
    const eqY = (v: number) => H - PAD.b - ((lg(v) - lg(eqLo)) / span) * (H - PAD.t - PAD.b) * 0.92;
    const eqPath = equity
      .map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${eqY(p.value).toFixed(1)}`)
      .join("");

    return { path, area, dd, minDd, xOf, yOf, eqPath, eqLo, eqHi };
  }, [equity]);

  if (!equity.length) return null;
  const ticks = niceTicks(minDd, 0, 4);

  return (
    <ChartFrame caption="En rojo, la distancia al maximo historico en cada sesion: cuanto mas ancha la mancha, mas tiempo bajo el agua. En verde tenue y al fondo, la curva de capital, para situar cada hundimiento — usa su propia escala, no la del eje.">
      <defs>
        {/* gradiente del area de drawdown */}
        <linearGradient id="ddgrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-ec-loss)" stopOpacity="0.05" />
          <stop offset="100%" stopColor="var(--color-ec-loss)" stopOpacity="0.34" />
        </linearGradient>
      </defs>

      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={PAD.l}
            x2={W - PAD.r}
            y1={yOf(t)}
            y2={yOf(t)}
            stroke="var(--color-ec-border)"
            strokeWidth="0.5"
          />
          <text
            x={PAD.l - 7}
            y={yOf(t) + 3}
            textAnchor="end"
            fontSize="9"
            fill="var(--color-ec-text-muted)"
            fontFamily="var(--color-ec-mono)"
          >
            {t.toFixed(0)}%
          </text>
        </g>
      ))}

      {/* Equity de fondo: detras del drawdown y muy tenue. */}
      <path d={eqPath} fill="none" stroke="var(--color-ec-profit)" strokeWidth="1" opacity="0.3" />

      <path d={area} fill="url(#ddgrad)" />
      <path d={path} fill="none" stroke="var(--color-ec-loss)" strokeWidth="1" />

      <g transform={`translate(${W - PAD.r - 4}, ${PAD.t + 8})`}>
        <text
          textAnchor="end"
          fontSize="9"
          fill="var(--color-ec-profit)"
          opacity="0.75"
          fontFamily="var(--color-ec-sans)"
        >
          equity (escala propia, {money(eqLo)} → {money(eqHi)})
        </text>
      </g>

      {/* Fechas: primera, media y ultima */}
      {[0, Math.floor(dd.length / 2), dd.length - 1].map((i, k) => (
        <text
          key={k}
          x={xOf(i)}
          y={H - 6}
          textAnchor={k === 0 ? "start" : k === 2 ? "end" : "middle"}
          fontSize="9"
          fill="var(--color-ec-text-muted)"
          fontFamily="var(--color-ec-mono)"
        >
          {epochToDate(equity[i].time)}
        </text>
      ))}

      {/* Capa de hover */}
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
          const i = Math.round(((rel - PAD.l) / (W - PAD.l - PAD.r)) * (dd.length - 1));
          setHover(i >= 0 && i < dd.length ? i : null);
        }}
      />
      {hover != null && (
        <g pointerEvents="none">
          <line
            x1={xOf(hover)}
            x2={xOf(hover)}
            y1={PAD.t}
            y2={H - PAD.b}
            stroke="var(--color-ec-copper)"
            strokeWidth="0.75"
          />
          <circle cx={xOf(hover)} cy={yOf(dd[hover])} r="2.5" fill="var(--color-ec-copper)" />
          <text
            x={Math.min(xOf(hover) + 8, W - 130)}
            y={PAD.t + 12}
            fontSize="10"
            fill="var(--color-ec-text-high)"
            fontFamily="var(--color-ec-mono)"
          >
            {epochToDate(equity[hover].time)} · {dd[hover].toFixed(2)}%
          </text>
        </g>
      )}
    </ChartFrame>
  );
}

/** Histograma de rachas perdedoras consecutivas. */
export function LosingStreakBars({ histogram }: { histogram: Array<{ length: number; count: number }> }) {
  if (!histogram.length) return null;
  const h = 150;
  const maxCount = Math.max(...histogram.map((d) => d.count));
  const innerW = W - PAD.l - PAD.r;
  const bw = innerW / histogram.length;

  return (
    <ChartFrame
      height={h}
      caption="Cuantas veces se encadenaron N perdidas seguidas. La cola derecha es la que hay que estar dispuesto a aguantar."
    >
      {histogram.map((d, i) => {
        const bh = (d.count / maxCount) * (h - PAD.t - PAD.b);
        const x = PAD.l + i * bw;
        // Las rachas largas son las que duelen: se van tiñendo hacia el rojo.
        const heat = Math.min(1, d.length / Math.max(4, histogram[histogram.length - 1].length));
        return (
          <g key={d.length}>
            <rect
              x={x + bw * 0.16}
              y={h - PAD.b - bh}
              width={bw * 0.68}
              height={Math.max(1, bh)}
              fill="var(--color-ec-loss)"
              opacity={0.28 + heat * 0.6}
              rx="1"
            />
            <text
              x={x + bw / 2}
              y={h - PAD.b + 12}
              textAnchor="middle"
              fontSize="9"
              fill="var(--color-ec-text-muted)"
              fontFamily="var(--color-ec-mono)"
            >
              {d.length}
            </text>
            {bh > 14 && (
              <text
                x={x + bw / 2}
                y={h - PAD.b - bh + 11}
                textAnchor="middle"
                fontSize="9"
                fill="var(--color-ec-text-high)"
                fontFamily="var(--color-ec-mono)"
              >
                {d.count}
              </text>
            )}
          </g>
        );
      })}
      <line
        x1={PAD.l}
        x2={W - PAD.r}
        y1={h - PAD.b}
        y2={h - PAD.b}
        stroke="var(--color-ec-border)"
        strokeWidth="0.5"
      />
      <text
        x={PAD.l - 7}
        y={h - PAD.b + 4}
        textAnchor="end"
        fontSize="9"
        fill="var(--color-ec-text-muted)"
        fontFamily="var(--color-ec-mono)"
      >
        0
      </text>
      <text
        x={W - PAD.r}
        y={PAD.t + 2}
        textAnchor="end"
        fontSize="9"
        fill="var(--color-ec-text-muted)"
        fontFamily="var(--color-ec-sans)"
      >
        perdidas consecutivas →
      </text>
    </ChartFrame>
  );
}
