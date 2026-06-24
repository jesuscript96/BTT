# 06 — Prompt maestro de ejecución

> **Propósito:** el guion que un loop de ejecución (Claude Code / Cursor) sigue para construir
> todo. Tareas atómicas, TDD, Definition of Done y comandos exactos de verificación. **No** empezar
> hasta firmar el doc 07.

---

## 0. Contexto que el agente DEBE leer antes de tocar nada

1. `docs/b2d-gateway/01_VIABILIDAD.md` … `05_ARQUITECTURA.md` (este suite completo).
2. El código fuente real (la verdad): `backtest_orchestrator.py`, `backtest_service.py`,
   `schemas/strategy.py`, `auth/clerk.py`, `main.py`, `backtest_validator.py`.
3. `.agent/CODING_RULES.md` (reglas del repo) y `docs/BACKTESTER_BRAIN.md` (semántica de dominio).

---

## 1. Restricciones globales (no negociables)

- **NO tocar** `backtester/engine.py`, `services/indicators.py`, `services/portfolio_sim.py`, ni
  el schema de `daily_metrics`/`intraday_1m` (lista "no tocar" de `CODING_RULES.md`). La API es una
  **capa nueva**; si necesitas algo del core, exponlo vía `facade.py`, no editando el core.
- **Aislamiento de IP:** `api_public/` solo importa del core a través de `facade.py`. Prohibido
  importar el motor directamente. Un test de CI lo verifica.
- **Sin fugas:** ninguna respuesta de error lleva `str(exc)`, traces ni nombres internos.
- **Contrato derivado, no a mano:** OpenAPI desde Pydantic; tipos TS del MCP desde el OpenAPI.
- **Backend manda:** si un doc y el código discrepan, gana el código → anota la divergencia y sigue.
- **Lenguajes:** API en Python (FastAPI, igual que el repo). MCP en **TypeScript estricto**
  (`tsconfig` con `strict: true`, `noUncheckedIndexedAccess`). Sin `any` salvo límite justificado.
- **TDD:** test primero, luego implementación, luego verde. Nada de código de producción sin test.
- **Un paso atómico a la vez**; verificar (comando exacto) antes de pasar al siguiente.
- **Mover, no borrar:** si hay que retirar código, va a `_archive/` (regla del repo).
- **Sin secrets en repo**; todo por `os.getenv` / env del MCP.

---

## 2. Secuenciación atómica

> Cada tarea: (a) escribe el test, (b) implementa, (c) corre el comando de verificación, (d) commit
> con mensaje convencional. No avanzar si el comando no pasa.

### EPIC A — Andamiaje modular y contrato

- **A1. Estructura modular** (doc 05 §0). Crear:
  `backend/app/api_public/` con `app.py` (monta `ENABLED_MODULES`), `facade.py` (único puente al
  motor), `core/` (`auth.py`, `metering.py`, `gating.py`, `errors.py`, `payload.py`, `ratelimit.py`)
  y `modules/backtest/` (`router.py`, `models.py`, `mapper.py`, `meta.py`). Y `mcp/` (paquete TS).
  **Verif:** `python -c "import app.api_public"` ok; el módulo `backtest` se monta vía su `meta.py`;
  `cd mcp && npm i && npm run build` ok.
- **A2. Modelos Pydantic** (`modules/backtest/models.py`): `UniverseSpec`, `Strategy` (reusar
  `schemas/strategy.py` donde sea idéntico), `Execution`, `BacktestCreate`, `BacktestResult`, DTOs.
  **Test:** round-trip de los ejemplos del doc 03 valida sin error.
- **A3. Generar OpenAPI** desde la app FastAPI y **diff contra** `openapi.draft.yaml`; actualizar el
  draft a la realidad. **Verif:** `GET /v1/openapi.json` responde y `openapi-spec-validator` pasa.
- **A4. Handler de errores propio** (`errors.py`) con el catálogo cerrado del doc 03 §6. **Test:**
  forzar excepción interna y assert que la respuesta == `{error:{code:"internal_error",...}}` sin trace.

### EPIC B — Auth, metering, límites (MVP mínimo: solo Postgres)

> **Solo MECANISMO, no política.** Nada de tiers/precios/quién-se-bloquea (decisión diferida de
> producto, doc 07 §A). Se construye el metering y el hook de gating; la política se rellena después.

