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
/**
 * Cada cuantas etiquetas se pinta una. Con agrupacion por trimestre puede haber
 * 24 periodos en 460 px: sin esto las etiquetas se comen unas a otras y no se
 * lee ninguna. Se cuenta DESDE EL FINAL para que la ultima —la que importa—
 * salga siempre.
 */
function saltoEtiquetas(n: number, anchoPorItem: number, minPx = 32): number {
  if (n <= 1 || anchoPorItem >= minPx) return 1;
  return Math.ceil(minPx / Math.max(1, anchoPorItem));
}
const tocaEtiqueta = (i: number, n: number, salto: number) => (n - 1 - i) % salto === 0;

/**
 * Alto del viewBox de los dos graficos que van al lado de la tabla.
 *
 * Se acepta el alto que impone `useEncaje` (para que el eje X caiga en la ultima
 * fila de la tabla) pero ACOTADO: en un panel estrecho la columna se queda en
 * 90 px y la cuenta pedia un viewBox de 1.344 de alto, con el dibujo aplastado
 * en una franja ilegible. Fuera de la horquilla manda el alto natural.
 */
function altoUtil(h: number | undefined, n: number): number {
  const natural = Math.max(164, 60 + n * 30);
  if (!h) return natural;
  return Math.round(Math.min(natural * 1.9, Math.max(natural * 0.8, h)));
}

const Rejilla = ({ x1, x2, y, label, ta = "end" as const, lx }:
  { x1: number; x2: number; y: number; label: string; ta?: "start" | "end"; lx: number }) => (
  <>
    <line x1={x1} y1={y} x2={x2} y2={y} stroke={T.bd} strokeWidth={1} strokeDasharray="2 3" />
    <Txt x={lx} y={y + 3.5} ta={ta} fs={10} mono>{label}</Txt>
  </>
);

/* ---- 1. Forest: valor central con su intervalo ---- */

export function Forest({ filas, unidad, leyenda, extremos, h }: {
  filas: { etiqueta: string; v: number; lo: number; hi: number }[];
  unidad: string;
  /** Qué mide el eje. Por defecto, la expectancy. */
  leyenda?: string;
  /** Etiquetas de los dos lados del cero, cuando el signo significa algo. */
  extremos?: [string, string];
  /** Alto del viewBox impuesto desde fuera para cuadrar con la tabla de al
   *  lado. Ver `useAltoDe` en EdgeTab: un valor fijo no vale porque el alto
   *  renderizado depende del ancho de la columna. */
  h?: number;
}) {
  const W = 460, H = altoUtil(h, filas.length), L = 78, R = 20, Tp = 24, B = 46;
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
      {extremos && (
        <>
          <Txt x={X(lo + (hi - lo) * 0.22)} y={Tp - 9} fs={10} fill={T.mut}>{extremos[0]}</Txt>
          <Txt x={X(lo + (hi - lo) * 0.78)} y={Tp - 9} fs={10} fill={T.mut}>{extremos[1]}</Txt>
        </>
      )}
      <Txt x={L + (W - L - R) / 2} y={H - 6} fs={10} fill={T.mut}>
        {leyenda ?? `expectancy por operación (${unidad})`} · la barra es el intervalo de confianza del 95 %
      </Txt>
    </Svg>
  );
}

/* ---- 1b. Expectancy descompuesta: de donde sale el numero ---- */

/**
 * De donde sale la expectancy, en la MISMA disposicion que el forest de al lado:
 * un periodo por fila, en el mismo orden y a la misma altura. Asi se leen los
 * dos de un vistazo — el forest dice si el cambio es distinguible del ruido y
 * este dice por que lado viene.
 *
 * La geometria (H, Tp, B y la formula de la fila) es DELIBERADAMENTE identica a
 * la de `Forest`: si se toca una hay que tocar la otra o las filas dejan de
 * cuadrar entre los dos graficos.
 */
