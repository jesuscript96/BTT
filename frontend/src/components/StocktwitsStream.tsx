"use client";

import React, { useCallback, useEffect, useState } from "react";
import { MessageSquareOff, Heart, AlertTriangle, RotateCw } from "lucide-react";
import {
    getSocialStream,
    ApiError,
    type SocialStreamMessage,
} from "@/lib/api";

function SentimentTag({ sentiment }: { sentiment: "Bullish" | "Bearish" | null }) {
    if (!sentiment) return null;
    const isBull = sentiment === "Bullish";
    return (
        <span style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: 9,
            fontWeight: 600,
            padding: "1px 6px",
            borderRadius: 3,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
            color: isBull ? "var(--color-ec-profit)" : "var(--color-ec-loss)",
            background: isBull
                ? "color-mix(in srgb, var(--color-ec-profit) 15%, transparent)"
                : "color-mix(in srgb, var(--color-ec-loss) 15%, transparent)",
            flexShrink: 0,
        }}>
            {sentiment}
        </span>
    );
}

function timeAgo(iso: string): string {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return "";
    const diff = Math.max(0, Date.now() - t) / 1000;
    if (diff < 60) return "ahora";
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
}

export function StocktwitsStream({ symbol }: { symbol?: string }) {
    const [messages, setMessages] = useState<SocialStreamMessage[]>([]);
    const [state, setState] = useState<"loading" | "empty" | "error" | "success">("loading");

    const load = useCallback(() => {
        if (!symbol) {
            setState("empty");
            return () => {};
        }
        let cancelled = false;
        setState("loading");
        getSocialStream(symbol, 15)
            .then((rows) => {
                if (cancelled) return;
                if (!rows || rows.length === 0) {
                    setMessages([]);
                    setState("empty");
                } else {
                    setMessages(rows);
                    setState("success");
                }
            })
            .catch((e) => {
                if (cancelled) return;
                if (e instanceof ApiError && e.status === 404) {
                    setState("empty");
                } else {
                    setState("error");
                }
            });
        return () => { cancelled = true; };
    }, [symbol]);

    useEffect(() => load(), [load]);

    // ── Loading: 5 tarjetas skeleton ──
    if (state === "loading") {
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {[0, 1, 2, 3, 4].map((i) => (
                    <div key={i} className="animate-pulse" style={{
                        height: 64,
                        borderRadius: 7,
                        background: "color-mix(in srgb, var(--color-ec-border) 22%, transparent)",
                    }} />
                ))}
            </div>
        );
    }

    // ── Empty ──
    if (state === "empty") {
        return (
            <div style={{
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                gap: 10, padding: "40px 16px", color: "var(--color-ec-text-muted)",
                border: "1px dashed var(--color-ec-border)", borderRadius: 8,
            }}>
                <MessageSquareOff size={28} style={{ opacity: 0.6 }} />
                <span style={{ fontSize: 12, fontWeight: 500, textAlign: "center" }}>
                    Sin debate relevante hoy. Filtrado de spam activo.
                </span>
            </div>
        );
    }

    // ── Error ──
    if (state === "error") {
        return (
            <div style={{
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                gap: 12, padding: "32px 16px",
                border: "1px solid color-mix(in srgb, var(--color-ec-loss) 40%, transparent)", borderRadius: 8,
            }}>
                <AlertTriangle size={26} style={{ color: "var(--color-ec-loss)" }} />
                <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-ec-text-secondary)" }}>
                    No se pudo cargar el debate.
                </span>
                <button
                    onClick={load}
                    style={{
                        display: "flex", alignItems: "center", gap: 6,
                        background: "var(--color-ec-bg-surface)",
                        border: "0.5px solid var(--color-ec-border)",
                        borderRadius: 5, padding: "7px 13px",
                        fontFamily: "'General Sans', sans-serif", fontSize: 11, fontWeight: 600,
                        textTransform: "uppercase", letterSpacing: "0.5px",
                        color: "var(--color-ec-text-secondary)", cursor: "pointer",
                    }}
                    className="hover:text-[var(--color-ec-text-primary)]"
                >
                    <RotateCw size={12} /> Reintentar cargar debate
                </button>
            </div>
        );
    }

    // ── Success ──
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {messages.map((m) => {
                const profileUrl = `https://stocktwits.com/${encodeURIComponent(m.username)}`;
                return (
                    <div
                        key={m.message_id ?? `${m.username}-${m.created_at}`}
                        style={{
                            background: "var(--color-ec-bg-surface)",
                            border: "0.5px solid var(--color-ec-border)",
                            borderRadius: 7,
                            padding: "12px 14px",
                            transition: "background 150ms ease",
                        }}
                        className="hover:bg-[var(--color-ec-bg-elevated)]"
                    >
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                            <a href={profileUrl} target="_blank" rel="noopener noreferrer" style={{ flexShrink: 0 }}>
                                {m.avatar_url ? (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img src={m.avatar_url} alt={m.username} width={24} height={24}
                                        style={{ borderRadius: "50%", objectFit: "cover", background: "var(--color-ec-bg-sidebar)" }} />
                                ) : (
                                    <span style={{
                                        width: 24, height: 24, borderRadius: "50%", display: "flex",
                                        alignItems: "center", justifyContent: "center",
                                        background: "var(--color-ec-bg-sidebar)", color: "var(--color-ec-copper-bright)",
                                        fontSize: 11, fontWeight: 700,
                                    }}>
                                        {(m.username[0] || "?").toUpperCase()}
                                    </span>
                                )}
                            </a>
                            <a href={profileUrl} target="_blank" rel="noopener noreferrer" style={{
                                fontFamily: "'General Sans', sans-serif", fontSize: 12, fontWeight: 600,
                                color: "var(--color-ec-text-primary)", textDecoration: "none",
                            }} className="hover:text-[var(--color-ec-copper-bright)]">
                                @{m.username}
                            </a>
                            <SentimentTag sentiment={m.user_sentiment} />
                            <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 500, color: "var(--color-ec-text-muted)" }}>
                                {timeAgo(m.created_at)}
                            </span>
                        </div>
                        <p style={{
                            fontFamily: "'General Sans', sans-serif", fontSize: 13, fontWeight: 400,
                            lineHeight: 1.5, color: "var(--color-ec-text-primary)", margin: "0 0 8px 0",
                            wordBreak: "break-word",
                        }}>
                            {m.body}
                        </p>
                        <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-muted)" }}>
                            <Heart size={12} /> {m.likes_count}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
