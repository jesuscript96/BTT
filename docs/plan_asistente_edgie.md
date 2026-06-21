# Plan Maestro: Asistente Edgie Omnipresente (Voz + Texto)

Este documento define la arquitectura y el plan por fases para convertir a **Edgie** (el chatbot actual) en un asistente capaz de operar **toda la plataforma Edgecute** mediante texto o voz, **sin alterar la UX existente**: el usuario sigue pudiendo hacer todo manualmente, pero el bot puede hacer lo mismo por él.

El principio rector es el mismo que en la [guía de tiers](guia_requisitos_tiers_usuarios.md): **nada hardcodeado y todo declarativo**. El asistente no debe "conocer" las páginas; cada página debe **declarar** qué sabe hacer y qué contexto tiene, y el asistente lo descubre dinámicamente.

---

## 1. Estado Actual (auditoría — rama `nextux-jesus`)

### 1.1 Lo que ya existe y funciona

| Pieza | Ubicación | Descripción |
|---|---|---|
| ChatBot flotante global | `frontend/src/components/ChatBot.tsx` (montado en `app/layout.tsx`) | Burbuja flotante en todas las páginas. Llama a DeepSeek directamente desde el navegador. |
| Contexto de ticker | `TickerAnalysis.tsx` → evento `ticker-loaded` + `window.__lastLoadedTicker` | Al cargar un ticker, se publica perfil, métricas, gap stats, SEC filings, noticias y XBRL facts para el bot. |
| Acciones sobre el backtester | Bloques ` ```json [backtest-action] ` parseados con regex en `ChatBot.tsx` | El LLM emite un JSON al final de su respuesta; el front lo intercepta y dispara `CustomEvent`s. |
| Listeners de acciones | `BacktestPanel.tsx` (`fill-backtest-form`, `run-backtest-action`), `InlineStrategyBuilder.tsx` (`fill-strategy-builder`), `InlineDatasetBuilder.tsx` (`fill-dataset-builder`), `backtester/page.tsx` (`change-backtester-mode`) | Cada componente aplica el detail del evento a su estado local. Matching de dataset/estrategia por substring de nombre. |
| Informe IA automático | `TickerAnalysis.tsx` → `triggerAiAnalysis()` | Informe de riesgo de dilución con bloque estructurado `<edgie_metrics>` (rating, runway, squeeze, etc.). |
| Datos SEC para la IA | `backend/app/routers/ticker_analysis.py` → `GET /{ticker}/sec-company-facts` | Endpoint que agrega XBRL facts de EDGAR como base de conocimiento. |
| Adjuntos | `ChatBot.tsx` | El usuario puede adjuntar `.txt/.csv/.json/...` que se inyectan en el prompt. |

### 1.2 Limitaciones del enfoque actual (por qué no escala)

1. **API key en el cliente.** La clave de DeepSeek vive en `localStorage` y la llamada sale del navegador. Sin control de coste, sin tiers, y cualquier usuario puede extraerla si se sirve via `NEXT_PUBLIC_*`. Es el bloqueo nº 1 para producción.
2. **JSON-en-texto + regex es frágil.** DeepSeek soporta *function calling* nativo; el bloque ```` ```json [backtest-action] ```` depende de que el modelo formatee bien y de que la regex acierte. Un fallo silencioso = el usuario cree que el bot "no hace nada".
3. **Eventos fire-and-forget.** Si el usuario está en `/` y pide "ejecuta un backtest", los `CustomEvent`s se disparan pero **no hay nadie montado escuchando** en esa página. No hay ACK, ni cola, ni error visible.
4. **El bot no sabe dónde está el usuario.** El system prompt es estático: no sabe qué página está abierta, qué formulario está a medias, ni qué resultados hay en pantalla.
5. **Sin validación.** Lo que el LLM emite se aplica directamente al estado de React. Un enum inventado (`riskType: "AGGRESSIVE"`) entra sin error.
6. **Matching por substring.** `datasetName: "small caps"` selecciona el primer dataset cuyo nombre contenga eso. Sin desambiguación.
7. **Sin voz.** Todo es texto.
8. **Dos integraciones LLM duplicadas.** `ChatBot.tsx` y `triggerAiAnalysis()` repiten el patrón fetch-DeepSeek-parsea-bloque con prompts gigantes inline.

