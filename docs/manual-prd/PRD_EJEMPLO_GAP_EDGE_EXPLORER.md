# PRD de ejemplo — Gap Edge Explorer (submódulo de Market Analysis)

> **Qué es este documento.** Un PRD **completo y real**, escrito siguiendo el
> [Manual del PM](GUIA_PRD_EJECUTABLE.md). Es el ejemplo de referencia de "cómo se ve un
> paquete de requerimientos impecable" — el que la IA puede construir a la primera. Está
> **anclado en código real** del repo (rama `api-jesus`); cada afirmación cita su fuente.
>
> **Por qué este feature.** El módulo de Market Analysis hoy tiene dos piezas: el **screener
> diario** (movers del último día, `routers/screener.py`) y las **gap-stats por ticker**
> (`/api/ticker-analysis/{ticker}/gap-stats`). Falta la vista que un short-seller de small
> caps necesita para decidir **qué setups tienen ventaja estadística a nivel de mercado**: la
> tasa base de fade/continuación de los gaps agregada sobre TODO el universo, filtrable. Eso
> es **Gap Edge Explorer**. Reusa las definiciones de stat que ya existen (no las reinventa) y
> aprovecha el hot cache en RAM para ser instantáneo.
>
> Este PRD va en **un solo documento** (suite 00–07 en línea), tal como sugiere el manual para
> features de tamaño medio. Si se aprueba, puede partirse a `docs/gap-edge-explorer/`.

---

## Índice del PRD

