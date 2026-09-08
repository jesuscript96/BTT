"use client";

// Pagina de Portfolio (laboratorio local, gated por
// NEXT_PUBLIC_PORTFOLIO_ENABLED): gestion de la union de estrategias, su
// escalado y reparto de pesos, y su monitorizacion.
//
// Tres pestañas: Baul (baul generico + portfolio + incubadora), Portfolio (la
// imagen general y, en fase 2, los modelos de escalado) y Monitorizacion
// (fase 3). Reemplaza a la antigua pagina /database.

import { useCallback, useEffect, useState } from "react";
import { Briefcase } from "lucide-react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { SubTabs } from "@/components/robustez/help";
import { BaulTab } from "@/components/portfolio/BaulTab";
import { PortfolioTab } from "@/components/portfolio/PortfolioTab";
import { MonitorTab } from "@/components/portfolio/MonitorTab";
import {
  deletePortfolioStrategy,
  listPortfolioStrategies,
  setPortfolioAssignment,
  type Bucket,
  type PortfolioStrategy,
} from "@/lib/api_portfolio_lab";
import { renameStrategy } from "@/lib/api";

type Tab = "baul" | "portfolio" | "monitor";

export default function PortfolioPage() {
  const [strategies, setStrategies] = useState<PortfolioStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("baul");
  const [busyId, setBusyId] = useState<string | null>(null);
  // Que se acaba de borrar, para decirlo con numeros en vez de un "hecho" seco.
  const [aviso, setAviso] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    listPortfolioStrategies()
      .then((list) => alive && setStrategies(list))
      .catch((e) => alive && setError(e?.message || "No se pudo cargar el listado de estrategias"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

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
        Une varias estrategias y estúdialas como una sola cartera: cómo se comportan juntas, cuánto se
        solapan, qué drawdown esperar del conjunto, y — con los modelos de escalado — cuánto peso darle
        a cada una en cada momento.
      </p>

      {error && (
        <div style={{ marginBottom: 18 }}>
          <ErrorBox>{error}</ErrorBox>
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
          { value: "portfolio", label: "Portfolio" },
          { value: "monitor", label: "Monitorización" },
        ]}
      />

      {loading ? (
        <div style={{ padding: "40px 20px", textAlign: "center", fontSize: 13, color: color.textMuted, fontFamily: font.sans }}>
          Cargando estrategias…
        </div>
      ) : tab === "baul" ? (
        <BaulTab strategies={strategies} onToggle={toggle} onDelete={borrar} onRename={renombrar} busyId={busyId} />
      ) : tab === "portfolio" ? (
        <PortfolioTab strategies={strategies} />
      ) : (
        <MonitorTab />
      )}
    </div>
  );
}