---

## 2. Arquitectura Objetivo

```
┌─────────────────────────── FRONTEND ───────────────────────────┐
│                                                                │
│  Páginas/Componentes                    ChatBot (Edgie)        │
│  ┌──────────────────┐                  ┌──────────────────┐    │
│  │ registran        │   AssistantBus   │ texto + voz      │    │
│  │  · acciones ─────┼─────────────────▶│ (STT/TTS)        │    │
│  │  · contexto ─────┼─────────────────▶│                  │    │
│  └──────────────────┘                  └────────┬─────────┘    │
│         ▲                                       │ SSE          │
│         │ ejecuta acción validada (zod)         ▼              │
│         └────────────────────────────── /api/assistant/chat    │
└────────────────────────────────────────────────┬───────────────┘
                                                 │
┌─────────────────────────── BACKEND ────────────▼───────────────┐
│  routers/assistant.py  (AI Gateway)                            │
│   · guarda la API key del proveedor (server-side)              │
│   · function calling nativo (tools del manifest recibido)      │
│   · streaming SSE de tokens y tool_calls                       │
│   · límites por tier (enlaza con sistema de Entitlements)      │
│   · telemetría de coste/uso                                    │
└────────────────────────────────────────────────────────────────┘
```

### 2.1 AI Gateway en el backend (`backend/app/routers/assistant.py`)

Sustituye las llamadas directas navegador→DeepSeek:

- `POST /assistant/chat` — recibe `{ messages, tools, context }`, reenvía al proveedor LLM con la key del servidor y devuelve **SSE** (tokens + `tool_call` events).
- El proveedor queda abstraído (DeepSeek hoy; intercambiable mañana). El modelo y temperatura se configuran en servidor.
- Aplica **Entitlements**: `feature: assistant_chat`, `limits: assistant_messages_24h`, `assistant_voice_minutes`, según la guía de tiers.
- Registra uso (tokens in/out, coste estimado, usuario, página origen) para analítica.
- `triggerAiAnalysis` de Ticker Analysis migra aquí también (`POST /assistant/ticker-report`), eliminando la segunda integración duplicada.

### 2.2 AssistantBus: registro central de acciones y contexto (frontend)

Nuevo módulo `frontend/src/lib/assistant/` que reemplaza los `CustomEvent`s sueltos:

```ts
// Cada componente, al montarse, registra sus capacidades:
useAssistantAction({
  name: "backtest.fill_form",
  description: "Rellena el formulario de configuración del backtest",
  schema: BacktestParamsSchema,        // zod — la fuente de verdad
  handler: (params) => { ...aplica al estado...; return { ok: true, applied: params }; }
});

// Y publica su contexto:
useAssistantContext("backtest.form", () => ({
  selectedDataset, selectedStrategy, initCash, riskR, startDate, endDate, ...
}));
```

Propiedades clave:

1. **Manifest dinámico.** En cada turno de conversación, el ChatBot pregunta al bus "¿qué acciones hay registradas ahora mismo?" y las convierte en `tools` de function calling. El LLM solo ve lo que de verdad puede ejecutar. Las acciones de páginas no montadas se exponen como variante `navigate-first` (ver 2.4).
2. **ACK y resultado.** El handler devuelve resultado (o error de validación), que se reenvía al LLM como `tool result`. El bot puede autocorregirse ("el dataset 'small caps' no existe; hay 3 parecidos: …").
3. **Validación zod previa.** Nada toca el estado de React sin pasar el schema. Los enums de `types/strategy.ts` (`IndicatorType` ~40 valores, `Comparator`, `Timeframe`, `RiskType`, `TakeProfitMode`) se convierten en schemas zod compartidos (`frontend/src/lib/assistant/schemas/`) — una sola fuente de verdad para el formulario manual Y para el bot.
4. **Retrocompatibilidad.** Durante la migración, el bus puede seguir despachando los `CustomEvent`s actuales internamente; los listeners existentes no se tocan en Fase 1.

