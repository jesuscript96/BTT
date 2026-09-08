# Cambios recientes en `staging` — resumen para Sailor

> Rama de trabajo conjunta: **`staging`**. Actualizado: 2026-08-17 (Álvaro).
> Resumen cortísimo de lo modificado; el detalle está en el código y en los commits.

## 🔴 Rigor del backtester (¡afecta a los resultados!)

1. **Conteo REAL de trades (no ejecuciones).**
   El simulador emite un registro por *ejecución*: cada Partial TP era un registro
   suelto, así que `total_trades` se inflaba y contaminaba el win rate. Ahora se
   agrupan todas las ejecuciones de una misma posición (mismo `entry_idx`) en **UN**
   trade.
   - `_group_partial_exits()` → `backend/app/services/backtest_service.py`
   - `_aggregate_partials()` → `backend/app/services/portfolio_service.py`
   - Regla: **una posición (entrada + parciales + cierre) = 1 trade. Un Partial TP nunca es un trade.**

2. **`look_ahead_prevention = True` por defecto.**
   Entrar/salir al cierre de la vela que dispara la señal era look-ahead encubierto.
   Ahora la ejecución realista entra en la **apertura de la vela siguiente** (los 5
   puntos de entrada quedan en `True`: orchestrator, service, optimization, API).
   - ⚠️ Cambia el resultado de **todos** los backtests (más conservador, sin sesgo).

## ✨ Nuevo

3. **Feature Portfolio.** Combinar varias estrategias en un portfolio (sizing por
   peso, con la agregación de partials del punto 1).
   - Backend: `routers/portfolio.py`, `services/portfolio_service.py` (+ tests).
   - Frontend: `components/database/PortfolioBuilder.tsx`, `lib/api.ts`.

4. **Indicador "Current Gap (%)" en Entrada lógica.** Gap vivo del precio
   (close de la vela) vs cierre de ayer, evaluado vela a vela durante todo el
   día (PM y RTH) — a diferencia de "PM High Gap (%)" (máximo acumulado del
   premarket, que se congela al cerrar el PM). Comparadores >=, <=, >, <.
   Misma cadena de fallback de `prev_close` que PM High Gap. Paridad
   legacy↔nativa cubierta en `tests/test_current_gap_semantics.py`.

5. **Ajustes menores:** indicadores (`indicators.py`), `CalendarTab`,
   `ConditionBuilder`, caché GCS, tipos de estrategia.

## 🔧 Flujo de trabajo
- Todo se commitea a **`staging`** (nuestro entorno común). `main` no se toca.
- `git pull origin staging` **antes** de trabajar; confirmar antes de cada push.
- Detalle en `AGENTS.md` → `.agent/SAILOR_DEV_BRANCH.md`.
