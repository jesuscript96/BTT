"use client";

import React, { useEffect, useState } from "react";
import { Radar, AlertTriangle, RotateCw } from "lucide-react";
import {
    getSocialTrending,
    type SocialTrendingItem,
} from "@/lib/api";

function fmtMarketCap(m: number | null): string {
    if (m === null || m === undefined) return "-";
    // m viene en millones de USD
    if (m >= 1000) return `$${(m / 1000).toFixed(2)}B`;
    return `$${m.toFixed(0)}M`;
}

function fmtVolume(v: number | null): string {
    if (v === null || v === undefined) return "-";
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return `${v.toFixed(0)}`;
}

function SentimentPill({ score }: { score: number | null }) {
    if (score === null || score === undefined) {
        return <span style={{ color: "var(--color-ec-text-muted)", fontSize: 11, fontWeight: 600 }}>—</span>;
    }
    const color = score > 55 ? "var(--color-ec-profit)" : score < 45 ? "var(--color-ec-loss)" : "var(--color-ec-text-muted)";
    const label = score > 55 ? "Bull" : score < 45 ? "Bear" : "Neut";
    return (
        <span style={{ color, fontFamily: "'General Sans', sans-serif", fontSize: 12, fontWeight: 700 }}>
            {score}% <span style={{ fontSize: 9, fontWeight: 600, textTransform: "uppercase" }}>{label}</span>
        </span>
    );
}

const TH: React.CSSProperties = {
    padding: "10px 12px",
    textAlign: "left",
    fontFamily: "'General Sans', sans-serif",
    fontSize: 9,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "1px",
    color: "var(--color-ec-text-muted)",
    borderBottom: "1px solid var(--color-ec-border)",
    position: "sticky",
    top: 0,
    background: "var(--color-ec-bg-base)",
    zIndex: 1,
};

const TD: React.CSSProperties = {
    padding: "11px 12px",
    fontFamily: "'General Sans', sans-serif",
    fontSize: 13,
    fontWeight: 600,
    color: "var(--color-ec-text-primary)",
    borderBottom: "0.5px solid color-mix(in srgb, var(--color-ec-border) 35%, transparent)",
};

export function RadarMomentum({ onSelectTicker }: { onSelectTicker?: (ticker: string) => void }) {
    const [rows, setRows] = useState<SocialTrendingItem[]>([]);
    const [state, setState] = useState<"loading" | "empty" | "error" | "success">("loading");

    const load = () => {
        let cancelled = false;
        setState("loading");
        getSocialTrending()
            .then((data) => {
                if (cancelled) return;
                if (!data || data.length === 0) {
                    setRows([]);
                    setState("empty");
                } else {
                    setRows(data);
                    setState("success");
                }
            })
            .catch(() => { if (!cancelled) setState("error"); });
        return () => { cancelled = true; };
    };

    useEffect(() => load(), []);

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
            {/* Banner del filtro por defecto */}
            <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "10px 24px", flexShrink: 0,
                borderBottom: "1px solid var(--color-ec-border)",
                background: "var(--color-ec-bg-base)",
            }}>
                <Radar size={14} style={{ color: "var(--color-ec-copper)" }} />
                <span style={{ fontSize: 10, fontWeight: 700, color: "var(--color-ec-text-secondary)", textTransform: "uppercase", letterSpacing: "1px" }}>
                    Radar de Momentum
                </span>
                <span style={{ fontSize: 10, fontWeight: 600, color: "var(--color-ec-copper)", background: "rgba(216,122,61,0.1)", padding: "2px 8px", borderRadius: 4 }}>
                    Small Caps &lt; $2,000M
                </span>
            </div>

            <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }} className="custom-scrollbar">
                {state === "loading" && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 1, padding: 24 }}>
                        {Array.from({ length: 8 }).map((_, i) => (
                            <div key={i} className="animate-pulse" style={{
                                height: 44, borderRadius: 6,
                                background: "color-mix(in srgb, var(--color-ec-border) 20%, transparent)",
                            }} />
                        ))}
                    </div>
                )}

                {state === "empty" && (
                    <div style={{
                        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                        gap: 10, height: "100%", minHeight: 240, color: "var(--color-ec-text-muted)",
                    }}>
                        <Radar size={30} style={{ opacity: 0.5 }} />
                        <span style={{ fontSize: 12, fontWeight: 500, textAlign: "center", maxWidth: 320 }}>
                            Sin small caps con tracción social inusual ahora mismo.
                        </span>
                    </div>
                )}

                {state === "error" && (
                    <div style={{
                        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                        gap: 12, height: "100%", minHeight: 240,
                    }}>
                        <AlertTriangle size={26} style={{ color: "var(--color-ec-loss)" }} />
                        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-ec-text-secondary)" }}>
                            No se pudo cargar el radar.
                        </span>
                        <button
                            onClick={load}
                            style={{
                                display: "flex", alignItems: "center", gap: 6,
                                background: "var(--color-ec-bg-surface)", border: "0.5px solid var(--color-ec-border)",
                                borderRadius: 5, padding: "7px 13px", fontSize: 11, fontWeight: 600,
                                textTransform: "uppercase", letterSpacing: "0.5px",
                                color: "var(--color-ec-text-secondary)", cursor: "pointer",
                            }}
                            className="hover:text-[var(--color-ec-text-primary)]"
                        >
                            <RotateCw size={12} /> Reintentar
                        </button>
                    </div>
                )}

                {state === "success" && (
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                            <tr>
                                <th style={TH}>Ticker</th>
                                <th style={TH}>Compañía</th>
                                <th style={{ ...TH, textAlign: "right" }}>Cap. Mercado</th>
                                <th style={{ ...TH, textAlign: "right" }}>Vol. Diario</th>
                                <th style={{ ...TH, textAlign: "right" }}>Trend Score</th>
                                <th style={{ ...TH, textAlign: "right" }}>Sentimiento</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((r) => (
                                <tr
                                    key={r.symbol}
                                    onClick={() => onSelectTicker?.(r.symbol)}
                                    style={{ cursor: onSelectTicker ? "pointer" : "default", transition: "background 120ms ease" }}
                                    onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-ec-bg-surface)"; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                                >
                                    <td style={{ ...TD, fontWeight: 700, color: "var(--color-ec-text-high)" }}>{r.symbol}</td>
                                    <td style={{ ...TD, color: "var(--color-ec-text-secondary)", fontWeight: 500 }}>{r.name}</td>
                                    <td style={{ ...TD, textAlign: "right", color: "var(--color-ec-text-high)" }}>{fmtMarketCap(r.market_cap)}</td>
                                    <td style={{ ...TD, textAlign: "right", color: "var(--color-ec-text-secondary)" }}>{fmtVolume(r.daily_volume)}</td>
                                    <td style={{ ...TD, textAlign: "right", color: "var(--color-ec-copper-bright)" }}>
                                        {r.trending_score !== null ? r.trending_score.toFixed(1) : "-"}
                                    </td>
                                    <td style={{ ...TD, textAlign: "right" }}>
                                        <SentimentPill score={r.sentiment_score} />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
