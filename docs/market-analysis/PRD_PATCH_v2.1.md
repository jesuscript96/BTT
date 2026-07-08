# PRD ejecutable — Market Analysis · Patch v2.1 (condensado)

> **Estado:** EJECUTADO (08-jul-2026) — ver §8 (log de ejecución, desviaciones del plan y pendientes).
> Cambio de diseño clave respecto al plan: los datos nuevos NO van como columnas en `daily_metrics`
> sino como **parquet derivado aditivo** (`cold_storage/derived/`) — cero riesgo sobre el lake, cero
> gate: borrar el prefijo lo revierte. El paquete con Adrián pasa de "consenso de schema" a "FYI +
> adopción del paso 6 del catchup".
> **Origen:** `PRD_MarketAnalysis_v1.2_Alvaro.md` (jul-2026; el fichero se llama v1.2 pero su contenido
> se titula **Patch v2.1**, addendum sobre el PRD v2.0 — aquí usamos v2.1). Reescrito como paquete
> ejecutable anclado en código real, per `docs/manual-prd/GUIA_PRD_EJECUTABLE.md` §4.9 (suite condensado).
> **Leer junto a:** `docs/market-analysis/PRD.md` (el PRD ejecutable del MVP v1.0, ya implementado).
> **Owner ejecución:** Jesús.
>
> **Hallazgos clave de la auditoría (2026-07-07, verificados en vivo):**
> 1. **El hot path no aplica NINGÚN filtro de calidad.** El cold path ya excluye splits del mismo día y
>    filtra tipos CS/ADRC/OS (`query_service.py:308-344`), pero Market Analysis con gap≥10 sirve del
>    hot cache en RAM (`market_analysis_service.py:314-352`), que no aplica ni splits ni tipos. Lo que
>    ve Álvaro contaminado viene de ahí.
> 2. **`massive.splits` existe (16.000 filas, con `split_from/split_to`) pero está STALE: última fila
>    2026-03-30** (hoy 2026-07-07). El endpoint de Massive `/v3/reference/splits` funciona con la key
>    actual (probado en vivo, HTTP 200, ratios incluidos). Hay que refrescar la tabla y/o complementar vía API.
> 3. **El join contra `intraday_1m` en GCS es inviable en request-time:** medido 16,2 s para UNA semana
>    de gappers CON poda de particiones. La query actual de MA-04 (12 meses, SIN poda year/month,
>    `market_analysis_service.py:483-503`) escanea el lake entero por red → ese es el bug de
>    "Sin datos de perfil mensual". El black swan (01.3) y las franjas 09:30/11:00 (04) por tanto
>    **se precomputan**, no se calculan en request.
> 4. `pmh_gap_pct` **ya existe precalculada** en `daily_metrics` → el KPI PM High Gap % (02) y los
>    sub-valores PM (07) son renames/medias de columnas existentes, no cálculo nuevo.
> 5. `m30_return_pct`/`m60_return_pct` dan las franjas 10:00/10:30 de Ventanas de Fade GRATIS
>    (entrada = `rth_open×(1+m/100)`); faltan 09:30 y 11:00 → 2 columnas aditivas (paquete Adrián).
> 6. `massive.tickers` NO tiene sector (probado: `ticker,name,market,primary_exchange,type,active`) →
>    Hot Sectors sigue siendo Fase 2 con enriquecimiento, tal y como decidió el PRD v2.0. No es un bug.

---

## 1 · Qué y por qué (+ alcance)

**Qué.** Correcciones y ajustes sobre el Market Analysis ya desplegado (MVP v1.0): filtros de calidad de
datos para todo el universo, KPI en % en vez de $, header de 5 tarjetas uniformes con toggle PM/RTH,
sustitución de MAE/MFE por "Ventanas de Fade", retirada de Recent Gaps Up, arreglo del módulo
Avg Change from Open, y Edgie con contexto de la página. **No se reestructura la página** (mandato del patch).

**Por qué.** El universo actual incluye tickers con gaps artificiales (reverse splits, spikes absurdos)
que revientan las medias; un KPI devuelve dólares donde el trader espera %; MAE/MFE no significa nada sin
trade abierto; y hay un módulo caído en prod (GCS).

### Principio global 00 (aplica a TODO este patch y a futuros PRDs)
El pre-market (04:00–09:29) es parte de la sesión del día igual que el RTH (09:30–16:00). Ninguna métrica
se limita a RTH salvo indicación explícita; si un módulo distingue PM vs RTH, la distinción es **visible
en la UI** (toggle/etiqueta), nunca decisión silenciosa del backend.
*Hallazgo de auditoría bajo este principio:* el filtro "Vol RTH mín" de la UI
(`MarketAnalysis.tsx:173`) mapea en realidad a `volume` (sesión completa 04:00–20:00, incluye after-hours)
vía `field_map` (`query_service.py:211`). Se corrige en T1.6.

