"use client";

import React from "react";
import { ChevronDown, Activity, Dices, TrendingUp, Bird, Grid3x3 } from "lucide-react";
import { color, font, radius } from "@/components/ui/tokens";

export type ModuleId = "basico" | "montecarlo" | "wfo" | "blackswan" | "locates";

interface ModuleDef {
  id: ModuleId;
  label: string;
  blurb: string;
  Icon: React.ComponentType<{ style?: React.CSSProperties }>;
  /** Los modulos que re-ejecutan backtests se marcan: cuestan tiempo de maquina. */
  heavy?: boolean;
}

export const MODULES: ModuleDef[] = [
  {
    id: "basico",
    label: "Analisis basico",
    blurb: "Drawdown, rachas y test de estres sobre los trades reales",
    Icon: Activity,
  },
  {
    id: "montecarlo",
    label: "Monte Carlo Bootstrap",
    blurb: "Reordena el histórico miles de veces y mide el abanico de finales",
    Icon: Dices,
  },
  {
    id: "wfo",
    label: "Walk Forward",
    blurb: "Optimiza en pasado y valida en futuro, ventana a ventana",
    Icon: TrendingUp,
    heavy: true,
  },
  {
    id: "blackswan",
    label: "Margen de EV — Black Swan",
    blurb: "Colchon frente a eventos extremos",
    Icon: Bird,
  },
  {
    id: "locates",
    label: "Locates vs Slippage",
    blurb: "A partir de que coste deja de ganar la estrategia",
    Icon: Grid3x3,
    heavy: true,
  },
];

interface Props {
  active: ModuleId;
  onChange: (id: ModuleId) => void;
  /** Configuracion del modulo activo, inyectada por la pagina. */
  config: React.ReactNode;
  disabled?: boolean;
}

export default function ModuleRail({ active, onChange, config, disabled }: Props) {
  // Plegado independiente de "cual esta activo": se puede cerrar la
  // configuracion sin perder de vista los resultados de ese motor, y volver a
  // abrirla pulsando otra vez. Antes solo se podia cerrar abriendo otro.
  const [collapsed, setCollapsed] = React.useState(false);

  const handleClick = (id: ModuleId) => {
    if (id === active) {
      setCollapsed((c) => !c);
    } else {
      onChange(id);
      setCollapsed(false);
    }
  };

  return (
    <div
      style={{
        background: color.bgSurface,
        border: `0.5px solid ${color.border}`,
        borderRadius: radius.md,
        overflow: "hidden",
        position: "sticky",
        top: 12,
      }}
    >
      <div
        style={{
          padding: "10px 16px",
          borderBottom: `0.5px solid ${color.border}`,
          fontSize: 10,
          letterSpacing: "0.11em",
          textTransform: "uppercase",
          color: color.copper,
          fontFamily: font.sans,
        }}
      >
        Motores de robustez
      </div>

      {MODULES.map((m, i) => {
        const isActive = m.id === active;
        const isOpen = isActive && !collapsed;
        const { Icon } = m;
        return (
          <div key={m.id} style={{ borderTop: i === 0 ? "none" : `0.5px solid ${color.border}` }}>
            <button
              type="button"
              onClick={() => handleClick(m.id)}
              aria-expanded={isOpen}
              title={isActive ? (collapsed ? "Desplegar" : "Plegar") : undefined}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "11px 14px",
                background: isActive ? color.bgElevated : "transparent",
                border: "none",
                borderLeft: `2px solid ${isActive ? color.copper : "transparent"}`,
                cursor: "pointer",
                textAlign: "left",
                transition: "background 150ms",
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.background = color.surfaceHover;
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.background = "transparent";
              }}
            >
              <Icon
                style={{
                  width: 15,
                  height: 15,
                  flexShrink: 0,
                  marginTop: 1,
                  color: isActive ? color.copper : color.textMuted,
                  strokeWidth: 1.5,
                }}
              />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 12.5,
                    fontFamily: font.sans,
                    color: isActive ? color.textHigh : color.textPrimary,
                  }}
                >
                  {m.label}
                  {m.heavy && (
                    <span
                      style={{
                        fontSize: 8.5,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        color: color.warning,
                        border: `0.5px solid ${color.warning}`,
                        borderRadius: radius.xs,
                        padding: "0px 3px",
                        lineHeight: 1.5,
                      }}
                    >
                      pesado
                    </span>
                  )}
                </span>
                <span
                  style={{
                    display: "block",
                    fontSize: 10.5,
                    fontFamily: font.sans,
                    color: color.textMuted,
                    marginTop: 2,
                    lineHeight: 1.45,
                  }}
                >
                  {m.blurb}
                </span>
              </span>
              <ChevronDown
                style={{
                  width: 13,
                  height: 13,
                  flexShrink: 0,
                  marginTop: 2,
                  color: color.textMuted,
                  transform: isOpen ? "rotate(180deg)" : "none",
                  transition: "transform 150ms",
                }}
              />
            </button>

            {isOpen && (
              <div
                style={{
                  padding: "14px 14px 16px",
                  background: color.bgBase,
                  borderTop: `0.5px solid ${color.border}`,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                  opacity: disabled ? 0.45 : 1,
                  pointerEvents: disabled ? "none" : "auto",
                }}
              >
                {config}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
