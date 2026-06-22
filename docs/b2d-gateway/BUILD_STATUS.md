# BUILD STATUS — Edgecute Backtest API + MCP (MVP)

> Estado real de lo construido. Para revisión del CTO. Rama `api-jesus`.

## ✅ Construido y verificado

### API pública (`backend/app/api_public/`) — 36 tests verde
- **Arquitectura modular**: `core/` transversal + `modules/backtest/`. Montaje genérico por
  `EDGECUTE_ENABLED_MODULES`. Cada módulo activable y gateable por separado.
- **Aislamiento de IP**: solo `facade.py` toca el motor (imports perezosos vía el orquestador).
  Guard de imports en test (`test_architecture.py`) — falla si algún módulo importa el motor.
- **Errores sin fugas**: handler propio; test que fuerza error interno y comprueba que NO sale
  trace/`str(exc)` (`test_internal_error_does_not_leak`).
- **Auth API-key** (hash SHA-256, prefijo `ek_live_`/`ek_test_`, owner = Clerk user_id), revocación.
- **Gating por módulo**: hook `can_access` con **default permitir** + `set_policy` (mecanismo, sin política).
- **Metering**: `usage_ledger` con ticker-days/trades reales del motor.
- **Rate limit** en proceso (token-bucket por key).
- **Reglas de payload**: downsample LTTB de equity, paginación de trades por cursor, `include` selectivo,
  intradía bajo demanda (nunca por defecto).
- **Endpoints v1**: health, openapi.json, catalog/indicators, strategies/validate (Pydantic),
  universe/preview, backtests (síncrono+cap), backtests/{id}, /intraday, /cancel.
- **Admin CLI** (`admin.py`): create/revoke/usage de API keys.
- **Store**: SQLite (zero-infra); abstracción para Postgres (v2).

### MCP (`mcp/`, TypeScript estricto) — 17 tests verde + e2e
- **9 tools**: list_modules, list_components, add_component, generate_api_client, get_types,
  validate_strategy, preview_universe, run_sample_backtest (dev-only), list_recipes.
- **Resources**: docs://*, schema://openapi (vivo), templates://backtest/{component}.
- **Prompts**: design_strategy, build_dashboard, analyze_results.
- **Submodularización**: 6 componentes de resultado escogibles sueltos; cada uno declara su `include`.
- **Cliente HTTP tipado** con backoff (429/5xx) y parsing del envelope de error.
- **Probado**: tsc estricto (0 errores), build, vitest, y **e2e con cliente MCP real por stdio**
  + **costura MCP → API en vivo** (validate_strategy y schema://openapi contra uvicorn).

### Verificaciones cruzadas hechas
- `fee_type` corregido a `PERCENT|FLAT` (el motor no soporta `PER_SHARE`) — evita cálculo erróneo silencioso.
- Plataforma de deploy: Railway + uvicorn (envelope ya probado por el `/backtest` síncrono actual).
- `BacktestRequest` ↔ mapper: campos verificados 1:1 contra el orquestador real.

## 🔜 Fuera del MVP (decidido, no es fallo)
- **Universo por filtros** → v2 (requiere pipeline screener+precache). Hoy: `dataset_ref` + `mock_dataset_1`. Devuelve `not_implemented` accionable.
- **Jobs async** → v2 (el `status` ya deja sitio; sin romper contrato).
- **Política de monetización** (tiers/precios/quién-se-bloquea) → decisión de producto diferida; el MVP entrega solo el mecanismo.
- Otros módulos (screener, ticker-analysis, optimization, Monte Carlo, what-if), webhooks, multi-estrategia.

## ▶️ Cómo arrancar
```bash
# API
cd backend && uvicorn app.api_public.app:app --port 8100
python -m app.api_public.admin create-key --owner <clerk_id> --test
# tests
.venv_313/bin/python -m pytest app/api_public/tests -q
# MCP
cd mcp && npm install && npm run build && npm test
node scripts/smoke-e2e.mjs
```

## ⚠️ Lo único pendiente para producción real
- Ejecutar un backtest real end-to-end requiere datos/dataset reales (MotherDuck/GCS): la API llama
  al MISMO `run_backtest_orchestrator` que ya usa la web app en prod. Validado localmente con la
  fachada simulada; el motor tiene su propia suite (`backend/tests/`).
- Load test para fijar `EDGECUTE_MAX_TICKER_DAYS` con margen al envelope de Railway.
