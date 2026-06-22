# 01 — Análisis de viabilidad (Reality Check)

> **Objetivo:** confirmar que la *física* del proyecto (datos, payload, latencia, seguridad,
> límites de las herramientas) soporta la visión de negocio **antes** de invertir en desarrollo.
>
> **VEREDICTO (resumen):** ✅ **Viable** — y, además, **ya construido y testeado** en la rama
> `api-jesus` (2026-06-22). Detalle abajo.

---

## Estado: esta versión está reconciliada con el MVP CONSTRUIDO

> Este análisis se escribió antes de desarrollar; esta versión está **alineada con lo que de hecho
> está en la rama `api-jesus`**. Mapa de "lo que dice el análisis ↔ lo que está construido"
> (estado exhaustivo en [`BUILD_STATUS.md`](BUILD_STATUS.md)):

| Decisión del análisis | Estado en `api-jesus` |
|---|---|
| Aislamiento por fachada + handler de errores sin fugas | ✅ Construido (test de no-fuga + guard de imports en CI) |
| Payloads pesados no por defecto (downsample LTTB / paginar / `include` / intradía perezoso) | ✅ Construido |
| Cap técnico de ticker-días por request | ✅ Construido (`EDGECUTE_MAX_TICKER_DAYS`) |
| API **síncrona** (no async) | ✅ Construido · async = **v2** |
| Metering (`usage_ledger`) + hook de gating por módulo (default permitir) | ✅ Construido · política de cobro diferida |
| MCP build-time (codegen + componentes + docs) | ✅ Construido (17 tests + e2e) |
| Panel de developer (keys / uso / billing / playground) | ✅ Construido (8 tests) |
| **Universo por filtros del screener** | ⏳ **v2** — el MVP usa `dataset_ref` (dataset existente) o `mock_dataset_1`; con filtros devuelve `not_implemented` accionable |
| **Export de trades a URL firmada (CSV/Parquet)** | ⏳ **v2** — el campo `export_url` está reservado en el contrato pero aún no genera el fichero |
| Store **Postgres/Redis**, créditos prepago, cola/worker | ⏳ **v2** — el MVP usa **SQLite** + rate-limit **en proceso**, sin cola |

> Lo único que NO se pudo verificar localmente: un backtest real end-to-end con datos reales
> (MotherDuck/GCS). La API llama al **mismo `run_backtest_orchestrator` que ya usa la web en prod**;
> falta una pasada con un `dataset_ref` real + un load test para fijar el cap.

---

## 0. El hallazgo que lo cambia todo: *el dato es el moat, no el motor*

Auditando `backtest_orchestrator.py` y `backtest_service.py` queda claro que un backtest **no
se puede ejecutar sin un `dataset_id`** que apunta a:

1. **Pares ticker–fecha "cualificados"** (`fetch_qualifying_data`), y
2. **Datos intradía de 1 minuto** cacheados server-side en DuckDB / Parquet en GCS / MotherDuck
   (`get_intraday_stream`, ver `main.py` precache y `docs/hot_storage_spec.md`).

El trader indie **no tiene estos datos en local**. Por tanto:

> **Condición de diseño nº1 (no negociable):** la API B2D no es "envíame tu CSV y te lo
> backtesteo". Es **"apunta a un universo definido en MI base de datos + una estrategia, y yo lo
> resuelvo contra MIS datos intradía y te devuelvo métricas"**. El valor que se cobra es **motor
> JIT propietario + datos intradía limpios + universo de gaps**. Eso es lo que el trader no puede
> replicar en casa, y es lo que justifica el cobro.

Implicación directa en la API: además de "estrategia" y "ejecución", **el formulario de entrada
incluye la referencia al universo**.

> **Estado del universo (MVP vs v2):** el MVP construido referencia un **dataset existente**
> (`universe.dataset_ref`) — o `mock_dataset_1` para el sandbox — y lo resuelve con
> `fetch_qualifying_data`. La **creación de universo por filtros del screener al vuelo**
> (`backend/app/routers/screener.py`, `query.py`) requiere el pipeline de precache y queda como
> **v2** (la API devuelve `not_implemented` accionable si mandas filtros sin dataset). El moat es el
> mismo en ambos casos: el trader no tiene los datos intradía.

---

## 1.1 Auditoría de carga útil y latencia (el cuello de botella)

### Forma real del resultado (medida en código, no estimada)

`run_backtest()` (`backtest_service.py:658`) devuelve:

