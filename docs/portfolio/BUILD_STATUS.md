# BUILD STATUS — Página de Portfolio

> Estado real de lo construido en la rama `portfolio`. Acompaña al suite `docs/portfolio/`.

## ✅ Construido y verificado

### Núcleo analítico — `backend/app/services/portfolio_analytics_service.py`
Funciones puras (unit-testables sin DB): `daily_returns_from_results_json`, `align_returns`,
`combine_returns`, `portfolio_montecarlo`, `correlation_matrices` (Pearson+Spearman),
`kelly_fraction`, `capital_allocation` (Líderes anti-lookahead + **HRP in-house con scipy**),
`account_scaling` (kelly / fixed_pct / drawdown_stop). **Cero lookahead.**
- Loader DB compartido: `services/portfolio_loader.py` (scoped por `user_id`).
- **21 tests verde**: `tests/test_portfolio_combine.py`, `test_portfolio_risk.py`, `test_capital_allocation.py`.

### API interna (web app) — `backend/app/routers/portfolio.py`
`POST /api/portfolio/{combine,montecarlo,correlation,allocation,scaling}` + schemas Pydantic
(`schemas/portfolio.py`). Registrado en `main.py`. Errores accionables (`invalid_backtest`, etc.).

### API comercial — `backend/app/api_public/modules/portfolio/`
Espejo de `modules/backtest/`: router/models/meta/__init__. Métodos `portfolio_*` en el `Facade`
(import perezoso del núcleo; **respeta el guard de aislamiento de IP**). Gating + metering por acción.
Activado en `EDGECUTE_ENABLED_MODULES` (`backtest,portfolio`). Features en `entitlements/policy.py`
(`portfolio.access`, `portfolio.montecarlo_max_sims`) **en abierto** (MVP, sin decidir tiers).
- **API comercial: 50 tests verde** (incluye `test_portfolio_module.py` + guard de arquitectura).

### MCP (build-time) — `mcp/`
4 componentes escogibles (`portfolio-equity-chart`, `correlation-heatmap`, `montecarlo-spaghetti`,
`portfolio-risk-grid`), módulo `portfolio` en `MODULES`, glosario didáctico en `docs://portfolio-glossary`.
- **18 tests verde**; `tsc` estricto 0 errores; build OK.

### Frontend — `frontend/src/app/portfolio/` + `components/portfolio/`
Página con tabs (Portfolio / Análisis de Riesgo / Seguimiento), tabla del Baúl con ticks, curva
combinada + Cuadro de Riesgo, panel 1/3-2/3 (Montecarlo spaghetti, heatmap cromático, escalado,
asignación), tooltips/banners didácticos literales (§2.5), eventos PostHog `PORTFOLIO_*`.
- API client `lib/api_portfolio.ts`; entrada en Sidebar (gateada por `admin.preview_features`).
- `tsc --noEmit` limpio; render verificado en navegador (3 tabs OK, sin errores de consola).

## 🔜 Diferido (decidido, no es fallo)
- **Seguimiento por Journal** → Fase 2 ("Próximamente"): no existe Journal (ver `PRD_EJEMPLO_JOURNAL.md`).
- **Re-ejecución 3M en caliente** ("Actualizar 3M") → Fase 2: el seguimiento solapa las curvas YA
  guardadas (sin motor); el re-run incremental toca el motor y se marca "Próximamente".
- **Markov / Fix-ratio** y **comparativa Journal vs Ideal** → Fase 2 ("Próximamente").
- **`/portfolio/monitoring/refresh`** y el modelo en la **API comercial** → fuera del MVP comercial
  (tocaría el motor; igual criterio que jobs async en b2d-gateway).
- **Monetización/tiers** → decisión de producto diferida (solo mecanismo de gating entregado).

## ▶️ Cómo verificar
```bash
# Backend (núcleo + API comercial)
cd backend && PYTHONPATH=. ./venv/bin/pytest tests/test_portfolio_*.py tests/test_capital_allocation.py app/api_public/tests/ -q
# MCP
cd mcp && npm run build && npm test
# Frontend
cd frontend && npx tsc --noEmit
```
