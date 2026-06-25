"use client";

import React, { useState } from "react";
import { Flame, Search, MousePointerClick } from "lucide-react";
import { RadarMomentum } from "./RadarMomentum";
import { SentimentGauge, WhyTrendingBox } from "./SentimentGauge";
import { StocktwitsStream } from "./StocktwitsStream";

// Página dedicada "Market Sentiment" — agrega TODO lo de la integración
// Stocktwits en un solo lugar, sin mezclarse con Ticker Analysis ni el Screener:
//   · Izquierda: Radar de Momentum (small caps en tendencia social).
//   · Derecha: detalle del ticker seleccionado → Sentiment Gauge, Why Trending
//     y Zona de Debate. El ticker se elige clicando una fila del radar o
//     buscándolo en la cabecera.
export default function MarketSentiment() {
    const [selected, setSelected] = useState<string>("");
    const [searchText, setSearchText] = useState<string>("");

    const submit = (raw: string) => {
        const t = raw.toUpperCase().trim();
        if (t) setSelected(t);
    };

    return (
        <div style={{
            display: "flex",
            flexDirection: "column",
            height: "100dvh",
            overflow: "hidden",
            background: "var(--color-ec-bg-base)",
            fontFamily: "'General Sans', sans-serif",
            color: "var(--color-ec-text-primary)",
        }}>
            {/* ── Header ── */}
            <header style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 16,
                padding: "14px 24px",
                borderBottom: "1px solid var(--color-ec-border)",
                flexShrink: 0,
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{
                        width: 34, height: 34, borderRadius: 8,
                        background: "rgba(216,122,61,0.12)",
                        border: "0.5px solid var(--color-ec-copper)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "var(--color-ec-copper)", flexShrink: 0,
                    }}>
                        <Flame size={18} strokeWidth={1.8} />
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                        <span style={{ fontSize: 8, fontWeight: 700, color: "var(--color-ec-copper)", textTransform: "uppercase", letterSpacing: "2px" }}>
                            Stocktwits · Social
                        </span>
                        <h1 style={{
                            fontFamily: "'Fraunces', serif",
                            fontSize: 22, fontWeight: 600,
                            color: "var(--color-ec-text-high)", margin: 0, letterSpacing: "-0.4px",
                        }}>
                            Market Sentiment
                        </h1>
                    </div>
                </div>

                {/* Buscador de ticker */}
                <div style={{
                    display: "flex", alignItems: "center", gap: 8,
                    background: "var(--color-ec-bg-sidebar)",
                    border: "1px solid var(--color-ec-border)",
                    borderRadius: 6, padding: "0 12px", height: 36, width: 240,
                    boxSizing: "border-box",
                }}>
                    <Search size={14} style={{ color: "var(--color-ec-text-muted)", flexShrink: 0 }} />
                    <input
                        type="text"
                        placeholder="Buscar ticker (ej. SOUN)..."
                        value={searchText}
                        onChange={(e) => setSearchText(e.target.value.toUpperCase())}
                        onKeyDown={(e) => { if (e.key === "Enter") submit((e.target as HTMLInputElement).value); }}
                        style={{
                            background: "transparent", border: "none", outline: "none",
                            fontFamily: "'General Sans', sans-serif", fontSize: 12, fontWeight: 500,
                            color: "var(--color-ec-text-primary)", width: "100%",
                        }}
                    />
                </div>
            </header>

            {/* ── Body: Radar | Detalle ── */}
            <div style={{ flex: 1, display: "flex", minHeight: 0, overflow: "hidden" }}>
                {/* Izquierda: Radar de Momentum */}
                <div style={{
                    flex: "1 1 52%", minWidth: 0,
                    borderRight: "1px solid var(--color-ec-border)",
                    display: "flex", flexDirection: "column", minHeight: 0,
                }}>
                    <RadarMomentum onSelectTicker={setSelected} />
                </div>

                {/* Derecha: detalle del ticker seleccionado */}
                <div style={{
                    flex: "1 1 48%", minWidth: 0,
                    overflowY: "auto", padding: 24,
                    display: "flex", flexDirection: "column", gap: 24,
                }} className="custom-scrollbar">
                    {!selected ? (
                        <div style={{
                            flex: 1, display: "flex", flexDirection: "column",
                            alignItems: "center", justifyContent: "center", gap: 12,
                            color: "var(--color-ec-text-muted)", textAlign: "center", padding: "0 24px",
                        }}>
                            <MousePointerClick size={30} style={{ opacity: 0.5 }} />
                            <span style={{ fontSize: 13, fontWeight: 500, maxWidth: 320, lineHeight: 1.5 }}>
                                Selecciona un ticker del radar o búscalo arriba para ver su sentimiento social, catalizador y debate.
                            </span>
                        </div>
                    ) : (
                        <>
                            {/* Ticker seleccionado */}
                            <div style={{ display: "flex", alignItems: "baseline", gap: 10, borderBottom: "1px solid var(--color-ec-border)", paddingBottom: 12 }}>
                                <h2 style={{
                                    fontFamily: "'Fraunces', serif", fontSize: 26, fontWeight: 600,
                                    color: "var(--color-ec-text-high)", margin: 0, letterSpacing: "-0.5px",
                                }}>{selected}</h2>
                                <span style={{ fontSize: 10, fontWeight: 600, color: "var(--color-ec-text-muted)", textTransform: "uppercase", letterSpacing: "1px" }}>
                                    Sentimiento social en vivo
                                </span>
                            </div>

                            {/* Gauge + Why Trending */}
                            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1.2fr)", gap: 16 }}>
                                <SentimentGauge symbol={selected} />
                                <WhyTrendingBox symbol={selected} />
                            </div>

                            {/* Debate */}
                            <div>
                                <h3 style={{
                                    fontFamily: "'General Sans', sans-serif", fontSize: 8, fontWeight: 700,
                                    color: "var(--color-ec-copper)", textTransform: "uppercase", letterSpacing: "1.5px",
                                    borderBottom: "1px solid var(--color-ec-border)", paddingBottom: 4, marginBottom: 16,
                                }}>Debate Stocktwits</h3>
                                <StocktwitsStream symbol={selected} />
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