| Campo | Forma real | Tamaño que escala con… | Riesgo de payload |
|---|---|---|---|
| `aggregate_metrics` | dict plano (~26 métricas) | constante | 🟢 nulo (~1 KB) |
| `global_equity` | `[{time, value}]` **por trade** (no por minuto) | nº de trades | 🟡 medio |
| `global_drawdown` | `[{time, value}]` por trade | nº de trades | 🟡 medio |
| `global_equity_expenses` | `[{time, value}]` por trade | nº de trades | 🟡 medio |
| `day_results` | `[{ticker, date, total_return_pct, …}]` (~15 campos) | nº de ticker-días con trades | 🟡 medio |
| `trades` | `[{…25 campos…}]` (`_enrich_trades`) | nº total de trades | 🔴 alto |
| `equity_curves` | `[{ticker, date, equity:[{time,value}]}]` **intradía 1-min por ticker-día** | ticker-días × ~390–960 barras | 🔴🔴 **bomba de payload** |

### Las matemáticas del peor caso

- Universo "gap scanner" típico: ~30–80 tickers/día.
- 10 años ≈ 2.520 días de trading.
- → hasta **~125.000 ticker-días**. Cada uno con 390 (RTH) a 960 (extended) barras de 1-min.
- `equity_curves` intradía: 125.000 × ~400 puntos × ~20 B ≈ **~1 GB en un solo JSON**. Inviable.
- `trades`: un backtest grande puede generar 50k–200k+ trades × ~300 B ≈ **15–60 MB**. Inviable en línea.

### Decisiones de diseño que esto impone (entran al contrato, doc 03)

1. **`equity_curves` intradía NO se devuelven por defecto.** Es la curva minuto-a-minuto por
   ticker-día y es la bomba. Se ofrece **bajo demanda** en un endpoint aparte
   (`GET /v1/backtests/{id}/intraday?ticker=AAPL&date=2024-03-01`), una serie a la vez.
2. **`global_equity` se devuelve siempre** (está acotado por nº de trades, no por minutos) y,
   si supera N puntos, se aplica **downsampling LTTB** preservando picos/valles para gráficos.
3. **`trades` se paginan** (`?limit&cursor`), con un `default_limit` (500). *(El export del set
   completo a CSV/Parquet vía URL firmada está **reservado en el contrato** — campo `export_url` —
   pero la generación del fichero es **v2**; en el MVP el set completo se recorre por paginación.)*
4. **`day_results` y `aggregate_metrics` se devuelven íntegros** (siempre acotados y son el 90%
   del valor analítico).
5. **Field selection / verbosity**: parámetro `include` (`metrics`, `equity`, `trades`,
   `days`) para que el cliente pida solo lo que va a renderizar. Por defecto: `metrics,equity,days`.

### Latencia y timeouts

- El motor stremea día a día con Numba JIT; los logs (`[TIMING]`, `[STREAM]`) confirman tiempos
  en **segundos a minutos** según tamaño de universo×rango.

> **Restricción nº2 (REVISADA tras decisión de Jesús — MCP solo build-time):** el motivo original
> del "async obligatorio" era el **timeout del LLM (~30–120 s)** cuando el MCP ejecutaba backtests
> en runtime. Con el MCP **solo en build-time** (no ejecuta backtests de producción; ver doc 04),
> ese motor desaparece. El runtime es la **app del trader = cliente HTTP normal**, igual que la web
> app de Edgecute.
>
> **MVP: API SÍNCRONA con cap.** `POST /v1/backtests` ejecuta y responde el resultado, igual que el
> `/backtest` actual, con un **cap de ticker-días por request** que garantiza terminar dentro del
> timeout de plataforma. Progreso por **polling separado** (reusa `/api/backtest/progress` y
> `cancel`, que ya existen).
>
> **Escalado (v2): jobs async.** Cuando un tier permita universos grandes, `POST` devuelve
> `202 + job_id` y se hace polling de `GET /v1/backtests/{job_id}`. El contrato ya deja sitio
> (campo `status`), así que pasar de sync a async **no rompe clientes**.

### 1.1-bis ¿Por qué hay reglas de payload si nuestra propia app ya consume este backend?

Pregunta legítima. **A nivel de backend/cómputo no hay diferencia**: mismo motor, mismo POST, mismo
resultado. Verificado en el front real:

- `frontend/src/lib/api_backtester.ts:305` → `api.post("/backtest")` **síncrono**, espera el resultado completo.
- Progreso: **polling separado** de `/backtest/progress/{dataset_id}` (`:490`) para la barra.
- Intradía: **perezoso** vía `/candles?ticker&date` cuando hace falta (no empaquetado).

Es decir, la web app **ya hace** las dos cosas "inteligentes" que parecían requisitos nuevos. Las
reglas de payload NO nacen de que el backend sea distinto, sino de la **frontera**:

