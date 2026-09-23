"use client";

// Pagina de Portfolio (laboratorio local, gated por
// NEXT_PUBLIC_PORTFOLIO_ENABLED).
//
// Dos pestañas (21-sep-2026, Jaume: «limpiar la pagina y dejar solo el Baul y
// el crudo, que pasa a llamarse Analisis de portfolio»): «Baul» (el baul de
// estrategias: cuadros, curvas, detalle, renombrar, borrar, orden manual) y
// «Analisis de portfolio» (la cartera en cinco pasos, antes «En crudo»). Las antiguas
// Portfolio (imagen general, modelos de escalado y pesos, comparativa) y
// Monitorizacion (control en tiempo real) se borraron ese dia: lo que valia
// de ellas vive en el crudo (calendario, Monte Carlo, escalado, cuenta real).

import { useCallback, useEffect, useMemo, useState } from "react";
import { Briefcase } from "lucide-react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { SubTabs } from "@/components/robustez/help";
import { BaulTab } from "@/components/portfolio/BaulTab";
import { CrudoTab } from "@/components/portfolio/crudo/CrudoTab";
import {
  deletePortfolioStrategy,
  listPortfolioStrategies,
  setPortfolioAssignment,
  type Bucket,
  type PortfolioStrategy,
} from "@/lib/api_portfolio_lab";
import { renameStrategy, setStrategyTags } from "@/lib/api";
import { aplicarOrden, guardarOrden, leerOrden, moverEnOrden } from "@/lib/ordenEstrategias";

type Tab = "baul" | "analisis";

