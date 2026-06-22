# 03 — Contrato de datos (la frontera inquebrantable)

> **Propósito:** definir el JSON de entrada (lo que el trader rellena) y el de salida (lo que la
> API devuelve), derivados del **backend real**. Con esto, el MCP se puede mockear y construir sin
> tocar el motor. El artefacto ejecutable es [`openapi.draft.yaml`](openapi.draft.yaml).

---

## 0. Reglas del contrato

1. **Versionado:** prefijo `/v1`. Cambios incompatibles → `/v2`. Campos nuevos opcionales no rompen.
2. **Identificadores opacos:** `job_id`, `api_key` no revelan internals. `job_id = "bt_<ulid>"`.
3. **Errores con forma fija** (ver §6). Nunca traces.
4. **El contrato se genera del backend**, no se escribe a mano (ver doc 06, tarea de generación).
5. **Snake_case** en todo el JSON (coincide con el backend Python actual).

---

## 1. Autenticación

- Header: `Authorization: Bearer <api_key>` donde `api_key = "ek_live_…" | "ek_test_…"`.
- **No** Clerk JWT: Clerk (`auth/clerk.py`) es para la sesión web humana. La API B2D usa
  **API-keys propias** (largas, revocables, con scope y rate-limit por key). Justificación en doc 05.
- Toda ruta `/v1/*` excepto `/v1/health` y `/v1/openapi.json` exige key válida.

---

## 2. Recurso: Universe (definición del universo)

`UniverseSpec` — qué tickers-días entran. Mapea a `UniverseFilters` + rango de fechas + postgap.

```jsonc
{
  "date_from": "2023-01-01",          // requerido
  "date_to":   "2023-12-31",          // requerido
  "apply_day": "gap_day",             // "gap_day" | "gap_1_day" | "gap_2_day"
  "filters": {                          // todos opcionales (UniverseFilters)
    "min_price": 1.0,
    "max_price": 20.0,
    "min_volume": 1000000,
    "max_market_cap": 500000000,
    "max_shares_float": 50000000,
    "require_shortable": true,
    "exclude_dilution": true
  },
  "postgap_preconditions": [            // opcional (PostGapPrecondition[])
    { "id": "p1", "day": "gap_day", "metric": "close_vs_open", "operator": ">", "value": 0 }
  ]
}
```

> **Nota:** en lugar de exigir un `dataset_id` interno (que el trader no conoce), la API acepta un
> `UniverseSpec` y **resuelve el dataset server-side**. Opcionalmente, si el trader ya creó un
> universo nombrado, puede referenciarlo por un `universe_ref` que devolvimos antes.

### `POST /v1/universe/preview`

Devuelve el **tamaño** del universo sin ejecutar el backtest (para presupuestar créditos):

```json
{ "ticker_days": 4213, "tickers": 318, "date_from": "2023-01-01", "date_to": "2023-12-31",
  "estimated_credits": 42, "within_plan_limit": true }
```

---

## 3. Recurso: Strategy (DSL de estrategia)

Espejo de `StrategyCreate` (`backend/app/schemas/strategy.py`). Estructura abreviada:

```jsonc
{
  "name": "VWAP fade short",
  "bias": "short",                       // "long" | "short"
  "apply_day": "gap_day",
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
    "take_profit": { "type": "Percentage", "value": 6.0 },
    "trailing_stop": { "active": false }
  }
}
```

- **Catálogo de `indicator.name`:** los ~90 valores de `IndicatorType` (`schema://strategy` +
  `GET /v1/catalog/indicators`). No se duplican aquí para no inflar contexto (ver doc 01 §1.3).
- **`comparator`:** valores de `Comparator`.
- **Validación:** `POST /v1/strategies/validate` valida la estrategia contra el modelo **Pydantic
  `StrategyCreate`** (`backend/app/schemas/strategy.py`) y devuelve `{ valid, errors:[{path,message}] }`
  **antes** de ejecutar. Es standalone y no toca el motor. *(Nota: `backtester/backtest_validator.py`
  NO sirve para esto — valida resultados contra VectorBT, no la estrategia de entrada.)*

---

## 4. Recurso: Backtest (entrada de ejecución)

