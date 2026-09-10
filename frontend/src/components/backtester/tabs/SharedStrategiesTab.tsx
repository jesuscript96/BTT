"use client";

// Pestaña "Compartidas" del backtester: compartir estrategias guardadas con
// el otro dev (Álvaro ↔ Sailor) vía JSON en <repo>/estrategias_compartidas/.
// El transporte es git — la app escribe el fichero, pero hasta que el dev no
// commitea esa carpeta el otro no lo ve. Nada automático: solo comparte la
// estrategia en la que se pulsa el botón.

import React, { useCallback, useEffect, useState } from "react";
import { Check, Download, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import {
  createStrategy,
  deleteSharedStrategy,
  getSharedStrategies,
  getStrategies,
  shareStrategy,
  type SharedStrategyEntry,
} from "@/lib/api";
import type { Strategy } from "@/types/strategy";

const OWNER_LABELS: Record<string, string> = { alvaro: "Álvaro", sailor: "Sailor" };

const btnBase: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "4px 10px",
  fontFamily: "var(--color-ec-sans)",
  fontSize: 10,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  backgroundColor: "transparent",
  border: "0.5px solid var(--color-ec-border)",
  borderRadius: 4,
  color: "var(--color-ec-text-muted)",
  cursor: "pointer",
  whiteSpace: "nowrap",
  transition: "all 150ms ease",
};

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  fontFamily: "var(--color-ec-sans)",
  fontSize: 9.5,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.12em",
  color: "var(--color-ec-text-muted)",
  opacity: 0.7,
};

const td: React.CSSProperties = {
  padding: "8px 12px",
  fontFamily: "var(--color-ec-sans)",
  fontSize: 12,
  color: "var(--color-ec-text-primary)",
  borderBottom: "0.5px solid var(--color-ec-border)",
};

