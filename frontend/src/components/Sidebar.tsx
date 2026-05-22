"use client";

import React, { useState } from "react";
import {
    LayoutDashboard,
    ChevronDown,
    ChevronRight,
    Play,
    LineChart,
    BookOpen,
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
    fontSize: 17,
    letterSpacing: "-0.6px",
    color: "var(--color-ec-text-high)",
};

export const Sidebar = () => {
    const pathname = usePathname();
    const [isHovered, setIsHovered] = useState(false);
    const [isStrategiesOpen, setIsStrategiesOpen] = useState(true);
    const [isTutorialsOpen, setIsTutorialsOpen] = useState(true);

    const isCollapsed = !isHovered;

    const isActive = (href: string) => {
        if (href === "/") return pathname === "/";
        return pathname.startsWith(href);
    };

    const linkActive = (href: string) =>
        isActive(href)
            ? "bg-ec-bg-surface text-ec-text-high"
            : "text-ec-text-secondary hover:bg-ec-bg-surface hover:text-ec-text-high";

    const linkLayout = (collapsed: boolean) =>
        collapsed
            ? "justify-center gap-0 px-0"
            : "gap-2.5 px-2";

    const labelFade = (collapsed: boolean) =>
        `text-sm overflow-hidden whitespace-nowrap transition-all duration-150 ${
            collapsed ? "w-0 opacity-0" : "opacity-100"
        }`;

    return (
        <aside
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            className="h-screen relative flex-shrink-0 flex flex-col overflow-hidden"
            style={{
                width: isCollapsed ? 56 : 240,
                backgroundColor: "var(--color-ec-bg-sidebar)",
                borderRight: "0.5px solid var(--color-ec-border)",
                transition: "width 200ms ease",
            }}
        >
            {/* Header */}
            <div
                className="flex items-center px-4"
                style={{
                    height: 56,
                    borderBottom: "0.5px solid var(--color-ec-border)",
                    justifyContent: isCollapsed ? "center" : "flex-start",
                    gap: 10,
                }}
            >
                {ISOTIPO}
                <span
                    className={labelFade(isCollapsed)}
                    style={wordmarkStyle}
                >
                    Edgecute
                </span>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-3 py-2 space-y-1">
                {/* MENU label */}
                {!isCollapsed && (
                    <div
                        className="px-2 py-2 uppercase tracking-widest"
                        style={{ fontSize: 11, fontWeight: 700, color: "var(--color-ec-text-muted)" }}
                    >
                        MENU
                    </div>
                )}

                {/* Market Analysis */}
                <Link
                    href="/"
                    className={`flex items-center ${linkLayout(isCollapsed)} py-1.5 rounded-md transition-all group ${linkActive("/")}`}
                >
                    <LayoutDashboard className="h-4 w-4 flex-shrink-0" />
                    <span className={labelFade(isCollapsed)}>Market Analysis</span>
                </Link>

                {/* My Strategies Group */}
                <div className="space-y-0.5">
                    <button
                        onClick={() => setIsStrategiesOpen(!isStrategiesOpen)}
                        className={`w-full flex items-center ${
                            isCollapsed ? "justify-center px-0" : "justify-between px-2"
                        } gap-2.5 py-1.5 rounded-md transition-all group text-left text-ec-text-secondary hover:bg-ec-bg-surface hover:text-ec-text-high`}
                    >
                        <div className={`flex items-center ${isCollapsed ? "gap-0" : "gap-2.5"}`}>
                            <LineChart className="h-4 w-4 flex-shrink-0" />
                            <span className={labelFade(isCollapsed)}>My Strategies</span>
                        </div>
                        {!isCollapsed &&
                            (isStrategiesOpen ? (
                                <ChevronDown className="h-3 w-3 opacity-50 flex-shrink-0" />
                            ) : (
                                <ChevronRight className="h-3 w-3 opacity-50 flex-shrink-0" />
                            ))}
                    </button>

                    {!isCollapsed && isStrategiesOpen && (
                        <div className="pl-9 space-y-0.5 mt-0.5 border-l border-[#2C2F33] ml-4">
                            <Link
                                href="/strategies/new"
                                className={`flex items-center gap-2.5 py-1.5 px-2 rounded-md transition-all ${
                                    isActive("/strategies/new")
                                        ? "text-ec-text-high bg-ec-bg-surface"
                                        : "text-ec-text-muted hover:text-ec-text-high hover:bg-ec-bg-surface"
                                }`}
                            >
                                <span className="text-sm">New Strategy</span>
                            </Link>
                            <Link
                                href="/database"
                                className={`flex items-center gap-2.5 py-1.5 px-2 rounded-md transition-all ${
                                    isActive("/database")
                                        ? "text-ec-text-high bg-ec-bg-surface"
                                        : "text-ec-text-muted hover:text-ec-text-high hover:bg-ec-bg-surface"
                                }`}
                            >
                                <span className="text-sm">Database</span>
                            </Link>
                        </div>
                    )}
                </div>

                {/* Backtester */}
                <Link
                    href="/backtester"
                    className={`flex items-center ${linkLayout(isCollapsed)} py-1.5 rounded-md transition-all group ${linkActive("/backtester")}`}
                >
                    <Play className="h-4 w-4 flex-shrink-0" />
                    <span className={labelFade(isCollapsed)}>Backtester</span>
                </Link>

                {/* Tutoriales Group */}
                <div className="space-y-0.5">
                    <button
                        onClick={() => setIsTutorialsOpen(!isTutorialsOpen)}
                        className={`w-full flex items-center ${
                            isCollapsed ? "justify-center px-0" : "justify-between px-2"
                        } gap-2.5 py-1.5 rounded-md transition-all group text-left text-ec-text-secondary hover:bg-ec-bg-surface hover:text-ec-text-high`}
                    >
                        <div className={`flex items-center ${isCollapsed ? "gap-0" : "gap-2.5"}`}>
                            <BookOpen className="h-4 w-4 flex-shrink-0" />
                            <span className={labelFade(isCollapsed)}>Tutoriales</span>
                        </div>
                        {!isCollapsed &&
                            (isTutorialsOpen ? (
                                <ChevronDown className="h-3 w-3 opacity-50 flex-shrink-0" />
                            ) : (
                                <ChevronRight className="h-3 w-3 opacity-50 flex-shrink-0" />
                            ))}
                    </button>

                    {!isCollapsed && isTutorialsOpen && (
                        <div className="pl-9 space-y-0.5 mt-0.5 border-l border-[#2C2F33] ml-4">
                            <Link
                                href="/tutorials"
                                className={`flex items-center gap-2.5 py-1.5 px-2 rounded-md transition-all ${
                                    isActive("/tutorials")
                                        ? "text-ec-text-high bg-ec-bg-surface"
                                        : "text-ec-text-muted hover:text-ec-text-high hover:bg-ec-bg-surface"
                                }`}
                            >
                                <span className="text-sm">Crea tu estrategia</span>
                            </Link>
                        </div>
                    )}
                </div>
            </nav>

            {/* Bottom Profile */}
            <div
                className="p-3 mt-auto"
                style={{ borderTop: "0.5px solid var(--color-ec-border)" }}
            >
                <div
                    className={`flex items-center rounded-md cursor-pointer transition-all hover:bg-ec-bg-surface py-2 ${
                        isCollapsed ? "justify-center px-0" : "gap-3 px-2"
                    }`}
                >
                    <div className="w-6 h-6 rounded-full bg-gradient-to-tr from-orange-400 to-red-500 shadow-sm flex-shrink-0" />
                    {!isCollapsed && (
                        <div className="flex-1 min-w-0">
                            <p className="text-sm font-bold truncate" style={{ color: "var(--color-ec-text-high)" }}>
                                Tito el Man
                            </p>
                            <p
                                className="uppercase tracking-tighter truncate"
                                style={{ fontSize: 10, fontWeight: 500, color: "var(--color-ec-text-muted)" }}
                            >
                                Admin
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </aside>
    );
};
