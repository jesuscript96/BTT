# PRD 03 — Un trade no es una ejecución: agrupar las ejecuciones de una posición en un solo trade

> **Para:** Edgecute (backend de agregación + frontend de reporte).
> **De:** Álvaro. **Fecha:** 2026-08-21.
> **Anclas verificadas sobre:** `develop` @ `e368839`.
> **Tipo:** fix de métricas/reporte. **Prioridad:** alta — `total_trades` y
> win rate cuentan hoy **ejecuciones**, no trades.
> **No toca el kernel de simulación** (Numba): es agregación posterior.
> **Implementación de referencia:** mi rama — función `_group_partial_exits`
> (`backtest_service.py:992`) + badge del calendario + CSV/tabla de trades.
> Código completo y probado en
> [`reference/group_partial_exits.py.txt`](reference/group_partial_exits.py.txt).

---

## 1. El problema (lenguaje de usuario)

Un trade, por definición, conlleva **al menos 2 ejecuciones** (entrada y
salida); con parciales, 3 o más. Hoy el simulador emite **un registro por
ejecución** — cada Partial TP es un registro aparte que comparte `entry_idx`
con el cierre final de la misma posición — y esos registros llegan a métricas
y UI **como si cada uno fuera un trade**:

- `total_trades` se infla: una posición con 2 parciales cuenta como 3 trades.
- **Win rate contaminado**: un trade ganador con un parcial en pérdida cuenta
  como 1 win + 1 loss.
- Streaks, avg win/loss, expectancy: todos por ejecución en vez de por trade.
- El usuario ve "más trades de los que realmente hizo".

## 2. Anclas en `develop` @ `e368839` (verificadas)

- `backend/app/services/portfolio_sim.py` — el simulador hace
  `trades.append({...})` **por cada ejecución**: TP full (**:250**), parcial
  (**:302**), SL/trailing/time (**:357, :404, :447**), cierre final/EOD
  (**:569**). Cada parcial comparte `entry_idx`/`entry_time` con el cierre
  final de su posición.
- `backend/app/services/backtest_service.py`
  - **:756** — `trades_records = _enrich_trades(`: punto único de
    post-procesado tras `simulate_and_accumulate`.
  - **:803** — `_aggregate_metrics(` consume esa lista.
  - No existe ninguna agrupación (`grep _group_partial_exits` = 0).

> Si `develop` avanzó, re-localizad por expresión (`_enrich_trades`,
> `trades.append`).

## 3. Spec

### T1 — Backend: agrupar ejecuciones en trades (el corazón del fix)

- Portar `_group_partial_exits` — **código completo en
  `reference/group_partial_exits.py.txt`** (98 líneas, portable casi tal
  cual: los campos que no existan en vuestros registros quedan a `None`/`[]`
  porque todo va con `.get()`) — y envolver el punto único:

  ```python
  trades_records = _group_partial_exits(_enrich_trades(...))   # antes de :803
  ```

- La función agrupa ejecuciones **consecutivas con el mismo `entry_idx`**
  (el simulador es monoposición: los registros de una posición salen
  consecutivos). El trade agrupado conserva los campos del primer registro;
  `pnl`/`fees`/`size` se suman; entry de la primera ejecución; exit
  (hora/precio/razón) de la última; `mae`/`mfe` toman el máximo; y añade:
  - `n_executions`: nº de ejecuciones de la posición.
  - `legs`: lista de ejecuciones (`exit_time`, `exit_time_epoch`,
    `exit_price`, `exit_reason`, `size`, `pnl`).
  - `exit_reasons`: cadena de razones (el parcial es intermedia;
    `exit_reason` solo conserva la última).
- Con esto, **todas las métricas y la UI pasan a contar trades**.

### T2 — API: tipos

`TradeRecord` (`frontend/src/lib/api_backtester.ts`):
`n_executions?: number; legs?: Leg[]; exit_reasons?: string[];`

### T3 — UI (reporte honesto)

- **Detalle de día del calendario** (`CalendarTab.tsx`): badge `×N` con
  tooltip "N ejecuciones agrupadas (parciales + cierre)" cuando
  `n_executions > 1`.
- **Tabla de trades** (`TradesTab.tsx`): la columna EXIT refleja las legs —
  un parcial no puede dejar la celda vacía.

### T4 — Opcional (valor extra, no bloquea el fix)

- Chart: línea horizontal al precio exacto de cada ejecución (visualización
  **dentro** del backtester).

> **Sin export CSV de trades — decisión de Álvaro**: los trades viven dentro
> del backtester, nada se externaliza. No añadáis botones de
> exportación/descarga de trades en este PRD.

## 4. Tests / verificación

- **Identidad**: un backtest **sin parciales** da resultados idénticos
  antes/después del cambio (los runs de 1 ejecución no se tocan).
- **Con parciales**: `total_trades` == nº de posiciones; `pnl` del trade ==
  Σ `pnl` de sus legs; win rate pasa al valor por-trade.
- Smoke con un backtest guardado con parciales: comparar `total_trades` y
  win rate antes→después y razonar la diferencia (debe ser exactamente la
  agrupación).

## 5. Definition of Done

- [ ] T1 aplicado en el punto único (`:756`) y las métricas (`:803`) sobre
      trades agrupados.
- [ ] T2 + T3 visibles: badge en calendario y EXIT con legs.
- [ ] Verificación §4 verde (identidad sin parciales incluida).
- [ ] Sin cambios de schema; el kernel de simulación intacto.

## 6. Riesgos

- **Cambian números en backtests con parciales**: `total_trades`, win rate,
  streaks, avg win/loss, expectancy pasan de contar ejecuciones a contar
  trades — los valores nuevos son los correctos; comunicarlo en la nota de
  release. Sin parciales: idénticos.
- La agrupación asume simulador monoposición con registros consecutivos por
  posición (cierto hoy). Si algún día hay reentrada en la misma barra,
  revisar la clave de agrupación.

## 7. Referencia

- [`reference/group_partial_exits.py.txt`](reference/group_partial_exits.py.txt)
  — la función completa tal cual corre en mi rama, con su docstring.
- Commits de referencia en `alvaro-rama-desarrollo`: `39a2d80` (agrupación
  backend + badge), `3dcd7d0` (tipos + TradesTab; **incluye un export CSV
  que NO forma parte de este PRD** — excluido por decisión de Álvaro),
  `1249ca1` (columna EXIT), `93656e0` (líneas por ejecución en el chart).
