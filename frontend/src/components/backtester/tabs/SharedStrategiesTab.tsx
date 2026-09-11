"use client";

// Pestaña "Compartidas": estrategias que Álvaro y Sailor se enseñan vía JSON en
// <repo>/estrategias_compartidas/. El transporte es git — la app escribe el
// fichero, pero hasta que el dev no commitea esa carpeta el otro no lo ve.
//
// DECISIÓN DE JAUME (10-sep-2026): aquí NO se importa nada. Esto es un VISOR.
// Se comparte la «radiografía» de la estrategia para poder mirar cómo está
// montada y, si convence, hacerse la suya a partir de lo que se ve. Importar
// una copia traía dos problemas: el `dataset_id` es del otro dev y no existe en
// tu base, y cualquier campo de su rama que la nuestra no conozca se caería en
// SILENCIO (la trampa de las listas blancas en tres capas).
//
// EXTENSIÓN (Álvaro, 11-sep-2026): «Abrir borrador» carga el definition en el
// builder como BORRADOR. No contradice lo de arriba: nada entra en la BD de
// estrategias y el dataset no se hereda — se revisa, se ajusta y se decide.
//
// El formato de fichero y el backend son los de Álvaro a propósito: si
// cambiáramos el formato, dejaríais de leeros.

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Loader2, Pencil, RefreshCw, Trash2, Upload } from "lucide-react";
import {
  deleteSharedStrategy,
  getSharedStrategies,
  getStrategies,
  shareStrategy,
  type SharedStrategyEntry,
} from "@/lib/api";
import type { Strategy } from "@/types/strategy";
import { color, font } from "@/components/ui";

const OWNER_LABELS: Record<string, string> = { alvaro: "Álvaro", sailor: "Sailor" };
const nombreDev = (o: string) => OWNER_LABELS[o] || o || "—";

/* ---- lectura defensiva del JSON: nunca reventar por una forma inesperada ---- */
type Json = unknown;
const O = (x: Json): Record<string, Json> =>
  x && typeof x === "object" && !Array.isArray(x) ? (x as Record<string, Json>) : {};
const A = (x: Json): Json[] => (Array.isArray(x) ? x : []);
const S = (x: Json): string =>
  x === null || x === undefined || x === "" ? "" : typeof x === "object" ? "" : String(x);

const vacio = (x: Json): boolean =>
  x === null || x === undefined || x === "" ||
  (Array.isArray(x) && x.length === 0) ||
  (typeof x === "object" && !Array.isArray(x) && Object.keys(x as object).length === 0);

/** Claves de un objeto que NINGUNA sección desglosa a mano. La garantía que
 *  pidió Jaume: «que estén bien especificados» — si un ajuste suyo no lo
 *  conocemos, tiene que salir igual, no desaparecer. */
const resto = (o: Record<string, Json>, usadas: Set<string>): [string, Json][] =>
  Object.entries(o).filter(([k, v]) => !usadas.has(k) && !vacio(v));

