"use client";

import React, { useState, type ReactNode } from "react";
import { color, font, motion } from "./tokens";

type Side = "top" | "bottom" | "left" | "right";

interface TooltipProps {
  content: ReactNode;
  side?: Side;
  children: ReactNode;
  /** Max width of the bubble. */
  width?: number;
}

const POS: Record<Side, React.CSSProperties> = {
  top: { bottom: "calc(100% + 7px)", left: "50%", transform: "translateX(-50%)" },
  bottom: { top: "calc(100% + 7px)", left: "50%", transform: "translateX(-50%)" },
  left: { right: "calc(100% + 7px)", top: "50%", transform: "translateY(-50%)" },
  right: { left: "calc(100% + 7px)", top: "50%", transform: "translateY(-50%)" },
};

/** Hover/focus tooltip. Dark elevated bubble with hairline border. */
export function Tooltip({ content, side = "top", children, width = 220 }: TooltipProps) {
  const [show, setShow] = useState(false);
  return (
    <span
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            ...POS[side],
            zIndex: 130,
            maxWidth: width,
            width: "max-content",
            background: color.bgElevated,
            border: `0.5px solid ${color.border}`,
            borderRadius: "var(--ec-radius-md)",
            boxShadow: "var(--ec-shadow-md)",
            padding: "7px 10px",
            fontFamily: font.sans,
            fontSize: 11.5,
            fontWeight: 500,
            lineHeight: 1.45,
            color: color.textPrimary,
            pointerEvents: "none",
            animation: `ec-fade-in ${motion.fast} ${motion.ease}`,
          }}
        >
          {content}
        </span>
      )}
    </span>
  );
}
