"use client";

// Selector de estrategias guardadas del panel del Backtester (2026-09-23).
//
// Sustituye al <select> nativo: un select no admite botones por opción ni
// chips, y con el baúl creciendo hacía falta poder BUSCAR, ver los grupos de
// sesión (premarket / RTH / conjuntas), etiquetar y BORRAR sin salir de aquí.
// El borrado usa el mismo endpoint que el Baúl (portfolio-lab, en cascada) y
// mantiene la confirmación en dos pasos con el preview de corridas.
//
// EL POPOVER VA EN UN PORTAL A document.body: el <aside> del panel lleva
// `overflowX: hidden` y recorta cualquier hijo absoluto a sus 280 px — con
// position: absolute dentro del panel, el ancho del popover da igual (lección
// de la primera iteración: 460 px que nunca se vieron). Con position: fixed
// en un portal escapa del recorte y puede extenderse sobre la zona de
// resultados. Se ancla al botón y se reposiciona con scroll/resize.
//
// Las compartidas siguen abriéndose como borrador, como hacía el optgroup
// del select viejo. Cierra con click-fuera y Escape (patrón de ui/Dropdown).

import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Pencil, Trash2 } from "lucide-react";
import type { Strategy } from "@/lib/api_backtester";
import type { SharedStrategyEntry } from "@/lib/api";
import {
  previewStrategyDeletion,
  type DeletionPreview,
} from "@/lib/api_portfolio_lab";
import { allTags, autoTags, sessionGroup, type SessionGroup } from "@/lib/strategyTags";
import { TagChip, TagEditor } from "@/components/ui/TagEditor";

const GROUP_ORDER: { key: SessionGroup; label: string }[] = [
  { key: "premarket", label: "Premarket" },
  { key: "rth", label: "RTH" },
  { key: "conjunta", label: "Conjuntas (pre + RTH)" },
  { key: "otras", label: "Otras" },
];

/** Ancho del popover: de verdad, no el del panel. Solo lo limita la ventana. */
const POPOVER_W = 520;

/** Definición de una estrategia venga como venga (envuelta de /data/strategies
 *  o plana): el resto del panel ya resuelve `s.definition ?? s` igual. */
function defOf(s: Strategy): Record<string, unknown> {
  return ((s.definition || s) as Record<string, unknown>) || {};
}

type Pos = { top: number; left: number; height: number };

/** Dónde poner el popover para que quepa: debajo del botón si hay sitio,
 * encima si no, y a pantalla completa como último recurso. */
function medir(r: DOMRect): Pos {
  const margin = 10;
  const gap = 6;
  const below = window.innerHeight - r.bottom - gap - margin;
  if (below >= 300) return { top: r.bottom + gap, left: r.left, height: Math.min(470, below) };
  const above = r.top - gap - margin;
  if (above >= 300) return { top: Math.max(margin, r.top - gap - Math.min(470, above)), left: r.left, height: Math.min(470, above) };
  return { top: margin, left: r.left, height: window.innerHeight - 2 * margin };
}