function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        fontFamily: "var(--color-ec-sans)",
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.12em",
        color: "var(--color-ec-text-secondary)",
      }}>
        {children}
      </div>
      {hint && (
        <div style={{ fontSize: 11, color: "var(--color-ec-text-muted)", marginTop: 3 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

export default function SharedStrategiesTab() {
  const [owner, setOwner] = useState("");
  const [shared, setShared] = useState<SharedStrategyEntry[]>([]);
  const [mine, setMine] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null); // clave de la fila en curso
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  const refetch = useCallback(async () => {
    // Listas independientes: si una falla (p. ej. backend corriendo una versión
    // sin el endpoint /shared-strategies), la otra sigue visible en vez de
    // vaciar la pestaña entera.
    const [sharedRes, mineRes] = await Promise.allSettled([
      getSharedStrategies(),
      getStrategies(),
    ]);
    if (sharedRes.status === "fulfilled") {
      setOwner(sharedRes.value.owner);
      setShared(sharedRes.value.strategies);
    }
    if (mineRes.status === "fulfilled") {
      setMine(mineRes.value);
    }
    const errorShared = sharedRes.status === "rejected" ? sharedRes.reason : null;
    if (errorShared || mineRes.status === "rejected") {
      const motivo = (errorShared ?? (mineRes as PromiseRejectedResult).reason);
      setFeedback({
        ok: false,
        text: `${motivo instanceof Error ? motivo.message : String(motivo)} — si es un 404, el backend necesita reinicio para cargar el endpoint de compartidas`,
      });
    } else {
      setFeedback(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const refreshSharedOnly = useCallback(async () => {
    try {
      const res = await getSharedStrategies();
      setOwner(res.owner);
      setShared(res.strategies);
    } catch {
      // El refresco de fondo falla en silencio: el feedback de la acción ya avisó.
    }
  }, []);

  const run = async (key: string, action: () => Promise<string>) => {
    setBusy(key);
    setFeedback(null);
    try {
      const msg = await action();
      setFeedback({ ok: true, text: msg });
    } catch (err) {
      setFeedback({
        ok: false,
        text: err instanceof Error ? err.message : "Error inesperado",
      });
    } finally {
      setBusy(null);
    }
  };

  const handleShare = (s: Strategy) =>
    run(`share:${s.id}`, async () => {
      if (!s.id) throw new Error("La estrategia no tiene id");
      const entry = await shareStrategy(s.id);
      await refreshSharedOnly();
      return `"${entry.name}" volcada a estrategias_compartidas/${entry.shared_by}/${entry.filename} — commitea esa carpeta para que llegue por staging`;
    });

  const handleImport = (entry: SharedStrategyEntry) =>
    run(`import:${entry.filename}`, async () => {
      // Copia nueva siempre (decisión de diseño): re-importar no actualiza,
      // crea otra copia que el que importa gestiona a mano.
      await createStrategy({
        name: entry.name,
        description: entry.description ?? "",
        ...(entry.definition as Record<string, unknown>),
      } as Strategy);
      setMine(await getStrategies());
      return `Copia de "${entry.name}" creada en tus estrategias guardadas`;
    });

  const handleRemove = (entry: SharedStrategyEntry) =>
    run(`remove:${entry.filename}`, async () => {
      if (!window.confirm(`¿Quitar "${entry.name}" de estrategias_compartidas?`)) {
        return "(sin cambios)";
      }
      await deleteSharedStrategy(entry.filename);
      await refreshSharedOnly();
      return `"${entry.name}" quitada de la carpeta compartida (recuerda commitear el borrado)`;
    });

  const isMineShared = (s: Strategy) =>
    shared.some((e) => e.shared_by === owner && e.source_strategy_id === s.id);

  const formatFecha = (iso?: string | null) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
  };

  const biasOf = (e: SharedStrategyEntry) => (e.definition as { bias?: string } | undefined)?.bias;

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "48px 0", gap: 8 }}>
        <Loader2 className="animate-spin" style={{ width: 16, height: 16, color: "var(--color-ec-text-muted)" }} />
        <span style={{ fontSize: 11, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>
          Cargando estrategias compartidas…
        </span>
      </div>
    );
  }

  return (
    <div style={{ padding: "16px 4px 24px", display: "flex", flexDirection: "column", gap: 28, maxWidth: 980 }}>
      {feedback && (
        <div style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 11.5,
          color: feedback.ok ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
        }}>
          {feedback.text}
        </div>
      )}

      {/* ── A: lo que ya viaja en el repo ─────────────────────────────── */}
      <section>
        <SectionTitle hint="JSONs en estrategias_compartidas/ — llegan por git (pull de staging). Importar crea una copia nueva en tus estrategias guardadas.">
          En el repo — compartidas por los dos
        </SectionTitle>
        <div style={{ overflowX: "auto", border: "0.5px solid var(--color-ec-border)", borderRadius: 6 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ backgroundColor: "var(--color-ec-bg-elevated)" }}>
              <tr>
                <th style={th}>Nombre</th>
                <th style={th}>Compartida por</th>
                <th style={th}>Bias</th>
                <th style={th}>Fecha</th>
                <th style={{ ...th, textAlign: "right" }}>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {shared.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ ...td, fontStyle: "italic", opacity: 0.55 }}>
                    Nada compartido todavía — usa la sección de abajo para volcar una tuya.
                  </td>
                </tr>
              )}
              {shared.map((e) => {
                const esMia = e.shared_by === owner;
                const bias = biasOf(e);
                return (
                  <tr key={`${e.shared_by}/${e.filename}`}>
                    <td style={td}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontWeight: 600, color: "var(--color-ec-text-high)" }}>{e.name}</span>
                        {e.description && (
                          <span style={{ fontSize: 10.5, color: "var(--color-ec-text-muted)", maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {e.description}
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ ...td, whiteSpace: "nowrap" }}>
                      {OWNER_LABELS[e.shared_by] ?? e.shared_by}
                      {esMia && (
                        <span style={{ marginLeft: 6, fontSize: 9, color: "var(--color-ec-copper)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                          tuya
                        </span>
                      )}
                    </td>
                    <td style={td}>
                      {bias && (
                        <span style={{
                          fontSize: 10,
                          fontWeight: 700,
                          padding: "2px 7px",
                          borderRadius: 3,
                          textTransform: "uppercase",
                          letterSpacing: "0.06em",
                          color: bias === "long" ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
                          backgroundColor: bias === "long" ? "rgba(74, 157, 127, 0.1)" : "rgba(201, 77, 63, 0.1)",
                        }}>
                          {bias}
                        </span>
                      )}
                    </td>
                    <td style={{ ...td, whiteSpace: "nowrap", fontFamily: "var(--color-ec-mono)", fontSize: 11 }}>
                      {formatFecha(e.shared_at)}
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>
                      <div style={{ display: "inline-flex", gap: 6 }}>
                        <button
                          style={btnBase}
                          disabled={busy !== null}
                          onClick={() => handleImport(e)}
                          onMouseEnter={(ev) => { ev.currentTarget.style.color = "var(--color-ec-copper)"; ev.currentTarget.style.borderColor = "var(--color-ec-copper)"; }}
                          onMouseLeave={(ev) => { ev.currentTarget.style.color = "var(--color-ec-text-muted)"; ev.currentTarget.style.borderColor = "var(--color-ec-border)"; }}
                        >
                          {busy === `import:${e.filename}`
                            ? <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} />
                            : <Download style={{ width: 12, height: 12, strokeWidth: 1.5 }} />}
                          Importar copia
                        </button>
                        {esMia && (
                          <button
                            style={{ ...btnBase, color: "var(--color-ec-loss)" }}
                            disabled={busy !== null}
                            onClick={() => handleRemove(e)}
                            onMouseEnter={(ev) => { ev.currentTarget.style.color = "var(--color-ec-text-high)"; ev.currentTarget.style.borderColor = "var(--color-ec-loss)"; }}
                            onMouseLeave={(ev) => { ev.currentTarget.style.color = "var(--color-ec-loss)"; ev.currentTarget.style.borderColor = "var(--color-ec-border)"; }}
                          >
                            {busy === `remove:${e.filename}`
                              ? <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} />
                              : <Trash2 style={{ width: 12, height: 12, strokeWidth: 1.5 }} />}
                            Quitar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── B: compartir una de las mías ──────────────────────────────── */}
      <section>
        <SectionTitle hint="Vuelca la estrategia a estrategias_compartidas/ — solo viaja si luego commiteas esa carpeta y la subes a staging.">
          Compartir una tuya
        </SectionTitle>
        <div style={{ overflowX: "auto", border: "0.5px solid var(--color-ec-border)", borderRadius: 6, maxHeight: 340, overflowY: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ backgroundColor: "var(--color-ec-bg-elevated)", position: "sticky", top: 0 }}>
              <tr>
                <th style={th}>Nombre</th>
                <th style={th}>Creada</th>
                <th style={{ ...th, textAlign: "right" }}>Acción</th>
              </tr>
            </thead>
            <tbody>
              {mine.length === 0 && (
                <tr>
                  <td colSpan={3} style={{ ...td, fontStyle: "italic", opacity: 0.55 }}>
                    No tienes estrategias guardadas todavía.
                  </td>
                </tr>
              )}
              {mine.map((s) => {
                const compartida = isMineShared(s);
                return (
                  <tr key={s.id}>
                    <td style={td}>
                      <span style={{ fontWeight: 600, color: "var(--color-ec-text-high)" }}>{s.name}</span>
                    </td>
                    <td style={{ ...td, whiteSpace: "nowrap", fontFamily: "var(--color-ec-mono)", fontSize: 11 }}>
                      {formatFecha(s.created_at)}
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {compartida && (
                        <span style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          marginRight: 8,
                          fontSize: 9.5,
                          fontWeight: 700,
                          textTransform: "uppercase",
                          letterSpacing: "0.08em",
                          color: "var(--color-ec-profit)",
                        }}>
                          <Check style={{ width: 12, height: 12, strokeWidth: 2 }} />
                          compartida
                        </span>
                      )}
                      <button
                        style={btnBase}
                        disabled={busy !== null || !s.id}
                        onClick={() => handleShare(s)}
                        onMouseEnter={(ev) => { ev.currentTarget.style.color = "var(--color-ec-copper)"; ev.currentTarget.style.borderColor = "var(--color-ec-copper)"; }}
                        onMouseLeave={(ev) => { ev.currentTarget.style.color = "var(--color-ec-text-muted)"; ev.currentTarget.style.borderColor = "var(--color-ec-border)"; }}
                      >
                        {busy === `share:${s.id}`
                          ? <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} />
                          : <Upload style={{ width: 12, height: 12, strokeWidth: 1.5 }} />}
                        {compartida ? "Actualizar" : "Compartir"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button
          style={btnBase}
          onClick={refetch}
          onMouseEnter={(ev) => { ev.currentTarget.style.color = "var(--color-ec-copper)"; ev.currentTarget.style.borderColor = "var(--color-ec-copper)"; }}
          onMouseLeave={(ev) => { ev.currentTarget.style.color = "var(--color-ec-text-muted)"; ev.currentTarget.style.borderColor = "var(--color-ec-border)"; }}
        >
          <RefreshCw style={{ width: 12, height: 12, strokeWidth: 1.5 }} />
          Refrescar
        </button>
        <span style={{ fontSize: 10.5, color: "var(--color-ec-text-muted)", fontFamily: "var(--color-ec-sans)" }}>
          Tras un pull de staging, refresca para ver lo nuevo del otro.
        </span>
      </div>
    </div>
  );
}
