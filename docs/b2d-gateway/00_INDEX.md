# Gateway B2D (Backtesting-to-Developer) — Documento de pre-producción

> **Qué es esto.** El plan completo y anclado en el código real para exponer el motor
> de backtesting de **Edgecute** como (1) una **API comercial** que recibe formularios y
> devuelve JSON sin filtrar la lógica/IP, y (2) un **servidor MCP** que permite a traders
> indie desarrollar sus backtests en local desde Cursor / Claude Code.
>
> **Estado:** PLAN. Ningún código de producción todavía. Este suite es el "cerebro" que un
> loop de ejecución posterior consumirá para construir todo sin alucinar.

> **Estado de las decisiones (importante):**
> - Lo que **Jesús ha dicho explícitamente**: MCP solo build-time; **API modulada por módulos**;
>   submodularización de componentes; **el gating/monetización se decide más tarde** (no es problema técnico).
> - Lo que son **defaults técnicos reversibles** (míos, no firmados por Jesús): API síncrona con cap,
>   Postgres mínimo, TS para el MCP, etc. → ver [`07`](07_DECISIONES_ABIERTAS.md) §B.
> - **NO hay política de monetización en este plan** (tiers/precios/quién-se-bloquea = decisión de
>   producto diferida). El MVP entrega solo el **mecanismo**: metering + hook de gating por módulo.
> - Preguntas realmente abiertas (de producto, sin resolver por mí): [`07`](07_DECISIONES_ABIERTAS.md) §A.

## Cómo se montó este plan (trazabilidad)

Todo lo que sigue está **anclado en el código actual** del repo (rama `api-jesus`), no en
suposiciones. Fuentes auditadas:

| Pieza real | Fichero | Qué aporta al plan |
|---|---|---|
| Contrato de entrada del backtest | `backend/app/services/backtest_orchestrator.py` (`BacktestRequest`) | Los campos del "formulario" de ejecución |
| Definición de estrategia (DSL) | `backend/app/schemas/strategy.py` (`StrategyCreate`, `IndicatorType`…) | El DSL de estrategia que el trader rellena |
| Forma real del resultado | `backend/app/services/backtest_service.py` (`run_backtest`, `_aggregate_metrics`, `_enrich_trades`) | El JSON de salida exacto |
| Auth actual | `backend/app/auth/clerk.py` | Por qué la API necesita API-keys propias, no Clerk |
| Sanitización de errores (gap) | `backend/app/main.py` (`global_exception_handler`) | Hoy **filtra `str(exc)`** → la API pública NO puede reusarlo |
| Asistente in-app actual | `frontend/src/lib/assistant/`, `docs/assistant/` | Patrón de tools reutilizable, pero NO es un MCP externo |
| Componentes que consumen datos | `frontend/src/components/backtester/tabs/` | Plantillas React que el MCP entregará |
| Reglas del repo | `.agent/CODING_RULES.md` | Restricciones de ingeniería que el loop debe respetar |

## Los documentos

| # | Documento | Propósito |
|---|---|---|
| 01 | [`01_VIABILIDAD.md`](01_VIABILIDAD.md) | El "reality check": payload, latencia, aislamiento de IP, límites MCP/LLM, monetización. **Veredicto de viabilidad.** |
| 02 | [`02_PRD.md`](02_PRD.md) | Qué construimos y para quién + glosario de dominio (nomenclatura exacta). |
| 03 | [`03_CONTRATO_DATOS.md`](03_CONTRATO_DATOS.md) | La frontera de comunicación: JSON de entrada/salida derivado del backend real. |
| — | [`openapi.draft.yaml`](openapi.draft.yaml) | Borrador OpenAPI 3.1 ejecutable (mockeable). |
| 04 | [`04_MCP_TOOLS_RESOURCES.md`](04_MCP_TOOLS_RESOURCES.md) | Mapa exacto de Tools y Resources del servidor MCP. |
| 05 | [`05_ARQUITECTURA.md`](05_ARQUITECTURA.md) | Fachada, API-keys, jobs async, metering/billing, despliegue. |
| 06 | [`06_PROMPT_MAESTRO_EJECUCION.md`](06_PROMPT_MAESTRO_EJECUCION.md) | El guion atómico para el loop de ejecución (TDD, DoD, comandos). |
| 07 | [`07_DECISIONES_ABIERTAS.md`](07_DECISIONES_ABIERTAS.md) | Decisiones que Jesús debe firmar (precios, hosting, nombres) con recomendación. |

## Orden de lectura recomendado

1. **01** para decidir si seguimos (viabilidad + riesgos).
2. **07** para firmar las decisiones abiertas (5 min de Jesús).
3. **02 → 03 → 04 → 05** para entender el sistema completo.
4. **06** es lo que se le pasa al loop de ejecución.

## Nomenclatura del producto (provisional)

- **Edgecute** = la plataforma (ya existe; ver `frontend/src/app/layout.tsx`).
- **Edgie** = el asistente in-app actual (NO confundir con el MCP; ver `docs/assistant/`).
- **Edgecute Backtest API** = el producto API B2D (este plan).
- **Edgecute MCP** = el servidor MCP que habla con la API (este plan).

> Los nombres comerciales finales se firman en el doc 07.
