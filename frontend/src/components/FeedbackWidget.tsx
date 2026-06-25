"use client";

import { useEffect, useState, useCallback } from "react";
import { useUser } from "@clerk/nextjs";
import { X, Check, Send } from "lucide-react";
import {
  getFeedbackBoard,
  voteFeature,
  sendSuggestion,
  type FeedbackBoard,
} from "@/lib/api_feedback";
import { track, EVENTS } from "@/lib/analytics";

const OTHER = "__other__";

export function FeedbackWidget({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { user } = useUser();
  const userId = user?.id ?? null;

  const [board, setBoard] = useState<FeedbackBoard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"vote" | "results">("vote");
  const [selected, setSelected] = useState<string | null>(null);
  const [otherText, setOtherText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [thanksOther, setThanksOther] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const b = await getFeedbackBoard(userId);
      setBoard(b);
      if (b.my_vote) {
        setSelected(b.my_vote);
        setView("results");
      } else {
        setView("vote");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    if (open) {
      setThanksOther(false);
      setOtherText("");
      load();
    }
  }, [open, load]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const maxVotes = Math.max(1, ...(board?.options.map((o) => o.votes) ?? [1]));

  async function submitVote() {
    if (!selected || !userId) return;
    if (selected === OTHER) {
      const text = otherText.trim();
      if (!text) return;
      setSubmitting(true);
      try {
        await sendSuggestion(text, userId);
        track(EVENTS.FEEDBACK_SUBMITTED, { round: board?.round });
        setThanksOther(true);
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo enviar");
      } finally {
        setSubmitting(false);
      }
      return;
    }
    setSubmitting(true);
    try {
      const b = await voteFeature(selected, userId);
      track(EVENTS.ROADMAP_VOTED, { option_id: selected, round: b.round });
      setBoard(b);
      setView("results");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo votar");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        fontFamily: "'General Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 460,
          maxHeight: "85vh",
          overflowY: "auto",
          background: "var(--color-ec-bg-surface)",
          border: "0.5px solid var(--color-ec-border)",
          borderRadius: 10,
          padding: "22px 24px 20px",
          boxShadow: "0 18px 50px rgba(0,0,0,0.5)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div
              style={{
                fontFamily: "'Fraunces', serif",
                fontSize: 19,
                fontWeight: 600,
                color: "var(--color-ec-text-high)",
                letterSpacing: "-0.3px",
              }}
            >
              Ayúdanos a priorizar
            </div>
            <div style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", marginTop: 4, lineHeight: 1.4 }}>
              ¿Qué echas de menos en Edgecute para tu día a día?
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Cerrar"
            style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--color-ec-text-muted)", padding: 4, lineHeight: 0 }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ height: 16 }} />

        {loading && <div style={{ fontSize: 12, color: "var(--color-ec-text-muted)" }}>Cargando…</div>}
        {error && (
          <div style={{ fontSize: 12, color: "#C94D3F", marginBottom: 10 }}>{error}</div>
        )}

        {/* THANKS for free-text suggestion */}
        {thanksOther && (
          <div style={{ textAlign: "center", padding: "18px 0" }}>
            <div style={{ fontSize: 28 }}>🙌</div>
            <div style={{ fontSize: 13, color: "var(--color-ec-text-high)", marginTop: 8, fontWeight: 600 }}>
              ¡Gracias! Lo tendremos en cuenta.
            </div>
            <button onClick={onClose} style={primaryBtn} >Cerrar</button>
          </div>
        )}

        {/* VOTE MODE */}
        {!loading && !thanksOther && view === "vote" && board && (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {board.options.map((o) => (
                <label key={o.id} style={optionRow(selected === o.id)}>
                  <input
                    type="radio"
                    name="feature"
                    checked={selected === o.id}
                    onChange={() => setSelected(o.id)}
                    style={{ accentColor: "var(--color-ec-copper)", marginTop: 2 }}
                  />
                  <span>
                    <span style={{ fontSize: 13, color: "var(--color-ec-text-high)", fontWeight: 500 }}>{o.label}</span>
                    {o.description && (
                      <span style={{ display: "block", fontSize: 11, color: "var(--color-ec-text-muted)", marginTop: 2 }}>{o.description}</span>
                    )}
                  </span>
                </label>
              ))}

              {/* Other */}
              <label style={optionRow(selected === OTHER)}>
                <input
                  type="radio"
                  name="feature"
                  checked={selected === OTHER}
                  onChange={() => setSelected(OTHER)}
                  style={{ accentColor: "var(--color-ec-copper)", marginTop: 2 }}
                />
                <span style={{ width: "100%" }}>
                  <span style={{ fontSize: 13, color: "var(--color-ec-text-high)", fontWeight: 500 }}>Otra cosa…</span>
                  {selected === OTHER && (
                    <textarea
                      autoFocus
                      value={otherText}
                      onChange={(e) => setOtherText(e.target.value)}
                      placeholder="Cuéntanos qué te falta"
                      rows={3}
                      style={{
                        width: "100%",
                        marginTop: 8,
                        background: "var(--color-ec-bg-base)",
                        border: "0.5px solid var(--color-ec-border)",
                        borderRadius: 6,
                        color: "var(--color-ec-text-high)",
                        fontSize: 12,
                        fontFamily: "inherit",
                        padding: "8px 10px",
                        resize: "vertical",
                      }}
                    />
                  )}
                </span>
              </label>
            </div>

            <button
              onClick={submitVote}
              disabled={submitting || !selected || (selected === OTHER && !otherText.trim()) || !userId}
              style={{ ...primaryBtn, opacity: submitting || !selected || (selected === OTHER && !otherText.trim()) || !userId ? 0.5 : 1 }}
            >
              {selected === OTHER ? <Send size={14} /> : <Check size={14} />}
              {selected === OTHER ? "Enviar" : "Votar"}
            </button>
            <div style={footNote}>Un voto por novedad. Todos los votos valen igual.</div>
          </>
        )}

        {/* RESULTS MODE */}
        {!loading && !thanksOther && view === "results" && board && (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {board.options.map((o) => {
                const mine = board.my_vote === o.id;
                const pct = Math.round((o.votes / maxVotes) * 100);
                return (
                  <div key={o.id} style={{ border: mine ? "0.5px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)", borderRadius: 7, padding: "9px 11px", background: "var(--color-ec-bg-base)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 12.5, color: "var(--color-ec-text-high)", fontWeight: mine ? 600 : 500 }}>
                        {o.label}
                        {mine && <span style={{ color: "var(--color-ec-copper)", fontSize: 10, fontWeight: 700, marginLeft: 7, textTransform: "uppercase", letterSpacing: 1 }}>Tu voto</span>}
                      </span>
                      <span style={{ fontSize: 12, color: "var(--color-ec-text-secondary)", fontWeight: 600, flexShrink: 0 }}>{o.votes}</span>
                    </div>
                    <div style={{ height: 5, background: "var(--color-ec-border)", borderRadius: 3, marginTop: 7, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${pct}%`, background: mine ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)", borderRadius: 3, transition: "width 300ms ease" }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 14 }}>
              <span style={{ fontSize: 11, color: "var(--color-ec-text-muted)" }}>{board.total_votes} votos en total</span>
              <button onClick={() => setView("vote")} style={{ background: "transparent", border: "none", color: "var(--color-ec-copper)", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                Cambiar voto
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  marginTop: 16,
  width: "100%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 7,
  background: "var(--color-ec-copper)",
  color: "var(--color-ec-copper-text)",
  border: "none",
  borderRadius: 6,
  padding: "10px 16px",
  fontSize: 12,
  fontWeight: 700,
  letterSpacing: 0.6,
  textTransform: "uppercase",
  cursor: "pointer",
  fontFamily: "'General Sans', sans-serif",
};

const footNote: React.CSSProperties = {
  fontSize: 10.5,
  color: "var(--color-ec-text-muted)",
  marginTop: 9,
  textAlign: "center",
};

function optionRow(active: boolean): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "flex-start",
    gap: 10,
    padding: "10px 11px",
    borderRadius: 7,
    border: active ? "0.5px solid var(--color-ec-copper)" : "0.5px solid var(--color-ec-border)",
    background: active ? "rgba(216,122,61,0.06)" : "var(--color-ec-bg-base)",
    cursor: "pointer",
  };
}