- **B1. Store de plataforma.** Migraciones Postgres: **`api_keys`** + **`usage_ledger`** (2 tablas).
  **Sin tabla de planes** (la política llega luego) y **sin tabla `jobs`** (API síncrona). **Verif:**
  migración aplica y revierte limpio.
- **B2. Auth API-key** (`core/auth.py`): resuelve `Authorization: Bearer ek_…`, verifica hash (argon2),
  owner = Clerk `user_id`. **Test:** key válida/ inválida/ revocada → 200/401/403.
- **B3. Rate limit** **en proceso** (token-bucket por key). **Redis = v2.** **Test:** ráfaga → 429 con `Retry-After`.
- **B4. Metering** (`core/metering.py` → `usage_ledger`, append-only, con `module`). **Test:** un run
  graba `ticker_days`/`trades` reales del orquestador.
- **B5. Hook de gating por módulo** (`core/gating.py`): `can_access(api_key, module, action)`. **Default
  MVP = permitir todo** (o leer un flag simple); la política es config futura. **Test:** el hook se
  invoca en cada endpoint de módulo y es overrideable por config sin tocar el módulo.
- **B6. Cap técnico de tamaño** (`core`, independiente de cualquier tier): `ticker_days > CAP` → `422
  universe_too_large`. **Test:** universo sobre el cap → `422` con `details.ticker_days`.

### EPIC C — Universo y validación (sin ejecutar el motor)

- **C1. `POST /v1/universe/preview`** vía `facade.resolve_universe` → `ticker_days`, `within_cap`.
  **Test (integración ligera):** un universo pequeño conocido da el conteo esperado.
- **C2. `POST /v1/strategies/validate`** validando contra el modelo Pydantic `StrategyCreate`
  (`schemas/strategy.py`), standalone, sin tocar el motor. (NO usar `backtest_validator.py` — ese
  valida resultados, no entrada.) **Test:** estrategia válida → `{valid:true}`; inválida → errores con `path`.
- **C3. `GET /v1/catalog/indicators`** derivado de `IndicatorType`. **Test:** incluye VWAP, RSI, PM High…

### EPIC D — Ejecución del backtest (MVP SÍNCRONO con cap)

> Decisión: API síncrona con cap (doc 01 §1.1-bis). **Sin cola/worker en el MVP.** Async = v2 (EPIC G).

- **D1. Endpoint síncrono.** `POST /v1/backtests`: auth + gating(`backtest`) + rate-limit + cap
  técnico → si excede `422 universe_too_large`; si ok, resuelve universo y llama
  `facade.run_backtest_orchestrator` **en la request**, registra en el ledger, responde `200` con
  `status:"succeeded"` + `result`. **Test (dataset mock):** devuelve `result` con `aggregate_metrics`.
- **D2. (cubierto por B6)** el cap técnico de `ticker_days` se aplica antes de ejecutar.
- **D3. Reglas de payload.** Downsample LTTB de `global_equity` > N puntos; paginar `trades`
  (`limit/cursor`); `include` selectivo. **Test:** `include=["metrics"]` no trae `trades`; equity
  grande viene downsampled con `meta.downsampled:true`.
- **D4. Export firmado** de trades completos a object store. **Test:** `export_url` accesible y expira.
- **D5. Intradía bajo demanda.** `GET /v1/backtests/{id}/intraday?ticker&date` → una serie. **Test.**
- **D6. Progreso/cancel (opcional).** `GET /v1/backtests/{id}` refleja `backtest_progress`;
  `POST …/cancel`. **Test.**

### EPIC E — Servidor MCP (TypeScript, BUILD-TIME)

> El MCP genera código y andamia componentes; **no ejecuta backtests de producción** (doc 04).

- **E1. Andamiaje MCP** (`@modelcontextprotocol/sdk`), `tsconfig` estricto, `gen` de tipos desde
  OpenAPI (`openapi-typescript`). **Verif:** `npm run build && npm test` verde.
- **E2. Cliente API** tipado (auth por env, backoff en 429/5xx, sin propagar traces). **Test (mock server).**
- **E3. Tools de codegen/docs** del doc 04 §2 (`list_modules`, `list_components`, `add_component`,
  `generate_api_client`, `get_types`, `validate_strategy`, `preview_universe`, `list_recipes`).
  **Test:** cada tool contra mock; `add_component` produce ficheros que compilan; errores accionables.
