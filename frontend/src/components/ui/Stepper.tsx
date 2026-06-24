"use client";

import React, { type ReactNode } from "react";
import { Check } from "lucide-react";
import { color, font, motion } from "./tokens";
import { Button } from "./Button";

export interface Step {
  key: string;
  label: string;
  /** Optional sub-label shown under the title on wider layouts. */
  hint?: string;
}

interface StepperProps {
  steps: Step[];
  current: number;
  completed?: Set<number>;
  onStepClick?: (idx: number) => void;
  /** Allow clicking ahead to not-yet-completed steps. Default false. */
  allowSkipAhead?: boolean;
}

/**
 * HORIZONTAL stepper — the canonical Edgecute wizard navigation. Steps ALWAYS
 * render on TOP of the content, never as a left/right rail. Numbered circles,
 * copper for active/complete, connector lines between nodes.
 */
export function Stepper({ steps, current, completed, onStepClick, allowSkipAhead }: StepperProps) {
  const done = completed ?? new Set<number>();
  return (
    <div style={{ display: "flex", alignItems: "flex-start", width: "100%" }}>
      {steps.map((step, idx) => {
        const isActive = idx === current;
        const isCompleted = done.has(idx) || idx < current;
        const isFuture = idx > current && !done.has(idx);
        const clickable = !!onStepClick && (allowSkipAhead || isCompleted || idx <= current);
        const isLast = idx === steps.length - 1;

        return (
          <React.Fragment key={step.key}>
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onStepClick?.(idx)}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 6,
                background: "transparent",
                border: "none",
                cursor: clickable ? "pointer" : "default",
                opacity: isFuture ? 0.5 : 1,
                padding: 0,
                flexShrink: 0,
                transition: `opacity ${motion.slow} ${motion.ease}`,
              }}
            >
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  background: isCompleted ? color.copper : isActive ? "rgba(216,122,61,0.15)" : "transparent",
                  border: isCompleted ? "none" : isActive ? `1.5px solid ${color.copper}` : `1px solid ${color.border}`,
                  transition: `all ${motion.slow} ${motion.ease}`,
                }}
              >
                {isCompleted ? (
                  <Check size={13} color={color.copperText} strokeWidth={3} />
                ) : (
                  <span style={{ fontFamily: font.sans, fontSize: 10, fontWeight: 700, color: isActive ? color.copper : color.textMuted }}>{idx + 1}</span>
                )}
              </div>
              <span
                style={{
                  fontFamily: font.sans,
                  fontSize: 11,
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? color.copper : isCompleted ? color.textHigh : color.textMuted,
                  whiteSpace: "nowrap",
                  transition: `color ${motion.base} ${motion.ease}`,
                }}
              >
                {step.label}
              </span>
            </button>

            {!isLast && (
              <div
                style={{
                  flex: 1,
                  height: 1.5,
                  marginTop: 12.5,
                  minWidth: 24,
                  background: idx < current ? color.copper : color.border,
                  transition: `background ${motion.slow} ${motion.ease}`,
                }}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

interface WizardProps {
  steps: Step[];
  current: number;
  completed?: Set<number>;
  onStepClick?: (idx: number) => void;
  onBack?: () => void;
  onNext?: () => void;
  /** Override the primary action label (default: "Siguiente" / "Finalizar"). */
  nextLabel?: ReactNode;
  backLabel?: ReactNode;
  nextDisabled?: boolean;
  nextLoading?: boolean;
  children: ReactNode;
  /** Extra footer content rendered on the left (e.g. validation hint). */
  footerLeft?: ReactNode;
}

/**
 * Full wizard shell with the canonical layout:
 *   ┌──────────────────────────────────┐
 *   │ Stepper (on TOP, horizontal)     │
 *   │ thin copper progress bar         │
 *   │ … step content …                 │
 *   │ [Back]              [Next →]      │
 *   └──────────────────────────────────┘
 * Never place the stepper in a side rail.
 */
export function Wizard({ steps, current, completed, onStepClick, onBack, onNext, nextLabel, backLabel = "Atrás", nextDisabled, nextLoading, children, footerLeft }: WizardProps) {
  const isLast = current === steps.length - 1;
  const pct = steps.length > 1 ? (current / (steps.length - 1)) * 100 : 100;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {/* Steps on top */}
      <div style={{ padding: "18px 24px 14px" }}>
        <Stepper steps={steps} current={current} completed={completed} onStepClick={onStepClick} />
      </div>

      {/* Progress bar */}
      <div style={{ height: 2, background: color.bgElevated, flexShrink: 0, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${color.copper}, rgba(216,122,61,0.6))`, borderRadius: "0 2px 2px 0", transition: `width ${motion.slower} ${motion.ease}` }} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 24 }}>{children}</div>

      {/* Footer nav */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "14px 24px", borderTop: `0.5px solid ${color.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Button variant="ghost" onClick={onBack} disabled={current === 0}>{backLabel}</Button>
          {footerLeft}
        </div>
        <Button variant="primary" onClick={onNext} disabled={nextDisabled} loading={nextLoading}>
          {nextLabel ?? (isLast ? "Finalizar" : "Siguiente")}
        </Button>
      </div>
    </div>
  );
}
