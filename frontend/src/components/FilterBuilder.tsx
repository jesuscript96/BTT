"use client";

import React, { useState } from "react";
import {
    X, DollarSign, Activity,
    BarChart2, Clock, Zap, Percent
} from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

// Missing icon fix
const RefreshCcw = ({ className }: { className?: string }) => (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /></svg>
);

interface FilterRule {
    id: string;
    category: string;
    metric: string;
    operator: string;
    valueType: "static" | "variable";
    value: string;
}

interface FilterBuilderProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (rules: FilterRule[]) => void;
}

const CATEGORIES = [
    { id: "price", label: "Price", icon: DollarSign },
    { id: "volume", label: "Volume", icon: BarChart2 },
    { id: "gap_run", label: "Gap & Run", icon: Activity },
    { id: "volatility", label: "Volatility", icon: Zap },
    { id: "intraday_return", label: "Intraday Return", icon: RefreshCcw },
    { id: "historical_return", label: "Historical Return", icon: BarChart2 },
    { id: "time", label: "Time", icon: Clock },
    { id: "intraday_vwap", label: "Intraday VWAP", icon: Percent },
];

const METRICS: Record<string, string[]> = {
    price: [
        "Open Price", "Close Price", "Previous Day Close Price", "Pre-Market High Price",
        "High Spike Price", "Low Spike Price", "M1 Price", "M5 Price", "M15 Price",
        "M30 Price", "M60 Price", "M90 Price", "M120 Price", "M180 Price"
    ],
    volume: [
        "EOD Volume", "Premarket Volume"
    ],
    gap_run: [
        "Open Gap %", "RTH Run %", "PMH Gap %", "PMH Fade to Open %", "RTH Fade to Close %"
    ],
    volatility: [
        "RTH Range %", "High Spike %", "Low Spike %",
        "M1 High Spike %", "M1 Low Spike %", "M5 High Spike %", "M5 Low Spike %",
        "M15 High Spike %", "M15 Low Spike %", "M30 High Spike %", "M30 Low Spike %",
        "M60 High Spike %", "M60 Low Spike %", "M90 High Spike %", "M90 Low Spike %",
        "M120 High Spike %", "M120 Low Spike %", "M180 High Spike %", "M180 Low Spike %"
    ],
    intraday_return: [
        "Day Return %", "M1 Return %", "M5 Return %", "M15 Return %", "M30 Return %",
        "M60 Return %", "M90 Return %", "M120 Return %", "M180 Return %",
        "Return % From M1 to Close", "Return % From M5 to Close", "Return % From M15 to Close",
        "Return % From M30 to Close", "Return % From M60 to Close", "Return % From M90 to Close",
        "Return % From M120 to Close", "Return % From M180 to Close", "Close Direction"
    ],
    historical_return: [
        "1D Return %", "1W Return %", "1M Return %", "3M Return %", "6M Return %", "1Y Return %"
    ],
    time: [
        "HOD Time", "LOD Time", "PM High Time"
    ],
    intraday_vwap: [
        "VWAP at Open", "VWAP at M5", "VWAP at M15", "VWAP at M30",
        "VWAP at M60", "VWAP at M90", "VWAP at M120", "VWAP at M180"
    ],
};

const OPERATORS = ["=", "!=", ">", ">=", "<", "<="];

