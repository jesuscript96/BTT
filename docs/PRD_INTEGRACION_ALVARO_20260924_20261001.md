# PRD · Integración a `staging` de lo construido en `alvaro-rama-desarrollo` (24-sep → 1-oct-2026)

> **Para:** Jaume / Jaime (deciden qué entra en `staging` y cuándo).
> **De:** Álvaro (redactado por Claude Code, 2026-10-01).
> **Punto de partida:** `staging` ya tiene todo lo de Álvaro hasta el **23-sep**
> (cherry-pick de Sailor: TP por lote, Fase 2 de picos, etiquetas y dos fixes —
> entrada `[INTEGRACIÓN · 2026-09-23 · SAILOR]`). Este documento cubre lo
> posterior.
> **Zona del bot y `market_frame.py`:** ninguno de los commits de abajo los toca
> (verificado commit a commit con `git show --stat`).

## 0. Resumen en una tabla

| # | Qué | Tipo | Flag | Commits (en orden) | Riesgo para lo existente |
|---|---|---|---|---|---|
| F1 | Fix vistas `massive.*` (creación de datasets rota en DuckDB moderno) | fix | — | `cd180fa` | bajo (solo nombres de vista) |
| F2 | Fix stall del WAL de `local_data.duckdb` (CHECKPOINT tras DDL de arranque) | fix | — | `171d789` | bajo (arranque) |
| F3 | Ventanas al-vuelo en la vía materializada del qualifying | fix | — | `75a6c95` | medio: cambia la vía del parquet bygap cuando falta una columna |
| U1 | Filtro 1.6 «Gap -1 · Day Return %» (víspera roja) | universo | — | `f1e401b` | nulo sin la regla |
| U2 | Filtro 3.2 «Gap -1 · Retorno 5 días %» | universo | — | `6c10158` | nulo sin la regla |
| U3 | Opción «si falta el dato: incluir» en reglas Gap -1 | universo | — | `3c97410` | nulo sin la clave `missing` |
| U4 | Filtro 6.1 «Días desde 1er día en lago (≈IPO)» | universo | — | `aa1e814` | nulo sin la regla |
| I1 | Indicador «Gappers activos (+X %)» | indicador | `GAPPERS_ACTIVE_ENABLED` | `18da9d7` → `b29a401` | nulo con flag OFF (bit-idéntico) |
| X1 | Salida programada condicional («a una hora, si condición, acción») | salida | `SCHEDULED_EXITS_ENABLED` | `6785359` → `e2b047f` | nulo con flag OFF / sin clave |
| U5 | Paquete «estrategias nuevas»: Vol $ víspera · Gappers víspera · Mecha sup. víspera | universo | — | `6e20d41` | nulo sin la regla |
| U6 | Filtro «Hora de cruce de gap» (tramo PMH/RTH + % + hora) | universo | — | `64e2000` → `68f3cdb` → `da0c76c` | nulo sin la regla |
| P1 | Franja horaria propia por nivel de pirámide | pirámide | `PYRAMID_LEVEL_WINDOWS_ENABLED` | `96602b6` | nulo con flag OFF / sin clave |

Dependencias: **F3 antes de U1-U6** (los filtros nuevos de Gap -1 rompían el
backtest sobre el parquet bygap viejo sin F3 — hallazgo 16). **I1 antes de U6**
(U6 toca `construir_gappers_activos.py`, que nace en I1). El resto es
independiente.

## 1. Fixes

### F1 · `cd180fa` — vistas `massive.*` con nombre 3-part
- **Problema:** crear un dataset en local daba «Binder Error: infinite
  recursion detected» con DuckDB moderno (hallazgos 11/12/13 del 25-sep).
- **Toca:** `backend/app/database.py`, `backend/app/init_db.py`.
- **Verificación:** creación de datasets otra vez operativa en local.

### F2 · `171d789` — CHECKPOINT tras el DDL de arranque
- **Problema:** WAL de `local_data.duckdb` que se quedaba con DDL sin aplicar y
  rompía el arranque (hallazgos 03/04/17). Causa raíz: `strategies.tags` solo
  vivía en WALs descartados por `taskkill`.
- **Toca:** `backend/app/init_db.py` (CHECKPOINT + saltar DDL idempotente).

### F3 · `75a6c95` — ventanas al-vuelo en la vía materializada
- **Problema:** cualquier filtro Gap -1 añadido después de generar el parquet
  bygap (7-sep) rompía el backtest con «Referenced column lag_* not found»
  (hallazgo 16).
