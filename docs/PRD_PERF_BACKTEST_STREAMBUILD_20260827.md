# PRD — Lentitud al lanzar un backtest: el cuello es `stream_build`

> **Estado:** §7 EJECUTADO (2026-08-27): profiler fino medido, alcance revisado —
> los precalculados dejan de ser la v1 (ver §7). Resto del PRD intacto a la
> espera de decisión. **Autor del borrador:** sesión IA de Álvaro, 2026-08-27.
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
| `origin/feat/resample-memo` (`17fdec3`) | memoiza el `cond_df` resampleado por (día, timeframe), dedup de resamples entre condiciones | **YA contenida en esta rama** (verificado 2026-08-27: `17fdec3` es ancestro). El memo ya vive en `_evaluate_single_condition`. |
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

## 7. Primer paso — EJECUTADO: profiler fino con números (2026-08-27)

**Instrumentación:** `backend/app/services/subphase_profiler.py`, gated tras
`BACKTEST_PROFILE_SUBPHASES=1` (apagado por defecto, regla R7; con la var en
off todo hook es un chequeo de booleano). Particiones medidas por ticker-día:
`fetch` (next del stream), `prep` (estructura+mini_df), `translate`
(señales; anidado: `resample`, `indicators`, `align`), `postproc`, `simulate`,
`emit`. Log por día (`[SUBPHASE-DAY]`) y resumen (`[SUBPHASE]`/`[SUBPHASE-SUMMARY]`).

**Medición** (máquina de Álvaro, lago local, dataset+estrategias suyos sin
tocar, `look_ahead_prevention: true`, completitud 100 % en los tres runs):

| Run | Estrategia / ventana | stream_build | fetch | translate (resample+ind+align) | simulate | Nota |
|---|---|---|---|---|---|---|
| 1 FRÍO | «RTH prueba XX» (EMA 5m + vol 1m), 9 pares, 1 mes | 3.404 ms | 873 ms (25,7 %) | 2.489 ms (73,1 %) — de los cuales indicators 2.352 ms | 3 ms (0,1 %) | 1.ª corrida tras arrancar backend |
| 3 CALIENTE | ídem ídem (re-run) | 460 ms | 332 ms (72,3 %) | 97 ms (21,1 %) = overhead ~63 + resample 27 + align 6 + **ind 0,9** | 2,5 ms (0,5 %) | mismo proceso, mes ya visto |
| 2 todo-1m | «Doble Techo 1» (5 condiciones 1m), 10 pares, 1 mes | 551 ms | 362 ms (65,7 %) | 117 ms (21,3 %) — indicators 110 ms | 2,3 ms (0,4 %) | mes nuevo para el proceso |

**Lectura de los números:**

1. **El resample es BARATO**: 3,0 ms/día (más 0,7 de align) con la estrategia
   multi-timeframe; 0 ms en estrategias todo-1m. Son el 7 % del stream_build
   caliente. **Materializar velas Nm en el lago no paga como v1** — el alcance
   cambia tal como anticipaba este apartado.
2. **Los "indicadores" del run frío eran compilación, no cálculo**: 2.352 ms
   concentrados en el PRIMER ticker-día del proceso; los días siguientes marcan
   0,1 ms. En caliente, el coste steady por llamada es overhead pandas
   (~1-2 ms/indicador): 0,1 ms/día en frames 5m, ~11 ms/día con 5 indicadores
   sobre el frame 1m completo. **La tabla de indicadores fijos tampoco paga**
   mientras el consumo siga pasando por pandas.
3. **`fetch` es recurrente por run y mes** (~0,33-0,9 s/mes aunque el mes ya se
   haya leído en ese proceso — el stream re-escanea el parquet del mes en cada
   corrida). Un dataset de 24 meses paga ~8-20 s por run solo en esto.
4. **La simulación NO es el problema — y además no es Numba**: el default es
   `BACKTEST_NUMBA_SIM=0` (kernel Python de `portfolio_sim`) y aun así cuesta
   0,1-0,8 % del stream_build. La fila «kernel Numba» de §2 era errónea para la
   config por defecto; activar Numba no compra throughput aquí.
5. **Extrapolación que cuadra con los 86 s del 26/08** (dataset 4.855 pares,
   24 meses): 4.855 × ~13 ms/día + 24 × ~0,35 s/mes ≈ 63 + 8 ≈ 71 s, más
   qualifying/aggregate/emit ≈ 80-90 s. ✓

**Recomendación (qué atacar primero — nada de tablas todavía):**

1. **Warmup de indicadores al arrancar el backend** (2,35 s del primer run a
   coste ~0). El patrón ya existe: `sim_dispatch.warmup()` para Numba.
2. **Slab stream** (`BTT_SLAB_STREAM_ENABLED`, ya implementado y gated): ataca
   justo el `fetch` mensual recurrente (mmap en vez de re-escanear).
3. **Path nativo N2a como default para estrategias simples**
   (`translate_strategy_native` ya existe): elimina el overhead pandas por
   condición/indicador que es el mayor coste steady por ticker-día (~7 ms).
4. Solo si tras 1-3 stream_build sigue doliendo: reconsiderar precalculados —
   y entonces más como columnas planas por (ticker, día) que como velas Nm.

**Sobre `feat/resample-memo` (§5):** ya está contenida en esta rama
(`17fdec3` es ancestro de `alvaro-rama-desarrollo`) — el memo `__resampled__`
por (día, timeframe) vive en `_evaluate_single_condition`. Nada que mergear;
explica que el resample muestre 1 llamada/día/timeframe y sea tan barato.

> Regla del repo (AGENTS.md): medir antes de optimizar; cambios de datos apagados
> por defecto (R7). Cualquier tabla nueva iría gated y regenerable, sin tocar el
> schema compartido sin consenso.

## 8. Fuera de alcance de este PRD

- Cualquier cambio en `staging` (solo auditar/reportar).
- El `UPDATE` de `pmh_gap_pct` sobre 19,2M filas **en cada arranque del backend**
  (`init_db.py` / `_alinear_pmh_gap_pct`): es lentitud de **arranque**, no de
  lanzar un backtest. Jaime lo dejó anotado como candidato aparte en
  `MEMORIA_MADRE.md`. Merece su propio mini-PRD si molesta el arranque.