### Alcance v2.1-A — se construye AHORA (sin tocar zona de datos)
- **P0a · Filtros de calidad sin datos nuevos:** exclusión por reverse split ≤5 días (tabla + API para el
  tail stale), exclusión gap>1000%, y **paridad hot/cold** (tipos CS/ADRC/OS y splits same-day también en hot path).
- **P1 · Header 5 KPIs:** renombrar PM High Average→**PM High Gap %** (en %), eliminar Max Fade y
  Close<VWAP del header, separar "Pulso del Periodo" en 2 tarjetas con sub-valores PM/RTH visibles.
- **P2a · Ventanas de Fade (parcial):** sustituye a MAE/MFE. Modo PM completo + franjas RTH 10:00 y
  10:30 (desde `m30/m60_return_pct`). Franjas 09:30 y 11:00 muestran "pendiente de backfill" hasta P5.
- **P3a · Quitar Recent Gaps Up** + mover el filtro Close Red a servidor.
- **P4 · Edgie en la página** con contexto de filtros/periodo/datos (patrón `ticker-loaded` existente).

### Alcance v2.1-B — GATED en consenso con Adrián (zona de datos; 1 paquete, ver §7-B)
- **P5.1** Columnas aditivas en `daily_metrics`: `m0_return_pct` (close vela 09:30), `m90_return_pct`
  (close 11:00), `max_spike_5m_pct` (black swan) + cálculo en `catchup_gcs.py` + backfill histórico.
- **P5.2** Refresco diario de `massive.splits` en el catchup (hoy stale desde 2026-03-30).
- **P5.3** Parquet derivado `cold_storage/derived/ma_monthly_curves.parquet` (curvas MA-04 precalculadas,
  actualización incremental diaria) → arregla "Avg Change from Open" de forma definitiva.
- **P0b** Filtro black swan (usa `max_spike_5m_pct`) — se activa al aterrizar P5.1.

### Fase 2 (NO ahora; el patch pide "revisar y priorizar" → decisión abierta §7-A)
- **Hot Sectors:** sigue requiriendo enriquecimiento ticker→sector que no existe (verificado en
  `massive.tickers`). Opciones dimensionadas en §7-A. Close<VWAP %: pospuesto (v1.2 del PRD producto).

### Fuera de alcance (que la IA NO lo invente)
- Reestructurar la página o su layout bento. Tocar el backtester o el Baúl. Cambiar la semántica del
  lake as-traded (`MASSIVE_ADJUSTED=false` es DELIBERADO, ver §2). Day2/Day3, treemaps, datos de journal.
- Decisiones de negocio (tiers/gating): Market Analysis sigue admin-only (`market.analysis.access`).

---

## 2 · Fuentes auditadas (anclaje en código — verdad verificada 2026-07-07)

| Pieza real | Fichero:línea | Qué aporta / hallazgo |
|---|---|---|
| Servicio MA (KPIs, dist, MAE/MFE, orquestación hot/cold) | `backend/app/services/market_analysis_service.py` | Todo el cálculo v1.0; aquí se aplican filtros de calidad y nuevos KPIs |
| Hot path en RAM sin filtros de calidad | `market_analysis_service.py:314-352` (`_hot_records`) | **No aplica tipos ni splits** (comentario explícito líneas 318-320) |
| Cold path con exclusión splits same-day + tipos | `backend/app/services/query_service.py:306-344` | `LEFT JOIN massive.splits … WHERE sp.ticker IS NULL` + `t.type IN ('CS','ADRC','OS')` |
| KPI PM High en $ (el bug del patch §02) | `market_analysis_service.py:194` | `pm_high_average = mean(pm_high)` en USD |
| `pmh_gap_pct` precalculada por fila | `backend/app/services/processor_service.py:85` | `(pm_high−prev_close)/prev_close×100` — lista para el rename |
| `m30/m60_return_pct` (close vela ≤10:00/≤10:30 vs open) | `processor_service.py:106-116` | Franjas 10:00/10:30 de Ventanas de Fade sin dato nuevo |
| `prev_close` = close raw del día anterior (self-join a `daily_metrics`) | `processor_service.py:59-76` | Lake as-traded → reverse split contamina gap_pct (síntoma del patch §01.1) |
| Ingesta as-traded DELIBERADA (`MASSIVE_ADJUSTED=false`, anécdota HUBC 1000x) | `backend/scripts/catchup_gcs.py:46-58` | NO cambiar a adjusted; la corrección correcta es excluir/ajustar por evento |
| Universo de ingesta: gap≥5% o PM runner≥10% | `catchup_gcs.py:30-31` | `intraday_1m` cubre todos los gappers del universo MA (gap≥30 ⊂ gap≥5) |
| Vistas GCS con hive partitioning year/month | `backend/app/database.py:28-42` | La poda de particiones existe SI la query la usa |
| Query MA-04 sin poda sobre `intraday_1m` | `market_analysis_service.py:483-503` | **Causa raíz** de "Sin datos de perfil mensual" en `DB_PROVIDER=gcs` |
| Hot cache: criterios `gap≥5 OR pmh≥20`, `gap≤500`, `open>0.10` | `backend/app/services/cache_service.py:158-162` | Ya capa gap≤500 en hot; el límite 1000% del patch afecta sobre todo al cold |
| Splits en RAM (ticker+execution_date, TTL 24h) | `cache_service.py:32-57` | Base para aplicar exclusión reverse-split en hot path (falta cargar ratios) |
| Widget Edgie actual (sin props; evento window + `__lastLoadedTicker`) | `frontend/src/components/ChatBot.tsx:51-125` | Patrón a extender para contexto de página MA |
| Montaje de Edgie por página | `TickerAnalysis.tsx:3675`, `Screener.tsx:1475` | `<ChatBot />` NO está montado en MarketAnalysis.tsx |
| Página + tipos + fetch | `MarketAnalysis.tsx`, `frontend/src/lib/api.ts:517-591` | Contrato actual a modificar (§4) |
| Filtro UI "Vol RTH mín" → columna `volume` (día completo) | `MarketAnalysis.tsx:173` + `query_service.py:211` | Violación silenciosa del principio 00 → T1.6 |

