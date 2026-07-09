# PRD ejecutable — Market Analysis · Gaps Up by Sector (condensado)

> **Estado:** EJECUTADO (08-jul-2026, verificado en local) — treemap elegido (§7-D1 resuelto por Jesús:
> "acepto tu recomendación"). Ver §8 log de ejecución.
> **Origen:** petición de Jesús (08-jul-2026): quitar "Distribución temporal" y añadir un mapa de calor
> de gappers (gap≥20%) por **sector** de la empresa, referencia visual en la captura adjunta;
> librería sugerida [visx/heatmaps](https://visx.airbnb.tech/heatmaps) → se usó `@visx/hierarchy` (treemap).
> **Redistribución de la página:** rejilla FIJA 2×2 al 50% — [Pulso (5 métricas) | Ventanas de Fade] /
> [Avg Change from Open | Treemap sector]. El KPI panel sin pills (todas las métricas visibles).
> **Owner ejecución:** Jesús. Sobre `docs/market-analysis/PRD.md` + `PRD_PATCH_v2.1.md` (ya en prod).
> **Formato:** §4.9 (suite condensado) de `docs/manual-prd/GUIA_PRD_EJECUTABLE.md`.

---

## 0 · Veredicto de viabilidad (verificado en vivo, 08-jul-2026)

**VIABLE.** El sector se obtiene del `sic_code` de Massive, con SEC EDGAR como fallback — ambas fuentes
**ya integradas** en el código (`massive_service`, `edgar_service`). Una salvedad real de cobertura,
resuelta con doble fuente:

| Pregunta de viabilidad | Resultado medido | Fuente |
|---|---|---|
| ¿`massive.tickers` tiene sector? | **No** (`ticker, name, market, primary_exchange, type, active`) | probe schema |
| ¿Massive da sector por otro lado? | **Sí**: `sic_code` + `sic_description` en `/v3/reference/tickers/{t}` (AAPL→3571 "Electronic Computers", HIMS→8011 "Doctors of Medicine") | probe API |
| ¿Hay endpoint bulk con SIC? | **No** — el listado `/v3/reference/tickers` devuelve `sic_code=null`. Enriquecimiento por-ticker | probe API |
| Cobertura Massive sobre el universo real (CS/ADRC/OS, gap≥20, 90D) | **63%** (292/464). Los que faltan son micro-caps que Massive no cubre (no solo deslistados: AHMA gapeó hace 6 días y no trae SIC ni con `date=`) | probe 464 tickers |
| ¿EDGAR recupera a los que faltan? | **Sí, ~7/8**: AHMA→7900, AKAN→2833, APWC→3357, AEHL→4899… vía `company_tickers.json`→CIK→`submissions/CIK.json.sic` | probe SEC |
| **Cobertura combinada estimada** | **~90-95%**, con bucket residual "Sin sector" (~5-10%: deslistados sin mapping SEC, p. ej. AGAE) | Massive+EDGAR |
| Coste de enriquecer TODO el histórico | **6.272 tickers** (gap≥20 histórico) → ~2 min de llamadas **una sola vez** (tabla de referencia) | probe count |
| Universo por ventana | 5D: 17 · 30D: 329 · 90D: 885 tickers distintos (crudo); ~la mitad tras filtro de tipos | probe count |

**Salvedad honesta:** el ~5-10% "Sin sector" se concentra en los shells/micro-caps más oscuros, que
son *parte del interés* del short-seller. Se muestra como bucket propio (principio 00: no se oculta).
Distribución real de una muestra 30D (189 con SIC): Financial Services 78 (SPACs/shells — real, no bug),
Healthcare 36, Technology 24, Industrials 11, Consumer Cyclical 9, resto ≤4.

---

## 1 · Qué y por qué (+ alcance)

**Qué.** (a) Eliminar el módulo "Distribución temporal" (HOD/LOD/PMH por franja). (b) Añadir
**"Gaps Up by Sector"**: los gappers con `gap_pct ≥ 20` del periodo, agrupados por sector de la empresa,
como mapa de calor; toggle de ventana **5D / 30D / 90D** (independiente del selector global, como lo era
Time Distribution) y selector de métrica (**Count / Close Red %**, extensible a Avg Gap %).

**Por qué.** Jesús: la distribución temporal "no tiene sentido" (además ya se le había puesto un parche
`MAX_GAP_FOR_DISTRIBUTION=100` para que no se sesgara a apertura — señal de que no aporta). El short-seller
de small-caps quiere leer **en qué sectores se están dando los gaps y cómo cierran** (rojo = a favor del
short), que es exactamente lo que muestra la captura de referencia.

### Alcance v1 — se construye
- **S1 · Enriquecimiento sector** (dato nuevo): tabla de referencia `ticker → sic_code → sector` en el
  lake, construida por script (Massive `sic_code` → fallback SEC EDGAR → mapeo SIC→sector) + refresco
  en el catchup. **Esto desbloquea también los filtros País/Sector/Float diferidos a F2.**
- **S2 · Endpoint** `GET /api/market/gaps-by-sector` (ventana + min_gap + métrica).
- **S3 · Frontend**: quitar panel "Distribución temporal" + su módulo; añadir panel "Gaps Up by Sector"
  con la viz elegida (§7-D1), toggle 5D/30D/90D y selector de métrica.

### Alcance v2 (no ahora; el v1 lo deja preparado)
- **Sector como FILTRO** de toda la página (`sector[]` en `/screener`) — Jesús dijo "que filtre por
  sector"; el enriquecimiento de S1 lo habilita sin coste extra de datos. Se reserva el parámetro.
- Agrupar por **Industria** (SIC más granular) o **País** (el `address.country`/sede de EDGAR),
  reusando el dropdown "Sectors" de la captura.

### Fuera de alcance (que la IA NO invente)
- Tocar `daily_metrics`/`intraday_1m`. Market cap/float en esta viz. Cambiar la taxonomía de sectores
  sin validación (§7-D3). Precio real de la API por-request (se sirve SIEMPRE de la tabla de referencia).

---

## 2 · Fuentes auditadas (anclaje en código + probes en vivo)

| Pieza real | Fichero:línea | Qué aporta |
|---|---|---|
| Overview con `sic_code`/`sic_description` (fallback deslistados) | `backend/app/services/massive_service.py:99-127` (`get_overview`) | fuente primaria de sector; ya memoizada 24h |
| CIK del ticker | `massive_service.py:129-136` (`get_cik`) | puente a EDGAR |
| Servicio EDGAR (ya lee submissions) | `backend/app/services/edgar_service.py` | fallback SIC vía `data.sec.gov/submissions/CIK{cik}.json` (`.sic`, `.sicDescription`) |
| Filtro de tipos CS/ADRC/OS (universo del sector) | `market_analysis_service.py` (`apply_quality_filters`) | el heatmap hereda ESTE universo ya limpio |
| Distribución temporal a ELIMINAR (backend) | `market_analysis_service.py` (`_distribution`, clave `distributions`) | quitar del payload |
| Distribución temporal a ELIMINAR (frontend) | `frontend/src/components/MarketAnalysis.tsx` (`TimingModule`, `TimingChart`, `TimingLegend`, panel "Distribución temporal") | quitar panel |
| Chart visx existente (patrón a seguir) | `frontend/src/components/market-analysis/charts.tsx` | mismos tokens/branding; visx ya en uso |
| Reference parquet pattern (splits/tickers/derived) | `backend/app/database.py:36-42`, `scripts/backfill_ma_derived.py` | dónde y cómo vive una tabla de referencia en GCS |
| Refresco en el pipeline nocturno | `backend/scripts/catchup_gcs.py` (paso 6, `MA_DERIVED_ENABLED`) | añadir paso 7 análogo para sector |
| Endpoint fino → service | `backend/app/routers/market.py` | patrón router fino |

**Probes (08-jul-2026):** ver §0. Paquetes visx instalados: `@visx/{axis,shape,scale,group,tooltip,
gradient,grid,text,...}` — **NO** están `@visx/hierarchy` (treemap) ni `@visx/heatmap`; la viz elegida
añade UNO de los dos (oficial, ^4.0.0, bajo riesgo).

---

## 3 · Glosario / nomenclatura

| Término | Nombre oficial (código) | Definición | Estado |
|---|---|---|---|
| SIC code | `sic_code` | código SIC de 4 dígitos (Massive u SEC) | existe (fuente) |
| Sector | `sector` (NUEVO) | uno de los 11 Yahoo/Finviz (Healthcare, Technology, Financial Services, Consumer Cyclical, Consumer Defensive, Communication Services, Industrials, Basic Materials, Energy, Real Estate, Utilities) + **"Sin sector"** | **nuevo** |
| Mapeo SIC→sector | `sic_to_sector(sic)` (NUEVO) | tabla curada por rangos SIC → sector | **nuevo** (§5) |
| Tabla de referencia | `ticker_sector` (NUEVO) | `cold_storage/reference/ticker_sector.parquet`: `ticker, sic_code, sector, source, updated_at` | **nuevo** |
| Gaps Up (count) | `count` | nº de **gapper-días** con `gap_pct ≥ min_gap` en la ventana (un ticker que gapea 2 días cuenta 2 — es un evento), como la captura ("GAPS UP") | derivado |
| Close Red % (por sector) | `close_red_pct` | `% de esos gapper-días con rth_close < rth_open` (usa `is_close_red`, ver Patch v2.1) | derivado |

---

## 4 · Contrato de datos

### 4.1 `GET /api/market/gaps-by-sector` (NUEVO, router fino → service)
Params: `window` (`5d|30d|90d`, default `5d`), `min_gap` (default `20`), `metric` (`count|close_red|avg_gap`,
default `count`). Reutiliza el hot cache (gap≥10 ya en RAM) + `apply_quality_filters`.
```jsonc
{
  "window": "5d", "min_gap": 20.0, "metric": "count",
  "sectors": [
    { "sector": "Healthcare",       "count": 4, "close_red_pct": 100.0, "avg_gap_pct": 41.2 },
    { "sector": "Consumer Cyclical","count": 2, "close_red_pct": 100.0, "avg_gap_pct": 33.0 },
    { "sector": "Technology",       "count": 3, "close_red_pct": 66.7,  "avg_gap_pct": 51.9 },
    { "sector": "Sin sector",       "count": 1, "close_red_pct": 0.0,   "avg_gap_pct": 22.4 }
  ],
  "total_gaps": 10, "unknown_pct": 8.3, "source": "hot_cache"
}
```
> `unknown_pct` = % de gapper-días sin sector resuelto (transparencia, principio 00).

### 4.2 Tabla de referencia `ticker_sector.parquet` (build offline + refresco)
`scripts/build_ticker_sector.py`: para cada ticker del universo (gap≥20 histórico, 6.272), resolver
`sic_code` por **Massive `get_overview` → si None, SEC EDGAR (CIK→submissions.sic)**; aplicar
`sic_to_sector`; escribir `ticker, sic_code, sic_description, sector, source ('massive'|'sec'|'none'),
updated_at`. Aditivo en `cold_storage/reference/` (no toca nada). Refresco: paso 7 del catchup solo para
tickers nuevos del día (sector cambia rara vez).

### 4.3 Estados de UI
Loading (skeleton de celdas), Empty ("Sin gaps ≥20% en esta ventana"), Error (reintento por `lib/api.ts`),
Success. El bucket "Sin sector" se muestra si `count>0` (no se oculta).

---

## 5 · Reglas (5 elementos) + ejemplos

| # | Regla | Fórmula | Unidad | Edge case | Ejemplo (captura 5D) |
|---|---|---|---|---|---|
| G1 | Universo | `gap_pct ≥ min_gap` (default 20) sobre el universo ya filtrado (CS/ADRC/OS, calidad) | — | sin sector → bucket "Sin sector" | 10 gaps ≥20% |
| G2 | Count por sector | `count(gapper-días del sector)` | conteo | — | Healthcare=4 |
| G3 | Close Red % por sector | `count(rth_close<rth_open) / count_sector × 100` (`is_close_red`) | % | count_sector=0 → n/a | Healthcare 100%, Tech 66.7% |
| G4 | Sector del ticker | `sic_to_sector(sic_code)`; SIC de Massive, fallback EDGAR | — | ambos None → "Sin sector" | HIMS 8011→Healthcare |
| G5 | Ventana | últimos N días naturales desde la última fecha con datos (indep. del selector global) | — | — | 5D/30D/90D |

**Mapeo `sic_to_sector` (curado por rangos — extracto; la tabla completa se fija en la ejecución y se
valida §7-D3):** 2833-2836 y 8000-8099 y 8731→Healthcare · 7370-7379 y 3571-3577 y 3661-3679→Technology ·
4800-4899→Communication Services · 2900-2999 y 1300-1399→Energy · 6500-6599→Real Estate ·
6000-6499 y 6700-6799→Financial Services · 4900-4999→Utilities · 2000-2199 y 5400-5499→Consumer Defensive ·
5200-5999 y 2300-2399 y 3710-3716→Consumer Cyclical · 1000-1299 y 2800-2824→Basic Materials ·
3721(aircraft) y 8742 y 4000-4799 y resto 3xxx→Industrials · sin match→"Other".
> ⚠️ El mapeo tiene casos frontera reales cazados en el probe (8731 biotech→Healthcare, 3721 eVTOL→
> Industrials, 8742 consulting→Industrials). La tabla curada debe cubrirlos; no improvisar por SIC suelto.

**Anti-lookahead:** N/A — estadística descriptiva ex-post; el sector es atemporal (no cambia con el día).

---

## 6 · Plan de ejecución + DoD + verificación

**EPIC S1 — Enriquecimiento de sector (datos)** (1 PR backend/scripts)
- T1.1 `services/sector_service.py`: `sic_to_sector(sic)` (tabla curada) + `resolve_sector(ticker)`
  (Massive `get_overview.sic_code` → fallback `edgar_service`/`get_cik`→submissions.sic → `sic_to_sector`).
- T1.2 `scripts/build_ticker_sector.py`: enriquece el universo (gap≥20 histórico) concurrente (≤16 workers),
  escribe `cold_storage/reference/ticker_sector.parquet`. **Ejecutar el build** (≈2 min).
- T1.3 `cache_service.get_ticker_sector_df()` (loader + memo) y paso 7 en `catchup_gcs.py` (tickers nuevos).
- **DoD:** tests unitarios de `sic_to_sector` (los ejemplos §5 + los frontera del probe); build genera
  parquet con `unknown_pct` reportado; cobertura ≥85% sobre una muestra 90D.

**EPIC S2 — Endpoint** (mismo PR)
- T2.1 `market_analysis_service.get_gaps_by_sector(window, min_gap, metric)` (hot cache + calidad + merge
  sector) → §4.1. `routers/market.py` endpoint fino. Reservar `sector[]` en `build_screener_query` (v2, ignorado si vacío).
- **DoD:** `pytest` contrato §4.1 con fixture; suma de `count` = `total_gaps`; `unknown_pct` correcto.

**EPIC S3 — Frontend** (1 PR)
- T3.1 Quitar panel "Distribución temporal" y `TimingModule`/`TimingChart`/`TimingLegend` de
  `MarketAnalysis.tsx`; quitar `distributions` del tipo y del payload consumido.
- T3.2 `market-analysis/charts.tsx`: `SectorHeatmap` con la viz elegida (§7-D1) — tokens/branding
  existentes (cobre = intensidad; rojo = close-red). Toggle 5D/30D/90D + selector de métrica (patrón
  `SegmentedControl` ya usado). Tooltip por sector (count, close red %, avg gap). Añadir el paquete visx.
- **DoD:** `npm run build` + `tsc` verdes; 4 estados UI; verificado en navegador con datos reales.

Verificación: `cd backend && python -m pytest tests/test_sector.py -q` · `cd frontend && npm run build`.

---

## 7 · Decisiones por tomar

**(D1) Visualización — la más importante, decidir antes de ejecutar.**
La captura de referencia es un **treemap** (rectángulos con área = nº de gaps, el recuadro grande de
Healthcare); la librería que enlazaste, `@visx/heatmap`, es una **rejilla** de celdas (necesita 2
dimensiones). No son lo mismo:
- **Opción T (recomendada) — Treemap** (`@visx/hierarchy`): área = Count, **color = Close Red %** (heat:
  más rojo = más bajista). Replica la captura EXACTA y es "mapa de calor" por color. Mejor para ~11
  sectores con conteos pequeños.
- **Opción H — Heatmap rejilla** (`@visx/heatmap`, lo que enlazaste): filas = sector, columnas = una 2ª
  dimensión (p. ej. franja de gap 20-30/30-50/50-100/>100% o recencia), color = Count. Aporta una
  dimensión extra pero con conteos de 1-4 sale muy escaso; NO se parece a la captura.

Recomiendo **T**. Si prefieres la rejilla de tu enlace, decidimos la 2ª dimensión. *(Esta es la única
decisión que bloquea empezar; el resto se ejecuta con el default.)*

**(D2) Cobertura ~90% — Jesús/Álvaro.** ¿Mostrar el bucket "Sin sector" (recomendado: sí, transparencia)
o filtrarlo del total? El ~5-10% son los micro-caps más oscuros.

**(D3) Taxonomía SIC→sector — Álvaro.** Los 11 sectores Yahoo (implementado) vs otra taxonomía; validar
los casos frontera del §5. Cambiar = editar la tabla curada + re-run del build.

**(D4) "Que filtre por sector" — Jesús.** ¿El sector es solo la agrupación del heatmap (v1) o también un
**filtro** de toda la página (v2, `sector[]` en el screener)? El enriquecimiento de S1 habilita ambos.

**(D5) Métricas del selector — Álvaro.** Count / Close Red % (implementados) + ¿Avg Gap %? ¿Avg Fade?

**(D6) Negocio — Jesús.** Ninguna (admin-only heredado). La IA no opina.
---

## 8 · Log de ejecución (08-jul-2026)

**Backend / datos**
- `services/sector_service.py`: `sic_to_sector` (mapa curado 11 sectores Yahoo, casos frontera del probe) +
  `resolve_sector` (Massive `sic_code` → fallback SEC EDGAR `company_tickers`→CIK→`submissions.sic`).
- `scripts/build_ticker_sector.py`: enriquece el universo (recent-first) → `cold_storage/reference/
  ticker_sector.parquet`. **Ejecutado**: 120d (576 tickers, **99% cobertura**) + histórico completo
  (3.867 tickers, 65% global — la cola son deslistados 2017-24 que ni Massive ni SEC listan; irrelevantes
  para las ventanas 5D/30D/90D). El merge preserva la alta cobertura reciente.
- `cache_service.get_ticker_sector_df()` (loader, TTL 6h) + carga en `main.py` startup (best-effort).
- `market_analysis_service.get_gaps_by_sector(window,min_gap,metric)` + `compute_gaps_by_sector` (pura) +
  endpoint fino `GET /api/market/gaps-by-sector` (`routers/market.py`).
- **Distribución temporal RETIRADA**: fuera `distributions` del payload (`compute_market_analysis`) y del
  contexto de Edgie. `_distribution` queda como código muerto (no referenciado).
- `catchup_gcs.py` paso 7 (`MA_SECTOR_ENABLED`): enriquece tickers nuevos del día.
- Tests: `test_market_analysis.py` 27/27 (sector agrega/ordena, sin-mapa, vacío; SIC→sector; sin distributions).
- Cobertura medida por ventana (endpoint en vivo): 5D 0% · 30D 0.6% · 90D 0.3% sin sector. Latencia warm ~2s.

**Frontend (rejilla 2×2 + treemap)**
- `MarketAnalysis.tsx`: layout `ma-grid` 2 columnas 50% fijas (colapsa a 1 col <900px). Celdas:
  `StatPanel` (Pulso: 5 métricas en filas, sin pills, todas visibles) · `FadeWindowsPanel` ·
  `Avg Change from Open` · `SectorPanel`. Quitados `TimingModule`/`TimingLegend`/`Distribución temporal`.
- `SectorPanel`: toggle ventana 5D/30D/90D (independiente del global) + toggle color Red%/Gap%; min_gap=20 fijo.
- `charts.tsx`: `SectorTreemap` (`@visx/hierarchy`, área=count, color=heat close_red%, tooltip).
- `api.ts`: `getGapsBySector` + tipos; fuera `distributions` de `MarketAnalysisResponse`.
- `@visx/hierarchy@4.0.0` añadido. `tsc` + `npm run build` verdes; eslint limpio en los ficheros tocados.

## 9 · Pendiente / decisiones (actualizado)
- **Backfill de cobertura de la cola histórica**: 65% global por deslistados antiguos. Si se quieren ventanas
  >90D con sector, añadir una 3ª fuente (Finviz/OpenFIGI) o aceptar "Sin sector" en la cola. No urge (la UI usa ≤90D).
- **"Other" ~5-7%**: SIC con código pero sin mapear en `sic_to_sector`. Refinar la tabla curada (D3, Álvaro).
- **D4 (Jesús)**: ¿sector como FILTRO de toda la página? El enriquecimiento ya lo habilita (`sector[]` reservado).
- **Refresco en prod**: paso 7 del catchup (`MA_SECTOR_ENABLED`) — verificar en Coolify tras deploy.