export default function StrategyPickerMenu({
  strategies,
  sharedList,
  selectedId,
  isDraft,
  activeStrategyName,
  onSelect,
  onOpenSharedDraft,
  onDelete,
  onTagsSaved,
  disabled,
}: {
  strategies: Strategy[];
  sharedList: SharedStrategyEntry[];
  /** Id de la guardada seleccionada (o el id draft_* si hay borrador). */
  selectedId: string;
  isDraft: boolean;
  activeStrategyName?: string;
  onSelect: (id: string) => void;
  onOpenSharedDraft: (entry: SharedStrategyEntry) => void;
  /** Borra en cascada (estrategia + corridas + asignaciones) y refresca la
   *  lista del panel. El picker ya enseñó el preview antes de llamar. */
  onDelete: (s: Strategy) => Promise<void>;
  /** Persiste los tags y refresca la lista del panel. */
  onTagsSaved: (s: Strategy, tags: string[]) => Promise<void>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<Pos | null>(null);
  const [q, setQ] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Confirmación de borrado en dos pasos, dentro de la propia fila.
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [preview, setPreview] = useState<DeletionPreview | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Fila con el editor de tags abierto.
  const [editingId, setEditingId] = useState<string | null>(null);

  const reposicionar = () => {
    const r = rootRef.current?.getBoundingClientRect();
    if (r) setPos(medir(r));
  };

  useEffect(() => {
    if (!open) return;
    // El popover vive en un portal (fuera del <aside> con overflow hidden):
    // el click-fuera tiene que mirar el botón Y el popover.
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || popRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    // Con scroll (capture: también el del propio panel) o resize, el popover
    // pegado al botón se queda colgado: se vuelve a medir.
    window.addEventListener("resize", reposicionar);
    window.addEventListener("scroll", reposicionar, true);
    // El buscador arranca listo para teclear: se abre a buscar, no a mirar.
    setTimeout(() => inputRef.current?.focus(), 30);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", reposicionar);
      window.removeEventListener("scroll", reposicionar, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const cerrar = () => {
    setOpen(false);
    setQ("");
    setConfirmId(null);
    setPreview(null);
    setEditingId(null);
    setDeleteError(null);
  };

  const abrir = () => {
    reposicionar();
    setOpen(true);
  };

  const seleccionar = (id: string) => {
    onSelect(id);
    cerrar();
  };

  const pedirConfirmacion = (s: Strategy) => {
    setConfirmId(s.id);
    setPreview(null);
    setDeleteError(null);
    previewStrategyDeletion(s.id)
      .then((p) => setPreview(p))
      .catch(() => setPreview(null)); // sin números, pero la confirmación sigue
  };

  const ejecutarBorrado = async (s: Strategy) => {
    if (deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(s);
      setConfirmId(null);
      setPreview(null);
      if (editingId === s.id) setEditingId(null);
    } catch (e) {
      console.error("Error deleting strategy:", e);
      setDeleteError("No se pudo borrar. Reintenta o usa el Baúl de Portfolio.");
    } finally {
      setDeleting(false);
    }
  };

  const query = q.trim().toLowerCase();
  const filtra = (s: Strategy) =>
    !query ||
    s.name.toLowerCase().includes(query) ||
    allTags(defOf(s), s.tags).some((t) => t.toLowerCase().includes(query));

  const porGrupo = useMemo(() => {
    const visibles = strategies.filter(filtra);
    const grupos = new Map<SessionGroup, Strategy[]>();
    for (const s of visibles) {
      const g = sessionGroup(defOf(s));
      if (!grupos.has(g)) grupos.set(g, []);
      grupos.get(g)!.push(s);
    }
    return grupos;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies, query]);

  const compartidasFiltradas = sharedList.filter(
    (c) => !query || c.name.toLowerCase().includes(query),
  );

  // Sugerencias: todos los tags manuales que ya existen en otras estrategias.
  const sugerencias = useMemo(
    () => [...new Set(strategies.flatMap((s) => s.tags || []))],
    [strategies],
  );

  const seleccionada = strategies.find((s) => s.id === selectedId);
  const etiquetaTrigger = isDraft
    ? `[Borrador] ${activeStrategyName || ""}`
    : seleccionada?.name || "cargar estrategia guardada…";

  const filaError = deleteError ? (
    <div style={{ padding: "4px 10px 6px", fontSize: 10, fontFamily: "var(--color-ec-sans)", color: "var(--color-ec-loss)" }}>
      {deleteError}
    </div>
  ) : null;

  const popover =
    open && pos ? (
      <div
        ref={popRef}
        role="listbox"
        style={{
          position: "fixed",
          top: pos.top,
          left: pos.left,
          width: POPOVER_W,
          maxWidth: "calc(100vw - 24px)",
          maxHeight: pos.height,
          overflowY: "auto",
          background: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: "var(--ec-radius-lg)",
          boxShadow: "var(--ec-shadow-lg)",
          zIndex: "var(--ec-z-dropdown, 50)",
          padding: 4,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ padding: "4px 4px 6px" }}>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setConfirmId(null);
              setEditingId(null);
            }}
            placeholder="buscar por nombre o tag…"
            style={{
              width: "100%",
              boxSizing: "border-box",
              backgroundColor: "var(--color-ec-bg-elevated)",
              border: "0.5px solid color-mix(in srgb, var(--color-ec-text-secondary) 45%, transparent)",
              borderRadius: 5,
              padding: "6px 9px",
              fontFamily: "var(--color-ec-sans)",
              fontSize: 11.5,
              color: "var(--color-ec-text-primary)",
              outline: "none",
            }}
          />
        </div>

        {isDraft && activeStrategyName && (
          <PickerRow
            label={`[Borrador] ${activeStrategyName}`}
            selected
            onClick={() => seleccionar(selectedId)}
          />
        )}

        {GROUP_ORDER.map(({ key, label }) => {
          const items = porGrupo.get(key);
          if (!items?.length) return null;
          return (
            <div key={key}>
              <GroupLabel>{label}</GroupLabel>
              {items.map((s) =>
                confirmId === s.id ? (
                  <ConfirmRow
                    key={s.id}
                    nombre={s.name}
                    preview={preview}
                    busy={deleting}
                    onCancel={() => { setConfirmId(null); setPreview(null); setDeleteError(null); }}
                    onConfirm={() => ejecutarBorrado(s)}
                  />
                ) : (
                  <React.Fragment key={s.id}>
                    <PickerRow
                      label={s.name}
                      selected={s.id === selectedId && !isDraft}
                      onClick={() => seleccionar(s.id)}
                      actions={
                        <>
                          <RowAction
                            title="Etiquetas de organización"
                            onClick={() => { setEditingId(editingId === s.id ? null : s.id); setConfirmId(null); }}
                          >
                            <Pencil size={12} strokeWidth={1.8} />
                          </RowAction>
                          <RowAction
                            title="Borrar esta estrategia (con sus corridas)"
                            danger
                            onClick={() => pedirConfirmacion(s)}
                          >
                            <Trash2 size={12} strokeWidth={1.8} />
                          </RowAction>
                        </>
                      }
                    >
                      {(() => {
                        const autos = autoTags(defOf(s));
                        const todos = allTags(defOf(s), s.tags);
                        return (
                          <>
                            {todos.slice(0, 2).map((t) => (
                              <TagChip key={t} label={t} auto={autos.includes(t)} maxLabelWidth={130} />
                            ))}
                            {todos.length > 2 && (
                              <span style={{ fontSize: 9.5, fontFamily: "var(--color-ec-sans)", color: "var(--color-ec-text-secondary)", whiteSpace: "nowrap" }}>
                                +{todos.length - 2}
                              </span>
                            )}
                          </>
                        );
                      })()}
                    </PickerRow>
                    {editingId === s.id && (
                      <div style={{ padding: "6px 10px 8px", borderBottom: "0.5px solid var(--color-ec-border)" }}>
                        <TagEditor
                          tags={s.tags || []}
                          autoTags={autoTags(defOf(s))}
                          suggestions={sugerencias}
                          onSave={(next) => onTagsSaved(s, next)}
                        />
                      </div>
                    )}
                  </React.Fragment>
                ),
              )}
            </div>
          );
        })}

        {strategies.length === 0 && (
          <div style={{ padding: "10px 10px 12px", fontSize: 11, fontFamily: "var(--color-ec-sans)", color: "var(--color-ec-text-muted)" }}>
            No hay estrategias guardadas. Crea una y guárdala con «Guardar estrategia en el baúl».
          </div>
        )}

        {filaError}

        {compartidasFiltradas.length > 0 && onOpenSharedDraft && (
          <div>
            {/* El rótulo va en mayúsculas y cobre (el acento de la casa), igual
                que el optgroup del select que sustituye. */}
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                color: "var(--color-ec-copper)",
                fontFamily: "var(--color-ec-sans)",
                padding: "8px 10px 3px",
                borderTop: "0.5px solid var(--color-ec-border)",
                marginTop: 4,
              }}
            >
              Compartidas — abren como borrador
            </div>
            {compartidasFiltradas.map((c) => (
              <PickerRow
                key={`shared:${c.shared_by}/${c.filename}`}
                label={`${c.name} · ${c.shared_by.toUpperCase()}`}
                onClick={() => {
                  onOpenSharedDraft(c);
                  cerrar();
                }}
              />
            ))}
          </div>
        )}
      </div>
    ) : null;

  return (
    <div ref={rootRef} style={{ position: "relative", flex: 1, minWidth: 0 }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => (open ? cerrar() : abrir())}
        style={{
          backgroundColor: "var(--color-ec-bg-elevated)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 5,
          padding: "7px 10px",
          fontFamily: "var(--color-ec-sans)",
          fontSize: 12,
          fontWeight: 500,
          color: seleccionada || isDraft ? "var(--color-ec-text-primary)" : "var(--color-ec-text-muted)",
          outline: "none",
          width: "100%",
          cursor: disabled ? "not-allowed" : "pointer",
          display: "flex",
          alignItems: "center",
          gap: 8,
          textAlign: "left",
        }}
      >
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {etiquetaTrigger}
        </span>
        <ChevronDown
          size={13}
          strokeWidth={2}
          style={{ flexShrink: 0, transform: open ? "rotate(180deg)" : "none", transition: "transform 150ms", color: "var(--color-ec-text-muted)" }}
        />
      </button>

      {/* El popover se monta FUERA del panel (portal): el <aside> del
          Backtester lleva overflowX: hidden y recortaría cualquier hijo
          absoluto a sus 280 px, por mucho ancho que le pongamos. */}
      {popover && createPortal(popover, document.body)}
    </div>
  );
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 8.5,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.09em",
        color: "var(--color-ec-text-muted)",
        fontFamily: "var(--color-ec-sans)",
        padding: "7px 10px 3px",
      }}
    >
      {children}
    </div>
  );
}

