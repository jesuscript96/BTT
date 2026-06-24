# 04 — Servidor MCP: codegen + librería de componentes + docs

> **Decisión (firmada por Jesús):** el **Edgecute MCP es una herramienta de BUILD-TIME**. Lo usa el
> trader en Cursor / Claude Code **para construir su app local**. Una vez construida, **la app del
> trader consume la API directamente** (HTTP), sin pasar por el MCP en runtime.
>
> **Implicación:** el MCP NO está en el hot path de producción, NO ejecuta backtests pesados, NO
> necesita encapsular polling robusto. Es un servidor de **generación de código + catálogo de
> componentes submodularizados + documentación/tipos**.

---

## 0. Qué es y qué no es

- ✅ **Es** un servidor MCP de *developer experience*: genera el cliente tipado de la API, andamia
  componentes de UI granulares (cada gráfica/métrica por separado), sirve docs/esquemas, y valida
  estrategias/universos en build-time (barato, sin gastar créditos de producción).
- ❌ **No es** el runtime. El backtest de producción lo lanza **la app del trader** llamando a la API.
- ❌ **No es** el asistente in-app "Edgie" (`frontend/src/lib/assistant/`), que opera la UI por el
  navegador. Reutilizamos su filosofía: tools con `{ ok, result?, error? }` y errores accionables.
- **Lenguaje:** TypeScript estricto con `@modelcontextprotocol/sdk` (ecosistema de Cursor/Claude Code).

### Por qué build-time-only es el MVP correcto

- Quita del medio el único motivo real del "async obligatorio": **el timeout del LLM** (~30–120 s).
  En runtime, la app del trader es un cliente HTTP normal que puede esperar/poll igual que la web app
  de Edgecute (ver doc 01 §1.1-bis). → la API MVP puede ser **síncrona con cap** (doc 03/05).
- El MCP queda simple, sin SPOF en producción, y enfocado en lo que aporta: **DX + codegen**.

> **Matiz (challenge aceptado):** se mantiene **una** tool de *muestra* (`run_sample_backtest`)
> contra el sandbox `ek_test_` para que el dev vea datos reales mientras construye. Es conveniencia
> de desarrollo, **no** el camino de runtime de producción. Su descripción lo deja explícito.

---

## 1. Principio rector: submodularización (la selección de componente determina los datos)

> Responde directo a "el trader puede no querer todo": **cada pieza del resultado es un módulo
> independiente**, y **elegir un componente decide qué `include` pide su data** (doc 03 §5).
> "No quiero todo" es el comportamiento por defecto y de paso es lo que hace eficiente la carga.

```
módulo            →  componente (escogible suelto)        →  datos que necesita (include)
─────────────────────────────────────────────────────────────────────────────────────────
backtest.metrics  →  metric_card (una métrica)            →  include=["metrics"]
backtest.metrics  →  metrics_grid (subconjunto elegible)  →  include=["metrics"]
backtest.equity   →  equity_chart                         →  include=["equity"]
backtest.equity   →  drawdown_chart                       →  include=["equity"]
backtest.trades   →  trades_table (columnas elegibles)    →  include=["trades"] (+paginado)
backtest.days     →  day_results_table / calendar_heatmap →  include=["days"]
backtest.analysis →  mae_scatter                          →  include=["trades"]
backtest.analysis →  rolling_ev_chart                     →  include=["trades"]
backtest.analysis →  rolling_avg_r_chart                  →  include=["trades"]
backtest.intraday →  intraday_chart (1 ticker-día)        →  endpoint /intraday (bajo demanda)
```

- Cada componente **declara** su `include` y su paginación → el código generado para runtime pide
  **solo eso**. Pides el Sharpe suelto y no se descarga ni un trade.
- **Otros módulos** (screener, ticker-analysis, optimization…) siguen el MISMO patrón
  `módulo → componente → datos`, así el catálogo crece sin rearquitectura. MVP cubre `backtest.*`.
- Origen real de las plantillas (se adaptan, quitando deps internas):
  `MetricsCard.tsx`, `TradeTable.tsx`, `MaeScatterChart.tsx`, `RollingEVChart.tsx`,
  `RollingAvgRChart.tsx`, `EquityCurveTab.tsx`, `Chart.tsx` (todas en `frontend/src/components/backtester/`).

---

## 2. Tools (build-time)

> Todas devuelven `{ ok, result?, error? }`; `error` siempre accionable.

| Tool | Entrada | Hace |
|---|---|---|
| `list_modules` | — | Lista módulos disponibles (`backtest.*` en MVP) y su estado |
| `list_components` | `module?` | Catálogo de componentes granulares + qué `include`/datos consume cada uno |
| `add_component` | `{ component, target_path?, options? }` | **Escribe en el repo del trader** UNA pieza (p.ej. `equity_chart`), con sus props tipadas, el `include` que necesita y el snippet de llamada a la API |
| `generate_api_client` | `{ target_path?, lang? }` | Emite el **cliente tipado** de la API desde el OpenAPI (`openapi-typescript`) en el proyecto del dev |
| `get_types` | `{ name? }` | Devuelve tipos TS (Strategy, UniverseSpec, BacktestResult…) para pegar/importar |
| `validate_strategy` | `Strategy` | Valida el DSL en build-time (API `/strategies/validate`, sin créditos de prod) |
| `preview_universe` | `UniverseSpec` | Estima ticker-días/créditos para que el dev presupueste (sin ejecutar) |
| `run_sample_backtest` | `{ strategy, universe?, include? }` | **Dev-only**: backtest pequeño contra sandbox `ek_test_` para ver forma real de datos |
| `list_recipes` | `tag?` | Recetas de estrategias/dashboards listas para scaffolding |

