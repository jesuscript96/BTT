# 00 — Índice y trazabilidad · Página de Portfolio

> **Feature:** `/portfolio` — combinar backtests del Baúl en una cartera, analizar riesgo
> (Montecarlo, VaR/CVaR, correlación Pearson/Spearman), optimizar pesos (Kelly, Líderes, HRP)
> y monitorizar el rendimiento a 3 meses. **Estado:** PLAN ejecutable (greenfield analítico
> sobre datos ya existentes en `backtest_results`).
>
> **Origen:** PRD de producto de Jaume (`PÁGINA DE PORTFOLIO.pdf` + `prd_pagina_portfolio.md`).
> Este suite es la **versión ejecutable anclada en el código real** del repo, con las decisiones
> técnicas (CTO) ya resueltas. Sigue la convención de [`docs/b2d-gateway/`](../b2d-gateway/00_INDEX.md)
> y del [Manual de PRD ejecutable](../manual-prd/GUIA_PRD_EJECUTABLE.md).

**Visión en una frase:** *"Quiero combinar mis mejores estrategias del Baúl, analizar cómo se
comportan juntas a nivel de riesgo, simular el tamaño de cuenta ideal, y monitorizarlas
solapándolas con el rendimiento real."*

## Documentos del suite

| Doc | Contenido |
|---|---|
| [00 · Índice y trazabilidad](00_INDEX.md) | Este documento. Fuentes auditadas y mapa. |
| [01 · Viabilidad](01_VIABILIDAD.md) | Reality-check contra el código, coste, riesgos, veredicto. |
| [02 · PRD](02_PRD.md) | Qué, para quién, alcance MVP, glosario didáctico (§2.5 literal). |
| [03 · Contrato de datos](03_CONTRATO_DATOS.md) | Modelos Pydantic, endpoints internos, errores, origen de la curva diaria. |
| [04 · API comercial · MCP · PostHog](04_API_MCP_ANALYTICS.md) | **Las tres capas transversales** que pidió Jesús: módulo en `api_public`, componentes MCP, taxonomía de eventos. |
| [05 · Arquitectura](05_ARQUITECTURA.md) | Dónde vive cada fichero, reuso, aislamiento de IP. |
| [06 · Prompt maestro de ejecución](06_PROMPT_MAESTRO_EJECUCION.md) | Guion por fases (TDD) para Claude Code. |
| [07 · Decisiones abiertas](07_DECISIONES_ABIERTAS.md) | Lo diferido y las decisiones de CTO ya tomadas. |

## Fuentes auditadas (verdad anclada en código)

| Pieza real | Fichero (fuente) | Qué aporta |
|---|---|---|
| Tabla de Backtests Guardados (Baúl) | `backend/app/init_db.py:222-240` | Tabla `backtest_results`: `results_json` (con `day_results`, `equity_curves`, `all_trades`) + columnas agregadas. **No tiene `user_id`** → la DuckDB es **por-usuario**. |
| Montecarlo existente | `backend/app/services/montecarlo_service.py` | Baraja **PnL de trades** (no retornos diarios). Sirve de referencia de estilo; el Montecarlo de cartera es **nuevo** (a nivel de retornos diarios). |
| Agregación de métricas | `backend/app/services/backtest_service.py` (`_aggregate_metrics`) | Sharpe, drawdown, win rate, profit factor sobre `day_results`. |
| Tabla de Estrategias | `backend/app/init_db.py:169` | `strategies` creadas por el usuario. |
| Simulador del motor (¡NO confundir!) | `backend/app/services/portfolio_sim.py` | Simulador numpy de **una** estrategia (motor de backtest). **Colisión de nombre** → el servicio nuevo se llama `portfolio_analytics_service.py`. |
| Módulo de API comercial (plantilla) | `backend/app/api_public/modules/backtest/` | Patrón router/models/meta/mapper + Facade + gating + metering. **Plantilla exacta** para el módulo `portfolio`. |
| Servidor MCP (build-time) | `mcp/src/{server,components,codegen,docs}.ts` | Catálogo de componentes + codegen del cliente tipado + docs/resources. |
| Taxonomía PostHog | `frontend/src/lib/analytics.ts` | `EVENTS` centralizados + `track()`. Punto único donde añadir eventos de portfolio. |
| Entitlements | `backend/app/entitlements/policy.py` | Catálogo de features y tiers (MVP en abierto). Aquí se declaran las features `portfolio.*`. |
| Tabs anidados (patrón UI) | `frontend/src/components/backtester/ResultsTabs.tsx` | Patrón de pestañas internas para el submenú de Portfolio. |
| Design System | `docs/DESIGN_SYSTEM.md` + `frontend/src/app/globals.css` | Tokens, tipografías (General Sans/Fraunces), colores de P&L. |