export function Descomposicion({ filas, h }: {
  filas: { etiqueta: string; aporta: number; resta: number; v: number }[];
  /** Igual que en `Forest`: alto del viewBox impuesto para cuadrar con la tabla. */
  h?: number;
}) {
  const W = 460, H = altoUtil(h, filas.length), L = 26, R = 26, Tp = 24, B = 46;
  if (!filas.length) return null;
  const max = Math.max(...filas.flatMap((f) => [f.aporta, f.resta])) * 1.12 || 1;
  const cx = L + (W - L - R) / 2;
  const X = (v: number) => cx + (v / max) * ((W - L - R) / 2);
  const alto = 13;
  return (
    <Svg w={W} h={H}>
      {[-1, -0.5, 0.5, 1].map((k, i) => (
        <React.Fragment key={i}>
          <line x1={X(max * k)} y1={Tp} x2={X(max * k)} y2={H - B}
                stroke={T.bd} strokeWidth={1} strokeDasharray="2 3" />
          <Txt x={X(max * k)} y={H - B + 15} fs={9.5} mono>{f1(Math.abs(max * k))}</Txt>
        </React.Fragment>
      ))}
      <line x1={cx} y1={Tp} x2={cx} y2={H - B} stroke={T.sec} strokeWidth={1.2} />
      {filas.map((f, i) => {
        const y = Tp + 15 + i * ((H - B - Tp - 18) / Math.max(1, filas.length - 1 || 1));
        return (
          <React.Fragment key={f.etiqueta}>
            <rect x={X(-f.resta)} y={y - alto / 2} width={Math.max(1, cx - X(-f.resta))}
                  height={alto} fill={T.dn} opacity={0.55} />
            <rect x={cx} y={y - alto / 2} width={Math.max(1, X(f.aporta) - cx)}
                  height={alto} fill={T.up} opacity={0.55} />
          </React.Fragment>
        );
      })}
      <Txt x={X(-max * 0.55)} y={Tp - 9} fs={9.5} fill={T.dn}>restan las perdedoras</Txt>
      <Txt x={X(max * 0.55)} y={Tp - 9} fs={9.5} fill={T.up}>aportan las ganadoras</Txt>
      <Txt x={cx} y={H - 6} fs={10} fill={T.mut}>
        misma escala a los dos lados · lo que queda es la diferencia
      </Txt>
    </Svg>
  );
}

/* ---- 2. Barras por periodo ---- */

export function Barras({ filas, sufijo, titulo }: {
  filas: { etiqueta: string; v: number; nota?: string }[]; sufijo: string; titulo: string;
}) {
  const W = 460, H = 206, L = 40, R = 14, Tp = 24, B = 42;
  const max = Math.max(1, ...filas.map((f) => f.v)) * 1.15;
  const paso = (W - L - R) / Math.max(1, filas.length);
  const Y = (v: number) => H - B - (v / max) * (H - B - Tp);
  const ancho = Math.min(46, paso * 0.62);
  const salto = saltoEtiquetas(filas.length, paso);
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
        const conEtiqueta = tocaEtiqueta(i, filas.length, salto);
        return (
          <React.Fragment key={f.etiqueta}>
            <rect x={x - ancho / 2} y={Y(f.v)} width={ancho} height={alto} fill={c} />
            {paso >= 38 && (
              <Txt x={x} y={Y(f.v) - 6} fs={10.5} mono fill={c} w={600}>{f1(f.v) + sufijo}</Txt>
            )}
            {conEtiqueta && (
              <>
                <Txt x={x} y={H - B + 15} fs={10} mono
                     fill={i === filas.length - 1 ? T.hi : T.mut}>{f.etiqueta}</Txt>
                {/* La segunda cifra es la que da sentido a la barra: sin ella no
                    se sabe si bajar la concentracion es bueno, o es que se esta
                    ganando menos y por eso depende de menos operaciones. */}
                {f.nota && (
                  <Txt x={x} y={H - B + 27} fs={9.5} mono fill={T.sec}>{f.nota}</Txt>
                )}
              </>
            )}
          </React.Fragment>
        );
      })}
    </Svg>
  );
}

/* ---- 3. Oportunidad vs edge ---- */

