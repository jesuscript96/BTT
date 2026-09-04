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
  borrarCorrida,
  crearCorrida,
  getCatalogo,
  guardarComoEstrategia,
  listarCorridas,
  listarDatasets,
  pararCorrida,
  reanudarCorrida,
  verCorrida,
  type CatalogoGenetico,
  type CondicionMotor,
  type ConfigCorrida,
  type CorridaDetalle,
  type CorridaResumen,
  type DatasetResumen,
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

function guardaMotor(nombre: string, comparador: string, valor: number): CondicionMotor {
  return { type: "indicator_comparison", source: { name: nombre, offset: 0 }, comparator: comparador, target: valor, timeframe: "1m" };
}

/* ── pagina ──────────────────────────────────────────────────────────── */

export default function GeneticoPage() {
  const [catalogo, setCatalogo] = useState<CatalogoGenetico | null>(null);
  const [datasets, setDatasets] = useState<DatasetResumen[]>([]);
  const [corridas, setCorridas] = useState<CorridaResumen[]>([]);
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<CorridaDetalle | null>(null);
  const [comparar, setComparar] = useState<string | null>(null);
  const [detalleB, setDetalleB] = useState<CorridaDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lanzando, setLanzando] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);

  // ── formulario ──
  const [nombre, setNombre] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [fechaIni, setFechaIni] = useState("2019-01-01");
  const [fechaFin, setFechaFin] = useState("2024-12-31");
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
    listarDatasets()
      .then((d) => { setDatasets(d); if (d.length && !datasetId) setDatasetId(d[0].id); })
      .catch((e) => setError(`No cargaron los datasets: ${String(e)}`));
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

  /* config que se manda */
  const config: ConfigCorrida & { parar_a_las?: string | null } = useMemo(() => {
    // Las guardas activas, en el orden del catálogo. Se arman desde la lista
    // que manda el backend: una guarda nueva allí aparece aquí sola.
    const guardasMotor: CondicionMotor[] = (catalogo?.guardas ?? [])
      .filter((g) => guardas[g.clave]?.on)
      .map((g) => guardaMotor(g.indicador, g.comparador, guardas[g.clave].valor));
    return {
      dataset_id: datasetId, fecha_ini: fechaIni || null, fecha_fin: fechaFin || null,
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
    };
  }, [datasetId, fechaIni, fechaFin, sesgo, sesion, horaIni, horaFin, ventanaOn, ventanaDe, ventanaA,
    catalogo, guardas, indicadores, nCond, stopPct, stopEstructura, tpPct, tpHora, tpTiempo, riesgo, fitness, minTrades,
    semilla, poblacion, generaciones, workers, paciencia, pararALas, pararALasOn]);

  const estimacion = useMemo(() => {
    const elite = Math.max(1, Math.round(poblacion * 0.05));
    const evals = Math.round(poblacion + generaciones * (poblacion - elite) * 0.65);
    return { evals, con1: evals * SEG_POR_EVAL, con2: evals * SEG_POR_EVAL / 2, con4: evals * SEG_POR_EVAL / 4 };
  }, [poblacion, generaciones]);

  const problemas: string[] = [];
  if (!config.dataset_id) problemas.push("elige un dataset");
  if (config.catalogo.length === 0) problemas.push("marca algún indicador");
  if (config.catalogo.length < config.n_condiciones) problemas.push("más indicadores que condiciones");
  if (config.stops.length === 0) problemas.push("marca algún tipo de stop");
  if (config.tps.length === 0) problemas.push("marca algún tipo de take profit");

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
    await accion(() => guardarComoEstrategia(nombreEst, desc, m.definicion, detalle.config.dataset_id), `Guardada «${nombreEst}»: ábrela en el Backtester.`);
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

        <Sec title="Datos" help="Qué ticker-días se usan. El dataset es uno de los tuyos (mismos filtros de universo que en el Backtester). El periodo es el IS: lo que el genético puede ver.">
          <Row label="Nombre" help="Solo para reconocer la corrida en la lista. Si lo dejas vacío se usa la fecha y hora.">
            <input style={{ ...control, fontFamily: font.sans }} value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="opcional" />
          </Row>
          <Row label="Dataset" help="Universo de ticker-días sobre el que se evalúa cada candidato. Igual que elegirlo en el Backtester.">
            <Sel value={datasetId} onChange={setDatasetId}
              options={datasets.map((d) => ({ value: d.id, label: `${d.name}${d.pair_count ? ` (${entero(d.pair_count)})` : ""}` }))} />
          </Row>
          <Row label="IS desde / hasta" help="Periodo dentro de la muestra. Deja fuera el tramo más reciente (p. ej. 2025→hoy): es tu OOS y solo se usa UNA vez, al final, con los finalistas.">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              <input type="date" style={control} value={fechaIni} onChange={(e) => setFechaIni(e.target.value)} />
              <input type="date" style={control} value={fechaFin} onChange={(e) => setFechaFin(e.target.value)} />
            </div>
          </Row>
        </Sec>

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

        <Sec title="Riesgo" help="Los mismos ajustes que el panel de riesgo del Backtester. Para que la R media sea una R de verdad: riesgo fijo en $ con «shares por distancia al SL» activado. Nunca % de equity: con composición y liquidez infinita el genético aprende a apalancarse, no a operar.">
          <Row label="Capital"><Num value={riesgo.init_cash} onChange={(v) => setRiesgo({ ...riesgo, init_cash: v })} min={100} step={1000} /></Row>
          <Row label="Riesgo fijo $" help="Dólares que arriesga cada operación (distancia al stop × acciones). Es la unidad R de la tabla."><Num value={riesgo.risk_r} onChange={(v) => setRiesgo({ ...riesgo, risk_r: v })} min={1} step={10} /></Row>
          <Row label="Comisión %"><Num value={riesgo.fees} onChange={(v) => setRiesgo({ ...riesgo, fees: v })} min={0} step={0.01} /></Row>
          <Row label="Slippage %" help="Se aplica en la entrada y en cada salida. Con stops estrechos pesa mucho: coste en R ≈ 2 × slippage ÷ distancia al stop."><Num value={riesgo.slippage} onChange={(v) => setRiesgo({ ...riesgo, slippage: v })} min={0} step={0.05} /></Row>
          <Row label="Coste locates"><Num value={riesgo.locates_cost} onChange={(v) => setRiesgo({ ...riesgo, locates_cost: v })} min={0} step={0.01} /></Row>
          <Row label="Tope locates" help="Máximo de paquetes de 100 acciones en corto por ticker-día (0 = sin tope). Acota el tamaño y cierra el atajo del stop a distancia cero."><Num value={riesgo.max_locates} onChange={(v) => setRiesgo({ ...riesgo, max_locates: v })} min={0} step={10} /></Row>
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
            <Check checked={!!riesgo.hybrid_stop} onChange={(v) => setRiesgo({ ...riesgo, hybrid_stop: v })} label="Activado" />
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
        </Sec>

        <Sec title="Búsqueda" help="Cómo busca. Población = cuántas estrategias viven a la vez; generaciones = cuántas rondas de probar, descartar, cruzar y mutar. El total de backtests es aproximadamente población × generaciones, menos los repetidos.">
          <Row label="Nota (fitness)" help="La nota de cada estrategia. Por defecto R media × √operaciones: premia el edge por operación y que ocurra a menudo, sin que 4.000 operaciones valgan 40 veces más que 100. Nunca retorno total.">
            <Sel value={fitness} onChange={setFitness} options={(catalogo?.fitness ?? []).map((f) => ({ value: f.id, label: f.label }))} />
          </Row>
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
                          <Td style={tdTxt}>{m.receta}</Td>
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