### Errores accionables (estilo `catalogo_tools.md`)

```json
{ "ok": false, "error": "No existe el componente 'equity_graph'. ¿Quizá 'equity_chart'? Lista: list_components(module='backtest.equity')." }
{ "ok": false, "error": "Estrategia inválida — entry_logic…source.name: 'VWHAP' no es indicador. ¿'VWAP'? Ver schema://strategy." }
```

---

## 3. Resources (docs, esquemas, plantillas — leídos bajo demanda)

> Fuera del contexto base; el LLM los pide cuando los necesita (presupuesto de tokens, doc 01 §1.3).

| URI | Tipo | Contenido |
|---|---|---|
| `schema://strategy` | JSON Schema | DSL completo de estrategia (de `StrategyCreate`) |
| `schema://universe` | JSON Schema | `UniverseSpec` completo |
| `schema://backtest-result` | JSON Schema | Forma del resultado (del backend) |
| `docs://getting-started` | MD | De `npx` a app que renderiza un backtest en < 10 min |
| `docs://indicators` | MD | Los ~90 indicadores (de `BACKTESTER_BRAIN.md`) |
| `docs://metrics-glossary` | MD | Definición exacta de cada métrica de salida (doc 02 §6) |
| `docs://recipes` | MD | Recetas de estrategia + dashboards |
| `templates://backtest/equity-chart` | TSX | Componente lightweight-charts para `global_equity` (consume 1:1) |
| `templates://backtest/drawdown-chart` | TSX | Para `global_drawdown` |
| `templates://backtest/metric-card` | TSX | Una métrica suelta de `aggregate_metrics` |
| `templates://backtest/metrics-grid` | TSX | Grid con subconjunto elegible de métricas |
| `templates://backtest/trades-table` | TSX | Tabla paginada (columnas configurables) de `trades.items` |
| `templates://backtest/day-results-table` | TSX | Tabla de `day_results` |
| `templates://backtest/mae-scatter` | TSX | Adaptado de `MaeScatterChart.tsx` |
| `templates://backtest/rolling-ev-chart` | TSX | Adaptado de `RollingEVChart.tsx` |
| `templates://backtest/rolling-avg-r-chart` | TSX | Adaptado de `RollingAvgRChart.tsx` |
| `templates://backtest/intraday-chart` | TSX | Candles + equity para `/intraday` (bajo demanda) |

### Por qué las plantillas encajan sin fricción (doc 01 §1.3)

Las series ya vienen en `{time, value}` (formato lightweight-charts), idéntico al del front de
Edgecute. Las plantillas se adaptan de los componentes reales; el trader renderiza sin transformar.

---

## 4. Prompts MCP (opcional, alto valor)

| Prompt | Para qué |
|---|---|
| `design_strategy` | Guía a construir una `Strategy` válida paso a paso, validando con `validate_strategy` |
| `build_dashboard` | Hace `add_component` de varias piezas elegidas y las cablea al cliente generado |
| `analyze_results` | Interpreta `aggregate_metrics` (overfitting, drawdown, expectancy) con el glosario |

---

## 5. Configuración en el IDE del cliente

```jsonc
// .cursor/mcp.json  o  settings de Claude Code
{
  "mcpServers": {
    "edgecute": {
      "command": "npx",
      "args": ["-y", "@edgecute/mcp"],
      "env": { "EDGECUTE_API_KEY": "ek_test_…" }   // sandbox para construir; ek_live_ para la app
    }
  }
}
```

- La API-key se inyecta por env; el MCP nunca la loguea. En build-time se recomienda `ek_test_`.
- La **app generada** lee su propia key (`ek_live_…`) de SU entorno, no del MCP.

---

## 6. Flujo de uso (end-to-end)

```
1. Trader en Cursor:  "monta una app que backtestee fades de VWAP en short y muestre
                       equity + tabla de trades, sin métricas que no use"
2. MCP → generate_api_client           (cliente tipado en su repo)
3. MCP → validate_strategy             (la estrategia que el dev escribe en código es válida)
4. MCP → add_component equity-chart     (+ include=["equity"])
   MCP → add_component trades-table     (+ include=["trades"])
   (no añade metrics-grid → su app no descargará métricas que no pinta)
5. MCP → run_sample_backtest (ek_test_) (el dev ve datos reales mientras desarrolla)
6. Deploy de SU app → en runtime llama a la API con ek_live_, pidiendo solo include=["equity","trades"]
```

---

## 7. Contrato de calidad del MCP (DoD, doc 06)

1. **Tipos generados, no a mano:** todo sale del `openapi.draft.yaml` (`openapi-typescript`). Drift → build roto.
2. **Sin lógica de trading** en el MCP: solo codegen, scaffolding, validación de forma y docs.
3. **Componentes verificables:** cada plantilla compila y renderiza con un `result` de ejemplo en un Next mínimo.
4. **Footprint de contexto:** estado base (lista de tools) < ~1.5k tokens; detalle en Resources.
5. **Tests:** cada tool contra un **mock server** del OpenAPI; `add_component` produce ficheros que compilan.
6. **`run_sample_backtest` aislado:** solo `ek_test_`/sandbox; marcado dev-only; nunca camino de runtime.
