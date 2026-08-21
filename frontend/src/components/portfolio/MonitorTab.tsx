"use client";

// Pestaña Monitorizacion (F3).
//
// Por cada estrategia del portfolio o la incubadora: una tarjeta con su
// equity SIMULADA de los ultimos 6 meses (re-ejecutada con sus parametros
// guardados al pulsar Actualizar), el drawdown actual frente al maximo
// teorico de su corrida completa, y sus cifras basicas. Debajo, la zona de la
// curva REAL: pegas tus PnL diarios y se comparan con la simulacion agregada.
//
// El refresco es trabajo PESADO (~20-40 s por estrategia, secuencial, un solo
// trabajo a la vez — 409 si ya hay uno). Los datos quedan guardados: solo se
// recalcula al pulsar el boton.

import React, { useCallback, useEffect, useRef, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import {
  ErrorBox,
  Placeholder,
  ProgressBar,
  ReadingNote,
  RunButton,
  fmt,
} from "@/components/robustez/shared";
import { Help } from "@/components/robustez/help";
import { Sparkline } from "./StrategyShelf";
import { ControlTiempoReal } from "./ControlTiempoReal";
import {
  getPortfolioMonitor,
  getPortfolioMonitorJob,
  refreshPortfolioMonitor,
  type MonitorStrategy,
} from "@/lib/api_portfolio_lab";

/* ── Tarjeta por estrategia ──────────────────────────────────────── */

function Row({ label, value, tone, help }: { label: string; value: string; tone?: string; help?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, padding: "2.5px 0" }}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, fontFamily: font.sans, color: color.textMuted }}>
        {label}
        {help && <Help title={label}>{help}</Help>}
      </span>
      <span style={{ fontSize: 12, fontFamily: font.mono, color: tone || color.textHigh }}>{value}</span>
    </div>
  );
}

function StrategyCard({ s }: { s: MonitorStrategy }) {
  const snap = s.snapshot;
  const ddNow = snap?.dd_now_pct ?? null;
  const ddTeo = s.theoretical.max_drawdown_pct;
  // Cerca del maximo teorico = señal de vigilancia: la estrategia esta
  // sufriendo tanto como lo peor que se le vio en todo el backtest.
  const nearMax = ddNow != null && ddTeo != null && ddTeo < 0 && ddNow / ddTeo > 0.8;

  return (
    <div style={{ background: color.bgSurface, border: `0.5px solid ${color.border}`, borderRadius: radius.md, padding: "13px 15px", display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 13, fontFamily: font.sans, color: color.textHigh, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {s.name}
        </span>
        <span style={{ display: "inline-flex", gap: 5, flexShrink: 0 }}>
          {s.buckets.map((b) => (
            <span key={b} style={{ fontSize: 8.5, letterSpacing: "0.06em", textTransform: "uppercase", fontFamily: font.sans, color: b === "portfolio" ? color.copper : color.info, border: `0.5px solid ${b === "portfolio" ? color.copper : color.info}`, borderRadius: radius.pill, padding: "1px 7px" }}>
              {b}
            </span>
          ))}
        </span>
      </div>

      {snap ? (
        <>
          <Sparkline points={snap.equity} />
          {nearMax && (
            <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.warning, lineHeight: 1.45 }}>
              ⚠ El drawdown actual está al {((ddNow! / ddTeo!) * 100).toFixed(0)}% de su máximo
              teórico — vigílala de cerca.
            </div>
          )}
          <div>
            <Row label="Retorno 6 meses" value={fmt.pct(snap.return_pct)} tone={(snap.return_pct ?? 0) >= 0 ? color.profit : color.loss} />
            <Row
              label="DD actual"
              value={fmt.pct(ddNow)}
              tone={ddNow != null && ddNow < -0.01 ? color.loss : color.textMuted}
              help="Distancia al máximo de la curva simulada de estos 6 meses, a día de hoy."
            />
            <Row label="DD máx 6 meses" value={fmt.pct(snap.max_dd_pct)} tone={color.loss} />
            <Row
              label="DD máx teórico"
              value={fmt.pct(ddTeo)}
              tone={color.loss}
              help="El peor drawdown de la corrida COMPLETA guardada — la vara contra la que se compara el DD actual."
            />
            <Row label="Trades 6 meses" value={fmt.int(snap.n_trades)} />
            <Row label="Win rate 6m" value={fmt.pct(snap.win_rate, 1)} />
          </div>
          <div style={{ fontSize: 9.5, fontFamily: font.sans, color: color.textMuted }}>
            actualizado: {(snap.refreshed_at || "").slice(0, 16).replace("T", " ") || "—"}
          </div>
        </>
      ) : (
        <div style={{ fontSize: 11.5, fontFamily: font.sans, color: color.textMuted, padding: "14px 0", lineHeight: 1.5 }}>
          Sin instantánea todavía — pulsa <strong>Actualizar monitorización</strong> arriba.
        </div>
      )}
    </div>
  );
}

