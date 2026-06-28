# 07 — Decisiones abiertas y decisiones tomadas

## A. Decisiones de producto (dueño: Jaume / Jesús) — DIFERIDAS

1. **Monetización del Portfolio.** ¿Panel completo gratis, o HRP/Montecarlo de alta simulación
   bajo plan Premium? **Diferido a Jesús.** El MVP entrega solo el **mecanismo** de gating
   (`portfolio.access`, `portfolio.montecarlo_max_sims` en `entitlements/policy.py`), en abierto.
   *(Coherente con la regla "no decidir negocio": no fijar tiers/precios sin OK de Jesús.)*
2. **Prioridad de la Fase 2 (Journal).** El evento PostHog `portfolio_journal_viewed` medirá la
   demanda real de la pestaña "Próximamente" para priorizar.

## B. Decisiones técnicas — TOMADAS (CTO) en este suite

| Tema | Decisión | Motivo |
|---|---|---|
| **HRP** | **In-house con `scipy.cluster.hierarchy`** (linkage + recursive bisection), **sin `riskfolio-lib`** | `scipy>=1.12.0` ya está en `requirements.txt`; `riskfolio-lib` arrastra `cvxpy` (riesgo de build en Railway). HRP de López de Prado son ~80 líneas. |
| **Journal** | **Diferido a Fase 2** ("Próximamente") | No existe tabla ni CRUD; tiene PRD propio (`PRD_EJEMPLO_JOURNAL.md`). El MVP no debe bloquearse por él. |
| **Nombre del servicio** | `portfolio_analytics_service.py` | Evita colisión con `portfolio_sim.py` (simulador del motor). |
| **Verbo HTTP** | `POST` en `/api/portfolio/*` | La entrada es lista de IDs + pesos (cuerpo JSON), no query-string. |
| **`monitoring/refresh` en API comercial** | **Fuera del MVP comercial** (`not_implemented` accionable) | Toca el motor pesado; igual criterio que los jobs async en `b2d-gateway`. Sí está en la web app interna. |
| **Origen de la serie diaria** | Derivar de `results_json.day_results`, alinear al calendario unión, 0% en días sin trades | Único origen consistente; `equity_curves` es intradía por ticker-día. |
| **Multi-tenant** | DuckDB **por-usuario** (sin `user_id` en la tabla) | Aislamiento natural; la API comercial scopea por owner de la API-key. |

## C. Defaults técnicos reversibles

1. **Montecarlo:** 1.000 simulaciones por defecto (`ge=100, le=10000`).
2. **Ventana de Líderes:** **15 días** calendario (acordado), configurable.
3. **Capital inicial:** **$10,000 USD** para riesgo/escalado, configurable.
4. **Horizonte de correlaciones:** histórico común completo de los backtests seleccionados.
5. **Fracción Kelly:** 0.5 (medio Kelly) por defecto en el simulador de escalado.

## D. Preguntas para validar con Jaume antes de Fase 1 (no bloquean el arranque)

1. **Agregación de la curva combinada:** ¿multiplicativa (compuesta sobre retornos) o aditiva en USD
   sobre el capital de simulación? El doc 03 §3.1 propone fijarlo y testearlo en Fase 1 — confirmar
   convención esperada por el trader.
2. **Métrica de ranking en Líderes:** ¿Sharpe o PnL de la ventana? (default Sharpe).
3. **Definición de "ruina"** para la probabilidad de ruina: el Montecarlo actual usa 10% del capital
   inicial — ¿se mantiene ese umbral para el portfolio?