- **E4. `run_sample_backtest` (dev-only)** contra sandbox `ek_test_`; marcado como conveniencia de
  desarrollo, nunca runtime. **Test:** rechaza `ek_live_`/universos grandes.
- **E5. Resources** (`schema://`, `docs://`, `templates://backtest/*`) del doc 04 §3. **Test:** se listan y leen.
- **E6. Plantillas granulares** adaptadas de `frontend/src/components/backtester/` (MetricsCard,
  TradeTable, MaeScatterChart, RollingEVChart, RollingAvgRChart, EquityCurveTab). Cada componente
  declara su `include`. **Verif:** un Next mínimo renderiza cada pieza con un `result` de ejemplo.
- **E7. Prompts MCP** (`design_strategy`, `build_dashboard`, `analyze_results`). **Test:** se exponen.

### EPIC G — (v2, NO MVP) Jobs async para universos grandes

- Cola (Redis) + worker + estados `queued/running`; `POST` → `202+job_id`; polling `GET`. El
  contrato ya lo soporta (`status`), así que es aditivo y no rompe clientes del MVP síncrono.

### EPIC F — Calidad, docs, release

- **F1. Test de contrato** API↔OpenAPI en CI (schemathesis o equivalente). **Verif:** pasa.
- **F2. Guard de imports** (`api_public` no importa el motor salvo en `facade.py`). **Verif:** CI falla si se viola.
- **F3. Test de no-fuga** (fuzz de errores → 0 traces/paths internos). **Verif:** pasa.
- **F4. Quickstart** (`docs://getting-started`): de `npx` a primer backtest. **Verif:** seguible en < 10 min.
- **F5. Publicar** `@edgecute/mcp` (npm, versión alineada al OpenAPI) y desplegar API+worker. **Verif:**
  smoke test e2e con `ek_test_` contra dataset sandbox.

---

## 3. Definition of Done (por tarea y global)

**Por tarea atómica:**
- [ ] Test escrito **antes** y ahora en verde.
- [ ] Comando de verificación de la tarea pasa.
- [ ] Sin regresiones: `cd backend && pytest` y `cd mcp && npm test` verdes.
- [ ] Sin fugas de IP introducidas (handler propio respetado).
- [ ] Commit convencional (`feat(api): …`, `feat(mcp): …`, `test: …`).

**Global (release-ready):**
- [ ] `GET /v1/openapi.json` válido y **0 drift** con la implementación (F1).
- [ ] Guard de imports verde (F2). Test de no-fuga verde (F3).
- [ ] e2e con `ek_test_`: `preview_universe → validate_strategy → run_backtest → get_backtest` ok.
- [ ] MCP instalable con `npx` y los 9 tools responden contra la API real (sandbox).
- [ ] Quickstart reproducible por alguien externo en < 10 min.

---

## 4. Comandos de verificación (exactos)

```bash
# Backend (API pública)
cd backend && source .venv/bin/activate
pytest tests/ -q                                  # toda la suite
pytest tests/test_api_public_*.py -q              # solo la API nueva
python -c "import app.api_public"                 # import sano
uvicorn app.api_public.app:app --port 8100        # arranque local
python -m openapi_spec_validator <(curl -s localhost:8100/v1/openapi.json)

# Guard de imports (ejemplo con grep; sustituible por import-linter)
! grep -rEn "from app.backtester|import.*engine|indicators|portfolio_sim" backend/app/api_public --include=*.py | grep -v facade.py

# MCP (TypeScript)
cd mcp
npm ci && npm run gen && npm run build           # gen tipos desde OpenAPI + build
npm test                                          # tests contra mock server
npx @modelcontextprotocol/inspector node dist/index.js   # smoke manual de tools
```

---

## 5. Orden de PRs sugerido (incremental, revisable)

1. PR-1: EPIC A (andamiaje + contrato + handler). Pequeño, sienta las bases.
2. PR-2: EPIC B (auth + store + metering).
3. PR-3: EPIC C (universo/validación/catálogo) — ya da valor demoable sin ejecutar el motor.
4. PR-4: EPIC D (jobs + worker + payload) — el corazón.
5. PR-5: EPIC E (MCP completo).
6. PR-6: EPIC F (calidad + release).

> Cada PR: verde en CI, sin tocar el core, con su slice de tests. Revisión humana entre PRs
> (Jesús trabaja en su rama; los merges los hace otra persona — ver memoria de flujo de trabajo).
