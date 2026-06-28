# Dilution & Runner Assessment v2.0 — Suite de Documentos PRD

Este suite de documentos define los requisitos, diseño técnico e implementación del módulo de **Evaluación de Dilución y Runner (v2.0)** para Edgecute/BTT, optimizando la visualización de SEC Filings (con la nueva subpágina de Balance), estructurando la visualización de Ownership (con priorización de personas físicas vs instituciones), integrando reglas detalladas de riesgo de dilución extrema (ATM, Warrants, Convertible Notes, Baby Shelf Rule, y regulaciones Nasdaq) y resolviendo problemas identificados en el asistente Edgie.

**Estado:** PLAN  
**Enfoque:** KISS (Keep It Simple, Stupid) pero Perfecto.

---

## Fuentes auditadas (Verdad anclada en código)

| Pieza real | Fichero | Qué aporta a este PRD |
|---|---|---|
| Enpoints de Filings y Balance Sheet | [ticker_analysis.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/ticker_analysis.py) | Endpoints de carga de filings RSS (`/sec-filings` línea 1272) y Balance Sheet trimestral de yfinance (`/balance-sheet` línea 1152). |
| Dilución & UI de Filings | [TickerAnalysis.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/TickerAnalysis.tsx) | Estructura visual de Filings y llamada a `triggerAiAnalysis` (línea 2029) con prompt y parseo de `<edgie_metrics>`. |
| Edgie Chatbot UI & Events | [ChatBot.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/ChatBot.tsx) y [ChatBotAgentic.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/ChatBotAgentic.tsx) | Manejador del evento `ticker-loaded` (líneas 92 y 170 respectivamente) que duplica el aviso de carga exitosa. |
| AI Chat Gateway BE | [assistant.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/assistant.py) | Router para llamadas LLM `/api/assistant/chat` delegadas a DeepSeek de forma segura. |

---

## Estructura del Suite de PRD

Este paquete de requerimientos consta de los siguientes documentos que deben leerse y seguirse secuencialmente:

| # | Documento | Propósito |
|---|---|---|
| **01** | [01_VIABILIDAD.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/01_VIABILIDAD.md) | Análisis de rendimiento (tiempos de análisis), factibilidad de la base de datos de bancos, riesgos y veredicto. |
| **02** | [02_PRD.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/02_PRD.md) | Definición funcional del MVP: subpágina "Balance", tabla de ownership, reglas avanzadas de dilución, y restricciones de comportamiento de Edgie. |
| **03** | [03_CONTRATO_DATOS.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/03_CONTRATO_DATOS.md) | Definición exacta de los payloads JSON intercambiados, incluyendo la actualización del schema de `<edgie_metrics>` y el modelo del balance. |
| **04** | [04_UI_COMPONENTES.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/04_UI_COMPONENTES.md) | Prototipos visuales y comportamiento de UI (tamaño compacto de cards, pestañas Filings/Balance, tabla de ownership y comportamiento del cargando). |
| **05** | [05_ARQUITECTURA.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/05_ARQUITECTURA.md) | Diseño de persistencia (tabla DuckDB para el registro de bancos dilusores), flujo de ejecución y modificaciones al prompt de Edgie. |
| **06** | [06_PROMPT_MAESTRO_EJECUCION.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/06_PROMPT_MAESTRO_EJECUCION.md) | Plan de tareas atómicas secuenciadas para la implementación paso a paso (TDD, código y comandos de verificación). |
| **07** | [07_DECISIONES_ABIERTAS.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/07_DECISIONES_ABIERTAS.md) | Puntos de negocio diferidos y decisiones de diseño frontend/backend reversibles. |
| **08** | [08_CONFIGURACION_EDGIE_PM.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/dilution-runner-assessment/08_CONFIGURACION_EDGIE_PM.md) | **Guía para el Product Manager**: cómo está configurado Edgie, dónde viven los prompts, qué se puede ajustar sin tocar arquitectura y qué se entregó en v2.0. |

**Orden de lectura sugerido:**  
`00_INDEX` → `01_VIABILIDAD` → `02_PRD` → `03_CONTRATO_DATOS` → `04_UI_COMPONENTES` → `05_ARQUITECTURA` → `06_PROMPT_MAESTRO_EJECUCION` → `07_DECISIONES_ABIERTAS` → `08_CONFIGURACION_EDGIE_PM`