**Probes en vivo (2026-07-07, `DB_PROVIDER=gcs`, backend `.venv_313`):**
- `massive.splits`: **16.000 filas, 2012-07-10 → 2026-03-30 (STALE ~3 meses)**; schema
  `ticker, execution_date, split_from, split_to` (ratios SÍ están en el parquet; `cache_service` hoy solo carga 2 columnas).
- API Massive `/v3/reference/splits?execution_date.gte=…` → HTTP 200 con key actual; devuelve ratios y
  splits con fecha futura (p. ej. PONX 5→1 exec 2026-07-21) → filtrar por `execution_date ≤ fecha del gap`.
- `daily_metrics` al día: max 2026-07-06; jun-2026: 482 gapper-days con gap≥30 (~23/sesión; 1 año ≈ 5.800).
- Join `intraday_1m` (4 franjas, 1 semana de gappers, CON poda year/month): **16,2 s** → confirma que
  cualquier cálculo intraday en request-time está muerto en GCS; 12 meses sin poda = timeout seguro.
- Sanity de Ventanas de Fade sobre datos reales (semana 22-26 jun 2026, gap≥30): fade medio desde
  09:30 = +9,6% (62,5% favorables), desde 11:00 = −0,4% (50,0%) — el decay esperado por el equipo de trading.

---

## 3 · Glosario / nomenclatura (usar SIEMPRE el nombre del código)

| Término patch | Nombre oficial (código) | Definición operativa | Estado |
|---|---|---|---|
| PM High Gap % (KPI renombrado) | `pm_high_gap_pct` (payload) ← media de `pmh_gap_pct` | `mean((pm_high−prev_close)/prev_close×100)` del universo | columna existe; rename de KPI |
| Gappers Count PM | `gappers_count_pm` | `count(pmh_gap_pct > 0)` (subió en pre respecto al cierre anterior) | nuevo (agregado trivial) |
| Avg Gap PM (sub-valor tarjeta 2) | = `pm_high_gap_pct` | misma fórmula que el KPI-02 (el patch las define igual) | reuso de clave |
| Reverse split reciente | `recent_reverse_split` (flag interno) | ∃ split con `split_to < split_from` y `execution_date ∈ (fecha_gap−5d naturales, fecha_gap]` | nuevo (tabla+API) |
| Gap absurdo | — (filtro) | `gap_pct > 1000` → excluir del universo | nuevo (WHERE/pandas) |
| Black swan intradía | `max_spike_5m_pct` (columna NUEVA) | `max sobre la sesión 04:00–16:00 de (high_t − close_{t−5min})/close_{t−5min}×100`; filtro: `>300` → excluir | **P5 (gated Adrián)** |
| Ventana de Fade (franja F, RTH) | `fade_windows.rth[F]` | `entrada = close última vela ≤ F` (semántica asof, igual que `get_return_at`); `salida = close_1559`; `fade = (entrada−salida)/entrada×100`; `entrada ≤ 0 → excluir gapper en F` | 10:00/10:30 derivables YA (`m30/m60`); 09:30/11:00 → `m0/m90_return_pct` (P5) |
| Ventana de Fade (modo PM) | `fade_windows.pm` | `entrada = pm_high`, `salida = close_1559`; **universo completo** (SIN `fade_threshold`) | nuevo (columnas existentes) |
| % favorable para el short | `pct_favorable` | `% de gappers válidos con fade > 0` en la franja | nuevo |
| Fade entrada 09:30 / 11:00 | `m0_return_pct` / `m90_return_pct` (columnas NUEVAS) | mismas semánticas que `m30_return_pct` con minutos 0 y 90 | **P5 (gated Adrián)** |
| Volumen del día (principio 00) | `pm_volume + rth_volume` | NO usar `volume` (incluye after-hours) para "volumen del día" | etiqueta/mapeo T1.6 |

