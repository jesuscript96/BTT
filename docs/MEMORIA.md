# MEMORIA — Álvaro × Claude (edgecute_app / BTT)

> Documento vivo. Se actualiza **cada sesión** en la que tocamos algo. Entradas
> por fecha, **lo más nuevo arriba**. Sirve para retomar con contexto: qué
> hicimos, por qué, qué decidimos y dónde lo dejamos.

---

## Estado actual del proyecto

- **Repo:** `edgecute_app` (monorepo BTT, GitHub `jesuscript96/BTT`).
- **Rama de trabajo de Álvaro:** `alvaro-rama-desarrollo` → integra a `staging`.
  Sailor: `sailor-rama-desarrollo`. **`main` NO se toca jamás** (producción con
  clientes de pago). Push solo con confirmación explícita de Álvaro.
- **Entorno local:** `DB_PROVIDER=local`, `DISABLE_GCS_SYNC=true`,
  `LIVE_SCREENER_ENABLED=false` (obligatorias; aíslan de producción).
- **Datos:** `daily_metrics` = **tabla** en `backend/local_data.duckdb` (~61 GB),
  **19.177.136 filas, 2019-01-02 → 2026-08-14**. Lago Parquet aparte en
  `.../TRADING APPs/cangrejo_data/datos/parquet/edgecute/`.
- **Nunca commitear** secretos ni datos: `.env`, `gcs-key.json`, `*.duckdb`,
  `data/`, `.cache/`. Ya en `.gitignore`.

## Reglas de trabajo entre Álvaro y Claude

- **No profundizar de más.** Si algo funciona en local y no aporta, se cierra.
- **No llenar `staging` de mierda.** Lo que funciona en local en
  `alvaro-rama-desarrollo` se queda ahí salvo decisión explícita de subir.
- Sailor también puede subir a `staging`; no somos los únicos.
- Esta memoria se actualiza al final de cada sesión con cambios.

---

## 2026-08-21 (tarde 2) — Rama handoff a producción con PRDs para Edgecute

**Qué hicimos**
- Álvaro pidió rama para entregar al developer de Edgecute (vía develop→main,
  ese salto es de Adrian) las dos mejoras apremiantes: fees por ejecución y
  calendario/retorno real. Creada **`alvaro/handoff-produccion`** (commit
  `7f65d83`) **basada en `origin/develop` @ `e368839`**, por worktree temporal
  (el working tree de esta rama no se tocó). Es un **canal permanente**: sin
  fecha en el nombre; cada tanda de mejoras va en una carpeta fechada dentro.
- **Solo documentación**: `docs/handoff-produccion/` con README índice vivo +
  tanda `2026-08-21-fees-y-calendario/` (PRD_01 fees, PRD_02 calendario,
  `reference/` con parches + `test_fees.py` copiable tal cual).
  Todas las anclas `fichero:línea` verificadas contra develop@e368839.

**Hechos verificados (importan para el futuro)**
- Cherry-pick de `77236d2` (fees) sobre develop **NO aplica limpio**:
  conflictúa en `portfolio_sim.py` (construido sobre trailing+locates+
  parciales fade de mi rama). Con `59a869d`+`77236d2` el trailing sí aplica,
  fees sigue conflictuando. → Handoff por PRD, no por código. `test_fees.py`
  sí es copiable (archivo nuevo, sin dependencias de features mías).
- `origin/alvaro-rama-desarrollo` == local (0 commits sin push): la nota
  "sin push" de las entradas anteriores quedó desactualizada.
- Clasificación del working tree sin commitear: **paquete calendario/retorno
  (6 ficheros: CalendarTab, PerformanceTab, EquityCurveTab, ChartsTab,
  MetricsCard, page.tsx)** = el fix que el usuario quiere en producción;
  `sl_dist_pct_*` (api_backtester, tradesCsv, MetricsCard, backend) y
  `activation_pct` (strategy.ts) = features aparte, fuera del handoff.
  El parche de referencia del calendario se generó de este diff.

**Decisiones**
- Handoff **docs-only**: nada de mi montaje local (bygap, migración GCS/lago,
  MEMORIA/PROXIMOS) puede colarse. README lista explícitamente lo excluido +
  candidatos futuros (fix locates `2a51b94..de14125`, OOS DD$ `5741202`).
