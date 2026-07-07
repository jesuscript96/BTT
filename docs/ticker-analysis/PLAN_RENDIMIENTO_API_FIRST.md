# Ticker Analysis — Análisis de rendimiento y plan API-first

> **Alcance**: página Ticker Analysis (`frontend/src/components/TickerAnalysis.tsx`,
> `backend/app/routers/ticker_analysis.py`) y su relación con Edgie
> (`backend/app/routers/assistant.py`, `app/services/edgar_service.py`).
> **Fuera de alcance**: backtester, screener, ingesta, WebSocket. No se tocan.
>
> Fecha del análisis: 2026-07-07 · Rama: `ticker-analysis`
>
> **ESTADO: ✅ IMPLEMENTADO COMPLETO (2026-07-07, mismo día).** Los 5 PRs del §6
> aplicados en la rama `ticker-analysis` (working tree, sin commits). Decisiones
> de Jesús incorporadas: (1) float = enrichment no bloqueante, (2) industry =
> `sic_description` Massive + sector vía enrichment yfinance, (3) informe Edgie
> cacheado por ticker+día con botón Regenerar, (4) rate limits sin restricción
> (plan Individual top). Nuevo: `app/services/massive_service.py`. Verificado
> con smoke tests (GME/MULN) y en navegador — resultados al final del doc (§11).

---

## 1. Resumen ejecutivo

La página es lenta y "a veces faltan datos" por una única causa raíz con tres caras:
**las fuentes primarias no son deterministas** (yfinance = Yahoo no oficial, scraping
de Finviz y knowthefloat.com), **la primera carga de cada ticker bloquea** la request
hasta 10–15 s (y el frontend aborta a los 20 s), y **la caché persiste resultados
vacíos** cuando la fuente falla "en silencio", sirviéndolos después como si fueran
buenos.

La solución no requiere infra nueva: **la key de Massive que ya pagamos cubre casi
todo lo que hoy se scrapea o se pide a Yahoo** (overview, precio, histórico 5y,
fundamentales XBRL, short interest oficial FINRA), y lo que Massive no tiene lo da la
**API JSON oficial de SEC** (data.sec.gov), que ya está integrada en `edgar_service`
para Edgie pero el router sigue usando el endpoint legacy `cgi-bin` + scraping de XMLs
en serie.

**Evidencia medida (2026-07-07, ver §3):** con MULN (small-cap deslistada, el perfil
típico de nuestro universo) yfinance devuelve **0 datos** (`.info` → 1 campo,
histórico → 0 filas, balance → vacío) mientras Massive devuelve **932 barras diarias
y 4 trimestres de financials** en <0,7 s. Con GME ambas van bien — por eso "algunos
tickers cargan y otros no".

---

## 2. Arquitectura actual (mapa dato → fuente → problema)

La página dispara 7 endpoints en paralelo al seleccionar ticker (más 1 lazy para el
informe de Edgie). Todos pasan por la caché SWR persistente en `users.duckdb`
(`_swr_cache`), con Redis opcional por delante en algunos.