| Diferencia real | Nuestra app | API B2D |
|---|---|---|
| Cliente | Nuestro código, co-ubicado, controlado | Tercero, remoto, impredecible |
| Coste | No nos cobramos | **Cobramos** → hay que acotar coste/request (cap) |
| Contrato | Lo cambiamos a la vez en front+back | **Promesa pública versionada** → eficiente por defecto o no se arregla luego |
| Red | localhost / misma región | **Egress + latencia** por cada MB al dev remoto |

> **Conclusión:** las reglas (downsample/paginar/`include`/intradía perezoso) **no** son por carga de
> backend, son por ser un producto cobrable con clientes remotos y contrato estable. Y el patrón ya
> está probado en tu propia app — solo lo formalizamos en el contrato.

---

## 1.2 Aislamiento Cero-Confianza (protección de IP)

### Qué hay que proteger (la joya)

- `backend/app/backtester/engine.py` — **82 KB** de motor Numba/JIT.
- `backend/app/services/indicators.py` — **57 KB** de cálculo de ~90 indicadores.
- `backend/app/services/portfolio_sim.py` — simulación de cartera.
- La **base de datos intradía** + el universo de gaps.

### Estado actual y gaps

- ✅ El acoplamiento ya es razonable: el orquestador expone `run_backtest_orchestrator(req)` como
  fachada; los routers no contienen lógica (`CODING_RULES.md` lo exige).
- 🔴 **Gap crítico:** `main.py:238` `global_exception_handler` devuelve `{"message": str(exc)}`
  al cliente. Un trace o un mensaje interno puede filtrar nombres de funciones/tablas. **La API
  pública NO puede heredar este handler.**
- 🟡 Varios `print("[DEBUG ORCH] strategy_def keys: …")` en el orquestador — server-side, ok,
  pero la capa pública nunca debe reenviar logs/stdout.

> **Restricción nº3 (aislamiento) — ✅ construida así:** la API B2D vive en un **paquete separado**
> (`backend/app/api_public/`) que llega al motor **solo por `facade.py`** (`facade.run_backtest` →
> `run_backtest_orchestrator`; `facade.preview_universe` → `fetch_qualifying_data`) y **nunca**
> importa `engine.py` / `indicators.py` / `portfolio_sim.py` (un test de CI lo verifica). Reglas:
> - Manejador de excepciones **propio**: mapea todo a `{code, message_safe, request_id}` con
>   catálogo cerrado de errores; **jamás** `str(exc)` ni traces. El trace real va a logs server-side
>   indexados por `request_id`.
> - El DSL de estrategia **sí** se expone (es el input que el usuario rellena) — eso es contrato,
>   no IP. Lo que se protege es **cómo** se computa cada indicador, no que exista "RSI".
> - Respuestas filtradas por allow-list de campos (nunca serializar el objeto interno completo;
>   construir el DTO explícitamente).

---

## 1.3 Viabilidad del ecosistema MCP y LLMs

### Presupuesto de tokens de los esquemas

- `IndicatorType` tiene **~90 valores** y el schema de estrategia (`strategy.py`) es grande
  (condiciones recursivas, risk management, preconditions…). Si se inyecta crudo en cada
  descripción de tool, el contexto de Cursor/Claude se infla **~5–10k tokens solo en schema**.

> **Decisión MCP:** las **tools llevan schemas compactos y curados**; el catálogo completo
> (los ~90 indicadores, todos los comparadores, ejemplos) vive en **Resources** (`docs://…`,
> `schema://strategy`) que el LLM **lee bajo demanda**, no en cada turno. Se añade un tool
> ligero `list_indicators(category?)` para descubrimiento incremental. Esto mantiene el footprint
> de contexto < ~1.5k tokens en estado base.

### Compatibilidad de componentes (lo que el trader renderiza en casa)

- 🟢 **Muy favorable.** Las series ya salen en formato **`{time, value}`** (epoch + valor), que es
  exactamente el de **lightweight-charts** (TradingView), la librería que el propio frontend usa
  (`EquityCurveTab.tsx`, `Chart.tsx`). Los `trades` y `day_results` son tablas planas trivialmente
  renderizables (`TradeTable.tsx`, `MetricsCard.tsx`).
- → El MCP puede entregar **plantillas React listas** (`templates://equity-chart`,
  `templates://metrics-grid`, `templates://trades-table`) que consumen el JSON 1:1 sin
  transformación. Ver doc 04.

### Compatibilidad de clientes

