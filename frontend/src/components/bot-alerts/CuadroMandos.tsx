"use client";

/**
 * Cuadro de mandos del bot de alertas.
 *
 * Estetica de hoja de calculo a proposito: rejilla densa, filas bajas, numeros
 * en monoespaciada y alineados a la derecha. El color NO decora — solo aparece
 * donde significa algo: direccion, tipo de aviso y estado.
 *
 * TRES COSAS QUE NO SON OBVIAS:
 *
 * 1. Las acciones se RECALCULAN al precio actual, no se muestra el numero
 *    congelado del aviso. El aviso sale al cierre de la vela de la senal y para
 *    cuando se pone la orden el precio se ha movido (0,5% de media, hasta 6%);
 *    con el numero viejo el riesgo real deja de ser el pedido.
 *
 * 2. PORTFOLIO E INCUBADORA VAN EN TABLAS SEPARADAS. Lo que se opera y lo que
 *    se esta validando no se mezclan: si se mezclaran, una estrategia en pruebas
 *    podria confundirse con una buena en el momento de operar.
 *
 * 3. El interruptor NO arranca ni mata ningun proceso. Solo deja escrito que el
 *    bot debe vigilar; el bot vive en su propio proceso y lo consulta.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, BellOff, Radio, Trash2 } from "lucide-react";

import { color, font, hairline, ErrorBox, Loading } from "@/components/ui";
import { API_BASE } from "@/lib/api";
import {
  accionesAlPrecio,
  cambiarEstado,
  guardarVigilancia,
  listarEstrategias,
  listarEventos,
  listarFechas,
  limpiarEventos,
  leerEstado,
  leerDiario,
  leerDiarioTexto,
  explicarEstrategia,
  limpiarInactivo,
  type Diario,
  type ExplicacionEstrategia,
  type EstadoBot,
  type EstrategiaCandidata,
  type EventoAlerta,
  type Radar,
} from "@/lib/api_bot_alerts";

const SONIDO_KEY = "botAlertas.sonido.v1";
/** Lo que se teclea en el radar (locate y EV por ticker). Se guarda en el
 *  navegador para no volver a escribirlo en cada recarga: son datos de la
 *  sesión de hoy, no configuración que deba viajar a ningún sitio. */
const LOCATES_KEY = "botAlertas.locates.v1";
const REFRESCO_MS = 2000;

/** Sin latido en este tiempo, el bot se considera caido aunque figure encendido. */
const LATIDO_VIVO_MS = 30_000;
/** Cuanto tarda una fila en volver a su fondo normal. */
const DESTACADO_MS = 12_000;

/**
 * Destellos de fila, como animacion del NAVEGADOR y no recalculando el color en
 * React: asi el degradado es continuo de verdad y no cuesta un re-render cada
 * pocos milisegundos.
 *
 * Ambar para la prealerta, rojo para la alerta confirmada. Muy diluidos (0,16 de
 * opacidad) — tienen que leerse de reojo, no gritar: en una sesion movida la
 * tabla entera estaria parpadeando.
 */
const ANIMACIONES = `
@keyframes bot-flash-prealerta {
  from { background-color: rgba(210,160,84,0.16); }
  to   { background-color: rgba(210,160,84,0); }
}
@keyframes bot-flash-alerta {
  from { background-color: rgba(201,77,63,0.16); }
  to   { background-color: rgba(201,77,63,0); }
}
@media (prefers-reduced-motion: reduce) {
  .bot-fila-prealerta, .bot-fila-alerta { animation: none !important; }
}
`;

/** Alto fijo de las rejillas. Fijo A PROPOSITO: si creciera con cada aviso, la
 *  pagina se estiraria sin fin y habria que buscar la barra de estado. */
const ALTO_PORTFOLIO = 430;
const ALTO_INCUBADORA = 210;
const ALTO_RADAR = 260;

/* ── Piezas de rejilla ────────────────────────────────────────────────── */

function Th({ children, num = false, ancho }: {
  children?: React.ReactNode; num?: boolean; ancho?: number;
}) {
  return (
    <th style={{
      textAlign: num ? "right" : "left",
      fontFamily: font.sans, fontSize: 9, fontWeight: 500,
      letterSpacing: "0.09em", textTransform: "uppercase",
      color: color.textMuted, padding: "7px 10px 6px",
      borderBottom: `0.5px solid ${color.border}`,
      whiteSpace: "nowrap", width: ancho,
      // Sticky: al desplazar la lista larga, las cabeceras se quedan.
      position: "sticky", top: 0, background: color.bgSurface, zIndex: 1,
    }}>{children}</th>
  );
}

function Td({ children, num = false, mono = false, tono, dim = false, title, fuerte = false }: {
  children?: React.ReactNode; num?: boolean; mono?: boolean;
  tono?: string; dim?: boolean; title?: string; fuerte?: boolean;
}) {
  return (
    <td title={title} style={{
      textAlign: num ? "right" : "left",
      fontFamily: mono || num ? font.mono : font.sans,
      // Los tres numeros que se teclean en el broker (precio, stop, acciones)
      // van en NEGRITA, no mas grandes: cambiar el cuerpo rompia la alineacion
      // optica de la rejilla y hacia que la fila pareciera de otra tabla.
      fontSize: 11.5,
      fontWeight: fuerte ? 700 : 400,
      fontVariantNumeric: num ? "tabular-nums" : undefined,
      color: tono || (dim ? color.textMuted : color.textPrimary),
      padding: "5px 10px",
      borderBottom: `0.5px solid ${color.border}`,
      whiteSpace: "nowrap",
    }}>{children}</td>
  );
}

function Seccion({ titulo, extra, alto, children }: {
  titulo: string; extra?: React.ReactNode; alto?: number; children: React.ReactNode;
}) {
  return (
    <section style={{ marginTop: 22 }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, marginBottom: 7,
      }}>
        <h2 style={{
          fontFamily: font.sans, fontSize: 10, fontWeight: 600,
          letterSpacing: "0.11em", textTransform: "uppercase",
          color: color.textSecondary, margin: 0,
        }}>{titulo}</h2>
        {extra}
      </div>
      <div style={{
        background: color.bgSurface, border: hairline, borderRadius: 3,
        overflowX: "auto", overflowY: alto ? "auto" : undefined,
        maxHeight: alto,
      }}>{children}</div>
    </section>
  );
}