> **Trampa 1:** el KPI `avg_fade_from_pmh` (header) se calcula sobre el subuniverso `gap_pct ≥ fade_threshold`
> (default 50, `market_analysis_service.py:177`); `fade_windows.pm` se calcula sobre el **universo completo**.
> Misma fórmula, universos distintos — no unificar.
> **Trampa 2:** los filtros de calidad (§5-F) se aplican al universo ANTES de todo: KPIs del periodo actual,
> KPIs del periodo anterior (deltas), distribuciones, fade_windows y curvas MA-04. Un solo punto de
> aplicación en el service, no N copias.
> **Trampa 3:** los splits de Massive traen fechas futuras (verificado) → exigir `execution_date ≤ fecha_gap`.

---

## 4 · Contrato de datos

Toda llamada por `frontend/src/lib/api.ts` (regla del repo). Routers finos, lógica en `services/`.
La página es el único consumidor del payload → los renames son seguros si van en el mismo PR.

### 4.1 `GET /api/market/screener` — deltas sobre el contrato v1.0 (`api.ts:545-567`)

```jsonc
{
  "records": [...],                    // SE MANTIENE en backend (lo usa Edgie §4.3); la UI ya no pinta tabla
  "kpis": {
    "gappers_count":     {"value": 142, "prev": 120},          // = RTH (universo del periodo)
    "gappers_count_pm":  {"value": 128, "prev": 111},          // NUEVO — pmh_gap_pct > 0
    "avg_gap_pct":       {"value": 41.3, "prev": 38.0},        // = RTH (open vs prev_close)
    "pm_high_gap_pct":   {"value": 55.2, "prev": 49.8},        // NUEVO nombre (antes pm_high_average en $)
    "close_red_pct":     {"value": 63.2, "prev": 60.1},
    "avg_fade_from_pmh": {"value": 22.7, "prev": 21.0},
    "close_lt_vwap_pct": {"value": null}                       // reservado v1.2 (se mantiene null)
    // ELIMINADOS: pm_high_average, max_fade_from_pmh
  },
  "fade_windows": {                    // NUEVO — sustituye a "mae_mfe" (clave mae_mfe ELIMINADA)
    "rth": [
      {"franja": "09:30", "avg_fade_pct": null, "pct_favorable": null, "n": 0, "pending_backfill": true},
      {"franja": "10:00", "avg_fade_pct": 4.6,  "pct_favorable": 62.7, "n": 51},
      {"franja": "10:30", "avg_fade_pct": 4.1,  "pct_favorable": 61.7, "n": 47},
      {"franja": "11:00", "avg_fade_pct": null, "pct_favorable": null, "n": 0, "pending_backfill": true}
    ],
    "pm": {"avg_fade_pct": 31.4, "pct_favorable": 71.2, "n": 140}
  },
  "quality_filters": {                 // NUEVO — transparencia de exclusiones (principio 00: nada silencioso)
    "excluded_reverse_split": 3,
    "excluded_gap_gt_1000": 1,
    "excluded_black_swan": null        // null hasta P0b (columna no disponible)
  },
  "distributions": { ... },            // sin cambios
  "source": "hot_cache | gcs", "period": { ... }
}
```
Params: sin cambios (los filtros de calidad NO son parámetros: se aplican siempre, servidor).
`close_red=yes|no|all` pasa a aplicarse **en servidor** (hot: pandas sobre `day_return_pct<0`; cold: WHERE).

### 4.2 `GET /api/market/aggregate/intraday` — mismo shape de response, nueva fuente
Mismo JSON (`MaMonthCurve[]`). Implementación: leer del parquet derivado
`cold_storage/derived/ma_monthly_curves.parquet` (P5.3) con universo estándar fijo (ver §7-C-Q3);
**interim** (hasta P5.3): query actual + poda `i.year/i.month` del rango + cache SWR en proceso por
hash de filtros, y si excede presupuesto (>25 s) → `[]` con log claro (la UI ya tiene empty state).
La UI etiqueta el universo del módulo (subtítulo), porque deja de obedecer los filtros globales (§7-C-Q3).

### 4.3 Contexto de página para Edgie (frontend-only, sin endpoint nuevo)
Patrón `ticker-loaded` extendido (`ChatBot.tsx:94-125`):
```ts
// MarketAnalysis.tsx — al resolver cada payload (y al desmontar, con detail=null para limpiar):
window.dispatchEvent(new CustomEvent("market-analysis-context", { detail: {
  period: data.period, preset: filters.period,
  filters: {min_gap, min_open, max_open, min_volume, min_pm_volume, close_red, fade_threshold},
  kpis: data.kpis, fade_windows: data.fade_windows,
  distributions_resumen: top3PorSerie(data.distributions),
  quality_filters: data.quality_filters,
  records_sample: data.records.slice(0, 20),   // muestra acotada, no las 2000 filas
}}));
(window as any).__lastMarketAnalysisContext = detail;  // para montajes tardíos del widget
```
ChatBot añade al system prompt una sección "### Market Analysis en pantalla" con ese JSON compactado
(respetando `MAX_CONTEXT_CHARS = 6000`, `ChatBot.tsx:46`) SOLO mientras el contexto sea no-nulo.

