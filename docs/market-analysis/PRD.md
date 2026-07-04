# PRD ejecutable — Market Analysis (condensado)

> **Estado:** PLAN — listo para handoff al loop.
> **Origen:** PRD de producto `Edgecute_PRD_MarketAnalysis_v1` (Álvaro · Jesús · Jaime), reescrito
> como paquete ejecutable anclado en el código real, siguiendo `docs/manual-prd/GUIA_PRD_EJECUTABLE.md` (§4.9, suite condensado).
> **Owner ejecución:** Jesús (rama `marketAnalysis`).
> **Hallazgo clave:** **no es greenfield.** El ~70% de la matemática ya está escrita y *comentada*
> (`HIDDEN FOR MVP`) en `routers/market.py`, con `query_service.py` vivo y casi todas las columnas
> precalculadas en `daily_metrics`. Esto es *des-ocultar + extender*, no construir de cero.

---

## 1 · Qué y por qué (+ alcance)

**Qué.** Sección de inteligencia de mercado para el short-seller discrecional de small-caps: lectura
rápida del comportamiento de los gappers del día (qué tipo sale, cómo se comporta, cuándo hace el HOD,
cuánto cae desde el high), filtrable por sus criterios. Referente: Flash Research.

**Por qué.** Hoy existe un prototipo huérfano en el home (`MarketIntelligenceCharts`) alimentado por
endpoints **apagados**, y la entrada de sidebar "Market Analysis" apunta en realidad a `/market-sentiment`
(Stocktwits, otra cosa). El PRD formaliza una página propia con las 7 KPIs + módulos especificados.

### Alcance MVP v1.0 (se construye AHORA)
Los 5 módulos cuya matemática ya está anclada en `daily_metrics`/`query_service`:

- **MA-01 · 6 KPIs** (los 7 menos Close<VWAP, que se va a Fase 2 por depender de `day_vwap`).
  Incluye 1 cálculo nuevo pequeño: Fade-a-EOD (`pmh_fade_to_close_pct`).
- **MA-02 · Time Distribution** (HOD / LOD / PM High por franja 30 min).
- **MA-04 · Avg Change from Open** (12 mini-gráficos mensuales).
- **MA-05 · MAE / MFE Distribution** (toggle PM/RTH).
- **MA-06 · Recent Gaps Up** (tabla).
- **Filtros base:** periodo (5 presets + rango libre), Gap %, Open price, Volumen RTH, Volumen PM,
  HOD fade %, Close Red, HOD time, Avg Fade umbral, PM Volume, PM High Gap %, Open vs PM High.
- **Página dedicada** `/market-analysis`, **admin-only** (`market.analysis.access`).
- **Click en ticker** → reusar el componente del Screener (`Screener.tsx`), sin modificarlo.

### Fase 2 (NO se construye ahora; el MVP no le cierra la puerta)
- **MA-03 · Hot Sectors** y **filtros Universo (País / Sector / Float).** Único lift de datos real:
  requiere una **tabla de enriquecimiento `ticker → sector / país / float`** (Polygon → Finviz →
  Dilution Tracker → Yahoo) que hoy **no existe** (`daily_metrics` no tiene esos campos).
  - *Decisión que impone al MVP:* el contrato del endpoint y los filtros se diseñan **extensibles**
    (parámetros `country[]`, `sector[]`, `float_min/max` ya reservados en el modelo de request, ignorados
    si no hay enriquecimiento) para no romper el contrato al añadirlos. Nada más.
- **KPI-05 Close<VWAP % + filtro `close_lt_vwap`.** Dependen de precalcular `day_vwap` en
  `daily_metrics` (toca zona de datos → consensuar con Adrián). **Diferido a Fase 2 por decisión de Jesús**
  (28-jun-2026): el MVP sale sin él. *Decisión que impone al MVP:* la clave `close_lt_vwap_pct` queda
  reservada en el contrato del response (puede venir `null`) y el toggle de filtro `close_lt_vwap` reservado.
- **v1.2 del PRD producto:** Resumen AI de Hot Sectors, Last Gaps, Period Comparison, PMH Break % como KPI.
  Reservar placeholder visual donde aplique.

### Fuera de alcance (que la IA NO lo invente)
- Day 2 / Day 3 / Previous Day como filtros · treemap Gaps by Sector · market cap / shares outstanding ·
  datos del journal del usuario. Market Analysis muestra **solo datos de mercado**.