export function Mensual({ serie, unidad }: { serie: PuntoMes[]; unidad: string }) {
  // Igual que en Excursiones: abajo hay dos filas de texto, hace falta hueco.
  const W = 620, H = 242, L = 40, R = 44, Tp = 18, B = 44;
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
      {/* `bgElevated` sobre `bgSurface` no se veia: son dos grises casi iguales.
          El gris de texto al 45 % se lee sin competir con la linea de cobre. */}
      {serie.map((p, i) => (
        <rect key={p.mes} x={L + bw * i + 0.6} y={Y1(p.ops)}
              width={Math.max(1, bw - 1.4)} height={Math.max(0, H - B - Y1(p.ops))}
              fill={T.mut} opacity={0.45} />
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
  // B grande a proposito: abajo van DOS filas de texto (los periodos y el pie),
  // y con el margen de antes se pisaban.
  const W = 460, H = 232, L = 40, R = 14, Tp = 18, B = 44;
  const max = Math.max(...filas.flatMap((f) => [f.mfeP[3], f.maeP[3]])) * 1.12 || 1;
  const paso = (W - L - R) / Math.max(1, filas.length);
  const Y = (v: number) => H - B - (v / max) * (H - B - Tp);
  const salto = saltoEtiquetas(filas.length, paso);
  const cx = (i: number) => L + paso * i + paso / 2;
  // Las cajas sueltas no dejan ver la TENDENCIA, que es justo lo que se busca:
  // dos lineas por las medianas y el encogimiento salta a la vista.
  const linea = (sel: (f: typeof filas[number]) => number[], off: number) =>
    "M" + filas.map((f, i) => `${cx(i) + off} ${Y(sel(f)[1])}`).join(" L ");
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
        <Rejilla key={i} x1={L} x2={W - R} y={Y(max * p)} lx={L - 7} label={f1(max * p) + " %"} />
      ))}
      {filas.length > 1 && (
        <>
          <path d={linea((f) => f.mfeP, -9)} fill="none" stroke={T.up}
                strokeWidth={1.6} strokeDasharray="4 3" opacity={0.85} />
          <path d={linea((f) => f.maeP, 9)} fill="none" stroke={T.dn}
                strokeWidth={1.6} strokeDasharray="4 3" opacity={0.85} />
        </>
      )}
      {filas.map((f, i) => (
        <React.Fragment key={f.etiqueta}>
          {([[f.mfeP, T.up, -9], [f.maeP, T.dn, 9]] as const).map(([p, c, off], k) => (
            <React.Fragment key={k}>
              <line x1={cx(i) + off} y1={Y(p[0])} x2={cx(i) + off} y2={Y(p[3])} stroke={c} strokeWidth={1.2} />
              <rect x={cx(i) + off - 6} y={Y(p[2])} width={12}
                    height={Math.max(1, Y(p[0]) - Y(p[2]))} fill={c} opacity={0.34} />
              <line x1={cx(i) + off - 7} y1={Y(p[1])} x2={cx(i) + off + 7} y2={Y(p[1])}
                    stroke={T.hi} strokeWidth={1.8} />
            </React.Fragment>
          ))}
          {tocaEtiqueta(i, filas.length, salto) && (
            <Txt x={cx(i)} y={H - B + 15} fs={10} mono
                 fill={i === filas.length - 1 ? T.hi : T.mut}>{f.etiqueta}</Txt>
          )}
        </React.Fragment>
      ))}
      <Txt x={L + (W - L - R) / 2} y={H - 5} fs={10} fill={T.mut}>
        la línea de puntos une las medianas: es donde se ve si se encoge
      </Txt>
    </Svg>
  );
}

/* ---- 5. Barrido (TP o SL) ---- */

