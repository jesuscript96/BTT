"use client";

import React, { useState } from "react";
import { LayoutDashboard, Database, ChevronDown, ChevronRight, Play, Plus, LineChart, BookOpen } from "lucide-react";
import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";

export const Sidebar = () => {
    // State to toggle the "My Strategies" group
    const [isStrategiesOpen, setIsStrategiesOpen] = useState(true);
    const [isTutorialsOpen, setIsTutorialsOpen] = useState(true);

    return (
        <aside className="w-64 bg-sidebar border-r border-border h-screen fixed left-0 top-0 flex flex-col font-sans transition-colors duration-300 z-50">
            {/* Header */}
            <div className="px-5 py-4 flex items-center justify-between gap-2 border-b border-border/50">
                <div className="flex items-center gap-2">
                    <div className="w-6 h-6 bg-foreground text-background rounded-sm flex items-center justify-center font-bold text-xs transition-colors">
                        B
                    </div>
                    <h1 className="text-foreground font-semibold text-sm tracking-tight transition-colors">
                        BTT Console
                    </h1>
                </div>
                <ThemeToggle />
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-3 py-2 space-y-1">
                <div className="text-[11px] font-black text-muted-foreground/60 px-2 py-2 uppercase tracking-widest">
                    MENU
                </div>

                <Link
                    href="/"
                    className="flex items-center gap-2.5 px-2 py-1.5 text-sidebar-foreground/80 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all group"
                >
                    <LayoutDashboard className="h-4 w-4 text-sidebar-foreground/50 group-hover:text-foreground transition-colors" />
                    <span className="text-sm font-medium">Market Analysis</span>
                </Link>

                {/* My Strategies Group */}
                <div className="space-y-0.5">
                    <button
                        onClick={() => setIsStrategiesOpen(!isStrategiesOpen)}
                        className="w-full flex items-center justify-between px-2 py-1.5 text-sidebar-foreground/80 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all group text-left"
                    >
                        <div className="flex items-center gap-2.5">
                            <LineChart className="h-4 w-4 text-sidebar-foreground/50 group-hover:text-foreground transition-colors" />
                            <span className="text-sm font-medium">My Strategies</span>
                        </div>
                        {isStrategiesOpen ? (
                            <ChevronDown className="h-3 w-3 opacity-50" />
                        ) : (
                            <ChevronRight className="h-3 w-3 opacity-50" />
                        )}
                    </button>

                    {/* Nested Items */}
                    {isStrategiesOpen && (
                        <div className="pl-9 space-y-0.5 mt-0.5 border-l border-border/50 ml-4">
                            <Link
                                href="/strategies/new"
                                className="flex items-center gap-2.5 py-1.5 px-2 text-sidebar-foreground/60 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all"
                            >
                                <span className="text-sm">New Strategy</span>
                            </Link>
                            <Link
                                href="/database"
                                className="flex items-center gap-2.5 py-1.5 px-2 text-sidebar-foreground/60 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all"
                            >
                                <span className="text-sm">Database</span>
                            </Link>
                        </div>
                    )}
                </div>

                <Link
                    href="/backtester"
                    className="flex items-center gap-2.5 px-2 py-1.5 text-sidebar-foreground/80 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all group"
                >
                    <Play className="h-4 w-4 text-sidebar-foreground/50 group-hover:text-foreground transition-colors" />
                    <span className="text-sm font-medium">Backtester</span>
                </Link>

                {/* Tutorials Group */}
                <div className="space-y-0.5">
                    <button
                        onClick={() => setIsTutorialsOpen(!isTutorialsOpen)}
                        className="w-full flex items-center justify-between px-2 py-1.5 text-sidebar-foreground/80 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all group text-left"
                    >
                        <div className="flex items-center gap-2.5">
                            <BookOpen className="h-4 w-4 text-sidebar-foreground/50 group-hover:text-foreground transition-colors" />
                            <span className="text-sm font-medium">Tutoriales</span>
                        </div>
                        {isTutorialsOpen ? (
                            <ChevronDown className="h-3 w-3 opacity-50" />
                        ) : (
                            <ChevronRight className="h-3 w-3 opacity-50" />
                        )}
                    </button>

                    {isTutorialsOpen && (
                        <div className="pl-9 space-y-0.5 mt-0.5 border-l border-border/50 ml-4">
                            <Link
                                href="/tutorials"
                                className="flex items-center gap-2.5 py-1.5 px-2 text-sidebar-foreground/60 hover:text-foreground hover:bg-sidebar-hover rounded-md transition-all"
                            >
                                <span className="text-sm">Crea tu estrategia</span>
                            </Link>
                        </div>
                    )}
                </div>
            </nav>

            {/* Bottom Section similar to Claude's User Profile/Settings */}
            <div className="p-3 mt-auto border-t border-border/50 bg-sidebar/50">
                <div className="flex items-center gap-3 px-2 py-2 hover:bg-sidebar-hover rounded-md cursor-pointer transition-all">
                    <div className="w-6 h-6 rounded-full bg-gradient-to-tr from-orange-400 to-red-500 shadow-sm flex-shrink-0"></div>
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold text-foreground truncate">Tito el Man</p>
                        <p className="text-[10px] font-medium text-muted-foreground truncate uppercase tracking-tighter">Admin</p>
                    </div>
                </div>
            </div>
        </aside>
    );
};