---

## 2 · Fuentes auditadas (anclaje en código — verdad)

| Pieza real | Fichero:línea | Qué aporta |
|---|---|---|
| Endpoint `/screener` (records + stats avg/p25/p50/p75) **OCULTO** | `backend/app/routers/market.py:27-191` | base de KPIs y Recent Gaps; reactivar |
| Endpoint `/aggregate/intraday` (curva avg change from open) **OCULTO** | `backend/app/routers/market.py:277-437` | base de Avg Change from Open; reactivar |
| Query service vivo | `backend/app/services/query_service.py` | `build_screener_query`, `get_stats_sql_logic`, `map_stats_row`, `build_aggregate_query` |
| Columnas precalculadas por día | `backend/app/services/processor_service.py:6-174` | ver §3 (catálogo) |
| Hot cache en RAM (`min_gap>=5` desde RAM) | `backend/app/services/cache_service.py` (`get_hot_daily_df`) | filtrado rápido <100ms |
| `intraday_1m` incluye `vwap` por minuto | `backend/app/ingestion.py:295,303` | habilita Close<VWAP y `day_vwap` |
| Prototipo frontend (a sustituir por página spec) | `frontend/src/components/MarketIntelligenceCharts.tsx` | referencia visual / recharts |
| Fetch centralizado | `frontend/src/lib/api.ts:463-476` | `getScreener`, `getAggregateIntraday` |
| Componente click-ticker (reuso) | `frontend/src/components/Screener.tsx` | tarjeta del ticker |
| Entitlements (patrón admin-only) | `backend/app/entitlements/policy.py:34,51-64` | `market.sentiment.access` → replicar `market.analysis.access` |
| Nav | `frontend/src/components/Sidebar.tsx:170-195` | añadir item `/market-analysis` |

**Columnas YA precalculadas en `daily_metrics`** (de `processor_service.py`): `ticker`, `timestamp`(fecha),
`open`, `close`, `high`, `low`, `volume`, `pm_volume`, `pm_high`, `pm_low`, **`pm_high_time`**, `pm_low_time`,
`gap_pct`, `pmh_gap_pct`, `pmh_fade_pct`, `rth_volume`, `rth_open`, `rth_high`, `rth_low`, `rth_close`,
**`hod_time`**, **`lod_time`**, `rth_run_pct`, `rth_fade_pct`, `rth_range_pct`, `m15/m30/m60/m180_return_pct`,
`close_1559`, `last_close`, `day_return_pct`, `prev_close`.

> ⚠️ `hod_time/lod_time/pm_high_time` **existen por fila** pero `get_stats_sql_logic` los emite como `'--'`
> y `distributions` viene `{}` (mock). MA-02 = **agregación nueva sobre dato existente**, no dato nuevo.

---

## 3 · Glosario / nomenclatura (usar SIEMPRE el nombre del código)

| Término PRD | Nombre oficial (código) | Definición operativa | Estado |
|---|---|---|---|
| Gap % | `gap_pct` | `(rth_open − prev_close) / prev_close × 100` | existe |
| PM High | `pm_high` | `max(high)` velas PM 04:00–09:29 | existe |
| PM High gap % | `pmh_gap_pct` | `(pm_high − prev_close) / prev_close × 100` | existe |
| Open price | `rth_open` | open primera vela RTH (**09:30 estricto**, Q1) | existe |
| HOD / LOD | `rth_high` / `rth_low` | max/min RTH 09:30–16:00 | existe |
| HOD time / LOD time / PMH time | `hod_time` / `lod_time` / `pm_high_time` | timestamp `"HH:MM"` del extremo | existe (sin agregar) |
| Close EOD | `close_1559` | close de la vela 15:59 (fallback `rth_close`) | existe |
| Close Red | `close_red` | `day_return_pct < 0` (≡ `rth_close < rth_open`) | derivado |
| **Day VWAP** | **`day_vwap`** (NUEVO) | `Σ(close×vol)/Σ(vol)` velas RTH | **Fase 2** |
| Close < VWAP | `close_lt_vwap` (NUEVO) | `rth_close < day_vwap` | **Fase 2** |
| **Fade desde PMH (a EOD)** | **`pmh_fade_to_close_pct`** (NUEVO) | `(pm_high − close_1559) / pm_high × 100` | **nuevo** (≠ `pmh_fade_pct`, que es a *open*) |
| HOD fade % | `hod_fade_pct` | `(rth_high − close_1559) / rth_high × 100` | nuevo (filtro) |
| MAE/MFE (RTH) | — | ref `rth_open`; ver §5 | derivado |
| MAE/MFE (PM) | — | ref `prev_close`; ver §5 | derivado |
| País / Sector / Float | `country` / `sector` / `float_shares` | enriquecimiento externo | **Fase 2** |