- [00 · Índice y trazabilidad (fuentes auditadas)](#s00)
- [01 · Viabilidad (reality check + veredicto)](#s01)
- [02 · PRD: qué, para quién, nomenclatura](#s02)
- [03 · Contrato de datos (request/response + errores)](#s03)
- [04 · UI y componentes (pantalla, estados, reuso)](#s04)
- [05 · Arquitectura (dónde vive el código)](#s05)
- [06 · Prompt maestro de ejecución (guion del loop)](#s06)
- [07 · Decisiones abiertas](#s07)

---

<a id="s00"></a>
## 00 · Índice y trazabilidad

**Feature:** Gap Edge Explorer — panel de estadísticas agregadas de comportamiento de gaps
sobre todo el universo histórico, filtrable por rango de gap, precio, volumen y sesión, con
desglose por gap day / gap+1 / gap+2. **Estado:** PLAN.

**Visión en una frase:** *"Dame, sobre todos los gaps del histórico que cumplan estos filtros,
con qué frecuencia fadean vs continúan y cuánto — para saber qué setup tiene edge antes de
construir la estrategia."*

### Fuentes auditadas (verdad anclada en código)

| Pieza real | Fichero | Qué aporta a este PRD |
|---|---|---|
| Tabla diaria precomputada | `daily_metrics` (vía `app/database.py`) | columnas de gap/PM/RTH que alimentan las stats |
| Definiciones de stat por ticker | `app/routers/ticker_analysis.py` → `get_gap_stats_all_days()` (línea 443) y endpoint `/{ticker}/gap-stats` (línea 1221) | **las claves de stat que reusamos** (`high_rth_spike_avg`, `pm_fade_avg`…) y la estructura `gap_stats` / `_plus_1` / `_plus_2` |
| Hot cache en RAM | `app/services/cache_service.py` (`get_hot_daily_cache()`, líneas 76, 113–132) | universo de gaps en RAM con `close_red`, `high_spike_pct`, `low_spike_pct`, `open_lt_vwap` ya derivados → **fast path** |
| Stats agregadas existentes | `app/services/processor_service.py` (líneas 145, 185–198) | patrón de agregación (`count`, `pmh_fade_to_open_pct`, `avg_volume`…) a imitar |
| Endpoint diario actual | `app/routers/screener.py` (`GET /api/screener/daily`, línea 29) + cache TTL 5 min | **dónde añadir** el nuevo endpoint y el patrón de caché en proceso |
| Pantalla del screener | `frontend/src/components/Screener.tsx` | dónde colgar la nueva vista; tabs ya existentes |
| Fetch centralizado | `frontend/src/lib/api.ts` (`getScreenerDaily`, `getTickerGapStats`, línea 346/443) | patrón para añadir `getGapEdge` |
| Filtros UI reusables | `frontend/src/components/AdvancedFilterPanel.tsx`, `FilterPanel.tsx`, `DataGrid.tsx` | componentes a reusar |
| Tokens visuales | `.agent/EDGECUTE_DESIGN_SYSTEM.md` | colores, tipografía, P&L (profit/loss) |
| Reglas de ingeniería | `.agent/CODING_RULES.md` | routers finos, queries parametrizadas, no tocar schema |

**Columnas reales de `daily_metrics` usadas** (verificadas en `cache_service.py` líneas 139–161):
`ticker, timestamp, gap_pct, pmh_gap_pct, pmh_fade_pct, rth_fade_pct, open, close, high, low,
volume, pm_volume, pm_high, pm_low, pm_high_time, pm_low_time, rth_open, rth_close, rth_high,
rth_low, rth_volume, rth_run_pct, day_return_pct, rth_range_pct, prev_close, last_close,
close_1559, eod_volume, open_lt_vwap`. Derivadas en hot cache: `close_red, high_spike_pct,
low_spike_pct`.

---

<a id="s01"></a>
## 01 · Viabilidad

### 1.1 Restricciones y coste

- **Volumen de datos.** El universo de gaps relevante ya vive en RAM: el hot cache carga
  `daily_metrics WHERE gap_pct >= 10.0` (~decenas de miles de filas, `cache_service.py:76`).
  Una agregación con filtros sobre ese DataFrame de pandas es **O(filas) en memoria**, sin GCS.
- **Latencia esperada.** Si los filtros caen dentro del hot cache (`gap_pct >= 10` o
  `pmh_gap_pct >= 20`), la respuesta es **< 100 ms** (mismo fast path que el screener,
  `.agent/ARCHITECTURE.md`). Si el filtro pide gaps por debajo del umbral del cache
  (`gap_pct < 10`), hay que ir a `daily_metrics` completo vía DuckDB → **segundos**; ese caso
  se marca como "fuera de fast path" (ver 1.2).
- **Payload.** La respuesta es un objeto de métricas agregadas + opcionalmente una distribución
  en buckets (histograma). **Pocos KB.** No devuelve filas crudas por defecto (eso sería fuga
  de dato masivo y lento de pintar).
- **Aislamiento.** No expone OHLCV crudo ni el motor; solo estadísticas derivadas. No toca la
  lista "no tocar" (`CODING_RULES.md`): no modifica `daily_metrics`, ni el engine, ni Parquet.

### 1.2 Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Filtros piden `gap_pct < 10` (fuera del hot cache) | Query lenta a GCS | Default mínimo `gap_min = 10`; si se pide menos, devolver `meta.fast_path=false` y permitir, pero avisar en UI |
| Muestra pequeña → stats engañosas | Decisión de trading sobre ruido | `min_sample` (default 30); marcar `low_confidence=true` si `count < min_sample` |
| Confundir base rate con señal tradeable | Mal uso del feature | Texto en UI + nota en doc 02 §8; cualquier estrategia derivada respeta `look_ahead_prevention` |
| `pm_high`/`pm_low` nulos (sin datos PM) | Stats PMH sesgadas | Excluir esas filas SOLO de las stats que dependen de PM; reportar `pm_coverage` |

### 1.3 Veredicto

**Viable — con fast path.** El dato ya está en RAM y las definiciones de stat ya existen; el
trabajo es agregación + UI. **Recomendación:** construir el MVP restringido al hot cache
(`gap_min >= 10`) y dejar el camino lento (GCS) como mejora posterior.

---

<a id="s02"></a>
## 02 · PRD: qué, para quién, nomenclatura

### 2.1 Usuarios

| Perfil | Necesidad | Cómo lo sirve Gap Edge Explorer |
|---|---|---|
| **Short-seller de small caps (Jaume, usuario principal)** | Saber qué setups de gap tienen ventaja antes de diseñar la estrategia | Tasa base de fade/continuación agregada y filtrable |
| **Trader que itera estrategias** | Validar una hipótesis ("gaps >50% en <$5 fadean más") con un número, no una corazonada | Filtra y lee `neg_close_freq`, `pm_fade_avg`, etc. |
| **Nosotros (producto)** | Diferenciador frente a Flash Research | Vista de edge de mercado que el competidor no ofrece igual |

### 2.2 Jobs-to-be-done

1. **Filtrar** el universo de gaps por: rango de gap %, rango de precio (open), volumen mínimo
   (RTH y/o PM), y rango de fechas.
2. **Leer** las stats agregadas de ese subconjunto, desglosadas por **gap day / gap+1 / gap+2**.
3. **Comparar** rápidamente fade vs continuación (las dos caras del short).
4. **(Opcional) Ver** la distribución (histograma de `day_return_pct` o de `gap_pct`).
5. **Saltar** desde un setup interesante al screener/estrategia (handoff a otros módulos).

### 2.3 Alcance del MVP (lo que SÍ entra)

- Endpoint `GET /api/screener/gap-edge` con filtros (ver doc 03).
- Cálculo agregado sobre el hot cache reusando las **mismas definiciones** que
  `get_gap_stats_all_days()`.
- Desglose `gap_day` / `gap_plus_1` / `gap_plus_2`.
- Métrica de confianza (`count`, `low_confidence`, `pm_coverage`).
- Nueva pestaña/vista en `Screener.tsx` con panel de filtros (reuso) + tarjetas de stats +
  (opcional) un histograma.
- Caché en proceso TTL 5 min (mismo patrón que `screener.py`).

### 2.4 Fase 2 y Fuera de alcance

**Fase 2 — NO se construye ahora; el MVP se diseña para no bloquearla.** Decisión que impone hoy:

| Idea (Fase 2) | Qué decisión impone YA en el MVP |
|---|---|
| **Exportar las filas crudas ticker–día** | La respuesta MVP es solo agregada, pero el service filtra el DataFrame completo → exportar luego es trivial, sin recalcular. |
| **`gap_min < 10` con query a GCS optimizada** | El MVP **permite pedirlo** pero marca `meta.fast_path=false`; el contrato ya contempla el flag, así que optimizar el camino lento no rompe clientes. |
| **"Screens guardados" de gap-edge** | Los filtros van en la URL (compartibles); persistirlos luego reutiliza ese mismo objeto de filtros. |

**Fuera de alcance — NO se hará (o es otro feature):**
- ❌ Datos en tiempo real / pre-market en vivo (aquí solo histórico; el screener reserva esas tabs).
- ❌ Ejecutar backtest o crear estrategia desde aquí (solo un enlace de navegación a otros módulos).

**Diferido a Jesús (negocio):**
- ❌ **Gating/monetización** (qué se bloquea, a quién): **el PRD no decide política** (doc 07).

### 2.5 Glosario de dominio (nomenclatura OFICIAL — usar exactamente estos nombres)

> Reusamos las claves de `get_gap_stats_all_days()` (`ticker_analysis.py:443`). **No renombrar.**

| Término | Definición operativa | Unidad | Fuente |
|---|---|---|---|
| **gap day** (`gap_day`) | Día del evento de gap (la fila base) | — | `apply_day`, glosario |
| **gap+1 / gap+2** (`gap_plus_1`, `gap_plus_2`) | Día siguiente / 2 días después del gap day del mismo ticker | — | `get_gap_stats_all_days` offsets 1,2 |
| **runner day** | Día que cualifica como gap: `pmh_gap_pct >= 20` (fallback `gap_pct >= 20`) | — | `ticker_analysis.py:527–533` |
| `gap_pct` | `(open - prev_close) / prev_close * 100` | % | `daily_metrics`, `ticker_analysis.py:523` |
| `pmh_gap_pct` | Gap medido contra el PMH | % | `daily_metrics` |
| **fade (PMH)** → `pm_fade_avg` | Media de `pmh_fade_pct`: cuánto retrocede el precio desde el PMH | % | `daily_metrics.pmh_fade_pct` |
| **fade (RTH high)** → `rthh_fade_avg` | Media de `rth_fade_pct`: retroceso desde el RTH high | % | `daily_metrics.rth_fade_pct` |
| **high spike** → `high_rth_spike_avg` | Media de `high_spike_pct = (rth_high - open)/open*100` | % | `cache_service.py:118–121` |
| **low spike** → `low_rth_spike_avg` | Media de `low_spike_pct = (rth_low - open)/open*100` | % | `cache_service.py:124–127` |
| **freq. cierre rojo** → `neg_close_freq` | % de días con `close < open` (`close_red`) | % | `cache_service.py:114–116` |
| **freq. cierre > PMH** → `close_above_pmh_freq` | % de días con `rth_close > pm_high` (continuación) | % | clave de `get_gap_stats_all_days` |
| **freq. cierre < VWAP** → `close_below_vwap_freq` | % de días con `open_lt_vwap` / cierre bajo VWAP | % | `cache_service.py:131–132` (`open_lt_vwap`) |
| `count` | Nº de filas (ticker–día) en la muestra tras filtros | entero | `processor_service.py:185` |
| `low_confidence` | `true` si `count < min_sample` | bool | nuevo (este PRD) |
| `pm_coverage` | % de filas con `pm_high` no nulo (fiabilidad de stats PM) | % | nuevo (este PRD) |

### 2.6 Reglas de trading (las 5 cosas por regla)

**Regla — qué es un "fade" para `neg_close_freq` (la métrica estrella del short):**
- **Nombre:** `neg_close_freq`.
- **Definición:** proporción de filas donde `rth_close < rth_open` (día rojo), reusando la
  derivación `close_red` del hot cache (`cache_service.py:114`). Expresada en %.
- **Unidad/rango:** % en `[0, 100]`.
- **Sesión:** RTH (open/close de la sesión regular).
- **Edge case:** filas con `rth_open` o `rth_close` nulos se **excluyen del denominador** de
  esta métrica (no cuentan como ni rojo ni verde).

**Regla — continuación (`close_above_pmh_freq`):**
- **Nombre:** `close_above_pmh_freq`.
- **Definición:** % de filas con `rth_close > pm_high` (el precio aguantó por encima del máximo
  pre-market hasta el cierre → señal de continuación, mala para el short).
- **Unidad/rango:** % en `[0, 100]`.
- **Sesión:** compara RTH close contra PM high.
- **Edge case:** filas con `pm_high` nulo se excluyen de esta métrica y reducen `pm_coverage`.

**Anti-lookahead (sagrado).** Estas estadísticas son **descriptivas e históricas**: cada fila
se resuelve con datos **de su propio día** (gap day) o de un día posterior **etiquetado como
tal** (gap+1, gap+2). **No** se usa información de gap+1 para describir el gap day. Además, en
la UI debe quedar claro que **una tasa base no es una señal tradeable**: si el usuario diseña
una estrategia a partir de este edge, la entrada en el backtester sigue obligada a
`look_ahead_prevention = true` (desplaza señales 1 barra; `BUSINESS_LOGIC.md`).

### 2.7 Métricas de éxito del feature

- El panel responde en **< 200 ms** para filtros dentro del hot cache.
- Las stats coinciden (±0.1) con las de `get_gap_stats_all_days()` cuando se filtra por un
  único ticker (test de consistencia — misma definición, misma cifra).
- Un usuario filtra y lee el edge de un setup **sin leer documentación**.

### 2.8 Principios de diseño para el agente

1. **Reusar definiciones, no reinventarlas.** Las claves de stat son las de
   `get_gap_stats_all_days()`. Si una difiere, gana el código existente.
2. **El backend manda.** Si una columna citada aquí no existe en `daily_metrics`, parar y
   anotar en doc 07; no inventar la columna.
3. **No tocar el schema** de `daily_metrics` ni el hot cache (solo leer).
4. **Router fino, lógica en service** (`CODING_RULES.md`).

---

<a id="s03"></a>
## 03 · Contrato de datos

### 3.1 Request — `GET /api/screener/gap-edge`

Query params (todos opcionales salvo donde se indica; mismos nombres en front y back):

| Param | Tipo | Unidad | Default | Semántica |
|---|---|---|---|---|
| `gap_min` | float | % | `10` | gap mínimo (`gap_pct >= gap_min`). < 10 ⇒ fuera de fast path |
| `gap_max` | float | % | `null` | gap máximo (`gap_pct <= gap_max`) si se da |
| `price_min` | float | USD | `null` | `open >= price_min` |
| `price_max` | float | USD | `null` | `open <= price_max` |
| `rth_vol_min` | int | shares | `null` | `rth_volume >= rth_vol_min` |
| `pm_vol_min` | int | shares | `null` | `pm_volume >= pm_vol_min` |
| `date_from` | str | `YYYY-MM-DD` | `null` | `timestamp >= date_from` |
| `date_to` | str | `YYYY-MM-DD` | `null` | `timestamp <= date_to` |
| `min_sample` | int | filas | `30` | umbral para `low_confidence` |
| `include_histogram` | bool | — | `false` | si `true`, añade `histogram` de `day_return_pct` |

**Validación:** `gap_min <= gap_max` si ambos; `price_min <= price_max`; fechas `YYYY-MM-DD`
válidas; numéricos `>= 0`. Entrada inválida → `400` (ver 3.3). **Nunca** concatenar params en
SQL: filtrar el DataFrame del hot cache en pandas o, en el camino lento, query parametrizada
con `?` (`CODING_RULES.md`).

### 3.2 Response (200) — forma exacta

```jsonc
{
  "filters_applied": {
    "gap_min": 20, "gap_max": null, "price_min": 1, "price_max": 10,
    "rth_vol_min": 1000000, "pm_vol_min": null,
    "date_from": null, "date_to": null, "min_sample": 30
  },
  "meta": {
    "fast_path": true,            // false si gap_min < 10 (se fue a GCS)
    "computed_at": 1750000000,    // epoch segundos
    "source": "hot_cache"         // "hot_cache" | "database"
  },
  "gap_day":   { /* StatBlock */ },
  "gap_plus_1":{ /* StatBlock */ },
  "gap_plus_2":{ /* StatBlock */ },
  "histogram": null               // o { "bins": [...], "counts": [...] } si include_histogram
}
```

**`StatBlock`** (claves reusadas de `get_gap_stats_all_days()` + las nuevas de confianza):

```jsonc
{
  "count": 1432,                 // filas en la muestra
  "low_confidence": false,       // count < min_sample
  "pm_coverage": 97.4,           // % filas con pm_high no nulo
  "high_rth_spike_avg": 14.2,    // %
  "low_rth_spike_avg": -9.8,     // %
  "pm_fade_avg": 22.1,           // % (pmh_fade_pct medio)
  "rthh_fade_avg": 31.5,         // % (rth_fade_pct medio)
  "neg_close_freq": 63.7,        // % días rojos (fade) -> clave para el short
  "close_above_pmh_freq": 18.2,  // % continuación
  "close_below_vwap_freq": 71.0  // %
}
```

> Tipos: `count` entero; `low_confidence` bool; el resto floats redondeados a 1–2 decimales.
> Cualquier media sobre muestra vacía ⇒ `null` (no `0`, para no mentir un "0%"). `count: 0` ⇒
> `low_confidence: true` y todas las medias `null` (igual que el `empty_stats` de
> `ticker_analysis.py:496–507`).

### 3.3 Errores (catálogo cerrado, sin filtrar internals)

| Código | Cuándo | Body |
|---|---|---|
| `400` | Param inválido (rango invertido, fecha mal formada, número negativo) | `{"error":{"code":"invalid_filters","message":"...","details":{...}}}` |
| `200` + `low_confidence` | Muestra pequeña pero válida | no es error; se sirve con la bandera |
| `500` | Fallo interno | `{"error":{"code":"internal_error","message":"Unexpected error"}}` — **sin** `str(exc)` ni traza |

> Nota: `main.py` hoy filtra `str(exc)` en el handler global. Este endpoint **no** debe
> propagar el mensaje interno; captura y devuelve el body genérico (alineado con la doctrina
> del suite b2d-gateway "leak nothing").

### 3.4 Ejemplo válido (request → response)

`GET /api/screener/gap-edge?gap_min=20&price_min=1&price_max=10&rth_vol_min=1000000`

→ devuelve un `gap_day.neg_close_freq` ≈ 63.7 sobre `count` ≈ 1432 (cifras ilustrativas):
"de los gaps ≥20% en valores de $1–$10 con >1M de volumen RTH, ~64% cerraron rojos".

---

<a id="s04"></a>
## 04 · UI y componentes

### 4.1 Dónde vive

Nueva **vista "Gap Edge"** dentro de `frontend/src/components/Screener.tsx` (o un componente
hijo `GapEdgePanel.tsx` montado por el Screener). Se añade como una sección/tab junto a las
tabs existentes (`gainers | losers | premarket | aftermarket`). El acceso es la página
`/screener` ya existente.

### 4.2 Wireframe textual

```
┌─ Market Analysis ▸ Gap Edge ──────────────────────────────────────┐
│ [1] Panel de filtros: gap min/max · precio min/max · vol RTH/PM ·  │
│     rango de fechas · [Aplicar]                                    │
├───────────────────────────────────────────────────────────────────┤
│ [2] Selector de offset:  ( Gap day ) ( Gap+1 ) ( Gap+2 )          │
├───────────────────────────────────────────────────────────────────┤
│ [3] Fila de tarjetas de stat (del StatBlock del offset elegido):  │
│   ┌ Días rojos (fade) ┐ ┌ Cierre>PMH (cont.) ┐ ┌ Fade PMH medio ┐ │
│   │   63.7%           │ │   18.2%            │ │   22.1%        │ │
│   └───────────────────┘ └────────────────────┘ └───────────────┘ │
│   ┌ High spike medio ┐ ┌ Low spike medio ┐ ┌ Cierre<VWAP ┐       │
│   │  +14.2%          │ │  -9.8%          │ │  71.0%      │       │
│   └──────────────────┘ └─────────────────┘ └─────────────┘       │
│   muestra: count=1432 · pm_coverage 97% · [⚠ baja confianza si <30]│
├───────────────────────────────────────────────────────────────────┤
│ [4] (opcional) Histograma de day_return_pct                       │
└───────────────────────────────────────────────────────────────────┘
```

- **[1]** reusa el patrón de `AdvancedFilterPanel.tsx` / `FilterPanel.tsx`.
- **[3]** reusa `MetricsCard` (`components/backtester/MetricsCard.tsx`) para cada tarjeta.
- **[4]** reusa `Chart`/recharts si se incluye el histograma (opcional MVP).

### 4.3 Los 4 estados obligatorios

| Estado | Qué se ve |
|---|---|
| **Loading** | Skeleton de las 6 tarjetas + spinner `Loader2` (ya importado en `Screener.tsx`) |
| **Empty** | `count: 0` → mensaje "Ningún gap cumple estos filtros. Prueba a ampliar el rango." + CTA reset |
| **Error** | `400`/`500` → `AlertCircle` (ya importado) + mensaje accionable; reintento |
| **Success** | Las tarjetas con cifras; si `low_confidence` → badge ⚠ "muestra pequeña (N<min)"; si `fast_path:false` → nota "consulta lenta (fuera de caché)" |

### 4.4 Comportamiento

- **Datos** vía `lib/api.ts`: nueva función `getGapEdge(params, signal)` que llama
  `/screener/gap-edge?...` siguiendo el patrón de `getScreenerDaily` (línea 443) y
  `getTickerGapStats` (línea 346). **Nunca** `fetch` suelto (`CODING_RULES.md`).
- **Estado en URL**: los filtros se reflejan en query params (compartible/recargable).
- **Cambiar de offset** (gap_day/+1/+2) **no** re-llama al backend: la respuesta ya trae los
  tres bloques; solo cambia qué bloque se pinta.
- **Debounce** de 300 ms al teclear filtros antes de re-llamar.

### 4.5 Estilo (tokens del design system)

- Tarjetas: `MetricsCard` estándar (bg `--ec-bg-surface #1C1E21`, borde `--ec-border`).
- **Color semántico de trading:** para el short, "días rojos / fade alto" es **bueno** →
  usar `--ec-profit #4A9D7F`; "continuación / cierre>PMH alto" es **malo para el short** →
  `--ec-loss #C94D3F`. (Decisión de color = ver doc 07 §B, reversible.)
- Tipografía: valores grandes en General Sans 600 (NUNCA Fraunces para *filter values*,
  `EDGECUTE_DESIGN_SYSTEM.md`); etiquetas en General Sans 700 9px uppercase.
- Cobre `--ec-copper` SOLO para marca/eyebrow, nunca para las cifras.

### 4.6 (Opcional) Asistible por Edgie

Si se quiere que el asistente pueda pilotar este panel, registrar
`screener.set_gap_edge_filters` siguiendo `docs/assistant/guia_dev_componente_asistible.md`
(schema con `gap_min`, `price_min`… `confirm: 'auto'`, handler que usa los mismos setters que
la UI). **Fuera del MVP salvo que se pida** (doc 07 §A).

---

<a id="s05"></a>
## 05 · Arquitectura

### 5.1 Ficheros (nuevos y tocados)

**Backend**
- `app/routers/screener.py` — **añadir** `GET /api/screener/gap-edge` (router fino: valida
  params, llama al service, aplica caché TTL 5 min como el `/daily`). No meter lógica aquí.
- `app/services/gap_edge_service.py` — **nuevo**. Toda la lógica: lee `get_hot_daily_cache()`,
  aplica filtros en pandas, computa los tres `StatBlock` reusando las definiciones de
  `get_gap_stats_all_days()`. Camino lento (GCS) detrás de un flag.
- *(Opcional)* extraer a una función compartida las definiciones de stat para que el endpoint
  por-ticker y este compartan **una sola** implementación (evita drift). Si se hace, mover la
  lógica común a `gap_edge_service.py` y que `ticker_analysis` la importe — **sin cambiar** su
  contrato de salida. Si es arriesgado, duplicar las fórmulas con un test que verifique que
  coinciden (consistencia, doc 02 §2.7).

**Frontend**
- `frontend/src/lib/api.ts` — **añadir** `getGapEdge()` + tipos `GapEdgeResponse`, `StatBlock`.
- `frontend/src/components/GapEdgePanel.tsx` — **nuevo**. La vista.
- `frontend/src/components/Screener.tsx` — **tocar**: montar la nueva vista/tab.

### 5.2 Flujo end-to-end

```
UI (GapEdgePanel) → lib/api.ts getGapEdge() → GET /api/screener/gap-edge
  → routers/screener.py (valida + caché) → services/gap_edge_service.py
     → cache_service.get_hot_daily_cache() [RAM]  (fast path)
     → filtra (pandas) → computa 3 StatBlock → vuelve JSON
  → UI pinta MetricsCards
```

### 5.3 Lista "no tocar" — cómo se respeta

- **No** se modifica el schema de `daily_metrics` ni el hot cache: solo lectura.
- **No** se toca `engine.py`/`indicators.py`/`portfolio_sim.py`: este feature no usa el motor.
- Reutiliza el hot cache existente; si necesitara nuevas columnas derivadas, se añadirían en
  `cache_service.py` con consenso (no en este MVP).

### 5.4 Decisiones técnicas (y alternativas descartadas)

- **Caché en proceso (dict + lock, TTL 5 min)** como `screener.py`. *Descartado Redis para el
  MVP* (añade infra; el `/daily` no lo necesita).
- **Filtrado en pandas sobre el hot cache** en vez de SQL. *Descartado SQL por defecto* porque
  el dato ya está en RAM y evita ida/vuelta a GCS.

---

<a id="s06"></a>
## 06 · Prompt maestro de ejecución

> Esto es lo que se pega en Claude Code (goal/loop). Tareas atómicas, TDD, comando por tarea.
> **No avanzar si el comando no pasa.**

### 0. Contexto obligatorio antes de tocar nada

1. Este documento (`docs/manual-prd/PRD_EJEMPLO_GAP_EDGE_EXPLORER.md`), entero.
2. `app/routers/ticker_analysis.py` → `get_gap_stats_all_days()` (def en línea 443) y el
   `empty_stats` (1221+) — **fuente de las definiciones de stat**.
3. `app/services/cache_service.py` — `get_hot_daily_cache()` y columnas derivadas (113–161).
4. `app/routers/screener.py` — patrón de endpoint + caché.
5. `frontend/src/lib/api.ts` (`getScreenerDaily`, `getTickerGapStats`) y
   `frontend/src/components/Screener.tsx`.
6. `.agent/CODING_RULES.md` y `.agent/EDGECUTE_DESIGN_SYSTEM.md`.

### 1. Restricciones globales (no negociables)

- Router fino; toda la lógica en `services/gap_edge_service.py`.
- Solo **lectura** de `daily_metrics`/hot cache. No modificar su schema.
- Filtrado en pandas o, en camino lento, **query parametrizada con `?`** (jamás concatenar).
- Errores: nunca propagar `str(exc)` ni trazas; body genérico.
- **Reusar** las definiciones de stat de `get_gap_stats_all_days()`; si difieren, gana el
  código existente y se anota.
- TDD: test primero. Mover, no borrar (a `_archive/`). Commits convencionales.
- No tocar `main.py` salvo para registrar el router si hiciera falta (ya está incluido vía
  `screener.py`).

### 2. Secuenciación atómica

**EPIC A — Backend**

- **A1. Service esqueleto + filtros.** Crear `services/gap_edge_service.py` con
  `compute_gap_edge(filters) -> dict`. Lee el hot cache, aplica filtros, devuelve `count` y
  `filters_applied`/`meta`.
  - *Test (primero):* `tests/test_gap_edge_service.py` — con un DataFrame mock de 5 filas,
    `gap_min=20` deja las correctas; `count` correcto.
  - *Verif:* `cd backend && source .venv/bin/activate && pytest tests/test_gap_edge_service.py -q`

- **A2. Cálculo de StatBlock (reuso de definiciones).** Implementar `neg_close_freq`,
  `close_above_pmh_freq`, `close_below_vwap_freq`, `pm_fade_avg`, `rthh_fade_avg`,
  `high_rth_spike_avg`, `low_rth_spike_avg`, `pm_coverage`, `low_confidence`. Muestra vacía ⇒
  medias `null`.
  - *Test:* casos numéricos cerrados (ver §6.4 abajo) + caso `count=0` ⇒ todas `null`,
    `low_confidence=true`.
  - *Verif:* `pytest tests/test_gap_edge_service.py -q`

- **A3. Offsets gap_day/+1/+2.** Para cada runner day (`pmh_gap_pct>=20` fallback
  `gap_pct>=20`), construir las muestras de offset 0/1/2 por ticker (misma lógica que
  `ticker_analysis.py:543–558`), y un `StatBlock` por offset.
  - *Test:* mock con 1 ticker y 3 días consecutivos ⇒ gap_plus_1/2 apuntan a los días
    correctos.
  - *Verif:* `pytest tests/test_gap_edge_service.py -q`

- **A4. Endpoint + caché.** En `routers/screener.py`: `GET /api/screener/gap-edge` que valida
  params (400 en inválidos), llama al service, cachea 5 min, sanea errores (500 genérico).
  - *Test:* `tests/test_gap_edge_endpoint.py` — 200 con forma correcta; `gap_min>gap_max` ⇒
    400; sin filtros ⇒ usa defaults.
  - *Verif:* `pytest tests/test_gap_edge_endpoint.py -q` y arranque
    `uvicorn app.main:app --port 8000` + `curl 'localhost:8000/api/screener/gap-edge?gap_min=20'`

- **A5. Test de consistencia con el por-ticker.** Filtrando por un único ticker, las stats del
  `gap_day` deben coincidir (±0.1) con `get_gap_stats_all_days(ticker)["gap_stats"]`.
  - *Verif:* `pytest tests/test_gap_edge_consistency.py -q`

**EPIC B — Frontend**

- **B1. API client + tipos.** `getGapEdge()` y tipos en `lib/api.ts` (patrón de
  `getScreenerDaily`). *Verif:* `cd frontend && npm run build`.
- **B2. GapEdgePanel (estados).** Componente con los 4 estados (loading/empty/error/success),
  filtros (reuso `AdvancedFilterPanel`), tarjetas (reuso `MetricsCard`), selector de offset
  client-side. *Verif:* `npm run build` y `npm run dev` → la vista renderiza con datos reales.
- **B3. Montaje en Screener.** Añadir la vista/tab "Gap Edge" en `Screener.tsx`.
  *Verif:* `npm run build`.
- **B4. (opcional) Histograma** si `include_histogram`. *Verif:* `npm run build`.

### 3. Definition of Done

**Por tarea:** test antes y en verde · comando de verificación pasa · sin regresiones
(`pytest` global + `npm run build`) · no se tocó schema/engine · commit convencional.

**Global:** endpoint responde con la forma del doc 03 · stats consistentes con el por-ticker
(A5) · 4 estados de UI funcionan · `low_confidence`/`fast_path`/`pm_coverage` correctos ·
filtros en URL · demoable en `/screener`.

### 4. Comandos de verificación

```bash
# Backend
cd backend && source .venv/bin/activate
pytest tests/test_gap_edge_service.py tests/test_gap_edge_endpoint.py tests/test_gap_edge_consistency.py -q
pytest tests/ -q                         # sin regresiones
uvicorn app.main:app --reload --port 8000
curl 'http://localhost:8000/api/screener/gap-edge?gap_min=20&price_min=1&price_max=10'

# Frontend
cd frontend && npm install && npm run build && npm run lint && npm run dev
```

### 5. Orden de PRs

1. **PR-1**: EPIC A (service + endpoint + tests). Demoable por `curl`.
2. **PR-2**: EPIC B (UI). 
3. *(v2)*: camino lento GCS, export, screens guardados, asistible Edgie.

> Jesús trabaja en su rama; los merges los hace otra persona. No pushear a `main` ni mergear
> desde el loop.

### 6.4 Casos numéricos cerrados (para los tests de A2)

Muestra mock (gap day) de 4 filas:

| ticker | rth_open | rth_close | pm_high | gap_pct |
|---|---|---|---|---|
| AAA | 10.0 | 9.0 | 11.0 | 30 |
| BBB | 5.0 | 5.5 | 5.2 | 25 |
| CCC | 8.0 | 7.0 | 9.0 | 40 |
| DDD | 4.0 | 4.0 | null | 22 |

- `neg_close_freq`: rojos = AAA, CCC (close<open). DDD (close==open) **no** es rojo. BBB verde.
  Denominador = 4 → **50.0%**.
- `close_above_pmh_freq`: ninguno cierra > pm_high (AAA 9<11, BBB 5.5>5.2 ✅, CCC 7<9, DDD pm
  null excluido). De 3 con pm_high → BBB ✅ → **33.3%**.
- `pm_coverage`: 3 de 4 con pm_high → **75.0%**.
- `count`: 4. `low_confidence` (min_sample=30): **true**.

---

<a id="s07"></a>
## 07 · Decisiones abiertas

### A. Decisiones de PRODUCTO (dueño: Jesús/Jaume)

- **A1. Color semántico.** ¿"días rojos/fade" en verde (bueno-para-short) o respetamos el
  convenio bursátil (rojo = bajista)? Recomendación: verde=bueno-para-short con leyenda clara.
  *Decisión de UX/producto, no técnica.*
- **A2. ¿Asistible por Edgie en el MVP?** Recomendación: no, v2.
- **A3. Gating/monetización** (¿este panel es premium? ¿límite de consultas?): **DIFERIDO a
  Jesús.** El PRD no decide política; si hace falta, se añade el hook de gating como mecanismo
  (igual que en el suite b2d-gateway), pero **no** se marca nada como "firmado" sin su OK.

### B. Defaults técnicos reversibles (los asume la IA)

- **B1.** `gap_min` default = 10 (alineado al hot cache). Reversible.
- **B2.** `min_sample` default = 30. Reversible.
- **B3.** Caché en proceso 5 min (no Redis) en el MVP. Reversible.
- **B4.** Histograma opcional y off por defecto. Reversible.

---

> **Cómo leer este ejemplo.** Fíjate en que **cada número tiene unidad**, **cada término existe
> en el código** (con su `fichero:línea`), **cada edge case está resuelto**, el **anti-lookahead
> está declarado**, hay **casos numéricos cerrados** que se vuelven tests, y la **monetización
> queda diferida**. Eso es un PRD que la IA construye a la primera. El método completo está en
> el [Manual del PM](GUIA_PRD_EJECUTABLE.md).
>
> Este ejemplo es un **submódulo que reusa código existente**. Para ver cómo se especifica un
> **área nueva (greenfield)** desde cero —con modelo de datos, persistencia por usuario, auth y
> la entrevista agente↔PM incluida—, mira el [PRD del Journal](PRD_EJEMPLO_JOURNAL.md).