export function Barrido({ series, todas, unidad, ejeX, marcaActual }: {
  series: { etiqueta: string; puntos: PuntoBarrido[]; mejor: PuntoBarrido | null }[];
  /** Todas las series, para que el color de cada periodo NO cambie al ocultar
   *  otro: la rampa se calcula sobre la lista completa, no sobre la visible. */
  todas?: string[];
  unidad: string; ejeX: string; marcaActual?: number | null;
}) {
  const W = 460, H = 235, L = 46, R = 16, Tp = 20, B = 40;
  const orden = todas ?? series.map((s) => s.etiqueta);
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
      {series.map((s) => {
        const j = orden.indexOf(s.etiqueta);
        const c = rampa(j < 0 ? 0 : j, orden.length);
        const ultimo = j === orden.length - 1;
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

/* ---- 6. Curva de valor marginal (necesita el recorrido) ---- */

export const hhmm = (m: number) =>
  String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(Math.round(m) % 60).padStart(2, "0");

export function CurvaMarginal({ series, todas, unidad, marcas }: {
  series: { etiqueta: string; puntos: { m: number; media: number }[]; pico: number | null }[];
  /** Lista completa de periodos: el color de cada uno no debe moverse porque se
   *  oculte otro. */
  todas?: string[];
  unidad: string; marcas: number[];
}) {
  // Tp deja hueco arriba para la cajita de A/B, que sube 17 px si se juntan.
  // W grande y H contenido: es una serie temporal, necesita ancho, no alto.
  const W = 1100, H = 300, L = 54, R = 22, Tp = 46, B = 44;
  const todos = series.flatMap((s) => s.puntos);
  if (todos.length < 2) return null;
  const m0 = Math.min(...todos.map((p) => p.m)), m1 = Math.max(...todos.map((p) => p.m));
  const vmin = Math.min(...todos.map((p) => p.media)), vmax = Math.max(...todos.map((p) => p.media));
  const pad = (vmax - vmin) * 0.12 || 0.1;
  const lo = vmin - pad, hi = vmax + pad;
  const X = (m: number) => L + ((m - m0) / Math.max(1, m1 - m0)) * (W - L - R);
  const Y = (v: number) => H - B - ((v - lo) / (hi - lo)) * (H - B - Tp);
  const salto = Math.max(15, Math.round((m1 - m0) / 6 / 15) * 15);
  const ticks: number[] = [];
  for (let m = Math.ceil(m0 / salto) * salto; m <= m1; m += salto) ticks.push(m);
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((k, i) => {
        const v = lo + (hi - lo) * k;
        return <Rejilla key={i} x1={L} x2={W - R} y={Y(v)} lx={L - 9} label={sgn(v, 2)} />;
      })}
      {lo < 0 && hi > 0 && <line x1={L} y1={Y(0)} x2={W - R} y2={Y(0)} stroke={T.mut} strokeWidth={1} />}
      {ticks.map((m) => (
        <React.Fragment key={m}>
          <line x1={X(m)} y1={Tp} x2={X(m)} y2={H - B} stroke={T.bd} strokeWidth={1} />
          <Txt x={X(m)} y={H - B + 16} fs={10.5} mono>{hhmm(m)}</Txt>
        </React.Fragment>
      ))}
      {(() => {
        const vis = marcas.filter((m) => m >= m0 && m <= m1);
        return vis.map((m, i) => {
          // Con A y B pegadas las dos cajitas se pisaban: la segunda sube.
          const juntas = i > 0 && Math.abs(X(m) - X(vis[i - 1])) < 70;
          const dy = juntas ? -17 : 0;
          // La letra va DENTRO de la cajita. Antes iba suelta bajo el eje y se
          // chocaba con el pie del grafico.
          return (
            <React.Fragment key={`marca-${m}`}>
              <line x1={X(m)} y1={Tp - 6 + dy} x2={X(m)} y2={H - B}
                    stroke={T.cop} strokeWidth={1} strokeDasharray="3 3" />
              <rect x={X(m) - 32} y={Tp - 20 + dy} width={64} height={15} fill={T.elev} stroke={T.cop} />
              <Txt x={X(m)} y={Tp - 9 + dy} fs={10} mono fill={color.copperBright} w={600}>
                {(i === 0 ? "A " : "B ") + hhmm(m)}
              </Txt>
            </React.Fragment>
          );
        });
      })()}
      {series.map((s) => {
        const orden = todas ?? series.map((x) => x.etiqueta);
        const j = orden.indexOf(s.etiqueta);
        const c = rampa(j < 0 ? 0 : j, orden.length), ultimo = j === orden.length - 1;
        const pico = s.pico != null ? s.puntos.find((p) => p.m === s.pico) : null;
        return (
          <React.Fragment key={s.etiqueta}>
            <path d={"M" + s.puntos.map((p) => `${X(p.m).toFixed(1)} ${Y(p.media).toFixed(1)}`).join(" L ")}
                  fill="none" stroke={c} strokeWidth={ultimo ? 2.6 : 1.7}
                  strokeLinejoin="round" strokeLinecap="round" />
            {pico && <circle cx={X(pico.m)} cy={Y(pico.media)} r={ultimo ? 4.5 : 3.4}
                             fill={c} stroke={T.surf} strokeWidth={1.5} />}
          </React.Fragment>
        );
      })}
      <Txt x={L - 9} y={Tp - 8} ta="end" fs={10} fill={T.mut}>{unidad}</Txt>
      <Txt x={L + (W - L - R) / 2} y={H - 6} fs={10.5} fill={T.mut}>
        hora de salida (ET) - el punto marca donde deja de compensar aguantar
      </Txt>
    </Svg>
  );
}

/* ---- 7. Tiempo hasta el maximo a favor ---- */

export function Piruleta({ filas, sufijo, titulo }: {
  filas: { etiqueta: string; p: number[] }[]; sufijo: string; titulo: string;
}) {
  const W = 460, H = 205, L = 42, R = 16, Tp = 26, B = 30;
  const max = Math.max(...filas.flatMap((f) => f.p)) * 1.15 || 1;
  const paso = (W - L - R) / Math.max(1, filas.length);
  const Y = (v: number) => H - B - (v / max) * (H - B - Tp);
  const salto = saltoEtiquetas(filas.length, paso);
  return (
    <Svg w={W} h={H}>
      {[0, 0.25, 0.5, 0.75, 1].map((k, i) => (
        <Rejilla key={i} x1={L} x2={W - R} y={Y(max * k)} lx={L - 7} label={f1(max * k)} />
      ))}
      <Txt x={L} y={Tp - 9} ta="start" fs={10} fill={T.mut}>{titulo}</Txt>
      <path d={"M" + filas.map((f, i) => `${L + paso * i + paso / 2} ${Y(f.p[1])}`).join(" L ")}
            fill="none" stroke={T.bd} strokeWidth={1.5} strokeDasharray="3 3" />
      {filas.map((f, i) => {
        const x = L + paso * i + paso / 2, c = rampa(i, filas.length);
        return (
          <React.Fragment key={f.etiqueta}>
            <line x1={x} y1={Y(f.p[0])} x2={x} y2={Y(f.p[2])} stroke={c} strokeWidth={1.4} opacity={0.5} />
            <circle cx={x} cy={Y(f.p[1])} r={5} fill={c} stroke={T.surf} strokeWidth={1.5} />
            {paso >= 44 && (
              <Txt x={x} y={Y(f.p[1]) - 11} fs={10.5} mono fill={c} w={600}>{f1(f.p[1]) + sufijo}</Txt>
            )}
            {tocaEtiqueta(i, filas.length, salto) && (
              <Txt x={x} y={H - B + 15} fs={10} mono
                   fill={i === filas.length - 1 ? T.hi : T.mut}>{f.etiqueta}</Txt>
            )}
          </React.Fragment>
        );
      })}
    </Svg>
  );
}

/* ---- 8. Envolvente de drawdown ---- */

export function Histograma({ hist, actual, p95, unidad }: {
  hist: { c: number; n: number }[]; actual: number; p95: number; unidad: string;
}) {
  const W = 460, H = 244, L = 30, R = 16, Tp = 30, B = 44;
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
              height={Math.max(0, H - B - Y(h.n))}
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
