# 06 — Prompt maestro de ejecución (guion para Claude Code)

> Copia este prompt en tu agente (modo goal/loop) para arrancar por fases. Trabaja en la rama
> **`nextux-jesus`**; los merges los hace otra persona; **no pushear sin avisar**.

## 0. Contexto obligatorio (audita antes de escribir)
1. Este suite: `docs/portfolio/00_INDEX.md` … `07_DECISIONES_ABIERTAS.md`.
2. `backend/app/services/montecarlo_service.py` (estilo percentiles/ruin — **referencia**, no importar).
3. `backend/app/services/backtest_service.py` (`_aggregate_metrics`).
4. `backend/app/init_db.py:222-240` (`backtest_results.results_json`).
5. `backend/app/api_public/modules/backtest/` (plantilla del módulo comercial).
6. `mcp/src/{components,docs,codegen}.ts` y `frontend/src/lib/analytics.ts`.

## 1. Restricciones críticas
* **Toda la lógica analítica en `portfolio_analytics_service.py`** (NO `portfolio_sim.py`).
  Routers finos.
* **Cero lookahead** en asignación (Líderes) y escalado.
* **TDD obligatorio:** test primero, validar, luego implementar.
* **HRP in-house con scipy** (sin `riskfolio-lib`).
* **Journal diferido a F2:** dibujar la pestaña con estado "Próximamente"; no implementar backend.
* **Didáctico:** tooltips/banners con las fórmulas y textos **literales** del doc 02 §2.5.

## 2. Fases

### FASE 1 — Combinar curvas y métricas (TDD)
1. Test `test_portfolio_combine.py`: alineación de calendario unión, relleno 0% en días sin trades,
   métricas consolidadas (Sharpe, MaxDD, PnL%) con un DataFrame ficticio.
2. Implementar `portfolio_analytics_service.combine_backtest_curves()` (derivación desde
   `results_json.day_results`, doc 03 §3.1).
3. Endpoint `POST /api/portfolio/combine` + registro en `main.py`.
4. Verificar: `pytest backend/app/tests/test_portfolio_combine.py -q`.

### FASE 2 — Riesgo: Montecarlo, VaR/CVaR, correlaciones (TDD)
1. Test `test_portfolio_risk.py`: VaR/CVaR 95% y 99% (% y USD); matrices Pearson y Spearman; días
   sin operación = 0%.
2. Implementar en el núcleo: `portfolio_montecarlo()` (shuffle de **retornos diarios**),
   `correlation_matrices()`, Kelly a nivel de cartera.
3. Endpoints `POST /api/portfolio/montecarlo`, `/correlation`.
4. Verificar: `pytest backend/app/tests/test_portfolio_risk.py -q`.

### FASE 3 — Asignación (Líderes + HRP) y escalado (TDD)
1. Test `test_capital_allocation.py`: Líderes con ventana deslizante configurable (default 15d) y
   **anti-lookahead**; HRP estable con scipy (linkage + recursive bisection); borde < 2 estrategias.
2. Implementar `capital_allocation()` y `account_scaling()` (kelly / fixed_pct / drawdown_stop).
3. Endpoints `POST /api/portfolio/allocation`, `/scaling`.
4. Verificar: `pytest backend/app/tests/test_capital_allocation.py -q`.

### FASE 4 — API comercial (módulo `portfolio`)
1. Crear `api_public/modules/portfolio/` espejando `modules/backtest/`.
2. Añadir métodos `portfolio_*` al `Facade` (import perezoso del núcleo).
3. Gating (`require_access(..., "portfolio", action)`) + metering + errores sin fugas.
4. Registrar en `EDGECUTE_ENABLED_MODULES`; features en `entitlements/policy.py` (abierto).
5. Verificar: `pytest backend/app/api_public/tests/ -q` (incluye guard de aislamiento de IP).

### FASE 5 — MCP (build-time)
1. Componentes `portfolio.*` en `components.ts` (+ `MODULES`), cada uno con su `include`.
2. Glosario §2.5 en `docs.ts` (`docs://portfolio/glossary`); plantillas `templates://portfolio/*`.
3. Codegen cubre los nuevos endpoints (vía `schema://openapi`).
4. Verificar: `cd mcp && npm run build && npm test` (tsc estricto 0 errores + vitest).

### FASE 6 — Frontend + PostHog + didáctico
1. `lib/api.ts`: integraciones `/api/portfolio/*` tipadas.
2. Página + tabs: tabla del Baúl, gráfico combinado, Cuadro de Riesgo; panel 1/3-2/3; heatmap
   cromático (rojo=1.0, neutro=0.0, verde=-1.0); Spaghetti de Montecarlo.
3. Tooltips/banners didácticos **literales** (`glossary.ts`). Markov/Fix-ratio y Journal como "Soon".
4. Eventos `PORTFOLIO_*` en `analytics.ts` y `track()` en cada sitio de acción (doc 04C).
5. Verificar: `cd frontend && npm run build` + lint (tsc 0 errores).

## 3. Definition of Done
* Todos los `pytest` de portfolio en verde; API comercial verde con guard de aislamiento.
* `mcp` build + tests verde; `frontend` build + tsc 0 errores.
* Eventos PostHog disparándose (verificar en preview/console).
* Textos didácticos §2.5 presentes y literales.
* Pestañas diferidas (Journal/Markov/Fix-ratio) visibles como "Próximamente".