/* ── Pestaña ─────────────────────────────────────────────────────── */

export function MonitorTab() {
  const [strategies, setStrategies] = useState<MonitorStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [jobErrors, setJobErrors] = useState<Array<{ strategy_id: string; error: string }>>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const m = await getPortfolioMonitor();
      setStrategies(m.strategies);
      if (m.busy && m.task_id) setTaskId(m.task_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la monitorización");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Polling del refresco en marcha. Un fallo suelto es transitorio, pero si
  // se repite (backend reiniciado, tarea desaparecida) hay que soltar el
  // botón: antes se quedaba en "Re-ejecutando…" para siempre.
  useEffect(() => {
    if (!taskId) return;
    let fails = 0;
    const stop = () => {
      if (pollRef.current) clearInterval(pollRef.current);
      setTaskId(null);
      setProgress(0);
    };
    pollRef.current = setInterval(async () => {
      try {
        const j = await getPortfolioMonitorJob(taskId);
        fails = 0;
        setProgress(j.progress);
        if (j.status !== "running") {
          stop();
          if (j.status === "error") setError(j.error || "El refresco falló");
          else setJobErrors(j.result?.errors || []);
          load();
        }
      } catch (e) {
        fails += 1;
        if (fails >= 4) {
          stop();
          setError(
            e instanceof Error && /404|desconocid/i.test(e.message)
              ? "El refresco ya no existe (¿se reinició el backend?). Vuelve a lanzarlo."
              : "Se perdió el contacto con el refresco. Vuelve a lanzarlo.",
          );
          load();
        }
      }
    }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [taskId, load]);

  const refresh = async () => {
    setError(null);
    setJobErrors([]);
    try {
      const r = await refreshPortfolioMonitor();
      setTaskId(r.task_id);
      setProgress(0); // sin porcentajes inventados: 0 hasta el primer tick real
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo lanzar el refresco");
    }
  };

  if (loading) {
    return <Placeholder>Cargando monitorización…</Placeholder>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {error && <ErrorBox>{error}</ErrorBox>}

      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <ReadingNote>
            Cada tarjeta re-ejecuta su estrategia con <strong>sus parámetros guardados</strong> sobre
            los últimos 6 meses del lago — la foto de «cómo habría ido si la hubieras estado
            operando». Se recalcula solo al pulsar el botón (~20-40 s por estrategia, en cola) y el
            resultado queda guardado entre sesiones.
          </ReadingNote>
        </div>
        <div style={{ width: 230, flexShrink: 0 }}>
          <RunButton
            onClick={refresh}
            loading={!!taskId}
            disabled={!strategies.length}
            label="Actualizar monitorización"
            loadingLabel="Re-ejecutando…"
          />
          {taskId && (
            <div style={{ marginTop: 8 }}>
              <ProgressBar pct={progress} label="estrategias re-ejecutadas" />
            </div>
          )}
        </div>
      </div>

      {jobErrors.length > 0 && (
        <ErrorBox>
          {jobErrors.map((e) => {
            const nm = strategies.find((s) => s.strategy_id === e.strategy_id)?.name || e.strategy_id;
            return (
              <div key={e.strategy_id}>
                <strong>{nm}</strong>: {e.error}
              </div>
            );
          })}
        </ErrorBox>
      )}

      {!strategies.length ? (
        <Placeholder>
          No hay nada que monitorizar: añade estrategias a <strong>Portfolio</strong> o{" "}
          <strong>Incubadora</strong> desde la pestaña Baúl (necesitan corrida guardada).
        </Placeholder>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))", gap: 14 }}>
          {strategies.map((s) => (
            <StrategyCard key={s.strategy_id} s={s} />
          ))}
        </div>
      )}

      <ControlTiempoReal />
    </div>
  );
}
