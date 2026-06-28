# 08 — Cómo está configurado Edgie y cómo modificarlo (Guía para Product Manager)

> **Para quién es esto:** este documento da visibilidad al Product Manager (Jaume)
> sobre qué es Edgie, dónde "vive" su comportamiento, qué se puede ajustar sin
> tocar arquitectura y qué requiere a un desarrollador. No hace falta saber
> programar para entenderlo; los enlaces a ficheros son para el dev que ejecute
> los cambios.

---

## 1. Qué es Edgie (en una frase)

Edgie es el **asistente de IA** de Edgecute. Hace dos cosas:

1. **Chatea** con el trader (texto y voz) y responde sobre el ticker cargado.
2. **Genera el reporte de "Dilución & Runner"** dentro de la página de Ticker
   Analysis (las tarjetas de riesgo + el informe en español).

Por debajo, Edgie **no es un modelo propio**: envía las preguntas a un proveedor
LLM externo (**DeepSeek**) a través de nuestro backend, que guarda la clave en
servidor para que nunca viaje al navegador.

---

## 2. Las dos "personalidades" de Edgie

Hoy conviven dos implementaciones. Es importante para el PM saber cuál está viva:

| | **Edgie Chat (en vivo)** | **Edgie Agéntico (POST-MVP)** |
|---|---|---|
| Estado | ✅ **Activo** | ⏸️ Construido pero **no encendido** |
| Qué hace | Responde preguntas del ticker cargado | Además **opera la app** (rellena backtests, navega, analiza cualquier ticker) |
| Fichero | [ChatBot.tsx](../../frontend/src/components/ChatBot.tsx) | [ChatBotAgentic.tsx](../../frontend/src/components/ChatBotAgentic.tsx) |
| Endpoint backend | `/api/edgie/chat` | `/api/assistant/chat` |
| Herramientas (tools) | No | Sí (vía "AssistantBus") |

> **Decisión de producto pendiente:** encender Edgie Agéntico. Cuando se active
> (es un cambio pequeño de un dev: montar `ChatBotAgentic` en el layout global en
> lugar del `ChatBot` simple), se desbloquean las capacidades agénticas, incluida
> la de analizar cualquier ticker desde cualquier página (ver §6).

---

## 3. Dónde está "el cerebro" de Edgie (los prompts)

El comportamiento de Edgie se controla con **prompts** (instrucciones en texto).
Hay tres prompts y cada uno gobierna algo distinto:

| Prompt | Qué controla | Dónde está |
|---|---|---|
| **Persona del chat** | Tono, brevedad, idioma del chat en vivo | [ChatBot.tsx:237](../../frontend/src/components/ChatBot.tsx) |
| **Reporte de Dilución** | Las reglas de dilución, el formato del informe y el JSON de métricas | [TickerAnalysis.tsx](../../frontend/src/components/TickerAnalysis.tsx), variable `systemPrompt` (buscar `const systemPrompt =`) |
| **Persona agéntica** | Cómo opera la app (POST-MVP) | [ChatBotAgentic.tsx](../../frontend/src/components/ChatBotAgentic.tsx) |

**El más importante para este módulo es el segundo.** Ahí están escritas, en
lenguaje natural, todas las reglas que el PRD pidió: bancos colocadores tóxicos,
ATM activo, convertible notes, warrants, Baby Shelf Rule, cumplimiento Nasdaq, y
la prohibición de interpretar velas. Cambiar una regla = editar ese texto.

---

## 4. Cómo fluye un reporte de dilución (paso a paso)

```
Trader pulsa "Re-procesar datos" en Ticker Analysis
        │
        ▼
Frontend arma el prompt (datos del ticker + reglas) y llama a:
   POST /api/assistant/dilution-report   (con el símbolo del ticker)
        │
        ▼
Backend (assistant.py):
   1. Busca en la BD qué bancos dilusores ya conocemos → los mete en el prompt
   2. Llama a DeepSeek
   3. Lee la respuesta, extrae los bancos nuevos detectados y los GUARDA en BD
        │
        ▼
Frontend pinta: tarjetas de riesgo + tabla de Ownership + Warrants + informe
```

La clave nueva (v2.0) es el paso 1 y 3: Edgie tiene **memoria**. Cada análisis
alimenta una base de datos de bancos dilusores; la próxima vez que ese banco
aparezca, el riesgo sube automáticamente.

---

## 5. El "JSON de métricas" (`<edgie_metrics>`)

Edgie devuelve, además del informe en texto, un bloque JSON oculto que alimenta
las tarjetas y tablas de la UI. Si el PM quiere **añadir un dato nuevo a la
pantalla** (ej. "quiero ver el número de warrants"), el proceso es:

