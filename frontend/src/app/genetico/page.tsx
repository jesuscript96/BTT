"use client";

// Pagina Genetico: configurar y lanzar corridas del algoritmo genetico de
// estrategias, seguirlas en vivo y llevarse los finalistas al Backtester.
// Todo lo que se elige aqui es la config de UNA corrida (nada es fijo).
//
// Estilo: hoja de datos. Sin tarjetas ni esquinas redondeadas; separadores
// hairline, controles cuadrados, cifras grandes directamente sobre el fondo,
// y un «?» con explicacion en cada parte (como el resto del programa).

import { useCallback, useEffect, useMemo, useState } from "react";
import { color, font, hairline } from "@/components/ui/tokens";
import { Table, Th, Td, Tr } from "@/components/ui";
import { Help } from "@/components/robustez/help";
import {
  PARAMETROS_UNIVERSO, DESCRIPCIONES_UNIVERSO, SECCIONES_UNIVERSO,
  construirFiltros, leeCondicion,
  type CondicionUniverso, type SeccionUniverso, type OperadorUniverso,
} from "@/lib/universoFiltros";
import {
  borrarCorrida,
  crearCorrida,
  getGenesEstrategia,
  getUniverso,
  type UniversoResp,
  type BloqueGenes,
  type GenGenetico,
  getCatalogo,
  guardarComoEstrategia,
  listarCorridas,
  pararCorrida,
  reanudarCorrida,
  verCorrida,
  type CatalogoGenetico,
  type CondicionMotor,
  type ConfigCorrida,
  type CorridaDetalle,
  type CorridaResumen,
  type Mejor,
} from "@/lib/api_genetico";

/* ── formato ─────────────────────────────────────────────────────────── */

// Formato propio, sin la API de locales del navegador: Node y Chrome no siempre
// traen el mismo ICU y el numero salia distinto en servidor y cliente -> error
// de hidratacion de Next. Asi el resultado es identico en los dos lados.
const miles = (entero: string) => entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
const n = (v: number | null | undefined, d = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const [ent, dec] = Math.abs(v).toFixed(d).split(".");
  return `${v < 0 ? "−" : ""}${miles(ent)}${dec ? `,${dec}` : ""}`;
};
const entero = (v: number | null | undefined) => n(v, 0);
const duracion = (s: number) => {
  if (!s || s < 0) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
};
const SEG_POR_EVAL = 25; // medido en esta maquina (fase 0)

/* ── primitivos sobrios (cuadrados, hairline) ────────────────────────── */

const control: React.CSSProperties = {
  background: color.bgSidebar, border: hairline, borderRadius: 0, color: color.textHigh,
  fontFamily: font.mono, fontSize: 12, padding: "5px 7px", width: "100%", outline: "none", height: 28,
};
const etiqueta: React.CSSProperties = {
  fontFamily: font.sans, fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.textMuted,
};

function Sec({ title, help, children, sinRelleno }: { title: string; help?: React.ReactNode; children: React.ReactNode; sinRelleno?: boolean }) {
  return (
    <section style={{ marginBottom: 14, border: `1px solid ${color.border}`, background: color.bgSurface }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderBottom: `1px solid ${color.border}`, background: color.bgElevated }}>
        <span style={{ ...etiqueta, color: color.textSecondary, fontSize: 10 }}>{title}</span>
        {help && <Help title={title}>{help}</Help>}
      </div>
      <div style={{ padding: sinRelleno ? 0 : "2px 10px 6px" }}>{children}</div>
    </section>
  );
}

/** Barra de progreso rectangular con etiquetas a los lados. */
function Barra({ pct, izq, der, activa }: { pct: number; izq: string; der: string; activa?: boolean }) {
  const p = Math.max(0, Math.min(100, pct));
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontFamily: font.sans, fontSize: 11.5, color: color.textSecondary }}>{izq}</span>
        <span style={{ fontFamily: font.mono, fontSize: 11.5, color: activa ? color.textHigh : color.textMuted }}>{der}</span>
      </div>
      <div style={{ height: 8, background: color.bgSidebar, border: `1px solid ${color.border}`, position: "relative" }}>
        <div style={{ width: `${p}%`, height: "100%", background: activa ? color.copper : color.textMuted, transition: "width .3s linear" }} />
      </div>
    </div>
  );
}

function Row({ label, help, children, wide }: { label: string; help?: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: wide ? "1fr" : "150px 1fr", gap: wide ? 4 : 10, alignItems: "center", padding: "5px 0", borderBottom: hairline }}>
      <span style={{ ...etiqueta, display: "flex", alignItems: "center", gap: 5 }}>{label}{help && <Help title={label}>{help}</Help>}</span>
      <div>{children}</div>
    </div>
  );
}

function Num({ value, onChange, min, max, step, disabled }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; disabled?: boolean }) {
  return <input type="number" style={{ ...control, opacity: disabled ? 0.5 : 1 }} value={value} min={min} max={max} step={step} disabled={disabled}
    onChange={(e) => onChange(Number(e.target.value))} />;
}

function Sel<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: Array<{ value: T; label: string }> }) {
  return (
    <select style={{ ...control, fontFamily: font.sans, cursor: "pointer" }} value={value} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function Toggle<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: Array<{ value: T; label: string }> }) {
  return (
    <div style={{ display: "flex", border: hairline }}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button key={o.value} type="button" onClick={() => onChange(o.value)} style={{
            flex: 1, height: 26, background: on ? color.bgElevated : "transparent", color: on ? color.textHigh : color.textSecondary,
            border: "none", borderLeft: i ? hairline : "none", borderBottom: on ? `2px solid ${color.copper}` : "2px solid transparent",
            fontFamily: font.sans, fontSize: 11.5, cursor: "pointer",
          }}>{o.label}</button>
        );
      })}
    </div>
  );
}

function Check({ checked, onChange, label, help }: { checked: boolean; onChange: (v: boolean) => void; label: string; help?: React.ReactNode }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 7, fontFamily: font.sans, fontSize: 12, color: color.textPrimary, cursor: "pointer", padding: "3px 0" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ margin: 0 }} />
      {label}{help && <Help title={label}>{help}</Help>}
    </label>
  );
}

function Btn({ onClick, children, danger, primary, disabled, title }: { onClick: () => void; children: React.ReactNode; danger?: boolean; primary?: boolean; disabled?: boolean; title?: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title} style={{
      background: primary ? color.copper : "transparent",
      color: primary ? "#1A0A00" : danger ? color.loss : color.textPrimary,
      border: primary ? `1px solid ${color.copper}` : `1px solid ${danger ? color.loss : color.border}`,
      borderRadius: 0, padding: "5px 12px", fontFamily: font.sans, fontSize: 11.5, fontWeight: primary ? 600 : 500,
      cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.45 : 1, height: 28, whiteSpace: "nowrap",
    }}>{children}</button>
  );
}

function Stat({ label, value, sub, help, tone }: { label: string; value: string; sub?: string; help?: React.ReactNode; tone?: "profit" | "loss" }) {
  return (
    <div style={{ padding: "6px 18px 6px 0", borderRight: hairline, minWidth: 120 }}>
      <div style={{ ...etiqueta, display: "flex", alignItems: "center", gap: 5 }}>{label}{help && <Help title={label}>{help}</Help>}</div>
      <div style={{ fontFamily: font.mono, fontSize: 22, lineHeight: 1.2, color: tone === "profit" ? color.profit : tone === "loss" ? color.loss : color.textHigh, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontFamily: font.sans, fontSize: 10.5, color: color.textMuted }}>{sub}</div>}
    </div>
  );
}

const th = (right?: boolean): React.CSSProperties => (right ? { textAlign: "right" } : {});
const tdNum: React.CSSProperties = { textAlign: "right", fontFamily: font.mono, fontSize: 12, whiteSpace: "nowrap", padding: "5px 10px" };
const tdTxt: React.CSSProperties = { fontSize: 12, padding: "5px 10px", color: color.textHigh };

/* ── config por defecto ──────────────────────────────────────────────── */

const RIESGO_DEFECTO: ConfigCorrida["riesgo"] = {
  init_cash: 50000, risk_r: 100, risk_type: "FIXED", fees: 0, fee_type: "PERCENT", slippage: 0,
  locates_cost: 0, max_locates: 0, size_by_sl: true, accept_reentries: true, max_reentries: -1,
};

/* ── Modo «mejorar»: leer y editar el rango de un gen ─────────────────────── */

function minutosAHora(m: number): string {
  const v = ((Math.round(m) % 1440) + 1440) % 1440;
  return `${String(Math.floor(v / 60)).padStart(2, "0")}:${String(v % 60).padStart(2, "0")}`;
}
function horaAMinutos(t: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(t.trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : 0;
}

/** Disparador de un parcial, en cristiano. El backend lo manda codificado
 *  (`pct:6`, `hora:10:30`, `tiempo:30`) para poder ordenarlo como rejilla. */
function leeDisparador(v: string): string | null {
  const m = /^(pct|hora|tiempo):(.+)$/.exec(v);
  if (!m) return null;
  if (m[1] === "pct") return `al +${m[2]} %`;
  if (m[1] === "hora") return `a las ${m[2]}`;
  return `a los ${m[2]} min`;
}

/** El valor de un gen, en la unidad en la que se lee. */
function leeValor(g: GenGenetico, v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "sí" : "no";
  if (typeof v === "string") {
    const d = leeDisparador(v);
    if (d) return d;
  }
  if (g.unit === "time_of_day") return minutosAHora(Number(v));
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(v);
  return String(v);
}

/** Desde / hasta / paso de un gen. Las horas se editan como horas, no como
 *  minutos desde medianoche — igual que en el optimizador 3D. */
function RangoGen({ gen, sel, set }: {
  gen: GenGenetico;
  sel: { on: boolean; min: number; max: number; step: number };
  set: (v: Partial<{ on: boolean; min: number; max: number; step: number }>) => void;
}) {
  const chico: React.CSSProperties = {
    background: "transparent", border: hairline, color: color.textHigh,
    fontFamily: font.mono, fontSize: 10, padding: "2px 4px", width: 62, outline: "none",
  };
  if (gen.unit === "time_of_day") {
    return (
      <>
        <input type="time" style={chico} value={minutosAHora(sel.min)}
          onChange={(e) => set({ min: horaAMinutos(e.target.value) })} />
        <span style={{ color: color.textMuted, fontSize: 10 }}>→</span>
        <input type="time" style={chico} value={minutosAHora(sel.max)}
          onChange={(e) => set({ max: horaAMinutos(e.target.value) })} />
        <input type="number" style={{ ...chico, width: 46 }} min={1} value={sel.step}
          title="paso en minutos" onChange={(e) => set({ step: Number(e.target.value) })} />
      </>
    );
  }
  return (
    <>
      <input type="number" style={chico} value={sel.min}
        onChange={(e) => set({ min: Number(e.target.value) })} />
      <span style={{ color: color.textMuted, fontSize: 10 }}>→</span>
      <input type="number" style={chico} value={sel.max}
        onChange={(e) => set({ max: Number(e.target.value) })} />
      <input type="number" style={{ ...chico, width: 46 }} step="any" value={sel.step}
        title="paso" onChange={(e) => set({ step: Number(e.target.value) })} />
    </>
  );
}

const COMPARADOR_CORTO: Record<string, string> = {
  GREATER_THAN: ">", LESS_THAN: "<",
  GREATER_THAN_OR_EQUAL: "≥", LESS_THAN_OR_EQUAL: "≤", EQUAL: "=",
};

/* ── La receta, estructurada ──────────────────────────────────────────────────
 *
 * Antes era UNA cadena con todo pegado («Entrada: X > 8 AND Y > 5 AND Z < 1 ·
 * Stop: … · TP: …») y con veinte filas no había forma de leerla. Jaume: «estaría
 * bien que estuvieran más estructuradas las condiciones que elige, no todo
 * apelotonado».
 *
 * Se pinta desde los DATOS, no parseando ese texto: `mejores.json` trae el
 * individuo entero y el config con las etiquetas. Parsear la cadena habría sido
 * frágil — cambia el formato y se rompe la tabla sin avisar.
 *
 * Dos formas de individuo, una por modo (ver genetico/especie.py). */

function Linea({ etq, val, antes }: { etq: string; val: string; antes?: string }) {
  const cambio = antes !== undefined && antes !== val;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 8, alignItems: "baseline" }}>
      <span style={{ color: color.textMuted, overflow: "hidden", textOverflow: "ellipsis" }}>{etq}</span>
      <span style={{ fontFamily: font.mono, color: cambio ? color.copper : color.textHigh, whiteSpace: "nowrap" }}>
        {cambio && <span style={{ color: color.textMuted, textDecoration: "line-through", marginRight: 5 }}>{antes}</span>}
        {val}
      </span>
    </div>
  );
}