- El fix del calendario sigue **sin commitear** en esta rama (trabajo de la
  sesión paralela); el PRD es autocontenido y el parche documenta el
  comportamiento exacto. Pendiente: validarlo (tsc + visual) y commitearlo
  aquí con su propio commit.

**Continuación (misma tarde)**
- Álvaro pidió mensaje + PRD de orientación para Adri (que sepa qué subir a
  main sin liarse). Añadido **`PRD_00_PLAN_DE_SUBIDA_A_MAIN.md`** a la tanda
  (commit `9f7e22c`, en la rama handoff): resumen simple, 2 PRs pedidos,
  orden recomendado (PRD_02 primero), checklist de verificación antes de
  main (incluye smoke de identidad con fees=0), guarda-raíles (no mergear
  mis ramas, no git apply, quirks intactos) y nota de release sugerida.
  README del handoff actualizado con su fila. Mensaje corto para Adri
  entregado en la conversación (no en el repo).

**Dónde lo dejamos**
- `alvaro/handoff-produccion`: tanda 1 (`7f65d83`) **pusheada**; PRD_00
  (`9f7e22c`) **sin push** (pendiente OK de Álvaro).
- `alvaro-rama-desarrollo`: este commit de MEMORIA **sin push**.
- Working tree de `alvaro-rama-desarrollo` intacto (solo se commiteó
  MEMORIA.md).

---

## 2026-08-21 — Ejecutados ITEM 3 e ITEM 1 (PROXIMOS_ITEMS); spec ITEM 2 corregida

**Contexto**
- Auditoría del backtester del 2026-08-21 → `docs/PROXIMOS_ITEMS.md` con 3 items.
- Revisión Claude (Opus) con notas 🔎 A/B/C sobre la spec de ITEM 2. Esta sesión:
  verificar esas notas contra el código, ejecutar ITEM 3 e ITEM 1 (aprobados por
  Álvaro, en ese orden), corregir la spec de ITEM 2. **ITEM 2 NO ejecutado.**

**Verificación de las notas A/B/C (todas correctas)**
- **A**: `BacktestPanel.tsx:688` ya divide `fees/100` antes de enviar → al motor
  llega como fracción; el `/100` de la fórmula PERCENT de la spec habría cobrado
  100× de menos.
- **B**: parciales sin clave `fees` a propósito (`sim_dispatch.py:348-351`,
  comentario "quirk contractual"); el total (`backtest_service.py:1033`) los
  excluye. Tocarlo rompería `test_sim_jit_equivalence`.
- **C**: label actual es `Fees ($)` (`BacktestPanel.tsx:1384`); con el cambio
  $/trade → $/share el relabel es obligatorio.
- Anclas de ITEM 1 (7/7) e ITEM 3 verificadas. Ningún test referenciaba
  `trail_activation` (hueco real de cobertura).

**ITEM 3 — MAX DD $ del tab OOS (commit `5741202`)**
- `OOSDegradationTab.tsx`: la serie (`:371`) y el header (`:556`) convertían
  `dd$ = (dd%/100) × initCash`, que subestima el DD cuando el pico supera el
  capital inicial. Arreglado copiando el patrón de `EquityCurveTab.tsx:177-193`:
  memo `ddDollarByTime` (value − running peak sobre `fullGlobalEquity`) para
  serie y header, con fallback a la fórmula vieja si no hay punto. Solo
  presentación; `tsc --noEmit` limpio.

**ITEM 1 — Trailing Break-Even desacoplado (commit `59a869d`)**
- La feature vivía sin commitear en la working tree. Validada contra cálculo
  manual, testeada, documentada y commiteada (solo sus 9 ficheros):
  `strategy_engine.py` (parsing ×2 paths), `portfolio_sim.py`, `portfolio_sim_jit.py`
  (puerto línea a línea, mismo orden FP), `sim_dispatch.py`, `schemas/strategy.py`
  (`activation_pct: None` explícito en el default), `RiskManagement.tsx`,
  `BACKTESTER_BRAIN.md` §4 + checklist.
- Tests nuevos: `backend/tests/test_trail_break_even.py` (T1 BE long, T2
  no-activación → SL, T3 activación+distancia, T4 espejo short, T5 regresión
  bit-identica del trailing clásico via `trail_activation=None` vs
  `=trail_pct`) y `test_sim_jit_equivalence.py::test_trail_activation_equivalence`
  (T6 paridad JIT con BE y mixto). **19/19 verdes** (suite ITEM 1 + fade
  partials). Numba 0.66.0 real, kernel cacheado.