### 4.4 Estados de UI
Los 4 estados obligatorios ya existen en la página; cambios: el Empty pasa a decidirse por
`kpis.gappers_count.value === 0` (ya no hay tabla de records); "Ventanas de Fade" muestra las franjas
`pending_backfill` con "—" y tooltip "backfill en curso"; el módulo MA-04 mantiene su empty actual.

---

## 5 · Reglas de trading (5 elementos) + ejemplos numéricos

Ejemplo base: `prev_close=10.00`, `pm_high=18.00`, `rth_open=13.00`, closes de vela:
`09:30→13.20`, `10:00→12.40`, `10:30→11.80`, `11:00→11.00`, `close_1559=9.00`.

| # | Métrica / filtro | Fórmula | Unidad / sesión | Edge case | Ejemplo |
|---|---|---|---|---|---|
| F1 | Exclusión reverse split | excluir si ∃ split `split_to<split_from` con `execution_date ∈ (d−5, d]` (naturales) y `execution_date ≤ d` | filtro / universo | splits futuros (existen en la API) → ignorar; tabla stale → complementar API | PONX 5→1 exec 21-jul → excluido 21→26-jul |
| F2 | Exclusión gap absurdo | `gap_pct > 1000` → fuera | filtro / día | hot cache ya recorta >500 en su criterio de carga; regla igualmente en ambos paths | gap 1200% ⇒ fuera |
| F3 | Exclusión black swan (P0b) | `max_spike_5m_pct > 300` → fuera; ventana móvil t−5min sobre **04:00–16:00** | filtro / sesión completa | <5 velas al inicio de sesión → ventana disponible; velas ilíquidas ausentes → asof sobre las existentes | close 06:00=2.00, high 06:05=8.20 ⇒ +310% ⇒ fuera |
| K2' | PM High Gap % | `mean(pmh_gap_pct)`, universo completo | % / PM | `pm_high=0` o `prev_close≤0` → fila excluida del promedio (pmh_gap_pct=0 en processor → excluir con `pm_high>0`) | (18−10)/10 = **80%** |
| K1' | Gappers Count PM | `count(pmh_gap_pct > 0)` | conteo / PM | sin velas PM (no se da, Q4 PRD v1) → no cuenta | 18>10 ⇒ cuenta |
| VF-RTH | Ventana de Fade franja F | `entrada=close asof F` (`rth_open×(1+m{F}_return_pct/100)`); `fade=(entrada−close_1559)/entrada×100`; `pct_favorable=%(fade>0)` | % / RTH | `entrada≤0` → excluir gapper en esa franja; sin vela ≤F → excluir | F=10:00: entrada=12.40 ⇒ (12.40−9)/12.40=**27.4%** ✓favorable |
| VF-PM | Ventana de Fade PM | `entrada=pm_high`, `fade=(pm_high−close_1559)/pm_high×100` — universo completo, SIN fade_threshold | % / PM+EOD | `pm_high≤0` → excluir | (18−9)/18=**50%** |
| — | Consistencia m-returns | `m0`: close vela ≤09:30; `m90`: close ≤11:00 — misma semántica asof que `get_return_at` (`processor_service.py:106-111`) | % | vela exacta ausente → última anterior (asof), NO interpolar | m0: (13.20−13)/13=+1.54% |

**Anti-lookahead:** N/A operativo — estadísticas descriptivas ex-post (igual que v1.0); los filtros de
calidad usan solo información del propio día o anterior (splits ejecutados ≤ fecha del gap). Se explicita
para que la IA no meta lógica de fills.

---

## 6 · Plan de ejecución atómico + DoD + verificación

> Cada tarea: (a) test primero, (b) implementar, (c) verificación, (d) commit convencional.
> Comandos: `cd backend && python -m pytest tests/test_market_analysis.py -q` ·
> `cd frontend && npm run build && npm run lint`. Estilo de tests: los existentes de
> `test_market_analysis.py` (ejemplos numéricos de §5 como asserts, sin BD viva).

**EPIC P0a — Filtros de calidad sin datos nuevos** (1 PR, backend)
- T0.1 `market_analysis_service.apply_quality_filters(records, splits_df)` — punto ÚNICO de exclusión:
  gap>1000 + reverse-split-5d (F1, F2 de §5). Se aplica a `cur_records`, `prev_records` y al set de MA-04.
  Devuelve contadores para `quality_filters` del payload.
- T0.2 Splits: ampliar `cache_service.load_splits_cache` a `ticker, execution_date, split_from, split_to`;
  añadir `massive_service.get_splits_since(date)` (paginando `next_url`, memo 24h) para cubrir el tail
  stale de la tabla (probe: tabla llega a 2026-03-30). Merge tabla+API en un DataFrame único.
- T0.3 Paridad hot/cold: en `_hot_records`, aplicar filtro de tipos (merge con `get_tickers_df()`) y
  exclusión splits same-day (cualquier dirección, como el cold path) — hoy solo lo hace el cold
  (`query_service.py:308-312`). Añadir `close_red` server-side en ambos paths.