function PickerRow({
  label,
  selected,
  onClick,
  actions,
  children,
}: {
  label: string;
  selected?: boolean;
  onClick: () => void;
  /** Botones que aparecen al pasar el ratón (etiquetar, borrar). */
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      role="option"
      aria-selected={selected}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 8px 5px 10px",
        borderRadius: "var(--ec-radius-sm)",
        cursor: "pointer",
        background: selected
          ? "rgba(216,122,61,0.12)"
          : hover
            ? "var(--color-ec-bg-elevated)"
            : "transparent",
        borderLeft: selected ? `3px solid var(--color-ec-copper)` : "3px solid transparent",
      }}
    >
      <span
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontSize: 12,
          fontFamily: "var(--color-ec-sans)",
          fontWeight: selected ? 600 : 400,
          color: "var(--color-ec-text-primary)",
        }}
      >
        {label}
      </span>
      {/* Chips: se ocultan cuando hay acciones a la vista para que el nombre
          no salte. Los tags completos siguen en el editor de la fila. */}
      <span
        style={{
          display: "inline-flex",
          gap: 3,
          overflow: "hidden",
          opacity: hover && actions ? 0 : 1,
          maxWidth: hover && actions ? 0 : undefined,
        }}
      >
        {children}
      </span>
      {actions && (
        <span
          style={{
            display: "inline-flex",
            gap: 3,
            opacity: hover ? 1 : 0,
            transition: "opacity 100ms",
            flexShrink: 0,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {actions}
        </span>
      )}
    </div>
  );
}

