import React from "react";
import { LayoutDashboard, Settings, Database, LineChart } from "lucide-react";

export const Sidebar = () => {
    return (
        <aside className="w-64 bg-[#F2F0ED] border-r border-zinc-200 h-screen fixed left-0 top-0 flex flex-col transition-colors shadow-sm">
            <div className="px-6 py-5 border-b border-zinc-200">
                <h1 className="text-lg font-black bg-gradient-to-r from-blue-600 to-indigo-700 bg-clip-text text-transparent uppercase tracking-tight">
                    BTT (ASG ft. JVC)
                </h1>
            </div>

            <nav className="flex-1 p-4 space-y-2">
                <div className="text-[10px] font-black text-zinc-400 uppercase px-3 mb-2 tracking-widest">Platform</div>
                <a href="#" className="flex items-center gap-3 px-3 py-2 bg-white text-zinc-900 rounded-lg border border-zinc-200 shadow-sm transition-all hover:border-blue-300">
                    <LayoutDashboard className="h-4 w-4 text-blue-600" />
                    <span className="text-sm font-black tracking-tight">Market Analysis</span>
                </a>
                <a href="#" className="flex items-center gap-3 px-3 py-2 text-zinc-500 hover:text-zinc-900 hover:bg-white/50 rounded-lg transition-colors">
                    <LineChart className="h-4 w-4" />
                    <span className="text-sm font-bold tracking-tight">Strategy Builder</span>
                </a>
                <a href="#" className="flex items-center gap-3 px-3 py-2 text-zinc-500 hover:text-zinc-900 hover:bg-white/50 rounded-lg transition-colors">
                    <Database className="h-4 w-4" />
                    <span className="text-sm font-bold tracking-tight">Data Manager</span>
                </a>
            </nav>

            <div className="p-4 border-t border-zinc-200">
                <a href="#" className="flex items-center gap-3 px-3 py-2 text-zinc-500 hover:text-zinc-900 hover:bg-white/50 rounded-lg transition-colors">
                    <Settings className="h-4 w-4" />
                    <span className="text-sm font-bold tracking-tight">Settings</span>
                </a>
            </div>
        </aside>
    );
};
