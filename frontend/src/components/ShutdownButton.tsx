"use client";

/**
 * Botón de apagado del entorno local: esquina inferior derecha.
 *
 * Para qué: cerrar backend (8010) y frontend (3000) de una vez, sin tener que
 * buscar las dos ventanas de consola. Sirve también cuando algo se queda
 * colgado y hay que dejar los puertos limpios antes de volver a arrancar.
 *
 * SOLO EXISTE EN LOCAL. Al montar pregunta a /api/local-control/status; si el
 * backend no tiene LOCAL_SHUTDOWN_ENABLED (en producción no lo tiene), este
 * componente devuelve null y no pinta absolutamente nada.
 *
 * El apagado lo ejecuta un script suelto en el backend, no este proceso: por
 * eso tras el POST no llega ninguna confirmación posterior — el servidor que
 * la enviaría es justo el que se está apagando. La cuenta atrás de la UI es
 * informativa.
 */

import { useCallback, useEffect, useState } from "react";
import { Power } from "lucide-react";
import { API_BASE } from "@/lib/api";

type Fase = "oculto" | "listo" | "confirmando" | "apagando" | "error";

const FUENTE = "'General Sans', sans-serif";

export default function ShutdownButton() {
  const [fase, setFase] = useState<Fase>("oculto");
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState(false);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/local-control/status`);
        if (!r.ok) return;
        const d: { disponible?: boolean } = await r.json();
        if (vivo && d?.disponible) setFase("listo");
      } catch {
        /* backend caído o endpoint inexistente: el botón simplemente no aparece */
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  const apagar = useCallback(async () => {
    setError(null);
    setFase("apagando");
    try {
      const r = await fetch(`${API_BASE}/local-control/shutdown`, { method: "POST" });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        const msg = j?.detail?.message || `No se pudo apagar (HTTP ${r.status})`;
        setError(msg);
        setFase("error");
      }
    } catch {
      // El backend puede morir antes de contestar. Eso no es un fallo: es
      // exactamente lo que se le ha pedido, así que se deja el aviso de apagado.
    }
  }, []);

  if (fase === "oculto") return null;

  // Aviso a pantalla completa mientras se apaga. No se quita nunca: cuando el
  // frontend muera, esta pantalla es lo último que queda pintado.
  if (fase === "apagando") {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1100,
          background: "rgba(0,0,0,0.75)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 14,
          fontFamily: FUENTE,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 26,
            height: 26,
            borderRadius: "50%",
            border: "2px solid var(--color-ec-loss)",
            borderTopColor: "transparent",
            animation: "btt-apagando-spin 700ms linear infinite",
          }}
        />
        <span style={{ fontSize: 15, fontWeight: 600, color: "var(--color-ec-text-high)" }}>
          Apagando el Backtester…
        </span>
        <span style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", textAlign: "center" }}>
          Se están cerrando el backend (8010) y el frontend (3000).
          <br />
          Cuando esta página deje de responder, ya puedes cerrar la pestaña.
        </span>
        <style>{`@keyframes btt-apagando-spin { to { transform: rotate(360deg) } }`}</style>
      </div>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        zIndex: 900,
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontFamily: FUENTE,
      }}
    >
      {fase === "error" && error && (
        <span
          style={{
            fontSize: 11,
            color: "var(--color-ec-loss)",
            background: "var(--color-ec-bg-surface)",
            border: "0.5px solid var(--color-ec-border)",
            borderRadius: 6,
            padding: "6px 9px",
            maxWidth: 320,
          }}
        >
          {error}
        </span>
      )}

      {fase === "confirmando" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "var(--color-ec-bg-surface)",
            border: "0.5px solid var(--color-ec-border)",
            borderRadius: 8,
            padding: "8px 10px",
            boxShadow: "0 10px 30px rgba(0,0,0,0.45)",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--color-ec-text-primary)" }}>
            ¿Apagar el Backtester?
          </span>
          <button
            onClick={() => setFase("listo")}
            style={{
              fontFamily: FUENTE,
              fontSize: 12,
              padding: "4px 10px",
              borderRadius: 5,
              border: "0.5px solid var(--color-ec-border)",
              background: "transparent",
              color: "var(--color-ec-text-secondary)",
              cursor: "pointer",
            }}
          >
            Cancelar
          </button>
          <button
            onClick={apagar}
            style={{
              fontFamily: FUENTE,
              fontSize: 12,
              fontWeight: 600,
              padding: "4px 10px",
              borderRadius: 5,
              border: "0.5px solid var(--color-ec-loss)",
              background: "var(--color-ec-loss)",
              color: "#FFF",
              cursor: "pointer",
            }}
          >
            Apagar
          </button>
        </div>
      )}

      <button
        onClick={() => setFase(fase === "confirmando" ? "listo" : "confirmando")}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        aria-label="Apagar el Backtester local"
        title="Apagar el Backtester local (backend y frontend)"
        style={{
          width: 34,
          height: 34,
          borderRadius: "50%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: `0.5px solid ${hover || fase === "confirmando" ? "var(--color-ec-loss)" : "var(--color-ec-border)"}`,
          background: "var(--color-ec-bg-surface)",
          color:
            hover || fase === "confirmando"
              ? "var(--color-ec-loss)"
              : "var(--color-ec-text-muted)",
          cursor: "pointer",
          transition: "color 120ms ease, border-color 120ms ease",
          boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
        }}
      >
        <Power size={16} strokeWidth={2} />
      </button>
    </div>
  );
}
