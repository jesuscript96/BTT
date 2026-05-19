"use client";

import type { DayResult } from "@/lib/api_backtester";

interface DaySelectorProps {
  days: DayResult[];
  selectedIdx: number;
  onSelect: (idx: number) => void;
}

export default function DaySelector({ days, selectedIdx, onSelect }: DaySelectorProps) {
  if (days.length <= 1) return null;

  return (
    <div className="bg-[var(--card-bg)] rounded-lg border border-[var(--border)] p-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)] mb-2">
        Dias ({days.length})
      </h2>
      <div className="flex flex-wrap gap-1.5 max-h-60 overflow-y-auto">
        {days.map((d, i) => (
          <button
            key={`${d.ticker}-${d.date}`}
            onClick={() => onSelect(i)}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${i === selectedIdx
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--card-muted-bg)] text-[var(--foreground)] hover:bg-[var(--sidebar-bg)]"
              }`}
          >
            {d.ticker} {d.date}
          </button>
        ))}
      </div>
    </div>
  );
}
