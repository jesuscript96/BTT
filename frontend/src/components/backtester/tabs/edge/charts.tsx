"use client";

// Gráficos de la pestaña Edge. SVG a mano, sin librería: son pequeños, no
// necesitan interacción y así no cargan Recharts en un tab más.
//
// La rampa de color codifica el TIEMPO: los periodos viejos tiran a gris y el
// más reciente es cobre. Se construye con `color-mix` sobre los tokens para que
// siga funcionando si algún día hay tema claro.

import React from "react";
import { color, font } from "@/components/ui/tokens";
import { f1, f2, sgn, type PuntoBarrido, type PuntoMes } from "./calc";

export function rampa(i: number, n: number): string {
  if (n <= 1 || i === n - 1) return color.copper;
  const pct = Math.round(18 + (72 * i) / Math.max(1, n - 1));
  return `color-mix(in srgb, ${color.copper} ${pct}%, ${color.textMuted})`;
}

const T = {
  bd: color.border, mut: color.textMuted, sec: color.textSecondary,
  hi: color.textHigh, cop: color.copper, up: color.profit, dn: color.loss,
  wa: color.warning, surf: color.bgSurface, elev: color.bgElevated,
};

const Svg = ({ w, h, children }: { w: number; h: number; children: React.ReactNode }) => (
  <svg viewBox={`0 0 ${w} ${h}`} role="img"
       style={{ display: "block", width: "100%", height: "auto", fontFamily: font.sans }}>
    {children}
  </svg>
);
const Txt = ({ x, y, children, fill = T.sec, fs = 10.5, ta = "middle" as const, w, mono }:
  { x: number; y: number; children: React.ReactNode; fill?: string; fs?: number;
    ta?: "start" | "middle" | "end"; w?: number; mono?: boolean }) => (
  <text x={x} y={y} fill={fill} fontSize={fs} textAnchor={ta} fontWeight={w}
        style={mono ? { fontFamily: font.mono, fontVariantNumeric: "tabular-nums" } : undefined}>
    {children}
  </text>
);
const Rejilla = ({ x1, x2, y, label, ta = "end" as const, lx }:
  { x1: number; x2: number; y: number; label: string; ta?: "start" | "end"; lx: number }) => (
  <>
    <line x1={x1} y1={y} x2={x2} y2={y} stroke={T.bd} strokeWidth={1} strokeDasharray="2 3" />
    <Txt x={lx} y={y + 3.5} ta={ta} fs={10} mono>{label}</Txt>
  </>
);

/* ---- 1. Forest: valor central con su intervalo ---- */

