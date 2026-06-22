# 02 — PRD para la IA (qué construimos y para quién)

> **Propósito:** definir el *qué* y el *para quién*, y fijar la **nomenclatura exacta de dominio**
> para que el agente de ejecución nombre variables y estructure datos sin inventar términos.

---

## 1. Visión en una frase

Exponer el motor de backtesting de gaps/short-selling de **Edgecute** como un **servicio
comercial (API + MCP)** para que traders-desarrolladores construyan, ejecuten y visualicen
backtests **desde su IDE local** (Cursor / Claude Code), **sin acceso a nuestra IP ni a nuestros
datos crudos**, pagando por uso.

## 2. Usuarios

| Perfil | Descripción | Necesidad | Cómo lo sirve |
|---|---|---|---|
| **Trader-dev indie** | Sabe programar (TS/Py), opera small-caps, quiere herramientas propias | No tiene datos intradía limpios ni motor de backtest serio | API + MCP: define universo+estrategia, recibe métricas |
| **Quant hobbyist** | Explora ideas, no quiere montar infra | Iterar rápido sobre estrategias | MCP en su IDE con plantillas de componentes |
| **Nosotros (interno)** | Operadores de Edgecute | Monetizar el motor existente sin rehacerlo | Fachada + metering sobre el motor actual |

**No-objetivo:** no servimos a quien quiere el *código del motor* ni los *datos OHLCV en bruto a
granel*. Eso es el moat.

## 3. Jobs-to-be-done (qué hace el usuario)

1. **Descubrir** qué se puede pedir (indicadores, filtros de universo, parámetros) → MCP `list_*`
   + Resources de docs.
2. **Definir un universo** por filtros (precio, float, market cap, gap %, shortable…) → contrato
   `UniverseSpec`.
3. **Definir/validar una estrategia** (entry/exit/risk) en el DSL → `validate_strategy`.
4. **Ejecutar** un backtest (async) y **recoger** métricas + curva de equity + trades.
5. **Visualizar** en local con componentes que consumen el JSON 1:1.
6. **Iterar** (cambiar un parámetro, re-ejecutar) y **comparar**.

## 4. Alcance del MVP (lo que SÍ entra)

- **API modular — módulo `backtest` (síncrona con cap):** `POST /v1/backtests` (devuelve `result`),
  `GET /v1/backtests/{id}`, intradía bajo demanda, `POST /v1/strategies/validate`,
  `POST /v1/universe/preview`, `GET /v1/catalog/indicators`, `GET /v1/openapi.json`, healthcheck.
  Servida bajo el armazón modular (doc 05 §0). (Async = v2.)
- **Core transversal:** auth por API-key, rate limit, **metering** (ledger) y **hook de gating por
  módulo** — el **mecanismo**, sin política (qué se cobra/bloquea es decisión diferida de producto).
- **MCP (build-time codegen + librería de componentes):** tools `list_modules`, `list_components`,
  `add_component`, `generate_api_client`, `get_types`, `validate_strategy`, `preview_universe`,
  `run_sample_backtest` (dev-only), `list_recipes`; resources `schema://*`, `docs://*`,
  `templates://backtest/*` (cada gráfica/métrica como pieza suelta). Ver doc 04.

> **El MCP NO ejecuta backtests de producción.** Construye la app del trader; la app generada
> consume la API directamente en runtime. Submodularización: el trader elige componentes sueltos y
> la selección decide qué datos (`include`) pide (doc 04 §1).

## 5. Fuera de alcance del MVP (explícito)

- **Política de monetización** (tiers, precios, qué se bloquea, a quién, cuándo): decisión de
  producto de Jesús, **diferida**. El MVP solo entrega metering + hook de gating (mecanismo).
- **Jobs async** del backtest (la API MVP es síncrona con cap; async es la vía de escalado v2).
- **Otros módulos** (`screener`, `ticker-analysis`, `optimization`, Monte Carlo, What-if): se añaden
  con la misma plantilla de módulo (doc 05 §0), pero son v2.
- Streaming de resultados parciales (v2).
- Datos fundamentales / noticias / SEC filings (no en esta API).
- Multi-estrategia con pesos/correlación (v2).
- Webhooks de "backtest terminado" (innecesario en sync; v2).

## 6. Glosario de dominio (NOMENCLATURA OFICIAL — usar exactamente estos nombres)

> Estos términos están tomados del código real. El agente de ejecución **debe** usar estos
> nombres en variables, claves JSON y docs. Fuente entre paréntesis.

### Universo y datos

| Término | Definición | Fuente |
|---|---|---|
| **dataset** / `dataset_id` | Conjunto guardado de pares ticker–fecha "cualificados" + su intradía precacheada | `query.py`, `BacktestRequest.dataset_id` |
| **universe / UniverseSpec** | Filtros que definen qué tickers-días entran (precio, float, gap…) | `UniverseFilters` (`strategy.py`) |
| **qualifying data** | Pares ticker–fecha que pasan los filtros del universo | `fetch_qualifying_data` |
| **gap day** (`gap_day`) | El día del hueco (evento principal) | `apply_day` |
| **gap+1 / gap+2** (`gap_1_day`, `gap_2_day`) | El día siguiente / 2 días después del gap | `apply_day` |
| **postgap precondition** | Filtro sobre el comportamiento del precio el gap day / gap+1 | `PostGapPrecondition` |
| **intraday 1m** | Velas de 1 minuto: `{time, open, high, low, close, volume, vwap}` | `generate_mock_candles`, hot storage |
| **market session** | `PM` (04:00–09:30), `RTH` (09:30–16:00), `AM`/post (16:00–20:00) | `_get_market_sessions_mask` |