| # | Endpoint | Alimenta | Fuente actual | Problema |
|---|----------|----------|---------------|----------|
| 1 | `GET /{ticker}` | Perfil, market snapshot, financials snapshot, officers | **yfinance `.info`** (timeout 10 s) ∥ **scrape Finviz** (6 s) ∥ DB tickers | yfinance 401/timeout/vacío en small-caps; Finviz "degradado" (solo market_cap, reconocido en comentario del código); primera visita **bloquea** |
| 2 | `GET /{ticker}/chart` | Velas 5y + performance 1w/1m/…/YTD | **yfinance `.history(5y)`** → fallback hot cache/DB | Deslistados → 0 filas; primera visita bloquea |
| 3 | `GET /{ticker}/balance-sheet` | 5 gráficos históricos (cash, deuda, WC, equity, acciones) | **yfinance `.quarterly_balance_sheet`** (timeout 15 s) | Primera visita bloquea hasta 15 s; vacío en muchos small-caps |
| 4 | `GET /{ticker}/gap-stats` | Gap stats 0/+1/+2, chart 15-min, **Know The Float** | **scrape knowthefloat.com** + hot cache daily + intradía GCS | Scraping frágil (regex sobre HTML); recompute completo cada 15 min de TTL; GCS US lento (cuello conocido) |
| 5 | `GET /{ticker}/sec-filings` | Listas de filings por categoría | **SEC `cgi-bin/browse-edgar` ATOM** (legacy) | Formato legacy sin estructura; ya existe alternativa JSON en `edgar_service` |
| 6 | `GET /{ticker}/insiders` | Transacciones Forms 3/4/5 (informe Edgie + tool agentic) | SEC ATOM + `index.json` + XML **por filing, EN SERIE** (~25 requests HTTP) | Peor caso >60 s; primera visita **bloquea**; el frontend aborta a los 20 s → "no hay datos" |
| 7 | `GET /{ticker}/finviz-news` | Noticias con sentiment | **Massive `/v2/reference/news`** ✓ | Ya API. Solo nombre legacy |
| 8 | `GET /{ticker}/logo` | Logo | **Massive `/v3/reference/tickers`** (branding) ✓ | Ya API, pero pide el mismo endpoint que daría TODO el overview y descarta el resto |

**Relación con Edgie:**

- La KB del chat se alimenta del evento `ticker-loaded` con los datos de arriba →
  si el payload viene vacío, Edgie responde "N/A" o improvisa.
- `POST /assistant/dilution-report`: inyecta bancos dilusores + **pre-extracción
  EDGAR secuencial** (directivos → oferta, ~4-6 requests en serie) + el frontend
  hace un fetch lazy de `/insiders` (el endpoint lento) **antes** de llamar al LLM
  + llamada DeepSeek **no-streaming** (30–90 s percibidos sin feedback).
- `POST /assistant/agentic-chat`: tools EDGAR; `get_insiders` reutiliza el mismo
  código lento del endpoint 6.

**Modelo de caché actual** (`_swr_cache` sobre `users.duckdb` + lock global RLock):

- Primera visita: **bloquea** en todos los endpoints salvo `gap_stats` (único con
  placeholder "calculating" + poll de 4 s en frontend).
- Payload devuelto por la fuente se persiste **sin validar**: un scrape fallido que
  devuelve `{}` o `{news: []}` se guarda como bueno y se sirve durante el TTL — y
  como stale-while-revalidate lo sirve *siempre* primero, un vacío puede quedarse
  días si los refresh siguen fallando. **Esta es la causa de "datos que no están".**
- Redis por delante solo en 4 de 8 endpoints (analysis, chart, gap_stats, news, logo;
  falta en balance-sheet, sec-filings, insiders).
- Frontend: `apiRequest` aborta a los **20 s** → cualquier primera carga que supere
  eso (insiders casi siempre, balance-sheet/analysis en el peor caso) se pierde
  aunque el backend acabe cacheándola.

---

## 3. Mediciones (2026-07-07, red doméstica; en prod con IP de datacenter Yahoo se degrada más)

### Fuentes actuales

| Fuente | Ticker | Resultado |
|--------|--------|-----------|
| yfinance `.info` | GME | 0,85 s · 169 campos ✓ |
| yfinance `.info` | **MULN** | 0,66 s · **1 campo** (HTTP 404 quote) ✗ |
| yfinance `.quarterly_balance_sheet` | GME | 0,40 s · 65×7 ✓ |
| yfinance `.quarterly_balance_sheet` | **MULN** | **vacío** ✗ |
| yfinance `.history(5y)` | GME | 0,42 s · 1.255 filas ✓ |
| yfinance `.history(5y)` | **MULN** | **0 filas** ("possibly delisted") ✗ |
| Scrape Finviz | — | HTTP 301 (redirección; parser ya degradado según comentario en código) |
| Scrape knowthefloat | — | 0,43 s cuando responde; sin contrato, regex sobre HTML |
| SEC cgi-bin ATOM (filings) | — | 0,39 s la lista; insiders = lista + ~24 requests más EN SERIE |