export function Forest({ filas, unidad }: {
  filas: { etiqueta: string; v: number; lo: number; hi: number }[];
  unidad: string;
}) {
  const W = 460, H = Math.max(150, 46 + filas.length * 30), L = 78, R = 20, Tp = 24, B = 32;
  const vals = filas.flatMap((f) => [f.lo, f.hi, 0]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = (max - min) * 0.12 || 0.1;
  const lo = min - pad, hi = max + pad;
  const X = (v: number) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const ticks = [0, 1, 2, 3, 4].map((k) => lo + ((hi - lo) * k) / 4);
  return (
    <Svg w={W} h={H}>
      {ticks.map((v, i) => (
        <React.Fragment key={i}>
          <line x1={X(v)} y1={Tp} x2={X(v)} y2={H - B} stroke={T.bd} strokeWidth={1} strokeDasharray="2 3" />
          <Txt x={X(v)} y={H - B + 15} fs={9.5} mono>{sgn(v, 2)}</Txt>
        </React.Fragment>
      ))}
      {lo < 0 && hi > 0 && <line x1={X(0)} y1={Tp} x2={X(0)} y2={H - B} stroke={T.mut} strokeWidth={1.2} />}
      {filas.map((f, i) => {
        const y = Tp + 15 + i * ((H - B - Tp - 18) / Math.max(1, filas.length - 1 || 1));
        const c = rampa(i, filas.length);
        return (
          <React.Fragment key={f.etiqueta}>
            <line x1={X(f.lo)} y1={y} x2={X(f.hi)} y2={y} stroke={c} strokeWidth={2} />
            <line x1={X(f.lo)} y1={y - 4} x2={X(f.lo)} y2={y + 4} stroke={c} strokeWidth={2} />
            <line x1={X(f.hi)} y1={y - 4} x2={X(f.hi)} y2={y + 4} stroke={c} strokeWidth={2} />
            <circle cx={X(f.v)} cy={y} r={4} fill={c} stroke={T.surf} strokeWidth={1.5} />
            <Txt x={L - 10} y={y + 4} ta="end" fs={11} mono
                 fill={i === filas.length - 1 ? T.hi : T.sec}>{f.etiqueta}</Txt>
          </React.Fragment>
        );
      })}
      <Txt x={L + (W - L - R) / 2} y={H - 6} fs={10} fill={T.mut}>
        expectancy por operación ({unidad}) · la barra es el intervalo de confianza del 95 %
      </Txt>
    </Svg>
  );
}

/* ---- 2. Barras por periodo ---- */

export function Barras({ filas, sufijo, titulo }: {
  filas: { etiqueta: string; v: number }[]; sufijo: string; titulo: string;
}) {
  const W = 460, H = 190, L = 40, R = 14, Tp = 24, B = 28;
  const max = Math.max(1, ...filas.map((f) => f.v)) * 1.15;
  const paso = (W - L - R) / Math.max(1, filas.length);
  const Y = (v: number) => H - B - (v / max) * (H - B - Tp);
  const ancho = Math.min(46, paso * 0.62);
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
        <Rejilla key={i} x1={L} x2={W - R} y={Y(max * p)} lx={L - 7}
                 label={f1(max * p) + sufijo} />
      ))}
      <Txt x={L} y={Tp - 8} ta="start" fs={10} fill={T.mut}>{titulo}</Txt>
      {filas.map((f, i) => {
        const x = L + paso * i + paso / 2, c = rampa(i, filas.length);
        const alto = Math.max(0, H - B - Y(f.v));
        return (
          <React.Fragment key={f.etiqueta}>
            <rect x={x - ancho / 2} y={Y(f.v)} width={ancho} height={alto} fill={c} rx={2} />
            <Txt x={x} y={Y(f.v) - 6} fs={10.5} mono fill={c} w={600}>{f1(f.v) + sufijo}</Txt>
            <Txt x={x} y={H - B + 15} fs={10} mono
                 fill={i === filas.length - 1 ? T.hi : T.mut}>{f.etiqueta}</Txt>
          </React.Fragment>
        );
      })}
    </Svg>
  );
}

/* ---- 3. Oportunidad vs edge ---- */

export function Mensual({ serie, unidad }: { serie: PuntoMes[]; unidad: string }) {
  const W = 620, H = 230, L = 40, R = 44, Tp = 18, B = 34;
  if (serie.length < 2) return null;
  const n = serie.length, bw = (W - L - R) / n;
  const maxO = Math.max(...serie.map((p) => p.ops)) * 1.15 || 1;
  const Y1 = (v: number) => H - B - (v / maxO) * (H - B - Tp);
  const vs = serie.flatMap((p) => [p.media - p.ee, p.media + p.ee]);
  const elo = Math.min(0, ...vs), ehi = Math.max(...vs);
  const pad = (ehi - elo) * 0.1 || 0.1;
  const Y2r = (v: number) => H - B - ((v - (elo - pad)) / (ehi + pad - (elo - pad))) * (H - B - Tp);
  const Y2 = (v: number) => Math.max(Tp, Math.min(H - B, Y2r(v)));
  const px = (i: number) => L + bw * i + bw / 2;
  const banda =
    "M" + serie.map((p, i) => `${px(i)} ${Y2(p.media + p.ee)}`).join(" L ") +
    " L " + serie.map((p, i) => `${px(i)} ${Y2(p.media - p.ee)}`).reverse().join(" L ") + " Z";
  const linea = "M" + serie.map((p, i) => `${px(i)} ${Y2(p.media)}`).join(" L ");
  const anios = new Map<string, number>();
  serie.forEach((p, i) => { const a = p.mes.slice(0, 4); if (!anios.has(a)) anios.set(a, i); });
  return (
    <Svg w={W} h={H}>
      {[0, 0.5, 1].map((k, i) => {
        const v = (elo - pad) + (ehi + pad - (elo - pad)) * k;
        return <Rejilla key={i} x1={L} x2={W - R} y={Y2r(v)} lx={W - R + 6} ta="start" label={f2(v)} />;
      })}
      {elo < 0 && ehi > 0 && <line x1={L} y1={Y2(0)} x2={W - R} y2={Y2(0)} stroke={T.mut} strokeWidth={1} />}
      {serie.map((p, i) => (
        <rect key={p.mes} x={L + bw * i + 0.6} y={Y1(p.ops)}
              width={Math.max(1, bw - 1.4)} height={Math.max(0, H - B - Y1(p.ops))} fill={T.elev} />
      ))}
      <path d={banda} fill={T.cop} opacity={0.13} />
      <path d={linea} fill="none" stroke={T.cop} strokeWidth={1.8} strokeLinejoin="round" />
      <circle cx={px(n - 1)} cy={Y2(serie[n - 1].media)} r={3.2}
              fill={T.cop} stroke={T.surf} strokeWidth={1.5} />
      {[...anios.entries()].map(([a, i]) => (
        <React.Fragment key={a}>
          <line x1={L + bw * i} y1={Tp} x2={L + bw * i} y2={H - B} stroke={T.bd} strokeWidth={1} />
          <Txt x={L + bw * i + 3} y={H - B + 15} ta="start" fs={10} mono fill={T.mut}>{a}</Txt>
        </React.Fragment>
      ))}
      <Txt x={L - 4} y={Tp + 4} ta="end" fs={9.5} fill={T.mut}>ops</Txt>
      <Txt x={W - R + 6} y={Tp + 4} ta="start" fs={9.5} fill={T.cop}>{unidad}</Txt>
      <Txt x={L + (W - L - R) / 2} y={H - 6} fs={10} fill={T.mut}>
        barras: operaciones al mes · línea: expectancy de los últimos 6 meses ±1 error estándar
      </Txt>
    </Svg>
  );
}

