"use client";

import { useState, useRef, useEffect } from "react";
import {
  INDICATOR_REGISTRY,
  getIndicatorsByCategory,
  getIndicatorDef,
  createDefaultParams,
  type ActiveIndicator,
  type IndicatorCategory,
} from "@/lib/indicatorRegistry";

interface IndicatorDropdownProps {
  activeIndicators: ActiveIndicator[];
  onAdd: (indicatorId: string) => void;
  onRemove: (instanceId: string) => void;
  onAddInstance: (indicatorId: string) => void;
  onUpdateParam: (instanceId: string, paramName: string, value: number) => void;
}

const CATEGORY_ICONS: Record<IndicatorCategory, string> = {
  Trend: "📈",
  Momentum: "⚡",
  Volatility: "📊",
  Volume: "📉",
};

const INDICATOR_COLORS: Record<string, { bg: string; text: string; accent: string; border: string }> = {
  // Trend
  SMA: { bg: "bg-amber-50", text: "text-amber-800", accent: "text-amber-600", border: "border-amber-200" },
  EMA: { bg: "bg-purple-50", text: "text-purple-800", accent: "text-purple-600", border: "border-purple-200" },
  WMA: { bg: "bg-orange-50", text: "text-orange-800", accent: "text-orange-600", border: "border-orange-200" },
  VWAP: { bg: "bg-yellow-50", text: "text-yellow-800", accent: "text-yellow-600", border: "border-yellow-200" },
  LINEAR_REGRESSION: { bg: "bg-lime-50", text: "text-lime-800", accent: "text-lime-600", border: "border-lime-200" },
  ICHIMOKU: { bg: "bg-teal-50", text: "text-teal-800", accent: "text-teal-600", border: "border-teal-200" },
  PARABOLIC_SAR: { bg: "bg-cyan-50", text: "text-cyan-800", accent: "text-cyan-600", border: "border-cyan-200" },
  // Volatility
  DONCHIAN: { bg: "bg-sky-50", text: "text-sky-800", accent: "text-sky-600", border: "border-sky-200" },
  BOLLINGER: { bg: "bg-indigo-50", text: "text-indigo-800", accent: "text-indigo-600", border: "border-indigo-200" },
  ZIGZAG: { bg: "bg-rose-50", text: "text-rose-800", accent: "text-rose-600", border: "border-rose-200" },
  OPENING_RANGE: { bg: "bg-fuchsia-50", text: "text-fuchsia-800", accent: "text-fuchsia-600", border: "border-fuchsia-200" },
  // Momentum
  RSI: { bg: "bg-blue-50", text: "text-blue-800", accent: "text-blue-600", border: "border-blue-200" },
  STOCHASTIC: { bg: "bg-violet-50", text: "text-violet-800", accent: "text-violet-600", border: "border-violet-200" },
  MOMENTUM: { bg: "bg-emerald-50", text: "text-emerald-800", accent: "text-emerald-600", border: "border-emerald-200" },
  CCI: { bg: "bg-pink-50", text: "text-pink-800", accent: "text-pink-600", border: "border-pink-200" },
  ROC: { bg: "bg-red-50", text: "text-red-800", accent: "text-red-600", border: "border-red-200" },
  MACD: { bg: "bg-blue-50", text: "text-blue-800", accent: "text-blue-600", border: "border-blue-200" },
  DMI: { bg: "bg-green-50", text: "text-green-800", accent: "text-green-600", border: "border-green-200" },
  WILLIAMS_R: { bg: "bg-orange-50", text: "text-orange-800", accent: "text-orange-600", border: "border-orange-200" },
  ADX: { bg: "bg-teal-50", text: "text-teal-800", accent: "text-teal-600", border: "border-teal-200" },
  // Volume
  ATR: { bg: "bg-violet-50", text: "text-violet-800", accent: "text-violet-600", border: "border-violet-200" },
  OBV: { bg: "bg-cyan-50", text: "text-cyan-800", accent: "text-cyan-600", border: "border-cyan-200" },
  VOL_AD: { bg: "bg-lime-50", text: "text-lime-800", accent: "text-lime-600", border: "border-lime-200" },
  VOLUME: { bg: "bg-gray-50", text: "text-gray-800", accent: "text-gray-600", border: "border-gray-200" },
  RVOL: { bg: "bg-amber-50", text: "text-amber-800", accent: "text-amber-600", border: "border-amber-200" },
  ACCUMULATED_VOLUME: { bg: "bg-emerald-50", text: "text-emerald-800", accent: "text-emerald-600", border: "border-emerald-200" },
  HEIKIN_ASHI: { bg: "bg-rose-50", text: "text-rose-800", accent: "text-rose-600", border: "border-rose-200" },
};