- MCP estándar (JSON-RPC sobre stdio/SSE) → soportado por Claude Code, Cursor, Claude Desktop,
  Windsurf, Cline. Riesgo bajo. Recomendado **TypeScript** (`@modelcontextprotocol/sdk`) por ser
  el ecosistema dominante de esos IDEs y por alinear con la sugerencia de Gemini (TS estricto).

---

## 1.4 Viabilidad técnica de medir y gatear (NO del modelo de cobro)

> **El modelo de cobro (tiers, precios, qué se bloquea y a quién) es decisión de producto de Jesús
> y queda DIFERIDO (doc 07 §A).** Aquí solo se valida que, *técnicamente*, el MVP puede medir el uso
> y gatear por módulo — de modo que cualquier política que decidas después sea config, no código nuevo.

- ✅ **Medir es trivial y ya está al alcance:** el orquestador conoce `n_qualifying` (ticker-días) y
  `n_trades` antes de devolver → un **`usage_ledger`** por API-key registra consumo **sin instrumentar
  el motor**.
- ✅ **Gatear por módulo es un hook fino:** cada módulo (`backtest`, futuros `screener`…) lleva una
  marca de acceso; la API consulta `can_access(api_key, module)`. El `if` es trivial; lo no-trivial
  (la política) es lo que decides tú, luego.
- ✅ **Cap de tamaño por request** (ticker-días) es una necesidad *técnica* (acota latencia/coste para
  que la API síncrona termine dentro del timeout), independiente de cualquier tier.

> **Conclusión:** sí es viable cobrar/gatear cuando quieras, porque el MVP entrega **el mecanismo**
> (metering + hook por módulo). La **política** no es asunto de este plan.

---

## 2. Riesgos y mitigaciones

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Payload `equity_curves`/`trades` revienta memoria/red | 🔴 Alta | ✅ No-default + paginación + downsampling LTTB (export firmado = v2) (1.1) |
| Timeout del LLM en backtests | ⚪ N/A | El MCP es **build-time**, no ejecuta backtests de prod → no hay LLM en el hot path (§1.1-bis) |
| Fuga de IP por errores/traces | 🔴 Alta | ✅ Servicio fachada + handler propio + DTO allow-list (1.2) |
| Abuso/scraping del dataset histórico vía API | 🟠 Media | ✅ Rate limit + cap de ticker-días por request; sin OHLCV crudo a granel |
| Coste de CPU no acotado (DoS económico) | 🟠 Media | ✅ Cap duro de ticker-días (créditos/cola con prioridad = v2) |
| Deriva del contrato (el `types/backtest.ts` del front está **desincronizado** del backend) | 🟠 Media | ✅ El contrato se deriva del backend real (Pydantic) → `openapi.generated.json` |
| Estrategias inválidas que rompen el motor | 🟡 Baja | ✅ `validate_strategy` con el modelo **Pydantic `StrategyCreate`** antes de ejecutar (NO `backtest_validator.py`, que valida resultados) |
| Concurrencia DuckDB (locks de `users.duckdb`) | 🟡 Baja | ✅ La API solo lee el histórico; keys/metering en store propio (SQLite en el MVP, Postgres en v2), no en `users.duckdb` |

### ⚠️ Nota de contrato desincronizado (evidencia)

`frontend/src/types/backtest.ts` describe un `BacktestResult` con campos (`run_id`,
`final_balance`, `sharpe_ratio`, `equity_curve`, `monte_carlo`…) que **NO coinciden** con lo que
`backtest_service.py` devuelve hoy (`aggregate_metrics`, `day_results`, `equity_curves`,
`global_equity`…). **El contrato de la API se deriva del backend real** (doc 03), nunca de ese TS.

---

## 3. Veredicto final

✅ **Procede.** El proyecto es viable y el `moat` (motor JIT + datos intradía + universo de gaps)
es exactamente lo que da poder de cobro. Restricciones que reescriben la API ingenua de Gemini
("envía formulario → recibe todo el JSON"):

1. **Aislamiento fachada** (IP) — no negociable.
2. **Payloads pesados no por defecto** (downsample/paginar/`include`/intradía perezoso) — por ser
   cobrable y con clientes remotos, no por el backend (ver §1.1-bis).
3. **Cap de tamaño por request** — para acotar coste/latencia.

> **Cambio tras decisión de Jesús (MCP solo build-time):** la API MVP es **síncrona con cap**
> (como el `/backtest` actual), NO jobs async. Async queda como vía de escalado v2 sin romper
> contrato. Esto **simplifica el MVP** (menos infra: sin cola/worker obligatorios).

Con eso, el resto del plan (docs 02–06) es ejecutable por un loop de desarrollo.