Además, los propios comentarios del código documentan el histórico de fallos de
yfinance en prod: *"HTTP 401 Invalid Crumb intermitente y timeouts bajo carga"*
(`get_yfinance_session`, `ticker_analysis.py:682`).

### Massive API (key actual, plan ya contratado)

| Endpoint | Latencia | Contenido verificado |
|----------|----------|----------------------|
| `/v3/reference/tickers/{t}` | 0,42 s | name, description, homepage, employees, address, `sic_description`, `market_cap`, `share_class_shares_outstanding`, `weighted_shares_outstanding`, **`cik`**, branding, list_date |
| `/v2/snapshot/.../tickers/{t}` | 0,28 s | day, lastTrade, prevDay, todaysChange → precio actual |
| `/v2/aggs/.../range/1/day/5y` | 0,66 s | GME 1.254 barras · **MULN 932 barras** (yfinance: 0) |
| `/vX/reference/financials` | 0,60 s | balance_sheet (current_assets/liabilities, equity, **long_term_debt**, inventory…), income (EPS básico/diluido, `basic_average_shares` por trimestre, net_income, operating_income), cash_flow. **MULN: 4 trimestres** (yfinance: nada) |
| `/stocks/v1/short-interest` | 0,33 s | **short_interest, days_to_cover, avg_daily_volume, settlement_date** (FINRA oficial) — dato NUEVO que hoy solo llega scrapeando knowthefloat |
| `/v3/reference/splits` | 0,27 s | splits oficiales |

**Huecos de Massive** (verificado): el balance no expone `cash` como posición (solo
flujos) y el overview de tickers deslistados devuelve vacío sin parámetro `date`.
Cobertura: `cash` → API XBRL oficial de SEC (`data.sec.gov/api/xbrl/companyconcept`,
gratuita, sin key, y el CIK ya viene en el overview de Massive); deslistados →
`?date=` o fallback a nuestra tabla `tickers` (GCS), que ya tiene nombre/exchange.

---

## 4. Diagnóstico raíz (ordenado por impacto)

1. **P0 — Fuentes no deterministas como primarias.** yfinance y 2 scrapers HTML
   alimentan perfil, market, financials, chart y float. En small-caps/deslistados
   (nuestro universo) fallan sistemáticamente → lentitud (esperar timeouts de
   10–15 s) y huecos (payloads vacíos).
2. **P0 — SWR persiste vacíos sin validar.** Un fallo "suave" (dict vacío) se cachea
   como éxito y el stale-while-revalidate lo sirve primero para siempre. Solo
   `gap_stats` tiene validación (`gap_dates` presente).
3. **P0 — Primera visita bloqueante + abort a 20 s en frontend.** Todos los endpoints
   menos gap-stats bloquean la primera vez. Insiders (~25 requests SEC en serie)
   supera los 20 s con frecuencia → el usuario nunca ve el resultado del trabajo
   que el backend sí hizo.
4. **P1 — Trabajo duplicado y en serie.** `/logo` y el futuro overview usan el mismo
   endpoint de Massive (2 requests donde sobra 1); `/{ticker}` y `/chart` llaman
   ambos a Yahoo; insiders y pre-extracción de Edgie descargan en serie lo que es
   paralelizable; gap-stats recomputa TODO el histórico (lecturas GCS US) cada 15 min
   de TTL aunque los gaps históricos no cambien intradía.
