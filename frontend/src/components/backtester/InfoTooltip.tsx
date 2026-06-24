"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";

interface InfoTooltipProps {
  text: string;
  position?: "left" | "right" | "top" | "bottom" | "top-left" | "top-right" | "top-right-aligned";
  style?: React.CSSProperties;
  width?: string | number;
  title?: string;
}

export default function InfoTooltip({ text, position = "top", style, width, title }: InfoTooltipProps) {
  const [hovered, setHovered] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0, width: 0, height: 0 });
  const iconRef = useRef<HTMLSpanElement>(null);

  const updateCoords = () => {
    if (iconRef.current) {
      const rect = iconRef.current.getBoundingClientRect();
      setCoords({
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      });
    }
  };

  const handleMouseEnter = () => {
    updateCoords();
    setHovered(true);
  };

  // Recalculate coordinates if window is resized or scrolled (in capture phase to catch container scrolling)
  useEffect(() => {
    if (hovered) {
      window.addEventListener("scroll", updateCoords, { capture: true, passive: true });
      window.addEventListener("resize", updateCoords);
      return () => {
        window.removeEventListener("scroll", updateCoords, { capture: true });
        window.removeEventListener("resize", updateCoords);
      };
    }
  }, [hovered]);

  const getFixedStyles = () => {
    switch (position) {
      case "top-right-aligned":
        return {
          top: coords.top,
          left: coords.left,
          transform: "translate(0, -100%) translateY(-6px)",
        };
      case "left":
        return {
          top: coords.top,
          left: coords.left,
          transform: "translate(0, -100%) translateY(-6px)",
        };
      case "right":
        return {
          top: coords.top,
          left: coords.left + coords.width,
          transform: "translate(-100%, -100%) translateY(-6px)",
        };
      case "top-left":
        return {
          top: coords.top,
          left: coords.left + coords.width / 2,
          transform: "translate(-75%, -100%) translateY(-6px)",
        };
      case "top-right":
        return {
          top: coords.top,
          left: coords.left + coords.width / 2,
          transform: "translate(-25%, -100%) translateY(-6px)",
        };
      case "bottom":
        return {
          top: coords.top + coords.height,
          left: coords.left + coords.width / 2,
          transform: "translate(-50%, 0) translateY(6px)",
        };
      case "top":
      default:
        return {
          top: coords.top,
          left: coords.left + coords.width / 2,
          transform: "translate(-50%, -100%) translateY(-6px)",
        };
    }
  };

  return (
    <span
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setHovered(false)}
      ref={iconRef}
      style={{
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
      {hovered && typeof document !== "undefined" && createPortal(
        <span
          style={{
            position: "fixed",
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
            zIndex: 100005,
            pointerEvents: "none",
            textTransform: "none",
            letterSpacing: "normal",
            whiteSpace: "pre-line",
            ...getFixedStyles(),
          }}
        >
          {title && (
            <div style={{ color: "var(--color-ec-copper)", fontWeight: 700, marginBottom: "4px", fontSize: "11px" }}>
              {title}
            </div>
          )}
          {text}
        </span>,
        document.body
      )}
    </span>
  );
}
