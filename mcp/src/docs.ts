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

export const PORTFOLIO_GLOSSARY = `# Glosario didáctico de Portfolio

Estos textos van LITERALES en la UI (tooltips/banners). Embébelos al construir la app.

## VaR (Value at Risk) 95% / 99%
Pérdida máxima esperable en un solo día bajo condiciones normales, para un nivel de
confianza dado. Ejemplo: un VaR diario al 95% de -$250 significa que hay un 95% de
probabilidad de que mañana tu cartera no pierda más de $250 (solo 1 de cada 20 días
sufrirás una pérdida mayor).
Fórmula: VaR_α(X) = -inf{ x : P(X ≤ x) > 1-α }, con X = retornos diarios agregados.

## CVaR (Expected Shortfall) 95% / 99%
"Si superamos la pérdida del VaR, ¿cuál es la pérdida media de ese peor escenario?".
Media de la cola del peor 5% (o 1%) de los días. Ejemplo: VaR 95% -$250 pero CVaR 95%
-$450 → si caes en ese 5% de peores días, la pérdida media esperada es $450.
Fórmula: CVaR_α(X) = 1/(1-α) ∫_α^1 VaR_u(X) du.

## Criterio de Kelly
% óptimo de la cuenta a arriesgar según win rate (p) y payoff ratio (b) para maximizar
crecimiento a largo plazo sin quebrar. Fractional Kelly (0.5, 0.25) reduce la volatilidad.
Fórmula: f* = p - (1-p)/b, con b = ganancia media / |pérdida media|.

## Correlación Pearson vs Spearman
Pearson mide relación LINEAL (sube proporcional los mismos días → ~+1 rojo; opuesto → -1
verde). Spearman mide relación NO lineal (monótona, por rangos): detecta si dos estrategias
ganan/pierden a la vez aunque la magnitud no sea proporcional. Spearman 0.85 → no diversifican;
-0.40 → cobertura que suaviza la curva.

## HRP (Hierarchical Risk Parity)
Método de López de Prado: clustering jerárquico sobre la covarianza, SIN invertir la matriz
→ robusto frente al ruido y evita concentrar todo en una estrategia sobreoptimizada. En
Edgecute se calcula in-house con scipy (sin riskfolio-lib).
`;
