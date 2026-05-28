"use client";

import React, { useState } from "react";
import {
    LayoutDashboard,
    Play,
    Briefcase,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const ISOTIPO = (
    <svg width="24" height="24" viewBox="0 0 90 90" className="flex-shrink-0">
        <rect x="0" y="0" width="90" height="90" rx="8" fill="var(--color-ec-copper)" />
        <rect x="20" y="18" width="52" height="10" fill="#16181A" />
        <rect x="20" y="40" width="38" height="10" fill="#16181A" />
        <rect x="20" y="62" width="52" height="10" fill="#16181A" />
    </svg>
);

const wordmarkStyle: React.CSSProperties = {
    fontFamily: "'General Sans', sans-serif",
    fontWeight: 700,
    fontSize: 15,
    letterSpacing: "-0.6px",
    color: "var(--color-ec-text-high)",
};

export const Sidebar = () => {
    const pathname = usePathname();
    const [isHovered, setIsHovered] = useState(false);

    const isCollapsed = !isHovered;

    const isActive = (href: string) => {
        if (href === "/") return pathname === "/";
        return pathname.startsWith(href);
    };

    const linkActive = (href: string): React.CSSProperties =>
        isActive(href)
            ? { background: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-high)', fontWeight: 600 }
            : { background: 'transparent', color: 'var(--color-ec-text-secondary)', fontWeight: 500 };

    const linkBase = (collapsed: boolean): React.CSSProperties => ({
        display: 'flex',
        alignItems: 'center',
        gap: collapsed ? 0 : 10,
        padding: collapsed ? '7px 0' : '7px 8px',
        borderRadius: 5,
        fontSize: 13,
        fontWeight: 500,
        width: '100%',
        textDecoration: 'none',
        transition: 'background 150ms ease, color 150ms ease',
        justifyContent: collapsed ? 'center' : undefined,
        color: 'var(--color-ec-text-secondary)',
        cursor: 'pointer',
    });



    const labelFade = (collapsed: boolean): React.CSSProperties => ({
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        transition: 'all 150ms ease',
        width: collapsed ? 0 : undefined,
        opacity: collapsed ? 0 : 1,
        fontSize: 12,
        fontWeight: 500,
    });

    return (
        <aside
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            className="relative flex-shrink-0 flex flex-col"
            style={{
                width: isCollapsed ? 56 : 240,
                backgroundColor: "var(--color-ec-bg-sidebar)",
                borderRight: "0.5px solid var(--color-ec-border)",
                transition: "width 200ms ease",
                height: '100dvh',
                minHeight: 0,
                overflowY: 'hidden',
                overflowX: 'hidden',
            }}
        >
            {/* Header */}
            <div
                className="flex items-center"
                style={{
                    height: 52,
                    padding: '0 14px',
                    display: 'flex',
                    alignItems: 'center',
                    borderBottom: '0.5px solid var(--color-ec-border)',
                    justifyContent: isCollapsed ? "center" : "flex-start",
                    gap: 10,
                }}
            >
                {ISOTIPO}
                <span
                    style={{ ...wordmarkStyle, ...labelFade(isCollapsed) }}
                >
                    Edgecute
                </span>
            </div>

            {/* Navigation */}
            <nav style={{
                flex: 1,
                minHeight: 0,
                overflowY: 'auto',
                overflowX: 'hidden',
                padding: '12px 8px',
                gap: 2,
                display: 'flex',
                flexDirection: 'column',
                scrollbarWidth: 'none',
                msOverflowStyle: 'none',
            }}>
                {/* MENU label */}
                {!isCollapsed && (
                    <div style={{
                        fontFamily: "'General Sans', sans-serif",
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: 2,
                        color: "var(--color-ec-text-muted)",
                        padding: '0 8px',
                        marginBottom: 4,
                        marginTop: 0,
                    }}>
                        MENU
                    </div>
                )}

                {/* Market Analysis */}
                <Link
                    href="/"
                    style={{
                        ...linkBase(isCollapsed),
                        ...linkActive("/"),
                    }}
                >
                    <LayoutDashboard style={{ width: 18, height: 18, strokeWidth: 1.5, flexShrink: 0, color: 'inherit' }} />
                    <span style={labelFade(isCollapsed)}>Market Analysis</span>
                </Link>

                {/* Backtester */}
                <Link
                    href="/backtester"
                    style={{
                        ...linkBase(isCollapsed),
                        ...linkActive("/backtester"),
                    }}
                >
                    <Play style={{ width: 18, height: 18, strokeWidth: 1.5, flexShrink: 0, color: 'inherit' }} />
                    <span style={labelFade(isCollapsed)}>Backtester</span>
                </Link>

                {/* Separator */}
                <div style={{ height: '0.5px', background: 'var(--color-ec-border)', margin: '8px 8px' }} />

                {/* Baúl */}
                <Link
                    href="/database"
                    style={{
                        ...linkBase(isCollapsed),
                        ...linkActive("/database"),
                    }}
                >
                    <Briefcase style={{ width: 18, height: 18, strokeWidth: 1.5, flexShrink: 0, color: 'inherit' }} />
                    <span style={labelFade(isCollapsed)}>Baúl</span>
                </Link>
            </nav>

            {/* Bottom Profile */}
            <div
                style={{
                    flexShrink: 0,
                    padding: '10px 8px',
                    borderTop: '0.5px solid var(--color-ec-border)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                }}
            >
                <div style={{
                    width: 28,
                    height: 28,
                    borderRadius: '50%',
                    background: 'var(--color-ec-copper)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                }}>
                    <span style={{
                        fontFamily: "'General Sans', sans-serif",
        fontSize: 12,
                        fontWeight: 700,
                        color: 'var(--color-ec-copper-text)',
                    }}>T</span>
                </div>
                {!isCollapsed && (
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 12,
                            fontWeight: 600,
                            color: 'var(--color-ec-text-high)',
                            margin: 0,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                        }}>
                            Tito el Man
                        </p>
                        <p style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 9,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '1.5px',
                            color: 'var(--color-ec-text-muted)',
                            margin: 0,
                        }}>
                            Admin
                        </p>
                    </div>
                )}
            </div>
        </aside>
    );
};
