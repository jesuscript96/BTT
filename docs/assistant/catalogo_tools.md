# Catálogo de Tools del Asistente

Cada tool se registra con `useAssistantAction` en el componente que posee el estado, por lo que **solo está disponible cuando ese componente está montado**. Los schemas completos (con descripciones por campo) viven en `frontend/src/lib/assistant/schemas.ts`.

> **Nombres "de cable":** los proveedores LLM solo admiten `[a-zA-Z0-9_-]` en nombres de tools, así que el bus traduce el nombre canónico con puntos al manifest sustituyéndolos por guiones bajos (`backtest.fill_form` → `backtest_fill_form`) y resuelve las llamadas en ambos formatos. En código y docs se usa el canónico.

## Globales (siempre disponibles)

| Tool | Nivel | Registrada en | Descripción |
|---|---|---|---|
| `app.navigate` | auto | `ChatBot.tsx` | Navega a `/`, `/backtester`, `/database` o `/tutorials`. Paso previo para usar acciones de otra página (el bus espera hasta 4 s a que se registren). |

## Ticker Analysis (`/`)

| Tool | Nivel | Registrada en | Descripción |
|---|---|---|---|
| `ticker.load` | auto | `TickerAnalysis.tsx` | Carga un ticker; al resolver, su base de conocimiento entra en la conversación vía evento `ticker-loaded`. |

Contexto publicado: `ticker.page` (ticker activo, loading, estado del informe IA con métricas de dilución).

## Backtester (`/backtester`)

| Tool | Nivel | Registrada en | Descripción |
|---|---|---|---|
| `backtester.set_mode` | auto | `backtester/page.tsx` | Cambia el panel: `config` / `builder` / `dataset`. |
| `backtest.fill_form` | auto | `BacktestPanel.tsx` | Rellena el formulario (parcial o completo) y selecciona dataset/estrategia por id o nombre. Devuelve error con candidatos si el nombre no resuelve de forma única. |
| `backtest.run` | auto | `BacktestPanel.tsx` | Ejecuta con el dataset **y la estrategia GUARDADA** seleccionados. Valida que ambos existan antes (si no, error accionable) y espera ~4s un fallo rápido del backend para reportarlo en vez de un falso "lanzado". **No** ejecuta el borrador del builder. |
| `strategy.fill` | auto | `InlineStrategyBuilder.tsx` | Construye una estrategia NUEVA en el Strategy Builder: nombre, bias, applyDay, precondiciones, entry/exit logic, riesgo. |
| `strategy.test` | auto | `InlineStrategyBuilder.tsx` | Ejecuta el **borrador actual** del builder directamente (sin guardarlo). Es el camino para "crear y probar" una estrategia nueva. Valida lógica y reporta fallos del backend. |
| `dataset.fill` | auto | `InlineDatasetBuilder.tsx` | Rellena el Dataset Builder: nombre, fechas, filtros por sección (`gap_day`, `gap_plus_1_day`, `gap_plus_2_day`). |
| `dataset.save` | **confirm** | `InlineDatasetBuilder.tsx` | Guarda el dataset actual (creación en segundo plano). |

Contextos publicados: `backtest.form` (todos los campos actuales), `backtest.catalog` (datasets y estrategias con id+nombre), `backtester.page` (modo, running, métricas agregadas del último resultado), `strategy.draft` (resumen legible del borrador), `dataset.draft`.

## Trunk (`/database`)

| Tool | Nivel | Registrada en | Descripción |
|---|---|---|---|
| `trunk.open_strategy_in_backtester` | auto | `database/page.tsx` | Abre el Backtester con una estrategia guardada preseleccionada. |
| `trunk.delete` | **danger** | `database/page.tsx` | Borra una estrategia o dataset guardado. Irreversible; siempre pide confirmación con tarjeta roja. |

Contexto publicado: `trunk.page` (estrategias, datasets y backtests guardados con ids, máx. 40 por lista).

## Dos flujos de backtest (importante)

| Intención del usuario | Secuencia correcta |
|---|---|
| Ejecutar una estrategia **ya guardada** | `backtest_fill_form` (selecciona datasetName/strategyName + parámetros) → `backtest_run` |
| **Crear y probar** una estrategia nueva | `backtester_set_mode("builder")` → `strategy_fill` (construye el borrador) → `strategy_test` (lo ejecuta directamente, sin guardar) |

`backtest_run` ejecuta la estrategia **guardada seleccionada**, no el borrador del builder. Confundir los dos flujos es lo que producía el error "Strategy not found": construir un borrador y luego llamar a `backtest_run` ejecutaba la estrategia seleccionada anterior (a menudo inválida). Las descripciones de las tools y el system prompt guían al modelo al flujo correcto, y `backtest_run` valida la selección antes de ejecutar.

## Convenciones de resultado

Todo handler devuelve `{ ok, result?, error? }`. El `error` debe ser **accionable para el LLM**: incluye los candidatos disponibles, el campo inválido o el siguiente paso sugerido. Ejemplos reales:

```json
{ "ok": false, "error": "Ningún dataset coincide con \"small caps\". Disponibles: \"Small Caps 2024\" (id=q_abc), \"Small Caps Q1\" (id=q_def)" }
{ "ok": false, "error": "Parámetros inválidos — $.riskType: valor \"KELLY\" no permitido; opciones: FIXED | PERCENT | FIXED_RATIO" }
```
