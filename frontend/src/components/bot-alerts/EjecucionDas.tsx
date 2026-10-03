"use client";

/**
 * Pestaña «Ejecución»: el bot de ejecución en DAS.
 *
 * El bot no habla con esta página: lee un fichero firmado (el «cuadro») cada
 * segundo y aplica lo que se puede aplicar en caliente. Aquí se ve su estado
 * (latidos, foto, avisos del diario) y se cambian unas pocas hojas del cuadro.
 *
 * Regla de Jaume: TODO botón que cambie algo pide confirmación. Las hojas que
 * el bot solo acepta apagado y sin posiciones (p. ej. halts.silencio) el backend
 * las rechaza con 409 si el bot está encendido; aquí se enseña su mensaje.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Cpu } from "lucide-react";

import { color, font, hairline, ErrorBox, Loading } from "@/components/ui";
import {
  cambiarCuadro,
  exportarCuadro,
  leerEstadoDas,
  mensajeError,
  type CambioCuadro,
  type EstadoDas,
  type EstrategiaCuadro,
} from "@/lib/api_bot_das";

const REFRESCO_MS = 3000;
/** Riesgo por operación por encima de este % del equity → en rojo. */
const UMBRAL_RIESGO_PCT_EQUITY = 1;
/** En fase CANARIO, riesgo por operación por encima de esto ($) → en rojo. */
const UMBRAL_RIESGO_CANARIO_USD = 50;

/* ── Piezas de rejilla (calcadas de CuadroMandos) ─────────────────────── */

function Th({ children, num = false, ancho }: { children?: React.ReactNode; num?: boolean; ancho?: number }) {
  return (
    <th style={{
      textAlign: num ? "right" : "left", fontFamily: font.sans, fontSize: 9, fontWeight: 500,
      letterSpacing: "0.09em", textTransform: "uppercase", color: color.textMuted,
      padding: "7px 10px 6px", borderBottom: `0.5px solid ${color.border}`, whiteSpace: "nowrap",
      width: ancho, background: color.bgSurface,
    }}>{children}</th>
  );
}

function Td({ children, num = false, mono = false, tono, dim = false, title }: {
  children?: React.ReactNode; num?: boolean; mono?: boolean; tono?: string; dim?: boolean; title?: string;
}) {
  return (
    <td title={title} style={{
      textAlign: num ? "right" : "left", fontFamily: mono || num ? font.mono : font.sans, fontSize: 11.5,
      fontVariantNumeric: num ? "tabular-nums" : undefined,
      color: tono || (dim ? color.textMuted : color.textPrimary),
      padding: "5px 10px", borderBottom: `0.5px solid ${color.border}`, whiteSpace: "nowrap",
    }}>{children}</td>
  );
}

function Seccion({ titulo, extra, children }: { titulo: string; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 22 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 7 }}>
        <h2 style={{
          fontFamily: font.sans, fontSize: 10, fontWeight: 600, letterSpacing: "0.11em",
          textTransform: "uppercase", color: color.textSecondary, margin: 0,
        }}>{titulo}</h2>
        {extra}
      </div>
      <div style={{ background: color.bgSurface, border: hairline, borderRadius: 3, overflowX: "auto" }}>
        {children}
      </div>
    </section>
  );
}

function Dato({ etiqueta, valor, tono }: { etiqueta: string; valor: string; tono?: string }) {
  return (
    <span style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
      <span style={{
        fontFamily: font.sans, fontSize: 9, letterSpacing: "0.09em", textTransform: "uppercase", color: color.textMuted,
      }}>{etiqueta}</span>
      <span style={{ color: tono || color.textPrimary }}>{valor}</span>
    </span>
  );
}

const boton = (activo: boolean, tono: string = color.copper): React.CSSProperties => ({
  fontFamily: font.mono, fontSize: 10.5, padding: "3px 10px", cursor: "pointer", borderRadius: 2,
  background: activo ? tono : color.bgElevated,
  border: `0.5px solid ${activo ? tono : color.border}`,
  color: activo ? "#fff" : color.textSecondary,
});

