"use client";

// Pestaña Baul: el baul generico con todas las estrategias guardadas y los
// dos cuadros de destino (portfolio e incubadora). Las asignaciones se
// guardan en el backend (tabla portfolio_lab_assignments) y por eso
// sobreviven a recargas y reinicios.

import React, { useEffect, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ReadingNote } from "@/components/robustez/shared";
import { StrategyShelf, ShelfAction, type CurveState } from "./StrategyShelf";
import { getPortfolioStrategyEquity, type Bucket, type PortfolioStrategy } from "@/lib/api_portfolio_lab";

export function BaulTab({
  strategies,
  onToggle,
  busyId,
}: {
  strategies: PortfolioStrategy[];
  onToggle: (s: PortfolioStrategy, bucket: Bucket, present: boolean) => void;
  busyId: string | null;
}) {
  const inPortfolio = strategies.filter((s) => s.buckets.includes("portfolio"));
  const inIncubator = strategies.filter((s) => s.buckets.includes("incubadora"));

  // Precarga de las curvas de equity de TODAS las estrategias con corrida
  // (~0,3 s cada una, en paralelo): al desplegar una fila, el minigrafico de
  // los ultimos 6 meses ya esta en memoria y sale al instante.
  const [curves, setCurves] = useState<Record<string, CurveState>>({});
  useEffect(() => {
    let alive = true;
    const pending = strategies.filter((s) => s.run && !curves[s.id]);
    if (!pending.length) return;
    setCurves((c) => {
      const next = { ...c };
      for (const s of pending) next[s.id] = "loading";
      return next;
    });
    for (const s of pending) {
      getPortfolioStrategyEquity(s.id)
        .then((r) => alive && setCurves((c) => ({ ...c, [s.id]: r.equity })))
        .catch(() => alive && setCurves((c) => ({ ...c, [s.id]: "error" })));
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies]);

  const toggles = (s: PortfolioStrategy) => {
    const p = s.buckets.includes("portfolio");
    const i = s.buckets.includes("incubadora");
    const busy = busyId === s.id;
    return (
      <>
        <ShelfAction
          label={p ? "✓ Portfolio" : "+ Portfolio"}
          active={p}
          disabled={busy || !s.run}
          title={s.run ? undefined : "Necesita un backtest guardado"}
          onClick={() => onToggle(s, "portfolio", !p)}
        />
        <ShelfAction
          label={i ? "✓ Incubadora" : "+ Incubadora"}
          active={i}
          disabled={busy || !s.run}
          title={s.run ? undefined : "Necesita un backtest guardado"}
          onClick={() => onToggle(s, "incubadora", !i)}
        />
      </>
    );
  };

  const removeFrom = (bucket: Bucket) => (s: PortfolioStrategy) => (
    <ShelfAction label="× quitar" onClick={() => onToggle(s, bucket, false)} disabled={busyId === s.id} />
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <ReadingNote>
        Las estrategias que vayan al portfolio deberían guardarse <strong>normalizadas</strong>: sin
        comisiones, sin slippage, sin locates y sin gastos fijos, con <strong>riesgo FIJO</strong> por
        trade (el importe da igual — el motor lo renormaliza a R=1). Así la unión y el reparto de pesos
        se calculan sobre la señal pura de cada estrategia, y los costes se aplican una sola vez, a
        nivel de portfolio. Si una corrida no está normalizada puede entrar igualmente: el motor la
        normaliza al calcular (distintivo ámbar; exacto salvo el slippage, que se reconstruye de forma
        aproximada).
      </ReadingNote>

      <StrategyShelf
        curves={curves}
        title="Baúl genérico"
        hint="todas las estrategias guardadas · pulsa una fila para ver con qué se corrió"
        strategies={strategies}
        emptyText="No hay estrategias guardadas. Crea una en el Backtester y guárdala con «Guardar estrategia en el baúl»."
        actions={toggles}
      />

      <StrategyShelf
        curves={curves}
        title="Portfolio"
        hint="las que se estudian juntas en la pestaña Portfolio"
        strategies={inPortfolio}
        emptyText="Vacío. Añade estrategias desde el baúl genérico con «+ Portfolio»."
        actions={removeFrom("portfolio")}
      />

      <StrategyShelf
        curves={curves}
        title="Incubadora"
        hint="listas para salir, en observación antes de operar en real"
        strategies={inIncubator}
        emptyText="Vacío. Añade estrategias desde el baúl genérico con «+ Incubadora»."
        actions={removeFrom("incubadora")}
      />

      <p style={{ margin: 0, fontSize: 11, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
        Una estrategia puede estar en los dos cuadros a la vez. Quitarla de un cuadro no borra nada:
        la estrategia y sus corridas siguen en el baúl genérico.
      </p>
    </div>
  );
}
