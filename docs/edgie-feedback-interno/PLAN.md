# Plan — Feedback Interno (Screener + Edgie)

> Basado en `Feedback Interno.pdf`. Rama: **edgie**. Sin fuentes nuevas ni de pago
> (regla de [[proyecto-edgie-agentic]]); todo reutiliza lo ya integrado.

## SCREENER

### S1 — Market Cap en vivo (no el campo obsoleto)
**Problema:** el Screener muestra Market Cap $3.38M para LABT; Edgie calcula $6.9M (precio × shares out). El campo `market_cap` del Screener está desincronizado.
**Fix:** en el panel de detalle del Screener, calcular `Market Cap = precio × shares_outstanding` en el momento (fallback al campo si falta alguno). Aplicar la misma coherencia en Ticker Analysis. *Frontend, pequeño.*
**Verif:** LABT muestra ~$6.9M, coincidiendo con Edgie.

---

## EDGIE

### E1 — El informe rápido asume que el usuario va CORTO
**Problema:** añadir "estoy interesado en hacer short" mejora la respuesta y su orden; no debería tener que escribirlo.
**Fix:** la pill "Informe rápido" inyecta ese contexto, y el preámbulo del informe deja claro que el usuario evalúa un short (prioriza dilución/procedencia/precios de referencia). *Frontend (pill) + `assistant.py` (preámbulo).*
**Verif:** pill de informe → mismo orden/calidad que cuando se escribe "…short".

### E2 — Noticias fiables + recencia
**Problema:** Edgie dice "sin noticias" pese a un Reverse Split de MSS hace 2 días (ACCESS Newswire). Usa Finviz, que se lo pierde.
**Fix:** cambiar la fuente de noticias del snapshot de Edgie de `get_finviz_news` → **`massive_service.get_news(ticker)`** (ya integrada, es la del panel "PR Releases"; trae `published_utc` + sentiment). Incluir la **fecha** de cada titular y regla en el preámbulo: "reciente = últimos ~7 días; 2 días atrás ES reciente; un reverse split es material". *Backend snapshot + preámbulo.*
**Verif:** "noticias de MSS" → sale el reverse split con su fecha.

### E3 — Tablas legibles en el chat
**Problema:** el renderer del ChatBot no pinta tablas markdown → salen como texto con `|` ilegible.
**Fix:** añadir render de tablas en `renderMessageContent` (parser ligero: filas `| … |` + separador `---` → `<table>` estilada con tokens del DS). Sin dependencia nueva. Instruir a Edgie a usar formato GFM consistente. *Frontend renderer + preámbulo.*
**Verif:** el desglose de dilución se ve como tabla real, escaneable de un vistazo.

### E4 — Warrants precisos (no confundir con opciones)
**Problema:** Edgie da ~300,683 @ $2.13–$10 (son opciones de directivos); el warrant real es 94,202 @ $69.00.
**Fix:** regla en el preámbulo: **warrants ≠ stock options** de directivos/empleados; reportar `outstanding` y `exercise price` EXACTOS del documento del warrant (warrant agreement / 424B "Description of Securities" / 8-K exhibit), horquilla solo si hay tramos reales. Depende de E5 para abrir el documento correcto. *Preámbulo + E5.*
**Verif:** en MSS, warrant = 94,202 @ $69.00 (o el dato exacto del filing), sin mezclar con opciones.

### E5 — `read_filing` lee cualquier documento (no solo el último)
**Problema:** `read_filing` devuelve solo el filing más reciente del tipo; no puede abrir un 8-K de una fecha anterior ni cruzar varios documentos.
**Fix:** `read_filing` acepta `date` (o índice) para abrir un filing concreto/antiguo; `list_filings` ya da las fechas → el modelo elige. Actualizar la descripción de la tool: "puedes pedir documentos antiguos por fecha; para dilución lee TODOS los tipos relevantes (10-K/Q, 424B/S-1, 8-K), no solo el 8-K más reciente". *Backend tool + preámbulo.*
**Verif:** "lee el 8-K del 22/10/2025 de X" → abre ese, no el de julio 2026.

---

## Orden de ejecución sugerido
1. **E5** (base para E4) → 2. **E4** → 3. **E2** (noticias) → 4. **E3** (tablas) → 5. **E1** (informe short) → 6. **S1** (market cap Screener).

## Decisiones (menores, con recomendación)
1. **E2**: fuente de noticias de Edgie → Massive (ya integrada, sin coste). **Recomendado.** ¿OK?
2. **E3**: render de tablas propio, sin dependencia (vs meter `react-markdown`). **Recomendado el propio** (más ligero y controlado).

## DoD
`npm run build` verde; snapshot/squeeze/informe siguen respondiendo; MSS muestra reverse split + warrant correcto; tablas legibles; market cap del Screener coincide con Edgie.
