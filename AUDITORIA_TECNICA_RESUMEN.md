# Auditoría técnica — Resumen (BTT + backtester2)

Fecha: 2026-05-06  
Scope: `C:\...edgecute\BTT` y `C:\...edgecute\backtester2`

## 1) Resumen ejecutivo (foto real hoy)

- Hay **2 repos separados**: `BTT` (plataforma completa: screener + strategy builder + backtest + resultados) y `backtester2` (iteración/MVP del backtester con arquitectura distinta y enfoque en GCS/MotherDuck + optimización).
- Ambos son **full-stack** (Next.js + React) con backend en **FastAPI**.
- **No hay autenticación** ni autorización en ninguno: si el backend está público, **todos los endpoints quedan expuestos**.
- `BTT` implementa backtester **Numba/JIT** con API asíncrona (background + polling) y persistencia en DuckDB/MotherDuck/GCS.
- `backtester2` implementa motor **pure numpy** con **streaming por día**, incluye **optimization surface**, **Monte Carlo** y **What-if**, con despliegue previsto en Render + Vercel.
- Señal clara de estado “en movimiento”: scripts de migración/diagnóstico, logs, parches temporales y docs de performance conviviendo con core.

---

## 2) Repos y estructura

### ¿Monorepo?
- **No**. Son repos/carpeta separados (sin workspaces ni tooling de monorepo).

### Árbol (BTT, máx 3 niveles — lo relevante)
- Raíz: `backend/`, `frontend/`, `docs/`, `.agent/` + scripts/logs sueltos.
- Backend: `backend/app/` (routers/services/backtester/schemas), `backend/scripts/`, `backend/tests/`.
- Frontend: `frontend/src/app/` (rutas), `frontend/src/components/` (UI), `frontend/src/config/`.

### Árbol (backtester2, máx 3 niveles — lo relevante)
- Raíz: `backend/`, `frontend/`, `scripts/`, `docs/` + `render.yaml`, `Procfile`, `gunicorn.conf.py`, `.env.example`.
- Backend: `backend/routers/`, `backend/services/`, `backend/db/`.
- Frontend: `frontend/src/app/page.tsx`, `frontend/src/components/`, `frontend/src/lib/api.ts`.

---

## 3) Configuración raíz / tooling

### BTT
- Frontend:
  - `frontend/package.json`: Next `16.1.6`, React `19.2.3`, Tailwind `^4`, ESLint `^9`.
  - `frontend/eslint.config.mjs`, `frontend/next.config.ts`, `frontend/tsconfig.json`.
- Backend:
  - `backend/requirements.txt`: FastAPI `0.115.0`, DuckDB `1.1.3`, Pandas `2.2.3`, Pydantic `2.9.2`, Numba `>=0.59.1`, Numpy `>=1.26.4`.
- Infra:
  - Docs: `DEPLOYMENT.md` (Vercel + Railway/Render sugeridos).
- CI / Docker / hooks:
  - **No** se observan `.github/workflows`, `Dockerfile`, `docker-compose`, `Makefile`, `.pre-commit-config.yaml`.

### backtester2
- Frontend:
  - `frontend/package.json`: Next `16.1.6`, React `19.2.3`, axios `^1.13.5`, plotly `^3.5.0`, recharts `^3.7.0`.
- Backend:
  - `backend/requirements.txt`: FastAPI `0.133.1`, DuckDB `1.4.4`, Gunicorn `25.1.0`, Numpy `2.2.6`, Pydantic `2.12.5`.
- Infra:
  - `render.yaml` (PYTHON_VERSION `3.13.0`, gunicorn timeout 300s), `Procfile`, `gunicorn.conf.py`.
- CI / hooks:
  - **No** se observan workflows ni pre-commit.

---

## 4) Stack tecnológico (con versiones)

### Frontend (BTT)
- Framework: Next.js **16.1.6**
- UI: Tailwind **^4** (`clsx`, `tailwind-merge`)
- Estado: React hooks (sin Redux/Zustand)
- Fetching: `fetch` nativo (debounce/abort manual)
- Routing: Next App Router
- Charts: `recharts` **^3.7.0**, `lightweight-charts` **^5.1.0**
- Testing FE: no se observan Jest/Vitest/Playwright/Cypress en deps
- Auth cliente: no existe

### Backend (BTT)
- Framework: FastAPI **0.115.0**
- DB: DuckDB **1.1.3** (con modo MotherDuck y modo GCS)
- Motor backtest: Pandas **2.2.3**, Numba **>=0.59.1**, Numpy **>=1.26.4**
- Task/async: FastAPI `BackgroundTasks` (no Celery/RQ)
- Websockets: no
- Cache: sin Redis; hay chunking/batching en queries/backtest

### Frontend (backtester2)
- Framework: Next.js **16.1.6**, React **19.2.3**
- Fetching: axios **^1.13.5**
- Charts: Plotly (`plotly.js` **^3.5.0**, `react-plotly.js`) + `recharts` **^3.7.0**
- Auth cliente: no existe

### Backend (backtester2)
- Framework: FastAPI **0.133.1**
- Server: Gunicorn **25.1.0** (uvicorn worker), `workers=1`, `timeout=300`
- DB: DuckDB **1.4.4**
- Motor: Numpy **2.2.6**, streaming por día (pure numpy)

---

## 5) Arquitectura y comunicación

### Comunicación FE ↔ BE
- REST/JSON por HTTP en ambos repos.

### Patrón
- BTT: routers + services + engine, pero con lógica pesada en routers (especialmente backtest).
- backtester2: routers más delgados, servicios más claros; motor separado.

---

## 6) Endpoints backend (BTT) — inventario