const campo = (rojo: boolean): React.CSSProperties => ({
  width: 84, textAlign: "right", background: color.bgElevated,
  border: `0.5px solid ${rojo ? color.loss : color.border}`, borderRadius: 2,
  color: rojo ? color.loss : color.textPrimary, fontFamily: font.mono, fontSize: 11.5, padding: "2px 6px",
});

const fmt = (v: number | null | undefined, d = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });

const horaDe = (iso: string | null | undefined) => (iso ? iso.slice(11, 19) : "—");

const tonoFase = (fase: string | null | undefined) =>
  fase === "real" ? color.loss : fase === "canario" ? color.warning : color.info;

const textoTramos = (x: unknown): string => {
  if (!Array.isArray(x)) return x == null ? "—" : String(x);
  return x.map((t) => Array.isArray(t)
    ? `${t[0] == null ? "resto" : `≤ ${t[0]} $`}: ${t.slice(1).map((p) => `+${p} %`).join(" / ")}`
    : String(t)).join(" · ");
};

const textoRutas = (r: unknown, prefijo = ""): string[] => {
  if (!r || typeof r !== "object") return [];
  return Object.entries(r as Record<string, unknown>).flatMap(([k, v]) =>
    v && typeof v === "object" ? textoRutas(v, `${prefijo}${k}.`) : [`${prefijo}${k} = ${String(v)}`]);
};

/* ── Componente ───────────────────────────────────────────────────────── */