const fmt = (v: number | null | undefined, d = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toLocaleString("es-ES", {
    minimumFractionDigits: d, maximumFractionDigits: d,
  });

const hora = (m: string) => (m || "").slice(11, 16);

/** ¿Compensa alquilar los locates de esta acción?
 *
 *      fade necesario (%) = coste por acción / precio × 100
 *      compensa           ⟺  EV (%) > fade necesario (%)
 *
 * EL TAMAÑO NO ENTRA. Ganancia esperada y coste escalan los dos con el número
 * de acciones, así que se cancela: si el fade no llega para un locate, tampoco
 * para mil. Lo comprobó Jaume preguntándolo y es correcto.
 *
 * `paquete` sí cambia el resultado en posiciones pequeñas: los locates se
 * cobran por lotes de 100 redondeando hacia ARRIBA, así que 150 acciones pagan
 * 2 paquetes y el coste real por acción sube un 33 %. Con 1.600 es ruido.
 */
function ventajaLocates(precio: number | null, costeAccion: number, evPct: number,
                        acciones?: number | null) {
  if (!precio || precio <= 0 || !costeAccion || !evPct) return null;
  // `costeAccion` es el precio del locate POR ACCIÓN — el que enseña el bróker,
  // que es lo que tienes delante al decidir. (El campo del backtester pide el
  // del PAQUETE de 100 porque allí el dato se rellena una vez: un locate de 1 $
  // el paquete son 0,01 $ la acción.)
  let costeReal = costeAccion;
  if (acciones && acciones > 0) {
    const paquetes = Math.ceil(acciones / 100);
    costeReal = (paquetes * 100 * costeAccion) / acciones;
  }
  const fade = (costeReal / precio) * 100;
  return { fade, ev: evPct, margen: evPct - fade, compensa: evPct > fade };
}


/** Campo numérico de la tabla de configuración. Un solo sitio para el estilo,
 *  que si no cada columna acaba con su propio borde y su propio ancho.
 *  `aviso` lo pinta en ámbar: el dato hace falta y está vacío. */
function CampoNum({ valor, onChange, onBlur, paso = 50, aviso = false, titulo }: {
  valor: string;
  onChange: (v: string) => void;
  onBlur: () => void;
  paso?: number;
  aviso?: boolean;
  titulo?: string;
}) {
  return (
    <input
      type="number" min={1} step={paso} value={valor} title={titulo}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      style={{
        width: 84, textAlign: "right", background: color.bgElevated,
        border: `0.5px solid ${aviso ? color.warning : color.border}`,
        borderRadius: 2, color: color.textPrimary,
        fontFamily: font.mono, fontSize: 11.5, padding: "2px 6px",
      }}
    />
  );
}

/** Lo que el motor VA A HACER con la estrategia, no lo que dice su JSON.
 *
 *  Nace del 2026-09-03: la 1B llevaba guardados dos take profit parciales que
 *  el motor ignoraba (`take_profit_mode: "Full"`) y que se habrían encendido
 *  cambiando OTRO campo, sin ningún aviso. El guardado es fiel —auditado con un
 *  round-trip, 370 campos y 0 pérdidas—; lo que faltaba era poder VER qué parte
 *  está viva. Por eso el bloque de abajo, el de lo inactivo, es el importante.
 */
function Detalle({ e, onLimpiar }: {
  e?: ExplicacionEstrategia;
  onLimpiar?: () => void;
}) {
  if (!e) return <span style={{ color: color.textMuted, fontSize: 11 }}>Leyendo…</span>;

  const Bloque = ({ titulo, children }: { titulo: string; children: React.ReactNode }) => (
    <div style={{ minWidth: 210 }}>
      <div style={{
        fontSize: 9, fontWeight: 700, letterSpacing: "0.06em",
        textTransform: "uppercase", color: color.textMuted, marginBottom: 4,
      }}>{titulo}</div>
      <div style={{ fontSize: 11, color: color.textSecondary, lineHeight: 1.55 }}>
        {children}
      </div>
    </div>
  );
  const Lista = ({ xs }: { xs: string[] }) =>
    xs.length === 0 ? <span style={{ color: color.textMuted }}>—</span> : (
      <>{xs.map((x, i) => <div key={i} style={{ fontFamily: font.mono, fontSize: 10.5 }}>{x}</div>)}</>
    );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 26 }}>
        <Bloque titulo="Entradas">
          <div style={{ color: color.textHigh, fontFamily: font.mono, fontSize: 10.5 }}>
            {e.entradas.ventanas.length ? e.entradas.ventanas.join(", ")
              : `sesión ${e.sesion.desde || "—"}→${e.sesion.hasta || "—"}`}
          </div>
          <Lista xs={e.entradas.condiciones} />
        </Bloque>

        <Bloque titulo="Salidas">
          <Lista xs={e.salidas} />
          <div style={{ marginTop: 3, color: color.textMuted }}>
            reentradas: {e.reentradas}
          </div>
        </Bloque>

        <Bloque titulo="Tamaño">
          <div style={{ color: color.textHigh }}>{e.dimensionado.modo}</div>
          {e.piramidacion.map((p, i) => (
            <div key={i} style={{ marginTop: 4 }}>
              <div style={{ fontFamily: font.mono, fontSize: 10.5 }}>
                {p.accion === "add" ? "añade" : "reduce"} {p.cantidad}
              </div>
              <Lista xs={p.condiciones} />
            </div>
          ))}
        </Bloque>

        <Bloque titulo="Universo">
          <Lista xs={e.universo} />
          {e.no_vigilable_en_vivo.length > 0 && (
            <div style={{ color: color.warning, marginTop: 4 }}>
              el bot NO sabe vigilar en vivo: {e.no_vigilable_en_vivo.join(", ")}
            </div>
          )}
        </Bloque>
      </div>

      {e.inactivo.length > 0 && (
        <div style={{
          borderTop: `0.5px dotted ${color.border}`, paddingTop: 8,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 10, marginBottom: 4,
          }}>
            <span style={{
              fontSize: 9, fontWeight: 700, letterSpacing: "0.06em",
              textTransform: "uppercase", color: color.warning,
            }}>
              Guardado pero SIN aplicar ({e.inactivo.length})
            </span>
            {onLimpiar && (
              <button
                onClick={onLimpiar}
                title="Borra lo que puede encenderse solo al cambiar otro campo. NO cambia el comportamiento: se quita lo que el motor ya ignoraba, así que los backtests dan lo mismo. Lo que tiene su propio interruptor (trailing, swing) se queda."
                style={{
                  fontSize: 9, padding: "1px 7px", cursor: "pointer",
                  background: "transparent",
                  border: `0.5px solid ${color.border}`, borderRadius: 2,
                  fontFamily: font.mono, color: color.textMuted,
                }}
              >LIMPIAR</button>
            )}
          </div>
          {e.inactivo.map((x, i) => (
            <div key={i} style={{ fontSize: 11, marginBottom: 3 }}>
              <span style={{ color: color.textSecondary }}>{x.que}: </span>
              <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.textMuted }}>
                {x.valor}
              </span>
              <div style={{ color: color.textMuted, fontSize: 10, marginLeft: 10 }}>
                ↳ {x.por_que}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Componente ───────────────────────────────────────────────────────── */

export default function CuadroMandos() {
  const [estado, setEstado] = useState<EstadoBot | null>(null);
  const [estrategias, setEstrategias] = useState<EstrategiaCandidata[]>([]);
  const [eventos, setEventos] = useState<EventoAlerta[]>([]);
  const [fechas, setFechas] = useState<string[]>([]);
  const [fecha, setFecha] = useState<string>("");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sonido, setSonido] = useState(true);
  const [riesgos, setRiesgos] = useState<Record<string, string>>({});
  /** Riesgo del ANYADIDO y capital de la cuenta, por estrategia. Vacio = no
   *  dicho: el anyadido cae a lo que diga la estrategia, y sin capital el
   *  backend no deja activar una estrategia con stop hibrido. */
  const [riesgosPir, setRiesgosPir] = useState<Record<string, string>>({});
  const [capitales, setCapitales] = useState<Record<string, string>>({});
  /** EV de cada estrategia, en % del precio de entrada. Lo tecleas tú: el bot
   *  no puede saber qué backtest consideras válido. Lo usa el cálculo de
   *  locates del radar y el comando /evf de Telegram. */
  const [evs, setEvs] = useState<Record<string, string>>({});
  /** Fila desplegada y su explicacion. Se pide al abrir, no al cargar la
   *  pagina: son datos que solo se miran cuando se duda de algo. */
  const [abierta, setAbierta] = useState<string | null>(null);
  /** Coste del locate y EV por ticker, tecleados en el radar. Persisten en el
   *  navegador: se escriben una vez y valen para toda la sesión. */
  const [locates, setLocates] = useState<Record<string, { coste: string; ev: string }>>({});
  /** Precio congelado por ticker: al pulsar OK el veredicto deja de moverse.
   *  Jaume lo pidió así — «hasta que le diéramos a OK para que detuviera el
   *  registro» — porque una vez decides, un número que sigue bailando estorba. */
  const [congelados, setCongelados] = useState<Record<string, number>>({});
  const [explicacion, setExplicacion] = useState<Record<string, ExplicacionEstrategia>>({});

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LOCATES_KEY);
      if (raw) setLocates(JSON.parse(raw));
    } catch { /* navegador sin storage: se teclea y ya */ }
  }, []);

  const ponLocate = useCallback((ticker: string, campo: "coste" | "ev", valor: string) => {
    setLocates((p) => {
      const actual = p[ticker] || { coste: "", ev: "" };
      const sig = { ...p, [ticker]: { ...actual, [campo]: valor } };
      try { localStorage.setItem(LOCATES_KEY, JSON.stringify(sig)); } catch { /* da igual */ }
      return sig;
    });
  }, []);

  const limpiarConfigMuerta = useCallback(async (id: string, nombre: string) => {
    // Confirmación explícita: modifica la estrategia GUARDADA. No cambia cómo
    // opera —se quita lo que el motor ya ignoraba— pero es un cambio en disco
    // y conviene que sea una decisión, no un clic despistado.
    const aviso = [
      `Se borrará de «${nombre}» la configuración que el motor no aplica.`,
      "",
      "NO cambia cómo opera ni los resultados de los backtests: se quita",
      "exactamente lo que ya se ignoraba. Lo que tiene su propio interruptor",
      "(trailing, swing) se queda.",
      "",
      "¿Seguir?",
    ].join("\n");
    if (!window.confirm(aviso)) return;
    try {
      const r = await limpiarInactivo(id);
      const e = await explicarEstrategia(id);
      setExplicacion((p) => ({ ...p, [id]: e }));
      setError(r.quitado.length
        ? `Limpiado de «${nombre}»: ${r.quitado.join(", ")}.`
        : `«${nombre}» no tenía nada que limpiar.`);
    } catch (err) {
      setError((err as Error)?.message || "No se pudo limpiar");
    }
  }, []);

  const alternarDetalle = useCallback(async (id: string) => {
    if (abierta === id) { setAbierta(null); return; }
    setAbierta(id);
    if (explicacion[id]) return;
    try {
      const e = await explicarEstrategia(id);
      setExplicacion((p) => ({ ...p, [id]: e }));
    } catch (err) {
      setError((err as Error)?.message || "No se pudo leer la configuración");
    }
  }, [abierta, explicacion]);
  /** Ids iluminados ahora mismo. Solo entradas y piramides: son las que hay que
   *  ejecutar. Una salida tambien avisa, pero no compite por tu atencion. */
  const [destacados, setDestacados] = useState<Record<string, number>>({});
  /** A quién está mirando el bot ahora mismo. Llega por el WebSocket. */
  const [radar, setRadar] = useState<Radar | null>(null);

  const vistosRef = useRef<Set<string>>(new Set());
  const audioRef = useRef<AudioContext | null>(null);
  // El sonido se lee de una ref, no del estado: si el efecto del WebSocket
  // dependiera del estado, silenciar reabriría la conexión por un simple clic.
  const sonidoRef = useRef(true);
  useEffect(() => { sonidoRef.current = sonido; }, [sonido]);

  useEffect(() => {
    try {
      const v = localStorage.getItem(SONIDO_KEY);
      if (v != null) setSonido(v === "1");
    } catch { /* modo privado: se queda con el valor por defecto */ }
  }, []);

  const alternarSonido = useCallback(() => {
    setSonido((s) => {
      const n = !s;
      try { localStorage.setItem(SONIDO_KEY, n ? "1" : "0"); } catch { /* noop */ }
      // El navegador no deja crear audio sin un gesto del usuario: este clic
      // es el gesto, asi que se aprovecha para dejar el contexto listo.
      if (n && !audioRef.current) {
        try {
          const Ctx = window.AudioContext
            || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
          audioRef.current = new Ctx();
        } catch { /* sin audio disponible */ }
      }
      return n;
    });
  }, []);

  const pitar = useCallback(() => {
    const ctx = audioRef.current;
    if (!ctx) return;
    try {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.36);
    } catch { /* noop */ }
  }, []);

  /* ── Carga inicial ──────────────────────────────────────────────────── */
  useEffect(() => {
    let vivo = true;
    Promise.all([leerEstado(), listarEstrategias(), listarFechas()])
      .then(([e, s, f]) => {
        if (!vivo) return;
        setEstado(e);
        setEstrategias(s);
        setFechas(f.fechas);
        setRiesgos(Object.fromEntries(
          s.map((x) => [x.strategy_id, x.riesgo_usd != null ? String(x.riesgo_usd) : ""]),
        ));
        setRiesgosPir(Object.fromEntries(
          s.map((x) => [x.strategy_id, x.riesgo_piramide_usd != null ? String(x.riesgo_piramide_usd) : ""]),
        ));
        setCapitales(Object.fromEntries(
          s.map((x) => [x.strategy_id, x.capital_usd != null ? String(x.capital_usd) : ""]),
        ));
        setEvs(Object.fromEntries(
          s.map((x) => [x.strategy_id, x.ev_pct != null ? String(x.ev_pct) : ""]),
        ));
      })
      .catch((e) => vivo && setError(e?.message || "No se pudo cargar el cuadro de mandos"))
      .finally(() => vivo && setCargando(false));
    return () => { vivo = false; };
  }, []);

  /* ── Novedades: el servidor EMPUJA, la página no pregunta ───────────
   *
   * Antes se consultaba cada 2 s y un aviso tardaba hasta 2 s en aparecer:
   * Telegram, que es un empujón directo, llegaba antes. En una prealerta el
   * margen útil son segundos, así que esa espera importaba.
   *
   * Se mantiene la vía de consulta como respaldo por si el WebSocket no
   * conecta (proxy, extensión del navegador): mejor lento que en blanco.
   */
  const aplicar = useCallback((e: EstadoBot, eventos: EventoAlerta[], r?: Radar | null) => {
    setEstado(e);
    if (r) setRadar(r);
    // Solo suena y se ilumina lo que no se había visto. En la primera carga se
    // marcan todos como vistos: si no, al abrir la página sonarían de golpe
    // todos los avisos del día.
    //
    // LA CLAVE LLEVA EL ESTADO. Al confirmarse, una prealerta conserva su id;
    // con la clave sin estado se daría por vista y la confirmación —el momento
    // que de verdad importa— pasaría sin destello ni sonido.
    const clave = (x: EventoAlerta) => `${x.id}|${x.estado}`;
    const primeraVez = vistosRef.current.size === 0;
    const nuevos = eventos.filter((x) => !vistosRef.current.has(clave(x)));
    eventos.forEach((x) => vistosRef.current.add(clave(x)));
    if (!primeraVez && nuevos.length) {
      // Ni las salidas ni las prealertas caídas piden atención: una salida
      // ya avisó por Telegram y una caída no tiene nada que ejecutar.
      const aEjecutar = nuevos.filter(
        (x) => x.tipo !== "salida" && x.estado !== "descartada");
      if (aEjecutar.length) {
        const ahora = Date.now();
        setDestacados((prev) => ({
          ...prev, ...Object.fromEntries(aEjecutar.map((x) => [clave(x), ahora])),
        }));
      }
      const suena = nuevos.some((x) => x.estado !== "descartada");
      if (sonidoRef.current && suena) {
        pitar();
        document.title = `(${nuevos.length}) Alertas · BTT`;
        setTimeout(() => { document.title = "Alertas · BTT"; }, 8000);
      }
    }
    setEventos(eventos);
  }, [pitar]);

  useEffect(() => {
    // El histórico de otro día no llega por WebSocket (que emite lo último):
    // ahí se pide una vez y ya está, porque no cambia.
    if (fecha) {
      let vivo = true;
      listarEventos(fecha).then((r) => { if (vivo) setEventos(r.eventos); }).catch(() => {});
      return () => { vivo = false; };
    }

    let parado = false;
    let reconectar: ReturnType<typeof setTimeout> | null = null;
    let respaldo: ReturnType<typeof setInterval> | null = null;
    let ws: WebSocket | null = null;

    const conectar = () => {
      if (parado) return;
      try {
        ws = new WebSocket(`${API_BASE.replace(/^http/, "ws")}/bot-alerts/live`);
      } catch {
        reconectar = setTimeout(conectar, 2000);
        return;
      }
      ws.onopen = () => {
        if (respaldo) { clearInterval(respaldo); respaldo = null; }
      };
      ws.onmessage = (m) => {
        try {
          const d = JSON.parse(m.data);
          if (d?.estado) aplicar(d.estado, Array.isArray(d.eventos) ? d.eventos : [], d.radar);
        } catch { /* trama malformada: se ignora */ }
      };
      ws.onclose = () => {
        if (parado) return;
        // Mientras esté caído, se vuelve a preguntar: lento, pero no en blanco.
        if (!respaldo) respaldo = setInterval(tick, REFRESCO_MS);
        reconectar = setTimeout(conectar, 2000);
      };
      ws.onerror = () => { try { ws?.close(); } catch { /* noop */ } };
    };

    const tick = async () => {
      try {
        const [e, ev] = await Promise.all([leerEstado(), listarEventos()]);
        if (!parado) aplicar(e, ev.eventos);
      } catch { /* un fallo suelto no rompe la página */ }
    };

    tick();          // primer pintado inmediato
    conectar();
    return () => {
      parado = true;
      if (reconectar) clearTimeout(reconectar);
      if (respaldo) clearInterval(respaldo);
      try { ws?.close(); } catch { /* noop */ }
    };
  }, [fecha, aplicar]);

  /* ── Apagar la iluminacion pasado su tiempo ─────────────────────────── */
  useEffect(() => {
    if (Object.keys(destacados).length === 0) return;
    const id = setInterval(() => {
      const corte = Date.now() - DESTACADO_MS;
      setDestacados((prev) => {
        const vivos = Object.entries(prev).filter(([, t]) => t > corte);
        return vivos.length === Object.keys(prev).length
          ? prev                              // nada que purgar: no re-renderiza
          : Object.fromEntries(vivos);
      });
    }, 1000);
    return () => clearInterval(id);
  }, [destacados]);

  /* ── Acciones ───────────────────────────────────────────────────────── */
  const alternarBot = async () => {
    if (!estado) return;
    try {
      const e = await cambiarEstado(!estado.vigilando);
      setEstado({ ...estado, ...e });
    } catch (err) {
      setError((err as Error)?.message || "No se pudo cambiar el estado del bot");
    }
  };

  const guardarEstrategia = async (s: EstrategiaCandidata, activa: boolean) => {
    const riesgo = Number(riesgos[s.strategy_id]);
    // Apagar nunca se bloquea: un frenazo no puede depender de tener los
    // campos bien puestos.
    if (activa && (!riesgo || riesgo <= 0)) {
      setError(`Faltan datos por rellenar en «${s.name}»: el riesgo por operación.`);
      return;
    }
    const riesgoPir = Number(riesgosPir[s.strategy_id]) || null;
    const capital = Number(capitales[s.strategy_id]) || null;
    const ev = Number(evs[s.strategy_id]) || null;
    try {
      // La comprobacion de verdad la hace el backend contra la definicion
      // GUARDADA, que es la que va a usar el bot. Aqui solo se pilla lo obvio.
      await guardarVigilancia(s.strategy_id, activa, riesgo, {
        riesgo_piramide_usd: riesgoPir, capital_usd: capital, ev_pct: ev,
      });
      setEstrategias((prev) => prev.map((x) =>
        x.strategy_id === s.strategy_id
          ? { ...x, activa, riesgo_usd: riesgo, riesgo_piramide_usd: riesgoPir,
              capital_usd: capital, ev_pct: ev }
          : x));
      setError(null);
    } catch (err) {
      setError((err as Error)?.message || "No se pudo guardar");
    }
  };

  const limpiar = async () => {
    const antes = prompt("Borrar avisos anteriores a (AAAA-MM-DD).\nSe borran de la base de datos, no solo de la vista:");
    if (!antes) return;
    try {
      const r = await limpiarEventos(antes);
      alert(`Borrados ${r.borrados} avisos.`);
      const [ev, f] = await Promise.all([listarEventos(fecha || undefined), listarFechas()]);
      setEventos(ev.eventos); setFechas(f.fechas);
    } catch (err) {
      setError((err as Error)?.message || "No se pudo limpiar");
    }
  };

  /* ── Derivados ──────────────────────────────────────────────────────── */
  const porEstrategia = useMemo(
    () => Object.fromEntries(estrategias.map((s) => [s.strategy_id, s])),
    [estrategias],
  );

  const cuboDe = useCallback(
    (e: EventoAlerta) => e.origen || porEstrategia[e.strategy_id]?.origen || "portfolio",
    [porEstrategia],
  );

  const dePortfolio = useMemo(
    () => eventos.filter((e) => cuboDe(e) !== "incubadora"), [eventos, cuboDe]);
  const deIncubadora = useMemo(
    () => eventos.filter((e) => cuboDe(e) === "incubadora"), [eventos, cuboDe]);

  const vivo = useMemo(() => {
    if (!estado?.latido_at) return false;
    const t = Date.parse(estado.latido_at.replace(" ", "T"));
    return Number.isFinite(t) && Date.now() - t < LATIDO_VIVO_MS;
  }, [estado]);

  if (cargando) return <Loading />;

  const activas = estrategias.filter((s) => s.activa).length;

  /* ── Rejilla de avisos, reutilizada por los dos cuadros ─────────────── */
  const TablaAvisos = ({ filas, vacio }: { filas: EventoAlerta[]; vacio: string }) => (
    <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1080 }}>
      <thead>
        <tr>
          <Th ancho={56}>Hora</Th>
          <Th ancho={86}>Estado</Th>
          <Th ancho={82}>Tipo</Th>
          <Th ancho={70}>Ticker</Th>
          <Th ancho={62}>Lado</Th>
          <Th num ancho={94}>Precio</Th>
          <Th num ancho={104}>Stop</Th>
          <Th num ancho={88}>Distancia</Th>
          <Th num ancho={110}>Acciones</Th>
          <Th num ancho={84}>Riesgo €</Th>
          <Th>Detalle</Th>
          <Th>Estrategia</Th>
        </tr>
      </thead>
      <tbody>
        {filas.length === 0 && (
          <tr><Td dim>{vacio}</Td></tr>
        )}
        {filas.map((e) => {
          const s = porEstrategia[e.strategy_id];
          const esSalida = e.tipo === "salida";
          const dist = e.precio != null && e.stop != null ? Math.abs(e.precio - e.stop) : null;
          // Acciones al precio de AHORA. Mientras no haya precio en vivo, el
          // ultimo conocido es el del aviso.
          const acc = esSalida ? null : accionesAlPrecio(
            e.riesgo_usd ?? s?.riesgo_usd ?? null, e.precio, e.stop, s?.size_by_sl ?? false,
          );
          const tonoTipo = e.tipo === "entrada" ? color.copper
            : e.tipo === "piramide" ? color.info : color.textMuted;
          const encendida = destacados[`${e.id}|${e.estado}`] != null;
          const espera = e.estado === "prealerta";
          // Una prealerta que no se confirmo. Se queda en la tabla, apagada:
          // borrarla escondería que hubo un aviso, y saber que se cayó también
          // es información. No suena ni destella.
          const caida = e.estado === "descartada";
          // Al llegar, la fila se enciende y se va apagando sola: ámbar si es
          // prealerta, rojo si es la alerta confirmada.
          //
          // La `key` incluye el estado A PROPÓSITO: al pasar de prealerta a
          // alerta, React remonta la fila y el navegador vuelve a lanzar la
          // animación — ahora en rojo. Con la key fija cambiaría el color pero
          // no habría destello, y el momento importante (la confirmación) se
          // vería menos que la prealerta que lo precedió.
          // Una prealerta caída NO destella: no hay nada que ejecutar, y un
          // destello es una llamada de atención.
          const anim = encendida && !caida
            ? {
                animation: `bot-flash-${espera ? "prealerta" : "alerta"} `
                  + `${DESTACADO_MS}ms ease-out forwards`,
              }
            : {};
          return (
            <tr key={`${e.id}|${e.estado}`}
                className={espera ? "bot-fila-prealerta" : "bot-fila-alerta"}
                style={anim}>
              <Td mono dim>{hora(e.momento)}</Td>
              <Td tono={espera ? color.warning : caida ? color.textMuted : color.textSecondary}>
                {espera ? "Prealerta" : caida ? "No confirmada" : "Alerta"}
              </Td>
              <Td tono={tonoTipo}>
                {e.tipo === "piramide"
                  ? (e.accion_piramide === "reduce" ? "Reducir" : "Añadir")
                  : e.tipo === "entrada" ? "Entrada" : "Salida"}
                {e.modo === "reproduccion" && (
                  <span style={{ color: color.textMuted, fontSize: 9 }}> ·rep</span>
                )}
              </Td>
              <Td tono={color.textHigh} mono>{e.ticker}</Td>
              <Td tono={e.direccion === "Short" ? color.loss : color.profit}>
                {e.direccion === "Short" ? "Corto" : e.direccion === "Long" ? "Largo" : "—"}
              </Td>
              {/* Precio, stop y acciones son lo que se teclea en el broker: los
                  tres en negrita y en blanco. El cobre se perdia contra el
                  fondo oscuro y ademas competia con el resalte de la fila. */}
              <Td num fuerte tono={color.textHigh}>{fmt(e.precio, 4)}</Td>
              <Td num dim={esSalida} fuerte={!esSalida}
                  tono={esSalida ? undefined : color.textHigh}>
                {esSalida ? "—" : fmt(e.stop, 4)}
              </Td>
              <Td num dim>{esSalida ? "—" : fmt(dist, 4)}</Td>
              <Td num fuerte={!esSalida} tono={esSalida ? undefined : color.textHigh}>
                {e.tipo === "piramide" ? fmt(e.acciones, 0) : acc != null ? fmt(acc, 0) : "—"}
              </Td>
              <Td num dim>{esSalida ? "—" : fmt(e.riesgo_usd ?? s?.riesgo_usd ?? null, 0)}</Td>
              <Td dim>
                {e.tipo === "salida" ? `Motivo: ${e.motivo || "?"}`
                  : e.tipo === "piramide" ? `Posición total: ${fmt(e.posicion_total, 0)}`
                  : ""}
              </Td>
              <Td dim>{e.estrategia || "—"}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );

  return (
    <div style={{ padding: "20px 26px 60px", maxWidth: 1680, margin: "0 auto" }}>
      <style dangerouslySetInnerHTML={{ __html: ANIMACIONES }} />
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <Radio style={{ width: 19, height: 19, color: color.copper, strokeWidth: 1.5 }} />
        <h1 style={{
          fontSize: 24, fontFamily: font.serif, color: color.textHigh,
          margin: 0, fontWeight: 400,
        }}>Cuadro de mandos</h1>
      </div>

      {error && <div style={{ marginBottom: 12 }}><ErrorBox>{error}</ErrorBox></div>}

      {/* ── Barra de estado ─────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "center", flexWrap: "wrap", gap: "10px 22px",
        background: color.bgSurface, border: hairline, borderRadius: 3,
        padding: "10px 14px", fontFamily: font.mono, fontSize: 11,
      }}>
        <button
          onClick={alternarBot}
          style={{
            fontFamily: font.sans, fontSize: 10.5, fontWeight: 600,
            letterSpacing: "0.08em", textTransform: "uppercase",
            padding: "5px 14px", borderRadius: 3, cursor: "pointer",
            border: `0.5px solid ${estado?.vigilando ? color.profit : color.border}`,
            background: estado?.vigilando ? "rgba(74,157,127,0.12)" : "transparent",
            color: estado?.vigilando ? color.profit : color.textSecondary,
          }}
        >{estado?.vigilando ? "Vigilando" : "Parado"}</button>

        <Dato etiqueta="Proceso" valor={
          !estado?.vigilando ? "—"
            : vivo ? `vivo · ${estado?.fuente || "?"}`
            : "SIN RESPUESTA"
        } tono={!estado?.vigilando ? color.textMuted : vivo ? color.profit : color.loss} />

        <Dato etiqueta="Tickers" valor={String(estado?.tickers_seguidos ?? 0)} />
        <Dato etiqueta="Estrategias" valor={`${activas} de ${estrategias.length}`} />
        <Dato
          etiqueta="Telegram"
          valor={estado?.telegram?.enviando ? "enviando" : (estado?.telegram?.detalle || "apagado")}
          tono={estado?.telegram?.enviando ? color.profit : color.textMuted}
        />

        <button
          onClick={alternarSonido}
          title={sonido ? "Silenciar" : "Activar sonido"}
          style={{
            marginLeft: "auto", display: "flex", alignItems: "center", gap: 6,
            background: "transparent", border: `0.5px solid ${color.border}`,
            borderRadius: 3, padding: "4px 10px", cursor: "pointer",
            color: sonido ? color.copper : color.textMuted,
            fontFamily: font.sans, fontSize: 10.5,
          }}
        >
          {sonido ? <Bell style={{ width: 13, height: 13, strokeWidth: 1.5 }} />
                  : <BellOff style={{ width: 13, height: 13, strokeWidth: 1.5 }} />}
          {sonido ? "Sonido" : "Silencio"}
        </button>
      </div>

      {/* ── Estrategias ─────────────────────────────────────────────── */}
      <Seccion titulo="Estrategias vigiladas">
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 880 }}>
          <thead>
            <tr>
              <Th ancho={72} />
              <Th>Estrategia</Th>
              <Th ancho={96}>Origen</Th>
              <Th ancho={64}>Sesgo</Th>
              <Th num ancho={100}>Riesgo €</Th>
              <Th num ancho={100}>Riesgo pir. €</Th>
              <Th num ancho={100}>Capital €</Th>
              <Th num ancho={78}>EV %</Th>
              <Th>El riesgo es</Th>
              <Th ancho={150}>Ventana entradas</Th>
              <Th num ancho={90}>Avisos hoy</Th>
            </tr>
          </thead>
          <tbody>
            {estrategias.length === 0 && (
              <tr><Td dim>
                No hay estrategias en el portfolio ni en la incubadora.
                Añade alguna desde la página de Portfolio.
              </Td></tr>
            )}
            {estrategias.map((s) => {
              const n = eventos.filter((e) => e.strategy_id === s.strategy_id).length;
              const esIncubadora = s.origen === "incubadora";
              const fila = (
                <tr key={s.strategy_id}>
                  <Td>
                    {/* BOTON, no un check (Jaume, 2026-09-03). Un check parece
                        que ya esta hecho en cuanto lo marcas; el boton deja que
                        el backend valide primero y diga que falta. */}
                    <button
                      onClick={() => guardarEstrategia(s, !s.activa)}
                      style={{
                        width: 62, padding: "3px 0", cursor: "pointer",
                        background: s.activa ? color.copper : color.bgElevated,
                        border: `0.5px solid ${s.activa ? color.copper : color.border}`,
                        borderRadius: 2, fontFamily: font.mono, fontSize: 10.5,
                        color: s.activa ? "#fff" : color.textSecondary,
                        letterSpacing: 0.3,
                      }}
                      title={s.activa
                        ? "Vigilando. Pulsa para parar."
                        : "Pulsa para activar. Si faltan datos, te lo dirá."}
                    >
                      {s.activa ? "ACTIVA" : "Activar"}
                    </button>
                  </Td>
                  <Td tono={s.activa ? color.textHigh : color.textMuted}>
                    {/* Desplegable de condiciones: enseña lo que el motor VA A
                        HACER, no lo que dice el JSON. Nace del susto del
                        2026-09-03 con los take profit parciales muertos. */}
                    <span
                      onClick={() => alternarDetalle(s.strategy_id)}
                      style={{ cursor: "pointer", userSelect: "none" }}
                      title="Ver las condiciones que el motor aplica de verdad"
                    >
                      <span style={{ color: color.textMuted, marginRight: 5, fontSize: 9 }}>
                        {abierta === s.strategy_id ? "▾" : "▸"}
                      </span>
                      {s.name}
                    </span>
                  </Td>
                  <Td tono={esIncubadora ? color.warning : color.textSecondary}>
                    {esIncubadora ? "Incubadora" : "Portfolio"}
                  </Td>
                  <Td tono={s.bias === "short" ? color.loss : color.profit}>
                    {s.bias === "short" ? "Corto" : s.bias === "long" ? "Largo" : "—"}
                  </Td>
                  <Td num>
                    <CampoNum
                      valor={riesgos[s.strategy_id] ?? ""}
                      onChange={(v) => setRiesgos((p) => ({ ...p, [s.strategy_id]: v }))}
                      onBlur={() => s.activa && guardarEstrategia(s, true)}
                      titulo="Riesgo por operación de la entrada."
                    />
                  </Td>
                  <Td num>
                    {/* Solo si la estrategia piramida. Vacio = usa lo que diga
                        su definicion, que es lo que pasaba hasta hoy. */}
                    {s.piramida ? (
                      <CampoNum
                        valor={riesgosPir[s.strategy_id] ?? ""}
                        onChange={(v) => setRiesgosPir((p) => ({ ...p, [s.strategy_id]: v }))}
                        onBlur={() => s.activa && guardarEstrategia(s, true)}
                        titulo="Riesgo del añadido. Vacío = el que diga la estrategia."
                      />
                    ) : <span style={{ color: color.textMuted }}>—</span>}
                  </Td>
                  <Td num>
                    {/* Solo con stop hibrido: sin capital no se puede calcular
                        el techo, y el backend no deja activar. */}
                    {s.hybrid_stop ? (
                      <CampoNum
                        valor={capitales[s.strategy_id] ?? ""}
                        onChange={(v) => setCapitales((p) => ({ ...p, [s.strategy_id]: v }))}
                        onBlur={() => s.activa && guardarEstrategia(s, true)}
                        paso={1000}
                        aviso={!capitales[s.strategy_id]}
                        titulo="Tu cuenta entera. El stop híbrido la necesita para el techo."
                      />
                    ) : <span style={{ color: color.textMuted }}>—</span>}
                  </Td>
                  <Td num>
                    {/* La esperanza de la estrategia, en % del precio de
                        entrada. La usa el cálculo de locates del radar y el
                        comando /evf de Telegram, para no repetirla en cada
                        mensaje. La tecleas tú: el bot no puede saber qué
                        backtest consideras válido. */}
                    <CampoNum
                      valor={evs[s.strategy_id] ?? ""}
                      onChange={(v) => setEvs((p) => ({ ...p, [s.strategy_id]: v }))}
                      onBlur={() => s.activa && guardarEstrategia(s, true)}
                      paso={0.1}
                      titulo="Esperanza matemática de la estrategia, en % del precio de entrada. Se usa para decidir si compensan los locates."
                    />
                  </Td>
                  <Td dim title={s.hybrid_stop
                    ? "Híbrido: por distancia al stop, pero sin exponer más de lo que aceptas perder ante un evento de cola."
                    : s.size_by_sl
                    ? "Se divide entre la distancia al stop: es la pérdida máxima si salta."
                    : "Se divide entre el precio: es el capital que se despliega."}>
                    {s.hybrid_stop
                      ? <span style={{ color: color.copper }}>híbrido (SL con techo)</span>
                      : s.size_by_sl ? "pérdida máxima" : "capital a desplegar"}
                  </Td>
                  <Td dim mono title={`Sesión: ${s.ventana?.inicio || "?"} → ${s.ventana?.fin || "?"}`}>
                    {/* La de ENTRADAS, no la de sesión. Son capas distintas y
                        confundirlas hacía creer que se podía entrar una hora
                        más tarde de lo que la estrategia permite. */}
                    {s.ventana_entradas && s.ventana_entradas.length > 0
                      ? s.ventana_entradas.map((w) => `${w.inicio}→${w.fin}`).join(", ")
                      : <span style={{ color: color.textMuted }}>
                          sesión {s.ventana?.inicio || "—"}→{s.ventana?.fin || "—"}
                        </span>}
                  </Td>
                  <Td num dim>{n || "—"}</Td>
                </tr>
              );
              const detalle = abierta === s.strategy_id ? (
                <tr key={`${s.strategy_id}-detalle`}>
                  <td colSpan={11} style={{
                    padding: "10px 14px 14px 26px",
                    background: color.bgElevated,
                    borderBottom: `0.5px solid ${color.border}`,
                  }}>
                    <Detalle
                      e={explicacion[s.strategy_id]}
                      onLimpiar={() => limpiarConfigMuerta(s.strategy_id, s.name)}
                    />
                  </td>
                </tr>
              ) : null;
              return detalle
                ? <React.Fragment key={s.strategy_id}>{fila}{detalle}</React.Fragment>
                : fila;
            })}
          </tbody>
        </table>
      </Seccion>

      {/* ── Avisos de portfolio ─────────────────────────────────────── */}
      <Seccion
        titulo="Avisos · portfolio"
        alto={ALTO_PORTFOLIO}
        extra={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <select
              value={fecha}
              onChange={(e) => { setFecha(e.target.value); vistosRef.current.clear(); }}
              style={{
                background: color.bgElevated, border: `0.5px solid ${color.border}`,
                borderRadius: 2, color: color.textSecondary, fontFamily: font.mono,
                fontSize: 11, padding: "3px 8px",
              }}
            >
              <option value="">Últimos</option>
              {fechas.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <button
              onClick={limpiar} title="Borrar avisos antiguos de la base de datos"
              style={{
                display: "flex", alignItems: "center", gap: 5, background: "transparent",
                border: `0.5px solid ${color.border}`, borderRadius: 2, padding: "3px 9px",
                cursor: "pointer", color: color.textMuted, fontFamily: font.sans, fontSize: 10.5,
              }}
            >
              <Trash2 style={{ width: 12, height: 12, strokeWidth: 1.5 }} /> Limpiar
            </button>
          </div>
        }
      >
        <TablaAvisos
          filas={dePortfolio}
          vacio={`Sin avisos${fecha ? ` el ${fecha}` : " todavía"}.${
            !estado?.vigilando ? " El bot está parado." : ""}`}
        />
      </Seccion>

      {/* ── Avisos de incubadora ────────────────────────────────────── */}
      <Seccion titulo="Avisos · incubadora" alto={ALTO_INCUBADORA}>
        <TablaAvisos
          filas={deIncubadora}
          vacio="Sin avisos de estrategias en validación."
        />
      </Seccion>

      {/* ── Radar ───────────────────────────────────────────────────── */}
      <Seccion
        titulo="Radar"
        alto={ALTO_RADAR}
        extra={radar?.actualizado ? (
          <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.textMuted }}>
            {radar.actualizado.slice(11, 19)}
          </span>
        ) : undefined}
      >
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 700 }}>
          <thead>
            <tr>
              <Th ancho={90}>Estado</Th>
              <Th ancho={80}>Ticker</Th>
              <Th>Estrategia</Th>
              <Th ancho={140}>Cumple</Th>
              <Th num ancho={96}>Valor</Th>
              <Th num ancho={100}>Precio</Th>
              <Th num ancho={100}>Cierre ayer</Th>
              <Th num ancho={120}>Volumen</Th>
              {/* ── ¿Compensan los locates? ──────────────────────────────
                  Se teclean los dos (coste del locate y EV de la estrategia)
                  y el veredicto se recalcula con cada tick, porque el precio
                  llega por el mismo WebSocket que alimenta el radar. */}
              <Th num ancho={96}>Locate $/acc</Th>
              <Th ancho={250}>Ventaja matemática</Th>
            </tr>
          </thead>
          <tbody>
            {(!radar || radar.candidatos.length === 0) && (
              <tr><Td dim>
                {estado?.vigilando
                  ? "Ningún ticker cruza el umbral ahora mismo."
                  : "El bot está parado; el radar no está barriendo."}
              </Td></tr>
            )}
            {(radar?.candidatos || []).map((c) => (
              // Un mismo ticker puede aparecer por VARIAS estrategias, cada una
              // con su umbral, así que la clave lleva las dos.
              <tr key={`${c.ticker}|${c.estrategia}`}>
                {/* `seguido` es la distinción que importa: un ticker puede
                    cumplir el filtro y NO estar vigilándose porque el cupo está
                    lleno. Sin decirlo, parecería que el bot lo está mirando. */}
                <Td tono={c.seguido ? color.profit : color.warning}>
                  {c.seguido ? "Vigilando" : "Sin cupo"}
                </Td>
                <Td tono={color.textHigh} mono>{c.ticker}</Td>
                <Td dim>{c.estrategia || "—"}</Td>
                <Td dim>{c.metrica || "—"}</Td>
                <Td num fuerte tono={color.textHigh}>{fmt(c.valor, 1)}</Td>
                <Td num>{fmt(c.precio, 4)}</Td>
                <Td num dim>{fmt(c.prev_close, 4)}</Td>
                <Td num dim>{fmt(c.volumen, 0)}</Td>
                {(() => {
                  const cfg = locates[c.ticker] || { coste: "", ev: "" };
                  // Congelado = el precio del momento en que se pulsó OK. Una
                  // vez has decidido, un veredicto que sigue bailando estorba.
                  const px = congelados[c.ticker] ?? c.precio;
                  // EL EV SALE DE LA ESTRATEGIA que trajo este candidato, no se
                  // teclea por ticker: es una propiedad de la estrategia, y
                  // repetirla en cada fila del radar era pedir el mismo número
                  // una y otra vez. Es también el que usa /evf en Telegram.
                  const dueña = estrategias.find((e) => e.name === c.estrategia);
                  const evEstrategia = Number(evs[dueña?.strategy_id ?? ""]) || 0;
                  const v = ventajaLocates(px, Number(cfg.coste), evEstrategia);
                  const fijo = congelados[c.ticker] != null;
                  return (
                    <>
                      <Td num>
                        <CampoNum
                          valor={cfg.coste} paso={0.005}
                          onChange={(x) => ponLocate(c.ticker, "coste", x)}
                          onBlur={() => {}}
                          titulo="Precio del locate POR ACCIÓN, el que da el bróker. Si el paquete de 100 vale 1 $, pon 0,01."
                        />
                      </Td>
                      <Td>
                        {!v ? (
                          <span style={{ color: color.textMuted }}>
                            {!evEstrategia
                              ? "pon el EV en la estrategia"
                              : "pon el coste del locate"}
                          </span>
                        ) : (
                          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{
                              color: v.compensa ? color.profit : color.loss,
                              fontWeight: 700, fontSize: 10.5,
                              letterSpacing: "0.04em",
                            }}>
                              {v.compensa ? "VENTAJA POSITIVA" : "VENTAJA NEGATIVA"}
                            </span>
                            <span style={{
                              fontFamily: font.mono, fontSize: 10,
                              color: color.textMuted,
                            }}
                              /* CUATRO decimales a propósito (Jaume,
                                 2026-09-03): con dos, un margen de +0,004 pp
                                 se lee "+0,00" y no sabes de qué lado cae. En
                                 una decisión de comprar o no comprar, el signo
                                 no se puede perder en el formato. */
                              title={`Fade necesario ${v.fade.toFixed(4)}% · EV ${v.ev.toFixed(4)}%`}>
                              {v.margen >= 0 ? "+" : ""}{v.margen.toFixed(4)} pp
                            </span>
                            <button
                              onClick={() => setCongelados((p) => {
                                const s = { ...p };
                                if (fijo) delete s[c.ticker];
                                else if (c.precio) s[c.ticker] = c.precio;
                                return s;
                              })}
                              title={fijo
                                ? `Congelado a ${px?.toFixed(4)}. Pulsa para volver al precio en vivo.`
                                : "Congelar el veredicto al precio de ahora."}
                              style={{
                                fontSize: 9, padding: "1px 6px", cursor: "pointer",
                                background: fijo ? color.copper : "transparent",
                                border: `0.5px solid ${fijo ? color.copper : color.border}`,
                                borderRadius: 2, fontFamily: font.mono,
                                color: fijo ? "#fff" : color.textMuted,
                              }}
                            >{fijo ? "FIJO" : "OK"}</button>
                          </span>
                        )}
                      </Td>
                    </>
                  );
                })()}
              </tr>
            ))}
          </tbody>
        </table>
      </Seccion>

      <DiarioBot />
    </div>
  );
}

