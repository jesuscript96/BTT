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
  listPortfolioStrategies,
  setPortfolioAssignment,
  type Bucket,
  type PortfolioStrategy,
} from "@/lib/api_portfolio_lab";

type Tab = "baul" | "portfolio" | "monitor";

export default function PortfolioPage() {
  const [strategies, setStrategies] = useState<PortfolioStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("baul");
  const [busyId, setBusyId] = useState<string | null>(null);

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
        <BaulTab strategies={strategies} onToggle={toggle} busyId={busyId} />
      ) : tab === "portfolio" ? (
        <PortfolioTab strategies={strategies} />
      ) : (
        <MonitorTab />
      )}
    </div>
  );
}
