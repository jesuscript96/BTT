# Plan de rendimiento y estabilidad del Backtester

## 1. Por qué ves 502 y "CORS" en producción

- **502 Bad Gateway** lo devuelve la plataforma (p. ej. Render), no FastAPI. Suele indicar:
  - **Timeout**: la petición supera el límite (p. ej. 30 s en plan gratis).
  - **Cold start**: el servicio estaba dormido y no respondió a tiempo.
  - **Crash**: el proceso murió (OOM, excepción no capturada).
- Cuando la respuesta es **502**, el proxy no suele añadir cabeceras CORS, por eso el navegador muestra *"blocked by CORS"* aunque el origen esté permitido en el backend. Es un efecto del 502, no un fallo de configuración CORS.

**Qué se ha hecho en el backend:**
- Middleware que añade CORS a **todas** las respuestas que sí genera la app (4xx/5xx), para que cuando falle la API el front reciba un error con CORS.
- Startup más resiliente: si la base de datos no está disponible al arrancar, la app sigue levantando; el primer uso de la API puede devolver 500/503 con CORS.

---

## 2. Objetivos de rendimiento

- Backtest **más rápido** y **estable** (menos timeouts y menos picos de memoria).
- Reducir probabilidad de 502 en hosting con límite de tiempo (p. ej. Render).

---

## 3. Plan por fases

### Fase A – Quick wins (implementados)

| Acción | Descripción | Cómo |
|--------|-------------|------|
| **Límite de universo** | `BACKTEST_UNIVERSE_LIMIT` (default **5000**). Sube para samples más grandes. | Variable de entorno. |
| **Audit opcional** | Validación VectorBT desactivada si `SKIP_BACKTEST_AUDIT=1`. | En Render: env `SKIP_BACKTEST_AUDIT=1` para ahorrar ~1–5 s. |
| **Monte Carlo más ligero** | `MONTE_CARLO_SIMULATIONS` (default **500**, máx 1000). | Variable de entorno. |
| **Tope de filas opcional** | `BACKTEST_MAX_ROWS`: si > 0, rechaza requests con más filas; **0 = sin tope** (usa chunked run). | Por defecto 0: no se limitan datos. |
| **Backtest por chunks** | Si el dataset tiene más de `CHUNK_BACKTEST_ROWS` (default **250000**) filas, se ejecuta por mes y se fusionan resultados. Memoria acotada sin recortar datos. | Automático. |
| **Health sin DB** | `GET /health` no usa la base de datos. | Útil para keep-alive (cron cada 5–10 min). |

### Fase B – Estabilidad en producción

| Acción | Descripción |
|--------|-------------|
| **Keep-alive** | Cron externo (o Render cron job) que llame a `GET /health` cada 5–10 min para evitar cold start. |
| **Timeout mayor en Render** | En plan de pago, subir el request timeout (p. ej. 60–120 s) para el endpoint de backtest. |
| **Límite de filas en backtest** | Cap máximo de filas de mercado (p. ej. 500k) y devolver 400 claro si se supera. |
| **Logs** | Log de duración por fase (fetch, engine, métricas, guardado) para detectar cuellos de botella. |

### Fase C – Escalabilidad (medio plazo)

| Acción | Descripción |
|--------|-------------|
| **Backtest asíncrono** | `POST /backtest/run` devuelve `202 Accepted` y un `run_id`; el cliente hace polling a `GET /backtest/results/{run_id}` hasta que termine. Así el request no supera el timeout del proxy. |
| **Worker en cola** | Cola (Redis/RQ, Celery, o cola de Render) para ejecutar el backtest en background y persistir resultado en DB. |
| **Chunked fetch** | En lugar de traer todo el intraday de una vez, leer por rangos de fechas o por tickers en chunks y alimentar al motor por partes (requiere cambios en el engine). |
| **Cache de universo** | Cachear el resultado de “universe” (screener) por filtros durante X minutos para repetir backtests con el mismo dataset sin re-ejecutar el screener. |

### Fase D – Optimización del motor

| Acción | Descripción |
|--------|-------------|
| **Numba cache** | Asegurar que los JIT de Numba usen `cache=True` (ya en uso) y que el volumen de datos no fuerce recompilaciones. |
| **Tipos numpy** | Reducir copias y asegurar tipos consistentes (float64, int64) en los arrays que se pasan al JIT. |
| **Downsample opcional** | Opción de ejecutar el backtest en velas de 5m en lugar de 1m para datasets muy grandes (menos barras, menos tiempo). |

---

## 4. Límite 4MB MotherDuck (RESOURCE_EXHAUSTED / SETUP_PLAN_FRAGMENTS)

Si el backtest falla con *"Received message larger than max (4.5MB vs 4MB)"*, el **plan** de la query que se envía a MotherDuck es demasiado grande. Para evitarlo, en el backtest se usa una ruta específica:

- **Universo sin JOINs** (`backtest_no_joins=True`): la query del universo es solo `SELECT ... FROM daily_metrics WHERE (filtros de métricas y fechas) ORDER BY ... LIMIT ?`. No se hace JOIN en esa query para que el plan quede bajo 4MB. **Mercados y splits se recuperan en Python**: tras cargar el universo se ejecutan dos queries ligeras (`SELECT ticker FROM massive.tickers WHERE type IN ('CS','ADRC','OS')` y `SELECT ticker, execution_date FROM massive.splits WHERE ...`) y se filtra el universo en memoria. Así se mantiene el mismo comportamiento que antes (solo CS/ADRC/OS y sin fechas de splits).
- **Universo e intraday por meses**: el universo se pide por mes y el intraday también, para no mandar un solo RPC con todo el rango.

Si aun así falla, alternativas son: contactar con MotherDuck para subir el límite gRPC, o ejecutar el backtest contra una réplica local de los datos (DuckDB local o otro almacén).

---

## 5. Usar samples grandes sin limitar datos

- **BACKTEST_UNIVERSE_LIMIT**: default 5000 (ticker/día en el screener). Puedes subirlo (p. ej. 10000) para universos más grandes.
- **BACKTEST_MAX_ROWS**: default **0** = sin tope. Solo si quieres rechazar requests enormes, pon un valor (p. ej. 5000000).
- **Chunked run**: si el dataset de mercado tiene más de **250000** filas (configurable con `CHUNK_BACKTEST_ROWS`), el backtest se ejecuta **por mes**: cada mes corre el motor con el capital final del mes anterior, y al final se fusionan trades y curva de equity. Así la memoria por request queda acotada y puedes usar datasets muy grandes sin tope artificial.

---

## 6. Límites recomendados en producción (opcionales)

- **Universe (screener):** 1500–2000 filas (ticker/día) para el backtest.
- **Filas de intraday:** tope recomendado 400k–500k; por encima, considerar backtest asíncrono o chunking.
- **Timeout request (Render):** ≥ 60 s si el backtest es pesado; si no, usar flujo 202 + polling.

---

## 7. Cómo validar

- Medir tiempo de `POST /api/backtest/run` por fases (fetch, engine, métricas, guardado) con logs.
- Reproducir en local con dataset grande y comprobar uso de memoria.
- En producción, revisar logs de Render al recibir 502 (timeout vs crash) y ajustar límites y keep-alive.
