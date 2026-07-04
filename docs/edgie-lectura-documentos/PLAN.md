# Edgie — Lectura real de documentos (pre-extracción + agentic)

> **Estado:** PLAN (para validar). Ningún código de producción todavía.
>
> **Objetivo.** Que Edgie deje de quedarse en los *títulos* de los filings (y de **alucinar** cuando se le pide más) y pase a **extraer información real del contenido** de los documentos y URLs que ya nos da la API/EDGAR. Aplica a **cualquier dato** que Edgie maneje (directivos, dilución, warrants, estructura de capital, caja, beneficial owners…), no solo a un caso.
>
> **Principio elegido por Jesús.** Primar la **pre-extracción determinista**: si el backend es capaz de bajar el documento y sacar la sección/dato real, esa es la vía buena. Solo donde la pre-extracción no llegue (exploración libre tipo "investiga ahí dentro y sigue"), se habilita el **modo agentic** (tools + bucle). → Enfoque **híbrido por defecto, pero con pre-extracción como motor principal**.

---

## 1. Diagnóstico (por qué falla hoy)

Edgie vive en dos superficies y **ninguna lee documentos**:

| Superficie | Qué recibe hoy | Síntoma observado |
|---|---|---|
| Chat conversacional ([ChatBot.tsx](../../frontend/src/components/ChatBot.tsx)) | KB con perfil, métricas, gap stats, **títulos** de filings y noticias. Sin insiders, sin tools. | Pregunté "¿quiénes son los directores?" → inventó nombres ("según el Form 20-F…") que **no coinciden** con SEC. **Alucinación + atribución falsa.** |
| Informe de dilución ([TickerAnalysis.tsx](../../frontend/src/components/TickerAnalysis.tsx) → `/assistant/dilution-report`) | userPrompt con métricas + **títulos** de filings + insiders (Forms 3/4/5). | Ownership con 1 fila vieja (13G de 2006). El contenido de 20-F/424B/13D nunca se lee. |

**Causa raíz:** la API ya nos da los **URLs** de cada documento, pero el backend solo guarda metadatos (tipo, título, fecha, link). El contenido (texto del 20-F, del prospecto 424B, del 13D…) **no se descarga ni se extrae**, y Edgie **no tiene herramientas** para ir a por él.

**Matiz técnico importante (explica el caso SPCB):** SPCB es **emisor extranjero** (Israel, declara **20-F**). Los foreign private issuers están en gran parte **exentos de Section 16 (Forms 3/4/5)**, así que su junta **no** está ahí: vive en el **20-F, Item 6 (Directors & Senior Management)**. Sin leer ese documento, es imposible dar los directores correctos. Por eso el patrón de "ir al documento" es imprescindible y debe ser **general**.

---

## 2. Arquitectura propuesta

Un **único motor de ingesta+extracción** reutilizable de dos formas:
- **Pre-extracción** (motor principal): el backend lo ejecuta de forma determinista y mete el resultado en el prompt del **informe** (y en la KB del **chat**).
- **Tools agentic** (fallback): las mismas funciones se exponen como herramientas para que, en el **chat**, Edgie decida qué documento/sección abrir e itere.

> Se escribe **una vez**, se consume de **dos** maneras. Eso cumple "pre-extracción primero; agentic solo donde haga falta".

### 2.1 Pipeline general (para cualquier dato)

```
1. DISCOVER   → resolver CIK del ticker y listar filings con sus URLs reales
2. FETCH      → de un filing, localizar y bajar el documento primario (HTML/XBRL/XML)
3. TO-TEXT    → limpiar HTML/iXBRL → texto plano (XML estructurado para 3/4/5)
4. SECTION    → recortar SOLO la sección relevante (un 20-F entero no cabe en contexto)
5. EXTRACT    → normalizar a datos (regex/parse donde el formato es regular) o
                pasar la sección acotada al LLM para que extraiga (donde es texto libre)
6. FEED       → inyectar el resultado en el prompt (informe) o devolverlo como tool-result (chat)
7. CACHE      → SWR por nº de accession (los filings no cambian) para no rebajar docs gigantes
```

Pasos 2–3 ya existen probados para Forms 3/4/5 (`_fetch_ownership_xml` + `parse_form345_xml`). Se **generaliza** ese patrón a los demás tipos.

### 2.2 Catálogo "info → de dónde sale" (la generalización que pediste)

Esto es el corazón del plan: para **cada dato** que Edgie da, definimos documento + sección + método.

| Dato que Edgie necesita | Documento(s) | Sección a recortar | Método extracción |
|---|---|---|---|
| **Directivos / junta** | 20-F, DEF 14A, 10-K | "Item 6 Directors & Senior Management" / "Directors and Executive Officers" | section → LLM extrae lista |
| **Insiders (compras/ventas)** | Forms 3/4/5 | XML completo | parse determinista (✅ hecho) |
| **Beneficial owners (>5/10%)** | SC 13D, SC 13G | tabla del cover + Item 4/7 | section → LLM/parse |
| **Placement agents / underwriters** | S-1/F-1/S-3/F-3, 424B | "Plan of Distribution" / "Underwriting" | section → LLM (nombres) |
| **ATM / shelf / capacidad** | S-3/F-3, 424B, 8-K/6-K | "The Offering" / "Plan of Distribution" | section → LLM + regex importes |
| **Convertibles tóxicos (descuento VWAP)** | 8-K + exhibits 4.1/10.1, prospectos | "Description of Securities" / exhibit | section → LLM (términos) |
| **Warrants: exercise/redemption** | Prospectos, 8-K | "Description of Securities/Warrants" | section → LLM + regex precios |
| **Shares outstanding / float** | Cover de 10-K/10-Q/20-F, **XBRL facts** | cover page / `dei:` facts | XBRL API (preferente) |
| **Caja / runway / deuda** | Estados financieros, **XBRL facts** | `us-gaap:` facts | XBRL API (preferente) |
| **Jurisdicción / país / gobernanza** | Cover + "Risk Factors" | cover / riesgos | section → LLM |

