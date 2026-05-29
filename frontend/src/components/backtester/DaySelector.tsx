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
    <div style={{
      backgroundColor: 'var(--color-ec-bg-surface)',
      border: '0.5px solid var(--color-ec-border)',
      borderRadius: 7,
      padding: 12,
    }}>
      <h2 style={{
        fontFamily: 'var(--color-ec-sans)',
        fontSize: 9,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.15em',
        color: 'var(--color-ec-text-muted)',
        marginBottom: 8,
      }}>
        Dias ({days.length})
      </h2>
      <div className="flex flex-wrap gap-1.5 max-h-60 overflow-y-auto" style={{ scrollbarWidth: 'none' }}>
        {days.map((d, i) => (
          <button
            key={`${d.ticker}-${d.date}`}
            onClick={() => onSelect(i)}
            style={i === selectedIdx ? {
              padding: '4px 8px',
              fontSize: 10,
              fontWeight: 600,
              borderRadius: 4,
              backgroundColor: 'var(--color-ec-copper)',
              color: 'var(--color-ec-copper-text)',
              border: 'none',
              cursor: 'pointer',
              fontFamily: 'var(--color-ec-sans)',
              whiteSpace: 'nowrap',
            } : {
              padding: '4px 8px',
              fontSize: 10,
              fontWeight: 500,
              borderRadius: 4,
              backgroundColor: 'var(--color-ec-bg-elevated)',
              color: 'var(--color-ec-text-secondary)',
              border: '0.5px solid var(--color-ec-border)',
              cursor: 'pointer',
              fontFamily: 'var(--color-ec-sans)',
              whiteSpace: 'nowrap',
              transition: 'background 150ms ease, color 150ms ease',
            }}
            onMouseEnter={i !== selectedIdx ? (e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-surface)';
              e.currentTarget.style.color = 'var(--color-ec-text-primary)';
            } : undefined}
            onMouseLeave={i !== selectedIdx ? (e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-elevated)';
              e.currentTarget.style.color = 'var(--color-ec-text-secondary)';
            } : undefined}
          >
            {d.ticker} {d.date}
          </button>
        ))}
      </div>
    </div>
  );
}