- **DoD:** tests con fixtures sintéticos (ticker con reverse split D-2 excluido; gap 1200% excluido;
  paridad hot vs cold sobre el mismo fixture); `quality_filters` reporta conteos correctos.

**EPIC P1 — Header 5 KPIs** (mismo PR o el siguiente; backend+frontend)
- T1.1 Backend: renombrar `pm_high_average`→`pm_high_gap_pct` con nueva fórmula (`mean(pmh_gap_pct)` con
  `pm_high>0`); añadir `gappers_count_pm`; eliminar `max_fade_from_pmh` del payload; mantener
  `close_lt_vwap_pct: null`. Actualizar `_DELTA_KPIS`.
- T1.2 Frontend (`MarketAnalysis.tsx` + `api.ts` types): 5 tarjetas uniformes (desaparece el hero
  "Pulso del Periodo" y su etiqueta) — Gappers Count y Avg Gap % con **toggle PM/RTH visible**
  (sub-valores: PM=`gappers_count_pm`/`pm_high_gap_pct`, RTH=`gappers_count`/`avg_gap_pct`);
  quitar tarjetas Max Fade y Close<VWAP.
- T1.6 Principio 00 en filtros: etiqueta del filtro de volumen → "Vol día (PM+RTH) mín" y mapeo a
  `pm_volume+rth_volume` (o exponer dos filtros separados PM/RTH — elegir en review; NUNCA `volume` con
  etiqueta RTH). Panel muestra con qué sesión trabaja cada filtro.
- **DoD:** build+lint verdes; snapshot de 5 tarjetas; delta "vs ant." conservado; sin referencias a
  `pm_high_average`/`max_fade_from_pmh` en el código.

**EPIC P2a — Ventanas de Fade (parcial, sin datos nuevos)** (1 PR)
- T2.1 Backend `compute_fade_windows(records)`: PM (completo) + RTH 10:00/10:30 vía `m30/m60_return_pct`;
  09:30/11:00 emiten `pending_backfill: true`. Eliminar `compute_mae_mfe` y la clave `mae_mfe`.
- T2.2 Frontend: sustituir `MaeMfePanel` por tabla "Ventanas de Fade" (Franja | Avg Fade % | % favorable
  short) con toggle PM/RTH visible (modo PM = fila única PM High→EOD). Subtítulo:
  "Caída media de los gappers por franja de entrada". Franjas pendientes → "—" + tooltip.
- **DoD:** asserts §5 (VF-RTH 27.4%, VF-PM 50%); build verde; el toggle PM/RTH renderiza ambos modos.

**EPIC P3a — Retirar Recent Gaps Up** (mismo PR que P2a)
- T3.1 Quitar `RecentGapsTable` y `recordsFiltered`; Empty state por `gappers_count===0`; `records` se
  mantiene en el payload (Edgie). El click-a-ticker desaparece con la tabla (la página es informativa).
- **DoD:** build+lint verdes; estados Loading/Empty/Error intactos.

**EPIC P4 — Edgie con contexto de página** (1 PR, frontend)
- T4.1 Montar `<ChatBot />` en `MarketAnalysis.tsx` (widget flotante colapsable — mismo componente
  que TickerAnalysis/Screener, `TickerAnalysis.tsx:3675`).
- T4.2 Evento `market-analysis-context` + `__lastMarketAnalysisContext` según §4.3 (emitir en cada payload,
  limpiar al desmontar) y sección condicional en el system prompt de ChatBot (truncada a 6000 chars).
- **DoD:** manual: abrir MA → preguntar "¿cuántos gappers hay y cuál es el fade medio desde las 10:00?"
  → Edgie responde con los números en pantalla; al navegar a otra página el contexto MA no contamina.

**EPIC P5 — Paquete zona de datos (GATE: consenso Adrián, §7-B)** (PR aparte; no bloquea P0a-P4)
- T5.1 `processor_service.process_daily_metrics`: añadir `m0_return_pct`, `m90_return_pct`,
  `max_spike_5m_pct` (rolling 5min sobre sesión 04:00–16:00). Columnas ADITIVAS (no rompen schema).
- T5.2 `catchup_gcs.py`: escribirlas a diario + **backfill one-off** de histórico desde `intraday_1m`
  (script `scripts/backfill_ma_columns.py`, por particiones month; correr en prod junto al bucket, no
  por red doméstica — medido 16 s/semana desde local). Regenerar hot cache parquet al terminar
  (`cache_service.py:144-168` ya auto-regenera si faltan columnas → añadirlas a `expanded_columns`).
- T5.3 Refresco diario de `massive.splits` en el catchup (API `/v3/reference/splits` incremental).
- T5.4 Derivado MA-04: `scripts/build_ma_curves.py` + paso incremental diario en catchup → parquet
  `derived/ma_monthly_curves.parquet` (12+ meses × franjas 30min × universo estándar); reescribir
  `get_avg_change_from_open` para leerlo (fallback: interim de §4.2).
