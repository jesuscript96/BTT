# 05 — Arquitectura (modular, fachada, auth, ejecución, despliegue)

> **Propósito:** cómo se monta el sistema sobre el backend existente **sin tocar el motor**, con
> **modularidad por módulos**, aislamiento de IP, metering y despliegue.

---

## 0. Principio rector: API modulada por módulos

> Lo que Jesús pidió explícitamente: el MVP es **una API modulada por módulos**.

- Cada **módulo** = un dominio del producto, como **paquete autocontenido** en `api_public/modules/`:
  ```
  api_public/
    modules/
      backtest/        # MVP: endpoints + DTOs + mapper a la fachada + tag de gating
        router.py  models.py  mapper.py  meta.py   # meta.py declara: nombre, endpoints, gating
      screener/        # v2 — misma forma
      ticker_analysis/ # v2 — misma forma
    core/              # auth, metering, gating, errores, payload-rules (transversal)
    facade.py          # único puente al motor
    app.py             # monta los módulos habilitados
  ```
- **Reglas del contrato de módulo** (todo módulo cumple lo mismo):
  1. Expone sus endpoints bajo `/v1/<modulo>/…` y declara su `meta` (nombre, versión, **tag de gating**).
  2. Importa el core **solo vía `facade.py`** (aislamiento de IP).
  3. Sus respuestas pasan por las **reglas de payload** comunes (downsample/paginar/`include`).
  4. Es **activable/desactivable** por config (`ENABLED_MODULES`) y **gateable** de forma independiente.
- El **gating es transversal y por módulo**: `core` provee `can_access(api_key, module, action)`. La
  **política** (qué módulo es gratis/pago, a quién, cuándo) NO vive en el módulo ni en este plan —
  es config que decide Jesús después (doc 07 §A).
- El **catálogo del MCP** ya está organizado `módulo → componente` (doc 04 §1), así que la
  modularidad del MCP y la de la API son la **misma estructura** end-to-end.
- **MVP entrega solo el módulo `backtest`** + el core transversal. Los demás módulos se añaden con la
  misma plantilla sin rearquitectura.

---

## 1. Vista de capas

