"use client";

import React, { useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import {
    getSocialSentiment,
    getSocialSummary,
    ApiError,
    type SocialSentiment,
    type SocialSummary,
} from "@/lib/api";

// ─── Helpers de color (PRD §9) ───────────────────────────────
// >55 verde (profit) · <45 rojo (loss) · 45-55 gris (muted)
function sentimentColor(score: number): string {
    if (score > 55) return "var(--color-ec-profit)";
    if (score < 45) return "var(--color-ec-loss)";
    return "var(--color-ec-text-muted)";
}

// Punto sobre un semicírculo (0 → izquierda, 100 → derecha)
function polarPoint(cx: number, cy: number, r: number, score: number) {
    const theta = (180 - (Math.max(0, Math.min(100, score)) / 100) * 180) * (Math.PI / 180);
    return { x: cx + r * Math.cos(theta), y: cy - r * Math.sin(theta) };
}

function arcPath(cx: number, cy: number, r: number, fromScore: number, toScore: number) {
    const start = polarPoint(cx, cy, r, fromScore);
    const end = polarPoint(cx, cy, r, toScore);
    return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${r} ${r} 0 0 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

const EYEBROW: React.CSSProperties = {
    fontFamily: "'General Sans', sans-serif",
    fontSize: 8,
    fontWeight: 700,
    color: "var(--color-ec-copper)",
    textTransform: "uppercase",
    letterSpacing: "1.5px",
    borderBottom: "1px solid var(--color-ec-border)",
    paddingBottom: 4,
    marginBottom: 12,
    display: "block",
};

const CARD: React.CSSProperties = {
    background: "var(--color-ec-bg-surface)",
    border: "0.5px solid var(--color-ec-border)",
    borderRadius: 7,
    padding: "16px 18px",
    display: "flex",
    flexDirection: "column",
    minHeight: 200,
};

// Semicírculo de sentimiento. `value` es el score 0-100 a pintar; el arco solo
// se colorea cuando `filled` (estado success).
function GaugeSvg({ value, color, filled, dashed = false }: { value: number; color: string; filled: boolean; dashed?: boolean }) {
    const needle = polarPoint(100, 100, 80, value);
    return (
        <svg viewBox="0 0 200 120" width="100%" height="120" style={{ overflow: "visible" }}>
            <path
                d={arcPath(100, 100, 80, 0, 100)}
                fill="none"
                stroke="var(--color-ec-border)"
                strokeWidth={10}
                strokeLinecap="round"
                strokeDasharray={dashed ? "4 4" : undefined}
            />
            {filled && (
                <path
                    d={arcPath(100, 100, 80, 0, value)}
                    fill="none"
                    stroke={color}
                    strokeWidth={10}
                    strokeLinecap="round"
                />
            )}
            <line x1={100} y1={100} x2={needle.x} y2={needle.y} stroke={color} strokeWidth={3} strokeLinecap="round" />
            <circle cx={100} cy={100} r={6} fill={color} />
        </svg>
    );
}

// ════════════════════════════════════════════════════════════
//  SentimentGauge — velocímetro de sentimiento a 15m
// ════════════════════════════════════════════════════════════
export function SentimentGauge({ symbol }: { symbol?: string }) {
    const [data, setData] = useState<SocialSentiment | null>(null);
    const [state, setState] = useState<"loading" | "empty" | "error" | "success">("loading");

    useEffect(() => {
        if (!symbol) {
            setState("empty");
            return;
        }
        let cancelled = false;
        setState("loading");
        setData(null);
        getSocialSentiment(symbol)
            .then((d) => {
                if (cancelled) return;
                setData(d);
                // Sin mensajes (volumen 0) → estado vacío "poco debate"
                if (!d.message_volume_score || d.message_volume_score <= 0) {
                    setState("empty");
                } else {
                    setState("success");
                }
            })
            .catch((e) => {
                if (cancelled) return;
                // 404/empty se tratan como vacío; el resto como error
                if (e instanceof ApiError && e.status === 404) setState("empty");
                else setState("error");
            });
        return () => { cancelled = true; };
    }, [symbol]);

    const score = data?.sentiment_score ?? 50;
    const isSuccess = state === "success";
    const color = isSuccess ? sentimentColor(score) : "var(--color-ec-text-muted)";
    const gaugeValue = isSuccess ? score : 50;

    return (
        <div style={CARD}>
            <span style={EYEBROW}>Sentiment Gauge · 15m</span>

            {state === "loading" && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }} className="animate-pulse">
                    <div style={{ width: "80%", height: 90, borderRadius: 999, background: "color-mix(in srgb, var(--color-ec-border) 25%, transparent)" }} />
                    <span style={{ fontSize: 10, fontWeight: 600, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                        Midiendo vibración social...
                    </span>
                </div>
            )}

            {state === "empty" && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6 }}>
                    <GaugeSvg value={gaugeValue} color={color} filled={false} />
                    <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-ec-text-muted)", textAlign: "center" }}>
                        Poco debate social
                    </span>
                </div>
            )}

            {state === "error" && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6, border: "1px dashed var(--color-ec-loss)", borderRadius: 6 }}>
                    <GaugeSvg value={gaugeValue} color={color} filled={false} dashed />
                    <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-ec-loss)" }}>
                        Sentimiento no disponible
                    </span>
                </div>
            )}

            {state === "success" && data && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                    <div style={{ position: "relative", width: "100%" }}>
                        <GaugeSvg value={gaugeValue} color={color} filled />
                        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", paddingBottom: 4 }}>
                            <span style={{ fontFamily: "'General Sans', sans-serif", fontSize: 30, fontWeight: 700, color, lineHeight: 1 }}>
                                {score}
                            </span>
                            <span style={{ fontSize: 11, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "1px" }}>
                                {data.sentiment_label}
                            </span>
                        </div>
                    </div>
                    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, fontSize: 10, fontWeight: 600, color: "var(--color-ec-text-secondary)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                        <TrendingUp size={12} style={{ color: "var(--color-ec-text-muted)" }} />
                        Volumen msgs: {data.message_volume_label}
                    </div>
                </div>
            )}
        </div>
    );
}