- T5.5 Activar P0b (filtro black swan) y franjas 09:30/11:00 (quitar `pending_backfill`).
- **DoD:** paridad processor vs backfill sobre 1 día golden; MA-04 responde <1 s en GCS; black swan
  excluye el fixture F3; franjas completas con `n>0`.

**Orden de PRs:** PR1 = P0a+P1 · PR2 = P2a+P3a · PR3 = P4 · PR4 = P5 (tras OK de Adrián; puede
prepararse en paralelo). Los 3 primeros salen esta semana sin dependencias externas.

---

## 7 · Decisiones por tomar

> Todo lo del patch está IMPLEMENTADO con una opción por defecto razonable y reversible. Estas
> decisiones **no bloquean el uso**: o confirman lo ya hecho (barato revertir si se quiere otra cosa)
> o abren trabajo futuro. Ninguna la decide la IA (regla del repo: negocio/dominio los fijan las personas).

### (A) Nueva funcionalidad — prioridad de producto · **dueño: Álvaro/Jaume** (Jesús prioriza)

| Decisión | Opciones | Recomendación | Qué desbloquea / cuesta |
|---|---|---|---|
| **Hot Sectors** (el patch §06 lo pedía "revisar"; sigue en F2 porque `massive.tickers` no tiene sector — verificado) | **A1** on-demand: `massive_service.get_overview` trae `sic_description`, mapeo SIC→sector, memo 24h. **A2** tabla de referencia en el lake (zona Adrián), sirve también País/Sector/Float de F2 | A1 si se quiere ya y solo sectores; A2 si entra el paquete Universo completo de F2 | A1 ≈ 1 día dev; A2 ≈ paquete de datos con Adrián. Hasta decidir, no se construye |

### (B) Dominio — confirmar lo ya implementado · **dueño: Álvaro** (validación, no construcción)

| Decisión | Implementado por defecto | Alternativa | Coste de cambiar |
|---|---|---|---|
| Ventana del reverse split | **5 días naturales** (conservador, simple) | días hábiles | 1 constante (`REVERSE_SPLIT_LOOKBACK_DAYS`) |
| ¿Mantener filtro Close Red en UI? (ahora es server-side, afecta a KPIs/módulos) | **sí, se mantiene** | quitarlo | quitar 1 control en `MarketAnalysis.tsx` |
| Universo estándar de las curvas MA-04 (no obedece filtros globales, va etiquetado) | **gap≥30 · vol día≥1M · filtros de calidad** | otros umbrales | 2 constantes en `backfill_ma_derived.py` + re-run del backfill |
| Entrada de franja (Ventanas de Fade) | **asof**: close de la última vela ≤ franja (igual que `mXX_return_pct`) | interpolar / vela exacta | lógica en `compute_fade_windows` |
| Filtros de calidad NO configurables por el usuario (siempre on, efecto visible en "Calidad de datos") | **fijo** | exponerlos como toggles | UI nueva |

### (C) Negocio — **dueño: Jesús** (la IA no opina, per repo)
- Tier que abre Market Analysis tras el arranque **admin-only** (`market.analysis.access`, ya en
  `policy.py`). Precio/gating: sin decidir, no urge para el uso interno.

### (D) Datos — **dueño: Adrián** (ver "Avisos a Adrián" en §8; no bloquean)
- Semántica de `day_return_pct` en origen (bug); adopción del prefijo `derived/` y del refresh de
  splits en el pipeline nocturno; 403 de GCS en full-scans con la HMAC local.

---

## 8 · Log de ejecución (08-jul-2026) — hecho, desviaciones y pendientes

### Hecho y verificado
- **P0a/P0b · Filtros de calidad** — `apply_quality_filters` como punto único
  (`market_analysis_service.py`), aplicado a periodo actual + anterior; paridad hot/cold (tipos y
  splits también en RAM); `close_red` y `min_day_volume` server-side en ambos paths;
  `quality_filters` en el payload y visible en la UI. **Black swan INCLUIDO** (el derivado se
  construyó en la propia sesión). Smoke real (1m, gap≥30, vol día≥1M): 21 excluidos por tipo,
  5 reverse split, 2 same-day, 1 black swan.
- **P1 · Header** — `pm_high_gap_pct` (%), `gappers_count_pm`, sin `max_fade_from_pmh`; frontend con
  5 tarjetas uniformes y toggle PM/RTH visible en Gappers Count y Avg Gap %.
- **P2a→completo · Ventanas de Fade** — 4 franjas RTH + modo PM, sustituye a MAE/MFE en backend y
  frontend. Smoke real (jun-jul 2026, n=129): 09:30→10.1% (68% favorable) · 10:00→9.9% · 10:30→8.7%
  · 11:00→7.8% · PM→37.9% (92% favorable).
- **P3a · Recent Gaps fuera** — tabla eliminada; `records` se mantiene en payload para Edgie.
- **P4 · Edgie** — `<ChatBot />` montado en la página; evento `market-analysis-context` +
  `__lastMarketAnalysisContext` (limpieza al desmontar); sección en el system prompt (cap 6k chars).
