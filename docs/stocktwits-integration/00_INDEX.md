# Integración de Stocktwits — Documento de pre-producción

> **Qué es esto.** El plan completo y anclado en el código real para integrar la API oficial de Stocktwits en **Edgecute**. Permite habilitar: (1) Radar de Momentum para Small Caps, (2) Explicaciones naturales "Why It's Trending", (3) Termómetro de Sentimiento a 15 minutos en el detalle de Tickers, (4) feeds de debate comunitario limpios de spam y (5) boletines técnicos como Chart Art.
>
> **Estado:** PLAN. Ningún código de producción todavía. Este suite es la especificación funcional y técnica que guiará el desarrollo futuro sin margen a la alucinación.

> **Estado de las decisiones (importante):**
> - Lo que **el PM ha decidido**: La integración debe priorizar Small Caps (Capitalización < $2,000M USD). Las llamadas externas deben mitigarse mediante almacenamiento en caché local.
> - Lo que son **defaults técnicos reversibles**: Uso del patrón SWR (Stale-While-Revalidate) en `users.duckdb` con TTLs diferenciados, persistencia en la tabla `ticker_analysis_cache`, y reutilización del componente de noticias.
> - **NO hay política de monetización definitiva en este plan**: El gating de qué tiers (Pro, Free) acceden a cada módulo social se deja diferido a Jesús. El PRD solo provee el mecanismo.
> - Preguntas realmente abiertas: Ver [`07_DECISIONES_ABIERTAS.md`](07_DECISIONES_ABIERTAS.md) §A.

## Cómo se montó este plan (trazabilidad)

Todo lo que sigue está **anclado en el código actual** del repositorio, no en suposiciones. Fuentes auditadas:

| Pieza real | Fichero | Qué aporta al plan |
|---|---|---|
| Ingesta y Caché SWR | [ticker_analysis.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/ticker_analysis.py#L50-L110) | Patrón de caché asíncrona SWR sobre DuckDB para evitar timeouts y rate limits de APIs de terceros. |
| Modelo de base de datos | [init_db.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/init_db.py#L200-L208) | Estructura de `ticker_analysis_cache` en `users.duckdb` para guardar los payloads JSON de Stocktwits. |
| Gestión de base de datos | [database.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/database.py#L11-L18) | Mecanismos de lectura/escritura y locks concurrentes de DuckDB. |
| Router de Noticias Existente | [news.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/news.py) | Estructura actual de feed de noticias RSS (Yahoo, Investing, MarketWatch) para evaluar la extensión o coexistencia de feeds. |
| Componente News Feed FE | [NewsFeed.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/NewsFeed.tsx) | Estructura visual para desplegar feeds y carruseles de noticias. |
| Panel de Análisis de Ticker | [TickerAnalysis.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/TickerAnalysis.tsx) | Dónde se integrará el Termómetro de Sentimiento, el catalizador de tendencia y la pestaña de Debate Comunitario. |
| Design System | [.agent/EDGECUTE_DESIGN_SYSTEM.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/.agent/EDGECUTE_DESIGN_SYSTEM.md) | Tokens de colores, tipografías (Fraunces/General Sans) y estilos de botones y badges de sentimiento. |

## Los documentos

| # | Documento | Propósito |
|---|---|---|
| 01 | [`01_VIABILIDAD.md`](01_VIABILIDAD.md) | El "reality check": latencias de la API de Stocktwits, límites de peticiones (Rate Limits) y veredicto de viabilidad. |
| 02 | [`02_PRD.md`](02_PRD.md) | Qué construimos y para quién, MVP vs. Fase 2, fuera de alcance, y glosario de dominio. |
| 03 | [`03_CONTRATO_DATOS.md`](03_CONTRATO_DATOS.md) | Especificación de los modelos Pydantic de entrada/salida y JSONs de ejemplo. |
| 04 | [`04_UI_COMPONENTES.md`](04_UI_COMPONENTES.md) | Detalle de pantallas y componentes visuales, incluyendo los 4 estados (loading/empty/error/success). |
| 05 | [`05_ARQUITECTURA.md`](05_ARQUITECTURA.md) | Flujo de datos end-to-end, modelo de caché en DuckDB y manejo de threads de refresco. |
| 06 | [`06_PROMPT_MAESTRO_EJECUCION.md`](06_PROMPT_MAESTRO_EJECUCION.md) | Guion de ejecución por tareas atómicas con TDD, Definition of Done y comandos de validación. |
| 07 | [`07_DECISIONES_ABIERTAS.md`](07_DECISIONES_ABIERTAS.md) | Decisiones pendientes de firma por el PM y defaults técnicos. |

## Orden de lectura recomendado

1. **01** para comprobar la viabilidad y los límites del API de Stocktwits.
2. **02** para alineación de producto y funcionalidades.
3. **07** para firmar las decisiones pendientes.
4. **03 → 04 → 05** para detalles técnicos y contratos.
5. **06** para el handoff y ejecución por parte del agente en modo loop.

## Nomenclatura del producto

- **Radar de Social/Momentum** = Módulo para buscar y filtrar small caps en tendencia social.
- **Why Trending Catalyst** = Explicación sintética de por qué el ticker es popular hoy.
- **Sentiment Gauge** = Termómetro visual de sentimiento alcista/bajista a 15m.
- **Zona de Debate** = Stream de publicaciones de la comunidad Stocktwits filtrado contra bots.
