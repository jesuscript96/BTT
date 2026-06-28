# 04 — API comercial · MCP · PostHog (las tres capas transversales)

> Esto es lo que pidió Jesús explícitamente: que el portfolio **también** viva en la API
> comercial, en el MCP y en PostHog. Las tres reusan el **mismo núcleo** (`portfolio_analytics_service`);
> no se duplica lógica.

---

## A. API comercial (`backend/app/api_public/modules/portfolio/`) [NEW]

**Patrón:** espejo exacto de [`modules/backtest/`](../../backend/app/api_public/modules/backtest).
La API comercial monta módulos por `EDGECUTE_ENABLED_MODULES` y los gatea/medie por separado.

```
api_public/modules/portfolio/
  __init__.py     # descriptor: { "router": router, "name": "portfolio", "meta": META }
  models.py       # Pydantic de la API pública (puede reusar schemas/portfolio.py)
  meta.py         # metadatos del módulo (versión, descripción, acciones gateables)
  router.py       # endpoints v1, FINOS: validan, llaman al Facade, serializan
  mapper.py       # request público -> kwargs del núcleo (igual que backtest/mapper.py)
```

**Reglas no negociables (heredadas de `docs/b2d-gateway/05`):**
1. **Aislamiento de IP:** los módulos NO importan el motor/servicios directamente. Todo pasa por el
   **Facade** (`api_public/facade.py`) con **import perezoso** del núcleo. Hay un test de arquitectura
   (`test_architecture.py`) que **falla** si un módulo importa el motor → respétalo.
2. **Errores sin fugas:** traducir a `ApiError` (`core/errors.py`); nunca `str(exc)`/trazas.
3. **Gating:** envolver cada acción con `require_access(principal, "portfolio", action)`
   (`core/gating.py`). El **mecanismo** existe; la **política** está diferida (default = permitir).
4. **Metering:** registrar uso en `usage_ledger` (`core/metering.py`). Para portfolio, métrica de
   uso = nº de simulaciones Montecarlo y nº de allocations (no hay ticker-days).
5. **Rate limit:** ya transversal (token-bucket por key).

**Facade — añadir métodos** (en `api_public/facade.py`, import perezoso del núcleo):
```python
def portfolio_combine(self, kwargs: dict) -> dict:
    from app.services.portfolio_analytics_service import combine_backtest_curves
    try:
        return combine_backtest_curves(**kwargs)
    except Exception as exc:
        raise ApiError("portfolio_failed", "No se pudo combinar la cartera.") from exc
# análogos: portfolio_montecarlo, portfolio_correlation, portfolio_allocation
```

**Endpoints públicos v1** (bajo `API_PREFIX`, p.ej. `/v1/portfolio/...`): `combine`, `montecarlo`,
`correlation`, `allocation`. *(El `monitoring/refresh` toca el motor pesado → **fuera del MVP de la
API comercial**, igual que los jobs async; se documenta como `not_implemented` accionable.)*

**Activación:** añadir `"portfolio"` a `EDGECUTE_ENABLED_MODULES`. Tests del módulo en
`api_public/tests/` siguiendo `test_api.py` (incluye el guard de aislamiento).

---

## B. MCP (`mcp/`) — build-time (codegen + catálogo de componentes + docs)

> Recordatorio (decisión firmada, `docs/b2d-gateway/04`): el MCP es **build-time**. Genera el
> cliente tipado y andamia componentes; **no** ejecuta cargas pesadas en runtime. El trader
> construye su app en Cursor/Claude Code y luego consume la API directamente por HTTP.

**Cambios:**
1. **`mcp/src/components.ts`** — añadir `module: "portfolio"` y componentes escogibles sueltos, cada
   uno declarando su `include`:
   | Componente | `include` | Origen plantilla |
   |---|---|---|
   | `combined_equity_chart` | `["combine"]` | `EquityCurveTab.tsx` |
   | `combined_drawdown_chart` | `["combine"]` | `Chart.tsx` |
   | `risk_metrics_grid` | `["combine"]` | `MetricsCard.tsx` |
   | `montecarlo_spaghetti` | `["montecarlo"]` | nuevo (percentiles) |
   | `correlation_heatmap` | `["correlation"]` | nuevo (Pearson/Spearman, rojo↔verde) |
   | `allocation_weights_table` | `["allocation"]` | `MetricsCard.tsx` |