- **P5 (variante derivado) · Datos** — `scripts/backfill_ma_derived.py` (ma_daily + curvas en un
  scan/mes) + `refresh_splits_from_api` + paso 6 en `catchup_gcs.py` (`MA_DERIVED_ENABLED`, best-effort).
  Ejecutado: splits +596 filas (390 reverse, hueco 2026-03-30→hoy cerrado); ma_daily + curvas para
  2026-03→07 y sigue hacia atrás hasta 2025-06 (~60-95s/mes 2026; meses 2025 ~34M velas, ~10-15min/mes).
- **MA-04** — `get_avg_change_from_open` lee `derived/ma_monthly_curves.parquet` (~1,3s medido);
  universo estándar fijo etiquetado en la UI; sin query intraday en request.
- **Tests** — `test_market_analysis.py` 25/25 (ejemplos §5 como asserts + regresión close_red);
  `tsc` limpio; `npm run build` verde; latencia warm del endpoint 0,15s.

### Bug preexistente encontrado y corregido (fuera del alcance del patch)
`day_return_pct` del lake NO es `(rth_close−rth_open)/rth_open` (la variante del catchup calcula otra
cosa; AHMA 2.80→1.47 con +36.1). El KPI Close Red daba 4-6% (imposible). Fix: `is_close_red()` compara
`rth_close < rth_open` directamente (fallback a `day_return_pct` solo sin columnas rth) en KPI, filtro
hot/cold y `records`. Con el fix: 70,5% (prev 63,2%) — coherente con el histórico.
**⚠️ Avisar a Adrián:** la columna del lake tiene semántica distinta a su nombre; otros consumidores
podrían estar asumiendo lo mismo que asumía este módulo.

### Pendiente — trabajo de ejecución (no son decisiones; nada bloquea usar la página)

| # | Qué | Dueño | Esfuerzo | Qué pasa si no se hace |
|---|---|---|---|---|
| E1 | **Backfill histórico del derivado 2022 → 2025-05** (los meses recientes ya están; ver estado abajo). `python scripts/backfill_ma_derived.py --start 2022-01 --end 2025-05`, idempotente por mes, **mejor en prod junto al bucket** (~34M velas/mes; ~4 min/mes local, menos en prod). | Adrián / infra (correr en prod) | ~1 job de ~2-3h desatendido | Presets 1S/1M/3M/6M ya salen completos; **1A y rangos largos** quedan parciales: black swan fail-open y franjas 09:30/11:00 promedian solo meses cubiertos (`n` lo refleja, no miente) |
| E2 | **Deploy de `market-analysis-v2.1` + verificar cron.** El paso 6 del catchup (`MA_DERIVED_ENABLED`, default on) mantiene splits/derivado/curvas al día solo. Confirmar que la env no está a `false` en Coolify. | Infra (deploy) | trivial | El derivado no se actualiza tras el deploy inicial; las curvas y el black swan se congelan en la última fecha del backfill |
| E3 | **Smoke test real de Edgie** (ronda LLM completa). Verificado el wiring (contexto en `window`, prompt inyectado); NO se disparó una pregunta al LLM (consume DeepSeek). Abrir MA → "¿cuántos gappers y fade medio desde las 10:00?" → debe responder con los números en pantalla. | Jesús/QA | 2 min manual | Riesgo bajo: el contexto se publica correctamente; falta confirmar que el modelo lo usa bien |
| E4 | **Push/PR de `market-analysis-v2.1`** (4 commits sobre el merge de PR #6, sin push). | Jesús decide cuándo; otro mergea | trivial | — |
| ~~E5~~ | ~~Retirar prototipo `MarketIntelligenceCharts` del home~~ → **NO aplica:** verificado que ya es una tarjeta estática que solo enlaza a `/market-analysis`, no consume el contrato. El cambio de claves NO rompe el home. | — | — | — |

**Estado del backfill (08-jul-2026, en curso):** hecho 2025-06 y **2025-11 → 2026-07** (9 meses,
sirviendo ya en la página); corriendo hacia atrás 2025-10 → 2025-07. Falta el tramo largo E1.

### Avisos a Adrián (datos) — no son decisiones, es información que debe conocer
1. **Bug de `day_return_pct`** (ver arriba): la columna del lake NO es `(rth_close−rth_open)/rth_open`.
   Market Analysis ya no la usa para Close Red, pero **otros consumidores podrían asumir esa semántica**
   y estar mal. Decidir si se corrige en origen o se documenta.
2. **Prefijo nuevo `cold_storage/derived/`** (ma_daily + ma_monthly_curves) y **parquet aditivo en
   `cold_storage/splits/`** (schema idéntico verificado). Todo aditivo: no toca `daily_metrics`/`intraday_1m`.
3. **GCS 403 intermitente** en full-scans desde la HMAC local (afecta a `/latest-date` y otros endpoints
   que escanean el lake entero; NO a Market Analysis, que va por hot cache). ¿Permiso de la key o del
   bucket? Verificar antes de que muerda a otra feature.
