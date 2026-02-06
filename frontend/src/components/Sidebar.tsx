"use client";

import React, { useState } from "react";
import { LayoutDashboard, Database, ChevronDown, ChevronRight, Play, Plus, LineChart } from "lucide-react";
import Link from "next/link"; // Assuming Next.js based on file structure

export const Sidebar = () => {
    // State to toggle the "My Strategies" group
    const [isStrategiesOpen, setIsStrategiesOpen] = useState(true);

    return (
        <aside className="w-64 bg-[#F2F0ED] h-screen fixed left-0 top-0 flex flex-col font-sans">
            {/* Header */}
            <div className="px-5 py-4 flex items-center gap-2">
                <div className="w-6 h-6 bg-zinc-900 rounded-sm flex items-center justify-center text-white font-bold text-xs">
                    B
                </div>
                <h1 className="text-zinc-900 font-semibold text-sm tracking-tight">
                    BTT Console
                </h1>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-3 py-2 space-y-1">
                {/* BUILD Section Header - mimicking Claude's "BUILD" etc if needed, 
                    but user asked for specific Main items. 
                    We will treat "Market Analysis" and "Backtester" as main items. 
                */}

                <div className="text-[11px] font-medium text-zinc-500 px-2 py-2">
                    MENU
                </div>

                <Link
                    href="/"
                    className="flex items-center gap-2.5 px-2 py-1.5 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 rounded-md transition-colors group"
                >
                    <LayoutDashboard className="h-4 w-4 text-zinc-500 group-hover:text-zinc-900" />
                    <span className="text-sm font-medium">Market Analysis</span>
                </Link>

                {/* My Strategies Group */}
                <div className="space-y-0.5">
                    <button
                        onClick={() => setIsStrategiesOpen(!isStrategiesOpen)}
                        className="w-full flex items-center justify-between px-2 py-1.5 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 rounded-md transition-colors group text-left"
                    >
                        <div className="flex items-center gap-2.5">
                            <LineChart className="h-4 w-4 text-zinc-500 group-hover:text-zinc-900" />
                            <span className="text-sm font-medium">My Strategies</span>
                        </div>
                        {isStrategiesOpen ? (
                            <ChevronDown className="h-3 w-3 text-zinc-400" />
                        ) : (
                            <ChevronRight className="h-3 w-3 text-zinc-400" />
                        )}
                    </button>

                    {/* Nested Items */}
                    {isStrategiesOpen && (
                        <div className="pl-9 space-y-0.5 mt-0.5">
                            <Link
                                href="/strategies/new"
                                className="flex items-center gap-2.5 py-1.5 px-2 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 rounded-md transition-colors"
                            >
                                <span className="text-sm">New Strategy</span>
                            </Link>
                            <Link
                                href="/strategies/database"
                                className="flex items-center gap-2.5 py-1.5 px-2 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 rounded-md transition-colors"
                            >
                                <span className="text-sm">Database</span>
                            </Link>
                        </div>
                    )}
                </div>

                <Link
                    href="/backtester"
                    className="flex items-center gap-2.5 px-2 py-1.5 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 rounded-md transition-colors group"
                >
                    <Play className="h-4 w-4 text-zinc-500 group-hover:text-zinc-900" />
                    <span className="text-sm font-medium">Backtester</span>
                </Link>
            </nav>

            {/* Bottom Section similar to Claude's User Profile/Settings */}
            <div className="p-3 mt-auto">
                <div className="flex items-center gap-3 px-2 py-2 hover:bg-zinc-200/50 rounded-md cursor-pointer transition-colors">
                    <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-orange-400 to-red-500"></div>
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-zinc-900 truncate">User Account</p>
                    </div>
                </div>
            </div>
        </aside>
    );
};
