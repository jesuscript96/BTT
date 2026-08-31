"use client";

/**
 * Configuración de alarmas de servidor.
 *
 * Amplía —no sustituye— los avisos rápidos del grid que ya existían. Aquellos
 * viven en el navegador y solo ven la tabla abierta; estos viven en el servidor,
 * ven el universo entero, funcionan con el navegador cerrado y pueden llegar a
 * Telegram.
 *
 * El usuario no elige si su alarma es instantánea o al cierre de barra: sale de
 * los campos que use (lo calcula el backend y se enseña en la ficha).
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, Plus, Send, Trash2, Loader2, Check, X } from "lucide-react";
import { Button, Input, Select } from "@/components/ui";
import {
  Alarm, AlarmCatalog, AlarmCondition, AlarmDefinition,
  createAlarm, createTelegramLink, deleteAlarm, getAlarmCatalog,
  getTelegramStatus, listAlarms, replayAlarm, type ReplayResult, sendTelegramTest,
  TelegramStatus, unlinkTelegram, updateAlarm,
} from "@/lib/api_alarms";

const LABEL: React.CSSProperties = {
  fontSize: 9, fontWeight: 700, letterSpacing: "1.2px", textTransform: "uppercase",
  color: "var(--color-ec-copper)",
};
const HINT: React.CSSProperties = { fontSize: 11, color: "var(--color-ec-text-muted)", lineHeight: 1.4 };
const ROW: React.CSSProperties = { display: "flex", alignItems: "center", gap: 6 };

const EMPTY_DEFINITION: AlarmDefinition = {
  conditions: [],
  universe: [],
  window: null,
  cooldown: { max_per_ticker_per_day: 3, min_minutes_between: 5 },
  sizing: null,
  channels: { browser: true, telegram: true, sound: true },
};

function newCondition(catalog: AlarmCatalog | null): AlarmCondition {
  return { left: catalog?.fields[0]?.key ?? "price", op: ">", right: 0 };
}

/** Filas de condiciones: campo · operador · (número o campo). */
function ConditionRows({
  catalog, value, onChange, emptyHint,
}: {
  catalog: AlarmCatalog | null;
  value: AlarmCondition[];
  onChange: (v: AlarmCondition[]) => void;
  emptyHint: string;
}) {
  const set = (i: number, patch: Partial<AlarmCondition>) =>
    onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {value.length === 0 && <span style={HINT}>{emptyHint}</span>}
      {value.map((c, i) => {
        const rightIsField = typeof c.right === "string" && Number.isNaN(Number(c.right));
        return (
          <div key={i} style={ROW}>
            <Select value={c.left} onChange={(e) => set(i, { left: e.target.value })}
                    style={{ flex: 2, fontSize: 11 }}>
              {catalog?.fields.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </Select>
            <Select value={c.op} onChange={(e) => set(i, { op: e.target.value })}
                    style={{ flex: 1, fontSize: 11, minWidth: 62 }}>
              {catalog?.operators.map((o) => (
                <option key={o.key} value={o.key}>{o.label}</option>
              ))}
            </Select>
            <Select
              value={rightIsField ? "__field__" : "__number__"}
              onChange={(e) => set(i, {
                right: e.target.value === "__field__" ? (catalog?.fields[0]?.key ?? "vwap") : 0,
              })}
              style={{ width: 74, fontSize: 11 }}
            >
              <option value="__number__">número</option>
              <option value="__field__">campo</option>
            </Select>
            {rightIsField ? (
              <Select value={String(c.right)} onChange={(e) => set(i, { right: e.target.value })}
                      style={{ flex: 2, fontSize: 11 }}>
                {catalog?.fields.map((f) => (
                  <option key={f.key} value={f.key}>{f.label}</option>
                ))}
              </Select>
            ) : (
              <Input type="number" value={String(c.right ?? "")} step="any"
                     onChange={(e) => set(i, { right: Number(e.target.value) })}
                     style={{ flex: 2, fontSize: 11 }} />
            )}
            <button onClick={() => onChange(value.filter((_, j) => j !== i))}
                    title="Quitar condición"
                    style={{ background: "none", border: "none", cursor: "pointer", padding: 2,
                             color: "var(--color-ec-text-muted)", flexShrink: 0 }}>
              <X size={13} />
            </button>
          </div>
        );
      })}
      <Button variant="ghost" onClick={() => onChange([...value, newCondition(catalog)])}
              style={{ alignSelf: "flex-start", fontSize: 11 }}>
        <Plus size={12} /> Añadir condición
      </Button>
    </div>
  );
}