function RowAction({
  children,
  onClick,
  title,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  danger?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 22,
        height: 22,
        padding: 0,
        border: `0.5px solid ${hover ? (danger ? "var(--color-ec-loss)" : "var(--color-ec-copper)") : "var(--color-ec-border)"}`,
        borderRadius: 4,
        background: "transparent",
        color: hover ? (danger ? "var(--color-ec-loss)" : "var(--color-ec-copper)") : "var(--color-ec-text-muted)",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

/** Fila de confirmación de borrado (dos pasos). Enumera lo que se arrastra,
 *  como la confirmación del Baúl. */
function ConfirmRow({
  nombre,
  preview,
  busy,
  onCancel,
  onConfirm,
}: {
  nombre: string;
  preview: DeletionPreview | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const piezas: string[] = [];
  if (preview) {
    if (preview.runs_own) piezas.push(`${preview.runs_own} corrida${preview.runs_own === 1 ? "" : "s"}`);
    if (preview.runs_portfolio) piezas.push(`${preview.runs_portfolio} de cartera`);
  }
  const aviso = preview
    ? piezas.length
      ? `arrastro ${piezas.join(" + ")}`
      : "sin corridas guardadas"
    : "";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
        margin: "2px 4px",
        padding: "6px 8px",
        borderRadius: 5,
        backgroundColor: "color-mix(in srgb, var(--color-ec-loss) 10%, transparent)",
        border: "0.5px solid color-mix(in srgb, var(--color-ec-loss) 30%, transparent)",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <span
        style={{
          flex: 1,
          minWidth: 140,
          fontSize: 10.5,
          lineHeight: 1.4,
          fontFamily: "var(--color-ec-sans)",
          color: "var(--color-ec-loss)",
        }}
      >
        ¿Borrar «{nombre}» para siempre?{aviso ? ` (${aviso})` : ""} Sin vuelta atrás.
      </span>
      <button
        type="button"
        onClick={onCancel}
        disabled={busy}
        className="text-xs font-medium underline hover:no-underline cursor-pointer"
        style={{ color: "var(--color-ec-text-muted)" }}
      >
        cancelar
      </button>
      <button
        type="button"
        onClick={onConfirm}
        disabled={busy}
        className="text-xs font-bold underline hover:no-underline cursor-pointer"
        style={{ color: "var(--color-ec-loss)" }}
      >
        {busy ? "borrando…" : "sí, borrar"}
      </button>
    </div>
  );
}