Espejo de `BacktestRequest` + el universo y la estrategia inline. **El "formulario".**

> **MVP = síncrono con cap (decisión de Jesús, doc 01 §1.1-bis).** `POST /v1/backtests` ejecuta y
> devuelve el resultado **en la misma respuesta** (`200`), igual que el `/backtest` actual, siempre
> que el universo esté bajo el cap del plan. El progreso, si se quiere barra, se consulta por
> polling separado de `GET /v1/backtests/{id}` mientras la respuesta está en vuelo (o se omite).
> **El campo `status` ya está en el contrato**, así que el día que se active el modo async (v2,
> universos grandes → `202 + job_id`) **no se rompe ningún cliente**: el cliente ya sabe mirar
> `status` (`succeeded` directo en sync, `queued`/`running` en async).

### `POST /v1/backtests` → `200 OK` (sync MVP) · `202 Accepted` (async v2)

```jsonc
{
  "universe": { /* UniverseSpec §2  (o "universe_ref": "uni_…") */ },
  "strategy": { /* Strategy DSL §3   (o "strategy_ref": "st_…") */ },
  "execution": {
    "init_cash": 10000,
    "risk_r": 100,
    "risk_type": "FIXED",                 // FIXED | PERCENT | FIXED_RATIO
    "size_by_sl": false,
    "fees": 0.0,
    "fee_type": "PERCENT",                // PERCENT | PER_SHARE
    "slippage": 0.0,
    "locates_cost": 0.0,
    "monthly_expenses": 0.0,
    "market_sessions": ["RTH"],          // PM | RTH | AM | custom
    "custom_start_time": null,
    "custom_end_time": null,
    "look_ahead_prevention": false
  },
  "include": ["metrics", "equity", "days"],  // qué secciones devolver (ver §5)
  "trades_limit": 500
}
```

Respuesta **sync (MVP)** — el resultado viene ya en el cuerpo (ver §5):

```json
{ "job_id": "bt_01HZX…", "status": "succeeded", "meta": { "credits_charged": 42, … },
  "result": { /* aggregate_metrics, global_equity, day_results, … */ } }
```

Respuesta **async (v2, universos grandes)**:

```json
{ "job_id": "bt_01HZX…", "status": "queued", "estimated_credits": 42,
  "poll_after_ms": 1500, "links": { "self": "/v1/backtests/bt_01HZX…" } }
```

### `GET /v1/backtests/{job_id}`

```json
{ "job_id": "bt_01HZX…", "status": "running", "progress": { "percent": 63.0,
  "current": 2650, "total": 4213 } }
```

Estados: `queued` → `running` → `succeeded` | `failed` | `cancelled`. (`progress` reusa la forma
de `/api/backtest/progress` actual.)

### `POST /v1/backtests/{job_id}/cancel` → cancela (reusa `cancel_backtest`).

---

## 5. Recurso: BacktestResult (salida)

Cuando `status == "succeeded"`, `GET /v1/backtests/{id}` incluye `result`. **Derivado 1:1 del
return de `run_backtest()`**, con las reglas de payload del doc 01:

