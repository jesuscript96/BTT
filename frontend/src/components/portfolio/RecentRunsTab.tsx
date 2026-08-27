"use client";

// Pestaña "Últimas pruebas": los backtests que el backend auto-guarda en cada
// run exitoso (search_mode='auto', retención BTT_AUTOSAVE_KEEP=50). Es la
// resurrección de la sección homónima del antiguo Baúl (/database), ahora con
// reapertura completa: al pulsar una fila se pide el payload guardado por id y
// se deja en la clave de sessionStorage que /backtester restaura al montar
// (backtester_results_state), así el run se repinta sin tocar su página.

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox, ReadingNote } from "@/components/robustez/shared";
import { ShelfAction } from "./StrategyShelf";
import {
  deleteBacktest,
  getRecentRuns,
  getSavedRunById,
  type RecentRun,
} from "@/lib/api";

const fmtPct = (v: number | null | undefined, sign = false) =>
  v == null || Number.isNaN(v)
    ? "—"
    : `${sign && v >= 0 ? "+" : ""}${v.toFixed(1)}%`;

const fmtNum = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(digits);

export function RecentRunsTab() {
  const router = useRouter();
  const [runs, setRuns] = useState<RecentRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [abriendoId, setAbriendoId] = useState<string | null>(null);
  const [borrandoId, setBorrandoId] = useState<string | null>(null);
  // Confirmación en dos pasos en la propia fila (mismo patrón que BaulTab):
  // un borrado de un clic en una lista densa se da sin querer.
  const [porBorrar, setPorBorrar] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getRecentRuns(30)
      .then((r) => alive && setRuns(r.runs))
      .catch((e) => alive && setError(e?.message || "No se pudo cargar el historial de runs"));
    return () => {
      alive = false;
    };
  }, []);

  const abrir = useCallback(async (run: RecentRun) => {
    setAbriendoId(run.id);
    setError(null);
    try {
      const full = await getSavedRunById(run.id);
      const p = full.results_json || {};
      // Sin jobId: el job del backend ya no vive (TTL ~1h) y la equity por día
      // queda deshabilitada para runs reabiertos — métricas, trades, calendario
      // y equity global se repintan igual.
      sessionStorage.setItem(
        "backtester_results_state",
        JSON.stringify({
          result: {
            ...p,
            trades: p.trades || [],
            day_results: p.day_results || [],
          },
          activeStrategy: p.strategy_definition
            ? {
                id: full.strategy_ids?.[0] || "draft_recuperado",
                name: (p.strategy_names || [])[0] || run.label || "Run recuperado",
                definition: p.strategy_definition,
              }
            : null,
        }),
      );
      router.push("/backtester");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo abrir el run");
    } finally {
      setAbriendoId(null);
    }
  }, [router]);

  const borrar = useCallback(async (id: string) => {
    setBorrandoId(id);
    setError(null);
    try {
      await deleteBacktest(id);
      setRuns((prev) => (prev ? prev.filter((r) => r.id !== id) : prev));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar el run");
    } finally {
      setBorrandoId(null);
    }
  }, []);

  if (error) {
    return (
      <div style={{ marginBottom: 18 }}>
        <ErrorBox>{error}</ErrorBox>
      </div>
    );
  }

  if (!runs) {
    return (
      <div style={{ padding: "40px 20px", textAlign: "center", fontSize: 13, color: color.textMuted, fontFamily: font.sans }}>
        Cargando últimos runs…
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <ReadingNote>
        Cada backtest que termina bien se guarda aquí <strong>automáticamente</strong> (las últimas 50
        corridas). Pulsa <strong>abrir</strong> para volver a verlo en el Backtester: métricas, trades,
        calendario y curva de equity global. La curva <strong>por día</strong> solo está disponible
        durante la primera hora tras el run (mientras el job sigue vivo en el backend).
      </ReadingNote>

      {runs.length === 0 ? (
        <div style={{ padding: "36px 16px", textAlign: "center", fontSize: 12.5, color: color.textMuted, fontFamily: font.sans, border: `0.5px solid ${color.border}`, borderRadius: 6 }}>
          Todavía no hay runs. Lanza un backtest en el Backtester y aparecerá aquí al terminar.
        </div>
      ) : (
        <div style={{ border: `0.5px solid ${color.border}`, borderRadius: 6, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontFamily: font.sans }}>
            <thead>
              <tr style={{ borderBottom: `0.5px solid ${color.border}`, backgroundColor: "rgba(28, 30, 33, 0.3)" }}>
                {["Run", "W.Rate", "P.Factor", "Return", "R total", "Trades", "Sharpe", "Fecha"].map((h) => (
                  <th key={h} style={{ padding: "7px 10px", fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: color.textMuted }}>
                    {h}
                  </th>
                ))}
                <th style={{ padding: "7px 10px" }} />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const fecha = r.executed_at
                  ? new Date(r.executed_at).toLocaleString("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
                  : "—";
                const esAuto = r.search_mode === "auto";
                return (
                  <tr
                    key={r.id}
                    style={{ borderBottom: "0.5px solid rgba(44, 47, 51, 0.25)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(216, 122, 61, 0.04)")}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                  >
                    <td style={{ padding: "7px 10px", maxWidth: 320 }}>
                      <div title={r.label || r.id} style={{ fontSize: 11.5, fontWeight: 600, color: color.textHigh, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {r.label || r.id}
                      </div>
                      {!esAuto && (
                        <div style={{ fontSize: 9.5, color: color.textMuted }}>guardado manual</div>
                      )}
                    </td>
                    <td style={{ padding: "7px 10px", fontSize: 11, color: color.textPrimary }}>{fmtPct(r.win_rate)}</td>
                    <td style={{ padding: "7px 10px", fontSize: 11, color: color.textPrimary }}>{fmtNum(r.profit_factor)}</td>
                    <td style={{ padding: "7px 10px", fontSize: 11, fontWeight: 600, color: r.total_return_pct >= 0 ? color.profit : color.loss }}>
                      {fmtPct(r.total_return_pct, true)}
                    </td>
                    <td style={{ padding: "7px 10px", fontSize: 11, color: color.textPrimary }}>{fmtNum(r.total_return_r, 1)}</td>
                    <td style={{ padding: "7px 10px", fontSize: 11, color: color.textPrimary }}>{r.total_trades ?? "—"}</td>
                    <td style={{ padding: "7px 10px", fontSize: 11, color: color.textPrimary }}>{fmtNum(r.sharpe_ratio)}</td>
                    <td style={{ padding: "7px 10px", fontSize: 10, color: color.textMuted, whiteSpace: "nowrap" }}>{fecha}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", whiteSpace: "nowrap" }}>
                      {porBorrar === r.id ? (
                        <>
                          <ShelfAction label="cancelar" onClick={() => setPorBorrar(null)} disabled={borrandoId === r.id} />
                          <ShelfAction
                            label={borrandoId === r.id ? "borrando…" : "¿seguro?"}
                            danger
                            disabled={borrandoId === r.id}
                            onClick={() => {
                              setPorBorrar(null);
                              borrar(r.id);
                            }}
                          />
                        </>
                      ) : (
                        <>
                          <ShelfAction
                            label={abriendoId === r.id ? "abriendo…" : "abrir"}
                            disabled={abriendoId === r.id}
                            onClick={() => abrir(r)}
                          />
                          <ShelfAction label="borrar" danger onClick={() => setPorBorrar(r.id)} disabled={borrandoId === r.id} />
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