### 2.3 Contexto situacional ("el bot sabe dónde estás")

En cada petición al gateway se adjunta automáticamente:

- **Ruta actual** y modo (ej. `/backtester`, mode=`builder`).
- **Snapshot de contextos publicados**: ticker cargado, formulario a medias, resultados visibles (métricas del backtest, trades en tabla), filtros del Trunk…
- **Catálogo de entidades**: nombres+IDs de datasets y estrategias guardadas (resuelve el problema del matching por substring: el LLM elige el ID exacto o pregunta).

### 2.4 Navegación como herramienta

Acción global `app.navigate({ to })` registrada en el layout. Si el usuario pide "ejecuta un backtest con la estrategia X" desde Ticker Analysis, el plan del LLM es: `app.navigate(/backtester)` → esperar mount (el bus notifica cuándo las acciones de esa página quedan registradas) → `backtest.fill_form(...)` → `backtest.run()`. El patrón actual de `sessionStorage backtester_prefill` ya existe como precedente; el bus lo generaliza con una **cola de acciones pendientes de mount**.

### 2.5 Confirmación humana (acciones sensibles)

Tres niveles declarados en el registro de cada acción:

| Nivel | Comportamiento | Ejemplos |
|---|---|---|
| `auto` | Se ejecuta directamente | rellenar formulario, navegar, filtrar |
| `confirm` | Tarjeta en el chat con preview de parámetros + botón Confirmar/Cancelar | `backtest.run`, `strategy.save`, `dataset.create` |
| `danger` | Confirmación con texto explícito de lo que se borra | `strategy.delete`, `dataset.delete` |

El formulario **se rellena visiblemente** antes de ejecutar: el usuario ve los campos cambiar (UX actual intacta) y la confirmación es sobre lo que ya está en pantalla. Eso convierte cada acción del bot en algo auditable y corregible a mano.

### 2.6 Voz

- **Fase voz-1 (coste cero):** Web Speech API. `SpeechRecognition` (es-ES) para dictado push-to-talk con botón de micro en el input del chat; `speechSynthesis` para leer respuestas (toggle). Cobertura: Chrome/Edge (mayoría de usuarios de plataformas de trading).
- **Fase voz-2 (calidad pro):** STT por streaming vía gateway (Whisper/Deepgram) para navegadores sin soporte y mejor precisión con jerga financiera ("VWAP", "gap del veinte por ciento"). Entitlement: `assistant_voice`.
- El dictado produce texto en el mismo input — la tubería texto/acciones es idéntica, la voz es solo otra forma de entrada.

---

## 3. Matriz de Cobertura: qué puede hacer Edgie en cada página

| Página | Contexto que publica | Acciones (tools) |
|---|---|---|
| **`/` Ticker Analysis** | ticker activo, métricas, gap stats, filings, noticias, informe Edgie | `ticker.load(ticker)`, `ticker.explain_metric(metric)`, `ticker.open_filing(id)`, `ticker.compare(other)` *(fase 3)* |
| **`/backtester` (config)** | formulario completo, dataset/estrategia seleccionados, catálogo de datasets/estrategias con IDs | `backtest.fill_form(params)`, `backtest.select_dataset(id)`, `backtest.select_strategy(id)`, `backtest.run()` ⚠️confirm |
| **`/backtester` (builder)** | borrador de estrategia actual | `strategy.fill(draft)`, `strategy.add_condition(...)`, `strategy.set_risk(...)`, `strategy.save()` ⚠️confirm |
| **`/backtester` (dataset)** | borrador de dataset, filtros activos | `dataset.fill(draft)`, `dataset.save()` ⚠️confirm |
| **`/backtester` (resultados) y `/backtester/[id]`** | métricas (PF, WR, DD, Sharpe), curva equity, trades visibles | `results.explain()`, `results.filter_trades(criteria)`, `results.save_backtest()` ⚠️confirm |
| **`/database` (Trunk)** | listas de estrategias/queries/backtests guardados | `trunk.search(query)`, `trunk.open(id)`, `trunk.rerun(id)`, `trunk.delete(id)` 🛑danger, `trunk.toggle_validation(id)` |
| **`/analysis/[ticker]/[date]`** | día intradía cargado | `day.explain()`, `day.navigate(offset)` |
| **Global (layout)** | ruta actual, usuario/tier | `app.navigate(to)`, `app.help(topic)` (responde con contenido de `/tutorials` y `docs/`) |