5. **P2 — Higiene.** `verify=False` en todas las requests salientes (TLS sin
   verificar; ya se resolvió con certifi en el WS del screener); threads daemon sin
   acotar para cada refresh; lock global de `users.duckdb` serializa las 7 lecturas
   SWR de cada carga; Redis solo en la mitad de los endpoints.

---

## 5. Objetivo (definición de "impecable")

| Métrica | Hoy | Objetivo |
|---------|-----|----------|
| p95 por endpoint, caché caliente | 50 ms–2 s (variable) | **< 300 ms** |
| p95 primera visita de un ticker (todo menos gap-stats) | 5–20 s, a veces abort | **< 1,5 s** (Massive/SEC JSON) |
| Campos vacíos por fallo de fuente | Frecuente en small-caps | **0 persistidos** (vacío no se cachea; fallback en cascada) |
| Ticker deslistado (p.ej. MULN) | Sin chart, sin financials, sin perfil | Chart ✓ financials ✓ filings ✓ nombre ✓ |
| Informe Edgie | Insiders bloquea + pre-extract en serie + sin feedback | Insiders precargado, pre-extract paralelo, datos deterministas en prompt |
| Scraping | 3 scrapers como fuente primaria | **0 primarios** (solo enriquecimiento opcional no bloqueante) |

---

## 6. Plan por fases (5 PRs, orden = impacto)

### PR1 — `massive_service.py` + sustitución de yfinance en los 3 endpoints core

Cliente único para Massive (sesión `requests` compartida con pool, retries
idempotentes, timeout 5 s, certifi — sin `verify=False`, key centralizada):

- `get_overview(ticker)` → `/v3/reference/tickers/{t}` (con `date=` para
  deslistados; fallback a tabla `tickers` propia para nombre/exchange).
  Alimenta: perfil completo, market_cap, shares_outstanding, CIK, branding/logo.
- `get_snapshot(ticker)` → precio actual (prevDay si mercado cerrado).
- `get_daily_bars(ticker, years=5)` → `/v2/aggs` → chart + performance (mismo
  cálculo actual). Fallback: hot cache propio (ya implementado).
- `get_financials(ticker)` → `/vX/reference/financials?limit=20` → los 5 gráficos
  históricos (equity, working capital = current_assets − current_liabilities,
  long_term_debt, acciones vía `basic_average_shares`) + EPS.
- `get_short_interest(ticker)` → short interest oficial (dato nuevo).
- `get_cash_position(cik)` en `edgar_service` → XBRL companyconcept
  (`CashAndCashEquivalentsAtCarryingValue`, fallback a conceptos hermanos) → cash
  history + runway. EV = mcap + deuda − cash (calculado, ya no de Yahoo).

Reestructuración de endpoints (rutas y shapes de respuesta **sin cambios** para no
tocar el frontend más que lo mínimo):

- `/{ticker}`: Massive overview + snapshot (2 requests paralelas ~0,5 s) como
  primario. yfinance queda SOLO como enriquecimiento no bloqueante en background
  (officers, held_percent_insiders/institutions, sector/industry de Yahoo si se
  quiere mantener esa nomenclatura) que hace merge al payload cacheado cuando llega.
- `/chart`: Massive aggs primario, hot cache fallback. Yahoo fuera.
- `/balance-sheet`: Massive financials + cash XBRL. Yahoo fuera.
- `/logo`: servido desde el mismo overview cacheado (elimina 1 request duplicada).

**Aceptación PR1:** MULN y GME muestran perfil/market/chart/balance completos;
p95 frío < 1,5 s en esos 3 endpoints; cero llamadas a Yahoo en el camino bloqueante.

### PR2 — SEC JSON + insiders en paralelo

- `/sec-filings`: sustituir cgi-bin ATOM por `edgar_service.list_filings`
  (data.sec.gov submissions JSON, ya implementado y cacheado) + categorización
  actual. 1 request estructurada en vez de ATOM legacy.