/** Cualquier trozo de JSON, legible y sin suponer forma. */
function Generico({ v, nivel = 0 }: { v: Json; nivel?: number }) {
  if (Array.isArray(v)) {
    if (!v.length) return null;
    if (v.every((x) => !x || typeof x !== "object")) return <>{v.map(S).join(", ")}</>;
    return (
      <div>
        {v.map((x, i) => (
          <div key={i} style={{ marginTop: 3 }}>
            <div style={{ fontSize: 9.5, color: color.textMuted }}>#{i + 1}</div>
            <Generico v={x} nivel={nivel + 1} />
          </div>
        ))}
      </div>
    );
  }
  if (v && typeof v === "object") {
    const e = Object.entries(O(v)).filter(([, x]) => !vacio(x));
    if (!e.length) return null;
    return (
      <div style={{ borderLeft: nivel ? `1px solid ${color.border}` : undefined, paddingLeft: nivel ? 8 : 0 }}>
        {e.map(([k, x]) => (
          <div key={k} style={{ display: "flex", gap: 8, padding: "2px 0", alignItems: "baseline" }}>
            <div style={{ fontSize: 10.5, color: color.textMuted, minWidth: 130, flexShrink: 0 }}>{k}</div>
            <div style={{ flex: 1, minWidth: 0, fontSize: 11, fontFamily: font.mono, overflowWrap: "anywhere" }}>
              <Generico v={x} nivel={nivel + 1} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return <>{S(v)}</>;
}

// Lo que SÍ desglosa cada sección a mano; el resto cae en «Otros ajustes».
const USADAS_DEF = new Set(["entry_logic", "exit_logic", "pyramiding", "risk_management",
  "universe_filters", "bias", "apply_day", "market_sessions", "custom_start_time",
  "custom_end_time", "postgap_preconditions"]);
const USADAS_RM = new Set(["hard_stop", "take_profit", "take_profit_mode", "trailing_stop",
  "partial_take_profits", "swing_option", "size_by_sl", "risk_per_trade", "risk", "cangrejo_mode",
  "accept_reentries", "max_reentries"]);
const USADAS_ENT = new Set(["root_condition", "entry_time_windows", "timeframe"]);
const USADAS_UNI = new Set(["rules", "date_from", "date_to"]);
const USADAS_PIR = new Set(["levels", "mode"]);

const COMPARADOR: Record<string, string> = {
  GREATER_THAN: ">", LESS_THAN: "<", GREATER_THAN_OR_EQUAL: "≥", LESS_THAN_OR_EQUAL: "≤",
  EQUAL: "=", NOT_EQUAL: "≠", DISTANCE_GT: "se aleja más de", DISTANCE_LT: "se acerca a menos de",
  CROSSES_ABOVE: "cruza al alza", CROSSES_BELOW: "cruza a la baja",
  ">=": "≥", "<=": "≤", ">": ">", "<": "<", "=": "=",
};
const SESION: Record<string, string> = { rth: "RTH", pre: "Premercado", post: "After", custom: "Personalizada" };
const DIA: Record<string, string> = { gap_day: "Día del gap", gap_1_day: "Día del gap +1", gap_2_day: "Día del gap +2" };
const CANGREJO: Record<string, string> = { recorrido: "Cangrejo por recorrido", perdida: "Cangrejo por pérdida" };

/* Una condición, en una línea que se lee. Los extras del `source` (dirección
   del squeeze, sesión de anclaje, referencia del fade…) van detrás, apagados. */
const CLAVES_COND = new Set(["source", "level", "metric", "type", "timeframe", "comparator",
  "operator", "value", "target", "threshold", "unit", "position", "id", "conditions"]);
const CLAVES_SRC = new Set(["name", "squeeze_direction", "ap_session", "session_ref", "fade_ref", "type", "id"]);

function condicionTexto(c: Record<string, Json>): { txt: string; extra: string } {
  const src = O(c.source), lvl = O(c.level);
  const nombre = S(src.name) || S(lvl.name) || S(c.metric) || S(c.type) || "condición";
  const tf = S(c.timeframe) ? ` [${S(c.timeframe)}]` : "";
  const cmpRaw = S(c.comparator) || S(c.operator);
  const cmp = COMPARADOR[cmpRaw] || cmpRaw;
  const val = S(c.value) || S(c.target) || S(c.threshold);
  const unidad = S(c.unit) || (S(c.type) === "price_level_distance" ? "%" : "");
  const extras = ([
    S(src.squeeze_direction) && `dirección ${S(src.squeeze_direction)}`,
    S(src.ap_session) && `ancla ${S(src.ap_session)}`,
    S(src.session_ref) && `sesión ${S(src.session_ref)}`,
    S(src.fade_ref) && `desde ${S(src.fade_ref)}`,
    S(c.position) && `precio ${S(c.position)}`,
    ...resto(src, CLAVES_SRC).map(([k, v]) => `${k}=${S(v) || JSON.stringify(v)}`),
    ...resto(c, CLAVES_COND).map(([k, v]) => `${k}=${S(v) || JSON.stringify(v)}`),
  ].filter(Boolean) as string[]);
  return {
    txt: `${nombre}${tf} ${cmp} ${val}${val ? unidad : ""}`.replace(/\s+/g, " ").trim(),
    extra: extras.join(" · "),
  };
}

function contarHojas(nodo: Json): number {
  const n = O(nodo);
  const hijos = A(n.conditions);
  if (!hijos.length) return Object.keys(n).length ? 1 : 0;
  return hijos.reduce((a: number, h) => a + contarHojas(h), 0);
}

/* Árbol de condiciones: los grupos se anidan con su operador en el raíl. */
function Arbol({ nodo, nivel = 0 }: { nodo: Json; nivel?: number }) {
  const n = O(nodo);
  const hijos = A(n.conditions);
  if (hijos.length) {
    const op = S(n.operator) || "AND";
    return (
      <div style={{
        borderLeft: nivel === 0 ? undefined : `1px solid ${color.border}`,
        paddingLeft: nivel === 0 ? 0 : 10, marginTop: nivel === 0 ? 0 : 4,
      }}>
        {hijos.map((h, i) => (
          <div key={i}>
            {i > 0 && (
              <div style={{ fontSize: 9.5, letterSpacing: "0.12em", color: color.copperBright, margin: "3px 0" }}>
                {op === "OR" ? "Ó" : "Y"}
              </div>
            )}
            <Arbol nodo={h} nivel={nivel + 1} />
          </div>
        ))}
      </div>
    );
  }
  if (!Object.keys(n).length) return null;
  const { txt, extra } = condicionTexto(n);
  return (
    <div style={{ fontSize: 11.5, color: color.textPrimary, lineHeight: 1.5 }}>
      <span style={{ fontFamily: font.mono }}>{txt}</span>
      {extra && <span style={{ color: color.textMuted, fontSize: 10.5 }}> · {extra}</span>}
    </div>
  );
}

function Fila({ k, v }: { k: string; v: React.ReactNode }) {
  if (v === null || v === undefined || v === "" || v === false) return null;
  return (
    <div style={{ display: "flex", gap: 10, padding: "3px 0", borderBottom: `0.5px solid ${color.border}` }}>
      <div style={{ width: 168, flexShrink: 0, fontSize: 10.5, color: color.textMuted }}>{k}</div>
      <div style={{ flex: 1, minWidth: 0, fontSize: 11.5, color: color.textPrimary, fontFamily: font.mono, overflowWrap: "anywhere" }}>{v}</div>
    </div>
  );
}

function Apartado({ t, children }: { t: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{
        fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: color.copperBright,
        marginBottom: 5, paddingBottom: 3, borderBottom: `1px solid ${color.border}`,
      }}>{t}</div>
      {children}
    </div>
  );
}

function Dato({ k, v, ultima }: { k: string; v: string; ultima?: boolean }) {
  return (
    <div style={{ flex: 1, padding: "0 12px", minWidth: 0, borderRight: ultima ? undefined : `0.5px solid ${color.border}` }}>
      <div style={{ fontSize: 9.5, letterSpacing: "0.07em", textTransform: "uppercase", color: color.textMuted }}>{k}</div>
      <div style={{ fontFamily: font.mono, fontSize: 15, color: color.textHigh, marginTop: 2, overflowWrap: "anywhere" }}>{v}</div>
    </div>
  );
}

const btn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px",
  fontFamily: font.sans, fontSize: 10, fontWeight: 700, textTransform: "uppercase",
  letterSpacing: "0.08em", background: "transparent", border: `0.5px solid ${color.border}`,
  color: color.textMuted, cursor: "pointer", whiteSpace: "nowrap",
};
const th: React.CSSProperties = {
  textAlign: "left", padding: "8px 12px", fontFamily: font.sans, fontSize: 9.5, fontWeight: 700,
  textTransform: "uppercase", letterSpacing: "0.12em", color: color.textMuted, opacity: 0.7,
};
const td: React.CSSProperties = {
  padding: "8px 12px", fontFamily: font.sans, fontSize: 12, color: color.textPrimary,
  borderBottom: `0.5px solid ${color.border}`,
};

/* ---- la radiografía ---- */
function Detalle({ entry }: { entry: SharedStrategyEntry }) {
  const [crudo, setCrudo] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const d = O(entry.definition as Json);
  const ent = O(d.entry_logic), sal = O(d.exit_logic), pir = O(d.pyramiding);
  const rm = O(d.risk_management), uni = O(d.universe_filters);
  const hs = O(rm.hard_stop), tp = O(rm.take_profit), ts = O(rm.trailing_stop), sw = O(rm.swing_option);
  const ventanas = A(ent.entry_time_windows)
    .map((w) => `${S(O(w).from_time)}–${S(O(w).to_time)}`).filter((x) => x !== "–");
  const sesiones = A(d.market_sessions).map((s) => SESION[S(s)] || S(s)).join(" + ");
  const reglas = A(uni.rules), niveles = A(pir.levels), parciales = A(rm.partial_take_profits);

  const json = useMemo(() => JSON.stringify(entry.definition, null, 2), [entry.definition]);
  const copiar = () => {
    navigator.clipboard?.writeText(json)
      .then(() => { setCopiado(true); setTimeout(() => setCopiado(false), 1600); })
      .catch(() => {});
  };

  return (
    <div style={{ background: color.bgSurface, border: `1px solid ${color.border}`, padding: 14, margin: "2px 0 8px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: color.textHigh }}>{entry.name}</span>
        <span style={{ fontSize: 11, color: color.textMuted }}>de {nombreDev(entry.shared_by)}</span>
      </div>
      {/* La descripcion NO se pinta aqui a proposito (DECISION DE JAUME,
       *  10-sep-2026). Al guardar con «incluir What-if» marcado se le mete
       *  dentro el volcado entero de parametros, `locates_by_pair` incluido:
       *  una estrategia real traia 43.191 caracteres de pares ticker|fecha.
       *  Esta pantalla quiere el NOMBRE y, al desplegar, la estrategia. */}
      <div style={{ fontSize: 10.5, color: color.textMuted, marginTop: 4 }}>
        Se muestra el fichero entero: lo que no esté desglosado abajo sale en «Otros ajustes», y siempre queda el JSON crudo.
      </div>

      {/* Los «stats» de un vistazo: el tamaño y la forma de la estrategia. */}
      <div style={{ display: "flex", marginTop: 12, paddingTop: 10, borderTop: `0.5px solid ${color.border}` }}>
        <Dato k="Sesgo" v={S(d.bias).toLowerCase() === "short" ? "Corto" : S(d.bias).toLowerCase() === "long" ? "Largo" : S(d.bias) || "—"} />
        <Dato k="Día" v={DIA[S(d.apply_day)] || S(d.apply_day) || "—"} />
        <Dato k="Cond. entrada" v={String(contarHojas(ent.root_condition))} />
        <Dato k="Cond. salida" v={String(contarHojas(sal.root_condition))} />
        <Dato k="Pirámides" v={niveles.length ? `${niveles.length} nivel${niveles.length > 1 ? "es" : ""}` : "no"} />
        <Dato k="Filtros universo" v={String(reglas.length)} ultima />
      </div>

      {/* Las condiciones van LAS PRIMERAS: es lo que se viene a mirar cuando
       *  se despliega una compartida. El resto de la radiografia sigue
       *  entero debajo. */}
      <Apartado t="Condiciones de entrada">
        {contarHojas(ent.root_condition)
          ? <Arbol nodo={ent.root_condition} />
          : <div style={{ fontSize: 11.5, color: color.textMuted }}>sin condiciones</div>}
      </Apartado>

      {contarHojas(sal.root_condition) > 0 && (
        <Apartado t="Condiciones de salida"><Arbol nodo={sal.root_condition} /></Apartado>
      )}

      <Apartado t="Cuándo puede entrar">
        <Fila k="Sesiones" v={sesiones} />
        <Fila k="Horario personalizado" v={S(d.custom_start_time) && `${S(d.custom_start_time)} – ${S(d.custom_end_time)}`} />
        <Fila k="Ventana de entrada" v={ventanas.join(", ")} />
        <Fila k="Temporalidad" v={S(ent.timeframe)} />
        {resto(ent, USADAS_ENT).map(([k, v]) => <Fila key={k} k={k} v={<Generico v={v} />} />)}
      </Apartado>

      {contarHojas(d.postgap_preconditions) > 0 && (
        <Apartado t="Precondiciones post-gap"><Arbol nodo={d.postgap_preconditions} /></Apartado>
      )}

      {reglas.length > 0 && (
        <Apartado t="Universo (qué tickers entran)">
          <Fila k="Fechas" v={S(uni.date_from) && `${S(uni.date_from)} → ${S(uni.date_to)}`} />
          {reglas.map((rg, i) => {
            const g = O(rg);
            const cmp = COMPARADOR[S(g.operator)] || S(g.operator);
            return <Fila key={i} k={i === 0 ? "Reglas" : ""} v={`${S(g.metric)} ${cmp} ${S(g.value)}`} />;
          })}
          {resto(uni, USADAS_UNI).map(([k, v]) => <Fila key={k} k={k} v={<Generico v={v} />} />)}
        </Apartado>
      )}

      <Apartado t="Riesgo y salidas">
        <Fila k="Stop" v={S(hs.type) && `${S(hs.type)}${S(hs.value) ? ` · ${S(hs.value)}` : ""}${S(hs.operator) ? ` (${COMPARADOR[S(hs.operator)] || S(hs.operator)})` : ""}`} />
        <Fila k="Tamaño por stop" v={rm.size_by_sl ? "sí" : ""} />
        <Fila k="Riesgo por operación" v={S(rm.risk_per_trade) || S(rm.risk)} />
        <Fila k="Estilo Cangrejo" v={CANGREJO[S(rm.cangrejo_mode)] || S(rm.cangrejo_mode)} />
        {/* Las reentradas se explicitan (antes caían en crudo en «Otros ajustes»)
         * porque son una trampa clásica al cruzar formatos: aquí max_reentries=-1
         * con accept_reentries activo son reentradas ILIMITADAS, no «ninguna». */}
        <Fila k="Reentradas" v={(() => {
          if (rm.accept_reentries === false) return "no";
          const mx = rm.max_reentries;
          if (mx === null || mx === undefined || mx === "" || S(mx) === "-1") {
            return <span style={{ color: color.loss }}>⚠ ILIMITADAS aquí (max_reentries={S(mx) || "—"} = sin límite en este motor)</span>;
          }
          return `máx ${S(mx)}`;
        })()} />
        <Fila k="Take profit" v={S(rm.take_profit_mode) && `${S(rm.take_profit_mode)}${S(tp.type) ? ` · ${S(tp.type)} ${S(tp.value)}` : ""}`} />
        {parciales.map((p, i) => {
          const q = O(p);
          const extra = resto(q, new Set(["size_pct", "qty_pct", "distance_pct"]))
            .map(([k, v]) => `${k}=${S(v) || JSON.stringify(v)}`).join(" · ");
          return <Fila key={i} k={i === 0 ? "Parciales" : ""}
                       v={`${S(q.size_pct) || S(q.qty_pct)}% a ${S(q.distance_pct)}${extra ? ` · ${extra}` : ""}`} />;
        })}
        <Fila k="Trailing" v={S(ts.type) && `${S(ts.type)} ${S(ts.value)}`} />
        <Fila k="Swing" v={S(sw.target_day) && (DIA[S(sw.target_day)] || S(sw.target_day))} />
        {resto(hs, new Set(["type", "value", "operator"])).map(([k, v]) => <Fila key={`hs${k}`} k={`stop · ${k}`} v={<Generico v={v} />} />)}
        {resto(tp, new Set(["type", "value"])).map(([k, v]) => <Fila key={`tp${k}`} k={`take profit · ${k}`} v={<Generico v={v} />} />)}
        {resto(ts, new Set(["type", "value"])).map(([k, v]) => <Fila key={`ts${k}`} k={`trailing · ${k}`} v={<Generico v={v} />} />)}
        {resto(sw, new Set(["target_day"])).map(([k, v]) => <Fila key={`sw${k}`} k={`swing · ${k}`} v={<Generico v={v} />} />)}
        {resto(rm, USADAS_RM).map(([k, v]) => <Fila key={k} k={k} v={<Generico v={v} />} />)}
      </Apartado>

      {niveles.length > 0 && (
        <Apartado t="Pirámides">
          <Fila k="Modo" v={S(pir.mode)} />
          {niveles.map((lv, i) => {
            const l = O(lv);
            return (
              <div key={i} style={{ padding: "6px 0", borderBottom: `0.5px solid ${color.border}` }}>
                <div style={{ fontSize: 10.5, color: color.textMuted }}>
                  Nivel {i + 1} · {S(l.action) === "add" ? "añade" : S(l.action)} {S(l.size)}{S(l.unit) === "pct" ? "%" : S(l.unit)}
                  {resto(l, new Set(["action", "size", "unit", "root_condition"]))
                    .map(([k, v]) => ` · ${k}=${S(v) || JSON.stringify(v)}`).join("")}
                </div>
                <div style={{ marginTop: 3 }}><Arbol nodo={l.root_condition} /></div>
              </div>
            );
          })}
          {resto(pir, USADAS_PIR).map(([k, v]) => <Fila key={k} k={k} v={<Generico v={v} />} />)}
        </Apartado>
      )}

      {resto(d, USADAS_DEF).length > 0 && (
        <Apartado t="Otros ajustes de la estrategia">
          {resto(d, USADAS_DEF).map(([k, v]) => <Fila key={k} k={k} v={<Generico v={v} />} />)}
        </Apartado>
      )}

      <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={() => setCrudo((v) => !v)} style={btn}>{crudo ? "Ocultar JSON" : "Ver JSON crudo"}</button>
        <button onClick={copiar} style={btn}>{copiado ? "Copiado" : "Copiar JSON"}</button>
        <span style={{ fontSize: 10.5, color: color.textMuted }}>
          «Abrir borrador» la carga en el builder para revisarla y ajustarla — no se guarda nada y el dataset lo eliges tú en el panel (el <code>dataset_id</code> del JSON es de quien la compartió y no existe en tu base).
        </span>
      </div>
      {crudo && (
        <pre style={{
          marginTop: 8, maxHeight: 380, overflow: "auto", background: color.bgElevated,
          border: `1px solid ${color.border}`, padding: 10, fontFamily: font.mono, fontSize: 10.5,
          color: color.textSecondary, lineHeight: 1.45,
        }}>{json}</pre>
      )}
    </div>
  );
}

function Titulo({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: color.textHigh }}>{children}</div>
      {hint && <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2, lineHeight: 1.5 }}>{hint}</div>}
    </div>
  );
}

/* ---- la pestaña ---- */
export default function SharedStrategiesTab({ onOpenDraft }: { onOpenDraft?: (entry: SharedStrategyEntry) => void }) {
  const [owner, setOwner] = useState("");
  const [compartidas, setCompartidas] = useState<SharedStrategyEntry[]>([]);
  const [mias, setMias] = useState<Strategy[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [ocupada, setOcupada] = useState<string | null>(null);

  // Listas independientes: si una falla (p. ej. backend sin reiniciar y sin el
  // endpoint), la otra sigue visible en vez de vaciar la pestaña entera.
  const cargar = useCallback(async () => {
    const [sh, st] = await Promise.allSettled([getSharedStrategies(), getStrategies()]);
    if (sh.status === "fulfilled") { setOwner(sh.value.owner); setCompartidas(sh.value.strategies); }
    if (st.status === "fulfilled") setMias(st.value);
    const fallo = sh.status === "rejected" ? sh.reason : st.status === "rejected" ? (st as PromiseRejectedResult).reason : null;
    setError(fallo ? `${fallo instanceof Error ? fallo.message : String(fallo)} — si es un 404, el backend necesita reinicio para cargar el endpoint de compartidas` : null);
    setCargando(false);
  }, []);

  useEffect(() => { void cargar(); }, [cargar]);

  const compartir = async (s: Strategy) => {
    if (!s.id) return;
    setOcupada(s.id); setError(null);
    try { await shareStrategy(s.id); await cargar(); }
    catch (e) { setError(e instanceof Error ? e.message : "No se pudo compartir"); }
    finally { setOcupada(null); }
  };

  const borrar = async (entry: SharedStrategyEntry) => {
    const mia = entry.shared_by === owner;
    // Borrar la del otro es destructivo Y VIAJA: al commitear y subir, le
    // desaparece a él también. Recuperable por git, pero hay que decirlo.
    const aviso = mia
      ? `¿Borrar "${entry.name}" de estrategias_compartidas?

Se quita el fichero de tu carpeta. Cuando subas el borrado, dejará de verla el otro.`
      : `¿Borrar "${entry.name}", que compartió ${nombreDev(entry.shared_by)}?

Borra SU fichero del repo. Cuando subas el borrado, también desaparecerá para él (se puede recuperar por git).`;
    if (!window.confirm(aviso)) return;
    setOcupada(entry.filename); setError(null);
    try {
      await deleteSharedStrategy(entry.filename, entry.shared_by || undefined);
      if (abierta === entry.filename) setAbierta(null);
      await cargar();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo borrar"); }
    finally { setOcupada(null); }
  };

  const yaCompartida = (id?: string) => !!id && compartidas.some((c) => c.source_strategy_id === id && c.shared_by === owner);

  return (
    <div style={{ padding: 14, fontFamily: font.sans, color: color.textPrimary }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <Titulo hint="Los JSON viven en estrategias_compartidas/ y viajan por git: nada se comparte hasta que commiteas esa carpeta. Pulsa una para ver cómo está montada y, si te convence, ábrela como borrador en el builder para revisarla y ajustarla antes de correr. Borrar quita el fichero del repo — también las del otro, para que la lista no se acumule.">
            En el repo
          </Titulo>
        </div>
        <button onClick={() => void cargar()} style={btn} disabled={cargando}>
          <RefreshCw size={11} /> Refrescar
        </button>
      </div>

      {error && (
        <div style={{ background: color.bgElevated, border: `1px solid ${color.loss}`, padding: "7px 11px", fontSize: 11.5, color: color.loss, marginBottom: 10 }}>
          {error}
        </div>
      )}

      {cargando ? (
        <div style={{ display: "flex", alignItems: "center", gap: 7, padding: 16, fontSize: 12, color: color.textMuted }}>
          <Loader2 size={13} className="animate-spin" /> Cargando…
        </div>
      ) : compartidas.length === 0 ? (
        <div style={{ border: `1px dashed ${color.border}`, padding: 20, fontSize: 12, color: color.textMuted, textAlign: "center" }}>
          No hay ninguna estrategia compartida todavía. Haz <b>pull</b> de staging, o comparte una tuya abajo.
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${color.border}` }}>
              <th style={{ ...th, width: "48%" }}>Estrategia</th>
              <th style={{ ...th, width: "14%" }}>De</th>
              <th style={{ ...th, width: "22%" }}>Compartida</th>
              <th style={{ ...th, width: "16%" }} />
            </tr>
          </thead>
          <tbody>
            {compartidas.map((c) => {
              const mia = c.shared_by === owner;
              const activa = abierta === c.filename;
              return (
                <React.Fragment key={c.filename}>
                  <tr onClick={() => setAbierta(activa ? null : c.filename)}
                      style={{ cursor: "pointer", background: activa ? color.bgElevated : "transparent" }}>
                    <td style={{ ...td, overflow: "hidden", textOverflow: "ellipsis" }}>
                      <span style={{ color: color.copperBright, marginRight: 6 }}>{activa ? "▾" : "▸"}</span>
                      {c.name}
                    </td>
                    <td style={{ ...td, color: mia ? color.copperBright : color.textSecondary }}>
                      {nombreDev(c.shared_by)}{mia ? " (tú)" : ""}
                    </td>
                    <td style={{ ...td, fontFamily: font.mono, fontSize: 11, color: color.textMuted }}>
                      {c.shared_at ? String(c.shared_at).slice(0, 16).replace("T", " ") : "—"}
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>
                      <div style={{ display: "inline-flex", gap: 6 }}>
                        {onOpenDraft && (
                          <button
                            onClick={(e) => { e.stopPropagation(); onOpenDraft(c); }}
                            style={btn}
                            title="La abre como BORRADOR en el builder para revisar criterios, universo y riesgo antes de correr. No guarda nada en tus estrategias."
                            onMouseEnter={(ev) => { ev.currentTarget.style.color = color.copperBright; ev.currentTarget.style.borderColor = color.copperBright; }}
                            onMouseLeave={(ev) => { ev.currentTarget.style.color = color.textMuted; ev.currentTarget.style.borderColor = color.border; }}
                          >
                            <Pencil size={11} /> Abrir borrador
                          </button>
                        )}
                        <button
                          onClick={(e) => { e.stopPropagation(); void borrar(c); }}
                          style={btn}
                          disabled={ocupada === c.filename}
                          title={mia ? "Borrar tu fichero compartido" : `Borrar el fichero que compartió ${nombreDev(c.shared_by)}`}
                          onMouseEnter={(ev) => { ev.currentTarget.style.color = color.loss; ev.currentTarget.style.borderColor = color.loss; }}
                          onMouseLeave={(ev) => { ev.currentTarget.style.color = color.textMuted; ev.currentTarget.style.borderColor = color.border; }}
                        >
                          {ocupada === c.filename ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />} Borrar
                        </button>
                      </div>
                    </td>
                  </tr>
                  {activa && (
                    <tr>
                      <td colSpan={4} style={{ padding: 0, borderBottom: `0.5px solid ${color.border}` }}>
                        <Detalle entry={c} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: 24, paddingTop: 14, borderTop: `1px solid ${color.border}` }}>
        <Titulo hint={`Escribe el JSON en estrategias_compartidas/${owner || "dev"}/. Solo sale de tu disco cuando commiteas esa carpeta y la subes.${owner && owner !== "dev" ? "" : " ⚠ Falta SHARED_STRATEGIES_OWNER en backend/.env: tus compartidas caen en dev/."}`}>
          Compartir una tuya
        </Titulo>
        {mias.length === 0 ? (
          <div style={{ fontSize: 12, color: color.textMuted }}>No tienes estrategias guardadas.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <tbody>
              {mias.map((s) => (
                <tr key={s.id}>
                  <td style={{ ...td, width: "70%", overflow: "hidden", textOverflow: "ellipsis" }}>{s.name}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <button onClick={() => void compartir(s)} style={btn} disabled={ocupada === s.id || !s.id}>
                      {ocupada === s.id ? <Loader2 size={11} className="animate-spin" />
                        : yaCompartida(s.id) ? <Check size={11} /> : <Upload size={11} />}
                      {yaCompartida(s.id) ? "Actualizar" : "Compartir"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