/** El diario del bot: lo que le ha saltado y su log, al final de todo.
 *
 * PARA QUE. Hasta ahora, si al bot le pasaba algo, el único sitio donde se veía
 * era la ventana de la consola o `bot_hoy.log`. Jaume, 2026-09-04: «si pasa
 * algo y no te tengo conectado cuando te encienda te lo pongo directamente».
 * De ahí el botón de copiar: esto está pensado para pegarlo en un chat.
 *
 * DOS DECISIONES QUE NO SE VEN:
 *
 * 1. PLEGADO, PERO EL CONTADOR SE VE SIEMPRE. Con el cuadro cerrado se piden
 *    solo las incidencias (`lineas=0`), no las 300 del log. Si el contador no
 *    se viera sin abrirlo, no se abriría nunca y no se enteraría uno de nada.
 *
 * 2. NO VA POR EL WEBSOCKET. El log crece con cada línea, y colgarlo del canal
 *    del estado empujaría el paquete entero —estado, 500 avisos y radar— a la
 *    página varias veces por minuto solo porque el bot escribió «latencia».
 */
function DiarioBot() {
  const [d, setD] = useState<Diario | null>(null);
  const [abierto, setAbierto] = useState(false);
  const [copiado, setCopiado] = useState<"" | "ok" | "no">("");

  useEffect(() => {
    let vivo = true;
    const pedir = async () => {
      try {
        // Plegado: solo las incidencias. Abierto: el log entero.
        const v = await leerDiario(abierto ? undefined : 0);
        if (vivo) setD(v);
      } catch {
        // El diario es informativo: si el backend no contesta, se deja lo
        // último que se vio en vez de borrar la pantalla. Justo cuando algo
        // va mal es cuando NO conviene perder lo que ya se tenía.
      }
    };
    pedir();
    const t = setInterval(pedir, abierto ? 5000 : 15000);
    return () => { vivo = false; clearInterval(t); };
  }, [abierto]);

  const copiar = useCallback(async () => {
    try {
      // El texto lo arma el backend: una sola versión del formato.
      const { texto } = await leerDiarioTexto();
      await navigator.clipboard.writeText(texto);
      setCopiado("ok");
    } catch {
      setCopiado("no");
    }
    setTimeout(() => setCopiado(""), 2000);
  }, []);

  const incidencias = d?.incidencias || [];
  const lineas = d?.lineas || [];
  // Un error pesa más que un aviso: si hay alguno, el contador va en rojo.
  const hayError = incidencias.some((i) => i.nivel !== "WARNING");

  return (
    <Seccion
      titulo="Diario del bot"
      extra={
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            fontFamily: font.mono, fontSize: 10,
            color: incidencias.length === 0 ? color.textMuted
                 : hayError ? color.loss : color.warning,
          }}>
            {d == null ? "…"
              : incidencias.length === 0 ? "sin incidencias"
              : `${incidencias.length} incidencia${incidencias.length !== 1 ? "s" : ""}`}
            {d?.desde ? ` · desde ${d.desde}` : ""}
          </span>
          <button
            onClick={copiar}
            title="Copia las incidencias y el log en texto plano, para pegarlo."
            style={botonDiario(copiado === "ok")}
          >{copiado === "ok" ? "COPIADO" : copiado === "no" ? "NO SE PUDO" : "COPIAR"}</button>
          <button
            onClick={() => setAbierto((v) => !v)}
            style={botonDiario(false)}
          >{abierto ? "OCULTAR" : "VER"}</button>
        </span>
      }
    >
      {incidencias.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <Th ancho={64}>Nivel</Th>
              <Th ancho={120}>Cuándo</Th>
              <Th num ancho={44}>Veces</Th>
              <Th ancho={110}>Origen</Th>
              <Th>Qué pasó</Th>
            </tr>
          </thead>
          <tbody>
            {incidencias.map((i, n) => (
              <tr key={`${i.origen}-${i.mensaje}-${n}`}>
                <Td mono tono={i.nivel === "WARNING" ? color.warning : color.loss}>
                  {i.nivel}
                </Td>
                {/* Una sola vez: la hora. Repetida: desde cuándo lleva
                    pasando, que es lo que dice si fue un momento malo o
                    lleva toda la mañana. */}
                <Td mono dim>
                  {i.veces > 1 ? `${i.primera}→${i.ultima}` : i.ultima}
                </Td>
                <Td num mono fuerte={i.veces > 1}>{i.veces}</Td>
                <Td dim>{i.origen}</Td>
                <Td title={i.traza || undefined}>
                  {i.mensaje}
                  {i.traza && (
                    <span style={{ color: color.textMuted, marginLeft: 6, fontSize: 9 }}>
                      (con traza — está en el copiado)
                    </span>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {abierto && (
        <div style={{
          maxHeight: 320, overflowY: "auto",
          borderTop: incidencias.length > 0 ? hairline : undefined,
          padding: "6px 10px", fontFamily: font.mono, fontSize: 10,
          lineHeight: 1.55, whiteSpace: "pre-wrap",
        }}>
          {lineas.length === 0
            ? <span style={{ color: color.textMuted }}>
                El bot no ha publicado nada todavía. Si está apagado o acaba de
                arrancar, es lo normal.
              </span>
            : lineas.map((l, n) => (
                <div key={n} style={{
                  color: l.nivel === "INFO" ? color.textSecondary
                       : l.nivel === "WARNING" ? color.warning : color.loss,
                }}>
                  <span style={{ color: color.textMuted }}>{l.hora}</span>{"  "}{l.texto}
                </div>
              ))}
        </div>
      )}

      {!abierto && incidencias.length === 0 && (
        <div style={{
          padding: "8px 10px", fontFamily: font.sans, fontSize: 10,
          color: color.textMuted,
        }}>
          Nada que contar. Aquí sale cualquier cosa que le salte al bot — cortes
          del feed, fallos al hablar con la página, errores sin capturar — y su
          log, con un botón para copiarlo entero y pegarlo.
        </div>
      )}
    </Seccion>
  );
}

const botonDiario = (activo: boolean): React.CSSProperties => ({
  fontFamily: font.mono, fontSize: 9, letterSpacing: "0.06em",
  padding: "2px 8px", cursor: "pointer", borderRadius: 2,
  background: activo ? color.copper : "transparent",
  border: `0.5px solid ${activo ? color.copper : color.border}`,
  color: activo ? "#fff" : color.textMuted,
});

function Dato({ etiqueta, valor, tono }: { etiqueta: string; valor: string; tono?: string }) {
  return (
    <span style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
      <span style={{
        fontFamily: font.sans, fontSize: 9, letterSpacing: "0.09em",
        textTransform: "uppercase", color: color.textMuted,
      }}>{etiqueta}</span>
      <span style={{ color: tono || color.textPrimary }}>{valor}</span>
    </span>
  );
}