- `/insiders`: listar Forms 3/4/5 desde el mismo submissions JSON; descargar los
  XML **en paralelo** (ThreadPoolExecutor(8)); **caché permanente por accession**
  (un filing publicado es inmutable — solo la lista lleva TTL). De ~25 requests en
  serie a ~3 rondas paralelas: peor caso pasa de >60 s a ~3–5 s frío, <100 ms
  caliente.
- CIK: usar el del overview de Massive y dejar `company_tickers.json` como fallback.

**Aceptación PR2:** insiders frío < 5 s, caliente < 300 ms; sec-filings < 1 s frío.

### PR3 — Modelo de caché sano (elimina "datos que no están")

- **Validación antes de persistir**: `is_valid_payload(endpoint, data)` por
  endpoint (como ya hace gap_stats con `gap_dates`). Un payload inválido NUNCA se
  guarda: se sirve el stale anterior si existe, o error explícito si no.
- **Primera visita no bloqueante universal**: generalizar el patrón
  placeholder+background que ya tiene gap_stats… pero solo donde haga falta — con
  PR1/PR2 todas las fuentes frías responden < 1,5 s, así que basta con un timeout
  duro de 8 s por endpoint: si la fuente no llega, respuesta parcial con
  `status: "partial"` y el resto llega por el refresh.
- **TTLs por naturaleza del dato** (hoy todo 15–30 min):
  - overview/financials/balance: 24 h (cambian con filings, no intradía)
  - snapshot/price: 1–5 min · news: 15 min · filings/insiders lista: 30–60 min
  - **gap-stats: 24 h** (+ invalidación dirigida si el ticker gapea hoy — aparece
    en el screener del día). Elimina recomputes de GCS cada 15 min.
- Redis delante de TODOS los endpoints (hoy falta en 3) con los mismos TTLs.
- Métrica en logs: una línea por fetch con `endpoint, source, ms, ok, campos_nulos`
  para poder medir p95 y % de nulos en prod.

**Aceptación PR3:** imposible persistir un payload vacío (test unitario por
endpoint); gap-stats no recomputa más de 1 vez/día sin señal.

### PR4 — Edgie más rápido y más determinista

- **Prefetch de insiders**: al cargar el ticker, disparar `/insiders` en background
  (barato tras PR2) para que el botón del informe no lo pague.
- **Pre-extracción paralela**: `_pre_extract_for_report` lanza directivos ∥
  oferta/dilución con `asyncio.gather`/threads (hoy secuencial).
- **Datos deterministas en el prompt del informe**: añadir short interest oficial
  (Massive), financials trimestrales (Massive) y cash XBRL (SEC) a la
  pre-extracción — menos "estimaciones" del modelo, mejor `cash_runway_months` y
  `runner_assessment` (alineado con feedback-edgie-analisis: datos, no opiniones).
- La KB del chat (`ticker-loaded`) se beneficia sola: sin N/A al desaparecer los
  vacíos.
- Opcional UX (decisión aparte): streaming del informe con parse de
  `<edgie_metrics>` al final del stream; y/o cachear el informe por ticker+día con
  botón "Regenerar" (ahorra coste LLM — lo decide Jesús).

**Aceptación PR4:** clic en informe → LLM empieza sin esperar a SEC (pre-extract
paralelo + insiders ya en caché); prompt incluye short interest y cash reales.

### PR5 — Higiene y frontend fino

- Quitar `verify=False` de todas las requests (certifi, como el WS del screener).
- Pool acotado (4–8) para refreshes SWR en vez de `threading.Thread` sueltos.
- Lecturas SWR fuera del lock global donde sea posible (lectura con conexión
  propia; el RLock solo para escrituras) — hoy las 7 llamadas de cada carga se
  serializan entre sí y con las de otros usuarios.
- Frontend: `AbortController` al cambiar de ticker (hoy solo se ignora la
  respuesta, la conexión sigue viva); backoff en el poll de gap-stats (4→8→15 s,
  cap 2 min); skeletons por tarjeta con "fuente + hora del dato" (opcional).

