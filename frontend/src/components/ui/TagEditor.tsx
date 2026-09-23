"use client";

// Editor de tags de organización (2026-09-23). Un solo componente para los
// dos sitios donde se etiqueta: el selector de estrategias del Backtester y
// el desplegable de fila del Baúl de Portfolio. Guarda en cada cambio
// (añadir/quitar dispara el SAVE inmediatamente, como el renombrado inline);
// si el PATCH falla, se vuelve al estado anterior y se ve el error.

import React, { useMemo, useState } from "react";
import { color, font, radius } from "./tokens";

/** Chip de solo lectura. `auto` = tag derivado de la definición (tinte cobre,
 *  no se puede quitar a mano); por defecto = tag manual del usuario.
 *
 *  Relleno SIEMPRE: en el tema oscuro un chip sin relleno se vuelve un
 *  fantasma (texto gris sobre gris, borde imperceptible). El texto de los
 *  automáticos es `copper` — NUNCA `copperText`, que es el color para texto
 *  SOBRE relleno cobre (oscuro casi negro) y aquí quedaría invisible. */
export function TagChip({
  label,
  auto,
  onRemove,
  title,
  maxLabelWidth,
}: {
  label: string;
  auto?: boolean;
  onRemove?: () => void;
  title?: string;
  /** Tope de anchura del TEXTO (en filas estrechas): el tag se corta con
   *  «…» DENTRO de la píldora, en vez de rebanar la píldora entera contra
   *  el borde del contenedor. Sin él (editor, detalle), se muestra entero. */
  maxLabelWidth?: number;
}) {
  const bg = auto
    ? "color-mix(in srgb, var(--color-ec-copper) 16%, transparent)"
    : color.bgElevated;
  const fg = auto ? color.copper : color.textHigh;
  const borde = auto
    ? "color-mix(in srgb, var(--color-ec-copper) 55%, transparent)"
    : "color-mix(in srgb, var(--color-ec-text-secondary) 45%, transparent)";
  return (
    <span
      title={title ?? label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 9.5,
        letterSpacing: "0.05em",
        textTransform: "uppercase",
        fontFamily: font.sans,
        fontWeight: 700,
        color: fg,
        background: bg,
        border: `0.5px solid ${borde}`,
        borderRadius: radius.pill,
        padding: "2px 8px",
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          maxWidth: maxLabelWidth,
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {label}
      </span>
      {onRemove && (
        <button
          type="button"
          aria-label={`Quitar tag ${label}`}
          onClick={onRemove}
          style={{
            border: "none",
            background: "transparent",
            color: "inherit",
            cursor: "pointer",
            padding: 0,
            fontSize: 11,
            fontWeight: 700,
            lineHeight: 1,
            fontFamily: font.sans,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}

const MAX_TAGS = 10;
const MAX_TAG_LEN = 24;

/** Editor de los tags manuales de una estrategia.
 *
 *  `tags` = lista guardada; `autoTags` solo se PINTA al lado (no se puede
 *  editar: sale de la definición). `onSave` recibe la lista completa nueva
 *  y debe devolver una promesa; si rechaza, el editor vuelve atrás. */
export function TagEditor({
  tags,
  autoTags = [],
  suggestions = [],
  onSave,
}: {
  tags: string[];
  autoTags?: string[];
  suggestions?: string[];
  onSave: (next: string[]) => Promise<void>;
}) {
  const [current, setCurrent] = useState<string[]>(tags);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Sugerencias = las que ya existen en otras estrategias, menos las que ya
  // lleva puestas. Es lo único que hace falta para no inventar ortografías.
  const sugeridas = useMemo(() => {
    const tiene = new Set(current.map((t) => t.toLowerCase()));
    return [...new Set(suggestions)].filter((s) => !tiene.has(s.toLowerCase())).slice(0, 8);
  }, [suggestions, current]);

  const commit = (next: string[]) => {
    setBusy(true);
    setError(null);
    onSave(next)
      .then(() => setCurrent(next))
      .catch(() => setError("no se pudo guardar"))
      .finally(() => setBusy(false));
  };

  const add = (raw: string) => {
    const t = raw.trim();
    if (!t || busy) return;
    if (t.length > MAX_TAG_LEN) {
      setError(`máx ${MAX_TAG_LEN} caracteres`);
      return;
    }
    if (current.some((x) => x.toLowerCase() === t.toLowerCase())) {
      setDraft("");
      return;
    }
    if (current.length >= MAX_TAGS) {
      setError(`máx ${MAX_TAGS} tags`);
      return;
    }
    setDraft("");
    commit([...current, t]);
  };

  const listId = useMemo(() => `tag-sug-${Math.random().toString(36).slice(2, 8)}`, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
        {autoTags.map((t) => (
          <TagChip key={`auto-${t}`} label={t} auto title="Tag automático: se deriva de la definición de la estrategia" />
        ))}
        {current.map((t) => (
          <TagChip key={t} label={t} onRemove={busy ? undefined : () => commit(current.filter((x) => x !== t))} />
        ))}
        <input
          list={listId}
          value={draft}
          disabled={busy || current.length >= MAX_TAGS}
          placeholder={current.length === 0 && autoTags.length === 0 ? "+ etiqueta…" : "+"}
          onChange={(e) => {
            setError(null);
            const v = e.target.value;
            // La coma añade: permite teclear «scalping, versión-2» de un tirón.
            if (v.endsWith(",")) {
              add(v.slice(0, -1));
            } else {
              setDraft(v);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          style={{
            width: 92,
            padding: "2px 8px",
            fontSize: 10,
            fontFamily: font.sans,
            color: color.textPrimary,
            background: color.bgElevated,
            border: `0.5px solid color-mix(in srgb, var(--color-ec-text-secondary) 45%, transparent)`,
            borderRadius: radius.sm,
            outline: "none",
          }}
        />
        <datalist id={listId}>
          {sugeridas.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        {error && (
          <span style={{ fontSize: 9.5, fontFamily: font.sans, color: color.loss }}>{error}</span>
        )}
      </div>
    </div>
  );
}