/** «Entry % Fade Target Value» dentro del bloque ENTRADA es ruido: el bloque ya
 *  lo dice. Se quitan los prefijos que repiten. */
function etiquetaCorta(label: string): string {
  return String(label)
    .replace(/^Entry\s+/i, "").replace(/^Exit\s+/i, "")
    .replace(/\s*Target Value$/i, "").trim();
}

function Bloque({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 5 }}>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.06em", color: color.textMuted, opacity: 0.7 }}>{titulo}</div>
      {children}
    </div>
  );
}

const BLOQUES_ORDEN = ["entrada", "salida", "horas", "sesion", "stop", "tp", "parciales", "piramide", "reentradas", "guardas"];
const BLOQUES_TITULO: Record<string, string> = {
  entrada: "Entrada", salida: "Salida", horas: "Horas de entrada",
  sesion: "Sesión", stop: "Stop", tp: "Take profit", parciales: "Parciales",
  piramide: "Pirámide", reentradas: "Reentradas", guardas: "Guardas",
};

/** Valor de un gen tal y como se lee (hora, disparador, sí/no o número). */
function valorGen(g: any, v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "sí" : "no";
  if (typeof v === "string") {
    const d = leeDisparador(v);
    if (d) return d;
    return v;
  }
  if (g?.unit === "time_of_day") return minutosAHora(Number(v));
  const num = Number(v);
  return Number.isInteger(num) ? String(num) : String(num);
}

/** Cuantos parciales usa de verdad un candidato. Los genes `parciales.i.nivel`
 *  guardan un valor SIEMPRE, pero solo los `i < n` se escriben en la
 *  estrategia: `a_definicion` ignora el resto. Pintarlos todos hacia creer que
 *  el genetico habia elegido cerrar «al +3 %» cuando no cierra nada. */
function parcialesActivos(ind: any, genes: any[]): number {
  const g = genes.find((x) => x.id === "parciales.n");
  const v = ind?.valores?.["parciales.n"];
  const n = v !== undefined ? v : g?.current_value;
  return Math.max(0, Number(n ?? 0));
}

/** Indice del gen `parciales.N.nivel`, o null. */
function idxParcial(id: string): number | null {
  const m = /^parciales\.(\d+)\.nivel$/.exec(String(id));
  return m ? Number(m[1]) : null;
}

/** Si un candidato acepta reentradas. Cuando NO, el gen `riesgo.max_reentries`
 *  sigue llevando un numero —el genetico lo mueve igual, porque no sabe que ahi
 *  no sirve de nada— pero el motor ni lo mira. Pintarlo dejaba la ficha
 *  diciendo «Acepta reentradas: no  ·  Maximo de reentradas: 2», que es
 *  exactamente lo que Jaume leyo y no cuadraba. Mismo caso que los parciales
 *  con n = 0.
 *  Si no hay gen de reentradas, manda la estrategia y aqui no se sabe: se
 *  devuelve true para NO esconder algo que quiza si aplica. */
function aceptaReentradas(ind: any, genes: any[]): boolean {
  const g = genes.find((x) => x.id === "riesgo.accept_reentries");
  const v = ind?.valores?.["riesgo.accept_reentries"];
  const x = v !== undefined ? v : g?.current_value;
  if (x === undefined || x === null) return true;
  return !(x === false || x === 0 || String(x).toLowerCase() === "false" || String(x) === "no");
}

/** Lo que hace DISTINTO a este candidato, en una linea. Es lo que se ve con la
 *  fila plegada: en modo mejorar, los genes que cambiaron respecto a la
 *  estrategia original; en explorar, los indicadores de la entrada. */
function resumenCorto(mejor: Mejor, config: any): string {
  const ind: any = mejor.individuo;
  if (String(config?.modo ?? "explorar") === "mejorar" && ind?.valores) {
    const genes: any[] = config?.genes ?? [];
    const nParc = parcialesActivos(ind, genes);
    const reent = aceptaReentradas(ind, genes);
    const cambios = genes
      .filter((g) => {
        const ip = idxParcial(g.id);
        if (ip !== null && ip >= nParc) return false;   // parcial que no se usa
        if (g.id === "riesgo.max_reentries" && !reent) return false;   // no reentra
        return g.current_value !== undefined && ind.valores[g.id] !== undefined
          && valorGen(g, ind.valores[g.id]) !== valorGen(g, g.current_value);
      })
      .map((g) => `${etiquetaCorta(g.label)} ${valorGen(g, g.current_value)}→${valorGen(g, ind.valores[g.id])}`);
    if (!cambios.length) return "igual que la original";
    return cambios.slice(0, 3).join("  ·  ") + (cambios.length > 3 ? `  ·  +${cambios.length - 3}` : "");
  }
  if (ind?.condiciones) {
    return ind.condiciones.map((c: any) => c.ind).join("  ·  ");
  }
  return mejor.receta.slice(0, 90);
}

function RecetaEstructurada({ mejor, config }: { mejor: Mejor; config: any }) {
  const ind: any = mejor.individuo;

  // ── Modo MEJORAR: genes por bloque, con lo que cambió respecto a la semilla
  if (String(config?.modo ?? "explorar") === "mejorar" && ind?.valores) {
    const genes: any[] = config?.genes ?? [];
    const porBloque = new Map<string, any[]>();
    for (const g of genes) {
      const b = g.bloque ?? "stop";
      if (!porBloque.has(b)) porBloque.set(b, []);
      porBloque.get(b)!.push(g);
    }
    const orden = BLOQUES_ORDEN.filter((b) => porBloque.has(b));
    const nParciales = parcialesActivos(ind, genes);
    const reentradas = aceptaReentradas(ind, genes);
    return (
      <div style={{ fontSize: 11, lineHeight: 1.5 }}>
        {orden.map((b) => (
          <Bloque key={b} titulo={BLOQUES_TITULO[b] ?? b}>
            {porBloque.get(b)!.map((g) => {
              const v = ind.valores[g.id];
              if (v === undefined) return null;
              const ip = idxParcial(g.id);
              if (ip !== null && ip >= nParciales) return null;   // no se usa
              if (g.id === "riesgo.max_reentries" && !reentradas) return null;
              return (
                <Linea key={g.id} etq={etiquetaCorta(g.label)}
                  val={valorGen(g, v)}
                  antes={g.current_value !== undefined ? valorGen(g, g.current_value) : undefined} />
              );
            })}
            {b === "parciales" && nParciales === 0 && (
              <div style={{ fontSize: 10, color: color.textMuted, fontStyle: "italic" }}>
                sin parciales: cierra con el take profit entero
              </div>
            )}
            {b === "reentradas" && !reentradas && (
              <div style={{ fontSize: 10, color: color.textMuted, fontStyle: "italic" }}>
                no reentra: el máximo de reentradas no se aplica
              </div>
            )}
          </Bloque>
        ))}
      </div>
    );
  }

  // ── Modo EXPLORAR: condiciones, stop, take profit y parciales
  if (ind?.condiciones) {
    const s = ind.stop ?? {};
    const leeTp = (t: any) => t?.modo === "hora" ? `a las ${t.valor}`
      : t?.modo === "tiempo" ? `a los ${t.valor} min` : `${t?.valor}%`;
    return (
      <div style={{ fontSize: 11, lineHeight: 1.5 }}>
        <Bloque titulo={`Entrada · ${ind.condiciones.length} condiciones (AND)`}>
          {ind.condiciones.map((c: any, i: number) => {
            const ps = Object.entries(c.params ?? {}).filter(([, v]) => v !== null && v !== undefined)
              .map(([, v]) => String(v)).join(", ");
            const obj = typeof c.objetivo === "object" && c.objetivo
              ? c.objetivo.ind : String(c.objetivo);
            return <Linea key={i} etq={ps ? `${c.ind} (${ps})` : c.ind}
              val={`${COMPARADOR_CORTO[c.comp] ?? c.comp} ${obj}`} />;
          })}
        </Bloque>
        <Bloque titulo="Stop">
          <Linea etq={s.modo === "pct" ? "Distancia" : `${s.nivel} ${s.operador}`}
            val={s.modo === "pct" ? `${s.valor}%` : `+${s.offset_pct}%`} />
        </Bloque>
        <Bloque titulo="Take profit"><Linea etq="Objetivo" val={leeTp(ind.tp)} /></Bloque>
        {(ind.parciales ?? []).length > 0 && (
          <Bloque titulo="Parciales">
            {ind.parciales.map((p: any, i: number) => (
              <Linea key={i} etq={`Cierra ${p.cierre_pct}%`} val={leeTp(p)} />
            ))}
          </Bloque>
        )}
      </div>
    );
  }

  // Forma desconocida: mejor el texto de siempre que una celda vacía.
  return <span style={{ fontSize: 11 }}>{mejor.receta}</span>;
}

function guardaMotor(nombre: string, comparador: string, valor: number): CondicionMotor {
  return { type: "indicator_comparison", source: { name: nombre, offset: 0 }, comparator: comparador, target: valor, timeframe: "1m" };
}

/* ── pagina ──────────────────────────────────────────────────────────── */