```
┌─────────────────────────────────────────────────────────────────────┐
│  TRADER LOCAL (Cursor / Claude Code)                                  │
│    └── Edgecute MCP (TS)  ── HTTPS+API-key ──┐                         │
└───────────────────────────────────────────────┼──────────────────────┘
                                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EDGECUTE BACKTEST API  (capa pública NUEVA, aislada)                 │
│  app/api_public/  (o microservicio aparte)                            │
│   • Auth API-key + rate limit + metering        [store propio]        │
│   • Validación de entrada (Pydantic, espejo del DSL)                  │
│   • Mapeo DTO ⇆ backend  +  handler de errores PROPIO (sin fugas)     │
│   • Cola de jobs (encolar / progreso / cancelar)                      │
│   • Reglas de payload (downsample, paginación, export firmado)        │
└───────────────┬───────────────────────────────────┬──────────────────┘
                │ (solo interfaces de fachada)        │
                ▼                                      ▼
┌──────────────────────────────┐      ┌──────────────────────────────────┐
│  EJECUCIÓN (MVP: en-request)  │      │  STORE de plataforma (NUEVO)      │
│   run_backtest_orchestrator() │      │   MVP → Postgres: api_keys,       │
│   resolve_universe()          │      │          usage_ledger             │
│   validate_strategy()         │      │   (planes = constantes en código) │
│   [v2: worker async + cola]   │      │   Object store (GCS): exports     │
└───────────────┬──────────────┘      │   [v2: Redis rate-limit/cola]     │
                │ (NO importable desde la capa pública)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MOTOR + DATOS (IP — INTOCABLE)                                       │
│   backtester/engine.py (Numba JIT) · services/indicators.py          │
│   services/portfolio_sim.py · DuckDB/Parquet GCS/MotherDuck intradía  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Aislamiento de IP (cómo se cumple la restricción nº3 del doc 01)

- La capa `api_public` **solo** importa una **interfaz de fachada** explícita, p.ej.
  `app/api_public/facade.py`:
  ```python
  # facade.py — ÚNICO puente permitido hacia el core
  from app.services.backtest_orchestrator import run_backtest_orchestrator, BacktestRequest
  from app.services.data_service import _resolve_filters, fetch_qualifying_data  # universo
  from app.schemas.strategy import StrategyCreate  # validación de estrategia (Pydantic, standalone)
  # PROHIBIDO: importar engine.py, indicators.py, portfolio_sim.py directamente
  # NOTA: backtester/backtest_validator.py valida RESULTADOS (VectorBT), no estrategias de entrada.
  ```
- **Handler de errores propio** (NO el de `main.py`, que filtra `str(exc)`):
  ```python
  @app.exception_handler(Exception)
  async def public_handler(request, exc):
      rid = request.state.request_id
      log.error("internal", request_id=rid, exc_info=exc)   # trace SOLO en logs
      return JSONResponse(500, {"error": {"code": "internal_error",
          "message": "Error interno.", "request_id": rid}})  # nada más
  ```
- **DTO allow-list:** la respuesta se construye campo a campo desde un mapper, nunca
  `return motor_obj`. Test de fuzzing que provoca errores y asserta que ninguna respuesta contiene
  rutas de fichero, nombres de función internos ni "Traceback".
- **Lint/guard:** un test de arquitectura (import-linter o un grep en CI) **falla** si `api_public/`
  importa `engine`, `indicators` o `portfolio_sim` fuera de `facade.py`.

---

## 3. Autenticación y autorización

- **API-keys propias**, no Clerk. Razón: Clerk (`auth/clerk.py`) emite JWT de sesión de usuario
  web (corta vida, browser). Un developer necesita credenciales **largas, revocables, con scope y
  rate-limit por key**, usables desde un servidor/IDE.
- Modelo:
  - `api_keys`: `id, prefix (ek_live_/ek_test_), hash, owner_id, plan_id, scopes, status, created, last_used`.
  - Se guarda **hash** (argon2/bcrypt) de la key, nunca la key. Se muestra una sola vez al crearla.
  - Resolución por prefijo → lookup → verificación hash → carga plan + límites.
- **Puente con Clerk (opcional):** el dashboard donde el humano gestiona sus keys puede seguir
  detrás de Clerk; solo la **API de máquina** usa keys. `owner_id` puede ser el `user_id` de Clerk.

---

## 4. Ejecución (MVP síncrono con cap · async = escalado v2)

> **Decisión de Jesús (doc 01 §1.1-bis):** el MCP es solo build-time, así que el runtime es la app
> del trader (cliente HTTP normal). El MVP **no necesita cola/worker**: ejecuta síncrono como el
> `/backtest` actual, acotado por un cap.

### MVP — síncrono

- `POST /v1/backtests`:
  1. Auth + rate-limit + `preview_universe` interno → `ticker_days` y créditos.
  2. Si `ticker_days > plan.limit` → `422 universe_too_large`. Créditos insuficientes → `402`.
  3. Resuelve universo (`_resolve_filters`) → `run_backtest_orchestrator(req)` **en la request**.
  4. Aplica reglas de payload (downsample `global_equity`, pagina `trades`, `include` selectivo,
     sube export a object store si se pide).
  5. **Carga créditos al ledger** (con `ticker_days`/`n_trades` reales que el orquestador ya conoce),
     responde `200` con `status:"succeeded"` + `result`.
- Progreso opcional: el cliente puede pollear `GET /v1/backtests/{id}` (reusa `backtest_progress`)
  mientras la respuesta está en vuelo, o ignorarlo.
- **Cap duro** `ticker_days` → garantiza terminar dentro del envelope de plataforma y acota coste.
  - **Plataforma real:** Railway + **uvicorn pelado** (`DEPLOYMENT.md`), sin timeout configurado en
    código; el límite lo pone el edge de Railway (permisivo, sin corte corto tipo Heroku).
  - **El envelope ya está probado:** el `/backtest` actual **ya corre síncrono en prod** en este mismo
    stack → la API hereda ese margen. **Sizing del cap** = un load test del universo grande contra el
    backend desplegado, medir wall-clock, fijar cap con margen.
  - ⚠️ Si se migra a **Render**, su timeout de respuesta (~100s) es más agresivo: revisar antes.

### Escalado v2 — async (cuando un tier permita universos grandes)

- `POST` crea `job` en Postgres, encola en Redis (`arq`/`rq`/`celery`), responde `202 + job_id`.
- **Worker** separado ejecuta y persiste el resultado (en object store si es grande); el cliente
  pollea `GET /v1/backtests/{id}`. El contrato ya soporta esto (`status`), sin romper a nadie.
- **Concurrencia/locks:** acceso al histórico en **solo lectura**; metering/keys/jobs en
  Postgres/Redis, **no en `users.duckdb`** (evita los locks que documenta el código).

---

## 5. Mecanismo de metering y gating (la POLÍTICA es de producto, diferida)

> **Importante:** este plan entrega el **mecanismo**, no la **política**. *Qué* se cobra/bloquea, *a
> quién* y *cuándo* es decisión de producto de Jesús, **diferida** (doc 07 §A). No hay tiers ni
> precios en este plan.

- **Metering (siempre on):** `usage_ledger` (Postgres, append-only): `id, api_key_id, module,
  ticker_days, trades, ts`. El orquestador ya expone `n_qualifying`/`n_trades` → registro exacto sin
  instrumentar el motor. Sirve para cualquier política futura (créditos, cuotas, facturación…).
- **Hook de gating por módulo:** la API consulta `can_access(api_key, module, action)` antes de
  servir. En el MVP la implementación por defecto es **permitir todo** (o leer un flag simple); la
  tabla/política real se rellena cuando Jesús decida. El `if` existe; la regla la pones tú.
- **Identidad:** owner de la key = `user_id` de Clerk → puente directo con lo que la app decida
  (tiers de Stripe u otro) sin tocar la API.
- **Cap de tamaño por request** (ticker-días): control **técnico** para acotar latencia/coste de la
  API síncrona. Su valor y si varía por política es parte de la decisión diferida.
- **Rate limit:** token-bucket **en proceso** por `api_key` (`429` + `Retry-After`). Redis diferido a v2.
- **No incluido en este plan:** tiers, precios, fórmula de créditos, Stripe. Son política de producto.

---

## 6. Dónde vive la capa pública

Dos opciones (decisión en doc 07; recomendación abajo):

| Opción | Pro | Contra |
|---|---|---|
| **A. Mismo repo, app FastAPI aparte** `backend/app_public/` que importa la fachada | Reusa entorno, datos y deploy; más rápido de montar | Comparte proceso/imagen con el core (riesgo de import accidental → mitigado por guard de imports) |
| **B. Microservicio separado** que llama al core por RPC/HTTP interno | Aislamiento físico de la IP; escala y se despliega aparte | Más infra; latencia extra; hay que exponer un RPC interno |

> **Recomendación MVP: Opción A** con **guard de imports en CI** + handler propio + worker en
> proceso separado. Migrar a B si/ cuando el volumen o el riesgo de IP lo justifiquen. Coste de
> migración bajo porque la fachada ya es el único puente.

---

## 7. Despliegue (alineado con lo actual)

- El backend hoy se despliega en Render/Railway + Vercel (front) con DuckDB/GCS/MotherDuck
  (`DEPLOYMENT.md`, `AUDITORIA_TECNICA_RESUMEN.md`). La API pública (MVP mínimo):
  - **API**: 2º servicio en el mismo proveedor (o mismo contenedor, entrypoint `api_public.app`).
    **Sin worker** (síncrona).
  - **Postgres gestionado** (Neon/Railway): solo `api_keys` + `usage_ledger`. NO usar `users.duckdb`.
    **Redis diferido** (no en MVP).
  - **Object store**: GCS (ya hay credenciales `GCS_KEY_*`) para exports firmados.
  - **MCP**: publicado en npm como `@edgecute/mcp` (`npx`), versionado con el OpenAPI.
- **Observabilidad:** structured logs por `request_id`/`job_id`; PostHog ya está en el repo
  (commit `posthog mejor`) → reutilizable para métricas de uso de la API.

---

## 8. Seguridad (checklist)

- [ ] API-keys hasheadas, scope y revocación; rotación documentada.
- [ ] Rate-limit + cap de universo por request (anti-abuso y anti-DoS económico).
- [ ] Handler de errores propio sin `str(exc)`; test de no-fuga.
- [ ] Guard de imports: `api_public` no importa el motor salvo vía fachada.
- [ ] Sin OHLCV crudo a granel por la API (solo intradía puntual con tope).
- [ ] CORS restrictivo (la API B2D es server-to-server; no necesita CORS amplio como el web app).
- [ ] Secrets por env (`CODING_RULES.md`); nunca en repo.
- [ ] Validación estricta de entrada (Pydantic) antes de encolar.

---

## 9. Lo que se reutiliza vs lo que es nuevo

| Reutilizado (no se toca) | Nuevo (este proyecto) |
|---|---|
| `engine.py`, `indicators.py`, `portfolio_sim.py` | Capa `api_public` (fachada + DTOs + handler) |
| `run_backtest_orchestrator`, `_resolve_filters` | Auth API-key + rate limit + metering |
| `backtest_validator.py` | Cola de jobs + worker + estados |
| Datos intradía DuckDB/GCS/MotherDuck | Store de plataforma (Postgres/Redis/object store) |
| Formato `{time,value}` de series | Reglas de payload (downsample/paginar/export) |
| PostHog | MCP `@edgecute/mcp` (TS) + plantillas de componentes |
