/** Documentation served as MCP resources (read on demand — keeps the LLM context
 *  small; docs/b2d-gateway/04 §3). */

export const GETTING_STARTED = `# Edgecute Backtest MCP — Quickstart

El MCP es **build-time**: te ayuda a CONSTRUIR tu app en Cursor / Claude Code. En
runtime, tu app llama a la API directamente (el cliente que genera el MCP).

## 1. Configura el MCP
\`\`\`jsonc
// .cursor/mcp.json
{ "mcpServers": { "edgecute": {
  "command": "npx", "args": ["-y", "@edgecute/mcp"],
  "env": { "EDGECUTE_API_KEY": "ek_test_…" }   // sandbox para construir
}}}
\`\`\`

## 2. Genera el cliente y elige componentes
- \`generate_api_client\` → cliente tipado en tu repo.
- \`list_components\` → ves las piezas (equity, métricas, trades, días…).
- \`add_component equity-chart\` y \`add_component trades-table\` → solo lo que vas a pintar.
  (Cada componente te dice qué \`include\` pedir: así no descargas lo que no usas.)

## 3. Valida y prueba
- \`validate_strategy\` → comprueba tu estrategia (sin gastar nada).
- \`preview_universe\` → cuántos ticker-días costaría.
- \`run_sample_backtest\` → ves datos reales contra el sandbox mientras construyes.

## 4. Runtime (tu app)
\`\`\`ts
const c = new EdgecuteClient({ apiKey: process.env.EDGECUTE_API_KEY! });
const job = await c.runBacktest({
  universe: { dataset_ref: "ds_123", date_from: "2024-01-01", date_to: "2024-03-31" },
  strategy: {/* … */},
  include: ["metrics", "equity"],   // solo lo que renderizas
});
// <EquityChart data={job.result!.global_equity!} />
\`\`\`
`;

export const METRICS_GLOSSARY = `# Glosario de métricas (aggregate_metrics)

| Clave | Significado |
|---|---|
| total_trades | Nº de trades cerrados |
| win_rate_pct | % de trades ganadores |
| total_pnl / total_pnl_net | PnL bruto / neto de gastos |
| total_return_pct | Retorno total sobre el capital inicial |
| avg_sharpe | Sharpe (anualizado) |
| sortino_ratio | Sortino |
| calmar_ratio | Calmar |
| max_drawdown_pct | Máximo drawdown |
| dd_return_ratio | Retorno / drawdown |
| avg_profit_factor | Profit factor medio |
| expectancy | Esperanza por trade |
| payoff_ratio | Avg win / avg loss |
| avg_win / avg_loss | Media de ganadores / perdedores |
| max_consecutive_wins / _losses | Rachas |
| avg_r_per_day / avg_r_ui | R medios |
| max_mae | Máxima excursión adversa |
| total_expenses | Gastos totales |
| r_squared | R² de la curva de equity |

Nota: cualquier métrica puede venir \`null\` (el motor sanea NaN/inf a null).
`;

export const STRATEGY_SCHEMA_NOTE = `# Esquema de estrategia

La forma completa y autoritativa del objeto \`Strategy\` está en el OpenAPI vivo
(\`schema://openapi\`) y se valida con \`validate_strategy\`. Resumen:

\`\`\`jsonc
{
  "name": "VWAP fade short",
  "bias": "short",                  // "long" | "short"
  "apply_day": "gap_day",           // gap_day | gap_1_day | gap_2_day
  "entry_logic": {
    "timeframe": "1m",
    "root_condition": {
      "type": "group", "operator": "AND",
      "conditions": [
        { "type": "indicator_comparison",
          "source": { "name": "Bar Close" },
          "comparator": "CROSSES_BELOW",
          "target": { "name": "VWAP" } }
      ]
    }
  },
  "exit_logic": { /* misma forma; opcional */ },
  "risk_management": {
    "use_hard_stop": true,
    "hard_stop": { "type": "Percentage", "value": 3.0 },
    "use_take_profit": true,
    "take_profit": { "type": "Percentage", "value": 6.0 }
  }
}
\`\`\`

Los indicadores válidos (\`source.name\` / \`target.name\`) salen de \`list_indicators\`.
`;
