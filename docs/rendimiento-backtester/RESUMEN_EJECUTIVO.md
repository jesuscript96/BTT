# RESUMEN EJECUTIVO — Rendimiento del backtester: análisis, ejecución y resultados

**Fecha:** 2026-07-02 · **Rama:** `performance` (commits `c81d394` → `cad5ef7`, 7 commits)
**Encargo:** "la competencia va 5-10x más rápido; analiza la performance de verdad, propón por
impactos, y ejecuta el plan completo demostrando que los resultados mejoran".

**Resultado en una línea: el mismo backtest, con resultados bit-idénticos, pasa de
2.532 ms a 154 ms (16,8x) — y la primera ejecución deja de pagar el peaje de GCS.**

---

## 1. El análisis sobre el análisis previo (por qué no nos fiábamos — y hacíamos bien)

Había tres piezas de trabajo previo, y las tres eran **correctas en lo suyo pero medían
dentro del marco equivocado**:

| Trabajo previo | Qué decía | Qué encontramos al medir end-to-end |
|---|---|---|
| `docs/PRD_SIGNAL_OPTIMIZATION.md` (jul-1) + commit `5bdaf8c` (N1+N2a, "6.2x") | "El 89% del tiempo es maquinaria pandas **dentro de la generación de señales**" → optimizó señales 1.229→66 µs/par | Cierto dentro de su fase — pero esa fase era **~3-6% del tiempo total**. El 6.2x real sobre el backtest completo era ≈1.05x. Midieron la fase, no el pipeline. |
| Rama `feat/f2-numba-engine` (Adrián, jun-29): kernel Numba de `simulate()`, MATCHED tol 0 | "Solo 1.7x on loop — not bottleneck for gap datasets" → se aparcó | El kernel era **perfecto** (lo hemos rescatado tal cual y pasa 660 equivalencias bit a bit). Rendía 1.7x porque el cuello estaba en otro sitio: con el ensamblado arreglado, ese mismo kernel deja el simulador en ~30 ms para 639 días. **Se descartó una pieza buena por medirla contra el cuello equivocado.** |
| Comentarios de hardware en el código ("CCX23 15GB", "CCX33 30GB", gates de RAM) | Diseño defensivo para cajas cloud pequeñas | La caja real es un **Xeon W-2145 dedicado con 128 GB y discos HDD** — medio código estaba defendiéndose de límites que ya no existen, y a la vez el diseño de "miles de parquets pequeños por-ticker" es lo peor posible para HDD (~10 ms/seek). |

**La lección metodológica** (vale para el futuro): optimizar una fase exige primero el
desglose end-to-end con el código real. Por eso lo primero que se construyó fue
`scripts/bench_e2e.py` (bench reproducible del pipeline completo, offline, con checksum).

## 2. El análisis nuevo (medido, no estimado) — dónde se iba el tiempo de verdad

Desglose del baseline con el código real (1.200 pares, caché de disco caliente = el mejor
caso de prod hoy; detalle en [`BASELINE.md`](BASELINE.md)):

| Fase | µs/par | % | Causa raíz |
|---|---|---|---|
| **Ensamblado** (`_fetch_and_cache_month`: read_parquet×N ficheros por-ticker → concat → to_datetime+merge → strftime → sort → groupby) | 1.526 | **72%** | maquinaria pandas re-ejecutada en CADA backtest; N ficheros pequeños (letal en HDD) |
| **Preproceso por par** (`sort_values`+`drop_duplicates`+`reset_index` × 1.200) | 276 | **13%** | limpieza repetida por par en cada run |
| Señales (ya optimizadas por el PRD anterior) | 120 | 6% | — |
| Simulate + acumulación (Python puro + pd.Series/.iloc por par) | 186 | 9% | motor sin JIT + payload con pandas |
| **TOTAL** | **2.110** | 100% | |

Y alrededor del CPU, los hallazgos de infraestructura:

- **Bucket GCS en US ↔ servidor en Alemania**: cada mes frío cruza el Atlántico; el layout
  (1 parquet de ~37M filas/mes + `ticker IN (...)`) tiene una amplificación de lectura
  enorme (medido: 20 tickers×1 mes = 74 s desde red doméstica).
- **Discos HDD sin NVMe** en la caja real → el caché de miles de parquets por-ticker es
  patológico en frío; el diseño correcto es ficheros grandes secuenciales + page cache
  (128 GB dan para el histórico entero).
- 2017 sigue en formato raw (250 ficheros/mes); 2018-2020 en backfill.
- **PR #4 (las señales) fue revertido en `main`** (`8c9fa96`) — sigue sin explicación;
  preguntarlo antes de mergear esta rama (decisión abierta A6 del PRD).

## 3. Qué se ha hecho (PRD ejecutado completo — 6 EPICs, todo tras flags default OFF)

Plan completo en [`PRD_EJECUTABLE.md`](PRD_EJECUTABLE.md); activación en [`RUNBOOK.md`](RUNBOOK.md).