const DEFAULT_COLOR = { bg: "bg-gray-50", text: "text-gray-800", accent: "text-gray-600", border: "border-gray-200" };

function getColor(id: string) {
  return INDICATOR_COLORS[id] || DEFAULT_COLOR;
}

export default function IndicatorDropdown({
  activeIndicators,
  onAdd,
  onRemove,
  onAddInstance,
  onUpdateParam,
}: IndicatorDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const grouped = getIndicatorsByCategory();
  const activeIds = new Set(activeIndicators.map(a => a.indicatorId));

  // Group active indicators by indicatorId for rendering
  const activeByType = new Map<string, ActiveIndicator[]>();
  for (const ai of activeIndicators) {
    if (!activeByType.has(ai.indicatorId)) activeByType.set(ai.indicatorId, []);
    activeByType.get(ai.indicatorId)!.push(ai);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {/* Add Indicator Button */}
      <div ref={dropdownRef} className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={`px-2.5 py-1.5 border rounded font-medium transition-all flex items-center gap-1.5
            ${isOpen
              ? "border-blue-400 bg-blue-50 text-blue-700 shadow-sm"
              : "border-[var(--border)] bg-[var(--card-bg)] text-[var(--muted)] hover:bg-[var(--sidebar-bg)] hover:border-gray-400"
            }`}
        >
          <span className="text-sm">＋</span> Indicators
        </button>

        {isOpen && (
          <div className="absolute left-0 top-full mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-xl z-50 overflow-hidden">
            <div className="max-h-96 overflow-y-auto custom-scrollbar">
              {(Object.keys(grouped) as IndicatorCategory[]).map(category => (
                <div key={category}>
                  <div className="px-3 py-1.5 bg-gray-50 text-[10px] font-bold text-gray-500 uppercase tracking-wider flex items-center gap-1.5 border-b border-gray-100 sticky top-0 z-10">
                    <span>{CATEGORY_ICONS[category]}</span> {category}
                  </div>
                  {grouped[category].map(def => {
                    const isActive = activeIds.has(def.id);
                    return (
                      <button
                        key={def.id}
                        onClick={() => {
                          onAdd(def.id);
                          if (!def.multi) setIsOpen(false);
                        }}
                        className={`w-full text-left pl-3 pr-4 py-1.5 text-xs transition-colors flex items-center justify-between
                          ${isActive
                            ? "bg-blue-50 text-blue-700"
                            : "text-gray-700 hover:bg-gray-50"
                          }`}
                      >
                        <span>{def.label}</span>
                        <span className="text-[10px] text-gray-400">
                          {def.displayMode === "overlay" ? "chart" : "panel"}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Active Indicator Chips */}
      {Array.from(activeByType.entries()).map(([indicatorId, instances]) => {
        const def = getIndicatorDef(indicatorId);
        if (!def) return null;
        const color = getColor(indicatorId);

        return (
          <div
            key={indicatorId}
            className={`flex items-center gap-0.5 ${color.bg} border ${color.border} rounded overflow-hidden`}
          >
            {/* Label / toggle off */}
            <button
              onClick={() => {
                // Remove all instances of this indicator
                for (const inst of instances) onRemove(inst.instanceId);
              }}
              className={`px-2 py-1 font-semibold ${color.text} hover:opacity-70 transition-opacity`}
              title={`Remove ${def.label}`}
            >
              {def.label}
            </button>

            {/* Parameter inputs for each instance */}
            {instances.map(inst => (
              <div key={inst.instanceId} className={`flex items-center ${color.bg} border-l ${color.border}`}>
                {def.params.map(p => (
                  <div key={p.name} className="flex items-center px-1">
                    {def.params.length > 1 && (
                      <span className={`text-[9px] ${color.accent} mr-0.5 opacity-70`}>{p.label}</span>
                    )}
                    <input
                      type="number"
                      value={inst.params[p.name] ?? p.default}
                      onChange={e => onUpdateParam(inst.instanceId, p.name, Number(e.target.value))}
                      className={`w-10 bg-transparent ${color.text} outline-none text-center`}
                      min={p.min}
                      max={p.max}
                      step={p.step || 1}
                    />
                  </div>
                ))}
                {instances.length > 1 && (
                  <button
                    onClick={() => onRemove(inst.instanceId)}
                    className={`px-1 ${color.accent} hover:opacity-70`}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}

            {/* Add another instance button (only for multi indicators) */}
            {def.multi && (
              <button
                onClick={() => onAddInstance(indicatorId)}
                className={`px-1.5 py-1 ${color.accent} hover:opacity-70 border-l ${color.border}`}
                title={`Add another ${def.label}`}
              >
                +
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
