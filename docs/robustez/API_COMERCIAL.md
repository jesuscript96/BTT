# API comercial — Módulo `robustness` (Gateway B2D)

> Doc humano del contrato. La fuente de verdad de los campos es el PRD §3
> ([`PRD_ROBUSTEZ.md`](./PRD_ROBUSTEZ.md)). El contrato máquina vivo está en
> `GET /v1/openapi.json` y el snapshot en
> [`../b2d-gateway/openapi.generated.json`](../b2d-gateway/openapi.generated.json).

## Montaje

Módulo `backend/app/api_public/modules/robustness/`, montado por
`EDGECUTE_ENABLED_MODULES` (default incluye `robustness`). Toca el motor solo vía
`facade.py`; el guard `test_architecture.py` garantiza el aislamiento de IP.

- Auth: `Authorization: Bearer ek_(live|test)_…` (igual que `backtest`).
- Rate limit + metering: por API key (`usage_ledger`). Las llamadas de robustez
  registran `trades`/combos analizados; `ticker_days = 0` (no tocan datos de mercado).
- Gating: `gating_tag = "robustness"`. **La política (gratis/pago) la decide Jesús**
  (`docs/b2d-gateway/07`), no este código.

## Endpoints v1 (síncronos)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/v1/robustness/montecarlo` | Bootstrap Montecarlo (ruina, drawdowns P95/P99, retorno negativo, percentiles). |
| POST | `/v1/robustness/sensitivity` | Curvas por coste de locate + umbral crítico + slippage estocástico. |
| POST | `/v1/robustness/black-swan` | TTR, riesgo de ruina post-swan, matriz posición×severidad. |
| POST | `/v1/robustness/walk-forward` | **501 (v2).** Proceso pesado/async; disponible hoy en la app web. |

Cada body usa `run_id` (= id de un run guardado del Baúl, `backtest_results.id`).

## Errores (sin fugas)

`invalid_strategy` / `parameter_out_of_bounds` → 422 · `processing_error` → 500
(genérico, sin trazas) · `not_implemented` → 501 (walk-forward v2).

## MCP

Catálogo `mcp/src/components.ts` módulo `robustness` con componentes escogibles:
`montecarlo-spaghetti`, `drawdown-histogram`, `locate-sensitivity-chart`,
`blackswan-sensitivity-matrix`, `wfe-heatmap`. El cliente tipado se genera desde
`schema://openapi` (build-time).