- **Toca:** `data_service.py`, `qualifying_windows.py` (+ test).
- **Ojo:** genérico para cualquier columna futura de `qualifying_windows`.

## 2. Filtros de universo (sin flag: no hacen nada hasta que una regla los usa)

Todos viven en las **tres vías** del qualifying (datasets, qualifying en
caliente, materializada) y en el catálogo único `frontend/src/lib/universoFiltros.ts`.

| # | Columna | Definición | Entrada en MEMORIA_MADRE |
|---|---|---|---|
| U1 | `lag_day_return_pct_1` | day_return_pct de la víspera | `[FEATURE · 2026-09-25 · FILTRO 1.6]` |
| U2 | `lag_ret5d_pct_1` | retorno acumulado 5 sesiones de la víspera | `[FEATURE · 2026-09-27 · FILTRO 3.2]` |
| U3 | clave `missing: "include"` | regla Gap -1 → `(cond OR col IS NULL)` | `[FEATURE · 2026-09-27 · OPCIÓN «SI FALTA EL DATO»]` |
| U4 | `days_since_first_day` | días desde el primer día del ticker en el lago (proxy de IPO) | `[FEATURE · 2026-09-27 · FILTRO 6.1]` |
| U5 | `lag_volusd_1` · `lag_gappers_prev_1` · `lag_wick_sup_1` | vol $ víspera · nº gappers ≥50 % la víspera · mecha superior víspera | `[FEATURE · 2026-09-28 · PAQUETE ESTRATEGIAS NUEVAS]` |
| U6 | `gap_start_min_<pct>` | minuto del PRIMER cruce del máximo sobre +pct % del cierre de ayer | hallazgos 24, 24-bis y 25 (1-oct) |

### U6 en detalle (lo último y lo que más ha cambiado)
- **UI:** una sola entrada «Hora de cruce de gap». Al elegirla aparecen el
  **tramo** (PMH = cruce antes de las 09:30, incluido el after-hours de ayer;
  RTH = cruce 09:30-15:59), el **%** (20-200, de 5 en 5) y la **hora**
  («08:00», «ayer 18:00»). Está en el «Añadir filtro de mercado» del
  constructor de estrategias y en el constructor de datasets; en el Genético
  se oculta (solo tiene casillas numéricas).
- **Reglas que viajan:** la de hora + una regla de tramo
  (`gap_start_min_<pct> <= 1049` para PMH, `> 1049` para RTH). Las dos llevan
  claves extra `cruce` / `cruce_limite` que el backend ignora
  (`_build_where_clause` solo lee metric/operator/value/missing).
- **Datos:** tabla `{CACHE_DIR}/gappers_activos/gap_start.parquet`, generada
  por el script nuevo **`backend/scripts/construir_gap_start.py`** (8 min,
  282.013 ticker-días, 37 niveles). `construir_gappers_activos.py` ya NO la
  escribe (la pisaría con la versión vieja). Sin la tabla, una regla U6 falla
  con error ruidoso (nunca filtra en silencio).
- **Compatibilidad:** los 217.301 cruces de la tabla anterior (9 niveles, solo
  hasta 09:30) son idénticos en la nueva → reglas guardadas siguen igual.
- **Fix incluido:** `parseHoraGapStart` tenía el punto sin escapar en el regex
  numérico: «08:00» devolvía `NaN` y viajaba como `"NaN"` (hallazgo 24).
- **Pendiente conocido (look-ahead RTH):** para cruces PMH basta exigir
  «PM High Gap % ≥ X» en la vela de entrada. Para cruces RTH no existe aún un
  indicador de entrada «máximo del día vs cierre de ayer (%)»; propuesta en el
  hallazgo 24-bis.

## 3. Detrás de flag (apagados por defecto; no-regresión bit-idéntica con el flag OFF)

### I1 · Indicador «Gappers activos (+X %)» — `GAPPERS_ACTIVE_ENABLED`
- Por vela: nº de acciones que YA han cruzado +X % sobre su cierre de ayer
  (causal: solo cruces anteriores a la vela). Bloque «Alternativos».
