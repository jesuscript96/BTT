# PRD — Lentitud al lanzar un backtest: el cuello es `stream_build`

> **Estado:** BORRADOR para revisión (Álvaro + GLM). Nada implementado.
> **Autor del borrador:** sesión IA de Álvaro, 2026-08-27.
> **Rama:** `alvaro-rama-desarrollo` (no tocar staging; no se implementa aquí).
> **Objetivo:** documentar el diagnóstico ya medido, aterrizarlo en el código
> real y dejar decididas las opciones antes de escribir una sola línea de fix.

---

## 1. Problema

Lanzar un backtest tarda demasiado. La medición del 26/08 (con los `[TIMING]`
del propio motor) es inequívoca:

- Run de ~86 s → **`stream_build` se lleva ~83 s (95 %)**.
- El **qualifying ya NO es el problema**: 3,5 s en frío, ms en caché. La vía
  materializada del bygap (`9f39a17`, ya en esta rama) hizo su trabajo.

Es decir: el tiempo se va **dentro del bucle que, por cada ticker-día,
resamplea velas y recalcula indicadores en Python antes de simular**, y ese
trabajo se **repite idéntico en cada backtest** (y decenas de veces por rejilla
en cada optimización).

## 2. Dónde se va el tiempo (camino caliente, con referencias)

Todo ocurre en el bucle de `run_backtest()`:

| Paso | Qué hace, por ticker-día | Ubicación |
|---|---|---|
| Estructura de mercado | `cummax`/`cummin` (HOD/LOD), PM high/low acumulado, prev high/low (`shift`) | `backtest_service.py:618-675` |
| Construcción `mini_df` | crea un `pd.DataFrame` nuevo por día | `backtest_service.py:678` |
| **Resample + indicadores + señales** | `translate_strategy()` → resample 1m→Nm y recálculo de indicadores | `backtest_service.py:704` → `strategy_engine.py:551` |
| Resample real | `_resample_arrays_time_based(...)` | `strategy_engine.py:703, :852` |
| Simulación | kernel Numba `simulate(...)` | `backtest_service.py:887` |
| Marca de tiempo de la fase | `_log_phase("stream_build", ...)` | `backtest_service.py:933-936` |

**Hipótesis a confirmar con profiler fino:** dentro de `stream_build`, el grueso
NO es la simulación Numba (ya compilada) sino **resample + indicadores en
pandas/numpy**, que es exactamente lo que se puede precalcular una vez.

## 3. Lo que ya está optimizado (no re-hacer)

- **Qualifying materializado** (`9f39a17`, bygap opt-in): ya rápido.
- **`_signal_cache` para optimización de solo-riesgo** (`backtest_service.py:683`):
  cuando el optimizer varía únicamente la gestión de riesgo, reutiliza
  entries/exits ya calculadas y solo re-parsea el riesgo. **No cubre** barridos
  que cambian condiciones de entrada/indicadores (ahí se recalcula todo).
- **Paralelización del bucle** ya existe (`should_parallelize`,
  `backtest_service.py:367`), pero se desactiva cuando corre el optimizer
  (`_signal_cache` presente).

## 4. Propuesta (del análisis del 26/08, aterrizada)

Aplicar el **patrón del bygap** (materializar una vez, regenerar tras cada
`actualizar_diario`) a lo que hoy se recalcula en cada run:

1. **Velas Nm precalculadas en el lago** — el resample 1m→5m/15m se hace una vez
   en el ETL (parquet por ticker-mes), no en cada backtest. Ataca directamente
   `_resample_arrays_time_based`.
2. **Indicadores de parámetros FIJOS precalculados por (ticker, día)** — lista
   cerrada inicial (EMAs típicas, Accum Volume, RVOL, PM high/low vs open…).
   Los de **parámetros libres** del usuario (p.ej. Squeeze con ventana variable)
   se siguen calculando en vivo: la tabla no puede llevar todas las
   combinaciones.
3. **Precarga del universo** — extender el `[PRECACHE]` para dejar calientes,
   tras cada update, los ticker-días candidatos más frecuentes.

**Impacto estimado (por confirmar con profiler):** si resample+indicadores son
la mitad de `stream_build`, una run en frío pasaría de ~3,5 min a ~1,5 min, y
las **optimizaciones serían las más beneficiadas** (repiten el mismo cálculo
por cada punto de la rejilla).

## 5. Arte previo en el repo (evaluar antes de construir)

Ramas remotas que atacan justo esto — revisar si alguna ya resuelve parte:

| Rama | Qué promete | Relación |
|---|---|---|
| `origin/feat/resample-memo` (`17fdec3`) | memoiza el `cond_df` resampleado por (día, timeframe), dedup de resamples entre condiciones | Ganancia **intra-run** barata; complementaria a materializar. **Candidata a mergear pronto.** |
| `origin/feat/backtest-multiprocessing` | paraleliza el bucle de ticker-días | Ortogonal: reparte, no elimina el recálculo |
| `origin/feat/f2-numba-engine` | motor Numba para la fase 2 | Puede reducir el coste de indicadores en vivo |
| `origin/perf-runner-stats`, `origin/performance` | instrumentación/perf general | Fuente de profiler ya hecho |

## 6. Puntos a decidir (juntos / con GLM)

1. **Qué indicadores entran** en la tabla fija (lista cerrada v1).
2. **Dónde viven** los precalculados: lago `cangrejo_data` vs caché del backend.
3. **Invalidación** tras cada `actualizar_diario` (el bygap ya se regenera en
   34 s; estas tablas seguirían el mismo paso final).
4. **Coste de disco**: estimación inicial ~1,5-2× el intradía para velas 5m +
   indicadores. ¿Aceptable en el disco de Álvaro?
5. **¿Merecería la pena antes** mergear `feat/resample-memo` y volver a medir?
   Puede que baje el `stream_build` lo suficiente para replantear el alcance.
6. **Optimización con cambio de condiciones**: ¿ampliar `_signal_cache` para
   cubrir también barridos de indicadores fijos leyendo de la tabla?

## 7. Primer paso (antes de construir NADA)

**Profiler fino sobre 5-10 ticker-días** que parta `stream_build` en sus
sub-fases: `lectura / resample / indicadores / simulación`. Solo con esos
números se decide **qué tabla paga su coste** y cuál no. Si el resample resulta
barato y el peso está en un indicador concreto, el alcance cambia por completo.

> Regla del repo (AGENTS.md): medir antes de optimizar; cambios de datos apagados
> por defecto (R7). Cualquier tabla nueva iría gated y regenerable, sin tocar el
> schema compartido sin consenso.

## 8. Fuera de alcance de este PRD

- Cualquier cambio en `staging` (solo auditar/reportar).
- El `UPDATE` de `pmh_gap_pct` sobre 19,2M filas **en cada arranque del backend**
  (`init_db.py` / `_alinear_pmh_gap_pct`): es lentitud de **arranque**, no de
  lanzar un backtest. Jaime lo dejó anotado como candidato aparte en
  `MEMORIA_MADRE.md`. Merece su propio mini-PRD si molesta el arranque.