export default function EjecucionDas() {
  const [estado, setEstado] = useState<EstadoDas | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  /** Lo tecleado y aún sin guardar, por strategy_id. Mientras hay algo aquí, el refresco no lo pisa. */
  const [riesgos, setRiesgos] = useState<Record<string, string>>({});
  const [evs, setEvs] = useState<Record<string, string>>({});
  const [tope, setTope] = useState<string | null>(null);

  const refrescar = useCallback(async () => {
    try {
      const e = await leerEstadoDas();
      setEstado(e);
    } catch (err) {
      setError(mensajeError(err, "No se pudo leer el estado del bot de ejecución"));
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    const primero = setTimeout(refrescar, 0);
    const id = setInterval(refrescar, REFRESCO_MS);
    return () => { clearTimeout(primero); clearInterval(id); };
  }, [refrescar]);

  const cuadro = estado?.cuadro ?? null;
  const foto = estado?.foto ?? null;
  const fase = cuadro?.fase ?? foto?.fase ?? null;
  const equity = foto?.equity ?? null;

  /** Un cambio del cuadro: confirmación, PUT con la versión que se tenía delante y refresco. */
  const aplicar = async (pregunta: string, cambio: CambioCuadro, alAcabar?: () => void) => {
    if (!cuadro || ocupado) return;
    if (!window.confirm(pregunta)) return;
    setOcupado(true);
    try {
      const r = await cambiarCuadro({ ...cambio, config_version: cuadro.config_version });
      setError(null);
      setAviso(r.escrito
        ? `Cuadro guardado (versión ${r.config_version}): ${r.cambios.map((c) => c.ruta).join(", ")}.`
        : "No había nada que cambiar.");
      alAcabar?.();
      await refrescar();
    } catch (err) {
      setAviso(null);
      setError(mensajeError(err, "No se pudo guardar el cuadro"));
    } finally {
      setOcupado(false);
    }
  };

  const alternarBot = () => {
    if (!cuadro) return;
    const encender = !cuadro.vigilando;
    const pregunta = encender
      ? `¿Encender el bot de ejecución en fase ${String(fase || "?").toUpperCase()}?`
      : "¿Apagar el bot de ejecución (deja de abrir posiciones nuevas)?";
    aplicar(pregunta, { vigilando: encender });
  };

  const alternarEjecutar = (e: EstrategiaCuadro) => {
    const activar = !e.ejecutar;
    aplicar(
      `${activar ? "¿ACTIVAR" : "¿Desactivar"} la ejecución de «${e.name}» en fase ${String(fase || "?").toUpperCase()}?`
        + (activar ? `\nRiesgo por operación: ${fmt(e.riesgo_usd, 0)} $ · EV: ${fmt(e.ev_pct, 2)} %` : ""),
      { estrategias: [{ strategy_id: e.strategy_id, ejecutar: activar }] },
    );
  };

  const guardarFila = (e: EstrategiaCuadro) => {
    const r = riesgos[e.strategy_id];
    const v = evs[e.strategy_id];
    const cambio: { strategy_id: string; riesgo_usd?: number | null; ev_pct?: number | null } = { strategy_id: e.strategy_id };
    const partes: string[] = [];
    if (r !== undefined) {
      const n = r.trim() === "" ? null : Number(r);
      if (n !== null && (!Number.isFinite(n) || n < 0)) { setError("El riesgo tiene que ser un número ≥ 0."); return; }
      cambio.riesgo_usd = n;
      partes.push(`riesgo ${fmt(e.riesgo_usd, 0)} → ${n == null ? "vacío" : fmt(n, 0)} $`);
    }
    if (v !== undefined) {
      const n = v.trim() === "" ? null : Number(v);
      if (n !== null && !Number.isFinite(n)) { setError("El EV tiene que ser un número."); return; }
      cambio.ev_pct = n;
      partes.push(`EV ${fmt(e.ev_pct, 2)} → ${n == null ? "vacío (no ejecuta)" : fmt(n, 2)} %`);
    }
    if (!partes.length) return;
    aplicar(`¿Guardar en «${e.name}»: ${partes.join(" · ")}?`, { estrategias: [cambio] }, () => {
      setRiesgos((p) => { const s = { ...p }; delete s[e.strategy_id]; return s; });
      setEvs((p) => { const s = { ...p }; delete s[e.strategy_id]; return s; });
    });
  };

  const guardarTope = () => {
    if (tope == null) return;
    const n = Number(tope);
    if (!Number.isFinite(n) || n <= 0) { setError("El tope de locates tiene que ser un número > 0."); return; }
    aplicar(`¿Cambiar el tope de gasto en locates del día a ${fmt(n, 0)} $?`,
      { locates: { tope_gasto_dia_usd: n } }, () => setTope(null));
  };

  const alternarSilencio = () => {
    const actual = cuadro?.halts?.silencio !== false;
    aplicar(
      `¿${actual ? "Desactivar" : "Activar"} el silencio en halts?\n`
        + (actual ? "Con el silencio APAGADO el bot sí envía órdenes durante un halt."
                  : "Con el silencio ENCENDIDO no se envía nada durante un halt.")
        + "\n(Solo se acepta con el bot apagado y sin posiciones.)",
      { halts: { silencio: !actual } },
    );
  };

  const exportar = async () => {
    if (ocupado) return;
    if (!window.confirm(
      "¿Exportar el cuadro desde las estrategias vigiladas del bot de alertas?\n\n"
      + "Se regeneran las definiciones con el cuadro de producción. Se conservan el ejecutar, el riesgo y el EV de "
      + "las estrategias que ya estaban, y el interruptor, el tope de locates y el silencio en halts. "
      + "Las estrategias NUEVAS entran sin ejecutar.")) return;
    setOcupado(true);
    try {
      const r = await exportarCuadro();
      setError(null);
      setAviso(`Exportado (versión ${r.config_version}): ${r.estrategias} estrategias, ${r.ejecutan} ejecutan.`
        + (r.nuevas.length ? ` Nuevas: ${r.nuevas.join(", ")}.` : "")
        + (r.quitadas.length ? ` Quitadas: ${r.quitadas.join(", ")}.` : "")
        + (r.avisos.length ? ` Avisos: ${r.avisos.join(" · ")}` : ""));
      await refrescar();
    } catch (err) {
      setAviso(null);
      setError(mensajeError(err, "No se pudo exportar el cuadro"));
    } finally {
      setOcupado(false);
    }
  };

  if (cargando) return <Loading />;

  const gasto = foto?.gasto_locates_dia ?? null;
  const topeActual = cuadro?.locates?.tope_gasto_dia_usd ?? null;
  const vivos = (foto?.ordenes || []).length;
  const stops = cuadro?.stops || {};

  const riesgoAlto = (valor: number | null): string | null => {
    if (valor == null || !Number.isFinite(valor)) return null;
    if (equity && valor > equity * UMBRAL_RIESGO_PCT_EQUITY / 100) {
      return `Más del ${UMBRAL_RIESGO_PCT_EQUITY} % del equity (${fmt(equity, 0)} $)`;
    }
    if (fase === "canario" && valor > UMBRAL_RIESGO_CANARIO_USD) {
      return `En CANARIO, más de ${UMBRAL_RIESGO_CANARIO_USD} $ por operación`;
    }
    return null;
  };

  return (
    <div>
      {error && <div style={{ marginBottom: 12 }}><ErrorBox>{error}</ErrorBox></div>}
      {aviso && (
        <div style={{
          marginBottom: 12, padding: "8px 12px", border: hairline, borderRadius: 3, background: color.bgSurface,
          fontFamily: font.sans, fontSize: 11.5, color: color.textSecondary,
        }}>{aviso}</div>
      )}
      {estado?.cuadro_error && (
        <div style={{ marginBottom: 12 }}><ErrorBox>Cuadro: {estado.cuadro_error}</ErrorBox></div>
      )}

      {/* ── Barra de estado ─────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "center", flexWrap: "wrap", gap: "10px 22px",
        background: color.bgSurface, border: hairline, borderRadius: 3,
        padding: "10px 14px", fontFamily: font.mono, fontSize: 11,
      }}>
        <span style={{
          fontFamily: font.sans, fontSize: 13, fontWeight: 700, letterSpacing: "0.12em",
          padding: "4px 12px", borderRadius: 3, border: `1px solid ${tonoFase(fase)}`, color: tonoFase(fase),
        }} title="Fase del cuadro (sombra: no envía órdenes; canario y real: sí)">
          {String(fase || "?").toUpperCase()}
        </span>

        <button
          onClick={alternarBot}
          disabled={!cuadro || ocupado}
          title="Interruptor del cuadro (vigilando)"
          style={{
            fontFamily: font.sans, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em",
            textTransform: "uppercase", padding: "5px 14px", borderRadius: 3, cursor: "pointer",
            border: `0.5px solid ${cuadro?.vigilando ? color.profit : color.border}`,
            background: cuadro?.vigilando ? "rgba(74,157,127,0.12)" : "transparent",
            color: cuadro?.vigilando ? color.profit : color.textSecondary,
          }}
        >{cuadro?.vigilando ? "Vigilando" : "Parado"}</button>

        <Dato etiqueta="Procesos" valor={estado?.encendido ? "encendido" : "apagado"}
              tono={estado?.encendido ? color.profit : color.textMuted} />
        <Dato etiqueta="Último latido" valor={horaDe(estado?.ultimo_latido)} />
        <Dato etiqueta="DAS" valor={foto?.das_conectado == null ? "—" : foto.das_conectado ? "conectado" : "SIN CONEXIÓN"}
              tono={foto?.das_conectado === false ? color.loss : undefined} />
        <Dato etiqueta="Posiciones" valor={String(foto?.posiciones?.length ?? 0)}
              tono={(foto?.posiciones?.length ?? 0) > 0 ? color.copper : undefined} />
        <Dato etiqueta="Órdenes vivas" valor={String(vivos)} />
        <Dato etiqueta="Locates hoy" valor={`${fmt(gasto, 0)} / ${fmt(topeActual, 0)} $`}
              tono={foto?.locates_tope_dia ? color.loss : undefined} />
        <Dato etiqueta="Cuadro" valor={cuadro ? `v${cuadro.config_version}` : "—"} />
        {foto?.control_humano && <Dato etiqueta="Control" valor="HUMANO" tono={color.warning} />}
        {(foto?.modos_degradados?.length ?? 0) > 0 && (
          <Dato etiqueta="Degradado" valor={foto!.modos_degradados.join(", ")} tono={color.warning} />
        )}
        <button onClick={exportar} disabled={ocupado} style={{ ...boton(false), marginLeft: "auto" }}
                title="Regenera el cuadro desde las estrategias vigiladas del bot de alertas">
          Exportar cuadro desde las estrategias vigiladas
        </button>
      </div>

      {/* ── Estrategias ─────────────────────────────────────────────── */}
      <Seccion titulo="Estrategias del cuadro" extra={
        <span style={{ fontFamily: font.sans, fontSize: 10, color: color.textMuted }}>
          Rojo: riesgo &gt; {UMBRAL_RIESGO_PCT_EQUITY} % del equity, o &gt; {UMBRAL_RIESGO_CANARIO_USD} $ en canario
        </span>
      }>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
          <thead>
            <tr>
              <Th ancho={90}>Ejecutar</Th>
              <Th>Estrategia</Th>
              <Th num ancho={110}>Riesgo $</Th>
              <Th num ancho={100}>EV %</Th>
              <Th ancho={90} />
              <Th>Nota</Th>
            </tr>
          </thead>
          <tbody>
            {(cuadro?.estrategias || []).length === 0 && (
              <tr><Td dim>No hay estrategias en el cuadro. Exporta desde las vigiladas.</Td></tr>
            )}
            {(cuadro?.estrategias || []).map((e) => {
              const rTxt = riesgos[e.strategy_id] ?? (e.riesgo_usd == null ? "" : String(e.riesgo_usd));
              const vTxt = evs[e.strategy_id] ?? (e.ev_pct == null ? "" : String(e.ev_pct));
              const sucio = riesgos[e.strategy_id] !== undefined || evs[e.strategy_id] !== undefined;
              const alto = riesgoAlto(rTxt === "" ? null : Number(rTxt));
              return (
                <tr key={e.strategy_id}>
                  <Td>
                    <button onClick={() => alternarEjecutar(e)} disabled={ocupado}
                            style={{ ...boton(e.ejecutar), width: 70 }}>
                      {e.ejecutar ? "SÍ" : "no"}
                    </button>
                  </Td>
                  <Td title={e.strategy_id}>{e.name}</Td>
                  <Td num>
                    <input type="number" min={0} step={10} value={rTxt} title={alto || undefined}
                           onChange={(ev) => setRiesgos((p) => ({ ...p, [e.strategy_id]: ev.target.value }))}
                           style={campo(!!alto)} />
                  </Td>
                  <Td num>
                    <input type="number" step={0.1} value={vTxt}
                           onChange={(ev) => setEvs((p) => ({ ...p, [e.strategy_id]: ev.target.value }))}
                           style={campo(false)} />
                  </Td>
                  <Td>
                    {sucio && (
                      <button onClick={() => guardarFila(e)} disabled={ocupado} style={boton(true)}>Guardar</button>
                    )}
                  </Td>
                  <Td dim tono={alto ? color.loss : undefined}>
                    {alto || e.motivo_no_ejecuta || (e.ev_pct == null ? "sin EV: no ejecuta" : "")}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Seccion>

      {/* ── Ajustes ─────────────────────────────────────────────────── */}
      <Seccion titulo="Ajustes">
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
          <tbody>
            <tr>
              <Td dim>Tope de gasto en locates del día ($)</Td>
              <Td>
                <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                  <input type="number" min={1} step={50}
                         value={tope ?? (topeActual == null ? "" : String(topeActual))}
                         onChange={(ev) => setTope(ev.target.value)} style={campo(false)} />
                  {tope != null && (
                    <button onClick={guardarTope} disabled={ocupado} style={boton(true)}>Guardar</button>
                  )}
                </span>
              </Td>
            </tr>
            <tr>
              <Td dim title="Solo con el bot apagado y sin posiciones">Silencio en halts (no se envía nada en un halt)</Td>
              <Td>
                <button onClick={alternarSilencio} disabled={!cuadro || ocupado}
                        style={{ ...boton(cuadro?.halts?.silencio !== false), width: 70 }}>
                  {cuadro?.halts?.silencio !== false ? "SÍ" : "no"}
                </button>
                {estado?.bloquea_no_calientes && (
                  <span style={{ marginLeft: 10, fontSize: 10.5, color: color.textMuted }}>
                    bot encendido: no se puede cambiar
                  </span>
                )}
              </Td>
            </tr>
            <tr><Td dim>Margen del stop por tramo</Td>
              <Td mono>{stops.limite_tramos ? textoTramos(stops.limite_tramos) : `+${String(stops.limite_pct ?? "—")} %`}</Td></tr>
            <tr><Td dim>Escalones del bot de emergencia (extendido / RTH)</Td>
              <Td mono>{stops.banda_tramos ? textoTramos(stops.banda_tramos) : `+${String(stops.banda_pct ?? "—")} %`}</Td></tr>
            <tr><Td dim>Techo sobre el límite del stop</Td>
              <Td mono>{stops.techo_pct == null ? "— (el límite del stop)" : `+${String(stops.techo_pct)} %`}</Td></tr>
            <tr><Td dim>Escalón cada · respaldo · sin ejecutar · Pref</Td>
              <Td mono>{`${String(stops.escalon_s ?? 0.5)} s · ${stops.respaldo ? "encendido" : "apagado"} · `
                + `${String(stops.sin_ejecutar_s ?? "—")} s · ${String(stops.pref ?? "—")}`}</Td></tr>
            <tr><Td dim>Rutas</Td>
              <Td mono>{textoRutas(cuadro?.rutas).join(" · ") || "—"}</Td></tr>
          </tbody>
        </table>
      </Seccion>

      {/* ── Posiciones y órdenes ───────────────────────────────────── */}
      {foto && ((foto.posiciones?.length ?? 0) > 0 || vivos > 0) && (
        <Seccion titulo="Posiciones y órdenes vivas">
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
            <thead>
              <tr><Th>Ticker</Th><Th num>Neta DAS</Th><Th num>Medio</Th><Th>Estado</Th><Th>Órdenes</Th></tr>
            </thead>
            <tbody>
              {foto.posiciones.map((p) => (
                <tr key={p.ticker}>
                  <Td mono>{p.ticker}{p.cisne_negro ? " · CISNE NEGRO" : ""}</Td>
                  <Td num>{p.neta_das ?? "—"}</Td>
                  <Td num>{p.avg_das ?? "—"}</Td>
                  <Td dim>{p.estado}{p.motivo ? ` · ${p.motivo}` : ""}</Td>
                  <Td dim mono>
                    {foto.ordenes.filter((o) => o.ticker === p.ticker)
                      .map((o) => `${o.proposito} ${o.lado} ${o.qty}@${o.precio ?? o.stop ?? "?"} (${o.estado})`).join(" · ") || "—"}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </Seccion>
      )}

      {/* ── Avisos ───────────────────────────────────────────────────── */}
      <Seccion titulo="Últimos avisos del bot (hoy)">
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
          <thead>
            <tr><Th ancho={80}>Hora</Th><Th ancho={90}>Proceso</Th><Th ancho={90}>Tipo</Th><Th ancho={60}>Nivel</Th><Th>Texto</Th></tr>
          </thead>
          <tbody>
            {(estado?.avisos || []).length === 0 && <tr><Td dim>Sin avisos hoy.</Td></tr>}
            {(estado?.avisos || []).map((a, k) => (
              <tr key={`${a.t}-${k}`}>
                <Td mono>{horaDe(a.t)}</Td>
                <Td dim>{a.proceso || "—"}</Td>
                <Td dim tono={a.tipo === "incidente" || a.tipo === "excepcion" ? color.loss : undefined}>{a.tipo}</Td>
                <Td num tono={(a.nivel ?? 0) >= 3 ? color.loss : undefined}>{a.nivel ?? "—"}</Td>
                <td style={{
                  fontFamily: font.sans, fontSize: 11.5, color: color.textPrimary, padding: "5px 10px",
                  borderBottom: `0.5px solid ${color.border}`, whiteSpace: "pre-wrap",
                }}>{a.ticker ? `${a.ticker} · ` : ""}{a.texto}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Seccion>

      <div style={{ marginTop: 14, fontFamily: font.mono, fontSize: 10, color: color.textMuted }}>
        <Cpu style={{ width: 11, height: 11, verticalAlign: "-1px", marginRight: 5 }} />
        {estado?.ruta_cuadro} · foto {estado?.foto_edad_s == null ? "—" : `hace ${fmt(estado.foto_edad_s, 0)} s`}
      </div>
    </div>
  );
}