> **Trampa a evitar:** `pmh_fade_pct` (ya existente) es fade **al open**; el PRD KPI-06/07 pide fade **al
> cierre EOD**. Son métricas distintas → crear `pmh_fade_to_close_pct`, no reutilizar `pmh_fade_pct`.

---

## 4 · Contrato de datos

Toda llamada pasa por `frontend/src/lib/api.ts` (regla `CODING_RULES.md`). Routers finos, lógica en
`services/`. Queries parametrizadas (`?`). **No** tocar `daily_metrics`/`intraday_1m`/Parquet salvo añadir
`day_vwap` (consensuar con Adrián: es columna aditiva, no rompe schema histórico).

### 4.1 `GET /api/market/screener` (reactivar + endurecer)
Params (query): `min_gap`, `max_gap`, `min_open`/`max_open`, `min_volume`/`max_volume`, `min_pm_volume`/`max_pm_volume`,
`min_pmh_gap`/`max_pmh_gap`, `min_open_vs_pmh`/`max_open_vs_pmh`, `min_hod_fade`/`max_hod_fade`,
`close_red` (`yes|no|all`), `close_lt_vwap` (`yes|no|all`), `hod_time[]` (`pre10|10_11|post11`),
`fade_threshold` (default 50), `start_date`, `end_date`, `period` (`1w|1m|3m|6m|1y`), `ticker`, `limit`.
*(Reservados Fase 2: `country[]`, `sector[]`, `float_min`, `float_max`.)*

Response:
```jsonc
{
  "records": [{                      // MA-06 Recent Gaps Up
    "ticker": "ABCD", "date": "2026-06-12",
    "gap_at_open_pct": 30.0, "open": 13.0,
    "vol_rth": 8200000, "vol_pm": 1500000,
    "hod": 14.2, "pmh": 18.0, "close_red": true
  }],
  "kpis": {                          // MA-01 (valor periodo + delta vs periodo anterior)
    "gappers_count":        {"value": 142, "prev": 120},
    "avg_gap_pct":          {"value": 41.3, "prev": 38.0},
    "pm_high_average":      {"value": 5.42, "prev": 5.10},
    "close_red_pct":        {"value": 63.2, "prev": 60.1},
    "close_lt_vwap_pct":    {"value": 58.0, "prev": 55.4},
    "avg_fade_from_pmh":    {"value": 22.7, "prev": 21.0},
    "max_fade_from_pmh":    {"value": 71.4, "ticker": "WXYZ", "date": "2026-06-03"}
  },
  "distributions": {                 // MA-02 (% por franja 30 min)
    "hod_time": {"09:30-10:00": 38.9, "10:00-10:30": 14.1, "...": 0},
    "lod_time": {"...": 0},
    "pmh_time": {"...": 0}
  },
  "mae_mfe": {                       // MA-05 (histograma + percentiles), por modo
    "rth": {"mae": {"buckets": {"0-5":..}, "p25":..,"p50":..,"p75":..,"mean":12.4},
            "mfe": {"...": 0}},
    "pm":  {"...": 0}
  },
  "source": "hot_cache | gcs"
}
```

### 4.2 `GET /api/market/aggregate/intraday` (reactivar + extender a 12 meses)
Devuelve, para cada uno de los **últimos 12 meses naturales** (independiente del selector global), la curva
media `change_from_open` por franja 30 min de **04:00 a 16:00** + la línea `avg_gap_pct` del mes:
```jsonc
[{ "month": "2026-06", "label": "Jun",
   "avg_gap_pct": 39.8,
   "points": [{"time":"04:00","avg_change":-1.2},{"time":"09:30","avg_change":0.0}, ...] }]
```

