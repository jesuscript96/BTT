"use client";

import type { AggregateMetrics } from "@/lib/api_backtester";

interface MetricsCardProps {
  metrics: AggregateMetrics;
  vertical?: boolean;
}

export default function MetricsCard({ metrics, vertical = false }: MetricsCardProps) {
  const rows = [
    { label: "Days", value: String(metrics.total_days ?? 0) },
    { label: "Trades", value: String(metrics.total_trades ?? 0) },
    { label: "Win Rate", value: `${(metrics.win_rate_pct ?? 0).toFixed(1)}%` },
    { label: "PF", value: (metrics.avg_profit_factor ?? 0).toFixed(3) },
    { label: "Return", value: `${(metrics.total_return_pct ?? 0).toFixed(2)}%` },
    { label: "Max MAE", value: `${(metrics.max_mae ?? 0).toFixed(2)}%` },
    { label: "Avg Ret/Day", value: `${(metrics.avg_return_per_day_pct ?? 0).toFixed(3)}%` },
    { label: "Avg R/Day", value: `${(metrics.avg_r_per_day ?? 0).toFixed(3)}R` },
    { label: "Sharpe", value: (metrics.avg_sharpe ?? 0).toFixed(3) },
    { label: "Sortino", value: (metrics.sortino_ratio ?? 0).toFixed(3) },
    { label: "Calmar", value: (metrics.calmar_ratio ?? 0).toFixed(3) },
    { label: "R\u00B2", value: (metrics.r_squared ?? 0).toFixed(4) },
    { label: "DD/Ret", value: (metrics.dd_return_ratio ?? 0).toFixed(3) },
    { label: "Max DD", value: `${(metrics.max_drawdown_pct ?? 0).toFixed(2)}%` },
    { label: "Max W Streak", value: String(metrics.max_consecutive_wins ?? 0) },
    { label: "Max L Streak", value: String(metrics.max_consecutive_losses ?? 0) },
  ];

  if (vertical) {
    return (
      <div className="transition-colors">
      <div className="px-1 flex items-center h-[30px] mb-2" style={{ borderBottom: '1px solid var(--border)' }}>
        <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">
          Aggregate Results
        </span>
      </div>
        <div className="grid grid-cols-2 gap-x-4">
          {rows.map((row, idx) => (
            <div
              key={idx}
              className="flex items-baseline justify-between py-2 transition-colors"
              style={{ borderBottom: '1px solid color-mix(in srgb, var(--border) 30%, transparent)' }}
            >
              <span className="text-[9px] font-medium text-[var(--muted)] uppercase tracking-tight">
                {row.label}
              </span>
              <span className="text-[12px] font-bold font-mono text-[var(--text-data)]">
                {row.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="transition-colors">
      <div className="px-1 flex items-center h-[30px] mb-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <span className="text-[10px] font-semibold text-[var(--muted)] uppercase tracking-[0.12em]">
          Aggregate Results
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6">
        {rows.map((row, idx) => (
          <div
            key={idx}
            className="flex items-baseline justify-between py-2.5 transition-colors"
            style={{ borderBottom: '1px solid color-mix(in srgb, var(--border) 30%, transparent)' }}
          >
            <span className="text-[9px] font-medium text-[var(--muted)] uppercase tracking-tight mr-2">
              {row.label}
            </span>
            <span className="text-[12px] font-bold font-mono text-[var(--text-data)]">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
