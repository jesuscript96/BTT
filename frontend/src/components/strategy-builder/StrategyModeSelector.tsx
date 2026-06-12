"use client";

import { useState } from "react";

interface Props {
  onSelectFree: () => void;
  onSelectWizard: () => void;
  onBack: () => void;
}

export default function StrategyModeSelector({ onSelectFree, onSelectWizard, onBack }: Props) {
  const [hoveredCard, setHoveredCard] = useState<"free" | "wizard" | null>(null);
  const [pressedCard, setPressedCard] = useState<"free" | "wizard" | null>(null);

  const cardBase = (id: "free" | "wizard"): React.CSSProperties => ({
    position: "relative",
    display: "flex",
    alignItems: "flex-start",
    gap: 16,
    padding: "22px 24px",
    borderRadius: 10,
    border: hoveredCard === id
      ? "1px solid rgba(216, 122, 61, 0.5)"
      : "1px solid var(--color-ec-border)",
    backgroundColor: hoveredCard === id
      ? "rgba(216, 122, 61, 0.04)"
      : "var(--color-ec-bg-surface)",
    cursor: "pointer",
    textAlign: "left" as const,
    transition: "all 280ms cubic-bezier(0.22, 1, 0.36, 1)",
    transform: pressedCard === id
      ? "scale(0.98)"
      : hoveredCard === id
        ? "translateY(-2px)"
        : "translateY(0)",
    boxShadow: hoveredCard === id
      ? "0 8px 32px rgba(0, 0, 0, 0.25), 0 0 0 1px rgba(216, 122, 61, 0.08)"
      : "0 1px 4px rgba(0, 0, 0, 0.08)",
    overflow: "hidden",
    outline: "none",
  });

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      overflow: "hidden",
    }}>
      {/* Header — same style as InlineStrategyBuilder */}
      <div style={{
        padding: "12px 16px",
        borderBottom: "0.5px solid var(--color-ec-border)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        backgroundColor: "var(--color-ec-bg-base)",
        flexShrink: 0,
      }}>
        <button
          onClick={onBack}
          style={{
            background: "none",
            border: "none",
            color: "var(--color-ec-text-muted)",
            cursor: "pointer",
            fontSize: 18,
            lineHeight: 1,
            padding: "0 4px",
          }}
        >
          ←
        </button>
        <span style={{
          fontFamily: "var(--color-ec-serif)",
          fontSize: 14,
          fontWeight: 600,
          color: "var(--color-ec-text-high)",
          letterSpacing: "-0.2px",
        }}>
          Nueva Estrategia
        </span>
      </div>

      {/* Content */}
      <div style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "32px 28px",
        gap: 0,
      }}>
        {/* Title block */}
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <h2 style={{
            fontFamily: "var(--color-ec-serif)",
            fontSize: 17,
            fontWeight: 600,
            color: "var(--color-ec-text-high)",
            margin: "0 0 6px 0",
            letterSpacing: "-0.3px",
          }}>
            ¿Cómo deseas configurar la estrategia?
          </h2>
          <p style={{
            fontFamily: "var(--color-ec-sans)",
            fontSize: 11,
            color: "var(--color-ec-text-muted)",
            margin: 0,
            lineHeight: 1.5,
            opacity: 0.7,
          }}>
            Elige el modo de creación que mejor se adapte a ti
          </p>
        </div>

        {/* Cards container */}
        <div style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          width: "100%",
          maxWidth: 440,
        }}>
          {/* ── Card: Config. guiada (Wizard) ── */}
          <button
            onClick={onSelectWizard}
            onMouseEnter={() => setHoveredCard("wizard")}
            onMouseLeave={() => { setHoveredCard(null); setPressedCard(null); }}
            onMouseDown={() => setPressedCard("wizard")}
            onMouseUp={() => setPressedCard(null)}
            style={cardBase("wizard")}
          >
            {/* Top accent bar */}
            <div style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: hoveredCard === "wizard" ? "100%" : "0%",
              height: 1.5,
              background: "linear-gradient(90deg, var(--color-ec-copper), rgba(216, 122, 61, 0.3))",
              transition: "width 400ms cubic-bezier(0.22, 1, 0.36, 1)",
            }} />

            {/* Icon container */}
            <div style={{
              width: 42,
              height: 42,
              borderRadius: 9,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              backgroundColor: hoveredCard === "wizard"
                ? "rgba(216, 122, 61, 0.1)"
                 : "var(--color-ec-bg-elevated)",
              border: hoveredCard === "wizard"
                ? "1px solid rgba(216, 122, 61, 0.2)"
                : "1px solid var(--color-ec-border)",
              transition: "all 280ms ease",
            }}>
              {/* Compass/Route SVG */}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={hoveredCard === "wizard" ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transition: "stroke 280ms ease" }}>
                <circle cx="12" cy="12" r="10" />
                <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" fill={hoveredCard === "wizard" ? "rgba(216, 122, 61, 0.3)" : "rgba(255,255,255,0.06)"} style={{ transition: "fill 280ms ease" }} />
              </svg>
            </div>

            {/* Text block */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 13,
                fontWeight: 700,
                color: hoveredCard === "wizard" ? "var(--color-ec-copper)" : "var(--color-ec-text-high)",
                marginBottom: 5,
                transition: "color 280ms ease",
              }}>
                Config. guiada (Wizard)
              </div>
              <div style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 10.5,
                color: "var(--color-ec-text-muted)",
                lineHeight: 1.55,
              }}>
                Un asistente paso a paso que te guía por cada sección de la estrategia. Ideal si prefieres ir con calma.
              </div>
              <div style={{
                display: "inline-flex",
                alignItems: "center",
                marginTop: 10,
                padding: "2px 7px",
                borderRadius: 3,
                backgroundColor: "rgba(216, 122, 61, 0.06)",
                border: "0.5px solid rgba(216, 122, 61, 0.18)",
              }}>
                <span style={{
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 8.5,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--color-ec-copper)",
                }}>
                  Recomendado
                </span>
              </div>
            </div>

            {/* Arrow */}
            <div style={{
              display: "flex",
              alignItems: "center",
              fontSize: 13,
              color: hoveredCard === "wizard" ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)",
              transition: "all 280ms ease",
              transform: hoveredCard === "wizard" ? "translateX(3px)" : "translateX(0)",
              alignSelf: "center",
              opacity: hoveredCard === "wizard" ? 1 : 0.4,
            }}>
              →
            </div>
          </button>

          {/* ── Card: Config. libre ── */}
          <button
            onClick={onSelectFree}
            onMouseEnter={() => setHoveredCard("free")}
            onMouseLeave={() => { setHoveredCard(null); setPressedCard(null); }}
            onMouseDown={() => setPressedCard("free")}
            onMouseUp={() => setPressedCard(null)}
            style={cardBase("free")}
          >
            {/* Top accent bar */}
            <div style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: hoveredCard === "free" ? "100%" : "0%",
              height: 1.5,
              background: "linear-gradient(90deg, var(--color-ec-copper), rgba(216, 122, 61, 0.3))",
              transition: "width 400ms cubic-bezier(0.22, 1, 0.36, 1)",
            }} />

            {/* Icon container */}
            <div style={{
              width: 42,
              height: 42,
              borderRadius: 9,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              backgroundColor: hoveredCard === "free"
                ? "rgba(216, 122, 61, 0.1)"
                : "var(--color-ec-bg-elevated)",
              border: hoveredCard === "free"
                ? "1px solid rgba(216, 122, 61, 0.2)"
                : "1px solid var(--color-ec-border)",
              transition: "all 280ms ease",
            }}>
              {/* Lightning bolt SVG */}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={hoveredCard === "free" ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transition: "stroke 280ms ease" }}>
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            </div>

            {/* Text block */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 13,
                fontWeight: 700,
                color: hoveredCard === "free" ? "var(--color-ec-copper)" : "var(--color-ec-text-high)",
                marginBottom: 5,
                transition: "color 280ms ease",
              }}>
                Config. libre
              </div>
              <div style={{
                fontFamily: "var(--color-ec-sans)",
                fontSize: 10.5,
                color: "var(--color-ec-text-muted)",
                lineHeight: 1.55,
              }}>
                Acceso total a todos los parámetros. Configura entradas, salidas y riesgo sin restricciones.
              </div>
              <div style={{
                display: "inline-flex",
                alignItems: "center",
                marginTop: 10,
                padding: "2px 7px",
                borderRadius: 3,
                backgroundColor: "rgba(255, 255, 255, 0.03)",
                border: "0.5px solid rgba(255, 255, 255, 0.08)",
              }}>
                <span style={{
                  fontFamily: "var(--color-ec-sans)",
                  fontSize: 8.5,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--color-ec-text-muted)",
                  opacity: 0.7,
                }}>
                  Avanzado
                </span>
              </div>
            </div>

            {/* Arrow */}
            <div style={{
              display: "flex",
              alignItems: "center",
              fontSize: 13,
              color: hoveredCard === "free" ? "var(--color-ec-copper)" : "var(--color-ec-text-muted)",
              transition: "all 280ms ease",
              transform: hoveredCard === "free" ? "translateX(3px)" : "translateX(0)",
              alignSelf: "center",
              opacity: hoveredCard === "free" ? 1 : 0.4,
            }}>
              →
            </div>
          </button>
        </div>

        {/* Footer */}
        <p style={{
          fontFamily: "var(--color-ec-sans)",
          fontSize: 9,
          color: "var(--color-ec-text-muted)",
          marginTop: 24,
          textAlign: "center",
          opacity: 0.45,
          lineHeight: 1.6,
        }}>
          Ambos modos generan la misma estrategia.
          <br />
          Solo cambia la forma de configurarla.
        </p>
      </div>
    </div>
  );
}