### Backtest (`/api/backtest`)
- `POST /run`
- `GET /status/{run_id}`
- `GET /results/{run_id}`
- `GET /history`
- `DELETE /{run_id}`

### Market (`/api/market`)
- `GET /screener`
- `GET /ticker/{ticker}/intraday`
- `GET /ticker/{ticker}/metrics_history`
- `GET /latest-date`
- `GET /aggregate/intraday`

### Data (`/api/data`)
- `POST /filter`
- `GET /tickers`
- `GET /historical`

### Strategies (`/api/strategies`)
- `POST /`
- `GET /`
- `GET /{strategy_id}`
- `DELETE /{strategy_id}`

### Queries (`/api/queries`)
- `POST /`
- `GET /`
- `GET /{query_id}`
- `DELETE /{query_id}`

### Strategy Search (`/api/strategy-search`)
- `POST /filter`
- `GET /list`
- `DELETE /{strategy_id}`
- `POST /export`

### Ticker analysis (`/api/ticker-analysis`)
- `GET /{ticker}`
- `GET /{ticker}/sec-filings`

### News
- `GET /api/market/news`

### Health
- `GET /health`

---

## 7) Rutas frontend (BTT) — inventario

- `/` (screener + tabs: rolling/regression/ticker)
- `/backtester`, `/backtester/[id]`
- `/strategies/new`
- `/database`
- `/analysis/[ticker]/[date]`
- `/tutorials`

---

## 8) Funcionalidades y estado (semáforo)

> Nota: evaluación basada en implementación y señales en docs/logs; no se ejecutó el sistema en esta auditoría.

### RUNSCAN
- Estado: **🔲 no implementada** como feature explícita en `BTT` (no se identificó por nombre/flujo).

### Market Analysis (BTT)
- Estado: **✅ implementada**
- Riesgo: **⚠️** mapeos duplicados y drift entre front/back.

### Strategy Builder (BTT)
- Estado: **✅ implementado**
- Persistencia: DuckDB `strategies` (definition JSON).
- Riesgo: **⚠️** contrato “schema ↔ engine” frágil.

### Backtester
- BTT: **✅** con **⚠️** riesgo de timeouts/escala por “ETL + simulación” en un request.
- backtester2: **✅** con **⚠️** por seguridad/config (CORS/auth) y limitaciones de threading/global state.

---

## 9) Performance — cuellos de botella evidentes

### BTT
- Endpoint de backtest mezcla selección de universo + fetch intradía + filtros + simulación + métricas + persistencia.
- Hay señales de mitigación por timeouts y límites de MotherDuck (docs y chunking/batching).
- Conexión DuckDB global compartida puede degradar concurrencia.
- Polling sin backoff (aceptable en MVP; mejorable).

### backtester2
- Startup sincroniza “hot tables” (cold start pesado).
- Optimization con threads + diccionarios globales no escala horizontalmente.
- `plotly` probablemente aumenta mucho el bundle.

---

## 10) Seguridad (hallazgos clave)

- **CRÍTICO**: sin autenticación/autorizar endpoints (ambos repos).
- **CRÍTICO**: `backtester2` tiene CORS configurado con `allow_origins=["*"]` (orígenes abiertos).
- No hay rate limiting en ninguno.
- SQL: mayormente parametrizado con `?`, pero hay SQL dinámico construido por strings (revisar caso a caso).

---

## 11) Deuda técnica (priorizada)

### CRÍTICO
- Sin auth + sin rate limit (BTT + backtester2).
- CORS abierto en backtester2.
- DuckDB connection/cursor global compartido en BTT (riesgo de concurrencia).

### ALTO
- Mezcla de scripts/logs/artefactos con core (operación y auditoría difíciles).
- Backtest “todo-en-uno” en BTT (timeouts/costos).
- Contratos duplicados (mapeos front/back) → drift.

### MEDIO
- Falta de formateo/linting Python (ruff/black/isort) y typing.
- Falta de CI (tests/lint).
- Migraciones no estandarizadas (mucho via scripts).

### BAJO
- Estandarizar estructura y documentación de “cómo correr”.

---

## 12) Top 5 problemas críticos “YA”

1. Sin autenticación + sin rate limiting (ambos).
2. CORS abierto en backtester2 (`allow_origins=["*"]`).
3. DuckDB cursor/conexión global compartida en BTT.
4. Backtest en BTT hace ETL completo por request (timeouts/502).
5. Repo hygiene: logs/dumps/scripts mezclados con core.

---

## 13) Estimaciones (orden de magnitud)

- **(a) RunScan** (si significa batch backtests sobre un universo + job mgmt):
  - 3–7 días (mínimo viable) / 2–4 semanas (robusto y operable).
- **(b) Consolidación de apps** (2 repos aquí; “journal” no está en scope):
  - 2–6 semanas para unificar backend + frontend + contratos + deploy.
- **(c) Performance general**:
  - 1–2 semanas quick wins / 4–8 semanas arquitectura async real (cola/worker/cache).

---

## 14) Recomendaciones para consolidación frontend

- Unificar en un solo Next.js con `lib/api` tipado (ideal: OpenAPI/types compartidos).
- Separar features claras: Screener / Strategy Builder / Backtester / Results / Optimization.
- Lazy load y code-splitting para charts pesados (especialmente Plotly).

---

## 15) Riesgos antes de tocar código

- Cambios en schema/indicadores rompen backtests históricos.
- Sin auth/rate limit, cualquier aumento de costo por request empeora abuso y facturación.
- Migraciones/schema (DuckDB/MotherDuck/GCS) ya son delicadas; tocar query builders sin regresión es peligroso.
- Arreglar concurrencia de DB puede destapar bugs latentes (pero es necesario).