- Nota semántica: `buffer_pct=0` antes era falsy → trailing inerte; ahora
  admite 0.0 → "BE inmediato" (caso documentado en BRAIN §4).

**ITEM 2 — Fix fees: spec corregida, PENDIENTE de orden**
- `docs/PROXIMOS_ITEMS.md` §ITEM 2 reescrito con A/B/C aplicadas: fórmula
  PERCENT sin `/100` (fees llega como fracción), tabla de fórmulas por bloque
  (el fee de ENTRADA cae en el cierre final: `original_size`; parciales solo su
  salida), decisión explícita de **mantener el quirk** de parciales sin `fees`,
  y relabel "$/share" marcado obligatorio.
- **Esperando visto bueno de Álvaro a la spec antes de tocar el motor.**

**Dónde lo dejamos**
- Commits en `alvaro-rama-desarrollo`, **sin push** (pendiente confirmación).
- Working tree: siguen los cambios WIP de Álvaro (migración GCS, renames
  `backend/scripts → backend/_archive/scripts_gcs_2026-08` staged, etc.).
- `test_strategy_api.py::test_create_and_get_strategy` falla 422 de forma
  **preexistente** (verificado con stash, sin relación con estos cambios). No
  estaba en la lista de tests rotos conocidos del Backlog.

---

## 2026-08-21 (tarde) — Ejecutado ITEM 2: fees por ejecución (fill)

**Qué hicimos**
- Álvaro dio el visto bueno a la spec corregida (A/B/C) y ordenó ejecutar.
- Nuevo modelo de comisiones **por fill** en `portfolio_sim.py` (helper
  `_fee_amount`, 6 puntos) y kernel JIT (`_fee_amount_jit`, puerto con mismo
  orden FP): FLAT = $/acción y lado (`fees × qty`); PERCENT = fracción del
  nocional (`notional × fees`, SIN `/100`: el frontend ya divide). El cierre
  final paga la entrada de TODO el tamaño (`original_size`) + la salida del
  restante; cada parcial paga solo su salida. Quirk B intacto: parciales sin
  clave `fees`, totales sin su fee, locates intactos.
- UI: labels `Fees (% notional)` / `Fees ($/share)` en `BacktestPanel.tsx`
  (relabel obligatorio por el cambio de significado de FLAT). BRAIN §5
  actualizado con el modelo por-fill.

**Verificación**
- `backend/tests/test_fees.py` nuevo (6 tests): FLAT/PERCENT full, trade plano
  paga fee (mata el bug `abs(pnl)`), parciales FLAT/PERCENT + quirk sin
  `fees`, paridad JIT. Escrito primero y visto en rojo (5 fallos con el motor
  viejo), verde tras el cambio.
- Paridad: `test_sim_jit_equivalence.py` (grid 220 configs con fees 0.01/2.5
  ambos tipos) + fade partials + trail + locates: **28/28**.
- Suite completa con diff contra stash: **0 fallos nuevos**; los ~119 fallos
  preexistentes son de entorno/datos (GCS 403, bygap Parquet local, DB).
- Humo (34 trades, 1.416 acciones, random walk sembrado): FLAT $0.01/share →
  fee total $28.32 = exacto a $0.02 × 1.416; PERCENT 0.01% → $13.59 ≈
  0.0002 × nocional; paridad JIT exacta en los 3 escenarios.

**Impacto (avisado en spec y commit)**
- PERCENT: cambia la fórmula, no la magnitud con el default 0.01%.
- FLAT: cambio de SIGNIFICADO ($/trade → $/share) — backtests guardados con
  FLAT>0 dan números muy distintos; el relabel de UI lo hace explícito.

**Dónde lo dejamos**
- Commits del día: `5741202` (ITEM 3), `59a869d` (ITEM 1), `75f4bee` (docs),
  + commit de ITEM 2 (fees). Todo en `alvaro-rama-desarrollo`, **sin push**.
- `PROXIMOS_ITEMS.md` queda solo con el Backlog congelado: los 3 items de la
  auditoría están ejecutados y registrados aquí.

---

## 2026-08-20 (tarde) — Diagnóstico inconsistencias de P&L + PRD fix de locates