> Esta matriz ES el backlog: cada celda es una unidad de trabajo pequeña (registrar acción + schema + handler) una vez exista el bus.

---

## 4. El Caso Estrella: rellenar y ejecutar el backtest por voz/texto

Es el reto más complejo porque el espacio de parámetros es enorme (40+ indicadores × 9 comparadores × timeframes × sesiones × riesgo × preconditions por día de gap…). Estrategia para que el LLM acierte "a la perfección":

1. **Schemas exhaustivos con descripciones.** Cada campo del schema zod lleva `.describe()` en español con unidades, rangos y ejemplos ("`riskR`: riesgo por operación en USD si `riskType=FIXED`, en % si `PERCENT`"). El JSON Schema generado alimenta el function calling — el conocimiento del formulario vive en el schema, no en el prompt.
2. **Acciones granulares además de la global.** `backtest.fill_form` acepta parciales (como hoy), pero también existen `strategy.add_condition` atómicas: para peticiones complejas el LLM construye paso a paso con feedback de validación en cada paso, en lugar de emitir un mega-JSON de una vez.
3. **Self-repair loop.** Error de validación → vuelve al LLM como tool result → reintenta corregido. Máximo 2 reintentos; después pregunta al usuario.
4. **Desambiguación conversacional.** Referencias ambiguas a datasets/estrategias → el bot lista candidatos con IDs y pregunta.
5. **Verificación visible.** El formulario rellenado ES la confirmación. "He configurado: 50.000$ inicial, riesgo fijo 200$, comisiones 0,05%… ¿Lanzo el backtest?" — y los campos ya se ven en la UI.
6. **Suite de evaluación.** `docs/assistant/evals/` con ~50 frases reales esperadas ("ponme un backtest short para el día del gap con entrada al romper el low del premarket con stop en el high y target 2R, en el dataset de small caps de 2024") y el JSON exacto esperado. Se ejecutan contra el gateway en CI para detectar regresiones de prompt/modelo.

---

## 5. Seguridad, Tiers y Coste

- **La API key sale del navegador → servidor** (Fase 0, no negociable). El ajuste "API key" del chat se elimina; la opción `NEXT_PUBLIC_DEEPSEEK_API_KEY` se elimina.
- **Entitlements** (ver [guía de tiers](guia_requisitos_tiers_usuarios.md)): `assistant_chat` (feature), `assistant_messages_24h`, `assistant_voice` (feature), `assistant_voice_minutes_24h` (límites). El gateway los consulta por petición.
- **El bot hereda los permisos del usuario, nunca los amplía:** las tools ejecutan las mismas llamadas API que la UI, con la misma sesión. Si el tier no permite `run_backtest`, la tool devuelve el mismo error que el botón.
- **Presupuesto:** límite de tokens de contexto por turno (truncar XBRL facts/noticias con resumen), y caché del system prompt estable.

---

## 6. Plan por Fases

### Fase 0 — Hardening (prerequisito) — ✅ IMPLEMENTADA
- [x] `routers/assistant.py`: proxy `POST /api/assistant/chat` con SSE y key en servidor (fallback transicional a key de cliente vía header `X-Assistant-Key`).
- [x] Migrar `ChatBot.tsx` y `triggerAiAnalysis` al gateway.
- [x] Function calling nativo en lugar del bloque `[backtest-action]` + regex (el parser legacy sigue como fallback).