| EPIC | Pieza | Efecto |
|---|---|---|
| A | Logs `[TIMING] phase=... pairs=... ms=...` greppables | medir prod antes/después sin adivinar |
| B | **Slab store**: 1 fichero Arrow/mes (mmap, sin compresión) + índice `(ticker,date)→filas` + manifest con fingerprint; el backtest lee **slices numpy zero-copy** | mata el 85% del coste (ensamblado+preproc): 1.831 ms → 12 ms |
| C | **Réplica local**: daemon que construye slabs de todo el histórico desde GCS **o desde un mirror local** (`BTT_REPLICA_SOURCE` — enchufe directo para la migración de datos del CTO) + warm de page cache para neutralizar los HDD | primera ejecución = siguientes; BROAD deja de ser especial |
| D | **Kernel Numba** del simulador — el de Adrián (`435ef11`) rescatado verbatim a módulo nuevo + dispatcher (`portfolio_sim.py` INTACTO) + Mitad B sin pandas por par | simulate+accum 224 → 72 ms; RSS pico −49% |
| E | Slab conectado al `run_backtest` real (fallback por mes al path legacy; workers por referencias mmap) | el speedup llega al endpoint de producción tal cual |
| F | Runbook, informe, comentarios de HW corregidos | operación y trazabilidad |

**No se ha tocado** (lista sagrada): `portfolio_sim.py`, `indicators.py`,
`backtester/engine.py`, el Parquet de GCS, el optimizador, la API pública (ni una clave del
response). Único cambio en zona core: 1 import en `backtest_service.py:21` → dispatcher
(consenso C1 pendiente con Adrián).

## 4. Resultados (todo con el MISMO checksum de resultados)

| Escala (bench del pipeline real, M4) | Antes | Después (slab+JIT) | Speedup | Checksum |
|---|---|---|---|---|
| 1.200 pares | 2.589 ms | **154 ms** | **16,8x** | 639 trades · −17,49 ✔ idéntico |
| 3.000 pares | 6.623 ms | **582 ms** | **11,4x** | 1.557 trades · −20,28 ✔ idéntico |
| `run_backtest` completo (endpoint real) | ~2,6 s | **169,5 ms** | ~15x | ✔ idéntico |
| RSS pico del proceso | 1.260 MB | **640 MB** | −49% | — |

**Garantías de equivalencia (43 tests nuevos, todos verdes):** stream legacy vs slab bit a
bit; señales por ambas vías idénticas; kernel JIT vs Python — 660 simulaciones sobre 220
configuraciones del espacio completo de parámetros con trades y equity **bit-idénticos**;
`run_backtest` entero legacy vs slab (inline/pool/JIT/fallback) → resultado completo igual.

**Extrapolación a prod** (W-2145 ≈ ×1,8-2 vs M4; coste/par legacy constante con la escala):
el backtest típico de 35k pares pasa de **~2,5-3 min a ~12-25 s**, y desaparece el peaje de
primera ejecución (hoy minutos de GCS US↔EU). **Objetivo "5-10x de la competencia": superado.**

**Honestidad sobre lo no alcanzado:** el gate D6 del PRD ("Mitad B <15% del E2E") quedó en
~47%: tras el JIT, lo que queda es la construcción **contractual** del payload (dicts de
equity/trades) y las métricas por día — reducirlo más exige API v2 columnar (Fase 2).
El gate E2E (≥8x), que es el que ve el usuario, se superó con margen doble.

## 5. Hallazgos que cambian recomendaciones

1. **`BACKTEST_PARALLEL_WORKERS=1` con slab+JIT** (el PRD asumía 6): las señales quedaron
   tan baratas (~55 µs/par) que el spawn del pool cuesta más que el trabajo (medido: 682 ms
   con 6 workers vs 169 ms inline). El knob queda para estrategias multi-timeframe pesadas.
2. **Staleness de slabs**: el bench a escala destapó que un slab construido sobre una fuente
   que luego muta se servía obsoleto → ahora el manifest lleva huella de la fuente y se
   reconstruye solo (`cad5ef7`). Relevante para la migración (mirror local mutable).
3. **La suite de tests tiene deuda pre-existente**: 2 módulos rotos por imports legacy y al
   menos un test que quema CPU sin fin (la pasada inicial estuvo 3h colgada). Mapa por
   fichero en BASELINE §5. Recomendación: `_archive/` para los rotos y `--timeout` en CI.

## 6. Qué falta para encenderlo (nada de código — está en el RUNBOOK)

1. **Golden B en el servidor** con flags OFF→ON (gate de Adrián, RUNBOOK §0).
2. Consenso C1 (import del dispatcher) + revisión del kernel rescatado (es suyo).
3. Réplica inicial en prod (~30-60 GB desde US, de noche) → medir gate C4 (primera ≈ steady).
4. Activación por fases con 1-2 días entre flags (RUNBOOK §1) midiendo con `[TIMING]`.
5. **Migración de datos del CTO**: cuando el histórico viva en el hardware propio con layout
   hive, `BTT_REPLICA_SOURCE=/data/mirror` y los builds pasan de horas (US↔EU) a minutos.
   El diseño ya lo asume; cero código.
6. Decisiones abiertas de negocio/ops (PRD §07.A): bucket a EU y NVMe opcional. El porqué
   del revert de PR #4 quedó ACLARADO (2-jul): lo revirtió Jesús por no ver mejora — coherente
   con que atacaba el 3% del tiempo; no hubo bug.

## 7. Documentos de este trabajo

| Doc | Qué es |
|---|---|
| [`../PERFORMANCE_ANALYSIS_CTO.md`](../PERFORMANCE_ANALYSIS_CTO.md) | el análisis medido (fase por fase, GCS, hardware) |
| [`PRD_EJECUTABLE.md`](PRD_EJECUTABLE.md) | el plan con contratos de datos (lo que se ejecutó) |
| [`BASELINE.md`](BASELINE.md) | números de partida + guion de medición en prod |
| [`INFORME_FINAL.md`](INFORME_FINAL.md) | resultados por gate, tabla antes/después |
| [`RUNBOOK.md`](RUNBOOK.md) | encendido por fases, rollback, troubleshooting |
| este | resumen para dirección/CTO |