**Qué hicimos**
- Diagnóstico de por qué los números del backtester **no cuadran entre paneles**
  (Álvaro veía cifras contradictorias en varias estrategias). Solo diagnóstico +
  un PRD: **no se tocó código esta sesión**.
- Revisión concreta del **cálculo de locates** (sospecha de Álvaro).

**Hallazgos (anclados en código)**
- **PnL% del grid mensual COMPONE los retornos diarios** (`PerformanceTab.tsx:148`,
  `∏(1+r/100)−1`) mientras el RETURN del backend es simple `Σpnl/init_cash`
  (`backtest_service.py:1336`). Por eso YTD salía +3133% con RETURN +27.67%. Bug real.
- **Capital por defecto $10.000 hardcodeado** en 4 sitios (`BacktestPanel.tsx:417`,
  `page.tsx:259/465/470/506`). Las métricas en $ del header de la curva usan
  `initCashRef.current` (`EquityCurveTab.tsx:663/682`), que se desincroniza del
  `init_cash` real → firma del $10k en `MAX DD` (−4941/−49.41%) con capital 2.500.
- **3–4 pipelines de P&L en paralelo sin fuente única**: backend agregado
  (`Σpnl/init_cash`), curva backend (`init_cash+cumsum`), calendario (suma cruda
  de `t.pnl`, `CalendarTab.tsx:68-75`), PnL% compuesto, y `page.tsx:1087` recalcula
  el return por su cuenta. Cada uno da un número distinto.
- **Calendario "verde pero plano"**: en modo neto no resta los `$150/mes` (solo en
  modo "gastos", `CalendarTab.tsx:87-89`); el neto real es `total_pnl−total_expenses`
  (`backtest_service.py:1327`).
- **Locates — el total es correcto, el reparto está mal**:
  - Todo el locate del día se imputa al **primer short** (`break`) en
    `portfolio_sim.py:878-882` y **duplicado verbatim** en `sim_dispatch.py:372-395`
    (path JIT). → falsea R por trade y win rate.
  - Se resta de **toda la curva de equity** desde la barra 0 (`equity[i]` para todo
    `i`), incluidas barras premarket sin posición → infla el DD intradía.
  - Evidencia (misma "Definitiva 2.3", 867 trades): locate 0 → 3 pasa RETURN de
    **+9876.73% a −71.73%** y **WIN RATE de 64.1% a 56.2%** (huella del mal reparto).

**Decisiones**
- Modelo de locate **"una sola compra por ticker-día"** confirmado por Álvaro:
  **no** se cobra por reentrada (el `max_short_size_today` + una imputación es
  correcto y se preserva).
- **Reparto FIJADO: proporcional al `size` de cada short**, preservando el total
  exacto (elimina la distorsión de win rate con reentradas).

**Entregable**
- **`docs/fix-locates-attribution/PRD.md`** — PRD ejecutable condensado (formato
  casa, anclado a `fichero:línea`, plan atómico T1–T5, DoD, ejemplo numérico).
  **Pensado para que lo ejecute GLM** en `alvaro-rama-desarrollo`. El fix va en los
  **dos** paths (`portfolio_sim.py` + `sim_dispatch.py`) y debe dejar verde
  `test_locates.py`, `test_locates_flat_semantics.py` y `test_sim_jit_equivalence.py`.

**Abierto (deferred)**
1. **El bug PnL%/initCash NO tiene PRD todavía** — solo diagnóstico. Decidir si se
   unifica todo a una sola curva de equity (fuente única de verdad) y quién lo hace.
2. **Trabajo en paralelo sobre los MISMOS ficheros**: `PerformanceTab.tsx`,
   `EquityCurveTab.tsx`, `page.tsx`, `CalendarTab.tsx` se editaron a las 19:54–19:57
   (otro agente/sesión). Cuidado con pisar al tocar el fix del P&L.

---

## 2026-08-20 — Vía rápida de qualifying (bygap ordenado por gap)

**Qué hicimos**
- Adoptada la optimización de Sailor: leer las 32 columnas de ventana (LAG/LEAD)
  del qualifying de un Parquet materializado y **ordenado por `pmh_gap_pct DESC`**,
  en vez de recalcularlas sobre 19,2 M filas en cada backtest.
