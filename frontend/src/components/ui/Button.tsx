"use client";

import React, { forwardRef, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { color, font, motion } from "./tokens";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  loading?: boolean;
  fullWidth?: boolean;
  /** Brand/auth micro-style: uppercase + tracked. Off by default (app style). */
  uppercase?: boolean;
}

const SIZES: Record<ButtonSize, CSSProperties> = {
  sm: { padding: "6px 10px", fontSize: 12 },
  md: { padding: "8px 14px", fontSize: 13 },
  lg: { padding: "10px 18px", fontSize: 14 },
};

// [bg, fg, border, hoverBg] — hover handled via direct DOM mutation (no re-render),
// matching the codebase idiom. Primary text is copper-text (#1A0A00), NEVER white.
const VARIANTS: Record<ButtonVariant, { bg: string; fg: string; border: string; hoverBg: string; hoverFg?: string }> = {
  primary:   { bg: color.copper, fg: color.copperText, border: "none", hoverBg: color.copperBright },
  secondary: { bg: color.bgSurface, fg: color.textSecondary, border: `0.5px solid ${color.border}`, hoverBg: color.bgElevated, hoverFg: color.textPrimary },
  ghost:     { bg: "transparent", fg: color.textSecondary, border: `0.5px solid ${color.border}`, hoverBg: color.bgElevated, hoverFg: color.textPrimary },
  danger:    { bg: "transparent", fg: color.loss, border: `0.5px solid ${color.border}`, hoverBg: "rgba(201,77,63,0.10)" },
  subtle:    { bg: color.bgElevated, fg: color.textPrimary, border: "none", hoverBg: color.surfaceHover },
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", leftIcon, rightIcon, loading, fullWidth, uppercase, disabled, children, style, onMouseEnter, onMouseLeave, ...rest },
  ref,
) {
  const v = VARIANTS[variant];
  const isDisabled = disabled || loading;

  return (
    <button
      ref={ref}
      disabled={isDisabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        width: fullWidth ? "100%" : undefined,
        borderRadius: "var(--ec-radius-sm)",
        fontFamily: font.sans,
        fontWeight: uppercase ? 700 : 600,
        letterSpacing: uppercase ? "1.2px" : undefined,
        textTransform: uppercase ? "uppercase" : undefined,
        cursor: isDisabled ? "not-allowed" : "pointer",
        opacity: isDisabled ? 0.5 : 1,
        background: v.bg,
        color: v.fg,
        border: v.border,
        transition: `background ${motion.base} ${motion.ease}, color ${motion.base} ${motion.ease}, opacity ${motion.base} ${motion.ease}`,
        ...SIZES[size],
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!isDisabled) {
          e.currentTarget.style.background = v.hoverBg;
          if (v.hoverFg) e.currentTarget.style.color = v.hoverFg;
        }
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        if (!isDisabled) {
          e.currentTarget.style.background = v.bg;
          e.currentTarget.style.color = v.fg;
        }
        onMouseLeave?.(e);
      }}
      {...rest}
    >
      {loading ? (
        <Loader2 size={size === "lg" ? 16 : 14} style={{ animation: "ec-spin 0.7s linear infinite" }} />
      ) : (
        leftIcon
      )}
      {children}
      {!loading && rightIcon}
    </button>
  );
});

/** Square icon-only button. Matches secondary styling; 32×32 default. */
interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  dimension?: number;
  label: string; // required for a11y
}
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { variant = "ghost", dimension = 32, label, children, style, disabled, onMouseEnter, onMouseLeave, ...rest },
  ref,
) {
  const v = VARIANTS[variant];
  return (
    <button
      ref={ref}
      aria-label={label}
      title={label}
      disabled={disabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: dimension,
        height: dimension,
        borderRadius: "var(--ec-radius-sm)",
        background: v.bg,
        color: v.fg,
        border: v.border,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: `background ${motion.base} ${motion.ease}, color ${motion.base} ${motion.ease}`,
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!disabled) {
          e.currentTarget.style.background = v.hoverBg;
          if (v.hoverFg) e.currentTarget.style.color = v.hoverFg;
        }
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        if (!disabled) {
          e.currentTarget.style.background = v.bg;
          e.currentTarget.style.color = v.fg;
        }
        onMouseLeave?.(e);
      }}
      {...rest}
    >
      {children}
    </button>
  );
});
