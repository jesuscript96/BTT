# 05 — Arquitectura (dónde vive el código)

## 5.1 Principio rector

> **La lógica analítica vive UNA sola vez** en `portfolio_analytics_service.py`. La web app
> (`/api/portfolio`), la API comercial (`api_public/modules/portfolio`) y el MCP (codegen) son
> **clientes** de ese núcleo. Routers finos; cero lookahead; TDD.

```
                       ┌─────────────────────────────────────────┐
                       │  portfolio_analytics_service.py  (núcleo) │
                       │  combine · montecarlo · correlation ·     │
                       │  allocation(leaders|hrp) · scaling        │
                       └───────────────┬───────────────┬───────────┘
            web app interna            │               │   API comercial (vía Facade, lazy import)
   routers/portfolio.py  ─────────────┘               └────────  api_public/modules/portfolio/
            │                                                            │
   /api/portfolio/*  (Clerk-auth, DuckDB por-usuario)        /v1/portfolio/* (API-key, gating, metering)
            │
   frontend/src/app/portfolio  ←── PostHog events (analytics.ts)        MCP (build-time): codegen + componentes
```

## 5.2 Ficheros a crear / modificar

### Backend — núcleo + web app interna
| Acción | Fichero | Nota |
|---|---|---|
| NEW | `backend/app/services/portfolio_analytics_service.py` | Toda la lógica. **No** confundir con `portfolio_sim.py` (motor). |
| NEW | `backend/app/schemas/portfolio.py` | Pydantic del doc 03. |
| NEW | `backend/app/routers/portfolio.py` | Router fino. Resuelve el Baúl del usuario logueado. |
| MODIFY | `backend/app/main.py` (~línea 213/226) | `from app.routers import portfolio` + `app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])`. |
| NEW | `backend/app/tests/test_portfolio_combine.py` | Alineación de fechas, relleno 0%, métricas. |
| NEW | `backend/app/tests/test_portfolio_risk.py` | VaR/CVaR 95/99 (% y USD), Pearson/Spearman. |
| NEW | `backend/app/tests/test_capital_allocation.py` | Líderes (ventana, anti-lookahead) + HRP (scipy). |

### Backend — API comercial
| Acción | Fichero | Nota |
|---|---|---|
| NEW | `backend/app/api_public/modules/portfolio/{__init__,models,meta,router,mapper}.py` | Espejo de `modules/backtest/`. |
| MODIFY | `backend/app/api_public/facade.py` | Métodos `portfolio_*` con import perezoso del núcleo. |
| MODIFY | `backend/app/api_public/config.py` | `portfolio` en `EDGECUTE_ENABLED_MODULES`. |
| MODIFY | `backend/app/entitlements/policy.py` | Features `portfolio.access`(bool), `portfolio.montecarlo_max_sims`(limit). MVP en abierto (`True`/`-1`). |
| NEW | `backend/app/api_public/tests/test_portfolio_module.py` | Incluye guard de aislamiento de IP. |

### MCP
| Acción | Fichero | Nota |
|---|---|---|
| MODIFY | `mcp/src/components.ts` | Componentes `portfolio.*` + `MODULES`. |
| MODIFY | `mcp/src/docs.ts` | Glosario §2.5 como `docs://portfolio/glossary`. |
| MODIFY | `mcp/src/codegen.ts` | Cubrir nuevos endpoints (vía `schema://openapi`). |
| NEW | `mcp/templates/portfolio/*` | Plantillas de componentes. |
| MODIFY | `mcp/tests/*.test.ts` | Cobertura. |

### Frontend
| Acción | Fichero | Nota |
|---|---|---|
| NEW | `frontend/src/app/portfolio/page.tsx` | Página + tabs (patrón `ResultsTabs.tsx`). |
| NEW | `frontend/src/components/portfolio/PortfolioTable.tsx` | Tabla del Baúl con ticks. |
| NEW | `frontend/src/components/portfolio/RiskAnalysisPanel.tsx` | Layout 1/3 controles · 2/3 viz. |
| NEW | `frontend/src/components/portfolio/MonitoringPanel.tsx` | Solapamiento 3m (+ Journal "Soon"). |
| NEW | `frontend/src/components/portfolio/glossary.ts` | Textos didácticos §2.5 (tooltips/banners). |
| MODIFY | `frontend/src/lib/api.ts` | Llamadas `/api/portfolio/*`. |
| MODIFY | `frontend/src/lib/analytics.ts` | Eventos `PORTFOLIO_*` (doc 04C). |
| MODIFY | Sidebar/nav | Entrada "Portfolio" (gateable por `admin.preview_features` mientras esté en dev). |

## 5.3 Multi-tenant / seguridad
* `backtest_results` **no tiene `user_id`**: la DuckDB es por-usuario (`get_user_db_connection` +
  `gcs_sync`). El router interno opera sobre el Baúl del usuario autenticado por Clerk → aislamiento
  natural. La API comercial scopea por `owner = Clerk user_id` de la API-key (igual que backtest).
* Mientras el módulo esté en desarrollo, gatearlo en la web app con `admin.preview_features`
  (solo Admin/Jaume lo ve), como el resto de features en construcción.

## 5.4 Reuso explícito
* `montecarlo_service.py` → **referencia de estilo** (percentiles, ruin), no se importa.
* `_aggregate_metrics` (`backtest_service.py`) → reusar para métricas del Cuadro de Riesgo si la
  forma del input encaja; si no, función equivalente en el núcleo (testeada).
* `scipy.cluster.hierarchy` (ya en `requirements.txt:14`) → HRP in-house.