- Tabla `gappers_activos.parquet` por `construir_gappers_activos.py`.
- No-regresión: 1B 2024-2026, 4.482 trades, hash idéntico con flag OFF.
- Detalle: `[FEATURE · 2026-09-28 · INDICADOR «Gappers activos (+X %)»]`.
- **Para el bot:** el bot en vivo no tiene la tabla; si algún día lo quieres
  allí, es otra pieza (contador en vivo).

### X1 · Salida programada condicional — `SCHEDULED_EXITS_ENABLED`
- «A las HH:MM, si CONDICIÓN, ACCIÓN» (cerrar todo / parcial…), genérica.
- Toca motor: `portfolio_sim.py` (+102), `strategy_engine.py`,
  `backtest_signals.py`, `backtest_service.py`, `sim_dispatch.py`, schema.
  **`portfolio_sim.py` lo usa también el bot (`bot_alerts_engine.py` lo
  referencia): el cambio es aditivo, pero revisadlo antes de integrarlo.** Sin clave `scheduled_exits` en la
  estrategia el camino es el de siempre.
- Detalle: `[FEATURE · 2026-09-28 · SALIDA PROGRAMADA CONDICIONAL]`.

### P1 · Franja horaria por nivel de pirámide — `PYRAMID_LEVEL_WINDOWS_ENABLED`
- `pyramiding.levels[].time_windows`: el nivel usa SU franja EN LUGAR de las
  horas de entrada (no la intersección). Caso de uso: entrar en premercado y
  piramidar solo en RTH (1B «aguantar RTH»). Misma regla estricta que la
  entrada: vela de señal y de relleno dentro.
- Toca: `strategy_engine.py` (+128), `backtest_signals.py`,
  `backtest_service.py`, schema (422 si la franja es inválida), router
  `/api/pyramid-level-windows`, `PyramidingBuilder.tsx`.
- Sin flag o sin clave: nivel compilado bit-idéntico (16 tests). Suite backend
  sin bot 1.434 / 0.
- **Sin entrada propia en MEMORIA_MADRE hasta hoy** (la añade la entrada de
  integración del 1-oct).

## 4. Cómo integrarlo (propuesta; la decisión es vuestra)

1. Cherry-pick en el orden de la tabla del §0 (F1, F2, F3, U1…U6, I1 antes de
   U6, X1, P1). Los commits `docs(...)` intermedios no hacen falta: esta
   memoria y este PRD ya los resumen.
2. `.env` de producción: **no** hace falta ningún flag nuevo para F/U. I1, X1 y
   P1 quedan apagados salvo que los encendáis.
3. Tras la integración, generar las tablas en la máquina que sirva backtests:
   `python backend/scripts/construir_gap_start.py` (U6) y, si encendéis I1,
   `python backend/scripts/construir_gappers_activos.py`. Ambas se regeneran
   tras cada actualización del lago.
4. Comprobación mínima: `pytest backend/tests/test_gap_start_filtro.py
   test_gappers_active.py` + la suite habitual; `npx tsc --noEmit`.

## 5. Solo documentación (estudios), para contexto — no requieren integración

- Bloques 1-9 de la investigación de criterios de universo
  (`docs/INVESTIGACION_CRITERIOS_UNIVERSO.md` + `docs/INFORME_BLOQUE*.md`).
- «Aguantar RTH 1B» (`INFORME_AGUANTAR_RTH_1B_20260928.md`), «Entrar solo en
  la pirámide» (`INFORME_ENTRAR_EN_PIRAMIDE_20260929.md`), Bloque 9 overhead
  (`INFORME_BLOQUE9_OVERHEAD_20260929.md`).
- Estudio «Fogonazos vs stop de la 1B» (`PRD_ESTUDIO_FOGONAZOS_STOP_1B_20260930.md`
  + entrada `[ESTUDIO · 2026-10-01 · FOGONAZOS VS STOP 1B]`).

## 6. Hallazgos abiertos de este periodo que conviene que conozcáis

- **18 (metodológico):** criterios de universo con datos del día D que se
  completan después de la entrada tienen look-ahead. Aplica a U6 en tramo RTH.
- **23:** añadir una `entry_time_windows` redundante cambia el resultado.
- **14 / 21:** un backtest sobre un `dataset_id` inexistente «sale bien» con 0
  días en vez de 404.
- **15:** `date_to` exclusivo en la vía de datasets e inclusivo en qualifying.
- **[PARA JAUME · 2026-09-27]:** datos del 6.1 en la 2B que chocan con la regla
  R-A-03 del libro («IPO < 30 d fuera en RTH»).
