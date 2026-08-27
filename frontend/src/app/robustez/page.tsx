"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { color, font, radius } from "@/components/ui/tokens";
import StrategyPicker from "@/components/robustez/StrategyPicker";
import ModuleRail, { type ModuleId } from "@/components/robustez/ModuleRail";
import ResultsPanel from "@/components/robustez/ResultsPanel";
import { ErrorBox } from "@/components/robustez/shared";
import { useBasico } from "@/components/robustez/modules/useBasico";
import { useMonteCarlo } from "@/components/robustez/modules/useMonteCarlo";
import { useWfo } from "@/components/robustez/modules/useWfo";
import { useBlackSwan } from "@/components/robustez/modules/useBlackSwan";
import { useLocates } from "@/components/robustez/modules/useLocates";
import {
  getRobustezRun,
  listRobustezStrategies,
  type RobustezRun,
  type RobustezStrategy,
} from "@/lib/api_robustez";
import { renameStrategy } from "@/lib/api";

export default function RobustezPage() {
  const [strategies, setStrategies] = useState<RobustezStrategy[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<RobustezRun | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingRunFor, setLoadingRunFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeModule, setActiveModule] = useState<ModuleId>("basico");

  /* Listado de estrategias (ligero: sin trades). */
  useEffect(() => {
    let alive = true;
    listRobustezStrategies()
      .then((list) => {
        if (!alive) return;
        setStrategies(list);
        // Auto-selecciona la primera que tenga backtest guardado: sin corrida
        // no hay nada que analizar.
        const first = list.find((s) => s.run);
        if (first) setSelectedId(first.id);
      })
      .catch((e) => alive && setError(e?.message || "No se pudo cargar el listado de estrategias"))
      .finally(() => alive && setLoadingList(false));
    return () => {
      alive = false;
    };
  }, []);

  /* Trades de la estrategia elegida. */
  useEffect(() => {
    if (!selectedId) {
      setRun(null);
      return;
    }
    let alive = true;
    setLoadingRunFor(selectedId);
    setError(null);
    getRobustezRun(selectedId)
      .then((r) => alive && setRun(r))
      .catch((e) => {
        if (!alive) return;
        setRun(null);
        setError(e?.message || "No se pudo cargar la corrida guardada");
      })
      .finally(() => alive && setLoadingRunFor(null));
    return () => {
      alive = false;
    };
  }, [selectedId]);

  const handleSelect = useCallback((id: string) => setSelectedId(id), []);

  const handleRename = useCallback(async (s: RobustezStrategy, newName: string) => {
    setError(null);
    try {
      const actualizada = await renameStrategy(s.id, newName);
      setStrategies((prev) => prev.map((x) => (x.id === s.id ? { ...x, name: actualizada.name } : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo renombrar la estrategia");
      throw e;
    }
  }, []);

  const selected = strategies.find((s) => s.id === selectedId) || null;

  // Los cinco motores se instancian siempre (los hooks no pueden ser
  // condicionales) pero solo el activo pinta algo: cada uno guarda su propia
  // configuracion, asi que cambiar de pestaña y volver no pierde lo ajustado.
  const ctx = { run, strategy: selected, loading: !!loadingRunFor };
  const engines = {
    basico: useBasico(ctx),
    montecarlo: useMonteCarlo(ctx),
    wfo: useWfo(ctx),
    blackswan: useBlackSwan(ctx),
    locates: useLocates(ctx),
  };
  const engine = engines[activeModule];

  return (
    <div style={{ padding: "26px 30px 60px", maxWidth: 1680, margin: "0 auto" }}>
      {/* ── Cabecera ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 6 }}>
        <ShieldCheck style={{ width: 19, height: 19, color: color.copper, strokeWidth: 1.5 }} />
        <h1
          style={{
            fontSize: 24,
            fontFamily: font.serif,
            color: color.textHigh,
            margin: 0,
            fontWeight: 400,
          }}
        >
          Robustez
        </h1>
      </div>
      <p
        style={{
          fontSize: 12.5,
          fontFamily: font.sans,
          color: color.textMuted,
          margin: "0 0 22px",
          maxWidth: 760,
          lineHeight: 1.6,
        }}
      >
        Somete una estrategia ya backtesteada a estres: cuanto de su resultado es habilidad y cuanto
        suerte del orden en que llegaron los trades, que drawdown deberias esperar, y a partir de que
        coste de locates o slippage deja de ser rentable.
      </p>

      {error && (
        <div style={{ marginBottom: 18 }}>
          <ErrorBox>{error}</ErrorBox>
        </div>
      )}

      {/* ── Cuadro 1: estrategias guardadas ── */}
      <section
        style={{
          background: color.bgSurface,
          border: `0.5px solid ${color.border}`,
          borderRadius: radius.md,
          overflow: "hidden",
          marginBottom: 18,
        }}
      >
        <div
          style={{
            padding: "10px 16px",
            borderBottom: `0.5px solid ${color.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <span
            style={{
              fontSize: 10,
              letterSpacing: "0.11em",
              textTransform: "uppercase",
              color: color.copper,
              fontFamily: font.sans,
            }}
          >
            Estrategias guardadas
          </span>
          <span style={{ fontSize: 11, color: color.textMuted, fontFamily: font.sans }}>
            {loadingList ? "cargando…" : "pulsa una para ver sus condiciones y analizarla"}
          </span>
        </div>

        {loadingList ? (
          <div style={{ padding: "26px 20px", textAlign: "center", fontSize: 13, color: color.textMuted, fontFamily: font.sans }}>
            Cargando estrategias…
          </div>
        ) : (
          <StrategyPicker
            strategies={strategies}
            selectedId={selectedId}
            onSelect={handleSelect}
            onRename={handleRename}
            loadingRunFor={loadingRunFor}
          />
        )}
      </section>

      {/* ── Cuadros 2 y 3: configuracion | visualizacion ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(280px, 340px) minmax(0, 1fr)",
          gap: 18,
          alignItems: "start",
        }}
      >
        <ModuleRail
          active={activeModule}
          onChange={setActiveModule}
          config={engine.config}
          disabled={!run}
        />
        <ResultsPanel module={activeModule}>{engine.results}</ResultsPanel>
      </div>
    </div>
  );
}