- Revalidado que `edgecute_app` = mismo montaje que Sailor (fuente **DuckDB**,
  `main.daily_metrics`), no la vía Parquet (eso fue un despiste del repo `edgecute_lab`,
  que era una prueba desechable y **se borró**).
- Generado el bygap con `opt_por_gap.py` desde `main.daily_metrics` (misma fuente
  que la app → paridad por construcción): **3,51 GB, 173 s**, 19.177.136 filas.
- Implementado + **merge de `origin/staging`** (trae `fbf8757` de Sailor) resuelto
  en **`23bd2e1`**: estructura de Sailor (`_remap_trading_day` extraída, `return`
  temprano, TTL por `QUALIFYING_CACHE_TTL`) + **guardián de frescura** (footer
  `parquet_metadata` + memo, CAST en SQL) + **`QUALIFYING_WINDOWED_STRICT`** con
  centinela `_BygapStaleStrictError` + **remap unificado** (vía lenta llama a la
  función, sin inline duplicado).

**Resultado medido**
- Baseline (vía lenta): 14,7 s (2020→hoy), 17,0 s (2022-2023).
- Vía rápida: **0,18 s** (~80-90×). Guardián: 0,25 s fresco; desfasado → degrada
  con resultados idénticos; desfasado + STRICT → error propagado (no cae al hot-cache).
- **Paridad 7/7, 0 diferencias, `rtol=1e-9`** sin aflojar, incluidos `gap_1_day`,
  `gap_2_day` y borde derecho. `py_compile` OK.

**Decisiones**
- **NO push a `staging`.** `fbf8757` ya está en `staging` (lo subió Sailor); nuestros
  extras (guardián, STRICT, test) se quedan en `alvaro-rama-desarrollo`. Env-gated y
  **apagado por defecto** → cero impacto en producción / resto del equipo.
- No perseguir convergencia total de código con Sailor. Él mantiene su versión.

**Config local añadida a `backend/.env`** (ignorado por git)
- `QUALIFYING_WINDOWED_PARQUET=.../cold_storage/daily_metrics_bygap/*.parquet` (glob, no fichero)
- `QUALIFYING_WINDOWED_STRICT` (default false), `QUALIFYING_CACHE_TTL=604800`,
  `MIN_AVAILABLE_DATE=2019-01-01`, `DUCKDB_MEMORY_LIMIT=3GB`,
  `INTRADAY_PREWARM_ENABLED=false`, `BACKTEST_MIN_AVAIL_GB=1.0`.

**Dónde lo dejamos**
- `23bd2e1` commiteado en `alvaro-rama-desarrollo`, **sin push**. Funciona en local.
  **Tema cerrado.**

**Abierto (deferred — no bloquea, no actuar salvo decisión)**
1. **Dos copias inline más del remap** sin unificar: hot-cache (~1060) y fallback
   GCS (~1131). Si se unifican algún día, acordar con Sailor al subir a `staging`.
2. **`except` ancho del branch local** (`data_service.py` ~975): cualquier excepción
   de la vía local cae al hot-cache, que filtra por `gap_pct` (no `pmh_gap_pct`) →
   "no falla, contesta otra cosa" (por eso 53 vs 65 filas). El centinela cubre STRICT;
   el caso general (`has_custom_rules`) queda como posible follow-up con dueño.
3. **Concurrencia** del `read_parquet` sobre el bygap (varios backtests a la vez)
   no probada. Irrelevante en local de 1 usuario.
4. Script de Sailor `opt_qualifying_incremental.py` tiene bug de orden (borra los
   parquet antes de renombrar el compactado). No lo usamos aún; si se adopta,
   renombrar primero y borrar después.
5. **Inyección SQL preexistente** en `_build_where_clause` (interpola filtros de
   usuario sin parametrizar). No la introduce este cambio; deuda aparte.

**Ficheros de referencia (Downloads)**
- PRDs de Sailor: `PRD_CONSTRUCCION_Y_OPTIMIZACION.md`, `PRD_RESPUESTAS_QUALIFYING.md`,
  `PRD_COORDINACION_QUALIFYING.md`, `PRD_REVISION_RECONCILIACION.md`.
- Nuestros: `PRD_ADOPCION_QUALIFYING_BYGAP_ALVARO.md`, `RECONCILIACION_QUALIFYING_STAGING.md`,
  `opt_por_gap.py`.
- En el repo: `backend/tests/test_bygap_parity.py`.
