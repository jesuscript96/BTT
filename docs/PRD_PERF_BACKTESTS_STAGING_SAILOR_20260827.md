# PRD — Rendimiento de backtests: plan para `staging` (Sailor)

> **Para:** Sailor (rama `sailor-rama-desarrollo`, integración en `staging`).
> **De:** sesión IA de Álvaro, 2026-08-27 (noche). Rama origen: `alvaro-rama-desarrollo`.
> **Base de todo:** `docs/PRD_PERF_BACKTEST_STREAMBUILD_20260827.md` (§7 medido).
> **Estado:** warmup YA implementado en la rama de Álvaro; slab/N2A medidos y
> **bloqueados por un bug de paridad reproducible** (abajo, §3).

---

## 1. Qué llega de la rama de Álvaro (para cuando se mergee a staging)

1. **Profiler de sub-fases** (`backend/app/services/subphase_profiler.py`), gated
   tras `BACKTEST_PROFILE_SUBPHASES=1` (apagado por defecto, R7). Particiones
   `fetch/prep/translate/postproc/simulate/emit` por ticker-día, con
   `resample/indicators/align` anidados. Logs `[SUBPHASE-DAY]` / `[SUBPHASE]`.
2. **Warmup de indicadores al arrancar** (§2 de este doc) — hilo daemon,
   opt-out `BTT_INDICATOR_WARMUP=0`.
3. **«Últimas pruebas» en Portfolio** (runs auto-guardados clicables) — ver
   MEMORIA_MADRE 2026-08-27 (noche, 2ª parte).
4. ⚠️ Coordinación ya documentada: al llegar `LAKE_PREV_CLOSE_YA_AJUSTADO` a
   staging, Sailor debe añadir `LAKE_PREV_CLOSE_YA_AJUSTADO=true` a su `.env`.

## 2. El diagnóstico medido (resumen; detalle en PRD principal §7)

Máquina de Álvaro, lago local, estrategias reales, ventanas de 9-81 pares:

| Dónde va el tiempo (stream_build) | Medido |
|---|---|
| `fetch` (lectura del stream) | ~0,33-0,9 s **por mes y por run**, recurrente |
| `translate` (señales) — overhead pandas | ~7 ms/ticker-día (el mayor coste recurrente por par) |
| `translate` — resample (1m→5m) | ~3 ms/día — **barato: materializar velas Nm NO paga** |
| `translate` — indicadores (steady) | 0,1-11 ms/día — **barato: tabla de indicadores NO paga** |
| primer ticker-día tras arranque | **2,35 s de compilación** (kernels Numba + 1.er toque pandas) |
| `simulate` (kernel Python, default) | 0,1-0,8 % — irrelevante |

La idea original de Álvaro (precalcular `gap%`, `PMH gap%` etc. en tablas)
apunta a la fase que **ya está materializada y es rápida** (qualifying porgap,
~0,03-2 s): el gap/PMH-gap de qualifying ya sale de la vía materializada
(`9f39a17`). Rechazada con números, no de oído.

**Orden de ataque por coste/beneficio:** ① warmup (hecho) → ② pipeline
slab/señales (bloqueado por paridad, §3) → ③ N2A nativo (depende de ②).

## 3. 🐛 BUG BLOCKER: el pipeline slab diverge del secuencial

A/B/C sobre la MISMA ventana (2026-08-27, máquina de Álvaro):

| Condición | Config | Total | Señales (signals+sim) | Trades | Días |
|---|---|---|---|---|---|
| A secuencial | defaults | 3,62 s | 1.871 ms (stream_build) | **29** | 29 |
| B slab | `BTT_SLAB_STREAM_ENABLED=1` | 1,26 s* | 1.182 ms (**-37 %**) | **37** | 29 |
| C slab+N2A | B + `BTT_N2A_NATIVE_ENABLED=1` | 1,28 s | 1.214 ms | **37** | 29 |

\* rechazado con 503 por `BACKTEST_STRICT_COMPLETENESS=true` (correcto).

- **Repro:** dataset `c9047c21-a3dd-4332-bd42-114f19b9ce59` («Universo_Estrategia_RTH_prueba_XX_8777»), estrategia `6a72068a-…` («Estrategia RTH prueba XX»: EMA20<EMA50 en 5m + Accumulated Volume>2M en 1m, short, sesión custom 09:30-11:00, hard stop + TP parcial, reentradas=1), ventana 2025-01-02→2025-01-31 (81 pares candidatos). Sin slabs construidos (el modo slab cayó al fallback legacy de fetch — la divergencia NO es del slab store, es del pipeline de señales/simulación).
- **37 vs 29 trades**: la diferencia parece estar en días con 2 trades
  (reentrada/TP parcial). Los tests de equivalencia existentes
  (`test_slab_stream_equivalence.py`, Golden B) no cubren esta forma de
  estrategia. Hipótesis a verificar: manejo de reentradas o partial-TPs entre
  el bucle secuencial y `simulate_and_accumulate`.
- **Bug 2 (observabilidad):** en modo slab el reconciliador de completitud
  reporta 0 % — `_tracked_stream` envuelve el `intraday_stream` que el modo
  slab nunca consume (consume `iter_slab_items_with_fallback`). Con
  `BACKTEST_STRICT_COMPLETENESS=true` esto rechaza TODOS los backtests slab.

**Petición concreta a Sailor:** reproducir ambos puntos en staging con datos
del lago de Sailor y, si confirma, priorizar la paridad del pipeline slab
(es la vía del -37 % y desbloquea además evaluar N2A). El warmup se puede
mergeear ya: es independiente y seguro.

## 4. Qué NO hacer (medido)

- **Velas Nm precalculadas en el lago**: el resample cuesta 3 ms/día (7 % del
  stream_build caliente). No paga ni como v1.
- **Tabla de indicadores fijos**: el math steady es 0,1-11 ms/día; lo caro es
  el overhead pandas por llamada, y eso no lo quita ninguna tabla.
- **Activar `BACKTEST_NUMBA_SIM=1` por rendimiento**: la simulación es el
  0,1-0,8 % del run incluso en Python.

## 5. Cómo medir en staging (10 minutos)

```
# backend/.env de staging (temporal):
BACKTEST_PROFILE_SUBPHASES=1
# arrancar, lanzar un backtest pequeño y grepear:
#   [SUBPHASE-SUMMARY] / [SUBPHASE] phase=... ms=... pct_stream_build=...
```

Con esos números de la máquina de staging se decide si el -37 % del pipeline
slab merece la inversión de paridad, o si el resto (fetch mensual) manda.