/* ---- 4. MFE / MAE por periodo ---- */

export function Excursiones({ filas }: {
  filas: { etiqueta: string; mfeP: number[]; maeP: number[] }[];
}) {
  const W = 460, H = 210, L = 40, R = 14, Tp = 18, B = 28;
  const max = Math.max(...filas.flatMap((f) => [f.mfeP[3], f.maeP[3]])) * 1.12 || 1;
  const paso = (W - L - R) / Math.max(1, filas.length);
  const Y = (v: number) => H - B - (v / max) * (H - B - Tp);
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
        <Rejilla key={i} x1={L} x2={W - R} y={Y(max * p)} lx={L - 7} label={f1(max * p) + " %"} />
      ))}
      {filas.map((f, i) => {
        const cx = L + paso * i + paso / 2;
        return (
          <React.Fragment key={f.etiqueta}>
            {([[f.mfeP, T.up, -9], [f.maeP, T.dn, 9]] as const).map(([p, c, off], k) => (
              <React.Fragment key={k}>
                <line x1={cx + off} y1={Y(p[0])} x2={cx + off} y2={Y(p[3])} stroke={c} strokeWidth={1.2} />
                <rect x={cx + off - 6} y={Y(p[2])} width={12}
                      height={Math.max(1, Y(p[0]) - Y(p[2]))} fill={c} opacity={0.34} rx={1.5} />
                <line x1={cx + off - 7} y1={Y(p[1])} x2={cx + off + 7} y2={Y(p[1])}
                      stroke={T.hi} strokeWidth={1.8} />
              </React.Fragment>
            ))}
            <Txt x={cx} y={H - B + 15} fs={10} mono
                 fill={i === filas.length - 1 ? T.hi : T.mut}>{f.etiqueta}</Txt>
          </React.Fragment>
        );
      })}
    </Svg>
  );
}

/* ---- 5. Barrido (TP o SL) ---- */