export default function GeneticoPage() {
  const [catalogo, setCatalogo] = useState<CatalogoGenetico | null>(null);
  const [corridas, setCorridas] = useState<CorridaResumen[]>([]);
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<CorridaDetalle | null>(null);
  /* Filas desplegadas de la tabla de mejores, por huella. Plegadas por defecto:
     con 20 filas, la receta entera desplegada llena tres pantallas. */
  const [abiertas, setAbiertas] = useState<Set<string>>(new Set());
  const [comparar, setComparar] = useState<string | null>(null);
  const [detalleB, setDetalleB] = useState<CorridaDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lanzando, setLanzando] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);

  // ── formulario ──
  const [nombre, setNombre] = useState("");
  /* ── Modo «mejorar» (6-sep-2026) ──────────────────────────────────────────
     El explorador se queda EXACTAMENTE como estaba; esto es un modo al lado.
     `modo` decide qué secciones se pintan y qué config se manda. */
  const [modo, setModo] = useState<"explorar" | "mejorar">("explorar");
  const [estrategias, setEstrategias] = useState<Array<{ id: string; name: string; dataset_id?: string | null }>>([]);
  const [estrategiaId, setEstrategiaId] = useState("");
  const [bloquesGenes, setBloquesGenes] = useState<BloqueGenes[]>([]);
  const [cargandoGenes, setCargandoGenes] = useState(false);
  /* Por gen: si se mueve y en qué rango. El rango lo elige el usuario, igual
     que en el optimizador 3D — el backend solo PROPONE ±2 escalones. */
  /* Por gen: si se mueve, en qué rango (numéricos) o con qué opciones
     (categóricos). `opciones` sin poner = todas, que es el defecto. */
  const [genesSel, setGenesSel] = useState<Record<string, { on: boolean; min: number; max: number; step: number; opciones?: string[] }>>({});
  /* Qué gen tiene abierto el selector de opciones. Uno cada vez: con cinco
     parciales × 20 opciones, abrirlos todos llena la pantalla. */
  const [genAbierto, setGenAbierto] = useState<string | null>(null);
  const [agregacion, setAgregacion] = useState("valor");
  const [trozos, setTrozos] = useState(4);
  /* Las fechas NO tienen control propio: son el «rango de fechas global» del
     cuadro de universo. Tener dos sitios donde poner el periodo (aquí y allí)
     era pedir que se contradijeran — Jaume: «no te compliques, ese rango de
     fechas global es el IS». */
  const [sesgo, setSesgo] = useState<"short" | "long">("short");
  const [sesion, setSesion] = useState<"rth" | "pre" | "custom">("rth");
  const [horaIni, setHoraIni] = useState("04:00");
  const [horaFin, setHoraFin] = useState("08:00");
  const [ventanaOn, setVentanaOn] = useState(false);
  const [ventanaDe, setVentanaDe] = useState("09:35");
  const [ventanaA, setVentanaA] = useState("11:00");
  /** Guardas fijas, por clave del catálogo. La lista la manda el backend, así
   *  que añadir una guarda nueva no toca esta pantalla. Los valores de partida
   *  son los de las estrategias de Jaume. */
  const [guardas, setGuardas] = useState<Record<string, { on: boolean; valor: number }>>({
    precio: { on: true, valor: 0.7 },
    volumen_acum: { on: true, valor: 1_000_000 },
    dollar_volume: { on: false, valor: 100_000 },
    pm_high_gap: { on: false, valor: 50 },
  });
  const ponGuarda = (clave: string, cambio: Partial<{ on: boolean; valor: number }>) =>
    setGuardas((g) => ({ ...g, [clave]: { ...(g[clave] ?? { on: false, valor: 0 }), ...cambio } }));

  const [indicadores, setIndicadores] = useState<Record<string, boolean>>({});
  /** Pestaña de indicadores abierta. Con dos docenas en la lista, plana no se
   *  puede leer; por familias se marca «volumen» de un vistazo. */
  const [familia, setFamilia] = useState<string>("precio");
  const [nCond, setNCond] = useState<"1" | "2" | "3">("2");
  const [stopPct, setStopPct] = useState(true);
  const [stopEstructura, setStopEstructura] = useState(true);
  const [tpPct, setTpPct] = useState(true);
  const [tpHora, setTpHora] = useState(true);
  const [tpTiempo, setTpTiempo] = useState(false);
  const [riesgo, setRiesgo] = useState(RIESGO_DEFECTO);
  const [fitness, setFitness] = useState("expR_sqrtN");
  const [minTrades, setMinTrades] = useState(100);
  const [semilla, setSemilla] = useState(42);
  const [poblacion, setPoblacion] = useState(80);
  const [generaciones, setGeneraciones] = useState(40);
  const [workers, setWorkers] = useState(0);
  const [paciencia, setPaciencia] = useState(12);
  const [pararALas, setPararALas] = useState("09:00");
  const [pararALasOn, setPararALasOn] = useState(true);

  /* carga inicial */
  useEffect(() => {
    getCatalogo()
      .then((c) => {
        setCatalogo(c);
        // Solo los que el catalogo marca por defecto: los siete de la v1.
        // Marcar los 26 dispararia el espacio de busqueda y contradice lo
        // que dice esta misma pantalla: cada indicador que no aporta anyade
        // formas de encontrar casualidades.
        setIndicadores(Object.fromEntries(c.indicadores.map((i) => [i.nombre, i.por_defecto])));
      })
      .catch((e) => setError(`No cargó el catálogo: ${String(e)}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refrescarLista = useCallback(() => {
    listarCorridas().then((l) => {
      setCorridas(l);
      setSeleccion((s) => s ?? (l[0]?.id ?? null));
    }).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => { refrescarLista(); }, [refrescarLista]);

  /* detalle + sondeo mientras viva (solo lee JSON en disco, no DuckDB) */
  useEffect(() => {
    if (!seleccion) { setDetalle(null); return; }
    let vivo = true;
    const carga = () => verCorrida(seleccion).then((d) => { if (vivo) { setDetalle(d); refrescarLista(); } }).catch((e) => { if (vivo) setError(String(e)); });
    carga();
    const t = setInterval(() => { if (detalle?.vivo || !detalle) carga(); }, 4000);
    return () => { vivo = false; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seleccion, detalle?.vivo]);

  useEffect(() => {
    if (!comparar) { setDetalleB(null); return; }
    verCorrida(comparar).then(setDetalleB).catch((e) => setError(String(e)));
  }, [comparar]);

  /* Estrategias guardadas: solo hacen falta en el modo «mejorar». */
  useEffect(() => {
    if (modo !== "mejorar" || estrategias.length) return;
    import("@/lib/api_backtester")
      .then((m) => m.fetchStrategies())
      .then((lista: any[]) => setEstrategias(lista.map((x) => ({
        id: x.id, name: x.name, dataset_id: x.dataset_id ?? x.definition?.dataset_id ?? null,
      }))))
      .catch(() => setError("No pude cargar las estrategias guardadas"));
  }, [modo, estrategias.length]);

  /* Los genes de la estrategia elegida. Se piden al backend, que los saca del
     mismo extractor que alimenta el optimizador 3D. */
  useEffect(() => {
    if (modo !== "mejorar" || !estrategiaId) { setBloquesGenes([]); return; }
    let vivo = true;
    setCargandoGenes(true);
    getGenesEstrategia(estrategiaId)
      .then((r) => {
        if (!vivo) return;
        setBloquesGenes(r.bloques || []);
        /* Todo empieza DESMARCADO: marcar por defecto sería mover cosas que el
           usuario no ha pedido. El rango propuesto sí se precarga. */
        const inicial: Record<string, { on: boolean; min: number; max: number; step: number }> = {};
        for (const b of r.bloques || []) {
          for (const g of b.genes) {
            inicial[g.id] = {
              on: false,
              min: Number(g.min ?? 0),
              max: Number(g.max ?? 0),
              step: Number(g.step ?? 1),
            };
          }
        }
        setGenesSel(inicial);
      })
      .catch(() => setError("No pude leer los parámetros de esa estrategia"))
      .finally(() => { if (vivo) setCargandoGenes(false); });
    return () => { vivo = false; };
  }, [modo, estrategiaId]);

  /* EL UNIVERSO, en vivo. Sustituye al selector de dataset: las guardas y las
     fechas lo definen, y aquí se ve cuántos ticker-días salen ANTES de lanzar.
     Con retardo, porque cada tecleo en una guarda dispararía una consulta. */
  const [universo, setUniverso] = useState<UniversoResp | null>(null);
  const [calculandoUniverso, setCalculandoUniverso] = useState(false);
  /* Los filtros de universo, con la MISMA forma y las MISMAS opciones que al
     crear un dataset en el backtester. No se traduce nada: viajan tal cual.
     Su rango de fechas ES el periodo IS de la corrida. */
  const [condUniverso, setCondUniverso] = useState<CondicionUniverso[]>([]);
  const [uDesde, setUDesde] = useState("2019-01-01");
  const [uHasta, setUHasta] = useState("2024-12-31");
  /* La fila para añadir una condición. */
  const [uSec, setUSec] = useState<SeccionUniverso>("gap_day");
  const [uParam, setUParam] = useState(PARAMETROS_UNIVERSO[4].key);   // Gap %
  const [uOp, setUOp] = useState<OperadorUniverso>(">=");
  const [uVal1, setUVal1] = useState(50);
  const [uVal2, setUVal2] = useState(0);

  const filtrosUniverso = useMemo(
    () => (condUniverso.length ? construirFiltros(condUniverso, uDesde, uHasta) : null),
    [condUniverso, uDesde, uHasta]);
  const fechaIni = uDesde;
  const fechaFin = uHasta;

  /* Cuántos parciales como MUCHO va a haber. Manda sobre qué filas de
     «Parcial N» tienen sentido: marcar el disparador del 4º cuando el rango
     llega a 2 no haría nada — el gen viajaría y `a_definicion` lo ignoraría,
     que es justo el tipo de ajuste fantasma que no da error. */
  const maxParciales = useMemo(() => {
    const gen = bloquesGenes.flatMap((b) => b.genes).find((g) => g.id === "parciales.n");
    if (!gen) return 0;
    const sel = genesSel["parciales.n"];
    return sel?.on ? Number(sel.max) : Number(gen.current_value ?? 0);
  }, [bloquesGenes, genesSel]);

  /** Índice del gen «parciales.N.nivel», o null si no lo es. */
  const indiceParcial = (id: string): number | null => {
    const m = /^parciales\.(\d+)\.nivel$/.exec(id);
    return m ? Number(m[1]) : null;
  };

  /* Los genes marcados, en el formato que espera el backend. */
  const genesMarcados: GenGenetico[] = useMemo(() => {
    const out: GenGenetico[] = [];
    for (const b of bloquesGenes) {
      for (const g of b.genes) {
        const sel = genesSel[g.id];
        if (!sel?.on) continue;
        const ip = indiceParcial(g.id);
        if (ip !== null && ip >= maxParciales) continue;   // fuera del tope
        out.push(g.opciones
          // Categórico: van SOLO las opciones que el usuario deja. `afinar`
          // usa esta lista tal cual como rejilla del gen.
          ? { ...g, opciones: sel.opciones ?? g.opciones }
          : { ...g, min: sel.min, max: sel.max, step: sel.step });
      }
    }
    return out;
  }, [bloquesGenes, genesSel, maxParciales]);

  /* Cuantas combinaciones hay en el espacio marcado. No es lo que el genetico
     recorre — es la medida de si hace falta un genetico o basta el 3D. */
  const combinaciones = useMemo(() => {
    let n = 1;
    for (const g of genesMarcados) {
      if (g.opciones) { n *= g.opciones.length; continue; }
      const paso = Number(g.step) || 1;
      n *= Math.max(1, Math.floor((Number(g.max) - Number(g.min)) / paso) + 1);
      if (n > 1e12) return 1e12;
    }
    return n;
  }, [genesMarcados]);

  /* config que se manda */
  const config: ConfigCorrida & { parar_a_las?: string | null } = useMemo(() => {
    // Las guardas activas, en el orden del catálogo. Se arman desde la lista
    // que manda el backend: una guarda nueva allí aparece aquí sola.
    const guardasMotor: CondicionMotor[] = (catalogo?.guardas ?? [])
      .filter((g) => guardas[g.clave]?.on)
      .map((g) => guardaMotor(g.indicador, g.comparador, guardas[g.clave].valor));
    return {
      fecha_ini: fechaIni || null, fecha_fin: fechaFin || null,
      universo: filtrosUniverso,
      sesgo, sesiones: [sesion],
      hora_ini: sesion === "custom" ? horaIni : null, hora_fin: sesion === "custom" ? horaFin : null,
      ventana_entrada: ventanaOn ? [{ from_time: ventanaDe, to_time: ventanaA }] : null,
      guardas: guardasMotor,
      catalogo: Object.entries(indicadores).filter(([, v]) => v).map(([k]) => k),
      n_condiciones: Number(nCond),
      stops: [...(stopPct ? ["pct"] : []), ...(stopEstructura ? ["estructura"] : [])],
      tps: [...(tpPct ? ["pct"] : []), ...(tpHora ? ["hora"] : []), ...(tpTiempo ? ["tiempo"] : [])],
      riesgo, fitness, min_trades: minTrades, semilla, poblacion, generaciones, workers, paciencia,
      parar_a_las: pararALasOn ? pararALas : null,
      // Modo «mejorar». En «explorar» estas claves no viajan y el backend se
      // comporta exactamente igual que antes de existir el modo.
      ...(modo === "mejorar"
        ? { modo, estrategia_id: estrategiaId, genes: genesMarcados, agregacion, trozos }
        : {}),
    };
  }, [filtrosUniverso, fechaIni, fechaFin, sesgo, sesion, horaIni, horaFin, ventanaOn, ventanaDe, ventanaA,
    catalogo, guardas, indicadores, nCond, stopPct, stopEstructura, tpPct, tpHora, tpTiempo, riesgo, fitness, minTrades,
    semilla, poblacion, generaciones, workers, paciencia, pararALas, pararALasOn,
    modo, estrategiaId, genesMarcados, agregacion, trozos]);

  useEffect(() => {
    if (!fechaIni || !fechaFin || condUniverso.length === 0) {
      setUniverso(null);
      return;
    }
    let vivo = true;
    setCalculandoUniverso(true);
    const t = window.setTimeout(() => {
      getUniverso(config)
        .then((u) => { if (vivo) setUniverso(u); })
        .catch(() => { if (vivo) setUniverso(null); })
        .finally(() => { if (vivo) setCalculandoUniverso(false); });
    }, 700);
    return () => { vivo = false; window.clearTimeout(t); };
    // Solo las claves que cambian el universo: guardas y fechas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fechaIni, fechaFin, JSON.stringify(condUniverso)]);

  const estimacion = useMemo(() => {
    const elite = Math.max(1, Math.round(poblacion * 0.05));
    const evals = Math.round(poblacion + generaciones * (poblacion - elite) * 0.65);
    return { evals, con1: evals * SEG_POR_EVAL, con2: evals * SEG_POR_EVAL / 2, con4: evals * SEG_POR_EVAL / 4 };
  }, [poblacion, generaciones]);

  const problemas: string[] = [];
  if (!fechaIni || !fechaFin) problemas.push("pon el periodo IS");
  if (condUniverso.length === 0) problemas.push("define el universo");
  if (universo?.pares != null && universo.pares > universo.tope) problemas.push("el universo se pasa del tope");
  if (modo === "mejorar") {
    if (!estrategiaId) problemas.push("elige la estrategia que quieres mejorar");
    if (genesMarcados.length === 0) problemas.push("marca al menos un parámetro que mover");
    for (const g of genesMarcados) {
      if (g.opciones) continue;
      if (Number(g.max) < Number(g.min)) problemas.push(`«${g.label}»: el máximo es menor que el mínimo`);
      if (!Number(g.step)) problemas.push(`«${g.label}»: el paso no puede ser 0`);
    }
  } else {
    if (config.catalogo.length === 0) problemas.push("marca algún indicador");
    if (config.catalogo.length < config.n_condiciones) problemas.push("más indicadores que condiciones");
    if (config.stops.length === 0) problemas.push("marca algún tipo de stop");
    if (config.tps.length === 0) problemas.push("marca algún tipo de take profit");
  }

  const lanzar = async () => {
    setLanzando(true); setError(null); setAviso(null);
    try {
      const r = await crearCorrida(config, nombre || undefined);
      setAviso(`Corrida ${r.id} lanzada (pid ${r.pid}, ${entero(r.pares_dataset)} ticker-días en el dataset).`);
      setNombre("");
      refrescarLista();
      setSeleccion(r.id);
    } catch (e) {
      setError(`No se pudo lanzar: ${String(e)}`);
    } finally {
      setLanzando(false);
    }
  };

  const accion = async (f: () => Promise<unknown>, ok: string) => {
    setError(null);
    try { await f(); setAviso(ok); refrescarLista(); if (seleccion) setDetalle(await verCorrida(seleccion)); }
    catch (e) { setError(String(e)); }
  };

  const guardar = async (m: Mejor, i: number) => {
    if (!detalle) return;
    const nombreEst = window.prompt("Nombre de la estrategia", `GA ${detalle.config.nombre ?? detalle.id} #${i + 1} [${m.huella}]`);
    if (!nombreEst) return;
    const desc = `${m.receta} · fitness ${n(m.fitness)} · IS ${detalle.config.fecha_ini}→${detalle.config.fecha_fin} · riesgo ${JSON.stringify(detalle.config.riesgo)}`;
    // Sin dataset (el universo ahora son las guardas) la estrategia se
    // guarda sin universo atado: se elige al abrirla en el Backtester.
    const ds = detalle.config.dataset_id ?? "";
    await accion(() => guardarComoEstrategia(nombreEst, desc, m.definicion, ds),
      ds ? `Guardada «${nombreEst}»: ábrela en el Backtester.`
         : `Guardada «${nombreEst}». Al abrirla en el Backtester elige el universo: esta corrida no usó dataset.`);
  };

  const est = detalle?.estado ?? {};
  const historial = est.historial ?? [];

  return (
    <div style={{ display: "flex", gap: 28, padding: "16px 22px", minHeight: "100vh", background: color.bgBase, color: color.textPrimary, fontFamily: font.sans }}>
      {/* ── configuración ── */}
      <div style={{ width: 430, flexShrink: 0 }}>
        <div style={{ paddingBottom: 10, marginBottom: 12, borderBottom: `1px solid ${color.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: color.textHigh }}>Genético</span>
            <Help title="Genético">
              Busca estrategias simples combinando indicadores, stops y take profits. Cada candidato se evalúa con un backtest real del motor
              (el mismo que el Backtester), así que lo que sale aquí es lo que sale allí. Corre en un proceso aparte: puedes cerrar la página
              y volver. Regla: solo con el bot de alertas apagado.
            </Help>
          </div>
          <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>Configuración de la corrida. Nada de esto es fijo.</div>
        </div>

        {error && <div style={{ borderLeft: `2px solid ${color.loss}`, padding: "6px 10px", marginBottom: 10, color: color.loss, fontSize: 12 }}>{error}</div>}
        {aviso && <div style={{ borderLeft: `2px solid ${color.profit}`, padding: "6px 10px", marginBottom: 10, fontSize: 12 }}>{aviso}</div>}
        {catalogo && !catalogo.python_ok && (
          <div style={{ borderLeft: `2px solid ${color.warning}`, padding: "6px 10px", marginBottom: 10, fontSize: 12 }}>No encuentro el Python del genético en {catalogo.python}.</div>
        )}

        <Sec title="Modo" help="«Explorar» busca estrategias nuevas combinando indicadores del catálogo: es lo que ha hecho el genético siempre y no cambia. «Mejorar» parte de UNA estrategia tuya y solo mueve los parámetros que marques; todo lo demás de esa estrategia queda intacto.">
          <Row label="Qué hace el genético">
            <Toggle value={modo} onChange={setModo} options={[
              { value: "explorar", label: "Explorar estrategias" },
              { value: "mejorar", label: "Mejorar una estrategia" },
            ]} />
          </Row>
          {modo === "mejorar" && (
            <Row label="Estrategia" help="La de partida. Su definición se congela al lanzar, así que editarla después no cambia una corrida en marcha. Al elegirla se carga sola SU dataset: es el universo sobre el que la construiste.">
              <Sel value={estrategiaId} onChange={setEstrategiaId} options={[
                { value: "", label: "— elige —" },
                ...estrategias.map((e) => ({ value: e.id, label: e.name })),
              ]} />
            </Row>
          )}
        </Sec>

        {modo === "mejorar" && (
          <Sec title="Qué se le puede mover" help="Marca lo que quieres que el genético pruebe y en qué rango. Lo que NO marques se queda exactamente como está en la estrategia. El rango que ves propuesto son ±2 escalones alrededor del valor de hoy, igual que en el optimizador 3D: cámbialo a tu gusto.">
            {!estrategiaId && <div style={{ fontSize: 11, color: color.textMuted, padding: "6px 0" }}>Elige antes una estrategia.</div>}
            {cargandoGenes && <div style={{ fontSize: 11, color: color.textMuted, padding: "6px 0" }}>Leyendo sus parámetros…</div>}
            {!cargandoGenes && estrategiaId && bloquesGenes.length === 0 && (
              <div style={{ fontSize: 11, color: color.warning, padding: "6px 0" }}>
                Esa estrategia no tiene ningún parámetro numérico que mover.
              </div>
            )}
            {bloquesGenes.map((b) => (
              <div key={b.id} style={{ padding: "8px 0", borderTop: hairline }}>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: color.textMuted, marginBottom: 6 }}>{b.label}</div>
                {b.genes.map((g) => {
                  const sel = genesSel[g.id] || { on: false, min: 0, max: 0, step: 1 };
                  const set = (v: Partial<typeof sel>) => setGenesSel((p) => ({ ...p, [g.id]: { ...sel, ...v } }));
                  const ip = indiceParcial(g.id);
                  const fuera = ip !== null && ip >= maxParciales;
                  if (fuera) {
                    return (
                      <div key={g.id} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center", padding: "3px 0", opacity: 0.35 }}>
                        <input type="checkbox" checked={false} disabled style={{ margin: 0 }} />
                        <span style={{ fontSize: 11, color: color.textMuted }}>
                          {g.label} <span style={{ fontStyle: "italic" }}>— por encima del máximo de parciales</span>
                        </span>
                      </div>
                    );
                  }
                  return (
                    <div key={g.id} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center", padding: "3px 0" }}>
                      <input type="checkbox" checked={sel.on} onChange={(e) => set({ on: e.target.checked })} style={{ margin: 0 }} />
                      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center" }}>
                        <span style={{ fontSize: 11, color: sel.on ? color.textHigh : color.textSecondary }}>
                          {g.label}
                          <span style={{ color: color.textMuted, fontFamily: font.mono, marginLeft: 6 }}>
                            (hoy: {leeValor(g, g.current_value)})
                          </span>
                        </span>
                        {sel.on && !g.opciones && (
                          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <RangoGen gen={g} sel={sel} set={set} />
                          </div>
                        )}
                        {sel.on && g.opciones && (() => {
                          const todas = g.opciones.map(String);
                          const puestas = sel.opciones ?? todas;
                          return (
                            <button
                              type="button"
                              onClick={() => setGenAbierto((a) => (a === g.id ? null : g.id))}
                              style={{
                                background: "none", border: hairline, borderRadius: 3,
                                color: puestas.length === todas.length ? color.textMuted : color.copper,
                                fontFamily: font.mono, fontSize: 10, padding: "1px 6px", cursor: "pointer",
                              }}
                              title="Elegir qué valores puede probar"
                            >
                              {puestas.length} de {todas.length}
                            </button>
                          );
                        })()}
                      </div>
                      {sel.on && g.opciones && genAbierto === g.id && (
                        <div style={{ gridColumn: "1 / -1", display: "flex", flexWrap: "wrap", gap: 4, padding: "6px 0 8px 0" }}>
                          {g.opciones.map((o) => {
                            const v = String(o);
                            const todas = g.opciones!.map(String);
                            const puestas = sel.opciones ?? todas;
                            const dentro = puestas.includes(v);
                            return (
                              <button
                                key={v}
                                type="button"
                                onClick={() => {
                                  const nuevas = dentro ? puestas.filter((x) => x !== v) : [...puestas, v];
                                  // Dejar UNO es legitimo: fija ese valor sin
                                  // que el genetico lo mueva. Vaciarlo del todo
                                  // no, que dejaria el gen sin rejilla.
                                  if (nuevas.length < 1) return;
                                  set({ opciones: nuevas.length === todas.length ? undefined : nuevas });
                                }}
                                style={{
                                  background: dentro ? "var(--color-ec-copper)" : "transparent",
                                  color: dentro ? "var(--color-ec-copper-text)" : color.textMuted,
                                  border: hairline, borderRadius: 3, fontFamily: font.mono,
                                  fontSize: 10, padding: "2px 6px", cursor: "pointer",
                                }}
                              >
                                {leeDisparador(v) ?? v}
                              </button>
                            );
                          })}
                          <button type="button" onClick={() => set({ opciones: undefined })}
                            style={{ background: "none", border: "none", color: color.textMuted, fontSize: 10, cursor: "pointer", textDecoration: "underline" }}>
                            todas
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
            {genesMarcados.length > 0 && (
              <div style={{ paddingTop: 8, fontSize: 11, color: color.textSecondary }}>
                <span style={{ fontFamily: font.mono, color: color.textHigh }}>{genesMarcados.length}</span> parámetros marcados
                {" · "}
                <span style={{ fontFamily: font.mono, color: color.textHigh }}>{entero(combinaciones)}</span> combinaciones posibles
                <Help title="Combinaciones">El producto de los valores de cada parámetro marcado. El genético no las recorre todas — por eso es un genético y no una rejilla — pero da la medida del espacio: si son cuatro, usa el optimizador 3D; si son millones, esto es lo que toca.</Help>
              </div>
            )}
          </Sec>
        )}

        {modo === "explorar" && (
        <Sec title="Operativa" help="Lo que define tu forma de operar y el genético no toca: lado, sesión y ventana de entradas.">
          <Row label="Sesgo" help="Short o long. Fijarlo ahorra la mitad del espacio de búsqueda. Con short, los stops de estructura van arriba (HOD, PMH, Previous Max); con long, abajo.">
            <Toggle<"short" | "long"> value={sesgo} onChange={setSesgo} options={[{ value: "short", label: "Short" }, { value: "long", label: "Long" }]} />
          </Row>
          <Row label="Sesión" help="Velas que ve el simulador: RTH (09:30–16:00), premarket (04:00–09:30) o un tramo de horas. Igual que el selector de sesión del Backtester.">
            <Toggle<"rth" | "pre" | "custom"> value={sesion} onChange={setSesion} options={[{ value: "rth", label: "RTH" }, { value: "pre", label: "Premarket" }, { value: "custom", label: "Horas" }]} />
          </Row>
          {sesion === "custom" && (
            <Row label="Horas">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                <input type="time" style={control} value={horaIni} onChange={(e) => setHoraIni(e.target.value)} />
                <input type="time" style={control} value={horaFin} onChange={(e) => setHoraFin(e.target.value)} />
              </div>
            </Row>
          )}
          <Row label="Ventana de entrada" help="Si se activa, solo se abren posiciones entre esas horas (las salidas siguen su curso). Es el mismo campo «entry_time_windows» de la lógica de entrada.">
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={ventanaOn} onChange={(e) => setVentanaOn(e.target.checked)} style={{ margin: 0 }} />
              <input type="time" style={{ ...control, opacity: ventanaOn ? 1 : 0.4 }} disabled={!ventanaOn} value={ventanaDe} onChange={(e) => setVentanaDe(e.target.value)} />
              <input type="time" style={{ ...control, opacity: ventanaOn ? 1 : 0.4 }} disabled={!ventanaOn} value={ventanaA} onChange={(e) => setVentanaA(e.target.value)} />
            </div>
          </Row>
        </Sec>

        )}

        <Sec title="Guardas fijas" help="Condiciones que van SIEMPRE en la entrada y el genético no cambia ni cuenta como condiciones de lógica: son filtros de universo (precio mínimo, liquidez). Así no gasta búsqueda en redescubrir que no quieres acciones de 20 céntimos.">
          {/* La lista sale del catálogo del backend: añadir una guarda allí la
              hace aparecer aquí sola, sin tocar esta pantalla. */}
          {(catalogo?.guardas ?? []).map((g) => {
            const est = guardas[g.clave] ?? { on: false, valor: 0 };
            const paso = g.clave === "precio" ? 0.1 : g.clave === "pm_high_gap" ? 5 : 100_000;
            return (
              <Row key={g.clave} label={g.etiqueta} help={g.ayuda}>
                <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center" }}>
                  <input type="checkbox" checked={est.on}
                    onChange={(e) => ponGuarda(g.clave, { on: e.target.checked })}
                    style={{ margin: 0 }} />
                  <Num value={est.valor} onChange={(v) => ponGuarda(g.clave, { valor: v })}
                    min={0} step={paso} disabled={!est.on} />
                </div>
              </Row>
            );
          })}
        </Sec>

        {modo === "explorar" && (
        <Sec title="Qué puede combinar" help="El vocabulario del genético. Tú pones los ingredientes; él escribe las recetas. Menos indicadores bien elegidos buscan mejor que el catálogo entero: cada uno que no aporta añade formas de encontrar casualidades.">
          <Row label="Indicadores" help="Cada condición de lógica compara uno de estos con un número de su rejilla o con otro nivel (Prev. Bar Low, VWAP, PM High, medias, bandas, Darvas…). Entre paréntesis, los parámetros que TAMBIÉN se buscan: no eliges uno, el genético prueba todos sus valores a lo largo de la población." wide>
            <div>
              {/* Pestañas por familia. Con dos docenas de indicadores, una lista
                  plana de casillas no se puede leer ni marcar. El contador dice
                  cuántos llevas activos de cada grupo, para verlo sin entrar. */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
                {(catalogo?.familias ?? []).map((f) => {
                  const suyos = (catalogo?.indicadores ?? []).filter((i) => i.familia === f.clave);
                  const activos = suyos.filter((i) => indicadores[i.nombre]).length;
                  const abierta = familia === f.clave;
                  return (
                    <button key={f.clave} onClick={() => setFamilia(f.clave)}
                      style={{
                        fontFamily: font.sans, fontSize: 11, padding: "3px 9px",
                        cursor: "pointer", borderRadius: 3,
                        background: abierta ? color.copper : "transparent",
                        border: `0.5px solid ${abierta ? color.copper : color.border}`,
                        color: abierta ? "#fff" : color.textSecondary,
                      }}>
                      {f.etiqueta}
                      {activos > 0 && (
                        <span style={{ marginLeft: 5, fontFamily: font.mono, opacity: 0.85 }}>
                          {activos}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 12 }}>
                {(catalogo?.indicadores ?? []).filter((i) => i.familia === familia).map((i) => (
                  <Check key={i.nombre} checked={!!indicadores[i.nombre]}
                    onChange={(v) => setIndicadores((s) => ({ ...s, [i.nombre]: v }))}
                    help={i.ayuda}
                    label={`${i.nombre}${Object.keys(i.params).length ? ` (${Object.keys(i.params).join(", ")})` : ""}`} />
                ))}
              </div>
            </div>
          </Row>
          <Row label="Condiciones" help="Cuántas condiciones de lógica lleva cada estrategia (las guardas aparte). Cada una son ~4 parámetros libres; con ~1.500 operaciones, el techo estadístico son 2–3. Empieza por 2.">
            <Toggle<"1" | "2" | "3"> value={nCond} onChange={setNCond} options={[{ value: "1", label: "1" }, { value: "2", label: "2" }, { value: "3", label: "3" }]} />
          </Row>
          <Row label="Stop" help={`Tipos de stop que puede elegir. En %: rejilla ${catalogo?.stops.pct.join(", ") ?? ""}. De estructura: HOD / PMH / Previous Max (short) o LOD / PML / Previous Min (long) con un margen de ${catalogo?.stops.offset_pct.join(", ") ?? ""} %. Un stop de estructura a +0 % con «shares por distancia» significa posición máxima: pon tope de locates.`}>
            <div style={{ display: "flex", gap: 16 }}>
              <Check checked={stopPct} onChange={setStopPct} label="Porcentaje" />
              <Check checked={stopEstructura} onChange={setStopEstructura} label="Estructura + margen" />
            </div>
          </Row>
          <Row label="Stop mínimo %" help="Suelo de la rejilla del stop en porcentaje. Un stop del 2 % en una acción que se mueve un 50 % al día no es un stop, es ruido — y el genético lo elige igualmente, porque con «shares por distancia» reparte un tamaño enorme y la R media sale preciosa hasta que un día salta el hueco. 0 = sin suelo. No toca los stops de estructura: allí la distancia la pone el mercado.">
            <Num value={riesgo.stop_min_pct ?? 0} onChange={(v) => setRiesgo({ ...riesgo, stop_min_pct: v })} min={0} step={1} />
          </Row>
          <Row label="Take profit" help={`Tipos de objetivo. En %: ${catalogo?.tps.pct.join(", ") ?? ""}. Por hora: cierre a una hora fija (${catalogo?.tps.hora.join(", ") ?? ""}). Por minutos: cierre pasado un tiempo (${catalogo?.tps.tiempo.join(", ") ?? ""}).`}>
            <div style={{ display: "flex", gap: 16 }}>
              <Check checked={tpPct} onChange={setTpPct} label="Porcentaje" />
              <Check checked={tpHora} onChange={setTpHora} label="Hora" />
              <Check checked={tpTiempo} onChange={setTpTiempo} label="Minutos" />
            </div>
          </Row>
          <Row label="TP mínimo %" help="Objetivo mínimo en porcentaje: por debajo no se busca. Solo afecta al modo porcentaje — los de hora y minutos cierran cuando toca, valga lo que valga. 0 = sin mínimo.">
            <Num value={riesgo.tp_min_pct ?? 0} onChange={(v) => setRiesgo({ ...riesgo, tp_min_pct: v })} min={0} step={1} />
          </Row>
          <Row label="TP parciales" help={`Deja que el genético pruebe a cerrar la posición por trozos: hasta ${catalogo?.tps.parcial_max ?? 2} niveles, cerrando ${catalogo?.tps.parcial_cierre.join(", ") ?? ""} % en cada uno, con los mismos criterios que el objetivo principal (porcentaje, hora o minutos). Sortea también NINGUNO, para poder comparar contra no ponerlos: si siempre los pusiera, no sabrías si compensan.`}>
            <Check checked={!!riesgo.tp_parciales} onChange={(v) => setRiesgo({ ...riesgo, tp_parciales: v })} label="Probarlos" />
          </Row>
        </Sec>

        )}

        <Sec title="Universo" help="Qué ticker-días entran y en qué periodo. Las MISMAS opciones que al crear un dataset en el Backtester — no hay desplegable de datasets guardados: se eligen aquí. El «rango de fechas global» de ahí dentro ES el periodo IS de la corrida. Las guardas de arriba son otra cosa: condiciones de entrada, vela a vela.">
          <Row label="Nombre" help="Solo para reconocer la corrida en la lista. Si lo dejas vacío se usa la fecha y hora.">
            <input style={{ ...control, fontFamily: font.sans }} value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="opcional" />
          </Row>
          <Row label="Periodo (IS)" help="El tramo que el genético puede ver. Deja fuera lo más reciente: ese es tu OOS y se usa UNA vez, al final, con los finalistas.">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input type="date" style={control} value={uDesde} onChange={(e) => setUDesde(e.target.value)} />
              <input type="date" style={control} value={uHasta} onChange={(e) => setUHasta(e.target.value)} />
            </div>
          </Row>

          <Row label="Añadir filtro" help="La misma lista de métricas que al crear un dataset en el Backtester: el día del gap, el anterior (GAP-1) y los dos siguientes.">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              <Sel value={uSec} onChange={(v) => setUSec(v as SeccionUniverso)}
                options={(Object.keys(SECCIONES_UNIVERSO) as SeccionUniverso[])
                  .map((k) => ({ value: k, label: SECCIONES_UNIVERSO[k] }))} />
              <Sel value={uParam} onChange={setUParam}
                options={PARAMETROS_UNIVERSO.map((p) => ({ value: p.key, label: `${p.label} (${p.unit})` }))} />
            </div>
          </Row>
          <Row label={DESCRIPCIONES_UNIVERSO[uParam] ? " " : ""}>
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 6, alignItems: "center" }}>
              <Sel value={uOp} onChange={(v) => setUOp(v as OperadorUniverso)}
                options={[
                  { value: ">=", label: "≥" }, { value: ">", label: ">" },
                  { value: "<=", label: "≤" }, { value: "<", label: "<" },
                  { value: "between", label: "entre" },
                ]} />
              {uOp === "between" ? (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                  <Num value={uVal1} onChange={setUVal1} step={0.5} />
                  <Num value={uVal2} onChange={setUVal2} step={0.5} />
                </div>
              ) : (
                <Num value={uVal1} onChange={setUVal1} step={0.5} />
              )}
              <Btn onClick={() => {
                const nueva: CondicionUniverso = {
                  section: uSec, paramKey: uParam, op: uOp,
                  val1: uVal1, ...(uOp === "between" ? { val2: uVal2 } : {}),
                };
                setCondUniverso((p) => [
                  // Una métrica repetida en la misma sección y con el mismo
                  // signo se SUSTITUYE: dos reglas contradictorias sobre lo
                  // mismo dejarían el universo vacío sin decir por qué.
                  ...p.filter((c) => !(c.section === nueva.section && c.paramKey === nueva.paramKey && c.op === nueva.op)),
                  nueva,
                ]);
              }}>Añadir</Btn>
            </div>
          </Row>
          {DESCRIPCIONES_UNIVERSO[uParam] && (
            <div style={{ fontSize: 11, color: color.textMuted, lineHeight: 1.5, padding: "0 0 6px" }}>
              {DESCRIPCIONES_UNIVERSO[uParam]}
            </div>
          )}

          {condUniverso.length === 0 ? (
            <div style={{ fontSize: 11, color: color.warning, lineHeight: 1.5, paddingTop: 4 }}>
              Sin filtros serían todos los ticker-días del lago (unos 7,4 millones).
            </div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, paddingTop: 4 }}>
              {condUniverso.map((c, i) => (
                <span key={i} style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  border: hairline, borderRadius: 3, padding: "3px 6px",
                  fontSize: 11, fontFamily: font.mono, color: color.textHigh,
                }}>
                  {leeCondicion(c)}
                  <button onClick={() => setCondUniverso((p) => p.filter((_, j) => j !== i))}
                    style={{ background: "none", border: "none", color: color.textMuted, cursor: "pointer", padding: 0, lineHeight: 1 }}>×</button>
                </span>
              ))}
            </div>
          )}

          {calculandoUniverso ? (
            <div style={{ fontSize: 11, color: color.textMuted, paddingTop: 8 }}>Contando ticker-días…</div>
          ) : universo?.pares != null ? (
            <div style={{ fontSize: 12, color: color.textSecondary, lineHeight: 1.7, paddingTop: 8 }}>
              <span style={{ fontFamily: font.mono, fontSize: 15, color: universo.pares > universo.tope ? color.loss : color.textHigh }}>
                {entero(universo.pares)}
              </span>{" "}ticker-días
              {universo.tickers ? <> · <span style={{ fontFamily: font.mono }}>{entero(universo.tickers)}</span> tickers</> : null}
              {universo.primer_dia ? <> · {universo.primer_dia} → {universo.ultimo_dia}</> : null}
              {universo.pares > universo.tope && (
                <div style={{ color: color.loss, fontSize: 11, marginTop: 4 }}>
                  Se pasa del tope de {entero(universo.tope)}: con tantos días cada backtest tarda
                  minutos y la corrida no acabaría. Aprieta algún filtro o acorta el periodo.
                </div>
              )}
            </div>
          ) : null}
        </Sec>

        <Sec title="Riesgo" help="Los mismos ajustes que el panel de riesgo del Backtester. Para que la R media sea una R de verdad: riesgo fijo en $ con «shares por distancia al SL» activado. Nunca % de equity: con composición y liquidez infinita el genético aprende a apalancarse, no a operar.">
          <Row label="Capital"><Num value={riesgo.init_cash} onChange={(v) => setRiesgo({ ...riesgo, init_cash: v })} min={100} step={1000} /></Row>
          <Row label="Riesgo fijo $" help="Dólares que arriesga cada operación (distancia al stop × acciones). Es la unidad R de la tabla."><Num value={riesgo.risk_r} onChange={(v) => setRiesgo({ ...riesgo, risk_r: v })} min={1} step={10} /></Row>
          <Row label="Comisión %"><Num value={riesgo.fees} onChange={(v) => setRiesgo({ ...riesgo, fees: v })} min={0} step={0.01} /></Row>
          <Row label="Slippage %" help="Se aplica en la entrada y en cada salida. Con stops estrechos pesa mucho: coste en R ≈ 2 × slippage ÷ distancia al stop."><Num value={riesgo.slippage} onChange={(v) => setRiesgo({ ...riesgo, slippage: v })} min={0} step={0.05} /></Row>
          <Row label="Coste locates"><Num value={riesgo.locates_cost} onChange={(v) => setRiesgo({ ...riesgo, locates_cost: v })} min={0} step={0.01} /></Row>
          <Row label="Tope locates" help="Máximo de paquetes de 100 acciones en corto por ticker-día (0 = sin tope). Acota el tamaño y cierra el atajo del stop a distancia cero."><Num value={riesgo.max_locates} onChange={(v) => setRiesgo({ ...riesgo, max_locates: v })} min={0} step={10} /></Row>
          {/* EN MODO MEJORAR ESTOS TRES NO PINTAN NADA. Reentradas, «shares por
              SL» y el stop híbrido salen de la ESTRATEGIA
              (`evaluador.parametros_backtest` los lee de la definición), así
              que dejarlos aquí sería un ajuste fantasma: se tocan, no hacen
              nada y nadie avisa — como el Max DD Diario. Las reentradas además
              se pueden mover como gen, arriba. */}
          {modo === "explorar" ? (
            <>
          <Row label="Reentradas" help="Si se permite volver a entrar el mismo día tras cerrar, y cuántas veces (−1 = sin límite).">
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={riesgo.accept_reentries} onChange={(e) => setRiesgo({ ...riesgo, accept_reentries: e.target.checked })} style={{ margin: 0 }} />
              <Num value={riesgo.max_reentries} onChange={(v) => setRiesgo({ ...riesgo, max_reentries: v })} min={-1} step={1} disabled={!riesgo.accept_reentries} />
            </div>
          </Row>
          <Row label="Shares por SL" help="«Cálculo de Shares por Distancia al SL» del panel. Activado, la posición es riesgo ÷ distancia al stop (riesgo real). Desactivado, son solo riesgo ÷ precio acciones y la R no significa nada.">
            <Check checked={riesgo.size_by_sl} onChange={(v) => setRiesgo({ ...riesgo, size_by_sl: v })} label="Activado" />
          </Row>
          <Row label="Stop híbrido" help="Va por distancia al stop, pero con TECHO de exposición: techo $ = (% de cuenta asumible × capital) ÷ % del evento. Resuelve el punto ciego del modo por SL, que es justo el que se come el genético: con el stop muy ceñido el tamaño se dispara y un hueco brutal deja debiendo dinero. Recorta, no anula. Implica «Shares por SL», así que lo activa solo.">
            {/* La ayuda promete que «lo activa solo» y hasta hoy no lo hacia:
                se podia dejar el hibrido puesto con «Shares por SL» quitado y
                correr un genetico entero sin techo, sin aviso. */}
            <Check checked={!!riesgo.hybrid_stop} onChange={(v) => setRiesgo({ ...riesgo, hybrid_stop: v, size_by_sl: v ? true : riesgo.size_by_sl })} label="Activado" />
          </Row>
          {riesgo.hybrid_stop && (
            <>
              <Row label="% del evento" help="El peor movimiento en contra que quieres contemplar. Si crees que lo peor que puede pasarte es un +50 % en tu contra de un salto, pon 50.">
                <Num value={riesgo.hybrid_black_swan_pct ?? 50} onChange={(v) => setRiesgo({ ...riesgo, hybrid_black_swan_pct: v })} min={1} step={5} />
              </Row>
              <Row label="% de cuenta asumible" help="Cuánto de tu CUENTA ENTERA aceptas perder si ese evento ocurre. Con 3 y un evento del 50 %, el techo de posición sale (3 % × capital) ÷ 50 %.">
                <Num value={riesgo.hybrid_max_loss_pct ?? 3} onChange={(v) => setRiesgo({ ...riesgo, hybrid_max_loss_pct: v })} min={0.1} step={0.5} />
              </Row>
            </>
          )}
            </>
          ) : (
            <div style={{ fontSize: 11, color: color.textMuted, lineHeight: 1.6 }}>
              Reentradas, «shares por SL» y stop híbrido salen de la estrategia que
              estás mejorando. Las reentradas se pueden mover como parámetro, arriba.
            </div>
          )}
        </Sec>

        <Sec title="Búsqueda" help="Cómo busca. Población = cuántas estrategias viven a la vez; generaciones = cuántas rondas de probar, descartar, cruzar y mutar. El total de backtests es aproximadamente población × generaciones, menos los repetidos.">
          <Row label="Nota (fitness)" help="La nota de cada estrategia. Por defecto R media × √operaciones: premia el edge por operación y que ocurra a menudo, sin que 4.000 operaciones valgan 40 veces más que 100. Nunca retorno total.">
            <Sel value={fitness} onChange={setFitness} options={(catalogo?.fitness ?? []).map((f) => ({ value: f.id, label: f.label }))} />
          </Row>
          {modo === "mejorar" && (
            <>
              <Row label="Cómo se agrega" help="Un eje APARTE de la métrica: «Profit factor con peor trozo» y «Profit factor» a secas son la misma métrica agregada distinto. «Valor» es lo que hace el explorador. Solo aparece en modo mejorar.">
                <Sel value={agregacion} onChange={setAgregacion} options={(catalogo?.agregacion ?? [
                  { id: "valor", label: "Valor (lo de siempre)" },
                ]).map((a) => ({ value: a.id, label: a.label }))} />
              </Row>
              {(agregacion === "peor_trozo" || agregacion === "media_menos_sigma") && (
                <Row label="Trozos" help="En cuántos tramos con el mismo número de días de mercado se parte el IS. Más trozos afinan más, pero cada uno lleva menos operaciones y su nota es más ruidosa. 4 es un buen punto de partida.">
                  <Num value={trozos} onChange={setTrozos} min={2} max={12} step={1} />
                </Row>
              )}
              {catalogo?.agregacion?.find((a) => a.id === agregacion)?.ayuda && (
                <div style={{ fontSize: 11, color: color.textMuted, lineHeight: 1.5, padding: "2px 0 6px" }}>
                  {catalogo.agregacion.find((a) => a.id === agregacion)?.ayuda}
                </div>
              )}
            </>
          )}
          <Row label="Mín. operaciones" help="Por debajo de esto la nota es 0. Sin este suelo el genético encuentra las seis operaciones perfectas de la historia y descarta todo lo demás."><Num value={minTrades} onChange={setMinTrades} min={1} step={10} /></Row>
          <Row label="Población" help="Cuántas estrategias distintas viven a la vez. Es la ANCHURA de la búsqueda: con 80, cada generación prueba 80 combinaciones y las mejores se cruzan entre sí. Poca población (menos de ~30) se queda enganchada en la primera idea decente, porque no hay variedad de donde tirar; mucha explora más pero cada generación cuesta proporcionalmente más backtests. 60–100 es el rango razonable con este catálogo."><Num value={poblacion} onChange={setPoblacion} min={4} step={10} /></Row>
          <Row label="Generaciones" help="Cuántas rondas de probar, quedarse con las mejores, cruzarlas y mutarlas. Es la PROFUNDIDAD: cada ronda refina lo que encontró la anterior. Las primeras 10–15 hacen casi todo el trabajo y luego las mejoras se aplanan — por eso existe la paciencia, que corta sola si deja de mejorar. Muchas generaciones sobre poca población no compensa: pule unas pocas ideas en vez de buscar mejores."><Num value={generaciones} onChange={setGeneraciones} min={1} step={5} /></Row>
          <Row label="Semilla" help="Número que fija el azar (qué estrategias iniciales, qué se muta). Misma semilla = misma corrida exacta. Corre dos veces con semillas distintas: si las listas se parecen hay señal; si no, ninguna vale."><Num value={semilla} onChange={setSemilla} min={0} step={1} /></Row>
          <Row label="Paciencia" help="Generaciones seguidas sin mejorar el mejor antes de parar sola."><Num value={paciencia} onChange={setPaciencia} min={1} step={1} /></Row>
          <Row label="Workers" help="Procesos en paralelo. 0 = los que quepan en RAM (cada uno ~1,2 GB; con Chrome abierto suelen caber 2, de noche 4)."><Num value={workers} onChange={setWorkers} min={0} max={8} step={1} /></Row>
          <Row label="Parar a las" help="Hora límite: la corrida se para sola, limpiamente, aunque no haya terminado (se puede reanudar). Para que nunca pille al bot de alertas encendido por la mañana.">
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={pararALasOn} onChange={(e) => setPararALasOn(e.target.checked)} style={{ margin: 0 }} />
              <input type="time" style={{ ...control, opacity: pararALasOn ? 1 : 0.4 }} disabled={!pararALasOn} value={pararALas} onChange={(e) => setPararALas(e.target.value)} />
            </div>
          </Row>
          <div style={{ padding: "10px 0 4px", fontSize: 12, color: color.textSecondary, lineHeight: 1.6 }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>≈ <span style={{ fontFamily: font.mono, color: color.textHigh }}>{entero(estimacion.evals)}</span> backtests
              <Help title="Estimación">Población + generaciones × (población − élite) × 0,65 (un tercio de los hijos salen repetidos y no se reevalúan), a {SEG_POR_EVAL} s por backtest medidos en esta máquina sin piramidación.</Help></span>
            <div style={{ fontFamily: font.mono, fontSize: 11.5 }}>
              1 worker <span style={{ color: color.textHigh }}>{duracion(estimacion.con1)}</span> · 2 workers <span style={{ color: color.textHigh }}>{duracion(estimacion.con2)}</span> · 4 workers <span style={{ color: color.textHigh }}>{duracion(estimacion.con4)}</span>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 6 }}>
            <Btn onClick={lanzar} primary disabled={problemas.length > 0 || lanzando}>{lanzando ? "Lanzando…" : "Lanzar corrida"}</Btn>
            {problemas.length > 0 && <span style={{ fontSize: 11, color: color.warning }}>Falta: {problemas.join(" · ")}</span>}
          </div>
        </Sec>
      </div>

      {/* ── resultados ── */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", paddingBottom: 10, borderBottom: `1px solid ${color.border}` }}>
          <span style={{ ...etiqueta, display: "flex", alignItems: "center", gap: 5 }}>Corrida<Help title="Corrida">Cada lanzamiento es una corrida con su carpeta en disco (config, estado, mejores, log). Se puede parar, reanudar y borrar. ● = el proceso sigue vivo.</Help></span>
          <div style={{ flex: 1, minWidth: 260 }}>
            <Sel value={seleccion ?? ""} onChange={(v) => setSeleccion(v || null)}
              options={corridas.length ? corridas.map((c) => ({
                value: c.id,
                label: `${c.nombre} · ${c.estado}${c.vivo ? " ●" : ""} · gen ${c.generacion}/${c.generaciones ?? "?"} · ${c.evaluadas} backtests${c.mejor ? ` · mejor ${n(c.mejor.fitness, 1)}` : ""}`,
              })) : [{ value: "", label: "Sin corridas todavía" }]} />
          </div>
          <Btn onClick={refrescarLista}>Refrescar</Btn>
          {detalle && detalle.vivo && !detalle.parada_pedida && (
            <Btn danger onClick={() => accion(() => pararCorrida(detalle.id), "Se parará al terminar la evaluación en curso.")} title="Parada limpia: termina el backtest en curso y guarda">Parar</Btn>
          )}
          {detalle && !detalle.vivo && detalle.estado.estado !== "terminada" && (
            <Btn onClick={() => accion(() => reanudarCorrida(detalle.id), "Reanudada.")} title="Sigue desde la última generación guardada">Reanudar</Btn>
          )}
          {detalle && !detalle.vivo && (
            <Btn danger onClick={() => { if (window.confirm("¿Borrar esta corrida y sus resultados?")) accion(() => borrarCorrida(detalle.id), "Borrada.").then(() => setSeleccion(null)); }}>Borrar</Btn>
          )}
        </div>

        {detalle && (
          <>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0 18px", padding: "12px 0 10px" }}>
              <Stat label="Estado" value={`${est.estado ?? "—"}${detalle.vivo ? " ●" : ""}`} sub={est.mensaje || undefined}
                help="preparando (cargando datos) · corriendo · parada (a mano o por hora límite; se puede reanudar) · terminada · error (mira el log)." />
              <Stat label="Generación" value={`${est.generacion ?? 0} / ${est.generaciones ?? detalle.config.generaciones}`}
                help="Ronda actual de las previstas. La 0 es la población inicial al azar." />
              <Stat label="Backtests" value={entero(est.evaluadas)} sub={est.unicas !== undefined ? `${entero(est.unicas)} distintos` : undefined}
                help="Evaluaciones hechas. «Distintos» descuenta los hijos repetidos, que se sirven de la caché sin volver a simular." />
              <Stat label="Por backtest" value={est.segundos_por_eval ? `${n(est.segundos_por_eval, 1)} s` : "—"} sub={detalle.config.workers ? `${detalle.config.workers} workers` : undefined}
                help="Segundos por evaluación efectivos (media de las últimas 20, ya repartidas entre workers)." />
              <Stat label="Queda" value={detalle.vivo ? duracion(est.eta_segundos ?? 0) : "—"}
                help="Estimación con el ritmo actual y las generaciones que faltan. Si la paciencia corta antes, sobra." />
              <Stat label="Mejor fitness" value={est.mejor ? n(est.mejor.fitness) : "—"} tone={est.mejor && est.mejor.fitness > 0 ? "profit" : undefined}
                help="La nota más alta de todo lo evaluado hasta ahora (no solo de la generación actual)." />
            </div>

            {(detalle.vivo || (est.generacion ?? 0) > 0) && (
              <div style={{ padding: "12px 0 14px", borderBottom: hairline }}>
                <Barra
                  activa={detalle.vivo}
                  pct={(() => {
                    const t = (est.actualizado ?? 0) - (est.inicio ?? 0);
                    const eta = est.eta_segundos ?? 0;
                    if (detalle.vivo && t > 0 && eta > 0) return (t / (t + eta)) * 100;
                    const g = est.generacion ?? 0, gs = est.generaciones ?? detalle.config.generaciones ?? 1;
                    return detalle.vivo ? (g / Math.max(1, gs)) * 100 : 100;
                  })()}
                  izq={detalle.vivo
                    ? `Generación ${est.generacion ?? 0} de ${est.generaciones ?? detalle.config.generaciones} · ${entero(est.evaluadas)} backtests`
                    : `${est.estado ?? "—"} · ${entero(est.evaluadas)} backtests en ${duracion(((est.actualizado ?? 0) - (est.inicio ?? 0)))}`}
                  der={detalle.vivo ? `quedan ~${duracion(est.eta_segundos ?? 0)}` : "—"}
                />
              </div>
            )}

            {detalle.datos && (
              <div style={{ fontSize: 11, color: color.textMuted, padding: "6px 0", borderBottom: hairline, fontFamily: font.mono }}>
                {entero(detalle.datos.pares)} ticker-días · {entero(detalle.datos.velas)} velas · {detalle.datos.primer_dia} → {detalle.datos.ultimo_dia}
                {" · "}semilla {detalle.config.semilla} · {detalle.config.n_condiciones} cond. · {detalle.config.catalogo.length} indicadores · {detalle.config.sesgo} · {detalle.config.sesiones.join("/")}
              </div>
            )}

            {historial.length > 1 && <Curva historial={historial} />}

            <Sec sinRelleno title={`Los ${detalle.mejores.length} mejores de todo lo evaluado`} help="Ordenados por nota, contando todas las generaciones. Cada fila es una estrategia completa: entrada (con tus guardas delante), stop y take profit. Los números son los del motor con la configuración de riesgo de la corrida.">
              {detalle.mejores.length === 0 ? (
                <div style={{ fontSize: 12, color: color.textMuted, padding: "10px" }}>Todavía nada evaluado.</div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <Table>
                    <thead>
                      <tr>
                        <Th style={{ width: 28 }}>#</Th>
                        <Th>Receta</Th>
                        <Th style={th(true)}><span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>Fitness<Help title="Fitness">La nota con la fórmula elegida en la corrida. Solo sirve para ordenar; las métricas de al lado son las que importan.</Help></span></Th>
                        <Th style={th(true)}>Trades</Th>
                        <Th style={th(true)}><span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>R media<Help title="R media">PnL medio por operación dividido por el riesgo fijo. 0,20 = gana de media un quinto de lo que arriesga.</Help></span></Th>
                        <Th style={th(true)}>PF</Th>
                        <Th style={th(true)}>WR %</Th>
                        <Th style={th(true)}>Max DD %</Th>
                        <Th></Th>
                      </tr>
                    </thead>
                    <tbody>
                      {detalle.mejores.map((m, i) => (
                        <Tr key={m.huella} hoverable>
                          <Td style={{ ...tdNum, color: color.textMuted, textAlign: "left" }}>{i + 1}</Td>
                          <Td style={{ ...tdTxt, minWidth: 320 }}>
                            <button
                              onClick={() => setAbiertas((p) => {
                                const n = new Set(p);
                                n.has(m.huella) ? n.delete(m.huella) : n.add(m.huella);
                                return n;
                              })}
                              style={{
                                background: "none", border: "none", padding: 0, cursor: "pointer",
                                textAlign: "left", width: "100%", color: "inherit", font: "inherit",
                                display: "grid", gridTemplateColumns: "auto 1fr", gap: 6, alignItems: "baseline",
                              }}
                              title={abiertas.has(m.huella) ? "Plegar" : "Ver todos los parámetros"}
                            >
                              <span style={{ color: color.textMuted, fontFamily: font.mono, fontSize: 10 }}>
                                {abiertas.has(m.huella) ? "▾" : "▸"}
                              </span>
                              <span style={{ minWidth: 0 }}>
                                {/* La HUELLA es el identificador de verdad: es la que
                                    usa el genético por dentro y la que se cuela en el
                                    nombre por defecto al guardar, así que se puede
                                    casar una fila con la estrategia guardada. */}
                                <span style={{ fontFamily: font.mono, fontSize: 10, color: color.copper }}>
                                  #{i + 1} · {m.huella}
                                </span>
                                <div style={{ fontSize: 11, color: color.textSecondary, lineHeight: 1.4 }}>
                                  {resumenCorto(m, detalle.config)}
                                </div>
                              </span>
                            </button>
                            {abiertas.has(m.huella) && (
                              <div style={{ marginTop: 6, paddingTop: 6, borderTop: hairline }}>
                                <RecetaEstructurada mejor={m} config={detalle.config} />
                              </div>
                            )}
                          </Td>
                          <Td style={{ ...tdNum, color: m.fitness > 0 ? color.profit : color.loss }}>{n(m.fitness)}</Td>
                          <Td style={tdNum}>{entero(m.metricas.trades)}</Td>
                          <Td style={{ ...tdNum, color: (m.metricas.avg_r ?? 0) > 0 ? color.profit : color.loss }}>{n(m.metricas.avg_r, 3)}</Td>
                          <Td style={tdNum}>{n(m.metricas.pf)}</Td>
                          <Td style={tdNum}>{n(m.metricas.wr, 1)}</Td>
                          <Td style={{ ...tdNum, color: color.loss }}>{n(m.metricas.max_dd, 1)}</Td>
                          <Td style={{ ...tdNum, padding: "3px 6px" }}>
                            <span style={{ display: "inline-flex", gap: 4 }}>
                              <Btn onClick={() => guardar(m, i)} title="La guarda como estrategia normal (mismo botón que «guardar» del panel) para abrirla en el Backtester y comprobarla">Guardar</Btn>
                              <Btn onClick={() => navigator.clipboard?.writeText(m.receta)} title="Copia la receta en texto">Copiar</Btn>
                            </span>
                          </Td>
                        </Tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              )}
            </Sec>

            <Sec title="Comparar con otra semilla" help="La prueba de fiabilidad: la misma configuración lanzada con otra semilla recorre otro camino. Si las dos listas se parecen (mismos indicadores, stops parecidos, la misma idea), hay señal real. Si no tienen nada que ver, el genético está pescando ruido y ninguna vale.">
              <Row label="Otra corrida">
                <Sel value={comparar ?? ""} onChange={(v) => setComparar(v || null)}
                  options={[{ value: "", label: "—" }, ...corridas.filter((c) => c.id !== detalle.id).map((c) => ({ value: c.id, label: `${c.nombre} · semilla ${c.semilla ?? "?"} · ${c.estado}` }))]} />
              </Row>
              {detalleB && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, paddingTop: 8 }}>
                  {[detalle, detalleB].map((d) => (
                    <Table key={d.id}>
                      <thead><tr><Th style={{ width: 28 }}>#</Th><Th>{d.config.nombre ?? d.id} · semilla {d.config.semilla}</Th><Th style={th(true)}>Fitness</Th></tr></thead>
                      <tbody>
                        {d.mejores.slice(0, 10).map((m, i) => (
                          <Tr key={m.huella}>
                            <Td style={{ ...tdNum, color: color.textMuted, textAlign: "left" }}>{i + 1}</Td>
                            <Td style={tdTxt}>{m.receta}</Td>
                            <Td style={tdNum}>{n(m.fitness, 1)}</Td>
                          </Tr>
                        ))}
                      </tbody>
                    </Table>
                  ))}
                </div>
              )}
            </Sec>

            <details style={{ fontSize: 11.5, border: `1px solid ${color.border}`, background: color.bgSurface, padding: "0 10px 6px", marginBottom: 14 }}>
              <summary style={{ cursor: "pointer", ...etiqueta, padding: "6px 0", borderBottom: hairline }}>Log de la corrida</summary>
              <pre style={{ margin: "8px 0 0", whiteSpace: "pre-wrap", fontFamily: font.mono, fontSize: 11, color: color.textSecondary }}>{[...detalle.log, ...(detalle.salida.length ? ["— salida del proceso —", ...detalle.salida] : [])].join("\n")}</pre>
            </details>
          </>
        )}
      </div>
    </div>
  );
}

/* ── curva mejor / media por generación (SVG sobre el fondo) ─────────── */

function Curva({ historial }: { historial: NonNullable<CorridaDetalle["estado"]["historial"]> }) {
  const W = 760, H = 140, P = 26;
  const xs = historial.map((h) => h.generacion);
  const ys = historial.flatMap((h) => [h.mejor, h.media]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys, 0), y1 = Math.max(...ys, 1e-9);
  const X = (g: number) => P + ((g - x0) / Math.max(1, x1 - x0)) * (W - 2 * P);
  const Y = (v: number) => H - P - ((v - y0) / Math.max(1e-9, y1 - y0)) * (H - 2 * P);
  const linea = (k: "mejor" | "media") => historial.map((h) => `${X(h.generacion).toFixed(1)},${Y(h[k]).toFixed(1)}`).join(" ");
  return (
    <Sec title="Mejor y media por generación" help="Línea clara: la mejor nota alcanzada en cada generación. Línea gris: la media de la población. Si la clara se aplana pronto, ya no hay más que rascar con esta configuración; si la media sube hacia la mejor, la población está convergiendo.">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, display: "block", marginTop: 6 }}>
        <line x1={P} y1={Y(0)} x2={W - P} y2={Y(0)} stroke={color.border} strokeWidth={1} />
        <line x1={P} y1={P} x2={P} y2={H - P} stroke={color.border} strokeWidth={0.5} />
        <polyline points={linea("media")} fill="none" stroke={color.textMuted} strokeWidth={1} />
        <polyline points={linea("mejor")} fill="none" stroke={color.textHigh} strokeWidth={1.5} />
        <text x={P} y={H - 8} fontSize={9} fill={color.textMuted} fontFamily={font.mono}>gen {x0}</text>
        <text x={W - P} y={H - 8} fontSize={9} fill={color.textMuted} fontFamily={font.mono} textAnchor="end">gen {x1}</text>
        <text x={W - P} y={P - 6} fontSize={9} fill={color.textSecondary} fontFamily={font.mono} textAnchor="end">mejor {n(y1, 1)}</text>
      </svg>
    </Sec>
  );
}
