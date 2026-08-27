"use client";

// Pestaña Baul: el baul generico con todas las estrategias guardadas y los
// dos cuadros de destino (portfolio e incubadora). Las asignaciones se
// guardan en el backend (tabla portfolio_lab_assignments) y por eso
// sobreviven a recargas y reinicios.

import React, { useEffect, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ReadingNote } from "@/components/robustez/shared";
import { StrategyShelf, ShelfAction, type CurveState } from "./StrategyShelf";
import {
  getPortfolioStrategyEquity,
  previewStrategyDeletion,
  type Bucket,
  type DeletionPreview,
  type PortfolioStrategy,
} from "@/lib/api_portfolio_lab";

export function BaulTab({
  strategies,
  onToggle,
  onDelete,
  onRename,
  busyId,
}: {
  strategies: PortfolioStrategy[];
  onToggle: (s: PortfolioStrategy, bucket: Bucket, present: boolean) => void;
  /** Borrado DEFINITIVO: la estrategia, sus corridas y sus asignaciones. */
  onDelete: (s: PortfolioStrategy) => void;
  onRename: (s: PortfolioStrategy, newName: string) => Promise<void>;
  busyId: string | null;
}) {
  // Confirmacion en dos pasos, en la propia fila: el borrado es irreversible y
  // un solo clic en una lista de filas finas se da sin querer. Se guarda el id
  // pendiente, no un booleano, para que abrir la confirmacion de otra fila
  // cierre la anterior sola.
  const [porBorrar, setPorBorrar] = useState<string | null>(null);
  // Lo que se lleva por delante, consultado al abrir la confirmacion. Sin esto
  // el usuario no sabria que tambien caen las corridas de cartera.
  const [previo, setPrevio] = useState<DeletionPreview | null>(null);

  const pedirConfirmacion = (s: PortfolioStrategy) => {
    setPorBorrar(s.id);
    setPrevio(null);
    previewStrategyDeletion(s.id)
      .then((p) => setPrevio(p))
      .catch(() => setPrevio(null)); // sin numeros, pero la confirmacion sigue
  };
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

    if (porBorrar === s.id) {
      // Se enumera lo que desaparece. Las corridas de cartera se destacan
      // porque son el efecto que nadie espera.
      const piezas: string[] = [];
      if (previo) {
        if (previo.runs_own) piezas.push(`${previo.runs_own} corrida${previo.runs_own === 1 ? "" : "s"}`);
        if (previo.runs_portfolio) {
          piezas.push(`${previo.runs_portfolio} de cartera`);
        }
      }
      const aviso = previo
        ? piezas.length
          ? `Se borra la estrategia y ${piezas.join(" + ")}. Sin vuelta atras`
          : "Se borra la estrategia. No tiene corridas guardadas"
        : "Se borra del todo, sin vuelta atras";
      return (
        <>
          <span style={{ fontSize: 10, fontFamily: font.sans, color: color.loss, whiteSpace: "nowrap" }}>
            {aviso}
          </span>
          <ShelfAction label="cancelar" onClick={() => { setPorBorrar(null); setPrevio(null); }} disabled={busy} />
          <ShelfAction
            label={busy ? "borrando…" : "sí, borrar"}
            danger
            disabled={busy}
            onClick={() => {
              setPorBorrar(null);
              setPrevio(null);
              onDelete(s);
            }}
          />
        </>
      );
    }

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
        <ShelfAction
          label="borrar"
          danger
          disabled={busy}
          title="Borra la estrategia y todo rastro de ella. Irreversible."
          onClick={() => pedirConfirmacion(s)}
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
        onRename={onRename}
      />

      <StrategyShelf
        curves={curves}
        title="Portfolio"
        hint="las que se estudian juntas en la pestaña Portfolio"
        strategies={inPortfolio}
        emptyText="Vacío. Añade estrategias desde el baúl genérico con «+ Portfolio»."
        actions={removeFrom("portfolio")}
        onRename={onRename}
      />

      <StrategyShelf
        curves={curves}
        title="Incubadora"
        hint="listas para salir, en observación antes de operar en real"
        strategies={inIncubator}
        emptyText="Vacío. Añade estrategias desde el baúl genérico con «+ Incubadora»."
        actions={removeFrom("incubadora")}
        onRename={onRename}
      />

      <p style={{ margin: 0, fontSize: 11, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
        Una estrategia puede estar en los dos cuadros a la vez. <strong>Quitarla</strong> de un cuadro
        no borra nada: la estrategia y sus corridas siguen en el baúl genérico. <strong>Borrar</strong>,
        en el baúl genérico, no deja rastro: se lleva la estrategia, todas sus corridas guardadas (con
        sus ficheros de disco) y sus asignaciones. También caen las <strong>corridas de cartera</strong>
        que la incluían — las demás estrategias de esa cartera no se tocan, pero ese resultado combinado
        desaparece porque ya no sería reproducible. La confirmación te dice cuántas son antes de pulsar.
      </p>
    </div>
  );
}