### Fase 1 — AssistantBus + caso estrella — ✅ IMPLEMENTADA
- [x] `lib/assistant/`: bus (registro de acciones/contexto, manifest, espera de mount 4s), hooks `useAssistantAction` / `useAssistantContext`.
- [x] Schemas JSON Schema de BacktestParams, Strategy y Dataset (validador ligero propio en `validate.ts`; los enums salen de `types/strategy.ts`; migrable a zod si crece).
- [x] Migrar los 5 eventos existentes al bus con validación + ACK (los `CustomEvent`s se mantienen por compatibilidad, despachados desde los handlers).
- [x] Contexto situacional (ruta + snapshots) en cada petición.
- [x] Confirmaciones `confirm`/`danger` como tarjetas en el chat.
- [x] Catálogo de datasets/estrategias con IDs en el contexto (`backtest.catalog`).

### Fase 2 — Cobertura total — ✅ IMPLEMENTADA (núcleo)
- [x] Strategy Builder: `strategy.fill` + `strategy.test`; Dataset Builder: `dataset.fill` + `dataset.save`.
- [ ] Acciones atómicas (`strategy.add_condition`, etc.) — pendiente; hoy el LLM construye el draft completo con feedback de validación.
- [x] Trunk: contexto con listas guardadas, `trunk.open_strategy_in_backtester`, `trunk.delete` con `danger`.
- [x] Resultados: contexto `backtester.page` con métricas agregadas del último run.
- [x] Navegación global (`app.navigate` con espera de montaje).
- [ ] `app.help` sobre tutoriales/docs — pendiente.

### Fase 3 — Voz y pulido — ✅ IMPLEMENTADA (núcleo)
- [x] Micro push-to-talk (Web Speech API es-ES) + TTS opcional (toggle en el header del chat).
- [x] Suite de evals conversacionales (`docs/assistant/evals/casos.json`) — ejecución manual; automatizar en CI pendiente.
- [x] Telemetría básica de uso en el gateway (log por petición con página y tokens).
- [ ] STT pro vía gateway con entitlement — pendiente.
- [ ] Límites por tier (Entitlements) en el gateway — pendiente de que exista el sistema de tiers.

---

## 7. Guía para Desarrolladores: "haz tu componente asistible"

Patrón obligatorio para cualquier feature nueva (se documentará con ejemplos completos en `docs/assistant/`):

1. **Define el schema zod** de los parámetros en `lib/assistant/schemas/` (con `.describe()` en español por campo).
2. **Registra la acción** con `useAssistantAction` en el componente que posee el estado. El handler aplica al estado y devuelve `{ ok, applied }` o lanza con mensaje útil.
3. **Publica el contexto** relevante con `useAssistantContext` (solo lo que cabría en ~1-2 KB; nada de datasets enteros).
4. **Declara el nivel de confirmación** (`auto`/`confirm`/`danger`).
5. **Añade 2-3 frases de eval** a la suite con el resultado esperado.

Regla de oro: si un humano puede hacerlo con la UI, debe existir una acción registrada equivalente — y **ninguna** acción debe poder hacer algo que la UI no permita.

### Estructura documental a crear

```
docs/assistant/
├── arquitectura.md          (este flujo en detalle + diagramas)
├── catalogo_tools.md        (toda tool: schema, ejemplos, nivel de confirmación)
├── contexto_por_pagina.md   (qué publica cada página y por qué)
├── prompts/                 (system prompts versionados, changelog)
├── evals/                   (frases → tool_calls esperados)
└── guia_dev_componente_asistible.md
```

---

## 8. Riesgos y Mitigaciones

| Riesgo | Mitigación |
|---|---|
| El LLM inventa parámetros/enums | Validación zod + self-repair loop + enums en el JSON Schema |
| Acción ejecutada en página equivocada / componente desmontado | Manifest dinámico + cola de mount + ACK obligatorio |
| Coste LLM descontrolado | Gateway con límites por tier, truncado de contexto, telemetría |
| Borrados accidentales por voz mal transcrita | Nivel `danger` siempre con confirmación textual explícita |
| Dependencia de DeepSeek | Proveedor abstraído en el gateway; el front solo habla con `/assistant/*` |
| Regresiones al cambiar prompts/modelo | Suite de evals en CI |
| Web Speech API no disponible (Firefox/Safari) | Botón de micro oculto si no hay soporte; fase voz-2 lo cubre vía gateway |