### 2.3 Fuentes EDGAR a usar (robustez)

- **CIK**: `https://www.sec.gov/files/company_tickers.json` (mapa ticker→CIK, cacheado).
- **Lista de filings**: migrar de la RSS actual (cap 40, `owner=exclude`) a **`https://data.sec.gov/submissions/CIK##########.json`** → da `form`, `accessionNumber`, `primaryDocument`, `filingDate` de todo el historial. Más fiable.
- **Documento primario**: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_sin_guiones}/{primaryDocument}`.
- **Datos numéricos** (shares, caja, deuda): `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (estructurado, sin parsear HTML).
- `User-Agent` SEC obligatorio (ya lo usamos), throttling y caché.

---

## 3. Componentes nuevos (backend)

- `app/services/edgar_service.py` (nuevo): `resolve_cik(ticker)`, `list_filings(cik)`, `fetch_primary_document(cik, accession)`, `html_to_text(html)`, `extract_section(text, section_key)`, `get_xbrl_facts(cik)`. Caché SWR por accession.
- `app/services/edgie_extract.py` (nuevo): por cada entrada del catálogo (§2.2), una función `extract_directors(...)`, `extract_offering_terms(...)`, etc., que combinan section + LLM-extract acotado.
- Endpoints: `GET /ticker-analysis/{ticker}/document?type=20-F&need=directors` (pre-extracción on-demand) y, para agentic, exponer estas funciones como **tools** en el gateway.
- Gateway agentic: `assistant.py` **ya pasa `tools`/`tool_choice:auto`**; falta el **bucle** (ejecutar tool_calls del modelo, devolver resultados, repetir) para `/chat`. Reutiliza las funciones de arriba.

## 4. Guardrails anti-alucinación (no negociable)

- Edgie **solo** afirma datos presentes en texto **realmente extraído**. Si una sección no se pudo bajar/encontrar → "dato no disponible", **nunca** inventar ni atribuir a un documento no leído.
- Prohibido decir "según el Form X…" si ese documento no está en el contexto/tool-result.
- En modo agentic: responder **únicamente** desde resultados de tools; citar form + fecha de la fuente.

## 5. Límites y costes (honesto)

- **Tamaño**: un 20-F son cientos de miles de tokens → el recorte de sección (paso 4) es obligatorio antes del LLM. Sin eso, no cabe.
- **Latencia/coste**: bajar docs grandes + 1–N llamadas LLM por consulta. Mitigado con caché SWR por accession y recorte de sección. El chat agentic será más lento que una respuesta normal (avisar al usuario en UI).
- **Fragilidad**: el HTML de los filings varía entre emisores; el recorte por encabezados + LLM-extract es más robusto que regex puro.
- **Rate limits SEC**: throttle + caché + cap de documentos por consulta.

## 6. Incrementos (fases) y verificación

- **F0 — Parche inmediato (chat, barato):** añadir al system prompt del chat la regla "no tienes tools, no puedes leer documentos, no afirmes haberlos leído; si el dato no está en la KB, di 'no disponible'". Frena la alucinación **ya**, antes del feature grande. *Verif.: preguntar directores sin datos → responde "no disponible", no inventa.*
- **F1 — Motor genérico + 1 caso real:** `edgar_service` (CIK, submissions, fetch primary doc, html→text, extract_section) + caché. Caso de validación: **directores de SPCB desde el 20-F (Item 6)**. *Verif.: la tool devuelve la junta real de SPCB, contrastada con el 20-F.*
- **F2 — Cobertura de dilución:** placement agents + offering/ATM/shelf + warrants desde 424B/S-1/S-3/8-K. *Verif.: en un caso US con H.C. Wainwright, los detecta del "Plan of Distribution".*
- **F3 — Chat agentic:** bucle de tool-calling en `/chat` usando el motor F1/F2. *Verif.: "investiga ahí dentro" abre el doc correcto e itera, citando fuente.*
- **F4 — Informe con pre-extracción:** el informe consume el motor (directivos, banks, warrants reales). *Verif.: ownership/directivos del informe = datos del documento, no metadatos.*

## 7. Decisiones abiertas (para Jesús)

1. **Modelo de extracción**: ¿usamos DeepSeek (el actual) para el paso EXTRACT, o conviene un modelo más barato/rápido para el troceo? (coste vs calidad).
2. **Profundidad agentic en chat**: ¿límite de iteraciones/documentos por pregunta? (coste/latencia).
3. **Gating**: ¿esta capacidad es para todos los tiers o solo Pro/Admin? (diferido a negocio — no lo decido yo).
4. **¿Migramos discovery a `data.sec.gov/submissions`** o mantenemos la RSS actual en paralelo?