```jsonc
{
  "job_id": "bt_01HZX…",
  "status": "succeeded",
  "meta": {
    "ticker_days": 4213, "trades_total": 1827, "credits_charged": 42,
    "engine_ms": 38120, "downsampled": true
  },
  "result": {
    "aggregate_metrics": { "total_trades": 1827, "win_rate_pct": 41.2, "total_pnl": 12840.5,
      "total_pnl_net": 11920.0, "total_return_pct": 128.4, "avg_sharpe": 1.83,
      "sortino_ratio": 2.41, "calmar_ratio": 1.12, "max_drawdown_pct": 18.7,
      "avg_profit_factor": 1.34, "expectancy": 7.02, "payoff_ratio": 1.9,
      "avg_win": 41.3, "avg_loss": -21.7, "max_consecutive_wins": 9,
      "max_consecutive_losses": 7, "avg_r_per_day": 0.21, "max_mae": -312.0,
      "total_expenses": 920.5, "r_squared": 0.88
      /* …todas las claves de _aggregate_metrics()… */ },

    "global_equity":   [ { "time": 1672531200, "value": 10000 }, … ],   // por trade, downsampled
    "global_drawdown": [ { "time": 1672531200, "value": 0.0 }, … ],
    "day_results":     [ { "ticker": "AAPL", "date": "2023-03-01", "total_return_pct": 1.2,
      "max_drawdown_pct": 0.8, "win_rate_pct": 50, "total_trades": 4, "profit_factor": 1.6,
      "sharpe_ratio": 0.9, "sortino_ratio": 1.1, "expectancy": 5.0, "best_trade_pct": 3.1,
      "worst_trade_pct": -1.2, "init_value": 10000, "end_value": 10120, "gap_pct": 12.4 }, … ],

    "trades": {                                  // SOLO si "trades" ∈ include
      "items": [ { "ticker": "AAPL", "date": "2023-03-01", "entry_time": "...", "exit_time": "...",
        "entry_price": 10.2, "exit_price": 9.8, "pnl": 38.0, "fees": 0.5, "return_pct": -3.9,
        "direction": "short", "status": "closed", "size": 95, "exit_reason": "Take Profit",
        "mae": -0.4, "mfe": 0.6, "r_multiple": 1.7, "entry_hour": 9, "entry_weekday": 2,
        "gap_pct": 12.4, "stop_loss": 10.5 } ],
      "page": { "limit": 500, "returned": 500, "next_cursor": "c_…", "total": 1827 },
      "export_url": "https://…signed…/trades.parquet?exp=…"   // set completo, expira 1h
    }
  }
}
```

### `include` (control de payload — doc 01 §1.1)

| Valor | Devuelve |
|---|---|
| `metrics` | `aggregate_metrics` (siempre recomendado) |
| `equity` | `global_equity` + `global_drawdown` (downsampled si grande) |
| `days` | `day_results` |
| `trades` | objeto `trades` paginado + `export_url` |

> **`equity_curves` intradía NO está en `include`.** Se pide por separado:

### `GET /v1/backtests/{id}/intraday?ticker=AAPL&date=2023-03-01`

Devuelve **una** serie `equity_curves` de un ticker-día: `{ ticker, date, equity: [{time,value}] }`.
Acotado a una serie por llamada.

---

## 6. Errores (forma fija, sin fugas — doc 01 §1.2)

```json
{ "error": { "code": "universe_too_large",
  "message": "El universo (128430 ticker-días) supera el límite de tu plan (20000).",
  "request_id": "req_01HZ…", "details": { "ticker_days": 128430, "limit": 20000 } } }
```

Catálogo cerrado de `code` (no exhaustivo): `unauthorized`, `invalid_api_key`,
`rate_limited`, `insufficient_credits`, `universe_too_large`, `invalid_strategy`,
`invalid_universe`, `job_not_found`, `job_failed`, `validation_error`, `internal_error`.

- `internal_error` **nunca** lleva detalle interno; el trace va a logs server-side por `request_id`.
- HTTP status: 401, 403, 404, 409 (job en estado incompatible), 422 (validación), 429, 500.

---

## 7. Mapa de equivalencias (API pública ↔ backend real)

| Campo API (`/v1`) | Origen backend | Notas |
|---|---|---|
| `execution.init_cash` | `BacktestRequest.init_cash` | idéntico |
| `execution.risk_r` | `BacktestRequest.risk_r` | idéntico |
| `execution.fee_type=PER_SHARE` | `fee_type="PERCENT"`-alterno | confirmar enum real en ejecución |
| `universe.*` | `UniverseFilters` + `_resolve_filters` | resuelve `dataset_id` server-side |
| `strategy.*` | `StrategyCreate` | 1:1 |
| `result.aggregate_metrics` | `_aggregate_metrics()` | claves literales |
| `result.trades.items` | `_enrich_trades()` | paginado |
| `result.global_equity` | `_compute_global_equity_and_drawdown()` | downsampling LTTB |
| intraday endpoint | `equity_curves` de `run_backtest()` | una serie/llamada |

> ⚠️ El agente de ejecución debe **leer el backend en el momento** y reconciliar cualquier
> divergencia (p.ej. el enum exacto de `fee_type`, o claves de `day_result`) — el código es la
> verdad. Los tests de contrato (doc 06) bloquean drift.