export default function PortfolioPage() {
  const [strategiesRaw, setStrategies] = useState<PortfolioStrategy[]>([]);
  // Orden manual (botones ▲▼ en las listas), recordado en el navegador. Es el
  // mismo para el Baul, sus cuadros y «En crudo».
  // Se lee al crear el estado (en el servidor no hay window y sale vacio; la
  // lista solo se pinta tras cargar, asi que no hay desajuste de hidratacion).
  const [orden, setOrden] = useState<string[]>(() => (typeof window === "undefined" ? [] : leerOrden()));
  const strategies = useMemo(() => aplicarOrden(strategiesRaw, orden), [strategiesRaw, orden]);
  const mover = useCallback(
    (s: PortfolioStrategy, dir: -1 | 1, visibles: string[]) => {
      // El orden completo actual = el orden aplicado a TODAS las estrategias.
      const completo = aplicarOrden(strategiesRaw, orden).map((x) => x.id);
      const nuevo = moverEnOrden(completo, visibles, s.id, dir);
      if (!nuevo) return;
      setOrden(nuevo);
      guardarOrden(nuevo);
    },
    [strategiesRaw, orden],
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("baul");
  const [busyId, setBusyId] = useState<string | null>(null);
  // Que se acaba de borrar, para decirlo con numeros en vez de un "hecho" seco.
  const [aviso, setAviso] = useState<string | null>(null);

  // `intento` fuerza una recarga desde el boton «reintentar» del error.
  const [intento, setIntento] = useState(0);
  const [lento, setLento] = useState(false);
  useEffect(() => {
    let alive = true;
    // (loading/error/lento los deja listos el estado inicial o «reintentar»)
    // Pasados 6 s se explica por que puede tardar (arranque de la app).
    const aviso = setTimeout(() => alive && setLento(true), 6000);
    listPortfolioStrategies()
      .then((list) => alive && setStrategies(list))
      .catch((e) => alive && setError(e?.message || "No se pudo cargar el listado de estrategias"))
      .finally(() => {
        clearTimeout(aviso);
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
      clearTimeout(aviso);
    };
  }, [intento]);

  const toggle = useCallback(async (s: PortfolioStrategy, bucket: Bucket, present: boolean) => {
    setBusyId(s.id);
    setError(null);
    try {
      const res = await setPortfolioAssignment(s.id, bucket, present);
      setStrategies((prev) => prev.map((x) => (x.id === s.id ? { ...x, buckets: res.buckets } : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar la asignación");
    } finally {
      setBusyId(null);
    }
  }, []);

  const renombrar = useCallback(async (s: PortfolioStrategy, newName: string) => {
    setError(null);
    try {
      const actualizada = await renameStrategy(s.id, newName);
      setStrategies((prev) => prev.map((x) => (x.id === s.id ? { ...x, name: actualizada.name } : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo renombrar la estrategia");
      throw e;
    }
  }, []);

  // Etiquetas de organización (2026-09-23). Actualización local tras el PATCH:
  // re-listar el Baúl entero cuesta 1-3 s y el listado ya lo trae todo.
  const etiquetar = useCallback(async (s: PortfolioStrategy, tags: string[]) => {
    setError(null);
    try {
      await setStrategyTags(s.id, tags);
      setStrategies((prev) => prev.map((x) => (x.id === s.id ? { ...x, tags } : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron guardar las etiquetas");
      throw e;
    }
  }, []);

  const borrar = useCallback(async (s: PortfolioStrategy) => {
    setBusyId(s.id);
    setError(null);
    setAviso(null);
    try {
      const res = await deletePortfolioStrategy(s.id);
      setStrategies((prev) => prev.filter((x) => x.id !== s.id));
      const partes = [`«${res.name}» borrada sin dejar rastro`];
      const corridas = res.runs_deleted + res.runs_portfolio_deleted;
      if (corridas) {
        partes.push(
          `${corridas} corrida${corridas === 1 ? "" : "s"}` +
            (res.runs_portfolio_deleted ? ` (${res.runs_portfolio_deleted} de cartera)` : ""),
        );
      }
      if (res.files_deleted) partes.push(`${res.files_deleted} ficheros de disco liberados`);
      setAviso(partes.join(" · "));
      setTimeout(() => setAviso(null), 12000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar la estrategia");
    } finally {
      setBusyId(null);
    }
  }, []);

  return (
    <div style={{ padding: "26px 30px 60px", maxWidth: 1680, margin: "0 auto" }}>
      {/* ── Cabecera ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 6 }}>
        <Briefcase style={{ width: 19, height: 19, color: color.copper, strokeWidth: 1.5 }} />
        <h1 style={{ fontSize: 24, fontFamily: font.serif, color: color.textHigh, margin: 0, fontWeight: 400 }}>
          Portfolio
        </h1>
      </div>
      <p style={{ fontSize: 12.5, fontFamily: font.sans, color: color.textMuted, margin: "0 0 22px", maxWidth: 760, lineHeight: 1.6 }}>
        Tus estrategias, una a una (baúl) y juntas como una sola cartera (análisis de portfolio): qué
        rinden en conjunto, qué caída esperar, a qué nivel ir y cuánto peso darle a cada una.
      </p>

      {error && (
        <div style={{ marginBottom: 18 }}>
          <ErrorBox>
            {error}
            {loading ? null : (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => {
                    setLoading(true);
                    setError(null);
                    setLento(false);
                    setIntento((k) => k + 1);
                  }}
                  style={{ background: "none", border: `0.5px solid ${color.border}`, borderRadius: 4, padding: "1px 8px", color: color.textHigh, cursor: "pointer", fontSize: 11, fontFamily: font.sans, marginLeft: 8 }}
                >
                  reintentar
                </button>
              </>
            )}
          </ErrorBox>
        </div>
      )}

      {aviso && (
        <div
          style={{
            marginBottom: 18,
            padding: "9px 13px",
            border: `0.5px solid ${color.border}`,
            borderLeft: `2px solid ${color.copper}`,
            borderRadius: 6,
            fontSize: 11.5,
            fontFamily: font.sans,
            color: color.textSecondary,
          }}
        >
          {aviso}
        </div>
      )}

      <SubTabs
        value={tab}
        onChange={setTab}
        options={[
          { value: "baul", label: "Baúl" },
          { value: "analisis", label: "Análisis de portfolio" },
        ]}
      />

      {loading ? (
        <div style={{ padding: "40px 20px", textAlign: "center", fontSize: 13, color: color.textMuted, fontFamily: font.sans, lineHeight: 1.6 }}>
          Cargando estrategias…
          {lento && (
            <div style={{ fontSize: 11.5, marginTop: 6 }}>
              Está tardando: nada más arrancar la app, el backend y el bot leen el lago del disco y esta lectura va
              detrás. Puede llegar al minuto; después va en un par de segundos.
            </div>
          )}
        </div>
      ) : tab === "baul" ? (
        <BaulTab strategies={strategies} onToggle={toggle} onDelete={borrar} onRename={renombrar} onTags={etiquetar} onMove={mover} busyId={busyId} />
      ) : (
        <CrudoTab strategies={strategies} onMove={mover} />
      )}
    </div>
  );
}