1. Añadir la clave al JSON en el `systemPrompt` (fichero del §3, fila 2).
2. Pedir al dev que pinte esa clave en la UI.

Claves actuales: `dilution_rating`, `dilution_score`, `cash_runway_months`,
`float_percentage`, `runner_assessment`, `shelf_capacity_usd`, `pending_s1`,
`active_atm_usd`, `hired_banks`, `ownership_list`, `warrants_triggers`,
`nasdaq_compliance`. (Detalle completo en [03_CONTRATO_DATOS.md](03_CONTRATO_DATOS.md).)

---

## 6. La herramienta global "analiza cualquier ticker"

El PRD pidió que el trader pudiera decir *"Edgie, analiza MULN"* desde cualquier
página. Eso ya está **implementado** como una herramienta (`ticker.get_analysis`)
dentro de Edgie Agéntico ([ChatBotAgentic.tsx](../../frontend/src/components/ChatBotAgentic.tsx)).

**Estado:** lista y probada, pero **se activará cuando se encienda Edgie
Agéntico** (§2). El Edgie Chat actual no ejecuta herramientas, por eso vive en el
agéntico, que es su sitio natural. No requiere trabajo extra de este módulo: es
la misma decisión de "encender lo agéntico".

---

## 7. Panel de mandos: qué puede ajustar el PM

| Quiero cambiar… | Dónde | Riesgo | ¿Necesita dev? |
|---|---|---|---|
| Una regla de dilución (ej. umbral Baby Shelf) | `systemPrompt` en TickerAnalysis.tsx | Bajo (es texto) | Sí, para editar y desplegar |
| El tono/brevedad del chat | ChatBot.tsx:237 | Bajo | Sí |
| Que el informe sea más corto/largo | `systemPrompt` (regla 4 de formato) | Bajo | Sí |
| Añadir un dato a las tarjetas | JSON `<edgie_metrics>` + UI | Medio | Sí |
| Resaltar dilución de acciones a otro % (hoy 15%) | [TickerAnalysis.tsx](../../frontend/src/components/TickerAnalysis.tsx), componente `BalanceSheetTable` | Bajo | Sí |
| Cambiar el modelo de IA (ej. otro DeepSeek) | Variable de entorno `ASSISTANT_MODEL` | Medio | Sí (ops) |
| Encender Edgie Agéntico (operar la app + tool global) | Montar `ChatBotAgentic` en el layout | Medio-alto | Sí |
| Restringir el reporte a planes de pago (gating) | Middleware de Clerk | Producto | Sí (decisión de Jesús) |

---

## 8. Cosas que conviene que el PM sepa

- **Clave de IA:** Edgie no funciona sin la variable `DEEPSEEK_API_KEY` en el
  servidor. Si falta, la UI muestra un aviso claro ("Clave API de DeepSeek
  faltante") en lugar de romperse.
- **La memoria de bancos es local y acumulativa:** se guarda en DuckDB
  (`dilution_banks_registry`). No se sube a git ni se borra entre análisis. Cuanto
  más se use, mejor detecta bancos reincidentes. Se normaliza el nombre para no
  duplicar ("H.C. Wainwright & Co. LLC" y "HC Wainwright" cuentan como el mismo).
- **Edgie no adivina precios por velas:** por diseño tiene prohibido interpretar
  patrones de velas como señal de dilución. Solo usa niveles "duros" (precios de
  warrants, umbrales de Nasdaq, Baby Shelf). Esto es intencional y reduce ruido.
- **Si un dato no existe, Edgie pone "—" en vez de inventarlo.** Preferimos un
  hueco honesto a un número falso.
- **Gating comercial:** quién puede ver el reporte avanzado (gratis vs. de pago)
  es una decisión de negocio que queda en manos de Jesús; técnicamente está todo
  listo para activarlo cuando se decida, sin rehacer nada.

---

## 9. Qué se entregó en esta iteración (Dilución & Runner v2.0)

- Pestaña **Balance** (histórico trimestral de caja/deuda/capital/patrimonio/
  acciones) junto a los SEC Filings, con dilución severa resaltada en rojo.
- **Tarjetas de riesgo** más compactas.
- **Tabla de Ownership** (personas primero, luego instituciones) y sección de
  **Warrants** en el informe.
- **Reglas avanzadas** de dilución y cumplimiento Nasdaq en el cerebro de Edgie.
- **Memoria de bancos dilusores** en base de datos (sube el riesgo de reincidentes).
- **Arreglo** del mensaje "ticker cargado" que se repetía 6+ veces (ahora una vez).
- **Herramienta global** de análisis de ticker, lista para cuando se encienda
  Edgie Agéntico.

Plan técnico completo y verificación: ver [06_PROMPT_MAESTRO_EJECUCION.md](06_PROMPT_MAESTRO_EJECUCION.md).
