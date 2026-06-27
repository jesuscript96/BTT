# 06 — Prompt Maestro de Ejecución · Módulo de Robustez

> **Cómo usar este documento.** Es el guion operativo para Claude Code en modo `/goal`.
> Pégalo (o referéncialo) con el repo abierto en la rama `robustez`. El agente debe leer
> primero la **§0 Contexto obligatorio**, luego ejecutar las tareas atómicas una a una,
> verificando cada comando antes de pasar a la siguiente. **Test primero, siempre.**
>
> PRD completo: [`docs/robustez/PRD_ROBUSTEZ.md`](./PRD_ROBUSTEZ.md). Nota original de Jaume:
> [`NOTA_ORIGINAL_JAUME.pdf`](./NOTA_ORIGINAL_JAUME.pdf).

---

## ✅ Estado de ejecución (rama `robustez`, sin commit/push)

Los 7 PRs del plan están **implementados y verificados localmente**:

| PR | Alcance | Verificación |
|---|---|---|
| 1 | Andamiaje + loader | `tests/test_robustness_loader.py` (6) ✓ |
| 2 | Montecarlo + Sensibilidad + Black Swan + endpoints | 16 tests ✓ |
| 3 | WFO (background + polling) | `tests/test_wfo_engine.py` (7) ✓ |
| 4-5 | Frontend (página, grid, config, charts, analytics) | `npm run build` ✓ · lint ficheros nuevos 0 errores |
| 6 | API comercial `modules/robustness/` | `pytest app/api_public/tests/` (52, incl. arquitectura) ✓ |
| 7 | OpenAPI regenerado + catálogo MCP | `mcp: npm run build && npm test` (18) ✓ |

**Total backend: 81 tests verde.** Ficheros nuevos clave: `services/robustness_service.py`,
`routers/robustness.py`, `api_public/modules/robustness/*`, `app/robustness/page.tsx`,
`components/robustness/*`, `lib/api_robustness.ts`, `mcp/src/components.ts` (5 componentes),
`docs/robustez/API_COMERCIAL.md`.

> Notas de entorno: el venv local no traía `pytest`/`python-jose`/`httpx` (deps de test) — se
> instalaron para verificar. La suite global `pytest tests/ -q` requiere `MOTHERDUCK_TOKEN`
> (tests de integración con datos reales), ajeno a este feature. El smoke-test en navegador exige
> el stack vivo (backend + Clerk + un run del Baúl): queda como paso manual de Jesús.

---

## ★ Hallazgos del análisis (verdad anclada, ya verificada)

Estos puntos se auditaron contra el código antes de escribir el goal. **No re-derivar; usar tal cual.**