export function Barrido({ series, unidad, ejeX, marcaActual }: {
  series: { etiqueta: string; puntos: PuntoBarrido[]; mejor: PuntoBarrido | null }[];
  unidad: string; ejeX: string; marcaActual?: number | null;
}) {
  const W = 460, H = 235, L = 46, R = 16, Tp = 20, B = 40;
  const todos = series.flatMap((s) => s.puntos.map((p) => p.v));
  if (!todos.length) return null;
  const x0 = series[0].puntos[0].x, x1 = series[0].puntos[series[0].puntos.length - 1].x;
  const vmin = Math.min(...todos), vmax = Math.max(...todos);
  const pad = (vmax - vmin) * 0.1 || 0.1;
  const lo = vmin - pad, hi = vmax + pad;
  const X = (x: number) => L + ((x - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v: number) => H - B - ((v - lo) / (hi - lo)) * (H - B - Tp);
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((k, i) => {
        const v = lo + (hi - lo) * k;
        return <Rejilla key={i} x1={L} x2={W - R} y={Y(v)} lx={L - 7} label={sgn(v, 2)} />;
      })}
      {lo < 0 && hi > 0 && <line x1={L} y1={Y(0)} x2={W - R} y2={Y(0)} stroke={T.mut} strokeWidth={1} />}
      {[0, 0.25, 0.5, 0.75, 1].map((k, i) => {
        const x = x0 + (x1 - x0) * k;
        return (
          <React.Fragment key={i}>
            <line x1={X(x)} y1={Tp} x2={X(x)} y2={H - B} stroke={T.bd} strokeWidth={1} />
            <Txt x={X(x)} y={H - B + 15} fs={10} mono>{f1(x)} %</Txt>
          </React.Fragment>
        );
      })}
      {marcaActual != null && marcaActual >= x0 && marcaActual <= x1 && (
        <>
          <line x1={X(marcaActual)} y1={Tp - 6} x2={X(marcaActual)} y2={H - B}
                stroke={T.wa} strokeWidth={1.5} strokeDasharray="4 3" />
          <Txt x={X(marcaActual)} y={Tp - 9} fs={9.5} mono fill={T.wa} w={600}>ahora</Txt>
        </>
      )}
      {series.map((s, i) => {
        const c = rampa(i, series.length);
        const ultimo = i === series.length - 1;
        return (
          <React.Fragment key={s.etiqueta}>
            <path d={"M" + s.puntos.map((p) => `${X(p.x).toFixed(1)} ${Y(p.v).toFixed(1)}`).join(" L ")}
                  fill="none" stroke={c} strokeWidth={ultimo ? 2.4 : 1.5} strokeLinejoin="round" />
            {s.mejor && (
              <circle cx={X(s.mejor.x)} cy={Y(s.mejor.v)} r={ultimo ? 4 : 3}
                      fill={c} stroke={T.surf} strokeWidth={1.4} />
            )}
          </React.Fragment>
        );
      })}
      <Txt x={L - 7} y={Tp - 5} ta="end" fs={9.5} fill={T.mut}>{unidad}</Txt>
      <Txt x={L + (W - L - R) / 2} y={H - 6} fs={10} fill={T.mut}>{ejeX}</Txt>
    </Svg>
  );
}

/* ---- 6. Envolvente de drawdown ---- */

export function Histograma({ hist, actual, p95, unidad }: {
  hist: { c: number; n: number }[]; actual: number; p95: number; unidad: string;
}) {
  const W = 460, H = 235, L = 30, R = 16, Tp = 30, B = 34;
  if (!hist.length) return null;
  const min = hist[0].c, max = hist[hist.length - 1].c;
  const span = max - min || 1;
  const maxN = Math.max(...hist.map((h) => h.n)) || 1;
  const X = (v: number) => L + ((v - min) / span) * (W - L - R);
  const Y = (n: number) => H - B - (n / (maxN * 1.2)) * (H - B - Tp);
  const bw = (W - L - R) / hist.length;
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((k, i) => {
        const v = min + span * k;
        return (
          <React.Fragment key={i}>
            <line x1={X(v)} y1={Tp} x2={X(v)} y2={H - B} stroke={T.bd} strokeWidth={1} strokeDasharray="2 3" />
            <Txt x={X(v)} y={H - B + 15} fs={10} mono>{f1(v)}</Txt>
          </React.Fragment>
        );
      })}
      {hist.map((h, i) => (
        <rect key={i} x={X(h.c) - bw / 2} y={Y(h.n)} width={Math.max(1, bw - 1.2)}
              height={Math.max(0, H - B - Y(h.n))} rx={1}
              fill={h.c <= p95 ? T.wa : T.elev} opacity={h.c <= p95 ? 0.55 : 1} />
      ))}
      <line x1={X(p95)} y1={Tp - 8} x2={X(p95)} y2={H - B} stroke={T.wa} strokeWidth={1.5} strokeDasharray="4 3" />
      <Txt x={X(p95)} y={Tp - 11} fs={9.5} mono fill={T.wa} w={600}>p95 {f1(p95)}</Txt>
      <line x1={X(actual)} y1={Tp + 4} x2={X(actual)} y2={H - B} stroke={T.cop} strokeWidth={2} />
      <circle cx={X(actual)} cy={Tp + 4} r={4} fill={T.cop} stroke={T.surf} strokeWidth={1.5} />
      <Txt x={X(actual)} y={Tp - 11} fs={9.5} mono fill={T.cop} w={600}>tú {f1(actual)}</Txt>
      <Txt x={L + (W - L - R) / 2} y={H - 6} fs={10} fill={T.mut}>
        peor caída en {unidad} de 2.000 reordenaciones de tus operaciones
      </Txt>
    </Svg>
  );
}
