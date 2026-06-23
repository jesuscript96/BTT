# Manual del PM — Cómo preparar un PRD que la IA construye a la primera

> **Para quién es esto.** Para Jaume (PM, experto en trading) y cualquiera que vaya a
> escribir requerimientos de producto para Edgecute/BTT que luego ejecutará una IA
> (Claude Code en modo *goal*/*loop*).
>
> **Qué resuelve.** Hoy la IA puede construir un módulo entero sola — pero solo si lo que
> recibe es **completo, inequívoco y anclado en el código real**. Este manual te enseña a
> producir exactamente eso: un *paquete de requerimientos ejecutable*. No es un manual de
> redacción de PRDs "bonitos"; es un manual de **ingeniería de especificación** para que el
> resultado salga **a la primera**, sin idas y venidas.
>
> **El listón.** Tienes tres ejemplos de este nivel a mano (léelos en paralelo a este manual;
> cada sección de un PRD aplica una parte de aquí):
> 1. **PRD de un área NUEVA (greenfield)** — un diario de trading que aún no existe:
>    [`PRD_EJEMPLO_JOURNAL.md`](PRD_EJEMPLO_JOURNAL.md). Incluye la **entrevista** agente↔PM.
>    *Demuestra que esta guía sirve para mucho más que el backtester.*
> 2. **PRD de un submódulo que REUSA código** — Gap Edge Explorer:
>    [`PRD_EJEMPLO_GAP_EDGE_EXPLORER.md`](PRD_EJEMPLO_GAP_EDGE_EXPLORER.md).
> 3. **El suite de pre-producción del Gateway B2D** — [`docs/b2d-gateway/`](../b2d-gateway/00_INDEX.md),
>    un caso grande con los 7 documentos separados.
>
> Cuando dudes de "cuánto detalle es suficiente", abre cualquiera. Tu objetivo es producir algo
> de esa calidad **por tu cuenta** (o, mejor: dejar que tu agente lo produzca entrevistándote).
>
> **Este es un documento único y autosuficiente.** Todo lo que necesitas para preparar un PRD
> (método, plantillas, catálogos, glosario y comandos) está aquí dentro. Las referencias a
> ficheros del repo son para que tu agente los audite, no dependencias para leer este manual.

---

## Índice

- [Parte 0 — El contrato mental: por qué tanta preparación](#parte-0)
- [Parte 1 — El modelo mental del repo (lo que tienes que saber del producto)](#parte-1)
- [Parte 2 — La fase de análisis: el agente te entrevista y, a la vez, interroga al repo](#parte-2)
- [Parte 3 — Tu capa de valor: cómo codificar conocimiento de trading sin ambigüedad](#parte-3)
- [Parte 4 — La estructura del PRD ejecutable (el suite de documentos)](#parte-4)
- [Parte 5 — Especificar el FRONTEND a prueba de balas](#parte-5)
- [Parte 6 — Especificar el BACKEND a prueba de balas](#parte-6)
- [Parte 7 — Criterios de aceptación, Definition of Done y verificación](#parte-7)
- [Parte 8 — El handoff: del PRD al loop de ejecución](#parte-8)
- [Parte 9 — La checklist pre-vuelo ("la puerta de impecable")](#parte-9)
- [Parte 10 — Anti-patrones y modos de fallo](#parte-10)
- [Apéndices (copiar y pegar)](#apendices)
  - [A. Plantilla completa del suite de PRD](#apendice-a)
  - [B. Prompts listos para tu agente](#apendice-b)
  - [C. Recetas de extracción de catálogos](#apendice-c)
  - [D. Glosario maestro de dominio](#apendice-d)
  - [E. Tabla de comandos de verificación](#apendice-e)
  - [F. Mini-ejemplo end-to-end](#apendice-f)
  - [G. Plantilla del "brief de idea" (lo que prepara el PM)](#apendice-g)
  - [H. La entrevista: batería de preguntas del agente + prompt de arranque](#apendice-h)
  - [I. Tipos de feature y cómo cambia el PRD en cada uno](#apendice-i)
- [Los dos PRD de ejemplo (plantillas vivas)](#ejemplos)

---

<a id="parte-0"></a>
## Parte 0 — El contrato mental: por qué tanta preparación

### 0.1 La idea en una frase

> Un módulo se construye **a la primera** cuando el PRD no deja **ninguna decisión** abierta
> que la IA tenga que **adivinar**. Cada hueco que dejas es una alucinación que vas a tener
> que corregir después.

La IA es excelente ejecutando y pésima adivinando *tu* intención de trading. No sabe si un
gap se mide contra el *close* ajustado o sin ajustar, no sabe si tu stop es intradía o
overnight, no sabe qué pasa cuando el volumen pre-market es cero. **Tú sí.** El trabajo de
este manual es sacarte ese conocimiento de la cabeza y meterlo en el documento de forma que
la máquina no pueda interpretarlo de dos maneras.

### 0.2 El reparto de roles (quién aporta qué)

| Rol | Quién | Qué aporta |
|---|---|---|
| **Idea + dominio (oráculo)** | **Jaume (tú)** | El *qué*, el *para quién*, y **la capa de trading**: reglas, fórmulas, edge cases, nomenclatura correcta. Esta es la capa que **nadie más puede aportar**. |
| **Redactor del PRD** | **Tu agente** (Claude Code / Cursor) | **Redacta el PRD por ti.** Para hacerlo bien: te **entrevista solo sobre funcionalidad y trading** (nunca sobre técnica), **interroga al repo** (ancla en código) y escribe el suite de documentos. Tú no tecleas markdown: tú tienes las respuestas. |
| **Decisiones técnicas** | **Adrián (CTO) + Jesús** | Modelo de datos, contrato, persistencia, arquitectura, performance, reuso. **El agente NO se las pregunta al PM**: las resuelve anclando en el repo o las escala al CTO. |
| **Ejecución con IA** | **Jesús** | Coge el PRD y lo pasa a Claude Code (goal/loop). Trabaja en su rama; los merges los hace otra persona. |
| **Core / arquitectura** | **Adrián** | Dueño del motor (`backtester/engine.py`, etc.). Lo que toca su zona se consensúa. |

> **El cambio de mentalidad importante.** No "escribes" el PRD: **lo diriges**. Traes una idea
> y respondes preguntas; el agente lo convierte en un documento ejecutable. Tu trabajo no es
> redactar, es **tener decidido** todo lo de trading y producto antes de que la IA ejecute.

El cuello de botella de calidad **eres tú**: tus respuestas. Si están claras, el PRD sale
impecable y la ejecución es casi mecánica. Si dejas dudas, ni el mejor loop de IA las rellena
bien — por eso el agente **te entrevista antes de redactar** (Parte 2).

### 0.3 Las tres leyes de un PRD ejecutable

Estas tres reglas vienen del propio repo (`.agent/CODING_RULES.md` y el suite b2d-gateway).
Memorízalas; todo lo demás son detalles.

1. **El backend manda (la fuente de verdad es el código).** Si un documento y el código
   discrepan, **gana el código**. Por eso tu PRD no se escribe "de memoria": se escribe
   *después* de interrogar el repo, citando `fichero:línea`. Un PRD sin citas al código es
   un PRD de adivinanzas.

2. **Cero ambigüedad = cero alucinación.** Cada término tiene un nombre oficial (el del
   código). Cada número tiene unidad. Cada regla tiene su caso límite resuelto. Si una frase
   admite dos lecturas, **reescríbela** hasta que admita una.

3. **No reinventar lo que ya existe.** Antes de pedir un componente, un endpoint o un enum
   nuevo, comprueba que no exista ya. La IA tiende a crear duplicados; tu PRD debe decirle
   explícitamente "reusa `X` de `fichero Y`".

### 0.4 El ciclo de vida de un PRD (las 6 fases)

```
  (1) BRIEF            (2) ENTREVISTA          (3) ANCLAJE
  Tú escribes tu     →  El agente te        →  El agente interroga
  idea "lo mejor        pregunta hasta         el repo y extrae
  que puedas"           cero dudas (sobre      catálogos. Ancla
  (Apéndice G).         todo de trading).      cada cosa en código.
        │                                            │
        ▼                                            ▼
  (4) REDACCIÓN  ──────────────────────────►  (5) PRE-VUELO
  El agente escribe                            Pasas la checklist
  el suite de PRD                              de "impecable" (Parte 9).
  con tus respuestas                           Si falla, no se entrega.
  + las citas al código.                              │
                                                      ▼
                                              (6) HANDOFF
                                              Jesús lo da al loop.
                                              La IA construye a la primera.
```

Fíjate: las fases 2 y 3 las lleva **el agente** (te entrevista y mira el código); tú solo
aportas el **brief** (fase 1) y las **respuestas** (fase 2), y validas al final (fase 5). No te
saltes la fase 2: **redactar antes de resolver las dudas es la causa #1 de módulos que salen
mal.**

> **Límite de la fase 2 (clave):** el agente te pregunta **solo de funcionalidad y de
> especificaciones de trading**. **Nunca** te consulta decisiones técnicas (modelo de datos,
> contrato, persistencia, arquitectura, performance, reuso): esas son del **CTO (Adrián) y de
> Jesús**, y el agente las resuelve solo o las escala a ellos. Detalle completo en §2.3.

---

<a id="parte-1"></a>
## Parte 1 — El modelo mental del repo

No necesitas programar, pero sí necesitas saber **dónde vive cada cosa** para poder pedirle
a tu agente que la audite y para anclar tu PRD. Esta es la foto mínima.

### 1.1 Qué es el producto

Edgecute/BTT es una plataforma de **backtesting de short-selling intradía de small caps**.
El competidor de referencia es Flash Research. El flujo del producto tiene 4 pasos
(fuente: `.agent/BUSINESS_LOGIC.md`):

1. **Market Analysis / Screener** — filtra el mercado por gap, volumen, precio, métricas PM/RTH.
2. **Strategy Builder** — define condiciones de entrada/salida y gestión de riesgo.
3. **Backtester** — ejecuta la simulación histórica sobre el universo filtrado.
4. **Resultados** — métricas de performance (win rate, R-multiple, drawdown, Sharpe…).

Pero el producto es **más que el backtester**. Hoy ya conviven varias áreas, y mañana habrá
más. Tu feature puede caer en cualquiera de ellas — **esta guía sirve para todas**:

| Área | Qué es | Dónde (front / back) |
|---|---|---|
| **Screener / Market Analysis** | filtrado y movers del mercado | `Screener.tsx` / `routers/screener.py`, `market.py` |
| **Ticker Analysis** | perfil y stats de un ticker (incl. gap-stats) | `TickerAnalysis.tsx` / `routers/ticker_analysis.py` |
| **Strategy Builder** | DSL de estrategia | `strategy-builder/` / `schemas/strategy.py`, `routers/strategies.py` |
| **Backtester + Resultados** | simulación y métricas | `components/backtester/` / `routers/backtest.py`, `services/` |
| **Baúl / Database** | datasets y queries guardadas | `app/database/` / `routers/query.py`, `data.py` |
| **Developers / API** | portal de API keys, billing, playground | `app/developers/` / `routers/api_console.py`, `api_public/` |
| **Edgie (asistente)** | asistente voz+texto in-app | `lib/assistant/` / `routers/assistant.py`, `edgie.py` |
| **Áreas nuevas (greenfield)** | p. ej. un **Journal/Diario de trading** que aún no existe | *a crear* |

> **Una feature greenfield (área nueva) no cambia el método, cambia el peso de las secciones.**
> Si lo que pides **no existe todavía** (como un journal), el PRD tendrá más peso en *modelo de
> datos nuevo*, *persistencia* (tabla en `users.duckdb`, sync a GCS), *auth por usuario* y
> *navegación*, y menos en "reusar lógica existente". El [PRD de ejemplo del
> Journal](PRD_EJEMPLO_JOURNAL.md) muestra exactamente cómo se especifica un área nueva
> anclándola en los **patrones** que sí existen (aunque la feature no exista). El [Apéndice
> I](#apendice-i) resume cómo cambia el PRD según el tipo de feature.

Lo primero que hace el agente: **situar tu idea** en este mapa. Sitúala tú también en el brief.

### 1.2 El stack (para hablar el idioma correcto)

| Capa | Tecnología | Dónde |
|---|---|---|
| Frontend | **Next.js 16, React 19, Tailwind 4**, TypeScript | `frontend/` |
| Auth FE | Clerk (`@clerk/nextjs`) | `frontend/src/middleware.ts`, `.clerk/` |
| Charts | lightweight-charts, recharts | `frontend/src/components/**` |
| Backend | **FastAPI, Python 3.13**, Pydantic 2 | `backend/app/` |
| Motor | NumPy + **Numba JIT**, Pandas | `backend/app/backtester/`, `backend/app/services/` |
| Datos | Google Cloud Storage (Parquet) + **DuckDB** vía httpfs; `users.duckdb` (runtime) | `backend/app/database.py` |
| Deploy | FE en Vercel, BE en Hetzner | — |

> ⚠️ **Aviso de "drift".** El `README.md` de la raíz dice "Next.js 15 / Python 3.14". El
> código real (`.agent/ARCHITECTURE.md` + `package.json` + `requirements.txt`) dice Next 16 /
> Python 3.13. **Esto es justo el motivo de la Ley #1: el código manda, los docs envejecen.**
> Nunca cites el README como verdad; cita el código.

### 1.3 La arquitectura backend (la separación que NO se rompe)

```
backend/app/
├── routers/      ← SOLO endpoints (firma HTTP). CERO lógica de negocio.
├── services/     ← TODA la lógica de negocio y procesamiento.
├── backtester/   ← el motor (engine, portfolio, validator). ZONA SENSIBLE.
├── schemas/      ← modelos Pydantic (el "contrato" de datos).
├── api_public/   ← la capa API comercial (proyecto B2D), aislada del core.
└── database.py   ← conexión DuckDB/GCS.
```

Regla de oro del backend (de `.agent/CODING_RULES.md`): **routers finos, services gordos.**
Si tu PRD describe lógica nueva, esa lógica va en `services/`, no en `routers/`. Dilo
explícitamente.

### 1.4 El mapa de "dónde vive la verdad" (los catálogos)

Esta tabla es **oro puro**. Es el mapa que tu agente debe auditar para extraer los
catálogos. Cópiala en tu cabeza:

| Catálogo / contrato | Fichero | Qué contiene |
|---|---|---|
| **DSL de estrategia** (indicadores, comparadores, patrones, riesgo) | `backend/app/schemas/strategy.py` | `IndicatorType` (~117 valores), `Comparator`, `CandlePattern`, `Timeframe`, `RiskType`, `TakeProfitMode`, `UniverseFilters`, `StrategyCreate` |
| **Contrato de ejecución del backtest** | `backend/app/services/backtest_orchestrator.py` | `BacktestRequest` (los campos del "formulario": `init_cash`, `risk_r`, `fees`, `slippage`, `look_ahead_prevention`…) |
| **Forma del resultado** (métricas exactas) | `backend/app/services/backtest_service.py` | `_aggregate_metrics()`, `_enrich_trades()` → las claves literales del JSON de salida |
| **Endpoints existentes** | `backend/app/routers/*.py` | screener, backtest, strategies, market, optimization, ticker_analysis, assistant, api_console… |
| **Lógica del motor** (no tocar) | `backend/app/backtester/engine.py`, `services/indicators.py`, `services/portfolio_sim.py` | el bucle JIT, los indicadores, la simulación de cartera |
| **Fetch centralizado FE** | `frontend/src/lib/api.ts`, `api_backtester.ts`, `api_console.ts` | TODA llamada al backend pasa por aquí |
| **Registro de indicadores FE** | `frontend/src/lib/indicatorRegistry.ts`, `indicators.ts`, `indicatorValidation.ts` | catálogo de indicadores en el front |
| **Componentes reutilizables** | `frontend/src/components/**` (ver §5.4) | tablas, charts, paneles, tabs ya hechos |
| **Asistente in-app (Edgie)** | `frontend/src/lib/assistant/`, `docs/assistant/` | acciones/contexto que el bot puede ejecutar |
| **Design system** | `.agent/EDGECUTE_DESIGN_SYSTEM.md` | tokens, tipografía, botones, cards, reglas críticas |
| **Reglas de ingeniería** | `.agent/CODING_RULES.md` | qué se puede y qué no |
| **Semántica de dominio** | `docs/BACKTESTER_BRAIN.md`, `.agent/BUSINESS_LOGIC.md`, `indicadores.md` | el significado de las cosas |

### 1.5 La lista "NO TOCAR" (consensuar antes)

De `.agent/CODING_RULES.md`. Si tu feature necesita algo de aquí, el PRD debe decir **"esto
se expone con una capa nueva, no se edita"** y marcarlo como decisión a consensuar con Adrián:

- `backtester/engine.py` — lógica JIT delicada.
- `services/indicators.py`, `services/portfolio_sim.py` — núcleo de cálculo.
- Schema de `daily_metrics` e `intraday_1m` — romperlo invalida backtests históricos.
- Estructura de Parquet en GCS.

> Patrón correcto (del suite b2d-gateway): cuando se necesitó el motor desde la API nueva, no
> se editó el motor — se creó una **fachada** (`facade.py`) que lo expone. Tu PRD debe pensar
> igual: **capa nueva sobre lo intocable, nunca cirugía en el núcleo.**

### 1.6 Reglas de ingeniería que el PRD debe respetar (resumen)

- Antes de modificar un archivo, leerlo completo.
- No borrar código: mover a `_archive/`.
- No commitear `.env`, `gcs-key.json`, `*.duckdb`, `*.log`.
- Variables de entorno siempre vía `os.getenv()` (back) / `NEXT_PUBLIC_*` (front). Nunca hardcodear URLs ni secretos.
- Queries SQL **siempre parametrizadas** (`?`), nunca concatenación de strings.
- El motor: cambios en `backtester/` exigen verificar que Numba JIT sigue compilando.

---

<a id="parte-2"></a>
## Parte 2 — La fase de análisis: el agente te entrevista y, a la vez, interroga al repo

Esta es **la fase que te diferencia**, y funciona distinto de lo que crees: **el PRD no lo
escribes tú solo de memoria — lo redacta el agente contigo**. Tú traes la idea y el
conocimiento de trading; el agente, para producir un PRD que la IA ejecute a la primera, hace
dos cosas en paralelo:

- **Te entrevista a ti** (el PM) para resolver toda duda de producto y de trading. *(§2.2–2.4)*
- **Interroga al repo** para anclar cada decisión en el código real. *(§2.5–2.7)*

> **Regla de oro de esta fase:** el agente **no empieza a redactar el PRD con preguntas
> abiertas**. Primero pregunta, tú respondes, y solo cuando no queda ninguna incógnita que
> cambie el comportamiento, redacta. Un PRD escrito sobre supuestos es un PRD que falla.

### 2.1 El modelo de trabajo (quién hace qué en esta fase)

| Paso | Quién | Qué produce |
|---|---|---|
| 1. Brief de idea | **Tú (Jaume)** | Una nota de 1 página con tu idea, "lo mejor que puedas" (§2.2, [Apéndice G](#apendice-g)) |
| 2. Entrevista | **Agente → tú** | El agente lee el brief + este manual y te pregunta hasta cero dudas (§2.3–2.4) |
| 3. Anclaje | **Agente → repo** | El agente interroga el código y extrae catálogos (§2.5–2.7) |
| 4. Redacción | **Agente** | Redacta el suite de PRD con tus respuestas + las citas al código |
| 5. Validación | **Tú** | Revisas con la checklist pre-vuelo (Parte 9) |

Tú no tienes que escribir markdown: tienes que **tener las respuestas**. El agente convierte
tus respuestas en el documento.

### 2.2 Paso 1 — El "brief de idea" (lo que preparas tú)

Antes de la entrevista, escribe un **brief de idea** corto (media-una página). No tiene que
estar pulido; tiene que dar al agente algo a lo que reaccionar. Mínimo:

- **Una frase:** qué quieres y para quién.
- **El problema / insight de trading** que lo motiva (tu capa de valor).
- **Cómo lo imaginas** (2–4 frases o un boceto).
- **Lo que NO es** (para acotar desde el principio).

La plantilla completa del brief está en el [Apéndice G](#apendice-g). Le das **el brief + este
manual** a tu agente y arrancas la entrevista con el prompt del [Apéndice H](#apendice-h).

### 2.3 Paso 2 — El agente te entrevista (SOLO funcionalidad y trading)

> **El límite más importante de toda la fase.** El agente te pregunta **EXCLUSIVAMENTE** sobre
> **funcionalidad y especificaciones de trading**. **No** te consulta decisiones técnicas
> (modelo de datos, esquema, contrato de la API, persistencia, arquitectura, performance, qué
> componente se reutiliza, en qué fichero vive): esas son del **CTO (Adrián) y de Jesús**, y el
> agente las resuelve solo o las escala a ellos — **nunca a ti**. Si tu agente te pregunta algo
> técnico, va por mal camino: recuérdale este límite.

**Tres tipos de decisión, tres dueños distintos:**

| Tipo de decisión | Dueño | Qué hace el agente |
|---|---|---|
| **Funcionalidad + trading** — qué hace, para quién, reglas y fórmulas de dominio, qué ve/captura el usuario, alcance, privacidad *en términos de producto*, criterios de aceptación | **PM (Jaume)** | **Te entrevista** (esto es la entrevista) |
| **Técnica** — modelo de datos, esquema, contrato de la API, persistencia, arquitectura, performance, reuso de componentes, en qué fichero vive | **CTO (Adrián) + Jesús** | La **resuelve solo** anclando en el repo; si hace falta una decisión humana técnica, la **escala al CTO/Jesús**; los defaults reversibles los asume y los marca en el doc 07 §B |
| **Negocio** — monetización, tiers, precios, gating | **Jesús** | La **difiere** al doc 07 §A; **nunca la decide** |

Por eso la entrevista al PM recorre solo estos bloques (**todos de funcionalidad / trading**).
No te bombardea: pregunta por tandas, **propone una respuesta recomendada** y marca como
*asunción reversible* lo no bloqueante. (Batería completa en el [Apéndice H](#apendice-h)):

1. **Problema y usuarios** — ¿qué decisión o acción habilita? ¿quién y con qué frecuencia? ¿cómo se hace hoy?
2. **Alcance funcional (idea amplia → MVP vs Fase 2)** — primero el agente te deja contar la
   idea **en grande**; luego te ayuda a recortar al **MVP** (lo mínimo que ya sirve) y aparcar el
   resto en **Fase 2** (ver recuadro). ¿Qué tiene que poder hacer el usuario en el MVP y **qué NO**?
3. **Reglas de trading** *(el bloque largo: tu capa de valor)* — cada regla con sus 5 elementos
   (Parte 3): fórmula, unidad, sesión, anti-lookahead, edge cases. Nomenclatura de dominio.
4. **Qué información ve / captura el usuario** — qué datos le importan al trader y qué significa
   cada uno (en términos de negocio, **no** de tipos ni de tablas).
5. **Qué se muestra y cómo se comporta** — pantallas y flujos en términos de usuario; qué espera
   ver en vacío / error (desde el punto de vista del trader, no de la implementación).
6. **Privacidad en términos de producto** — ¿quién puede ver qué? (p. ej. "el diario de un
   trader es privado"). *El cómo se garantiza es técnico.*
7. **Aceptación** — 2–3 ejemplos concretos (entrada → resultado esperado) que, si funcionan, lo
   dan por bueno. *(Se convierten en los tests.)*

> **La idea amplia: separa MVP de Fase 2 (importante).** Es normal —y bueno— que traigas una
> idea **grande**. El agente NO la construye entera: la parte en tres cubos.
>
> | Cubo | Qué es | Para qué sirve |
> |---|---|---|
> | **MVP** | Lo mínimo que **ya aporta valor** y se construye **ahora** | Es lo que ejecuta la IA en este PRD |
> | **Fase 2** | Lo que viene **después** (NO se construye ahora) | **Solo se anota para que el MVP no le cierre la puerta.** No es permiso para hacer más |
> | **Fuera de alcance** | Lo que **no se hará** (descartado o de otro feature) | Acotar y evitar que la IA lo invente |
>
> **La regla de oro de la Fase 2:** *existe únicamente para tomar decisiones de diseño en el MVP
> que no la bloqueen* — no para ampliarlo. Ejemplo real: en el [Journal](PRD_EJEMPLO_JOURNAL.md),
> "importar trades del backtester" es **Fase 2**; por eso el MVP define el contrato con las
> **mismas claves de trade** (import-ready) aunque la importación **no se construya todavía**. Si
> una idea de Fase 2 no impone ninguna decisión en el MVP, basta con listarla; no la diseñes.

> **Lo que el agente NO te pregunta (lo resuelve él con el CTO/Jesús):** tipos de campo, esquema
> de base de datos, forma del JSON, dónde y cómo se persiste, paginación, caché, qué componente
> se reutiliza, en qué carpeta vive, si va síncrono o en background, qué librería se usa… Todo
> eso lo **deriva del código** (anclaje, §2.5) o lo decide como **default reversible** (doc 07
> §B). Si necesita una decisión técnica de peso, la marca para el **CTO**, no para ti.

> **Cuándo el agente debe PREGUNTARTE.** Solo cuando la respuesta (a) dependa de **conocimiento
> de trading**, (b) defina **qué hace el producto** o **qué ve el usuario**, o (c) sea de
> **privacidad / producto**. Si la duda es de *implementación*, **no es para ti**: la resuelve el
> agente o el CTO. Toda asunción (técnica reversible) va al doc 07 §B para que la veas de un vistazo.

### 2.4 Cómo converger (cerrar la entrevista)

- El agente agrupa las preguntas y te las da en **tandas cortas**, no de una en una.
- Para cada pregunta importante, te ofrece **opciones con una recomendación**, así respondes
  rápido ("la B", "sí", "no, mejor X").
- Repite hasta que **no quede ninguna incógnita bloqueante**. Lo no bloqueante queda como
  asunción reversible (doc 07).
- **Cierre:** el agente te devuelve una **minuta de decisiones** (qué quedó fijado y qué se
  asumió) para que la confirmes antes de redactar. Esa minuta es el germen del doc 02 y 07.

> Buen patrón: pídele a tu agente que **guarde la minuta** (preguntas + tus respuestas) dentro
> del propio PRD, como hizo el [PRD del Journal](PRD_EJEMPLO_JOURNAL.md) en su apéndice "Registro
> de la entrevista". Así queda la trazabilidad de por qué se decidió cada cosa.

### 2.5 El protocolo: cómo el agente interroga al repo (en orden)

El agente recorre estas preguntas **sobre el repo**, en este orden, al empezar cualquier
feature (en paralelo a la entrevista). Tú puedes pedírselas explícitamente; los prompts
exactos listos para copiar están en el [Apéndice B](#apendice-b). Aquí va la lógica:

1. **Orientación** — "Dame el mapa de este repo: stack, estructura de `backend/app` y
   `frontend/src`, y dónde vive la lógica de negocio vs los endpoints." *(Confirmas el modelo
   mental de la Parte 1.)*

2. **Ubicar el feature** — "Quiero construir **[descripción del feature]**. ¿Qué partes del
   código ya tocan esto? Lista ficheros front y back con una línea de qué hace cada uno."

3. **Extraer catálogos** — "Lístame los valores de `IndicatorType`, `Comparator`,
   `CandlePattern`, `RiskType`, `TakeProfitMode` de `schemas/strategy.py`, y los campos de
   `BacktestRequest`. Dame el valor literal de cada enum, no un resumen." *(Ver recetas exactas
   en el [Apéndice C](#apendice-c).)*

4. **Contrato de datos existente** — "Dame la forma exacta del request y del response del
   endpoint **[X]**: el modelo Pydantic de entrada y las claves del JSON de salida, con tipos."

5. **Reutilización front** — "¿Qué componentes de `frontend/src/components/` puedo reusar para
   **[pantalla]**? ¿Cómo se llama al backend (patrón de `lib/api.ts`)? ¿Qué tokens del design
   system aplican?"

6. **Restricciones** — "¿Qué de lo que necesito está en la lista 'no tocar' de
   `CODING_RULES.md`? ¿Qué tendría que exponerse con una capa nueva en vez de editarse?"

7. **Edge cases técnicos** — "¿Cómo maneja hoy el código **[caso límite]** (p. ej. volumen PM
   cero, ticker sin datos intradía, día sin gap)? Si no lo maneja, dímelo."

8. **Tests existentes** — "¿Qué tests hay en `backend/tests/` relacionados con esto? ¿Qué
   patrón siguen?" *(Te dice cómo debe pedir tests tu PRD.)*

### 2.6 Cómo exigir evidencia (y detectar alucinaciones)

Tu agente a veces inventará. Estas son tus defensas:

- **Exige cita siempre.** Añade a cada pregunta: *"Cita `fichero:línea` de cada afirmación. Si
  no lo encuentras en el código, di explícitamente 'no encontrado', no lo supongas."*
- **Pide el valor literal, no el resumen.** "Dame los valores exactos del enum" en vez de
  "dime qué indicadores hay". Un resumen se puede inventar; un literal copiado, no tanto.
- **Triangula lo crítico.** Para lo que de verdad importa (una fórmula, una clave de métrica),
  pídele que te pegue el **fragmento de código** y léelo tú. No hace falta que programes para
  ver si un `if` dice lo que crees.
- **Señal de alarma:** si el agente describe un campo "redondo" que encaja sospechosamente bien
  con lo que tú querías oír, sospecha. Pide la línea.

### 2.7 El "log de análisis" (lo que pega evidencia en tu PRD)

Mientras interroga, el agente va guardando un log con este formato. Va literalmente dentro del doc 00
del suite (trazabilidad), igual que hace el [`00_INDEX.md`](../b2d-gateway/00_INDEX.md):

```markdown
## Fuentes auditadas (verdad anclada en código)

| Pieza real | Fichero | Qué aporta al feature |
|---|---|---|
| Contrato de entrada | backend/app/services/backtest_orchestrator.py (BacktestRequest) | campos del formulario |
| DSL de estrategia | backend/app/schemas/strategy.py (IndicatorType…) | catálogo de indicadores |
| ...
```

Si una fila no la pudiste verificar, **no la pongas como verdad**: ponla en "preguntas
abiertas" (doc 07). Mejor un hueco declarado que una mentira anclada.

---

<a id="parte-3"></a>
## Parte 3 — Tu capa de valor: codificar conocimiento de trading sin ambigüedad

Aquí es donde **tú ganas o pierdes el PRD**. La IA sabe programar; no sabe operar. Todo lo que
no especifiques de trading, lo inventará — y lo inventará plausible pero mal. Esta parte es la
más importante del manual.

### 3.1 El principio: cada regla de trading necesita 5 cosas

Para cada regla de trading que entre en el PRD, da **las cinco**:

1. **Nombre oficial** — el del código (`gap_pct`, no "el porcentaje del hueco"). Si no existe
   aún, propones uno y lo marcas como nuevo.
2. **Definición operativa** — la fórmula o condición exacta, con qué columnas se calcula.
3. **Unidad y rango** — %, USD, R, shares, epoch segundos… y el rango válido.
4. **Sesión y timezone** — ¿PM, RTH, AM/post? ¿hora de ET? (ver glosario).
5. **Edge case resuelto** — qué pasa en el caso degenerado (división por cero, dato ausente,
   empate, etc.).

### 3.2 Ejemplo: bien vs mal especificado

**❌ Mal (ambiguo — la IA adivina):**

> "Que filtre por gap grande y entre en short cuando el precio rompa el mínimo del pre-market."

Problemas: ¿"gap grande" es cuánto? ¿gap contra qué precio? ¿"rompa" es toca o cierra por
debajo? ¿qué pre-market, el de ese día? ¿en qué timeframe se evalúa la rotura? ¿anti-lookahead?

**✅ Bien (inequívoco — la IA ejecuta):**

> **Filtro de universo:** `gap_pct >= 20`, donde `gap_pct = (open_RTH / prev_close - 1) * 100`
> usando `prev_close` ajustado por splits (fuente: `daily_metrics`, ver
> `cache_service.py`). Unidad: porcentaje. Solo días con `gap_pct` no nulo.
>
> **Entrada (short):** condición `CROSSES_BELOW` sobre el indicador `PM Low` evaluada en
> velas de `Timeframe.M1`. "Cruce por debajo" = la vela cierra `close < PML` habiendo cerrado
> la anterior `close >= PML` (no basta con que el `low` lo toque). `bias = short`.
>
> **Anti-lookahead:** `look_ahead_prevention = true` (la señal se desplaza 1 barra; la entrada
> ocurre en la apertura de la barra siguiente a la señal). Esto es **obligatorio**.
>
> **Edge case:** si no hay datos PM ese día (`PM Low` nulo), el día **no genera entrada** (se
> descarta, no se usa el RTH low como sustituto).

Nota cómo cada término es un valor real del catálogo (`CROSSES_BELOW` de `Comparator`,
`Timeframe.M1`, `bias=short` de `StrategyCreate`). Eso es anclar.

### 3.3 La regla sagrada: anti-lookahead

El backtester **no debe mirar al futuro** (`.agent/BUSINESS_LOGIC.md`). El mecanismo es
`look_ahead_prevention` → desplaza las señales 1 barra. **Toda** lógica de entrada/salida que
especifiques debe declarar explícitamente cómo respeta esto. Si una regla solo es calculable
con información que el trader no tendría en ese instante (p. ej. "vende en el HOD"), es
lookahead y hay que reformularla. Decláralo siempre; es el error de trading más caro y más
fácil de colar.

### 3.4 Nomenclatura: usa SIEMPRE los nombres del código

El doc 02 del suite b2d-gateway tiene el ejemplo perfecto de tabla de nomenclatura oficial
(cópiala como plantilla). Reglas:

- **Métricas de resultado:** las claves son **literales** de `_aggregate_metrics()`
  (`win_rate_pct`, `total_pnl_net`, `max_drawdown_pct`, `expectancy`, `payoff_ratio`,
  `r_squared`…). **No renombrar.** Si tu PRD dice "ratio de aciertos" en vez de
  `win_rate_pct`, la IA creará una clave nueva.
- **Estrategia:** `bias`, `entry_logic`/`exit_logic`, `indicator`, `comparator`,
  `candle pattern`, `risk_management`, `hard_stop`, `take_profit`, `trailing_stop`,
  `swing_option`.
- **Ejecución:** `init_cash`, `risk_r` (R), `risk_type`, `size_by_sl`, `fees`/`fee_type`
  (`PERCENT`|`FLAT`), `slippage`, `locates_cost`, `look_ahead_prevention`, `monthly_expenses`.
- **Universo y datos:** `dataset`/`dataset_id`, `UniverseSpec`/`UniverseFilters`,
  `qualifying data`, `gap_day`, `gap_1_day`/`gap_2_day`, `intraday 1m`, `market session`
  (`PM`/`RTH`/`AM`).

El [Apéndice D](#apendice-d) tiene el glosario maestro completo. Tu trabajo es **mapear tu
vocabulario de trader al vocabulario del código** y usar siempre el segundo en el PRD.

### 3.5 La checklist "preguntas de trader" (solo tú las respondes)

Antes de dar un feature por especificado, responde estas. Si alguna queda en blanco, la IA la
inventará:

- [ ] **Dirección:** ¿long, short o ambos? (`bias`)
- [ ] **Universo:** ¿qué pares ticker–día entran exactamente? (filtros, valores, unidades)
- [ ] **Sesión:** ¿PM, RTH o ambas? ¿horas exactas en ET?
- [ ] **Timeframe:** ¿en qué velas se evalúa cada condición? (`1m`, `5m`…)
- [ ] **Entrada:** ¿condición exacta? ¿"toca" vs "cierra"? ¿precio de fill (open de la barra siguiente)?
- [ ] **Salida:** ¿stop? ¿take profit (full/partial)? ¿trailing? ¿cierre forzado EOD? ¿overnight (swing)?
- [ ] **Sizing y riesgo:** ¿`risk_r`? ¿`size_by_sl`? ¿`risk_type` (FIXED/PERCENT/FIXED_RATIO)?
- [ ] **Costes:** ¿`fees`/`fee_type`? ¿`slippage`? ¿`locates_cost` para shorts?
- [ ] **Anti-lookahead:** ¿cómo se respeta? (siempre `look_ahead_prevention`)
- [ ] **Edge cases:** sin datos PM, ticker halteado, volumen cero, gap nulo, dato ausente, empate de señales.
- [ ] **Métricas a mostrar:** ¿qué claves exactas de resultado? ¿qué gráficas?

### 3.6 Da ejemplos numéricos cerrados

Nada blinda una especificación como un **ejemplo concreto con números**. Para tu regla clave,
da una fila de datos de entrada y el resultado esperado:

> Ejemplo: `prev_close=10.00`, `open_RTH=13.00` → `gap_pct = 30.0`. Entra en short cuando una
> vela 1m cierra a `9.80` tras una que cerró a `10.10`, siendo `PM Low = 10.00`. Con
> `risk_r=100`, `risk_type=FIXED`, stop a `10.50` (0.70 de riesgo/share) → size ≈ 142 shares.

Esos ejemplos se convierten directamente en **casos de test** que la IA escribe primero (TDD).
Un ejemplo numérico vale por diez párrafos de prosa.

---

<a id="parte-4"></a>
## Parte 4 — La estructura del PRD ejecutable (el suite de documentos)

No entregues "un documento". Entrega un **suite** de documentos numerados, como
[`docs/b2d-gateway/`](../b2d-gateway/00_INDEX.md). Cada uno tiene un trabajo. Para features
pequeñas puedes fusionar algunos (ver §4.9), pero la **estructura mental** es siempre esta.

> Crea una carpeta `docs/<nombre-feature>/` y dentro los ficheros `00..07`. El esqueleto
> completo listo para copiar está en el [Apéndice A](#apendice-a).

### 4.1 `00_INDEX.md` — Índice y trazabilidad

- Qué es el feature en 3 líneas y su estado (PLAN / EN CONSTRUCCIÓN).
- **La tabla de "fuentes auditadas"** (tu log de análisis de §2.4). Esto es lo que prueba que
  el PRD está anclado en el código y no inventado.
- Lista de los documentos y orden de lectura.
- Nomenclatura del feature (nombres provisionales si los hay).

**Rúbrica:** ¿alguien externo entiende en 2 minutos qué es y por dónde empezar? ¿La tabla de
fuentes cita ficheros reales?

### 4.2 `01_VIABILIDAD.md` — El reality check

El "¿esto se puede y a qué coste?". Cubre: tamaño de payload, latencia esperada, límites
técnicos (memoria, tiempo de cálculo del motor), aislamiento (si toca IP), y los **riesgos**.
Termina con un **veredicto**: viable / viable-con-condiciones / no-viable-aún.

**Rúbrica:** ¿identifica el mayor riesgo técnico y propone mitigación? ¿da un veredicto claro?

### 4.3 `02_PRD.md` — El qué y el para quién + nomenclatura

El corazón "producto". Secciones (ver el [02 del b2d-gateway](../b2d-gateway/02_PRD.md) como
plantilla):

1. **Visión en una frase** (la idea **amplia**, para dar contexto).
2. **Usuarios** (tabla perfil → necesidad → cómo lo sirve).
3. **Jobs-to-be-done** (qué hace el usuario, paso a paso).
4. **Alcance del MVP** (lo que SÍ se construye **ahora**, explícito).
5. **Fase 2** (lo que **NO** se construye ahora pero **sí se tiene en cuenta**: cada ítem dice
   **qué decisión impone al MVP** para no cerrarle la puerta. Si no impone ninguna, solo se lista).
6. **Fuera de alcance** (lo que **no se hará** / es de otro feature — **igual de explícito** para
   que la IA no lo invente).
7. **Glosario de dominio** (nomenclatura oficial anclada al código — tu Parte 3).
8. **Métricas de éxito** del feature.
9. **Principios de diseño** para el agente.

> **MVP vs Fase 2 vs Fuera de alcance** son tres cosas distintas: *construir ahora* / *después,
> pero condiciona el MVP* / *nunca o ya descartado*. La **Fase 2 existe solo para que el MVP no
> la bloquee**, no para ampliarlo (ver el recuadro de la Parte 2).

**Rúbrica:** ¿el "fuera de alcance" es tan detallado como el "dentro de alcance"? ¿cada ítem de
Fase 2 dice qué decisión impone (o no) al MVP? ¿el glosario
cita la fuente de cada término?

### 4.4 `03_CONTRATO_DATOS.md` — La frontera de comunicación

El JSON exacto de **entrada y salida**, derivado del backend real. Para cada endpoint o acción:

- **Request:** modelo Pydantic / forma JSON, con tipo, unidad y obligatoriedad de cada campo.
- **Response:** claves exactas (literales del código), tipos, ejemplos.
- **Errores:** catálogo cerrado de códigos de error (sin filtrar traces internos).
- **Ejemplos válidos** completos (un request real y su response real).

Si hay API, acompaña un **OpenAPI** (el suite b2d-gateway tiene
[`openapi.draft.yaml`](../b2d-gateway/openapi.draft.yaml)). Regla del repo: **el contrato se
deriva del código (Pydantic → OpenAPI), no se escribe a mano** para que no haya drift.

**Rúbrica:** ¿cada campo tiene tipo + unidad? ¿los ejemplos son copiables y válidos?

### 4.5 `04_*` — UI / Componentes (o MCP/Tools si aplica)

Depende del feature:

- **Si es UI:** mapa de pantallas, componentes a reusar, estados, interacciones (Parte 5).
- **Si es API/integración:** tools, resources, contratos de la integración (como el
  [04 del b2d-gateway](../b2d-gateway/04_MCP_TOOLS_RESOURCES.md)).

### 4.6 `05_ARQUITECTURA.md` — Cómo encaja en el sistema

- Dónde vive el código nuevo (qué carpetas, qué ficheros nuevos).
- Qué reusa y qué crea.
- Cómo respeta la lista "no tocar" (fachadas, capas nuevas).
- Flujo de datos end-to-end (FE → `lib/api.ts` → router → service → motor/DB → vuelta).
- Decisiones técnicas y sus alternativas descartadas.

**Rúbrica:** ¿un dev nuevo sabría exactamente qué ficheros se van a crear y cuáles no se tocan?

### 4.7 `06_PROMPT_MAESTRO_EJECUCION.md` — El guion para el loop

**El documento que Jesús le da a Claude Code.** Es el más operativo. Usa el
[06 del b2d-gateway](../b2d-gateway/06_PROMPT_MAESTRO_EJECUCION.md) como plantilla exacta.
Debe tener:

0. **Contexto que el agente DEBE leer antes de tocar nada** (lista de ficheros).
1. **Restricciones globales no negociables** (no tocar el motor, TDD, no filtrar errores,
   mover-no-borrar, etc.).
2. **Secuenciación atómica** en EPICs y tareas. **Cada tarea:** (a) escribe el test, (b)
   implementa, (c) corre el comando de verificación, (d) commit convencional. *No avanzar si
   el comando no pasa.*
3. **Definition of Done** por tarea y global (Parte 7).
4. **Comandos de verificación exactos** (Parte 7 / Apéndice E).
5. **Orden de PRs sugerido** (incremental, revisable).

**Rúbrica:** ¿cada tarea tiene su comando de verificación concreto? ¿un loop podría seguirlo
sin hacerte preguntas?

### 4.8 `07_DECISIONES_ABIERTAS.md` — Lo que falta firmar

Aquí van **(A)** las decisiones de producto que tú/Jesús debéis cerrar, y **(B)** los defaults
técnicos reversibles que la IA puede asumir.

> ⚠️ **Regla de negocio (importante en este repo):** las decisiones de **monetización (tiers,
> precios, qué se bloquea, a quién)** NO se deciden en el PRD. Se dejan explícitamente
> diferidas a Jesús. El PRD entrega el **mecanismo**, no la **política**. (Esto es exactamente
> lo que hace el suite b2d-gateway.) No marques nada como "firmado" sin el OK explícito de Jesús.

**Rúbrica:** ¿toda decisión abierta tiene un dueño y una recomendación? ¿ninguna decisión de
negocio se ha colado como "hecho técnico"?

### 4.9 Para features pequeñas: el suite condensado

No todo necesita 8 ficheros. Para algo pequeño (un filtro nuevo, una columna en una tabla),
condensa en **un solo `PRD.md`** con estas secciones mínimas obligatorias:

1. Qué y por qué (+ **alcance MVP / Fase 2 / fuera de alcance**).
2. Fuentes auditadas (anclaje en código).
3. Glosario/nomenclatura de lo nuevo.
4. Contrato de datos (request/response o estado de UI).
5. Reglas de trading con sus 5 elementos (§3.1) y ejemplos numéricos.
6. Plan de ejecución atómico + DoD + comandos de verificación.
7. Decisiones abiertas.

> Incluso condensado, separa **MVP** (ahora) de **Fase 2** (después, pero condiciona el MVP).
> Aunque sea una línea: "Fase 2: X — el MVP deja Y preparado para no bloquearla".

Si dudas si condensar o no: **¿toca el motor, los datos o el contrato de la API?** Si sí, suite
completo. Si es solo UI o un filtro aditivo, condensado.

---

<a id="parte-5"></a>
## Parte 5 — Especificar el FRONTEND a prueba de balas

La IA construye UIs muy bien **si le das el contrato visual y de comportamiento completo**.
Estas son las piezas que tu PRD debe incluir para cualquier pantalla.

### 5.1 El design system es ley (no se improvisa estilo)

Todo lo visual sale de `.agent/EDGECUTE_DESIGN_SYSTEM.md`. Tu PRD **no** describe colores a
ojo; **referencia los tokens**. Ejemplos de reglas críticas que debes citar cuando apliquen:

- Tema oscuro por defecto. Variables CSS: `--ec-bg-base #16181A`, `--ec-bg-surface #1C1E21`,
  `--ec-border #2C2F33`, `--ec-text-primary #D4D2CF`, `--ec-text-high #E4E2DF`.
- **Cobre `#D87A3D` SOLO para marca y eyebrow.** Nunca para texto de card destacada.
- **P&L:** `--ec-profit #4A9D7F`, `--ec-loss #C94D3F`.
- **Botón primary:** fondo cobre, texto `#1A0A00` (**NUNCA blanco**), General Sans 700 11px
  uppercase.
- Tipografía: títulos en **Fraunces**, cuerpo/UI en **General Sans** (cargada solo desde
  Fontshare). *Filter values* siempre General Sans 600, nunca Fraunces.

En el PRD, en vez de "un botón naranja", escribe: *"botón primary del design system (token
cobre, texto `#1A0A00`)"*. La IA ya sabe leer ese doc; tú solo le dices qué aplica.

### 5.2 Describir una pantalla: los 4 estados obligatorios

Para cada pantalla/componente nuevo, especifica **siempre** los cuatro estados (si los olvidas,
la IA solo hace el "feliz" y luego hay bugs):

1. **Loading** — qué se ve mientras carga (skeleton, spinner, texto).
2. **Empty** — qué se ve sin datos (mensaje, CTA).
3. **Error** — qué se ve si la llamada falla (mensaje accionable, reintento).
4. **Success** — el estado con datos (el que todos describen).

### 5.3 El contrato de comportamiento (no solo el aspecto)

Por cada elemento interactivo, declara:

- **Interacción:** qué pasa al hacer click / escribir / seleccionar.
- **Validación:** reglas de entrada (rango, formato, obligatoriedad) y mensajes de error.
- **Datos:** qué endpoint alimenta esto y con qué forma (enlaza al doc 03). Recuerda: **toda
  llamada va por `frontend/src/lib/api.ts`** (regla de `CODING_RULES.md`), nunca `fetch` suelto.
- **Estado:** qué se guarda, dónde (URL, estado local, contexto), si persiste.
- **Responsive:** comportamiento en pantallas estrechas si aplica.

### 5.4 Reutiliza componentes existentes (catálogo)

Antes de pedir un componente nuevo, mira si ya existe. Catálogo actual (fuente:
`frontend/src/components/`):

- **Backtester:** `MetricsCard`, `TradeTable`, `Chart`, `MaeScatterChart`, `RollingEVChart`,
  `RollingAvgRChart`, `ResultsTabs`, y tabs (`PerformanceTab`, `EquityCurveTab`, `TradesTab`,
  `ChartsTab`, `CalendarTab`, `OOSDegradationTab`, `OptimizationSurfaceTab`).
- **Strategy builder:** `InlineStrategyBuilder`, `InlineDatasetBuilder`, `IndicatorDropdown`,
  `FilterBuilder`, `RiskManagementPanel`, `PassCriteriaFilters`, `ConfigurationPanel`.
- **Screener / mercado:** `Screener`, `AdvancedFilterPanel`, `FilterPanel`, `DataGrid`,
  `MarketIntelligenceCharts`, `NewsFeed`, `TickerAnalysis`.
- **Shell:** `LayoutShell`, `Sidebar`, `Dashboard`, `ChatBot`/`ChatBotAgentic`.

En el PRD: *"reusar `MetricsCard` (`frontend/src/components/backtester/MetricsCard.tsx`) para
las KPIs; crear solo `XGrid` nuevo"*. Explícito sobre qué reusar y qué crear.

### 5.5 Si el componente debe ser "asistible" por Edgie

Si la pantalla debe poder controlarse por el asistente de voz/texto (Edgie), tu PRD debe pedir
que se registre la acción siguiendo `docs/assistant/guia_dev_componente_asistible.md`. Regla de
oro de esa guía: *"si un humano puede hacerlo con la UI, debe existir una acción registrada
equivalente — y ninguna acción puede hacer algo que la UI no permita."* Especifica: nombre de
la acción (`pagina.accion`), schema de parámetros, nivel de `confirm` (`auto`/`confirm`/`danger`),
y qué contexto publica.

### 5.6 Wireframe textual

No necesitas Figma. Un wireframe en texto/ASCII + lista de elementos numerados es suficiente y
**inequívoco**:

```
┌─ Resultados del backtest ──────────────────────────────┐
│ [1] Fila de KPIs: win_rate_pct · total_pnl_net · expectancy │
│ [2] Tabs: Performance | Equity | Trades | Charts        │
│ [3] Panel activo del tab seleccionado                   │
└────────────────────────────────────────────────────────┘
[1] = MetricsCard (reuso), 3 tarjetas, P&L con color profit/loss
[2] = ResultsTabs (reuso), tab por defecto: Performance
[3] = contenido del tab; datos del doc 03 §response
```

---

<a id="parte-6"></a>
## Parte 6 — Especificar el BACKEND a prueba de balas

### 6.1 Respeta la separación routers / services / schemas

- **Router** (`backend/app/routers/`): firma del endpoint y nada más. Método, ruta, modelo de
  request, modelo de response, códigos de estado. **Cero lógica.**
- **Service** (`backend/app/services/`): toda la lógica de negocio nueva.
- **Schema** (`backend/app/schemas/`): el modelo Pydantic del contrato.

Tu PRD debe decir explícitamente en qué capa va cada cosa. Ejemplo: *"endpoint en
`routers/screener.py`; lógica de filtrado nueva en `services/data_service.py`; modelo de
entrada `XFilter` en `schemas/strategy.py`."*

### 6.2 El contrato de cada endpoint

Por cada endpoint nuevo o modificado, especifica:

| Campo | Qué dar |
|---|---|
| **Método + ruta** | `POST /api/...` (mira el prefijo del router: muchos usan `/api`) |
| **Auth** | ¿requiere usuario (Clerk)? ¿API-key? |
| **Request** | modelo Pydantic con cada campo: tipo, unidad, default, obligatoriedad |
| **Response** | forma exacta del JSON, claves literales, tipos |
| **Errores** | códigos posibles y su significado (sin filtrar internals) |
| **Efectos** | ¿lee?, ¿escribe en `users.duckdb`?, ¿lanza tarea en background? |

### 6.3 Reglas de datos (innegociables)

- Queries **siempre parametrizadas** con `?`. Tu PRD nunca debe sugerir construir SQL por
  concatenación.
- **No modificar** el schema de `daily_metrics` / `intraday_1m` / Parquet en GCS sin marcar
  consenso con Adrián.
- `users.duckdb` es dato de runtime; las estrategias se persisten como JSON ahí.
- Datos intradía = velas de 1 minuto: `{time, open, high, low, close, volume, vwap}`.

### 6.4 Performance (el cliente lo nota)

La performance del backtester es prioridad del cliente (`.agent/BUSINESS_LOGIC.md`). Si tu
feature toca rutas calientes:

- El motor corre el bucle bar-by-bar con **Numba JIT** (`@njit`). Cambios en `backtester/`
  exigen verificar que sigue compilando.
- Universos grandes se procesan **por chunks mensuales** para no reventar memoria.
- El **hot storage en RAM**: el screener con `min_gap >= 20` se sirve desde RAM en <100ms
  (fuente: `.agent/ARCHITECTURE.md`, `cache_service.py`). Si tu feature necesita filtrado
  rápido, di si puede aprovechar el hot cache o si requiere scan de GCS (lento).
- El backtester corre como **BackgroundTask** de FastAPI con polling desde el front. Si tu
  endpoint es pesado, especifica si es síncrono (con cap) o background+polling.

### 6.5 Tests que el PRD debe exigir

Mira el patrón en `backend/tests/` y pide tests del mismo estilo. Como mínimo:

- **Test de contrato:** el request/response cumple el modelo Pydantic / OpenAPI.
- **Test de lógica:** tus ejemplos numéricos de §3.6 convertidos en asserts.
- **Test de edge cases:** los de tu checklist de §3.5.

---

<a id="parte-7"></a>
## Parte 7 — Criterios de aceptación, Definition of Done y verificación

Un PRD ejecutable no dice "que funcione"; dice **cómo se comprueba que funciona**, con comandos.

### 7.1 Criterios de aceptación en formato Given/When/Then

Escribe los criterios de forma que sean **comprobables**, no opiniones:

```
DADO  un universo con gap_pct >= 20 y datos PM presentes
CUANDO se ejecuta el backtest con la estrategia [X]
ENTONCES aggregate_metrics.total_trades > 0
   Y     cada trade tiene entry_time dentro de la sesión declarada
   Y     ningún trade usa información posterior a su entry (anti-lookahead)
```

Cada criterio debe poder responderse con sí/no mirando el resultado. Si no, reescríbelo.

### 7.2 Definition of Done (copia esta plantilla)

**Por tarea atómica:**

- [ ] Test escrito **antes** y ahora en verde.
- [ ] El comando de verificación de la tarea pasa.
- [ ] Sin regresiones (`pytest` y, si aplica, `npm test`/`npm run build` verdes).
- [ ] No se tocó el motor / lista "no tocar" (o se hizo vía capa nueva consensuada).
- [ ] Commit convencional (`feat(...)`, `fix(...)`, `test: ...`).

**Global (listo para entregar):**

- [ ] Todos los criterios de aceptación (§7.1) verdes.
- [ ] Contrato sin drift (lo documentado == lo que devuelve el código).
- [ ] Edge cases de §3.5 cubiertos por tests.
- [ ] El feature es demoable end-to-end siguiendo el quickstart del propio PRD.

### 7.3 Comandos de verificación exactos (del repo)

Tu PRD debe listar los comandos reales. Los base de este repo:

```bash
# Backend
cd backend && source .venv/bin/activate
pytest tests/ -q                         # toda la suite
pytest tests/test_<tu_feature>.py -q     # solo lo tuyo
uvicorn app.main:app --reload --port 8000   # arrancar API local

# Frontend
cd frontend
npm install
npm run dev          # arrancar (http://localhost:3000)
npm run build        # build de producción (falla = no entregable)
npm run lint         # eslint
```

Para cada tarea del doc 06, asocia el comando concreto que la valida. "Verificar" sin comando
no es verificar.

### 7.4 Pide TDD explícitamente

El estándar del repo (doc 06 b2d-gateway) es **test primero**. Tu prompt maestro debe decir:
*"para cada tarea: (a) escribe el test, (b) implementa hasta verde, (c) corre el comando, (d)
commit. No hay código de producción sin su test."* Tus ejemplos numéricos de §3.6 **son** esos
tests; por eso darlos cerrados es tan valioso.

---

<a id="parte-8"></a>
## Parte 8 — El handoff: del PRD al loop de ejecución

### 8.1 Qué recibe Jesús

Le entregas la carpeta `docs/<feature>/` completa. El documento operativo es el
`06_PROMPT_MAESTRO_EJECUCION.md`: es lo que se pega (o se referencia) en Claude Code en modo
*goal* o *loop*. El loop leerá primero el "contexto obligatorio" (sección 0 del doc 06), luego
ejecutará las tareas atómicas una a una verificando cada comando.

### 8.2 Por qué la secuenciación atómica importa

Un loop construye mejor en pasos pequeños y verificables que en un "constrúyelo todo". Por eso
el doc 06 parte el trabajo en EPICs → tareas, cada una con su test y su comando. Si una tarea
falla la verificación, el loop se detiene ahí en vez de acumular errores. Tu trabajo como PM no
es escribir el código de las tareas, sino **ordenarlas** de forma que cada una sea pequeña,
testeable y construya sobre la anterior.

### 8.3 Orden de PRs (incremental)

Recomienda un orden de PRs como el del b2d-gateway (andamiaje → contrato → lógica → UI →
calidad). Cada PR: verde en CI, sin tocar el core, con su slice de tests. Esto hace la revisión
humana posible entre pasos.

### 8.4 El flujo de ramas (importante en este equipo)

- Jesús trabaja **en su rama**; **los merges los hace otra persona**. El PRD/prompt maestro no
  debe pedirle a la IA que mergee a `main` ni que pushee sin avisar.
- No commitear secretos ni datos (`.env`, `gcs-key.json`, `*.duckdb`, `*.log`).

---

<a id="parte-9"></a>
## Parte 9 — La checklist pre-vuelo ("la puerta de impecable")

> **Si el PRD no pasa todas estas casillas, no se entrega.** Esta es la diferencia entre
> "preparación impecable" (sale a la primera) y "casi" (sale a la tercera).

**Anclaje (Ley #1):**
- [ ] Existe la tabla de "fuentes auditadas" y cada afirmación clave cita `fichero:línea`.
- [ ] Ninguna verdad del PRD se contradice con el código (lo verificaste con el agente).
- [ ] No se cita el README ni docs viejos como fuente de verdad.

**Nomenclatura (Ley #2):**
- [ ] Todos los términos usan el nombre del código (enums, claves de métricas, campos).
- [ ] Hay un glosario que mapea tu vocabulario de trader → nombres del código.
- [ ] Las claves de resultado son literales de `_aggregate_metrics()` (no renombradas).

**Trading (tu capa):**
- [ ] Cada regla de trading tiene sus 5 elementos (nombre, definición, unidad, sesión, edge case).
- [ ] El anti-lookahead está declarado explícitamente en toda entrada/salida.
- [ ] La checklist "preguntas de trader" (§3.5) está 100% respondida.
- [ ] Hay al menos un ejemplo numérico cerrado por regla clave.

**Alcance (Ley #3):**
- [ ] Están separados los tres cubos: **MVP** (ahora), **Fase 2** (después) y **Fuera de alcance** (no se hará).
- [ ] Cada ítem de **Fase 2** dice qué decisión impone (o no) al MVP para no bloquearla; no se construye nada de Fase 2 ahora.
- [ ] "Fuera de alcance" es tan explícito como "dentro de alcance".
- [ ] Se dice qué se reusa (componentes/endpoints/enums existentes) y qué se crea.
- [ ] Lo que toca la lista "no tocar" se resuelve con capa nueva, no cirugía.

**Entrevista y dueños de decisión:**
- [ ] La entrevista al PM fue **solo de funcionalidad y trading**; ninguna pregunta técnica se le hizo al PM.
- [ ] Las decisiones técnicas (modelo de datos, contrato, persistencia, arquitectura, reuso) las tomó el **agente** (ancladas) o se escalaron al **CTO** — están en doc 05 / doc 07 §B.
- [ ] La **minuta** de la entrevista (decisiones + asunciones) está guardada como apéndice del PRD.

**Contrato y front/back:**
- [ ] Request y response de cada endpoint con tipo + unidad por campo.
- [ ] Cada pantalla tiene sus 4 estados (loading/empty/error/success).
- [ ] Datos de UI enlazan al contrato (doc 03) y van por `lib/api.ts`.
- [ ] Estilo referencia tokens del design system, no colores a ojo.

**Ejecutabilidad:**
- [ ] Plan atómico en tareas, cada una con test + comando de verificación.
- [ ] DoD por tarea y global presentes.
- [ ] Comandos de verificación son reales y copiables.
- [ ] Decisiones de negocio (monetización) marcadas como diferidas a Jesús, no decididas.

---

<a id="parte-10"></a>
## Parte 10 — Anti-patrones y modos de fallo

| Anti-patrón | Por qué falla | Antídoto |
|---|---|---|
| Escribir el PRD de memoria | El código real difiere; la IA construye sobre supuestos falsos | Interroga el repo primero (Parte 2) |
| "Que filtre por gap grande" | "Grande" no es un número; la IA elige uno | Da el valor y la fórmula con unidad |
| Renombrar métricas a tu gusto | La IA crea claves nuevas; el front no las encuentra | Usa los literales de `_aggregate_metrics()` |
| Olvidar el anti-lookahead | Backtest optimista e inválido (el peor bug de trading) | Declara `look_ahead_prevention` en cada regla |
| Solo describir el "happy path" | Loading/empty/error quedan rotos | Los 4 estados obligatorios (§5.2) |
| Pedir componentes que ya existen | Duplicados, inconsistencia visual | Catálogo de reuso (§5.4) |
| Editar el motor "de pasada" | Rompe JIT / backtests históricos | Capa nueva / fachada (§1.5) |
| Decidir tiers/precios en el PRD | No es decisión técnica; es de Jesús | Diferir a doc 07, marcar abierto |
| Preguntar al PM cosas técnicas (esquema, contrato, persistencia) | No es su decisión; ralentiza y confunde | El agente las resuelve/escala al CTO; al PM solo func.+trading (§2.3) |
| Meter la Fase 2 dentro del MVP | Desborda el alcance, retrasa el "a la primera" | Fase 2 NO se construye; solo condiciona el diseño del MVP (Parte 2) |
| Tratar la Fase 2 como "descartado" | Se diseña un MVP que la bloquea | Anótala y di qué deja preparada el MVP (doc 02 §5) |
| "Que funcione bien" como criterio | No es comprobable | Given/When/Then + comando (Parte 7) |
| Un solo mega-párrafo de prosa | La IA pierde requisitos enterrados | Listas, tablas, ejemplos numéricos |
| Color "naranja", botón "bonito" | Ignora el design system | Referencia tokens (`--ec-copper`, etc.) |
| SQL por concatenación | Inseguro y contra las reglas | Queries parametrizadas con `?` |

---

<a id="apendices"></a>
# Apéndices (copiar y pegar)

<a id="apendice-a"></a>
## Apéndice A — Plantilla completa del suite de PRD

> Copia esto en `docs/<nombre-feature>/` como ficheros separados. Borra las anotaciones `>`.

### `00_INDEX.md`

```markdown
# <Feature> — Documento de pre-producción

> Qué es esto: <3 líneas>. Estado: PLAN.

## Fuentes auditadas (verdad anclada en código)
| Pieza real | Fichero | Qué aporta |
|---|---|---|
| <...> | <backend/app/...> | <...> |

## Documentos
| # | Doc | Propósito |
|---|---|---|
| 01 | 01_VIABILIDAD.md | reality check + veredicto |
| 02 | 02_PRD.md | qué/para quién + nomenclatura |
| 03 | 03_CONTRATO_DATOS.md | request/response |
| 04 | 04_UI_COMPONENTES.md | pantallas/componentes |
| 05 | 05_ARQUITECTURA.md | dónde vive el código |
| 06 | 06_PROMPT_MAESTRO_EJECUCION.md | guion del loop |
| 07 | 07_DECISIONES_ABIERTAS.md | lo que falta firmar |

## Orden de lectura: 01 → 07 → 02 → 03 → 04 → 05 → 06
```

### `01_VIABILIDAD.md`

```markdown
# 01 — Viabilidad
## 1. Restricciones técnicas (payload, latencia, memoria, motor)
## 2. Riesgos y mitigaciones
## 3. Aislamiento / cosas "no tocar" implicadas
## 4. Veredicto: viable / viable-con-condiciones / no-aún
```

### `02_PRD.md`

```markdown
# 02 — PRD
## 1. Visión en una frase (la idea amplia)
## 2. Usuarios (perfil → necesidad → cómo lo sirve)
## 3. Jobs-to-be-done
## 4. Alcance del MVP (lo que SÍ se construye ahora)
## 5. Fase 2 (NO se construye ahora; por cada ítem: qué decisión impone al MVP para no bloquearlo)
## 6. Fuera de alcance (lo que NO se hará — explícito)
## 7. Glosario de dominio (nomenclatura oficial, con fuente)
## 8. Métricas de éxito
## 9. Principios de diseño para el agente
```

### `03_CONTRATO_DATOS.md`

```markdown
# 03 — Contrato de datos
## Por cada endpoint/acción:
### Request (modelo Pydantic / JSON): campo · tipo · unidad · obligatorio · default
### Response (claves literales del código): clave · tipo · significado
### Errores: código · cuándo · mensaje (sin internals)
### Ejemplo válido: <request real> → <response real>
```

### `04_UI_COMPONENTES.md`

```markdown
# 04 — UI y componentes
## Mapa de pantallas (wireframe textual)
## Componentes a reusar (de frontend/src/components/...)
## Componentes nuevos (qué y por qué no se reusa)
## Por componente: 4 estados (loading/empty/error/success) + interacciones + validación
## Datos: qué endpoint del doc 03 lo alimenta (vía lib/api.ts)
## Estilo: tokens del design system que aplican
## (Si aplica) acción asistible para Edgie: nombre, schema, confirm
```

### `05_ARQUITECTURA.md`

```markdown
# 05 — Arquitectura
## Ficheros nuevos (front y back) y dónde
## Qué se reusa
## Lista "no tocar" implicada → cómo se evita (capa nueva/fachada)
## Flujo end-to-end (FE → lib/api.ts → router → service → DB/motor → vuelta)
## Decisiones técnicas y alternativas descartadas
```

### `06_PROMPT_MAESTRO_EJECUCION.md`

```markdown
# 06 — Prompt maestro de ejecución
## 0. Contexto que el agente DEBE leer antes de tocar nada (lista de ficheros)
## 1. Restricciones globales no negociables
## 2. Secuenciación atómica (EPICs → tareas)
   - Tarea Nn: (a) test, (b) implementación, (c) comando de verificación, (d) commit
## 3. Definition of Done (por tarea / global)
## 4. Comandos de verificación exactos
## 5. Orden de PRs sugerido
```

### `07_DECISIONES_ABIERTAS.md`

```markdown
# 07 — Decisiones abiertas
## A. Decisiones de PRODUCTO (dueño: Jesús) — incl. monetización (DIFERIDA, no decidir aquí)
## B. Defaults técnicos reversibles (los asume la IA; documentados para poder revertir)
```

<a id="apendice-b"></a>
## Apéndice B — Prompts listos para tu agente

> Pégalos en Claude Code / Cursor con el repo abierto. Sustituye `[FEATURE]`.

**B1 · Orientación**
```
Mapea este repo para mí: stack real (no el README), estructura de backend/app y
frontend/src, y dónde vive la lógica de negocio vs los endpoints. Cita fichero:línea.
Si algo del README contradice el código, dímelo: gana el código.
```

**B2 · Ubicar el feature**
```
Quiero construir: [FEATURE].
Lista TODOS los ficheros (front y back) que ya tocan algo relacionado, con una línea
de qué hace cada uno. Marca cuáles podría reusar. Cita fichero:línea. Si no encuentras
nada relacionado, dilo explícitamente; no inventes.
```

**B3 · Extraer catálogos (anclado)**
```
Del fichero backend/app/schemas/strategy.py, pégame los VALORES LITERALES (no un
resumen) de: IndicatorType, Comparator, CandlePattern, Timeframe, RiskType,
TakeProfitMode. Y los campos de UniverseFilters y StrategyCreate con su tipo.
Luego, de backend/app/services/backtest_orchestrator.py, los campos de BacktestRequest
con tipo y default. Cita la línea de cada bloque.
```

**B4 · Contrato de un endpoint**
```
Para el endpoint [RUTA] (router backend/app/routers/[X].py): dame el modelo Pydantic
de request y las claves EXACTAS del JSON de response con tipos, leyendo el service que
lo implementa. Cita fichero:línea. No supongas claves; léelas del código.
```

**B5 · Reutilización front**
```
Para construir [PANTALLA], ¿qué componentes de frontend/src/components/ puedo reusar?
¿Cómo se llama al backend (patrón de lib/api.ts)? ¿Qué tokens del design system
(.agent/EDGECUTE_DESIGN_SYSTEM.md) aplican? Cita fichero:línea.
```

**B6 · Restricciones / no tocar**
```
De lo que necesita [FEATURE], ¿qué cae en la lista "no tocar" de .agent/CODING_RULES.md?
¿Qué tendría que exponerse con una capa nueva (tipo fachada) en vez de editar el core?
```

**B7 · Edge cases**
```
¿Cómo maneja hoy el código estos casos para [FEATURE]: [lista de edge cases]?
Para cada uno, dime: lo maneja (cita línea) / no lo maneja / no aplica. No inventes
comportamiento; si no está en el código, di "no implementado".
```

**B8 · Auditoría final del PRD (antes de entregar)**
```
Lee mi PRD en docs/[feature]/ y contrástalo con el código real. Lista toda
discrepancia entre lo que afirma el PRD y lo que dice el código, citando fichero:línea.
Marca cualquier término que no exista en el código y cualquier clave de métrica
renombrada respecto a _aggregate_metrics().
```

<a id="apendice-c"></a>
## Apéndice C — Recetas de extracción de catálogos

> Para verificar tú mismo (o que las pegue el agente). Salida = verdad anclada.

```bash
# Enums del DSL de estrategia (valores literales)
grep -nE "^\s+[A-Z_]+ = " backend/app/schemas/strategy.py

# Todas las clases (enums y modelos Pydantic) del schema
grep -nE "^class .*(Enum|BaseModel)" backend/app/schemas/strategy.py

# Campos del contrato de ejecución del backtest
grep -nE "BacktestRequest|: float|: int|: str|: bool" backend/app/services/backtest_orchestrator.py

# Claves literales de las métricas de resultado
grep -nE "\"[a-z_]+\":" backend/app/services/backtest_service.py | grep -iE "pnl|rate|ratio|drawdown|return|sharpe|sortino|expectancy|trades"

# Prefijos/rutas de todos los routers
grep -rn "APIRouter(" backend/app/routers/*.py

# Catálogo de componentes front
ls -R frontend/src/components/

# Tokens del design system
sed -n '1,120p' .agent/EDGECUTE_DESIGN_SYSTEM.md
```

> Nota: estos catálogos **cambian con el código**. No los pegues "congelados" en el PRD como
> verdad eterna; extráelos en el momento del análisis y cita la fuente para que se puedan
> re-verificar.

<a id="apendice-d"></a>
## Apéndice D — Glosario maestro de dominio

> Fuente primaria: `.agent/BUSINESS_LOGIC.md`, `docs/BACKTESTER_BRAIN.md` y el código. Usa
> SIEMPRE estos nombres en el PRD.

**Trading básico**
- **Gap** — diferencia % entre el close del día previo y el open del día actual (`gap_pct`).
- **Small cap** — empresa de baja capitalización, alta volatilidad.
- **Short** — operación bajista (vender primero, comprar después).
- **PM (Pre-Market)** — sesión 04:00–09:30 ET. **RTH** — 09:30–16:00 ET. **AM/post** — 16:00–20:00.
- **PMH / PM Low** — máximo / mínimo del pre-market. **HOD/LOD** — High/Low of Day.
- **R-multiple** — unidad de riesgo; 1R = riesgo inicial del trade.
- **SL** stop loss · **TP** take profit · **EOD** cierre forzado al final de sesión.
- **VWAP** — precio medio ponderado por volumen. **EV** — valor esperado por operación.

**Universo y datos**
- `dataset`/`dataset_id` · `UniverseSpec`/`UniverseFilters` · `qualifying data` ·
  `gap_day` · `gap_1_day`/`gap_2_day` · `postgap precondition` · `intraday 1m`
  (`{time, open, high, low, close, volume, vwap}`) · `market session`.

**Estrategia (DSL — fuente `schemas/strategy.py`)**
- `bias` (`long`|`short`) · `entry_logic`/`exit_logic` · `indicator` (`IndicatorType`, ~117) ·
  `comparator` (`GREATER_THAN`, `LESS_THAN`, `CROSSES_ABOVE`, `CROSSES_BELOW`, `DISTANCE_*`…) ·
  `candle pattern` (`RED_VOLUME`, `GREEN_VOLUME`, `DOJI`, `HAMMER`, `SHOOTING_STAR`…) ·
  `Timeframe` (`1m`,`5m`,`15m`,`30m`,`1h`,`1d`) · `risk_management` · `hard_stop` ·
  `RiskType` (`Fixed Amount`, `Percentage`, `ATR Multiplier`, `Market Structure (HOD/LOD)`) ·
  `take_profit` / `TakeProfitMode` (`Full`|`Partial`) · `trailing_stop` · `swing_option`.

**Ejecución (fuente `backtest_orchestrator.py`)**
- `init_cash` · `risk_r` (R, USD por trade) · `risk_type` (`FIXED`|`PERCENT`|`FIXED_RATIO`) ·
  `size_by_sl` · `fees`/`fee_type` (`PERCENT`|`FLAT`) · `slippage` · `locates_cost` ·
  `look_ahead_prevention` · `monthly_expenses`.

**Resultados (claves literales de `_aggregate_metrics()` — NO renombrar)**
- `total_trades` · `win_rate_pct` · `total_pnl` / `total_pnl_net` · `total_return_pct` ·
  `avg_return_per_day_pct` · `avg_sharpe` · `sortino_ratio` · `calmar_ratio` ·
  `max_drawdown_pct` · `dd_return_ratio` · `avg_profit_factor` · `expectancy` ·
  `payoff_ratio` · `avg_win`/`avg_loss` · `max_consecutive_wins`/`..._losses` ·
  `avg_r_per_day`/`avg_r_ui` · `max_mae` · `total_expenses` · `r_squared`.
- **trade:** `ticker, date, entry_time, exit_time, entry_price, exit_price, pnl, fees,
  return_pct, direction, status, size, exit_reason, mae, mfe, r_multiple, entry_hour,
  entry_weekday, gap_pct, stop_loss`.
- **equity point:** `{time, value}` (epoch segundos, USD — formato lightweight-charts).

<a id="apendice-e"></a>
## Apéndice E — Tabla de comandos de verificación

| Qué | Comando |
|---|---|
| Suite de tests backend | `cd backend && source .venv/bin/activate && pytest tests/ -q` |
| Test de un feature | `cd backend && pytest tests/test_<feature>.py -q` |
| Arrancar API local | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Import sano de un módulo | `cd backend && python -c "import app.<modulo>"` |
| Instalar front | `cd frontend && npm install` |
| Arrancar front | `cd frontend && npm run dev` → http://localhost:3000 |
| Build de producción front | `cd frontend && npm run build` |
| Lint front | `cd frontend && npm run lint` |
| Extraer enums del DSL | `grep -nE "^\s+[A-Z_]+ = " backend/app/schemas/strategy.py` |

<a id="apendice-f"></a>
## Apéndice F — Mini-ejemplo end-to-end (PRD condensado)

> Feature pequeño, especificado entero con el formato condensado de §4.9. Sirve de molde.

```markdown
# PRD — Columna "Distancia a VWAP" en la tabla de resultados de trades

## 1. Qué y por qué
Añadir una columna que muestre, por trade, la distancia % del entry_price al VWAP en
el minuto de entrada. Ayuda a evaluar si las entradas extendidas sobre VWAP rinden mejor.
**Fuera de alcance:** no se recalcula el backtest; solo se deriva y se muestra. No se
toca el motor. No se añade filtro (solo columna).

## 2. Fuentes auditadas
| Pieza | Fichero | Aporta |
|---|---|---|
| Forma de un trade | services/backtest_service.py (_enrich_trades) | claves del trade |
| VWAP intradía | intraday 1m {..., vwap} (hot storage) | el valor de VWAP por minuto |
| Tabla de trades FE | components/backtester/TradeTable.tsx | dónde se pinta la columna |
| Llamada FE | lib/api_backtester.ts | de dónde vienen los trades |

## 3. Nomenclatura nueva
- `dist_vwap_pct` (float, %): (entry_price / vwap_at_entry - 1) * 100. Negativo = bajo VWAP.

## 4. Contrato de datos
- Response del trade: añadir clave `dist_vwap_pct: float | null` (null si no hay vwap ese
  minuto). El resto de claves del trade NO cambian.

## 5. Reglas de trading (5 elementos)
- Nombre: dist_vwap_pct. Definición: (entry_price/vwap_at_entry - 1)*100.
- Unidad: %. Rango: sin límite. Sesión: la del entry_time (PM o RTH). Timeframe: 1m.
- Edge case: si vwap_at_entry es null o 0 → dist_vwap_pct = null (no dividir por cero;
  la celda muestra "—").
- Ejemplo: entry_price=9.80, vwap=10.00 → dist_vwap_pct = -2.0 (entrada bajo VWAP).
- Anti-lookahead: usa el vwap del MISMO minuto de entrada (ya conocido al entrar); no mira futuro.

## 6. Ejecución atómica + DoD + verificación
- T1 (back): en _enrich_trades, derivar dist_vwap_pct por trade.
  Test primero: trade con entry 9.80 y vwap 10.00 → -2.0; vwap null → null.
  Verif: `cd backend && pytest tests/test_enrich_trades.py -q`. Commit: feat(backtest): dist_vwap_pct.
- T2 (front): TradeTable muestra columna "Dist. VWAP %" con color profit/loss y "—" si null.
  Reusa el patrón de columnas existentes; datos vía api_backtester.ts.
  Verif: `cd frontend && npm run build`. Commit: feat(ui): columna dist VWAP.
- DoD global: pytest verde, build verde, columna visible con dato real, null → "—".

## 7. Decisiones abiertas
- A (Jesús): ¿se quiere también como filtro de universo en el futuro? (diferido, no en este PRD)
- B (técnico, reversible): formato 1 decimal; alineación a la derecha.
```

<a id="apendice-g"></a>
## Apéndice G — Plantilla del "brief de idea" (lo que prepara el PM)

> Esto es lo único que escribe el PM antes de la entrevista. Media-una página. No tiene que
> estar pulido: tiene que dar al agente algo a lo que reaccionar. Copia, rellena, y entrégalo
> junto con este manual a tu agente con el prompt del [Apéndice H](#apendice-h).

```markdown
# Brief de idea — <nombre provisional del feature>

## 1. En una frase
<Qué quiero y para quién. Ej: "Un diario de trades para que el trader registre y
revise sus operaciones reales y aprenda de sus errores.">

## 2. Área del producto
<¿Screener / Strategy Builder / Backtester / Ticker Analysis / Baúl / Developers /
Edgie / ÁREA NUEVA? (ver Parte 1.1). Si es nueva, dilo: "es greenfield".>

## 3. El problema / insight de trading (mi capa de valor)
<Por qué importa, en lenguaje de trader. Qué decisión o hábito mejora. Esto es lo que
solo yo sé; cuanto más concreto, mejor saldrá la entrevista.>

## 4. La visión AMPLIA (sin filtros)
<Cómo lo imaginas en grande, todo lo que te gustaría que llegara a ser. No te cortes:
es bueno que pienses a lo grande. El agente te ayudará a recortar.>

## 5. Lo MÍNIMO que ya me sirve (mi intuición de MVP)
<Si solo pudiéramos hacer una cosa de la visión amplia, ¿cuál es el corazón que ya
aporta valor? El agente afinará contigo qué es MVP y qué es Fase 2.>

## 6. Lo que NO es (acotación inicial)
<Lo que quiero dejar fuera del todo. "No es un broker", "no ejecuta órdenes reales".>

## 7. Dudas que YA sé que tengo
<Cosas sobre las que yo mismo dudo y quiero decidir en la entrevista.>

## 8. Referencias (opcional)
<Capturas, links a competidores (Flash Research, TraderSync…), o un módulo del repo
que se parezca.>
```

> No tienes que separar tú MVP de Fase 2 en el brief — basta con dar la **visión amplia** (§4) y
> tu **intuición de lo mínimo** (§5). Esa separación la afináis en la entrevista; el agente se
> asegura de que el MVP no le cierre la puerta a la Fase 2.

<a id="apendice-h"></a>
## Apéndice H — La entrevista: prompt de arranque + batería de preguntas del agente

> Dos piezas: (H1) el prompt que pega el PM para arrancar; (H2) la batería de preguntas que el
> agente debe recorrer. El agente usa H2 como guion; el PM no necesita leerla, pero saber que
> existe ayuda a venir preparado.

### H1 · Prompt de arranque (lo pega el PM)

```
Vas a ayudarme a preparar un PRD EJECUTABLE para una funcionalidad nueva. Lee primero,
enteros, estos dos documentos:
1) docs/manual-prd/GUIA_PRD_EJECUTABLE.md  (el método: síguelo al pie de la letra)
2) Mi brief de idea (lo pego abajo / está en <ruta>)

REGLA INNEGOCIABLE: NO empieces a redactar el PRD todavía. Primero:
(a) ENTREVÍSTAME, pero SOLO sobre FUNCIONALIDAD y ESPECIFICACIONES DE TRADING
    (Apéndice H2 del manual). NO me preguntes decisiones técnicas (modelo de datos,
    contrato, persistencia, arquitectura, performance, qué se reutiliza, dónde vive el
    código): eso lo resuelves tú anclando en el repo, o lo escalas al CTO — nunca a mí.
    Pregúntame en tandas cortas y, en cada pregunta, PROPÓN una respuesta recomendada.
    Lo que sea un default técnico reversible, ASÚMELO y márcalo en el doc 07 §B (no me
    molestes con eso). Lo de negocio (precios/gating) NO lo decidas: difiérelo a Jesús.
(b) En paralelo, INTERROGA EL REPO para anclar todo en el código real; cita fichero:línea
    y, si algo no existe, dilo ("no encontrado"), no lo inventes.

Cuando tengas todo, DEVUÉLVEME UNA MINUTA: decisiones fijadas + asunciones reversibles,
para que la confirme. Solo DESPUÉS de que yo confirme, redacta el suite de PRD siguiendo
la estructura del manual (Parte 4) y guarda la minuta como apéndice del PRD.

Mi brief:
<pega aquí el brief del Apéndice G>
```

### H2 · Batería de preguntas (guion del agente)

> **Regla del agente:** estas preguntas son **solo de funcionalidad y trading**. El agente
> adapta el detalle al tipo de feature ([Apéndice I](#apendice-i)) y **descarta explícitamente**
> las que no apliquen. Lo técnico **no** se pregunta aquí: ver el bloque "NO preguntar al PM".

**Bloque 1 — Problema y usuarios** *(funcional)*
- ¿Qué decisión o acción concreta habilita esto que hoy no se puede hacer (o se hace mal)?
- ¿Quién lo usa y con qué frecuencia (cada operación, a diario, semanal)?
- ¿Cómo se hace hoy sin esta feature? ¿Qué duele de ese workaround?
- ¿Cómo sabremos que aporta valor (señal de éxito en una frase)?

**Bloque 2 — Alcance funcional** *(funcional)*
- ¿Cuál es el MVP mínimo que ya es útil? Si solo pudiéramos hacer una cosa, ¿cuál?
- ¿Qué dejamos **explícitamente fuera** de esta primera versión? (clave para no desbordar)
- ¿Hay algo que parezca parte de esto pero sea otro feature distinto?

**Bloque 3 — Reglas de trading (el bloque largo — tu capa)** *(trading)*
- Por cada regla/cálculo: ¿cuál es la **fórmula exacta**? ¿con qué dato se calcula?
- ¿**Unidad** y **rango** de cada número? (%, USD, R, shares…)
- ¿**Qué sesión** (PM 04:00–09:30 / RTH 09:30–16:00 / AM-post) y en qué timeframe?
- ¿**Anti-lookahead**: la regla usa solo información disponible en ese instante? Si presenta
  estadística histórica, ¿cómo evita "mirar al futuro"? *(Si no aplica, decláralo "N/A".)*
- ¿Qué pasa en los **edge cases**: dato ausente, volumen 0, gap nulo, división por cero,
  empates, ticker halteado, sin datos PM?
- ¿Qué nombres de dominio usas para esto? *(el agente los cruza con el código para no renombrar)*

**Bloque 4 — Qué información ve / captura el usuario** *(funcional, NO técnico)*
- ¿Qué datos le importan al trader en esta feature y qué significa cada uno (en lenguaje de
  negocio)? *(El agente decide tipos, esquema y dónde se guardan — eso no se pregunta.)*
- ¿De dónde viene esa información: la **calcula** el sistema, la **importa** de otra parte, o la
  **escribe el usuario** a mano?
- ¿El usuario puede **crear / editar / borrar**? *(comportamiento de producto, no el cómo)*

**Bloque 5 — Qué se muestra y cómo se comporta** *(funcional)*
- ¿Qué ve el usuario y qué puede hacer, paso a paso (en términos de trader)?
- ¿Qué espera ver cuando no hay datos o cuando algo falla? *(experiencia, no implementación)*

**Bloque 6 — Privacidad (en términos de producto)** *(funcional)*
- ¿Quién puede ver estos datos? ¿Son privados de cada usuario o compartidos?
- ¿Hay algo sensible que no deba mostrarse nunca? *(El cómo se garantiza es técnico.)*

**Bloque 7 — Aceptación** *(funcional / trading)*
- Dame 2–3 **ejemplos concretos** (entrada → salida esperada) que, si funcionan, lo dan por
  bueno. *(Se convierten en los tests.)*
- ¿Qué sería un fallo inaceptable (lo que NUNCA debe pasar)?

> **NO preguntar al PM (lo resuelve el agente con el CTO/Jesús).** El agente **no** plantea
> estas al PM; las deriva del repo o las marca para el CTO / como default reversible (doc 07 §B):
> tipos de campo y esquema de BD · forma del JSON / contrato de la API · dónde y cómo se
> persiste (tabla, store, sync) · paginación, caché, sync vs background · qué componente se
> reutiliza y en qué fichero vive · librerías · rendimiento e índices. **Y lo de negocio**
> (precios, tiers, gating) se **difiere a Jesús**, no se decide.

> **Cierre obligatorio:** el agente entrega la **minuta** (decisiones funcionales/trading
> fijadas + asunciones técnicas reversibles que ha tomado) y espera confirmación del PM **antes**
> de redactar. La minuta se guarda como apéndice del PRD (trazabilidad).

<a id="apendice-i"></a>
## Apéndice I — Tipos de feature y cómo cambia el PRD en cada uno

> El método es siempre el mismo; cambia **el peso** de cada sección. El agente identifica el
> tipo en la entrevista y ajusta dónde poner el esfuerzo.

| Tipo | Ejemplo | Dónde pesa más el PRD | Riesgo principal |
|---|---|---|---|
| **Greenfield (área nueva)** | **Journal/Diario** ([ejemplo](PRD_EJEMPLO_JOURNAL.md)) | Modelo de datos nuevo · persistencia (`users.duckdb` + sync GCS) · auth por usuario (`scope_clause`) · navegación · migración (`init_db.py`) | Inventar en vez de reusar patrones; olvidar el scoping por usuario |
| **Submódulo / extensión** | Gap Edge ([ejemplo](PRD_EJEMPLO_GAP_EDGE_EXPLORER.md)) | Reuso de definiciones y componentes existentes · contrato del endpoint nuevo | Duplicar lógica que ya existe |
| **Analítica / solo lectura** | un panel de stats | Reglas de trading + anti-lookahead · payload/latencia (hot cache) | Confundir base rate con señal tradeable |
| **Columna / cambio pequeño** | "Dist. a VWAP" ([Apéndice F](#apendice-f)) | Una regla + su edge case + un test | Sobre-especificar / tocar de más |
| **Transversal / no funcional** | rate limit, caché, perf | Restricciones globales · DoD con medición · no romper contratos | Regresiones silenciosas |
| **Integración externa** | SEC filings, news, KnowTheFloat | Contrato del tercero · errores/timeouts · sin secretos en repo | Acoplar el core a un servicio frágil |

Para **greenfield**, el peso extra es **técnico** (modelo de datos, persistencia, auth,
migración, navegación) y lo resuelve el **agente** anclando en los **patrones** que sí existen
aunque la feature no exista: persistencia y sync (`routers/strategies.py` +
`gcs_sync.upload_user_db`), auth (`app/auth`), creación de tablas (`init_db.py`), registro de
router (`main.py`), navegación (`Sidebar.tsx`). Al PM solo se le pregunta **qué información le
importa al trader y quién puede verla** (funcional), no cómo se modela ni dónde se guarda.

---

<a id="ejemplos"></a>
## Los dos PRD de ejemplo (plantillas vivas)

Tienes dos PRD completos hechos con este método. Léelos: valen más que mil explicaciones.

| Ejemplo | Tipo | Qué demuestra |
|---|---|---|
| [**PRD_EJEMPLO_JOURNAL.md**](PRD_EJEMPLO_JOURNAL.md) | Greenfield (área nueva) | Cómo especificar un módulo que **no existe** anclándolo en patrones reales: modelo de datos, persistencia por usuario, auth, migración, navegación — y la **minuta de la entrevista** agente↔PM incluida. |
| [**PRD_EJEMPLO_GAP_EDGE_EXPLORER.md**](PRD_EJEMPLO_GAP_EDGE_EXPLORER.md) | Submódulo / analítica | Cómo **reusar** definiciones y código existentes sin duplicar, y cómo tratar el anti-lookahead en estadística de mercado. |

Y para un caso grande con los 7 documentos en ficheros separados:
[`docs/b2d-gateway/`](../b2d-gateway/00_INDEX.md).

---

## Cierre

Si interiorizas una sola idea de este manual, que sea esta: **el PRD compite contra la
imaginación de la IA.** Todo lo que no cierres, ella lo abrirá — y lo abrirá según una intuición
de programador, no de trader. Por eso el flujo es: tú traes la idea, **el agente te entrevista**
hasta vaciarte las dudas, ancla todo en el código, y redacta. Tu ventaja es el dominio; la
herramienta del agente es el anclaje; el producto es un documento sin huecos. Con eso, el módulo
sale a la primera.

> **Referencia viva.** Tus plantillas de "cómo se ve impecable" son los dos PRD de ejemplo:
> [`PRD_EJEMPLO_JOURNAL.md`](PRD_EJEMPLO_JOURNAL.md) (área nueva, con la entrevista incluida) y
> [`PRD_EJEMPLO_GAP_EDGE_EXPLORER.md`](PRD_EJEMPLO_GAP_EDGE_EXPLORER.md) (submódulo que reusa
> código). Para un caso grande con documentos separados, mira
> [`docs/b2d-gateway/`](../b2d-gateway/00_INDEX.md). Cuando dudes del formato, ábrelos.