### 4.3 Estados de UI (4 obligatorios)
- **Loading:** skeleton de KPIs + spinner cobre (patrón del prototipo).
- **Empty:** "Sin gappers para estos filtros" + CTA "Limpiar filtros".
- **Error:** mensaje accionable + reintento (toda llamada por `lib/api.ts`).
- **Success:** la página completa.

---

## 5 · Reglas de trading (5 elementos) + ejemplos numéricos

Cada regla: **nombre · fórmula · unidad · sesión · edge case.** Ejemplo base para todas:
`prev_close=10.00`, `rth_open=13.00`, `pm_high=18.00`, `rth_high=14.00`, `rth_low=8.50`, `pm_low=11.50`,
`close_1559=9.00`, `day_vwap=10.20`.

| # | Métrica | Fórmula | Unidad / sesión | Edge case | Ejemplo |
|---|---|---|---|---|---|
| K1 | `gappers_count` | count gappers con `gap_pct ≥ filtro_gap` (default 30) | conteo / día | `prev_close=0`→excluir | gap=30 ⇒ cuenta |
| K2 | `avg_gap_pct` | `mean(gap_pct)` | % | sin gappers→null | — |
| K3 | `pm_high_average` | `mean(pm_high)` | USD / PM 04:00–09:29 | sin PM→excluir | — |
| K4 | `close_red_pct` | `count(day_return_pct<0)/N×100` | % / RTH | `rth_open=0`→excluir | day_ret=(9−13)/13=−30.8%→red |
| K5 | `close_lt_vwap_pct` — **FASE 2** | `count(rth_close<day_vwap)/N×100`; `day_vwap=Σ(close×vol)/Σ(vol)` RTH | % / RTH | `Σvol=0`→excluir | 9.00<10.20→red bajo VWAP |
| K6 | `avg_fade_from_pmh` | univ. `gap_pct≥fade_threshold` (def 50); `mean((pm_high−close_1559)/pm_high×100)` | % | `pm_high=0`→excluir | (18−9)/18=**50%** |
| K7 | `max_fade_from_pmh` | `max(...)` mismo universo; expone `ticker`+`date` (tooltip) | % | igual | 50% (este ticker) |
| TD | Time Distribution | franja 30min de `hod_time`/`lod_time`/`pm_high_time`; `%=count_franja/N×100`. RTH 09:30→16:00, PM 04:00→09:30 | % | time null→excluir de esa dist | hod_time `09:42`→franja `09:30-10:00` |
| AC | Avg Change from Open | por mes: `mean((close_vela−rth_open)/rth_open×100)` por franja, 04:00–16:00; ref horizontal `mean(gap_pct)` del mes | % | `rth_open=0`→excluir día | — |
| M-RTH | MAE/MFE RTH (def) | ref **`rth_open`** (09:30 estricto, Q1). `MAE=max(0,(rth_high−rth_open)/rth_open×100)` (≡`rth_run_pct`); `MFE=max(0,(rth_open−rth_low)/rth_open×100)` | % / RTH | `rth_open=0`→excluir | MAE=(14−13)/13=7.7%; MFE=(13−8.5)/13=34.6% |
| M-PM | MAE/MFE PM | ref **`prev_close`**. `MAE=max(0,(pm_high−prev_close)/prev_close×100)` (≡`pmh_gap_pct`); `MFE=max(0,(prev_close−pm_low)/prev_close×100)` | % / PM | `prev_close=0`→excluir | MAE=(18−10)/10=80%; MFE=(10−11.5)/10=−15→0 |
| F | HOD fade % (filtro) | `(rth_high−close_1559)/rth_high×100` | % | `rth_high=0`→excluir | (14−9)/14=35.7% |

Histograma MAE/MFE: rangos `0-5,5-10,10-15,15-20,20-30,30-50,>50`; marcar `P25,P50,P75`; header = media.
**Anti-lookahead:** N/A operativo — son estadísticas descriptivas ex-post, no señales de entrada; no se usan
para decidir fills. Se documenta para que la IA no introduzca lógica de ejecución aquí.

---

## 6 · Plan de ejecución atómico + DoD + verificación

> Cada tarea: (a) test primero, (b) implementar, (c) correr verificación, (d) commit convencional. No
> avanzar si la verificación no pasa. Tests al estilo de `backend/tests/test_backtest_golden.py`.

**EPIC F0 — Reactivar backend** (1 PR)
- T0.1 Des-ocultar `/screener` y `/aggregate/intraday` en `routers/market.py`; mover lógica de cálculo a
  `services/` (router fino). Test de contrato: el response cumple §4.