---

## 7. Mapa campo → fuente nueva (referencia de implementación)

| Campo | Fuente hoy | Fuente nueva (primaria → fallback) |
|-------|-----------|-------------------------------------|
| name, exchange, description, website, employees, address | yfinance | **Massive overview** → tabla `tickers` propia |
| sector / industry | yfinance | **Massive `sic_description`** → yfinance (enrichment bg) |
| logo | Massive (request aparte) | **Mismo overview** (sin request extra) |
| market_cap, shares_outstanding | Finviz scrape → yfinance | **Massive overview** |
| float_shares | Finviz/yfinance/knowthefloat | ⚠️ Sin API con las keys actuales → yfinance + knowthefloat como **enrichment no bloqueante**; ver §8 |
| short % / short interest | knowthefloat scrape | **Massive short-interest** (FINRA oficial) + days_to_cover (nuevo) |
| price | yfinance → Finviz → DB | **Massive snapshot** → hot cache propio |
| held % insiders/institutions | yfinance | yfinance **enrichment bg** (sin alternativa API; el dato fino sale de 13D/G/13F vía Edgie) |
| officers | yfinance | yfinance enrichment bg → pre-extract SEC de Edgie (Item 6/10) ya existente |
| chart 5y + performance | yfinance | **Massive aggs** → hot cache propio |
| cash history / cash | yfinance | **SEC XBRL companyconcept** (CIK del overview) |
| debt, equity, working capital, shares history | yfinance | **Massive financials** (long_term_debt, equity, current_assets−liabilities, basic_average_shares) |
| EPS | yfinance | **Massive financials** |
| EBITDA | yfinance | Calculado de Massive (operating_income) o yfinance enrichment bg — dato menor en small-caps que queman caja |
| enterprise_value | yfinance | **Calculado**: mcap + deuda − cash |
| SEC filings | cgi-bin ATOM | **data.sec.gov submissions JSON** (edgar_service) |
| insiders Forms 3/4/5 | ATOM + XMLs en serie | **submissions JSON + XMLs en paralelo + caché por accession** |
| news + sentiment | Massive ✓ | sin cambio |
| gap stats | hot cache + intradía GCS | sin cambio de fuente; TTL 24 h + invalidación dirigida |

## 8. Decisiones que necesita Jesús (no las tomo yo)

1. **Float por API → RESUELTO con Alpha Vantage (2026-07-07).** Massive no lo
   expone y la SEC solo tiene el público anual en USD (inútil para small-caps que
   diluyen). Verificado que **Alpha Vantage `OVERVIEW`** trae `SharesFloat` +
   `SharesOutstanding` + `PercentInsiders` + `PercentInstitutions` + `EBITDA` +
   sector/industry en una sola llamada determinista, con cobertura fresca (Q1
   2026) en small-caps activas — ARBE (96.8M), KOSS (5.5M low-float), GNS (144M).
   No cubre deslistadas (MULN → vacío; irrelevante, no cotizan). Implementado como
   **fuente primaria de enriquecimiento** (`app/services/alphavantage_service.py`),
   con yfinance de fallback para officers y cuando AV no cubre.
   - ⚠️ **Pendiente de Jesús (coste)**: el tier gratis son **25 req/día**. Con
     caché de 24h = 1 llamada/ticker/día y enriquecimiento no bloqueante, degrada
     con elegancia al agotarse (float en blanco ese día, sin romper nada). Para
     prod con tráfico real probablemente quiera **premium de Alpha Vantage** (más
     cuota, misma línea de código) — decisión de coste suya.
   - ⚠️ **Prod**: hay que poner `ALPHAVANTAGE_API_KEY` en el entorno (Coolify).
2. **Nomenclatura sector/industry**: aceptar `sic_description` de Massive (SEC) o
   mantener la de Yahoo vía enrichment.
