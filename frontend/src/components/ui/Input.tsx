"use client";

import React, { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes, type SelectHTMLAttributes, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { color, font, motion } from "./tokens";

const fieldBase: React.CSSProperties = {
  width: "100%",
  background: color.bgSidebar, // inputs sit on the darkest surface (#101213)
  border: `0.5px solid ${color.border}`,
  borderRadius: "var(--ec-radius-sm)",
  padding: "8px 11px",
  fontFamily: font.sans,
  fontSize: 12,
  fontWeight: 400,
  color: color.textPrimary,
  outline: "none",
  transition: `border-color ${motion.base} ${motion.ease}, box-shadow ${motion.base} ${motion.ease}`,
};

function focusOn(el: HTMLElement) {
  el.style.borderColor = color.copper;
  el.style.boxShadow = "var(--ec-ring-copper)";
}
function focusOff(el: HTMLElement) {
  el.style.borderColor = color.border;
  el.style.boxShadow = "none";
}

interface FieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  htmlFor?: string;
  children: ReactNode;
  style?: React.CSSProperties;
}

/** Label + control + hint/error wrapper. Labels are 9px uppercase tracked. */
export function Field({ label, hint, error, required, htmlFor, children, style }: FieldProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, ...style }}>
      {label && (
        <label htmlFor={htmlFor} style={{ fontFamily: font.sans, fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "2px", color: color.textMuted }}>
          {label}
          {required && <span style={{ color: color.copper, marginLeft: 3 }}>*</span>}
        </label>
      )}
      {children}
      {error ? (
        <span style={{ fontFamily: font.sans, fontSize: 10, color: color.loss }}>{error}</span>
      ) : hint ? (
        <span style={{ fontFamily: font.sans, fontSize: 10, color: color.textMuted }}>{hint}</span>
      ) : null}
    </div>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ invalid, style, onFocus, onBlur, ...rest }, ref) {
  return (
    <input
      ref={ref}
      style={{ ...fieldBase, borderColor: invalid ? color.loss : color.border, ...style }}
      onFocus={(e) => { if (!invalid) focusOn(e.currentTarget); onFocus?.(e); }}
      onBlur={(e) => { if (!invalid) focusOff(e.currentTarget); onBlur?.(e); }}
      {...rest}
    />
  );
});

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ invalid, style, onFocus, onBlur, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      style={{ ...fieldBase, lineHeight: 1.5, resize: "vertical", borderColor: invalid ? color.loss : color.border, ...style }}
      onFocus={(e) => { if (!invalid) focusOn(e.currentTarget); onFocus?.(e); }}
      onBlur={(e) => { if (!invalid) focusOff(e.currentTarget); onBlur?.(e); }}
      {...rest}
    />
  );
});

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean;
}
/** Native styled select. For rich menus (icons, groups, search) use Dropdown. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select({ invalid, style, children, onFocus, onBlur, ...rest }, ref) {
  return (
    <div style={{ position: "relative", width: "100%" }}>
      <select
        ref={ref}
        style={{
          ...fieldBase,
          appearance: "none",
          WebkitAppearance: "none",
          paddingRight: 30,
          cursor: "pointer",
          borderColor: invalid ? color.loss : color.border,
          ...style,
        }}
        onFocus={(e) => { if (!invalid) focusOn(e.currentTarget); onFocus?.(e); }}
        onBlur={(e) => { if (!invalid) focusOff(e.currentTarget); onBlur?.(e); }}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown size={14} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: color.textSecondary }} />
    </div>
  );
});
