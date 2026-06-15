"use client";

import type { AggregateMetrics } from "@/lib/api_backtester";

interface MetricsCardProps {
  metrics: AggregateMetrics;
  vertical?: boolean;
}

export default function MetricsCard({ metrics, vertical = false }: MetricsCardProps) {
  const rows = [
    { label: "Days", value: String(metrics.total_days ?? 0), tooltip: "Número total de días que abarca el período del backtest." },
    { label: "Trades", value: String(metrics.total_trades ?? 0), tooltip: "Cantidad total de operaciones ejecutadas." },
    { label: "Win Rate", value: `${(metrics.win_rate_pct ?? 0).toFixed(1)}%`, tooltip: "Porcentaje de operaciones ganadas sobre el total de trades. Ej: 55% significa que ganas 55 de cada 100 operaciones." },
    { label: "PF", value: (metrics.avg_profit_factor ?? 0).toFixed(3), tooltip: "Profit Factor. Relación de beneficio bruto / pérdida bruta. Ej: PF de 1.8 significa que por cada $1 que pierdes, ganas $1.80. Valores > 1.0 son rentables." },
    { label: "Return", value: `${(metrics.total_return_pct ?? 0).toFixed(2)}%`, tooltip: "Rentabilidad porcentual total acumulada en base al capital inicial." },
    { label: "Max MAE", value: `${(metrics.max_mae ?? 0).toFixed(2)}%`, tooltip: "Mínima excursión adversa máxima. La mayor pérdida flotante porcentual que llegó a registrar una sola operación antes de cerrarse." },
    { label: "Avg Ret/Day", value: `${(metrics.avg_return_per_day_pct ?? 0).toFixed(3)}%`, tooltip: "Retorno porcentual promedio por día." },
    { label: "Avg R/Day", value: `${(metrics.avg_r_per_day ?? 0).toFixed(3)}R`, tooltip: "Resultado promedio por día medido en múltiplos de tu riesgo inicial por operación (R)." },
    { label: "Sharpe", value: (metrics.avg_sharpe ?? 0).toFixed(3), tooltip: "Ratio de Sharpe. Muestra el rendimiento en relación al riesgo asumido (volatilidad). Cuanto más alto, más estable y seguro es el retorno. Sharpe > 1.0 es bueno, > 1.5 es excelente." },
    { label: "Sortino", value: (metrics.sortino_ratio ?? 0).toFixed(3), tooltip: "Ratio de Sortino. Similar al Sharpe, pero solo penaliza la volatilidad de los rendimientos negativos (las pérdidas reales), ignorando la volatilidad de las ganancias." },
    { label: "Calmar", value: (metrics.calmar_ratio ?? 0).toFixed(3), tooltip: "Ratio de Calmar. Relación entre la rentabilidad anualizada y el drawdown máximo (peor caída). Mide la eficiencia retorno/riesgo de caída histórica. Calmar alto = más ganancias con menos sustos." },
    { label: "Avg Y/U.index", value: (metrics.avg_r_ui ?? 0).toFixed(2), tooltip: "Rendimiento promedio ajustado por el Ulcer Index (profundidad y duración de las caídas de la cuenta)." },
    { label: "DD/Ret", value: (metrics.dd_return_ratio ?? 0).toFixed(3), tooltip: "Relación Drawdown vs Retorno. Cuanto menor sea, mejor es el sistema generando beneficios con bajas caídas temporales." },
    { label: "Max DD", value: `${(metrics.max_drawdown_pct ?? 0).toFixed(2)}%`, tooltip: "Drawdown Máximo. La mayor caída porcentual desde el punto más alto del capital hasta el más bajo antes de recuperarse. Representa la peor racha de pérdida temporal." },
    { label: "Max W Streak", value: String(metrics.max_consecutive_wins ?? 0), tooltip: "Número máximo de operaciones ganadoras consecutivas (racha de victorias)." },
    { label: "Max L Streak", value: String(metrics.max_consecutive_losses ?? 0), tooltip: "Número máximo de operaciones perdedoras consecutivas (racha de pérdidas)." },
  ];

  if (vertical) {
    return (
      <div className="transition-colors">
      <div style={{
        borderBottom: '0.5px solid var(--color-ec-border)',
        height: 32,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-start',
        padding: '0 0px',
      }}>
        <span style={{
          fontFamily: 'var(--color-ec-sans)',
          fontSize: 11,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          color: 'var(--color-ec-text-muted)',
        }}>
          Agregate results
        </span>
      </div>
        <div className="grid grid-cols-2 gap-x-4">
          {rows.map((row, idx) => (
            <div
              key={idx}
              className="flex items-baseline justify-between py-1 transition-colors"
              style={{ borderBottom: '1px solid color-mix(in srgb, var(--border) 30%, transparent)' }}
            >
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-text-muted)',
                display: 'inline-flex',
                alignItems: 'center',
              }}>
                {row.label}
                <span
                  title={row.tooltip}
                  style={{
                    cursor: 'help',
                    marginLeft: '4px',
                    opacity: 0.6,
                    fontSize: '8px',
                    color: 'var(--color-ec-text-secondary)',
                    userSelect: 'none',
                  }}
                >
                  (?)
                </span>
              </span>
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 13,
                fontWeight: 700,
                color: 'var(--color-ec-text-primary)',
                letterSpacing: '-0.2px',
              }}>
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
      <div style={{
        borderBottom: '0.5px solid var(--color-ec-border)',
        height: 32,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-start',
        padding: '0 0px',
        marginBottom: 12,
      }}>
        <span style={{
          fontFamily: 'var(--color-ec-sans)',
          fontSize: 11,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          color: 'var(--color-ec-text-muted)',
        }}>
          Agregate results
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6">
        {rows.map((row, idx) => (
          <div
            key={idx}
            className="flex items-baseline justify-between py-2.5 transition-colors"
            style={{ borderBottom: '0.5px solid color-mix(in srgb, var(--color-ec-border) 30%, transparent)' }}
          >
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--color-ec-text-muted)',
              marginRight: 8,
              display: 'inline-flex',
              alignItems: 'center',
            }}>
              {row.label}
              <span
                title={row.tooltip}
                style={{
                  cursor: 'help',
                  marginLeft: '4px',
                  opacity: 0.6,
                  fontSize: '8px',
                  color: 'var(--color-ec-text-secondary)',
                  userSelect: 'none',
                }}
              >
                (?)
              </span>
            </span>
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 13,
              fontWeight: 700,
              color: 'var(--color-ec-text-primary)',
              letterSpacing: '-0.2px',
            }}>
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