3. **Cachear el informe de Edgie por ticker+día** (ahorro de coste LLM) con botón
   regenerar — afecta a percepción de frescura.
4. **Rate limits del plan Massive**: la misma key sirve ingesta + screener + esto.
   Con TTL 24 h son ~5 requests por ticker nuevo/día — verificar el límite del plan
   antes de PR1 (si es "unlimited" como el plan Advanced, no hay tema).

## 9. Qué NO se toca

- Backtester completo (routers/backtest*, strategy_engine, motor V2, rama
  `feat/f2-numba-engine`, `.agent/SYSTEM.md`).
- Screener, ingesta Massive, WebSocket, hot cache (solo se consume).
- Diseño visual de la página (mismo layout; solo skeletons/estados opcionales).
- Shapes de respuesta de los endpoints (el frontend sigue funcionando igual).

## 10. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Massive financials tarda en reflejar el último filing (XBRL) | Complemento SEC XBRL directo (mismo origen que yfinance en realidad) + `filing_date` visible en el widget |
| Overview vacío en deslistados | `?date=` + fallback tabla `tickers` propia (verificado que existe el hueco) |
| Cambio silencioso de shape en scraper de float (si se mantiene como enrichment) | Nunca bloquea ni se persiste si viene vacío (PR3) |
| gap-stats sigue atado a GCS US | TTL 24 h reduce el 96 % de recomputes; la solución de raíz (hot storage intradía) pertenece al proyecto rendimiento-backtester, no a este |

## 11. Resultados de la implementación (medidos 2026-07-07, local)

### Timings (backend local, DB_PROVIDER=local, fuentes reales Massive/SEC)

| Endpoint | Frío (1ª visita ticker) | Caliente (SWR) | Antes |
|----------|------------------------|----------------|-------|
| `/{ticker}` (GME) | 0,79 s | 0,015 s | 5–16 s (timeouts yfinance+Finviz) |
| `/{ticker}` (MULN deslistada) | 2,4 s (triple fallback overview) | 0,011 s | vacío para siempre |
| `/chart` | 0,45 s | 0,027 s | 0,5–10 s o vacío |
| `/balance-sheet` | 0,014 s (memo financials compartido) | 0,010 s | hasta 15 s bloqueante |
| `/sec-filings` | 0,37 s | 0,011 s | 0,4 s (ATOM legacy) |
| `/insiders` (GME, 16 filas) | 0,55 s | 0,011 s | 10–60+ s EN SERIE (abort frontend) |
| `/insiders` (MULN, 21 filas) | 0,72 s | 0,010 s | 0 filas (CIK irresoluble) |

### Verificado en navegador (GME)

Nombre/exchange/mcap/shares (Massive) + float 408,79 M y 8,83 % insiders /
37,20 % inst. + EBITDA (enrichment yfinance fusionado en background) + cash
$7,40 B (SEC XBRL, 24 trimestres) + EV calculado $2,81 B + sector Yahoo +
industry SIC + performance completa + news con sentiment. MULN (deslistada):
nombre, 932 velas, 5 series de balance, 21 insiders, cash $454 K — antes todo
vacío.

### Desviaciones conscientes del plan

- **Lock global de users.duckdb**: se mantiene tal cual (correctness-first; las
  lecturas calientes ya van por caché en memoria/Redis y no lo tocan).
- **Skeletons "fuente + hora del dato"**: no implementados (opcionales, UI).
- **CORS**: añadido regex dev-only `http://localhost:<puerto>` en main.py (el
  dev server de Next salta de puerto con autoPort; sin riesgo, auth = Bearer).
- **sec-filings**: límite subido de 40 → 100 filings (misma request única).
- **Extra**: fallback `active=false` en overview para deslistados (recupera
  name+CIK+delisted_utc, imprescindible para XBRL/insiders de deslistados) y
  concepto XBRL `Cash` añadido a la cascada de caja.