// ════════════════════════════════════════════════════════════
//  WhyTrendingBox — catalizador en lenguaje natural
// ════════════════════════════════════════════════════════════
export function WhyTrendingBox({ symbol }: { symbol?: string }) {
    const [data, setData] = useState<SocialSummary | null>(null);
    const [state, setState] = useState<"loading" | "empty" | "error" | "success">("loading");

    useEffect(() => {
        if (!symbol) {
            setState("empty");
            return;
        }
        let cancelled = false;
        setState("loading");
        setData(null);
        getSocialSummary(symbol)
            .then((d) => {
                if (cancelled) return;
                setData(d);
                setState(d.why_trending ? "success" : "empty");
            })
            .catch((e) => {
                if (cancelled) return;
                if (e instanceof ApiError && e.status === 404) setState("empty");
                else setState("error");
            });
        return () => { cancelled = true; };
    }, [symbol]);

    return (
        <div style={CARD}>
            <span style={EYEBROW}>Why It&apos;s Trending</span>

            {state === "loading" && (
                <div className="animate-pulse" style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, justifyContent: "center" }}>
                    {[90, 100, 70].map((w, i) => (
                        <div key={i} style={{ height: 12, width: `${w}%`, borderRadius: 4, background: "color-mix(in srgb, var(--color-ec-border) 25%, transparent)" }} />
                    ))}
                </div>
            )}

            {state === "empty" && (
                <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "0 8px" }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-ec-text-muted)", lineHeight: 1.5, fontStyle: "italic" }}>
                        Tracción social baja en los últimos 15 minutos. Sin catalizadores detectados.
                    </span>
                </div>
            )}

            {state === "error" && (
                <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "0 8px" }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-ec-loss)" }}>
                        Catalizador no disponible
                    </span>
                </div>
            )}

            {state === "success" && data?.why_trending && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
                    <p style={{
                        fontFamily: "'Fraunces', serif",
                        fontSize: 16,
                        fontWeight: 500,
                        lineHeight: 1.55,
                        color: "var(--color-ec-text-high)",
                        margin: 0,
                    }}>
                        {data.why_trending}
                    </p>
                </div>
            )}
        </div>
    );
}
