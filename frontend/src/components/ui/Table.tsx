"use client";

import React, { type ReactNode, type ThHTMLAttributes, type TdHTMLAttributes, type HTMLAttributes } from "react";
import { color, font } from "./tokens";

/** Bordered data table. Hairline row separators, uppercase header row. */
export function Table({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: font.sans, ...style }}>
      {children}
    </table>
  );
}

export function Th({ children, style, ...rest }: ThHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <th
      style={{
        textAlign: "left",
        padding: "8px 10px",
        fontSize: 9,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "1px",
        color: color.textMuted,
        borderBottom: `0.5px solid ${color.border}`,
        whiteSpace: "nowrap",
        ...style,
      }}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({ children, style, ...rest }: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <td style={{ padding: "8px 10px", fontSize: 13, color: color.textPrimary, borderBottom: `0.5px solid ${color.border}`, ...style }} {...rest}>
      {children}
    </td>
  );
}

/** Table row with optional hover highlight. */
export function Tr({ children, hoverable, style, ...rest }: HTMLAttributes<HTMLTableRowElement> & { children?: ReactNode; hoverable?: boolean }) {
  return (
    <tr
      style={style}
      onMouseEnter={hoverable ? (e) => { e.currentTarget.style.background = color.bgElevated; } : undefined}
      onMouseLeave={hoverable ? (e) => { e.currentTarget.style.background = "transparent"; } : undefined}
      {...rest}
    >
      {children}
    </tr>
  );
}
