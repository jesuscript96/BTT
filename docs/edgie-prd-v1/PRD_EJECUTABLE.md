# PRD Ejecutable — Edgie v1.0 (locates · informe rápido · squeeze)

> Basado en `Edgecute PRD Edgie v1_0.md`. **Decisión de producto (Jesús): CERO fuentes nuevas y
> nada de pago. NO web search.** Ya tenemos suficiente info; el esfuerzo va a **UX** (flujos
> conversacionales, formato de 30s, chips, comportamiento copiloto) + orquestar lo que ya existe.
> Edgie informa/calcula, nunca da señales ni inventa datos ([[proyecto-edgie-agentic]]).

## Todo lo del PRD se cubre con lo que YA tenemos
| Dato del PRD | Fuente existente | Estado |
|---|---|---|
| Sector | `ticker_analysis.profile.sector` | ✅ |
| Temperatura del sector | `/market/gaps-by-sector` (envolver) | ✅ existe el endpoint |
| Procedencia / directivos (China/Asia) | motor EDGAR: `read_filing` 20-F Item 6 / DEF 14A | ✅ |
| Noticias del día | `get_finviz_news` | ✅ ya integrado |
| Filings dilución (S-3/ATM/424B/warrants) | motor EDGAR: `read_filing` | ✅ |
| Precios de referencia | derivados de esos filings | ✅ |
| Insiders % / institucional % | Finviz/Yahoo (`held_percent_*`) | ✅ |
| Float | Finviz/yfinance (`float_shares`) | ✅ |
| Short interest | Finviz `short_percent` | ✅ ya scrapeado |
| Days to cover | Finviz "Short Ratio" | ➕ 1 campo al scraper (misma página) |
| **Borrow rate** | — no existe en fuente gratuita | ❌ → mostrar "sin datos disponibles" |

**No se añade ninguna fuente ni API.** El borrow rate se marca "sin datos disponibles" (regla del propio PRD).

## Lo que hay que construir (casi todo UX)
| # | Pieza | Dónde |
|---|---|---|
| A | 3 pills directas sobre el input (locates · informe · squeeze), sin paso previo ni emojis | `ChatBot.tsx` |
| B | Tool `locates_calc` (determinista, `ceil` a paquetes de 100) | backend, nueva |
| C | Flujo conversacional de locates (pregunta 1→4, sin defaults) + formato salida | prompt/orquestación |
| D | Guion "informe rápido" (6 bloques, ≤2 frases c/u, 30s) sobre datos existentes | prompt |
| E | Guion "riesgo de squeeze" (SI + days-to-cover + float; borrow="sin datos") | prompt |
| F | `short_ratio` (days-to-cover) al scraper Finviz + `sector_temperature` wrapper | backend, pequeño |
| G | Preámbulo de comportamiento v1 (copiloto, 30s, news=pump, sin señales, sin defaults) | `assistant.py` |

---

## EPIC 1 — Calculadora de locates (lo más autónomo)
- **T1.1** `app/services/locates.py` + `tests/test_locates.py`: `shares` directas o `round(riesgo/(stop-entrada))`; `paquetes=ceil(shares/100)`; `coste_total=paquetes*coste_paquete`; `coste/share`; `fade_break_even_total=(riesgo_share+coste/share)/entrada*100`. Devuelve todos los campos + la frase de conclusión. **Verif:** `pytest` (350 sh→4 paquetes; opción riesgo→shares).
- **T1.2** Registrar `locates_calc` como tool en `assistant.py`. **Verif:** import OK.
- **T1.3** Flujo conversacional: Edgie pide en orden precio_entrada → stop → coste_paquete → shares|riesgo; **ningún default**; formato de salida del PRD §02. **Verif:** "calcula locates" pide los 4 y devuelve el fade %.

## EPIC 2 — Informe rápido + squeeze (orquestación sobre datos existentes)
- **T2.1** `short_ratio` al `scrape_finviz_snapshot` (days-to-cover) + wrapper `sector_temperature` sobre `/market/gaps-by-sector`. **Verif:** ambos devuelven dato o `None`.
- **T2.2** Guion "informe rápido" (6 bloques, ≤2 frases, 30s) reutilizando EDGAR/Finviz/news; bloque noticias añade el aviso "en small caps la noticia es catalizador del pump". **Verif:** "dame info de WHLR" → 6 bloques compactos.
- **T2.3** Guion "riesgo de squeeze": short interest + days-to-cover + float (existentes); borrow rate → "sin datos disponibles". Formato compacto del PRD §04. **Verif:** "riesgo de squeeze WHLR".

## EPIC 3 — UX del chat
- **T3.1** 3 pills directas en `ChatBot.tsx` (visibles sobre el input desde el inicio, sin botón intermedio ni emojis; pill → inyecta el texto y desaparecen; vuelven al resetear). **Verif:** `npm run build` + click de las 3.
- **T3.2** Preámbulo v1 (§06 PRD) en el gateway: copiloto; nunca señales/"buen short"; brevedad 30s (una frase > dos); "sin datos disponibles" si falta; recordatorio news=pump; locates ceil a 100; sin defaults. **Verif:** respuestas breves, sin señales.

---

## Decisiones (ya tomadas por Jesús)
1. **Sin fuentes nuevas ni de pago. Sin web search.** (revierte lo del PRD original que pedía web search + Dilution Tracker).
2. **Borrow rate** = "sin datos disponibles" en v1. No se persigue.

## Abierto (menor)
- Gating por tier (negocio, no lo decido yo).

## Fuera de scope v1 (del PRD)
Predicción de precio, sizing, análisis técnico, histórico del usuario, comparativas entre tickers.

## DoD global
Los 3 flujos responden en <30s de lectura, compactos, sin inventar, reutilizando datos existentes; `pytest` verde (locates); `npm run build` verde; chips OK. Cero fuentes/APIs nuevas.