- T0.2 `get_stats_sql_logic`: emitir KPIs reales (K1–K4, K6, K7) + `distributions` (TD) reales en vez de
  `'--'`/`{}`. `close_lt_vwap_pct` → `null` (Fase 2).
- T0.3 Crear `pmh_fade_to_close_pct` y MAE/MFE (PM/RTH) en el stats SQL.
- **DoD:** `pytest backend/tests/test_market_analysis.py -q` verde; ejemplos numéricos de §5 como asserts;
  paridad hot_cache vs gcs.

> ~~T0.x `day_vwap` en `processor_service`~~ → **diferido a F3/Fase 2** (toca zona de datos, consensuar Adrián).

**EPIC F1 — Página `/market-analysis`** (1 PR)
- T1.1 Ruta `frontend/src/app/market-analysis/page.tsx` + entitlement `market.analysis.access`
  (`policy.py`: Admin=True, resto=False) + item en `Sidebar.tsx`; `LockedFeature` para no-admin.
- T1.2 KPIs (MA-01) con delta rojo/verde + Recent Gaps Up (MA-06, 9 col, paginada 50, ordenable, click→Screener).
- T1.3 Panel de filtros base (periodo + Gap Day + Pre-Market) con contador + "Limpiar filtros"; estado en URL.
- **DoD:** `npm run build` y `npm run lint` verdes; los 4 estados de UI; al cambiar filtro recalcula todo.

**EPIC F2 — Módulos analíticos** (1 PR)
- T2.1 Time Distribution (MA-02) con toggles independientes 5D/30D/90D y header de franja dominante.
- T2.2 Avg Change from Open (MA-04): 12 mini-gráficos, curva 04:00–16:00, línea vertical 09:30, ref avg gap.
- T2.3 MAE/MFE (MA-05) histograma + P25/P50/P75 + toggle PM/RTH.
- **DoD:** build/lint verdes; cada gráfico contra un fixture conocido.

**EPIC F3 — Enriquecimiento + VWAP (Fase 2, PR aparte, no bloquea v1.0)**
- Tabla `ticker_reference` (sector/país/float, Polygon→Finviz→Dilution→Yahoo) + Hot Sectors (MA-03) +
  filtros Universo. Reglas de dominio: §7 (Q2/Q3 fijadas).
- `day_vwap` aditivo en `daily_metrics` (consensuar Adrián) + KPI-05 Close<VWAP % + filtro `close_lt_vwap`.

Comandos de verificación: `cd backend && python -m pytest tests/test_market_analysis.py -q` ·
`cd frontend && npm run build && npm run lint`.

---

## 7 · Decisiones abiertas

**(A) Negocio — diferido a Jesús (no se decide aquí, regla del repo).**
- Tier exacto que abre Market Analysis tras el arranque admin-only. **Arranque confirmado: admin-only**
  (`market.analysis.access`, patrón `market.sentiment.access`). Precio/gating del resto: Jesús.

**(B) Técnicas reversibles (asumidas; marcar a Adrián la columna nueva).**
- `day_vwap` como **columna aditiva** en `daily_metrics` (alt.: calcular en query desde `intraday_1m.vwap` —
  más lento). **Diferido a Fase 2 por Jesús (28-jun-2026)**: el MVP no lo incluye; KPI-05/filtro Close<VWAP
  quedan reservados en el contrato. Consensuar con Adrián cuando entre.
- Nueva ruta `/market-analysis` (no se evoluciona el prototipo del home; el prototipo se retira/migra).
- Reusar `query_service` + hot cache; KPIs y distribuciones en un solo response de `/screener`.

**(C) Dominio — respondidas por Jesús (pendiente OK de Jaume/Álvaro).**
- **Q1 (ref MAE/MFE RTH):** open **estricto de 09:30** (`rth_open`). ✅ fijado en §3/§5.
- **Q2 (float, Fase 2):** float **en el momento del gap**; si Massive/fuente no lo da fiable, usar el
  disponible. Se diseña el campo como histórico-preferente con fallback.
- **Q3 (país, Fase 2):** **sede fiscal** (el exchange es casi siempre US, no discrimina).
- **Q4 (gapper sin datos PM):** **se excluye** del universo; en la práctica todos tienen PM (no se da).