| # | Afirmación del PRD | Estado real en el código | Acción en el goal |
|---|---|---|---|
| 1 | El módulo recibe `strategy_id` | El selector es el **Baúl**, que lista filas de `backtest_results` vía `GET /api/strategy-search/list` (router `strategy_search.py:222`). El id de cada fila es `backtest_id` (= `backtest_results.id`). La tabla `strategies` es otra cosa (definiciones, no resultados). | **Renombrar el campo del contrato a `run_id`** (alias aceptado: `strategy_id`). El service carga trades desde `backtest_results.results_json`, NO desde `strategies`. |
| 2 | Montecarlo/What-If reusables | Hoy `run_montecarlo(pnls,...)` (`montecarlo_service.py:9`) y `run_what_if(trades, params,...)` (`what_if_service.py:14`) reciben los datos **directos**, no un id. La inyección de slippage/black-swan vive en `what_if_service.py:160-196`. | El nuevo `robustness_service.py` **carga los trades una vez** (helper `_load_trades(run_id)`) y se los pasa a la lógica. Reutiliza los patrones de remuestreo y de inyección, pero con bootstrap **con reemplazo** (`rng.choice`), no `permutation`. |
| 3 | WFO corre en background con `task_id` y polling | La infra ya existe en `optimization_service.py`: `set_progress` (:115), `get_progress` (:130), `store_result` (:144), `pop_result` (:169), `cancel_optimization_task` (:50). El router `optimization.py:101-120` ya hace el patrón POST→`task_id` / GET `/progress` / GET `/result`. | **Reutilizar esos helpers tal cual.** No inventar un sistema de colas nuevo. WFO llama a `run_optimization_grid` (`optimization_service.py:565`) en cada ventana IS y a `extract_parameters` (`:225`) para validar parámetros. |
| 4 | Campos del trade: `ticker,date,entry_price,exit_price,size,pnl,return_pct,direction,exit_reason` | Confirmados en `_enrich_trades` (`backtest_service.py:778-828`). Además existen `r_multiple`, `mae`, `mfe`, `fees`, `stop_loss`, `status`, `entry_time`. | Usar esos nombres literales. Para el umbral de locates usar `size * entry_price` de los trades con `direction` corto. |
| 5 | Tokens `--ec-profit`, `--ec-loss`, `--ec-copper` | En `frontend/src/app/globals.css` los nombres reales son `--color-ec-profit` (#4A9D7F), `--color-ec-loss` (#C94D3F), `--color-ec-copper` (#D87A3D). | Usar los nombres `--color-ec-*`. |
| 6 | Gráficos | `recharts@3.7` y `lightweight-charts@5.1` ya están en `frontend/package.json`. | Espagueti/histograma/heatmap con **recharts**. No añadir dependencias nuevas. |
| 7 | Métricas de agregación consistentes | `_aggregate_metrics` (`backtest_service.py:1029`) produce las claves canónicas (`win_rate_pct`, `total_pnl`, `max_drawdown_pct`, `total_return_pct`, `sharpe`/`avg_sharpe`, etc.). | WFO y Sensibilidad reusan ese helper para no driftear definiciones. |
| 8 | Baúl en el frontend | Vive en `frontend/src/app/backtester/page.tsx`; el listado de runs guardados sale de `strategy-search/list`. El `DataGrid` (`components/DataGrid.tsx`) es reutilizable. | El grid superior de Robustez reutiliza el mismo patrón de fetch + `DataGrid`. |
| 9 | API comercial (Gateway B2D) | **Ya implementada** en `backend/app/api_public/` (`core/` + `modules/backtest/`, 36 tests). Cada módulo = `router.py + models.py + mapper.py + meta.py`, expone `/v1/<modulo>/…`, declara `MODULE` con `gating_tag`, importa el motor **solo vía `facade.py`**, se monta por `EDGECUTE_ENABLED_MODULES` (`app.py:64`). Guard `test_architecture.py` falla si un módulo importa el motor. | **Replicar el contrato de módulo** en `modules/robustness/`. Añadir métodos al `Facade` (import perezoso de `robustness_service`). NO importar el motor directo. |
| 10 | MCP del backtester | **Ya implementado** en `mcp/` (TS estricto, 9 tools, build-time). Catálogo `módulo→componente→include` en `src/components.ts`; cliente tipado generado desde `schema://openapi` (vivo); docs:// y prompts. | Añadir módulo `robustness` al catálogo con sus componentes (cada uno declara su `include`); regenerar cliente tipado; docs/types; tests vitest. |
| 11 | PostHog / Product Analytics | Taxonomía única en `frontend/src/lib/analytics.ts` (`EVENTS` + `track()`), posthog-js + proxy. **No hay PostHog server-side** (grep vacío). La API comercial mide uso por `usage_ledger` (metering), no PostHog. | Añadir eventos `robustness_*` a `EVENTS` y llamarlos en los sitios de acción. El analytics de la API comercial = metering existente, no se duplica en PostHog. |

**Dev local:** API web por defecto en `http://127.0.0.1:8010/api` (ver `lib/api.ts:12`), no 8000. API comercial (Gateway) se monta aparte vía `api_public/app.py`. Frontend en `:3000`.

**Política de gating / monetización: NO es del goal.** El módulo declara su `gating_tag` (mecanismo); qué es gratis/pago lo decide Jesús (ver §Decisiones abiertas y `docs/b2d-gateway/07`).

---

## 0 · Contexto obligatorio (leer antes de tocar nada)

1. Este documento y el PRD: `docs/robustez/PRD_ROBUSTEZ.md`.
2. Backend a reutilizar:
   - `backend/app/services/montecarlo_service.py` (remuestreo + percentiles + DD/ruina).
   - `backend/app/services/what_if_service.py:14,158-196` (inyección slippage / black swan).
   - `backend/app/services/optimization_service.py:50,115-180,225,565` (background tasks + grid + extract_parameters).
   - `backend/app/services/backtest_service.py:778-828` (`_enrich_trades`), `:1029` (`_aggregate_metrics`).
   - `backend/app/routers/optimization.py:66-128` (patrón task_id/polling a copiar).
   - `backend/app/routers/strategy_search.py:52-130,222` (carga de `backtest_results`/Baúl).
   - `backend/app/routers/backtest.py:210-231` (cómo se exponen montecarlo/what-if hoy).
   - `backend/app/main.py:213-238` (registro de routers).
   - `backend/app/init_db.py:222-240` (DDL `backtest_results`).
3. Frontend a reutilizar:
   - `frontend/src/lib/api.ts` (patrón de cliente, `API_BASE`, `getAuthHeaders`).
   - `frontend/src/app/backtester/page.tsx` (Baúl + carga de runs guardados).
   - `frontend/src/components/DataGrid.tsx`, `frontend/src/components/Sidebar.tsx` (navegación).
   - `frontend/src/app/globals.css` (tokens `--color-ec-*`).
4. API comercial + MCP + analytics (para EPIC C/D/E):
   - `backend/app/api_public/modules/backtest/` (plantilla de módulo: `meta.py`, `router.py`, `models.py`, `mapper.py`).
   - `backend/app/api_public/facade.py` (único puente al motor), `core/` (auth, gating, metering, payload, errors), `app.py` (montaje), `config.py` (`ENABLED_MODULES`).
   - `backend/app/api_public/tests/test_architecture.py` (guard de aislamiento — debe seguir verde).
   - `mcp/src/components.ts` (catálogo módulo→componente→include), `mcp/src/server.ts`, `mcp/src/codegen.ts`, `mcp/src/docs.ts`.
   - `docs/b2d-gateway/04_MCP_TOOLS_RESOURCES.md`, `05_ARQUITECTURA.md`, `openapi.generated.json`.
   - `frontend/src/lib/analytics.ts` (`EVENTS` + `track`), `frontend/src/components/PostHogPageView.tsx`.
5. Reglas de casa: `.agent/EDGECUTE_DESIGN_SYSTEM.md`, `.agent/CODING_RULES.md`.

---

## 1 · Restricciones globales no negociables

1. **Lógica en `services/`, nunca en `routers/`.** El router solo valida (Pydantic) y delega.
2. **Capa nueva, no tocar el core.** No editar `backtest_service.py`, `montecarlo_service.py`,
   `what_if_service.py` ni `optimization_service.py` salvo para *importar y llamar* funciones
   existentes. Todo lo nuevo vive en `robustness_service.py` / `robustness.py`.
3. **WFO asíncrono.** Bloquear el hilo principal está prohibido: usar `BackgroundTasks` +
   `set_progress`/`store_result`/`pop_result` de `optimization_service.py`. Los demás módulos
   (Montecarlo, Sensibilidad, Black Swan) responden **síncronos en <200 ms**.
4. **Todo cálculo numérico con `numpy`** y **un test unitario por regla** antes de implementar.
5. **Identificador = `run_id`** (un `backtest_results.id`). Aceptar `strategy_id` como alias para
   no romper el PRD, pero internamente resolver a `backtest_results`.
6. **Ramas:** trabajar en `robustez`. **No mergear a `main`, no pushear sin avisar a Jesús.**
   No commitear `.env`, `*.duckdb`, `*.log`, claves.
7. **Edge cases del PRD §2.6 son ley** (M=0 → 400; IS≤0 → WFE=0; sin shorts → locate crítico null;
   balance post-swan ≤ ruina → 100%). Cada uno tiene su test.

---

## 2 · Secuenciación atómica (EPICs → tareas)

> Patrón por tarea: **(a)** escribe el test con los números cerrados del PRD §3 → **(b)** implementa
> hasta verde → **(c)** corre el comando de verificación → **(d)** commit pequeño. Sin test no hay
> código de producción.

### EPIC A — Backend: andamiaje + carga de datos

- **A0 · Esqueleto + helper de carga.**
  Crear `backend/app/services/robustness_service.py` con:
  - `_load_trades(run_id) -> tuple[list[dict], dict]`: lee `backtest_results` (`results_json`),
    devuelve `(trades, results_json)`. Si no existe → `ValueError("INVALID_STRATEGY")`. Si
    `len(trades) == 0` → `ValueError("No trades available")`.
  - `_load_strategy_def(run_id) -> dict`: vía `strategy_ids` → `strategies.definition` (para WFO).
  Crear `backend/app/routers/robustness.py` (router vacío) y registrarlo en `main.py`
  con prefix `/api/robustness`.
  - *Test:* `backend/tests/test_robustness_loader.py` (run válido carga N trades; run inexistente → ValueError; run sin trades → ValueError).
  - *Verif:* `cd backend && pytest tests/test_robustness_loader.py -q` y `uvicorn app.main:app --reload --port 8010` arranca sin error.

- **A1 · Montecarlo bootstrap con reemplazo** (`run_montecarlo_bootstrap`).
  Remuestreo con `rng.choice(pnls, size=K, replace=True)` × `S` simulaciones. Calcular:
  `ruin_probability` (% curvas que tocan `init_cash*ruin_pct/100`), `worst/median_drawdown`,
  `extreme_drawdown_p95/p99`, `probability_negative_return` a `N` trades, `n_trades_calculated`
  (de `period_unit` con `factor_periodo` 1/12, 1/4, 1.0 sobre años efectivos del histórico),
  y `percentiles` p5/p25/p50/p75/p95 de la curva.
  - *Test:* `backend/tests/test_montecarlo_bootstrap.py` — con PnLs deterministas y `rng` semillado, comprobar shape de percentiles, ruina con caso forzado, y `M=0` → error.

- **A2 · WFO (Walk-Forward).**
  En background: particiona el histórico por `is_pct`/`oos_pct`/`step_pct`; en cada IS llama a
  `run_optimization_grid` (parámetros validados con `extract_parameters`), elige el mejor por
  `metric`, evalúa **ciego** en OOS, concatena curvas OOS. Calcula `wfe` (OOS/IS×100, IS≤0→0),
  `win_rate_penalty` (WinRate_IS − WinRate_OOS), `oos_max_drawdown`, `is_metrics`, `oos_metrics`,
  `heatmap_matrix`. **Cap MVP: máx 50 combinaciones** (decisión §7-A, reversible). Progreso vía
  `set_progress`; resultado vía `store_result`.
  - *Test:* `backend/tests/test_wfo_engine.py` — partición correcta de índices IS/OOS, WFE con IS=0 → 0.0, no hay solape OOS↔IS (anti-lookahead).

- **A3 · Sensibilidad (locates + slippage).**
  `critical_locate_threshold = NP_base / Σ(size_i·entry_price_i for shorts) × 100`
  (sin shorts o denom 0 → `null`). Curvas de equity para cada locate del rango (`min..max` step).
  Slippage estocástico: con prob `slippage_probability%`, restar `slippage_value` al retorno del
  trade (reutilizar la lógica de `what_if_service.py:173-186`).
  - *Test:* `backend/tests/test_sensitivity.py` — umbral crítico con caso cerrado a mano; sin shorts → null; nº de curvas = nº de locates del rango.

- **A4 · Black Swan + métricas post-swan.**
  Inyectar `black_swan_count` pérdidas extremas (`severity_multiplier` × pérdida media) en índices
  aleatorios; `time_to_recovery_trades` (media de trades para recuperar el pico pre-swan);
  `post_swan_ruin_risk_100t` = bootstrap 1000×100 con `Capital_inicial = pre_swan − pérdida_swan`
  (si ≤ ruina → 100.0). `sensitivity_matrix` (position_size × severity → ruin_probability,
  max_drawdown, zone GREEN/YELLOW/RED según §07 minuta: verde ruina<5%&DD<20%, amarillo 5-20%&20-40%, rojo >20%||>40%).
  - *Test:* `backend/tests/test_black_swan.py` — balance post-swan ≤ ruina → 100%; zonas asignadas según umbrales; TTR en caso recuperable conocido.

- **A5 · Router + contratos + errores.**
  Exponer en `robustness.py`: `POST /api/robustness/montecarlo`, `POST /walk-forward` +
  `GET /walk-forward/result/{task_id}` + `GET /walk-forward/progress/{task_id}`,
  `POST /sensitivity`, `POST /black-swan`. Modelos Pydantic = contrato del PRD §3. Mapear errores
  `INVALID_STRATEGY`/`PARAMETER_OUT_OF_BOUNDS` (400), `PROCESSING_ERROR` (500).
  - *Verif:* `cd backend && pytest tests/ -q` (verde) + `uvicorn ...` + `curl` a cada endpoint con un `run_id` real del Baúl.

### EPIC B — Frontend: pantalla de Robustez

- **B1 · API client & tipos.** En `frontend/src/lib/api.ts` (o `lib/api_robustness.ts`) añadir
  tipos de request/response del §3 y funciones cliente (`postMontecarlo`, `postWalkForward`,
  `pollWfoResult`, `postSensitivity`, `postBlackSwan`) usando `API_BASE` + `getAuthHeaders`.
- **B2 · Página + grid superior.** `frontend/src/app/robustness/page.tsx` con layout dividido
  (grid superior + 2 columnas). El grid reutiliza el patrón de `backtester/page.tsx` (fetch a
  `strategy-search/list`) y `DataGrid`. Añadir entrada en `Sidebar.tsx`.
- **B3 · Panel de configuración (`RobustnessConfig.tsx`).** Selector de módulo (Montecarlo/WFO/
  Sensibilidad/Swan) + formularios con validación. Aviso "WFO es pesado". 4 estados obligatorios
  (loading/empty/error/success); WFO con barra de progreso por polling.
- **B4 · Visualizaciones (`RobustnessCharts.tsx`).** Espagueti (percentiles) + histograma de DD
  (Montecarlo), heatmap paramétrico (WFO), multi-línea de equity por locate + indicador "Umbral
  Crítico de Locates: X.XX%" (Sensibilidad), simulador de estrés + matriz de sensibilidad
  coloreada (Swan). Todo con **recharts**.
- **B5 · Pulido + tooltips + color semántico.** Popovers con fórmula+ejemplo en cada métrica
  (WFE/RoR/TTR/Post-Swan). Colores por umbral con `--color-ec-profit/copper/loss`. Estética
  "sobre el fondo", pocos bordes, profesional (PDF de Jaume).
  - *Verif:* `cd frontend && npm run build && npm run lint` verde; `npm run dev` y smoke-test manual de los 4 módulos.

### EPIC C — API comercial (Gateway B2D): módulo `robustness`

> Reusar el contrato de módulo de `api_public` **sin tocar el motor ni el core**. Todo lo pesado
> entra por el `Facade`. Espejo del PRD §3 pero con DTOs propios y errores sin fugas.

- **C0 · Facade.** En `backend/app/api_public/facade.py` añadir métodos (import perezoso de
  `app.services.robustness_service`): `montecarlo(...)`, `walk_forward_start(...)`,
  `walk_forward_result(task_id)`, `sensitivity(...)`, `black_swan(...)`. Traducir excepciones a
  `ApiError` (`invalid_strategy`, `parameter_out_of_bounds`, `processing_error`) — nunca filtrar
  `str(exc)`/traza.
- **C1 · Módulo.** Crear `backend/app/api_public/modules/robustness/` con:
  - `meta.py` → `MODULE = {name:"robustness", version:"0.1.0", gating_tag:"robustness", router, description:...}`.
  - `models.py` → DTOs request/response (espejo PRD §3, validación de rangos → 400 `parameter_out_of_bounds`).
  - `mapper.py` → DTO ⇆ resultado del service; aplicar **reglas de payload** del core (downsample de
    curvas, `include` selectivo) igual que hace `backtest`.
  - `router.py` → `POST /v1/robustness/montecarlo`, `/v1/robustness/walk-forward` (+ `GET …/result/{task_id}`),
    `/v1/robustness/sensitivity`, `/v1/robustness/black-swan`. Auth API-key + rate limit + metering
    vía el core (igual patrón que `modules/backtest/router.py`).
  - Registrar `robustness` en `config.ENABLED_MODULES`.
  - *Test:* `backend/app/api_public/tests/test_robustness_module.py` (auth requerida; error interno NO
    filtra traza; gating `can_access` con default permitir). **`test_architecture.py` debe seguir verde**
    (el módulo NO importa el motor; solo el facade).
  - *Verif:* `cd backend && pytest app/api_public/tests/ -q` (incl. los 36 previos + nuevos) verde.

### EPIC D — Documentación de API + MCP

- **D1 · OpenAPI vivo + doc de contrato.** Verificar que `/v1/openapi.json` (`api_public/app.py:58`)
  incluye los nuevos endpoints. Regenerar el snapshot `docs/b2d-gateway/openapi.generated.json` y
  reflejar el contrato en `docs/robustez/` (el §3 del PRD ya es la fuente). Si existe script de
  generación, usarlo; si no, exportar `app.openapi()`.
- **D2 · MCP catálogo.** En `mcp/src/components.ts` añadir el módulo `robustness` con sus componentes
  escogibles sueltos, cada uno con su `include`:
    - `montecarlo_spaghetti` (percentiles), `drawdown_histogram`, `wfe_heatmap` (WFO),
      `locate_sensitivity_chart` + `critical_locate_indicator`, `blackswan_sensitivity_matrix`.
  Actualizar `list_modules`/`list_components` para que devuelvan `robustness`.
- **D3 · MCP cliente + docs + tests.** Regenerar el cliente tipado (`generate_api_client` lee
  `schema://openapi`), añadir `docs://robustness` y `templates://robustness/{component}` si aplica.
  - *Verif:* `cd mcp && npm run build && npm test` (tsc estricto 0 errores; vitest verde, incl. costura
    MCP→API en vivo si está disponible).

### EPIC E — Product Analytics (PostHog)

> Solo frontend (no hay PostHog server-side). La analítica de la API comercial es el `usage_ledger`
> existente — no se duplica.

- **E1 · Taxonomía.** En `frontend/src/lib/analytics.ts` añadir a `EVENTS`:
  `ROBUSTNESS_STRATEGY_SELECTED`, `ROBUSTNESS_MODULE_VIEWED`, `ROBUSTNESS_MONTECARLO_RUN`,
  `ROBUSTNESS_WFO_RUN`, `ROBUSTNESS_SENSITIVITY_RUN`, `ROBUSTNESS_BLACKSWAN_RUN`.
- **E2 · Instrumentación.** Llamar `track(EVENTS.X, props)` en cada sitio de acción de la página de
  Robustez (props útiles y **sin PII**: `module`, `run_id`, `simulations`, `period_unit`, etc.). El
  pageview de `/robustness` lo cubre el `PostHogPageView` global ya montado.
  - *Verif:* `npm run build` verde; en `npm run dev`, confirmar los eventos en la consola/red de PostHog
    al ejecutar cada módulo.

---

## 3 · Definition of Done

**Por tarea:** test escrito y verde · comando de verificación corrido y pegado · commit atómico.
**Global:**
- [ ] `pytest tests/ -q` verde (4 tests nuevos + loader) y `pytest app/api_public/tests/ -q` verde (incl. `test_architecture.py`).
- [ ] `npm run build` y `npm run lint` verdes (frontend) y `cd mcp && npm run build && npm test` verde.
- [ ] Los 4 módulos responden con datos reales de un run del Baúl; WFO completa por polling.
- [ ] **API comercial:** los 4 módulos expuestos bajo `/v1/robustness/*` con auth API-key, metering y errores sin fugas; `robustness` en `ENABLED_MODULES`.
- [ ] **Docs API:** `/v1/openapi.json` incluye robustness; snapshot OpenAPI regenerado.
- [ ] **MCP:** módulo `robustness` en el catálogo con componentes e `include`; cliente tipado regenerado.
- [ ] **PostHog:** eventos `robustness_*` en la taxonomía e instrumentados (sin PII).
- [ ] Edge cases del §2.6 cubiertos con test.
- [ ] Sin tocar el core/motor (solo importar/llamar vía facade). Sin secretos commiteados.
- [ ] Tooltips y colores semánticos según §04/§07.

## 4 · Comandos de verificación exactos

```bash
# Backend
cd backend && source .venv/bin/activate
pytest tests/test_robustness_loader.py tests/test_montecarlo_bootstrap.py \
       tests/test_wfo_engine.py tests/test_sensitivity.py tests/test_black_swan.py -q
pytest tests/ -q
uvicorn app.main:app --reload --port 8010

# API comercial (Gateway B2D)
cd backend && pytest app/api_public/tests/ -q          # incl. test_architecture.py + test_robustness_module.py

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000/robustness
npm run build && npm run lint

# MCP
cd mcp && npm run build && npm test          # tsc estricto + vitest
```

## 5 · Orden de PRs sugerido (incremental, verde en cada paso)

1. **PR-1 Andamiaje + loader** (A0): router vacío registrado + `_load_trades` + test loader.
2. **PR-2 Cálculo rápido** (A1, A3, A4): Montecarlo + Sensibilidad + Black Swan + sus tests + endpoints internos.
3. **PR-3 WFO** (A2 + parte de A5): motor en background + polling + test.
4. **PR-4 Frontend datos** (B1, B2): cliente, página, grid del Baúl.
5. **PR-5 Frontend visual + analytics** (B3, B4, B5, E1, E2): config, charts, tooltips, color semántico, eventos PostHog.
6. **PR-6 API comercial** (C0, C1): facade + módulo `robustness` en `api_public` + tests (arquitectura verde).
7. **PR-7 Docs API + MCP** (D1, D2, D3): OpenAPI regenerado + catálogo MCP + cliente tipado + tests.

Cada PR: verde en CI, sin tocar el core/motor, con su slice de tests. Revisión humana entre pasos.
PR-1→5 entregan el feature en la app web; PR-6→7 lo comercializan (API+MCP) y documentan.

---

## Decisiones abiertas (dueño: Jesús — NO decidir en el goal)

- **Cap de combinaciones WFO** (recomendado 50 en MVP). Asumido reversible; documentar.
- **Semántica `run_id` vs `strategy_id`** en el contrato público (el goal usa `run_id` con alias).
- **Gating/monetización del módulo `robustness`** en la API comercial: el módulo declara su
  `gating_tag`; QUÉ es gratis/pago y para quién lo decide Jesús (`docs/b2d-gateway/07`). El goal NO
  fija política. Ver memoria "No decidir negocio".
- **¿`robustness` entra en `ENABLED_MODULES` por defecto?** Default técnico: activado en dev,
  decisión de exposición pública = Jesús.
- Defaults reversibles ya asumidos: `simulations=1000`, trimestre ≈ 65 trades (~260 días/año).