export const FilterBuilder: React.FC<FilterBuilderProps> = ({ isOpen, onClose, onSave }) => {
    const [activeCategory, setActiveCategory] = useState("price");
    const [selectedMetric, setSelectedMetric] = useState<string | null>(null);
    const [step, setStep] = useState<"select" | "build">("select");

    // Builder State
    const [operator, setOperator] = useState(">");
    const [valueType, setValueType] = useState<"static" | "variable">("static");
    const [value, setValue] = useState("");

    if (!isOpen) return null;

    const handleMetricSelect = (metric: string) => {
        setSelectedMetric(metric);
        setStep("build");
    };

    const handleSaveRule = () => {
        if (selectedMetric) {
            const newRule: FilterRule = {
                id: Math.random().toString(36).substr(2, 9),
                category: activeCategory,
                metric: selectedMetric,
                operator,
                valueType,
                value
            };
            onSave([newRule]);
            setStep("select");
            setSelectedMetric(null);
            onClose();
        }
    };

    return (
        <div className="absolute top-4 left-6 z-[100] animate-in zoom-in-95 fade-in duration-150">
            <div className="bg-white border border-zinc-200 w-[600px] h-[520px] rounded-2xl shadow-[0_15px_40px_rgba(0,0,0,0.1)] flex flex-col overflow-hidden transition-colors">
                {/* Header */}
                <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between bg-[#F2F0ED]">
                    <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-blue-600 shadow-sm" />
                        <p className="text-[10px] text-zinc-500 font-black uppercase tracking-widest">Rule Builder</p>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-zinc-200 rounded-lg transition-all text-zinc-400 hover:text-zinc-600">
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="flex-1 flex overflow-hidden bg-white">
                    {step === "select" ? (
                        <>
                            {/* Sidebar */}
                            <div className="w-48 border-r border-zinc-100 p-4 space-y-1 bg-[#F9F9F8]">
                                {CATEGORIES.map((cat) => (
                                    <button
                                        key={cat.id}
                                        onClick={() => setActiveCategory(cat.id)}
                                        className={cn(
                                            "w-full flex items-center gap-3 px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-tight transition-all",
                                            activeCategory === cat.id
                                                ? "bg-blue-50 text-blue-600 border border-blue-100 shadow-sm"
                                                : "text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100"
                                        )}
                                    >
                                        <cat.icon className="h-3.5 w-3.5" />
                                        {cat.label}
                                    </button>
                                ))}
                            </div>

                            {/* Main Selection Area */}
                            <div className="flex-1 p-5 overflow-auto scrollbar-none">
                                <div className="grid grid-cols-2 gap-1.5">
                                    {METRICS[activeCategory]?.map((metric) => (
                                        <button
                                            key={metric}
                                            onClick={() => handleMetricSelect(metric)}
                                            className="group px-4 py-2.5 bg-white border border-zinc-100 rounded-lg text-left hover:border-blue-400 hover:bg-blue-50/50 transition-all shadow-sm active:scale-95"
                                        >
                                            <span className="text-[10px] font-black text-zinc-500 group-hover:text-blue-600 tracking-tight uppercase leading-tight">{metric}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </>
                    ) : (
                        /* Builder Step */
                        <div className="flex-1 flex flex-col p-10 space-y-8 items-center justify-center bg-white">
                            <div className="w-full max-w-sm space-y-6">
                                <div className="text-center space-y-1">
                                    <p className="text-[9px] uppercase font-black text-zinc-400 tracking-widest">Comparing</p>
                                    <h4 className="text-lg font-black text-zinc-900">{selectedMetric}</h4>
                                </div>

                                <div className="grid grid-cols-6 gap-1">
                                    {OPERATORS.map(op => (
                                        <button
                                            key={op}
                                            onClick={() => setOperator(op)}
                                            className={cn(
                                                "py-3 rounded-lg font-black text-xs border transition-all shadow-sm",
                                                operator === op
                                                    ? "bg-blue-600 border-blue-500 text-white shadow-md"
                                                    : "bg-zinc-50 border-zinc-100 text-zinc-400 hover:border-zinc-300 hover:text-zinc-600"
                                            )}
                                        >
                                            {op}
                                        </button>
                                    ))}
                                </div>

                                <div className="flex gap-1 p-1 bg-zinc-50 border border-zinc-100 rounded-xl w-full shadow-inner">
                                    {["static", "variable"].map(type => (
                                        <button
                                            key={type}
                                            onClick={() => setValueType(type as any)}
                                            className={cn(
                                                "flex-1 py-2 rounded-lg text-[9px] font-black uppercase tracking-widest transition-all",
                                                valueType === type
                                                    ? "bg-white text-zinc-900 shadow-sm border border-zinc-100"
                                                    : "text-zinc-400 hover:text-zinc-600"
                                            )}
                                        >
                                            {type === "static" ? "Value" : "Variable"}
                                        </button>
                                    ))}
                                </div>

                                <input
                                    type="text"
                                    placeholder={activeCategory === 'time' ? "HH:MM (e.g. 09:45)" : "Value..."}
                                    value={value}
                                    onChange={(e) => setValue(e.target.value)}
                                    className="w-full p-4 bg-white border border-zinc-200 rounded-xl font-black text-xl text-center focus:border-blue-500 outline-none transition-all placeholder:text-zinc-200 text-zinc-900 shadow-inner"
                                />
                            </div>

                            <div className="flex gap-2 w-full max-w-sm pt-4">
                                <button
                                    onClick={() => setStep("select")}
                                    className="flex-1 py-3 rounded-xl font-black text-[10px] uppercase tracking-widest text-zinc-400 hover:text-zinc-600 transition-colors bg-white border border-zinc-200 hover:bg-zinc-50"
                                >
                                    Back
                                </button>
                                <button
                                    onClick={handleSaveRule}
                                    className="flex-[2] py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-black text-[10px] uppercase tracking-widest shadow-md hover:shadow-lg transition-all active:scale-95"
                                >
                                    Add Filter
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

const ChevronRight = ({ className }: { className?: string }) => <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6" /></svg>;