export function AlarmsPanel() {
  const [catalog, setCatalog] = useState<AlarmCatalog | null>(null);
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [telegram, setTelegram] = useState<TelegramStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Alarm | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftSide, setDraftSide] = useState<"long" | "short">("short");
  const [draft, setDraft] = useState<AlarmDefinition>(EMPTY_DEFINITION);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testSent, setTestSent] = useState(false);
  const [replayTicker, setReplayTicker] = useState("");
  const [replayDate, setReplayDate] = useState("");
  const [replayResult, setReplayResult] = useState<ReplayResult | null>(null);
  const [replaying, setReplaying] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [cat, list, tg] = await Promise.all([
        getAlarmCatalog(), listAlarms(), getTelegramStatus(),
      ]);
      setCatalog(cat); setAlarms(list); setTelegram(tg);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las alarmas.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const startNew = () => {
    setEditing({ id: "", name: "", enabled: true, side: "short", definition: EMPTY_DEFINITION });
    setDraftName(""); setDraftSide("short"); setDraft(EMPTY_DEFINITION); setError(null);
  };

  const startEdit = (a: Alarm) => {
    setEditing(a); setDraftName(a.name); setDraftSide(a.side);
    setDraft({ ...EMPTY_DEFINITION, ...a.definition }); setError(null);
  };

  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body = { name: draftName.trim() || "Alarma sin nombre", side: draftSide,
                     enabled: true, definition: draft };
      if (editing?.id) await updateAlarm(editing.id, body);
      else await createAlarm(body);
      setEditing(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (a: Alarm) => {
    setAlarms((prev) => prev.map((x) => (x.id === a.id ? { ...x, enabled: !x.enabled } : x)));
    try { await updateAlarm(a.id, { enabled: !a.enabled }); } catch { await refresh(); }
  };

  const remove = async (a: Alarm) => {
    setAlarms((prev) => prev.filter((x) => x.id !== a.id));
    try { await deleteAlarm(a.id); } catch { await refresh(); }
  };

  const connectTelegram = async () => {
    setBusy(true);
    try {
      const { url } = await createTelegramLink();
      window.open(url, "_blank", "noopener");
      // El vínculo se cierra cuando la persona pulsa START en Telegram; se
      // refresca a los pocos segundos para reflejarlo sin recargar la página.
      setTimeout(() => { void refresh(); }, 6000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo generar el enlace.");
    } finally { setBusy(false); }
  };

  const modeOf = (a: Alarm) =>
    a.definition?.mode === "bar" ? "al cierre de cada minuto" : "al instante";

  const barFieldsUsed = useMemo(() => {
    if (!catalog) return false;
    const barKeys = new Set(catalog.fields.filter((f) => f.kind === "bar").map((f) => f.key));
    return [...(draft.conditions ?? [])].some(
      (c) => barKeys.has(c.left) || (typeof c.right === "string" && barKeys.has(c.right)),
    );
  }, [catalog, draft.conditions]);

  if (loading) {
    return <div style={{ ...ROW, gap: 8, padding: "12px 0", ...HINT }}>
      <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> Cargando alarmas…
    </div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ── Telegram ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={LABEL}>Avisos en el móvil</span>
        {!telegram?.configured ? (
          <span style={HINT}>El bot de Telegram no está configurado en este entorno.</span>
        ) : telegram.link && !telegram.link.broken ? (
          <div style={{ ...ROW, justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "var(--color-ec-profit)", ...ROW, gap: 5 }}>
              <Check size={13} /> Telegram conectado
              {telegram.link.username ? ` (@${telegram.link.username})` : ""}
            </span>
            <div style={ROW}>
              <Button variant="ghost" disabled={busy} style={{ fontSize: 11 }}
                      onClick={async () => {
                        try { await sendTelegramTest(); setTestSent(true);
                              setTimeout(() => setTestSent(false), 3000); }
                        catch (e) { setError(e instanceof Error ? e.message : "Falló el envío."); }
                      }}>
                <Send size={12} /> {testSent ? "Enviado" : "Probar"}
              </Button>
              <Button variant="ghost" style={{ fontSize: 11 }}
                      onClick={async () => { await unlinkTelegram(); await refresh(); }}>
                Desconectar
              </Button>
            </div>
          </div>
        ) : (
          <>
            <Button variant="secondary" onClick={connectTelegram} disabled={busy}
                    style={{ alignSelf: "flex-start", fontSize: 12 }}>
              <Send size={13} /> Conectar Telegram
            </Button>
            <span style={HINT}>
              Se abre una conversación con el bot: pulsa <b>Start</b> y queda vinculado.
              No hace falta dar tu usuario — un bot solo puede escribir a quien le
              escribe primero.
            </span>
          </>
        )}
      </div>

      {/* ── Lista ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ ...ROW, justifyContent: "space-between" }}>
          <span style={LABEL}>Alarmas de estrategia</span>
          <Button variant="ghost" onClick={startNew} style={{ fontSize: 11 }}>
            <Plus size={12} /> Nueva
          </Button>
        </div>

        {alarms.length === 0 && !editing && (
          <span style={HINT}>
            Todavía no tienes alarmas de servidor. Estas vigilan el universo entero
            desde las 4:00 ET aunque tengas el navegador cerrado.
          </span>
        )}

        {alarms.map((a) => (
          <div key={a.id} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
            border: "1px solid var(--color-ec-border)", borderRadius: 4,
            background: "var(--color-ec-bg-surface)",
          }}>
            <input type="checkbox" checked={a.enabled} onChange={() => toggle(a)}
                   title={a.enabled ? "Encendida" : "Apagada"}
                   style={{ width: 16, height: 16, accentColor: "var(--color-ec-copper)", cursor: "pointer" }} />
            <button onClick={() => startEdit(a)} style={{
              flex: 1, background: "none", border: "none", textAlign: "left", cursor: "pointer",
              display: "flex", flexDirection: "column", gap: 2, padding: 0,
            }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--color-ec-text-high)" }}>
                {a.name}
              </span>
              <span style={HINT}>
                {a.side === "short" ? "Corto" : "Largo"} · {a.definition?.conditions?.length ?? 0} condiciones · se evalúa {modeOf(a)}
              </span>
            </button>
            <button onClick={() => remove(a)} title="Borrar"
                    style={{ background: "none", border: "none", cursor: "pointer",
                             color: "var(--color-ec-text-muted)", padding: 2 }}>
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>

      {/* ── Editor ── */}
      {editing && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 12,
          border: "1px solid var(--color-ec-copper)", borderRadius: 4,
          background: "var(--color-ec-bg-elevated)",
        }}>
          <div style={ROW}>
            <Input placeholder="Nombre de la alarma" value={draftName}
                   onChange={(e) => setDraftName(e.target.value)}
                   style={{ flex: 1, fontSize: 12 }} />
            <Select value={draftSide} onChange={(e) => setDraftSide(e.target.value as "long" | "short")}
                    style={{ width: 92, fontSize: 11 }}>
              <option value="short">Corto</option>
              <option value="long">Largo</option>
            </Select>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={LABEL}>Tickers concretos (opcional)</span>
            <Input
              placeholder="XYZ, ABC — vacío para vigilar según el universo"
              value={(draft.watchlist ?? []).join(", ")}
              onChange={(e) => setDraft({
                ...draft,
                watchlist: e.target.value.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean),
              })}
              style={{ fontSize: 11 }}
            />
            <span style={HINT}>
              Si pones tickers, la alarma solo mira esos. Es la vía rápida para
              «avísame de este» y para probar una alarma nueva sin esperar a que
              aparezca un setup.
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={LABEL}>Universo (opcional)</span>
            <span style={HINT}>
              Qué tickers vigilar hoy. Una vez que uno entra, se queda dentro el resto
              de la sesión aunque la condición deje de cumplirse.
            </span>
            <ConditionRows catalog={catalog} value={draft.universe ?? []}
                           emptyHint="Sin filtro: se vigila todo el universo."
                           onChange={(universe) => setDraft({ ...draft, universe })} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={LABEL}>Cuándo avisar</span>
            <ConditionRows catalog={catalog} value={draft.conditions ?? []}
                           emptyHint="Añade al menos una condición."
                           onChange={(conditions) => setDraft({ ...draft, conditions })} />
            <span style={HINT}>
              Se evaluará <b>{barFieldsUsed ? "al cierre de cada minuto" : "al instante"}</b>
              {barFieldsUsed ? " porque usa campos de barra (VWAP, EMA, barra anterior…)." : "."}
            </span>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 128 }}>
              <span style={LABEL}>Franja horaria (ET)</span>
              <div style={ROW}>
                <Input type="time" value={draft.window?.from ?? ""}
                       onChange={(e) => setDraft({ ...draft, window: { ...draft.window, from: e.target.value } })}
                       style={{ fontSize: 11 }} />
                <Input type="time" value={draft.window?.to ?? ""}
                       onChange={(e) => setDraft({ ...draft, window: { ...draft.window, to: e.target.value } })}
                       style={{ fontSize: 11 }} />
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 128 }}>
              <span style={LABEL}>Máx. avisos por ticker/día</span>
              <Input type="number" min={1} value={String(draft.cooldown?.max_per_ticker_per_day ?? 3)}
                     onChange={(e) => setDraft({
                       ...draft,
                       cooldown: { ...draft.cooldown, max_per_ticker_per_day: Number(e.target.value) },
                     })}
                     style={{ fontSize: 11 }} />
              <span style={HINT}>Sin tope, un fade que oscila alrededor del VWAP avisa diez veces por hora.</span>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={LABEL}>Stop y tamaño en el aviso (opcional)</span>
            <span style={HINT}>
              Todo esto es calculable sin saber si estás dentro: el nivel del stop
              es un dato de mercado y el riesgo es configuración.
            </span>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Select
                value={draft.sizing?.stop_ref ?? ""}
                onChange={(e) => setDraft({
                  ...draft, sizing: { ...draft.sizing, stop_ref: e.target.value || undefined },
                })}
                style={{ flex: 2, minWidth: 150, fontSize: 11 }}
              >
                <option value="">Sin stop en el aviso</option>
                {catalog?.fields.filter((f) => f.unit === "$").map((f) => (
                  <option key={f.key} value={f.key}>Stop en {f.label.toLowerCase()}</option>
                ))}
              </Select>
              <Input type="number" step="any" placeholder="% offset"
                     value={String(draft.sizing?.stop_offset_pct ?? "")}
                     onChange={(e) => setDraft({
                       ...draft,
                       sizing: { ...draft.sizing, stop_offset_pct: Number(e.target.value) },
                     })}
                     style={{ width: 84, fontSize: 11 }} />
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Input type="number" step="any" placeholder="Riesgo $ por trade"
                     value={String(draft.sizing?.risk_usd ?? "")}
                     onChange={(e) => setDraft({
                       ...draft,
                       sizing: { ...draft.sizing, risk_usd: Number(e.target.value) || undefined },
                     })}
                     style={{ flex: 1, minWidth: 120, fontSize: 11 }} />
              <Input type="number" step="any" placeholder="…o nominal $ por trade"
                     value={String(draft.sizing?.notional_usd ?? "")}
                     onChange={(e) => setDraft({
                       ...draft,
                       sizing: { ...draft.sizing, notional_usd: Number(e.target.value) || undefined },
                     })}
                     style={{ flex: 1, minWidth: 120, fontSize: 11 }} />
            </div>
            <span style={HINT}>
              Elige uno de los dos. Con entrada 3,42 $ y stop 3,85 $, «riesgo 300 $»
              da 697 acciones y «nominal 300 $» da 88: no son lo mismo.
            </span>
            {draftSide === "short" && (
              <Input type="number" step="any" placeholder="Coste por paquete de locates $ (opcional)"
                     value={String(draft.sizing?.locate_package_cost ?? "")}
                     onChange={(e) => setDraft({
                       ...draft,
                       sizing: { ...draft.sizing, locate_package_cost: Number(e.target.value) || undefined },
                     })}
                     style={{ fontSize: 11 }} />
            )}
          </div>

          {error && (
            <span style={{ fontSize: 11.5, color: "var(--color-ec-loss)" }}>{error}</span>
          )}

          {/* Probar contra un día pasado. Es la única forma de probar el motor
              cuando el WebSocket de Massive no está disponible en este entorno
              (la cuenta solo admite una conexión por clave). */}
          {editing.id && (
            <div style={{ display: "flex", flexDirection: "column", gap: 5,
                          paddingTop: 10, borderTop: "1px solid var(--color-ec-border)" }}>
              <span style={LABEL}>Probar con un día pasado</span>
              <div style={ROW}>
                <Input placeholder="Ticker" value={replayTicker}
                       onChange={(e) => setReplayTicker(e.target.value.toUpperCase())}
                       style={{ width: 96, fontSize: 11 }} />
                <Input type="date" value={replayDate}
                       onChange={(e) => setReplayDate(e.target.value)}
                       style={{ fontSize: 11 }} />
                <Button variant="secondary" disabled={replaying || !replayTicker || !replayDate}
                        style={{ fontSize: 11 }}
                        onClick={async () => {
                          setReplaying(true); setReplayResult(null); setError(null);
                          try {
                            setReplayResult(await replayAlarm(editing.id, replayTicker, replayDate, true));
                          } catch (e) {
                            setError(e instanceof Error ? e.message : "No se pudo reproducir.");
                          } finally { setReplaying(false); }
                        }}>
                  {replaying ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> : null}
                  {replaying ? "Reproduciendo…" : "Reproducir"}
                </Button>
              </div>
              {replayResult && (
                <div style={{ display: "flex", flexDirection: "column", gap: 4,
                              padding: 8, borderRadius: 4,
                              background: "var(--color-ec-bg-surface)" }}>
                  <span style={{ fontSize: 11.5, color: "var(--color-ec-text-high)" }}>
                    {replayResult.bars} barras · universo{" "}
                    {replayResult.entered_universe ? "superado" : "NO superado"} ·{" "}
                    <b>{replayResult.signals.length} señal(es)</b>
                  </span>
                  {replayResult.signals.slice(0, 5).map((sig, i) => (
                    <span key={i} style={{ fontSize: 11, fontFamily: "monospace",
                                           color: "var(--color-ec-copper)" }}>
                      {sig.fired_minute} ET @ {sig.price}
                      {sig.sizing?.stop ? ` · stop ${sig.sizing.stop}` : ""}
                      {sig.sizing?.shares ? ` · ${sig.sizing.shares} acc.` : ""}
                    </span>
                  ))}
                  <span style={HINT}>{replayResult.note}</span>
                </div>
              )}
            </div>
          )}

          <div style={{ ...ROW, justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setEditing(null)} style={{ fontSize: 12 }}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={save} disabled={busy} style={{ fontSize: 12 }}>
              <Bell size={12} /> {busy ? "Guardando…" : "Guardar alarma"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
