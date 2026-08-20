"use client";

/**
 * El titulo de la cabecera, que ademas actua como boton de actualizacion del
 * lago local.
 *
 * Por que en el titulo y no en un boton aparte: para no anadir cromo a la
 * cabecera. Al pulsarlo lanza la actualizacion en el backend y el propio
 * titulo pasa a mostrar el progreso.
 *
 * No bloquea nada: el backend corre el script en un hilo y aqui solo se
 * consulta el estado cada 2 s. Se puede seguir usando la app mientras tanto
 * (aunque conviene no lanzar backtests pesados a la vez: competirian por el
 * disco).
 *
 * Si el backend no tiene la actualizacion habilitada (LAKE_UPDATE_ENABLED),
 * el titulo se comporta como texto normal, sin cursor ni hover.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

type Estado = {
  status: "idle" | "running" | "done" | "error";
  fase?: string;
  error?: string | null;
  disponible?: boolean;
  ultima_linea?: string;
};

const TITULO_STYLE: React.CSSProperties = {
  fontFamily: "var(--color-ec-serif)",
  fontSize: 20,
  fontWeight: 600,
  letterSpacing: "-0.3px",
  margin: 0,
};

export default function LakeUpdateLogo({ texto = "Backtester" }: { texto?: string }) {
  const [estado, setEstado] = useState<Estado>({ status: "idle" });
  const [hover, setHover] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const leerEstado = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/lake/status`);
      if (!r.ok) return;
      const d: Estado = await r.json();
      setEstado(d);
      // Dejar de sondear cuando termina
      if (d.status !== "running" && timer.current) {
        clearInterval(timer.current);
        timer.current = null;
        if (d.status === "done") {
          setAviso("Datos actualizados");
          setTimeout(() => setAviso(null), 6000);
        } else if (d.status === "error") {
          setAviso(d.error ? `Error: ${d.error}` : "Error al actualizar");
          setTimeout(() => setAviso(null), 12000);
        }
      }
    } catch {
      /* backend caido: se reintenta en el siguiente tick */
    }
  }, []);

  // Estado inicial (para saber si esta disponible y si ya hay uno corriendo)
  useEffect(() => {
    leerEstado();
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [leerEstado]);

  // Sondeo mientras corre
  useEffect(() => {
    if (estado.status === "running" && !timer.current) {
      timer.current = setInterval(leerEstado, 2000);
    }
  }, [estado.status, leerEstado]);

  const lanzar = useCallback(async () => {
    if (estado.status === "running" || !estado.disponible) return;
    setAviso(null);
    setEstado((e) => ({ ...e, status: "running", fase: "Arrancando..." }));
    try {
      const r = await fetch(`${API_BASE}/lake/update`, { method: "POST" });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        const msg = j?.detail?.message || `No se pudo lanzar (HTTP ${r.status})`;
        setEstado({ status: "error", error: msg, disponible: estado.disponible });
        setAviso(msg);
        setTimeout(() => setAviso(null), 12000);
        return;
      }
      leerEstado();
    } catch (e) {
      const msg = "No se pudo contactar con el backend";
      setEstado({ status: "error", error: msg, disponible: estado.disponible });
      setAviso(msg);
      setTimeout(() => setAviso(null), 12000);
    }
  }, [estado.status, estado.disponible, leerEstado]);

  const corriendo = estado.status === "running";
  const clicable = !!estado.disponible && !corriendo;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
      <h1
        onClick={clicable ? lanzar : undefined}
        // Accesible por teclado: un <h1> con onClick no lo es. Con role,
        // tabIndex y onKeyDown se comporta como el boton que realmente es.
        role={clicable ? "button" : undefined}
        tabIndex={clicable ? 0 : undefined}
        onKeyDown={
          clicable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  lanzar();
                }
              }
            : undefined
        }
        aria-busy={corriendo || undefined}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        title={
          !estado.disponible
            ? "Backtester"
            : corriendo
            ? estado.fase || "Actualizando..."
            : "Pulsa para traer los datos de mercado que falten hasta hoy"
        }
        style={{
          ...TITULO_STYLE,
          color:
            corriendo || (hover && clicable)
              ? "var(--color-ec-copper)"
              : "var(--color-ec-text-high)",
          cursor: clicable ? "pointer" : "default",
          transition: "color 120ms ease",
          userSelect: "none",
        }}
      >
        {texto}
      </h1>

      {corriendo && (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontFamily: "var(--color-ec-sans)",
            fontSize: 11,
            color: "var(--color-ec-copper)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            maxWidth: 340,
          }}
        >
          <span
            aria-hidden
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              border: "1.5px solid var(--color-ec-copper)",
              borderTopColor: "transparent",
              animation: "lake-spin 700ms linear infinite",
              flexShrink: 0,
            }}
          />
          Actualizando{estado.fase ? ` — ${estado.fase}` : "..."}
        </span>
      )}

      {!corriendo && aviso && (
        <span
          style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 11,
            color:
              estado.status === "error"
                ? "var(--color-ec-text-secondary)"
                : "var(--color-ec-copper)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            maxWidth: 420,
          }}
        >
          {aviso}
        </span>
      )}

      <style>{`@keyframes lake-spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  );
}