### Estrategia (DSL)

| Término | Definición | Fuente |
|---|---|---|
| **bias** | Dirección: `long` \| `short` | `StrategyCreate.bias` |
| **entry_logic / exit_logic** | Árbol de condiciones (AND/OR) sobre indicadores | `EntryLogic`, `ExitLogic` |
| **indicator** | Uno de ~90 indicadores (SMA, VWAP, RSI, PM High…) | `IndicatorType` |
| **comparator** | `GREATER_THAN`, `LESS_THAN`, `CROSSES_ABOVE`… | `Comparator` |
| **candle pattern** | `RED_VOLUME`, `DOJI`, `HAMMER`… | `CandlePattern` |
| **risk_management** | Hard stop, take profit, trailing, reentries | `RiskManagement` |
| **hard_stop** | Stop por `Percentage` / `ATR Multiplier` / `Fixed Amount` / `Market Structure` | `RiskType` |
| **take_profit** | Objetivo (Full / Partial) | `TakeProfitMode` |
| **trailing_stop** | Stop que solo se endurece a favor | `RiskManagement.trailing_stop` |
| **swing_option** | Mantener overnight hacia `gap_1_day`/`gap_2_day` | `RiskManagement.swing_option` |

### Ejecución (parámetros del backtester)

| Término | Definición | Fuente |
|---|---|---|
| **init_cash** | Capital inicial | `BacktestRequest.init_cash` |
| **risk_r** (R) | USD arriesgados por trade; el sizing iguala el riesgo a R | `BacktestRequest.risk_r` |
| **risk_type** | `FIXED` \| `PERCENT` \| `FIXED_RATIO` | `BacktestRequest.risk_type` |
| **size_by_sl** | Dimensionar posición por distancia al stop | `BacktestRequest.size_by_sl` |
| **fees / fee_type** | Comisión (`PERCENT` o por share) | `BacktestRequest.fees` |
| **slippage** | % que empeora entrada y salida | `BacktestRequest.slippage` |
| **locates_cost** | Coste por cada 100 acciones (short) | `BacktestRequest.locates_cost` |
| **look_ahead_prevention** | Desplaza señales 1 barra (anti-lookahead) | `BacktestRequest.look_ahead_prevention` |
| **monthly_expenses** | Gastos fijos mensuales a descontar | `BacktestRequest.monthly_expenses` |

### Resultados (métricas — claves EXACTAS del JSON)

> Las claves de `aggregate_metrics` son **literales** de `_aggregate_metrics()`. No renombrar.

| Clave | Significado |
|---|---|
| `total_trades` | Nº de trades cerrados |
| `win_rate_pct` | % de trades ganadores |
| `total_pnl` / `total_pnl_net` | PnL bruto / neto de gastos |
| `total_return_pct` | Retorno total sobre `init_cash` |
| `avg_return_per_day_pct` | Retorno medio por día |
| `avg_sharpe` | Sharpe (anualizado interno) |
| `sortino_ratio` | Sortino |
| `calmar_ratio` | Calmar |
| `max_drawdown_pct` | Máximo drawdown |
| `dd_return_ratio` | Retorno / drawdown |
| `avg_profit_factor` | Profit factor medio |
| `expectancy` | Esperanza por trade |
| `payoff_ratio` | Avg win / avg loss |
| `avg_win` / `avg_loss` | Media de ganadores / perdedores |
| `max_consecutive_wins` / `..._losses` | Rachas |
| `avg_r_per_day` / `avg_r_ui` | R medios |
| `max_mae` | Máxima excursión adversa |
| `total_expenses` | Gastos totales |
| `r_squared` | R² de la curva de equity |

| Objeto | Claves |
|---|---|
| **trade** | `ticker, date, entry_time, exit_time, entry_price, exit_price, pnl, fees, return_pct, direction, status, size, exit_reason, mae, mfe, r_multiple, entry_hour, entry_weekday, gap_pct, stop_loss` |
| **day_result** | `ticker, date, total_return_pct, max_drawdown_pct, win_rate_pct, total_trades, profit_factor, sharpe_ratio, sortino_ratio, expectancy, best_trade_pct, worst_trade_pct, init_value, end_value, gap_pct` |
| **equity point** | `{time, value}` (epoch segundos, USD) — formato lightweight-charts |

## 7. Métricas de éxito del producto

- **Activación:** un trader pasa de `npx edgecute-mcp` a su primer backtest con resultado en
  **< 10 min** sin leer más que el README.
- **Robustez de contrato:** 0 errores de tipo entre lo documentado (OpenAPI) y lo que devuelve la
  API (test de contrato en CI).
- **Aislamiento:** 0 respuestas con traces/nombres internos (test de fuzzing de errores).
- **Negocio:** coste de CPU por backtest < precio de crédito consumido (margen positivo por uso).

## 8. Principios de diseño (para el agente de ejecución)

1. **El backend real manda.** Si el código y un doc discrepan, gana el código; abrir incidencia.
2. **No tocar el motor.** `engine.py`, `indicators.py`, schema de `daily_metrics`/`intraday_1m`
   están en la lista "no tocar sin consenso" (`CODING_RULES.md`). La API es una **capa nueva**.
3. **Contrato derivado, no escrito a mano.** El OpenAPI sale de modelos Pydantic; los tipos TS del
   MCP salen del OpenAPI (`openapi-typescript`).
4. **Fail loud, leak nothing.** Errores accionables para el LLM, opacos sobre la IP.
