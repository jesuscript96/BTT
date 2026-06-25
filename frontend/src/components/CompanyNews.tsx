"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Newspaper, AlertTriangle, RotateCw, ExternalLink } from "lucide-react";
import { getTickerFinvizNews, ApiError } from "@/lib/api";

interface NewsItem {
    title: string;
    url: string;
    source: string;
    published: string;
    description: string;
    image_url?: string;
    sentiment?: string | null;
    date?: string;
    time?: string;
}

function SentimentBadge({ sentiment }: { sentiment?: string | null }) {
    if (!sentiment) return null;
    const s = sentiment.toLowerCase();
    const map: Record<string, { bg: string; fg: string; label: string }> = {
        positive: { bg: "rgba(74, 157, 127, 0.18)", fg: "var(--color-ec-profit)", label: "BULLISH" },
        bullish:  { bg: "rgba(74, 157, 127, 0.18)", fg: "var(--color-ec-profit)", label: "BULLISH" },
        negative: { bg: "rgba(201, 77, 63, 0.18)", fg: "var(--color-ec-loss)", label: "BEARISH" },
        bearish:  { bg: "rgba(201, 77, 63, 0.18)", fg: "var(--color-ec-loss)", label: "BEARISH" },
        neutral:  { bg: "rgba(106, 109, 114, 0.18)", fg: "var(--color-ec-text-muted)", label: "NEUTRAL" },
    };
    const cfg = map[s];
    if (!cfg) return null;
    return (
        <span style={{
            fontFamily: "var(--ec-sans, 'General Sans', sans-serif)",
            fontSize: 8,
            fontWeight: 700,
            padding: "2px 6px",
            borderRadius: 3,
            backgroundColor: cfg.bg,
            color: cfg.fg,
            letterSpacing: "0.5px",
            display: "inline-block",
        }}>
            {cfg.label}
        </span>
    );
}

function formatDate(dateStr?: string, publishedIso?: string): string {
    if (dateStr) {
        // Try parsing YYYY-MM-DD
        const parts = dateStr.split("-");
        if (parts.length === 3) {
            const date = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
            if (!isNaN(date.getTime())) {
                return date.toLocaleDateString("es-ES", {
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                });
            }
        }
    }
    if (publishedIso) {
        const date = new Date(publishedIso);
        if (!isNaN(date.getTime())) {
            return date.toLocaleDateString("es-ES", {
                day: "numeric",
                month: "short",
                year: "numeric",
            });
        }
    }
    return dateStr || "";
}

export function CompanyNews({ symbol }: { symbol?: string }) {
    const [news, setNews] = useState<NewsItem[]>([]);
    const [state, setState] = useState<"loading" | "empty" | "error" | "success">("loading");

    const load = useCallback(() => {
        if (!symbol) {
            setState("empty");
            return () => {};
        }
        let cancelled = false;
        setState("loading");
        getTickerFinvizNews(symbol)
            .then((res) => {
                if (cancelled) return;
                const payload = res as NewsItem[] | { news?: NewsItem[] };
                const items = Array.isArray(payload) ? payload : (payload.news ?? []);
                
                if (!items || items.length === 0) {
                    setNews([]);
                    setState("empty");
                } else {
                    setNews(items);
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

    // ── Loading: Skeletons ──
    if (state === "loading") {
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="animate-pulse" style={{
                        height: 100,
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
                <Newspaper size={28} style={{ opacity: 0.6 }} />
                <span style={{ fontSize: 12, fontWeight: 500, textAlign: "center" }}>
                    No se encontraron noticias recientes para {symbol}.
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
                    No se pudieron cargar las noticias.
                </span>
                <button
                    onClick={load}
                    style={{
                        display: "flex", alignItems: "center", gap: 6,
                        background: "var(--color-ec-bg-surface)",
                        border: "0.5px solid var(--color-ec-border)",
                        borderRadius: 5, padding: "7px 13px",
                        fontFamily: "var(--ec-sans, 'General Sans', sans-serif)", fontSize: 11, fontWeight: 600,
                        textTransform: "uppercase", letterSpacing: "0.5px",
                        color: "var(--color-ec-text-secondary)", cursor: "pointer",
                    }}
                    className="hover:text-[var(--color-ec-text-primary)]"
                >
                    <RotateCw size={12} /> Reintentar
                </button>
            </div>
        );
    }

    // ── Success ──
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {news.map((item, idx) => {
                const itemDate = formatDate(item.date, item.published);
                return (
                    <a
                        key={idx}
                        href={item.url || item.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                            display: "flex",
                            gap: 16,
                            background: "var(--color-ec-bg-surface)",
                            border: "0.5px solid var(--color-ec-border)",
                            borderRadius: 7,
                            padding: "16px 18px",
                            textDecoration: "none",
                            transition: "all 150ms ease",
                            cursor: "pointer",
                        }}
                        className="hover:bg-[var(--color-ec-bg-elevated)] hover:border-[var(--color-ec-copper)]"
                    >
                        {/* News details */}
                        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                <span style={{
                                    fontFamily: "var(--ec-sans, 'General Sans', sans-serif)",
                                    fontSize: 9,
                                    fontWeight: 700,
                                    color: "var(--color-ec-copper)",
                                    textTransform: "uppercase",
                                    letterSpacing: "2.5px",
                                }}>
                                    {item.source}
                                </span>
                                {item.time && (
                                    <span style={{
                                        fontFamily: "var(--ec-sans, 'General Sans', sans-serif)",
                                        fontSize: 10,
                                        fontWeight: 500,
                                        color: "var(--color-ec-text-muted)",
                                    }}>
                                        • {item.time}
                                    </span>
                                )}
                                <span style={{
                                    fontFamily: "var(--ec-sans, 'General Sans', sans-serif)",
                                    fontSize: 10,
                                    fontWeight: 500,
                                    color: "var(--color-ec-text-muted)",
                                    marginLeft: item.time ? 0 : "auto",
                                }}>
                                    {itemDate}
                                </span>
                                {item.sentiment && (
                                    <div style={{ marginLeft: "auto" }}>
                                        <SentimentBadge sentiment={item.sentiment} />
                                    </div>
                                )}
                            </div>

                            <h4 style={{
                                fontFamily: "var(--ec-serif, 'Fraunces', serif)",
                                fontSize: 16,
                                fontWeight: 500,
                                color: "var(--color-ec-text-high)",
                                margin: 0,
                                lineHeight: 1.4,
                                letterSpacing: "-0.2px",
                            }} className="hover:text-[var(--color-ec-copper-bright)]">
                                {item.title}
                            </h4>

                            <p style={{
                                fontFamily: "var(--ec-sans, 'General Sans', sans-serif)",
                                fontSize: 12,
                                fontWeight: 400,
                                color: "var(--color-ec-text-secondary)",
                                margin: 0,
                                lineHeight: 1.5,
                                display: "-webkit-box",
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: "vertical",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                            }}>
                                {item.description}
                            </p>
                        </div>

                        {/* Optional thumbnail image */}
                        {item.image_url && (
                            <div style={{
                                width: 80,
                                height: 80,
                                borderRadius: 6,
                                overflow: "hidden",
                                flexShrink: 0,
                                border: "0.5px solid var(--color-ec-border)",
                                background: "var(--color-ec-bg-sidebar)",
                            }}>
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                    src={item.image_url}
                                    alt={item.title}
                                    style={{
                                        width: "100%",
                                        height: "100%",
                                        objectFit: "cover",
                                    }}
                                />
                            </div>
                        )}
                    </a>
                );
            })}
        </div>
    );
}
