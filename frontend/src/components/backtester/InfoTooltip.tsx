"use client";

import { useState } from "react";

interface InfoTooltipProps {
  text: string;
  position?: "left" | "right" | "top" | "bottom" | "top-left" | "top-right" | "top-right-aligned";
  style?: React.CSSProperties;
  width?: string | number;
  title?: string;
}

export default function InfoTooltip({ text, position = "top", style, width, title }: InfoTooltipProps) {
  const [hovered, setHovered] = useState(false);

  const getPositionStyles = () => {
    switch (position) {
      case "top-right-aligned":
        return {
          bottom: "110%",
          left: 0,
          right: "auto",
          transform: "none",
        };
      case "left":
        return {
          bottom: "140%",
          left: 0,
          right: "auto",
          transform: "none",
        };
      case "right":
        return {
          bottom: "140%",
          left: "auto",
          right: 0,
          transform: "none",
        };
      case "top-left":
        return {
          bottom: "140%",
          left: "50%",
          right: "auto",
          transform: "translateX(-75%)",
        };
      case "top-right":
        return {
          bottom: "140%",
          left: "50%",
          right: "auto",
          transform: "translateX(-25%)",
        };
      case "bottom":
        return {
          top: "140%",
          bottom: "auto",
          left: "50%",
          right: "auto",
          transform: "translateX(-50%)",
        };
      case "top":
      default:
        return {
          bottom: "140%",
          left: "50%",
          right: "auto",
          transform: "translateX(-50%)",
        };
    }
  };

  return (
    <span
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        ...style
      }}
    >
      <span
        style={{
          cursor: "help",
          opacity: 0.6,
          fontSize: "8px",
          color: "var(--color-ec-text-secondary)",
          userSelect: "none",
          marginLeft: "4px",
          display: "inline-block",
        }}
      >
        (?)
      </span>
      {hovered && (
        <span
          style={{
            position: "absolute",
            width: width ?? "240px",
            backgroundColor: "var(--color-ec-bg-elevated)",
            border: "0.5px solid var(--color-ec-border)",
            color: "var(--color-ec-text-primary)",
            textAlign: "left",
            padding: "8px 10px",
            borderRadius: "6px",
            fontFamily: "var(--font-sans), sans-serif",
            fontSize: "11px",
            fontWeight: 500,
            lineHeight: "1.4",
            boxShadow: "0 4px 20px rgba(0, 0, 0, 0.45)",
            zIndex: 99999,
            pointerEvents: "none",
            textTransform: "none",
            letterSpacing: "normal",
            whiteSpace: "pre-line",
            ...getPositionStyles(),
          }}
        >
          {title && (
            <div style={{ color: "var(--color-ec-copper)", fontWeight: 700, marginBottom: "4px", fontSize: "11px" }}>
              {title}
            </div>
          )}
          {text}
        </span>
      )}
    </span>
  );
}
