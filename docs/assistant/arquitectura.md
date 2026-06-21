# Arquitectura del Asistente Edgie

Estado: **implementado** (fases 0-3 del [plan maestro](../plan_asistente_edgie.md)).

## Flujo completo de un turno

```
Usuario (texto o voz es-ES)
   │
   ▼
ChatBot.tsx ── construye system prompt:
   │            persona + ruta actual + snapshot de contextos (AssistantBus)
   │            + base de conocimiento del ticker activo
   │
   ▼
POST /api/assistant/chat  (SSE, tools = assistantBus.getToolsManifest())
   │
   ▼   backend/app/routers/assistant.py (AI Gateway)
DeepSeek (function calling nativo) ── la API key vive en el SERVIDOR
   │
   ▼
ChatBot acumula deltas (texto en streaming + tool_calls)
   │
   ├─ sin tool_calls → respuesta final (+ TTS opcional)
   │
   └─ con tool_calls → por cada una:
        ├─ confirm='auto'   → assistantBus.execute() (valida JSON Schema → handler)
        └─ confirm/danger   → tarjeta de confirmación en el chat; el bucle se
                              pausa hasta Confirmar/Cancelar
      resultados → mensajes role:'tool' → nueva llamada al modelo
      (máx. 5 iteraciones por turno)
```

## Piezas

### Backend: AI Gateway (`backend/app/routers/assistant.py`)
- `POST /api/assistant/chat` — proxy al proveedor LLM. `stream=true` reenvía el SSE tal cual (formato OpenAI); `stream=false` devuelve el JSON completo.
- La key se resuelve: `DEEPSEEK_API_KEY` del servidor → si no existe, header `X-Assistant-Key` del cliente (**fallback transicional**, eliminar cuando todos los entornos tengan key de servidor).
- `GET /api/assistant/health` — indica si hay key de servidor configurada.
- Telemetría: log `[ASSISTANT] page=... tokens=...` por petición. Punto de enganche para los límites por tier (Entitlements).
- El informe automático de Ticker Analysis (`triggerAiAnalysis`) también pasa por aquí (`stream=false`, `page=/ticker-analysis/ai-report`).

### Frontend: AssistantBus (`frontend/src/lib/assistant/`)
| Fichero | Qué hace |
|---|---|
| `bus.ts` | Singleton: registro de acciones y contextos, manifest de tools, snapshot de contexto, `execute()` con validación y espera de montaje (4 s) para flujos navega-y-actúa. |
| `hooks.ts` | `useAssistantAction(def)` y `useAssistantContext(key, getter)` — registran mientras el componente está montado; el handler/getter siempre ve estado fresco (refs). |
| `validate.ts` | Validador JSON Schema ligero (tipos, enums, required, rangos, patrones). Sin dependencias; sustituible por zod/ajv. |
| `schemas.ts` | **Fuente de verdad** de los parámetros de cada tool, con descripciones en español (unidades, rangos, semántica). Los enums salen de `types/strategy.ts`. |
| `client.ts` | Cliente del gateway: `assistantChatStream` (SSE + acumulación de tool_calls) y `assistantChatOnce`. |

### Niveles de confirmación
- `auto` — se ejecuta directamente (rellenar formularios, navegar). El usuario lo ve en pantalla y puede corregir a mano.
- `confirm` — tarjeta con preview de argumentos (lanzar backtest, guardar dataset, test de estrategia).
- `danger` — tarjeta roja (borrados en Trunk).

El resultado de cada acción (ok/error con detalle) vuelve al LLM como `tool result`: si la validación falla o un nombre no resuelve, el modelo se autocorrige o pregunta (self-repair).

### Voz
- **STT**: Web Speech API (`SpeechRecognition`, `lang=es-ES`), botón de micro en el input; oculto si el navegador no lo soporta.
- **TTS**: `speechSynthesis` (es-ES), toggle en el header del chat; el markdown se limpia antes de leer.

## Garantías de diseño
1. **El bot nunca amplía permisos**: cada handler ejecuta las mismas llamadas/setters que la UI manual.
2. **Nada toca el estado sin validar**: `bus.execute` valida contra el schema antes del handler.
3. **El manifest es dinámico**: el LLM solo ve las acciones de los componentes montados (+ las globales como `app.navigate`).
4. **Compatibilidad**: los `CustomEvent`s históricos (`fill-backtest-form`, etc.) se mantienen — varios handlers los despachan internamente — y el parser legacy de bloques `[backtest-action]` sigue activo como fallback.

## Variables de entorno (backend)
| Variable | Default | Descripción |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | Key del proveedor. **Configurarla en todos los entornos.** |
| `ASSISTANT_PROVIDER_BASE` | `https://api.deepseek.com` | Base URL del proveedor (abstracción de proveedor). |
| `ASSISTANT_MODEL` | `deepseek-chat` | Modelo por defecto. |