2. **`mcp/src/components.ts` → `MODULES`** — registrar `portfolio`.
3. **`mcp/src/codegen.ts`** — el generador del cliente tipado debe cubrir los nuevos endpoints
   (sale gratis si lee `schema://openapi`, que es vivo).
4. **`mcp/src/docs.ts`** — añadir el glosario didáctico §2.5 (VaR/CVaR/Kelly/Pearson-Spearman/HRP)
   como recurso `docs://portfolio/glossary`, para que el dev lo embeba en su app.
5. **Resources** — `templates://portfolio/{component}` con las plantillas adaptadas (sin deps internas).
6. **(Opcional) tool de muestra** `run_sample_portfolio` contra sandbox `ek_test_`, como
   `run_sample_backtest`: conveniencia de desarrollo, **no** runtime de producción (dejarlo explícito
   en la descripción).
7. **Tests** — extender `mcp/tests/{logic,smoke,client}.test.ts` (tsc estricto 0 errores + vitest).

---

## C. PostHog / Product Analytics

**Patrón existente:** taxonomía centralizada en `frontend/src/lib/analytics.ts` (`EVENTS` + `track()`),
`PostHogIdentify`/`PostHogPageView` ya montados, proxy server-side ya configurado. **Único punto** a
tocar para la taxonomía: añadir a `EVENTS`.

**Añadir a `EVENTS`:**
```ts
PORTFOLIO_BUILT:               'portfolio_built',
PORTFOLIO_MONTECARLO_RUN:      'portfolio_montecarlo_run',
PORTFOLIO_CORRELATION_VIEWED:  'portfolio_correlation_viewed',
PORTFOLIO_ALLOCATION_COMPUTED: 'portfolio_allocation_computed',
PORTFOLIO_SCALING_RUN:         'portfolio_scaling_run',
PORTFOLIO_WEIGHTS_SAVED:       'portfolio_weights_saved',
PORTFOLIO_MONITORING_REFRESHED:'portfolio_monitoring_refreshed',
PORTFOLIO_JOURNAL_VIEWED:      'portfolio_journal_viewed',   // F2: clic en la pestaña "Próximamente"
```

**Dónde se dispara cada evento (sitio de acción):**
| Evento | Trigger | Props recomendadas |
|---|---|---|
| `portfolio_built` | clic "Construir portfolio" | `{ n_strategies, weighting: 'equal'|'custom' }` |
| `portfolio_montecarlo_run` | ejecutar Montecarlo | `{ simulations, init_cash, n_strategies }` |
| `portfolio_correlation_viewed` | abrir matriz | `{ n_strategies }` |
| `portfolio_allocation_computed` | calcular pesos | `{ method: 'leaders'|'hrp', lookback_days }` |
| `portfolio_scaling_run` | simular escalado | `{ mode, kelly_fraction }` |
| `portfolio_weights_saved` | "Guardar pesos" → Cuadro de Riesgo | `{ method, n_strategies }` |
| `portfolio_monitoring_refreshed` | "Actualizar" 3m | `{ n_strategies }` |
| `portfolio_journal_viewed` | clic pestaña Journal (F2) | `{ state: 'coming_soon' }` (mide demanda) |

**Reglas:**
* Solo cliente (`track()` es no-op en server). No romper la app si PostHog falla (ya está envuelto en
  try/catch en `analytics.ts`).
* Reusar el `identify` existente (no re-identificar). No enviar PII en props.
* **Funnel sugerido** (medir adopción del módulo): `portfolio_built` → `..._montecarlo_run` /
  `..._allocation_computed` → `..._weights_saved`. El evento `portfolio_journal_viewed` mide la
  **demanda real** del Journal para priorizar la Fase 2.
